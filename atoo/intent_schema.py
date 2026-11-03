"""The intent: what a front end model is asked to write for `atoo patch --intent`.

An **intent** is a short list of operations, bounded by the console, that says
WHAT an engineer's request wants; `atoo/intent_compile.py` turns it into the
change set `atoo patch` already merges and reviews. The model does not write
channel objects, sockets for strips whose socket nobody named, indices, sends
or levels: code works those out from `console_facts`, the same for every
console model.

    {"name": "<a few words>", "ops": [op, ...], "notes": [str, ...]}

| op | what it says |
|---|---|
| `add_channel` | a new strip: `name`, and what the request states of it |
| `drop` | take a channel, bus, DCA, mute group or output away, by `name` or `index` |
| `move_channel` | the same source on another strip and/or socket |
| `rename` | only the display name |
| `set` | one setting of something on the desk, from the **menu** below |
| `assign` | which DCAs, mute groups and bus sends a channel already on the desk has: add some, take some away |
| `add_bus` | a mix bus (`index` to reuse a freed number, `to` for its output) |
| `add_group` | a DCA or mute group |
| `add_output` | a main or matrix output |
| `order` | (a build) the strips in the order of a list of categories |

`add_channel` may name the input-list `rows` it is built from (two rows are one stereo
pair), `add_group` and `add_bus` may take `members` (by category, by name, or all), and an
intent for a whole show also carries `categories`, the Category table's entries.

Every field but the few an op cannot do without is nullable, and `null` means
"the request did not say". A bus, DCA, mute group or output may have no
`name`: the request did not give one, and the compiler takes it from the
request's own words.

**The menu** (`settings`): the settings `set` may change are not a table kept
here but generated from the plan's own format (`plan_schema`), minus what a
change may never set (`patch._FROZEN_FIELDS`): `processing.hpf_hz`,
`fader.fader_db`, `source.phantom` ... A new field in the plan format is on the
menu the next day. Each entry carries the schema's own type and range, so a
value outside the console's range is refused with the range.

**Bounds per console** come from `console_facts`: strip counts, the socket
groups the console has and their sizes, and every numeric range; no branch on
the model name. The three desks differ only in their local sockets.
"""

from __future__ import annotations

from atoo import category_table
from atoo import console_facts as facts
from atoo import patch

#: The object words an intent uses, and the plan key of each.
OBJECTS = ("channel", "bus", "dca", "mute_group", "output")
KEY = {"channel": "channels", "bus": "busses", "dca": "dcas", "mute_group": "mute_groups",
       "output": "outputs"}
#: `patch`'s own words for the same objects (`patch.OBJECT_KINDS`).
PATCH_WORD = {"channel": "channel", "bus": "bus", "dca": "dca", "mute_group": "mute group",
              "output": "output"}
CAPACITY_KEY = {"bus": "bus", "dca": "dca", "mute_group": "mgrp", "output": "main"}
SOURCE_TYPES = {"mic": "Mic", "di": "DI", "line": "Line"}

#: Leaves the menu leaves out although a change may set them: the socket is
#: placed by `move_channel`, a colour index is the colour's, a flag is the build's.
_NOT_ON_THE_MENU = ("patch", "alt_patch", "col", "icon", "channel", "bank", "provenance",
                    "inferred", "index", "destination", "destinations")


def _leaves(schema: dict, prefix: str = "") -> dict[str, dict]:
    found: dict[str, dict] = {}
    for key, sub in (schema.get("properties") or {}).items():
        path = f"{prefix}{key}"
        kinds = sub.get("type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if "object" in kinds and sub.get("properties"):
            found.update(_leaves(sub, path + "."))
        elif any(k in kinds for k in ("number", "integer", "boolean", "string")):
            found[path] = sub
    return found


def settings(kind: str) -> dict[str, dict]:
    """The menu for an object kind: `{dotted path: the plan format's schema for
    that leaf}`, minus what a change may never set. Generated, not kept."""
    key = KEY[kind]
    frozen = patch._FROZEN_FIELDS.get(key, {})
    menu = {}
    for path, leaf in _leaves(patch._OBJECT_SCHEMAS[key]).items():
        if path.split(".")[0] in _NOT_ON_THE_MENU or path.endswith(".stated"):
            continue
        if patch._frozen_reason(frozen, path):
            continue
        menu[path] = leaf
    return menu


def menu_text() -> str:
    """The menu, for the prompt: one line per object kind."""
    return "\n".join(f"- {kind}: " + ", ".join(settings(kind)) for kind in OBJECTS if settings(kind))


def input_groups(console_model: str) -> list[str]:
    """The input socket groups this console has at all (a Rack has no AUX)."""
    return sorted(g for g in facts.INPUT_SOCKETS if g not in ("OSC", "USR")
                  and facts.input_socket_limit(g, console_model) > 0)


def output_groups(console_model: str) -> list[str]:
    return sorted(g for g in facts.OUTPUT_SOCKETS
                  if facts.output_socket_limit(g, console_model) > 0)


def intent_schema(console_model: str, *, build: bool = False) -> dict:
    """The JSON schema of an intent for `console_model`. Raises
    `console_facts.UnknownConsoleModel` for one it does not know. `build`: an intent for a
    whole show (`atoo build --intent`), which also carries the Category `categories`."""
    facts.panel_for(console_model)
    nullable = lambda s: {**s, "type": [s["type"], "null"]}  # noqa: E731
    name = {"type": "string", "minLength": 1}
    index = lambda key: {"type": ["integer", "null"], "minimum": 1,  # noqa: E731
                         "maximum": facts.CAPACITY[key]}

    def socket(groups, direction):
        limits = [(facts.input_socket_limit if direction == "in" else facts.output_socket_limit)(
            g, console_model) for g in groups]
        return {"type": ["object", "null"], "properties": {
            "group": {"type": "string", "enum": groups},
            "first": {"type": "integer", "minimum": 1, "maximum": max(limits)},
            "count": {"type": ["integer", "null"], "enum": [1, 2, None]}},
            "required": ["group", "first"], "additionalProperties": False}

    place = {"type": ["object", "null"], "properties": {
        "at": {"type": ["integer", "null"], "minimum": 1, "maximum": facts.CAPACITY["ch"]},
        "after": nullable({"type": "string"}), "before": nullable({"type": "string"}),
        "renumber": {"type": ["boolean", "null"]}}, "additionalProperties": False}
    send = {"type": "object", "properties": {
        "bus": name, "mode": {"type": ["string", "null"], "enum": [*facts.PLAN_SEND_MODES, None]},
        "level_db": {"type": ["number", "null"], "minimum": facts.SEND_LEVEL_DB_RANGE[0],
                     "maximum": facts.SEND_LEVEL_DB_RANGE[1]}},
        "required": ["bus"], "additionalProperties": False}
    ins, outs = input_groups(console_model), output_groups(console_model)

    def op(tag, *required, **props):
        """An op: `required` names the fields without which it means nothing."""
        return {"type": "object", "properties": {"op": {"type": "string", "enum": [tag]}, **props},
                "required": ["op", *required], "additionalProperties": False}

    names = {"type": ["array", "null"], "items": name}
    members = {"type": ["object", "null"], "properties": {
        "categories": names, "channels": names, "all": {"type": ["boolean", "null"]}},
        "additionalProperties": False}
    on_menu = sorted({path for kind in OBJECTS for path in settings(kind)})
    ops = [
        # Key order matters to a decoding grammar (llama.cpp's fixes it: required keys, then the
        # optional ones in this order), so it follows the order the prompts' examples write them;
        # `tests/test_intent_key_order.py` holds the examples to it.
        op("add_channel", "name", name=name, rows={"type": ["array", "null"], "items": name},
           category=nullable({"type": "string"}),
           kind={"type": ["string", "null"], "enum": [*SOURCE_TYPES, None]},
           model=nullable({"type": "string"}), phantom={"type": ["boolean", "null"]},
           stereo={"type": ["boolean", "null"]}, patch=socket(ins, "in"), place=place,
           bank={"type": ["string", "null"], "enum": ["ch", "aux", None]},
           dca={"type": ["array", "null"], "items": name},
           mute_group={"type": ["array", "null"], "items": name},
           sends={"type": ["array", "null"], "items": send},
           fader_db=nullable({"type": "number"}), gain_db=nullable({"type": "number"}),
           hpf_hz=nullable({"type": "number"}), preset=nullable({"type": "string"}),
           color=nullable({"type": "string"})),
        op("drop", "object", object={"type": "string", "enum": list(OBJECTS)},
           name=nullable({"type": "string"}), quote=nullable({"type": "string"}),
           index={"type": ["integer", "null"], "minimum": 1,
                  "maximum": max(facts.CAPACITY[k] for k in ("ch", "bus", "dca", "mgrp", "main"))}),
        op("move_channel", "name", name=name, place=place, patch=socket(ins, "in"),
           stereo={"type": ["boolean", "null"]}),
        op("rename", "object", "name", "new_name", object={"type": "string", "enum": list(OBJECTS)},
           name=name, new_name=name),
        op("set", "object", "name", "field", "value", object={"type": "string", "enum": list(OBJECTS)},
           name=name, field={"type": "string", "enum": on_menu},
           value={"type": ["number", "string", "boolean", "null"]}),
        op("assign", "name", name=name,
           dca_add=names, dca_remove=names, mute_group_add=names, mute_group_remove=names,
           send_add={"type": ["array", "null"], "items": send}, send_remove=names),
        op("add_bus", name=nullable({"type": "string"}), stereo={"type": ["boolean", "null"]},
           index=index("bus"), members=members,
           mode={"type": ["string", "null"], "enum": [*facts.PLAN_SEND_MODES, None]},
           level_db={"type": ["number", "null"], "minimum": facts.SEND_LEVEL_DB_RANGE[0],
                     "maximum": facts.SEND_LEVEL_DB_RANGE[1]},
           to={"type": ["object", "null"], "properties": {
               "main": {"type": ["boolean", "null"]}, "output": socket(outs, "out")},
               "additionalProperties": False},
           color=nullable({"type": "string"}), preset=nullable({"type": "string"})),
        op("add_group", "object", object={"type": "string", "enum": ["dca", "mute_group"]},
           name=nullable({"type": "string"}), members=members,
           index={"type": ["integer", "null"], "minimum": 1, "maximum": facts.CAPACITY["dca"]}),
        op("order", "categories", categories={"type": "array", "items": name},
           channels={"type": ["array", "null"], "items": name}),
        op("add_output", "object", name=nullable({"type": "string"}),
           object={"type": "string", "enum": ["main", "matrix"]},
           index={"type": ["integer", "null"], "minimum": 1, "maximum": facts.CAPACITY["mtx"]},
           patch=socket(outs, "out")),
    ]
    properties = {
        "name": {"type": "string", "minLength": 1, "maxLength": patch.CHANGE_NAME_MAX},
        "ops": {"type": "array", "items": {"oneOf": ops}},
        "notes": {"type": "array", "items": {"type": "string"}}}
    required = ["name", "ops", "notes"]
    if build:
        # The Category table (`category_table.py`) as a small JSON list in the reply itself, in
        # place of the long rewrite of the conventions: one entry per category, code applies it.
        # Declared second, before `ops`: a decoding grammar keeps this order, and a table
        # forced after `notes` is easy for a small model to leave empty.
        properties = {"name": properties["name"],
                      "categories": {"type": "array", "items": category_table.ENTRY_SCHEMA},
                      "ops": properties["ops"], "notes": properties["notes"]}
        required = ["name", "categories", "ops", "notes"]
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def without_bounds(schema):
    """`schema` without the numeric `minimum` / `maximum` of every field: what a reply is
    checked against for SHAPE. A number past the console's range is a physical
    impossibility the compiler refuses by name, saying which limit ("bus 40: this console
    has 16 buses"), not a malformed reply for which a model is asked again."""
    if isinstance(schema, dict):
        return {k: without_bounds(v) for k, v in schema.items() if k not in ("minimum", "maximum")}
    if isinstance(schema, list):
        return [without_bounds(v) for v in schema]
    return schema


#: The most `notes` a Build reply's decoding grammar lets a model write, and the longest one. A
#: grammar that leaves the list open lets a weak (or fine-tuned) model write notes until the reply
#: cap -- the ops done, the reply still "unfinished" -- which made a build 2-5x slower. The bound is
#: on the WIRE schema only, the one a host builds its grammar from: a reply with more notes (a host
#: that sends no schema) is still read whole, never refused for it. The prompt asks for "one
#: sentence each"; measured replies carry at most 5, of at most 93 characters (oracles and local
#: runs, 2026-10-26), so 12 of 400 is room to spare.
NOTES_MAX = 12
NOTE_MAX_CHARS = 400


def wire_schema(schema):
    """The schema a host's decoding grammar is built from, for a Build: `without_bounds`, with
    `notes` bounded (`NOTES_MAX`, `NOTE_MAX_CHARS`) so the grammar cannot loop in them."""
    wire = without_bounds(schema)
    notes = (wire.get("properties") or {}).get("notes")
    if isinstance(notes, dict) and notes.get("type") == "array":
        wire["properties"]["notes"] = {**notes, "maxItems": NOTES_MAX,
                                       "items": {**(notes.get("items") or {}), "maxLength": NOTE_MAX_CHARS}}
    return wire


def explain(value, schema, validate) -> list[str]:
    """The problems of `value` against an intent `schema`, each naming the op and the field.

    `oneOf` reports only "matches none of the allowed shapes", which tells a model nothing it can
    fix in one more try. Each op is held to the shape its own `op` tag names instead, so the
    message says "ops[12] (add_output): missing required field 'object'" and, for a field that
    op does not have, which fields it does."""
    problems = validate(value, schema, path="intent")
    if not problems or not isinstance(value, dict) or not isinstance(value.get("ops"), list):
        return problems
    branches = {b["properties"]["op"]["enum"][0]: b for b in schema["properties"]["ops"]["items"]["oneOf"]}
    explained = []
    for n, op in enumerate(value["ops"]):
        tag = op.get("op") if isinstance(op, dict) else None
        if tag not in branches:
            explained.append(f"ops[{n}]: 'op' must be one of {', '.join(branches)}"
                             + (f", not {tag!r}" if tag else " and is missing"))
            continue
        explained += validate(op, branches[tag], path=f"ops[{n}] ({tag})")
    rest = [p for p in problems if not p.startswith("intent.ops[") and "allowed shapes" not in p]
    return explained + rest if explained else problems
