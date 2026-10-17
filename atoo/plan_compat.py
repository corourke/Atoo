"""Where an output or a bus's dedicated output is patched -- read the same
way whatever a plan on disk calls it.

The vocabulary, fixed 2026-09-28: a **socket** is the physical input or
output on the desk; a **patch** is the connection between a channel or
bus and a socket. So an output's plan entry says where it is *patched*:

    "outputs": {"Matrix 1": {"patch": {"group": "LCL", "sockets": [7, 8], "stated": true},
                             "patches": [{"group": "USB", "sockets": [47]}, ...]}}

the same `{group, sockets, stated}` shape a channel's `patch` has, and a
bus's `destination` of type `dedicated_output` carries the same pair.
`patches` is the fan-out -- one entry per socket GROUP the output feeds at
once -- and is authoritative when it is not empty; `patch` is
the first, or only, one.

Plans written before an earlier change call these `socket` and `sockets`. Those plans
are on disk -- in every show bundle built before 2026-09-28 -- and still
have to verify, apply, render and open on the page, so EVERY reader goes
through this module rather than reading the keys itself. That is the
whole of the backward compatibility: one place that knows the old names.

`patch.sockets` INSIDE a patch keeps its name: those are the physical
sockets the connection lands on.
"""

from __future__ import annotations

#: The older key -> the key a plan uses now, on an `outputs` entry and
#: on a bus's `destination`.
RENAMED_KEYS = {"socket": "patch", "sockets": "patches"}


def normalise_entry(entry):
    """`entry` (an `outputs` value or a bus `destination`) with the old
    `socket`/`sockets` keys under their new names. A new key already
    present wins, and the old one is dropped either way. Returns `entry`
    itself when there is nothing to rename, else a shallow copy -- never
    mutates what it was given. Anything that is not a dict is returned
    unchanged."""
    if not isinstance(entry, dict) or not any(old in entry for old in RENAMED_KEYS):
        return entry
    out = {}
    for key, value in entry.items():
        new = RENAMED_KEYS.get(key)
        if new is None:
            out[key] = value
        elif new not in entry:
            out[new] = value
    return out


def normalise_plan(plan):
    """`plan` with every output and dedicated-output destination read by
    `normalise_entry` -- a copy of only what changed, the input never
    mutated. What `verify_plan` checks the schema against, so a plan built
    is not refused for a field it spelled the old way."""
    if not isinstance(plan, dict):
        return plan
    out = plan
    outputs = plan.get("outputs")
    if isinstance(outputs, dict):
        renamed = {name: normalise_entry(entry) for name, entry in outputs.items()}
        if any(renamed[name] is not outputs[name] for name in outputs):
            out = dict(out, outputs=renamed)
    busses = plan.get("busses")
    if isinstance(busses, dict):
        new_busses = {}
        changed = False
        for name, bus in busses.items():
            if isinstance(bus, dict):
                # `destination`, and the `destinations` list
                # when a bus states several.
                dest = bus.get("destination")
                fixed = normalise_entry(dest)
                if fixed is not dest:
                    bus = dict(bus, destination=fixed)
                    changed = True
                many = bus.get("destinations")
                if isinstance(many, list):
                    fixed_many = [normalise_entry(d) for d in many]
                    if any(a is not b for a, b in zip(fixed_many, many)):
                        bus = dict(bus, destinations=fixed_many)
                        changed = True
            new_busses[name] = bus
        if changed:
            out = dict(out, busses=new_busses)
    return out


def output_patch(entry):
    """The one (primary) patch of an output or a dedicated-output
    destination -- `{group, sockets, stated?}` -- or None when it states
    none (a null patch is legitimate: `output.no-patch` says so, at WARNING)."""
    entry = normalise_entry(entry)
    if not isinstance(entry, dict):
        return None
    return entry.get("patch")


def output_patches(entry) -> list:
    """Every patch of an output or a dedicated-output destination: the
    fan-out `patches` when it is not empty, else the one `patch`, else
    `[]`. Only object entries are returned: a patch written as a list or
    a string is not a patch (the schema check names it), and every caller
    reads `.get` off what comes back -- review 2026-09-28, R4, where a
    `patch` written as a list made `verify_plan` raise."""
    entry = normalise_entry(entry)
    if not isinstance(entry, dict):
        return []
    many = entry.get("patches")
    if isinstance(many, list) and many:
        return [p for p in many if isinstance(p, dict)]
    one = entry.get("patch")
    return [one] if isinstance(one, dict) else []
