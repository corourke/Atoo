"""Validate a document against the subset of JSON Schema this project uses.

Stdlib only, on purpose. `jsonschema` would be the obvious import, but it
pulls `attrs`, `referencing` and `rpds-py` -- the last a compiled
extension -- and Atoo's install has to stay a thing you can do on a
venue laptop with no toolchain (FR-X.9's spirit: no vendor dependency in
the core). We also own both schemas, so the subset they use is known and
closed rather than arbitrary.

Supported: type (single or list), properties, required,
additionalProperties (bool or schema), items, enum, minimum, maximum,
minLength, maxLength, minItems, maxItems, oneOf, anyOf (read as oneOf: a
value must match some branch). Anything else in a schema
is IGNORED -- so if you add a keyword to plan_schema.py, add it here too
or it silently stops being enforced. `test_schema_check.py` asserts the
two stay in step.

Returns a list of human-readable errors, each naming its path. Never
raises on bad input: a malformed plan is a finding, the same policy as
verify_plan.
"""

from __future__ import annotations

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}

# Every keyword this module understands. plan_schema.py must not use one
# that is missing here, or the schema would claim a constraint nothing
# enforces -- the exact failure mode this whole file exists to avoid.
SUPPORTED_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "items",
    "enum", "minimum", "maximum", "minLength", "maxLength",
    "minItems", "maxItems", "oneOf", "anyOf",
})


def _type_ok(value, expected: str) -> bool:
    py = _TYPES.get(expected)
    if py is None:
        return True                      # unknown type name: not ours to judge
    if expected == "integer":
        # JSON has no int/float distinction, but a bool is not an integer
        # here -- `"channel": true` must fail.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, py)


def _check(value, schema: dict, path: str, errors: list[str]) -> None:
    if "oneOf" in schema or "anyOf" in schema:
        branches = schema.get("oneOf") or schema["anyOf"]
        if not any(not _collect(value, b, path) for b in branches):
            errors.append(f"{path}: matches none of the {len(branches)} allowed shapes")
        return

    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, n) for n in names):
            got = type(value).__name__
            errors.append(f"{path}: expected {' or '.join(names)}, got {got}")
            return                       # further checks would be noise

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(v) for v in schema["enum"])
        errors.append(f"{path}: {value!r} is not one of {allowed}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: must not be shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(
                f"{path}: {len(value)} characters, limit is {schema['maxLength']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value:g} is below the minimum {schema['minimum']:g}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value:g} is above the maximum {schema['maximum']:g}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: at most {schema['maxItems']} item(s), got {len(value)}")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{i}]", errors)

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field {key!r}")
        for key, item in value.items():
            child = f"{path}.{key}" if path else key
            if key in properties:
                _check(item, properties[key], child, errors)
                continue
            extra = schema.get("additionalProperties", True)
            if extra is False:
                errors.append(
                    f"{child}: not a field this format has"
                    + (f" (known: {', '.join(sorted(properties))})" if properties else ""))
            elif isinstance(extra, dict):
                _check(item, extra, child, errors)


def _collect(value, schema: dict, path: str) -> list[str]:
    errors: list[str] = []
    _check(value, schema, path, errors)
    return errors


def validate(instance, schema: dict, *, path: str = "plan") -> list[str]:
    """Every way `instance` fails `schema`, as readable strings.

    Empty list means valid. Order is document order, so the first error is
    usually the one to fix.
    """
    return _collect(instance, schema, path)


def unsupported_keywords(schema: dict) -> set[str]:
    """Keywords used by `schema` that this module does not enforce.

    A schema promising something nothing checks is worse than a looser
    schema, because it reads as a guarantee. A test walks both project
    schemas through this and fails if it returns anything.
    """
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in ("properties",) and isinstance(child, dict):
                    for sub in child.values():
                        walk(sub)
                    found.add(key)
                    continue
                if key in SUPPORTED_KEYWORDS:
                    found.add(key)
                    if key in ("items", "additionalProperties", "oneOf", "anyOf"):
                        walk(child)
                elif isinstance(child, (dict, list)):
                    found.add(key)
                    walk(child)
                else:
                    found.add(key)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return found - SUPPORTED_KEYWORDS


# ---------------------------------------------------------------------------
# Anthropic structured outputs: what their decoder can and cannot be given.
# ---------------------------------------------------------------------------
#
# `output_config.format` does not take JSON Schema, it takes a subset, and a
# schema outside that subset is a 400 rather than a warning. Found the hard
# way on the first real hosted run:
#
#   HTTP 400 output_config.format.schema: For 'integer' type, properties
#   maximum, minimum are not supported
#
# The vendor SDKs strip these silently and re-check them client-side.
# Atoo talks plain HTTP on purpose (FR-X.9), so it does the same job
# here, explicitly.

# Constraints the decoder cannot enforce. Dropping them costs nothing: every
# generated plan is validated locally against the FULL schema afterwards
# (generate.py), which is the check that was always doing the real work --
# constrained decoding only ever bought a guarantee of well-formedness.
_UNSUPPORTED_CONSTRAINTS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern",
    "minItems", "maxItems", "uniqueItems",
})


def anthropic_schema(schema: dict) -> dict | None:
    """`schema` projected onto Anthropic's structured-output subset, or None
    if it cannot be expressed there at all.

    None is not a failure to handle by guessing: it means constrained
    decoding is unavailable for this shape, and the caller should send no
    schema rather than a lie about one. The plan format hits this today --
    `busses`, `outputs`, `dcas` and `mute_groups` are open maps keyed by the
    engineer's own names, expressed as `additionalProperties: <subschema>`,
    and the subset allows `additionalProperties` to be `false` and nothing
    else. There is no rewriting around it: `false` would forbid every bus.
    Reshaping those maps into arrays would make the
    whole format expressible.
    """
    if not _expressible(schema):
        return None
    return _project(schema)


# Anthropic's structured outputs refuse a schema with more than this many
# optional properties (keys not in their object's `required`), counted
# across the whole schema: "Schemas contains too many optional parameters
# (103), which would make grammar compilation inefficient ... (limit: 24)."
# The compact reply has ~100, one per field a reply may leave out; getting
# under 24 would make ~80 of them required-but-null, written out on every
# channel, for a guarantee the local validation and repair already give.
ANTHROPIC_MAX_OPTIONAL = 24


def optional_count(schema) -> int:
    """How many properties across `schema` are not required."""
    count = 0
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            required = set(schema.get("required") or [])
            count += sum(1 for key in props if key not in required)
        count += sum(optional_count(v) for v in schema.values())
    elif isinstance(schema, list):
        count += sum(optional_count(v) for v in schema)
    return count


def anthropic_format(schema: dict) -> dict | None:
    """What to send as `output_config.format`'s schema: the projection
    (`anthropic_schema`), or None when there is none or the API would
    refuse it for its size (`ANTHROPIC_MAX_OPTIONAL`). None means send no
    schema: every reply is validated locally against the full one anyway.
    Every 2026-09-30 Sonnet build was refused for this, then asked again
    without it -- a wasted round trip per call."""
    projected = anthropic_schema(schema)
    if projected is None or optional_count(projected) > ANTHROPIC_MAX_OPTIONAL:
        return None
    return projected


def _expressible(node) -> bool:
    if isinstance(node, dict):
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):           # an open map, keyed by name
            return False
        return all(_expressible(v) for v in node.values())
    if isinstance(node, list):
        return all(_expressible(v) for v in node)
    return True


def _project(node):
    if isinstance(node, list):
        return [_project(v) for v in node]
    if not isinstance(node, dict):
        return node

    out = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_CONSTRAINTS:
            continue
        if key == "oneOf":
            # anyOf is in the supported list, oneOf is not. For these
            # schemas the two mean the same thing -- the branches are
            # disjoint (an object, or null) -- so the decoder's behaviour is
            # unchanged. schema_check still applies the stricter oneOf
            # locally.
            out["anyOf"] = _project(value)
            continue
        out[key] = _project(value)

    # An enum under a list of types ({"type": ["string", "null"], "enum":
    # ["E84", ..., None]}) is refused outright: "Enum value 'E84' does not
    # match declared type '['string', 'null']'" -- every Sonnet call of the
    # 2026-09-29 rebuilds lost its schema to this, and was asked again
    # without one. Split into one branch per type, each with its own values.
    if isinstance(out.get("type"), list) and "enum" in out:
        values = out.pop("enum")
        branches = []
        for kind in out.pop("type"):
            mine = [v for v in values if _TYPES.get(kind) is not None
                    and isinstance(v, _TYPES[kind]) and not
                    (kind in ("integer", "number") and isinstance(v, bool))]
            if kind == "null":
                branches.append({"type": "null"})
            elif mine:
                branches.append({"type": kind, "enum": mine})
        out["anyOf"] = branches

    # "additionalProperties: false is required for all objects."
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out
