"""Preset expansion: a named channel preset, resolved INTO the plan at build
time.

The design was settled on 2026-09-21:

- **`build` expands a named preset into the plan**, as resolved values
  carrying their provenance (which preset, which file). `apply` writes
  what the plan says; it never opens a `.chn` itself. A plan that says
  `preset: "Kick In"` and nothing else would be a plan that cannot be
  reviewed -- you would be approving a filename.
- **The plan always wins over the preset**, and says so out loud when it
  overrides one (an INFO naming both values).
- **Merge by ADDRESS, not by appending.** A preset's `eq/1g` and the
  plan's own EQ band 1 gain are the same parameter on the desk, so they
  produce ONE resolved value -- the plan's -- rather than two write
  targets whose list order decides which one lands.

## The plan-format change

One new, optional key on a channel's `processing`:

    "preset_values": {
      "preset":  "Kick In",              # the preset's own name (info_text)
      "file":    "Kick In.chn",          # which file it came from
      "library": "/home/me/presets",     # the library it was resolved in
      "sha256":  "…",                    # of that file's bytes, as expanded
      "leaves":  {"eq/1g": -5.5, "dyn/thr": -20.0, …},
      "overridden": {"flt/lcf": 40.19342422, …}
    }

`leaves` is keyed by the ADDRESS each value is written to, relative to
the strip (`/ch/1` + `eq/1g`) -- a dict, so one address holds one value
by construction. Relative rather than absolute because `amend` may place
a channel on a different strip from the one `build` numbered, and the
leaves must travel with it. `overridden` records what the preset wanted
at each address the plan's own processing took instead: it is never
written, it is there so a reviewer can see what the preset lost.

Every value is already in the type the desk takes (`LEAF_TYPES`): an int
for an on/off, a float for a knob, a string for a list choice. The
compressor and gate ride along without being typed in the schema --
nothing has to know what `dyn.thr` means to carry it and write it back.

A plan without `preset_values` is an older plan, or one built with no
library, and it still loads, verifies and applies; `verify` says the
named preset's values are not in it (`preset.not-expanded`), and `apply`
writes nothing from the preset.

## The type table

Every OSC write needs the right type tag, and a `.chn`'s JSON cannot say
which: `eq.3g: 0` is a float knob that happens to be whole, and
`dyn.ratio: 5` is a LIST choice whose token is `"5.0"`. `LEAF_TYPES` is
built from the evidence already in this repository, and each entry says
which:

- **map** -- the Compact parameter map, a walk of a
  real Compact's own parameter descriptions (firmware 3.1): `int` -> `i`,
  `lin`/`log` -> `f`, `list` -> `s`. This is the console describing itself,
  and it is the primary source.
- **JSON** -- the value types in four WING snapshots
  (`tests/fixtures/console-runs/Initialized-Compact.snap`,
  `tests/fixtures/Initialized-Full.snap`, `tests/fixtures/console-runs/Church-Full.snap`,
  and the A8 initialized snapshot) and
  in every `.chn` in `tests/fixtures/presets/` and
  `tests/fixtures/channel_presets/`. A bool agrees with `i`; a float or a whole
  number agrees with `f`; a string agrees with `s`.
- **hw** -- written by `apply` and read back as a match on a real desk:
  A3 (the EQ journal of 2026-09-21) for the
  EQ and PreSend EQ leaves, A1 (the apply journal of 2026-09-21)
  for the high-pass.

`confirmed=True` means the map and every JSON type seen agree.
`confirmed=False` means they disagree or the map has no entry, and the
choice recorded is the reasonable one, announced here rather than made
silently: `dyn.ratio` (the map says list, the JSON says number -- the
list wins, and a number is written as its list token), and five gate
leaves a newer firmware's snapshot carries that the 3.1 walk never saw
(`gate.col/drv/hrm/trim/wmix`, taken as knobs, `f`).

## Choices a strip's bank does not offer

A list value is also checked against the choices the strip's own bank
offers (`bank_choices`, from `initialized/leaf_types.json`): a `.chn` is a
channel's file, and a channel's `dynsc.tap` `IN` is not on an aux's list. Build carries the aux's equivalent where there is one
(`BANK_EQUIVALENTS`) and leaves the value out otherwise, both at INFO
(`preset.value-not-on-strip`); verify and apply refuse such a value in a
plan that still carries it. See the comment above `BANK_EQUIVALENTS`.

**None of these is confirmed on a desk as a preset write until desk
script A22 runs** (`a22-preset-apply.sh`). Every
write is read back, so a wrong tag surfaces as a readback mismatch in the
journal, never as a silently mis-set desk.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from atoo.diagnostics import Diagnostic, Severity
from atoo.presets import PresetError, _classify, normalize_preset_name

#: Which strip banks carry a leaf. From the parameter map: an aux strip has
#: `in/set`, `eq`, `dyn` and `dynsc` only -- no `flt`, `peq`, `gate`,
#: `gatesc` or `dynxo` node at all.
_CH = frozenset({"ch"})
_CH_AUX = frozenset({"ch", "aux"})


@dataclass(frozen=True)
class LeafType:
    """How one preset leaf is written: its OSC type tag, which strip banks
    have it, and the evidence for both."""

    osc: str                 # "i" | "f" | "s"
    banks: frozenset
    evidence: str
    confirmed: bool          # map and every JSON type seen agree
    hw: str | None = None    # desk run that wrote it and read it back as a match
    tokens: tuple = ()       # a list leaf's numeric tokens, as the desk spells them


_T = LeafType

# Generated from the evidence above, then kept by hand; see the module
# docstring for what each column means. `tests/test_preset_expand.py`
# re-derives the map half from the parameter map and fails if they drift.
LEAF_TYPES: dict[str, LeafType] = {
    "dyn.acc": _T("f", _CH_AUX, "map lin; JSON int", True),
    "dyn.att": _T("f", _CH_AUX, "map lin; JSON float/int", True),
    "dyn.auto": _T("i", _CH_AUX, "map int; JSON bool", True),
    "dyn.det": _T("s", _CH_AUX, "map list; JSON str", True),
    "dyn.env": _T("s", _CH_AUX, "map list; JSON str", True),
    "dyn.gain": _T("f", _CH_AUX, "map lin; JSON float/int", True),
    "dyn.hld": _T("f", _CH_AUX, "map lin/log; JSON int", True),
    "dyn.in": _T("f", _CH, "map lin; JSON int", True),
    "dyn.knee": _T("i", _CH_AUX, "map int; JSON int", True),
    "dyn.mdl": _T("s", _CH_AUX, "map list; JSON str", True),
    "dyn.mix": _T("f", _CH_AUX, "map lin; JSON int", True),
    "dyn.on": _T("i", _CH_AUX, "map int; JSON bool", True),
    "dyn.out": _T("f", _CH, "map lin; JSON int", True),
    "dyn.range": _T("f", _CH_AUX, "map lin; JSON int", True),
    # The one disagreement. The map describes `ratio` as a LIST under every
    # model it saw; the snapshots and every .chn carry a bare number for a
    # COMP-family model (5, 2.5) and a string for others ("4:1"). The list
    # wins -- it is the console describing its own control -- and a number
    # is written as the token the list spells it with (5 -> "5.0"), so the
    # readback compares like with like.
    "dyn.ratio": _T("s", _CH_AUX, "map list; JSON float/int/str -- DISAGREE", False,
                    tokens=("1.1", "1.2", "1.3", "1.5", "1.7", "2.0", "2.5", "3.0", "3.5",
                            "4.0", "5.0", "6.0", "8.0", "10", "20", "50", "100",
                            "4", "8", "12")),
    "dyn.rel": _T("f", _CH_AUX, "map lin/log; JSON float/int", True),
    "dyn.thr": _T("f", _CH_AUX, "map lin; JSON float/int", True),
    "dynsc.f": _T("f", _CH_AUX, "map log; JSON float", True),
    "dynsc.q": _T("f", _CH_AUX, "map log; JSON float", True),
    "dynsc.src": _T("s", _CH_AUX, "map list; JSON str", True),
    "dynsc.tap": _T("s", _CH_AUX, "map list; JSON str", True),
    "dynsc.type": _T("s", _CH_AUX, "map list; JSON str", True),
    "dynxo.depth": _T("f", _CH, "map lin; JSON int", True),
    "dynxo.f": _T("f", _CH, "map log; JSON float", True),
    "dynxo.q": _T("f", _CH, "map log; JSON float", True),
    "dynxo.type": _T("s", _CH, "map list; JSON str", True),
    "eq.1f": _T("f", _CH_AUX, "map log; JSON float/int", True, hw="A3"),
    "eq.1g": _T("f", _CH_AUX, "map lin; JSON float/int", True, hw="A3"),
    "eq.1q": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.2f": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.2g": _T("f", _CH_AUX, "map lin; JSON float/int", True, hw="A3"),
    "eq.2q": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.3f": _T("f", _CH_AUX, "map log; JSON float/int", True, hw="A3"),
    "eq.3g": _T("f", _CH_AUX, "map lin; JSON float/int", True, hw="A3"),
    "eq.3q": _T("f", _CH_AUX, "map log; JSON float", True),
    "eq.4f": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.4g": _T("f", _CH_AUX, "map lin; JSON float/int", True, hw="A3"),
    "eq.4q": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.heq": _T("s", _CH_AUX, "map list; JSON str", True, hw="A3"),
    "eq.hf": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.hg": _T("f", _CH_AUX, "map lin; JSON float/int", True, hw="A3"),
    "eq.hq": _T("f", _CH_AUX, "map log; JSON float", True),
    "eq.leq": _T("s", _CH_AUX, "map list; JSON str", True),
    "eq.lf": _T("f", _CH_AUX, "map log; JSON float", True, hw="A3"),
    "eq.lg": _T("f", _CH_AUX, "map lin; JSON float/int", True, hw="A3"),
    "eq.lq": _T("f", _CH_AUX, "map log; JSON float", True),
    "eq.mdl": _T("s", _CH_AUX, "map list; JSON str", True),
    "eq.mix": _T("f", _CH_AUX, "map lin; JSON int", True),
    "eq.on": _T("i", _CH_AUX, "map int; JSON bool", True, hw="A3"),
    "flt.hc": _T("i", _CH, "map int; JSON bool", True),
    "flt.hcf": _T("f", _CH, "map log; JSON float", True),
    "flt.hcs": _T("s", _CH, "map list; JSON str", True, tokens=("6", "12")),
    "flt.lc": _T("i", _CH, "map int; JSON bool", True, hw="A1"),
    "flt.lcf": _T("f", _CH, "map log; JSON float/int", True, hw="A1"),
    "flt.lcs": _T("s", _CH, "map list; JSON str", True, tokens=("6", "12", "18", "24")),
    "flt.mdl": _T("s", _CH, "map list; JSON str", True),
    "flt.tf": _T("i", _CH, "map int; JSON bool", True),
    "flt.tilt": _T("f", _CH, "map lin; JSON float/int", True),
    "gate.acc": _T("f", _CH, "map lin; JSON int", True),
    "gate.att": _T("f", _CH, "map lin; JSON int", True),
    "gate.col": _T("f", _CH, "no map entry; JSON float", False),
    "gate.depth": _T("f", _CH, "map lin; JSON float/int", True),
    "gate.drv": _T("f", _CH, "no map entry; JSON int", False),
    "gate.fast": _T("i", _CH, "map int; JSON bool", True),
    "gate.gain": _T("f", _CH, "map lin; JSON int", True),
    "gate.hld": _T("f", _CH, "map log; JSON float/int", True),
    "gate.hrm": _T("f", _CH, "no map entry; JSON int", False),
    "gate.mdl": _T("s", _CH, "map list; JSON str", True),
    "gate.mix": _T("f", _CH, "map lin; JSON int", True),
    "gate.on": _T("i", _CH, "map int; JSON bool", True),
    "gate.peak": _T("i", _CH, "map int; JSON bool", True),
    "gate.range": _T("f", _CH, "map lin; JSON float/int", True),
    "gate.ratio": _T("s", _CH, "map list; JSON str", True),
    "gate.rel": _T("f", _CH, "map log; JSON float", True),
    "gate.thr": _T("f", _CH, "map lin; JSON float/int", True),
    "gate.trim": _T("f", _CH, "no map entry; JSON int", False),
    "gate.wmix": _T("f", _CH, "no map entry; JSON int", False),
    "gatesc.f": _T("f", _CH, "map log; JSON float", True),
    "gatesc.q": _T("f", _CH, "map log; JSON float", True),
    "gatesc.src": _T("s", _CH, "map list; JSON str", True),
    "gatesc.tap": _T("s", _CH, "map list; JSON str", True),
    "gatesc.type": _T("s", _CH, "map list; JSON str", True),
    "in.set.dly": _T("f", _CH_AUX, "map lin; JSON float/int", True),
    "in.set.dlymode": _T("s", _CH_AUX, "map list; JSON str", True),
    "in.set.dlyon": _T("i", _CH_AUX, "map int; JSON bool", True),
    "peq.1f": _T("f", _CH, "map log; JSON float", True, hw="A3"),
    "peq.1g": _T("f", _CH, "map lin; JSON int", True, hw="A3"),
    "peq.1q": _T("f", _CH, "map log; JSON float", True),
    "peq.2f": _T("f", _CH, "map log; JSON float", True),
    "peq.2g": _T("f", _CH, "map lin; JSON int", True),
    "peq.2q": _T("f", _CH, "map log; JSON float", True),
    "peq.3f": _T("f", _CH, "map log; JSON float", True),
    "peq.3g": _T("f", _CH, "map lin; JSON int", True),
    "peq.3q": _T("f", _CH, "map log; JSON float", True),
    "peq.on": _T("i", _CH, "map int; JSON bool", True, hw="A3"),
}

PRESET_VALUES_KEY = "preset_values"


def leaf_address(leaf: str) -> str:
    """A `.chn` dotted leaf (`in.set.dly`) as the address under the strip
    it is written to (`in/set/dly`) -- the key `preset_values.leaves` uses."""
    return leaf.replace(".", "/")


def address_leaf(address: str) -> str:
    """The inverse: `eq/1g` -> `eq.1g`, for the allow-list and the table."""
    return address.replace("/", ".")


def leaf_type(address: str) -> LeafType | None:
    return LEAF_TYPES.get(address_leaf(address))


# The order a strip's preset leaves are written in, which matters twice:
#
# 1. **Selectors first.** A compressor's `thr`, `att` and `ratio` mean
#    different things under different `dyn.mdl` (the map records up to four
#    variants of each), and `in/set/dly` is metres or samples depending on
#    `dlymode`. Write the value before the model and the desk interprets it
#    against the model it is about to leave.
# 2. **Switches last.** A gate switched in before its threshold is set
#    gates at whatever threshold the strip had.
_SELECTOR_SUFFIXES = ("/mdl", "/dlymode", "/type", "/leq", "/heq")
_SWITCH_SUFFIXES = ("/on", "/dlyon")
_SWITCH_EXACT = {"flt/lc", "flt/hc", "flt/tf"}
# A bus's (and a Matrix's) output delay: `dly/mode` (M, FT, MS, SMP) says
# what unit `dly/dly` is in, exactly as a channel's `in/set/dlymode` does
# -- so it is a selector too. A bus preset carries it.
_DLY_MODE = "dly/mode"


SELECTOR, VALUE, SWITCH = 0, 1, 2


def write_order(address: str) -> int:
    """`SELECTOR` (0), `VALUE` (1) or `SWITCH` (2) for an address, relative
    to the strip (`flt/lc`) or absolute (`/ch/1/flt/lc`) -- both spellings
    classify the same."""
    if address.endswith(_SELECTOR_SUFFIXES) or address == _DLY_MODE or address.endswith("/" + _DLY_MODE):
        return SELECTOR
    if address.endswith(_SWITCH_SUFFIXES) or any(
            address == leaf or address.endswith("/" + leaf) for leaf in _SWITCH_EXACT):
        return SWITCH
    return VALUE


def ordered(addresses) -> list[str]:
    """Addresses in write order; stable within a class."""
    return sorted(addresses, key=write_order)


# Which values a selector GOVERNS. A governed value is one
# whose meaning the desk re-reads when the selector changes, so a baseline
# read under the old selector says nothing about what the value will read
# under the new one. Found at desk run A22 (2026-09-28): `in/set/dly` read
# 0.5 under `dlymode` M, apply switched the mode to FT, compared the
# preset's 0.5 against that stale 0.5 and skipped the write; undo then put
# the mode back and the delay read 0.1.
#
# The family is taken from the address, and is deliberately wide: writing
# a value the plan already intends costs one write and one readback, while
# leaving one out is the defect.
#
#   selector                 governs (on the same strip)
#   ---------------------    ----------------------------------------------
#   in/set/dlymode           in/set/dly -- ONLY that; trim, bal and inv
#                            share the node and do not depend on the mode
#   dly/mode (bus, mtx)      dly/dly -- every value in the `dly` node
#   dyn/mdl                  every dyn/* value (thr, att, ratio, rel, ...)
#   gate/mdl                 every gate/* value
#   eq/mdl, eq/leq, eq/heq   every eq/* value (bands, shelves, mix, tilt)
#   flt/mdl                  every flt/* value (lcf, hcf, tilt, slopes)
#   gatesc/type, dynxo/type  every value in that node (f, q, depth, ...)
#   dynsc/type
#
# "Every X/* value" means the leaves directly under the selector's own node
# that are neither a selector nor a switch (`write_order` VALUE): the
# `/on` of a node is not reinterpreted by a model change, and a second
# selector in the same node is ordered by its own class. The parameter map
# ("Instance variance")
# records per-model variants of exactly these: `dyn.thr/att/ratio/rel/
# hld/in/out`, `gate.thr` and `in/set.dly` -- every one inside a family
# above. It also records `/mtx/{n}/dly.dly`, governed by `/mtx/{n}/dly.
# mode` -- the `dly/mode` row (a bus preset writes a bus's).
#
# An FX engine's `/fx/{n}/mdl` is a selector by the same rule (`/mdl`), and
# governs every parameter directly under `/fx/{n}` -- the model decides
# which parameters exist at all (engines 1-16 of the 2026-09-08
# walk each list a different parameter set, one per loaded model).
_DELAY_MODE = "/dlymode"


def governs(selector: str, address: str) -> bool:
    """Whether `selector` (an absolute or strip-relative address whose
    class is SELECTOR) governs the VALUE at `address` -- see the table
    above. Both addresses must be spelled the same way."""
    if selector == address or write_order(selector) != SELECTOR:
        return False
    if write_order(address) != VALUE:
        return False
    if selector.endswith(_DELAY_MODE):
        return address == selector[: -len(_DELAY_MODE)] + "/dly"
    node, _, _leaf = selector.rpartition("/")
    prefix = node + "/"
    return address.startswith(prefix) and "/" not in address[len(prefix):]


# The strip nodes whose leaves are ordered by class when undo restores
# them (see `atoo/undo.py`). Only these are reordered: an undo's
# other rows (a patch, a send's `/on`, release's mute bracket) keep the
# reverse-journal order their stage dependencies need.
_PROCESSING_NODE = re.compile(
    r"^/(?:(?:ch|aux|bus|main|mtx)/\d+/(?:flt|eq|peq|dyn|gate|gatesc|dynxo|dynsc|in/set|dly)"
    r"|fx/\d+)/[^/]+$")


def is_processing_address(address: str) -> bool:
    """Whether `address` is a leaf of a strip's processing -- one whose
    order among its neighbours is decided by `write_order`."""
    return bool(_PROCESSING_NODE.match(address))


def coerce_value(address: str, value) -> tuple[object, str | None]:
    """`(value, None)` in the type the desk takes at `address`, or
    `(None, why)` when it cannot be put in that type honestly."""
    spec = leaf_type(address)
    if spec is None:
        return None, "no confirmed type for this leaf"
    if spec.osc == "i":
        if isinstance(value, bool):
            return int(value), None
        if isinstance(value, (int, float)) and float(value).is_integer():
            return int(value), None
        return None, f"{value!r} is not an on/off or whole number"
    if spec.osc == "f":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"{value!r} is not a number"
        if not math.isfinite(float(value)):
            return None, f"{value!r} is not a finite number"
        return float(value), None
    # "s": a list choice.
    if isinstance(value, str):
        return value, None
    if isinstance(value, bool):
        return None, f"{value!r} is not a list choice"
    if isinstance(value, (int, float)):
        for token in spec.tokens:
            try:
                if float(token) == float(value):
                    return token, None
            except ValueError:
                continue
        number = float(value)
        return (str(int(number)) if number.is_integer() else str(number)), None
    return None, f"{value!r} is not a list choice"


def leaf_refusal(address: str, bank: str) -> str | None:
    """Why this address may NOT be written from a preset on a `bank` strip,
    or None if it may. The same three rules at build, verify and apply, so
    a hand-edited plan cannot talk its way past any of them."""
    leaf = address_leaf(address)
    if _classify(leaf) != "in_scope":
        return ("not on the preset allow-list -- a preset writes processing only, never "
                "sends, main routing, fader, mute, input patch or tags")
    spec = LEAF_TYPES.get(leaf)
    if spec is None:
        return "no confirmed type for this leaf, so there is no honest way to write it"
    if bank not in spec.banks:
        return f"a {bank} strip has no {leaf.split('.')[0]} node"
    return None


# A list choice the strip's bank does not offer. A `.chn`
# is a CHANNEL's file, and some of a channel's list choices are not on an
# aux strip's list at all: every preset in the starter library carries
# `dynsc.tap: "IN"`, a channel's sidechain tap, and an aux's tap is one of
# BUS, DYN, PFL, AFL, EQ, INS2 (the parameter map, through
# `initialized/leaf_types.json`). Written to an aux, `IN` does not take: the
# first full apply on the Compact (2026-10-02) wrote it to aux 2 HOST and
# read back BUS. That is a setting the desk cannot hold, not a preference,
# so build does not carry it as it stands:
#
# * where the aux has the same point in the signal under another name, it
#   takes that, said at INFO (`BANK_EQUIVALENTS`): a channel's `IN` (the
#   strip's input, before any processing) is an aux's `BUS` (the same
#   point, and the value each bank's initialized capture holds), and a
#   channel's `FILT` (after the low/high-cut filter) is also the aux's
#   input, because an aux has no filter;
# * otherwise the value is left out, with every value it governs if it is
#   a selector (`governs`), said at INFO: the strip keeps what it holds.
#
# apply and verify refuse a value the bank does not offer (a plan built
# before this, or edited by hand), with a WARNING naming the leaf, rather
# than writing it to read back a mismatch.
BANK_EQUIVALENTS: dict[tuple[str, str], dict[str, str]] = {
    ("aux", "dynsc/tap"): {"IN": "BUS", "FILT": "BUS"},
}

#: List leaves whose choices change with the strip's model (the parameter
#: map's `variant_templates`): the type table's tokens are one model's, so
#: they cannot say what another model offers, and the value is not checked.
_MODEL_VARIANT_LISTS = frozenset({"dyn/ratio"})


def bank_choices(address: str, bank: str) -> tuple[str, ...] | None:
    """The list choices a `bank` strip offers at `address` (strip-relative),
    from the parameter map -- or None when the leaf is not a list, or its
    list depends on the strip's model."""
    from atoo.initialize import leaf_types

    if address in _MODEL_VARIANT_LISTS:
        return None
    spec = leaf_types().get(f"/{bank}/{{n}}/{address}")
    if spec is None or spec.get("osc") != "s" or not spec.get("tokens"):
        return None
    return tuple(spec["tokens"])


def _choices_text(choices: tuple[str, ...]) -> str:
    return ", ".join(choices)


def _a(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def value_refusal(address: str, bank: str, value) -> str | None:
    """Why a `bank` strip cannot hold `value` at `address`, or None if it
    can -- a list choice its bank does not offer."""
    choices = bank_choices(address, bank)
    if choices is None or not isinstance(value, str) or value in choices:
        return None
    why = (f"{_a(bank)} {bank} strip's {address} has no {value!r} "
           f"(it offers {_choices_text(choices)})")
    equivalent = BANK_EQUIVALENTS.get((bank, address), {}).get(value)
    if equivalent is not None:
        why += (f"; rebuild, or run `atoo presets --expand` on the plan, to carry "
                f"{equivalent!r}, the {bank}'s same point")
    return why


def fit_to_bank(address: str, bank: str, value) -> tuple[object, str | None, str | None]:
    """`(value, mapped_from, refusal)` for a preset value going onto a
    `bank` strip: the value unchanged; the bank's equivalent and the value
    it replaces; or a refusal saying why it is left out."""
    if value_refusal(address, bank, value) is None:
        return value, None, None
    equivalent = BANK_EQUIVALENTS.get((bank, address), {}).get(value)
    if equivalent is not None:
        return equivalent, value, None
    choices = bank_choices(address, bank) or ()
    return None, None, (f"{address} {value!r} ({_a(bank)} {bank} strip offers "
                        f"{_choices_text(choices)})")


def file_sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_label(channel: dict) -> str:
    return f"{channel.get('bank', 'ch')} {channel.get('channel', '?')} ({channel.get('name')!r})"


def expand_channel(channel: dict, library) -> list[Diagnostic]:
    """Resolve this channel's named preset into `processing.preset_values`,
    in place, and return what was decided.

    Always recomputed rather than trusted: a channel naming no preset, or
    one the library cannot resolve, ends up with NO `preset_values`, so a
    generator that emitted the key cannot put values in a plan the library
    never supplied.
    """
    from atoo import apply  # the plan's own processing addresses

    processing = channel.get("processing")
    if not isinstance(processing, dict):
        return []
    processing.pop(PRESET_VALUES_KEY, None)
    name = processing.get("preset")
    if not name or library is None:
        return []
    try:
        preset = library.get(name)
    except PresetError:
        return []   # verify says preset.unknown / preset.unreadable-library

    bank = channel.get("bank", "ch")
    # Keyed by name, as every other check is: a number alone does not
    # say whether it is ch 2 or aux 2.
    where = f"channels[{channel.get('name') or (channel.get('bank', 'ch') + ' ' + str(channel.get('channel', '?')))}]"
    label = _strip_label(channel)
    findings: list[Diagnostic] = []
    for warning in preset.warnings:
        findings.append(Diagnostic(
            severity=Severity.WARNING, code="preset.leaf-dropped", where=where,
            message=f"{label}: preset {preset.name!r} ({preset.source_path.name}): {warning}",
            source="build"))

    explicit = apply.explicit_processing_addresses(channel)
    leaves: dict[str, object] = {}
    overridden: dict[str, object] = {}
    not_on_strip: list[str] = []
    mapped: list[str] = []
    off_list: list[str] = []
    off_list_selectors: list[str] = []
    for leaf, raw in preset.parameters.items():
        address = leaf_address(leaf)
        refusal = leaf_refusal(address, bank)
        if refusal is not None:
            if leaf in LEAF_TYPES:
                not_on_strip.append(address)
            else:
                findings.append(Diagnostic(
                    severity=Severity.WARNING, code="preset.leaf-untyped", where=where,
                    message=f"{label}: preset {preset.name!r} carries {leaf}={raw!r}, which is "
                            f"not carried into the plan: {refusal}",
                    source="build"))
            continue
        value, why = coerce_value(address, raw)
        if why is not None:
            findings.append(Diagnostic(
                severity=Severity.WARNING, code="preset.leaf-untyped", where=where,
                message=f"{label}: preset {preset.name!r} carries {leaf}={raw!r}, which is not "
                        f"carried into the plan: {why}",
                source="build"))
            continue
        fitted, mapped_from, refusal = fit_to_bank(address, bank, value)
        if refusal is not None:
            off_list.append(refusal)
            off_list_selectors.append(address)
            continue
        if mapped_from is not None:
            mapped.append(f"{address} {mapped_from!r} -> {fitted!r}")
            value = fitted
        if address in explicit:
            overridden[address] = value
        else:
            leaves[address] = value

    # A selector left out takes the values it governs with it: they were
    # set for the preset's choice, and would land under the strip's own.
    for selector in off_list_selectors:
        for address in [a for a in leaves if governs(selector, a)]:
            del leaves[address]
            off_list.append(f"{address} (set for {selector}, which is left out)")

    processing[PRESET_VALUES_KEY] = {
        "preset": preset.name,
        "file": preset.source_path.name,
        "library": str(library.directory),
        "sha256": file_sha256(preset.source_path),
        "leaves": {a: leaves[a] for a in ordered(leaves)},
        "overridden": {a: overridden[a] for a in ordered(overridden)},
    }

    # Plan wins, said out loud: which addresses, what the preset wanted,
    # and what the plan writes instead. An address where the plan and the
    # preset agree is not an override -- nothing was decided there -- so it
    # is not counted ("flt/lc 1 (both agree)" was on 22 of
    # sixpiece's 22 notes). It is still in `preset_values.overridden`.
    changed = [a for a in ordered(overridden) if overridden[a] != explicit[a]]
    if changed:
        findings.append(Diagnostic(
            severity=Severity.INFO, code="preset.overridden", where=where,
            message=f"{label}: the plan's own processing wins at {len(changed)} address(es) "
                    f"the preset {preset.name!r} also sets -- "
                    + "; ".join(_override_text(a, overridden[a], explicit[a])
                                for a in changed),
            source="build"))
    if not_on_strip:
        sections = sorted({a.split("/")[0] for a in not_on_strip})
        findings.append(Diagnostic(
            severity=Severity.INFO, code="preset.leaf-not-on-strip", where=where,
            message=f"{label}: {len(not_on_strip)} of the preset {preset.name!r} values are for "
                    f"nodes a {bank} strip does not have ({', '.join(sections)}) and are not "
                    "carried into the plan",
            source="build"))
    if mapped or off_list:
        parts = []
        if mapped:
            parts.append(f"carried as the {bank}'s equivalent: " + "; ".join(mapped))
        if off_list:
            parts.append("left out, so the strip keeps what it holds: " + "; ".join(off_list))
        findings.append(Diagnostic(
            severity=Severity.INFO, code="preset.value-not-on-strip", where=where,
            message=f"{label}: the preset {preset.name!r} makes a choice {_a(bank)} {bank} "
                    "strip does not offer -- " + ". ".join(parts),
            source="build"))
    return findings


def _override_text(address: str, preset_value, plan_value) -> str:
    if preset_value == plan_value:
        return f"{address} {plan_value!r} (both agree)"
    return f"{address} preset {preset_value!r} -> plan {plan_value!r}"


def expand_plan(plan: dict, library) -> list[Diagnostic]:
    """Expand every channel's named preset (see `expand_channel`), plus one
    INFO for the plan saying what it now carries, then every bus's
    (`bus_presets.expand_busses`). Mutates `plan`."""
    findings: list[Diagnostic] = []
    expanded = []
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        findings.extend(expand_channel(channel, library))
        values = (channel.get("processing") or {}).get(PRESET_VALUES_KEY)
        if values:
            expanded.append(f"{channel.get('bank', 'ch')} {channel.get('channel')} "
                            f"{values['preset']} ({len(values['leaves'])})")
    if expanded:
        findings.insert(0, Diagnostic(
            severity=Severity.INFO, code="preset.expanded", where="plan",
            message=f"{len(expanded)} channel(s) carry a preset's values, resolved from "
                    f"{library.directory} and written at the processing stage: "
                    + ", ".join(expanded),
            source="build"))
    # A bus's preset, and the effect it inserts.
    from atoo import bus_presets
    findings.extend(bus_presets.expand_busses(plan, library))
    return findings


def preset_values(channel: dict) -> dict | None:
    values = (channel.get("processing") or {}).get(PRESET_VALUES_KEY)
    return values if isinstance(values, dict) else None


def expansion_matches_name(channel: dict) -> bool:
    """Whether the values this channel carries came from the preset it
    names (a hand edit can change one without the other)."""
    values = preset_values(channel)
    name = (channel.get("processing") or {}).get("preset")
    if values is None or not name:
        return False
    return normalize_preset_name(str(values.get("preset", ""))) == normalize_preset_name(name)
