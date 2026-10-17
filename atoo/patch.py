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
whole in `add`, a `modify` said in words with no fields, and dropping a
bus, DCA, mute group or output (nothing returns one of those to free
yet). The merged plan keeps the base's version of anything it did not
write, so the plan journalled as "on the desk" stays true.

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
from atoo import console_facts as facts
from atoo import generate
from atoo import inferred
from atoo import journal_stack
from atoo import plan_schema
from atoo.allocate import (CONSOLE_BUS_CAPACITY, CONSOLE_DCA_CAPACITY,
                                CONSOLE_MAIN_CAPACITY, CONSOLE_MATRIX_CAPACITY,
                                CONSOLE_MUTE_GROUP_CAPACITY, allocate_console_indices)
from atoo.amend import Change, ChangeKind
from atoo.json_repair import extract_json_object, loads_with_repair
from atoo import plan_compat
from atoo.schema_check import validate as validate_schema
from atoo import verify_plan
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
    return f"""\
# Domain knowledge

{generate._domain_knowledge()}

---

{conventions_part}

---

# The plan currently on the desk

{desk}

```json
{json.dumps(_base_for_prompt(base), indent=2)}
```

---

# The change

{change_text.strip()}

---

Compile this change. Emit the change set JSON and nothing else."""


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
    violations = validate_schema(change_set, CHANGE_SET_SCHEMA)
    if violations:
        shown = "\n  ".join(violations[:10])
        more = f"\n  ...and {len(violations) - 10} more" if len(violations) > 10 else ""
        raise ChangeError(f"the change set does not match the change-set format:\n  {shown}{more}",
                          partial_text=partial_text or json.dumps(change_set, indent=2))
    return change_set


def compile_change(change_text: str, base: dict, *, provider, console_model: str,
                   conventions: str | None = None, conventions_name: str | None = None,
                   instructions: str | None = None, instructions_name: str | None = None,
                   constrain: bool = True, infos: list[str] | None = None) -> dict:
    """The typed change -> a change set, by one model call. Anything
    decided while reading the reply is appended to `infos`."""
    raw = provider.complete(
        system=change_system(console_model),
        user=change_user(base, change_text, conventions=conventions,
                         conventions_name=conventions_name, instructions=instructions,
                         instructions_name=instructions_name),
        response_schema=CHANGE_SET_SCHEMA if constrain else None,
        label="change",
    )
    return parse_change_set(raw, infos=infos)


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


def _choose_sockets(group: str, count: int, used, console_model: str | None) -> list[int] | None:
    """The lowest free socket(s) in `group`: one, or an odd-started
    consecutive pair for a stereo channel (`facts.STEREO_PAIR_RULE`)."""
    try:
        limit = facts.input_socket_limit(group, console_model)
    except facts.UnknownConsoleModel:
        limit = facts.INPUT_SOCKETS.get(group, 0)
    step = 2 if count == 2 else 1
    for start in range(1, limit - count + 2, step):
        sockets = list(range(start, start + count))
        if all((group, s) not in used for s in sockets):
            return sockets
    return None


def _settle_socket(channel: dict, used: dict, console_model: str | None,
                   infos: list[str], warnings: list[str]) -> None:
    """Decision 5: a socket the change named is honoured; one it did not
    name is chosen, and the choice announces itself at INFO."""
    where = repr(channel.get("name"))
    patch = channel.get("patch") or {}
    group = patch.get("group")
    sockets = [s for s in patch.get("sockets") or [] if isinstance(s, int)]
    if not isinstance(group, str) or not sockets or group == "OFF":
        return
    text = f"{group} {'+'.join(str(s) for s in sockets)}"
    try:
        limit = facts.input_socket_limit(group, console_model)
    except facts.UnknownConsoleModel:
        limit = facts.INPUT_SOCKETS.get(group, 0)
    clash = [used[(group, s)] for s in sockets if (group, s) in used]
    if patch.get("stated"):
        if clash:
            warnings.append(
                f"channel {where}: the change names {text}, which {clash[0]} already uses -- "
                "honoured as named (one socket can feed two strips on a WING), but check "
                "that is what was meant")
        else:
            infos.append(f"channel {where}: patched to {text}, the socket the change named")
        return
    missing = [s for s in sockets if s > limit]
    if not clash and not missing:
        infos.append(
            f"channel {where}: the change named no socket, so {text} was chosen -- the first "
            "the model picked, and nothing on the desk uses it. Say the socket in the change "
            "to choose it yourself.")
        return
    chosen = _choose_sockets(group, len(sockets), used, console_model)
    why = (f"{clash[0]} already uses it" if clash
           else f"this console has no {group} {missing[0]}")
    if chosen is None:
        warnings.append(
            f"channel {where}: the change named no socket, and {text} was picked -- but {why}, "
            f"and no free {group} socket is left to choose instead. Left as picked; name the "
            "socket in the change.")
        return
    patch["sockets"] = chosen
    new = f"{group} {'+'.join(str(s) for s in chosen)}"
    infos.append(
        f"channel {where}: the change named no socket; {text} was picked, but {why}, so "
        f"{new} was chosen instead -- the first free {group} socket. Say the socket in the "
        "change to choose it yourself.")


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


def _restated(what: str) -> str:
    return (f"{what} -- not written: it restates something already running on the desk "
            "whole, and a running object is changed only through the change set's `modify`, "
            "naming each field it sets -- so nothing it did not name can move")


def _drop_not_built(word: str, name: str) -> str:
    return (f"the change drops {word} {name!r} -- not written: only a channel's strip can be "
            f"returned to free; nothing returns a {word} to free yet")


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
        "channel": "moving a running channel to another strip is a renumber, which a change "
                   "never does -- drop it and add it where you want it",
        "bank": "moving a running channel to another bank is a renumber",
        # Of a running strip's source, a change sets what the engineer
        # reasonably changes in the setup window -- `phantom`, `pair_phantom`,
        # `model`, `type` -- and not what says WHICH source the strip is.
        "source.input": "the source is how a running strip is recognised -- drop the channel "
                        "and add the new source; the settable parts of a source are "
                        "source.phantom, source.model and source.type",
        "source.pair_input": "the second row of a stereo pair is how its strip is recognised "
                             "-- drop the channel and add the new source",
        "source.stereo": "mono to stereo changes how many sockets and strips the channel "
                         "takes -- drop it and add it again",
        "source.from": SOURCE_RECORD,
        "source.quote": SOURCE_RECORD,
        "source.condition": SOURCE_RECORD,
        "processing.preset_values": PRESET_RECORD,
        "provenance": "provenance is the build's own record, not a setting",
        "inferred": "the inferred marks are the build's own record, not a setting",
    },
    "busses": {"index": "renumbering a running bus moves every send into it",
               "preset_values": PRESET_RECORD,
               "provenance": "provenance is the build's own record, not a setting",
               "inferred": "the inferred marks are the build's own record, not a setting"},
    "dcas": {"index": "renumbering a running DCA moves every strip's tag"},
    "mute_groups": {"index": "renumbering a running mute group moves every strip's tag"},
    "outputs": {"index": "renumbering a running output makes it a different Main or Matrix",
                "kind": "a Main does not become a Matrix -- drop it and add the new one",
                "provenance": "provenance is the build's own record, not a setting",
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
                   "dcas": plan_schema.DCA_SCHEMA, "mute_groups": {"type": "object"},
                   "outputs": plan_schema.OUTPUT_SCHEMA}

#: Where a running object names its preset, per kind of object.
_PRESET_NAME_PATH = {"channels": "processing.preset", "busses": "preset"}


def _preset_record(key: str, obj: dict) -> dict | None:
    """The preset values the build expanded into a running channel or bus
    (`preset_values`), or `None` for an object that carries none."""
    record = (obj.get("processing") or {}).get("preset_values") if key == "channels" \
        else obj.get("preset_values") if key == "busses" else None
    return record if isinstance(record, dict) else None


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


def _merge_modify(merged: dict, change_set: dict, text: str | None, changes: list,
                  infos: list, warnings: list, occupancy, on_desk: dict) -> list:
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
        if found is None:
            changes.append(Change(
                ChangeKind.REFUSED, word, repr(ref),
                f"the change edits it ({asked}), and no {word} of that name is on the desk"))
            continue
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
        if not problems and key == "channels" and isinstance(edited.get("source"), dict) \
                and any(p.split(".")[0] == "source" for p in paths):
            ribbon = _ribbon_with_phantom(edited["source"])
            if ribbon and not _ribbon_with_phantom(original.get("source") or {}):
                problems.append(
                    f"{ribbon!r} is a passive ribbon microphone and the change leaves it with "
                    "phantom power on -- 48V destroys a ribbon element and switching it off "
                    "again does not undo the damage; set source.phantom false in the same change")
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
            if record is not None and path == _PRESET_NAME_PATH[key]:
                amend_engine.set_path(edited, path, old)
                changes.append(Change(
                    ChangeKind.MODIFIED, word, repr(name),
                    f"{path} {amend_engine.format_value(path, old)} -> "
                    f"{amend_engine.format_value(path, new)} -- not written: the values of "
                    f"preset {old!r} were written into this {word} when it was built, and "
                    "switching a running preset would leave the plan naming one preset and "
                    "carrying the values of another. Rebuild to change it, or set the "
                    "processing fields themselves", slot=slot))
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
                    "uses -- honoured as named (one socket can feed two strips on a WING), but "
                    "check that is what was meant")

        if key == "channels":
            merged["channels"] = [edited if c is original else c for c in merged["channels"]]
        else:
            merged[key][name] = edited
        for path, old, new in kept:
            edits.append(amend_engine.FieldEdit(key=key, name=str(name), path=path,
                                                old=old, new=new, slot=slot))
    return edits


def merge_change(base: dict, change_set: dict, *, occupancy=None,
                 console_model: str | None = None, presets=None,
                 text: str | None = None) -> MergeResult:
    """Merge a change set onto the base. Pure: `base` is not modified.

    The rules, in the order they are applied:

    1. **Drops.** A dropped channel is taken out of the merged plan, so the
       back half returns its strip to free -- if the desk still reads as
       the strip this show built (`amend.release_refusal`). A drop naming
       nothing on the desk is REFUSED. A dropped bus, DCA, mute group or
       output is NOT written in this slice (nothing can return one to free
       yet) and is reported as MODIFIED, with the base's copy kept.
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
    # A base plan built before an earlier change names its outputs' patches
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
            changes.append(Change(
                ChangeKind.MODIFIED, word, repr(name), _drop_not_built(word, name)))

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
            entry.pop("index", None)
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

    # 5. Sockets.
    used = _occupied_sockets(
        merged, occupancy, leaving=frozenset(dropped_keys[key] for key in result.moved))
    for channel in kept:
        _settle_socket(channel, used, model, infos, warnings)
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
    pending = _merge_modify(merged, change_set, text, changes, infos, warnings, occupancy,
                            on_desk)

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
               console_model: str | None = None, presets=None, text: str | None = None):
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
    merge = merge_change(base, change_set, occupancy=occupancy, console_model=console_model,
                         presets=presets, text=text)
    amendment = amend_engine.plan_amendment(
        base, merge.plan, occupancy, allow_strips=allow_strips, console_model=console_model,
        by="the change", edits=merge.edits, moved=merge.moved)
    amendment.changes = merge.changes + amendment.changes
    amendment.infos = merge.infos + amendment.infos
    amendment.warnings = merge.warnings + amendment.warnings

    prior = amend_engine.amend_placements(base)
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
