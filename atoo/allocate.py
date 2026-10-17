"""Give a generated plan the console indices `apply` needs.

A generated plan is name-based -- a DCA called "Drums", a bus called
"Monitor 1" -- because that is what an engineer wrote and what a model can
reason about. The console is number-based: /dca/3, /bus/7, /mtx/2. Nothing
bridges the two without this.

The compiler has always done it. The generator did not, and the
consequence was a hard failure nobody had hit because nobody had tried:

    >>> apply_plan(generated_plan, console, dry_run=True)
    KeyError: 'index'

So a generated plan could pass verification and still be unapplyable.

**Allocation is code's job, not the model's** (D11). Which console
slot a named DCA occupies is not a judgement about the show -- it is
bookkeeping, it must be collision-free, and it must match what the
compiler would have chosen for the same plan. Asking a model for it would
add a way to be wrong (a duplicate index, a bus 17) in exchange for
nothing.

The compiler's own `_assign_indices` / `_assign_output_slots` are reused
rather than reimplemented, so a generated plan and a compiled one get
identical numbering for the same names.
"""

from __future__ import annotations

import re

from atoo import console_facts as facts
from atoo import inferred

# Capacities and the index-assignment helpers, moved here from compiler.py
# when the deterministic compile path was retired. This module
# is the only allocator now, which is what compiler.py's own import comment
# ("one allocator, deliberately") was always aiming at -- the functions just
# happened to live on the other side of the import.
#
# Note the overlap with `console_facts.CAPACITY`, which holds the same six
# numbers in a flat, Compact-only shape. These stay keyed by console model
# because `allocate_console_indices(console_model=...)` is, and collapsing
# the two is its own change, which is about the other
# console models these dicts exist to accommodate.

# All three models share a mainboard and therefore a DSP engine
# (`WING_Remote-Protocols-3.1-03.pdf` pp. 11-12: Rack and Compact "offer
# the same overall functionality than the initial WING" and each has the
# "Same Mainboard as on WING"), so these six counts are family-wide.
#
# Recorded as DOCUMENTED-COMMON, not hardware-verified: only the Compact
# has been walked (2026-09-08). That distinction is why the question stays open --
# but note it can never be closed by walking the other two either, because
# the address tree is identical across the family whatever the panel has.
# See `console_facts.CONSOLE_MODELS` for the counts that do differ.
_FAMILY_WIDE = ("wing-full", "wing-rack", "wing-compact")

CONSOLE_DCA_CAPACITY = dict.fromkeys(_FAMILY_WIDE, 16)

CONSOLE_MUTE_GROUP_CAPACITY = dict.fromkeys(_FAMILY_WIDE, 8)

CONSOLE_BUS_CAPACITY = dict.fromkeys(_FAMILY_WIDE, 16)

CONSOLE_MAIN_CAPACITY = dict.fromkeys(_FAMILY_WIDE, 4)

CONSOLE_MATRIX_CAPACITY = dict.fromkeys(_FAMILY_WIDE, 8)

# "## Outputs" entries are free-named ("Main", "Matrix", "MON1", "Drum
# wedge", ...) -- only entries whose name IS (optionally followed by a
# number) "Main"/"Matrix"/"Mtx" map onto the console's actual main.{1..4}
# / mtx.{1..8} objects; everything else is a bus's dedicated output or
# similar and has no main/matrix index concept at all. A trailing number
# is the engineer stating a specific slot ("Main 2") -- see
# _assign_output_slots for how that's honoured.
_OUTPUT_KIND_RE = re.compile(r"^(?P<kind>main|matrix|mtx)\s*(?P<index>\d+)?$", re.IGNORECASE)

def _assign_indices(names: list[str], capacity: int | None, label: str) -> tuple[dict[str, int], list[str]]:
    """The plan is name-based (a DCA called "Drums") but the console is
    number-based (DCA 1..16) -- O2/apply has nothing to write to without a
    console index for every DCA, mute group, and bus. Assigned
    deterministically in declaration order (the order names appear in
    `names`, which callers pass as the conventions file's own dict order --
    insertion order, i.e. the order the '## DCAs' etc. bullets were
    written), starting at 1, same policy as channel numbering above: never
    given by the conventions file, always computed, always recorded in the
    plan so it's reviewable/diffable rather than implicit. Indices are
    still assigned past `capacity` (a plan that's over budget is still a
    complete, diffable plan) -- the warning is what makes the overflow
    visible; apply.py's job, not this function's, to refuse writing an
    out-of-range index to real hardware."""
    warnings: list[str] = []
    indices = {name: i for i, name in enumerate(names, start=1)}
    if capacity is not None and len(names) > capacity:
        overflow = names[capacity:]
        warnings.append(
            f"{len(names)} {label}(s) declared but the console only has {capacity} -- "
            f"{', '.join(overflow)} assigned an index beyond what the console supports "
            "and cannot be applied as-is"
        )
    return indices, warnings

def _output_kind_and_explicit_index(
    name: str, stated_kind: str | None = None,
) -> tuple[str | None, int | None]:
    """`stated_kind` -- "main"/"matrix" the text or a generated
    plan said outright ("FOH is a main output"; a generated plan's own
    `outputs[name].kind`) -- wins over name-based guessing when given, so
    an output named anything at all still gets a console index as long as
    ITS KIND was stated. An explicit slot number is still read from the
    NAME regardless of where kind came from ("Main 2" states slot 2
    whether "main" was inferred from that name or handed in explicitly).
    An `index` the entry itself carries is read separately
    (`_stated_index`) and wins over the name -- review 2026-09-28, R1."""
    m = _OUTPUT_KIND_RE.match(name.strip())
    if stated_kind in ("main", "matrix"):
        index = int(m.group("index")) if m and m.group("index") else None
        return stated_kind, index
    if not m:
        return None, None
    kind = "matrix" if m.group("kind").lower() in ("matrix", "mtx") else "main"
    index = int(m.group("index")) if m.group("index") else None
    return kind, index

def _stated_index(entry) -> int | None:
    """The `index` an output entry already carries, when it is a usable
    slot number -- the slot apply will write for it, whatever its name
    says. Anything else (absent, a string, a bool) is not a claim."""
    if not isinstance(entry, dict):
        return None
    value = entry.get("index")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def _assign_output_slots(
    entries: list[tuple[str, int | None]], capacity: int | None, label: str,
    stated: dict[str, int] | None = None,
) -> tuple[dict[str, int], list[str]]:
    """Allocate a 1-based console slot (main.{n} or mtx.{n}) to each
    output entry. The owner's own words for Main: "would default to Main
    1 unless otherwise specified -- same idea as when we auto-allocate
    channels, pick the first available slot" -- so an entry that states
    an explicit slot (name "Main 2") claims it, and everything else fills
    the first free slot left over, in declaration order (exactly
    _assign_patches' auto-socket policy above, not _assign_indices'
    pure 1..N scheme, because an explicit slot can leave a gap another
    entry must skip over). Two entries explicitly claiming the same slot
    is a real conflict -- the second is treated as if it hadn't stated a
    slot at all (auto-assigned instead) rather than silently letting one
    win, and it's warned about by name. Indices are still assigned past
    `capacity` so the plan stays complete/diffable, same policy as
    _assign_indices."""
    warnings: list[str] = []
    claimed: dict[int, str] = {}
    unassigned: list[str] = []
    indices: dict[str, int] = {}

    # `stated` (review 2026-09-28, R1): entries that already carry an
    # `index` field. Those slots are taken, full stop -- the entry keeps
    # its index whatever this function decides, so an unnumbered sibling
    # must never be placed on it. Two entries STATING one index is a
    # physical conflict verify refuses (`output.index-duplicated`); it is
    # not resolved here, because the field is what apply would write.
    stated = stated or {}
    for name, slot in stated.items():
        claimed.setdefault(slot, name)
        indices[name] = slot

    for name, explicit in entries:
        if name in stated:
            continue
        if explicit is None:
            unassigned.append(name)
            continue
        if explicit in claimed:
            warnings.append(
                f"{label} {name!r} states slot {explicit}, already claimed by {label} "
                f"{claimed[explicit]!r} -- {name!r} left unassigned rather than guessing a "
                "different slot for it (auto-assigned to the next free one instead)"
            )
            unassigned.append(name)
            continue
        claimed[explicit] = name

    next_slot = 1
    for name in unassigned:
        while next_slot in claimed:
            next_slot += 1
        claimed[next_slot] = name
        next_slot += 1

    indices.update({name: slot for slot, name in claimed.items() if name not in stated})
    if capacity is not None:
        overflow = sorted((n for n, i in indices.items() if i > capacity), key=lambda n: indices[n])
        if overflow:
            warnings.append(
                f"{len(indices)} {label}(s) allocated but the console only has {capacity} -- "
                f"{', '.join(overflow)} assigned a slot beyond what the console supports "
                "and cannot be applied as-is"
            )
    return indices, warnings

def _output_index_basis(name: str, kind: str, explicit: int | None, slot: int,
                        of_kind: int) -> str:
    """What an allocated Main/Matrix index was decided from, in words the
    engineer can check against the plan -- the `basis` of its marker."""
    label = "Main" if kind == "main" else "Matrix"
    if explicit is not None and explicit == slot:
        return f"its name, {name!r}, states slot {slot}"
    if explicit is not None:
        return (f"its name states slot {explicit}, which another {label} already claims, "
                f"so it takes the first free slot, {slot}")
    if of_kind == 1:
        return f"the plan has one {label}, so it is {label} {slot}"
    return (f"the plan has {of_kind} {label}s and does not number this one, so it takes the "
            f"first free {label} slot in the order the plan declares them")


def allocate_console_indices(
    plan: dict, *, console_model: str | None = None
) -> list[str]:
    """Fill in every console index a plan is missing, in place.

    Returns warnings -- an overflow (a seventeenth DCA). Names already
    carrying an `index` are left alone, so this is safe to run on a compiled
    plan and on a re-run.

    Raises `console_facts.UnknownConsoleModel` when `console_model` is
    missing or unrecognised. It once returned a warning and skipped
    the overflow checks; an unknown model is now a hard
    stop, because "we have no way of knowing what its capabilities are and
    any plan would be meaningless". A skipped capacity check that reads as
    a pass is exactly the failure this project exists to prevent.
    """
    facts.panel_for(console_model)
    warnings: list[str] = []

    for key, capacity, label in (
        ("dcas", CONSOLE_DCA_CAPACITY.get(console_model), "DCA"),
        ("mute_groups", CONSOLE_MUTE_GROUP_CAPACITY.get(console_model), "mute group"),
        ("busses", CONSOLE_BUS_CAPACITY.get(console_model), "bus"),
    ):
        section = plan.get(key) or {}
        # Declaration order, exactly as the compiler assigns it -- so the
        # same plan gets the same numbers whichever path built it.
        indices, overflow = _assign_indices(list(section), capacity, label)
        warnings.extend(overflow)
        for name, entry in section.items():
            if isinstance(entry, dict) and "index" not in entry and name in indices:
                entry["index"] = indices[name]

    outputs = plan.get("outputs") or {}
    # An output's stated `kind` (the generator prompt documents
    # this field) wins over guessing from the name -- an output named
    # "FOH" gets a console index as long as the model said what it is,
    # the same fix as the deterministic compile path's own name-only
    # limitation.
    kinds = {
        name: _output_kind_and_explicit_index(
            name, entry.get("kind") if isinstance(entry, dict) else None)
        for name, entry in outputs.items()
    }
    # Review 2026-09-28, R1: an output that already carries an `index`
    # has TAKEN that slot -- apply writes it as-is. Allocation used to read
    # an explicit slot from the name only, so `FOH {index: 2}` beside an
    # unnumbered `Broadcast` handed Broadcast slot 2 as well: two Mains on
    # one index, Main 1 patched to nothing. The stated index now claims
    # its slot before any unnumbered sibling is placed.
    stated = {name: _stated_index(entry) for name, entry in outputs.items()}
    mains = [(n, i) for n, (k, i) in kinds.items() if k == "main"]
    matrices = [(n, i) for n, (k, i) in kinds.items() if k == "matrix"]

    main_indices, main_overflow = _assign_output_slots(
        mains, CONSOLE_MAIN_CAPACITY.get(console_model), "main output",
        stated={n: stated[n] for n, _ in mains if stated[n] is not None})
    matrix_indices, matrix_overflow = _assign_output_slots(
        matrices, CONSOLE_MATRIX_CAPACITY.get(console_model), "matrix output",
        stated={n: stated[n] for n, _ in matrices if stated[n] is not None})
    warnings.extend(main_overflow + matrix_overflow)

    for name, entry in outputs.items():
        if not isinstance(entry, dict):
            continue
        kind, explicit = kinds[name]
        entry.setdefault("kind", kind)
        slots, peers = ((main_indices, mains) if kind == "main" else
                        (matrix_indices, matrices) if kind == "matrix" else ({}, []))
        if name in slots and "index" not in entry:
            # Which strip this entry IS -- a Matrix's `fed_by: {type:
            # main, index: N}` is matched against it -- so a filled index
            # announces itself (an inferred value that does not
            # announce itself is the defect). Verify reports the marker as
            # the INFO `inferred.output-index`. Haiku 4.5 left both indices
            # out of smallband's plan (2026-09-28); Sonnet states them.
            entry["index"] = slots[name]
            inferred.set_marker(entry, "index",
                                _output_index_basis(name, kind, explicit, slots[name], len(peers)),
                                "fallback")

    # A bus that says "routes to main" with no number: same resolution the
    # compiler uses, rather than apply.py's old hardcoded Main 1.
    # Review 2026-09-28, R1: the Mains the plan actually carries, stated
    # index or allocated, so a bus never defaults to a Main nothing feeds.
    # R6: which Main is a choice, so the bus is marked and verify reports
    # it (`inferred.bus-main-index`). Every "main" entry in
    # `destinations` gets the same Main as the singular mirror.
    for bus in (plan.get("busses") or {}).values():
        if isinstance(bus, dict):
            inferred.fill_main_destination_index(bus, main_indices)

    return warnings
