"""The generated-plan contract, defined once.

Three consumers, one definition, so they cannot disagree:

  1. the generator prompt, which states the rules in words
  2. Anthropic's `output_config.format`, which constrains decoding
  3. Ollama's `format`, which does the same via a llama.cpp grammar

Before this, the prompt carried an illustrative example with `//` comments
-- which is not valid JSON. We were showing a model an unparseable
document as the template for its parseable output.

## What constrained decoding does and does not buy

It makes a schema-INVALID reply impossible: no missing brace, no `//`
comment, no `"channel": "one"`, no field the schema does not name. The
14B run that spent 85 minutes and produced an unparseable reply over a
single missing `}` could not have happened.

It does NOT make the plan correct. It cannot know that `AES50-A 1` means
group `A` rather than group `AES` -- both are valid strings. Every
semantic check still belongs to `verify_plan.py`, and every judgement
about whether this is the show the engineer asked for still belongs to
the engineer. A grammar buys syntax, nothing more, and treating it as a
correctness guarantee would be the same mistake as treating the
compiler's output as a standard.

It also has a cost worth knowing: forcing tokens to fit a grammar can
degrade the content within that grammar, and on a local model a large
grammar measurably slows generation. Hence `--no-constrain`.

## Deliberately loose in places

`provenance` values and `description` are free strings: they exist for a
human to read, and a grammar that constrained them would be constraining
prose. `dcas`/`mute_groups`/`busses`/`outputs` are open objects keyed by
name, because the names are the engineer's, not ours -- in the PLAN. The
REPLY the generator writes (`REPLY_SCHEMA`, further down) holds them as
arrays of named objects, which is what lets it be sent as a schema to
Anthropic's decoder at all (`reply_expand.py`). `notes` entries are
`{"text", "source"}` objects rather than bare strings so a
reader can tell which of Atoo's own processes wrote each one, but
`text` itself is exactly as loose as `provenance`/`description` -- still
free prose, just no longer anonymous prose.
"""

from __future__ import annotations

import copy

from atoo import console_facts as facts

_DB = {"type": ["number", "null"], "minimum": facts.MINUS_INF_DB, "maximum": 10.0}


def _eq_schema(strips: tuple[str, ...]) -> dict:
    """The `processing.eq` object for one family of strip classes.

    `strips` is every console strip class this one
    schema has to cover at once -- ("ch", "aux") for a channel, ("bus",)
    for a bus, ("main", "mtx") for an output -- because the plan's own
    shape does not split them: one CHANNEL_SCHEMA serves both banks.

    Where those classes AGREE (band count for ch/aux, everything for
    main/mtx), the bound below is exact. Where they differ -- a channel's
    shelf takes only PEQ/SHV while an aux's also takes CUT, a channel's
    `eq.mdl` has MACH4 where an aux has neither MACH4 nor PIA -- this
    takes the UNION, and `verify_plan.py` makes the exact per-bank call,
    because only it knows which bank a given channel is on. The union is
    the honest bound for a schema that cannot see the bank; it is not the
    last word, and it is not where a wrong value gets caught.
    """
    band_ids = sorted(
        {b for s in strips for b in facts.eq_band_ids(s)},
        key=lambda b: (0, 0) if b == "low" else (2, 0) if b == "high" else (1, int(b)),
    )
    shelf_types = sorted({t for s in strips for t in facts.EQ_SHELF_TYPES[s]})
    models = sorted({m for s in strips for m in facts.EQ_MODELS[s]})
    band = {
        "type": "object",
        "properties": {
            # Which band, not which order: "low"/"high" are the shelf
            # bands (`eq.lf`/`eq.hf`), the numbers are the parametric
            # ones between them. Named rather than positional so a plan
            # that states one band states only that band -- an array
            # index would force four nulls to reach band 5.
            "band": {"type": "string", "enum": band_ids},
            "freq_hz": {"type": ["number", "null"],
                        "minimum": facts.EQ_FREQ_HZ_RANGE[0], "maximum": facts.EQ_FREQ_HZ_RANGE[1]},
            "gain_db": {"type": ["number", "null"],
                        "minimum": facts.EQ_GAIN_DB_RANGE[0], "maximum": facts.EQ_GAIN_DB_RANGE[1]},
            "q": {"type": ["number", "null"],
                  "minimum": facts.EQ_Q_RANGE[0], "maximum": facts.EQ_Q_RANGE[1]},
            # `eq.leq`/`eq.heq`, and ONLY on the two shelf bands -- a
            # parametric band has no filter-type leaf at all. Not
            # expressible here (the constraint is on a sibling key's
            # value), so verify_plan.py owns it and apply.py refuses to
            # write it.
            "shape": {"type": ["string", "null"], "enum": [*shelf_types, None]},
        },
        "required": ["band"],
        "additionalProperties": False,
    }
    return {
        "type": ["object", "null"],
        "properties": {
            # null, not false, for "the conventions never said": the
            # console's own EQ-on state is left alone then. Stating any
            # band implies on (apply.py writes `eq.on` = 1), the same
            # precedent `hpf_hz` set with `flt.lc`.
            "on": {"type": ["boolean", "null"]},
            "model": {"type": ["string", "null"], "enum": [*models, None]},
            # The wet/dry blend (`eq.mix`), uniform on every strip class.
            # Distinct from `on`: 0% keeps the curve and takes it out of
            # circuit, `on: false` bypasses the whole node.
            "mix_pct": {"type": ["number", "null"],
                        "minimum": facts.EQ_MIX_PCT_RANGE[0], "maximum": facts.EQ_MIX_PCT_RANGE[1]},
            "bands": {"type": "array", "items": band},
        },
        "additionalProperties": False,
    }


def _presend_eq_schema() -> dict:
    """`processing.presend_eq` -- a channel's SECOND EQ.

    `ch.{n}.peq`, WING's "PreSend EQ": three bells and an on switch at a
    different tap point in the strip. Deliberately not `_eq_schema` with
    a different band list, because it is not the same control with fewer
    bands -- it has no shelf bands, so no filter type, and no `mdl`,
    `mix` or `tilt` either. Modelling it as a variant of the main EQ
    would invite exactly the "surely it has a low band too" assumption
    this issue's whole band-count lesson is against.

    Channel-only: an aux strip has no `peq` node, the same way it has no
    `flt` node. apply.py holds that guard, because only it knows the bank.
    """
    band = {
        "type": "object",
        "properties": {
            "band": {"type": "string", "enum": list(facts.presend_eq_band_ids("ch"))},
            "freq_hz": {"type": ["number", "null"],
                        "minimum": facts.EQ_FREQ_HZ_RANGE[0], "maximum": facts.EQ_FREQ_HZ_RANGE[1]},
            "gain_db": {"type": ["number", "null"],
                        "minimum": facts.EQ_GAIN_DB_RANGE[0], "maximum": facts.EQ_GAIN_DB_RANGE[1]},
            "q": {"type": ["number", "null"],
                  "minimum": facts.EQ_Q_RANGE[0], "maximum": facts.EQ_Q_RANGE[1]},
        },
        "required": ["band"],
        "additionalProperties": False,
    }
    return {
        "type": ["object", "null"],
        "properties": {
            "on": {"type": ["boolean", "null"]},
            "bands": {"type": "array", "items": band},
        },
        "additionalProperties": False,
    }


# A resolved preset value: an on/off or a whole number, a knob, or a list
# choice -- already in the type the desk takes (preset_expand.LEAF_TYPES).
_PRESET_LEAF_VALUE = {"type": ["number", "string"]}


def _preset_values_schema() -> dict:
    """`processing.preset_values`. The design was settled on
    2026-09-21: `build` expands a named preset INTO the plan, so
    the plan says exactly what will be written.

    Optional and additive, like every processing field: a plan
    without it is an older plan (or one built with no library) and stays
    valid. `leaves` is keyed by address, which is what makes "one value per
    address" a property of the format rather than of the code: a dict
    cannot hold `eq/1g` twice. The compressor and gate are carried here
    WITHOUT a typed field each -- that was the point of the design.

    Deliberately NOT described to the generator (`schema_section()`): the
    values come from a file the model never sees, and `build` recomputes
    this key for every channel after generation, discarding anything a
    model put there.
    """
    # Keyed by the address under the strip (`eq/1g`, `in/set/dly`). The
    # keys are not constrained here -- the validator has no `pattern` -- and
    # need not be: verify and apply refuse any address off the processing
    # allow-list (`preset_expand.leaf_refusal`), whoever wrote it.
    leaf_map = {"type": "object", "additionalProperties": _PRESET_LEAF_VALUE}
    return {
        "type": "object",
        "properties": {
            "preset": {"type": "string", "minLength": 1},
            "file": {"type": ["string", "null"]},
            "library": {"type": ["string", "null"]},
            "sha256": {"type": ["string", "null"]},
            "leaves": leaf_map,
            "overridden": leaf_map,
        },
        "required": ["preset", "leaves"],
        "additionalProperties": False,
    }


# A bus/Main/Matrix's own processing. These
# strips had no `processing` field AT ALL -- a bus's EQ and compressor had
# nowhere to go but the plan's free-text `notes`. Phase 2a gives them the
# EQ half. The compressor half stays in `notes` on purpose: its ranges move
# with `dyn.mdl` across 32 models, so it needs a decision before a schema.
def _strip_processing_schema(strips: tuple[str, ...]) -> dict:
    props = {"eq": _eq_schema(strips)}
    if all(s in facts.EQ_TILT_STRIPS for s in strips):
        # `{strip}.{n}.eq.tilt`, which is a DIFFERENT node from a
        # channel's `ch.{n}.flt.tilt` even though the numbers match -- and
        # an aux strip has neither. Same field name as a channel's
        # `processing.tilt_db` because it is the same control to whoever
        # writes the plan; where it lands on the wire is apply.py's problem.
        props["tilt_db"] = {"type": ["number", "null"],
                            "minimum": facts.TILT_DB_RANGE[0], "maximum": facts.TILT_DB_RANGE[1]}
    return {
        "type": ["object", "null"],
        "properties": props,
        "additionalProperties": False,
    }

# An error of judgement is not an error of patching: a value
# the conventions never stated, but that the board cannot be left without,
# is DECIDED -- from the conventions first, then domain knowledge and
# naming -- and the decision announces itself. This is how it announces
# itself in the plan: an `inferred` list on the object that holds the
# value, one entry per field that was decided rather than stated.
#
# Deliberately narrow. Only the fields below may carry a marker, because
# only these leave the desk undecided -- or the plan blocked -- when null.
# Every other nullable field (hpf, eq, fader, colour, ...) keeps rule 4:
# null means "not stated", and apply leaves the desk's own value alone,
# which is a working board. `atoo/inferred.py`'s docstring has the
# field-by-field audit behind this list.
#
#   field   which value on this object was decided
#   basis   what it was decided FROM, in words the engineer can check
#           against their conventions -- never just "domain knowledge"
#   by      "model" (the generator decided it) or "fallback" (Atoo's
#           own deterministic rule filled a value the plan left null).
#           Optional: absent means "model", and generate.py fills it in.
INFERABLE_FIELDS = {
    "bus": ("mono", "destination"),
    "channel": ("stereo",),
    "send": ("mode",),
}
INFERRED_BY = ("model", "fallback")

# Values Atoo's own index allocation fills when a plan leaves them
# out, and marks `by: "fallback"` so the choice announces itself like any
# other (`allocate.allocate_console_indices`). Not rule-4b fields -- the
# model is never asked to decide them (D11: numbering is code's job) --
# but the same marker, so one INFO path reports both. Only an output's
# `index` is here: it says WHICH Main or Matrix strip the entry is, and a
# Matrix's `fed_by: {type: main, index: N}` is matched against it. A bus's,
# DCA's or mute group's index is declaration-order bookkeeping that the
# model is never asked for and nothing in a generated plan refers to by
# number, so marking it would only add noise.
#
# A bus's `destination.index` when its destination is a Main (review
# 2026-09-28, R6) is the one exception on the bus side: "routes to main"
# with no number is resolved to a Main the plan carries, and which of up
# to four Mains a monitor or FX bus is summed into is a choice that must
# announce itself (`inferred.bus-main-index`).
#
# A send's `level_db` (2026-09-29) is filled the same way: a listed send
# with no level is written at unity by Atoo's fallback, never left
# null, because apply writes no level for null and a fresh desk's -144
# leaves the send on and silent (`inferred.send-level`). The model may
# also mark a level it decided rather than read.
ALLOCATED_FIELDS = {
    "output": ("index",),
    "bus": ("destination.index",),
    "send": ("level_db",),
}


def markable_fields(kind: str) -> tuple[str, ...]:
    """Every field an `inferred` marker on a `kind` object may name."""
    return INFERABLE_FIELDS.get(kind, ()) + ALLOCATED_FIELDS.get(kind, ())


def _inferred_schema(kind: str) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "enum": list(markable_fields(kind))},
                "basis": {"type": "string", "minLength": 1},
                "by": {"type": "string", "enum": list(INFERRED_BY)},
            },
            "required": ["field", "basis"],
            "additionalProperties": False,
        },
    }


# Only ever used for a bus/output DESTINATION's patch (_DESTINATION.patch,
# outputs.*.patch and the `patches` fan-out below; `socket`/`sockets`
# still read by plan_compat) -- never for a channel's
# `patch`, which has the same shape but its
# own separate group/sockets/stated block keyed off INPUT_SOCKETS,
# further down. This used to be named _SOCKET and keyed off INPUT_SOCKETS
# regardless, which was wrong here: OUTPUT_SOCKETS is a different table
# (it has "REC", a recorder tap, that no input has; it lacks
# "PLAY"/"OSC"/"USR", which only exist as inputs) -- see console_facts.py.
# A plan naming a real output group "REC" was wrongly rejected, and one
# naming an input-only group for an output socket was wrongly accepted.
_OUTPUT_PATCH = {
    "type": "object",
    "properties": {
        "group": {"type": "string", "enum": sorted(facts.OUTPUT_SOCKETS)},
        "sockets": {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1},
        # Optional, not required: a channel's `patch` (below) has the same
        # group/sockets shape plus a REQUIRED `stated`, and the one worked
        # example in the prompt is a channel's patch -- so an unconstrained
        # model reliably generalizes `stated` onto every socket it writes,
        # bus/output destinations included. That is a sensible
        # generalization of a real distinction ("did the source state
        # this, or did I choose it"), not a hallucination, so the schema
        # accepts it here rather than rejecting a field the model had good
        # reason to add.
        "stated": {"type": "boolean"},
    },
    "required": ["group", "sockets"],
    "additionalProperties": False,
}

CHANNEL_SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {"type": "integer", "minimum": 1, "maximum": facts.CAPACITY["ch"]},
        "bank": {"type": "string", "enum": ["ch", "aux"]},
        # The console truncates at 16 characters, so a longer name is not
        # what the operator will see -- enforced here rather than hoped for.
        "name": {"type": "string", "minLength": 1, "maxLength": facts.NAME_MAX_CHARS},
        # A human/UI-readable fact, same category as `description` and
        # `provenance` below -- still not a console write. The OSC address
        # for a channel-strip colour IS confirmed now (`ch.{n}.col`, see `col` below), but this text field ("Red", "Blue", ...)
        # and that numeric palette index are two different things: WING's
        # `col` is an int [1..18] with no confirmed name-to-index mapping
        # anywhere in this project's hardware notes. Cross-referencing a
        # real show's `col` values against this field's own conventions-
        # derived labels (the touringband plan.json vs its .snap) was
        # tried and came back inconclusive -- the same label ("Red") maps
        # to different `col` values across channels, meaning those numbers
        # predate this plan and were never derived from this field at all.
        # Writing `color` straight to `col` would mean guessing the
        # palette order, exactly the guess this codebase refuses to make
        # elsewhere -- so this stays UI-only until someone
        # confirms the real mapping against a live console. Optional, not
        # required: a compiled plan (compiler.py never parses "Color
        # coding: ..." rules) is still valid without it.
        "color": {"type": ["string", "null"]},
        # The actual numeric console values -- confirmed OSC
        # addresses (`ch.{n}.col` int [1..18], `ch.{n}.icon` int [0..999]),
        # unlike `color` above. Distinct field, not a replacement: nothing
        # in this codebase can populate these from conventions text yet
        # (no confirmed palette-name mapping, see `color`'s comment), so
        # they're only ever set by hand-editing a plan or a future
        # AI-generate run a human explicitly gives real numbers to. null
        # means unstated, same "leave the console alone" policy as every
        # other optional field.
        "col": {"type": ["integer", "null"], "minimum": 1, "maximum": 18},
        "icon": {"type": ["integer", "null"], "minimum": 0, "maximum": 999},
        "source": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "minLength": 1},
                # Null is allowed (2026-09-25): an input list row with no
                # model, or no type, is common, and the generator's rule 4
                # says an unstated value is null. A strict string here
                # rejected a whole festival build over 23 blank model
                # cells. Nothing downstream needs them: verify's ribbon
                # check falls back to the input list, render skips them.
                "type": {"type": ["string", "null"]},
                "model": {"type": ["string", "null"]},
                "stereo": {"type": "boolean"},
                "phantom": {"type": "boolean"},
                # A stereo channel's SECOND input-list row, by name
                # (2026-09-29). `input` names the first; a compact reply
                # pairs two rows (`pair`) and the expander writes the
                # second here. Without it, a pair whose rows state no
                # socket had its second row read as dropped by verify,
                # which otherwise finds that row only by its stated
                # socket. Optional: a plan without it reconciles as before.
                "pair_input": {"type": "string", "minLength": 1},
                # That second row's own phantom. Phantom lives
                # on each SOCKET, and a pair of one condenser and one
                # dynamic needs it on one only, so the second socket takes
                # this rather than `phantom`. Absent where the plan states
                # one value for the pair (a single stereo row, a channel
                # from the instructions): then `phantom` is read as both
                # sockets' (`inferred.socket_phantom`), announced at INFO.
                "pair_phantom": {"type": "boolean"},
                # A channel the conventions or instructions ask for that is
                # not a row of the input list
                # (`instructed_channels.py`): which of the two asked, and the
                # sentence that did, verbatim. Absent on every channel that
                # IS a row -- so every plan before this reads unchanged.
                # verify checks the quote is really there and reports the
                # channel (`reconcile.from-instructions`, INFO or WARNING).
                "from": {"type": "string", "enum": ["conventions", "instructions"]},
                "quote": {"type": "string", "minLength": 1},
                # The text's condition on the strip's socket, verbatim, when
                # it has one ("if available"; 2026-10-01). With `patch:
                # null` it says why the strip is unpatched: the stated
                # socket was taken, and the text asked for it only if free.
                "condition": {"type": "string", "minLength": 1},
            },
            "required": ["input", "stereo", "phantom"],
            "additionalProperties": False,
        },
        # Null only on a strip the conventions ask for "if available" whose
        # socket was not (2026-10-01, `instructed_channels.py`): the strip
        # is built, unpatched. verify refuses a null patch anywhere else
        # (`patch.missing`).
        "patch": {
            "type": ["object", "null"],
            "properties": {
                "group": {"type": "string", "enum": sorted(facts.INPUT_SOCKETS)},
                "sockets": {"type": "array", "items": {"type": "integer", "minimum": 1},
                            "minItems": 1, "maxItems": 2},
                "stated": {"type": "boolean"},
            },
            "required": ["group", "sockets", "stated"],
            "additionalProperties": False,
        },
        # The ALTERNATE input patch -- the second
        # patch every WING strip carries (`in/conn/altgrp`/`.altin`), which
        # the desk switches to per strip (`in/set/altsrc`) or globally.
        # Virtual soundcheck is its ordinary use: WING LIVE plays last
        # night's tracks back as `CRD n`. The same shape as `patch`, set
        # ONLY when the conventions, instructions or input list state an
        # alternate; null or absent means none was stated, and apply leaves
        # the desk's alternate alone. `stated` is true when they gave the
        # socket numbers, false when code counted them (the alternate
        # itself is always stated). Never invented: an unset alternate
        # breaks nothing -- the strip works on its main input.
        "alt_patch": {"oneOf": [{
            "type": "object",
            "properties": {
                "group": {"type": "string", "enum": sorted(facts.INPUT_SOCKETS)},
                "sockets": {"type": "array", "items": {"type": "integer", "minimum": 1},
                            "minItems": 1, "maxItems": 2},
                "stated": {"type": "boolean"},
            },
            "required": ["group", "sockets", "stated"],
            "additionalProperties": False,
        }, {"type": "null"}]},
        "processing": {
            "type": "object",
            "properties": {
                "hpf_hz": {"type": ["number", "null"],
                           "minimum": facts.HPF_HZ_RANGE[0], "maximum": facts.HPF_HZ_RANGE[1]},
                "preset": {"type": ["string", "null"]},
                # Filters (hi-cut, tilt), trim, balance,
                # invert, head-amp gain -- representable and writable
                # (apply.py). The remaining gap was closed on 2026-09-17
                #  by teaching the deterministic
                # `--strategy compile` parser to produce all six from a
                # conventions file's "## Processing" section; that parser and its
                # module were then retired entirely, so today the
                # only thing that produces these from conventions text is
                # the model, working from schema_section()'s prose below --
                # which is why that prose is the load-bearing half of this
                # block and not a restatement of it. Optional, NOT added to
                # `required` below, on purpose: `processing` has
                # additionalProperties: False and hpf_hz/preset are both
                # required-but-nullable today, so making these six required
                # too would break every existing plan.json (every show
                # bundle, every test fixture) that predates this field
                # for omitting it -- a huge, unwanted blast radius for what
                # is meant to be a purely additive, backward-compatible
                # change. An old-style plan may omit these entirely; a new
                # one may state them or leave them null, exactly like
                # hpf_hz already works.
                "hi_cut_hz": {"type": ["number", "null"],
                              "minimum": facts.HI_CUT_HZ_RANGE[0], "maximum": facts.HI_CUT_HZ_RANGE[1]},
                "tilt_db": {"type": ["number", "null"],
                            "minimum": facts.TILT_DB_RANGE[0], "maximum": facts.TILT_DB_RANGE[1]},
                "trim_db": {"type": ["number", "null"],
                            "minimum": facts.TRIM_DB_RANGE[0], "maximum": facts.TRIM_DB_RANGE[1]},
                "balance_db": {"type": ["number", "null"],
                               "minimum": facts.BALANCE_DB_RANGE[0], "maximum": facts.BALANCE_DB_RANGE[1]},
                "invert": {"type": ["boolean", "null"]},
                # Not `{base}`-relative like the rest of `processing` --
                # the head amp lives on the physical input SOCKET a channel
                # is patched to (`/io/in/{group}/{socket}/g`), same as
                # phantom power -- see apply.py's `_channel_write_targets`.
                # Modeled here anyway (rather than under `source`/`patch`)
                # because it's a processing-style value an engineer states
                # per-channel, exactly like hpf_hz -- where it lands on the
                # wire is an apply-time concern, not a plan-shape one.
                "gain_db": {"type": ["number", "null"],
                            "minimum": facts.HEAD_AMP_GAIN_DB_RANGE[0],
                            "maximum": facts.HEAD_AMP_GAIN_DB_RANGE[1]},
                # Optional and additive for exactly
                # the reason the six above are -- an older plan omits it
                # and stays valid. ch and aux share this one schema, so
                # the band list is the two banks' (identical) four-band
                # one and the enums are their union; see _eq_schema.
                "eq": _eq_schema(("ch", "aux")),
                # The channel's OTHER EQ. `presets.py` already allow-lists
                # `peq.` under the EQ scope, so a `.chn` export carries
                # one -- without this field, a plan could name a preset
                # whose PreSend EQ it has no way to state or show.
                "presend_eq": _presend_eq_schema(),
                # `preset_values` is NOT here: it is
                # added to PLAN_CHANNEL_SCHEMA below, the shape a plan on
                # disk may take, and kept out of this one, the shape a
                # model is asked to produce. See _preset_values_schema.
            },
            "required": ["hpf_hz", "preset"],
            "additionalProperties": False,
        },
        "fader": {
            "type": "object",
            "properties": {"fader_db": _DB, "muted": {"type": ["boolean", "null"]}},
            "required": ["fader_db", "muted"],
            "additionalProperties": False,
        },
        "dca": {"type": "array", "items": {"type": "string"}},
        "mute_group": {"type": "array", "items": {"type": "string"}},
        "bus_sends": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bus": {"type": "string", "minLength": 1},
                    # Nullable, for plans written before 2026-09-25 (the
                    # retired compiler left it unset rather than guessing).
                    # Pre vs post is a judgement call, not a patching fact:
                    # a wrong choice displeases at soundcheck,
                    # a null one used to BLOCK the plan as
                    # value.send-mode-unknown. So the generator now decides
                    # it and marks the send's `inferred`; a plan that still
                    # arrives null is filled by `inferred.decide_unstated()`
                    # (pre into a bus that only feeds a physical output --
                    # a monitor send -- post otherwise) with an INFO.
                    "mode": {"type": ["string", "null"], "enum": [*facts.PLAN_SEND_MODES, None]},
                    "level_db": _DB,
                    # Optional: see INFERABLE_FIELDS. A send's `mode` when
                    # the conventions never said pre or post for it.
                    "inferred": _inferred_schema("send"),
                },
                "required": ["bus", "mode", "level_db"],
                "additionalProperties": False,
            },
        },
        "main_routes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer", "minimum": 1,
                                         "maximum": facts.CAPACITY["main"]}},
                "required": ["index"],
                "additionalProperties": False,
            },
        },
        "provenance": {"type": "object"},   # free-form: it is prose for a human
        # Optional: see INFERABLE_FIELDS. On a channel only `stereo` -- a
        # pairing made from the sources' names rather than a stated rule.
        "inferred": _inferred_schema("channel"),
    },
    "required": ["channel", "bank", "name", "source", "patch", "processing",
                 "fader", "dca", "mute_group", "bus_sends", "main_routes"],
    "additionalProperties": False,
}

_DESTINATION = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["main", "dedicated_output", "matrix"]},
        "index": {"type": "integer", "minimum": 1},
        "label": {"type": ["string", "null"]},
        "patch": {"oneOf": [_OUTPUT_PATCH, {"type": "null"}]},
        # A dedicated output can fan out to SEVERAL physical
        # sockets at once (TOURING_260821_MIX.snap's Main feeds USB
        # 47/48, CRD 31/32 AND REC 1/2 simultaneously) -- authoritative
        # when non-empty; `patch` above stays the first/primary one for
        # every caller that only wants the one.
        "patches": {"type": "array", "items": _OUTPUT_PATCH},
    },
    "required": ["type"],
    "additionalProperties": False,
}

_FADER = {
    "type": "object",
    "properties": {"fader_db": _DB, "muted": {"type": ["boolean", "null"]}},
    "additionalProperties": False,
}

# A DCA's own starting fader/mute, the same `fader` block a
# bus already has. A plan could not state one at all, which is why
# `CH002 DCA Fader Low With Active Members` had nothing to stand down
# against even on a desk set up exactly as its conventions describe --
# seven of the A5 run's surviving warnings were that.
#
# **Deliberately open**, unlike BUS_SCHEMA: no `"type": "object"` and no
# `additionalProperties: False`, so this constrains `fader` and `index`
# where they appear and rejects nothing that is valid today. `dcas` has
# been an unconstrained object since the beginning, and real plans on
# disk carry `provenance`, `description` and, in one archived generation,
# a bare list. Tightening that is a separate decision from adding a field.
DCA_SCHEMA = {
    "properties": {
        # Filled in by allocate.py, exactly as a bus's is.
        "index": {"type": "integer", "minimum": 1},
        "fader": _FADER,
    },
}

BUS_SCHEMA = {
    "type": "object",
    "properties": {
        "destination": {"oneOf": [_DESTINATION, {"type": "null"}]},
        # A bus can state BOTH a main route AND a
        # dedicated output at once (Festival_STANDALONE.snap's
        # VOCALS bus: bus.7.main.1.on=true, plus io.out.A.44/
        # io.out.SC.4 both sourcing from it) -- every
        # destination this bus actually has, authoritative
        # when non-empty; `destination` above always mirrors
        # entry 0 for every caller that only wants the one/
        # primary value.
        "destinations": {"type": "array", "items": _DESTINATION},
        # Filled in by allocate.py, not by whoever wrote the
        # plan: the console is number-based and the plan is
        # name-based, and bridging them is bookkeeping rather
        # than judgement.
        "index": {"type": "integer", "minimum": 1},
        "fader": _FADER,
        # A bus can itself be a DCA/mute-group member -- real
        # shows do this (confirmed against
        # Festival_STANDALONE.snap: its MONITORS mute group
        # holds busses, not channels). Same shape as a
        # channel's own `dca`/`mute_group`, same write path
        # (apply.py's `_merge_tags` onto `/bus/{n}/tags` --
        # `bus.{n}` carries a `tags` field exactly like
        # `ch.{n}` does). Optional: a compiled plan or an
        # older generated one has no bus-level membership and
        # is still valid.
        "dca": {"type": "array", "items": {"type": "string"}},
        "mute_group": {"type": "array", "items": {"type": "string"}},
        # A bus's own mono/stereo width -- confirmed OSC
        # address `/bus/{n}/busmono` (int [0..1]) in the parameter map.
        # Kept separate from a channel's own stereo/mono concept
        # (`_MODE_CAPABLE_GROUPS` in apply.py), which lives on the
        # physical input source, not a bus.
        #
        # Always DECIDED, never left to whatever the desk had. The width
        # decides what a dedicated output's physical jack carries, and the judgement-vs-patching rule says the
        # mono/stereo decision may not be left undecided. So: stated by the
        # conventions; else decided by the generator and marked in this
        # bus's `inferred`; else -- a plan that still arrives null, from
        # before this rule or by hand -- filled by
        # `inferred.decide_unstated()`'s fallback (one socket mono, a pair
        # stereo, no physical output the WING's factory stereo) with an
        # INFO. Schema-nullable only so those older plans stay valid.
        # Until 2026-09-25 a null here on a bus feeding a dedicated output
        # was the ERROR `bus.unstated-width-for-dedicated-output`, which
        # blocked the plan; the fallback retired it.
        #
        # THREE states, only two of which are a fact, and the
        # generator got the tri-state wrong in the one direction nobody
        # notices -- both shipped example plans came back null on busses
        # whose conventions said "these will all be MONO busses" and "These
        # are stereo busses" in the very bullet the plan's own `provenance`
        # quotes. See the prose below, which is what the model reads: the
        # old wording said only "state true when the conventions ask for a
        # mono bus", which gives a model no reason to ever write false and
        # reads as "otherwise leave it null".
        "mono": {"type": ["boolean", "null"]},
        # A bus colour stated in the conventions, by name -- the same field,
        # and the same resolution, as a channel's `color`: the model writes
        # one of the desk's eighteen names, `apply` maps it through
        # `console_facts.colour_index` and writes `/bus/{n}/col`, and a
        # name the desk does not have is verify's WARNING
        # `bus.colour-not-writable` and is left unwritten.
        #
        # A bus is coloured when the conventions say
        # so and stays uncoloured when they don't (state them in
        # conventions). So this is STATED or null, never decided -- it is
        # not in INFERABLE_FIELDS and never carries an `inferred` marker.
        # A per-type statement counts ("FX busses are purple"), and so
        # does "take their category's colour", which means the category
        # colour map the conventions give for channels.
        "color": {"type": ["string", "null"]},
        # Same numeric col/icon concept as CHANNEL_SCHEMA's
        # (`bus.{n}.col` int [1..18], `bus.{n}.icon` int [0..999], both
        # confirmed in the parameter map). `col` wins over `color` when
        # both are set, as on a channel; it is only ever set by hand, and
        # a plan from before `color` existed carries it alone.
        "col": {"type": ["integer", "null"], "minimum": 1, "maximum": 18},
        "icon": {"type": ["integer", "null"], "minimum": 0, "maximum": 999},
        # A bus's own EQ (and tilt), the gap this
        # issue was filed for. Six parametric bands, not a channel's four.
        "processing": _strip_processing_schema(("bus",)),
        # A BUS preset (`.bus`, saved on the desk) by its name
        # -- the bus's processing and the effect it inserts. Chosen by the
        # conventions ("FX busses get the bus preset of the same name"),
        # stated or null, never invented. `build` expands it into
        # `preset_values` (PLAN_BUS_SCHEMA), which a model never writes.
        "preset": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        # One sentence here, unlike a channel's per-field object.
        "provenance": {"type": ["string", "object", "null"]},
        # Optional: see INFERABLE_FIELDS -- `mono`, and `destination` when
        # a mix or FX bus is routed to a Main nobody named.
        "inferred": _inferred_schema("bus"),
    },
    "required": ["destination"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    # patch is NULLABLE on purpose. "Matrix: fed from Main" with
    # no stated destination is a real thing an engineer writes,
    # and the honest response is null plus a note -- not an
    # invented socket. verify_plan then refuses to apply it,
    # which is where that gap belongs.
    "properties": {
        "patch": {"oneOf": [_OUTPUT_PATCH, {"type": "null"}]},
        # A Main/Matrix can fan out to SEVERAL
        # physical sockets at once (TOURING_260821_MIX.
        # snap's Main feeds USB 47/48, CRD 31/32 AND REC 1/2
        # simultaneously) -- authoritative when non-empty;
        # `patch` above stays the first/primary one.
        "patches": {"type": "array", "items": _OUTPUT_PATCH},
        "description": {"type": ["string", "null"]},
        "kind": {"type": ["string", "null"], "enum": ["main", "matrix", None]},
        "index": {"type": "integer", "minimum": 1},
        "fader": _FADER,
        # What feeds a MATRIX output's input -- a
        # Main or a bus, confirmed against real hardware as a
        # SEND on that source (/main/{n}/send/MX{m}, /bus/{n}/
        # send/MX{m}), never a field on the matrix itself.
        # Meaningful only when kind is "matrix"; a "main"
        # output has no input concept of its own to state.
        "fed_by": {
            "type": ["object", "null"],
            "properties": {
                "type": {"type": "string", "enum": ["main", "bus"]},
                "index": {"type": "integer", "minimum": 1},
                "name": {"type": "string", "minLength": 1},
            },
            "required": ["type"],
            "additionalProperties": False,
        },
        # A Main's or a Matrix's own EQ (and tilt).
        # Both strip classes have the identical six-band node, so unlike a
        # channel's ch/aux pair there is nothing to take a union over.
        "processing": _strip_processing_schema(("main", "mtx")),
        "provenance": {"type": ["string", "object", "null"]},
        # Optional: the same marker a bus or channel carries, for `index`
        # only (ALLOCATED_FIELDS) -- allocation fills a Main/Matrix index
        # the plan left out and says so. A marker a model wrote for some
        # other field (Haiku 4.5 put `destination` on a Main, 2026-09-28)
        # is dropped before validation with a repair note
        # (`inferred.drop_unmarkable`) rather than failing the build.
        "inferred": _inferred_schema("output"),
    },
    "additionalProperties": False,
}

# A bare string in `notes` gave a reader no way to tell "the
# model flagged a genuine gap in the conventions" apart from "conventions
# extraction couldn't place this line" apart from "Atoo's own repair
# step patched a truncated JSON reply" apart from "allocate.py recorded an
# index decision" -- four unrelated authors merged into one flat list,
# with very different reactions warranted for each. Every `notes` entry is
# now one of these, tagged with which wrote it.
# "capture": what `atoo capture` decided or could not hold
# when it wrote a plan from a desk. "sheets": what a Save in Build's step 04
# decided when it carried a sheet's cells into the plan (`atoo/sheets.py`).
NOTE_SOURCES = ("model", "extraction", "repair", "allocation", "capture", "sheets")

NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1},
        "source": {"type": "string", "enum": list(NOTE_SOURCES)},
    },
    "required": ["text", "source"],
    "additionalProperties": False,
}


# One entry of the plan's top-level `conventions_audit` (FR-6.2).
#
#   kind      "conflict" -- two statements set the same thing differently
#             and nothing settles it (instructions overriding the house
#             conventions is the design, and is NOT a conflict);
#             "unused" -- something declared (a DCA, a mute group, a bus)
#             that nothing in this show ends up joining.
#   quotes    the lines it is about, copied VERBATIM from the conventions
#             or instructions -- code checks each one is really there.
#   message   which statement the plan followed, or what is left empty.
CONVENTIONS_AUDIT_KINDS = ("conflict", "unused")

CONVENTIONS_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(CONVENTIONS_AUDIT_KINDS)},
        "quotes": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "message": {"type": "string", "minLength": 1},
    },
    "required": ["kind", "quotes", "message"],
    "additionalProperties": False,
}


def note_text(note: dict | str) -> str:
    """A `notes` entry's plain text, tagged ({"text", "source"})
    or not. The "not" branch covers a plan built before this change and
    any bare string a consumer hands in by mistake -- never raises on
    either."""
    return note.get("text", "") if isinstance(note, dict) else str(note)


def note_line(note: dict | str) -> str:
    """Same text, prefixed with its `source` tag when the entry carries
    one -- e.g. "[model] ...". Human-facing output (cli.py, render.py,
    report.py) uses this rather than the bare text, since telling these
    apart is the entire point: a flat, unprefixed line reads
    exactly as ambiguous as the one bare-string array it replaces."""
    if isinstance(note, dict) and "source" in note:
        return f"[{note['source']}] {note_text(note)}"
    return note_text(note)


# One entry of the plan's `user_sources` -- one slot of WING's `USR` input
# group, defined by this plan rather than assumed to exist on the desk.
#
#
# ## What this is for
#
# A stereo pair on a WING is two consecutive sockets starting on an odd one
# (`console_facts.STEREO_PAIR_RULE`, confirmed at the desk 2026-09-21). A
# show whose two halves are neither adjacent nor in the same group -- the
# protocol PDF's own example is WLIVE PLAY 1 and WLIVE PLAY 33 -- could not
# be planned here at all: `patch` is a group plus socket numbers, and there
# was no way to say "left comes from X, right from Y".
#
# The desk's answer is its `USR` group: 56 virtual source slots, each with
# its own source assignment (`console_facts.USER_SIGNAL_SLOTS` carries the
# measurements). Two consecutive slots, odd first, each pointed wherever you
# like, and the channel patches the pair exactly as it would patch two
# adjacent XLRs. This section is how a plan says what those slots are.
#
# ## Why `slot`, and not "USER PATCH 3"
#
# A plan already patches by console numbering -- `{"group": "USR",
# "sockets": [25, 26]}` is the address a channel uses, and it is the USR
# slot number. Per-kind numbering ("USER PATCH 3") would need a plan to know
# that USER PATCH 3 is USR 27: one more mapping to get wrong, for a name the
# plan never uses again. Which KIND a slot is follows from its number and is
# never stated -- 1..24 user signals, 25..56 user patches.
#
# ## What the schema cannot say here
#
# The source `group` enum below is the UNION of the two kinds' -- a channel
# bank (CH/AUX/BUS/MAIN/MTX) for a user signal, a socket group
# (LCL/A/B/C/...) for a user patch -- because a JSON Schema cannot see which
# slot an entry is for, exactly as `_eq_schema` cannot see which bank a
# channel is on. `verify_plan` makes the per-slot call, bounds the index by
# the real object count, and rejects `tap`/`leg` on a user patch, which has
# neither leaf. Note `AUX` is in both halves of that union and means two
# different things: the 8 aux STRIPS on a user signal, the 1/4" aux JACKS on
# a user patch.
USER_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        # Which USR slot this defines -- the same number a channel's `patch`
        # names in group "USR".
        "slot": {"type": "integer", "minimum": 1,
                 "maximum": facts.INPUT_SOCKETS["USR"]},
        # `/io/in/USR/{n}.name`, the slot's own display name. Optional and
        # nullable: naming it is a courtesy to whoever opens the ROUTING
        # screen, not part of the routing.
        "name": {"type": ["string", "null"], "maxLength": facts.NAME_MAX_CHARS},
        "source": {
            "type": "object",
            "properties": {
                "group": {"type": "string",
                          "enum": list(facts.USER_SOURCE_GROUPS)},
                # `/io/in/USR/{n}/user.in`. A strip number for a user
                # signal, a socket number for a user patch.
                "index": {"type": "integer", "minimum": 1,
                          "maximum": facts.USER_SOURCE_INDEX_MAX},
            },
            "required": ["group", "index"],
            "additionalProperties": False,
        },
        # `/io/in/USR/{n}/user.tap` and `.lr`. USER SIGNAL slots only; null
        # or absent means the conventions never said, the same "leave the
        # console alone" policy every other optional field here has.
        "tap": {"type": ["string", "null"], "enum": [*facts.USER_SIGNAL_TAPS, None]},
        "leg": {"type": ["string", "null"], "enum": [*facts.USER_SIGNAL_LEGS, None]},
        # Did a human state this routing, or did Atoo choose it? The
        # same question, and the same answer shape, as a channel `patch`'s
        # own `stated`.
        "stated": {"type": "boolean"},
    },
    "required": ["slot", "source"],
    "additionalProperties": False,
}


# A channel as a PLAN may carry it: CHANNEL_SCHEMA plus the one field only
# `build` writes, never a model -- `processing.preset_values`.
# Two schemas rather than one because the difference matters to
# a decoder as well as to a reader: `preset_values.leaves` is an open map
# keyed by address, which Anthropic's structured-output subset cannot
# express (`schema_check.anthropic_schema`), so putting it in the channel
# a model is asked for would silently switch constrained decoding off for
# `patch`'s change sets. Derived, not copied, so the two cannot drift.
PLAN_CHANNEL_SCHEMA = copy.deepcopy(CHANNEL_SCHEMA)
PLAN_CHANNEL_SCHEMA["properties"]["processing"]["properties"]["preset_values"] = \
    _preset_values_schema()

# Where a captured plan found an object's name on the desk --
# `socket` (the strip shows its source's name), `strip` (its own) or `none`
# (no name; the plan's is a placeholder such as "Bus 5"). `apply` writes the
# name only there, so a capture applied back to its desk changes nothing.
# Only `atoo capture` writes it, so it is in the plan's schema and not the
# model's, like `preset_values`.
NAME_ON = {"type": "string", "enum": ["socket", "strip", "none"]}
PLAN_CHANNEL_SCHEMA["properties"]["name_on"] = NAME_ON


def _sends_schema(target: str) -> dict:
    """A list of sends to `target` objects (`matrix` or `bus`), each naming its
    target by the plan's key for it, with the tap and level a channel's
    `bus_sends` carry. Both nullable: null leaves it to `decide`/apply as a
    bus send's does, and on a captured plan to the desk."""
    return {"type": "array", "items": {
        "type": "object",
        "properties": {
            target: {"type": "string", "minLength": 1},
            "mode": {"type": ["string", "null"], "enum": [*facts.PLAN_SEND_MODES, None]},
            "level_db": _DB,
        },
        "required": [target],
        "additionalProperties": False,
    }}


# The routes a desk has that a plan could not hold, which the
# maintainer asked for in the desk sheets. A send lives on its SOURCE, as on the
# desk (`/ch/{n}/send/MX{m}`, `/bus/{n}/send/{b}`, `/main/{n}/send/MX{m}`):
#
#   channel  matrix_sends  -> a Matrix, by its `outputs` key
#   bus      bus_sends     -> another bus, by its `busses` key
#   bus      matrix_sends  -> a Matrix
#   Main     matrix_sends  -> a Matrix (an `outputs` entry of kind main)
#
# So a Matrix fed by several sources is simply named by several of them, and
# its feeds are its `fed_by` plus every `matrix_sends` naming it
# (`plan_compat.matrix_feeds`). `fed_by` stays for the one-source Matrix a
# build writes. Plan schema only: a build from conventions does not produce
# these yet, so the model's schema does not offer them.
PLAN_CHANNEL_SCHEMA["properties"]["matrix_sends"] = _sends_schema("matrix")


def _bus_preset_values_schema() -> dict:
    """`busses[X].preset_values`: a bus preset expanded into
    the plan (`atoo/bus_presets.py`). The channel's shape, plus the
    effect(s) the preset inserts and the engine each was given."""
    schema = _preset_values_schema()
    schema["properties"]["inserts"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "point": {"type": "string", "enum": ["preins", "postins"]},
                "model": {"type": ["string", "null"]},
                # The effect's parameters as saved, keyed by the engine's
                # own leaf name (`pdel`, `dcy`); typed when written.
                "parameters": {"type": "object",
                               "additionalProperties": {"type": ["number", "string", "boolean"]}},
                "saved_engine": {"type": ["integer", "null"]},
                "saved_on": {"type": ["boolean", "null"]},
                # Allocated by `fx_engines.allocate`; null when no engine
                # could hold it (verify's ERROR `fx.no-engine`).
                "engine": {"type": ["integer", "null"]},
            },
            "required": ["point", "model", "parameters", "engine"],
            "additionalProperties": False,
        },
    }
    return schema


# A bus as a PLAN may carry it: BUS_SCHEMA plus `preset_values`, for the
# same reason PLAN_CHANNEL_SCHEMA exists.
PLAN_BUS_SCHEMA = copy.deepcopy(BUS_SCHEMA)
PLAN_BUS_SCHEMA["properties"]["preset_values"] = _bus_preset_values_schema()
PLAN_BUS_SCHEMA["properties"]["name_on"] = NAME_ON
PLAN_BUS_SCHEMA["properties"]["bus_sends"] = _sends_schema("bus")
PLAN_BUS_SCHEMA["properties"]["matrix_sends"] = _sends_schema("matrix")
PLAN_OUTPUT_SCHEMA = copy.deepcopy(OUTPUT_SCHEMA)
PLAN_OUTPUT_SCHEMA["properties"]["name_on"] = NAME_ON
PLAN_OUTPUT_SCHEMA["properties"]["matrix_sends"] = _sends_schema("matrix")

# The bus sheet's `role`: what a bus, Main or Matrix is FOR, in
# the engineer's words from a fixed list, so a rule can rely on it. Written
# from `busses.csv` by a Save in Build's step 04 (`atoo/sheets.py`), and by
# `atoo capture` for an effect return. Absent or null is "not said".
BUS_ROLES = ("mix", "parallel", "fx", "monitor", "feed", "other")
OUTPUT_ROLES = ("pa", "fill", "delay", "monitor", "feed", "record", "other")
PLAN_BUS_SCHEMA["properties"]["role"] = {"type": ["string", "null"],
                                         "enum": [*BUS_ROLES, None]}
PLAN_OUTPUT_SCHEMA["properties"]["role"] = {"type": ["string", "null"],
                                            "enum": [*OUTPUT_ROLES, None]}
# A Main's or a Matrix's own width (`/main/{n}/busmono`, `/mtx/{n}/busmono`),
# as a bus's `mono`. Only a capture or the bus sheet states it; null or absent
# leaves the desk's.
PLAN_OUTPUT_SCHEMA["properties"]["mono"] = {"type": ["boolean", "null"]}
# A Main's or Matrix's own DCAs and mute groups (`/main|mtx/{n}/tags`),
# as a bus's. Absent: the plan states none, and Apply leaves the desk's.
PLAN_OUTPUT_SCHEMA["properties"]["dca"] = {"type": "array", "items": {"type": "string"}}
PLAN_OUTPUT_SCHEMA["properties"]["mute_group"] = {"type": "array", "items": {"type": "string"}}
# A Main's or Matrix's own colour (`/main|mtx/{n}/col`, 1-18), as a
# bus's `col`. Stated by a capture; null or absent leaves the desk's.
PLAN_OUTPUT_SCHEMA["properties"]["col"] = {"type": ["integer", "null"], "minimum": 1, "maximum": 18}

# The effects a strip inserts, as the plan states them for the
# strip itself -- a capture's (what the desk had), or the bus sheet's `fx`
# cell. One entry per insert point; a bus preset's insert at a point the
# strip's own `inserts` also names loses to it (`bus_presets.strip_inserts`).
# `model` null takes the insert off (`ins` NONE). `engine` is the desk's FX
# engine: the one a capture found it in, or one `fx_engines.allocate` gave a
# model the sheet added. `parameters` are the engine's own leaves (`dcy`,
# `pdel`), as read; empty leaves them at what the desk gives the model.
# Absent: the plan states no insert of its own, and Apply leaves the desk's.
STRIP_INSERTS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "point": {"type": "string", "enum": ["preins", "postins"]},
            "model": {"type": ["string", "null"]},
            "engine": {"type": ["integer", "null"]},
            "parameters": {"type": "object",
                           "additionalProperties": {"type": ["number", "string", "boolean"]}},
        },
        "required": ["point", "model"],
        "additionalProperties": False,
    },
}
for _schema in (PLAN_CHANNEL_SCHEMA, PLAN_BUS_SCHEMA, PLAN_OUTPUT_SCHEMA):
    _schema["properties"]["inserts"] = copy.deepcopy(STRIP_INSERTS_SCHEMA)

# What ANY valid plan looks like, whichever path built it. The
# deterministic compiler emits no `unassigned_inputs` or `notes`, so they
# are optional here; everything else is the same shape.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "channels": {"type": "array", "items": PLAN_CHANNEL_SCHEMA, "minItems": 1},
        "dcas": {"type": "object", "additionalProperties": DCA_SCHEMA},
        "mute_groups": {"type": "object"},
        # Provenance fields the compiler records so a reader can trace any
        # value back to the files it came from.
        "conventions_file": {"type": "string"},
        "input_list": {"type": "string"},
        "busses": {"type": "object", "additionalProperties": PLAN_BUS_SCHEMA},
        "outputs": {"type": "object", "additionalProperties": PLAN_OUTPUT_SCHEMA},
        # A row left off the desk on purpose. A bare name in every plan
        # built before 2026-09-29; since then `{input, quote, from}`: the
        # words that said to leave it out, and whose they were
        # ("conventions", "instructions" or "input list" -- the row's own
        # notes). `build` puts a row here only when that quote is really
        # in them; every other row is built (`reply_expand.
        # build_left_out_rows`). Both shapes load.
        "unassigned_inputs": {"type": "array", "items": {"oneOf": [
            {"type": "string"},
            {"type": "object",
             "properties": {
                 "input": {"type": "string", "minLength": 1},
                 "quote": {"type": ["string", "null"]},
                 "from": {"type": ["string", "null"],
                          "enum": ["conventions", "instructions", "input list", None]},
             },
             "required": ["input"],
             "additionalProperties": False},
        ]}},
        # Optional and NOT on `required`: every plan.json that
        # predates it -- this repo's examples, every test fixture, every
        # plan on anyone's disk -- omits it and stays valid, the same
        # purely-additive posture `processing`'s phase-1 fields took. A plan
        # with no disjoint stereo pair has nothing to put here, which is
        # almost every plan.
        #
        # `apply` writes each slot ahead of the channel or output that reads
        # it (`apply.user_source_targets`), and `atoo capture`
        # records the slots a channel or an output reads. `schema_section()`
        # below does not offer it to the generator yet: a model names
        # strips, not their numbers, so a processed feed waits on its own
        # reply shape.
        "user_sources": {"type": "array", "items": USER_SOURCE_SCHEMA},
        # Output sockets an `atoo capture` found carrying an
        # input (or a monitor or send feed) straight from the routing, not a
        # bus, Main or Matrix -- a recording or Dante split. Recorded so the
        # plan declares them (CV009 reports one only if it changes, and
        # `apply --clean-output-sockets` keeps it), and Apply writes them as
        # output patches; a built plan has none. `source` is
        # the desk's own `/io/out/{group}/{socket}/grp` and `in`.
        "direct_outputs": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "enum": sorted(facts.OUTPUT_SOCKETS)},
                "socket": {"type": "integer", "minimum": 1},
                "source": {"type": "object",
                           "properties": {"group": {"type": "string", "minLength": 1},
                                          "index": {"type": "integer"}},
                           "required": ["group", "index"],
                           "additionalProperties": False},
            },
            "required": ["group", "socket", "source"],
            "additionalProperties": False,
        }},
        "notes": {"type": "array", "items": NOTE_SCHEMA},
        # FR-6.2, folded into the build (no separate
        # pre-compile stage). Where the conventions text itself is at fault
        # -- two statements that disagree with nothing settling it, or
        # something declared that nothing joins -- the generator says so
        # here, quoting the lines. Structured rather than a `notes` entry
        # because code turns each one into a finding and CHECKS the quotes
        # (`conventions_audit.py`): a quote that is not in the conventions
        # or instructions text is not trusted. Optional, so every plan on
        # disk and every canned test reply stays valid.
        "conventions_audit": {"type": "array", "items": CONVENTIONS_AUDIT_SCHEMA},
        # `build`'s own record of itself -- when it ran, and
        # whether verify_plan() looked clean at that moment. (It also named
        # the strategy until 2026-09-28, C5; an older plan's `strategy`
        # key still loads, since `meta` is open.)
        # The raw findings behind that verdict are kept --
        # `critic_findings` and `verify_findings` -- each `None` when that
        # pass never ran, distinct from `[]`/an empty errors+warnings dict
        # meaning it ran and found nothing. `meta` is an open object, so a
        # plan built before expectations were retired still loads with its
        # now-meaningless `expectations_findings` key intact.
        # Optional (never required, and never on the compiler's or a
        # generator's own required list) because it is this project's
        # metadata about a build, not part of the console spec a build
        # describes -- namespaced under one key rather than several new
        # top-level fields so the two stay visually distinct. Never
        # consulted by `apply_cmd`'s gate (cli.py re-verifies fresh every
        # time) -- see report.verify_at_generation_status()'s docstring.
        "meta": {"type": "object"},
    },
    "required": ["channels", "dcas", "mute_groups", "busses", "outputs"],
    "additionalProperties": False,
}

# What a GENERATED plan must look like: the same format, plus the two
# fields where a model says what it left out and what it could not
# express. Required of a generator and not of the compiler, because a
# generator that may omit `unassigned_inputs` can drop an input silently
# -- the worst failure available to it. The compiler cannot: it assigns
# every row or raises.
#
# Derived, not copied, so the two cannot drift.
GENERATION_SCHEMA = {
    **PLAN_SCHEMA,
    "properties": {
        **PLAN_SCHEMA["properties"],
        # A model produces channels WITHOUT preset values: those come from
        # a file it never sees, and `build` fills them in afterwards.
        "channels": {**PLAN_SCHEMA["properties"]["channels"], "items": CHANNEL_SCHEMA},
    },
    "required": [*PLAN_SCHEMA["required"], "unassigned_inputs", "notes"],
}

# Every key that may appear at a plan's top level. Used by json_repair to
# tell a safe end-of-document repair from one that would re-nest a
# section, so it has to cover optional keys too -- a reply whose `notes`
# ended up inside `busses` is exactly the case that guard exists for.
TOP_LEVEL_KEYS = frozenset(PLAN_SCHEMA["properties"])

# Lifted from a real plan rather than hand-typed, and validated against
# CHANNEL_SCHEMA at import, so the exemplar in the prompt cannot be
# subtly wrong -- which the previous one, with its `//` comments, was.
EXAMPLE_CHANNEL = {'channel': 1, 'bank': 'ch', 'name': 'Kick', 'color': 'Red', 'source': {'input': 'Kick', 'type': 'Mic', 'model': '', 'stereo': False, 'phantom': False}, 'patch': {'group': 'A', 'sockets': [1], 'stated': True}, 'processing': {'hpf_hz': 80, 'preset': None}, 'fader': {'fader_db': None, 'muted': None}, 'dca': ['Drums'], 'mute_group': ['Drums', 'All Band'], 'bus_sends': [{'bus': 'Drums', 'mode': 'post', 'level_db': 0.0}, {'bus': 'Monitor 1', 'mode': 'pre', 'level_db': 0.0}, {'bus': 'Monitor 3', 'mode': 'pre', 'level_db': 0.0}, {'bus': 'Monitor 5', 'mode': 'pre', 'level_db': 0.0}], 'main_routes': [], 'provenance': {'channel': "Inputs: 'Patch order: drums first'; 'Within drums: kick, snare, tom 1, hi-hat, floor, overhead' puts kick first", 'patch': "Input list patch column: 'AES50-A 1'", 'dca': "DCAs: 'Drums: all drums-category channels'", 'bus_sends': 'Busses: Drums (post, unity); Monitor 1/3/5 (pre, unity, all categories)', 'processing': "Processing: 'Drums get a high-pass at 80Hz'"}}
EXAMPLE_CHANNEL_JSON = __import__('json').dumps(EXAMPLE_CHANNEL, indent=2)

# A worked "patch" and "patches" shape, both nesting levels at once: a
# _OUTPUT_PATCH is {group, sockets (of ints), stated?} REGARDLESS of
# whether it sits under a bus/output's singular "patch" or its plural
# "patches" fan-out array. Those were "socket" and
# "sockets" -- the same word one level apart from a patch's own
# "sockets", meaning different things, and unconstrained runs confused
# them (the
# hosted-generation evidence: a model wrote `{"number": N}` fan-out
# entries instead of full group/sockets objects). Validated against
# BUS_SCHEMA/OUTPUT_SCHEMA in test_plan_schema.py for the same reason
# EXAMPLE_CHANNEL is validated against CHANNEL_SCHEMA.
EXAMPLE_BUS = {'destination': {'type': 'dedicated_output', 'label': 'Monitor 1',
                                'patch': {'group': 'A', 'sockets': [15], 'stated': True}},
               'dca': ['Monitors'], 'mute_group': [], 'mono': True, 'description': None,
               'provenance': "Busses: 'Monitor 1 feeds wedge on A15'",
               'inferred': [{'field': 'mono',
                             'basis': "the conventions state no width; Monitor 1 feeds one "
                                      "wedge on one socket (A15) -- a wedge send, conventionally mono"}]}
EXAMPLE_BUS_JSON = __import__('json').dumps(EXAMPLE_BUS, indent=2)

EXAMPLE_OUTPUT = {'kind': 'matrix', 'fed_by': {'type': 'bus', 'name': 'Drums'},
                   'patch': {'group': 'USB', 'sockets': [47], 'stated': False},
                   'patches': [{'group': 'USB', 'sockets': [47]},
                               {'group': 'REC', 'sockets': [1, 2]}],
                   'description': None,
                   'provenance': "Outputs: 'Matrix 1 fans out to a USB stream and a REC tap'"}
EXAMPLE_OUTPUT_JSON = __import__('json').dumps(EXAMPLE_OUTPUT, indent=2)
EXAMPLE_OUTPUT_PATCH_JSON = __import__('json').dumps(EXAMPLE_OUTPUT["patch"])


# --------------------------------------------------------------------------
# the REPLY: what the generator writes, before `reply_expand` turns it
# into a plan (output compaction, slices 2-4)
# --------------------------------------------------------------------------
#
# The plan on disk is `PLAN_SCHEMA` and does not change. What the model
# WRITES is this shorter shape, and `atoo/reply_expand.py` expands it
# into a plan inside `generate.generate_plan` before `GENERATION_SCHEMA`
# is checked. Three differences, each its own slice:
#
#   * omitted means null (slice 2): `processing`, `fader` and the rest
#     have no required leaves here; the expander writes the nulls and the
#     empty arrays the plan format wants;
#   * name-keyed maps are ARRAYS of `{"name": ...}` objects (slice 2): `busses`, `outputs`, `dcas` and `mute_groups`. Anthropic's
#     structured-output subset takes `additionalProperties: false` and
#     nothing else, so a map keyed by the engineer's own names could never
#     be sent as a schema and the plan was generated unconstrained. This
#     shape can be sent (`schema_check.anthropic_schema(REPLY_SCHEMA)` is
#     not None), so every hosted generator reply is decoded against it.
#
# The `provenance` object is the one place the projection bites: the
# subset forbids an open object, so a channel's per-field provenance names
# its keys here. Locally the object stays open (`schema_check` ignores
# `additionalProperties: True`); on the wire it is closed to these keys.
PROVENANCE_KEYS = (
    "channel", "bank", "name", "color", "source", "stereo", "pair", "patch", "alt_patch",
    "processing", "fader", "dca", "mute_group", "bus_sends", "main_routes",
    "inferred", "notes",
)

_REPLY_PROVENANCE = {
    "type": "object",
    "properties": {key: {"type": "string"} for key in PROVENANCE_KEYS},
    "additionalProperties": True,
}


def _named_item(schema: dict, *, drop: tuple[str, ...] = ()) -> dict:
    """`schema` (the value of one entry of a name-keyed map) as one item
    of the reply's array: the same fields, plus a required `name` first,
    minus `drop` (an `index` the model is never asked for)."""
    item = copy.deepcopy(schema)
    props = item.get("properties", {})
    for key in drop:
        props.pop(key, None)
    item["properties"] = {"name": {"type": "string", "minLength": 1}, **props}
    item["required"] = ["name", *[r for r in item.get("required", []) if r not in drop]]
    item["type"] = "object"
    item.setdefault("additionalProperties", True)
    if "provenance" in item["properties"]:
        # A bus's or output's provenance is one sentence in the reply; an
        # open object here could not be sent (see PROVENANCE_KEYS).
        item["properties"]["provenance"] = {"type": ["string", "null"]}
    return item


def _reply_channel_schema() -> dict:
    """A channel as the reply writes it (slice 4, C4): the input-list row
    it comes from and what the model DECIDED about it, nothing the row
    already states and nothing that is counting. `reply_expand.
    expand_mechanical` writes the rest: the number (list order, per
    bank), `source` (the row's type, model, phantom), a stated patch (the
    row's patch column), an unstated one (the next free socket of the
    group the reply chose, a pair on an odd socket), and the colour (the
    reply's `category_colors` map, by the row's category)."""
    ch = copy.deepcopy(CHANNEL_SCHEMA)
    props = ch["properties"]
    props["processing"]["required"] = []
    props["fader"]["required"] = []
    # Sends are written on the bus (`REPLY_SEND_GROUP_SCHEMA`), never here.
    del props["bus_sends"]
    del props["source"]
    props["provenance"] = _REPLY_PROVENANCE
    # Which group is judgement; which number is counting. `stated` is
    # read off the input list, so it is not the reply's to write.
    props["patch"] = {
        "type": "object",
        "properties": {
            "group": props["patch"]["properties"]["group"],
            "sockets": props["patch"]["properties"]["sockets"],
        },
        "required": ["group"],
        "additionalProperties": False,
    }
    # The alternate the same way: the group is what the conventions
    # state, the numbers are counted unless they state those too.
    props["alt_patch"] = copy.deepcopy(props["patch"])
    ordered = {
        "input": {"type": "string", "minLength": 1},
        # Only for a channel the conventions or instructions ask for that is
        # not on the input list: their sentence asking for it, verbatim,
        # stating its source socket (`instructed_channels.py`).
        "quote": {"type": "string", "minLength": 1},
        "pair": {"type": "string", "minLength": 1},
        "stereo": {"type": "boolean"},
        **{k: props[k] for k in ("bank", "channel", "name", "color", "patch", "alt_patch",
                                 "processing",
                                 "fader", "dca", "mute_group", "main_routes", "provenance",
                                 "inferred")},
    }
    ch["properties"] = ordered
    ch["required"] = ["input"]
    return ch


# The conventions' colour map, written once ("Color coding: Drums-Red,
# ...") and applied per channel by the row's category.
REPLY_CATEGORY_COLOR_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "minLength": 1},
        "color": {"type": "string", "minLength": 1},
    },
    "required": ["category", "color"],
    "additionalProperties": False,
}


REPLY_CHANNEL_SCHEMA = _reply_channel_schema()

REPLY_DCA_SCHEMA = _named_item({
    "type": "object",
    "properties": {
        "fader": _FADER,
        "description": {"type": ["string", "null"]},
        "provenance": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}, drop=("index",))

REPLY_MUTE_GROUP_SCHEMA = _named_item({
    "type": "object",
    "properties": {
        "description": {"type": ["string", "null"]},
        "provenance": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
})

# One group of senders into a bus, written on the bus (slice 3): the
# channels named in `from` (their input-list names, or the name the reply
# gave them; `["*"]` is every channel) each get a `bus_sends` entry with
# this mode, level and marker. A send's mode is rule 4b, so it is a
# required non-null enum here where the plan keeps it nullable for older
# plans. A send's level is required too (2026-09-29): the slice-C reply
# let it be left out "for unity", but apply writes nothing for null and a
# fresh desk's send sits at -144, so every unity send of a
# festival build came back silent. Null is still accepted -- it is then
# decided, unity, and announced (`inferred.send-level`).
REPLY_SEND_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "from": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "mode": {"type": "string", "enum": list(facts.PLAN_SEND_MODES)},
        "level_db": _DB,
        "inferred": _inferred_schema("send"),
        "provenance": {"type": ["string", "null"]},
    },
    "required": ["from", "mode", "level_db"],
    "additionalProperties": False,
}

REPLY_BUS_SCHEMA = _named_item(BUS_SCHEMA, drop=("index",))
REPLY_BUS_SCHEMA["properties"]["sends"] = {"type": "array", "items": REPLY_SEND_GROUP_SCHEMA}
# Rule 4b: a bus's width is decided, never null and never left out. The
# plan schema keeps `mono` nullable for plans written before that rule;
# the reply is written today, so here it is a required boolean.
REPLY_BUS_SCHEMA["properties"]["mono"] = {"type": "boolean"}
REPLY_BUS_SCHEMA["required"].append("mono")
REPLY_OUTPUT_SCHEMA = _named_item(OUTPUT_SCHEMA)
# Where an output lands is stated or null, never left out and never
# decided (rule 4): the reply writes `"patch": null` for an output the
# conventions never place, so the gap is a claim and not an omission.
REPLY_OUTPUT_SCHEMA["required"].append("patch")

REPLY_UNASSIGNED_SCHEMA = {
    "type": "object",
    "properties": {
        "input": {"type": "string", "minLength": 1},
        "quote": {"type": "string"},
    },
    "required": ["input", "quote"],
    "additionalProperties": False,
}

# The output sockets the conventions feed straight from a source
# -- a split, a recording feed -- stated as runs, which code expands into the
# plan's `direct_outputs`, one entry per socket (`reply_expand.expand_output_runs`).
# "from" is "inputs" (every input socket the plan patches, in channel order) or
# a source in the desk's words ("AES50-A 1", "USR 3"); "count" bounds the run.
REPLY_OUTPUT_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "minLength": 1},
        "from": {"type": "string", "minLength": 1},
        "count": {"type": "integer", "minimum": 1},
        "quote": {"type": "string"},
    },
    "required": ["to", "from", "quote"],
    "additionalProperties": False,
}

# A processed feed -- a strip at its tap, to an output socket,
# a post-fader vocal to a recorder, say -- stated by the strip's name. The desk
# carries it through a user signal, which code picks
# (`reply_expand.expand_processed_feeds`); the model never names a USR slot.
REPLY_PROCESSED_FEED_SCHEMA = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "minLength": 1},
        "strip": {"type": "string", "minLength": 1},
        "tap": {"type": "string", "enum": ["pre", "post"]},
        "quote": {"type": "string"},
    },
    "required": ["to", "strip", "tap", "quote"],
    "additionalProperties": False,
}

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "channels": {"type": "array", "items": REPLY_CHANNEL_SCHEMA, "minItems": 1},
        "category_colors": {"type": "array", "items": REPLY_CATEGORY_COLOR_SCHEMA},
        "dcas": {"type": "array", "items": REPLY_DCA_SCHEMA},
        "mute_groups": {"type": "array", "items": REPLY_MUTE_GROUP_SCHEMA},
        "busses": {"type": "array", "items": REPLY_BUS_SCHEMA},
        "outputs": {"type": "array", "items": REPLY_OUTPUT_SCHEMA},
        # Every row is built unless something the
        # engineer wrote says to leave it out -- so the reply names the row
        # AND quotes those words (the conventions, the instructions, or the
        # row's own notes). Code checks the quote; a row with none, or one
        # that is not there, is built anyway.
        "unassigned_inputs": {"type": "array", "items": REPLY_UNASSIGNED_SCHEMA},
        "output_runs": {"type": "array", "items": REPLY_OUTPUT_RUN_SCHEMA},
        "processed_feeds": {"type": "array", "items": REPLY_PROCESSED_FEED_SCHEMA},
        "notes": PLAN_SCHEMA["properties"]["notes"],
        "conventions_audit": PLAN_SCHEMA["properties"]["conventions_audit"],
    },
    "required": ["channels", "busses", "outputs", "unassigned_inputs", "notes"],
    "additionalProperties": False,
}

# The sections a reply writes as arrays and a plan holds as maps.
REPLY_ARRAY_SECTIONS = ("dcas", "mute_groups", "busses", "outputs")


def _without_nulls(value):
    """`value` with every null leaf and empty object left out -- what a
    reply that says only what it decided looks like. Arrays are kept
    even when empty: `[]` is a statement (no DCA) and costs two bytes."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if v is None or v == "":
                continue
            v = _without_nulls(v)
            if v == {} and k != "provenance":
                continue
            out[k] = v
        return out
    if isinstance(value, list):
        return [_without_nulls(v) for v in value]
    return value


# The reference channel as the reply writes it: the row, and the
# decisions. Its number is its place in the list, its colour is the
# category map's, its socket is stated on the input list, its sends are
# on the busses; none of those is written here.
EXAMPLE_REPLY_CHANNEL = {
    "input": EXAMPLE_CHANNEL["source"]["input"],
    "processing": _without_nulls(EXAMPLE_CHANNEL["processing"]),
    "dca": EXAMPLE_CHANNEL["dca"],
    "mute_group": EXAMPLE_CHANNEL["mute_group"],
    "main_routes": EXAMPLE_CHANNEL["main_routes"],
    "provenance": {k: v for k, v in EXAMPLE_CHANNEL["provenance"].items()
                   if k in ("channel", "dca", "processing")},
}
EXAMPLE_REPLY_CHANNEL_JSON = __import__('json').dumps(EXAMPLE_REPLY_CHANNEL, indent=None)
EXAMPLE_REPLY_BUS = {"name": "Monitor 1", **_without_nulls(EXAMPLE_BUS),
                     "sends": [{"from": ["*"], "mode": "pre", "level_db": 0.0,
                                "provenance": "Busses: 'Monitor 1 gets every channel, pre-fader'"},
                               {"from": ["Kick", "Snare"], "mode": "pre", "level_db": -10.0,
                                "provenance": "Busses: 'a little kick and snare in Monitor 1'"}]}
EXAMPLE_REPLY_BUS_JSON = __import__('json').dumps(EXAMPLE_REPLY_BUS, indent=None)
EXAMPLE_REPLY_OUTPUT = {"name": "Matrix 1", **_without_nulls(EXAMPLE_OUTPUT)}
EXAMPLE_REPLY_OUTPUT_JSON = __import__('json').dumps(EXAMPLE_REPLY_OUTPUT, indent=None)


# --------------------------------------------------------------------------
# the prompt's view of all this
# --------------------------------------------------------------------------

def _bounds(spec: dict) -> str:
    lo, hi = spec.get("minimum"), spec.get("maximum")
    if "enum" in spec:
        # repr(None) is the Python literal 'None' -- meaningless to a
        # model being told what JSON to write. 'null' is what actually
        # belongs in the reply.
        return " | ".join("null" if v is None else repr(v) for v in spec["enum"])
    if lo is not None and hi is not None:
        return f"{lo:g}..{hi:g}"
    if spec.get("maxLength"):
        return f"string, at most {spec['maxLength']} characters"
    return ""


def _eq_bounds(key: str) -> str:
    """One EQ band field's bound, read from the schema like every other
    number in the prompt, so the two cannot drift."""
    band = CHANNEL_SCHEMA["properties"]["processing"]["properties"]["eq"]["properties"]["bands"]["items"]
    return _bounds(band["properties"][key])


def _eq_shelf_prose(strip: str) -> str:
    return "/".join(facts.EQ_SHELF_TYPES[strip])


def _eq_model_prose(strip: str) -> str:
    return "/".join(facts.EQ_MODELS[strip])


def facts_tilt_spec() -> dict:
    return {"minimum": facts.TILT_DB_RANGE[0], "maximum": facts.TILT_DB_RANGE[1]}


def schema_section(compact: bool = True) -> str:
    """The normative field rules, GENERATED from GENERATION_SCHEMA.

    Deliberately not the JSON Schema itself. When decoding is constrained
    the grammar already enforces shape, so repeating it in prose would add
    a thousand tokens and a second thing to drift. What the prompt has to
    carry is what the fields MEAN -- which the grammar cannot express and
    the model cannot guess.

    Every bound quoted below is read from the schema, so the two cannot
    disagree even when someone edits one of them.

    `compact` (the default, and what `build`'s generator reads) describes
    the REPLY format (`REPLY_SCHEMA`, `reply_expand.py`): no indentation,
    omitted fields meaning null, and `dcas`/`mute_groups`/`busses`/
    `outputs` as arrays of named objects. `compact=False` describes the
    plan itself, as `patch`'s change compiler still asks for it
    (`change_compile.md`): a change set is a handful of objects and has
    little to gain from the shorter form.
    """
    ch = CHANNEL_SCHEMA["properties"]
    send = ch["bus_sends"]["items"]["properties"]
    socket_groups = ", ".join(sorted(facts.OUTPUT_SOCKETS))
    patch_shape = (
        f'{{"group": one of {socket_groups}, "sockets": [socket number(s) within '
        f'that group], "stated": optional bool}}'
    )
    if compact:
        omission_rule = """\
Write it with NO indentation, on as few lines as you like. A field you
leave out means what
`null` means -- "the conventions never said" (rule 4) -- and code writes
the null. So write only what you decided or the conventions state, and
never leave out a rule-4b field."""
        group_shape = ('arrays, one {{"name": "..."}} object per group you\n'
                       '                      referenced, in the order they should be numbered')
        bus_shape = 'array of {{"name": "...", ...}} objects'
        output_shape = 'array of {{"name": "...", ...}} objects'
        bus_index_note = ('Busses, DCAs and mute groups take\n'
                          '                      no index from you: code numbers each in the order\n'
                          '                      you write them. Per bus:')
        example_channel = EXAMPLE_REPLY_CHANNEL_JSON
        example_bus = EXAMPLE_REPLY_BUS_JSON
        example_output = EXAMPLE_REPLY_OUTPUT_JSON
        example_intro = "Example of one channel (nothing it did not decide, no indentation):"
        bus_intro = "Example of one bus (a width the conventions did not state, decided and marked):"
        output_intro = "Example of one output fanning out to two socket groups:"
        channel_head_prose = f"""\
  input         REQUIRED: the input-list row name, exactly. Code copies
                the row's type, model and phantom.
  pair          the SECOND row of a stereo pair (rule 3a), by name.
  stereo        true only when ONE row stands for a pair (its notes say
                so): a stated socket n takes n and n+1.
  bank          {_bounds(ch['bank'])}; "ch" when left out.
  channel       leave it out: code numbers each bank 1, 2, 3... in the
                order you write the channels, so write them in desk
                order. Aux strips count from 1 on their own, never on
                from the ch numbers. A number ({_bounds(ch['channel'])}) only starts a run.
  name          only when it differs from the input name; at most {facts.NAME_MAX_CHARS} characters.
  color         Written to the strip; only when it is not the category's
                (category_colors, below), or is stated for this alone.
  patch         leave it out when the input list states the row's patch.
                Otherwise {{"group": "LCL"}} (a group from the console
                section): the group is your judgement, the number is
                counting -- code takes the group's next free socket in
                channel order, a pair on an odd one, and says so. Add
                "sockets" only when the conventions state which.
  alt_patch     ONLY when the conventions state alternate inputs (e.g.
                WING LIVE playback, CRD): {{"group": "CRD"}}, as patch.
"""
        unassigned_prose = ('[{"input", "quote"}]: a row left out ONLY where words quoted from the\n'
                            '                      conventions, instructions or its notes say so; code builds the rest')
        output_runs_prose = """\
  output_runs         optional, [{"to", "from", "count", "quote"}]: output
                      sockets fed STRAIGHT from a source, not from a bus,
                      Main or Matrix -- a split to a monitor desk or a
                      recording feed -- ONLY where the conventions or
                      instructions state one; "quote" is their exact line.
                      "to" is the first output socket ("AES50-B 1", "CRD 1",
                      "USB 1"); code fills one socket per source from there.
                      "from" is "inputs" -- every input socket the channels
                      are patched from, in channel order, a stereo
                      channel's two in turn -- or the first source, in the
                      desk's words ("AES50-A 1", "LCL 3", "USR 3"). "count"
                      is how many sockets; leave it out for every input.
                      A processed or post-fader feed is processed_feeds,
                      never a run. A bus, Main or Matrix's own sockets are
                      its "patch", never a run.
  processed_feeds     optional, [{"to", "strip", "tap", "quote"}]: an
                      output socket fed from a strip AFTER its processing
                      -- a post-fader vocal to a recorder, a channel's
                      pre-fader feed to a stream -- ONLY where the
                      conventions or instructions state one; "quote" is
                      their exact line. "strip" is the channel's, bus's,
                      Main's or Matrix's name as the plan has it; "tap" is
                      "pre" or "post" its fader; "to" is the output socket
                      ("USB 13"). Code carries it through a user signal and
                      picks the slot: never name a USR slot. A stereo strip
                      takes "to" and the next socket.
"""
        category_colors_prose = """\
  category_colors     [{"category": "drums", "color": "Red"}, ...]: the
                      conventions' colour map, once; code colours each
                      channel by its input-list category. Omit if none.
"""
        bus_sends_prose = """\
  bus_sends     NOT on a channel: sends are written on the bus ("sends").
"""
        sends_prose = f"""\
                        sends         array of {{"from": [names], "mode", "level_db",
                                      "inferred", "provenance"}}: who sends to
                                      THIS bus, once. "from" names channels by
                                      input name (or the "name" you gave one);
                                      ["*"] is every channel. mode ({_bounds(send['mode'])})
                                      is never null (rule 4b): stated, or
                                      decided -- monitor sends "pre", mix and
                                      FX sends "post" -- and marked with
                                      "inferred": [{{"field": "mode", "basis":
                                      "..."}}]. level_db always: 0 is unity. A later
                                      group naming a channel replaces its send
                                      (a channel at another level). "provenance":
                                      the line the senders come from. A listed
                                      send is applied switched ON (unmuted), so
                                      "mute off" needs no note.
"""
    else:
        omission_rule = """\
Every field below is REQUIRED on every channel, except `color` and
`inferred` (optional). A value that is not known is `null` where the type
allows it, or an empty array -- never omitted, and never invented, except
the four rule-4b fields, which are decided and marked "inferred"."""
        group_shape = '{{"Name": {{}} -- one key per group you referenced.'
        bus_shape = '{{"Name": {{...}}'
        output_shape = '{{"Name": {{...}}, per name'
        bus_index_note = ('Busses, DCAs and mute groups take\n'
                          '                      no index from you: code numbers each in the order\n'
                          '                      you write them, so write them in the order they\n'
                          '                      should be numbered. Per name:')
        example_channel = EXAMPLE_CHANNEL_JSON
        example_bus = EXAMPLE_BUS_JSON
        example_output = EXAMPLE_OUTPUT_JSON
        example_intro = "A complete, valid example of one channel:"
        bus_intro = """\
A complete, valid example of one bus (note "patch" is the full
group/sockets/stated object, never a bare number, and a width the
conventions did not state is decided and marked, never null):"""
        output_intro = """\
A complete, valid example of one output that fans out to more than one
socket GROUP (note "patches" holds full group/sockets/stated objects too --
one per group, not one per physical socket number):"""
        channel_head_prose = f"""\
  channel       integer {_bounds(ch['channel'])}: the strip's number in ITS bank.
                Aux strips count from 1 on their own (see "aux:" above),
                never on from the ch numbers.
  bank          {_bounds(ch['bank'])}
  name          {_bounds(ch['name'])}. The console truncates beyond that,
                so a longer name is not what the operator will see.
  color         a desk colour name ("Red") or null. Written to the strip;
                set only when the conventions state it (by name or per
                category), never an invented scheme.
  source        input (MUST equal an input list row name, exactly),
                type and model as the input list gives them (null when it
                gives none), stereo, phantom
  patch         group {_bounds(ch['patch']['properties']['group'])}
                sockets: 1 socket for a mono source, exactly 2 for stereo
                stated: true if the input list gave the socket, false if you chose it.
                A row with no socket gets one you choose; stated: false is its
                announcement, so it needs no note of its own.
  alt_patch     the alternate input, patch's shape, or null. ONLY when the
                conventions state one (e.g. WING LIVE playback, CRD).
"""
        category_colors_prose = ""
        unassigned_prose = "input list rows you deliberately did NOT assign, by name"
        output_runs_prose = ""
        bus_sends_prose = f"""\
  bus_sends     array of {{bus, mode ({_bounds(send['mode'])}), level_db}}.
                Every bus must appear in "busses". mode is never null
                (rule 4b): stated, or decided -- monitor sends "pre", mix
                and FX sends "post" -- and then marked on that send with
                "inferred": [{{"field": "mode", "basis": "..."}}].
                A listed send is applied switched ON (unmuted), so a send the
                conventions call "mute off" needs nothing more, and no note.
"""
        sends_prose = ""
    section = f"""\
## The plan format

Emit exactly one JSON object. No prose before or after it, no markdown
fence, no comments -- JSON has none, and a `//` line makes the whole
document unparseable.

{omission_rule}

{channel_head_prose}  processing    hpf_hz ({_bounds(ch['processing']['properties']['hpf_hz'])}) or null
                preset name or null
                hi_cut_hz ({_bounds(ch['processing']['properties']['hi_cut_hz'])}) or null,
                tilt_db ({_bounds(ch['processing']['properties']['tilt_db'])}) or null,
                trim_db ({_bounds(ch['processing']['properties']['trim_db'])}) or null,
                balance_db ({_bounds(ch['processing']['properties']['balance_db'])}) or null
                (signed; which sign means "left" is not confirmed, so only
                write a value the conventions actually stated a number for),
                invert true/false or null,
                gain_db ({_bounds(ch['processing']['properties']['gain_db'])}) or null --
                this is the physical input socket's head-amp gain, not a
                channel-relative trim; use it only when the conventions
                state a starting gain for the mic pre itself, and only on a
                socket that has a head amp (see the console section). Every one of
                these six is null unless the conventions state it -- never
                invent a value to "improve" the sound.
                eq: omit it, or {{"on": true/false/null, "model": ... or null,
                "bands": [...]}}. A channel strip has SIX bands and no more:
                "low", "1", "2", "3", "4", "high" -- a bus or a Main has
                six numbered ones, a channel does not, so "5" here is a
                control that does not exist. One entry per band the
                conventions actually state, each {{"band": ..., "freq_hz"
                ({_eq_bounds('freq_hz')}), "gain_db" ({_eq_bounds('gain_db')}),
                "q" ({_eq_bounds('q')}), "shape"}}; leave out any of the four
                the conventions did not give. "shape" is the filter type and
                belongs ONLY to "low" and "high" ({_eq_shelf_prose('ch')} on a
                channel, {_eq_shelf_prose('aux')} on an aux) -- a numbered band
                is always a bell and has no shape at all. "model" ({_eq_model_prose('ch')})
                changes the EQ's character, never its numbers, and
                "mix_pct" ({_bounds(ch['processing']['properties']['eq']['properties']['mix_pct'])})
                is the wet/dry blend -- 100 is the EQ fully in circuit.
                Same rule as
                every field above: state a band only when the conventions
                state it. An EQ curve nobody asked for is the single most
                damaging thing you could invent here.
                presend_eq: omit it, or {{"on": ..., "bands": [...]}} -- the
                channel's SECOND EQ ("PreSend EQ", a different tap point
                in the strip), and a DIFFERENT control from "eq" above,
                not an alias for it. Three bands only, "1"/"2"/"3", each
                {{"band", "freq_hz", "gain_db", "q"}} -- no low/high
                shelf, so no "shape", and no "model" or "mix_pct" either.
                Use it only when the conventions distinguish the two
                ("pre-send EQ", "EQ the sends"); an ordinary "EQ" or
                "high-pass" instruction means "eq", never this.
  fader         fader_db ({_bounds({'minimum': -144.0, 'maximum': 10.0})}, where -144 is
                -infinity) or null, muted true/false or null. null means the
                conventions did not say -- soundcheck decides.
  dca           array of DCA names. [] for none. Every name must appear in "dcas".
  mute_group    array of mute-group names, same rule against "mute_groups".
{bus_sends_prose}  main_routes   [] for a channel that reaches Main only through a mix bus,
                or not at all.
                [{{"index": N}}] for a channel routed STRAIGHT to a Main. A DCA
                is not a path, and neither is a monitor or FX send. Every
                Main you do not list is switched OFF on the desk.
  provenance    free text per field you decided, citing the conventions line or
                input-list column you used. A human reads this beside the
                conventions; "1" is not a reason, "Inputs: patch order position 1"
                is.
  inferred      optional, [{{"field": "stereo", "basis": "..."}}] when a
                pairing came from the sources' names, not a stated rule.

"inferred" (channel, bus, bus send) lists the rule-4b values on that
object you DECIDED rather than read: {{"field", "basis"}}, where basis is
what you decided from in words the engineer can check ("feeds one wedge
socket -- conventionally mono"), never just "domain knowledge".

And at the top level:

  channels            the array above
{category_colors_prose}  dcas, mute_groups   {group_shape}
                      A group with no channel below joining it AND no bus
                      below joining it (see busses.dca/mute_group) is
                      declared but empty -- it does nothing. If the
                      conventions describe a group's purpose, something
                      has to actually join it.
                      A DCA may also carry "fader" ({{fader_db, muted}},
                      the same shape a channel's and a bus's use) -- the
                      DCA's OWN starting position, not its members'. State
                      it whenever the conventions give DCAs a fader
                      position ("every DCA starts fully down"); leave it
                      out when they do not.
  busses              {bus_shape}. {bus_index_note}
                        destination   REQUIRED. {{"type": "main", "index": N}},
                                      {{"type": "matrix", "index": N}}, or
                                      {{"type": "dedicated_output", "label": "...",
                                      "patch": {patch_shape}}} -- that "patch"
                                      is ALWAYS this exact three-field shape,
                                      never just a number. This is the bus's OWN
                                      physical/Main routing, not a Matrix feed --
                                      a bus that ALSO feeds a Matrix states that
                                      on the MATRIX's own "outputs" entry instead
                                      (see outputs.fed_by below), because that's
                                      a send, not this bus's exclusive destination.
                                      A mix or FX bus given no destination goes
                                      to Main 1, marked "inferred" (rule 4b); a
                                      physical socket is never decided that way.
                                      A route to a Main carries no level or
                                      pre/post here: the desk's factory route
                                      is post-fader at unity, which is what
                                      "POST fader at unity" asks for.
                                      Every Main a bus does not list is
                                      switched OFF on the desk.
                        destinations  optional, array of destination objects (same
                                      shape as "destination" above). A bus can
                                      route to Main AND a dedicated output AT ONCE
                                      -- state every one here when the
                                      conventions say so; "destination" alone
                                      still works when there's only the one.
                        fader         optional, same shape as a channel's fader
                                      ({{fader_db, muted}}). The BUS's own starting
                                      level -- distinct from what a channel sends
                                      to it. State it whenever the conventions give
                                      this bus a fader position.
                        dca           optional, array of DCA names, same rule as a
                                      channel's. A BUS can be a DCA/mute-group
                                      member in its own right -- use this
                                      when the conventions say a bus (not its
                                      member channels) joins a group.
                        mute_group    optional, same rule, for mute groups.
                        color         colour name ONLY if stated for this bus or its type
                                      (a category's = its channels' colour); else null.
                        mono          true (mono) or false (STEREO) -- never
                                      null (rule 4b): the width decides what a
                                      dedicated output's jack carries.
                                      STATED first: true for "all mono"; false
                                      for "both stereo": false is as stated as true.
                                      A width in a HEADING applies to every bus
                                      under it (rule 4a).
                                      Otherwise DECIDED -- a wedge on one socket
                                      mono; in-ear, mix and FX busses stereo; a
                                      socket pair stereo -- with "inferred":
                                      [{{"field": "mono", "basis": "..."}}].
{sends_prose}                        description   optional, one sentence, free text.
                        provenance    optional. Exactly the same field, and the same
                                      purpose, as a channel's own "provenance" above --
                                      never invent a differently-named field ("notes",
                                      "provenance_note", ...) to hold this same thing.
                        processing    optional, {{"eq": ..., "tilt_db": ...}}. The
                                      bus's OWN EQ -- exactly the shape a channel's
                                      "processing.eq" takes above, with two
                                      differences the console imposes: a bus has
                                      SIX numbered bands ("low", "1".."6", "high"),
                                      and its shelf bands take a wider set of
                                      filter types ({_eq_shelf_prose('bus')}).
                                      "tilt_db" ({_bounds(facts_tilt_spec())})
                                      is the bus's tilt.
                        preset        optional, the name of a BUS preset, or null.
                                      Set it ONLY when the conventions name one for
                                      this bus or its type ("FX busses get the bus
                                      preset of the same name"). It carries the
                                      bus's compressor and its insert effect
                                      (a reverb, a delay); Atoo loads them.
                      A bus's COMPRESSOR and insert settings otherwise have no field --
                      a compressor's own value ranges move with which of the 32
                      compressor models is loaded, and this format does not model
                      that yet. State those values in the plan's top-level "notes"
                      array (prefixed with the bus's name), never a new field on
                      the bus itself.
  outputs             {output_shape}. "patch" and "patches" BOTH
                      hold this same three-field object -- {patch_shape} --
                      never a bare number and never `{{"number": N}}`:
                        patch     REQUIRED, or null if the conventions never state
                                  where this output physically lands (say so in
                                  "notes" too -- a null patch blocks apply), or
                                  null with no note for a Main/Matrix the
                                  conventions route only through another output.
                                  One patch object, e.g. {EXAMPLE_OUTPUT_PATCH_JSON}.
                        patches   optional, array of THAT SAME per-group object
                                  shape (each entry is its own full
                                  {{"group", "sockets", "stated"}}, not a single
                                  number) -- one entry per GROUP being fanned out
                                  to, not one entry per socket number. A Main/
                                  Matrix can fan out to SEVERAL physical outputs
                                  AT ONCE (a real show file: one Main feeding a
                                  live send AND two independent recording taps
                                  simultaneously) -- state every group here when
                                  the conventions say so; "patch" alone still
                                  works when there's only the one.
                        kind      optional, "main" or "matrix" if this output IS
                                  one of the console's Main or Matrix strips
                                  (distinct from an ordinary physical output).
                        fed_by    optional, ONLY for kind "matrix". A matrix has
                                  no routing table of its own on real hardware --
                                  it is fed by a SEND on a Main or a bus. State
                                  {{"type": "main", "index": N}} or {{"type": "bus",
                                  "name": "..."}} when the conventions say what
                                  feeds this matrix ("fed from Main", "fed from
                                  the Drums bus"); omit or null if they don't say.
                        fader     optional, same shape as a channel's fader --
                                  this output strip's own starting level.
                        description   optional, one sentence, free text.
                        provenance    optional. Exactly the same field, and the same
                                      purpose, as a channel's own "provenance" above --
                                      never invent a differently-named field ("notes",
                                      "provenance_note", ...) to hold this same thing.
                        processing    optional, and ONLY meaningful together with
                                      kind+index -- exactly the same {{"eq",
                                      "tilt_db"}} shape as a bus's above, six
                                      numbered bands and the same wide filter-type
                                      set. Without kind+index there is no Main or
                                      Matrix strip to put it on.
                      A Main/Matrix COMPRESSOR or insert still has no field, for
                      the same reason as a bus's -- put those in the plan's
                      top-level "notes" array (prefixed with the output's name),
                      never a new field on the output itself.
  unassigned_inputs   {unassigned_prose}
{output_runs_prose}  notes               array of {{"text": "...", "source": "model"}}. "source"
                      is ALWAYS the literal string "model" here -- the other
                      values this field can hold ("extraction", "repair",
                      "allocation") are written by Atoo's own code
                      afterward, never by you. "text" is anything the
                      conventions asked for that this format cannot hold.
  conventions_audit   optional (rule 7), array of {{"kind": "conflict" or
                      "unused", "quotes": [exact lines], "message": "..."}}.
                      [] or omitted when there is nothing to say.

{example_intro}

{example_channel}

{bus_intro}

{example_bus}

{output_intro}

{example_output}"""
    if compact:
        # An omitted field is null (above), so "or null" says nothing here.
        section = section.replace(" or null", "")
    return section
