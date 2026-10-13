"""WING channel preset (`.chn`) and bus preset (`.bus`, see
`load_bus_preset` and `atoo/bus_presets.py`) loading -- D2's "rules carry policy,
presets carry values" (docs/product/project-brief.md), now that D7's
console-recall design is confirmed dead (experiments/wing/spike_preset_recall.py:
WING has no remote "load this preset" command -- presets are only
recallable as Scenes inside an open Show, and Scene tags can only be
assigned by hand on the console screen).

A `.chn` file is plain JSON whose `ch_data` object has exactly the same
shape as a channel inside a saved show (`ae_data.ch.{n}`) -- the same
field names Atoo already writes over the network parameter-by-
parameter (docs/reference/wing-compact-parameter-map.json). That means
Atoo never needs the console's own preset library: it keeps its own
directory of `.chn` files (seeded from real WING exports) and "recalls" a
preset by writing its parameter values to the target channel, exactly
like any other planned write -- no upload, no Scenes.

A `.chn` file carries far more than a sound, though: `in.conn` (physical
patch), `fdr`/`mute`/`pan`/`wid` (live levels), `main`/`send` (bus
routing), `tags` (DCA/mute-group membership) and `name`/`col`/`icon`
(identity) are all in there alongside the actual processing. Applying a
preset's fields blindly would repatch inputs, wreck routing and rename
channels from a preset that was only meant to carry a drum sound -- so
this module enforces an explicit allow-list of processing-only fields
(see `docs/reference/wing-channel-preset.md` for the full field-by-field
justification, derived from the WING protocol's own "Library Scopes"
taxonomy plus a diff of five real preset exports; the fixtures in
tests/fixtures/presets/ are now the maintainer's own set). Anything in `ch_data` this module doesn't
recognize -- as either in-scope or deliberately excluded -- becomes a
named warning on the loaded preset, never a silent guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Dotted-path prefixes (within ch_data, "." joining nested keys) that WING's
# own "Library Scopes" appendix (WING_Remote-Protocols-3.1-03.pdf, Appendix
# "Scopes and Safes") groups under the sound-shaping CONTENTS icons FILTER,
# GATE, DYN and EQ -- not under CUST (identity), CONN/IN (patch/gain stage),
# MAIN/SEND (routing), FDR/MUTE/PAN (live levels) or TAGS (membership).
# `peq` (WING's "PreSend EQ" node) is included under EQ: the same appendix
# lists "TAP EQ Settings in Bus Sends" as part of the EQ icon, and the
# protocol text names `/ch/{n}/peq` a "PreSend EQ node" -- same scope,
# different tap point.
_ALLOWED_PREFIXES = (
    "flt.",
    "gate.",
    "gatesc.",
    "dyn.",
    "dynxo.",
    "dynsc.",
    "eq.",
    "peq.",
)

# WING's own scope doc puts input DELAY in its own CONTENTS icon, separate
# from IN (trim/balance/phase, gain-staging for whatever source is patched
# in) and CONN (the patch itself) -- time-alignment is a processing decision
# about the mic, not a fact about this show's patch, so these three (and
# only these three, out of the whole in.set.* block) are in scope.
_ALLOWED_EXACT = frozenset(
    {
        "in.set.dly",
        "in.set.dlymode",
        "in.set.dlyon",
    }
)

# Fields that live inside an otherwise in-scope section but hold a
# cross-channel reference rather than a portable value: WING's protocol
# text (`/ch/1/gatesc/src`, `/ch/1/dynsc/src`) allows "SELF, CH.1..CH.40".
# Replaying a captured "CH.12" onto a different channel or show would
# silently sidechain-key off whatever happens to occupy channel 12 there --
# exactly the kind of guess this project refuses to make. These are pulled
# out of `parameters` and reported as warnings instead of being applied.
_CHANNEL_REFERENCE_FIELDS = frozenset({"gatesc.src", "dynsc.src"})

# Everything else in ch_data that this module has actually seen (across the
# real exports, and every preset in tests/fixtures/) and deliberately excludes,
# because it is patch, live level, routing, membership or identity rather
# than processing -- D2. Kept explicit, alongside the allow-list, so that a
# field belonging to *neither* set is recognized as genuinely unknown
# (see `_classify`) instead of quietly falling through as "not allowed".
_EXCLUDED_EXACT = frozenset(
    {
        # "custom link" (protocol PDF p.48), i.e. the desk's "Link
        # Customization to Source" switch -- NOT stereo-link pairing,
        # which is what this comment said until 2026-09-22. It governs
        # whether the strip shows its own name/colour/icon or inherits the
        # patched socket's, so it is identity, not sound, and it stays
        # excluded -- with more reason than before. `apply` forces
        # `clink=1` on every patched strip and puts the name on the
        # SOURCE socket, so a preset flipping this to 0 would strand every
        # strip showing its own (unwritten) name instead.
        "clink",
        "col",  # cosmetic scribble-strip color
        "name",  # channel label -- identity, set by conventions/input list
        "icon",  # cosmetic scribble-strip icon
        "led",  # cosmetic scribble-strip LED state
        "mute",  # live mix state
        "fdr",  # fader level -- live mix state, and boilerplate -144 in all 5 fixtures anyway
        "pan",  # live mix state
        "wid",  # live mix state (stereo width)
        "solosafe",  # solo/mix config, not processing
        "mon",  # monitor-routing mode
        "proc",  # process order -- WING's own scope doc files this under CONFIG, not GATE/DYN/EQ/FILTER
        "ptap",  # pretap-to-sends point -- CONFIG scope; also governs what audio the sends hear (routing)
        "tapwid",  # the pretap's width -- `ptap`'s other half, same routing reasoning (chpreset.11)
        "tags",  # DCA / mute-group membership
    }
)
_EXCLUDED_PREFIXES = (
    "in.conn.",  # physical patch (WING's CONN scope)
    "main.",  # bus assignment/level (MAIN[1..4] scope) -- routing
    "send.",  # bus assignment/level (SEND scope) -- routing
    "preins.",  # FX-engine slot assignment -- allocates a shared, show-wide hardware resource
    "postins.",  # same, post-chain insert point
)
_EXCLUDED_IN_SET_EXACT = frozenset(
    {
        "in.set.srcauto",  # source-select behavior -- tied to what's actually patched this show
        "in.set.altsrc",
        "in.set.inv",  # phase flip -- WING's IN scope (patch/gain-stage), not FILTER/DELAY
        "in.set.trim",  # gain-staged for a specific physical source level
        "in.set.bal",
        # The channel's VIEW of its input socket's head amp, not a channel
        # leaf of its own -- WING's `$` prefix, and the protocol PDF p.47
        # says of both "depends on source type". New in chpreset.11 (they
        # are absent from every chpreset.8 export).
        #
        # Excluding them is not housekeeping. Gain and phantom belong to
        # the physical socket and are the input list's to state; phantom
        # in particular is the one value in this system with a `safety`
        # check over it (`_check_safety`, a ribbon mic and 48V). A preset
        # saved on someone else's desk quietly carrying 48V into a channel
        # the plan never asked to energise is the exact failure that check
        # exists to prevent, and a preset must not be a side door around
        # it.
        "in.set.$g",
        "in.set.$vph",
    }
)


class PresetError(ValueError):
    """Raised for any problem with a `.chn` preset file -- malformed JSON,
    an unexpected `type`, or a missing `ch_data` -- always naming the file
    at fault. Matches the project's standing rule: never silently coerce
    or drop a malformed input."""


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    """Reduce a nested ch_data dict to dotted-path leaves ("eq.2g" ->
    -11.1). ch_data has no lists in any of the five reference exports --
    every leaf is a scalar, bool or string -- so a list here is itself
    unrecognized shape, not something to flatten further."""
    if not isinstance(node, dict):
        return {prefix: node}
    out: dict[str, Any] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _classify(path: str) -> str:
    """Return "in_scope", "excluded" or "unknown" for one dotted ch_data
    leaf path. "unknown" is the load-bearing case: a field this module has
    never seen and so has no basis to include or exclude -- see the
    warning this produces in `load_preset`."""
    if path in _ALLOWED_EXACT or any(path.startswith(p) for p in _ALLOWED_PREFIXES):
        return "in_scope"
    if (
        path in _EXCLUDED_EXACT
        or path in _EXCLUDED_IN_SET_EXACT
        or any(path.startswith(p) for p in _EXCLUDED_PREFIXES)
    ):
        return "excluded"
    return "unknown"


@dataclass(frozen=True)
class ChannelPreset:
    """One Atoo-managed channel preset, loaded from a WING `.chn`
    export. `parameters` is restricted to the processing allow-list --
    the flat dotted-path -> value form the apply layer can write directly,
    one leaf at a time, the same way it writes any other planned
    parameter. `warnings` names anything this loader found in the source
    file that it could neither confidently include nor confidently
    exclude, and is never empty-by-omission: an empty list is a positive
    claim that nothing unrecognized was found."""

    name: str
    source_path: Path
    creator_fw: str
    creator_model: str
    created: str
    source_channel: int | None
    parameters: dict[str, Any]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def leaves(self) -> dict[str, Any]:
        """Alias for `parameters`, named to match how the apply layer
        talks about a plan: a flat set of dotted-path leaves to write."""
        return self.parameters


def load_preset(path: str | Path) -> ChannelPreset:
    """Load and validate one `.chn` file. Raises PresetError for anything
    that isn't a WING channel preset in the shape this module understands
    -- never returns a partially valid result."""
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PresetError(f"{path}: could not read preset file ({exc})") from exc

    try:
        doc = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PresetError(f"{path}: not valid JSON ({exc})") from exc

    if not isinstance(doc, dict):
        raise PresetError(f"{path}: expected a JSON object at the top level")

    doc_type = doc.get("type")
    if not isinstance(doc_type, str) or not doc_type.startswith("chpreset"):
        raise PresetError(
            f"{path}: expected a WING channel preset (type starting with "
            f"'chpreset'), got {doc_type!r}"
        )

    ch_data = doc.get("ch_data")
    if not isinstance(ch_data, dict):
        raise PresetError(f"{path}: missing or malformed 'ch_data'")

    flat = _flatten(ch_data)

    parameters: dict[str, Any] = {}
    warnings: list[str] = []
    for leaf_path, value in flat.items():
        classification = _classify(leaf_path)
        if classification == "in_scope":
            if leaf_path in _CHANNEL_REFERENCE_FIELDS and value != "SELF":
                warnings.append(
                    f"{leaf_path} references channel {value!r} instead of SELF -- "
                    "not portable across channels/shows, dropped rather than "
                    "silently rewiring a sidechain"
                )
                continue
            parameters[leaf_path] = value
        elif classification == "unknown":
            warnings.append(
                f"{leaf_path}={value!r} is not on the processing allow-list "
                "and not recognized as a deliberately excluded field -- "
                "see docs/reference/wing-channel-preset.md"
            )
        # "excluded" fields (patch/level/routing/membership/identity) are
        # dropped on purpose, per D2 -- no warning, that's the design.

    name = doc.get("info_text")
    if not isinstance(name, str) or not name:
        # info_text is the only human-assigned label in a .chn file (the
        # ch_data "name" field is deliberately excluded -- see above), so
        # falling back to the filename is the only option left, not a guess
        # at what the engineer meant to call it.
        name = path.stem

    source_channel = doc.get("source_channel")
    if not isinstance(source_channel, int):
        source_channel = None

    return ChannelPreset(
        name=name,
        source_path=path,
        creator_fw=str(doc.get("creator_fw", "")),
        creator_model=str(doc.get("creator_model", "")),
        created=str(doc.get("created", "")),
        source_channel=source_channel,
        parameters=parameters,
        warnings=tuple(warnings),
    )


# -- Bus presets (`.bus`) -- an earlier change -------------------------------------
#
# A `.bus` is the same `chpreset.11` envelope as a `.chn` (the extension is
# what tells them apart), whose `ch_data` is a BUS strip: `in.set`
# (inv/trim/bal), `busmono`, a six-band `eq`, `dyn`, `dynxo`, `dynsc`
# (tapped at `BUS`), `dly`, `preins`, `postins`, `main`, `send`, `bus_feed`,
# plus identity and live state. Beside it, `preins_data` (and
# `postins_data`) carries the EFFECT the insert names -- `mdl` and every
# parameter -- and `target_fx` the engines it was saved from, `[pre, post]`
# with 0 for none (the maintainer's two: `[5, 0]` and `[8, 0]`, each matching its
# `preins.ins`).
#
# The processing allow-list is the channel preset's, for the nodes a bus
# has: EQ, dynamics, its crossover and sidechain filter, and the bus's own
# output delay (WING's DELAY scope, as a channel's input delay is). Not
# the width (`busmono`: the plan decides mono/stereo, CLAUDE.md), not the
# routing, level, identity or tags -- the same reasons as a channel's.
# The insert is not written from `ch_data` at all: the engine is a shared
# desk resource that Atoo allocates (`fx_engines.allocate`), so the
# preset's `preins.ins` is only a preference, and its `preins.on` is only
# a record of how it was saved.
_BUS_ALLOWED_PREFIXES = ("eq.", "dyn.", "dynxo.", "dynsc.", "dly.")
_BUS_EXCLUDED_EXACT = frozenset({
    "col", "name", "icon", "led", "mute", "fdr", "pan", "wid", "mon", "tags",
    "busmono",  # the bus's width: the plan decides it, never a preset
    "in.set.inv", "in.set.trim", "in.set.bal",  # gain stage, as on a channel
})
_BUS_EXCLUDED_PREFIXES = ("main.", "send.", "bus_feed.", "preins.", "postins.")
#: A bus's sidechain source: SELF, or another bus/Main/Matrix/aux.
_BUS_REFERENCE_FIELDS = frozenset({"dynsc.src"})
INSERT_POINT_NAMES = {"preins": "pre-insert", "postins": "post-insert"}


def classify_bus_leaf(path: str) -> str:
    """"in_scope", "excluded" or "unknown" for a bus preset's `ch_data` leaf."""
    if any(path.startswith(p) for p in _BUS_ALLOWED_PREFIXES):
        return "in_scope"
    if path in _BUS_EXCLUDED_EXACT or any(path.startswith(p) for p in _BUS_EXCLUDED_PREFIXES):
        return "excluded"
    return "unknown"


@dataclass(frozen=True)
class PresetInsert:
    """The effect a bus preset inserts: at `point` (`preins`/`postins`),
    `model` with its `parameters`, saved from engine `saved_engine`
    (None when the file names none), switched on or bypassed (`saved_on`)."""

    point: str
    model: str | None
    parameters: dict[str, Any]
    saved_engine: int | None
    saved_on: bool


@dataclass(frozen=True)
class BusPreset:
    """One bus preset, loaded from a WING `.bus` export: the bus's own
    processing (`parameters`, the bus allow-list, flat dotted paths like a
    `ChannelPreset`'s) and the effect(s) it inserts (`inserts`)."""

    name: str
    source_path: Path
    creator_fw: str
    creator_model: str
    created: str
    source_channel: int | None
    parameters: dict[str, Any]
    inserts: tuple[PresetInsert, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _engine_number(value: object) -> int | None:
    if isinstance(value, str) and value.upper().startswith("FX"):
        try:
            n = int(value[2:])
        except ValueError:
            return None
        return n if n >= 1 else None
    return None


def load_bus_preset(path: str | Path) -> BusPreset:
    """Load and validate one `.bus` file. Raises PresetError for anything
    that is not a WING bus preset in the shape this module understands."""
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PresetError(f"{path}: could not read preset file ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise PresetError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(doc, dict):
        raise PresetError(f"{path}: expected a JSON object at the top level")
    doc_type = doc.get("type")
    if not isinstance(doc_type, str) or not doc_type.startswith("chpreset"):
        raise PresetError(f"{path}: expected a WING preset (type starting with 'chpreset'), "
                          f"got {doc_type!r}")
    ch_data = doc.get("ch_data")
    if not isinstance(ch_data, dict):
        raise PresetError(f"{path}: missing or malformed 'ch_data'")

    parameters: dict[str, Any] = {}
    warnings: list[str] = []
    for leaf_path, value in _flatten(ch_data).items():
        kind = classify_bus_leaf(leaf_path)
        if kind == "in_scope":
            if leaf_path in _BUS_REFERENCE_FIELDS and value != "SELF":
                warnings.append(
                    f"{leaf_path} references {value!r} instead of SELF -- not portable across "
                    "busses/shows, dropped rather than silently rewiring a sidechain")
                continue
            parameters[leaf_path] = value
        elif kind == "unknown":
            warnings.append(
                f"{leaf_path}={value!r} is not on the bus processing allow-list and not "
                "recognized as a deliberately excluded field")

    target_fx = doc.get("target_fx")
    if not isinstance(target_fx, list):
        target_fx = []
    inserts: list[PresetInsert] = []
    for position, point in enumerate(("preins", "postins")):
        node = ch_data.get(point) if isinstance(ch_data.get(point), dict) else {}
        data = doc.get(f"{point}_data")
        named = _engine_number(node.get("ins"))
        if not isinstance(data, dict):
            if named is not None:
                warnings.append(
                    f"{point}.ins names FX{named}, but the file carries no {point}_data -- no "
                    "effect to load, so this insert is not set")
            continue
        saved = named
        if saved is None and position < len(target_fx):
            t = target_fx[position]
            saved = t if isinstance(t, int) and not isinstance(t, bool) and t >= 1 else None
        model = data.get("mdl")
        inserts.append(PresetInsert(
            point=point,
            model=model if isinstance(model, str) else None,
            parameters={k: v for k, v in data.items() if k != "mdl"},
            saved_engine=saved,
            saved_on=bool(node.get("on")),
        ))

    name = doc.get("info_text")
    if not isinstance(name, str) or not name:
        name = path.stem
    source_channel = doc.get("source_channel")
    if not isinstance(source_channel, int):
        source_channel = None
    return BusPreset(
        name=name, source_path=path,
        creator_fw=str(doc.get("creator_fw", "")),
        creator_model=str(doc.get("creator_model", "")),
        created=str(doc.get("created", "")),
        source_channel=source_channel,
        parameters=parameters, inserts=tuple(inserts), warnings=tuple(warnings),
    )


def normalize_preset_name(name: str) -> str:
    """The form two preset names are compared in.

    Case-insensitive, and `-`, `_` and any run of whitespace all collapse
    to one space: `"Lead Vocal"`, `"lead_vocal"` and `"LEAD-VOCAL"` are
    one name. Deliberately does NOT strip other punctuation -- "Kick
    In" and "Kick (In)" stay different, because guessing further
    starts merging presets an engineer meant to keep apart.
    """
    return re.sub(r"[-_\s]+", " ", name).strip().lower()


@dataclass(frozen=True)
class PresetLibrary:
    """Atoo's own preset library -- a directory of `.chn` files,
    looked up by name (the same `info_text` a `ChannelPreset` exposes as
    `.name`, e.g. "Kick In"), not by the console's scene/tag mechanism,
    since that mechanism can't be driven remotely at all (see this
    module's docstring). Lookup is case-insensitive since engineers won't
    reliably match a preset's saved capitalization from memory."""

    directory: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", Path(self.directory))

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            raise PresetError(f"{self.directory}: not a directory")
        return sorted(self.directory.glob("*.chn"))

    def names(self) -> list[str]:
        """Every preset name in the library, loading each file to do it --
        a `.chn`'s name lives in `info_text`, not in the filename, so
        listing names honestly requires opening every file rather than
        just listing a directory."""
        return [preset.name for preset in self]

    def matches(self, name: str) -> list[ChannelPreset]:
        """Every preset whose name normalizes to `name`'s, **newest
        first**.

        Forgiving matching (the maintainer, 2026-09-20): case, and
        `-`/`_`/whitespace, are all treated alike, so a conventions file
        saying *"Lead Vox uses the Lead Vocal preset"* finds
        `lead_vocal.chn`. An engineer is writing prose, not a filename,
        and will not reliably reproduce a preset's saved punctuation.

        Ordering is by file modification time, which is what makes
        `get`'s "pick the newest" meaningful. Worth knowing: mtime is not
        preserved by `git clone`, so in a fresh checkout of a library kept
        in git the order is arbitrary. That only decides between two
        presets that already share a name, which is the case this reports
        on anyway.
        """
        target = normalize_preset_name(name)
        found = [p for p in self if normalize_preset_name(p.name) == target]
        return sorted(found, key=lambda p: p.source_path.stat().st_mtime, reverse=True)

    def get(self, name: str) -> ChannelPreset:
        """The preset called `name`, matched forgivingly.

        Raises `PresetError` (never returns None) when nothing matches.
        When *several* do, the newest wins rather than raising -- the maintainer,
        2026-09-20: "Two files naming the same name is a Warning, pick the
        newest one." That reverses this method's original posture, on the
        grounds that a duplicate is a library-hygiene problem and should
        not stop a show being built. Callers that want to *report* the
        ambiguity ask `matches()` for the full list; `verify_plan` does.
        """
        found = self.matches(name)
        if not found:
            raise PresetError(f"no preset named {name!r} in {self.directory}")
        return found[0]

    def __iter__(self):
        for file_path in self._files():
            yield load_preset(file_path)

    # -- bus presets (`.bus`): a name space of their own, so a
    # bus preset called "Vocal" never answers for the channel preset.

    def bus_presets(self) -> list[BusPreset]:
        if not self.directory.is_dir():
            raise PresetError(f"{self.directory}: not a directory")
        return [load_bus_preset(p) for p in sorted(self.directory.glob("*.bus"))]

    def bus_matches(self, name: str) -> list[BusPreset]:
        """Every bus preset whose name normalizes to `name`'s, newest first
        -- the same forgiving match, and the same order, as `matches`."""
        target = normalize_preset_name(name)
        found = [p for p in self.bus_presets() if normalize_preset_name(p.name) == target]
        return sorted(found, key=lambda p: p.source_path.stat().st_mtime, reverse=True)

    def bus_get(self, name: str) -> BusPreset:
        found = self.bus_matches(name)
        if not found:
            raise PresetError(f"no bus preset named {name!r} in {self.directory}")
        return found[0]
