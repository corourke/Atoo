"""Bus presets, resolved into the plan.

The decision, 2026-10-12: effects on FX busses come from **bus
presets saved on the desk**. A plan's bus names one (`busses[X].preset`),
chosen by the conventions the same way a channel's preset is ("FX busses
get the bus preset of the same name"), and `build` expands it here, the
way `preset_expand` expands a channel's -- so the plan says exactly what
will be written, and `apply` never opens a `.bus`:

    "preset": "Vox Verb",
    "preset_values": {
      "preset":  "Vox Verb",            # the preset's own name (info_text)
      "file":    "FX Vox Verb.bus",
      "library": "/home/me/presets",
      "sha256":  "…",
      "leaves":  {"eq/on": 0, "dyn/thr": -10.0, …},   # the bus's processing
      "overridden": {…},                               # what the plan's own won over
      "inserts": [{
        "point": "preins",              # the bus's pre-insert
        "model": "V-REV",               # loaded into the engine
        "parameters": {"pdel": 20, "dcy": 1.5, …},
        "saved_engine": 5,              # where the preset was saved from
        "saved_on": false,              # saved bypassed
        "engine": 5                     # allocated (fx_engines.allocate)
      }]
    }

`leaves` follow the channel preset's rules, on the bus allow-list
(`presets.classify_bus_leaf`) and typed by the parameter map's own
`/bus/{n}/...` entries (`initialize.leaf_types`). `inserts[].parameters`
are carried as saved; `fx_engines.coerce_param` types each one when it is
checked (verify) and written (apply).

**The insert is always switched ON.** A preset saved with its insert
bypassed (the Vox Verb is) is switched on, with an INFO, because an
FX bus with its effect bypassed is a silent FX bus.
"""

from __future__ import annotations

from atoo import fx_engines
from atoo.diagnostics import Diagnostic, Severity
from atoo.presets import (INSERT_POINT_NAMES, PresetError, classify_bus_leaf,
                               normalize_preset_name)

PRESET_KEY = "preset"
VALUES_KEY = "preset_values"
BANK = "bus"
_MODEL_VARIANT_LISTS = frozenset({"dyn/ratio"})


def bus_where(name: str) -> str:
    return f"busses[{name}]"


def bus_label(name: str, entry: dict) -> str:
    index = entry.get("index")
    return f"bus {index} ({name!r})" if index is not None else f"bus {name!r}"


def leaf_spec(address: str) -> dict | None:
    from atoo.initialize import leaf_types

    return leaf_types().get(f"/bus/{{n}}/{address}")


def leaf_refusal(address: str) -> str | None:
    """Why a bus preset value at `address` (strip-relative, `eq/1g`) may not
    be written, or None. The same rules at build, verify and apply."""
    leaf = address.replace("/", ".")
    if classify_bus_leaf(leaf) != "in_scope":
        return ("not on the bus preset allow-list -- a bus preset writes the bus's processing "
                "only, never its width, routing, level, name or tags")
    if leaf_spec(address) is None:
        return "no confirmed type for this leaf, so there is no honest way to write it"
    return None


def coerce_leaf(address: str, value) -> tuple[object, str | None]:
    """`(value, None)` in the type the desk takes, or `(None, why)`."""
    from atoo.initialize import coerce

    spec = leaf_spec(address)
    if spec is None:
        return None, "no confirmed type for this leaf"
    if spec["osc"] in ("i", "f") and (isinstance(value, str) or value is None):
        return None, f"{value!r} is not a number"
    out = coerce(value, spec)
    tokens = spec.get("tokens")
    if (spec["osc"] == "s" and tokens and address not in _MODEL_VARIANT_LISTS
            and out not in tokens):
        return None, f"a bus strip's {address} has no {out!r} (it offers {', '.join(tokens)})"
    return out, None


def leaf_osc(address: str) -> str | None:
    spec = leaf_spec(address)
    return spec["osc"] if spec else None


def preset_values(entry: dict) -> dict | None:
    values = entry.get(VALUES_KEY) if isinstance(entry, dict) else None
    return values if isinstance(values, dict) else None


def inserts(entry: dict) -> list[dict]:
    values = preset_values(entry) or {}
    out = values.get("inserts")
    return [i for i in out if isinstance(i, dict)] if isinstance(out, list) else []


#: A strip's own inserts, on a channel, a bus, a Main or a Matrix.
OWN_INSERTS_KEY = "inserts"
_POINT_ORDER = {"preins": 0, "postins": 1}


def own_inserts(entry: dict) -> list[dict]:
    out = entry.get(OWN_INSERTS_KEY) if isinstance(entry, dict) else None
    return [i for i in out if isinstance(i, dict)] if isinstance(out, list) else []


def strip_inserts(entry: dict) -> list[dict]:
    """Every insert the plan puts on a strip, one per point, pre before
    post: the strip's own `inserts` (a capture's, or the bus
    sheet's fx cell), and a bus preset's at a point those do not name. An
    entry whose `model` is None takes the insert at its point off."""
    own = own_inserts(entry)
    named = {i.get("point") for i in own}
    merged = [i for i in inserts(entry) if i.get("point") not in named] + own
    return sorted(merged, key=lambda i: _POINT_ORDER.get(i.get("point"), 2))


def plan_strips(plan: dict):
    """`(bank, index, label, entry)` for every channel, bus, Main and Matrix
    of `plan` with an index: what `strip_inserts` is read on. `bank` is the
    desk's (`ch`, `aux`, `bus`, `main`, `mtx`), so `/{bank}/{index}` is the
    strip."""
    for ch in plan.get("channels") or []:
        if isinstance(ch, dict) and isinstance(ch.get("channel"), int):
            bank = ch.get("bank") or "ch"
            yield bank, ch["channel"], f"{bank} {ch['channel']} ({ch.get('name')!r})", ch
    for name, entry in (plan.get("busses") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("index"), int):
            yield "bus", entry["index"], bus_label(name, entry), entry
    for name, entry in (plan.get("outputs") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("index"), int) \
                and entry.get("kind") in ("main", "matrix"):
            bank = "main" if entry["kind"] == "main" else "mtx"
            word = "Main" if bank == "main" else "Matrix"
            yield bank, entry["index"], f"{word} {entry['index']} ({name!r})", entry


def expansion_matches_name(entry: dict) -> bool:
    values = preset_values(entry)
    name = entry.get(PRESET_KEY)
    if values is None or not name:
        return False
    return normalize_preset_name(str(values.get("preset", ""))) == normalize_preset_name(name)


def explicit_addresses(name: str, entry: dict) -> dict[str, object]:
    """`{address under the bus: value}` for the bus's own typed processing
    (its EQ and tilt) -- what a preset value at the same address loses to."""
    from atoo import apply

    base = "/bus/0"
    targets, _ = apply._strip_processing_targets(base, "bus", name, entry.get("processing"))
    return {t.address[len(base) + 1:]: t.compute_value(None) for t in targets}


def _ordered(addresses) -> list[str]:
    from atoo.preset_expand import ordered

    return ordered(addresses)


def expand_bus(name: str, entry: dict, library) -> list[Diagnostic]:
    """Resolve this bus's named preset into `preset_values`, in place,
    WITHOUT allocating engines (`expand_busses` does that over all of
    them). Always recomputed: a bus naming no preset, or one the library
    does not have, ends up with no `preset_values`."""
    from atoo.preset_expand import file_sha256

    entry.pop(VALUES_KEY, None)
    preset_name = entry.get(PRESET_KEY)
    if not preset_name or library is None:
        return []
    try:
        preset = library.bus_get(preset_name)
    except PresetError:
        return []   # verify says preset.unknown
    where, label = bus_where(name), bus_label(name, entry)
    findings: list[Diagnostic] = []
    for warning in preset.warnings:
        findings.append(Diagnostic(
            severity=Severity.WARNING, code="preset.leaf-dropped", where=where,
            message=f"{label}: bus preset {preset.name!r} ({preset.source_path.name}): {warning}",
            source="build"))

    explicit = explicit_addresses(name, entry)
    leaves: dict[str, object] = {}
    overridden: dict[str, object] = {}
    for leaf, raw in preset.parameters.items():
        address = leaf.replace(".", "/")
        refusal = leaf_refusal(address)
        value = None
        if refusal is None:
            value, refusal = coerce_leaf(address, raw)
        if refusal is not None:
            findings.append(Diagnostic(
                severity=Severity.WARNING, code="preset.leaf-untyped", where=where,
                message=f"{label}: bus preset {preset.name!r} carries {leaf}={raw!r}, which is "
                        f"not carried into the plan: {refusal}",
                source="build"))
            continue
        if address in explicit:
            overridden[address] = value
        else:
            leaves[address] = value

    entry[VALUES_KEY] = {
        "preset": preset.name,
        "file": preset.source_path.name,
        "library": str(library.directory),
        "sha256": file_sha256(preset.source_path),
        "leaves": {a: leaves[a] for a in _ordered(leaves)},
        "overridden": {a: overridden[a] for a in _ordered(overridden)},
        "inserts": [{
            "point": ins.point,
            "model": ins.model,
            "parameters": dict(ins.parameters),
            "saved_engine": ins.saved_engine,
            "saved_on": ins.saved_on,
            "engine": None,
        } for ins in preset.inserts],
    }
    changed = [a for a in _ordered(overridden) if overridden[a] != explicit[a]]
    if changed:
        findings.append(Diagnostic(
            severity=Severity.INFO, code="preset.overridden", where=where,
            message=f"{label}: the plan's own processing wins at {len(changed)} address(es) the "
                    f"bus preset {preset.name!r} also sets -- "
                    + "; ".join(f"{a} preset {overridden[a]!r} -> plan {explicit[a]!r}"
                                for a in changed),
            source="build"))
    return findings


def insert_owner(name: str, entry: dict, point: str) -> str:
    return f"{bus_label(name, entry)}'s {INSERT_POINT_NAMES.get(point, point)}"


def claimed_engines(plan: dict, skip=()) -> dict[int, str]:
    """Engines the plan already inserts (engine -> who), on any strip,
    leaving out the busses named in `skip`. An insert taken off claims
    nothing."""
    out: dict[int, str] = {}
    skipped = [e for name, e in (plan.get("busses") or {}).items() if name in skip]
    for _bank, _index, label, entry in plan_strips(plan):
        if any(entry is e for e in skipped):
            continue
        for ins in strip_inserts(entry):
            if isinstance(ins.get("engine"), int) and ins.get("model") is not None:
                out.setdefault(ins["engine"],
                               f"{label}'s {INSERT_POINT_NAMES.get(ins.get('point'), ins.get('point'))}")
    return out


def own_claimed_engines(plan: dict) -> dict[int, str]:
    """Engines a strip's own `inserts` hold: what a bus
    preset's effect must not be given."""
    out: dict[int, str] = {}
    for _bank, _index, label, entry in plan_strips(plan):
        for ins in own_inserts(entry):
            if isinstance(ins.get("engine"), int) and ins.get("model") is not None:
                out.setdefault(ins["engine"],
                               f"{label}'s {INSERT_POINT_NAMES.get(ins.get('point'), ins.get('point'))}")
    return out


def allocate_engines(plan: dict, only=None, taken: dict[int, str] | None = None) -> list[Diagnostic]:
    """Give every bus preset's effect an engine (`fx_engines.allocate`), in
    the plan's bus order, and say what was chosen and why -- in place.
    `only` limits it to those busses, around the engines in `taken`."""
    requests, slots = [], {}
    for name, entry in (plan.get("busses") or {}).items():
        if only is not None and name not in only:
            continue
        for k, ins in enumerate(inserts(entry)):
            ins["engine"] = None
            if not fx_engines.is_known_model(ins.get("model")):
                continue
            key = (name, k)
            slots[key] = (name, entry, ins)
            requests.append(fx_engines.EngineRequest(
                key=key, owner=insert_owner(name, entry, ins.get("point")),
                model=ins["model"], saved_engine=ins.get("saved_engine")))
    findings: list[Diagnostic] = []
    for key, allocation in fx_engines.allocate(requests, taken).items():
        name, entry, ins = slots[key]
        ins["engine"] = allocation.engine
        if allocation.engine is None:
            continue   # verify: fx.no-engine
        findings.append(Diagnostic(
            severity=Severity.INFO, code="fx.engine-allocated", where=bus_where(name),
            message=f"{insert_owner(name, entry, ins.get('point'))}: {ins['model']} goes into "
                    f"FX{allocation.engine} -- {allocation.reason}",
            source="build"))
    return findings


def expand_added_busses(plan: dict, names: list[str], library) -> list[Diagnostic]:
    """`patch`'s half: expand only the busses a change adds,
    and give their effects engines the busses already on the desk leave
    free. The engines are judged free from the plan on the desk alone,
    as a new bus's index is."""
    if library is None or not names:
        return []
    return expand_busses(plan, library, only=set(names),
                         taken=claimed_engines(plan, skip=set(names)))


def expand_busses(plan: dict, library, only=None,
                  taken: dict[int, str] | None = None) -> list[Diagnostic]:
    """`expand_bus` for every bus (or those in `only`), then
    `allocate_engines`, then one INFO each for an insert that was saved
    bypassed and a parameter typed from its saved value. Mutates `plan`."""
    findings: list[Diagnostic] = []
    for name, entry in (plan.get("busses") or {}).items():
        if isinstance(entry, dict) and (only is None or name in only):
            findings.extend(expand_bus(name, entry, library))
    if taken is None:
        taken = own_claimed_engines(plan)
    findings.extend(allocate_engines(plan, only, taken))
    for name, entry in (plan.get("busses") or {}).items():
        if not isinstance(entry, dict) or (only is not None and name not in only):
            continue
        for ins in inserts(entry):
            owner = insert_owner(name, entry, ins.get("point"))
            if ins.get("saved_on") is False and ins.get("engine"):
                findings.append(Diagnostic(
                    severity=Severity.INFO, code="fx.insert-switched-on", where=bus_where(name),
                    message=f"{owner}: the preset {preset_values(entry)['preset']!r} was saved "
                            f"with its insert bypassed; it is switched on, because an FX bus "
                            f"with its effect bypassed is silent",
                    source="build"))
            from_value = [p for p, v in (ins.get("parameters") or {}).items()
                          if fx_engines.is_engine_parameter(p)
                          and not fx_engines.param_type(p, v)[1]]
            if from_value and ins.get("engine"):
                findings.append(Diagnostic(
                    severity=Severity.INFO, code="fx.parameter-typed-from-value",
                    where=bus_where(name),
                    message=f"{owner}: {len(from_value)} of {ins.get('model')}'s parameters "
                            f"({', '.join(from_value)}) are written with the type their saved "
                            f"value has -- the parameter map has no single type for them (it "
                            f"was walked with other models loaded); each is read back",
                    source="build"))
    expanded = [f"{name}: {preset_values(e)['preset']!r}"
                + "".join(f" ({i['model']} on FX{i['engine']})" for i in inserts(e) if i.get("engine"))
                for name, e in (plan.get("busses") or {}).items()
                if isinstance(e, dict) and preset_values(e) and (only is None or name in only)]
    if expanded:
        findings.insert(0, Diagnostic(
            severity=Severity.INFO, code="preset.bus-expanded", where="plan",
            message=f"{len(expanded)} bus(ses) carry a bus preset's values, resolved from "
                    f"{library.directory}: " + ", ".join(expanded),
            source="build"))
    return findings
