"""`atoo build --intent --intent-steps`: the Build's model step as THREE calls, not one.

`atoo build --intent` (`atoo/intent_build.py`) asks the model for the whole show's intent in one
reply. A small local model writes good channels and then leaves whole sections out, buses and
outputs above all. This path asks for the same intent in three scoped replies, each a smaller
problem with its own schema:

1. **categories and exceptions** (`add_channel`, `drop`, `order`, and the `categories` table
   without `dca` / `mute_group`): stereo pairs, strips that are not rows, renamed rows, rows left
   out, the strip order;
2. **buses and their sends** (`add_bus`, with `members`, `mode`, `level_db`, `to`);
3. **DCAs, mute groups and outputs** (`add_output`, Main first, then `add_group`).

Code still writes one channel per input-list row (`intent_build.with_rows`), and the same compile
(`intent_compile.compile_intent`) and merge (`patch.merge_change`) make the plan. Nothing in the
shared compiler is changed for this path.

**The prefix is built to be read once.** Every call's prompt starts with one byte-identical
prefix: the system prompt (`intent.md` and `intent_steps.md`, the same for all three steps),
then the user message's cached groups (`ai_provider.Prompt`): the domain knowledge, then the full
conventions, the input list and the preset names. Nothing in the prefix depends on the step.
Everything step-specific comes after it: the step's instruction and op list
(`intent_step_*.md`), and a compact summary of what the earlier steps compiled. So:

- on **Ollama** the shared prefix is its own user turn, then a fixed assistant turn (`TURN`),
  then the step's text as a second user turn (`ai_provider.chat_messages`). llama.cpp can reuse
  a prefix of a model with sliding-window attention (gemma3) only from a checkpoint, and it makes
  them at the start of a user turn and near a prompt's end: in one user turn, the steps shared no
  checkpoint past the system prompt, and each step read the whole prefix again (the Mac,
  2026-10-24: step 2 read its prompt in about 85 s, as step 1 did, while a repair, which extends
  its step's prompt, took 4-7 s). The second turn's start is the same in every step. The three
  calls (and any repair) also run with ONE `num_ctx`, sized once for the longest of them (a changed size reloads the model and loses its cached prefix), `keep_alive`
  set so the model stays loaded between them, one request at a time. Ollama's
  `prompt_eval_count` is the whole prompt either way; `prompt_eval_cached_count` says how much of
  it the cache held (steps 2 and 3: all but their tail), and `prompt_eval_duration` how long the
  rest took to read;
- on **Claude** the `cache_control` breakpoints fall after the prefix's groups (the
  mechanism), and no step schema is sent: a changed output format misses the cache, and step 2's
  schema is one Anthropic's decoder takes while steps 1 and 3 are not, so sending them would
  change the request between steps before the breakpoint. Each reply is checked against its
  step's schema here either way, as the single call's is;
- the per-step reply schema is a decoding grammar on Ollama, not part of the prompt.

**The single call's rules hold in every step**, so the two arms differ only in how the model is
asked: a near spelling of one row is read as that row (`intent_build.resolve_row_names`), an
output socket that cannot exist takes the one the conventions state (`with_stated_outputs`); the
completeness check (`intent_build.asked_for` / `left_out`) is run per step on its own sections
(buses in step 2; DCAs, mute groups and outputs in step 3; in step 1, an empty Category table
when the conventions give categories settings, `intent_build.categories_left_out`, which the
single call checks too), and a reply that compiles but leaves
one out is asked once more for that only, the answer added to it (what it repeats is dropped; an
unusable answer leaves the first standing; what is still missing is said at INFO and not made by
code); and Main's sockets the conventions state are filled in by code at INFO in the last
compile (`intent_build.with_main`).

**Per step.** The step's reply is parsed against its own schema and the joined intent (every
step so far) is compiled, so a name the compile refuses (a bus member that is no channel) is
refused AT THAT STEP, naming the step's own op. A member CATEGORY no channel carries is what it
is in the single call: a judgement miss, not an impossibility. The compile still makes the bus
or group and says at INFO that no channel matched (`intent_compile.resolve_members`); the step's
reply is kept, and no repair round is spent on it, so the two arms treat it alike. A step's ops only add: each step's schema holds only ops that
make something new, no two steps share an op, and only step 1 writes `categories`. Each step gets ONE section-scoped repair round, shown
its own reply and what was wrong. A refusal that is the engineer's own words meeting a limit is
final, as in `intent.compile_change`, and so is a second refusal after the repair (the build
stops, naming the reasons). A step whose reply is still not a usable intent after its repair (not
JSON, not the step's shape) adds nothing, said at INFO: what it would have written is a content
miss, and code never invents it.

**Measured per call** (`trace["steps"]`, kept in the build's own log): the step, first try or
repair, seconds, the prompt's size and its step tail's size (estimated from characters), what the
provider reported (`input`: the whole prompt -- Ollama's `prompt_eval_count` counts it all, cached
or not; `cache_read`: what the prompt cache held, Claude's cache reads or Ollama's
`prompt_eval_cached_count` (v0.33.3 and later); `cache_write` on Claude; `output`;
`prompt_eval_ms`: how long Ollama took to read the prompt, the cache's only sign on an older
Ollama), and whether the reply was accepted.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import sys
import time
from dataclasses import dataclass

from atoo import category_table as category_table_module
from atoo import generate, input_list, intent, intent_build, intent_schema, patch
from atoo.ai_provider import AIProviderError, CHARS_PER_TOKEN, ClaudeProvider, Prompt
from atoo.intent_compile import IntentRefused, compile_intent

#: How long Ollama keeps the model loaded after a call: longer than any step of a build on a CPU.
KEEP_ALIVE = "30m"
#: The request every step's compile reads (the build's own).
REQUEST = intent_build.REQUEST
#: The category fields step 1 may write: a DCA or mute group is step 3's `add_group`, so a group
#: has one way to be made.
_STEP1_CATEGORY_FIELDS = ("name", "aliases", "color", "hpf_hz", "gain_db", "trim_db", "fader_db",
                          "main_direct")
#: `add_channel` fields that name a group or a bus, which do not exist in step 1.
_NOT_IN_STEP1 = ("dca", "mute_group", "sends")


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    ops: tuple[str, ...]
    prompt: str
    categories: bool = False
    #: The kinds of `intent_build.asked_for` item this step must make (its completeness check).
    asks: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"intent-{self.key}"


STEPS = (
    Step("categories", "categories and exceptions", ("add_channel", "drop", "order"),
         "intent_step_categories.md", categories=True),
    Step("buses", "buses and their sends", ("add_bus",), "intent_step_buses.md", asks=("bus",)),
    Step("outputs", "DCAs, mute groups and outputs", ("add_output", "add_group"),
         "intent_step_outputs.md", asks=("DCA", "mute group", "output")),
)


def step_schema(console_model: str, step: Step) -> dict:
    """The JSON schema of one step's reply: the build intent's, with only the step's ops, and
    `categories` (without `dca` / `mute_group`) in step 1 alone."""
    whole = intent_schema.intent_schema(console_model, build=True)
    ops = []
    for branch in whole["properties"]["ops"]["items"]["oneOf"]:
        tag = branch["properties"]["op"]["enum"][0]
        if tag not in step.ops:
            continue
        if tag == "add_channel":
            branch = {**branch, "properties": {k: v for k, v in branch["properties"].items()
                                               if k not in _NOT_IN_STEP1}}
        ops.append(branch)
    # In the order a decoding grammar keeps (`tests/test_intent_key_order.py`): the table first,
    # as step 1's instruction asks for it.
    properties = {"name": whole["properties"]["name"]}
    required = ["name"]
    if step.categories:
        entry = category_table_module.ENTRY_SCHEMA
        properties["categories"] = {"type": "array", "items": {
            **entry, "properties": {k: v for k, v in entry["properties"].items()
                                    if k in _STEP1_CATEGORY_FIELDS}}}
        required.append("categories")
    properties.update(ops={"type": "array", "items": {"oneOf": ops}}, notes=whole["properties"]["notes"])
    required += ["ops", "notes"]
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def system_prompt(console_model: str) -> str:
    """The same for all three steps: the intent front end's rules and the steps' Build note."""
    return intent.system_prompt(console_model) + "\n" + generate.load_prompt("intent_steps.md")


def prefix_groups(*, conventions: str | None, conventions_name: str | None,
                  instructions: str | None, instructions_name: str | None, input_csv: str,
                  input_name: str | None, presets: list[str] | None) -> tuple[str, str]:
    """The user message's cached groups, from the part that changes least: the domain knowledge
    (the same for every show), then the show (the full conventions, the input list, the presets).
    Byte-identical for every call of one build: nothing here may depend on the step."""
    static = "\n".join(["# Domain knowledge", "", generate._domain_knowledge(), "", ""])
    show: list[str] = []
    if conventions or instructions:
        show += [generate._conventions_section(
            conventions or "", conventions_name or "<conventions>", instructions,
            instructions_name or "<instructions>"), ""]
    show += [f"# The input list ({input_name or 'input list'})", "", "```csv", input_csv.strip(), "```", ""]
    if presets:
        show += ["# Presets in the library", "", ", ".join(sorted(presets)), ""]
    return static, "\n".join(show) + "\n"


def step_tail(step: Step, built: str) -> str:
    """What comes after the prefix for `step`: its instruction, then what the earlier steps built."""
    n = STEPS.index(step) + 1
    return "\n".join([generate.load_prompt(step.prompt).strip(), "",
                      "# What the earlier steps built", "", built.strip(), "",
                      f"Reply with the JSON of step {n} and nothing else."])


#: The assistant turn between the shared prefix and a step's own text on a host that takes chat
#: turns (`ai_provider.chat_messages`); the same in every call, so it is part of the shared prefix.
TURN = "I have read the rules, the domain knowledge, the conventions and the input list. Which step?"


def step_prompt(groups: tuple[str, str], step: Step, built: str) -> Prompt:
    return Prompt(groups, step_tail(step, built), TURN)


def _again(step: Step, reply: str, problem: str) -> str:
    n = STEPS.index(step) + 1
    return (f"\n\n---\n\nYour previous reply for step {n}:\n\n{reply}\n\nIt was not accepted: "
            f"{problem}\n\nChange what that names and nothing else. Reply again with the corrected "
            f"JSON of step {n} and nothing else.")


def _missing_only(step: Step, reply: str, missing: str) -> str:
    """The section-scoped repair of a step whose reply was accepted but left something out: ask
    for that only; what comes back is added to the reply, never written over it."""
    n = STEPS.index(step) + 1
    return (f"\n\n---\n\nYour previous reply for step {n}:\n\n{reply}\n\nIt was accepted, but {missing}."
            f"\n\nReply with the JSON of step {n} carrying ONLY what is missing: its ops"
            + (", or its `categories`" if STEPS[n - 1].categories else "")
            + " (and `notes` for anything you leave out on purpose); they are added to your previous "
            "reply. Do not repeat anything from it.")


def _new_only(reply: dict, onto: dict) -> dict:
    """`reply` without the ops `onto` already has (a model asked for the missing part often
    writes some of the rest again): a repair adds, it never writes over."""
    def key(op):
        return (op.get("op"), op.get("object"), _norm(op.get("name")))
    have = {key(op) for op in onto["ops"]}
    return {**reply, "ops": [op for op in reply["ops"] if key(op) not in have]}


# -- what the earlier steps built, for the later ones --------------------------------------------

def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def channel_categories(change_set: dict, rows, joined: dict) -> dict[str, str]:
    """`{channel name: its category word}`: the input-list row's, else the one the intent gave."""
    by_row = {_norm(r.name): r.category for r in rows}
    stated = {_norm(op["name"]): op.get("category") for op in joined["ops"]
              if op["op"] == "add_channel" and op.get("category")}
    out = {}
    for c in change_set["add"]["channels"]:
        source = (c.get("source") or {}).get("input")
        out[c["name"]] = by_row.get(_norm(source)) or stated.get(_norm(c["name"])) or ""
    return out


def known_categories(change_set: dict, rows, joined: dict) -> dict[str, str]:
    """Every category word a member may name, normalised -> as it is spelled: the Category
    table's names and aliases, and the categories the built channels carry."""
    known = {}
    for entry in joined.get("categories") or []:
        for word in [entry["name"], *entry.get("aliases", [])]:
            known.setdefault(_norm(word), word)
    for word in channel_categories(change_set, rows, joined).values():
        if word:
            known.setdefault(_norm(word), word)
    return known


def built_summary(change_set: dict | None, rows, joined: dict) -> str:
    """The names later steps may use: every channel with its strip and category, the categories,
    and the buses. Compact: one line per channel."""
    if change_set is None:
        return "Nothing yet: code writes one channel for every input-list row after this step."
    cats = channel_categories(change_set, rows, joined)
    lines = ["Channels (strip: name, category):"]
    for c in change_set["add"]["channels"]:
        bank = "aux " if c.get("bank") == "aux" else "ch "
        stereo = ", stereo" if (c.get("source") or {}).get("stereo") else ""
        lines.append(f"- {bank}{c.get('channel')}: {c['name']}, {cats.get(c['name']) or 'no category'}{stereo}")
    known = known_categories(change_set, rows, joined)
    lines += ["", "Categories a member may name: " + (", ".join(sorted(set(known.values()), key=str.casefold))
                                                     or "none")]
    busses = change_set["add"].get("busses") or {}
    if busses:
        lines += ["", "Buses (written in step 2): " + ", ".join(busses)]
    return "\n".join(lines)


# -- one step ------------------------------------------------------------------------------------

_OP_REF = re.compile(r"^op (\d+) \(")


def _local(reasons: list[str], prepared: dict, mine_ops: list) -> list[str]:
    """The compile's reasons with its op numbers (of the whole prepared intent) turned into the
    step reply's own `ops[j]`, or "an op written earlier" for one this step did not write.
    `mine_ops`: the reply's ops as the prepared intent holds them, in the reply's order."""
    mine = {id(op): j for j, op in enumerate(mine_ops)}
    out = []
    for reason in reasons:
        m = _OP_REF.match(reason)
        if m:
            n = int(m.group(1))
            op = prepared["ops"][n - 1] if 0 < n <= len(prepared["ops"]) else None
            j = mine.get(id(op)) if op is not None else None
            reason = _OP_REF.sub(f"ops[{j}] (" if j is not None else "an op written earlier (", reason)
        out.append(reason)
    return out


def _joined(joined: dict, reply: dict, step: Step) -> dict:
    out = {**joined, "ops": [*joined["ops"], *reply["ops"]],
           "notes": [*joined["notes"], *(reply.get("notes") or [])]}
    if step.categories:
        # A repair asked only for the empty table brings the table; one that writes none keeps
        # what was there.
        out["categories"] = reply.get("categories") or joined.get("categories") or []
        out["name"] = reply.get("name") or joined["name"]
    return out


def _usage(provider, label: str) -> dict:
    usage = ((getattr(provider, "build_log", None) or {}).get(label) or {}).get("usage") or {}
    return {k: usage.get(k) for k in ("input", "cache_read", "cache_write", "output", "prompt_eval_ms")}


def _say(line: str) -> None:
    print(f"  INFO {line}", file=sys.stderr, flush=True)


def _tokens(n: int | None) -> str:
    return "?" if n is None else f"{n:,}"


def _call_line(call: dict) -> str:
    cached = (f", {_tokens(call['cache_read'])} cache read, {_tokens(call['cache_write'])} cache write"
              if call.get("cache_read") is not None or call.get("cache_write") is not None else "")
    return (f"intent step {call['n']}/3 ({call['step']}), {call['attempt']}: {call['seconds']:.1f} s; "
            f"prompt ~{call['prompt_tokens_estimated']:,} tokens of which the step's own ~"
            f"{call['tail_tokens_estimated']:,}; the provider counted {_tokens(call['input'])} in{cached}, "
            f"{_tokens(call['output'])} out"
            + (f"; prompt read in {call['prompt_eval_ms'] / 1000:.1f} s" if call.get("prompt_eval_ms") is not None
               else ""))


def generate_plan(conventions: str, input_csv: str, *, provider, console_model: str,
                  conventions_name: str = "<conventions>", input_name: str = "<input list>",
                  instructions: str | None = None, instructions_name: str | None = None,
                  category_table=None, known_presets=None, infos: list[str] | None = None,
                  replies: list | None = None, trace: dict | None = None,
                  reserved_user_slots=()) -> dict:
    """Conventions + input list -> a plan, by three scoped intents. The contract of
    `intent_build.generate_plan`: anything code decided goes to `infos`, the model's replies to
    `replies`, and `generate.GenerationError` names what made a plan impossible. `trace` gets
    `steps`, one record per call (see the module docstring), and `settings` (num_ctx, keep_alive,
    seed and temperature as sent, where the provider has them)."""
    infos = infos if infos is not None else []
    trace = trace if trace is not None else {}
    replies_out = trace.setdefault("replies", [])
    calls = trace.setdefault("steps", [])
    base = patch.empty_base(console_model)
    rows = input_list.parse_input_list(input_csv)
    presets = sorted(known_presets) if known_presets else None
    conventions_text = "\n".join(t for t in (conventions, instructions) if t)
    system = system_prompt(console_model)
    groups = prefix_groups(conventions=conventions, conventions_name=conventions_name,
                           instructions=instructions, instructions_name=instructions_name,
                           input_csv=input_csv, input_name=input_name, presets=presets)
    worker = for_steps(provider, system, groups, input_csv)
    trace["settings"] = settings_of(worker)

    asked = intent_build.asked_for(conventions_text)
    boxes = intent_build.stage_boxes(rows)
    row_words = {w for row in rows for w in re.findall(r"[a-z0-9]+", (row.category or "").casefold())}

    def compile_raw(prepared):
        return compile_intent(
            prepared, base, console_model, text=REQUEST, category_table=category_table,
            input_list_text=input_csv, known_presets=known_presets,
            conventions_text=conventions_text, build=True, reserved_user_slots=reserved_user_slots)

    def compile_(joined, *, fill_main=False, salvage=False):
        """The joined intent compiled as the single call's is: near spellings of a row read as the
        row, code's rows, and (the last compile only) Main's stated sockets filled in. `salvage`:
        a refusal costs only the ops refused (`intent.salvaged`), as the single call's last compile
        does, and the intent returned is the one that compiled."""
        valued, value_infos = intent_build.with_reasonable_values(joined)
        named, row_infos = intent_build.resolve_row_names(valued, rows)
        named, pair_infos = intent_build.with_stated_pairs(named, rows, conventions_text)
        named, aux_infos = intent_build.with_stated_aux(named, rows, conventions_text)
        named, hpf_infos = intent_build.with_stated_hpf(named, rows, conventions_text)
        named, strip_infos = intent_build.with_asked_strips(named, conventions_text, rows)
        named, order_infos = intent_build.with_stated_order(named, conventions_text, rows)
        row_infos = [*value_infos, *row_infos, *pair_infos, *aux_infos, *hpf_infos, *strip_infos,
                     *order_infos]
        named, out_infos = intent_build.with_stated_outputs(named, asked, console_model, boxes, conventions_text)
        row_infos = [*row_infos, *out_infos]
        prepared = intent_build.with_rows(named, rows)
        filled = None
        if fill_main:
            prepared, filled = intent_build.with_main(prepared, asked, conventions_text)
        prepared, free_infos = intent_build.with_free_outputs(prepared, asked, console_model, boxes, conventions_text)
        row_infos = [*row_infos, *free_infos]
        try:
            cs, made = compile_raw(prepared)
        except IntentRefused as refused:
            if not salvage:
                raise
            cs, made, notes, prepared = intent.salvaged(compile_raw, prepared, refused, [r.name for r in rows])
            made = [*made, *notes]
        return prepared, cs, [*row_infos, *([filled] if filled else []), *made]

    def left_out(step, merged):
        """What the conventions ask for in this step's sections that the joined intent neither
        makes nor names in its notes (`intent_build.left_out`, the single call's own check)."""
        if step.categories:
            return intent_build.categories_left_out(merged, conventions_text, rows)
        mine = [a for a in asked if a.kind in step.asks]
        if not mine:
            return ""
        return intent_build.left_out(intent_build.with_main(merged, asked, conventions_text)[0], mine, row_words)

    joined = {"name": "Build the show", "ops": [], "notes": [], "categories": []}
    try:
        # The rows alone, before any step: what a later step may name if an earlier one fails.
        _, cs, made = compile_(joined, salvage=True)   # one bad row costs that row, never the show
        compiled = (cs, made)             # (change set, infos) of the joined intent so far
        for n, step in enumerate(STEPS, start=1):
            schema = step_schema(console_model, step)
            wire = None if isinstance(worker, ClaudeProvider) else intent_schema.wire_schema(schema)
            built = built_summary(compiled[0] if n > 1 else None, rows, joined)
            user = step_prompt(groups, step, built)

            def attempt(prompt, label, word, onto, only_new=False):
                """One call; `(raw, (merged, cs, infos) or None, problem, refusal)`. `onto` is the
                joined intent the reply adds to; `only_new`: a repair that asked only for what was
                missing, so what the reply repeats is dropped (it adds, never edits)."""
                started = time.monotonic()
                cut = None
                try:
                    raw = worker.complete(system=system, user=prompt, response_schema=wire, label=label)
                except AIProviderError as exc:
                    # Cut off at a limit: what the reply finished stands, as in the single call.
                    if "done_reason 'length'" not in str(exc) or not (getattr(exc, "partial_text", "") or "").strip():
                        raise
                    cut, raw = str(exc), exc.partial_text
                call = {"n": n, "step": step.key, "attempt": word, "label": label,
                        "seconds": round(time.monotonic() - started, 1),
                        "prompt_tokens_estimated": int((len(system) + len(prompt)) / CHARS_PER_TOKEN),
                        "tail_tokens_estimated": int(len(prompt.tail) / CHARS_PER_TOKEN),
                        **_usage(worker, label), "accepted": False, "problem": None}
                calls.append(call)
                replies_out.append(raw)
                if cut is None:
                    reply, problem = intent.parse_intent(raw, schema, infos, drop_bad_ops=word == "repair")
                else:
                    part = intent.complete_part(raw) or {}
                    part = {"name": part.get("name") or step.title, "notes": part.get("notes") or [],
                            "ops": part.get("ops") or [],
                            **({"categories": part["categories"]} if "categories" in part
                               and "categories" in schema["properties"] else {})}
                    infos.append(f"intent step {n} ({step.title}): the reply was cut off ({cut[:200]}); the "
                                 f"{len(part['ops'])} op(s) it finished are kept")
                    reply, problem = intent.parse_intent(json.dumps(part), schema, infos, drop_bad_ops=True)
                result = refusal = None
                if reply is not None:
                    if only_new:
                        reply = _new_only(reply, onto)
                    merged = _joined(onto, reply, step)
                    try:
                        prepared, cs, made = compile_(merged)
                        result = (merged, cs, made)
                    except IntentRefused as refused:
                        refused.joined = merged       # for a last compile that drops what it refused
                        if not refused.repairable:
                            raise
                        refusal = refused
                        named = intent_build.resolve_row_names(merged, rows)[0]
                        problem = "the compile refused it: " + "; ".join(_local(
                            refused.reasons, intent_build.with_rows(named, rows),
                            named["ops"][len(onto["ops"]):]))
                call.update(accepted=result is not None, problem=problem)
                _say(_call_line(call))
                return raw, result, problem, refusal

            raw, result, problem, _ = attempt(user, step.label, "first try", joined)
            missing = left_out(step, result[0]) if result is not None else ""
            if missing:
                # The reply is a step's worth of show, short of something its sections ask for:
                # asked once more for that only, and what comes back is added to it.
                kept = result
                _say(f"intent step {n}/3 ({step.key}): the first reply left something out ({missing[:300]}), "
                     "so it was asked once more, for that only")
                _, more, problem2, _ = attempt(user.with_tail(_missing_only(step, raw, missing)),
                                               step.label + "-repair", "repair", kept[0], only_new=True)
                infos.append(f"intent step {n} ({step.title}): the model's first reply left something out "
                             f"({missing}), so it was asked once more, for that only")
                if more is None:
                    infos.append(f"intent step {n} ({step.title}): the second reply was not usable "
                                 f"({(problem2 or '')[:200]}), so the first stands")
                    result = kept
                else:
                    result = more
                    still = left_out(step, more[0])
                    if still:
                        infos.append(f"still left out after asking once more, and not made by code: {still}")
            elif result is None:
                _say(f"intent step {n}/3 ({step.key}): the first reply was not accepted "
                     f"({problem[:200]}), so it was asked once more")
                raw, result, problem2, refusal = attempt(user.with_tail(_again(step, raw, problem)),
                                                         step.label + "-repair", "repair", joined)
                if refusal is not None:
                    # A second refusal is the answer, as in the single call: in a build it costs
                    # only what was refused, and the rest of the step stands.
                    joined, cs, made = compile_(refusal.joined, salvage=True)
                    infos.append(f"intent step {n} ({step.title}): the first reply was not accepted "
                                 f"({problem[:200]}), so it was asked once more; what the second "
                                 "still had refused is left out")
                    infos.extend(m for m in made if m.startswith("not built"))
                    compiled = (cs, made)
                    continue
                if result is None:
                    infos.append(f"intent step {n} ({step.title}) gave no usable reply after its "
                                 f"repair round ({(problem2 or '')[:200]}), so nothing of it is in the "
                                 "show: code does not write it in the model's place")
                    continue
                infos.append(f"intent step {n} ({step.title}): the first reply was not accepted "
                             f"({problem[:200]}), so it was asked once more")
                still = left_out(step, result[0])
                if still:
                    infos.append(f"still left out after asking once more, and not made by code: {still}")
            joined, cs, made = result
            compiled = (cs, made)
        # The last compile, as the single call's: Main's stated sockets filled in where the steps
        # left Main unpatched or unmade (said at INFO, "filled by code").
        _, cs, made = compile_(joined, fill_main=True, salvage=True)
        compiled = (cs, made)
    except IntentRefused as refused:
        raise generate.GenerationError(
            "the intent cannot be built on this console:\n  " + "\n  ".join(refused.reasons),
            reply=(replies_out or [""])[-1]) from refused
    finally:
        if replies is not None:
            replies.extend(replies_out)
        _keep_usage(provider, worker)
    trace["intent"] = joined
    change_set, made = compiled
    infos.extend(made)
    text = change_set.get(patch.TEXT_KEY)
    change_set = patch.validate_change_set(copy.deepcopy(change_set), infos=infos)
    merge = intent_build.merge_built(base, change_set, console_model=console_model, text=text,
                                     infos=infos, reply=(replies_out or [""])[-1])
    plan = merge.plan
    intent_build.declare_left_out(plan, rows, [*infos, *merge.infos])
    plan.setdefault("meta", {})["console_model"] = console_model
    plan.setdefault("notes", []).extend(
        {"text": line, "source": "allocation"} for line in [*infos, *merge.infos])
    return plan


# -- the provider, set up once for the run ---------------------------------------------------------

def for_steps(provider, system: str, groups: tuple[str, str], input_csv: str):
    """The provider the three steps share: the intent's reply cap (`intent._capped`), and on
    Ollama ONE `num_ctx` for every call, sized for the longest (the last step's tail lists every
    channel, and a repair re-sends a whole reply), and `keep_alive`, so the model stays loaded
    with its cached prefix. A setting the caller made (`ATOO_AI_NUM_CTX`) is kept. A copy: the
    caller's provider is not changed."""
    worker = intent._capped(provider)
    if not dataclasses.is_dataclass(worker):
        return worker
    changes = {}
    if hasattr(worker, "keep_alive") and getattr(worker, "keep_alive") is None:
        changes["keep_alive"] = KEEP_ALIVE
    if hasattr(worker, "num_ctx") and getattr(worker, "num_ctx") is None and hasattr(worker, "_auto_num_ctx"):
        longest_tail = max(len(step_tail(s, "")) for s in STEPS)
        # The summary is about two lines of text per input row; a repair adds the reply it re-sends.
        room = longest_tail + 2 * len(input_csv) + int(intent.REPLY_TOKENS * CHARS_PER_TOKEN) + 1000
        changes["num_ctx"] = worker._auto_num_ctx(system, "".join(groups) + " " * room)
    return dataclasses.replace(worker, **changes) if changes else worker


def settings_of(worker) -> dict:
    """What the steps were sent with, for the report: unset where the provider has no such field."""
    return {k: getattr(worker, k, None) for k in ("num_ctx", "keep_alive", "seed", "num_predict")} \
        | {"temperature": 0 if type(worker).__name__ == "OllamaProvider" else None}


def _keep_usage(provider, worker) -> None:
    """The steps' per-call usage, in the caller's provider's build log too: `dataclasses.replace`
    gives the copy a fresh one, and the build's own log is written from the caller's."""
    mine, theirs = getattr(worker, "build_log", None), getattr(provider, "build_log", None)
    if mine is not None and theirs is not None and mine is not theirs:
        theirs.update(mine)


__all__ = ["STEPS", "Step", "built_summary", "for_steps", "generate_plan", "prefix_groups",
           "step_prompt", "step_schema", "system_prompt"]
