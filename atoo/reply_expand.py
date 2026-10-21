"""The generator's reply, expanded into a plan (output compaction, slices 2-4;
cost reduction, slice C).

The plan had a lot of the same channel parameters over and over. On the 38-channel
festival build the model
wrote ~20K tokens of plan text, and a third of its thinking was
arithmetic: counting sockets, numbering channels, repeating one send
decision on every channel. So the model now writes LESS, and this module
writes the rest, inside `generate.generate_plan` right after the JSON is
extracted and before `GENERATION_SCHEMA` is checked. The plan on disk
keeps today's shape exactly; verify, apply, undo and the UI are untouched.

Three expansions, each detected on its own so an older full-format reply
(a replay fixture, an unconstrained provider that ignored the prompt)
still builds unchanged:

  * **omitted means null** (`fill_defaults`, slice 2). A field the reply
    leaves out makes the claim `null` makes -- "the conventions never
    said" -- and is written as null (or `[]`) here. The four rule-4b
    fields are never defaulted: the reply schema requires them.
  * **arrays, not name-keyed maps** (`expand_structure`, slice 2). The
    reply's `busses`, `outputs`, `dcas` and `mute_groups` are arrays of
    `{"name": ...}` objects, because Anthropic's structured-output subset
    cannot take an open map and this is what lets the reply
    be decoded against a schema at all. Turned back into maps here.
  * **sends per bus** (`expand_sends`, slice 3). Each bus lists its
    senders once (`sends: [{"from": [...], "mode", "level_db"}]`) and code
    writes every channel's `bus_sends` from those lists -- 14 membership
    decisions on the festival instead of 210 per-channel send objects.
    A `from` naming no channel is refused: it is a send from a strip that
    does not exist, which `patch.merge_change` refuses for the same
    reason. A group's `inferred` marker is copied onto each send, so
    verify still announces each decided mode at INFO. A group with no
    level is NOT "omitted means null": it is set to unity and marked
    (`inferred.decide_send_level`), because apply writes no level for
    null and a fresh desk's -144 would leave the send silent (a festival
    build, 2026-09-29).
  * **slips with one meaning are read** (`repair_reply`), before the
    reply's shape is checked: a missing field with one safe default, and
    an unknown field whose value says nothing. One `[repair]` note per
    kind; anything that means something is still refused.
  * **code does the mechanical parts** (`expand_mechanical`, slice 4). A
    reply channel is the input-list row it comes from (`input`, and
    `pair` for a stereo pair's second row) plus what the model decided.
    Code numbers each bank in the order written, copies the row's type,
    model and phantom, copies a stated patch off the list, takes the
    next free socket of the group the reply chose for an unstated one (a
    pair on an odd socket, skipping one to align it), applies the reply's
    `category_colors` map by the row's category, and writes `provenance`
    for each of those. Which group and which order are judgement and
    stay the model's; which number is counting. A group that runs out is
    a hard error: the model chose it, so it must choose where the
    overflow goes. An ALTERNATE patch (`alt_patch`) is
    counted the same way, in a second pass, from the sockets no main
    patch uses; the reply writes one only when the conventions state it.

  * **the Category table** (`CategoryRules`, 2026-09-30, FR-1.18a). When
    the build read the resolved conventions and their Category table is
    valid (`category_table.py`), each channel built from an input-list
    row whose category is one of an entry's aliases takes that entry's
    colour, HPF, DCA, mute group, gain, trim, fader and Main routing for
    every one of those fields the reply left out or wrote null. A value
    the reply wrote wins. A channel the instructions ask for (Talkback),
    or on a category no entry covers, gets nothing. One INFO per
    category (`reply.category-rule`), and `provenance` cites
    "category table: <category>".

  * **the instructed strips** (2026-10-01; `instructed_channels.py`). The
    resolved conventions' `## Instructed strips` block lists the strips the
    conventions ask for that are not input-list rows (sixpiece's Aux 1
    MUSIC, Aux 2 HOST, Aux 8 TALKBACK). Their sockets and strip numbers are
    held before any row is counted (`prepare_instructed_strips`), and code
    builds each one the reply did not (`build_instructed_strips`): the
    stated strip, socket, stereo pair and preset, the Category table's
    defaults for its category, and the sends and Main routing it states
    (`write_instructed_sends`; a bus's `"*"` does not reach it). An "if
    available" strip whose socket is taken is built unpatched, at INFO; any
    other conflict is built as stated and refused by verify.

Every value this module derives rather than copies is announced at INFO
(an error of judgement is not an error of patching) and
cited in the object's `provenance`, so the engineer can see what code
chose and from what.
"""

from __future__ import annotations

import copy
import json
import re

from atoo import console_facts as facts
from atoo import inferred, plan_compat, plan_schema
from atoo.diagnostics import Diagnostic, Severity
from atoo.schema_check import validate as validate_schema


class ReplyError(ValueError):
    """The reply is in the compact form but cannot be expanded into a
    plan: an unknown name, a duplicate, a group with no room. Raised
    rather than repaired, because each of these is something the model
    decided and only it can decide differently."""


# What a channel leaf is when the reply leaves it out: the same claim
# `null` makes, and the same `[]` the plan format's own examples write.
_CHANNEL_DEFAULTS = {
    "color": None,
    "dca": [],
    "mute_group": [],
    "bus_sends": [],
    "main_routes": [],
}
_SOURCE_DEFAULTS = {"type": None, "model": None, "stereo": False}
_PROCESSING_DEFAULTS = {
    "hpf_hz": None, "preset": None, "hi_cut_hz": None, "tilt_db": None,
    "trim_db": None, "balance_db": None, "invert": None, "gain_db": None,
}
_FADER_DEFAULTS = {"fader_db": None, "muted": None}
_SEND_DEFAULTS = {"level_db": None}


def is_array_form(reply: dict) -> bool:
    """Whether any of the reply's map sections was written as an array --
    the reply format's shape, checked against `REPLY_SCHEMA`."""
    return any(isinstance(reply.get(key), list) for key in plan_schema.REPLY_ARRAY_SECTIONS)


def _fill(target: dict, defaults: dict) -> int:
    filled = 0
    for key, value in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            filled += 1
    return filled


def fill_defaults(plan: dict) -> int:
    """Write the null/empty a reply left out, on every channel; returns
    how many leaves were filled. Idempotent, and a no-op on a reply that
    wrote every field (today's full format)."""
    filled = 0
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        filled += _fill(channel, _CHANNEL_DEFAULTS)
        source = channel.get("source")
        if isinstance(source, dict):
            filled += _fill(source, _SOURCE_DEFAULTS)
        if not isinstance(channel.get("processing"), dict):
            channel["processing"] = {}
            filled += 1
        filled += _fill(channel["processing"], _PROCESSING_DEFAULTS)
        if not isinstance(channel.get("fader"), dict):
            channel["fader"] = {}
            filled += 1
        filled += _fill(channel["fader"], _FADER_DEFAULTS)
        for send in channel.get("bus_sends") or []:
            if isinstance(send, dict):
                filled += _fill(send, _SEND_DEFAULTS)
    for key in ("dcas", "mute_groups"):
        if key not in plan:
            plan[key] = {}
            filled += 1
    return filled


def _accepts_null(schema: dict) -> bool:
    """Whether a property's schema takes null as a value."""
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    if "enum" in schema and None in schema["enum"]:
        return True
    return any(_accepts_null(b) for b in schema.get("oneOf", []) if isinstance(b, dict))


def _object_branch(schema: dict) -> dict:
    """The schema to walk a dict against: `schema`, or its object branch
    when it is a `oneOf` (a destination: an object or null)."""
    for branch in schema.get("oneOf", []):
        if isinstance(branch, dict) and (branch.get("type") == "object" or "properties" in branch):
            return branch
    return schema


def drop_null_optionals(value, schema: dict) -> int:
    """Drop, in place, every null that says nothing: a null under a key
    the format does not have, and a null in an OPTIONAL field whose type
    does not take null (an output's `fader`, an `inferred` list). Returns
    how many were dropped.

    A smaller hosted model writes null for everything it has nothing to
    say about (Haiku 4.5's smallband outputs, 2026-09-28: `fader: null`,
    `destination: null` on a Main), and each of those failed the build
    as a shape error. Null is the claim "the conventions never said",
    and a field that is absent makes the same claim -- so a null where
    null cannot be written is read as the absence it means. A REQUIRED
    field's null is kept: the validator then names it, which is right
    for a rule-4b field. An unknown key with a value is kept too, and
    still fails: it says something, and that something has no home.
    """
    dropped = 0
    schema = _object_branch(schema)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        extra = schema.get("additionalProperties", True)
        for key in list(value):
            child = value[key]
            if key in properties:
                spec = properties[key]
                if child is None and key not in required and not _accepts_null(spec):
                    del value[key]
                    dropped += 1
                elif child is not None:
                    dropped += drop_null_optionals(child, spec)
            elif child is None and extra is False:
                del value[key]
                dropped += 1
            elif isinstance(extra, dict):
                dropped += drop_null_optionals(child, extra)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for item in value:
            dropped += drop_null_optionals(item, schema["items"])
    return dropped


# --------------------------------------------------------------------------
# repair: what a model left out or added that has only one meaning
# --------------------------------------------------------------------------

# A REQUIRED field a reply may leave out because its absence has one safe
# meaning: (where, field, value, why). `where` is the path of the objects
# that carry it -- () the reply itself, ("outputs",) each output,
# ("busses", "sends") each send group of each bus. Deliberately a list and
# not a rule: a rule-4b field (a bus's width, a send's mode) or a channel's
# input has no safe default, and stays refused by the schema check.
_MISSING_DEFAULTS = (
    ((), "unassigned_inputs", [],
     "an empty list: no row left out on purpose, so code builds every input-list row "
     "no channel names"),
    ((), "notes", [], "an empty list: nothing to report"),
    (("outputs",), "patch", None,
     "null, not stated: a Main that only feeds a Matrix has no socket of its own, and "
     "verify warns about a null patch on an output nothing carries to a socket"),
    (("busses", "sends"), "level_db", None,
     "null, not stated. The level is then decided, unity, and reported at INFO "
     "(inferred.send-level)"),
)

# Unknown keys whose `false` is NOT the absence of anything: a send
# switched off, a strip disabled. Dropping one would switch it on, so it
# is refused like any other unknown key with a value.
_SWITCH_KEYS = frozenset({"on", "enabled", "active"})


def _says_nothing(key: str, value) -> bool:
    if value is None or value == [] or value == "":
        return True
    return value is False and key not in _SWITCH_KEYS


def _objects_at(reply: dict, where: tuple) -> list[dict]:
    found = [reply]
    for key in where:
        found = [item for obj in found for item in (obj.get(key) or [])
                 if isinstance(obj.get(key), list) and isinstance(item, dict)]
    return found


def _drop_unmarkable(value, schema: dict, path: str, stray: dict) -> None:
    """Drop each `inferred` marker whose `field` the schema does not allow
    on that object -- Haiku's sixpiece reply of 2026-09-29 marked `mono`
    as decided on a Matrix, which carries no width. Same rule as the
    plan-side repair: a marker naming a field the object cannot carry
    announces nothing, so it is dropped and said, never refused."""
    schema = _object_branch(schema)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        marks = value.get("inferred")
        allowed = (((_object_branch(properties.get("inferred", {})).get("items") or {})
                    .get("properties", {}).get("field", {})).get("enum"))
        if isinstance(marks, list) and allowed:
            kept = [m for m in marks if not isinstance(m, dict) or m.get("field") in allowed]
            for m in marks:
                if m not in kept:
                    kind = (path, str(m.get("field")))
                    stray[kind] = stray.get(kind, 0) + 1
            value["inferred"] = kept
        for key, child in value.items():
            if key in properties and key != "inferred":
                _drop_unmarkable(child, properties[key], f"{path}.{key}", stray)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for item in value:
            _drop_unmarkable(item, schema["items"], f"{path}[*]", stray)


def _drop_unknown_empty(value, schema: dict, path: str, dropped: dict) -> None:
    schema = _object_branch(schema)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key in list(value):
            child = value[key]
            if key in properties:
                _drop_unknown_empty(child, properties[key], f"{path}.{key}", dropped)
            elif extra is False and _says_nothing(key, child):
                del value[key]
                kind = (path, key, json.dumps(child))
                dropped[kind] = dropped.get(kind, 0) + 1
            elif isinstance(extra, dict):
                _drop_unknown_empty(child, extra, f"{path}.{key}", dropped)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for item in value:
            _drop_unknown_empty(item, schema["items"], f"{path}[*]", dropped)


def repair_reply(reply: dict) -> list[str]:
    """Before the reply is checked against `REPLY_SCHEMA`: fill each
    required field in `_MISSING_DEFAULTS` the reply left out, and drop
    each unknown field whose value says nothing (`false`, `null`, `[]`,
    `""`). In place; returns one repair note per kind, not per occurrence.

    Haiku is never sent the schema, and its smallband reply of
    2026-09-29 failed on exactly these: no `unassigned_inputs`, no `patch`
    on a Main that only feeds a Matrix, `"muted": false` on every send
    group and `"mono": false` on a Matrix. Each has one meaning, so each
    is read, and said so. An unknown field with a value that means
    something (`"muted": true`, `"mono": true`, `"on": false`) is kept and
    still refused: a muted send cannot be silently un-muted. A missing
    field with no safe default is left for the schema check to refuse.
    """
    notes: list[str] = []
    for where, field, default, why in _MISSING_DEFAULTS:
        filled = 0
        for obj in _objects_at(reply, where):
            if field not in obj:
                obj[field] = copy.deepcopy(default)
                filled += 1
        if filled:
            path = "reply" + "".join(f".{k}[*]" for k in where)
            notes.append(f"{path}: {field!r} left out {'once' if filled == 1 else f'{filled} times'}"
                         f"; read as {why}")
    # An unassigned row by bare name, as every reply before 2026-09-29
    # wrote it: read as a row named with no quote -- which code builds
    # (`build_left_out_rows`), because nothing the engineer wrote was
    # cited for leaving it out.
    bare = [n for n in reply.get("unassigned_inputs") or [] if isinstance(n, str)]
    if bare and isinstance(reply.get("unassigned_inputs"), list):
        reply["unassigned_inputs"] = [{"input": n, "quote": ""} if isinstance(n, str) else n
                                      for n in reply["unassigned_inputs"]]
        notes.append(f"reply.unassigned_inputs: {len(bare)} row(s) named with no quote "
                     f"({', '.join(bare)}) -- read as unquoted, so each is built unless a "
                     "quote says to leave it out")
    uncoloured = [e for e in (reply.get("category_colors") or [])
                  if isinstance(e, dict) and e.get("color") in (None, "")]
    if uncoloured:
        reply["category_colors"] = [e for e in reply["category_colors"] if e not in uncoloured]
        names = ", ".join(repr(e.get("category")) for e in uncoloured)
        notes.append(f"reply.category_colors: {names} given no colour -- dropped from the map, "
                     "so that category's channels take no colour from it")
    notes.extend(_drop_channel_stated(reply))
    notes.extend(_move_processing_notes(reply))
    stray: dict = {}
    _drop_unmarkable(reply, plan_schema.REPLY_SCHEMA, "reply", stray)
    for (path, field), count in stray.items():
        notes.append(f"{path}.inferred: dropped a marker for {field!r} "
                     f"{'once' if count == 1 else f'{count} times'} -- this object has no "
                     f"{field!r} to decide, so the marker announces nothing")
    dropped: dict = {}
    _drop_unknown_empty(reply, plan_schema.REPLY_SCHEMA, "reply", dropped)
    for (path, key, shown), count in dropped.items():
        notes.append(f"{path}: dropped {key!r}: {shown} "
                     f"{'once' if count == 1 else f'{count} times'} -- not a field this format "
                     f"has, and {shown} says nothing")
    return notes


def _drop_channel_stated(reply: dict) -> list[str]:
    """A compact channel's `patch.stated`, dropped -- true or false.

    A reply's channel patch is `{group, sockets}`; whether a socket is
    STATED is not the model's to say, because the input list is
    authoritative for it and `expand_mechanical` reads it from there
    (a stated row's socket is copied off the list, and marked so). Haiku's
    second sixpiece reply of 2026-09-29 wrote `"stated": true` on the
    Talkback channel it built from the instructions -- whose socket code
    then checks against the quoted sentence anyway. Either value is
    redundant, so it is dropped and said once."""
    names = []
    for channel in reply.get("channels") or []:
        patch = channel.get("patch") if isinstance(channel, dict) else None
        if isinstance(patch, dict) and "stated" in patch:
            del patch["stated"]
            names.append(str(channel.get("input") or channel.get("name") or "?"))
    if not names:
        return []
    return [f"reply.channels[*].patch: dropped 'stated' on {', '.join(names)} -- not a field "
            "a reply channel has; whether a socket is stated is read from the input list "
            "(and, for a channel built from the instructions, from the sentence it quotes)"]


def _move_processing_notes(reply: dict) -> list[str]:
    """A bus's or channel's `processing.notes`, moved to the plan's
    top-level `notes`, never lost.

    It is not a field: it is free text the model meant as a note --
    Haiku's sixpiece reply of 2026-09-29 wrote the Drums Comp compressor
    settings there ("No Stressor, threshold -20dB, attack 20ms, release
    50ms"), which the format cannot set. So it is kept, as the model's own
    note naming the strip, where the engineer reads the others. A value
    that is not text is left for the schema check to refuse."""
    moved = []
    for section, key in (("busses", "name"), ("channels", "input")):
        for item in reply.get(section) or []:
            processing = item.get("processing") if isinstance(item, dict) else None
            if not isinstance(processing, dict) or not isinstance(processing.get("notes"), str):
                continue
            text = processing.pop("notes").strip()
            label = str(item.get(key) or item.get("name") or "?")
            if text:
                if not isinstance(reply.get("notes"), list):
                    reply["notes"] = [] if reply.get("notes") is None else [reply["notes"]]
                reply["notes"].append({"text": f"{label}: {text}", "source": "model"})
            moved.append(f"{section} {label!r}")
    if not moved:
        return []
    return [f"reply.*.processing: moved 'notes' on {', '.join(moved)} to the plan's notes -- "
            "not a field processing has; the text is kept as the model's note"]


def _named_map(items: list, section: str) -> dict:
    """`[{"name": "MON1", ...}, ...]` -> `{"MON1": {...}, ...}`, in order.
    Two entries with one name is refused: a map cannot hold both, and
    keeping either would silently drop a bus the model wrote."""
    out: dict = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ReplyError(f"{section}[{i}] is not an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ReplyError(f"{section}[{i}] has no name")
        if name in out:
            raise ReplyError(f"{section}: {name!r} is written twice")
        entry = {k: v for k, v in item.items() if k != "name"}
        out[name] = entry
    return out


def _normalise_old_keys(reply: dict) -> None:
    """The courtesy, before the reply is checked: an output's or a
    dedicated-output destination's `socket`/`sockets` meant `patch`/
    `patches`, and a model that reached for the old names is not refused
    for it (`plan_compat`). In place, on the array-form sections."""
    for i, item in enumerate(reply.get("outputs") or []):
        if isinstance(item, dict):
            reply["outputs"][i] = plan_compat.normalise_entry(item)
    for bus in reply.get("busses") or []:
        if not isinstance(bus, dict):
            continue
        if "destination" in bus:
            bus["destination"] = plan_compat.normalise_entry(bus["destination"])
        many = bus.get("destinations")
        if isinstance(many, list):
            bus["destinations"] = [plan_compat.normalise_entry(d) for d in many]


def expand_structure(plan: dict) -> None:
    """Every array section of the reply becomes the map the plan holds.
    In place; a section already a map is left alone."""
    for section in plan_schema.REPLY_ARRAY_SECTIONS:
        items = plan.get(section)
        if isinstance(items, list):
            plan[section] = _named_map(items, section)


# --------------------------------------------------------------------------
# slice 3: sends per bus
# --------------------------------------------------------------------------

EVERY_CHANNEL = "*"


def _channel_lookup(plan: dict) -> dict[str, list[dict]]:
    """Every name a `from` entry may use, to the channels it means: the
    strip's `name` and its input-list name (`source.input`), which are
    the same on most channels and both the model's own words."""
    lookup: dict[str, list[dict]] = {}
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        for key in (channel.get("name"), (channel.get("source") or {}).get("input")):
            if isinstance(key, str) and key.strip():
                bucket = lookup.setdefault(key.strip(), [])
                if channel not in bucket:
                    bucket.append(channel)
    return lookup


def expand_sends(plan: dict, findings: list | None = None, exclude: dict | None = None) -> int:
    """Write each channel's `bus_sends` from the busses' `sends` groups,
    in place, and take the groups off the busses. Returns how many sends
    were written. A bus with no `sends` key is left alone (a full-format
    reply, or a bus nothing sends to).

    `exclude` (`id(channel) -> strip`) are the instructed strips code
    built: a group's `"*"` (every channel) does not reach them -- their
    sends are the ones the conventions state (`write_instructed_sends`)
    -- but a group naming one does."""
    lookup = _channel_lookup(plan)
    channels = [c for c in plan.get("channels") or [] if isinstance(c, dict)
                and id(c) not in (exclude or {})]
    written = 0
    summary: list[str] = []
    for bus_name, bus in (plan.get("busses") or {}).items():
        if not isinstance(bus, dict) or "sends" not in bus:
            continue
        groups = bus.pop("sends") or []
        if not isinstance(groups, list):
            raise ReplyError(f"busses[{bus_name}].sends is not an array")
        senders: dict[int, dict] = {}   # id(channel) -> that channel
        for g, group in enumerate(groups):
            if not isinstance(group, dict):
                raise ReplyError(f"busses[{bus_name}].sends[{g}] is not an object")
            names = group.get("from")
            if isinstance(names, str):
                names = [names]
            if not isinstance(names, list):
                raise ReplyError(f"busses[{bus_name}].sends[{g}] has no 'from' list")
            targets: list[dict] = []
            for name in names:
                if name == EVERY_CHANNEL:
                    targets.extend(channels)
                    continue
                found = lookup.get(str(name).strip())
                if not found:
                    known = ", ".join(sorted(lookup))
                    raise ReplyError(
                        f"busses[{bus_name}].sends[{g}] names {name!r}, which is no channel "
                        f"of this plan -- a send from a strip that does not exist. "
                        f"Channels: {known}")
                targets.extend(found)
            send = {"bus": bus_name, "mode": group.get("mode"),
                    "level_db": group.get("level_db")}
            if group.get("inferred"):
                send["inferred"] = copy.deepcopy(group["inferred"])
            if send["level_db"] is None:
                # Never left null: apply writes no level for null, and a
                # fresh desk's -144 would leave the send on and silent.
                # Decided here by
                # the same rule verify and apply use, and marked, so
                # verify announces it (`inferred.send-level`).
                inferred.decide_send_level(send, bus_name)
            cite = group.get("provenance")
            for channel in targets:
                entry = copy.deepcopy(send)
                sends = channel.setdefault("bus_sends", [])
                if not isinstance(sends, list):
                    sends = channel["bus_sends"] = []
                # A later group naming this channel replaces the earlier
                # send into the same bus: one channel at another level.
                sends[:] = [s for s in sends if not (isinstance(s, dict) and s.get("bus") == bus_name)]
                sends.append(entry)
                senders[id(channel)] = channel
                provenance = channel.setdefault("provenance", {})
                if isinstance(provenance, dict):
                    line = f"{bus_name}: {cite}" if cite else f"{bus_name} ({send['mode']})"
                    lines = [x for x in str(provenance.get("bus_sends") or "").split("; ")
                             if x and not x.startswith(f"{bus_name}: ") and x != f"{bus_name} ({send['mode']})"]
                    provenance["bus_sends"] = "; ".join(lines + [line])
                written += 1
        if groups:
            summary.append(f"{bus_name} <- {len(senders)} of {len(channels)}"
                           + (" (every channel)" if len(senders) == len(channels) else ""))
    if findings is not None and summary:
        findings.append(_info(
            "reply.sends-expanded", "plan",
            f"each channel's bus_sends written from the busses' sender lists "
            f"({written} sends): " + "; ".join(summary)))
    return written


# --------------------------------------------------------------------------
# slice 4: code does the mechanical parts
# --------------------------------------------------------------------------

# The socket group an unstated row goes to when the reply names none:
# the small-rig default the compiler always used (requirements.md,
# FR-1.10), said at INFO when it is taken.
DEFAULT_SOCKET_GROUP = "LCL"

# The order a plan's channel keys are written in, the same as the plan
# format's own example, so a plan built from a reply reads like one
# built from a full reply.
_CHANNEL_KEY_ORDER = ("channel", "bank", "name", "color", "source", "patch", "alt_patch",
                      "processing",
                      "fader", "dca", "mute_group", "bus_sends", "main_routes", "provenance",
                      "inferred")


def _norm(name) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().casefold()


def is_compact_channel(channel) -> bool:
    """A channel written the reply's way: it names its `input` at the top
    and carries no `source` (a full-format channel has both under
    `source`)."""
    return isinstance(channel, dict) and "input" in channel and "source" not in channel


def has_compact_channels(plan: dict) -> bool:
    return any(is_compact_channel(c) for c in plan.get("channels") or [])


class _Sockets:
    """The input sockets already spoken for, per group, and the next
    free one: every socket the input list states (FR-1.10: never handed
    out to another row), every socket a reply channel names, and each
    one this pass gives out."""

    def __init__(self, rows, console_model):
        from atoo.input_list import parse_socket_spec
        self.console_model = console_model
        self.used: dict[str, set[int]] = {}
        for row in rows:
            if row.patch:
                parsed = parse_socket_spec(row.patch)
                if parsed:
                    self.take(*parsed)

    def take(self, group: str, *numbers: int) -> None:
        self.used.setdefault(group, set()).update(numbers)

    def limit(self, group: str) -> int:
        return facts.input_socket_limit(group, self.console_model)

    def next_free(self, group: str, count: int) -> tuple[list[int], list[int]]:
        """The next `count` consecutive free sockets of `group` (a pair
        starting on an odd socket), and the sockets skipped to get
        there. Empty when the group has no room."""
        used = self.used.setdefault(group, set())
        limit = self.limit(group)
        skipped: list[int] = []
        n = 1
        while n + count - 1 <= limit:
            if n in used:
                n += 1
                continue
            if count == 2 and (n % 2 == 0 or n + 1 in used):
                skipped.append(n)
                n += 1
                continue
            return list(range(n, n + count)), skipped
        return [], skipped


def _row_lookup(rows) -> dict:
    return {_norm(row.name): row for row in rows}


def _resolve_instructed(channel: dict, label: str, rows, layers, console_model,
                        repairs: list[str]) -> dict:
    """A compact channel whose `input` is no row of the list: built only
    when the conventions or instructions ask for it AND state its source
    socket (`instructed_channels.py`). Returns
    `{quote, layer, group, sockets, cited_by}`; raises `ReplyError` for a
    channel with no verifiable quote or no stated socket -- that one is
    invented, and rule 2 still holds."""
    from atoo import instructed_channels as ic
    from atoo.input_list import format_socket

    input_name = channel.get("input")
    refused = (f"{label}: input {input_name!r} is not a row of the input list (rule 2: invent "
               "nothing)")
    rows_named = " Rows: " + ", ".join(r.name for r in rows)
    quotes = ic.candidate_quotes(channel)
    if not quotes:
        raise ReplyError(f"{refused}, and the reply quotes no line of the conventions or "
                         "instructions asking for it." + rows_named)
    if not layers:
        raise ReplyError(f"{refused}. The reply quotes {quotes[0]!r} for it, but no conventions "
                         "or instructions were given to check that quote against." + rows_named)
    hit = ic.first_found(quotes, layers)
    if hit is None:
        raise ReplyError(f"{refused}, and what the reply quotes for it ({quotes[0]!r}) "
                         f"{ic.not_found_reason(quotes[0], layers)}." + rows_named)
    quote, layer = hit
    # Stated in the quote, or in the line it was quoted from.
    stated = ic.sockets_for(quote, layer)
    if not stated:
        raise ReplyError(f"{refused}. {layer.name} asks for it ({quote!r}) but states no source "
                         "socket for it, so there is nowhere to patch it; state one, as a group "
                         "and number like 'A 40' or 'LCL 3'." + rows_named)
    explicit = channel.get("patch") if isinstance(channel.get("patch"), dict) else {}
    want = (explicit.get("group"), (explicit.get("sockets") or [None])[0])
    if want in stated:
        group, first = want
    elif len(stated) == 1:
        group, first = stated[0]
        if explicit.get("sockets"):
            repairs.append(f"{label}: the reply patched {input_name!r} to "
                           f"{explicit.get('group')} {explicit['sockets']}, but {layer.name} "
                           f"states {format_socket(group, first)}; the stated socket wins")
    else:
        raise ReplyError(f"{label}: {layer.name} asks for {input_name!r} ({quote!r}) and names "
                         f"more than one socket ({', '.join(format_socket(*s) for s in stated)}); "
                         "the reply must say which with \"patch\"")
    stereo = bool(channel.get("stereo"))
    # A channel number the text states is the number, as its socket is:
    # "Setup Talkback on Channel 40" goes on ch 40 whether or not the
    # reply wrote `channel` (sixpiece, 2026-09-29: Haiku left it out and
    # the strip was counted onto ch 24).
    number = ic.stated_channel(quote, layer)
    if number is not None and channel.get("channel") not in (None, number):
        repairs.append(f"{label}: the reply placed {input_name!r} on channel "
                       f"{channel['channel']}, but {layer.name} states channel {number}; the "
                       "stated channel wins")
    return {"quote": quote, "layer": layer, "group": group,
            "sockets": [first, first + 1] if stereo else [first], "channel": number}


def expand_mechanical(plan: dict, rows, *, console_model: str | None,
                      findings: list | None = None, pairs: dict | None = None,
                      layers: list | None = None, category_table=None,
                      strips=None, built: dict | None = None) -> list[str]:
    """Every compact channel becomes a full one, in place, from the input
    list's rows. Returns repair notes; INFO findings go to `findings`.
    A full-format channel is left as it is. `pairs`, when given, is filled
    with `id(channel) -> the pair's second row` for each stereo channel the
    reply paired; the plan names that row too, as `source.pair_input`, so
    verify can count it built when the input list states no socket for it.

    `layers` are the conventions and instructions the build was given
    (`conventions_audit.Layer`). A channel naming no row is built from
    them only when it quotes a line of them that states its source socket
    (`_resolve_instructed`); without them every such channel is refused.

    `category_table`, when given (a checked `category_table.Table`), fills
    each field a channel's reply left out from its row's category
    (`CategoryRules`); a channel not built from a row gets nothing from it.

    `strips` are the resolved conventions' instructed strips
    (`instructed_channels.Strip`, 2026-10-01): their stated sockets and
    strip numbers are held before any row is counted, and code builds each
    one (`prepare_instructed_strips`, `build_instructed_strips`); `built`
    is filled with `id(channel) -> strip` for `expand_sends`."""
    from atoo.input_list import format_socket, parse_socket_spec

    channels = [c for c in plan.get("channels") or [] if isinstance(c, dict)]
    if not any(is_compact_channel(c) for c in channels):
        plan.pop("category_colors", None)
        return []
    by_name = _row_lookup(rows)
    sockets = _Sockets(rows, console_model)
    # Sockets a channel names outright are taken before any is counted.
    for channel in channels:
        patch = channel.get("patch") if is_compact_channel(channel) else channel.get("patch")
        if isinstance(patch, dict) and patch.get("group") and patch.get("sockets"):
            sockets.take(patch["group"], *[n for n in patch["sockets"] if isinstance(n, int)])

    # The strips the resolved conventions ask for (2026-10-01): their
    # sockets and strip numbers held before any row is counted, and a
    # reply channel that is one of them merged into it.
    reserved: dict[str, set[int]] = {}
    strip_work = (prepare_instructed_strips(plan, strips, rows, sockets=sockets,
                                            reserved=reserved, findings=findings)
                  if strips else [])
    channels = [c for c in plan.get("channels") or [] if isinstance(c, dict)]

    # Channels the conventions or instructions ask for, not on the list:
    # resolved first, so their stated sockets are taken before any
    # unstated row is counted onto one.
    instructed: dict[int, dict] = {}
    repairs: list[str] = []
    for i, channel in enumerate(channels):
        if is_compact_channel(channel) and by_name.get(_norm(channel.get("input"))) is None:
            if channel.get("pair"):
                raise ReplyError(f"channels[{i}]: input {channel.get('input')!r} is not a row of "
                                 "the input list, and a pair is two rows of it")
            found = _resolve_instructed(channel, f"channels[{i}]", rows, layers, console_model,
                                        repairs)
            instructed[id(channel)] = found
            sockets.take(found["group"], *found["sockets"])

    # A channel number the conventions or instructions state is held for
    # that strip; the counted ones step round it.
    for channel in channels:
        found = instructed.get(id(channel))
        if found and found.get("channel") is not None:
            reserved.setdefault(channel.get("bank") or "ch", set()).add(found["channel"])

    colours = _category_colours(plan.pop("category_colors", None))
    rules = CategoryRules(category_table, plan)
    pending_alts: list[tuple[dict, dict, bool, str]] = []
    counters: dict[str, int] = {}
    paired: set[str] = set()
    numbered: dict[str, list[int]] = {}
    chosen: dict[str, list[str]] = {}
    coloured: dict[str, list[str]] = {}
    own_colour: list[str] = []
    null_colour: list[str] = []
    for i, channel in enumerate(channels):
        if not is_compact_channel(channel):
            continue
        label = f"channels[{i}]"
        input_name = channel.get("input")
        row = by_name.get(_norm(input_name))
        if row is None:
            _expand_instructed(channel, instructed[id(channel)], counters, numbered, colours,
                               findings, reserved)
            continue
        pair_row = None
        if channel.get("pair"):
            pair_row = by_name.get(_norm(channel["pair"]))
            if pair_row is None:
                raise ReplyError(f"{label}: pair {channel['pair']!r} is not a row of the input list")
        stereo = bool(pair_row) or bool(channel.get("stereo"))
        bank = channel.get("bank") or "ch"
        number = channel.get("channel") or _next_number(counters, bank, reserved)
        counters[bank] = number
        numbered.setdefault(bank, []).append(number)
        name = channel.get("name") or row.name
        if len(name) > facts.NAME_MAX_CHARS:
            cut = name[:facts.NAME_MAX_CHARS]
            if findings is not None:
                findings.append(_info("reply.name-cut", f"channels[{name}]",
                                      f"{name!r} is longer than the {facts.NAME_MAX_CHARS} characters "
                                      f"the console shows; the strip is named {cut!r}"))
            name = cut
        where = f"channels[{name}]"
        provenance = channel.get("provenance") if isinstance(channel.get("provenance"), dict) else {}
        provenance = dict(provenance)

        # -- patch: the list's, the reply's, or the next free one --------
        explicit = channel.get("patch") if isinstance(channel.get("patch"), dict) else {}
        stated = parse_socket_spec(row.patch) if row.patch else None
        pair_stated = parse_socket_spec(pair_row.patch) if pair_row and pair_row.patch else None
        if stated:
            group, first = stated
            if pair_stated and pair_stated[0] == group:
                numbers = [first, pair_stated[1]]
            elif stereo:
                numbers = [first, first + 1]
            else:
                numbers = [first]
            if explicit.get("sockets") and list(explicit["sockets"]) != numbers:
                repairs.append(f"{where}: the reply patched it to {explicit.get('group', group)} "
                               f"{explicit['sockets']}, but the input list states "
                               f"{format_socket(group, first)}; the list wins (rule 3)")
            sockets.take(group, *numbers)
            cite = f"Input list patch column: {row.patch!r}"
            if pair_row and pair_row.patch:
                cite += f" and {pair_row.patch!r}"
            patch = {"group": group, "sockets": numbers, "stated": True}
        elif explicit.get("sockets"):
            group = explicit.get("group") or DEFAULT_SOCKET_GROUP
            numbers = list(explicit["sockets"])
            patch = {"group": group, "sockets": numbers, "stated": False}
            cite = provenance.get("patch") or (
                f"the reply chose {format_socket(group, numbers[0])}"
                + (f"-{numbers[-1]}" if len(numbers) > 1 else ""))
        else:
            group = explicit.get("group")
            if not group:
                group = DEFAULT_SOCKET_GROUP
                if findings is not None:
                    findings.append(_info(
                        "reply.socket-group-assumed", where,
                        f"the reply named no socket group for {row.name!r} and the input list "
                        f"states no patch; taken as {group}, the group a small rig cables into"))
            numbers, skipped = sockets.next_free(group, 2 if stereo else 1)
            if not numbers:
                taken = sorted(sockets.used.get(group, ()))
                raise ReplyError(
                    f"{where}: no room in {group} for {'a stereo pair' if stereo else 'a socket'}: "
                    f"{group} 1-{sockets.limit(group)} on this console, and "
                    f"{format_socket(group, taken[0]) if taken else 'none'}"
                    f"{' to ' + str(taken[-1]) if len(taken) > 1 else ''} already taken "
                    f"({len(taken)} sockets). The reply chose the group, so it must choose "
                    "where the overflow goes")
            for n in skipped:
                if findings is not None:
                    findings.append(_info(
                        "reply.socket-skipped", where,
                        f"{format_socket(group, n)} left empty so the stereo pair {row.name!r} "
                        f"starts on an odd socket ({format_socket(group, numbers[0])}-{numbers[1]}); "
                        "a WING forms a pair from [odd, even] only"))
            sockets.take(group, *numbers)
            patch = {"group": group, "sockets": numbers, "stated": False}
            spelled = format_socket(group, numbers[0]) + (f"-{numbers[-1]}" if len(numbers) > 1 else "")
            chosen.setdefault(group, []).append(f"{name} {spelled}")
            cite = (f"next free {group} socket in channel order ({spelled}): the reply chose "
                    f"the group, code the number")
        if "patch" in provenance and provenance["patch"] != cite and not explicit.get("sockets"):
            cite = f"{cite}; reply: {provenance['patch']}"
        provenance["patch"] = cite

        # -- colour: the channel's own, else the category map's ----------
        # A `color: null` is "not stated", like an absent key (review
        # 2026-09-28, R7): the module's rule is that
        # omitted means null, and the prompt asks for `color` only when it
        # is not the category's. Haiku writes null for every field it has
        # nothing to say about, so reading null as "deliberately
        # uncoloured" silently lost every category colour. The INFO names
        # each channel whose null was read this way.
        if channel.get("color") is not None:
            color = channel["color"]
            own_colour.append(f"{name} {color}")
        else:
            color = colours.get(_norm(row.category))
            if color is not None:
                coloured.setdefault(f"{row.category} -> {color}", []).append(name)
                provenance.setdefault("color", f"category map: {row.category} -> {color}")
                if "color" in channel:
                    null_colour.append(name)
        if "channel" not in provenance:
            provenance["channel"] = (f"numbered {bank} {number} in the order the reply listed it"
                                     if "channel" not in channel else
                                     f"the reply placed it at {bank} {number}")
        written = _written_fields(channel, color)

        phantom = row.phantom
        if pair_row is not None:
            phantom = _pair_phantom(row, pair_row, where, findings)
        full = {
            "channel": number,
            "bank": bank,
            "name": name,
            "color": color,
            "source": {"input": row.name, "type": row.type or None, "model": row.model or None,
                       "stereo": stereo, "phantom": phantom,
                       # The pair's second row, by name: the one thing
                       # that says a row with no stated socket is built.
                       # ... and the value written for its socket, which
                       # is the pair's: the desk switches both together.
                       **({"pair_input": pair_row.name, "pair_phantom": phantom}
                          if pair_row is not None else {})},
            "patch": patch,
            "processing": dict(channel.get("processing") or {}),
            "fader": dict(channel.get("fader") or {}),
            "dca": list(channel.get("dca") or []),
            "mute_group": list(channel.get("mute_group") or []),
            "bus_sends": list(channel.get("bus_sends") or []),
            "main_routes": list(channel.get("main_routes") or []),
            "provenance": provenance,
        }
        if channel.get("inferred"):
            full["inferred"] = channel["inferred"]
        rules.apply(full, row, written)
        alt = channel.get("alt_patch")
        channel.clear()
        channel.update(full)
        if pair_row is not None:
            paired.add(_norm(pair_row.name))
        if pairs is not None and pair_row is not None:
            pairs[id(channel)] = pair_row
        if isinstance(alt, dict) and alt.get("group"):
            pending_alts.append((channel, alt, stereo, where))

    # The instructed strips no row is, before the left-out rows take the
    # lowest free strips; the ones a row is, once every row has a channel.
    added = build_instructed_strips(
        plan, [w for w in strip_work if w["row"] is None], rules=rules, colours=colours,
        reserved=reserved, findings=findings, built=built)
    channels.extend(added)

    # Every row no channel names and nothing the engineer wrote leaves
    # out is built here, before the alternates are
    # counted, so they see its socket.
    added = build_left_out_rows(plan, rows, sockets=sockets, claimed=paired, colours=colours,
                                chosen=chosen, layers=layers, findings=findings, rules=rules)
    for channel in added:
        numbered.setdefault(channel["bank"], []).append(channel["channel"])
    channels.extend(added)
    build_instructed_strips(plan, [w for w in strip_work if w["row"] is not None], rules=rules,
                            colours=colours, reserved=reserved, findings=findings, built=built)
    alt_chosen = _expand_alt_patches(channels, pending_alts, rows, console_model, repairs)

    if findings is not None:
        parts = []
        for bank, numbers in numbered.items():
            runs = ", ".join(_runs(numbers))
            parts.append(f"{bank} {runs}")
        findings.append(_info("reply.channels-numbered", "plan",
                              "channels numbered in the order the reply listed them: "
                              + "; ".join(parts)))
        for group, names in chosen.items():
            findings.append(_info(
                "reply.sockets-chosen", "plan",
                f"{group}: the reply chose the group, code the next free socket in channel "
                f"order -- " + ", ".join(names)))
        for group, names in alt_chosen.items():
            findings.append(_info(
                "reply.alt-sockets-chosen", "plan",
                f"alternate inputs from {group}, as the conventions state: code the next "
                f"{group} socket no main patch uses and the input list does not state, in "
                f"channel order -- " + ", ".join(names)))
        if coloured or own_colour:
            text = "; ".join(f"{key} ({len(names)}: {', '.join(names)})"
                             for key, names in coloured.items())
            if own_colour:
                text += ("; " if text else "") + "stated for the channel alone: " + ", ".join(own_colour)
            if null_colour:
                text += ("; the reply's color: null read as not stated, so the category map "
                         "applies: " + ", ".join(null_colour))
            findings.append(_info("reply.colours-applied", "plan",
                                  "colour applied from the reply's category map by each "
                                  "input-list row's category: " + text))
        findings.extend(rules.findings())
    return repairs


def _unassigned_quote_layers(row, layers) -> list:
    """What a quote leaving `row` out is checked against: the conventions,
    the instructions, and that row's own notes -- "not patched for this
    event" is the engineer's word about that row, and only that row."""
    from atoo.conventions_audit import Layer

    out = list(layers or [])
    if getattr(row, "notes", ""):
        out.append(Layer("input list", f"the input list's notes for {row.name!r}", row.notes))
    return out


def build_left_out_rows(plan: dict, rows, *, sockets: "_Sockets", claimed: set,
                        colours: dict, chosen: dict, layers=None,
                        findings: list | None = None,
                        rules: "CategoryRules | None" = None) -> list[dict]:
    """Every input-list row no channel names is built as a channel, unless
    the reply's `unassigned_inputs` leaves it out with a quote that is
    really in the conventions, the instructions or that row's own notes.
    Returns the channels added (already appended to
    `plan["channels"]`) and rewrites `unassigned_inputs` to the rows
    validly left out, as `{input, quote, from}`.

    The evidence: Haiku's festival reply left 14 rows out, and its
    smallband reply dropped Playback without a word. A dropped input is
    the worst failure there is (rule 1), and whether a row is on the desk
    is not the model's to decide silently: the engineer says so, or it is
    built. A built row is a judgement that can displease -- a strip nobody
    uses -- where a dropped one is a dead microphone at soundcheck.

    An added row takes its own fields (name, type, model, phantom, stated
    patch, preset via the list's column) and the next free strip of the
    `ch` bank; an unstated socket is counted from the group the reply used
    most for unstated rows (else `LCL`), and a row whose notes or model
    say "stereo" is a stereo channel on an odd socket. It has no DCA,
    mute group or processing beyond what the Category table gives its
    category (`rules`); a bus whose senders are every channel (`["*"]`)
    includes it. Each is one INFO (`reply.row-built`) naming the
    row and why; a quote that is not there is a WARNING
    (`reply.unassigned-quote-not-found`), and the row is built anyway."""
    from atoo import instructed_channels as ic
    from atoo.input_list import format_socket, parse_socket_spec

    channels = [c for c in plan.get("channels") or [] if isinstance(c, dict)]
    for channel in channels:
        source = channel.get("source") if isinstance(channel.get("source"), dict) else {}
        claimed.add(_norm(source.get("input") or channel.get("name") or ""))
    entries: dict[str, dict] = {}
    unknown: list = []
    for entry in plan.get("unassigned_inputs") or []:
        name = entry.get("input") if isinstance(entry, dict) else entry
        key = _norm(name or "")
        if not key:
            continue
        if not any(_norm(r.name) == key for r in rows):
            unknown.append(entry)
            continue
        entries[key] = entry if isinstance(entry, dict) else {"input": name, "quote": ""}

    left_out: list[dict] = []
    added: list[dict] = []
    used_numbers = {c.get("channel") for c in channels if (c.get("bank") or "ch") == "ch"}
    counted_groups = sorted(chosen, key=lambda g: -len(chosen[g]))
    fallback_group = counted_groups[0] if counted_groups else DEFAULT_SOCKET_GROUP
    for row in rows:
        key = _norm(row.name)
        if key in claimed:
            if key in entries:
                left_out.append(entries.pop(key))   # verify says a row both built and left out
            continue
        entry = entries.pop(key, None)
        quote = str((entry or {}).get("quote") or "").strip()
        if quote:
            layer = ic.find(quote, _unassigned_quote_layers(row, layers))
            if layer is not None:
                left_out.append({"input": row.name, "quote": quote, "from": layer.role})
                continue
            if findings is not None:
                findings.append(Diagnostic(
                    severity=Severity.WARNING, code="reply.unassigned-quote-not-found",
                    where=f"input list[{row.name}]", source="build",
                    message=(f"the reply left {row.name!r} out, quoting {quote!r}, which is not "
                             "in the conventions, the instructions or the row's notes -- so it "
                             "is built")))
            why = f"the reply left it out quoting {quote!r}, which is not there"
        elif entry is not None:
            why = "the reply left it out without a quote saying so"
        else:
            why = "the reply left it out without a word"

        number = next((n for n in range(1, facts.CAPACITY["ch"] + 1) if n not in used_numbers),
                      None)
        if number is None:
            raise ReplyError(f"input list row {row.name!r} is on no channel and nothing says to "
                             f"leave it out, and all {facts.CAPACITY['ch']} channel strips are "
                             "taken; free a strip or leave the row out with a quote saying so")
        used_numbers.add(number)
        text = f"{row.notes} {row.model}".casefold()
        stereo = "stereo" in text
        stated = parse_socket_spec(row.patch) if row.patch else None
        if stated:
            group, first = stated
            numbers = [first, first + 1] if stereo else [first]
            sockets.take(group, *numbers)
            patch_cite = f"Input list patch column: {row.patch!r}"
            patch = {"group": group, "sockets": numbers, "stated": True}
        else:
            group = fallback_group
            numbers, _skipped = sockets.next_free(group, 2 if stereo else 1)
            if not numbers:
                raise ReplyError(f"input list row {row.name!r} is on no channel and nothing says "
                                 f"to leave it out, and {group} has no free socket for it")
            sockets.take(group, *numbers)
            patch = {"group": group, "sockets": numbers, "stated": False}
            patch_cite = (f"next free {group} socket ({format_socket(group, numbers[0])}), in the "
                          "group the reply used most for unstated rows")
        spelled = format_socket(patch["group"], numbers[0]) + (
            f"-{numbers[-1]}" if len(numbers) > 1 else "")
        name = row.name[:facts.NAME_MAX_CHARS]
        color = colours.get(_norm(row.category))
        channel = {
            "channel": number, "bank": "ch", "name": name, "color": color,
            "source": {"input": row.name, "type": row.type or None, "model": row.model or None,
                       "stereo": stereo, "phantom": row.phantom},
            "patch": patch,
            "processing": {}, "fader": {}, "dca": [], "mute_group": [], "bus_sends": [],
            "main_routes": [],
            "provenance": {"input": f"input list row {row.name!r}, built by code: {why}",
                           "channel": f"the lowest free ch strip, {number}",
                           "patch": patch_cite},
        }
        if color is not None:
            channel["provenance"]["color"] = f"category map: {row.category} -> {color}"
        if stereo:
            channel["inferred"] = [{"field": "stereo", "by": "fallback",
                                    "basis": "the row's notes or model say stereo"}]
        if rules is not None:
            rules.apply(channel, row, {"color"} if color is not None else set())
        plan.setdefault("channels", []).append(channel)
        added.append(channel)
        if findings is not None:
            findings.append(_info(
                "reply.row-built", f"channels[{name}]",
                f"input list row {row.name!r} built as ch {number} on {spelled}: {why}. Every "
                "row is built unless the conventions, the instructions or its notes say to "
                "leave it out"
                + ("; stereo, because its notes or model say so" if stereo else "")))
    plan["unassigned_inputs"] = left_out + list(entries.values()) + unknown
    return added


# --------------------------------------------------------------------------
# the resolved conventions' Instructed strips (2026-10-01)
# --------------------------------------------------------------------------

def _quote_matches(quotes: list[str], quote: str) -> bool:
    """Whether one of a reply channel's quotes is the strip's sentence (or
    a part of it four words long, or the whole of it inside a longer one)."""
    from atoo import conventions_audit
    from atoo import instructed_channels as ic

    want = conventions_audit.normalise(ic.clean_quote(quote))
    for q in quotes:
        have = conventions_audit.normalise(ic.clean_quote(q))
        if not have or not want:
            continue
        if have == want or want in have or (
                have in want and len(have.split()) >= ic.MIN_QUOTE_WORDS):
            return True
    return False


def _occupants(rows, channels: list[dict]) -> dict[tuple[str, int], str]:
    """Who already holds each socket before any is counted: every socket the
    input list states (by row), and every socket a reply channel names
    outright (by channel)."""
    from atoo.input_list import parse_socket_spec

    held: dict[tuple[str, int], str] = {}
    for row in rows:
        stated = parse_socket_spec(row.patch) if row.patch else None
        if stated:
            held[stated] = f"input list row {row.name!r}"
    for channel in channels:
        patch = channel.get("patch")
        if isinstance(patch, dict) and patch.get("group") and patch.get("sockets"):
            name = channel.get("name") or channel.get("input") or (
                (channel.get("source") or {}).get("input"))
            for n in patch["sockets"]:
                if isinstance(n, int):
                    held.setdefault((patch["group"], n), f"channel {name!r}")
    return held


def prepare_instructed_strips(plan: dict, strips, rows, *, sockets: "_Sockets",
                              reserved: dict[str, set[int]],
                              findings: list | None) -> list[dict]:
    """Before any socket or strip is counted: for each instructed strip
    (`instructed_channels.Strip`), decide what code builds, and hold its
    socket and strip number so no counted row lands on them.

      * an input-list row with the strip's name IS the strip: code puts that
        row's channel where the strip goes (festival's HOST row is the
        conventions' "HOST mic on Aux 2");
      * a reply channel that is not a row and is the same strip (by name or
        by its quote) is merged into it: code's stated strip, socket,
        stereo pair and preset win, and the reply's other decisions stand.
        It is taken out of the reply here, and built once, by code;
      * a stated socket an input-list row states, or a reply channel names,
        is a physical conflict. "If available" in the text: the strip is
        built unpatched (INFO). Otherwise it is built on the stated socket
        anyway -- never silently dropped -- and verify refuses the plan
        (`reconcile.instructed-conflict`, an ERROR);
      * a stated strip number is held (`reserved`) for the strip; one a reply
        channel names outright is a conflict verify refuses
        (`strip.double-booked`).

    Returns one work item per strip, for `build_instructed_strips`."""
    from atoo import instructed_channels as ic
    from atoo.input_list import format_socket, parse_socket_spec

    by_name = _row_lookup(rows)
    channels = [c for c in plan.get("channels") or [] if isinstance(c, dict)]
    held = _occupants(rows, channels)
    strip_held: dict[tuple[str, int], str] = {}
    work: list[dict] = []
    for strip in strips or []:
        item: dict = {"strip": strip, "row": by_name.get(_norm(strip.name)), "merged": None,
                      "patched": True, "conflict": None, "number_conflict": None}
        where = f"instructed strips[{strip.name}]"
        if item["row"] is None:
            for channel in channels:
                if not is_compact_channel(channel) or by_name.get(_norm(channel.get("input"))):
                    continue
                if (_norm(channel.get("input")) == _norm(strip.name)
                        or _norm(channel.get("name") or "") == _norm(strip.name)
                        or _quote_matches(ic.candidate_quotes(channel), strip.quote)):
                    item["merged"] = channel
                    break
            if item["merged"] is not None:
                merged = item["merged"]
                plan["channels"] = [c for c in plan["channels"] if c is not merged]
                channels = [c for c in channels if c is not merged]
                _rename_senders(plan, {merged.get("input"), merged.get("name")}, strip.name)
                # Its own explicit patch no longer holds a socket; the
                # strips already placed still do.
                held = {**_occupants(rows, channels), **strip_held}
        row = item["row"]
        row_socket = parse_socket_spec(row.patch) if row is not None and row.patch else None
        if row_socket:
            if (row_socket[0], row_socket[1]) != (strip.group, strip.sockets[0]) \
                    and findings is not None:
                findings.append(_info(
                    "reply.instructed-strip-row", where,
                    f"the conventions put {strip.name!r} on {strip.spelled_source} "
                    f"({strip.quote!r}), but the input list's row {row.name!r} states "
                    f"{format_socket(*row_socket)}; the list wins, as it does for every row"))
            item["row_socket"] = True
        else:
            taken = [(n, held[(strip.group, n)]) for n in strip.sockets
                     if (strip.group, n) in held
                     and not (row is not None and held[(strip.group, n)] ==
                              f"input list row {row.name!r}")]
            if taken:
                who = "; ".join(f"{format_socket(strip.group, n)} is taken by {by}"
                                for n, by in taken)
                item["conflict"] = who
                item["patched"] = not strip.if_available
            if item["patched"]:
                sockets.take(strip.group, *strip.sockets)
                for n in strip.sockets:
                    strip_held[(strip.group, n)] = f"instructed strip {strip.name!r}"
                    held.setdefault((strip.group, n), strip_held[(strip.group, n)])
        if strip.number is not None:
            reserved.setdefault(strip.bank, set()).add(strip.number)
            for channel in channels:
                if channel is (item.get("merged")):
                    continue
                if row is not None and _norm(channel.get("input")) == _norm(row.name):
                    continue
                if (channel.get("bank") or "ch") == strip.bank \
                        and channel.get("channel") == strip.number:
                    item["number_conflict"] = (channel.get("name") or channel.get("input")
                                               or "a channel")
        work.append(item)
    return work


def _rename_senders(plan: dict, old_names: set, new_name: str) -> None:
    """A merged reply channel's name, in the busses' `sends.from` lists, as
    the strip code builds: the reply's sends still reach it."""
    old = {str(n).strip() for n in old_names if isinstance(n, str) and n.strip()}
    old.discard(new_name)
    if not old:
        return
    for bus in (plan.get("busses") or {}).values():
        if not isinstance(bus, dict):
            continue
        for group in bus.get("sends") or []:
            if isinstance(group, dict) and isinstance(group.get("from"), list):
                group["from"] = [new_name if str(n).strip() in old else n for n in group["from"]]


def _next_free_strip(plan: dict, bank: str, reserved: dict | None) -> int | None:
    used = {c.get("channel") for c in plan.get("channels") or []
            if isinstance(c, dict) and (c.get("bank") or "ch") == bank}
    held = (reserved or {}).get(bank, set())
    return next((n for n in range(1, facts.CAPACITY[bank] + 1)
                 if n not in used and n not in held), None)


def build_instructed_strips(plan: dict, work: list[dict], *, rules: "CategoryRules | None",
                            colours: dict, reserved: dict | None,
                            findings: list | None, built: dict | None = None) -> list[dict]:
    """Each instructed strip `prepare_instructed_strips` planned, built into
    `plan["channels"]` (or, for one an input-list row is, applied to that
    row's channel). Returns the channels added; `built` is filled with
    `id(channel) -> strip` for every strip channel, so `expand_sends` keeps
    them out of a bus's `"*"` and writes their stated sends instead
    (`write_instructed_sends`).

    Every value code decided rather than read off the strip is said at INFO
    (an error of judgement is not an error of patching):
    stereo from two sockets, the source type, phantom, an unpatched
    strip's reason, the category it took its defaults from."""
    from atoo import instructed_channels as ic
    from types import SimpleNamespace

    added: list[dict] = []
    for item in work:
        strip = item["strip"]
        if item["row"] is not None:
            _apply_strip_to_row(plan, item, findings, reserved, built)
            continue
        merged = item["merged"] or {}
        number = strip.number if strip.number is not None else _next_free_strip(
            plan, strip.bank, reserved)
        where = f"channels[{strip.name}]"
        if number is None:
            if findings is not None:
                findings.append(Diagnostic(
                    severity=Severity.WARNING, code="reply.instructed-strip-no-room", where=where,
                    source="build",
                    message=(f"the conventions ask for {strip.name!r} ({strip.quote!r}), but every "
                             f"{strip.bank} strip is taken, so it is not built")))
            continue
        name = strip.name[:facts.NAME_MAX_CHARS]
        kind, kind_why = ic.decide_type(strip.quote, strip.name)
        phantom, phantom_why = ic.decide_phantom(strip.quote)
        provenance = dict(merged.get("provenance")) if isinstance(merged.get("provenance"), dict) \
            else {}
        provenance["input"] = f"not on the input list; the conventions ask for it: {strip.quote!r}"
        if item["patched"]:
            patch = {"group": strip.group, "sockets": list(strip.sockets), "stated": True}
            provenance["patch"] = f"the conventions state {strip.spelled_source}: {strip.quote!r}"
        else:
            patch = None
            provenance["patch"] = (f"unpatched: the conventions ask for {strip.spelled_source} "
                                   f"if available, and {item['conflict']}")
        provenance["channel"] = (f"the conventions state {strip.bank} {number}: {strip.quote!r}"
                                 if strip.number is not None else
                                 f"the lowest free {strip.bank} strip, {number}")
        source = {"input": strip.name, "type": kind, "model": None, "stereo": strip.stereo,
                  "phantom": phantom, "from": "conventions", "quote": strip.quote}
        if strip.if_available:
            source["condition"] = strip.condition or "if available"
        processing = dict(merged.get("processing") or {})
        if strip.preset:
            processing["preset"] = strip.preset
            provenance["preset"] = f"the conventions state preset {strip.preset!r}: {strip.quote!r}"
        written: set[str] = set()
        # The category the strip takes its defaults from: the one the
        # resolved file states, else the one its name or its kind points
        # at (the 2026-10-01 sixpiece build: TALKBACK and MUSIC came with
        # no category and no gain, trim or fader, though Misc -- "aux",
        # "music" -- states all three). Decided, so said at INFO.
        category, category_why = strip.category, None
        if not category and rules is not None and rules.table is not None:
            category, category_why = _strip_category(rules.table, strip)
        if not category and merged.get("color") is None:
            category, category_why = ic.playback_category(strip.quote, strip.name, colours.keys())
        color = merged.get("color")
        if color is not None:
            written.add("color")
        elif category and colours.get(_norm(category)):
            color = colours[_norm(category)]
            provenance["color"] = f"category map: {category} -> {color}"
            written.add("color")
        full = {
            "channel": number, "bank": strip.bank, "name": name, "color": color,
            "source": source, "patch": patch, "processing": processing,
            "fader": dict(merged.get("fader") or {}),
            "dca": list(merged.get("dca") or []),
            "mute_group": list(merged.get("mute_group") or []),
            "bus_sends": [],
            "main_routes": list(merged.get("main_routes") or []),
            "provenance": provenance,
        }
        written |= _written_fields(merged, None) - {"color"} if merged else set()
        if strip.main_direct is not None and "main_direct" not in written:
            full["main_routes"] = [{"index": 1}] if strip.main_direct else []
            provenance["main_routes"] = ("the resolved conventions: "
                                         + ("straight to Main 1" if strip.main_direct
                                            else "not to Main"))
            written.add("main_direct")
        if merged.get("inferred"):
            full["inferred"] = merged["inferred"]
        if strip.stereo and strip.stereo_why != "stated":
            full.setdefault("inferred", []).append(
                {"field": "stereo", "by": "fallback", "basis": strip.stereo_why})
        category_note = ""
        if category_why:
            category_note = f"; category {category} ({category_why})"
            provenance["category"] = f"decided: {category} ({category_why})"
        if rules is not None and category:
            if rules.table is not None and rules.table.entry_for(category) is None:
                category_note = (f"; category {category!r} is not in the Category table, "
                                 "so no category defaults")
            rules.apply(full, SimpleNamespace(category=category.casefold()), written)
        plan.setdefault("channels", []).append(full)
        added.append(full)
        if built is not None:
            built[id(full)] = strip
        if findings is None:
            continue
        said = (f"{strip.bank} {number} {name!r} is not on the input list; built by code because "
                f"the conventions say {strip.quote!r}"
                + (" (merged with the reply's own channel for it: code's strip, socket, stereo "
                   "and preset win, the reply's other decisions stand)" if item["merged"] else "")
                + ". ")
        if item["patched"]:
            said += f"Patched from {strip.spelled_source}, as stated"
            if item["conflict"]:
                said += f" -- but {item['conflict']}, a physical conflict verify refuses"
        else:
            said += (f"Left UNPATCHED: the conventions ask for {strip.spelled_source} if "
                     f"available, and {item['conflict']}")
        if strip.number is None:
            said += f"; the lowest free {strip.bank} strip"
        if item["number_conflict"]:
            said += (f"; {strip.bank} {number} is also {item['number_conflict']!r}'s, a "
                     "conflict verify refuses")
        decided = [f"type {kind} ({kind_why})",
                   f"phantom {'on' if phantom else 'off'} ({phantom_why})"]
        if strip.stereo:
            decided.append(f"stereo ({strip.stereo_why})")
        said += ". Decided where the text is silent: " + "; ".join(decided) + category_note
        severity = Severity.WARNING if (item["patched"] and item["conflict"]) \
            or item["number_conflict"] else Severity.INFO
        findings.append(Diagnostic(severity=severity, code="reply.instructed-strip", where=where,
                                   message=said, source="build"))
    return added


def _strip_category(table, strip) -> tuple[str | None, str | None]:
    """The Category table entry a strip with no stated category takes its
    defaults from, and why: its whole name as a category word ("MUSIC"),
    then each word of its name, then its strip kind ("aux"). None when
    nothing matches -- the strip then has no category defaults, as before."""
    from atoo import instructed_channels as ic

    words = [strip.name] + [w for w in re.split(r"[^\w/]+", strip.name) if w]
    for word in words:
        entry = table.entry_for(word)
        if entry is not None:
            return entry["name"], f"its name {strip.name!r} is a {entry['name']} word"
    names = [a for e in table.entries for a in [e["name"], *e["aliases"]]]
    music, music_why = ic.playback_category(strip.quote, strip.name, names)
    if music is not None:
        return table.entry_for(music)["name"], music_why
    entry = table.entry_for(strip.bank)
    if entry is not None:
        return entry["name"], (f"no category is stated, and {entry['name']} is the category "
                               f"for {strip.bank} strips")
    return None, None


def _apply_strip_to_row(plan: dict, item: dict, findings: list | None, reserved: dict | None,
                        built: dict | None) -> None:
    """An input-list row that IS an instructed strip (by name): its channel
    goes on the stated strip, from the stated socket (unless the list
    states one), with the stated preset (unless the list's preset column
    states one, which `apply_stated_presets` applies after)."""
    from atoo.input_list import format_socket

    strip, row = item["strip"], item["row"]
    channel = next((c for c in plan.get("channels") or [] if isinstance(c, dict)
                    and _norm((c.get("source") or {}).get("input") or "") == _norm(row.name)),
                   None)
    if channel is None:
        return   # left out with a quote saying so (`build_left_out_rows`)
    moved: list[str] = []
    provenance = channel.setdefault("provenance", {})
    if strip.number is not None and ((channel.get("bank") or "ch"), channel.get("channel")) \
            != (strip.bank, strip.number):
        moved.append(f"from {channel.get('bank') or 'ch'} {channel.get('channel')} to "
                     f"{strip.bank} {strip.number}")
        channel["bank"], channel["channel"] = strip.bank, strip.number
        provenance["channel"] = f"the conventions state {strip.bank} {strip.number}: {strip.quote!r}"
        if strip.bank == "aux":
            (channel.get("processing") or {}).pop("hpf_hz", None)
    if not item.get("row_socket") and item["patched"]:
        patch = {"group": strip.group, "sockets": list(strip.sockets), "stated": True}
        if channel.get("patch") != patch:
            moved.append(f"patched from {strip.spelled_source}")
            channel["patch"] = patch
            channel.setdefault("source", {})["stereo"] = strip.stereo
            provenance["patch"] = f"the conventions state {strip.spelled_source}: {strip.quote!r}"
    if strip.preset and not row.preset:
        channel.setdefault("processing", {})["preset"] = strip.preset
        provenance["preset"] = f"the conventions state preset {strip.preset!r}: {strip.quote!r}"
        moved.append(f"preset {strip.preset!r}")
    if built is not None:
        built[id(channel)] = strip
    if findings is not None:
        findings.append(_info(
            "reply.instructed-strip-row", f"channels[{channel.get('name')}]",
            f"input list row {row.name!r} is the strip the conventions ask for ({strip.quote!r}); "
            + (", ".join(moved) if moved else "it is already where they put it")
            + (f". {item['conflict']}" if item.get("conflict") else "")))


def write_instructed_sends(plan: dict, built: dict, findings: list | None) -> None:
    """The sends the resolved conventions state for each strip code built
    (`Strip.sends`), into busses this plan has. A send the reply wrote for
    the strip stands; a bus the plan does not have is skipped and said."""
    busses = plan.get("busses") or {}
    by_norm = {_norm(name): name for name in busses}
    for channel in plan.get("channels") or []:
        strip = built.get(id(channel)) if isinstance(channel, dict) else None
        if strip is None or not strip.sends:
            continue
        sends = channel.setdefault("bus_sends", [])
        have = {_norm(s.get("bus")) for s in sends if isinstance(s, dict)}
        wrote, missing = [], []
        for send in strip.sends:
            bus = by_norm.get(_norm(send["bus"]))
            if bus is None:
                missing.append(send["bus"])
                continue
            if _norm(bus) in have:
                continue
            entry = {"bus": bus, "mode": send.get("mode"), "level_db": send.get("level_db")}
            if entry["mode"] is not None:
                entry["mode"] = str(entry["mode"]).strip().lower()
                if entry["mode"] not in facts.PLAN_SEND_MODES:
                    entry["mode"] = None   # decided by `inferred.decide_unstated`, at INFO
            if entry["level_db"] is None:
                inferred.decide_send_level(entry, bus)
            sends.append(entry)
            wrote.append(bus)
        provenance = channel.setdefault("provenance", {})
        if wrote:
            provenance["bus_sends"] = f"the resolved conventions: sends to {', '.join(wrote)}"
        if findings is not None and (wrote or missing):
            text = f"{channel['name']!r}: sends the resolved conventions state, to " + (
                ", ".join(wrote) if wrote else "none of its busses")
            if missing:
                text += (f"; not written, because this plan has no such bus: "
                         + ", ".join(missing))
            findings.append(_info("reply.instructed-strip-sends", f"channels[{channel['name']}]",
                                  text))


def _next_number(counters: dict, bank: str, reserved: dict | None) -> int:
    """The next strip of `bank` in the order written, stepping over any the
    conventions or instructions hold for a channel they state."""
    number = counters.get(bank, 0) + 1
    while number in (reserved or {}).get(bank, ()):
        number += 1
    return number


def _expand_instructed(channel: dict, found: dict, counters: dict, numbered: dict,
                       colours: dict, findings: list | None,
                       reserved: dict | None = None) -> None:
    """One channel the conventions or instructions ask for, in place, as
    a full plan channel: the stated socket, and a type, phantom and colour
    taken from the text where it says and otherwise decided and said at
    INFO. `source.from`/`source.quote` record where it came from, which
    is what verify reports it by (`reconcile.from-instructions`)."""
    from atoo import instructed_channels as ic
    from atoo.input_list import format_socket

    quote, layer = found["quote"], found["layer"]
    input_name = str(channel.get("input")).strip()
    bank = channel.get("bank") or "ch"
    stated_number = found.get("channel")
    if stated_number is not None:
        # Held for it, not counted: the strips after it keep counting on
        # from where they were.
        number = stated_number
    else:
        number = channel.get("channel") or _next_number(counters, bank, reserved)
        counters[bank] = number
    numbered.setdefault(bank, []).append(number)
    name = channel.get("name") or input_name
    if len(name) > facts.NAME_MAX_CHARS:
        name = name[:facts.NAME_MAX_CHARS]
    where = f"channels[{name}]"
    provenance = dict(channel.get("provenance")) if isinstance(channel.get("provenance"), dict) else {}
    group, numbers = found["group"], found["sockets"]
    spelled = format_socket(group, numbers[0]) + (f"-{numbers[-1]}" if len(numbers) > 1 else "")
    kind, kind_why = ic.decide_type(quote, input_name)
    phantom, phantom_why = ic.decide_phantom(quote)
    if channel.get("color") is not None:
        color, colour_why = channel["color"], "stated by the reply"
    else:
        category, colour_why = ic.decide_category(quote, input_name, colours.keys())
        color = colours.get(_norm(category)) if category else None
        if color is not None:
            colour_why = f"{colour_why} -> {color}"
            provenance.setdefault("color", f"category map: {category} -> {color} ({colour_why})")
    provenance["input"] = (f"not on the input list; {layer.name} asks for it: {quote!r}")
    provenance["patch"] = f"{layer.name} states {spelled}: {quote!r}"
    if stated_number is not None:
        provenance["channel"] = f"{layer.name} states channel {number}: {quote!r}"
    else:
        provenance.setdefault("channel", f"the reply placed it at {bank} {number}"
                              if "channel" in channel else
                              f"numbered {bank} {number} in the order the reply listed it")
    full = {
        "channel": number,
        "bank": bank,
        "name": name,
        "color": color,
        "source": {"input": input_name, "type": kind, "model": None,
                   "stereo": len(numbers) == 2, "phantom": phantom,
                   "from": layer.role, "quote": quote},
        "patch": {"group": group, "sockets": numbers, "stated": True},
        "processing": dict(channel.get("processing") or {}),
        "fader": dict(channel.get("fader") or {}),
        "dca": list(channel.get("dca") or []),
        "mute_group": list(channel.get("mute_group") or []),
        "bus_sends": list(channel.get("bus_sends") or []),
        "main_routes": list(channel.get("main_routes") or []),
        "provenance": provenance,
    }
    if channel.get("inferred"):
        full["inferred"] = channel["inferred"]
    channel.clear()
    channel.update(full)
    if findings is not None:
        findings.append(_info(
            "reply.from-instructions", where,
            f"{bank} {number} {name!r} is not on the input list; built because {layer.name} "
            f"says {quote!r}. "
            f"{'On that channel and p' if stated_number is not None else 'P'}atched from "
            f"{spelled}, as stated. Decided where the text is "
            f"silent: type {kind} ({kind_why}); phantom {'on' if phantom else 'off'} "
            f"({phantom_why}); colour {color or 'none'} ({colour_why})"))


def _expand_alt_patches(channels: list[dict], pending: list[tuple[dict, dict, bool, str]],
                        rows, console_model: str | None,
                        repairs: list[str]) -> dict[str, list[str]]:
    """Each reply channel's `alt_patch`, as the plan's
    `{group, sockets, stated}`. Run after every main patch is placed, so
    a counted alternate never lands on a socket a main patch uses -- a
    channel switched to its alternate should not quietly hear another
    channel's stage source. Seeded, as the main pass is, from every
    socket the input list states (FR-1.10: a cabled socket is never
    handed out) -- review 2026-09-28, R3, where a counted alternate
    landed on the socket an unassigned spare mic was cabled into. Sockets the reply names are the conventions'
    (the prompt asks for them only then), so they are `stated`; counted
    ones are not, and are announced. Returns `{group: ["Kick CRD 1", ...]}`
    for the INFO."""
    from atoo.input_list import format_socket

    chosen: dict[str, list[str]] = {}
    if not pending:
        return chosen
    free = _Sockets(rows, console_model)
    for channel in channels:
        patch = channel.get("patch")
        if isinstance(patch, dict) and patch.get("group"):
            free.take(patch["group"], *[n for n in patch.get("sockets") or [] if isinstance(n, int)])
    for _channel, alt, _stereo, _where in pending:
        if alt.get("sockets"):
            free.take(alt["group"], *[n for n in alt["sockets"] if isinstance(n, int)])
    for channel, alt, stereo, where in pending:
        group = alt["group"]
        provenance = channel.setdefault("provenance", {})
        if alt.get("sockets"):
            numbers = list(alt["sockets"])
            cite = provenance.get("alt_patch") or "the conventions state the alternate's sockets"
            channel["alt_patch"] = {"group": group, "sockets": numbers, "stated": True}
        else:
            numbers, skipped = free.next_free(group, 2 if stereo else 1)
            if not numbers:
                raise ReplyError(
                    f"{where}: no room in {group} for {'a stereo' if stereo else 'an'} alternate "
                    f"input: {group} 1-{free.limit(group)} on this console, all taken by main or "
                    "alternate patches. The reply chose the group, so it must choose where the "
                    "overflow goes")
            if skipped:
                repairs.append(f"{where}: alternate {group} {skipped} left empty so the pair "
                               "starts on an odd socket")
            free.take(group, *numbers)
            spelled = format_socket(group, numbers[0]) + (f"-{numbers[-1]}" if len(numbers) > 1 else "")
            chosen.setdefault(group, []).append(f"{channel['name']} {spelled}")
            cite = (f"next {group} socket no main patch uses and the input list does not "
                    f"state, in channel order ({spelled})")
            if provenance.get("alt_patch"):
                cite = f"{cite}; reply: {provenance['alt_patch']}"
            channel["alt_patch"] = {"group": group, "sockets": numbers, "stated": False}
        provenance["alt_patch"] = cite
        # Keep the plan's own key order: alt_patch sits after patch.
        ordered = {k: channel[k] for k in _CHANNEL_KEY_ORDER if k in channel}
        ordered.update({k: v for k, v in channel.items() if k not in ordered})
        channel.clear()
        channel.update(ordered)
    return chosen


def _runs(numbers: list[int]) -> list[str]:
    out: list[str] = []
    start = prev = None
    for n in numbers:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return out


def _category_colours(entries) -> dict[str, str]:
    """The reply's `category_colors` as a map by normalised category."""
    out: dict[str, str] = {}
    if isinstance(entries, dict):
        entries = [{"category": k, "color": v} for k, v in entries.items()]
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("category") and entry.get("color"):
            out[_norm(entry["category"])] = str(entry["color"])
    return out


def expand(reply: dict, *, input_csv: str | None = None, findings: list | None = None,
           console_model: str | None = None, layers: list | None = None,
           category_table=None, strips=None) -> list[str]:
    """The reply as a plan, in place. Returns the repair notes it made
    (`repair_reply`'s, and a stated socket the reply moved) and appends
    its INFO findings to `findings`.

    A reply in the array form is first checked against `REPLY_SCHEMA`,
    so a shape error is named against the format the model was asked
    for rather than against the plan it never wrote. `ReplyError`
    carries the message; the caller turns it into a `GenerationError`.

    `input_csv` is the input list the reply's compact channels name their
    rows from; it is parsed only when one does. `console_model` bounds
    the socket groups counted out for them. `layers` are the conventions
    and instructions the build was given: a channel naming no row is
    built from them only when it quotes a line of them that states its
    socket (`instructed_channels.py`).

    `category_table` is the resolved conventions' checked Category table
    (`category_table.py`), or None: code fills each field a compact
    channel's reply left out from its input-list row's category.

    `strips` are the resolved conventions' instructed strips
    (`instructed_channels.parse_strips`), or None: code builds each one
    the reply did not (`build_instructed_strips`), and writes the sends
    they state (`write_instructed_sends`).
    """
    repairs: list[str] = []
    pairs: dict = {}
    built: dict = {}
    rows = None
    array_form = is_array_form(reply)
    if array_form:
        _normalise_old_keys(reply)
        drop_null_optionals(reply, plan_schema.REPLY_SCHEMA)
        repairs.extend(repair_reply(reply))
        violations = validate_schema(reply, plan_schema.REPLY_SCHEMA, path="reply")
        if violations:
            shown = "\n  ".join(violations[:10])
            more = f"\n  ...and {len(violations) - 10} more" if len(violations) > 10 else ""
            raise ReplyError(f"the model's reply does not match the reply format:\n  {shown}{more}")
        expand_structure(reply)
    compact = has_compact_channels(reply)
    if compact:
        if input_csv is None:
            raise ReplyError("the reply names its channels by input-list row, and no input "
                             "list was given to read them from")
        from atoo.input_list import InputListError, parse_input_list
        try:
            rows = parse_input_list(input_csv)
        except InputListError as exc:
            raise ReplyError("the reply names its channels by input-list row, and the input "
                             f"list could not be read: {exc}") from exc
        repairs.extend(expand_mechanical(reply, rows, console_model=console_model,
                                         findings=findings, pairs=pairs, layers=layers,
                                         category_table=category_table, strips=strips,
                                         built=built))
    else:
        reply.pop("category_colors", None)
        rows = None
        if input_csv is not None:
            # A full-format reply still honours the list's preset column;
            # a list that will not parse is reported by build, not here.
            from atoo.input_list import InputListError, parse_input_list
            try:
                rows = parse_input_list(input_csv)
            except InputListError:
                rows = None
    if array_form:
        expand_sends(reply, findings, exclude=built)
    else:
        # The plan's own shape, from a replay or an unconstrained provider:
        # the same reading of a null that says nothing -- after the
        # renaming, so an old `"socket": null` is kept as `"patch": null`.
        renamed = plan_compat.normalise_plan(reply)
        if renamed is not reply:
            reply.clear()
            reply.update(renamed)
        drop_null_optionals(reply, plan_schema.GENERATION_SCHEMA)
    if strips and rows is not None and not compact:
        # A reply with no compact channel (a replay, an unconstrained
        # provider): nothing was counted, so the strips are built round
        # what the reply placed.
        _build_strips_on_full_reply(reply, rows, strips, console_model=console_model,
                                    category_table=category_table, findings=findings,
                                    built=built)
    if built:
        write_instructed_sends(reply, built, findings)
    fill_defaults(reply)
    settle_line_gains(reply, findings, [getattr(layer, "text", "") for layer in layers or []])
    if rows is not None:
        apply_stated_presets(reply, rows, findings=findings, pairs=pairs)
    return repairs


def _build_strips_on_full_reply(plan: dict, rows, strips, *, console_model, category_table,
                                findings, built) -> None:
    """The instructed strips, for a reply already in the plan's own shape
    (a replay, an unconstrained provider): every socket and strip it
    placed is held as it is, and each strip is built round them."""
    sockets = _Sockets(rows, console_model)
    for channel in plan.get("channels") or []:
        patch = channel.get("patch") if isinstance(channel, dict) else None
        if isinstance(patch, dict) and patch.get("group") and patch.get("sockets"):
            sockets.take(patch["group"], *[n for n in patch["sockets"] if isinstance(n, int)])
    # A strip the reply already built in full (by name) is the reply's:
    # there is nothing left to count round, so it is not built twice.
    have = {_norm(n) for c in plan.get("channels") or [] if isinstance(c, dict)
            for n in (c.get("name"), (c.get("source") or {}).get("input")) if n}
    rows_by_name = _row_lookup(rows)
    kept = []
    for strip in strips:
        if _norm(strip.name) in have and rows_by_name.get(_norm(strip.name)) is None:
            if findings is not None:
                findings.append(_info(
                    "reply.instructed-strip", f"channels[{strip.name}]",
                    f"{strip.name!r}: the reply, written in the plan's own shape, already "
                    "builds it, so code does not build it again"))
            continue
        kept.append(strip)
    reserved: dict[str, set[int]] = {}
    work = prepare_instructed_strips(plan, kept, rows, sockets=sockets, reserved=reserved,
                                     findings=findings)
    rules = CategoryRules(category_table, plan)
    build_instructed_strips(plan, work, rules=rules, colours={}, reserved=reserved,
                            findings=findings, built=built)
    if findings is not None:
        findings.extend(rules.findings())


# --------------------------------------------------------------------------
# the input list's preset column
# --------------------------------------------------------------------------

def settle_line_gains(plan: dict, findings: list | None = None, texts=()) -> int:
    """A Line source on a head amp does not keep the mic gain the reply
    copied onto it (`inferred.settle_line_gain`): it takes a line gain, said
    at INFO per channel. Returns how many it set."""
    from atoo import inferred

    count = 0
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        said = inferred.settle_line_gain(
            channel, stated=inferred.gain_stated_for(channel, texts))
        if said is None:
            continue
        count += 1
        if findings is not None:
            findings.append(_info("reply.line-gain", f"channels[{channel.get('name')}]", said))
    return count


def apply_stated_presets(plan: dict, rows, *, findings: list | None = None,
                         pairs: dict | None = None) -> int:
    """A row's stated preset replaces whatever its channel carries, in
    place; returns how many channels it set.

    *"a preset column to the input list which would override anything in
    conventions and instructions (as is currently done with patches)"* --
    so it runs after the reply is expanded and before `preset_expand`
    resolves the name into `processing.preset_values`, and is the last
    word on `processing.preset`. Where it replaces a DIFFERENT preset the
    model chose from the conventions, that is said at INFO
    (`reply.preset-from-input-list`), naming both; either way the
    channel's `provenance.preset` cites the column. A name the library
    does not have is left as written: `verify`'s `preset.unknown` says so.
    A stereo pair whose two rows disagree takes the first row's
    (`input_list.stated_preset`), and `verify` warns about the other.
    """
    from atoo.input_list import rows_feeding, stated_preset
    from atoo.presets import normalize_preset_name

    set_count = 0
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        stated = stated_preset(rows_feeding(channel, rows, (pairs or {}).get(id(channel))))
        if stated is None:
            continue
        name, row, others = stated
        processing = channel.get("processing")
        if not isinstance(processing, dict):
            processing = channel["processing"] = {}
        before = processing.get("preset")
        label = f"channels[{channel.get('name')}]"
        if before and normalize_preset_name(str(before)) != normalize_preset_name(name) \
                and findings is not None:
            findings.append(_info(
                "reply.preset-from-input-list", label,
                f"the reply chose the preset {before!r} for {channel.get('name')!r}, but the "
                f"input list's preset column states {name!r} for {row.name!r}; the list wins"))
        processing["preset"] = name
        cite = f"Input list preset column: {name!r} ({row.name})"
        if others:
            cite += ("; " + ", ".join(f"{o.name} says {o.preset!r}" for o in others)
                     + ", and the first row wins")
        provenance = channel.get("provenance")
        if provenance is None:
            provenance = channel["provenance"] = {}
        if isinstance(provenance, dict):
            provenance["preset"] = cite
        set_count += 1
    return set_count


def _pair_phantom(row, pair_row, where: str, findings: list | None) -> bool:
    """The one 48V value for a stereo channel built from two input-list
    rows: on if either row wants it. The desk switches a pair's two sockets
    together, so two values cannot be put on it; a condenser left without
    48V is silent, where a dynamic given it is unharmed, so "on" is the
    choice that displeases at worst. Said at INFO, naming the row that
    asked, when the rows disagree; rows that agree say nothing."""
    if row.phantom == pair_row.phantom:
        return row.phantom
    asked, other = (row, pair_row) if row.phantom else (pair_row, row)
    if findings is not None:
        findings.append(_info(
            "reply.pair-phantom", where,
            f"48V is on for both sockets of the stereo channel: {asked.name!r} asks for it "
            f"and {other.name!r} does not, and the desk switches a pair's two sockets "
            "together, so the pair takes the value either row wants (split the pair into "
            f"two mono channels if you want {other.name!r} without 48V)"))
    return True


def _info(code: str, where: str, message: str) -> Diagnostic:
    return Diagnostic(severity=Severity.INFO, code=code, where=where,
                      message=message, source="build")


# --------------------------------------------------------------------------
# the resolved conventions' Category table (2026-09-30, FR-1.18a)
# --------------------------------------------------------------------------

def _written_fields(channel: dict, color) -> set[str]:
    """The Category-table fields a compact reply channel WROTE: a value, or
    an explicit `[]` for a list. Left out or null is not written -- the
    table fills those (`category_table.py`)."""
    written: set[str] = set()
    if color is not None:
        written.add("color")
    processing = channel.get("processing") if isinstance(channel.get("processing"), dict) else {}
    for key in ("hpf_hz", "gain_db", "trim_db"):
        if processing.get(key) is not None:
            written.add(key)
    fader = channel.get("fader") if isinstance(channel.get("fader"), dict) else {}
    if fader.get("fader_db") is not None:
        written.add("fader_db")
    for key in ("dca", "mute_group"):
        if channel.get(key) is not None:
            written.add(key)
    if channel.get("main_routes") is not None:
        written.add("main_direct")
    return written


def _describe(key: str, value) -> str:
    if key == "color":
        return f"colour {value}"
    if key == "hpf_hz":
        return f"HPF {value:g} Hz"
    if key == "gain_db":
        return f"gain {value:g} dB"
    if key == "trim_db":
        return f"trim {value:g} dB"
    if key == "fader_db":
        return ("fader fully down (-144 dB)" if value <= facts.MINUS_INF_DB
                else f"fader {value:g} dB")
    if key == "dca":
        return "DCA " + ", ".join(value)
    if key == "mute_group":
        return "mute group " + ", ".join(value)
    if key == "main_direct":
        return "straight to Main 1" if value else "Main only through its busses"
    return f"{key} {value}"


def _current(full: dict, key: str):
    """A table field's value on a built channel."""
    if key in ("hpf_hz", "gain_db", "trim_db"):
        return (full.get("processing") or {}).get(key)
    if key == "fader_db":
        return (full.get("fader") or {}).get("fader_db")
    if key == "main_direct":
        return bool(full.get("main_routes"))
    return full.get(key)


def _same(key: str, have, want) -> bool:
    if key in ("dca", "mute_group"):
        return sorted(_norm(n) for n in have or []) == sorted(_norm(n) for n in want or [])
    if key == "color":
        return have is not None and _norm(have) == _norm(want)
    return have == want


_PLAIN = {"color": "colour", "hpf_hz": "HPF", "gain_db": "gain", "trim_db": "trim",
          "fader_db": "fader", "dca": "DCA", "mute_group": "mute group",
          "main_direct": "Main routing"}


class CategoryRules:
    """Applies a checked Category table (`category_table.Table`) to the
    channels built from input-list rows, and says what it did: one INFO
    per category (`reply.category-rule`), plus one per DCA or mute group
    it had to declare.

    Decided here, each said in the INFO:
      * an aux strip gets no `hpf_hz` (it has no filter node);
      * `gain_db` only on a socket with a head amp
        (`console_facts.PHANTOM_CAPABLE_GROUPS`) -- a digital source's
        gain is rightly unset;
      * `main_direct: true` is not applied to a click, guide or talkback
        strip, recognised by name as verify recognises it
        (`verify_plan._stays_off_main`): the domain knowledge keeps them
        off Main, and a table entry for "tracks" cannot tell the click
        from the backing tracks;
      * a DCA or mute group the table names that the reply did not
        declare is declared, since the channel is now its member.
    """

    def __init__(self, table, plan: dict):
        self.table = table
        self.plan = plan
        self.by_entry: dict[str, dict] = {}
        self.declared: list[tuple[str, str, str]] = []

    def _group_name(self, section: str, name: str, cite: str) -> str:
        groups = self.plan.get(section)
        if not isinstance(groups, dict):
            groups = self.plan[section] = {}
        for existing in groups:
            if _norm(existing) == _norm(name):
                return existing
        groups[name] = {"description": None,
                        "provenance": f"{cite} names it; the reply did not declare it"}
        self.declared.append((section, name, cite))
        return name

    def apply(self, full: dict, row, written: set[str]) -> None:
        from atoo import category_table as ct
        from atoo.verify_plan import _stays_off_main

        if self.table is None or row is None:
            return
        entry = self.table.entry_for(row.category)
        if entry is None:
            return
        name = full.get("name")
        record = self.by_entry.setdefault(entry["name"], {
            "entry": entry, "words": [], "channels": [], "set": {}, "kept": {},
            "skipped": {}})
        if row.category not in record["words"]:
            record["words"].append(row.category)
        record["channels"].append(name)
        cite = f"category table: {entry['name']}"
        provenance = full.setdefault("provenance", {})
        group = (full.get("patch") or {}).get("group")
        processing_set: list[str] = []
        for key in ct.FIELDS:
            value = entry.get(key)
            if value is None or (isinstance(value, list) and not value):
                continue
            if key in written:
                # The reply's own value stands; said only where it differs
                # from the table's -- the exception the model made.
                if not _same(key, _current(full, key), value):
                    record["kept"].setdefault(key, []).append(name)
                continue
            if key == "hpf_hz" and full.get("bank") == "aux":
                record["skipped"].setdefault("an aux strip has no high-pass", []).append(name)
                continue
            if key == "gain_db" and group not in facts.PHANTOM_CAPABLE_GROUPS:
                record["skipped"].setdefault(
                    f"no gain on {group or 'an unpatched strip'}: that source has no head amp",
                    []).append(name)
                continue
            if key == "main_direct" and value and _stays_off_main(full):
                record["skipped"].setdefault(
                    "not straight to Main: a click, guide or talkback strip stays off Main "
                    "(by name), so its routing is the reply's", []).append(name)
                continue
            if key == "color":
                full["color"] = value
                provenance["color"] = cite
            elif key in ("hpf_hz", "gain_db", "trim_db"):
                full.setdefault("processing", {})[key] = value
                processing_set.append(_describe(key, value))
            elif key == "fader_db":
                full.setdefault("fader", {})["fader_db"] = value
                provenance["fader"] = f"{cite}: {_describe(key, value)}"
            elif key in ("dca", "mute_group"):
                section = "dcas" if key == "dca" else "mute_groups"
                full[key] = [self._group_name(section, n, cite) for n in value]
                provenance[key] = cite
            elif key == "main_direct":
                full["main_routes"] = [{"index": 1}] if value else []
                provenance["main_routes"] = f"{cite}: {_describe(key, value)}"
            record["set"].setdefault(key, []).append(name)
        if processing_set:
            line = f"{cite}: {', '.join(processing_set)}"
            before = provenance.get("processing")
            provenance["processing"] = f"{before}; {line}" if before else line

    def findings(self) -> list[Diagnostic]:
        out: list[Diagnostic] = []
        for entry_name, record in self.by_entry.items():
            entry, channels = record["entry"], record["channels"]
            words = ", ".join(repr(w) for w in record["words"])

            def who(names: list[str]) -> str:
                return "all" if len(names) == len(channels) else ", ".join(names)

            parts = [f"{_describe(key, entry[key])} ({who(names)})"
                     for key, names in record["set"].items()]
            text = (f"{entry_name} (input-list category {words}): {len(channels)} channel(s), "
                    f"{', '.join(channels)}. Written by code where the reply left the field "
                    "out: " + ("; ".join(parts) if parts else "nothing"))
            if record["kept"]:
                text += (". The reply's own, different value kept: "
                         + "; ".join(f"{_PLAIN[k]} ({', '.join(n)})"
                                     for k, n in record["kept"].items()))
            for reason, names in record["skipped"].items():
                text += f". Not applied, {reason}: {', '.join(names)}"
            out.append(_info("reply.category-rule", "category table", text))
        for section, name, cite in self.declared:
            kind = "DCA" if section == "dcas" else "mute group"
            out.append(_info("reply.category-group-declared", "category table",
                             f"{kind} {name!r} declared by code: {cite} puts channels in it, "
                             "and the reply did not declare it"))
        return out
