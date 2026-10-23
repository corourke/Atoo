"""A reply schema in the form OpenAI-compatible hosts take for
`response_format: {"type": "json_schema", "json_schema": {"strict": true}}`,
and the way back from what they reply (The api provider path).

Strict mode takes a SUBSET of JSON Schema, the same way Anthropic's decoder
does (`schema_check.anthropic_schema`), but a different one:

  * every object lists every property in `required`, and says
    `additionalProperties: false`;
  * a property that may be left out is written as nullable instead, and the
    model says "unstated" with `null`;
  * an object whose keys are the engineer's own names (a bus map, a DCA map,
    `mute_groups`, a modify entry's `fields`) cannot be described at all.

Those last two are the plan format's open maps. They are not dropped and
not guessed: each is sent as an ARRAY, which strict mode does express --
`[{"key": name, "value": entry}]` for a map of known entries, and
`[{"key": path, "json": "<the value as JSON text>"}]` for an object whose
values have no common shape -- and `from_wire` turns the reply back into the
object the rest of Atoo reads. `to_wire` is the same step in the other
direction; it exists so a test can prove the two schemas accept the same
replies (every valid reply survives `from_wire(to_wire(x)) == x`).

Constraints strict mode refuses (`minimum`, `maxLength`, `minItems`, ...) are
not sent. Every reply is validated locally against the full schema either way,
so what is lost is a guarantee of shape, never a check.
"""

from __future__ import annotations

import json

from atoo.schema_check import _TYPES, _UNSUPPORTED_CONSTRAINTS

#: What the wire form of an open map and of a free-form object is called, so
#: the prompt note (`WIRE_NOTE`) and the schema agree.
KEY, VALUE, JSON = "key", "value", "json"

#: Added to the system prompt when the wire schema is sent. The prompt's
#: format section describes these objects as JSON objects, which is what
#: Atoo reads; the schema a strict host enforces cannot, and a model
#: shown both needs to be told which wins.
WIRE_NOTE = f"""

## The reply's wire form

This reply is checked against a JSON schema that cannot describe an object
whose keys are names you choose. So wherever the format above shows such an
object -- the `busses`, `dcas`, `mute_groups` and `outputs` maps, a `modify`
entry's `fields`, a channel's `provenance` object -- write it as an ARRAY of
entries instead:

  a map of named entries:      [{{"{KEY}": "<name>", "{VALUE}": <the entry>}}, ...]
  an object of loose values:   [{{"{KEY}": "<key>", "{JSON}": "<the value, written as JSON text>"}}, ...]

Everything else is as described above. A field the format lets you leave out
is still written: use `null` for "not stated"."""


class Inexpressible(ValueError):
    """The schema has a shape this module cannot send."""


def _py_matches(value, kind: str) -> bool:
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    py = _TYPES.get(kind)
    return py is not None and isinstance(value, py)


def branches(schema: dict) -> list[dict]:
    """`schema` as a list of single-shape schemas: `oneOf`/`anyOf` flattened,
    and a type list split into one schema per type (an enum under a type list
    is split too, each type keeping its own values)."""
    out: list[dict] = []
    for key in ("oneOf", "anyOf"):
        if key in schema:
            for branch in schema[key]:
                out.extend(branches(branch))
            return out
    kinds = schema.get("type")
    if isinstance(kinds, list):
        for kind in kinds:
            branch = {k: v for k, v in schema.items() if k != "type"}
            branch["type"] = kind
            if "enum" in branch:
                branch["enum"] = [v for v in branch["enum"] if
                                  (v is None if kind == "null" else _py_matches(v, kind))]
                if kind != "null" and not branch["enum"]:
                    continue
            out.append(branch)
        return out
    return [schema]


def kind_of(branch: dict) -> str:
    """null | scalar | array | object | map | free."""
    kind = branch.get("type")
    if kind == "null":
        return "null"
    if kind == "array":
        return "array"
    if kind == "object" or "properties" in branch:
        if "properties" in branch:
            return "object"
        if isinstance(branch.get("additionalProperties"), dict):
            return "map"
        return "free"
    return "scalar"


def _nullable(wire: dict) -> dict:
    if "anyOf" in wire:
        if any(b.get("type") == "null" for b in wire["anyOf"]):
            return wire
        return {"anyOf": wire["anyOf"] + [{"type": "null"}]}
    if wire.get("type") == "null":
        return wire
    return {"anyOf": [wire, {"type": "null"}]}


def _derive_one(branch: dict) -> dict:
    kind = kind_of(branch)
    if kind == "null":
        return {"type": "null"}
    if kind == "scalar":
        out = {k: v for k, v in branch.items() if k not in _UNSUPPORTED_CONSTRAINTS
               and k in ("type", "enum")}
        if "type" not in out:
            raise Inexpressible(f"a schema with no type: {branch!r}")
        return out
    if kind == "array":
        if "items" not in branch:
            raise Inexpressible("an array with no items schema")
        return {"type": "array", "items": derive(branch["items"])}
    if kind == "object":
        required = set(branch.get("required") or [])
        props = {}
        for name, sub in branch["properties"].items():
            wire = derive(sub)
            props[name] = wire if name in required else _nullable(wire)
        return {"type": "object", "properties": props,
                "required": list(props), "additionalProperties": False}
    if kind == "map":
        entry = {"type": "object",
                 "properties": {KEY: {"type": "string"},
                                VALUE: derive(branch["additionalProperties"])},
                 "required": [KEY, VALUE], "additionalProperties": False}
        return {"type": "array", "items": entry}
    entry = {"type": "object",
             "properties": {KEY: {"type": "string"}, JSON: {"type": "string"}},
             "required": [KEY, JSON], "additionalProperties": False}
    return {"type": "array", "items": entry}


def derive(schema: dict) -> dict:
    """`schema` in strict-mode form (see the module docstring)."""
    parts = [_derive_one(b) for b in branches(schema)]
    return parts[0] if len(parts) == 1 else {"anyOf": parts}


def strict_wire(schema: dict) -> dict | None:
    """The schema to send as `response_format.json_schema.schema`, or None
    when it has a shape strict mode cannot take (nothing is sent then)."""
    try:
        return derive(schema)
    except Inexpressible:
        return None


# --------------------------------------------------------------------------
# Value conversion
# --------------------------------------------------------------------------


def pick(value, branches: list[dict]) -> dict:
    """The branch of the ORIGINAL schema a reply value belongs to."""
    kinds = [(b, kind_of(b)) for b in branches]
    if len(kinds) == 1:
        return kinds[0][0]
    def first(*wanted):
        return next((b for b, k in kinds if k in wanted), None)
    if value is None:
        found = first("null")
    elif isinstance(value, dict):
        found = first("object", "map", "free")
    elif isinstance(value, list):
        found = first("array") or first("map", "free")
    else:
        found = next((b for b, k in kinds if k == "scalar"
                      and _py_matches(value, b.get("type", ""))), None)
    return found or branches[0]


def accepts_null(branches: list[dict]) -> bool:
    return any(kind_of(b) == "null" for b in branches)


def from_wire(value, schema: dict, dropped: list[str] | None = None, path: str = ""):
    """A strict-mode reply back to the shape `schema` describes: arrays
    become the maps they stand for, and a `null` on a property the schema
    lets a reply leave out is removed -- "not stated" -- with its dotted path
    appended to `dropped`. A `{key, json}` value that is not JSON text is kept
    as the string. Raises ValueError for a value of the wrong shape;
    the caller then keeps the raw text, and the ordinary validation says
    what is wrong with it."""
    options = branches(schema)
    branch = pick(value, options)
    kind = kind_of(branch)
    if kind in ("null", "scalar") or value is None:
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path or 'reply'}: expected a list")
        return [from_wire(v, branch["items"], dropped, f"{path}[{i}]")
                for i, v in enumerate(value)]
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path or 'reply'}: expected an object")
        required = set(branch.get("required") or [])
        out = {}
        for name, item in value.items():
            sub = branch["properties"].get(name)
            if sub is None:
                out[name] = item
                continue
            child = f"{path}.{name}" if path else name
            got = from_wire(item, sub, dropped, child)
            if got is None and name not in required and not accepts_null(branches(sub)):
                if dropped is not None:
                    dropped.append(child)
                continue
            out[name] = got
        return out
    if not isinstance(value, list) or not all(isinstance(e, dict) for e in value):
        raise ValueError(f"{path or 'reply'}: expected a list of {{key, ...}} entries")
    out = {}
    for entry in value:
        name = entry.get(KEY)
        if not isinstance(name, str):
            raise ValueError(f"{path or 'reply'}: an entry has no {KEY!r}")
        if kind == "map":
            out[name] = from_wire(entry.get(VALUE), branch["additionalProperties"],
                                  dropped, f"{path}.{name}" if path else name)
        else:
            # Text that is not JSON is kept as the string it is: the local
            # validator then judges that one value, and the rest of the
            # reply is not thrown away with it.
            try:
                out[name] = json.loads(entry.get(JSON))
            except (TypeError, ValueError):
                out[name] = entry.get(JSON)
    return out


def to_wire(value, schema: dict):
    """The inverse of `from_wire`, for a valid reply: every property the
    schema lists is present (`null` where the reply left it out), and each
    map is an array. Used to prove the two schemas accept the same replies."""
    options = branches(schema)
    branch = pick(value, options)
    kind = kind_of(branch)
    if kind in ("null", "scalar") or value is None:
        return value
    if kind == "array":
        return [to_wire(v, branch["items"]) for v in value]
    if kind == "object":
        return {name: (to_wire(value[name], sub) if name in value else None)
                for name, sub in branch["properties"].items()}
    if kind == "map":
        return [{KEY: k, VALUE: to_wire(v, branch["additionalProperties"])}
                for k, v in value.items()]
    return [{KEY: k, JSON: json.dumps(v)} for k, v in value.items()]
