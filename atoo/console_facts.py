"""What a WING Compact can actually be set to.

This is the whole point of the generator+verifier experiment:
a conventions schema is unbounded because English is unbounded, but *this*
table is bounded -- it is finished the day it matches the console. Nothing
here is inferred from a conventions file or from what any model said; every
number below was read out of the real hardware walk of 2026-09-08
(the raw walk of a WING Compact), with the originating
`.../data` string quoted beside it.

Extracted 2026-09-11 by enumerating that walk. Re-derive, don't hand-edit:

    python -c "import json,re,collections; ..."   # see this file's git log
"""

from __future__ import annotations

import re

CONSOLE_MODEL = "wing-compact"

# --------------------------------------------------------------------------
# Which console model, and what its front panel actually has
# --------------------------------------------------------------------------
#
# **A walk of the address tree is not a measurement of the hardware.** This
# is the distinction the rest of this file predates, and it matters more
# than it sounds.
#
# Every table below `CAPACITY` is derived from the 2026-09-08 walk, which
# enumerates what the *firmware* can address. All three WING models run the
# same firmware on the same mainboard, so the tree is identical on all
# three -- and it therefore says nothing about which sockets physically
# exist. The proof is in our own walk: it reports a complete
# `/io/in/AUX/1..8` and `/io/out/AUX/1..8` for a Compact, a console
# that has no local aux jacks at all.
#
# So `INPUT_SOCKETS`/`OUTPUT_SOCKETS` are an *address space*, and using them
# as a physical bound silently passes plans that cannot be patched. The
# panel counts below come from the one source that does distinguish the
# models -- Behringer's `WING_Remote-Protocols-3.1-03.pdf` pp. 11-12,
# which enumerates the three side by side -- cross-checked against p.4's
# preamp count ("8 (full size console) or 24 (Rack and Compact consoles)
# original MIDAS PRO microphone preamps").
#
# **An unknown console-model is a hard stop**: we have
# no way of knowing what its capabilities are and any plan would be
# meaningless. Hence `panel_for()` raises rather than falling back, and
# every caller that needs a socket bound has to say which console it means.
CONSOLE_MODELS = {
    "wing-full": {
        "label": "WING (full-size console)",
        # p.11: "8 local Inputs, 8 Aux inputs, 8 aux outputs, 8 local outputs"
        "inputs": {"LCL": 8, "AUX": 8},
        "outputs": {"LCL": 8, "AUX": 8},
        "gpio": 4,
    },
    "wing-rack": {
        "label": "WING Rack (19\", 4U)",
        # p.11: "24 Local Inputs (8 on the WING)" / "No local Aux IO
        # (8 IN, 8 OUT on the WING)"
        "inputs": {"LCL": 24, "AUX": 0},
        "outputs": {"LCL": 8, "AUX": 0},
        "gpio": 4,
    },
    "wing-compact": {
        "label": "WING Compact",
        # p.12: same two lines as the Rack, plus "2 GPIO (1 TRS) on the rear
        # of the console (4 GPIO / 2 TRS on the WING)".
        "inputs": {"LCL": 24, "AUX": 0},
        "outputs": {"LCL": 8, "AUX": 0},
        "gpio": 2,
    },
}

# Groups whose socket count depends on the model. Everything else (AES50
# A/B/C, StageCONNECT, AES/EBU, the two expansion bays, USB) hangs off the
# mainboard, which pp. 11-12 describe as shared across all three models
# ("Same Mainboard as on WING"), so none of those varies by model.
#
# Confirming that for the bays specifically: all three
# models -- full-size, Compact and Rack -- have the same two, and they work
# **at the same time**, not one or the other. One rear-panel expansion slot
# (`CRD`), shipping with the WING-LIVE 64-channel dual-SD recorder and
# swappable for WING-DANTE/MADI; one internal AoIP module slot (`MOD`) on
# the motherboard, for an optional Dante or Waves SoundGrid module, another
# 64x64. The PDF's p.256 "an extension card... **or** an internal module"
# reads as exclusive and is not. "The expansion bay", unqualified, means
# the rear slot.
#
# That is **not** the same as saying the address-space count is the panel
# count for all of them, and this comment said so until 2026-09-21. `CRD`
# (the expansion card bay) and `MOD` (the AoIP module bay) are
# sockets that exist only when something is *in* the bay, which is a fact
# about the rig rather than the model: `/cards.$type` and
# `/$syscfg.opt_mod` both have a `NONE`, and the firmware answers
# `/io/in/{CRD,MOD}/1..64` either way. Same lesson as this whole section,
# a layer down -- but the desk states this one itself, so it belongs at
# apply time rather than in a table here. That is where it now is
# (done 2026-09-22): `EXPANSION_BAY_ADDRESSES`/`bay_is_empty`
# below, read by `apply.read_fitted_bays` in pre-flight.
MODEL_VARIANT_GROUPS = frozenset({"LCL", "AUX"})


def panel_for(console_model: str | None) -> dict:
    """The physical panel of `console_model`, or raise.

    Deliberately has no default and no permissive fallback: an unknown model
    is a hard stop, because the socket bound is the only thing
    standing between a plan and a patch to a jack that isn't there.
    """
    if not console_model:
        raise UnknownConsoleModel(None)
    if console_model not in CONSOLE_MODELS:
        raise UnknownConsoleModel(console_model)
    return CONSOLE_MODELS[console_model]


class UnknownConsoleModel(ValueError):
    """Raised for a missing or unrecognised console model.

    Carries `model` so a caller can render its own guidance -- the CLI says
    which flag to pass, `verify_plan` turns it into a diagnostic.
    """

    def __init__(self, model: str | None) -> None:
        self.model = model
        known = ", ".join(sorted(CONSOLE_MODELS))
        if model is None:
            super().__init__(
                "no console model stated -- Atoo cannot check a plan without "
                f"knowing which console it is for. Known models: {known}")
        else:
            super().__init__(
                f"unknown console model {model!r} -- Atoo has no confirmed "
                f"capacities for it. Known models: {known}")


# What the desk calls itself, where that is not what we call it
#
# Measured 2026-09-23 on a real full-size WING -- the first console other
# than the reference Compact this project has ever been connected to:
#
#     WING,192.0.2.148,WING-CCC,wing-fullsize,SERIAL00000002,
#     3.1-0-g9f314617:release
#
# (the A17 capture of 2026-09-23, field
# `identity`.) The desk's own token is `wing-fullsize`; our key -- and the
# `--console-model` choice a user types, and the value written into a
# plan's `meta.console_model` -- is `wing-full`. Both have to resolve to
# the same model, so the console's spelling is translated here rather than
# by renaming the key out from under the CLI and every plan on disk.
#
# **This table holds measured tokens only.** It is deliberately not a
# normalising rule (strip a "size" suffix, fold hyphens, prefix-match),
# because such a rule would silently invent an answer for a token nobody
# has ever read off a desk -- and the answer it invents decides the socket
# bound that stands between a plan and a patch to a jack that isn't there.
# That is the same line `panel_for` and `model_from_identity` already
# draw, one field earlier.
#
# The cost of that choice is that it buys nothing for the Rack. **Nobody
# has seen a WING Rack's identity string.** If a Rack answers `wing-rack`
# it already works; if it answers `wing-racksize`, or anything else, it
# will land here as None until one line is added below. What settles it is
# one capture: `atoo ping` against a Rack (or A17's survey), and the
# `<model>` field of its `/?` reply.
#
# **What `apply` does with that None** -- this comment used to say it
# refuses, and it never did: the model cross-check simply did not fire,
# and a desk calling itself something unmeasured was written to without a
# word (found by the agent, 2026-09-24). It now proceeds and SAYS so,
# at WARNING, before writing: the token the desk sent, that sockets were
# checked against the plan's own model only, and that every write is
# still read back and proved (`apply.check_desk_model`). Proceeding rather
# than refusing follows the principle that a judgement call is not an
# impossible patch -- the WING family shares one
# firmware and one mainboard, the plan's own model has already been
# verified, and a wrong guess at the model shows up in the readback rather
# than as a silent patch. The token goes into the apply journal's `desk`
# block as `model_token` (`identity_model_token`), so the first real run
# against an unmeasured desk hands us the exact string to add below.
IDENTITY_MODEL_ALIASES = {
    # measured: the A17 capture of 2026-09-23
    "wing-fullsize": "wing-full",
}


def model_from_identity(identity_args) -> str | None:
    """The console model out of a `/?` reply, or None if it isn't in there.

    WING answers `/?` with `WING,<ip>,<name>,<model>,<serial>,<firmware>`
    (`console.py:identity`), so the desk states its own model -- which beats
    asking the engineer to, and is the reason `apply`/`audit`/`watch` need
    no `--console-model` while `build`/`verify` do. Only recognised models
    are returned; an unfamiliar string is None rather than a guess.

    A desk does not necessarily spell its model the way we key it -- a
    full-size WING says `wing-fullsize` where `CONSOLE_MODELS` says
    `wing-full` -- so each field is put through
    `IDENTITY_MODEL_ALIASES` first. That table is measured tokens only,
    never a pattern: an unrecognised spelling is still None.

    Returns a key of `CONSOLE_MODELS`, so callers never see a console's
    own spelling and nothing downstream needs to know this table exists.

    Accepts the reply's args either already split or as the single
    comma-joined string WING actually sends.
    """
    if not identity_args:
        return None
    fields: list[str] = []
    for arg in identity_args:
        fields.extend(str(arg).split(","))
    for field_value in fields:
        candidate = field_value.strip()
        candidate = IDENTITY_MODEL_ALIASES.get(candidate, candidate)
        if candidate in CONSOLE_MODELS:
            return candidate
    return None


def identity_model_token(identity_args) -> str | None:
    """The `<model>` field of a `/?` reply exactly as the desk spelled it,
    or None when the reply has no such field (or it is blank).

    Positional -- `WING,<ip>,<name>,<model>,<serial>,<firmware>`, field 3
    -- because that is the reply's shape, and because the point is to
    report what the desk SAID when `model_from_identity` could not resolve
    it: an unmeasured spelling is the string somebody needs to read off a
    journal and add to `IDENTITY_MODEL_ALIASES`. Never translated, never
    normalised.
    """
    fields: list[str] = []
    for arg in identity_args or ():
        fields.extend(str(arg).split(","))
    if len(fields) < 4:
        return None
    return fields[3].strip() or None


def input_socket_limit(group: str, console_model: str | None) -> int:
    """Highest input socket that physically exists in `group`, for this model.

    Falls through to the address-space count for every group the models
    share; only `MODEL_VARIANT_GROUPS` differ panel to panel.
    """
    panel = panel_for(console_model)
    if group in panel["inputs"]:
        return panel["inputs"][group]
    return INPUT_SOCKETS.get(group, 0)


def output_socket_limit(group: str, console_model: str | None) -> int:
    """Same, output side."""
    panel = panel_for(console_model)
    if group in panel["outputs"]:
        return panel["outputs"][group]
    return OUTPUT_SOCKETS.get(group, 0)


# --------------------------------------------------------------------------
# What a console patches before anybody tells it anything (2026-09-23)
# --------------------------------------------------------------------------
#
# The audit's "in use" test (`audit.is_in_use`, FR-4.7) has to tell a patch
# somebody made from a patch the desk came with, so it needs to know what
# the desk came with -- per model, because the models do not ship alike.
#
# **Measured, on two models.** Every entry below was read out of a
# factory-initialized capture taken from the desk itself
# (`ae_data.{ch,aux,bus}.{n}.in.conn`). Nothing here is inferred from the
# protocol PDF and nothing is a guess at what a console "probably" does.
#
# `wing-compact`, from `tests/fixtures/console-runs/Initialized-Compact.snap`:
#
#   ch  1-24   LCL 1-24, each channel from its own number   (24 patched)
#   ch  25-40  OFF                                           (16)
#   aux 1      USB 1     (the USB stick player)
#   aux 2      PLAY 1    (the media player)
#   aux 3-8    OFF                                           (6)
#   bus 1-16   no input patch at all -- a bus has no `in.conn` node
#
# `wing-full`, from `tests/fixtures/Initialized-Full.snap` (a factory-initialized
# full-size WING, committed 2026-09-23 in c402c2f):
#
#   ch  1-8    LCL 1-8, each channel from its own number    (8 patched)
#   ch  9-40   OFF                                           (32)
#   aux 1      USB 1
#   aux 2      PLAY 1
#   aux 3-8    OFF                                           (6)
#   bus 1-16   no input patch at all -- no `in.conn` node, as on the Compact
#
# So the local-input run stops where each panel's local inputs stop (8 on
# a Full, 24 on a Compact -- `CONSOLE_MODELS`), and the two media auxes are
# the same on both. The capture cannot say which model wrote it
# (`creator_model` is `"wing"` on every WING); the file name and the
# 8-channel LCL run, which matches only the Full's panel, are what say so.
#
# **`wing-rack` is NOT measured.** We have never had one in front of us.
# Its panel has 24 local inputs like the Compact, which makes the Compact's
# row a plausible guess -- and a plausible guess is the very mistake
# this table exists to avoid, writing down a number nobody read off hardware.
#
# So an unmeasured model (and an unknown one, and a state with no model at
# all) falls back to `FACTORY_CHANNEL_PATCH_IDENTITY`: channel n from
# LCL n, and nothing else excluded. That direction is the safe one **for a
# reading**, and the choice is between two ways of being wrong:
#
#   * exclude nothing, and every strip on an untouched desk of that model
#     reads as in use again -- the 97-findings noise that was removed;
#   * exclude everything we imagine a factory might patch, and a REAL
#     patch that happens to match our imagination disappears out of the
#     report. A finding that never prints is the failure this project
#     cannot see.
#
# The identity is the one shape we are confident of across the family --
# it is what makes channel 1 the first XLR on every WING -- and it is
# exactly what the audit already did for every model before this table
# existed. Falling back to it costs the two media auxes on an unmeasured
# board (visible, at INFO) and hides nothing.
#
# **The fallback is for reading only. Never write it.** Returning a
# dropped channel to free restores its factory patch (decided
# 2026-09-24), and "channel 19 back to LCL 19" on a desk with 8 local
# inputs is a patch to a socket that does not exist. A write asks
# `measured_factory_input_patch()`, which answers only from this table and
# only with a socket the model's panel actually has.
#
# To add a model: capture an initialized board of it and add its measured
# banks here. The fallback is not a placeholder to be filled in with
# plausible values.
FACTORY_CHANNEL_PATCH_IDENTITY = "LCL"

# `bus: {}` is not padding: it says the bus bank was looked at and had
# nothing, which is a different statement from leaving it out.
FACTORY_INPUT_PATCHES: dict[str, dict[str, dict[int, tuple[str, int]]]] = {
    "wing-compact": {
        "ch": {n: (FACTORY_CHANNEL_PATCH_IDENTITY, n) for n in range(1, 25)},
        "aux": {1: ("USB", 1), 2: ("PLAY", 1)},
        "bus": {},
    },
    "wing-full": {
        "ch": {n: (FACTORY_CHANNEL_PATCH_IDENTITY, n) for n in range(1, 9)},
        "aux": {1: ("USB", 1), 2: ("PLAY", 1)},
        "bus": {},
    },
}

MEASURED_FACTORY_PATCH_MODELS = tuple(sorted(FACTORY_INPUT_PATCHES))


# --------------------------------------------------------------------------
# What a strip and an input socket LOOK like before anybody customizes
# them -- the values a released strip is returned to.
# --------------------------------------------------------------------------
#
# Measured, not assumed, off
# the A13 snapshot of 2026-09-22 (board with Podium): a
# Compact carrying the touring-band show, so every strip the show did not
# build and every socket it did not name is a factory reading. Counted
# across the whole board rather than read off one strip:
#
#     /ch/*   untouched (21 of them):  name='',  col=1, icon=0
#     /io/in/A/*   (28 untouched):     name='',  col=1, icon=0
#     /io/in/B/*   (48):               name='',  col=1, icon=0
#     /io/in/LCL/* (23 untouched):     name='',  col=1, icon=1
#     /io/in/AUX/* (8):                name='',  col=1, icon=2
#     /io/in/USB/*, /io/in/PLAY/*:     col=1, icon=0 where unnamed
#
# `col` is `int [1 .. 18]` in the parameter map -- there is no 0, so
# "no colour" on a WING is colour 1, and writing 0 would be a value out
# of the console's range. `icon` is `int [0 .. 999]`, and 0 is the
# ordinary "none" -- except on LCL and AUX, where the desk ships its own
# little socket glyph. `factory_source_icon` carries that, because
# returning an LCL socket to icon 0 would leave it one glyph away from
# every other untouched LCL socket on the board.
FACTORY_STRIP_NAME = ""
FACTORY_STRIP_COLOUR_INDEX = 1
FACTORY_STRIP_ICON = 0
# The fader of an untouched channel: -144 (-inf) on all 40 strips of both
# `tests/fixtures/console-runs/Initialized-Compact.snap` and
# `tests/fixtures/Initialized-Full.snap`. A released strip is pulled back to it
# : once release restores the factory patch, a strip
# left unmuted at the plan's level would pass a stray source on its
# factory jack straight to Main 1.
FACTORY_STRIP_FADER_DB = -144.0

FACTORY_SOURCE_NAME = ""
FACTORY_SOURCE_COLOUR_INDEX = 1
#: Per input group, where the desk ships something other than icon 0.
FACTORY_SOURCE_ICONS: dict[str, int] = {"LCL": 1, "AUX": 2}


def factory_source_icon(group: str) -> int:
    """The icon an input socket of this group carries out of the box."""
    return FACTORY_SOURCE_ICONS.get((group or "").upper(), FACTORY_STRIP_ICON)


# The factory reading of the strip PROCESSING block, measured off
# the A8 initialized snapshot of 2026-09-23 --
# a Compact captured straight after an Initialize, so every one of its 40
# channel strips and 8 aux strips is an untouched reading. Counted across
# all 48 rather than read off one: `flt`, `in.set`, `eq` and `peq` are
# byte-identical on every strip in that capture, and `eq`/`in.set` read
# the same on both banks (an aux strip has no `flt` and no `peq` node at
# all -- see `apply._channel_write_targets` -- so those leaves simply
# never come up for one).
#
# This table exists rather than a list of
# "what a release clears": it is keyed by the leaf path under the strip
# base (`/ch/18` + `flt/lcf`), so `apply.release_write_targets` can take
# the addresses the plan's own BUILD produced and look up the reading to
# put back. A second hand-maintained list of processing leaves would stop
# covering the next one this project learns; deriving the clear from the
# build cannot. A leaf that is NOT in this table has no measured factory
# reading, and a release says so in a warning rather than guessing one.
#
# Note the frequencies are the desk's own steps, not round numbers
# (`lcf` is 100.2374573Hz, not 100) -- writing 100 would land on the same
# step, but writing what was measured is the claim this project makes
# everywhere else.
FACTORY_STRIP_PROCESSING: dict[str, object] = {
    # `flt` -- the high-pass, hi-cut and tilt. All three OFF, and their
    # frequencies/gain at the reading a strip nobody has touched gives.
    "flt/lc": 0,
    "flt/lcf": 100.2374573,
    "flt/lcs": "24",
    "flt/hc": 0,
    "flt/hcf": 10018.26074,
    "flt/hcs": "12",
    "flt/tf": 0,
    "flt/mdl": "TILT",
    "flt/tilt": 0.0,
    # `in/set` -- trim, balance, polarity. Present on BOTH banks.
    "in/set/trim": 0.0,
    "in/set/bal": 0.0,
    "in/set/inv": 0,
    # The main EQ: off, model STD, full wet, four bells and two shelves
    # flat at the desk's own default frequencies.
    "eq/on": 0,
    "eq/mdl": "STD",
    "eq/mix": 100.0,
    "eq/leq": "SHV",
    "eq/lf": 80.19641876,
    "eq/lg": 0.0,
    "eq/lq": 0.997970223,
    "eq/1f": 200.0,
    "eq/1g": 0.0,
    "eq/1q": 0.997970223,
    "eq/2f": 601.3883667,
    "eq/2g": 0.0,
    "eq/2q": 0.997970223,
    "eq/3f": 1499.78833,
    "eq/3g": 0.0,
    "eq/3q": 0.997970223,
    "eq/4f": 3990.524414,
    "eq/4g": 0.0,
    "eq/4q": 0.997970223,
    "eq/heq": "SHV",
    "eq/hf": 11999.27539,
    "eq/hg": 0.0,
    "eq/hq": 0.997970223,
    # The PreSend EQ -- channel strips only.
    "peq/on": 0,
    "peq/1f": 99.68543243,
    "peq/1g": 0.0,
    "peq/1q": 0.997970223,
    "peq/2f": 999.2504883,
    "peq/2g": 0.0,
    "peq/2q": 0.997970223,
    "peq/3f": 10016.52734,
    "peq/3g": 0.0,
    "peq/3q": 0.997970223,
    # Everything else a channel PRESET can write, so a
    # strip a preset was applied to returns to free completely rather than
    # keeping its compressor and gate (a release derives what to clear from
    # the build, and the build now writes preset leaves). Same capture, same
    # rule: every channel strip in A8 reads identically here.
    # Input delay -- both banks.
    "in/set/dlymode": "M",
    "in/set/dly": 0.100000001,
    "in/set/dlyon": 0,
    # The gate and its sidechain filter -- channel strips only.
    "gate/mdl": "GATE",
    "gate/thr": -40.0,
    "gate/range": 40.0,
    "gate/att": 10.0,
    "gate/hld": 10.0,
    "gate/rel": 200.474884,
    "gate/acc": 0.0,
    "gate/ratio": "1:3",
    "gate/gain": 0.0,
    "gate/mix": 100.0,
    "gate/on": 0,
    "gatesc/type": "OFF",
    "gatesc/f": 1002.37439,
    "gatesc/q": 1.995881796,
    "gatesc/src": "SELF",
    "gatesc/tap": "IN",
    # Dynamics: a channel strip's factory model is COMP. An aux strip's is
    # GATE, with different readings -- FACTORY_AUX_PROCESSING below.
    "dyn/mdl": "COMP",
    "dyn/mix": 100.0,
    "dyn/gain": 0.0,
    "dyn/thr": -10.0,
    # A list choice; the snapshot stores the COMP ratio as the number 3,
    # and the desk lists it as "3.0" (the parameter map).
    "dyn/ratio": "3.0",
    "dyn/knee": 3,
    "dyn/det": "RMS",
    "dyn/att": 50.0,
    "dyn/hld": 20.0,
    "dyn/rel": 150.3349457,
    "dyn/env": "LOG",
    "dyn/auto": 0,
    "dyn/on": 0,
    "dynxo/type": "OFF",
    "dynxo/depth": 6.0,
    "dynxo/f": 1002.37439,
    "dynxo/q": 0.400000006,
    "dynsc/type": "OFF",
    "dynsc/f": 1002.37439,
    "dynsc/q": 1.995881796,
    "dynsc/src": "SELF",
    "dynsc/tap": "IN",
}

#: An AUX strip's factory reading where it differs from a channel strip's
#: (same A8 capture, all 8 aux strips identical). Its dynamics come up as
#: the GATE model, so the COMP-only leaves have no reading at all there --
#: `NO_FACTORY_READING`, not the channel's value, because writing a COMP
#: knee onto a GATE-model strip is writing a leaf that is not there.
FACTORY_AUX_PROCESSING: dict[str, object] = {
    "dyn/mdl": "GATE",
    "dyn/thr": -36.0,
    "dyn/ratio": "1:3",
    "dyn/att": 10.0,
    "dyn/hld": 10.0,
    "dyn/rel": 200.474884,
    "dyn/acc": 0.0,
    "dyn/range": 40.0,
    "dynsc/tap": "BUS",
}

#: Sentinel for "this leaf has no measured factory reading", so a caller
#: can tell it apart from a leaf whose measured reading is `None`.
NO_FACTORY_READING = object()


_AUX_ABSENT = frozenset({"dyn/knee", "dyn/det", "dyn/env", "dyn/auto"})


def factory_strip_processing(leaf: str, bank: str = "ch") -> object:
    """The reading an untouched strip gives at this processing leaf
    (`"flt/lcf"`, `"eq/1g"`), or `NO_FACTORY_READING` if nothing measured
    one. `bank` matters for the dynamics only, whose factory model differs
    between a channel strip and an aux strip (FACTORY_AUX_PROCESSING).

    The caller must not substitute a default for the miss: an invented
    value written to a strip this tool has just advertised as free is the
    exact defect the release's success test rules out, one layer down.
    """
    if bank == "aux":
        if leaf in _AUX_ABSENT:
            return NO_FACTORY_READING
        if leaf in FACTORY_AUX_PROCESSING:
            return FACTORY_AUX_PROCESSING[leaf]
    return FACTORY_STRIP_PROCESSING.get(leaf, NO_FACTORY_READING)


def factory_input_patch(console_model: str | None, bank: str,
                        index: int) -> tuple[str, int] | None:
    """`(group, socket)` this object is patched from on a console straight
    out of the box, or None if the factory leaves it unpatched.

    Measured per model where we have measured one
    (`MEASURED_FACTORY_PATCH_MODELS`); for every other model, and for a
    state that never learned which console it came from, the answer is
    the channel-n-from-LCL-n identity and nothing else. See this section's
    comment for why that is the safe direction rather than the tidy one.
    """
    measured = FACTORY_INPUT_PATCHES.get(console_model or "")
    if measured is not None:
        return measured.get(bank, {}).get(index)
    if bank == "ch":
        return (FACTORY_CHANNEL_PATCH_IDENTITY, index)
    return None


#: Why `measured_factory_input_patch` has no socket to give, so a caller
#: writing OFF instead can say which of the three it was.
FACTORY_PATCH_UNMEASURED = "unmeasured"
FACTORY_PATCH_NONE = "none"
FACTORY_PATCH_NO_SUCH_SOCKET = "no-such-socket"


def measured_factory_input_patch(
        console_model: str | None, bank: str,
        index: int) -> tuple[tuple[str, int] | None, str | None]:
    """The factory patch **to write**: `((group, socket), None)`, or
    `(None, why)` where `why` is one of the `FACTORY_PATCH_*` reasons.

    The write-side counterpart of `factory_input_patch`, and deliberately
    not a wrapper over it. That function falls back to channel-n-from-
    LCL-n for any model nobody measured, which is right for deciding
    whether a reading looks untouched and wrong for a write: on a
    full-size WING's 8 local inputs, "channel 19 back to LCL 19" is a
    patch to a socket that does not exist -- a physical setting that
    cannot work. So this answers only from `FACTORY_INPUT_PATCHES`, and
    only with a socket `CONSOLE_MODELS` (via `input_socket_limit`) says
    the panel has.
    """
    measured = FACTORY_INPUT_PATCHES.get(console_model or "")
    if measured is None or console_model not in CONSOLE_MODELS:
        return None, FACTORY_PATCH_UNMEASURED
    patch = measured.get(bank, {}).get(index)
    if patch is None:
        return None, FACTORY_PATCH_NONE
    group, socket = patch
    if not 1 <= socket <= input_socket_limit(group, console_model):
        return None, FACTORY_PATCH_NO_SUCH_SOCKET
    return patch, None


def is_factory_input_patch(console_model: str | None, bank: str, index: int,
                           patch: tuple[str, int] | None) -> bool:
    """Is `patch` exactly what this object carries from the factory?

    Exact, deliberately: `/ch/3` on LCL 7 is a patch, and so is `/ch/3` on
    AES50-A 3. Only the reading the desk itself produces before anyone
    touches it is excluded.
    """
    if patch is None:
        return False
    return patch == factory_input_patch(console_model, bank, index)


# Strip/object counts. Confirmed against the walk's collection counts and
# against the requirements' Compact line.
CAPACITY = {
    "ch": 40,
    "aux": 8,
    "bus": 16,
    "main": 4,
    "mtx": 8,
    "dca": 16,
    "mgrp": 8,
}

# An input strip's direct routes to the Mains, `/{ch|aux}/{n}/main/{m}/on`
# for m in 1..CAPACITY["main"], as the desk ships them: Main 1 ON and every
# other Main OFF, with `lvl` 0 and `pre` off on all four. Counted across
# all 40 channel strips and all 8 aux strips of
# `tests/fixtures/console-runs/Initialized-Compact.snap`,
# the A8 initialized snapshot of 2026-09-23 and
# `tests/fixtures/Initialized-Full.snap` -- identical on every strip of all
# three, so neither the bank nor the model changes it.
#
# This is why `apply` writes every Main for every strip a plan builds, OFF
# included (2026-09-27): a plan that routes a channel to Main only through
# a mix bus -- `main_routes: []` -- left it on Main 1 as well, because the
# route the plan did not list was never in the write set. That put the
# festival's click track on the PA, and the drums and vocals on Main
# twice. A released strip goes back to exactly this reading.
#
# (Busses differ: see FACTORY_BUS_MAIN_ON_FROM below.)
FACTORY_STRIP_MAIN_INDEX = 1
FACTORY_STRIP_MAIN_LEVEL_DB = 0.0
FACTORY_STRIP_MAIN_PRE = 0


def main_indices() -> range:
    """Every Main a strip has a direct route to: 1..CAPACITY["main"]."""
    return range(1, CAPACITY["main"] + 1)


def factory_strip_main_on(index: int) -> int:
    """`/{ch|aux}/{n}/main/{index}/on` on a strip nobody has touched."""
    return 1 if index == FACTORY_STRIP_MAIN_INDEX else 0


# A bus's direct routes to the Mains, `/bus/{n}/main/{m}/on`, as the desk
# ships them: bus 1-8 on NO Main, bus 9-16 on Main 1 only (`lvl` 0, `pre`
# off throughout). Counted on the same three initialized captures as the
# strips above, identical on all three. So `apply` writes
# every Main for every bus a plan builds, OFF included: a monitor bus the
# plan puts on 9-16 would otherwise reach the PA as well.
FACTORY_BUS_MAIN_INDEX = 1
FACTORY_BUS_MAIN_ON_FROM = 9


def factory_bus_main_on(bus: int, index: int) -> int:
    """`/bus/{bus}/main/{index}/on` on a bus nobody has touched."""
    return 1 if bus >= FACTORY_BUS_MAIN_ON_FROM and index == FACTORY_BUS_MAIN_INDEX else 0

# Highest socket number the ADDRESS TREE carries per physical group, INPUT
# side, from `/io/in/{GROUP}/{n}` in the walk. **Not a panel inventory** --
# see `CONSOLE_MODELS` above and use `input_socket_limit()` for anything
# that decides whether a socket physically exists.
#
# Note LCL: 24 in, but only 8 out. This comment once called that "a
# real asymmetry on the Compact", which had it backwards: local outputs are
# 8 on all three models, and it is the *inputs* that vary (8 on a Full, 24
# on a Rack and Compact). Still exactly the kind of thing a
# plausible-looking generated plan gets wrong.
# How each group is written on an input list, for the prompt. Without
# this, "AES50-A 1" reads as group "AES" -- which exists (AES/EBU, 2
# sockets) and is wrong. A 14B model made exactly that substitution on
# every one of 19 channels; the verifier caught all 19 as
# patch.socket-out-of-range, but the model was never given what it needed
# to get it right.
GROUP_ALIASES = {
    "A": "AES50-A", "B": "AES50-B", "C": "AES50-C",
    "LCL": "Local / LCL", "AUX": 'Aux In (1/4")', "SC": "StageConnect",
    "CRD": "expansion card", "MOD": "AoIP module: Dante/WSG",
    "AES": "AES/EBU",
    "PLAY": "USB player", "REC": "recorder", "USB": "USB", "OSC": "oscillator",
    "USR": "user signal",
}

# CRD/MOD. **CRD is the expansion card,
# not the SD card; the SD card is used by WING LIVE** -- so this table and
# the console-model notes were both wrong, and wrong in *different* ways
# (those notes had CRD as the SD card and MOD as the expansion card; this file
# had MOD as an "expansion module"). CRD is now settled.
#
# What the *fitted* card is, the walk also answers (2026-09-20):
# `/cards.$type` is `list [NONE, WLIVE, WDANTE, WMADI, WDWSG]` -- one
# expansion slot, four possible cards -- so `CRD n` is a WING LIVE
# playback track only when a WING-LIVE card is the one in the slot, and a
# Dante/MADI stream otherwise. That is why "SD card" is refused as an
# input-list spelling rather than re-pointed here: the spelling
# names a card this group may not be carrying.
#
# **MOD is the AoIP module slot, and it is a different slot from CRD**
# (settled 2026-09-21 from the protocol PDF and our own walk, after
# being carried as "unconfirmed" rather than guessed at twice).
# `WING_Remote-Protocols-3.1-03.pdf` p.10: "64 channels of Audio over IP
# (**AoIP module optional**)"; p.256: "an extension card (W-DANTE) that
# replaces the standard SD card, **or an internal module (Dante or WSG)
# that can be directly installed in a dedicated module slot on the main
# motherboard**... a typical additional 64 INs and 64 OUTs". The walk
# corroborates all three ways: `/$syscfg.opt_mod` is
# `list [NONE, DANTE, WSG, ACOM]` ("Installed optional module", [RO]),
# `/cards.$type` is the *card* bay's own enum, and `/$globals.clksrc` is
# `list [INT, A, B, C, AES, CRD, MOD]` -- two bays, two clock sources.
# Both hold 64 sockets, which is why the two were mistakable for each
# other. `ACOM` is in the enum and named nowhere in the PDF's prose, so
# the label names only what the specification names.
#
# These tables are rendered straight into the generate prompt and are what
# `verify_plan` checks a patch against, so a confident wrong label here
# produces a plausible patch nobody catches -- which is exactly what the issue
# was filed about, and why this label waited for a source instead of a
# second guess.
#
# **Neither bay is necessarily occupied, and these counts do not know
# that**. `opt_mod: NONE` is the factory default and
# `/cards.$type` has a `NONE` too, yet the firmware answers
# `/io/in/MOD/1..64` on every console -- so a plan patching `MOD 1` into an
# empty bay verifies clean, applies clean, and the channel is silent. The
# counts here are an address space, the same distinction the model-variant table draws for the
# panel counts; unlike those, the desk states this one itself, on
# `/$syscfg/opt_mod` and `/cards/$type`, so a console we are connected to
# can be asked -- and is. `atoo apply` reads both in pre-flight and
# refuses a plan that needs an empty bay (FR-1.8b); offline,
# `verify_plan` raises `patch.expansion-bay-not-checked` to say it could
# not. Nothing has made these two numbers an inventory: they are still
# the address space, and the check is what closes the gap.
#
# The SD card is not an input group at all: it is the storage behind WING
# LIVE, the multichannel recorder/player, whose patching is its own
# unbuilt concern.
INPUT_SOCKETS = {
    "A": 48, "B": 48, "C": 48,     # AES50 A/B/C
    "LCL": 24,                      # local XLR
    "AUX": 8,                       # 1/4" jacks
    "SC": 32,                       # StageConnect
    "USB": 48,
    "CRD": 64,                      # expansion card
    "MOD": 64,                      # AoIP module: Dante/WSG
    "AES": 2,                       # AES/EBU
    "PLAY": 4,                      # USB-stick player
    "OSC": 2,                       # internal oscillator
    "USR": 56,                      # user signals/patches
}

# Same, OUTPUT side (`/io/out/{GROUP}/{n}`). REC (recorder tap) exists here
# and not on the input side; OSC/USR exist on the input side and not here.
OUTPUT_SOCKETS = {
    "A": 48, "B": 48, "C": 48,
    "LCL": 8,
    "AUX": 8,
    "SC": 32,
    "USB": 48,
    "CRD": 64,
    "MOD": 64,                      # 64 out as well as 64 in (PDF p.256)
    "AES": 2,
    "REC": 4,
}

# What can feed an output socket (`/io/out/{GROUP}/{n}/grp`, the walk's own
# `list` descriptor), and the range of its `/in` (`int [1 .. 64]`, for every
# group). A physical group's own count bounds `/in` further, as an input
# patch's: the source is that input socket.
OUTPUT_SOURCE_GROUPS = ("OFF", "LCL", "AUX", "A", "B", "C", "SC", "USB", "CRD", "MOD",
                        "PLAY", "AES", "USR", "OSC", "BUS", "MAIN", "MTX", "SEND", "MON")
OUTPUT_SOURCE_INDEX_MAX = 64

# Value domains, quoted from the walk's own `data` descriptors.
#
#   ch.{n}.fdr          fader [-oo .. 10.0 dB], 1024 steps
#   ch.{n}.main.{m}.lvl fader [-oo .. 10.0 dB], 1024 steps
#   ch.{n}.send.{s}.lvl fader [-oo .. 10.0 dB], 1024 steps
#   ch.{n}.flt.lcf      log [20.0 .. 2k00 Hz], 641 steps
#   ch.{n}.flt.hcf      log [50.0 .. 20k00 Hz], 833 steps
#   ch.{n}.flt.tilt     lin [-6.00 .. +6.00 dB], 49 steps
#   ch.{n}.in.set.trim  lin [-18.0 .. +18.0 dB], 361 steps
#   ch.{n}.in.set.bal   lin [-9.0 .. +9.0 dB], 181 steps
#   io.in.{g}.{n}.g     lin [-3.0 .. 45.5 dB], 98 steps
#   ch.{n}.name         string [16]
#   ch.{n}.send.{s}.mode  list [PRE, POST, GRP]
#
# -oo is -144.0 on the wire (wing-console-model.md).
MINUS_INF_DB = -144.0
FADER_DB_RANGE = (MINUS_INF_DB, 10.0)
# What a strip the plan builds is left at when the plan states nothing for
# it: unity, unmuted. `apply` writes exactly these for an unstated
# `fader.fader_db` / `fader.muted`, and the critic is shown them in the
# place of the null, so "unset" means the same thing to the desk, to the
# audit and to the reviewer.
FADER_DEFAULT_DB = 0.0
MUTED_DEFAULT = False
SEND_LEVEL_DB_RANGE = (MINUS_INF_DB, 10.0)
HPF_HZ_RANGE = (20.0, 2000.0)
# Hi-cut, tilt, trim, balance -- each confirmed against
# the Compact parameter map's own `ch.{n}.flt.hcf` /
# `.tilt` / `ch.{n}.in.set.trim` / `.bal` entries (quoted above), same
# source and method as HPF_HZ_RANGE.
HI_CUT_HZ_RANGE = (50.0, 20000.0)
TILT_DB_RANGE = (-6.0, 6.0)
TRIM_DB_RANGE = (-18.0, 18.0)
BALANCE_DB_RANGE = (-9.0, 9.0)
HEAD_AMP_GAIN_DB_RANGE = (-3.0, 45.5)

# The step of a preamp the desk can ask for (`/io/in/{grp}/{n}/g` takes any
# 0.5 dB value, -3 .. 45.5) against the step the hardware holds. A write
# lands on the nearest step the preamp has, and that step is 2.5 dB:
#
#   * a Behringer S16 on AES50 A, written and read back (Compact, fw 3.1):
#     -2.0 .. +45.5 in 2.5 dB steps, so 0 asked holds 0.5, 20 asked holds
#     20.5, 33.3 asked holds 33.0, 55 asked holds 45.5;
#   * the Compact's own local preamps (LCL 20): -2.5 .. +45 in 2.5 dB steps,
#     so 1.2 asked holds 0.0, 1.3 asked holds 2.5, 20.5 asked holds 20.0,
#     33.3 asked holds 32.5, 50 asked holds 45.0.
#
# The two grids sit on different offsets, but a 2.5 dB grid has exactly one
# step within half a step (1.25 dB) of any request that lies inside its
# range, so "the nearest step" is the same question as "within half a step"
# for either offset, and the offset need not be known. Every plan value the
# schema allows (`HEAD_AMP_GAIN_DB_RANGE`) is within half a step of a step
# of both. The Behringer design team gives the same 2.5 dB step for the
# X32-family boxes on AES50, which is why the three AES50 ports share it.
# A group not named here has no measured step.
HEAD_AMP_GAIN_STEP_DB = {"LCL": 2.5, "A": 2.5, "B": 2.5, "C": 2.5}

# --------------------------------------------------------------------------
# The parametric EQ
# --------------------------------------------------------------------------
#
# Quoted from the Compact parameter map, the real
# console capture, same source and method as the filter ranges above:
#
#   {ch|aux|bus|main|mtx}.{n}.eq.{1..N}f   log [20.0 .. 20k00 Hz], 961 steps
#   {ch|aux|bus|main|mtx}.{n}.eq.{1..N}g   lin [-15.0 .. +15.0 dB], 301 steps
#   {ch|aux|bus|main|mtx}.{n}.eq.{1..N}q   log [0.44 .. 10.00], 181 steps
#   ...and the same three, spelled l*/h*, for the low and high bands.
#
# The NUMBERS are uniform -- identical on every strip class, and (the point
# of phase 2a) unchanged by `eq.mdl`, which picks the filter's character,
# not its domain. That is what makes EQ schematizable today while the
# compressor is not: `dyn.thr/att/rel/ratio` shift their range with
# `dyn.mdl` across 32 models, so a structured compressor field has to
# answer "which model" first (phase 2, still deferred).
EQ_FREQ_HZ_RANGE = (20.0, 20000.0)
EQ_GAIN_DB_RANGE = (-15.0, 15.0)
EQ_Q_RANGE = (0.44, 10.0)
# `{strip}.{n}.eq.mix` -- lin [0 .. 125 %], 126 steps, confirmed on all
# five strip classes. The EQ's wet/dry blend: 100% is the EQ fully in
# circuit, 0% is a bypass that keeps the curve, and above 100 pushes past
# the stated curve. Included because the scope for this issue
# is that EQ be modelled in FULL for channels and busses (2026-09-21) -- it is the one leaf on the node, besides the transient solo
# state, that an engineer can set and a show can depend on.
EQ_MIX_PCT_RANGE = (0.0, 125.0)

# ...but the TOPOLOGY is not uniform, and this is the part that bites.
#
# The lesson, one node over: the address tree is identical across console
# MODELS, so it cannot tell you what a Compact's front panel has. Here the
# opposite asymmetry is real and the tree does state it -- a channel's EQ
# node stops at band 4, a bus's runs to band 6. A schema that modelled "six
# bands" everywhere would let a plan ask for `/ch/12/eq.5f`, a leaf that
# does not exist on a channel: the write would be accepted by nothing,
# report nothing, and the band would silently not be there.
#
#   ch    eq.1f..4q, eq.$solobd int [1 .. 6]   (low + 4 + high)
#   aux   eq.1f..4q, eq.$solobd int [1 .. 6]
#   bus   eq.1f..6q, eq.$solobd int [1 .. 8]   (low + 6 + high)
#   main  eq.1f..6q, eq.$solobd int [1 .. 8]
#   mtx   eq.1f..6q, eq.$solobd int [1 .. 8]
EQ_PARAMETRIC_BAND_COUNT = {
    "ch": 4,
    "aux": 4,
    "bus": 6,
    "main": 6,
    "mtx": 6,
}

# The low/high bands' own filter type (`eq.leq`/`eq.heq`) -- four tiers,
# not one, and a plan that asks a channel's low band for a 24dB
# Linkwitz-Riley is asking for a value the enum does not contain:
#
#   ch    list [PEQ, SHV]
#   aux   list [PEQ, SHV, CUT]
#   bus   list [PEQ, SHV, CUT, BW6, BW12, BS12, LR12, BW18, BW24, BS24, LR24, BW48, LR48]
#   main  (as bus)
#   mtx   (as bus)
_EQ_SHELF_TYPES_FULL = ("PEQ", "SHV", "CUT", "BW6", "BW12", "BS12", "LR12",
                        "BW18", "BW24", "BS24", "LR24", "BW48", "LR48")
EQ_SHELF_TYPES = {
    "ch": ("PEQ", "SHV"),
    "aux": ("PEQ", "SHV", "CUT"),
    "bus": _EQ_SHELF_TYPES_FULL,
    "main": _EQ_SHELF_TYPES_FULL,
    "mtx": _EQ_SHELF_TYPES_FULL,
}

# `eq.mdl` -- the filter's character. Three tiers again: a channel has
# MACH4 and no PIA, a bus/Main/Matrix has PIA and no MACH4, and an aux has
# neither.
EQ_MODELS = {
    "ch": ("STD", "SOUL", "E88", "E84", "F110", "PULSAR", "MACH4"),
    "aux": ("STD", "SOUL", "E88", "E84", "F110", "PULSAR"),
    "bus": ("STD", "SOUL", "E88", "E84", "F110", "PULSAR", "PIA"),
    "main": ("STD", "SOUL", "E88", "E84", "F110", "PULSAR", "PIA"),
    "mtx": ("STD", "SOUL", "E88", "E84", "F110", "PULSAR", "PIA"),
}

# Tilt is the fourth asymmetry, and the one that crosses nodes: a channel's
# tilt is `ch.{n}.flt.tilt` (already modelled as a channel's
# `processing.tilt_db`), a bus/Main/Matrix's is `{strip}.{n}.eq.tilt`, and
# an aux strip has NEITHER -- it has no `flt` node at all. Same numbers on
# both nodes: lin [-6.00 .. +6.00 dB], 49 steps.
#
# While confirming that: `flt` is confirmed absent on EVERY strip class
# except `ch` -- not just on aux, which is all apply.py's existing guard
# claimed.
EQ_TILT_STRIPS = ("bus", "main", "mtx")

# A channel has a SECOND EQ, and only a channel does. `{ch}.{n}.peq` is
# WING's "PreSend EQ" node -- three bells and an on switch, sitting at a
# different tap point in the strip (the protocol's Library Scopes appendix
# calls it "TAP EQ Settings in Bus Sends", grouped under the same EQ icon
# as the main `eq` node, which is why `presets.py` already allow-lists
# `peq.` and a `.chn` export can carry one):
#
#   ch    peq.1f/1g/1q .. 3f/3g/3q, peq.on
#   aux   none -- confirmed 0 templates, like `flt`
#   bus / main / mtx   none
#
# Ranges are the main EQ's, to the same bounds (`peq.1f` reads
# "log [20 .. 20k0 Hz], 960 steps" against `eq.1f`'s 961 -- the same
# domain at a different step count, which nothing here depends on). There
# are no shelf bands, so no `leq`/`heq`, no filter type, no `mdl`, no
# `mix` and no `tilt`: three bells, in or out.
PRESEND_EQ_BAND_COUNT = 3
PRESEND_EQ_STRIPS = ("ch",)


def presend_eq_band_ids(strip: str) -> tuple[str, ...]:
    """The PreSend EQ's bands, or () for a strip class that has no such
    node -- which is every strip class except `ch`."""
    if strip not in PRESEND_EQ_STRIPS:
        return ()
    return tuple(str(i) for i in range(1, PRESEND_EQ_BAND_COUNT + 1))


# The plan's own words for a strip, mapped to the console's node name: a
# channel carries `bank` ("ch"/"aux"), an output carries `kind`
# ("main"/"matrix"), and a bus is just a bus.
OUTPUT_KIND_TO_EQ_STRIP = {"main": "main", "matrix": "mtx"}


def eq_band_ids(strip: str) -> tuple[str, ...]:
    """Every band a strip class actually has, in console order.

    "low" and "high" are the shelf bands (`eq.lf`/`eq.hf`); the numbered
    ones are the parametric bands between them. A strip class not in
    EQ_PARAMETRIC_BAND_COUNT has no EQ node this project has confirmed,
    and gets no bands rather than a guess.
    """
    count = EQ_PARAMETRIC_BAND_COUNT.get(strip)
    if count is None:
        return ()
    return ("low", *(str(i) for i in range(1, count + 1)), "high")


NAME_MAX_CHARS = 16

# The console's own send modes. The plan schema currently models only two
# of these three; "GRP" has no plan representation today (noted rather than
# silently accepted, because schema loss must not go unnoticed).
SEND_MODES = ("PRE", "POST", "GRP")
PLAN_SEND_MODES = ("pre", "post")


# --------------------------------------------------------------------------
# Stereo pairing: a restriction of the hardware, not a convention
# --------------------------------------------------------------------------
#
# The last uncovered rule, and the one fact in this file that the
# walk cannot supply. `/ch/{n}.clink` is `int [0 .. 1]` and `/io/in/{g}/{n}/mode`
# is `[M, ST]`; neither says anything about which socket a pair may start
# on. `WING_Remote-Protocols-3.1-03.pdf` p.225 does, verbatim:
#
#   "All routing scenarios presented above have a restriction when it comes
#    to stereo pairs. The HW limitations of the desk impose stereo pairs to
#    always be in the form [odd-even] SOURCE numbers; i.e. you cannot route
#    a stereo signal to a single channel strip if your two mono sources are
#    connected to say LOCAL IN 2 and LOCAL IN 3, or if they are connected to
#    WLIVE PLAY 1 and WLIVE PLAY 33."
#
# Those two examples are the two ways to break it: wrong parity (2+3) and
# non-adjacency (1+33). Both are refused here.
#
# The desk's own escape hatch is USER SIGNALS / USER PATCHES, and it does
# NOT contradict the rule above -- it satisfies it one layer down. See
# `USER_SIGNAL_SLOTS` below.

STEREO_PAIR_RULE = """\
A stereo channel's two sockets must be CONSECUTIVE and must start on an
ODD socket: 1+2, 15+16, 23+24. Never 2+3, and never a gap such as 1+5.
The desk forms a stereo pair only from [odd, even] source numbers, so any
other pairing is refused before it reaches the console."""


def stereo_pair_problem(sockets: list) -> str | None:
    """Why `sockets` cannot be a stereo pair on a WING, or None if it can.

    Returns the reason rather than a bool so the caller's message can name
    which half of the rule was broken. Callers: `verify_plan._check_patch`
    (the finding) and `generate.console_section` (via `STEREO_PAIR_RULE`,
    the prompt the model reads) -- deliberately the same module, so the
    numbers the model is told cannot drift from the ones the verifier
    enforces.

    Says nothing about a list that is not exactly two sockets, or one
    holding something that is not an int: those are already
    `patch.stereo-socket-count` and `patch.socket-out-of-range`, and a
    second finding on the same fact only makes a report harder to read.
    """
    if not isinstance(sockets, list) or len(sockets) != 2:
        return None
    first, second = sockets
    if any(not isinstance(n, int) or isinstance(n, bool) for n in sockets):
        return None
    if second != first + 1:
        return (f"{first} and {second} are not consecutive (a pair is always "
                f"n and n+1)")
    if first % 2 == 0:
        return (f"the pair starts on {first}, an even socket (a pair always "
                f"starts on an odd one)")
    return None


# --------------------------------------------------------------------------
# USER SIGNALS and USER PATCHES: the `USR` group's 56 slots
# --------------------------------------------------------------------------
#
# The escape hatch STEREO_PAIR_RULE points at.
# `WING_Remote-Protocols-3.1-03.pdf` pp.225-227 describes two kinds of
# virtual source that "remove some of this restriction":
#
#   USER SIGNAL (24 entries) -- takes a CHANNEL as its source: an input
#     strip, an aux strip, a bus, a Main or a Matrix, at a chosen tap point.
#   USER PATCH (32 entries) -- takes a PHYSICAL SOCKET as its source
#     directly, "bypassing the need for using an intermediate channel
#     strip": LOCAL IN, AUX IN, AES50 A/B/C, ST CONNECT, USB AUDIO, add-on
#     card, internal module, USB PLAYER or AES/EBU IN.
#
# **The issue said these addresses had not been walked. They had.** They are
# in the 2026-09-08 raw walk of a Compact under
# `/io/in/USR/{n}/user` -- not under `/$ctl/...`, which is where the issue looked.
# The walk carries exactly 112 `USR` keys: 56 entries, each a
# `/io/in/USR/{n}` node plus one `/io/in/USR/{n}/user` child, and the child's
# descriptor differs by index in precisely the way the PDF's two variants
# predict:
#
#   /io/in/USR/1..24/user   grp  list [OFF, CH, AUX, BUS, MAIN, MTX]
#                           in   int [1 .. 40]
#                           tap  list [PRE, POST]
#                           lr   list [L+R, L, R]
#
#   /io/in/USR/25..56/user  grp  list [OFF, LCL, AUX, A, B, C, SC, USB,
#                                      CRD, MOD, PLAY, AES]
#                           in   int [1 .. 64]
#
# 24 + 32 = 56 = `INPUT_SOCKETS["USR"]`, and the split falls exactly on the
# boundary the PDF's counts give. So: **USR 1..24 are the USER SIGNALS and
# USR 25..56 are the USER PATCHES**, in the one `USR` input group a channel
# patches to. Three sources agree (the PDF's counts, the walk's two
# descriptor variants, the group's own size), which is why this is recorded
# as a fact rather than carried as a guess.
#
# **How a disjoint pair becomes legal.** Each USR slot holds exactly ONE
# source assignment -- one `grp`, one `in`; the walk shows no second one. So
# a STEREO user signal/patch is two CONSECUTIVE USR slots, odd first: slot n
# carries the left source, slot n+1 the right, both get `mode: ST`
# (`/io/in/USR/{n}.mode` is `list [M, ST, M/S]`, the same leaf every physical
# input group has) and the channel patches at the first of the two. That is
# exactly the shape `knowledge.md`'s "Every input is mono" describes for two
# physical sockets -- the USR layer is not an exception to it.
#
# Which is the point: the [odd-even] consecutive rule still applies, to the
# USR SLOT numbers. What moves is the disjointness, down one level, into
# each slot's own `grp`/`in`. The routing chip still only ever sees a legal
# consecutive odd-even pair. Nothing here contradicts `stereo_pair_problem`,
# and `verify_plan` runs that function over a `USR` pair unchanged.
#
# The PDF names the slots of a pair "25L/26R" in one sentence and "26L/26R"
# in the next, on p.227, for the same worked example. The address tree
# settles it: one `user` node per slot means 25L/26R, and 26L/26R is a typo.
#
# **Measured how far, and no further.** The address space, the two variants,
# their value domains and the 24/32 split are from our own walk of a
# Compact -- a real measurement of what the firmware addresses. That a pair
# of ST-mode USR slots with disjoint sources then *sounds* like the intended
# L/R at the strip is the PDF's claim, not ours: nobody has set one up at
# the desk and listened. Per the rule that a walk of the address tree is not a
# measurement of the hardware, that distinction is kept out loud -- it is
# why `verify_plan` checks these definitions but `apply` does not yet write
# them.
USER_SIGNAL_SLOTS = (1, 24)
USER_PATCH_SLOTS = (25, 56)

# `OFF` is in both `grp` enums and is deliberately NOT offered to a plan: a
# plan states what a thing IS, and "this slot is assigned to nothing" is
# what omitting the slot already says.
USER_SLOT_UNASSIGNED = "OFF"

# `/io/in/USR/1..24/user.grp` minus OFF. Note these are CHANNEL banks, not
# socket groups: `AUX` here is the 8 aux STRIPS, not the 1/4" aux jacks --
# the one spelling that means two different things depending on which half
# of the USR range the slot is in.
USER_SIGNAL_SOURCE_GROUPS = ("CH", "AUX", "BUS", "MAIN", "MTX")

# Which strip bank each of those names is, so the index can be bounded by
# what the console actually has (`CAPACITY`) rather than by the `in` leaf's
# 1..40, which is only the widest of the five.
USER_SIGNAL_SOURCE_BANKS = {
    "CH": "ch", "AUX": "aux", "BUS": "bus", "MAIN": "main", "MTX": "mtx",
}

# `/io/in/USR/25..56/user.grp` minus OFF -- physical input groups, and every
# one of them is a key of `INPUT_SOCKETS`. `OSC` and `USR` itself are not
# here: a user patch cannot take the oscillator or another user slot.
USER_PATCH_SOURCE_GROUPS = ("LCL", "AUX", "A", "B", "C", "SC", "USB",
                            "CRD", "MOD", "PLAY", "AES")

# The `in` leaf's own bound per variant. A real source is usually narrower
# (there are 16 busses, not 40), which is what `user_source_problem` checks
# against; these are the address space, in the sense the top of this file
# means it.
USER_SIGNAL_SOURCE_INDEX_MAX = 40
USER_PATCH_SOURCE_INDEX_MAX = 64

# `/io/in/USR/{n}/user.tap` and `.lr`, on the USER SIGNAL slots only. `tap`
# is where on the source strip the signal is taken; `lr` picks one leg of a
# stereo source, or both summed. Neither leaf exists on a USER PATCH slot --
# there is no strip to tap and nothing to pick a leg from.
USER_SIGNAL_TAPS = ("PRE", "POST")
USER_SIGNAL_LEGS = ("L+R", "L", "R")

# Every group name a plan may give a USR slot, either kind. The union, for a
# JSON Schema that cannot see which slot the entry is for -- the same bound
# `plan_schema._eq_schema` takes across strip classes, and for the same
# reason. `verify_plan` makes the exact per-slot call.
USER_SOURCE_GROUPS = tuple(sorted(set(USER_SIGNAL_SOURCE_GROUPS)
                                  | set(USER_PATCH_SOURCE_GROUPS)))
USER_SOURCE_INDEX_MAX = max(USER_SIGNAL_SOURCE_INDEX_MAX,
                            USER_PATCH_SOURCE_INDEX_MAX)

USER_SIGNAL = "user signal"
USER_PATCH = "user patch"


def user_slot_kind(slot: object) -> str | None:
    """`USER_SIGNAL`, `USER_PATCH`, or None for anything that is not a USR
    slot number. The two kinds are told apart by index alone -- there is no
    leaf that says which a slot is, only the shape of its `user` node."""
    if not isinstance(slot, int) or isinstance(slot, bool):
        return None
    if USER_SIGNAL_SLOTS[0] <= slot <= USER_SIGNAL_SLOTS[1]:
        return USER_SIGNAL
    if USER_PATCH_SLOTS[0] <= slot <= USER_PATCH_SLOTS[1]:
        return USER_PATCH
    return None


def user_source_groups(slot: object) -> tuple[str, ...]:
    """What `slot` may take as a source. Empty for a non-slot."""
    kind = user_slot_kind(slot)
    if kind == USER_SIGNAL:
        return USER_SIGNAL_SOURCE_GROUPS
    if kind == USER_PATCH:
        return USER_PATCH_SOURCE_GROUPS
    return ()


def user_source_index_limit(slot: object, group: object,
                            console_model: str | None = None) -> int | None:
    """Highest source index `slot` may name in `group`, or None if the pair
    is not one this console has at all.

    The bound is the real object count, not the `in` leaf's range: a USER
    SIGNAL on `BUS` reaches busses 1..16 because that is how many busses a
    WING has, even though the leaf accepts 1..40. A USER PATCH is bounded
    the same way an ordinary patch is -- by the panel when the model is
    known (`input_socket_limit`), by the address space when it is not --
    because it is addressing the very same jacks.
    """
    kind = user_slot_kind(slot)
    if kind == USER_SIGNAL:
        bank = USER_SIGNAL_SOURCE_BANKS.get(group)
        return None if bank is None else CAPACITY[bank]
    if kind == USER_PATCH:
        if group not in USER_PATCH_SOURCE_GROUPS:
            return None
        if console_model is None:
            return INPUT_SOCKETS.get(group)
        return input_socket_limit(group, console_model)
    return None


# -- No stereo pair can straddle the two kinds, and nothing had to be added
#    to make that true ---------------------------------------------------
#
# The obvious worry about one `USR` group holding two different kinds of
# virtual source is a pair with one of each in it. There is exactly one
# candidate -- `[24, 25]`, the two slots either side of the boundary -- and
# `stereo_pair_problem` already refuses it, because 24 is EVEN and a pair
# always starts on an odd slot. Every other consecutive pair sits wholly
# inside 1..24 or wholly inside 25..56.
#
# So the boundary falls exactly where the hardware rule already forbids a
# pair, and `verify_plan` needs no separate check for it. Recorded because
# the absence of that check is a decision, not an oversight: a later change
# that moved the boundary to an even slot would need one.
USER_KIND_BOUNDARY_IS_PROTECTED_BY_PARITY = USER_PATCH_SLOTS[0] % 2 == 1


# --------------------------------------------------------------------------
# GET/SET index-base mismatch on connector leaves
# --------------------------------------------------------------------------
#
# WING's GET reply for a patch connector is **one less** than the value its
# SET takes. Approved 2026-09-21 after the
# mechanism was established three ways over:
#
#   * 25 readings across two real apply runs, `readback == intended - 1`,
#     **zero exceptions**;
#   * cross-checked against the console's own post-apply `.snap`, which
#     WING writes itself and which never passes through our read path:
#     all 25 agree with what was INTENDED, not with what was read back;
#   * documented by Behringer as a convention, not an anomaly.
#     `WING_Remote-Protocols-3.1-03.pdf` p.72, footnote [54] on
#     `/$ctl/$stat/selidx`: *"The get command reports values between 0 and
#     75, but index 1 to 76 should be used when setting values."* The next
#     entry, `/$ctl/$stat/sof`, documents the same thing again.
#
# **Corrected on READ, never on write.** The write path is confirmed
# correct by the `.snap` evidence, so touching it would break a thing that
# works. This adjusts only the number a reply reports, before anything
# compares it to what was asked for.
#
# The table is an allow-list and the default is zero. An address that is
# not listed here is not adjusted, which is the posture that matters: an
# unverified correction turns a real "did not land" into a false "landed",
# and that is the same category of mistake as the bug.
_READBACK_INDEX_OFFSETS = (
    # Confirmed affected. 20 of 20 mismatches in the 2026-09-18 run, and
    # not one clean match -- 100% failure on this leaf while all ten other
    # leaves in the same run, including 140 other int writes, were 100%
    # clean. So this is not "ints are broken"; it is the 1-based
    # connection index specifically. The `grp` half of the very same patch
    # verifies 21/21, which is why a broken patch looks half-right.
    (re.compile(r"^/ch/\d+/in/conn/in$"), 1),
    (re.compile(r"^/io/out/[A-Z]+/\d+/in$"), 1),
    # The identical leaf on the aux bank. It sat on the "not corrected,
    # no evidence" list below until 2026-09-23, when A11 measured it:
    # the A11 read-speed run of 2026-09-22 read the
    # whole desk twice, per-leaf and by node dump, and out of 5,712 values
    # exactly **eight** disagreed -- `/aux/1..8/in/conn/in`, per-leaf 0,
    # dump 1. A dump carries the TEXT form, which is the number the desk
    # shows (`console.value_from_dump_text`), so the dump is the true one
    # and the per-leaf read was low by one. `/ch/{n}/in/conn/in`, already
    # corrected here, did NOT appear in that list of eight, which is the
    # control: the two paths agree wherever the correction is right.
    #
    # It had a live consequence. A Compact ships `/aux/1` patched from
    # USB 1 and `/aux/2` from PLAY 1 (`FACTORY_INPUT_PATCHES`), so an
    # uncorrected live read saw socket 0, matched neither, and reported
    # both media auxes as in use -- four findings on an untouched board
    # that the snapshot path scores at zero.
    (re.compile(r"^/aux/\d+/in/conn/in$"), 1),
    # Measured 2026-09-22 (A2b), the first run that ever wrote a colour:
    # wrote 3, 5, 11 and 18 to /ch/{3,5,11,18}/col and read back 2, 4, 10
    # and 17. Four for four. `col` was listed below as a candidate for
    # exactly this shape and came off that list on evidence, not on the
    # resemblance that put it there.
    # The user-patch source leaf. Measured 2026-09-23 (A16),
    # (the A16 after-capture): USR 25 was set to LOCAL IN 5 by hand, and the desk screen read
    # "USR 25, LCL 5". The `/io/in/USR/25` node dump -- the TEXT form, the
    # number the desk shows -- said 5; the per-leaf read said 4. Same
    # signature as the aux leaf above, same answer: the per-leaf read is
    # low by one. It also explains A11's 32 disagreements on
    # `/io/in/USR/{25..56}/user/in` (per-leaf 0, dump 1, on empty slots),
    # which were the reason `--bulk-read` could not become the default.
    #
    # This sat on the "not corrected" list below on the grounds that these
    # leaves are not in the node dump. A16 read 552 values out of the
    # `/io/in/USR/{n}` dumps, this leaf among them, so that premise was
    # wrong -- which is a fair illustration of why the list waits for a
    # desk rather than reasoning.
    #
    # It had a live consequence: `audit.user_patch_sources` read it
    # uncorrected, so C001 treated a user patch fed from LCL 5 as fed
    # from LCL 4 -- phantom power on the real jack was reported as
    # "patched to nothing", and the jack beside it was excused.
    (re.compile(r"^/io/in/USR/\d+/user/in$"), 1),
    # The alternate patch's socket. CONFIRMED on the
    # Compact by A23 (2026-09-28 19:22):
    # channel 1's alternate set to CRD 5 by hand answered `altin` text '5',
    # int 4 -- the same -1 as `in/conn/in`. The earlier, read-only evidence
    # it was first inferred from is A7 (2026-09-21):
    #   * `A7-with-AES-alt.txt`: `/ch/1/in/conn/altin` answered
    #     `sfi ['1', 0.0, 0]` -- text '1', int 0;
    #   * `A7-ch1-with-WLIVE-alt.snap`, the desk's own file of that
    #     session: `altin: 1`;
    #   * the A1 raw log of 2026-09-21: `/ch/1/in/conn/in`, whose SET value was
    #     1, answered the identical `sfi ['1', 0.0, 0]`.
    # Same leaf shape, same reply, same snapshot value as the corrected
    # `in/conn/in` beside it. `apply` writes this leaf from slice 3 on, so
    # leaving it uncorrected would have turned every correct alternate
    # patch into a reported mismatch. The desk check is in
    # the console session checklist.
    (re.compile(r"^/(ch|aux)/\d+/in/conn/altin$"), 1),
    (re.compile(r"^/(ch|aux|bus|main|mtx|dca)/\d+/col$"), 1),
    (re.compile(r"^/io/in/[A-Z]+/\d+/col$"), 1),
)

# Deliberately NOT corrected, each for the same reason -- same shape, no
# hardware evidence either way, and guessing is the mistake this fix is
# repairing. Every one of these is a line item on the next console session.
# The list is empty today: `in/conn/altin` left it on 2026-09-28, inferred from A7 and confirmed the same evening by A23.
#
# (`col` was on this list until 2026-09-22, `/aux/{n}/in/conn/in` until
# 2026-09-23, and `/io/in/USR/{n}/user/in` until 2026-09-24 (A16); all are
# in the table above now, measured rather than guessed. Each behaved exactly as its shape predicted, which is
# encouraging and was still not a reason to correct it in advance.)
#
# Filtering the parameter map for `int` params with `min == 1` gives 93
# addresses. Most are console-UI state nothing here touches; the ones
# above are the ones that are ours.


def readback_index_offset(address: str) -> int:
    """How much to ADD to a GET reply for `address` before comparing it to
    an intended value. Zero for everything not explicitly
    listed in `_READBACK_INDEX_OFFSETS`."""
    for pattern, offset in _READBACK_INDEX_OFFSETS:
        if pattern.match(address):
            return offset
    return 0


def correct_readback_index(address: str, value: object) -> object:
    """`value` as the console meant it, for an address whose GET reply is
    offset from its SET value.

    A no-op unless the address is in the table AND the value is a plain
    int: a `None` (unreadable), a bool, or a float is returned untouched
    rather than being arithmetic'd into something that looks like data.
    """
    offset = readback_index_offset(address)
    if not offset or value is None or isinstance(value, bool) or not isinstance(value, int):
        return value
    return value + offset


# ==========================================================================
# Confirmed on hardware, 2026-09-21. WING Compact, firmware
# 3.1-0-g9f314617, WLIVE card fitted, no AoIP module.
#
# Evidence is kept from the 2026-09-21 console runs -- raw OSC
# replies, not a recollection of what the desk looked like. Cited per fact
# below, because the whole value of this file is that a future session can
# tell what was measured from what was assumed.
# ==========================================================================

# -- Alternate input patch ------------------------------------
#
# A channel carries TWO patches and a switch between them;
# this is the encoding, from A7-{no-alts,with-AES-alt,with-WLIVE-alt}.txt.
#
#   /ch/{n}/in/conn/altgrp   S   the alternate patch's GROUP, exactly the
#                                vocabulary /in/conn/grp uses, plus 'OFF'
#                                when no alternate is set. Observed: 'OFF',
#                                'A' (AES50-A), 'CRD' (the WLIVE card).
#   /ch/{n}/in/conn/altin    sfi the alternate patch's socket index, the
#                                same shape as /in/conn/in -- so PRESUMED
#                                to carry the same -1 readback offset, and
#                                deliberately NOT corrected until measured.
#   /ch/{n}/in/set/altsrc    sfi 0/1: which of the two patches is LIVE.
#                                0 = main, 1 = alternate. The direction is
#                                settled by evidence, not by the name
#                                (2026-09-28): every
#                                factory-initialized snapshot on disk has
#                                0 with no alternate at all (OFF), so 0 is
#                                the main input by definition; the two show
#                                desks (Church-Full.snap, A17-wing-full.snap)
#                                carry 36 alternates each (32 USB, 4 CRD)
#                                for virtual soundcheck and every strip
#                                reads 0; A7's one
#                                strip deliberately put on its WLIVE
#                                alternate reads 1. So `apply` writes 0 --
#                                back on main -- on every strip it builds.
#   /ch/{n}/in/set/srcauto   0/1: the strip's "Input Select": 1 = Global
#                                (follows /io/altsw), 0 = Individual. A7's
#                                strip on Individual read 0; A23 (2026-09-28)
#                                set channel 1 to Global and it read 1 with
#                                the global switch both on and off. Read by
#                                nothing, written by nothing.
#
# Two addresses that do NOT exist, so nothing should reach for them:
#   /ch/{n}/in/conn/alt      no reply
#   /cfg/altsrc              no reply
#
# The GLOBAL "switch every channel at once" control was NOT found.
# `/$ctl/$stat/altsrc` answered once (echoing the per-channel leaf) and
# not on the other two runs, which is not a control -- that is the reply
# matching bug in this same session's data. Per-channel is confirmed.
# The global switch was found later, in the snapshots: `GLOBAL_ALT_SWITCH`
# below.
ALT_PATCH_GROUP = "/ch/{n}/in/conn/altgrp"
ALT_PATCH_SOCKET = "/ch/{n}/in/conn/altin"
ALT_PATCH_SELECTED = "/ch/{n}/in/set/altsrc"
ALT_PATCH_OFF = "OFF"
ALT_PATCH_MAIN = 0          # `in/set/altsrc`: on the main patch (see above)

# The GLOBAL alternate switch (`/io.altsw` in the parameter map, `io.altsw`
# in a .snap; `/io/altsw` over OSC). Found in the snapshots rather than by
# the A7b sweep, which never looked under /io: every snapshot on disk reads
# `false` except the A1 snapshot of 2026-09-21 (21:00), saved after
# the desk's global switch was flipped in A7b, which reads `true`. A23
# (2026-09-28) CONFIRMED it: with channel 1 on Input Select: Global, the
# switch ON read `/io/altsw` 1 and the strip's own `altsrc` 1; OFF read 0
# and 0. So 1 = global alternate engaged, and a strip following it
# reports the switch through its own `altsrc`. `apply` still NEVER writes
# it -- it moves every strip set to follow it, which is the engineer's
# call at the desk, not a show setting. `audit` reads it and reports it
# once per desk (C005).
GLOBAL_ALT_SWITCH = "/io/altsw"

# -- FX slots and the strip inserts that use them --------------
#
# WING has sixteen FX slots, `/fx/{1..16}`, and no send/return path to
# them: an effect is heard only when some strip INSERTS it. The insert
# lives on the strip, not the slot:
#
#   /{bank}/{n}/preins/on    int 0/1   the insert switch -- the bypass
#   /{bank}/{n}/preins/ins   S         'NONE', or 'FX1'..'FX16'
#   /{bank}/{n}/postins/...            the same pair, after the dynamics
#   /fx/{n}/mdl              S         the loaded effect, 'NONE' when empty
#
# Which banks carry which insert point is from
# the Compact parameter map: a channel, bus, Main and
# Matrix have both; an aux has `preins` only. The same leaves appear in
# the PDF's own `/ch/1` node dump (p25: `.preins.on=0,ins=NONE`,
# `postins.on=0,mode=FX,ins=NONE`). Values, not just descriptors, are in
# the A17 full-size capture (A17-wing-full.snap, 2026-09-23): sixteen
# loaded slots, each named by exactly one strip insert, every one on.
#
# The slot's own `$a_chn`/`$a_pos` report the same attachment from the
# other end, but they are read-only mirrors whose zero-means-unassigned
# reading is inferred, not measured -- the strip's `ins` is the setting
# itself, so that is what is read.
FX_SLOTS = 16
FX_EMPTY = "NONE"
FX_MODEL = "/fx/{n}/mdl"
INSERT_POINTS = {
    "ch": ("preins", "postins"),
    "aux": ("preins",),
    "bus": ("preins", "postins"),
    "main": ("preins", "postins"),
    "mtx": ("preins", "postins"),
}

# -- Which FX models make a bus an effect send ---------------
#
# A WING has no send/return path to an effect: a reverb is heard when a bus
# INSERTS the slot, and the usual way to build one is a bus whose only job
# is that insert, set fully wet, routed to Main. A strip that reaches Main
# directly and through that bus is not a doubled dry signal, which is what
# R012 warns about: the bus carries the effect's return. So a bus with one of
# these models inserted (switch on) is read as an effect send.
#
# The models are the time-based and modulation effects in the desk's own list
# (`initialized/fx_models.json`, the `/fx/{n}/mdl` enum on firmware 3.1),
# the ones built to be heard as a wet return:
#
#   reverb      HALL ROOM CHAMBER PLATE CONCERT AMBI V-ROOM V-REV V-PLATE
#               GATED REVERSE DEL/REV SHIMMER SPRING VSS3 BPLATE
#   delay       ST-DL TAP-DL TAPE-DL OILCAN BBD-DL
#   modulation  DIMCRS CHORUS FLANGER PHASER
#   pitch       PITCH D-PITCH
#
# Left out, as a judgement: DOUBLE (a doubler blends a shifted, delayed copy
# WITH the dry signal and is normally inserted on the voice itself; the one
# seen on a desk sat at mix 36 on a vocal bus, which carries a dry copy),
# ROTARY (a speaker simulator, inserted on the instrument), TAPE (tape
# saturation), and every EQ, dynamics, amp, enhancer and channel-strip model.
# EXT is an outboard loop whose content is unknown. Whether the slot is set
# fully wet (`fxmix`) is not read: that would be 16 more requests on every
# Watch pass, and the INFO that stands R012 down names the model it went on.
#: model -> what it is, as the INFO says it ("a reverb").
EFFECT_SEND_MODELS = {
    **dict.fromkeys(("HALL", "ROOM", "CHAMBER", "PLATE", "CONCERT", "AMBI", "V-ROOM",
                     "V-REV", "V-PLATE", "GATED", "REVERSE", "DEL/REV", "SHIMMER",
                     "SPRING", "VSS3", "BPLATE"), "reverb"),
    **dict.fromkeys(("ST-DL", "TAP-DL", "TAPE-DL", "OILCAN", "BBD-DL"), "delay"),
    **dict.fromkeys(("DIMCRS", "CHORUS", "FLANGER", "PHASER"), "modulation effect"),
    **dict.fromkeys(("PITCH", "D-PITCH"), "pitch shifter"),
}

# -- Talkback (the comms half) ----------------------------------
#
# From the 2026-09-08 walk of a Compact
# and the PDF's `/cfg/talk` table:
#
#   /cfg/talk/assign          list [OFF, CH40, AUX8]   the strip talkback uses
#   /cfg/talk/{A,B}/{dest}    int 0/1                  where TALK A / TALK B go
#
# with `{dest}` one of B1..B16 (busses), MX1..MX8 (Matrices), M1..M4
# (Mains): 28 per button. Every capture on disk -- Compact and full-size --
# has `assign` OFF and every destination 0, which is the factory state, so
# there are no values yet for a talkback somebody set up. What the rule
# reads is only whether each bit is 0 or 1, never a readback-offset int.
TALK_ASSIGN = "/cfg/talk/assign"
TALK_OFF = "OFF"
TALK_BUTTONS = ("A", "B")
TALK_DESTINATIONS = (tuple(f"B{n}" for n in range(1, 17))
                     + tuple(f"MX{n}" for n in range(1, 9))
                     + tuple(f"M{n}" for n in range(1, 5)))


def talk_destination(button: str, dest: str) -> str:
    return f"/cfg/talk/{button}/{dest}"


# The strips `assign` can name, as a plan channel's (bank, channel), and
# the enum value each one is -- from the same `list [OFF, CH40, AUX8]`
# (the Compact parameter map, `/cfg/talk.assign`).
# The desk's talkback can use no other strip: a talk mic on ch 12 is an
# ordinary mic channel, and the TALK buttons cannot reach it.
TALK_ASSIGN_STRIPS = {("ch", 40): "CH40", ("aux", 8): "AUX8"}

# A strip whose name (or input) reads like this IS the talk mic:
# "Talkback", "TALKBACK", "Talk Mic", "Talk", "TB", "T/B". One spelling
# for every reader -- `apply` sets `assign` by it (2026-10-02), `audit`'s
# CV014 exempts the strip by it, and `verify_plan` warns by it about a
# talkback strip `assign` cannot reach. "Talk box" is a guitar effect,
# not a talk mic.
TALKBACK_NAME_RE = re.compile(
    r"(?<![a-z])(?:talk ?back|talk(?! ?box)|t/?b)(?![a-z])", re.IGNORECASE)


def is_talkback_name(*texts: object) -> bool:
    """True when any of `texts` (a strip's name, its input's name) reads
    as the talk mic -- see `TALKBACK_NAME_RE`."""
    return any(isinstance(t, str) and TALKBACK_NAME_RE.search(t) for t in texts)


# -- AES50 ports and the monitor source ----------------
#
# From the 2026-09-08 walk of a WING Compact
# (the raw walk of a Compact):
#
#   /$stat/{A,B,C}/stat   list [-, OK, ERR, UPD]   the AES50 port's link
#   /$stat/{A,B,C}/dev    string                   the device on it
#   /cfg/mon/{1,2}/src    list [OFF, MAIN.1.., MTX.1.., BUS.1.., AUX.1..]
#
# **AES50.** An output patch is stored on the SOCKET, never on the bus, so
# a desk cannot be asked "where does bus 1 go"; only "what feeds AES50-A
# 7". A read that never visits AES50-A therefore cannot see a monitor bus
# patched to a stage box's output, and R002 called six correctly
# patched wedges "no route" on a Compact. So the read
# asks each port's link status first, and reads the outputs of every port
# with a device on it (`OK`, `ERR` or `UPD`). The walk's desk had nothing on
# AES50, so `-` is the only value seen on hardware; `OK`, `ERR` and `UPD`
# are the list's own words. **UPD means the stage box's firmware needs an
# update** (2026-10-25): the desk flags a box whose
# firmware is older than it expects, or does not fully match the console's
# version. The protocol document (WING_Remote-Protocols-3.1-03.pdf, the
# `/$stat/A/stat` row) lists `-, OK, ERR, UPD` without a meaning; a
# full-size WING reads `UPD` on AES50-A with a healthy Behringer S32 on it
# passing audio, with port B unplugged as well.
# Audio passes, but preamp remote control and dual-port A/B need current
# stage-box firmware, so the audit says it at INFO (C010) and never raises
# it. `ERR` is still read as a link error, **not yet confirmed on a desk**
# (a cable pull). Forge's capture of that desk
# (2026-10-22): `/$stat/A/dev "S32"`, `/$stat/A/stat "UPD"`,
# B and C `dev ""` / `stat "-"`, `/$syscfg/opt_mod "DANTE"`; `errorsc` and
# `errorsu` were not in it and are still unread.
#
# **Monitor source.** `/cfg/mon/1` and `/cfg/mon/2` are the desk's two
# monitor outputs (the phones and the monitor speakers), and `src` names
# the bus, Main or Matrix each listens to. A Matrix chosen there is in use
# inside the desk with no socket of its own, which is what `verify`'s
# output.no-patch already says; R006 said the opposite.
AES50_PORTS = ("A", "B", "C")
#: The `stat` values that mean a device is on the port: linked, in error,
#: or linked with stage-box firmware the desk wants updated (`UPD`). `-` is an empty port.
AES50_DEVICE_STATES = ("OK", "ERR", "UPD")


def aes50_status_address(port: str) -> str:
    return f"/$stat/{port}/stat"


def aes50_device_address(port: str) -> str:
    """The leaf naming the device on an AES50 port (`S16`, or empty)."""
    return f"/$stat/{port}/dev"


# The size of a stage box. `/io/in/A` lists 48 sockets whatever is on the
# port (that is the address space, like the expansion bays' 64), so the
# count the DESK gives says nothing of the box: an S16 on AES50-A has 16
# inputs, and a channel patched to `A 17` is patched to nothing -- silent on
# stage, and the console accepts and reads it back. The device names what is
# on the port (`/$stat/A/dev` reads `S16`), and this table gives its size.
#
# **Only boxes with a measured or documented size are here, never a guess**:
# a name this table does not have is reported and its sockets are left
# unchecked (`box_size`). The S16 is the Behringer S16 manual's own count,
# 16 mic/line inputs and 8 outputs; an SD8, SD16, DL16 or DL32 goes in once
# its name has been read off a desk and its size confirmed.
#: `{device name as `/$stat/{port}/dev` reads it, casefolded: (inputs, outputs)}`
AES50_BOX_SOCKETS = {"s16": (16, 8)}


def box_size(device: object) -> tuple[int, int] | None:
    """`(inputs, outputs)` of the stage box `device` names, or None for a
    name this project has no size for."""
    return AES50_BOX_SOCKETS.get(str(device or "").strip().casefold())


MONITOR_SOURCES = ("/cfg/mon/1/src", "/cfg/mon/2/src")
#: `MTX.4` -> ("MTX", 4): the objects a monitor source can name.
MONITOR_SOURCE_RE = re.compile(r"^(MAIN|MTX|BUS|AUX)\.(\d+)$")


# -- Expansion bays: what is fitted ---------------------
#
# From A8_patch_test.txt. Both are read-only and answer on every model.
#
#   /cards/$type        S   the rear-panel card. 'WLIVE' on this desk.
#   /$syscfg/opt_mod    S   the internal AoIP module. 'NONE' when the slot
#                           is empty -- which is the case that matters.
FITTED_CARD_ADDRESS = "/cards/$type"
FITTED_MODULE_ADDRESS = "/$syscfg/opt_mod"
NO_MODULE_FITTED = "NONE"

# The two input/output groups that are a BAY rather than a socket -- the
# only two whose existence is a question about what is physically plugged
# into the console, and the only two the desk answers that question for.
# Mapped to the address that answers it, so a caller never has to pair
# them up by hand and get one of them wrong.
#
# LCL/AUX are the other "the address space lies about the panel" case
# (`MODEL_VARIANT_GROUPS`) and are deliberately NOT here: the desk
# states no inventory for those, which is exactly why they needed a
# `--console-model` flag and these do not.
EXPANSION_BAY_ADDRESSES = {
    "CRD": FITTED_CARD_ADDRESS,
    "MOD": FITTED_MODULE_ADDRESS,
}


def bay_is_empty(reported: object) -> bool:
    """Does this `/cards/$type` or `/$syscfg/opt_mod` reading mean "there
    is nothing in that bay"?

    True only for the literal `NONE` both enums carry
    (`[NONE, WLIVE, WDANTE, WMADI, WDWSG]` and
    `[NONE, DANTE, WSG, ACOM]`). Anything else -- a card name, a module
    name, a name from a firmware newer than this table, an unparseable
    reply, or no reply at all -- is NOT an empty bay. That asymmetry is
    the point: the caller refuses a patch on the strength of this
    answer, so it may only say "empty" when the desk said so in as many
    letters. Guessing in the other direction would refuse a plan over a
    card we simply do not have a name for.
    """
    return isinstance(reported, str) and reported.strip().upper() == NO_MODULE_FITTED

# -- The desk does NOT refuse a patch to an unfitted bay ------
#
# The measurement that matters most here, because it decides whether this
# is our problem. With /$syscfg/opt_mod = 'NONE', setting
# /ch/40/in/conn/grp to 'MOD' was ACCEPTED: the readback came back 'MOD'.
# No error token, no refusal, no clamp.
#
# So a channel can be patched to a bay with no hardware in it, and the
# console will show that patch and pass audio from nowhere. Nothing
# downstream will report it -- the patch is, as far as the desk is
# concerned, exactly what was asked for. **Refusing this is Atoo's
# job or it does not happen at all**, which is what the empty-bay audit rule is for.
UNFITTED_BAY_PATCH_IS_ACCEPTED = True

# -- Stereo pairs must start on an odd socket ------------------
#
# A10_result.txt, tested by hand at the desk: asked for a stereo pair
# starting on an EVEN socket, the console refused and snapped the pair
# back to [prior odd, selected even]. This confirms STEREO_PAIR_RULE above
# is the desk's own rule and not just the protocol PDF's description of
# it, so verify_plan refusing the same thing agrees with the hardware
# rather than merely with the documentation.
STEREO_PAIR_RULE_CONFIRMED_ON_HARDWARE = "2026-09-21"

# -- the index offset, confirmed a second way ----------------------------
#
# The A1 snapshot (A1-touringband.snap) is a console-side export that does
# not pass through this project's read path at all. It shows
# ae_data.ch.{1..19}.in.conn.in = 1..19, the INTENDED values, for the same
# run whose GET replies returned 0..18. Two independent paths disagreeing
# by exactly one is what promotes the offset from "the readbacks look off"
# to a fact about the GET reply specifically.


# -- "Link Customization to Source" (`clink`), the switch that decides
#    whether a name is visible at all. -------------------
#
# Protocol PDF p.48: `/ch/1/clink  I  0..1  Channel 1 custom link`, and the
# same leaf on aux (p.52), bus, main, mtx and dca.
#
# **It defaults to ON, and while it is on the strip displays the NAME,
# COLOUR and ICON of the input socket it is patched to.** The strip's own
# name/col/icon are accepted, stored, and read back correctly -- and
# ignored by the surface. A write that verifies and changes nothing an
# engineer can see is the worst failure shape this project has, because
# the proof and the desk disagree and the proof looks right.
#
# Measured 2026-09-22. The A1 journal called all 19 channel names a match;
# a note read "Channel names are NOT present." A name set by hand
# "would only stick if the 'Link Customization to Source' box
# is unchecked (seems to be the default)". Diffing the snapshots either
# side of that changes exactly two leaves: `ch/40/clink` True -> False and
# `ch/40/col` 1 -> 13.
#
# **The fix is to name the SOURCE, not to break the link** (2026-09-22):
# set the name, icon and color on the source, and let the 'Link
# Customization to Source' flag flow the customization to the channel,
# since that is the default. That is right for a better reason than going
# with the desk's grain: `input.csv` is one row per PHYSICAL INPUT, so the name originates
# at the socket. Naming the strip and cutting the link is the distortion.
#
# So `apply` writes the name/col/icon to `/io/in/{grp}/{n}/...` and forces
# `clink=1`, and only falls back to unlinking for a strip whose source
# group has no nameable socket (BUS, MAIN, MTX, OFF).
CUSTOM_LINK_ADDRESS = "/{bank}/{n}/clink"
CUSTOM_LINK_DEFAULT_IS_ON = True
CUSTOM_LINK_LINKED = 1
CUSTOM_LINK_UNLINKED = 0

# -- One measured point on the 1..18 colour palette -----------
#
# From that same snapshot pair: channel 40 was set to ORANGE by hand
# and the snapshot records `col: 13`. A snapshot is console-side, so this
# is the true value rather than the offset readback.
#
# **Measured in full on 2026-09-22** (A2b, the palette-names run): col=1..18 written to AES50-A
# sockets 1..18 and read off the desk's I/O page in order.
#
# The 13 = Orange prediction held, which is the cross-check that makes the
# rest trustworthy: it came from a completely different route -- one channel
# was set orange by hand the night before and the snapshot
# recorded `col: 13`.
#
# **Four of the NAMES were then corrected by the desk itself, 2026-09-28**
# (A24, desk run 2026-09-28-1927): every index was written
# to a strip named "<index> <our name>", all 208 writes read back, and the
# desk's own colour names differed at four of them -- 9 is Red (we said
# Crimson), 11 is Pink (Magenta), 13 is Amber (Orange) and 15 is Orange
# (Red). The indexes were never wrong; the words were. It mattered: a
# conventions file's "Drums-Red" had been putting 15 on the desk, which
# the desk calls Orange. The table below is the desk's own names.
COLOUR_NAMES = {
    1: "Navy", 2: "Blue", 3: "Violet", 4: "Turquoise", 5: "Green",
    6: "Lime", 7: "Yellow", 8: "Rust", 9: "Red", 10: "Salmon",
    11: "Pink", 12: "Purple", 13: "Amber", 14: "Cyan", 15: "Orange",
    16: "Mint", 17: "Grey", 18: "White",
}

# The two names A24 retired, kept so a plan or conventions file written
# with them still colours the strip it meant to. `verify` says, at INFO,
# which desk colour each became (`strip.colour-alias`, `bus.colour-alias`).
#
# "Red" and "Orange" are deliberately NOT here: they changed meaning
# (Red 15 -> 9, Orange 13 -> 15), and the new meaning is the point of the
# fix -- the desk's Red is what "Drums-Red" asks for.
COLOUR_ALIASES = {"Crimson": 9, "Magenta": 11}


def _normalise_colour(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


_COLOUR_BY_NORMALISED = {
    _normalise_colour(name): index for index, name in COLOUR_NAMES.items()
}
_ALIAS_BY_NORMALISED = {
    _normalise_colour(name): index for name, index in COLOUR_ALIASES.items()
}


def colour_index(name: object) -> int | None:
    """The console's 1..18 index for a colour stated in words, or None.

    Forgiving in the same way preset matching is -- case, spaces,
    punctuation -- because a conventions file says "red" or "Red" or
    "RED" and means the same thing all three times. A retired name in
    `COLOUR_ALIASES` ("Crimson", "Magenta") resolves too; `colour_alias`
    says when one did.

    **None is a real answer, not a failure to try.** The desk has
    eighteen colours and engineers use more words than that ("Gold",
    "Brown"). Guessing at the nearest would put a colour on a desk that
    nobody chose, so an unmatched name is reported and left alone instead.
    """
    if not isinstance(name, str):
        return None
    key = _normalise_colour(name)
    index = _COLOUR_BY_NORMALISED.get(key)
    return index if index is not None else _ALIAS_BY_NORMALISED.get(key)


def colour_alias(name: object) -> int | None:
    """The index a retired colour name stands for, or None if it is not one.

    None for any of the desk's eighteen, and for a word the desk does not
    have at all: only a name `colour_index` resolves THROUGH an alias
    answers here, so a caller can announce the translation.
    """
    if not isinstance(name, str):
        return None
    key = _normalise_colour(name)
    if key in _COLOUR_BY_NORMALISED:
        return None
    return _ALIAS_BY_NORMALISED.get(key)


# -- Input groups whose sockets carry name/col/icon -----
#
# Protocol PDF pp.40-43: each of these has the full customization triple
# `/io/in/{grp}/{n}/{name,col,icon}`. `BUS`, `MAIN`, `MTX` and `OFF` are
# internal or absent sources and have none, so a strip patched to one of
# those has no socket to name and has to carry its own identity instead.
NAMEABLE_INPUT_GROUPS = frozenset({
    "A", "AES", "AUX", "B", "C", "CRD", "LCL", "MOD", "OSC", "PLAY", "SC",
    "USB", "USR",
})


# -- Which input groups actually have a head amp --------------------------
#
# The physical mic/line inputs, and only those. `apply` writes phantom to
# `/io/in/{grp}/{n}/vph` for exactly this set (its `_VPH_CAPABLE_GROUPS`),
# and it is the same question as "do two strips sharing this source share
# a gain knob" -- a USR slot, PLAY, OSC, USB, CRD and MOD carry a signal
# that was already levelled somewhere else.
#
# Named here rather than left in apply.py because verify_plan needs the
# same fact, and two copies of a hardware fact is how they drift.
#
# `audit.console_read_plan` reads it too: the first live
# audit of a full-size WING (A18)
# asked for `/io/in/AUX/1..8/vph`, the full-size's line-level AUX inputs,
# and none of the eight answered -- 24s of a 47s read.
PHANTOM_CAPABLE_GROUPS = frozenset({"LCL", "A", "B", "C"})


# ==========================================================================
# Confirmed on hardware, 2026-09-23. WING Compact, firmware
# 3.1-0-g9f314617. Evidence:
# the A11 read-speed run and the A12 protocol probes, 2026-09-22.
# ==========================================================================

# -- A send's leaves depend on WHAT IS SENDING ----------------
#
# A strip's send carries a pre/post `mode` and a `pon` ("pre always on")
# switch. **A bus's and a Main's send does not.** It has `on`, `lvl` and a
# plain `pre` flag, and the two leaves a strip would have do not answer at
# all.
#
# The desk says so in as many characters. A12 asked it to dump
# `/bus/1/send` whole, and the whole 568-byte reply is:
#
#     1.on=0,lvl=-oo,pre=0,.2.on=0,lvl=-oo,pre=0,. ... .MX8.on=0,lvl=-oo,pre=0,.
#
# Twenty-four children -- busses 1..16 AND matrices MX1..MX8 -- carrying
# `on`, `lvl`, `pre` and nothing else. The same probe's `/ch/1/send/1` is
# `on=0,lvl=-oo,pon=0,mode=PRE,plink=0,pan=0,`. So this is a fact about
# the SOURCE object, not about matrix sends: a bus's send to another bus
# has the same three leaves as its send to a matrix.
#
# A11 had already measured the cost of not knowing it. Of the 6,032
# addresses a live audit read asked for, 320 went unanswered -- every one
# a `/bus/{n}/send/MX{m}/mode` or `.../pon`, or the same on a Main. 16
# busses x 8 matrices x 2 leaves = 256, plus 4 Mains x 8 x 2 = 64, which
# is exactly 320 with nothing left over. Its node dump of `/bus/1` agreed:
#
#     of the 39 address(es) a read wants here, 23 are in the dump;
#     MISSING ['/bus/1/send/MX1/mode', '/bus/1/send/MX1/pon', ...]
#
# 39 - 23 = 16 = 8 matrices x 2 leaves. And the dump of `/ch/1` carried
# **all 106** addresses a read wants from a channel.
#
# The Compact parameter map agrees a third time,
# from the protocol PDF and independently of any hardware:
# `/bus/{n}/send/*` and `/main/{n}/send/MX*` carry `{on, lvl, pre}`, while
# `/ch/{n}/send/*` and `/aux/{n}/send/*` carry
# `{on, lvl, mode, pon, pan, plink}`. `apply.py` has written the bus/Main
# form (`on`, `lvl`, `pre`).
#
# **`pre` is not in this project's read plan and this table does not put
# it there.** `SEND_LEAVES` says what the console HAS; `audit.
# send_fields_for` intersects it with what a read asks for, and no rule
# reads a bus send's pre/post state today. Adding an address to the read
# plan is a separate decision from removing one that does not exist --
# see the PR discussion.
#
# **Why this is a table and not an `if` in the read loop.** Asking for a
# leaf that is not there costs three seconds -- `WingConsole._request`
# sends and then retries twice, and none of the three is answered. 320 of
# them is 960 seconds, 96% of the wall time of a full read on real
# hardware. That is a fact about the console, so it lives where the
# measured facts live and every caller gets it.
SEND_LEAVES = {
    "ch": frozenset({"on", "lvl", "mode", "pon", "pan", "plink"}),
    "aux": frozenset({"on", "lvl", "mode", "pon", "pan", "plink"}),
    "bus": frozenset({"on", "lvl", "pre"}),
    "main": frozenset({"on", "lvl", "pre"}),
}

# Banks whose send leaves have been enumerated above.
MEASURED_SEND_LEAF_BANKS = tuple(sorted(SEND_LEAVES))


def send_has_leaf(bank: str, leaf: str) -> bool:
    """Does a send on an object in `bank` carry `leaf` at all?

    True for every leaf of a bank nobody has enumerated, which is the
    direction that costs a timeout rather than a value: an address
    wrongly skipped is a value the report silently does not have, and an
    address wrongly asked for is three seconds and an honest
    "unanswered". Same posture as `_READBACK_INDEX_OFFSETS` above -- only
    what was measured changes what happens.
    """
    leaves = SEND_LEAVES.get(bank)
    return True if leaves is None else leaf in leaves


def parse_socket_counts(spec: str | None) -> dict[str, int]:
    """"LCL=20,A=48" -> {"LCL": 20, "A": 48}: socket groups and how many sockets
    each has. Physical socket counts have no confirmed console-wide default
    (they vary with hardware and expansion cards), so stating them is the only
    way to give them, never a guess. Anything that is not `GROUP=COUNT` raises
    a ValueError that says what to write instead."""
    counts: dict[str, int] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        group, equals, count = part.partition("=")
        group, count = group.strip(), count.strip()
        if not (equals and group and count.isascii() and count.isdigit()):
            raise ValueError(f"{part!r} is not a socket group and its count. Write "
                             "GROUP=COUNT pairs separated by commas, for example LCL=8,A=48.")
        counts[group] = int(count)
    return counts

