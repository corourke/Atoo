"""`atoo patch --intent`: a model writes an INTENT, code compiles it.

The change-set contract (`patch.compile_change`) asks the model for the change
set in the plan's own JSON: the dozen nested fields of a channel, the sockets,
the indices. A weak or local model fails the schema or the physics. This is the
other contract. The model reads a request and a small, console-bounded
description of the desk and writes a short **intent** (`atoo/intent_schema.py`);
`atoo/intent_compile.py` turns it into the SAME change set, which
`patch.merge_change` and the rest of `atoo patch` then review exactly as they do
for any change. Both contracts stay until this one is at parity.

What the model is shown (`user_prompt`), in this order so a host that keeps the
prompt's prefix (Ollama, a hosted prompt cache) reads the rules once for every
request on a show:

1. the conventions and the show's instructions, and the domain knowledge;
2. **the desk slice** (`atoo/intent_desk.py`): every object's name and slot, what
   is free, and the details of what the request touches -- not the whole plan;
3. the request.

**One repair round.** If the reply is not a valid intent, or the compile refuses
something the MODEL made up (a socket nobody named, a channel that is not on the
desk, a made-up microphone), the model is asked once more, shown what was wrong
and a wider slice (the objects its own answer named). A refusal that is the
engineer's own instruction meeting a limit (a socket they typed that the stage
box does not have) is final: asking the model to "fix" it would be carrying the
instruction out somewhere else. A second failure is the error.

**A reply is capped.** A model that never stops writing is not waited for: the
reply is limited to `REPLY_TOKENS` where the provider can be limited, because a
local model once wrote 12,000 tokens for one request. A model that thinks first
(`OllamaProvider.thinks`) is not capped: its thinking counts as the reply, so a cap fair for
a model that answers at once would stop it before it answered.
"""

from __future__ import annotations

import json
import re

import dataclasses

from atoo import console_facts as facts
from atoo.ai_provider import AIProviderError
from atoo import generate, input_list, intent_desk, intent_schema, patch
from atoo.intent_compile import IntentRefused, compile_intent
from atoo.json_repair import extract_json_object, loads_with_repair
from atoo.schema_check import validate as validate_schema

#: The most an intent reply may run to, in tokens, on a provider that can be capped.
#: A 19-input Build is about 1,100 tokens compact and 2,600 with every key written.
REPLY_TOKENS = 4000


def bounds_text(console_model: str) -> str:
    """The limits of `console_model`, in words, from `console_facts`."""
    panel = facts.panel_for(console_model)
    cap = facts.CAPACITY
    ins = ", ".join(f"{g} 1-{facts.input_socket_limit(g, console_model)}"
                    for g in intent_schema.input_groups(console_model))
    outs = ", ".join(f"{g} 1-{facts.output_socket_limit(g, console_model)}"
                     for g in intent_schema.output_groups(console_model))
    return "\n".join([
        f"- Console: {panel['label']}.",
        f"- Channel strips ch 1-{cap['ch']}; aux strips 1-{cap['aux']}; buses 1-{cap['bus']}; "
        f"DCAs 1-{cap['dca']}; mute groups 1-{cap['mgrp']}; main outputs 1-{cap['main']}; "
        f"matrix outputs 1-{cap['mtx']}.",
        f"- Input socket groups: {ins}. `A`, `B`, `C` are AES50 ports; a stage box on one has "
        "fewer sockets than the port (the desk list shows what is free).",
        f"- Output socket groups: {outs}.",
        "- A stereo channel takes two consecutive sockets and the first must be odd "
        "(1+2, 15+16; never 2+3).",
        f"- Fader {facts.FADER_DB_RANGE[0]:g} to {facts.FADER_DB_RANGE[1]:g} dB; "
        f"high-pass {facts.HPF_HZ_RANGE[0]:g} to {facts.HPF_HZ_RANGE[1]:g} Hz; "
        f"gain {facts.HEAD_AMP_GAIN_DB_RANGE[0]:g} to {facts.HEAD_AMP_GAIN_DB_RANGE[1]:g} dB; "
        f"trim {facts.TRIM_DB_RANGE[0]:g} to {facts.TRIM_DB_RANGE[1]:g} dB; "
        f"a send level {facts.SEND_LEVEL_DB_RANGE[0]:g} to {facts.SEND_LEVEL_DB_RANGE[1]:g} dB.",
        f"- A name longer than {facts.NAME_MAX_CHARS} characters is cut by code: write it as the "
        "engineer said it.",
    ])


def system_prompt(console_model: str, *, build: bool = False) -> str:
    text = generate.load_prompt("intent.md", label=facts.panel_for(console_model)["label"],
                                bounds=bounds_text(console_model),
                                menu=intent_schema.menu_text())
    return text + "\n" + generate.load_prompt("intent_build.md") if build else text


def user_prompt(request: str, graph: dict, *, conventions: str | None, conventions_name: str | None,
                instructions: str | None, instructions_name: str | None,
                wide_for: dict | None = None, members: bool = False,
                presets: list[str] | None = None, input_csv: str | None = None,
                input_name: str | None = None) -> tuple[str, dict]:
    """`(the user message, {"hints", "slice"})`. `wide_for`: an intent, whose own
    names widen the slice (the repair round)."""
    hints = intent_desk.hints_from_request(request, graph)
    if wide_for is not None:
        extra = intent_desk.hints_from_intent(wide_for, graph)
        hints = {**hints, "names": hints["names"] + extra["names"],
                 "numbered": hints["numbered"] + extra["numbered"],
                 "sockets": hints["sockets"] + extra["sockets"], "ops": hints["ops"] | extra["ops"]}
    sl = intent_desk.slice_for(hints, graph, members=members)
    parts: list[str] = []
    if conventions or instructions:
        parts += [generate._conventions_section(
            conventions or "", conventions_name or "<conventions>", instructions,
            instructions_name or "<instructions>"), ""]
    parts += ["# Domain knowledge", "", generate._domain_knowledge(), ""]
    if input_csv:
        parts += [f"# The input list ({input_name or 'input list'})", "", "```csv", input_csv.strip(), "```", ""]
    if presets:
        parts += ["# Presets in the library", "", ", ".join(sorted(presets)), ""]
    parts += ["# The desk", "", "```json", intent_desk.slice_json(sl), "```", "",
              "# The request", "", request.strip(), "",
              "Reply with the intent JSON and nothing else."]
    return "\n".join(parts), {"hints": hints, "slice": sl}


def _lists_from_strings(value, said: list[str]) -> None:
    """A group list written as one name ("dca": "Drums" for ["Drums"]) read as a list of that
    name, in a Category-table entry and on an `add_channel`, said in `said`. What the model meant
    is plain, and a host that sends no schema (Claude) has nothing else to catch it."""
    if not isinstance(value, dict):
        return
    holders = [("category", e) for e in value.get("categories") or [] if isinstance(e, dict)]
    holders += [("add_channel", op) for op in value.get("ops") or []
                if isinstance(op, dict) and op.get("op") == "add_channel"]
    for what, holder in holders:
        for key in ("dca", "mute_group"):
            if isinstance(holder.get(key), str):
                holder[key] = [holder[key]]
                said.append(f"{what} {holder.get('name')!r}: `{key}` was one name, not a list; read as "
                            f"[{holder[key][0]!r}]")


def complete_part(raw: str) -> dict | None:
    """What a reply that was cut off mid-way finished writing: every top-level key whose value is
    complete, and of a list cut off inside (the `ops`), every element that is complete. None when
    nothing is. The element being written when the reply stopped is not guessed at."""
    import json as _json

    start = raw.find("{")
    if start < 0:
        return None
    decoder = _json.JSONDecoder()
    out: dict = {}

    def skip(i):
        while i < len(raw) and raw[i] in " \t\r\n,":
            i += 1
        return i

    i = start + 1
    while True:
        i = skip(i)
        if i >= len(raw) or raw[i] == "}":
            break
        try:
            key, i = decoder.raw_decode(raw, i)
        except ValueError:
            break
        i = skip(i)
        if i >= len(raw) or raw[i] != ":":
            break
        i = skip(i + 1)
        try:
            out[key], i = decoder.raw_decode(raw, i)
            continue
        except ValueError:
            pass
        if i < len(raw) and raw[i] == "[":
            items, j = [], i + 1
            while True:
                j = skip(j)
                try:
                    item, j = decoder.raw_decode(raw, j)
                except ValueError:
                    break
                items.append(item)
            out[key] = items
        break
    return out or None


#: A socket group written as the engineer writes it, not as the desk names it: "AES50-A" is the
#: group A, "Local" is LCL. Read so, at INFO, where a host sent no schema to stop it.
_GROUP_SPELLINGS = [(re.compile(r"^aes\s*50[\s_-]*([abc])$", re.IGNORECASE), lambda m: m.group(1).upper()),
                    (re.compile(r"^local$", re.IGNORECASE), lambda m: "LCL")]


def _groups_as_the_desk_names_them(value, said: list[str]) -> None:
    for op in (value.get("ops") or []) if isinstance(value, dict) else []:
        if not isinstance(op, dict):
            continue
        for spec in (op.get("patch"), (op.get("to") or {}).get("output") if isinstance(op.get("to"), dict) else None):
            if isinstance(spec, dict) and isinstance(spec.get("group"), str):
                for pattern, fix in _GROUP_SPELLINGS:
                    m = pattern.match(spec["group"].strip())
                    if m:
                        said.append(f"{op.get('op')} {op.get('name')!r}: the group {spec['group']!r} is the "
                                    f"desk's {fix(m)}")
                        spec["group"] = fix(m)
                        break


def parse_intent(raw: str, schema: dict, said: list[str] | None = None,
                 drop_bad_ops: bool = False) -> tuple[dict | None, str | None]:
    """`(intent, None)` or `(None, why)`: the reply as JSON, held to the schema. What was read
    leniently on the way (`_lists_from_strings`) is appended to `said`. `drop_bad_ops` (a build's
    last reply): an op that is not well formed is left out, named in `said`, and the rest is the
    intent, so one malformed op costs that op, not the show; a problem outside the ops still
    makes the reply unusable."""
    try:
        value = extract_json_object(raw)
    except Exception:  # noqa: BLE001
        try:
            value, _repairs = loads_with_repair(raw, expect_keys=frozenset(schema["properties"]))
        except Exception as exc:  # noqa: BLE001
            return None, f"not JSON: {exc}"
    _lists_from_strings(value, said if said is not None else [])
    _groups_as_the_desk_names_them(value, said if said is not None else [])
    problems = intent_schema.explain(value, intent_schema.without_bounds(schema), validate_schema)
    if problems and drop_bad_ops and isinstance(value, dict) and isinstance(value.get("ops"), list):
        bad = {int(m.group(1)) for p in problems for m in [re.match(r"ops\[(\d+)\]", p)] if m}
        if bad and all(re.match(r"ops\[\d+\]", p) for p in problems):
            for p in problems:
                (said if said is not None else []).append(f"not built: the reply's {p} (the op was malformed)")
            value = {**value, "ops": [op for k, op in enumerate(value["ops"]) if k not in bad]}
            problems = intent_schema.explain(value, intent_schema.without_bounds(schema), validate_schema)
    if problems:
        return None, "; ".join(problems[:4])
    return value, None


#: A whole show's reply grows with its input list (a verbose model writes every row): the cap for a
#: build is REPLY_TOKENS plus this much a row, up to BUILD_REPLY_TOKENS_MAX. A cap of 4000 cut off
#: a full-size show's reply at about 17,600 characters.
BUILD_TOKENS_PER_ROW = 120
BUILD_REPLY_TOKENS_MAX = 16000


def build_reply_tokens(rows: int) -> int:
    """The reply cap for a build of `rows` input-list rows."""
    return min(BUILD_REPLY_TOKENS_MAX, REPLY_TOKENS + BUILD_TOKENS_PER_ROW * max(rows, 0))


def _capped(provider, tokens: int = REPLY_TOKENS):
    """`provider` with its reply limited to `tokens`, where it has a limit to set and none set.
    A fresh copy: the caller's provider is not changed."""
    thinks = getattr(provider, "thinks", None)
    thinking = thinks is not None and thinks()
    if dataclasses.is_dataclass(provider) and hasattr(provider, "reply_tokens") \
            and getattr(provider, "reply_tokens") is None:
        # The context is sized for an intent's reply, not a whole plan's (a thinking model's
        # thinking is part of its reply, so it gets more room).
        provider = dataclasses.replace(provider, reply_tokens=tokens * (4 if thinking else 1))
    if thinking:
        return provider      # a thinking model is not cut off: its thinking is part of the reply
    for field in ("num_predict", "max_tokens"):
        if dataclasses.is_dataclass(provider) and hasattr(provider, field) \
                and getattr(provider, field) in (None, -1):
            return dataclasses.replace(provider, **{field: tokens})
    return provider


def _again(user: str, reply: str, problem: str) -> str:
    return (f"{user}\n\n---\n\nYour previous reply:\n\n{reply}\n\nIt was not accepted: {problem}\n\n"
            "Change what that names and nothing else. Reply again with the corrected intent JSON and "
            "nothing else.")


#: What a section-scoped repair may add: the sections the completeness check asks for, and a strip
#: it asks for by name. It never edits, renames, drops or re-categorises what the first reply wrote.
_REPAIR_ADDS = ("add_bus", "add_group", "add_output", "add_channel")


def _joined(first: dict, more: dict) -> dict:
    """`first` with what `more` adds: its new buses, groups and outputs (`_REPAIR_ADDS`), its
    notes, and its Category table where the first's was empty. Any other op, and any it repeats from the first (a model asked for the missing part
    often writes some of the rest again), is dropped, so the repair only adds."""
    def key(op):
        return (op.get("op"), op.get("object"), str(op.get("name") or "").casefold())
    have = {key(op) for op in first.get("ops") or []}
    first_notes = list(first.get("notes") or [])
    if not first.get("categories") and more.get("categories"):
        # The Category table the first reply left empty (`intent_build.categories_left_out`).
        first = {**first, "categories": more["categories"]}
    return {**first,
            "ops": [*(first.get("ops") or []), *(op for op in more.get("ops") or []
                                                  if op.get("op") in _REPAIR_ADDS and key(op) not in have)],
            "notes": [*first_notes, *(n for n in more.get("notes") or [] if n not in first_notes)]}


def _missing_only(user: str, reply: str, missing: str) -> str:
    """The section-scoped repair: ask for what the first reply left out, and only that. The
    reply is added to the first; nothing in the first is written again."""
    return (f"{user}\n\n---\n\nYour previous reply:\n\n{reply}\n\nIt was accepted, but {missing}.\n\n"
            "Reply with an intent whose `ops` are ONLY the ops for what is missing (and `notes` for "
            "anything you leave out on purpose); they are added to your previous reply. Do not repeat "
            "anything from it. Reply with the intent JSON and nothing else.")


#: How many times a build drops what was refused and compiles the rest: a drop can leave another
#: op naming what was dropped (a member channel), which the next round drops in turn.
SALVAGE_ROUNDS = 4


_MISSING_MEMBER_RE = re.compile(r"its member (['\"])(?P<name>.+?)\1 is not a channel of the desk")


def _only_missing_members(op: dict, reasons: list[str]) -> set[str]:
    """The members `op` (a group or bus with named channel members) was refused for, when they are
    its only reasons; else an empty set."""
    if not reasons or not isinstance((op.get("members") or {}).get("channels"), list):
        return set()
    names = [m.group("name") for r in reasons for m in [_MISSING_MEMBER_RE.search(r)] if m]
    return {n.casefold() for n in names} if len(names) == len(reasons) else set()


def salvaged(compile_prepared, intent_: dict, refused: IntentRefused, row_names=()) -> tuple:
    """A BUILD's answer to a refusal that survived the repair round: one bad op costs that object,
    never the show. `(change_set, made, notes)` for `intent_` (already prepared: code's rows in it)
    with every refused op left out and the rest compiled by `compile_prepared`. A refused op that
    writes an input-list row (a pair, a name, a preset) falls back to the plain row as the list
    states it, so the input is still built. Each is said in `notes` ("not built as the reply wrote
    it"), naming the reason. Raises the refusal when it is of the intent as a whole, or when
    nothing is left that compiles."""
    rows = {str(n).casefold(): n for n in row_names}
    notes: list[str] = []
    for _ in range(SALVAGE_ROUNDS):
        if not refused.ops:
            raise refused
        kept = []
        for k, op in enumerate(intent_.get("ops") or [], start=1):
            if k not in refused.ops:
                kept.append(op)
                continue
            why = next((r for r in refused.reasons if r.startswith(f"op {k} (")), f"op {k} ({op.get('op')})")
            missing = _only_missing_members(op, [r for r in refused.reasons if r.startswith(f"op {k} (")])
            if missing:
                # A group or bus refused only for members that are not channels (one the build
                # could not make): it does not depend on them, so it stands without them.
                left = [n for n in op["members"]["channels"] if str(n).casefold() not in missing]
                kept.append({**op, "members": {**op["members"], "channels": left}})
                notes.append(f"{op.get('object') or 'bus'} {op.get('name')!r} is built without "
                             f"{', '.join(repr(n) for n in op['members']['channels'] if str(n).casefold() in missing)}, "
                             "which is not a channel of the show")
                continue
            own = [rows[str(n).casefold()] for n in (op.get("rows") or [op.get("name")])
                   if op.get("op") == "add_channel" and str(n).casefold() in rows]
            plain = [{"op": "add_channel", "name": n} for n in own]
            if plain and plain != [op]:
                kept.extend(plain)
                notes.append(f"not built as the reply wrote it, so built from the input list as it "
                             f"stands: {why}")
            else:
                notes.append(f"not built: {why}")
        intent_ = {**intent_, "ops": kept}
        try:
            change_set, made = compile_prepared(intent_)
            return change_set, made, notes, intent_
        except IntentRefused as again:
            refused = again
    raise refused


def compile_change(request: str, base: dict, *, provider, console_model: str,
                   conventions: str | None = None, conventions_name: str | None = None,
                   instructions: str | None = None, instructions_name: str | None = None,
                   input_list_text: str | None = None, aes50_devices: dict | None = None,
                   category_table=None, known_presets=None, infos: list[str] | None = None,
                   members: bool = False, trace: dict | None = None,
                   input_csv: str | None = None, input_name: str | None = None,
                   prepare=None, complete=None, reserved_user_slots=()) -> dict:
    """The typed change -> a change set, by a model's intent. Anything decided on the
    way is appended to `infos`. `complete(intent)`, if given, names what the intent leaves out
    that the request's own texts ask for ("" when nothing): a first reply that compiles but
    leaves something out goes to the repair round once, naming it; the repaired reply is kept
    only if it compiles, and what it still leaves out is said at INFO. Raises `IntentRefused` for a change that cannot be made
    (the compile's own reasons, each saying which limit), `patch.ChangeError` when the
    model could not give a usable intent in two tries. `trace`, if given, is filled in
    for an eval: `replies`, `intent`, `first_try_valid`, `repaired`, `prompt_chars`."""
    infos = infos if infos is not None else []
    trace = trace if trace is not None else {}
    trace.update(replies=[], intent=None, first_try_valid=False, repaired=False)
    build = input_csv is not None
    schema = intent_schema.intent_schema(console_model, build=build)
    # What the host decodes against has no numeric bounds: a grammar that stops at the console's
    # range makes it impossible to write what the engineer asked for ("bus 40" came out as bus 4),
    # and then there is nothing for the compile to refuse. The bounds are checked, and named,
    # by `compile_intent`.
    wire = intent_schema.wire_schema(schema) if build else intent_schema.without_bounds(schema)
    graph = intent_desk.index_desk(base, aes50_devices=aes50_devices, console_model=console_model)
    system = system_prompt(console_model, build=input_csv is not None)
    names = dict(conventions=conventions, conventions_name=conventions_name,
                 instructions=instructions, instructions_name=instructions_name,
                 presets=list(known_presets) if known_presets else None,
                 input_csv=input_csv, input_name=input_name)
    user, _ = user_prompt(request, graph, members=members, **names)
    capped = _capped(provider, build_reply_tokens(len(input_list.parse_input_list(input_csv)))
                     if build else REPLY_TOKENS)
    conventions_text = "\n".join(t for t in (conventions, instructions) if t)

    def compile_prepared(intent):
        return compile_intent(
            intent, base, console_model, text=request, category_table=category_table,
            aes50_devices=aes50_devices, input_list_text=input_list_text,
            known_presets=known_presets, conventions_text=conventions_text, build=build,
            reserved_user_slots=reserved_user_slots)

    def compile_(intent):
        if prepare is not None:
            intent = prepare(intent)      # e.g. a build: code adds the rows the model did not
        return compile_prepared(intent)

    def answer(intent):
        """The last compile: a refusal is the answer to a change, but in a build it costs only
        the ops refused (`salvaged`), and what was left out is said."""
        try:
            return compile_(intent)
        except IntentRefused as refused:
            if not build:
                raise
            prepared = prepare(intent) if prepare is not None else intent
            names = [r.name for r in input_list.parse_input_list(input_csv)]
            change_set, made, notes, _ = salvaged(compile_prepared, prepared, refused, names)
            return change_set, [*made, *notes]

    def call(prompt, label):
        """`(reply, cut)`: in a build, a reply cut off at a limit is not the end of the show --
        `cut` says which limit, and what the reply finished is read by `read`."""
        try:
            return capped.complete(system=system, user=prompt, response_schema=wire, label=label), None
        except AIProviderError as exc:
            partial = getattr(exc, "partial_text", "") or ""
            if not (build and "done_reason 'length'" in str(exc) and partial.strip()):
                raise
            return partial, str(exc)

    def read(reply, cut, lenient=False):
        if not cut:
            return parse_intent(reply, schema, infos, drop_bad_ops=lenient)
        part = complete_part(reply) or {}
        defaults = {"name": "Build the show", "notes": [], "ops": [], "categories": []}
        part = {**{k: v for k, v in defaults.items() if k in schema.get("required", [])},
                **{k: v for k, v in part.items() if k in schema["properties"]}}
        infos.append(f"the reply was cut off ({cut[:240]}); the {len(part.get('ops') or [])} op(s) it "
                     "finished are kept, and what it did not reach is asked for")
        return parse_intent(json.dumps(part), schema, infos, drop_bad_ops=True)

    trace["prompt_chars"] = len(system) + len(user)
    raw, cut = call(user, "intent")
    trace["replies"].append(raw)
    intent, problem = read(raw, cut)
    kept = None          # a first reply that compiled, kept should its repair not
    first = intent       # a first reply that parsed, for a build to fall back on
    if intent is not None:
        trace.update(intent=intent, first_try_valid=True)
        try:
            change_set, made = compile_(intent)
            missing = complete(intent) if complete is not None else ""
            if not missing:
                infos.extend(made)
                return change_set
            kept = (change_set, made, missing, intent)
            problem = missing
        except IntentRefused as refused:
            if not refused.repairable:
                if not build:
                    raise
                change_set, made = answer(intent)
                infos.extend(made)
                return change_set
            problem = "the compile refused it: " + "; ".join(refused.reasons)
    # One repair round: what was wrong, and a slice widened by what the answer named.
    again_user, _ = user_prompt(request, graph, wide_for=intent, members=members, **names)
    ask = _missing_only(again_user, raw, problem) if kept is not None else _again(again_user, raw, problem)
    second, cut2 = call(ask, "intent-repair")
    trace["replies"].append(second)
    intent, problem2 = read(second, cut2, lenient=build)
    if kept is not None and intent is not None:
        # The repair wrote only what was missing: it joins the first reply, and the compile
        # checks every name it uses (a member category, a channel) against the whole show.
        intent = _joined(kept[3], intent)
    if intent is not None:
        trace.update(intent=intent, repaired=True)
    if kept is not None:
        # The first reply was a show; asking for what it left out must not lose it.
        try:
            if intent is None:
                raise patch.ChangeError(problem2)
            change_set, made = compile_(intent)
        except (IntentRefused, patch.ChangeError) as why:
            trace.update(intent=kept[3], repaired=False)
            change_set, made = kept[0], kept[1]
            infos.append(f"the model was asked once more for what its reply left out ({kept[2][:200]}); "
                         f"the second reply was not usable ({str(why)[:200]}), so the first stands")
            infos.extend(made)
            return change_set
        still = complete(intent)
        infos.append(f"the model's first reply left something out ({kept[2]}), so it was asked once "
                     "more, for that only")
        if still:
            infos.append(f"still left out after asking once more, and not made by code: {still}")
        infos.extend(made)
        return change_set
    if intent is None and build and first is None:
        first, _ = parse_intent(raw, schema, infos, drop_bad_ops=True)
        problem = problem or ""
    if intent is None and build and first is not None:
        # The repair was not usable; the first reply was a show the compile refused in part.
        trace.update(intent=first, repaired=False)
        change_set, made = answer(first)
        infos.append(f"the model's first reply was not accepted ({problem[:200]}) and the second "
                     f"was not usable ({(problem2 or '')[:200]}), so the first was built without "
                     "what was refused")
        infos.extend(made)
        return change_set
    if intent is None:
        raise patch.ChangeError(
            f"the model's reply was not a usable intent, twice: {problem2}", partial_text=second)
    change_set, made = answer(intent)      # a second refusal is the answer (a build: in part)
    infos.append("the model's first reply was not accepted (" + problem[:200]
                 + "), so it was asked once more")
    infos.extend(made)
    return change_set


def compile_given(intent: dict, request: str, base: dict, *, console_model: str,
                  conventions: str | None = None, instructions: str | None = None,
                  input_list_text: str | None = None, aes50_devices: dict | None = None,
                  category_table=None, known_presets=None, infos: list[str] | None = None) -> dict:
    """The change set for an intent already written (`--intent-file`): no model is called.
    Raises `IntentRefused` for one that cannot be made, `patch.ChangeError` for one that
    is not an intent."""
    schema = intent_schema.intent_schema(console_model)
    problems = intent_schema.explain(intent, intent_schema.without_bounds(schema), validate_schema)
    if problems:
        raise patch.ChangeError("the file is not a valid intent:\n  " + "\n  ".join(problems[:8]))
    change_set, made = compile_intent(
        intent, base, console_model, text=request, category_table=category_table,
        aes50_devices=aes50_devices, input_list_text=input_list_text, known_presets=known_presets,
        conventions_text="\n".join(t for t in (conventions, instructions) if t))
    if infos is not None:
        infos.extend(made)
    return change_set


__all__ = ["compile_given", "IntentRefused", "REPLY_TOKENS", "bounds_text", "compile_change", "compile_intent",
           "parse_intent", "system_prompt", "user_prompt"]
