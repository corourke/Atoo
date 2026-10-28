"""`atoo patch`: a change typed in plain English, compiled on its own
and merged onto the show already on the desk, slices 1 and 2.

Amend is a special case. The idea is to add
something temporary to an existing show or make changes to an existing
show, typically on the fly and at short notice, without spending the time
on a whole rebuild: the user states what is needed in plain English, and
only that part is compiled, the delta worked out and applied.

## Words

What the engineer types is a **change** ("trumpet, sax and trombone on
A 21-23, in the Horns DCA"). What the model hands back is the
change's **change set**: objects to add, objects to drop, and a short name
for the change. "Patch" is the command's name and, everywhere else in this
project, still means socket routing -- a channel's `patch` field, the
`patch.*` findings -- so this module never calls the model's output "the
patch".

## The front half is new; the back half is amend's, unchanged

1. **The base** -- the plan on the desk. Chosen by the caller
   (`cli.patch_cmd`): the desk's own newest journal entry's plan, else
   `plan.json` (with an INFO), else **an empty base** (`empty_base`),
   because building a show up from an initialized board, one change at a
   time, is a supported use.
2. **The compile** (`compile_change`) -- one model call. Input: the base
   as read-only context, the house conventions and the bundle's
   instructions (comments stripped, exactly as `build` sends them, through
   `generate._conventions_section`), and the typed change. Output: a
   change set (`CHANGE_SET_SCHEMA`), never a whole plan -- a model asked
   to restate the show re-decides things nobody asked about, which is
   where amend's "modified, not written" noise came from.
3. **The merge** (`merge_change`) -- deterministic. Adds the new objects
   to a copy of the base, drops the dropped channels, and **refuses a
   reference to anything that does not exist**: a send to a bus that is
   neither on the desk nor added by this change cannot be set, so the
   whole change is refused (`ChangeKind.REFUSED`, a blocking kind) rather
   than written half-connected. Console indices for new busses, DCAs,
   mute groups and outputs are code's job (D11), taken from what is free
   in the base. Sockets the change named are honoured; ones it did not
   name are chosen and announced at INFO (the judgement rule).
4. **The back half** -- `amend.plan_amendment` over `(base, merged)`, and
   then everything `atoo amend` already does: placement on free
   strips, the pre-flight verify and socket check, the review, the one
   arming control, the write, the FR-2.2 untouched-strip proof, the
   journal and undo. Nothing downstream of the merge knows the difference
   between a merged change and a rebuilt plan.

## Editing what is running: only the fields the change names (slice 2)

A change may also edit something already on the desk -- "move the sax to
MON3 at -10", "HPF 100 on the vocals" -- through the change set's
`modify`, each entry naming the object and `fields`: a dotted path per
field the change names, and its new value. `_merge_modify` sets those
paths on a copy of the object and on nothing else, so the merged plan
differs from the desk's in the named fields only; the back half
(`amend._plan_edits`) then writes exactly the addresses those fields
change. That is the enforcement -- in code, not in the prompt. A fader
or mute is set only when the change's own words name it. What is still
**not written**, as `ChangeKind.MODIFIED`: a running object restated
whole in `add` and a `modify` said in words with no fields. Dropping a bus,
a DCA, a mute group or an output is carried out:
`_drop_bus`, `_drop_group`, `_drop_output`. The merged plan keeps the base's
version of anything it did not write, so the plan journalled as "on the
desk" stays true.

Keeping a change for good -- its text into `instructions.md`, its new
inputs into `input.csv` -- is `atoo/promote.py` (slice 3).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from atoo import amend as amend_engine
from atoo import apply as apply_module
from atoo import console_facts as facts
from atoo import generate
from atoo import inferred
from atoo import journal_stack
from atoo import plan_schema
from atoo import strict_schema
from atoo.allocate import (CONSOLE_BUS_CAPACITY, CONSOLE_DCA_CAPACITY,
                                CONSOLE_MAIN_CAPACITY, CONSOLE_MATRIX_CAPACITY,
                                CONSOLE_MUTE_GROUP_CAPACITY, allocate_console_indices)
from atoo.amend import Change, ChangeKind
from atoo.json_repair import extract_json_object, loads_with_repair
from atoo import plan_compat
from atoo.schema_check import validate as validate_schema
from atoo import verify_plan
from atoo.ai_provider import Prompt
from atoo.verify_plan import PASSIVE_RIBBON_MODELS, resolve_console_model

#: How long a change's short name may be. "A few words" -- it is a row in
#: a journal listing and a line on a review, not a description.
CHANGE_NAME_MAX = 48

#: The kinds of object a change set can add or drop, as `(plan key, word)`.
OBJECT_KINDS = (("channels", "channel"), ("busses", "bus"), ("dcas", "dca"),
                ("mute_groups", "mute group"), ("outputs", "output"))

_NAMED_KINDS = ("busses", "dcas", "mute_groups", "outputs")

#: What the model returns. The objects it adds are the SAME shapes a plan
#: holds (`plan_schema`'s own sub-schemas, not copies), so an added channel
#: is checked by exactly the rules a built one is, and the merged plan is an
#: ordinary plan to everything after it.
CHANGE_SET_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": CHANGE_NAME_MAX},
        "add": {
            "type": "object",
            "properties": {
                "channels": {"type": "array", "items": plan_schema.CHANNEL_SCHEMA},
                "busses": {"type": "object",
                           "additionalProperties": plan_schema.BUS_SCHEMA},
                "dcas": {"type": "object",
                         "additionalProperties": plan_schema.DCA_SCHEMA},
                "mute_groups": {"type": "object"},
                "outputs": {"type": "object",
                            "additionalProperties": plan_schema.OUTPUT_SCHEMA},
            },
            "required": ["channels", "busses", "dcas", "mute_groups", "outputs"],
            "additionalProperties": False,
        },
        "drop": {
            "type": "object",
            "properties": {
                key: {"type": "array", "items": {"type": "string", "minLength": 1}}
                for key, _ in OBJECT_KINDS
            },
            "required": [key for key, _ in OBJECT_KINDS],
            "additionalProperties": False,
        },
        # What the change asks of something ALREADY on the desk that is
        # neither an addition nor a removal (slice 2): the object, what was
        # asked in words, and `fields` -- each named field's dotted path and
        # its new value, and nothing else. Only those are written
        # (`_merge_modify`); an entry with no fields is reported, not written.
        "modify": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "object": {"type": "string",
                               "enum": [word for _, word in OBJECT_KINDS]},
                    "name": {"type": "string", "minLength": 1},
                    "change": {"type": "string", "minLength": 1},
                    "fields": {"type": "object"},
                },
                "required": ["object", "name", "change", "fields"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "add", "drop", "modify", "notes"],
    "additionalProperties": False,
}

#: The key a SAVED change set carries its change text under
#: (`--save-change-set`, and the review's `change.change_set`). Not part of
#: the model's reply -- it is the question, recorded beside the answer.
TEXT_KEY = "change"


class ChangeError(RuntimeError):
    """The model answered, but the answer is not a usable change set.

    `partial_text` carries what there was to look at, exactly as
    `generate.GenerationError` does -- a paid-for reply is the only evidence
    of why it failed."""

    def __init__(self, *args, partial_text: str = ""):
        super().__init__(*args)
        self.partial_text = partial_text


def empty_base(console_model: str | None) -> dict:
    """The plan of a desk nothing has been written to by this bundle and no
    build describes: no channels, no groups, no busses, no outputs. A change
    compiled onto it builds a show up from an initialized board, which is a supported
    way to build up a show file: dictating one piece at a time."""
    plan = {"channels": [], "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {}}
    if console_model:
        plan["meta"] = {"console_model": console_model}
    return plan


def empty_change_set(name: str = "") -> dict:
    return {"name": name, "add": {"channels": [], "busses": {}, "dcas": {},
                                  "mute_groups": {}, "outputs": {}},
            "drop": {key: [] for key, _ in OBJECT_KINDS}, "modify": [], "notes": []}


# --------------------------------------------------------------------------
# The compile -- one model call
# --------------------------------------------------------------------------


def change_system(console_model: str) -> str:
    return generate.load_prompt("change_compile.md",
                                console=generate.console_section(console_model),
                                # The plan's own format, not the shorter
                                # reply the generator writes: a change set
                                # is a handful of objects, merged into a
                                # plan as they are (reply_expand.py).
                                schema=plan_schema.schema_section(compact=False))


def _base_for_prompt(base: dict) -> dict:
    """The base as the model reads it: the console objects, not this
    project's bookkeeping. `meta` carries build findings and hashes the
    model has no use for, and `notes` are the previous build's questions,
    not facts about the desk."""
    return {k: base.get(k) for k in ("channels", "dcas", "mute_groups", "busses", "outputs")
            if k in base}


def change_user(base: dict, change_text: str, *, conventions: str | None,
                conventions_name: str | None, instructions: str | None = None,
                instructions_name: str | None = None) -> str:
    if conventions:
        conventions_part = generate._conventions_section(
            conventions, conventions_name or "<conventions>", instructions, instructions_name)
    elif instructions:
        conventions_part = generate._conventions_section(
            instructions, instructions_name or "<instructions>", None, None)
    else:
        conventions_part = ("# The engineer's conventions\n\nNone were given for this "
                            "change. Follow the change as written, and the domain "
                            "knowledge above.")
    channels = base.get("channels") or []
    if channels:
        desk = (f"The desk holds {len(channels)} channel(s). This is READ-ONLY context: "
                "refer to its busses, DCAs and mute groups by these exact names, and "
                "never restate an object that is already here.")
    else:
        desk = ("The desk holds NO channels yet -- this change builds on an initialized "
                "board. Add whatever the change needs, busses and groups included.")
    # Cache groups: the domain knowledge is true of every
    # show; the conventions are a show's; the desk is what a repair of this
    # change re-sends and what a second patch re-sends only if nothing was
    # applied in between. The change itself is last.
    return Prompt((
        f"""\
# Domain knowledge

{generate._domain_knowledge()}

---

""",
        f"""\
{conventions_part}

---

""",
        f"""\
# The plan currently on the desk

{desk}

```json
{generate.prompt_json(_base_for_prompt(base))}
```

---

""",
    ), f"""\
# The change

{change_text.strip()}

---

Compile this change. Emit the change set JSON and nothing else.""")


def parse_change_set(raw: str, *, infos: list[str] | None = None) -> dict:
    """A model reply -> a validated change set, or `ChangeError`. What was
    decided on the way (`validate_change_set`) is appended to `infos`."""
    try:
        change_set = extract_json_object(raw)
    except Exception:  # noqa: BLE001
        try:
            change_set, _repairs = loads_with_repair(
                generate._json_fragment(raw), expect_keys=frozenset(CHANGE_SET_SCHEMA["properties"]))
        except Exception as exc:  # noqa: BLE001
            raise ChangeError(f"the model's reply did not contain a usable change set: {exc}",
                              partial_text=raw) from exc
    return validate_change_set(change_set, partial_text=raw, infos=infos)


def _fill_omitted_sections(change_set: dict) -> list[str]:
    """Give every section the reply left out the empty value it means, in
    place, and return the dotted names of those it filled.

    The format asks for every key, and a model that has nothing to put in
    a section sometimes leaves the key out -- an `add` of one channel with
    no `busses`, `dcas`, `mute_groups` or `outputs`. An absent section says
    exactly what an empty one does, so refusing the change for it would
    refuse a change that can be applied. A section of the wrong type is
    not filled; the schema reports it."""
    def empty_of(section: str, key: str):
        return [] if section == "drop" or key == "channels" else {}

    filled: list[str] = []
    for section in ("add", "drop"):
        if section not in change_set:
            change_set[section] = {key: empty_of(section, key) for key, _ in OBJECT_KINDS}
            filled.append(section)
        elif isinstance(change_set[section], dict):
            body = change_set[section] = dict(change_set[section])
            for key, _ in OBJECT_KINDS:
                if key not in body:
                    body[key] = empty_of(section, key)
                    filled.append(f"{section}.{key}")
    for section in ("modify", "notes"):
        if section not in change_set:
            change_set[section] = []
            filled.append(section)
    return filled


def _cut_cosmetic_names(change_set: dict, infos: list[str] | None) -> None:
    """Cut the names that are only labels to the length they are shown at,
    in place, and say so in `infos`.

    A change's short name is a row in a journal and a strip's name is what
    the console shows in sixteen characters: a longer one is a preference
    the model did not keep to, not a setting that cannot work, so it must
    not refuse a reply that is otherwise whole (and was paid for)."""
    def cut(owner: dict, what: str, limit: int) -> None:
        name = owner.get("name")
        if isinstance(name, str) and len(name) > limit:
            owner["name"] = name[:limit].rstrip() or name[:limit]
            if infos is not None:
                infos.append(f"{what} {name!r} is {len(name)} characters, longer than the "
                             f"{limit} it is shown at; it is cut to {owner['name']!r}")

    cut(change_set, "the change's name", CHANGE_NAME_MAX)
    modify = change_set.get("modify")
    if isinstance(modify, list):
        # A rename of a strip already on the desk is cut the way the name of
        # one this change adds is; the entries are copied, never edited.
        change_set["modify"] = modify = list(modify)
        for index, request in enumerate(modify):
            if not (isinstance(request, dict) and request.get("object") == "channel"):
                continue
            fields = request.get("fields")
            if isinstance(fields, dict) and isinstance(fields.get("name"), str):
                modify[index] = request = dict(request, fields=dict(fields))
                cut(request["fields"], f"the new name for channel {request.get('name')!r}",
                    facts.NAME_MAX_CHARS)
    add = change_set.get("add")
    channels = add.get("channels") if isinstance(add, dict) else None
    if isinstance(channels, list):
        change_set["add"] = add = dict(add)
        add["channels"] = channels = [dict(c) if isinstance(c, dict) else c for c in channels]
        for channel in channels:
            if isinstance(channel, dict):
                cut(channel, "the new channel's name", facts.NAME_MAX_CHARS)


#: Required booleans a reply may write as `null` and be read as `false`: the
#: safe state, said at INFO. A 48V switch left off breaks nothing (a
#: condenser stays silent until the engineer says so), and `stated: false`
#: only means the code checks the socket against the desk.
_NULL_READ_AS_OFF = {"phantom": "48V is not switched on; say \"phantom on\" in the change if the mic needs it",
                     "stated": "the socket is treated as chosen, not named, and checked against the desk"}


def _read_nulls(node, schema: dict, path: str, unstated: list[str], off: list[tuple[str, str]]) -> None:
    """Walk a reply with its schema and settle every `null` the format does
    not allow, in place. A property the schema lets a reply leave out is
    removed (it is "not stated", the same as omitted); a required boolean in
    `_NULL_READ_AS_OFF` becomes `false`. Anything else is left for the
    schema to report -- a null where a real setting is needed is a reply
    that does not say."""
    options = strict_schema.branches(schema)
    branch = strict_schema.pick(node, options)
    kind = strict_schema.kind_of(branch)
    if kind == "array" and isinstance(node, list):
        for i, item in enumerate(node):
            _read_nulls(item, branch["items"], f"{path}[{i}]", unstated, off)
    elif kind == "object" and isinstance(node, dict):
        required = set(branch.get("required") or [])
        for name, sub in branch["properties"].items():
            if name not in node:
                continue
            where = f"{path}.{name}" if path else name
            if node[name] is None and not strict_schema.accepts_null(strict_schema.branches(sub)):
                if name not in required:
                    del node[name]
                    unstated.append(where)
                elif name in _NULL_READ_AS_OFF:
                    node[name] = False
                    off.append((where, _NULL_READ_AS_OFF[name]))
            else:
                _read_nulls(node[name], sub, where, unstated, off)
    elif kind == "map" and isinstance(node, dict):
        for name, item in node.items():
            _read_nulls(item, branch["additionalProperties"], f"{path}.{name}", unstated, off)


def _read_nulls_as_unstated(change_set: dict, infos: list[str] | None) -> None:
    """`null` for a field the format lets a reply leave out is not a setting
    that cannot work, only a reply that does not say: it is read as not stated,
    and the INFO says which fields."""
    unstated: list[str] = []
    off: list[tuple[str, str]] = []
    for section in ("add", "modify"):
        if section in change_set:
            _read_nulls(change_set[section], CHANGE_SET_SCHEMA["properties"][section],
                        section, unstated, off)
    if infos is None:
        return
    def shape(paths):
        return sorted({re.sub(r"\[\d+\]", "[]", p) for p in paths})
    if unstated:
        infos.append(f"{len(unstated)} field(s) were null where the format lets a reply leave them "
                     f"out; each is read as not stated: {', '.join(shape(unstated))}")
    for field_ in shape(w for w, _ in off):
        why = next(r for w, r in off if re.sub(r"\[\d+\]", "[]", w) == field_)
        count = sum(1 for w, _ in off if re.sub(r"\[\d+\]", "[]", w) == field_)
        infos.append(f"{field_} was null on {count} entr{'y' if count == 1 else 'ies'}; read as "
                     f"false -- {why}")


def validate_change_set(change_set, *, partial_text: str = "",
                        infos: list[str] | None = None) -> dict:
    if not isinstance(change_set, dict):
        raise ChangeError("a change set is a JSON object", partial_text=partial_text)
    change_set = dict(change_set)
    change_set.pop(TEXT_KEY, None)
    filled = _fill_omitted_sections(change_set)
    if filled and infos is not None:
        infos.append(
            f"the change set left out {', '.join(filled)}; each is read as empty -- "
            "nothing to add, drop or modify there -- and the rest of the change stands")
    # The same tolerance `generate` extends to a plan: an unconstrained
    # model writing "" for "no notes" means the same as [].
    notes = change_set.get("notes")
    if isinstance(notes, str):
        change_set["notes"] = [notes] if notes.strip() else []
    modify = change_set.get("modify")
    if isinstance(modify, list):
        # A change set saved before slice 2 said a modification in words
        # only. It still loads, and is still reported rather than written.
        change_set["modify"] = [dict(m, fields=m.get("fields") or {})
                                if isinstance(m, dict) and "fields" not in m else m
                                for m in modify]
    add = change_set.get("add")
    if isinstance(add, dict):
        # An output's or a bus destination's `socket`/`sockets` are
        # `patch`/`patches`; a change set saved before
        # then, or a model that reached for the old name, still reads.
        add = change_set["add"] = plan_compat.normalise_plan(add)
        inferred.tag_model_markers(add)
    _cut_cosmetic_names(change_set, infos)
    _read_nulls_as_unstated(change_set, infos)
    violations = validate_schema(change_set, CHANGE_SET_SCHEMA)
    if violations:
        shown = "\n  ".join(violations[:10])
        more = f"\n  ...and {len(violations) - 10} more" if len(violations) > 10 else ""
        raise ChangeError(f"the change set does not match the change-set format:\n  {shown}{more}",
                          partial_text=partial_text or json.dumps(change_set, indent=2))
    return change_set


def _repair_user(user: str, reply: str, problem: str) -> str:
    """The user message of a repair call: the original, then the reply that
    was not accepted and exactly why, so the model changes what the message
    names and nothing else."""
    more = f"""

---

# Your previous reply was not accepted

```json
{reply.strip()}
```

It was refused for this reason:

{problem}

Return the corrected change set: the whole JSON object, and nothing else. Change only what the
reason names; keep everything the reason does not name."""
    # A Prompt keeps its cached groups, so the repair reads the original
    # request from the cache; a plain string just grows.
    return user.with_tail(more) if isinstance(user, Prompt) else f"{user}{more}"


#: Phrases that mean a reply's own note says it is not the answer. Short and
#: conservative: a note that merely says "supersedes the factory name" is a
#: description of the change, not a retraction of the reply.
_RETRACTION = re.compile(
    r"\b(?:(?:this|the)\s+(?:reply|response|change set|answer|change)\s+(?:is\s+)?"
    r"(?:superseded|retracted|incomplete|void|invalid)"
    r"|(?:is|was|been|are)\s+(?:retracted|withdrawn)"
    r"|(?:reply|response|answer)\s+(?:is|was)\s+superseded"
    r"|need(?:s|ed|ing)?\s+(?:a\s+)?re-?run|please\s+re-?run|re-?run\s+(?:this|the)\s+(?:change|request)"
    r"|treat\s+this\s+(?:change|reply|response)\s+as"
    r"|(?:entry|reply|response|answer|change\s+set)(?:\s+above)?\s+is\s+incorrect"
    r"|see\s+the\s+corrected\s+(?:set|change|reply)|not\s+possible\s+in\s+this\s+format"
    r"|ignore\s+(?:this|the)\s+(?:reply|response|change set|answer|change)"
    r"|incomplete\s+(?:reply|response|change set|answer)"
    r"|(?:i|we)\s+(?:could\s*not|couldn't|cannot|can't|was\s+unable\s+to|am\s+unable\s+to)\b"
    r"|will\s+not\s+apply|not\s+the\s+(?:final|complete)\s+(?:answer|change|reply))"
    r"|^\W*superseded\b|\bsuperseded\b.*\b(?:re-?run|retry|redo|corrected|incorrect)\b",
    re.IGNORECASE | re.DOTALL)

_COUNT_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
_COUNT_NOUN = (r"(?:channels?|mics?|microphones?|inputs?|strips?|dis?|di\s+boxes|sources?|"
               r"players?|vocals?|singers?)")
_COUNT_ASK = re.compile(
    r"\b(?:add|adding|insert|new|put\s+in|patch)\s+(\d+|" + "|".join(_COUNT_WORDS) + r")\s+"
    r"(?:[\w-]+\s+){0,2}?" + _COUNT_NOUN + r"\b", re.IGNORECASE)
_ADD_WORD = re.compile(r"\b(?:add|adding|new|insert|create)\b", re.IGNORECASE)
_QUOTED = re.compile(r"[\"\u201c]([^\"\u201d]{1,%d})[\"\u201d](?!\s*preset)" % CHANGE_NAME_MAX)
_SIDE = re.compile(r"^(.*\S)[\s-]+[LR]$")


def _object_names(section: dict) -> set[str]:
    """The names of the objects a plan or an `add` section holds -- the only
    places a quoted name counts as written. A title, a note or an
    explanation that echoes it counts for nothing."""
    names = {_norm(c.get("name")) for c in section.get("channels") or [] if isinstance(c, dict)}
    for key in _NAMED_KINDS:
        group = section.get(key)
        if isinstance(group, dict):
            names |= {_norm(k) for k in group}
            names |= {_norm(v.get("name")) for v in group.values() if isinstance(v, dict)}
    return names - {""}


def changes_nothing(change_set: dict) -> bool:
    """A change set that adds, drops and edits nothing. An instruction typed
    to change the desk that compiles to this was not carried out: a model
    that judged it impossible (a send to a bus the desk does not have) and
    said so in `notes` instead of writing it for the code to refuse."""
    for section in ("add", "drop"):
        body = change_set.get(section)
        if isinstance(body, dict) and any(body.get(key) for key, _ in OBJECT_KINDS):
            return False
    return not change_set.get("modify")


def retraction_note(change_set: dict) -> str | None:
    """The first of the reply's notes that says the reply is not the answer."""
    for note in change_set.get("notes") or []:
        if isinstance(note, str) and _RETRACTION.search(note):
            return note
    return None


def reply_shortfall(change_text: str, base: dict, change_set: dict) -> str | None:
    """Why a parsed reply is not the whole change, or None. Two readings,
    both conservative -- this never invents an expectation: a note that
    retracts the reply, and fewer additions than the words name (quoted
    names, or a count the words state). A quoted name the reply writes
    anywhere, or that is already on the desk, is not missing, and an L/R
    pair merged into one stereo "Choir" counts as both. A quoted name longer
    than the console shows counts as written when its cut form is: the reply
    has already been read, and a strip's name cut to its sixteen characters
    (`_cut_cosmetic_names`, said at INFO)."""
    note = retraction_note(change_set)
    if note:
        return (f'the reply\'s own note says it is not the answer: "{note.strip()}". '
                "Return the complete change.")
    text = change_text or ""
    if not _ADD_WORD.search(text):
        return None
    channels = (change_set.get("add") or {}).get("channels") or []
    seen = _object_names(base) | _object_names(change_set.get("add") or {}) | {
        _norm(m.get(k)) for m in change_set.get("modify") or [] if isinstance(m, dict)
        for k in ("name",)} | {
        _norm((m.get("fields") or {}).get("name")) for m in change_set.get("modify") or []
        if isinstance(m, dict) and isinstance(m.get("fields"), dict)}
    missing = []
    quotes = list(dict.fromkeys(q.strip() for q in _QUOTED.findall(text)))
    for quoted in quotes:
        name = _norm(quoted)
        if not name or name in seen:
            continue
        if len(quoted) > facts.NAME_MAX_CHARS and _norm(
                quoted[:facts.NAME_MAX_CHARS].rstrip() or quoted[:facts.NAME_MAX_CHARS]) in seen:
            continue
        side = _SIDE.match(quoted)
        if side and any(_norm(c.get("name")) == _norm(side.group(1)) for c in channels):
            continue
        missing.append(quoted)
    if missing:
        return ("the change names " + ", ".join(f'"{m}"' for m in missing)
                + "; the reply does not add it. Return the complete change.")
    if quotes:      # names given: they decide, a count beside them may be a stereo pair
        return None
    counts = [_COUNT_WORDS[w] if w in _COUNT_WORDS else int(w)
              for w in (m.group(1).lower() for m in _COUNT_ASK.finditer(text))]
    wanted = sum(counts)
    width = sum(2 if _stereo_sockets(c) else 1 for c in channels)
    if wanted and len(channels) < wanted and width < wanted:
        return (f"the change asks for {wanted} channels; the reply adds {len(channels)}. "
                "Return the complete change.")
    return None


def compile_change(change_text: str, base: dict, *, provider, console_model: str,
                   conventions: str | None = None, conventions_name: str | None = None,
                   instructions: str | None = None, instructions_name: str | None = None,
                   constrain: bool = True, infos: list[str] | None = None) -> dict:
    """The typed change -> a change set, by one model call. Anything
    decided while reading the reply is appended to `infos`.

    A provider that says `repairs_replies` (the api provider) gets ONE more
    call when the reply fails the format: the same request, then the reply
    and the validator's message (`_repair_user`). Both calls are counted in
    the usage lines (the second is labelled `change-repair`), the second is
    said at INFO, and a second failure is the error."""
    system = change_system(console_model)
    user = change_user(base, change_text, conventions=conventions,
                       conventions_name=conventions_name, instructions=instructions,
                       instructions_name=instructions_name)
    schema = CHANGE_SET_SCHEMA if constrain else None
    raw = provider.complete(system=system, user=user, response_schema=schema, label="change")
    def shortfall(change_set: dict) -> str | None:
        return reply_shortfall(change_text, base, change_set)

    try:
        change_set = parse_change_set(raw, infos=infos)
        problem = shortfall(change_set)
        if problem is None:
            return change_set
        first = ChangeError(problem, partial_text=raw)
    except ChangeError as exc:
        first = exc
    if not getattr(provider, "repairs_replies", False):
        raise first
    return _repair(provider, system, user, schema, raw, str(first), infos, check=shortfall)


def repair_change_set(change_text: str, base: dict, change_set: dict, problem: str, *, provider,
                      console_model: str, conventions: str | None = None,
                      conventions_name: str | None = None, instructions: str | None = None,
                      instructions_name: str | None = None, constrain: bool = True,
                      infos: list[str] | None = None) -> dict:
    """A change set that parsed but that the desk REFUSED (`problem` says
    why: the review's blocked lines), compiled once more with that message
    in front of the model. Same bound and the same accounting as the repair
    in `compile_change`."""
    system = change_system(console_model)
    user = change_user(base, change_text, conventions=conventions,
                       conventions_name=conventions_name, instructions=instructions,
                       instructions_name=instructions_name)
    return _repair(provider, system, user, CHANGE_SET_SCHEMA if constrain else None,
                   generate.prompt_json(change_set), problem, infos)


def _repair(provider, system: str, user: str, schema, reply: str, problem: str,
            infos: list[str] | None, *, check=None) -> dict:
    first_line = problem.strip().splitlines()[0] if problem.strip() else "no reason given"
    raw = provider.complete(system=system, user=_repair_user(user, reply, problem),
                            response_schema=schema, label="change-repair")
    try:
        change_set = parse_change_set(raw, infos=infos)
        again = check(change_set) if check else None
        if again:
            raise ChangeError(again, partial_text=raw)
    except ChangeError as second:
        raise ChangeError(f"{second} (the first reply failed too -- {first_line} -- and was "
                          "sent back once with that message)", partial_text=second.partial_text) from second
    if infos is not None:
        infos.append(f"the first reply was not accepted ({first_line}); it was sent back once with "
                     "that message and the second reply is the one used -- both calls are in the "
                     "usage lines above, the second labeled 'change-repair'")
    return change_set


def load_change_set(path: str | Path, *,
                    infos: list[str] | None = None) -> tuple[dict, str | None]:
    """`(change set, the change text it was compiled from or None)` from a
    file `--save-change-set` wrote, or from a `--review-json` file, whose
    `change.change_set` is the same thing. Sections the file leaves out are
    read as empty and said in `infos`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("change"), dict) \
            and isinstance(payload["change"].get("change_set"), dict):
        payload = payload["change"]["change_set"]
    text = payload.get(TEXT_KEY) if isinstance(payload, dict) else None
    return (validate_change_set(payload, infos=infos),
            (text if isinstance(text, str) else None))


def saved_change_set(change_set: dict, text: str | None) -> dict:
    """The change set as it is saved and reviewed: the model's answer with
    the question beside it."""
    return {TEXT_KEY: text, **change_set}


# --------------------------------------------------------------------------
# The merge -- deterministic
# --------------------------------------------------------------------------


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


@dataclass
class MergeResult:
    """What the merge made of a change set: the merged plan (the "amended
    plan" the back half is handed), and every verdict it reached on its
    own -- refusals, what it did not write, and the choices it made."""

    plan: dict
    changes: list[Change] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: The named fields the change sets on objects already on the desk
    #: (`amend.FieldEdit`, slice 2) -- handed to the back half, which writes
    #: exactly the addresses they own.
    edits: list = field(default_factory=list)
    #: Source keys of the channels this change drops and adds again --
    #: "move Playback to Aux 8" is said that way, there being no other.
    moved: set = field(default_factory=set)
    #: An explicit insert's renumbering (`_plan_insert`): `{old strip label:
    #: new strip label}` for each running channel that moves down, and
    #: `{source key: strip label}` for each channel put in the room made.
    renumbered: dict = field(default_factory=dict)
    inserted: dict = field(default_factory=dict)
    #: Names of the busses the change drops and the desk returns to free, handed to `amend.plan_amendment`.
    freed_busses: list = field(default_factory=list)
    freed_indices: set = field(default_factory=set)
    #: `(plan key, name)` of the DCAs, mute groups and outputs the change
    #: drops and the desk returns to free, and the
    #: indices they held, per plan key.
    freed_objects: list = field(default_factory=list)
    freed_object_indices: dict = field(default_factory=dict)
    #: Source keys of the channels the change drops by name: an
    #: explicit drop is carried out even where the desk no longer reads the
    #: strip as the one the plan built (`amend.plan_amendment`).
    explicit_drops: set = field(default_factory=set)
    #: Channels the change put "after Snare" without saying insert, that
    #: went on a free strip instead: `[(name, position asked for, wording
    #: that would renumber)]`. `plan_patch` says where each landed.
    not_renumbered: list = field(default_factory=list)

    @property
    def refused(self) -> list[Change]:
        return [c for c in self.changes if c.kind is ChangeKind.REFUSED]


def _find_channel(channels: list[dict], name: str) -> dict | None:
    """A base channel by its strip name, or by the source it carries."""
    wanted = _norm(name)
    for channel in channels:
        if _norm(channel.get("name")) == wanted:
            return channel
    for channel in channels:
        if amend_engine._source_key(channel) == wanted:
            return channel
    return None


def _capacity(table: dict, model: str | None, default: int) -> int:
    return table.get(model) or default


def _free_index(taken: set[int], capacity: int) -> int | None:
    for index in range(1, capacity + 1):
        if index not in taken:
            return index
    return None


def _occupied_sockets(plan: dict, occupancy, *,
                      leaving: frozenset[str] = frozenset()) -> dict[tuple[str, int], str]:
    """Every input socket something already uses, mapped to what uses it:
    each channel of `plan`, and each strip the desk read found patched that
    is not FREE (a free strip on its factory patch claims nothing). The
    strips in `leaving` (labels, `ch:13`) are being vacated by a channel
    that moves, and claim nothing."""
    used: dict[tuple[str, int], str] = {}
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        patch = channel.get("patch") or {}
        for socket in patch.get("sockets") or []:
            if isinstance(patch.get("group"), str) and isinstance(socket, int):
                used.setdefault((patch["group"], socket),
                                f"channel {channel.get('name')!r}")
    for status in occupancy or ():
        if status.patch is not None and status.state is not amend_engine.StripState.FREE \
                and status.label not in leaving:
            used.setdefault(tuple(status.patch), f"{status.label} on the desk")
    return used


def _socket_limit(group: str, console_model: str | None, boxes: dict | None) -> int:
    """How many input sockets `group` has: the panel's, or -- on an AES50
    port with a stage box of a known size on it -- the box's."""
    try:
        limit = facts.input_socket_limit(group, console_model)
    except facts.UnknownConsoleModel:
        limit = facts.INPUT_SOCKETS.get(group, 0)
    if boxes and group in boxes:
        limit = min(limit, boxes[group][1])
    return limit


def _choose_sockets(group: str, count: int, used, console_model: str | None,
                    boxes: dict | None = None) -> list[int] | None:
    """The lowest free socket(s) in `group`: one, or an odd-started
    consecutive pair for a stereo channel (`facts.STEREO_PAIR_RULE`)."""
    limit = _socket_limit(group, console_model, boxes)
    step = 2 if count == 2 else 1
    for start in range(1, limit - count + 2, step):
        sockets = list(range(start, start + count))
        if all((group, s) not in used for s in sockets):
            return sockets
    return None


_NUMBER_LIST = r"\d+(?:\s*(?:,|and|&|/|\+|-|to)\s*\d+)*"


def _numbers_after(text: str, group: str) -> set[int]:
    """Every socket number `text` writes after `group` ("on A 5 and 6",
    "LCL 21-22", "A5/6"); a range of two is both ends and what lies between."""
    found: set[int] = set()
    for match in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(group)}\s*({_NUMBER_LIST})",
                             text, re.I):
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        found.update(numbers)
        if len(numbers) == 2 and re.search(r"-|to", match.group(1)) and numbers[0] < numbers[1]:
            found.update(range(numbers[0], numbers[1] + 1))
    return found


def _stated_by_text(patch: dict, sockets: list[int], missing: list[int],
                    text: str | None) -> bool:
    """Whether the engineer's words name these sockets. The model's `stated`
    flag is a claim; the words are the evidence, and which sockets are the
    engineer's and which are Atoo's to choose must not turn on a draw. A socket the words write after its group is named, whatever the
    flag says; a flag of true on a socket that does not exist, with no such
    number anywhere in the words, is the model's invention, not an instruction."""
    if text is None:
        return bool(patch.get("stated"))
    group = patch.get("group")
    if group and all(s in _numbers_after(text, group) for s in sockets):
        return True
    if patch.get("stated") and missing:
        written = {int(n) for n in re.findall(r"\d+", text)}
        return any(s in written for s in missing)
    return bool(patch.get("stated")) and not missing


def _settle_socket(channel: dict, used: dict, console_model: str | None,
                   infos: list[str], warnings: list[str], boxes: dict | None = None,
                   words: str | None = None) -> None:
    """Decision 5: a socket the change named is honoured; one it did not
    name is chosen, and the choice announces itself at INFO. Whether it was
    named is read from the change's words (`_stated_by_text`), not taken from
    the model's flag alone."""
    where = repr(channel.get("name"))
    patch = channel.get("patch") or {}
    group = patch.get("group")
    sockets = [s for s in patch.get("sockets") or [] if isinstance(s, int)]
    if not isinstance(group, str) or not sockets or group == "OFF":
        return
    text = f"{group} {'+'.join(str(s) for s in sockets)}"
    limit = _socket_limit(group, console_model, boxes)
    clash = [used[(group, s)] for s in sockets if (group, s) in used]
    missing = [s for s in sockets if s > limit]
    patch["stated"] = _stated_by_text(patch, sockets, missing, words)
    if patch["stated"]:
        if clash:
            warnings.append(
                f"channel {where}: the change names {text}, which {clash[0]} already uses -- "
                "honored as named (one socket can feed two strips on a WING), but check "
                "that is what was meant")
        else:
            infos.append(f"channel {where}: patched to {text}, the socket the change named")
        return
    if not clash and not missing:
        infos.append(
            f"channel {where}: the change named no socket, so {text} was chosen -- the first "
            "the model picked, and nothing on the desk uses it. Say the socket in the change "
            "to choose it yourself.")
        return
    chosen = _choose_sockets(group, len(sockets), used, console_model, boxes)
    if clash:
        why = f"{clash[0]} already uses it"
    elif boxes and group in boxes and missing[0] > boxes[group][1]:
        device, inputs, _outputs = boxes[group]
        why = f"the {device} on AES50-{group} has {inputs} inputs, so there is no {group} {missing[0]}"
    else:
        why = f"this console has no {group} {missing[0]}"
    what = "stereo pair" if len(sockets) == 2 else "socket"
    place = group
    if chosen is None and group != "LCL":
        # The box has no room; the desk's own local inputs are always there.
        chosen = _choose_sockets("LCL", len(sockets), used, console_model, boxes)
        place = "LCL"
    if chosen is None:
        warnings.append(
            f"channel {where}: the change named no socket, and {text} was picked -- but {why}, "
            f"and no free {what} is left on {group} or LCL to choose instead. Left as picked; "
            "name the socket in the change.")
        return
    patch["group"] = place
    patch["sockets"] = chosen
    new = f"{place} {'+'.join(str(s) for s in chosen)}"
    elsewhere = f" -- {group} has no free {what}, so on the desk's own inputs" \
        if place != group else ""
    infos.append(
        f"channel {where}: the change named no socket; {text} was picked, but {why}, so "
        f"{new} was chosen instead -- the first free {what} on {place}{elsewhere}. Say the "
        "socket in the change to choose it yourself.")


def _references(obj: dict) -> list[tuple[str, str]]:
    """`(plan key, name)` for every named object `obj` points at."""
    refs: list[tuple[str, str]] = []
    for name in obj.get("dca") or []:
        refs.append(("dcas", str(name)))
    for name in obj.get("mute_group") or []:
        refs.append(("mute_groups", str(name)))
    for send in obj.get("bus_sends") or []:
        if isinstance(send, dict) and send.get("bus") is not None:
            refs.append(("busses", str(send["bus"])))
    fed_by = obj.get("fed_by")
    if isinstance(fed_by, dict) and fed_by.get("type") == "bus" and fed_by.get("name"):
        refs.append(("busses", str(fed_by["name"])))
    return refs


_WORD = dict(OBJECT_KINDS)

# ----------------------------------------------------------------------
# Objects the plan does not know
# ----------------------------------------------------------------------

#: The console root of each kind of named object the desk holds a name for.
_DESK_ROOT = {"busses": "bus", "dcas": "dca", "mute_groups": "mgrp"}
#: An output is a Main or a Matrix: the roots its name is read under, and the
#: plan's `kind` for each.
_OUTPUT_ROOTS = {"main": "main", "mtx": "matrix"}
_OUTPUT_NUMBER = re.compile(r"^\s*(main|matrix|mtx)\s*(\d+)\s*$", re.IGNORECASE)
_DESK_CAPACITY = {"busses": "bus", "dcas": "dca", "mute_groups": "mgrp"}
_TAG_OF = {"dcas": "D", "mute_groups": "M"}


def unknown_names(base: dict, change_set: dict) -> dict[str, list[str]]:
    """The busses, DCAs, mute groups and outputs the change names (drops, edits,
    and the references of the channels it adds or edits) that the plan on the desk
    does not know: `{plan key: [names]}`. A desk Atoo did not set up holds
    them anyway; `adopt_desk_objects` reads what it holds."""
    wanted: dict[str, list[str]] = {}

    def want(key: str, name: object) -> None:
        if (key in _DESK_ROOT or key == "outputs") and name is not None \
                and str(name) not in (base.get(key) or {}):
            if str(name) not in wanted.setdefault(key, []):
                wanted[key].append(str(name))

    for key in (*_DESK_ROOT, "outputs"):
        for name in (change_set.get("drop") or {}).get(key) or []:
            want(key, name)
    for channel in (change_set.get("add") or {}).get("channels") or []:
        for key, name in _references(channel):
            want(key, name)
    for request in change_set.get("modify") or []:
        if not isinstance(request, dict):
            continue
        kind = _KEY_OF.get(str(request.get("object")))
        if kind in _DESK_ROOT or kind == "outputs":
            want(kind, request.get("name"))
        fields = request.get("fields")
        if isinstance(fields, dict):
            for key, name in _references(fields):
                want(key, name)
    return {key: names for key, names in wanted.items() if names}


def name_reads(base: dict, change_set: dict, known: dict) -> list[tuple[str, str]]:
    """The names to read first, as `(address, OSC type)`: every name of the
    kinds the change names an unknown object of, unless `known` has it."""
    reads: list[tuple[str, str]] = []
    for key in unknown_names(base, change_set):
        for root in ((_DESK_ROOT[key],) if key != "outputs" else tuple(_OUTPUT_ROOTS)):
            reads.extend((f"/{root}/{n}/name", "s") for n in range(1, facts.CAPACITY[root] + 1)
                         if f"/{root}/{n}/name" not in known)
    return reads


def member_reads(base: dict, change_set: dict, known: dict) -> list[tuple[str, str]]:
    """Then, once the names are in `known`: for an unknown bus the change drops,
    which strips send into it; for an unknown DCA or mute group it drops,
    every strip's tags; for an unknown Matrix it drops, which strips, busses
    and Mains send into it; for an unknown bus whose destination it edits,
    which Mains the bus is routed to; and for an unknown Main or Matrix it
    renumbers, every setting of it and every send or route into it. Only
    these objects, never a sweep."""
    reads: list[tuple[str, str]] = []
    dropped = change_set.get("drop") or {}
    strips = [(bank, n) for bank in ("ch", "aux") for n in range(1, facts.CAPACITY[bank] + 1)]
    for key, names in _found_on_desk(unknown_names(base, change_set), known).items():
        for name, index in names.items():
            if key == "busses" and _edits_destination(change_set, name):
                reads.extend(pair for pair in _bus_route_reads(index)
                             if pair[0] not in known and pair not in reads)
            if key == "outputs" and _output_renumber(change_set, name) is not None:
                seen = set(reads)
                for leaf in _output_move_leaves(_model_of(base), *index):
                    pair = (leaf.address, leaf.value_type)
                    if leaf.address not in known and pair not in seen:
                        reads.append(pair)
                        seen.add(pair)
            if name not in (dropped.get(key) or []):
                continue
            if key == "outputs":
                kind, index = index
                if kind != "matrix":
                    continue      # what feeds a Main is the strips' own routes
                senders = strips + [("bus", n) for n in range(1, facts.CAPACITY["bus"] + 1)] \
                    + [("main", n) for n in range(1, facts.CAPACITY["main"] + 1)]
                pairs = [(f"/{bank}/{n}/send/MX{index}/on", "i") for bank, n in senders]
            else:
                pairs = [(f"/{bank}/{n}/send/{index}/on", "i") if key == "busses"
                         else (f"/{bank}/{n}/tags", "s") for bank, n in strips]
            for pair in pairs:
                if pair[0] not in known and pair not in reads:
                    reads.append(pair)
    return reads


def _edits_destination(change_set: dict, name: str) -> bool:
    """Whether the change edits where bus `name` goes."""
    for request in change_set.get("modify") or []:
        if isinstance(request, dict) and _KEY_OF.get(str(request.get("object"))) == "busses" \
                and str(request.get("name")) == name \
                and any(str(path).split(".")[0] in ("destination", "destinations")
                        for path in request.get("fields") or {}):
            return True
    return False


def _bus_route_reads(index: int) -> list[tuple[str, str]]:
    """Which Mains a bus is routed to: what an edit of its destination needs,
    so a route it leaves is switched off as for a bus the plan built."""
    return [(f"/bus/{index}/main/{m}/on", "i") for m in range(1, facts.CAPACITY["main"] + 1)]


def _model_of(plan: dict) -> str | None:
    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    return meta.get("console_model")


def _output_renumber(change_set: dict, name: str) -> int | None:
    """The number the change gives output `name`, when it names one."""
    for request in change_set.get("modify") or []:
        if isinstance(request, dict) and _KEY_OF.get(str(request.get("object"))) == "outputs" \
                and str(request.get("name")) == name \
                and isinstance((request.get("fields") or {}).get("index"), int):
            return request["fields"]["index"]
    return None


def _without_index(change_set: dict, name: str) -> dict:
    """The change with output `name`'s renumber taken out, the request
    dropped when that was all it asked: `_renumber_adopted_output` did it."""
    change_set = copy.deepcopy(change_set)
    kept = []
    for request in change_set.get("modify") or []:
        if isinstance(request, dict) and _KEY_OF.get(str(request.get("object"))) == "outputs" \
                and str(request.get("name")) == name:
            request["fields"] = {k: v for k, v in (request.get("fields") or {}).items()
                                 if k != "index"}
            if not request["fields"]:
                continue
        kept.append(request)
    change_set["modify"] = kept
    return change_set


def _output_senders(kind: str, index: int) -> list[str]:
    """The prefixes of everything that feeds Main or Matrix `index`: every
    strip's, bus's and Main's send into a Matrix; every strip's and bus's
    route to a Main."""
    if kind == "matrix":
        return [f"/{bank}/{n}/send/MX{index}/" for bank in ("ch", "aux", "bus", "main")
                for n in range(1, facts.CAPACITY[bank] + 1)]
    return [f"/{bank}/{n}/main/{index}/" for bank in ("ch", "aux", "bus")
            for n in range(1, facts.CAPACITY[bank] + 1)]


def _output_move_leaves(model: str | None, kind: str, index: int) -> list:
    """Every leaf a renumber of an adopted Main or Matrix carries: the
    object's own, in the order a reset writes them, and every send or route
    into it. Scoped to that object, never a sweep."""
    from atoo import initialize
    root = "main" if kind == "main" else "mtx"
    leaves = list(initialize.freed_leaves(model, f"/{root}/{index}/"))
    for prefix in _output_senders(kind, index):
        leaves.extend(initialize.freed_leaves(model, prefix))
    return leaves


def _renumber_adopted_output(plan: dict, name: str, kind: str, old: int, new: int,
                             known: dict, model: str | None, vacating: set, infos: list,
                             landings: list, clears: list, changes: list,
                             follows: dict) -> bool:
    """Renumber a Main or Matrix the plan does not know
    from what the desk read: every setting of the object, and every send or
    route into it, written on the new number at the value read, and the old
    number returned to the initialized reading -- the move `_renumber` makes
    for an object the plan built, from the desk instead of the plan.

    False when the planned road should judge the number instead: out of
    range, the same number, or held by an output of the plan -- it refuses
    those saying why. A number the desk holds under a name the plan does not
    know is refused here, as somebody else's -- unless another object read off
    the desk is renumbered away from it by the same change (`vacating`, a
    swap). The writes on the new number are `landings`, those on the old one
    `clears`: the caller drops a clear where another renumber lands."""
    from atoo import initialize
    root = "main" if kind == "main" else "mtx"
    word = "Main" if kind == "main" else "Matrix"
    if not 1 <= new <= facts.CAPACITY[root] or new == old or any(
            isinstance(o, dict) and o.get("kind") == kind and o.get("index") == new
            and (kind, new) not in vacating
            for n, o in (plan.get("outputs") or {}).items() if n != name):
        return False
    held = known.get(f"/{root}/{new}/name")
    if isinstance(held, str) and held.strip() and (kind, new) not in vacating:
        changes.append(Change(
            ChangeKind.REFUSED, "output", repr(name),
            f"the change renumbers it to {word} {new}, which the desk holds as {held!r} -- not "
            "this plan's, so it is not written over; say what to do with it too, and both are "
            "carried out", asked_by="the change"))
        return True
    stage = {"name": apply_module.STAGE_NAMES, "fdr": apply_module.STAGE_FADER_MUTE,
             "mute": apply_module.STAGE_FADER_MUTE}
    feed_stage = apply_module.STAGE_SENDS if kind == "matrix" else apply_module.STAGE_ROUTING
    moved, unread, senders = 0, 0, []
    groups = [(f"/{root}/{old}/", f"/{root}/{new}/", None)] + [
        (prefix, target, " ".join(prefix.strip("/").split("/")[:2]))
        for prefix, target in zip(_output_senders(kind, old), _output_senders(kind, new))]
    for source, target, sender in groups:
        leaves = initialize.freed_leaves(model, source)
        values = {leaf.address: known.get(leaf.address) for leaf in leaves}
        if sender is not None:
            if values.get(f"{source}on") in (None, 0, "0", "OFF"):
                continue      # nothing feeds it from here
            senders.append(sender)
        of = f" of {sender}'s feed" if sender else ""
        for leaf in leaves:
            value = values[leaf.address]
            if value is None:
                unread += 1
                continue
            rel = leaf.address[len(source):]
            at = stage.get(rel, apply_module.STAGE_PROCESSING) if sender is None else feed_stage
            landings.append(apply_module.WriteTarget(
                target + rel, leaf.value_type,
                f"{word} {old} ({name!r}) renumbered to {word} {new}: {rel}{of}, as the desk "
                "held it", apply_module._const(value), at))
            moved += 1
            # The old number reads as an initialized one, and nothing feeds
            # it any more: a feed's switch goes off even where an initialized
            # desk has it on (every strip routed to Main 1).
            left = 0 if sender is not None and rel == "on" else leaf.value
            if value != left:
                clears.append(apply_module.WriteTarget(
                    leaf.address, leaf.value_type,
                    f"{word} {old} ({name!r}) renumbered: {rel}{of} on its old number -> "
                    + ("off" if left == 0 and rel == "on" else "as initialized"),
                    apply_module._const(left), at))
    plan["outputs"][name]["index"] = new
    # The plan's own records that name it by number follow it (the caller,
    # once for every renumber); their routes on the desk moved with the feed
    # above, so they are records only, not edits.
    follows.setdefault(kind, {})[old] = (new, name)
    fed = (f" and the feed into it from {', '.join(senders[:8])}"
           + (f" and {len(senders) - 8} more" if len(senders) > 8 else "")) if senders else ""
    changes.append(Change(
        ChangeKind.EDITED, "output", repr(name),
        f"renumbered ({word} {old} -> {new}) from what the desk read: every setting of "
        f"{word} {old}{fed} written on {word} {new}, and {word} {old} returned to the "
        "initialized reading", asked_by="the change"))
    infos.append(
        f"output {name!r}: renumbered from {word} {old} to {word} {new} from what the desk read "
        f"({moved} setting(s)); the output sockets it feeds were not read, so they still take "
        f"{word} {old} -- name them in the change to move them too. Undo puts it all back"
        + (f". {unread} setting(s) the desk did not answer for were not moved" if unread else ""))
    return True


def _adopted_bus(name: str, index: int, known: dict, change_set: dict, dropped: bool) -> tuple:
    """The entry for a bus the plan does not know, and the INFO it is said
    with. Where the change edits its destination, the Mains the desk routes it
    to are its destination, so the routes it leaves are switched off;
    otherwise its destination was not read and is null, and nothing of it is
    written but what the change names."""
    entry = {"index": index, "provenance": amend_engine.READ_FROM_DESK, "destination": None}
    note = ""
    if _edits_destination(change_set, name):
        mains = [m for m in range(1, facts.CAPACITY["main"] + 1)
                 if known.get(f"/bus/{index}/main/{m}/on") not in (None, 0, "0", "OFF")]
        if len(mains) == 1:
            entry["destination"] = {"type": "main", "index": mains[0]}
        elif mains:
            del entry["destination"]
            entry["destinations"] = [{"type": "main", "index": m} for m in mains]
        note = ("; the desk routes it to " + (", ".join(f"Main {m}" for m in mains)
                                              if mains else "no Main"))
    if not dropped:
        note += ("; nothing else of it was read, so only what the change names is written "
                 "and the rest of it stays as the desk has it")
    return entry, note


def _found_on_desk(unknown: dict[str, list[str]], known: dict) -> dict[str, dict[str, int]]:
    """`{plan key: {name asked for: desk index}}` for each unknown name the desk
    holds under that name (case aside; the lowest index when two hold it)."""
    found: dict[str, dict] = {}
    for key, names in unknown.items():
        if key == "outputs":
            for name in names:
                spot = _output_on_desk(name, known)
                if spot is not None:
                    found.setdefault(key, {})[name] = spot
            continue
        root = _DESK_ROOT[key]
        held = {n: known.get(f"/{root}/{n}/name") for n in range(1, facts.CAPACITY[root] + 1)}
        for name in names:
            index = next((n for n, held_name in held.items()
                          if isinstance(held_name, str) and held_name.strip().casefold()
                          == name.strip().casefold()), None)
            if index is not None:
                found.setdefault(key, {})[name] = index
    return found


def _output_on_desk(name: str, known: dict) -> tuple[str, int] | None:
    """`(kind, index)` of the Main or Matrix the desk holds under `name` (case
    aside), else of the one "Matrix 1" / "Main 2" names by its number, else
    None."""
    for root, kind in _OUTPUT_ROOTS.items():
        for n in range(1, facts.CAPACITY[root] + 1):
            held = known.get(f"/{root}/{n}/name")
            if isinstance(held, str) and held.strip() \
                    and held.strip().casefold() == name.strip().casefold():
                return kind, n
    match = _OUTPUT_NUMBER.match(name)
    if match:
        kind = "main" if match.group(1).lower() == "main" else "matrix"
        number = int(match.group(2))
        if 1 <= number <= facts.CAPACITY["main" if kind == "main" else "mtx"]:
            return kind, number
    return None


def adopt_desk_objects(base: dict, change_set: dict,
                       known: dict) -> tuple[dict, dict, list[str], list[str], list, list, set]:
    """The plan on the desk, with each bus, DCA, mute group or output the
    change names that the plan does not know but the desk holds put in as the
    desk has it (outputs by `_adopt_output`):
    `(plan, change_set, infos, warnings, writes, changes, read)`.

    The entry is the desk's index and nothing the desk was not asked: a bus
    the change drops then goes through the same road as one the plan built --
    returned to free from the model's capture -- and the strips of the plan
    that send into it, or belong to a DCA or mute group it drops, are given
    that membership so the change takes it away. A strip the plan does not
    hold that does the same has it taken away too, from what the desk read: its send into the bus switched off, or the group's
    tag taken out of its tags -- `writes`, which the review writes, journals
    and Undo restores, said at INFO. The plan gains no record of the strip.

    A Main or Matrix the change renumbers is moved here, from what the desk
    read (`_renumber_adopted_output`): its writes join `writes`, its verdict
    is in `changes`, the addresses it writes in `read` (the plan's own render
    of it is not written beside them), and `change_set` comes back without
    that renumber."""
    unknown = unknown_names(base, change_set)
    found = _found_on_desk(unknown, known)
    if not found:
        return base, change_set, [], [], [], [], set()
    plan = copy.deepcopy(base)
    infos: list[str] = []
    warnings: list[str] = []
    writes: list = []
    changes: list = []
    read: set = set()
    dropped = change_set.get("drop") or {}
    for key, names in found.items():
        word = _WORD[key]
        plan.setdefault(key, {})
        if key == "outputs":
            for name, (kind, index) in names.items():
                _adopt_output(plan, name, kind, index, known,
                              name in (dropped.get(key) or []), infos, writes)
            # Renumbers of objects read off the desk land before any clear:
            # two that swap numbers each write the other's old number, once.
            vacating = {spot for name, spot in names.items()
                        if _output_renumber(change_set, name) is not None}
            landings: list = []
            clears: list = []
            follows: dict = {}
            for name, (kind, index) in names.items():
                new = _output_renumber(change_set, name)
                if new is not None and _renumber_adopted_output(
                        plan, name, kind, index, new, known, _model_of(base), vacating,
                        infos, landings, clears, changes, follows):
                    change_set = _without_index(change_set, name)
            for key in ("channels", "busses", "outputs"):
                plan.setdefault(key, [] if key == "channels" else {})
            for kind, moves in follows.items():
                _follow_number(plan, kind, moves, infos)
            landed = {t.address for t in landings}
            writes.extend(landings + [t for t in clears if t.address not in landed])
            read.update(t.address for t in landings + clears)
            continue
        for name, index in names.items():
            note = ""
            if key == "busses":
                plan[key][name], note = _adopted_bus(name, index, known, change_set,
                                                     name in (dropped.get(key) or []))
            else:
                plan[key][name] = {"index": index, "provenance": amend_engine.READ_FROM_DESK}
            infos.append(
                f"{word} {name!r} is not in the plan on the desk, but the desk holds it as "
                f"{word} {index} ({known.get(f'/{_DESK_ROOT[key]}/{index}/name')!r}), so the "
                "change is carried out against that" + note)
            if name not in (dropped.get(key) or []):
                continue
            by_slot = {(str(c.get("bank", "ch")), c.get("channel")): c
                       for c in plan.get("channels") or [] if isinstance(c, dict)}
            unrecorded = []
            for bank in ("ch", "aux"):
                for n in range(1, facts.CAPACITY[bank] + 1):
                    if key == "busses":
                        on = known.get(f"/{bank}/{n}/send/{index}/on")
                        held = bool(on) and on not in (0, "0", "OFF")
                    else:
                        tags = str(known.get(f"/{bank}/{n}/tags") or "")
                        held = f"#{_TAG_OF[key]}{index}" in [t.strip() for t in tags.split(",")]
                    if not held:
                        continue
                    channel = by_slot.get((bank, n))
                    if channel is None:
                        unrecorded.append(f"{bank} {n}")
                        writes.append(_unrecorded_write(key, name, index, bank, n))
                    elif key == "busses":
                        channel.setdefault("bus_sends", []).append(
                            {"bus": name, "mode": None, "level_db": None})
                    else:
                        field_name = "dca" if key == "dcas" else "mute_group"
                        channel.setdefault(field_name, []).append(name)
            if unrecorded:
                infos.append(
                    f"{word} {name!r}: "
                    + ("a send into it" if key == "busses" else "membership of it")
                    + f" on {', '.join(unrecorded[:8])}"
                    + (f" and {len(unrecorded) - 8} more" if len(unrecorded) > 8 else "")
                    + (", a strip" if len(unrecorded) == 1 else ", strips")
                    + " the plan has no record of, is "
                    + ("switched off" if key == "busses" else "taken off")
                    + " there too, from what the desk read; Undo puts it back")
    return plan, change_set, infos, warnings, writes, changes, read


def _adopt_output(plan: dict, name: str, kind: str, index: int, known: dict, dropped: bool,
                  infos: list, writes: list) -> None:
    """A Main or Matrix the plan does not know, put in as the desk holds it. Its sockets are not read: they stay patched as the
    desk has them, said at INFO. For a Matrix the change drops, every send into
    it the desk read is switched off -- a write, whether or not the plan holds
    the strip, bus or Main it comes from, since the plan has no record of the
    send -- reviewed, journalled and undone with the rest of the change."""
    root = "main" if kind == "main" else "mtx"
    word = "Main" if kind == "main" else "Matrix"
    held = known.get(f"/{root}/{index}/name")
    plan["outputs"][name] = {"kind": kind, "index": index, "socket": None,
                             "provenance": amend_engine.READ_FROM_DESK}
    infos.append(f"output {name!r} is not in the plan on the desk, but the desk holds it as "
                 f"{word} {index}" + (f" ({held!r})" if isinstance(held, str) and held else "")
                 + ", so the change is carried out against that; the output sockets it feeds "
                 "are not in the plan, and are left patched as the desk has them")
    if not dropped:
        return
    if kind == "main":
        infos.append(f"output {name!r}: the strips and busses routed to Main {index} keep "
                     "their routes as the desk has them; the Main itself reads as an "
                     "initialized one")
        return
    owned = {("ch" if str(c.get("bank", "ch")) == "ch" else "aux", c.get("channel"))
             for c in plan.get("channels") or [] if isinstance(c, dict)}
    owned |= {("bus", e.get("index")) for e in (plan.get("busses") or {}).values()
              if isinstance(e, dict)}
    owned |= {("main", e.get("index")) for e in (plan.get("outputs") or {}).values()
              if isinstance(e, dict) and e.get("kind") == "main"}
    sent: list[str] = []
    unrecorded: list[str] = []
    senders = [(b, n) for b in ("ch", "aux") for n in range(1, facts.CAPACITY[b] + 1)] \
        + [("bus", n) for n in range(1, facts.CAPACITY["bus"] + 1)] \
        + [("main", n) for n in range(1, facts.CAPACITY["main"] + 1)]
    for bank, n in senders:
        on = known.get(f"/{bank}/{n}/send/MX{index}/on")
        if not on or on in (0, "0", "OFF"):
            continue
        mine = (bank, n) in owned
        (sent if mine else unrecorded).append(f"{bank} {n}")
        writes.append(apply_module.WriteTarget(
            f"/{bank}/{n}/send/MX{index}/on", "i",
            f"{bank} {n}" + ("" if mine else " (not in the plan)")
            + f": no longer sends to Matrix {index} ({name!r}), dropped by the change",
            apply_module._const(0), apply_module.STAGE_SENDS))

    def listed(where: list[str]) -> str:
        return ", ".join(where[:8]) + (f" and {len(where) - 8} more" if len(where) > 8 else "")

    if sent:
        infos.append(f"output {name!r}: the send into it on {listed(sent)}, which the desk "
                     "reads as on, is switched off, from what the desk read; Undo puts it back")
    if unrecorded:
        infos.append(f"output {name!r}: a send into it on {listed(unrecorded)}"
                     + (", a strip" if len(unrecorded) == 1 else ", strips")
                     + " the plan has no record of, is switched off there too, from what the "
                     "desk read; Undo puts it back")


def _unrecorded_write(key: str, name: str, index: int, bank: str, n: int):
    """The write that takes a dropped bus, DCA or mute group off a strip the
    plan has no record of: its send switched off, or the group's token taken
    out of its tags, leaving every other token where it is."""
    base = f"/{bank}/{n}"
    word = _WORD[key]
    if key == "busses":
        return apply_module.WriteTarget(
            f"{base}/send/{index}/on", "i",
            f"{bank} {n} (not in the plan): no longer sends to {word} {index} ({name!r}), "
            "dropped by the change", apply_module._const(0), apply_module.STAGE_SENDS)
    dcas, mutes = ([index], []) if key == "dcas" else ([], [index])
    return apply_module.WriteTarget(
        f"{base}/tags", "s",
        f"{bank} {n} (not in the plan): taken out of {word} {index} ({name!r}), dropped by "
        "the change", lambda current, d=dcas, m=mutes: apply_module._released_tags(current, d, m),
        apply_module.STAGE_TAGS)


def _restated(what: str) -> str:
    return (f"{what} -- not written: it restates something already running on the desk "
            "whole, and a running object is changed only through the change set's `modify`, "
            "naming each field it sets -- so nothing it did not name can move")


#: Why a change cannot switch one side of a stereo channel's 48V alone.
PAIR_PHANTOM_TOGETHER = (
    "a stereo channel's two sockets switch 48V together -- the desk does not take one "
    "side on its own; set source.phantom, which switches both")


def _stereo_sockets(channel: dict) -> bool:
    """A stereo channel patched to its two sockets."""
    source = channel.get("source") or {}
    return bool(source.get("stereo")) and len((channel.get("patch") or {}).get("sockets") or []) == 2


def _pair_phantom_problems(original: dict, edited: dict, paths: list[str], infos: list,
                           name: str) -> list[str]:
    """A stereo channel's 48V is switched on both sockets or not at all.

    `source.phantom` is the pair's. When a change sets it and the plan states
    a different value for the second socket (`source.pair_phantom`), that is
    set to match, as an edit of its own, and said at INFO, so both sockets
    are written and the review marks both. Switching the second socket
    alone, or leaving the two different, is not something the desk allows:
    it is refused, naming the field to set. A mono channel, or a stereo one
    the change does not touch the 48V of, is not looked at, so a pair built
    with one condenser and one dynamic stays as built."""
    if not _stereo_sockets(edited):
        return []
    before, after = original.get("source") or {}, edited["source"]
    second_moved = before.get("pair_phantom") != after.get("pair_phantom")
    first_moved = bool(before.get("phantom")) != bool(after.get("phantom"))
    named_first = "source.phantom" in paths
    if second_moved and not (first_moved or named_first):
        return [PAIR_PHANTOM_TOGETHER]
    if second_moved:
        sides = [on for _socket, on in inferred.stated_socket_phantom(edited)]
        if sides[0] != sides[1]:
            return [PAIR_PHANTOM_TOGETHER]
        return []
    if (first_moved or named_first) and isinstance(before.get("pair_phantom"), bool) \
            and before["pair_phantom"] != bool(after.get("phantom")):
        after["pair_phantom"] = bool(after.get("phantom"))
        paths.append("source.pair_phantom")
        infos.append(
            f"channel {name!r}: 48V on a stereo channel switches both sockets together, so "
            f"source.pair_phantom is set to {str(after['pair_phantom']).lower()} to match "
            "source.phantom")
    return []


def _take_out_of(merged: dict, result: MergeResult, path: str, keep) -> None:
    """Take what a dropped object was to every running channel and bus out of
    their `path` field: `keep(old list)` is what is left. Each owner that
    changes gets ONE edit of that field -- from what the desk has to what is
    left, even where two dropped objects were in it -- which the back half
    writes as the thing switched off."""
    for key in ("channels", "busses"):
        owners = merged["channels"] if key == "channels" else [
            n for n, e in merged["busses"].items() if isinstance(e, dict)]
        for owner in owners:
            obj = owner if key == "channels" else merged["busses"][owner]
            old = obj.get(path) or []
            kept = keep(old)
            if len(kept) == len(old):
                continue
            edited = copy.deepcopy(obj)
            edited[path] = kept
            if key == "channels":
                merged["channels"] = [edited if c is obj else c for c in merged["channels"]]
                who, slot = str(obj.get("name")), f"{obj.get('bank', 'ch')}:{obj.get('channel')}"
            else:
                merged["busses"][owner] = edited
                who, slot = str(owner), None
            prior = next((i for i, e in enumerate(result.edits)
                          if (e.key, e.name, e.path) == (key, who, path)), None)
            was = old if prior is None else result.edits[prior].old
            edit = amend_engine.FieldEdit(key=key, name=who, path=path, old=was,
                                          new=kept, slot=slot)
            if prior is None:
                result.edits.append(edit)
            else:
                result.edits[prior] = edit


def _drop_bus(merged: dict, name: str, result: MergeResult) -> None:
    """A change that drops a bus returns it to free: the bus is
    taken out of the merged plan, so the back half reads it as freed
    (`amend.plan_amendment`'s `freed_busses`), and what pointed at it goes
    with it -- every running channel's send into it is taken out of that
    channel's `bus_sends` as an edit, which the back half writes as the send
    switched off, and a matrix it fed no longer names it. The engineer said
    "clear bus 5"; nothing here is a reason to refuse."""
    index = (merged["busses"][name] or {}).get("index")
    del merged["busses"][name]
    result.freed_busses.append(name)
    if isinstance(index, int):
        result.freed_indices.add(index)
    _take_out_of(merged, result, "bus_sends", lambda sends: [
        x for x in sends if not (isinstance(x, dict) and x.get("bus") == name)])
    for out_name, out in merged["outputs"].items():
        fed = out.get("fed_by") if isinstance(out, dict) else None
        if isinstance(fed, dict) and fed.get("type") == "bus" and fed.get("name") == name:
            out["fed_by"] = None
            result.infos.append(
                f"output {out_name!r} was fed by bus {name!r}; the bus's send to it is cleared "
                "with the bus, so the matrix now has no source named -- feed it from something "
                "else in a later change")
    result.infos.append(
        f"the change drops bus {name!r}"
        + (f" (bus {index})" if index else "")
        + ": carried out -- the bus is returned to free, and every channel's send into it is "
        "switched off")


def _drop_group(merged: dict, key: str, name: str, result: MergeResult) -> None:
    """A change that drops a DCA or a mute group returns it to free: taken out of the merged plan, so the back half
    reads it as freed, and every running channel and bus that was a member
    has it taken out of its `dca` / `mute_group` list as an edit, which the
    back half writes as that strip's tags rebuilt without it."""
    word, field_name = _WORD[key], ("dca" if key == "dcas" else "mute_group")
    index = (merged[key][name] or {}).get("index")
    del merged[key][name]
    result.freed_objects.append((key, name))
    if isinstance(index, int):
        result.freed_object_indices.setdefault(key, set()).add(index)
    members = [str(c.get("name")) for c in merged["channels"] if name in (c.get(field_name) or [])]
    _take_out_of(merged, result, field_name, lambda names: [n for n in names if n != name])
    result.infos.append(
        f"the change drops {word} {name!r}" + (f" ({word} {index})" if index else "")
        + ": carried out -- it is returned to free"
        + (f", and {', '.join(members)} no longer belong" if members else "")
        + (" to it" if members else ""))


def _drop_output(merged: dict, name: str, result: MergeResult) -> None:
    """A change that drops an output returns it to free: the
    Main or Matrix behind it and the socket it fed read as initialized."""
    out = merged["outputs"][name] or {}
    kind, index = out.get("kind"), out.get("index")
    del merged["outputs"][name]
    result.freed_objects.append(("outputs", name))
    still_fed = [n for n, o in merged["outputs"].items() if isinstance(o, dict)
                 and isinstance(o.get("fed_by"), dict) and o["fed_by"].get("type") == kind
                 and o["fed_by"].get("index") == index and kind == "main"]
    result.infos.append(
        f"the change drops output {name!r}"
        + (f" ({kind} {index})" if kind and index else "")
        + ": carried out -- the output is returned to free and "
        + ("its sockets stay patched as the desk has them" if out.get("provenance") == amend_engine.READ_FROM_DESK
           else "its socket reads as an initialized desk's")
        + (f"; {', '.join(map(repr, still_fed))} is fed from that Main and keeps its own settings"
           if still_fed else ""))


#: Why a change cannot set the values a preset was expanded into.
PRESET_RECORD = ("the preset's expanded values are the build's own record, not a setting -- "
                 "set the processing field itself (processing.hpf_hz, processing.gain_db, ...)")

#: Why a change cannot set the record of where a source came from.
SOURCE_RECORD = ("which sentence asked for the strip, and on what condition, is the build's "
                 "own record, not a setting")

#: Fields a change may NOT set on a running object, and why. Everything
#: else the object's own schema carries may be set, when named. A key names
#: a field and everything under it.
_FROZEN_FIELDS = {
    "channels": {
        # Which input-list row a running strip takes (`source.input`,
        # `source.pair_input`) is set like any field;
        # where the build recorded the row from is not.
        "source.from": SOURCE_RECORD,
        "source.quote": SOURCE_RECORD,
        "source.condition": SOURCE_RECORD,
        "processing.preset_values": PRESET_RECORD,
        "provenance": "provenance is the build's own record, not a setting",
        "inferred": "the inferred marks are the build's own record, not a setting",
    },
    "busses": {"preset_values": PRESET_RECORD,
               "provenance": "provenance is the build's own record, not a setting",
               "inferred": "the inferred marks are the build's own record, not a setting"},
    "outputs": {"provenance": "provenance is the build's own record, not a setting",
                "inferred": "the inferred marks are the build's own record, not a setting"},
}

#: What a running object is checked against once a change has edited it: the
#: shape a PLAN holds, not the shape a model is asked for. A running channel
#: or bus carries what the build wrote into it -- an expanded preset's
#: values (`preset_values`) -- which the model's shape leaves out, so
#: checking the edited entry against that shape refuses every edit to
#: a show built with a preset.
_OBJECT_SCHEMAS = {"channels": plan_schema.PLAN_CHANNEL_SCHEMA,
                   "busses": plan_schema.PLAN_BUS_SCHEMA,
                   "dcas": plan_schema.DCA_SCHEMA,
                   # A mute group is a name and its number: the number is all
                   # a change can set on it.
                   "mute_groups": {"type": "object", "properties": {
                       "index": {"type": "integer", "minimum": 1}}},
                   "outputs": plan_schema.PLAN_OUTPUT_SCHEMA}

#: Where a running object names its preset, per kind of object.
_PRESET_NAME_PATH = {"channels": "processing.preset", "busses": "preset"}


def _preset_record(key: str, obj: dict) -> dict | None:
    """The preset values the build expanded into a running channel or bus
    (`preset_values`), or `None` for an object that carries none."""
    record = (obj.get("processing") or {}).get("preset_values") if key == "channels" \
        else obj.get("preset_values") if key == "busses" else None
    return record if isinstance(record, dict) else None


def _switch_channel_preset(edited: dict, new, presets, name, word: str, slot,
                           changes: list, infos: list, warnings: list):
    """Expand `new` over a running channel's `edited` copy, in place, and
    return the new `preset_values` (None for a channel left with no preset),
    or False with a REFUSED/MODIFIED change appended when it cannot be done:
    the preset is not in the library, or there is no library to read."""
    from atoo import preset_expand
    old_values = copy.deepcopy(edited["processing"].get("preset_values"))
    edited["processing"]["preset"] = new
    if not new:
        edited["processing"].pop("preset_values", None)
        infos.append(f"{word} {name!r}: the preset is taken off -- what the old preset set "
                     "goes back to what an initialized strip reads")
        return None
    if presets is None:
        changes.append(Change(
            ChangeKind.MODIFIED, word, repr(name),
            f"processing.preset -> {new!r} -- not written: no preset library is loaded to "
            "read the preset's values from", slot=slot))
        return False
    for finding in preset_expand.expand_channel(edited, presets):
        (infos if finding.severity == "info" else warnings).append(finding.message)
    values = preset_expand.preset_values(edited)
    if values is None:
        changes.append(Change(
            ChangeKind.REFUSED, word, repr(name),
            f"the change gives it the preset {new!r}, and the preset library has no preset of "
            "that name -- there are no values to write", slot=slot))
        return False
    infos.append(
        f"{word} {name!r}: the preset {values['preset']!r} ({values['file']}) replaces the "
        f"old one's {len(values['leaves'])} processing values; what the old preset set and "
        "this one does not goes back to what an initialized strip reads, and fields the "
        "plan states itself stay as the plan states them" + _moved_leaves(old_values, values))
    return values


def _moved_leaves(old: dict | None, new: dict | None) -> str:
    """"; the leaves that move: eq/1g, dyn/thr and 4 more" -- the preset
    leaves whose value the switch changes, set or taken away."""
    before = (old or {}).get("leaves") or {}
    after = (new or {}).get("leaves") or {}
    moved = [leaf for leaf in dict.fromkeys([*before, *after])
             if before.get(leaf, _UNSET) != after.get(leaf, _UNSET)]
    if not moved:
        return "; no preset leaf changes value"
    shown = ", ".join(moved[:8]) + (f" and {len(moved) - 8} more" if len(moved) > 8 else "")
    return f"; the leaves that move: {shown}"


_UNSET = object()


def _switch_bus_preset(merged: dict, edited: dict, new, presets, name, word: str, slot,
                       changes: list, infos: list, warnings: list):
    """Expand `new` over a running bus's `edited` copy, in place, and give
    its effects FX engines the rest of the desk leaves free: the new
    `preset_values` (None for a bus left with no preset), or False with a
    REFUSED/MODIFIED change appended when it cannot be done -- no library to
    read, a preset the library does not have, or an effect no free engine can
    hold."""
    from atoo import bus_presets, fx_engines
    from atoo.presets import INSERT_POINT_NAMES

    old_values = copy.deepcopy(bus_presets.preset_values(edited))
    edited[bus_presets.PRESET_KEY] = new
    if not new:
        edited.pop(bus_presets.VALUES_KEY, None)
        infos.append(f"{word} {name!r}: the preset is taken off -- what the old preset set "
                     "goes back to what an initialized strip reads, and its effect comes off "
                     "the insert; the FX engine keeps the model, inserted nowhere")
        return None
    if presets is None:
        changes.append(Change(
            ChangeKind.MODIFIED, word, repr(name),
            f"preset -> {new!r} -- not written: no preset library is loaded to read the "
            "preset's values from", slot=slot))
        return False
    findings = bus_presets.expand_bus(name, edited, presets)
    values = bus_presets.preset_values(edited)
    if values is None:
        changes.append(Change(
            ChangeKind.REFUSED, word, repr(name),
            f"the change gives it the bus preset {new!r}, and the preset library has no bus "
            "preset of that name -- there are no values to write", slot=slot))
        return False
    # Engines every other strip inserts stay theirs; so do this bus's own
    # inserts (a capture's, or the bus sheet's fx cell) at the points they hold.
    view = {**merged, "busses": {**(merged.get("busses") or {}), name: edited}}
    taken = bus_presets.claimed_engines(view, skip={name})
    for ins in bus_presets.own_inserts(edited):
        if isinstance(ins.get("engine"), int) and ins.get("model") is not None:
            taken.setdefault(ins["engine"], bus_presets.insert_owner(name, edited,
                                                                     ins.get("point")))
    findings.extend(bus_presets.allocate_engines(view, only={name}, taken=taken))
    for ins in bus_presets.inserts(edited):
        model = ins.get("model")
        if fx_engines.is_known_model(model) and ins.get("engine") is None:
            legal = fx_engines.engines_for(model)
            changes.append(Change(
                ChangeKind.REFUSED, word, repr(name),
                f"the bus preset {new!r} inserts {model} on its "
                f"{INSERT_POINT_NAMES.get(ins.get('point'), ins.get('point'))}, and every FX "
                f"engine that can hold it (FX{fx_engines.engine_range_text(legal)}) is already "
                "in use on the desk", slot=slot))
            return False
    for finding in findings:
        (infos if finding.severity == "info" else warnings).append(finding.message)
    effects = "".join(f"; its {ins['model']} goes into FX{ins['engine']}"
                      for ins in bus_presets.inserts(edited) if ins.get("engine"))
    infos.append(
        f"{word} {name!r}: the bus preset {values['preset']!r} ({values['file']}) replaces the "
        f"old one's processing values and effects{effects}; what the old preset set and this "
        "one does not goes back to what an initialized strip reads"
        + _moved_leaves(old_values, values))
    for ins in bus_presets.inserts(edited):
        if ins.get("engine"):
            infos.append(f"{word} {name!r}: FX{ins['engine']} was judged free from the plan on "
                         "the desk alone -- the occupancy read covers strips, not FX engines")
    return values


def _settle_stereo(original: dict, edited: dict, used: dict, console_model: str | None,
                   boxes: dict | None, infos: list, name) -> str | None:
    """Mono to stereo and back. Returns the reason it cannot be
    done, or None with `edited`'s patch settled and the choice said at INFO.

    A stereo channel takes two consecutive sockets starting on an odd one
    (`facts.STEREO_PAIR_RULE`): a mono channel on an odd socket takes the next
    one, if nothing else uses it; one on an even socket has no pair to form,
    and a second socket another channel uses is not the engineer's to take.
    A change that also names the two sockets is held to the same rule. Stereo
    to mono keeps the first socket; the second is left as the desk has it."""
    was, now = bool((original.get("source") or {}).get("stereo")), \
        bool((edited.get("source") or {}).get("stereo"))
    if was == now:
        return None
    patch = edited.setdefault("patch", {}) if isinstance(edited.get("patch"), dict) else {}
    group = patch.get("group")
    sockets = [s for s in patch.get("sockets") or [] if isinstance(s, int)]
    if not isinstance(group, str) or group == "OFF" or not sockets:
        return ("it has no input socket to make a pair of or to take one from; give the "
                "socket(s) in the same change")
    if not now:
        if len(sockets) == 2:
            patch["sockets"] = sockets[:1]
            infos.append(f"channel {name!r}: made mono on {group} {sockets[0]}; {group} "
                         f"{sockets[1]}, its other half, is left exactly as the desk has it")
        # The second row of the pair is no longer this channel's: it stays on the input
        # list, unused, and a change is not called to account for a row the plan does not
        # use (`verify_plan.rows_for_a_change`). Leaving `pair_input` would hold the
        # engineer to a row they just said to leave alone.
        source = edited.get("source")
        if isinstance(source, dict) and source.get("pair_input"):
            infos.append(f"channel {name!r}: its second input-list row {source['pair_input']!r} "
                         "is no longer on any channel; it stays on the list, unused")
            source.pop("pair_input", None)
            source.pop("pair_phantom", None)
        return None
    if len(sockets) == 2:
        problem = facts.stereo_pair_problem(sockets)
        return (f"{group} {sockets[0]}+{sockets[1]} cannot be a stereo pair: {problem}"
                if problem else None)
    first = sockets[0]
    if first % 2 == 0:
        return (f"it is on {group} {first}, and a stereo pair on a WING starts on an odd "
                f"socket (a pair is {group} {first - 1}+{first}), so this cable cannot become "
                "one half of a pair where it is -- name the odd pair to patch it to")
    limit = _socket_limit(group, console_model, boxes)
    if first + 1 > limit:
        return f"there is no {group} {first + 1} to be its other half on this console"
    taken = used.get((group, first + 1))
    if taken:
        return (f"{group} {first + 1}, the other half of the pair, is used by {taken} -- "
                "a stereo pair cannot be formed without it; name a free odd pair to patch to")
    patch["sockets"] = [first, first + 1]
    infos.append(f"channel {name!r}: made stereo on {group} {first}+{first + 1} -- the socket "
                 f"after the one it is on, which nothing uses (a stereo pair starts on an odd "
                 "socket). Say the pair in the change to choose it yourself.")
    return None


def _frozen_reason(frozen: dict, path: str) -> str | None:
    """Why `path` is not something a change sets, when it or a field above
    it is in `frozen` (a key names a field and everything under it)."""
    parts = path.split(".")
    return next((frozen[prefix] for prefix in (".".join(parts[:n]) for n in range(1, len(parts) + 1))
                 if prefix in frozen), None)


def _ribbon_with_phantom(source: dict) -> str | None:
    """The microphone model, when a source has 48V on and the model is a
    passive ribbon: 48V destroys the element, and switching it off again
    does not undo that."""
    model = verify_plan._norm(source.get("model") or "")
    if source.get("phantom") and model and any(r in model for r in PASSIVE_RIBBON_MODELS):
        return str(source["model"])
    return None


_KEY_OF = {word: key for key, word in OBJECT_KINDS}

#: "fader" / "faders" -- a change names the fader when it says so. A send
#: level ("MON3 at -10") is a send, not the fader.
_FADER_WORDS = re.compile(r"\bfaders?\b", re.IGNORECASE)
#: "mute", "unmute", "muted" -- but not "mute group", which is a membership.
_MUTE_WORDS = re.compile(r"\b(?:un)?mut(?:e|es|ed|ing)\b(?!\s+groups?\b)", re.IGNORECASE)

_SLOT_REF = re.compile(r"^\s*(ch|channel|aux)\s*[:# ]?\s*(\d+)\s*$", re.IGNORECASE)

_ABSENT = object()


#: The fields whose objects are walked to their leaves, so the review says
#: `processing.hpf_hz 120 -> 100` and not the whole processing block twice.
#: Everything else is one value: a patch's group and sockets are one
#: socket, and changed apart they would name a socket nobody asked for.
_WALKED = frozenset({"processing", "fader", "source"})


def _leaves(path: str, old, new) -> list[tuple[str, object, object]]:
    """`(dotted path, old, new)` for every leaf that differs under `path`.
    Objects under `_WALKED` fields are walked; anything else, lists
    included, is one leaf (its whole value)."""
    if path.split(".")[0] in _WALKED and isinstance(new, dict) \
            and (isinstance(old, dict) or old is None or old is _ABSENT):
        old_d = old if isinstance(old, dict) else {}
        out: list[tuple[str, object, object]] = []
        for key in list(old_d) + [k for k in new if k not in old_d]:
            out.extend(_leaves(f"{path}.{key}", old_d.get(key, _ABSENT), new.get(key, _ABSENT)))
        return out
    before = None if old is _ABSENT else old
    after = None if new is _ABSENT else new
    return [] if before == after else [(path, before, after)]


def _find_object(merged: dict, key: str, ref: str, on_desk: dict):
    """`(object or name, slot label or None)` for a modify entry's
    reference, or `(None, None)`. A channel by its strip ("ch 5", "ch:5"),
    its name, or the source it carries; anything else by its name. Only
    what is ON THE DESK (`on_desk`: the base's channel ids and names per
    key) -- something this same change adds is set in its `add` entry."""
    if key == "channels":
        channels = [c for c in merged["channels"] if id(c) in on_desk["channels"]]
        match = _SLOT_REF.match(ref)
        if match:
            bank = "aux" if match.group(1).lower() == "aux" else "ch"
            number = int(match.group(2))
            channel = next((c for c in channels if isinstance(c, dict)
                            and str(c.get("bank", "ch")) == bank and c.get("channel") == number),
                           None)
        else:
            channel = _find_channel(channels, ref)
        if channel is None or channel.get("channel") is None:
            return None, None
        return channel, f"{channel.get('bank', 'ch')}:{channel.get('channel')}"
    table = {name: v for name, v in (merged.get(key) or {}).items() if name in on_desk[key]}
    if ref in table:
        return ref, None
    wanted = _norm(ref)
    for name in table:
        if _norm(name) == wanted:
            return name, None
    return None, None


def _edit_added(merged: dict, key: str, ref: str, fields: dict, on_desk: dict, word: str,
                asked: str, changes: list, infos: list) -> bool:
    """An edit of something this same change adds ("insert HiHat after Snare,
    HPF 200 on it"): set on the new entry, which is
    written whole as it is added. True when it was found and dealt with --
    set, or refused for a field it cannot carry -- False when the change adds
    nothing of that name either."""
    if key == "channels":
        entry = _find_channel([c for c in merged["channels"] if id(c) not in on_desk["channels"]],
                              ref)
        name = str(entry.get("name")) if entry is not None else ref
    else:
        added = {n: e for n, e in (merged.get(key) or {}).items() if n not in on_desk[key]}
        name = next((n for n in added if _norm(n) == _norm(ref)), None)
        entry = added.get(name) if name is not None else None
    if not isinstance(entry, dict):
        return False
    edited = copy.deepcopy(entry)
    frozen = _FROZEN_FIELDS.get(key, {})
    problems = []
    for path, value in fields.items():
        path = str(path).strip()
        why = _frozen_reason(frozen, path)
        if why:
            problems.append(f"its {path} is not something a change sets: {why}")
            continue
        amend_engine.set_path(edited, path, value)
    problems = problems or validate_schema(edited, _OBJECT_SCHEMAS[key], path=f"{word} {name!r}")
    if problems:
        changes.append(Change(
            ChangeKind.REFUSED, word, repr(name),
            f"the change adds it and edits it ({asked}), and {'; '.join(problems[:4])}"))
        return True
    entry.clear()
    entry.update(edited)
    infos.append(f"{word} {name!r} is added by this change; {asked or 'the edit'} "
                 f"({', '.join(map(str, fields))}) is set on it and written with it")
    return True


def _renumber(merged: dict, key: str, name: str, original: dict, edited: dict,
              paths: list[str], renumbering: set[str], model: str | None,
              infos: list) -> str | None:
    """A running bus, DCA, mute group or output given a new number, or an
    output made a Main or a Matrix: the number checked,
    and for a new kind with no number named, the lowest free one of that kind
    chosen and said. Returns why it cannot be done -- a number past the
    desk's range, or one another object holds that the change does not also
    renumber -- or None. What the new number moves on other objects (the
    sends and tags into it) is the back half's to write and say
    (`amend._plan_edits`)."""
    word = _WORD[key]
    kind = edited.get("kind") if key == "outputs" else None
    if key == "outputs" and kind not in ("main", "matrix"):
        return None if edited.get("index") == original.get("index") else (
            f"an output of kind {kind!r} has no number on the desk to give it")
    if key == "outputs":
        cap = _capacity(CONSOLE_MAIN_CAPACITY if kind == "main" else CONSOLE_MATRIX_CAPACITY,
                        model, 4 if kind == "main" else 8)
        word = "Main" if kind == "main" else "Matrix"
        same = lambda o: isinstance(o, dict) and o.get("kind") == kind  # noqa: E731
    else:
        cap = _capacity({"busses": CONSOLE_BUS_CAPACITY, "dcas": CONSOLE_DCA_CAPACITY,
                         "mute_groups": CONSOLE_MUTE_GROUP_CAPACITY}[key], model,
                        {"busses": 16, "dcas": 16, "mute_groups": 8}[key])
        same = lambda o: isinstance(o, dict)  # noqa: E731
    holders = {o.get("index"): n for n, o in merged[key].items()
               if n != name and same(o) and n not in renumbering}
    if key == "outputs" and kind != original.get("kind") and "index" not in paths:
        free = _free_index(set(holders), cap)
        if free is None:
            return f"every {word} on this console is already in use"
        edited["index"] = free
        paths.append("index")
        infos.append(f"output {name!r} becomes {word} {free}, the lowest {word} the plan on the "
                     "desk leaves free -- name the number to choose it")
        return None
    index = edited.get("index")
    if index == original.get("index") and kind == original.get("kind"):
        return None
    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= cap:
        return f"this console has {_PLURAL.get(word, word + 's')} 1 to {cap} -- there is no {word} {index}"
    if index in holders:
        return (f"{word} {index} is {holders[index]!r}'s, which the change does not renumber or "
                "drop -- say what to do with it too, and both are carried out")
    infos.append(f"{_WORD[key]} {name!r}: {word} {index} was judged free from the plan on the "
                 f"desk alone -- the occupancy read covers strips, not "
                 f"{_PLURAL.get(word, word + 's')}")
    return None


_PLURAL = {"bus": "busses", "dca": "DCAs", "mute group": "mute groups", "Main": "Mains",
           "Matrix": "Matrices"}


def _is_ref(value, kind: str, index) -> bool:
    return isinstance(value, dict) and value.get("type") == kind and value.get("index") == index


def _routes_to(merged: dict, kind: str, index) -> list[str]:
    """Who routes to Main/Matrix `index` by its number: channels' `main_routes`,
    busses' `destination(s)`, outputs' `fed_by`, in words."""
    who = []
    for channel in merged["channels"]:
        if kind == "main" and any(isinstance(r, dict) and r.get("index") == index
                                  for r in channel.get("main_routes") or []):
            who.append(f"channel {channel.get('name')!r}")
    for name, bus in merged["busses"].items():
        if isinstance(bus, dict) and (_is_ref(bus.get("destination"), kind, index) or any(
                _is_ref(d, kind, index) for d in bus.get("destinations") or [])):
            who.append(f"bus {name!r}")
    for name, out in merged["outputs"].items():
        if isinstance(out, dict) and _is_ref(out.get("fed_by"), kind, index):
            who.append(f"output {name!r}")
    return who


def _follow_number(merged: dict, kind: str, moves: dict[int, tuple[int, str]],
                   infos: list) -> list:
    """Mains or Matrices renumbered (`moves`: {old number: (new number,
    name)}): every route the plan names BY NUMBER (a channel's `main_routes`,
    a bus's `destination`/`destinations`, an output's `fed_by`) follows its
    object, one edit per field that changes. Every move is made at once, so
    two that swap numbers each carry their own routes and no route moves
    twice. Matrix sends name a Matrix by its key, and follow by themselves."""
    def moved(value):
        if isinstance(value, dict) and value.get("index") in moves and (
                value.get("type") == kind or (kind == "main" and "type" not in value)):
            return {**value, "index": moves[value["index"]][0]}
        return value

    edits, who = [], {old: [] for old in moves}
    renumbered = {name for _new, name in moves.values()}
    owners = [("channels", c, str(c.get("name")), f"{c.get('bank', 'ch')}:{c.get('channel')}")
              for c in merged["channels"]]
    owners += [("busses", e, n, None) for n, e in merged["busses"].items() if isinstance(e, dict)]
    owners += [("outputs", e, n, None) for n, e in merged["outputs"].items()
               if isinstance(e, dict) and n not in renumbered]
    fields = {"channels": ("main_routes",) if kind == "main" else (),
              "busses": ("destination", "destinations"), "outputs": ("fed_by",)}
    for key, obj, who_name, slot in owners:
        for path in fields[key]:
            value = obj.get(path)
            after = [moved(v) for v in value] if isinstance(value, list) else moved(value)
            if after == value:
                continue
            obj[path] = after
            edits.append(amend_engine.FieldEdit(key=key, name=who_name, path=path,
                                                old=copy.deepcopy(value), new=after, slot=slot))
            for v in (value if isinstance(value, list) else [value]):
                if isinstance(v, dict) and moved(v) != v:
                    who[v["index"]].append(f"{_WORD[key]} {who_name!r}")
    word = "Main" if kind == "main" else "Matrix"
    for old, (new, name) in moves.items():
        if who[old]:
            infos.append(f"output {name!r}: {', '.join(dict.fromkeys(who[old]))} routed to "
                         f"{word} {old} by number, and follow it to {word} {new}")
    return edits


#: The fields of a running channel that say WHERE it is: setting either moves it.
_MOVE_FIELDS = ("channel", "bank")


def _channel_moves(merged: dict, change_set: dict, occupancy, changes: list,
                   infos: list) -> dict:
    """A change that names a running channel's strip or bank ("move the Kick
    to ch 20") moves it: the modify entry becomes a drop
    of the channel and an add of it, every other field the entry names set
    on it, so the back half returns the old strip to free and builds the
    channel whole on the new one (`MergeResult.moved`), as a drop and an add
    of one source in one change already are.

    Refused only for a strip that cannot take it: one past the desk's range,
    one another running channel holds, or one the desk read as somebody
    else's or could not read -- each named. Moving onto a strip something
    else is on would overwrite what the change does not name. Returns the
    change set to merge (a copy when anything moved)."""
    moves = [(i, m) for i, m in enumerate(change_set.get("modify") or [])
             if isinstance(m, dict) and _KEY_OF.get(str(m.get("object") or "")) == "channels"
             and isinstance(m.get("fields"), dict)
             and any(str(p).strip() in _MOVE_FIELDS for p in m["fields"])]
    if not moves:
        return change_set
    change_set = copy.deepcopy(change_set)
    add = change_set.setdefault("add", {})
    drop = change_set.setdefault("drop", {})
    by_label = {s.label: s for s in occupancy or ()}
    # A strip whose channel this same change moves away or drops is free to
    # take ("swap the Kick and the Snare").
    leaving = {_norm(n) for n in drop.get("channels") or []} | {
        _norm(m.get("name")) for _i, m in moves}
    taken_out: list[int] = []
    for i, entry in moves:
        found = _find_channel(merged["channels"], str(entry.get("name") or ""))
        if found is None:
            continue    # `_merge_modify` refuses a name that is not on the desk
        name = str(found.get("name"))
        fields = {str(p).strip(): v for p, v in entry["fields"].items()}
        bank = fields.get("bank", found.get("bank") or "ch")
        number = fields.get("channel", found.get("channel"))
        here = f"{found.get('bank') or 'ch'}:{found.get('channel')}"
        there = f"{bank}:{number}"
        word = "aux" if bank == "aux" else "channel"
        capacity = facts.CAPACITY.get(str(bank))
        why = None
        if capacity is None:
            why = f"there is no strip bank {bank!r} on this console (ch, aux)"
        elif isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= capacity:
            why = f"this console has {word} strips 1 to {capacity} -- there is no {there}"
        elif there == here:
            fields.pop("channel", None)
            fields.pop("bank", None)
        else:
            holder = next((c for c in merged["channels"] if c is not found
                           and f"{c.get('bank') or 'ch'}:{c.get('channel')}" == there
                           and _norm(c.get("name")) not in leaving), None)
            status = by_label.get(there)
            if holder is not None:
                why = (f"{there} holds channel {holder.get('name')!r}, which the change does not "
                       "move or drop -- say what to do with it too, and both are carried out")
            elif status is not None and status.state.value not in ("free", "ours"):
                held = status.name or status.source_name
                what = (f"something that is not this show's ({held!r})" if held
                        else "something that is not this show's")
                why = (f"the desk reads {there} as holding {what}"
                       if status.state.value == "theirs" else
                       f"the desk did not answer for {there}, so it counts as occupied")
        if why:
            changes.append(Change(
                ChangeKind.REFUSED, "channel", repr(name),
                f"the change moves it from {here} to {there}, and {why}", slot=here))
            taken_out.append(i)
            continue
        if "channel" not in fields and "bank" not in fields:
            entry["fields"] = fields    # named its own strip: nothing to move
            continue
        moved = copy.deepcopy(found)
        problems = []
        for path, value in fields.items():
            why_not = _frozen_reason(_FROZEN_FIELDS["channels"], path)
            if why_not:
                problems.append(f"its {path} is not something a change sets: {why_not}")
                continue
            amend_engine.set_path(moved, path, value)
        if problems:
            changes.append(Change(
                ChangeKind.REFUSED, "channel", repr(name),
                f"the change moves it and {'; '.join(problems)} -- refused rather than "
                "half-written", slot=here))
            taken_out.append(i)
            continue
        drop.setdefault("channels", []).append(name)
        add.setdefault("channels", []).append(moved)
        taken_out.append(i)
        others = [p for p in fields if p not in _MOVE_FIELDS]
        if others:
            infos.append(f"channel {name!r}: moved to {there} with {', '.join(others)} as the "
                         "change set them -- written with the rest of the strip there")
    change_set["modify"] = [m for i, m in enumerate(change_set.get("modify") or [])
                            if i not in taken_out]
    return change_set


def _merge_modify(merged: dict, change_set: dict, text: str | None, changes: list,
                  infos: list, warnings: list, occupancy, on_desk: dict,
                  renumbered_ids: frozenset | set = frozenset(), presets=None,
                  console_model: str | None = None, boxes: dict | None = None) -> list:
    """Slice 2: set the fields a change names on objects already on the
    desk, and ONLY those, returning an `amend.FieldEdit` per leaf that moved.

    The guarantee that nothing unnamed moves is structural: each object is
    copied, the named paths are set on the copy, and the copy replaces the
    object -- so the merged plan differs from the desk's in the named paths
    and nowhere else. Refused (the whole change with it): an object that is
    not there, a field its schema does not carry or a change may not set
    (`_FROZEN_FIELDS`), a value its schema refuses, and a reference to a
    bus, DCA or mute group that does not exist. Not written, with the
    reason: an entry naming no fields, and a fader or mute the change's own
    words do not name."""
    edits: list = []
    # Main and Matrix renumbers, by kind: {old number: (new number, name)}.
    follows: dict[str, dict[int, tuple[int, str]]] = {}
    # Objects this change renumbers, each freeing its number for another
    # ("swap busses 5 and 6").
    renumbering: dict[str, set[str]] = {}
    for request in change_set.get("modify") or []:
        key = _KEY_OF.get(str(request.get("object") or ""))
        fields = request.get("fields") if isinstance(request.get("fields"), dict) else {}
        if key in _NAMED_KINDS and {"index", "kind"} & {str(p).strip() for p in fields}:
            renumbering.setdefault(key, set()).add(str(request.get("name") or ""))
    for request in change_set.get("modify") or []:
        word = str(request.get("object") or "object")
        key = _KEY_OF.get(word)
        ref = str(request.get("name") or "")
        fields = request.get("fields") or {}
        asked = str(request.get("change") or "")
        if key is None:
            continue
        if not isinstance(fields, dict) or not fields:
            changes.append(Change(
                ChangeKind.MODIFIED, word, repr(ref),
                f"{asked} -- not written: the change set says this in words only and names no "
                "field to set, so nothing can be written without guessing"))
            continue
        found, slot = _find_object(merged, key, ref, on_desk)
        if found is None and _edit_added(merged, key, ref, fields, on_desk, word, asked,
                                         changes, infos):
            continue
        if found is None:
            changes.append(Change(
                ChangeKind.REFUSED, word, repr(ref),
                f"the change edits it ({asked}), and no {word} of that name is on the desk"))
            continue
        # A strip the same change's insert moves is rewritten whole on its new
        # number from the merged entry, so an edit of it needs no write of its
        # own: it is set on the entry and rides with the move.
        rides = key == "channels" and id(found) in renumbered_ids
        if key == "channels":
            original = found
            name = str(original.get("name") or ref)
        else:
            name = found
            original = merged[key][name] if isinstance(merged[key][name], dict) else {}
        edited = copy.deepcopy(original)
        props = _OBJECT_SCHEMAS[key].get("properties") or {}
        frozen = _FROZEN_FIELDS.get(key, {})
        problems: list[str] = []
        paths = [str(path).strip() for path in fields]
        for path, value in zip(paths, fields.values()):
            top = path.split(".")[0]
            why = _frozen_reason(frozen, path)
            if why:
                problems.append(f"its {path} is not something a change sets: {why}")
                continue
            if top not in props:
                problems.append(f"a {word} carries no field {top!r}")
                continue
            if "." in path:
                parent = amend_engine.get_path(edited, path.rsplit(".", 1)[0])
                if parent is not None and not isinstance(parent, dict):
                    problems.append(f"{path}: {path.rsplit('.', 1)[0]} is not an object")
                    continue
            amend_engine.set_path(edited, path, value)
        if not problems and key in _NAMED_KINDS and ("index" in paths or "kind" in paths):
            problem = _renumber(merged, key, name, original, edited, paths, renumbering.get(
                key, set()), console_model, infos)
            if problem:
                problems.append(problem)
        if not problems and key == "channels" and "source.stereo" in paths:
            others = [c for c in merged["channels"] if c is not original]
            problem = _settle_stereo(
                original, edited, _occupied_sockets(
                    {"channels": others}, [s for s in occupancy or () if s.label != slot]),
                console_model, boxes, infos, name)
            if problem:
                problems.append(problem)
            elif edited.get("patch") != original.get("patch") and "patch" not in paths:
                paths.append("patch")
        if not problems and key == "channels" and isinstance(edited.get("source"), dict) \
                and any(p.split(".")[0] == "source" for p in paths):
            ribbon = _ribbon_with_phantom(edited["source"])
            if ribbon and not _ribbon_with_phantom(original.get("source") or {}):
                problems.append(
                    f"{ribbon!r} is a passive ribbon microphone and the change leaves it with "
                    "phantom power on -- 48V destroys a ribbon element and switching it off "
                    "again does not undo the damage; set source.phantom false in the same change")
        if not problems and key == "channels":
            problems.extend(_pair_phantom_problems(original, edited, paths, infos, name))
        record = _preset_record(key, original)
        if record is not None and key == "channels" and isinstance(edited.get("processing"), dict):
            # A whole `processing` object the change restates is the
            # change's words for the fields in it; the expanded preset
            # values were never among them, so they stay.
            edited["processing"].setdefault("preset_values", copy.deepcopy(record))
        if not problems:
            # A whole object the change restates (`source`, say) is held to
            # the same list, field by field: restating what is there moves
            # nothing, changing a frozen part of it is refused.
            for path in dict.fromkeys(paths):
                for leaf, _old, _new in _leaves(path, amend_engine.get_path(original, path),
                                                amend_engine.get_path(edited, path)):
                    why = _frozen_reason(frozen, leaf)
                    if why and leaf != path:
                        problems.append(f"its {leaf} is not something a change sets: {why}")
        if not problems:
            problems = validate_schema(edited, _OBJECT_SCHEMAS[key], path=f"{word} {name!r}")
        if problems:
            shown = "; ".join(problems[:4]) + (f"; and {len(problems) - 4} more"
                                               if len(problems) > 4 else "")
            changes.append(Change(
                ChangeKind.REFUSED, word, repr(name),
                f"the change edits it, and {shown} -- refused rather than half-written",
                slot=slot))
            continue

        leaves: list[tuple[str, object, object]] = []
        for path in dict.fromkeys(paths):
            leaves.extend(_leaves(path, amend_engine.get_path(original, path),
                                  amend_engine.get_path(edited, path)))
        kept: list[tuple[str, object, object]] = []
        for path, old, new in leaves:
            if key == "channels" and path == _PRESET_NAME_PATH[key]:
                # Switching a running channel's preset: the new
                # preset is expanded over the channel as a build does, the
                # leaves it sets are written, and what the old preset set and
                # the new one does not is returned to what an initialized
                # strip reads (`amend._vanished_target`).
                values = _switch_channel_preset(edited, new, presets, name, word, slot,
                                                changes, infos, warnings)
                if values is False:
                    amend_engine.set_path(edited, path, old)
                    if record is not None:
                        edited["processing"]["preset_values"] = copy.deepcopy(record)
                    else:
                        edited["processing"].pop("preset_values", None)
                    continue
                kept.append((path, old, new))
                kept.append(("processing.preset_values", record, values))
                continue
            if key == "busses" and path == _PRESET_NAME_PATH[key]:
                # Switching a running bus's preset: its values
                # and its effects, each effect in an engine the desk leaves free.
                values = _switch_bus_preset(merged, edited, new, presets, name, word, slot,
                                            changes, infos, warnings)
                if values is False:
                    amend_engine.set_path(edited, path, old)
                    if record is not None:
                        edited["preset_values"] = copy.deepcopy(record)
                    else:
                        edited.pop("preset_values", None)
                    continue
                kept.append((path, old, new))
                kept.append(("preset_values", record, values))
                continue
            if path.split(".")[0] == "fader":
                muted = path.endswith("muted")
                if not (_MUTE_WORDS if muted else _FADER_WORDS).search(text or ""):
                    amend_engine.set_path(edited, path, old)
                    what = "mute" if muted else "fader"
                    changes.append(Change(
                        ChangeKind.MODIFIED, word, repr(name),
                        f"{path} {amend_engine.format_value(path, old)} -> "
                        f"{amend_engine.format_value(path, new)} -- not written: the change "
                        f"does not name the {what}, and a {what} is never moved unless the "
                        "change names it", slot=slot))
                    continue
            kept.append((path, old, new))
        if not kept:
            if not any(c.kind is ChangeKind.MODIFIED and c.where == repr(name) for c in changes):
                infos.append(f"{word} {name!r}: {asked} -- already so on the desk; nothing "
                             "to change")
            continue

        missing = [f"{_WORD[k]} {r!r}" for k, r in _references(edited) if r not in merged[k]]
        if missing:
            changes.append(Change(
                ChangeKind.REFUSED, word, repr(name),
                f"the change edits it to name {', '.join(missing)}, which is neither on the "
                "desk nor added by this change", slot=slot))
            continue

        if key == "channels" and any(p.split(".")[0] == "patch" for p, _o, _n in kept):
            others = [c for c in merged["channels"] if c is not original]
            used = _occupied_sockets({"channels": others},
                                     [s for s in occupancy or () if s.label != slot])
            patch = edited.get("patch") or {}
            clash = [used[(patch.get("group"), n)] for n in patch.get("sockets") or []
                     if (patch.get("group"), n) in used]
            if clash:
                warnings.append(
                    f"channel {name!r} on {slot}: the change repatches it to "
                    f"{amend_engine.format_value('patch', patch)}, which {clash[0]} already "
                    "uses -- honored as named (one socket can feed two strips on a WING), but "
                    "check that is what was meant")

        if key == "channels":
            merged["channels"] = [edited if c is original else c for c in merged["channels"]]
        else:
            merged[key][name] = edited
        if rides:
            infos.append(f"{word} {name!r}: {asked} -- this strip moves with the insert and is "
                         "rewritten whole on its new number, so the edit "
                         f"({', '.join(p for p, _o, _n in kept)}) is written with it")
            continue
        if key == "channels" and not any(p.split(".")[0] == "patch" for p, _o, _n in kept):
            for path, old, new in kept:
                if path in ("source.input", "source.pair_input"):
                    infos.append(
                        f"channel {name!r} on {slot}: its input-list row {old!r} -> {new!r}; the "
                        "change names no socket, so its patch stays "
                        f"{amend_engine.format_value('patch', edited.get('patch'))} -- the "
                        "cable is taken to be where it was. Name the socket to move it")
        if key == "outputs" and any(p == "index" for p, _o, _n in kept) \
                and edited.get("kind") == original.get("kind"):
            follows.setdefault(edited.get("kind"), {})[original.get("index")] = (
                edited.get("index"), name)
        elif key == "outputs" and any(p == "kind" for p, _o, _n in kept):
            routed = _routes_to(merged, original.get("kind"), original.get("index"))
            if routed:
                infos.append(
                    f"output {name!r} is no longer {original.get('kind')} "
                    f"{original.get('index')}; {', '.join(routed)} still route there, to that "
                    "number on the desk -- route them to it in a change if they should feed it")
        for path, old, new in kept:
            edits.append(amend_engine.FieldEdit(key=key, name=str(name), path=path,
                                                old=old, new=new, slot=slot))
    for kind, moves in follows.items():
        edits.extend(_follow_number(merged, kind, moves, infos))
    return edits


#: Words by which a change asks for room to be made: the strips after the
#: new one move down. Without one of them, "add HiHat after Snare" adds the
#: channel on the next free strip and moves nothing.
_INSERT_WORDS = re.compile(
    r"\binsert\w*|\brenumber\w*|\bmake\s+(?:room|space)\b"
    r"|\b(?:move|shift|push|bump)\s+(?:the\s+)?(?:rest|remaining|others|everything|"
    r"channels|strips)\b[^.;]{0,30}\b(?:down|up)\b", re.IGNORECASE)

_AFTER = re.compile(r"\b(after|behind|below|following|before)\s+(?:the\s+)?([^,.;]+)",
                    re.IGNORECASE)
_AT_STRIP = re.compile(r"\b(?:as|at|into|on|in)\s+(?:channel|ch|strip)\s*(\d+)\b", re.IGNORECASE)


def _spoken_position(text: str, channels: list[dict]) -> tuple[int, dict | None] | None:
    """The strip a change's words put a new channel on, as `(number, the
    channel it is beside or None)`: "after Snare" is the strip below
    Snare's, "before Kick" Kick's own, "as channel 3" that number. The
    longest run of words after the preposition that names a channel on the
    desk is the one meant ("after Snare and renumber the rest" is Snare)."""
    if (at := _AT_STRIP.search(text or "")):
        return int(at.group(1)), None
    for match in _AFTER.finditer(text or ""):
        words = match.group(2).split()
        for count in range(min(len(words), 4), 0, -1):
            beside = _find_channel(channels, " ".join(words[:count]).strip(" '\""))
            if beside is not None and isinstance(beside.get("channel"), int):
                before = match.group(1).lower() == "before"
                return beside["channel"] + (0 if before else 1), beside
    return None


def _spoken_wording(name: str, number: int, channels: list[dict]) -> str:
    """The words that would make this change an insert, with the channel it
    sits beside named: what the INFO gives the engineer to say next time."""
    above = next((c for c in channels if c.get("channel") == number - 1), None)
    where = f"after {above['name']}" if above is not None and above.get("name") \
        else f"as channel {number}"
    return f"insert {name} {where} and renumber the channels after it"


def _gain_named(text: str | None, channel: dict, texts=()) -> bool:
    """Whether the change names a gain for this channel: a clause of it
    mentions the channel (or its source) and the word gain; so does a line of
    `texts`, the conventions and instructions the change is compiled with;
    or the conventions' Category table set it for the channel's category."""
    return inferred.gain_stated_for(channel, (text, *texts))


def _plan_insert(merged: dict, kept: list[dict], text: str | None,
                 changes: list, infos: list, result: MergeResult) -> set[int]:
    """An explicit insert: the channels after the new one move down.

    What the change says decides it (the maintainer's rule): *insert* (or
    renumber, or "move the rest down") renumbers; "add X after Snare" with no
    such word does not -- the channel goes on the next free strip and the
    INFO says so, with the words that would renumber. The usual reason for
    either is that something was missed on the input list, and the desk has
    to be lined up with the real one on site.

    The channels from the insertion point up, to the first free strip, each
    move down by the number inserted; the strips after that gap are left
    where they are. The plan's channels carry their own sends, DCA and
    mute-group membership, so those go with them, and the back half
    (`amend.plan_amendment`) rewrites each moved strip whole. Returns the
    ids of the channel entries that moved, which a `modify` may not also
    edit in the same change."""
    base = [c for c in merged["channels"] if isinstance(c, dict)
            and str(c.get("bank", "ch")) == "ch" and isinstance(c.get("channel"), int)]
    by_number = {c["channel"]: c for c in base}
    new = [c for c in kept if str(c.get("bank", "ch")) == "ch" and isinstance(c.get("channel"), int)
           and amend_engine._source_key(c) not in result.moved]
    if not new:
        return set()
    explicit = bool(_INSERT_WORDS.search(text or ""))
    spoken = _spoken_position(text or "", base)
    colliding = sorted((c for c in new if c["channel"] in by_number), key=lambda c: c["channel"])
    if not colliding and spoken is not None and spoken[0] in by_number:
        # The model put it elsewhere (the next free strip) though the change
        # names a position: the words decide, not the proposal.
        if explicit:
            colliding = new
        else:
            result.not_renumbered.extend(
                (c.get("name"), spoken[0], _spoken_wording(str(c.get("name")), spoken[0], base))
                for c in new)
            return set()
    if not colliding:
        return set()
    if not explicit:
        first = colliding[0]["channel"]
        result.not_renumbered.extend(
            (c.get("name"), c["channel"], _spoken_wording(str(c.get("name")), first, base))
            for c in colliding)
        return set()

    point = spoken[0] if spoken is not None and colliding is new else colliding[0]["channel"]
    inserts = colliding
    count = len(inserts)
    moves: dict[int, int] = {}
    cursor = point + count
    for channel in sorted((c for c in base if c["channel"] >= point), key=lambda c: c["channel"]):
        if channel["channel"] >= cursor:
            break
        moves[channel["channel"]] = cursor
        cursor += 1
    capacity = facts.CAPACITY["ch"]
    if max([point + count - 1, *moves.values()]) > capacity:
        for c in inserts:
            changes.append(Change(
                ChangeKind.REFUSED, "channel", repr(c.get("name")),
                f"inserting it at ch {point} moves the strips after it down, and the last would "
                f"go past ch {capacity}, which is as far as this console goes"))
        return set()

    ids: set[int] = set()
    for old, new_number in moves.items():
        channel = by_number[old]
        channel["channel"] = new_number
        ids.add(id(channel))
        note = (f"renumbered ch:{old} -> ch:{new_number} by `atoo patch`: the change inserted "
                f"a channel at ch:{point}")
        provenance = channel.get("provenance")
        if provenance is None:
            provenance = channel["provenance"] = {}
        if isinstance(provenance, dict):
            earlier = provenance.get("channel")
            provenance["channel"] = f"{earlier}; {note}" if earlier else note
        result.renumbered[f"ch:{old}"] = f"ch:{new_number}"
    for offset, channel in enumerate(inserts):
        channel["channel"] = point + offset
        result.inserted[amend_engine._source_key(channel)] = f"ch:{point + offset}"
    names = ", ".join(repr(c.get("name")) for c in inserts)
    if moves:
        infos.append(
            f"the change inserts {names} at ch {point}, so the {len(moves)} channel(s) from "
            f"ch {min(moves)} to ch {max(moves)} move down to ch {min(moves.values())}-"
            f"ch {max(moves.values())}: each strip is rewritten whole on its new number (its "
            "patch, name, color, processing, sends, DCA and mute-group membership go with it), "
            "and every strip that moves is listed below. A fader or mute the plan does not "
            "state is not carried: that strip's fader goes to -inf and it is unmuted, so raise "
            "it again."
            + (f" The strips after ch {max(moves.values())} are left where they are, because "
               "a free strip stood in the way of the move."
               if max(moves.values()) < max(by_number, default=0) else ""))
    else:
        infos.append(f"the change inserts {names} at ch {point}, which nothing stands on, so "
                     "nothing moved")
    return ids


def merge_change(base: dict, change_set: dict, *, occupancy=None,
                 console_model: str | None = None, presets=None,
                 text: str | None = None, aes50_devices: dict | None = None,
                 gain_texts=()) -> MergeResult:
    """Merge a change set onto the base. Pure: `base` is not modified.

    The rules, in the order they are applied:

    1. **Drops.** A dropped channel is taken out of the merged plan, so the
       back half returns its strip to free -- if the desk still reads as
       the strip this show built (`amend.release_refusal`). A drop naming
       nothing on the desk is REFUSED. A dropped bus is carried out
       (`_drop_bus`): taken out of the merged plan, so the back
       half returns it to free, and the sends into it taken out of the
       channels that had them. A dropped DCA, mute group or output is the
       same (`_drop_group`, `_drop_output`); a DCA or
       mute group's members have it taken out of their tags.
    2. **Named objects** (busses, DCAs, mute groups, outputs). New ones are
       added with a free console index; one that already exists under that
       name is the existing object -- identical, it is simply referred to;
       different, it would change a running object and is reported as
       MODIFIED, not written.
    3. **Channels.** One whose name or source is already on the desk would
       change a running strip: MODIFIED, not written. Two with the same
       name in one change: REFUSED.
    4. **References.** Every DCA, mute group and bus an added channel, bus
       or output names must be on the desk or added by this change. One
       that is neither is REFUSED -- a send to a bus that does not exist is
       a setting the desk cannot be left in.
    5. **Sockets**, for each added channel: named ones honoured, unnamed
       ones checked against every socket in use and chosen afresh when
       taken (`_settle_socket`), with an INFO either way.
    6. **Decisions.** `inferred.decide_unstated` on the result, so a new
       bus's width, destination and send modes are decided and marked,
       exactly as for a build.
    7. **Presets**. An added channel that names a
       preset gets the same expansion `build` gives one -- the preset's
       processing values resolved into it from `presets` (the library),
       merged by address, the channel's own processing winning. Only the
       ADDED channels: a channel already on the desk is the base's, and
       re-expanding it here would describe it differently from the plan
       that built it. With no library, the added channel names the preset
       and carries none of its values, and the pre-flight verify says so.
    8. **Edits** (slice 2, `_merge_modify`) -- the named fields of objects
       already on the desk, set and nothing else; applied after the adds
       and before the decisions. `text` is the change as typed: a fader or
       mute is edited only when it names one.
    """
    model = resolve_console_model(base, console_model)
    # A base plan built before the rename to `patch` names its outputs' patches
    # `socket`; the merged plan is written with the current names.
    merged = copy.deepcopy(plan_compat.normalise_plan(base))
    for key in ("channels",):
        merged.setdefault(key, [])
    for key in _NAMED_KINDS:
        if not isinstance(merged.get(key), dict):
            merged[key] = {}
    if model:
        merged.setdefault("meta", {})
        if isinstance(merged["meta"], dict):
            merged["meta"].setdefault("console_model", model)
    result = MergeResult(plan=merged)
    changes, infos, warnings = result.changes, result.infos, result.warnings
    # What is on the desk before this change adds anything -- all a
    # `modify` entry may name.
    on_desk: dict = {"channels": {id(c) for c in merged["channels"]},
                     **{key: set(merged[key]) for key in _NAMED_KINDS}}
    # 0. A running channel the change moves to another strip or bank is
    #    dropped and added again.
    change_set = _channel_moves(merged, change_set, occupancy, changes, infos)
    add = change_set.get("add") or {}
    drop = change_set.get("drop") or {}

    # 1. Drops.
    dropped_keys: dict[str, str] = {}
    for name in drop.get("channels") or []:
        found = _find_channel(merged["channels"], name)
        if found is None:
            changes.append(Change(
                ChangeKind.REFUSED, "channel", repr(name),
                "the change drops it, and no channel of that name is on the desk -- nothing "
                "to remove, so the change is refused rather than guessed at"))
            continue
        merged["channels"] = [c for c in merged["channels"] if c is not found]
        result.explicit_drops.add(amend_engine._source_key(found))
        dropped_keys[amend_engine._source_key(found)] = amend_engine._slot_label(
            amend_engine._channel_slot(found)) if isinstance(found.get("channel"), int) else ""
    for key in _NAMED_KINDS:
        word = _WORD[key]
        for name in drop.get(key) or []:
            if name not in merged[key]:
                changes.append(Change(
                    ChangeKind.REFUSED, word, repr(name),
                    f"the change drops it, and no {word} of that name is on the desk"))
                continue
            if key == "busses":
                _drop_bus(merged, name, result)
            elif key == "outputs":
                _drop_output(merged, name, result)
            else:
                _drop_group(merged, key, name, result)

    # 2. Named objects.
    capacities = {
        "busses": _capacity(CONSOLE_BUS_CAPACITY, model, 16),
        "dcas": _capacity(CONSOLE_DCA_CAPACITY, model, 16),
        "mute_groups": _capacity(CONSOLE_MUTE_GROUP_CAPACITY, model, 8),
    }
    added_busses: list[str] = []
    for key in ("dcas", "mute_groups", "busses", "outputs"):
        word = _WORD[key]
        for name, entry in (add.get(key) or {}).items():
            entry = copy.deepcopy(entry) if isinstance(entry, dict) else {}
            if name in merged[key]:
                existing = {k: v for k, v in (merged[key][name] or {}).items() if k != "index"}
                proposed = {k: v for k, v in entry.items() if k != "index"}
                if proposed and proposed != existing and key != "mute_groups":
                    changes.append(Change(
                        ChangeKind.MODIFIED, word, repr(name),
                        _restated(f"the change restates {word} {name!r} with different "
                                  "settings")))
                continue
            named = entry.pop("index", None)
            if key == "outputs":
                named = None  # an output's number is its Main or Matrix, decided below
            if key == "outputs":
                kind = entry.get("kind")
                if kind in ("main", "matrix"):
                    taken = {o.get("index") for o in merged["outputs"].values()
                             if isinstance(o, dict) and o.get("kind") == kind}
                    cap = _capacity(CONSOLE_MAIN_CAPACITY if kind == "main"
                                    else CONSOLE_MATRIX_CAPACITY, model, 4 if kind == "main"
                                    else 8)
                    index = _free_index(taken, cap)
                    if index is None:
                        changes.append(Change(
                            ChangeKind.REFUSED, word, repr(name),
                            f"every {kind} on this console is already in use"))
                        continue
                    entry["index"] = index
            else:
                taken = {o.get("index") for o in merged[key].values() if isinstance(o, dict)}
                index = _free_index(taken, capacities[key])
                if isinstance(named, int) and not isinstance(named, bool):
                    # "reuse bus 5": the engineer named the number.
                    if not 1 <= named <= capacities[key]:
                        changes.append(Change(
                            ChangeKind.REFUSED, word, repr(name),
                            f"the change puts it on {word} {named}, and this console has "
                            f"{_PLURAL.get(word, word + 's')} 1 to {capacities[key]} -- there "
                            f"is no {word} {named}"))
                        continue
                    if named not in taken:
                        index = named
                        infos.append(f"{word} {name!r} is new, put on {word} {named} as the "
                                     "change said"
                                     + (f" -- the {word} this change returns to free"
                                        if named in (result.freed_indices if key == "busses"
                                                     else result.freed_object_indices.get(key, ()))
                                        else ""))
                        entry["index"] = index
                        merged[key][name] = entry
                        added_busses.append(name)
                        continue
                    infos.append(f"the change puts {word} {name!r} on {word} {named}, which "
                                 "a running bus the change does not drop already holds, so it "
                                 "was put on the lowest free index instead")
                if index is None:
                    changes.append(Change(
                        ChangeKind.REFUSED, word, repr(name),
                        f"every {word} on this console is already in use"))
                    continue
                entry["index"] = index
                infos.append(f"{word} {name!r} is new, given index {index} -- the lowest "
                             f"the plan on the desk leaves free")
            merged[key][name] = entry
            if key == "busses":
                added_busses.append(name)

    # 3. Channels.
    seen: set[str] = set()
    added: list[dict] = []
    for channel in add.get("channels") or []:
        channel = copy.deepcopy(channel)
        name = channel.get("name")
        where = repr(name)
        if _norm(name) in seen:
            changes.append(Change(
                ChangeKind.REFUSED, "channel", where,
                "the change adds two channels of this name -- one strip name, one strip"))
            continue
        seen.add(_norm(name))
        if amend_engine._source_key(channel) in dropped_keys:
            result.moved.add(amend_engine._source_key(channel))
        existing = _find_channel(merged["channels"], name) or next(
            (c for c in merged["channels"]
             if amend_engine._source_key(c) == amend_engine._source_key(channel)), None)
        if existing is not None:
            changes.append(Change(
                ChangeKind.MODIFIED, "channel", where,
                _restated(f"channel {existing.get('name')!r} is already on the desk "
                          f"({existing.get('bank', 'ch')}:{existing.get('channel')}), and "
                          "the change describes it differently"),
                slot=f"{existing.get('bank', 'ch')}:{existing.get('channel')}"))
            continue
        added.append(channel)

    # 4. References -- checked against the merged plan, so an object this
    #    change adds satisfies a reference from another thing it adds.
    def dangling(obj: dict) -> list[str]:
        return [f"{_WORD[key]} {ref!r}" for key, ref in _references(obj)
                if ref not in merged[key]]

    kept: list[dict] = []
    for channel in added:
        missing = dangling(channel)
        if missing:
            changes.append(Change(
                ChangeKind.REFUSED, "channel", repr(channel.get("name")),
                f"it names {', '.join(missing)}, which is neither on the desk nor added by "
                "this change -- a strip cannot be sent to, or grouped with, something that "
                "does not exist"))
            continue
        kept.append(channel)
    for key in ("busses", "outputs"):
        for name in list((add.get(key) or {})):
            entry = merged[key].get(name)
            if not isinstance(entry, dict) or name not in (add.get(key) or {}):
                continue
            missing = dangling(entry)
            if missing:
                changes.append(Change(
                    ChangeKind.REFUSED, _WORD[key], repr(name),
                    f"it names {', '.join(missing)}, which is neither on the desk nor added "
                    "by this change"))

    # 4b. An explicit insert -- the channels after a new one move down.
    renumbered_ids = _plan_insert(merged, kept, text, changes, infos, result)

    # 5. Sockets. A socket past the end of a stage box is not one it has: the
    #    desk lists every AES50 port at 48 whatever is on it, so the box's own
    #    size (`aes50_devices`, what the desk named on each port) bounds the choice.
    boxes = apply_module.box_limits(aes50_devices)
    used = _occupied_sockets(
        merged, occupancy, leaving=frozenset(dropped_keys[key] for key in result.moved))
    for channel in kept:
        _settle_socket(channel, used, model, infos, warnings, boxes, text)
        said = inferred.settle_line_gain(
            channel, stated=_gain_named(text, channel, gain_texts))
        if said:
            infos.append(said)
        patch = channel.get("patch") or {}
        for socket in patch.get("sockets") or []:
            if isinstance(patch.get("group"), str) and isinstance(socket, int):
                used.setdefault((patch["group"], socket), f"channel {channel.get('name')!r}")
        merged["channels"].append(channel)

    # 7. Presets -- the added channels only; see the docstring.
    if presets is not None:
        from atoo import preset_expand
        for channel in kept:
            for finding in preset_expand.expand_channel(channel, presets):
                (infos if finding.severity == "info" else warnings).append(finding.message)
            values = preset_expand.preset_values(channel)
            if values is not None:
                infos.append(
                    f"channel {channel.get('name')!r}: the preset {values['preset']!r} "
                    f"({values['file']}) puts {len(values['leaves'])} processing values into "
                    "the change, written with it and read back like every other write")
        # A new bus's preset and its effect, given an engine
        # the busses already on the desk leave free.
        from atoo import bus_presets
        for finding in bus_presets.expand_added_busses(merged, added_busses, presets):
            (infos if finding.severity == "info" else warnings).append(finding.message)

    # 8. Edits (slice 2) -- the named fields of objects already on the
    #    desk. After the adds, so an edit may name a DCA or bus this change
    #    adds ("put the horns in a new Brass DCA"); before the decisions, so
    #    a send the edit adds with no mode gets one, as a build's would --
    #    and each edit's new value is read again after them (below), so the
    #    review's old -> new is what is written.
    drop_edits, result.edits = result.edits, []
    pending = drop_edits + _merge_modify(merged, change_set, text, changes, infos, warnings,
                                         occupancy, on_desk, renumbered_ids, presets,
                                         model, boxes)

    # 6. Decisions, and the remaining index defaults (a new bus routed to
    #    "main" with no number) -- every index is already set, so this
    #    fills defaults and renumbers nothing.
    inferred.decide_unstated(merged)
    if model:
        try:
            allocate_console_indices(merged, console_model=model)
        except facts.UnknownConsoleModel:
            pass

    for edit in pending:
        # The value after the decisions -- what is actually written.
        obj = amend_engine.edited_object(merged, edit)
        new = amend_engine.get_path(obj, edit.path) if obj is not None else edit.new
        result.edits.append(amend_engine.FieldEdit(
            key=edit.key, name=edit.name, path=edit.path, old=edit.old, new=new,
            slot=edit.slot))

    for note in change_set.get("notes") or []:
        infos.append(f"the model said: {note}")
    return result


def plan_patch(base: dict, change_set: dict, occupancy, *, allow_strips=None,
               console_model: str | None = None, presets=None, text: str | None = None,
               aes50_devices: dict | None = None, gain_texts=(), desk_objects: dict | None = None):
    """The whole review of one change: `(amendment, merge)`.

    `amend.plan_amendment` over `(base, merged)` -- the back half -- with
    the merge's own verdicts put in front of its changes, and the merge's
    choices in front of its INFO lines. A REFUSED change is a blocking
    kind, so `amendment.blocked` refuses the write exactly as it refuses an
    unplaceable channel.

    Earlier placements (`amend.PLACEMENTS_META`) are carried forward for
    every channel still on the strip they were placed on: they are what
    lets a later `--amended-plan` rebuild recognise a channel an amend put
    somewhere other than where the build numbered it, and a change that
    did not touch that channel must not forget it."""
    adopted_infos: list[str] = []
    adopted_warnings: list[str] = []
    adopted_writes: list = []
    adopted_changes: list = []
    adopted_read: set = set()
    if desk_objects is not None:
        (base, change_set, adopted_infos, adopted_warnings, adopted_writes,
         adopted_changes, adopted_read) = adopt_desk_objects(base, change_set, desk_objects)
    merge = merge_change(base, change_set, occupancy=occupancy, console_model=console_model,
                         presets=presets, text=text, aes50_devices=aes50_devices,
                         gain_texts=gain_texts)
    amendment = amend_engine.plan_amendment(
        base, merge.plan, occupancy, allow_strips=allow_strips, console_model=console_model,
        by="the change", edits=merge.edits, moved=merge.moved,
        renumbered=merge.renumbered, inserted=merge.inserted, freed_busses=merge.freed_busses,
        freed_objects=merge.freed_objects,
        explicit_drops=merge.explicit_drops)
    amendment.changes = adopted_changes + merge.changes + amendment.changes
    # A dropped bus's send, or a dropped group's tag, on a strip the plan has
    # no record of: written beside the change's own,
    # journalled and undone like them -- unless the change is refused, when
    # nothing is written at all.
    for target in adopted_writes:
        amendment.edit_extra.append(target)
        amendment.edit_scope.grant(target.address, target.description)
    amendment.read_from_desk |= adopted_read
    amendment.infos = adopted_infos + merge.infos + amendment.infos
    amendment.warnings = adopted_warnings + merge.warnings + amendment.warnings

    # "Add X after Snare" with no word asking for room: said where it went,
    # and the exact words that would have moved the strips after it.
    for name, asked, wording in merge.not_renumbered:
        landed = next((c.slot for c in amendment.changes
                       if c.kind is ChangeKind.ADDED and c.where == repr(name)), None)
        amendment.infos.append(
            f"channel {name!r}: the change puts it at ch {asked}, which is in use, and does not "
            "ask for the strips after it to be renumbered, so "
            + (f"it went on {landed}, the next free strip" if landed else
               "it goes on the next free strip")
            + ", and nothing already on the desk moved. To put it there and move the others "
            f'down, say: "{wording}".')

    prior = amend_engine.amend_placements(base)
    if prior and merge.renumbered:
        # A strip an insert moved is the same channel on a new number: the
        # record of where an earlier amend placed it follows it.
        prior = {merge.renumbered.get(k, k): v for k, v in prior.items()}
    if prior:
        slots = {f"{c.get('bank', 'ch')}:{c.get('channel')}"
                 for c in amendment.effective_plan.get("channels") or [] if isinstance(c, dict)}
        meta = amendment.effective_plan.setdefault("meta", {})
        carried = {k: v for k, v in prior.items() if k in slots}
        carried.update(meta.get(amend_engine.PLACEMENTS_META) or {})
        if carried:
            meta[amend_engine.PLACEMENTS_META] = carried
    return amendment, merge


def default_name(text: str) -> str:
    """A short name when the model gave none worth using: the first few
    words of the change."""
    words = re.sub(r"\s+", " ", text or "").strip().split(" ")
    name = " ".join(words[:6])
    return name[:CHANGE_NAME_MAX] or "change"


def change_block(text: str | None, change_set: dict, number: int | None) -> dict:
    """What the journal entry (and the stack's index row) records about the
    change: its number on this bundle's stack, its short name, and the text
    the engineer typed -- so the journal reads as a list of changes."""
    name = str(change_set.get("name") or "").strip() or default_name(text or "")
    return {"number": number, "name": name[:CHANGE_NAME_MAX], "text": text}


#: `change 3: Add horns on A 21-23` -- how a change is named in a message, a
#: journal listing and the UI. One definition, the journal stack's.
change_label = journal_stack.change_label


__all__ = [
    "CHANGE_NAME_MAX", "CHANGE_SET_SCHEMA", "ChangeError", "MergeResult", "TEXT_KEY",
    "change_block", "change_label", "change_system", "change_user", "compile_change",
    "default_name", "empty_base", "empty_change_set", "load_change_set", "merge_change",
    "parse_change_set", "plan_patch", "saved_change_set", "validate_change_set",
]
