"""O2 (apply) + O3 (prove it landed): plan -> console writes -> readback
verification, with a reversal journal. FR-X.1-X.3.

## Fader / mute: stated, never invented -- this tool still does not mix

An earlier rule here said a strip this plan builds could only ever be
written to unity (0dB) / unmuted, full stop, enforced by an assertion
that rejected any other literal. That was itself a mistake, overruled by
the project owner (a working live-sound engineer, 2026-09-10): a starting
level is a stated convention like any other -- "busses at -6dB to give
some headroom during the show," a compressed drums bus with its fader
"pulled down 6dB" (natural-language conventions that were previously
unimplementable under the unity-only rule), "start everything muted" --
and refusing to write anything but unity made those conventions
impossible to apply, not safer.

"Mixing" was always the real thing this module must never do: *choosing*
a level -- riding a fader during a show, or this tool inventing a value
nobody asked for. Writing a level the engineer explicitly wrote down in
the conventions file is not mixing, it's executing their instruction --
exactly like every other parameter this module writes. So the
constraint that actually matters, replacing the old value-whitelist, is
structural rather than a fixed literal: **this module may only write
`fdr`/`mute` for a strip THIS PLAN IS BUILDING (a channel/aux/bus/Main/
Matrix entry actually present in the plan), and only a value the plan
itself states or this module's own documented default (unity, unmuted --
still the sound-check starting point, applied when the conventions said
nothing at all).** That's enforced by shape, not by an assertion against
a fixed set of literals: `_fader_starting_target`/`_mute_starting_target`
are the ONLY functions that construct an `fdr`/`mute` WriteTarget, both
take their value as a parameter sourced ONLY from a plan entry's own
`fader` dict (or the default when that dict states nothing) --
there is no third path by which a value could reach the wire here, and
every call site is inside the loop over the plan's own channels/busses/
outputs, so a strip the plan doesn't mention never has its fader or mute
touched (a full apply unpatches it, and writes nothing else to it).

**One documented exception: `mute` for a strip this run is
RETURNING TO FREE.** A channel the rebuild dropped has its strip muted,
put back on its factory input patch (or OFF where that is unmeasured,
absent or claimed), blanked and its processing put
back (`release_write_targets`). The mute is **a bracket around the clear,
not the end state** (corrected off the first hardware run):
it goes ON as the strip's first address so nothing pops while the strip
is taken apart, and OFF again as its last, because an untouched WING
strip is unmuted. Both writes stay inside the shape
the rule protects: the values are a fixed documented state, not a
choice, `release_write_targets` is the only function that builds them,
and the strips it may build them for are only those
`atoo/amend.py` has proved against a fresh read of the desk were
ours. **`fdr` is written for a released strip too, and only to one
value: -144 (-inf), the reading every untouched strip gives**
(`console_facts.FACTORY_STRIP_FADER_DB`, measured on a Compact and a
full-size). That is not a level chosen for a show, which is what this
rule forbids; it is the same "return to the factory reading" as the
name, colour and processing. It became necessary when release started
restoring the factory patch: an unmuted strip left
at the plan's level, routed to Main 1 and patched to its factory socket,
would carry a stray source on that jack to the PA. Pulled to -inf before
the closing unmute, it passes nothing until somebody raises it -- exactly
like an initialized strip.

The same issue added the **processing** half: the `flt`, `in/set`, `eq`
and `peq` leaves the plan's own build wrote go back to the reading an
untouched strip gives. A 120Hz high-pass left on a strip this tool has
just advertised as free is invisible until somebody patches a mic into
it, and then it is a filter nobody set and nobody can account for. The
set is derived from the build rather than listed (see
`_release_processing_targets`), which is what keeps "undo exactly what
this plan wrote, never more" true as the build learns new leaves.
**Head-amp gain is not in it** -- it belongs to the socket, it is shared
on a split, and nobody has said what a freed one should read.

WING represents -inf as literally `-144` on the wire (confirmed against a
real show file, Festival_STANDALONE.snap: a parked channel's `fdr` is
exactly `-144`, unity is `0`) -- JSON has no `-Infinity`, so `-144.0` IS
how a stated "all the way down"/"-inf"/"off"/"minus infinity"/"fully
down" starting level is represented all the way from the conventions
grammar through the plan to this module's own write.

`set_fader_levels` (default True, see `apply_plan`) decides WHETHER a
strip's fader/mute is written at all, as distinct from which value goes
there. **It is not the amend path's safety mechanism, and this paragraph
used to say that it was**. It is wrong for that job twice
over: it is global across every strip in the plan, so an amend using it
would also suppress the fader and mute of the strips it is *adding* --
leaving a new horn channel at whatever level the last show left on it,
which is the unsafe outcome and not the safe one -- and it suppresses
only `fdr`/`mute` anyway, so an existing strip's name, patch, tags and
every send would still be rewritten. FR-2.2 asks for no parameter of an
unrelated channel to move, and only `target_filter` below delivers that.
The flag keeps its narrower, real use: a full build that must not move
levels at all.

## Matrix and Main outputs, and a bus's own Main destination

Grounding an Output entry's physical socket to what actually feeds it
requires knowing the *internal source* -- `/io/out/{grp}/{n}` with
`grp=MAIN, in=<main index>` or `grp=MTX, in=<matrix index>` -- and an
engineer's own free-text Output name (real show file
`Festival_STANDALONE.snap`, seen in use: `MAIN/1`, `MAIN/2`, `MTX/9`,
`MTX/11`, `BUS/1`, `MON/1`, `LCL/21`, `USB/1`) can't be pattern-matched
to that reliably ("FOH", "Broadcast", ...). The plan now states this
directly (`outputs[*]["kind"]` is `"main"`/`"matrix"`, `["index"]` the
internal source's own number), so this module writes `grp=MAIN`/`grp=MTX`
+ `in=<index>` for any Output entry that states both, and warns (never
guesses) for one that doesn't -- no name is special-cased anymore. A
bus's own `dedicated_output` destination never had this problem -- the
bus IS the internal source, its own index is already known -- and a
bus's `main` destination likewise now carries the plan's own Main index
(`destination["index"]`, defaulting to 1 for an older plan that doesn't
state one) instead of this module hardcoding `/bus/{n}/main/1/on`.

The `in=<index>` above is never the object's raw declared index by
itself -- see `_output_slot`'s docstring: every bus/Main/
Matrix reserves a fixed 2-slot pair (`2*index - 1` for its first/"L"
physical socket, `2*index` for a second/"R" one), confirmed against a
real console after the first live apply run wrote the bare index and
scrambled a monitor-bus routing. `_output_slot(index, position)`
is the one place that math happens; every write site below calls it
rather than using `index`/`idx` directly.

## A strip's direct Main routes: every Main written, OFF included

A channel's or aux strip's `main_routes` is the complete statement of
where it goes straight to a Main, so `_channel_write_targets` writes
`/{bank}/{n}/main/{m}/on` for every Main the desk has
(`console_facts.main_indices()`): ON, with `lvl`/`pre`, for each listed
route, and OFF for every other (2026-09-27). A factory WING ships every
strip on Main 1, and writing only the listed routes left a
`main_routes: []` channel -- "reaches Main only through a mix bus" --
on Main 1 as well: a click track on the PA, and a drum or vocal on Main
twice. A released strip goes back to the factory reading, Main 1 ON and
the rest OFF (`release_write_targets`).

A bus's `destinations` are the same complete statement of ITS direct Main
routing: `_bus_write_targets` writes `/bus/{n}/main/{m}/on`
for every Main, OFF for each one no `main` destination lists. A factory
WING ships bus 9-16 on Main 1 (`console_facts.FACTORY_BUS_MAIN_ON_FROM`),
so a monitor bus the plan put there used to reach the PA as well. No code
path releases a bus today; `undo` restores one from the journal.

## A full apply takes the whole desk: unbuilt strips, talkback (2026-10-02)

`apply_plan(full_apply=True)` -- passed by `atoo apply` and by
nothing else -- also writes `/{ch|aux}/{n}/in/conn/grp` OFF for every
input strip the plan does not build, and `/cfg/talk/assign` to `CH40` /
`AUX8` when the plan builds a talkback strip there
(`full_apply_targets`). A strip outside the plan otherwise keeps its
factory patch and listens to a socket the plan may use: sixpiece's
ch 24 sat on LCL 24, which the plan had made aux 1's MUSIC. This is the
one place this module writes to a strip the plan does not mention, and
it writes only the source. `amend`/`patch` cannot reach it: it is
refused together with `target_filter`/`extra_targets`. See the section
comment above `unbuilt_strips`.

## Aux strips (`bank: "aux"`)

`aux.*` is WING's second bank of full input strips (`/aux/{n}/...`
instead of `/ch/{n}/...`), addressed by `channels[*]["bank"]` (missing
means `"ch"`, for an older plan). Everything this module already does
for a channel strip applies the same way -- EXCEPT the `flt` node:
confirmed against a real saved show (`Festival_STANDALONE.snap`) that an
aux strip has no `flt` node at all (also no `gate`/`peq`/`gatesc`/
`dynxo`/`proc`/`ptap` -- this module doesn't touch any of those on a
channel either, so only `flt` needed a guard). A plan that asks for a
high-pass, hi-cut, or tilt on an aux strip gets one
explicit warning naming the strip and which filter(s) were blocked, never
a silent drop and never a write to an address that doesn't exist. Trim,
balance, and invert (`{base}/in/set/*`) are confirmed present on BOTH
banks, so they carry no such guard. Patch, phantom, stereo mode, and
head-amp gain are unaffected either way -- they live on the physical
SOURCE (`/io/in/...`), not the strip, regardless of which bank the strip
is in.

## Address grounding

Every address this module writes is confirmed present in
the Compact parameter map's schema (the 2026-09-08
live walk) and cross-checked against the console model notes.
One thing is NOT hardware-confirmed and is called out at the point it
matters, below: whether `/ch/{n}/flt/lcf` (a "log" type param) replies
with the same raw-fraction-plus-real-value double-float shape that
`spike_write_verify.py` confirmed for `/ch/{n}/fdr` (a "fader" type
param) -- see `_extract_reply_value`.

## Write path choice: prefer set_node (acked) over set_param (silent)

atoo/console.py documents the two write paths in detail. Every
address this module writes is a *direct child* of some node address (the
leaf key is the last "/"-segment, the node is everything before it) --
structurally identical in shape to spike_write_verify.py's hardware-
confirmed `/ch/1` + "fdr=3,mute=1" case, just at different node depths
(e.g. node `/ch/3/flt` with key "lc", not just node `/ch/3` with key
"fdr"). The spec documents Node Data set as working against "any node",
not only a channel's top-level node, so this generalization is spec-
grounded even where a given node depth hasn't itself been hardware-
tested. `set_node` is used for every write except the rare case where the
value is a string containing a ",", "=", or a space (`_format_for_node_command`
returns None) -- "," and "=" are the node-command's own field/pair
delimiters (spec p23), so encoding them there would silently corrupt the
command rather than set what was asked. Space is the same problem for a
different reason, confirmed on real hardware (2026-09-16's first live
apply): a name like "Drums Comp" landed on the console as "DrumsComp" --
the value's own space vanished, not truncated, not rejected, just
silently dropped from the middle. The spec's Node Data examples (p23-25)
never show a value containing whitespace, only single tokens
(`fdr=-1`, `mdl=NONE`), so this command format was never demonstrated as
whitespace-safe -- rather than debug WING's own text-command tokenizer
further, this module now treats a space the same as "," and "=": route
it through `set_param` instead, which sends the string as one raw,
null-terminated OSC argument (spec p21-22) with no delimiter parsing to
lose a space to. `set_param` is the fallback for all three cases, and
its silence is exactly why readback verification runs regardless of
which path was used, not only when using the unacked one.

### The readback on the unacked path can lose a race with the write

The silence has a second consequence, and it produced false MISMATCH
lines on three real runs before it was understood. With no ack there is
nothing to wait on, so the readback goes out immediately -- and the desk
answers it from the value the address held BEFORE the write, then sends
the new value as its own datagram one or two later, by which time this
module is reading the next address and the client discards it as stale
(`/bus/10/name` and `/ch/7/tags` in the A1 runs of 2026-09-21, where the
writes were confirmed at the desk, both nights, to have landed).

The fix is not to read again harder. It is that **a discarded datagram
carries the address it is about**, so the answer is already in hand:
`console.py` keeps the most recent one per address (`late_reply`) and
this module consults it for the address it names, never for any other,
and only for a datagram that arrived after the write (`_late_confirmation`).
Anything still unresolved is held back to `_recheck_disagreements`,
which runs after the whole plan has been written -- a re-read there is
bounded by the number of disagreements and comes long after the race,
instead of the immediate re-read plus fixed 0.1s sleep this replaced
(the sleep was a guess at the desk's timing, and on
`/ch/7/tags` it guessed wrong). A verdict can only ever move from
mismatch to match this way: every path requires a reading that EQUALS
the intended value, so a write the console never accepted stays a
mismatch however many datagrams arrive.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

# The only intra-package import in this module, and a deliberate one:
# `console_facts` is pure data with no imports of its own, and two things
# it holds have to live beside the parameter facts they describe rather
# than being copied in here:
#
#   * The readback index-base table;
#   * the EQ topology facts -- so the addresses
#     written below and the bounds the schema enforces cannot drift apart.
#
# The capacity constants further down predate this import and still state
# themselves locally.
from atoo import console_facts as facts

# The second, since 2026-09-25: the rule that DECIDES a bus width or send
# mode a plan left null. It must be the one `verify_plan` reports from, or
# the INFO would name a value apply does not write -- so it is imported,
# never restated. It depends only on `diagnostics` and `plan_schema`.
from atoo import inferred
from atoo import plan_compat

# The WING family's fixed object counts come from `console_facts.CAPACITY`
# -- one name for one fact (review 2026-09-28, R23; they were Compact-named
# copies here, and every model shares them). verify_plan rejects a plan
# that declares more than this before apply ever sees it
# (capacity.exceeded); the checks below are the apply-time enforcement,
# which still matters under --skip-verify -- an index the console doesn't
# have is never sent, not sent-and-hope.

# Physical source/output groups confirmed (wing-console-model.md) to carry
# a phantom-power address (`.vph`) at all -- USB/SC/CRD/MOD/AES sockets
# have no such field in the parameter map, so a channel patched there with
# phantom requested has nothing groundable to write.
# The single source of this fact is console_facts; verify_plan asks the
# same question when it warns about two strips sharing one source.
_VPH_CAPABLE_GROUPS = facts.PHANTOM_CAPABLE_GROUPS

# Stereo/mono/M-S width, like phantom power, lives on the physical SOURCE
# (`/io/in/{grp}/{n}/mode`, values "M"/"ST"/"M/S"), not on the channel --
# confirmed against a real show file (Festival_STANDALONE.snap:
# io.in.LCL.15/16.mode == "ST" for a stereo "Keys" pair), and BOTH sockets
# of a stereo pair carry it, unlike vph which is per-source but a stereo
# pair is still two independent sources. Unlike vph, `.mode` is confirmed
# in the parameter map for every group the plan's patch vocabulary can
# name (LCL/A/B/C/SC/USB/CRD/MOD/AES) -- listed explicitly anyway,
# same defensive pattern as vph, rather than assuming "every group" holds
# forever.
_MODE_CAPABLE_GROUPS = {"LCL", "A", "B", "C", "SC", "USB", "CRD", "MOD", "AES"}

# Plan send-mode text (conventions.py's _SEND_MODE_MAP: "pre"/"post"/
# "group") -> WING's own enum (/ch/{n}/send/{n}.mode: PRE/POST/GRP).
_SEND_MODE_TO_WING = {"pre": "PRE", "post": "POST", "group": "GRP"}

# A Node Data set command is a comma-separated list of key=value pairs
# (console.py / spec p22-23) -- a string value containing "," or "="
# would silently corrupt the command rather than set what was asked, and
# a space is confirmed (2026-09-16's first live apply) to just vanish
# from the value instead of landing -- all three go through set_param
# instead (see module docstring's "Write path choice" section).
_UNSAFE_NODE_COMMAND_CHARS = (",", "=", " ")

# The documented default when the conventions state nothing for a strip's
# starting level (`facts.FADER_DEFAULT_DB`, `facts.MUTED_DEFAULT`; see the
# module docstring's fader/mute section). Unity/unmuted is the sound-check
# starting point the owner asked for; it is a FALLBACK for an unstated
# value, not the only value this module is willing to write.

# A channel's direct-to-main route (no bus, no DCA -- the festival
# conventions' HOST) writes `ch.{n}/main/{m}.on`/.lvl/.pre (FR-1.5,
# confirmed present -- the 2026-09-08 raw walk of a Compact:
# every /ch/{n}/main/{m} node is exactly `on int[0..1]`, `lvl fader`,
# `pre int[0..1]`). The conventions grammar has no phrasing yet for this
# route's OWN level or pre/post-fader tap (only THAT it routes, and
# optionally which Main) -- same "documented fallback, not guessed"
# policy as the starting-level defaults above: unity (0dB, this
# project's one standard "no level stated" default) and post-fader
# (0 -- a channel's main feed reflecting its own fader is the ordinary,
# expected wiring; pre-fader would silently bypass the channel's own
# fader, which nothing asked for).
MAIN_ROUTE_LEVEL_DEFAULT_DB = 0.0
MAIN_ROUTE_PRE_DEFAULT = 0

# The one Main every WING routes every strip to out of the box --
# `console_facts.FACTORY_STRIP_MAIN_INDEX`, counted on three initialized
# captures (every ch and aux strip: Main 1 on, 2-4 off). It is why a
# strip this plan builds has EVERY Main written, not only the ones it
# lists (`_channel_write_targets`), and why a released strip is put back
# on Main 1 (`release_write_targets`). `audit.DEFAULT_MAIN_INDEX` is the
# same number and `audit._has_sends` makes the same exception for it.
_FACTORY_MAIN_ROUTE_INDEX = facts.FACTORY_STRIP_MAIN_INDEX

_DCA_TAG_RE = re.compile(r"^#D(\d+)$")
_MUTE_GROUP_TAG_RE = re.compile(r"^#M(\d+)$")

# Ordering matters: FR-X.3 journals prior-vs-new per address, but some
# addresses are also *logically* dependent on another one already having
# landed -- phantom power targets the socket a channel was just patched
# to, so patch must be written (and, in principle, could be re-verified)
# before phantom is attempted against it. Stage number is applied as the
# primary sort key over the write list; ties keep the order they were
# built in (channel order, then per-channel field order).
STAGE_NAMES = 0
STAGE_PATCH = 1
# Naming the physical source. After the patch for the same reason phantom
# is: a name written to a socket the plan has not yet patched to lands on
# the wrong input, and unlike phantom it looks entirely correct.
STAGE_SOURCE_LABEL = 2
STAGE_PHANTOM = 3
STAGE_PROCESSING = 4
STAGE_TAGS = 5
STAGE_SENDS = 6
STAGE_ROUTING = 7
# Last, deliberately: fader/mute starting state (Job 3) is only meaningful
# once everything that defines what's actually flowing through the strip --
# patch, phantom, sends, routing -- has already landed. Bringing a strip
# out of mute/-inf before that would un-mute a signal path that isn't
# necessarily the one the plan intends yet.
STAGE_FADER_MUTE = 8


@dataclass(frozen=True)
class WriteTarget:
    """One address this apply run intends to touch. `compute_value` takes
    the address's CURRENT value (already read back, per FR-X.3) and
    returns the value to write -- a plain `lambda _: literal` for most
    targets, but genuinely a function of the current value for /ch/{n}/tags
    (DCA/mute-group membership is merged into, not overwritten onto, that
    field -- see `_merge_tags`)."""

    address: str
    value_type: str  # "s" | "i" | "f" -- OSC type tag this leaf actually uses
    description: str
    compute_value: Callable[[object], object]
    stage: int


@dataclass
class WriteRecord:
    """One row of the journal (FR-X.3): enough to reverse this write
    without re-reading the console (prior_value is captured BEFORE any
    write attempt), plus what verification found."""

    address: str
    description: str
    # The OSC type tag this leaf uses ("s" | "i" | "f"), carried over from
    # the WriteTarget. Without it a record cannot answer
    # "would this write change anything?" the way the write path answers
    # it: `_values_equal` is type-aware, and for "f" it carries the
    # stepped-parameter tolerance. A record that knows only its two values
    # has to fall back on exact equality -- which is exactly the
    # preview-vs-apply disagreement that this exists to close. Journalled, so a
    # journal can be re-scored later with the comparison its run used.
    value_type: str
    method: str | None  # "node" | "param" | None (dry_run, or skipped)
    ack: str | None  # "OK" / a console error token / "no_ack_path" (set_param) / None (not written)
    prior_value: object
    intended_value: object
    readback_value: object
    status: str  # see apply_plan's docstring for the full status vocabulary
    timestamp: str
    # Which reading settled this verdict, when it was not the readback
    # taken straight after the write: "late_reply" for a
    # datagram the client had drained as stale and kept, "recheck" for
    # the deferred second read at the end of the run, None for the
    # ordinary case. Journalled, because "this address only verified on
    # the second look" is exactly what someone diagnosing a desk that
    # answers slowly needs to see.
    readback_source: str | None = None
    # The selector address whose change in THIS run made this
    # value's baseline meaningless -- `/ch/1/in/set/dlymode` for
    # `/ch/1/in/set/dly`. Set, the value was written and read back even
    # though its baseline equalled the plan's (never `skipped_no_change`),
    # and `prior_value` is the reading taken BEFORE the selector was
    # written, which is what undo must put back. None for every other
    # write, and absent from every journal written before the fix.
    forced_by: str | None = None

    @property
    def would_change(self) -> bool:
        """Whether a real apply would actually write this address --
        decided with `_values_equal`, the SAME comparison `apply_plan`'s
        write loop uses to choose between writing and
        `skipped_no_change`.

        The dry-run summary used to answer this with a plain
        `prior_value != intended_value`, which is stricter than the write
        path for floats (`_values_equal` carries the stepped-parameter
        tolerance). On the 631-address A1 run that was 340 "would
        change" against 337 actually written -- three `flt/lcf` addresses
        sitting at 100.237Hz where the plan says 100Hz, a difference the
        desk cannot even represent. A preview that overstates what will
        happen is a preview an engineer stops trusting, and it cannot be
        used as the baseline to diff a later apply against, which is what
        the desk-testing walkthrough tells a tester to keep.

        A value governed by a selector this run changes (`forced_by`) is always written, so it always "would change".

        Only meaningful before the write: for a record the apply loop has
        already resolved, `status` is the answer."""
        if self.forced_by is not None:
            return True
        return not _values_equal(self.value_type, self.prior_value, self.intended_value,
                                self.address)


@dataclass
class ApplyResult:
    dry_run: bool
    writes: list[WriteRecord] = field(default_factory=list)
    journal_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Set when a genuine socket-level failure stopped the run
    # early -- see apply_plan's own docstring for why this is a fatal
    # abort rather than an ordinary per-address "unreadable" outcome.
    aborted: bool = False
    abort_reason: str | None = None
    # Datagrams the client drained because they answered a different
    # address (WingConsole.replies_discarded). Nonzero means the console
    # duplicated or volunteered something during this run. It is recorded
    # because before reply matching existed, one such datagram silently
    # invalidated every readback that followed it -- so "how many were
    # there" is the question a future journal should be able to answer
    # about itself.
    replies_discarded: int = 0
    # How many of those discarded datagrams were then USED as evidence
    # about the address they name -- the console answering a
    # write late rather than not at all. A subset of replies_discarded.
    replies_used: int = 0
    # What this run was ALLOWED to touch. None for a full
    # build, where the answer is "all of it" and saying so adds nothing.
    # An amend sets it to `{"strips": ["ch:21", ...], "grants": {...}}`
    # -- see `atoo/amend.py`. Journalled, because "which strips was
    # this run scoped to" is the first question anyone asks of a journal
    # written mid-show, and until this field existed a journal could only
    # answer it by having the reader infer it from the addresses.
    scope: dict | None = None
    # The desk this run was pointed at (`journal_stack.desk_from_identity`,
    # carrying `model_token` -- the model exactly as the desk spelled it),
    # and what `check_desk_model` said about it when it said anything.
    # Journalled so a run against a desk whose model Atoo has never
    # measured hands back the string to add to
    # `console_facts.IDENTITY_MODEL_ALIASES`, and so the Apply screen can
    # put the cross-model INFO / unmeasured WARNING in its findings dock.
    desk: dict | None = None
    model_check: dict | None = None

    @property
    def mismatches(self) -> list[WriteRecord]:
        return [w for w in self.writes if w.status == "mismatch"]

    @property
    def changed(self) -> list[WriteRecord]:
        return [w for w in self.writes if w.status in ("match", "mismatch")]

    @property
    def cleaned(self) -> list[WriteRecord]:
        """The writes that came from
        `--clean-output-sockets`, not the plan itself -- identified by
        `_clean_write_targets`'s own description prefix, the only marker
        that distinguishes "the plan asked for this" from "this socket
        had undeclared routing and got disconnected". Surfaced separately
        in `summary()` because silently folding a console-altering action
        nobody's plan asked for into the ordinary write count would be
        exactly the kind of quiet console change this option exists to surface.

        Deliberately NOT just `self.changed` filtered by prefix -- in
        `dry_run` mode every record's status is "dry_run" regardless of
        whether the value would actually change (`changed` only ever
        matches "match"/"mismatch", a real-apply-only pair), so a preview
        run asks `WriteRecord.would_change`, the same question the write
        loop asks, just scoped to clean writes. It used to ask it with a
        plain `!=` of its own, the second copy of the bug -- no
        observed effect, because every clean-write target is a `.grp`
        string enum and the tolerance only applies to floats, but two
        hand-written copies of "would this change?" is how the counts
        drifted apart in the first place."""
        return [
            w for w in self.writes
            if w.description.startswith("--clean-output-sockets:")
            and (w.status in ("match", "mismatch") or (w.status == "dry_run" and w.would_change))
        ]

    def summary(self) -> str:
        """One paragraph, safe to print or log -- never swallows a
        mismatch into a bare count without saying which addresses."""
        if self.aborted:
            lines = [
                f"ABORTED: lost the connection to the console ({self.abort_reason}).",
                f"{len(self.writes)} address(es) were evaluated before stopping; "
                "nothing further was attempted.",
            ]
        elif self.dry_run:
            # `would_change`, not `prior_value != intended_value`
            # -- the count has to be the one the write path would reach.
            would_change = [w for w in self.writes if w.status == "dry_run" and w.would_change]
            lines = [
                f"DRY RUN: {len(self.writes)} address(es) evaluated, "
                f"{len(would_change)} would change, nothing written.",
            ]
        else:
            lines = [
                f"APPLIED: {len(self.writes)} address(es) evaluated, "
                f"{len(self.changed)} written, {len(self.mismatches)} mismatch(es).",
            ]
        for w in self.mismatches:
            lines.append(f"  MISMATCH {w.address}: expected {w.intended_value!r}, read back {w.readback_value!r}")
        unreadable = [w for w in self.writes if w.status in ("unreadable", "unreadable_skipped")]
        for w in unreadable:
            lines.append(f"  UNREADABLE {w.address}: could not establish a baseline value, skipped")
        if self.cleaned:
            verb = "would be disconnected" if self.dry_run else "disconnected"
            lines.append(f"  {len(self.cleaned)} undeclared output socket(s) {verb} (--clean-output-sockets):")
            for w in self.cleaned:
                lines.append(f"    {w.address}: was {w.prior_value!r}")
        # The fixed-default INFO lines (`_fixed_default_notes`) ride in
        # `.warnings` so every consumer already shows them in full (the CLI
        # prints each one under this summary); they are notes, so they are
        # not counted as warnings here.
        real = [w for w in self.warnings if not w.startswith("INFO ")]
        if real:
            lines.append(f"  {len(real)} warning(s), listed below")
        if self.replies_discarded:
            # Not a warning about this run's result -- reply matching means
            # the readbacks above are still sound. It is reported because
            # a console that duplicates datagrams is exactly the condition
            # that made the 2026-09-21 journal worthless, and a run that
            # says nothing about it cannot be told apart from a run where
            # it did not happen.
            line = (
                f"  note: {self.replies_discarded} stale reply/replies from the console were "
                "discarded (duplicated or unsolicited datagrams). Readbacks above are matched "
                "by address, so this did not affect them."
            )
            if self.replies_used:
                # A discarded datagram still names its own
                # address, so one carrying the value of a write whose
                # readback raced it is the console answering late, not
                # noise. Said out loud because a verdict reached that way
                # should be visible, not quietly indistinguishable.
                line += (
                    f" {self.replies_used} of them named an address whose readback had raced "
                    "the write, and confirmed it."
                )
            lines.append(line)
        return "\n".join(lines)


def _const(value):
    return lambda _current: value


def _output_slot(internal_index: int, position: int) -> int:
    """The value `/io/out/{grp}/{n}/in` actually wants for the `position`-th
    (0-based) physical socket fed by internal object `internal_index` (a
    bus, Main, or Matrix's own declared number).

    The console model notes' original example
    ("grp=BUS, in=3 patches Bus 3 to this output socket") was never
    hardware-confirmed -- it was written straight from the parameter map's
    schema, before any real console existed to check it against, and reads
    as "in == the object's own declared index" (an implicit `position=0`
    assumption that happens to be right for object 1 and silently wrong
    for every object after it, so it went uncaught until a plan actually
    used a bus other than the first). Reconstructed from a real
    console (the 2026-09-18/19 apply run cross-checked line-for-line against
    WING-Edit screenshots and the post-apply `.snap`): each internal
    object of a given type reserves a FIXED pair of slots -- object N's
    position 0 (its "L"/mono feed) is slot `2N - 1`, position 1 ("R") is
    `2N` -- independent of the object's own busmono/stereo setting, which
    changes what plays on those slots, not their addresses. A single
    physical jack wanting an object's primary/mono feed (a monitor bus
    links to the Left channel; stereo was never asked for) always wants
    position 0.
    """
    return internal_index * 2 - 1 + position


def _merge_tags(current: str | None, dca_indices: list[int], mute_group_indices: list[int]) -> str:
    """/ch/{n}/tags is one free-form 80-char field shared by DCA membership
    (#D1..#D16), mute-group membership (#M1..#M8), AND any other tag text
    an operator put there (spike_dca_mgrp.py, confirmed against a real
    show's tags string "#D1,#M1,#M8"). A plain overwrite would silently
    destroy whichever of those three this write wasn't thinking about --
    so this reads the current value apart into (everything else) plus the
    two tag families the plan is actually authoritative for, and rebuilds
    from the plan's own membership rather than trying to diff/patch the
    existing D/M tokens one at a time (the plan already fully states this
    channel's DCA/mute-group membership -- there's nothing to preserve in
    the old D/M tokens once the new set is known).

    In practice this means most non-trivial tags writes fall back to
    set_param rather than set_node (`_format_for_node_command` refuses a
    string containing a comma, since comma is the node-command's own
    pair separator) -- a merged tags value is comma-joined by definition
    whenever it carries more than one token. That's fine: readback
    verification runs regardless of which write path was used, which is
    exactly why it exists rather than trusting an ack."""
    tokens = [t.strip() for t in (current or "").split(",") if t.strip()]
    other = [t for t in tokens if not _DCA_TAG_RE.match(t) and not _MUTE_GROUP_TAG_RE.match(t)]
    dca_tokens = [f"#D{i}" for i in sorted(set(dca_indices))]
    mute_tokens = [f"#M{i}" for i in sorted(set(mute_group_indices))]
    return ",".join(other + dca_tokens + mute_tokens)


def _fader_starting_target(base: str, label: str, fader_db: float) -> WriteTarget:
    """The ONLY function that builds an `fdr` WriteTarget for a strip a
    plan is BUILDING. (A strip being returned to free gets the one fixed
    factory reading, -inf, from `release_write_targets` -- the documented
    exception in the module docstring.)
    `fader_db` is sourced ONLY from a plan entry's own stated
    `fader["fader_db"]` (a convention the engineer wrote down) or
    `facts.FADER_DEFAULT_DB` (the documented default, unity)
    -- see the module docstring's fader/mute section for the full "stated
    vs invented" reasoning, and why -144.0 there means -inf, not some
    other float this module decided on its own."""
    description = "unity (0dB)" if fader_db == 0.0 else f"{fader_db:g}dB"
    return WriteTarget(f"{base}/fdr", "f", f"{label}: starting fader -> {description}", _const(fader_db), STAGE_FADER_MUTE)


def _mute_starting_target(base: str, label: str, muted: bool) -> WriteTarget:
    """The ONLY function that ever constructs a `mute` WriteTarget -- see
    `_fader_starting_target`, same reasoning, same guarantee."""
    description = "on" if muted else "off"
    return WriteTarget(f"{base}/mute", "i", f"{label}: starting mute -> {description}", _const(1 if muted else 0), STAGE_FADER_MUTE)


_EQ_SHELF_LEAVES = {"low": ("lf", "lg", "lq", "leq"), "high": ("hf", "hg", "hq", "heq")}


def eq_band_leaves(band: str) -> tuple[str, str, str, str | None]:
    """`(frequency, gain, Q, shape)` leaf names under `{base}/eq/` for one
    plan band id (`low`, `1`..`4`, `high`). Only the two shelf bands have a
    shape leaf; the numbered ones return None for it. The one place the band
    naming is written down, for the write path and for the audit that reads
    the same leaves back."""
    if band in _EQ_SHELF_LEAVES:
        return _EQ_SHELF_LEAVES[band]
    return f"{band}f", f"{band}g", f"{band}q", None


def _eq_write_targets(base: str, strip: str, label: str, eq: dict | None) -> tuple[list[WriteTarget], list[str]]:
    """One strip's parametric EQ.

    `strip` is the CONSOLE's node name ("ch"/"aux"/"bus"/"main"/"mtx"),
    not the plan's word for it -- the caller maps `bank`/`kind` first,
    because that mapping is where a Matrix stops being called "matrix"
    and starts being `/mtx/{n}`.

    Every guard here is deliberately a second line rather than the first:
    the schema already fixes the band list and the ranges, and
    verify_plan.py already makes the per-bank shelf/model call. This runs
    anyway because `apply --skip-verify` exists, and because the cost of
    getting it wrong is the worst kind -- `/ch/12/eq.5f` is a leaf a
    channel does not have, so the write lands nowhere, reports nothing,
    and the band the engineer asked for is simply absent at soundcheck.
    """
    targets: list[WriteTarget] = []
    warnings: list[str] = []
    if not eq:
        return targets, warnings

    valid_bands = facts.eq_band_ids(strip)
    stated_any = False
    seen: set[str] = set()
    for entry in eq.get("bands") or []:
        band = entry.get("band")
        if band in seen:
            warnings.append(f"{label}: EQ band {band!r} is stated more than once -- the later entry is ignored")
            continue
        seen.add(band)
        if band not in valid_bands:
            warnings.append(
                f"{label}: EQ band {band!r} requested, but a {strip} strip has bands "
                f"{', '.join(valid_bands)} (confirmed: wing-compact-parameter-map.json) -- not written"
            )
            continue
        freq_leaf, gain_leaf, q_leaf, shape_leaf = eq_band_leaves(band)

        for leaf, key, unit in ((freq_leaf, "freq_hz", "frequency"),
                                (gain_leaf, "gain_db", "gain"),
                                (q_leaf, "q", "Q")):
            if entry.get(key) is not None:
                stated_any = True
                targets.append(WriteTarget(
                    f"{base}/eq/{leaf}", "f", f"{label}: EQ band {band} {unit}",
                    _const(float(entry[key])), STAGE_PROCESSING,
                ))

        shape = entry.get("shape")
        if shape is not None:
            if shape_leaf is None:
                warnings.append(
                    f"{label}: EQ band {band} states shape {shape!r}, but only the low and high bands "
                    "have a filter-type leaf (eq.leq/eq.heq) -- not written"
                )
            elif shape not in facts.EQ_SHELF_TYPES.get(strip, ()):
                warnings.append(
                    f"{label}: EQ band {band} states shape {shape!r}, which a {strip} strip's "
                    f"eq.{shape_leaf} does not offer ({', '.join(facts.EQ_SHELF_TYPES[strip])}) -- not written"
                )
            else:
                stated_any = True
                targets.append(WriteTarget(
                    f"{base}/eq/{shape_leaf}", "s", f"{label}: EQ band {band} filter type",
                    _const(shape), STAGE_PROCESSING,
                ))

    model = eq.get("model")
    if model is not None:
        # `.get`, not `[...]`: a plan applied with --skip-verify can carry
        # a bank this project has no EQ facts for at all, and the answer
        # to that is a warning, not a KeyError in the middle of a run.
        available = facts.EQ_MODELS.get(strip, ())
        if model not in available:
            warnings.append(
                f"{label}: EQ model {model!r} requested, which a {strip} strip does not offer "
                f"({', '.join(available) or 'no confirmed EQ models'}) -- not written"
            )
        else:
            stated_any = True
            targets.append(WriteTarget(
                f"{base}/eq/mdl", "s", f"{label}: EQ model", _const(model), STAGE_PROCESSING,
            ))

    if eq.get("mix_pct") is not None:
        stated_any = True
        targets.append(WriteTarget(
            f"{base}/eq/mix", "f", f"{label}: EQ wet/dry mix",
            _const(float(eq["mix_pct"])), STAGE_PROCESSING,
        ))

    # Same precedent `hpf_hz` set with `flt.lc`: asking for a value is
    # asking for it to be in circuit. An explicit `on: false` still wins --
    # "these are the settings, but start it bypassed" is a real request --
    # and `on: null` with no band stated writes nothing at all, leaving the
    # console's own EQ state alone.
    on = eq.get("on")
    if on is not None:
        targets.append(WriteTarget(
            f"{base}/eq/on", "i", f"{label}: EQ {'on' if on else 'off'}",
            _const(1 if on else 0), STAGE_PROCESSING,
        ))
    elif stated_any:
        targets.append(WriteTarget(
            f"{base}/eq/on", "i", f"{label}: EQ on", _const(1), STAGE_PROCESSING,
        ))

    return targets, warnings


def _presend_eq_write_targets(base: str, strip: str, label: str, peq: dict | None) -> tuple[list[WriteTarget], list[str]]:
    """A channel's PreSend EQ (`ch.{n}.peq`), three bells and an on switch.

    Channel-only, and the guard is the same shape as the `flt` one above:
    an aux strip has no `peq` node at all (this module's own docstring has
    said so since phase 1), so a plan asking for one there gets a warning
    naming the reason rather than a write to an address that isn't there.
    """
    targets: list[WriteTarget] = []
    warnings: list[str] = []
    if not peq:
        return targets, warnings

    valid_bands = facts.presend_eq_band_ids(strip)
    if not valid_bands:
        warnings.append(
            f"{label}: PreSend EQ requested, but a {strip} strip has no peq node "
            "(confirmed: wing-compact-parameter-map.json) -- not written"
        )
        return targets, warnings

    stated_any = False
    seen: set[str] = set()
    for entry in peq.get("bands") or []:
        band = entry.get("band")
        if band in seen:
            warnings.append(f"{label}: PreSend EQ band {band!r} is stated more than once -- the later entry is ignored")
            continue
        seen.add(band)
        if band not in valid_bands:
            warnings.append(
                f"{label}: PreSend EQ band {band!r} requested, but the peq node has bands "
                f"{', '.join(valid_bands)} -- not written"
            )
            continue
        for leaf, key, unit in ((f"{band}f", "freq_hz", "frequency"),
                                (f"{band}g", "gain_db", "gain"),
                                (f"{band}q", "q", "Q")):
            if entry.get(key) is not None:
                stated_any = True
                targets.append(WriteTarget(
                    f"{base}/peq/{leaf}", "f", f"{label}: PreSend EQ band {band} {unit}",
                    _const(float(entry[key])), STAGE_PROCESSING,
                ))

    on = peq.get("on")
    if on is not None:
        targets.append(WriteTarget(
            f"{base}/peq/on", "i", f"{label}: PreSend EQ {'on' if on else 'off'}",
            _const(1 if on else 0), STAGE_PROCESSING,
        ))
    elif stated_any:
        targets.append(WriteTarget(
            f"{base}/peq/on", "i", f"{label}: PreSend EQ on", _const(1), STAGE_PROCESSING,
        ))
    return targets, warnings


def _strip_processing_targets(base: str, strip: str, label: str, processing: dict | None) -> tuple[list[WriteTarget], list[str]]:
    """A bus/Main/Matrix's own `processing` block.

    Deliberately NOT shared with a channel's, which predates it and has
    six filter/head-amp fields living on entirely different nodes
    (`flt/*`, `in/set/*`, `/io/in/...`) that no bus has at all.
    """
    targets, warnings = [], []
    if not processing:
        return targets, warnings
    eq_targets, eq_warnings = _eq_write_targets(base, strip, label, processing.get("eq"))
    targets.extend(eq_targets)
    warnings.extend(eq_warnings)
    if processing.get("tilt_db") is not None:
        if strip in facts.EQ_TILT_STRIPS:
            targets.append(WriteTarget(
                f"{base}/eq/tilt", "f", f"{label}: tilt gain",
                _const(float(processing["tilt_db"])), STAGE_PROCESSING,
            ))
        else:
            warnings.append(f"{label}: tilt requested, but a {strip} strip has no eq.tilt leaf -- not written")
    return _ordered_processing(targets), warnings


def _ordered_processing(targets: list[WriteTarget]) -> list[WriteTarget]:
    """One strip's processing writes in `preset_expand.write_order`:
    selectors (`eq/mdl`, `dyn/mdl`, `in/set/dlymode`, ...) first, then the
    values they govern, then the switches -- stable within each class.

    The preset leaves were already in this order, but the plan's own typed
    fields were not, and the two were simply concatenated: `_eq_write_
    targets` builds the bands before `eq/mdl`, and a preset's `flt/mdl` was
    written after the plan's own `flt/lcf` (seen at A22). A
    value written before its selector is re-read by the desk when the
    selector lands, and apply's forced write of governed values
    (`_governed_later`) only looks forward from a selector."""
    from atoo import preset_expand

    return sorted(targets, key=lambda t: preset_expand.write_order(t.address))


def _fader_targets(base: str, label: str, fader: dict | None) -> list[WriteTarget]:
    """Both starting-level WriteTargets for one strip this plan builds --
    a channel/aux strip, a bus, a DCA, or a Main/Matrix output -- built together
    since they share the same "plan value or documented default"
    resolution. `fader` is that plan entry's own
    `{"fader_db": ..., "muted": ...}` dict; missing or None (an older plan
    predating this field, or a mute group, which has no fader) is treated
    as "nothing stated" exactly like every other optional plan field this
    module reads, never an error. A DCA has one (2026-10-01)."""
    fader = fader or {}
    fader_db = fader.get("fader_db")
    if fader_db is None:
        fader_db = facts.FADER_DEFAULT_DB
    muted = fader.get("muted")
    if muted is None:
        muted = facts.MUTED_DEFAULT
    return [_fader_starting_target(base, label, fader_db), _mute_starting_target(base, label, muted)]


def source_name_link(group: str, sockets: list, shared_sockets:
                     dict[tuple[str, int], list[str]] | None = None
                     ) -> tuple[bool, str | None]:
    """Whether a channel's name is written to its input SOCKET (and the
    strip inherits it through `clink` = 1), or to the strip itself with
    `clink` = 0 -- and, for the second, why.

    `(True, None)` when the group has name/col/icon leaves and the socket
    feeds this strip alone; `(False, reason)` otherwise. It is the one
    decision `_channel_write_targets` makes below, pulled out so Build
    step 04 can say "written to /io/in/A/4/name" from the same rule the
    write uses rather than a copy of it (the web page's plan payload
    reads it through `webui._channel_display`).
    """
    shared_sockets = shared_sockets or {}
    if any((group, socket) in shared_sockets for socket in sockets):
        return False, f"{group} {sockets[0]} feeds several strips"
    if group not in facts.NAMEABLE_INPUT_GROUPS:
        return False, f"{group} has no nameable socket"
    return True, None


def _channel_processing_targets(channel: dict, bank: str, base: str,
                                warnings: list[str]) -> list[WriteTarget]:
    """The processing a channel states in its OWN typed fields -- the
    filters, trim/balance/invert, the EQ and the PreSend EQ -- at
    `STAGE_PROCESSING`. Head-amp gain is not here: it lives on the
    socket and is built with phantom.

    Pulled out of `_channel_write_targets` so preset
    expansion can ask "which addresses does the plan itself write on this
    strip?" with the very code that writes them, rather than a second
    list that would drift (`explicit_processing_addresses`)."""
    n = channel["channel"]
    name = channel["name"]
    strip_label = bank
    processing = channel.get("processing") or {}
    targets: list[WriteTarget] = []

    # Filters that live under `{base}/flt/*` -- confirmed absent on an aux
    # strip entirely (Festival_STANDALONE.snap). Hi-cut and tilt
    # sit alongside the existing high-pass; all three share the
    # exact same aux guard, so a plan asking for more than one of them on
    # one aux strip gets ONE combined warning naming every filter that was
    # blocked, rather than a near-duplicate line per field. This is the
    # only place that answers "does this address exist on an aux strip";
    # whether the rule should have been written for an aux strip at all is
    # a different question, and one nothing upstream asks today.
    _aux_blocked_filters = []
    if processing.get("hpf_hz") is not None:
        if bank == "aux":
            _aux_blocked_filters.append("high-pass")
        else:
            targets.append(WriteTarget(f"{base}/flt/lc", "i", f"{strip_label} {n} ({name}): high-pass on", _const(1), STAGE_PROCESSING))
            targets.append(WriteTarget(
                f"{base}/flt/lcf", "f", f"{strip_label} {n} ({name}): high-pass frequency",
                _const(float(processing["hpf_hz"])), STAGE_PROCESSING,
            ))
    if processing.get("hi_cut_hz") is not None:
        if bank == "aux":
            _aux_blocked_filters.append("hi-cut")
        else:
            targets.append(WriteTarget(f"{base}/flt/hc", "i", f"{strip_label} {n} ({name}): hi-cut on", _const(1), STAGE_PROCESSING))
            targets.append(WriteTarget(
                f"{base}/flt/hcf", "f", f"{strip_label} {n} ({name}): hi-cut frequency",
                _const(float(processing["hi_cut_hz"])), STAGE_PROCESSING,
            ))
    if processing.get("tilt_db") is not None:
        if bank == "aux":
            _aux_blocked_filters.append("tilt")
        else:
            targets.append(WriteTarget(f"{base}/flt/tf", "i", f"{strip_label} {n} ({name}): tilt on", _const(1), STAGE_PROCESSING))
            targets.append(WriteTarget(
                f"{base}/flt/tilt", "f", f"{strip_label} {n} ({name}): tilt gain",
                _const(float(processing["tilt_db"])), STAGE_PROCESSING,
            ))
    if _aux_blocked_filters:
        warnings.append(
            f"aux {n} ({name!r}): {', '.join(_aux_blocked_filters)} requested but aux strips have no "
            "flt node (confirmed: Festival_STANDALONE.snap) -- not written"
        )

    # Trim, balance, invert live under `{base}/in/set/*` -- confirmed
    # present on BOTH ch and aux (unlike `flt`), so no bank guard here.
    if processing.get("trim_db") is not None:
        targets.append(WriteTarget(
            f"{base}/in/set/trim", "f", f"{strip_label} {n} ({name}): trim",
            _const(float(processing["trim_db"])), STAGE_PROCESSING,
        ))
    if processing.get("balance_db") is not None:
        targets.append(WriteTarget(
            f"{base}/in/set/bal", "f", f"{strip_label} {n} ({name}): balance",
            _const(float(processing["balance_db"])), STAGE_PROCESSING,
        ))
    if processing.get("invert") is not None:
        targets.append(WriteTarget(
            f"{base}/in/set/inv", "i", f"{strip_label} {n} ({name}): invert",
            _const(1 if processing["invert"] else 0), STAGE_PROCESSING,
        ))

    # The EQ node, unlike `flt`, is confirmed present on BOTH ch and aux --
    # with the same four parametric bands, and different shelf-type and
    # model enums, which is why the strip class (not just "is this an
    # aux") is what gets passed down.
    eq_targets, eq_warnings = _eq_write_targets(base, bank, f"{strip_label} {n} ({name})", processing.get("eq"))
    targets.extend(eq_targets)
    warnings.extend(eq_warnings)

    # The channel's second EQ -- `peq`, the PreSend EQ. Channel-only,
    # like `flt`.
    peq_targets, peq_warnings = _presend_eq_write_targets(
        base, bank, f"{strip_label} {n} ({name})", processing.get("presend_eq"))
    targets.extend(peq_targets)
    warnings.extend(peq_warnings)

    return targets


def explicit_processing_addresses(channel: dict) -> dict[str, object]:
    """`{address under the strip: value}` for every processing leaf the
    channel's own typed fields write (`flt/lcf`, `eq/1g`, `eq/on`, ...).

    What preset expansion merges against: a preset value at one of these
    addresses is replaced by the plan's, never written beside it."""
    bank = channel.get("bank", "ch")
    if bank not in ("ch", "aux"):
        bank = "ch"
    base = f"/{bank}/{channel.get('channel')}"
    out: dict[str, object] = {}
    for target in _channel_processing_targets(channel, bank, base, []):
        if target.address.startswith(base + "/"):
            out[target.address[len(base) + 1:]] = target.compute_value(None)
    return out


def _preset_write_targets(channel: dict, bank: str, base: str, explicit: set[str],
                          warnings: list[str]) -> list[WriteTarget]:
    """The preset values `build` resolved into this channel
    (`processing.preset_values`, see `atoo/preset_expand.py`), as
    ordinary writes at `STAGE_PROCESSING` -- read back and journalled like
    every other write, so FR-X.5's verification is not a second mechanism.

    `apply` does not open a `.chn`. It writes what the plan says, and it
    re-applies the four rules `build` applied, because a plan is a file
    anyone can edit: a leaf off the processing allow-list (a send, main
    routing, fader, mute, input patch, tags) is never written; a leaf
    with no confirmed type is never guessed at; a leaf the strip does not
    have is not sent into the void; and a list choice the strip's bank
    does not offer (a channel's `dynsc/tap` `IN` on an aux) is
    not written to read back as a mismatch. Each is a warning naming the
    leaf.
    And an address the plan's own processing already writes is skipped --
    one value per address, the plan's.

    A channel that names a preset but carries no values from it (a plan
    built before expansion, or without a library) writes nothing from
    the preset, and says so."""
    from atoo import preset_expand

    n = channel["channel"]
    name = channel["name"]
    processing = channel.get("processing") or {}
    values = preset_expand.preset_values(channel)
    if values is None:
        if processing.get("preset"):
            warnings.append(
                f"{bank} {n} ({name!r}): processing names preset {processing['preset']!r}, but "
                "the plan carries none of its values (built before presets were expanded, or "
                "without a preset library) -- nothing from that preset is written; rebuild with "
                "--presets, or run `atoo presets --expand` on the plan")
        return []
    leaves = values.get("leaves")
    if not isinstance(leaves, dict):
        warnings.append(f"{bank} {n} ({name!r}): preset_values has no leaves -- nothing from the "
                        "preset is written")
        return []
    preset = values.get("preset") or processing.get("preset") or "?"
    targets: list[WriteTarget] = []
    for address in preset_expand.ordered(leaves):
        refusal = preset_expand.leaf_refusal(address, bank)
        if refusal is not None:
            warnings.append(f"{bank} {n} ({name!r}): preset {preset!r} value at {address} not "
                            f"written -- {refusal}")
            continue
        full = f"{base}/{address}"
        if full in explicit:
            continue
        value, why = preset_expand.coerce_value(address, leaves[address])
        if why is None:
            why = preset_expand.value_refusal(address, bank, value)
        if why is not None:
            warnings.append(f"{bank} {n} ({name!r}): preset {preset!r} value at {address} not "
                            f"written -- {why}")
            continue
        spec = preset_expand.leaf_type(address)
        targets.append(WriteTarget(
            full, spec.osc, f"{bank} {n} ({name}): preset {preset} {address}",
            _const(value), STAGE_PROCESSING,
        ))
    return targets


def _channel_write_targets(
    channel: dict,
    dca_index: dict[str, int],
    mute_group_index: dict[str, int],
    bus_index: dict[str, int],
    warnings: list[str],
    set_fader_levels: bool,
    shared_sockets: dict[tuple[str, int], list[str]] | None = None,
) -> list[WriteTarget]:
    shared_sockets = shared_sockets or {}
    n = channel["channel"]
    name = channel["name"]
    # "bank" distinguishes WING's two full-input-strip banks -- ch.{n} and
    # aux.{n} -- addressed identically except aux has no flt node at all
    # (handled below). Missing means an older plan predating this field;
    # "ch" was the only bank apply.py ever wrote before, so that's the
    # only sane default. An unrecognized value is never guessed past --
    # warn and fall back to "ch" rather than build an address for a bank
    # that isn't one of the two WING actually has.
    bank = channel.get("bank", "ch")
    if bank not in ("ch", "aux"):
        warnings.append(f"channel {n} ({name!r}): unrecognized bank {bank!r} -- only 'ch'/'aux' are known, treated as 'ch'")
        bank = "ch"
    strip_label = bank
    base = f"/{bank}/{n}"
    targets: list[WriteTarget] = [
        # The strip's own name. It is NOT what the desk displays when the
        # strip is patched (see `clink` below) -- it is the identity the
        # strip falls back on, and it is what `audit`'s conventions diff
        # and every offline reader compare against, so it is written
        # either way.
        WriteTarget(f"{base}/name", "s", f"{strip_label} {n} ({name}): name", _const(name), STAGE_NAMES),
    ]
    # Confirmed OSC addresses (ch.{n}.col int [1..18], ch.{n}.icon
    # int [0..999]) -- distinct from the plan's free-text `color` field,
    # which stays UI-only (no confirmed name-to-palette mapping, see
    # plan_schema.py's comment on it). None means unstated, same policy as
    # every other optional field here.
    # `col` is the console's own 1..18 index and wins if the plan states
    # it. Otherwise the free-text `color` conventions actually write in --
    # "Red", "the drums are red" -- is resolved through the palette
    # measured on hardware 2026-09-22. Before that measurement existed
    # there was no mapping, so a stated colour reached the plan and was
    # silently dropped at write time; this is the half of
    # that which needed a desk.
    col = channel.get("col")
    if col is None:
        col = facts.colour_index(channel.get("color"))
    if col is not None:
        targets.append(WriteTarget(f"{base}/col", "i", f"{strip_label} {n} ({name}): color", _const(col), STAGE_NAMES))
    if channel.get("icon") is not None:
        targets.append(WriteTarget(f"{base}/icon", "i", f"{strip_label} {n} ({name}): icon", _const(channel["icon"]), STAGE_NAMES))

    patch = channel["patch"]
    if patch is None:
        # A strip the conventions ask for "if available" whose socket was
        # not (2026-10-01; `reply_expand.build_instructed_strips`): built,
        # and left unpatched -- OFF, so it does not hear whatever the desk
        # had on it. Nothing below that lives on a socket is written.
        group, sockets = None, []
        targets.append(WriteTarget(f"{base}/in/conn/grp", "s", f"{strip_label} {n} ({name}): left unpatched (OFF)", _const("OFF"), STAGE_PATCH))
        warnings.append(f"{strip_label} {n} ({name!r}): left unpatched -- "
                        f"{(channel.get('source') or {}).get('condition') or 'its socket was taken'}; patch it at soundcheck")
    else:
        group, sockets = patch["group"], patch["sockets"]
        targets.append(WriteTarget(f"{base}/in/conn/grp", "s", f"{strip_label} {n} ({name}): patch group", _const(group), STAGE_PATCH))
        # Stereo rows get two consecutive sockets (the plan's patch.sockets,
        # which verify_plan checks against the row's stereo flag); WING's own
        # in/conn.in is a single base-socket int -- the second socket of a
        # stereo pair isn't addressed here at all, because it's implied by the
        # SOURCE's own stereo mode (/io/in/{grp}/{n}/mode, written below, on
        # BOTH sockets of the pair), not by anything under {base}/in/conn.
        targets.append(WriteTarget(f"{base}/in/conn/in", "i", f"{strip_label} {n} ({name}): patch socket", _const(sockets[0]), STAGE_PATCH))
        if patch.get("stated") is False:
            warnings.append(f"{strip_label} {n} ({name!r}): patch socket was not stated in the input list and was assigned during generation -- verify before trusting this write")

    # --- The alternate input ----------------------
    #
    # Written only where the plan states one: an unset alternate breaks
    # nothing, so the desk's own is left alone. `.altin` is the same
    # 1-based socket index as `in/conn/in`, written as the number the desk
    # shows; its GET offset is corrected on read (console_facts, INFERRED
    # from A7 until a desk confirms it -- see the session checklist).
    alt = channel.get("alt_patch")
    if isinstance(alt, dict) and isinstance(alt.get("group"), str) and alt.get("sockets"):
        alt_group, alt_sockets = alt["group"], alt["sockets"]
        targets.append(WriteTarget(f"{base}/in/conn/altgrp", "s", f"{strip_label} {n} ({name}): alternate patch group", _const(alt_group), STAGE_PATCH))
        targets.append(WriteTarget(f"{base}/in/conn/altin", "i", f"{strip_label} {n} ({name}): alternate patch socket", _const(alt_sockets[0]), STAGE_PATCH))
        if alt.get("stated") is False:
            warnings.append(f"{strip_label} {n} ({name!r}): alternate socket was counted during generation, not stated -- verify before trusting this write")
        # Width lives on the socket, for an alternate as for a main patch;
        # `verify_plan` refuses a socket two uses would give two widths.
        if alt_group in _MODE_CAPABLE_GROUPS:
            alt_mode = "ST" if channel["source"]["stereo"] else "M"
            for socket in alt_sockets:
                targets.append(WriteTarget(
                    f"/io/in/{alt_group}/{socket}/mode", "s",
                    f"{strip_label} {n} ({name}): {alt_mode} width on alternate {alt_group} {socket}",
                    _const(alt_mode), STAGE_PHANTOM,
                ))
    # Every strip this plan builds is put back on its MAIN input. A strip
    # left on its alternate after a virtual soundcheck is a strip that does
    # not hear the stage, and the main patch just written above would be
    # inaudible. Not a guess at direction: 0 = main is settled by the
    # snapshots (console_facts, `ALT_PATCH_MAIN`). The per-strip selector
    # only -- the GLOBAL switch (`/io/altsw`) is never written, since its
    # direction is inferred from one flip; `audit` reports it (C005).
    targets.append(WriteTarget(
        f"{base}/in/set/altsrc", "i",
        f"{strip_label} {n} ({name}): listening to its main input, not its alternate",
        _const(facts.ALT_PATCH_MAIN), STAGE_PATCH))

    # --- Who owns the name: the socket, not the strip -------------------
    #
    # `clink` (protocol PDF p.48, "custom link") is the desk's "Link
    # Customization to Source" switch, and it DEFAULTS TO ON. While it is
    # on, the strip displays the name, colour and icon of the input SOCKET
    # it is patched to; the strip's own values are stored, read back
    # correctly, and never shown.
    #
    # That cost a whole apply on 2026-09-22: the journal reported all 19
    # channel names as `match` while the desk showed "Channel names are
    # NOT present." A write that verifies and changes nothing an engineer
    # can see is the worst failure shape this project has.
    #
    # The first fix was to unlink -- write clink=0 and name the strip.
    # The better approach is to set the name, icon and color on the
    # source, and let the 'Link Customization to Source' flag flow the
    # customization to the channel, since that is the default. That is
    # right, and for a better reason than going with the desk's grain:
    # **`input.csv` is one row per
    # PHYSICAL INPUT.** The name originates at the socket. Naming the
    # strip and cutting the link is the distortion; naming the socket is
    # what the input list already says.
    #
    # Staged after STAGE_PATCH for exactly the reason phantom is (below):
    # naming a socket this plan has not yet patched to would put the name
    # on the wrong physical input, and unlike phantom it would look right.
    # A socket feeding more than one strip is the exception, and it is a
    # deliberate one: a separate strip for monitors, or one jack reused
    # between acts at a festival (`atoo/domain/knowledge.md`). One
    # socket cannot carry two names, so those strips keep their own: the
    # channel and source customization are unlinked and the channels
    # customized separately, while the source is given a composite name.
    # The socket's label is
    # written once by `_shared_source_name_targets`, not fought over here.
    linked, why = source_name_link(group, sockets, shared_sockets)

    if linked:
        targets.append(WriteTarget(
            f"{base}/clink", "i",
            f"{strip_label} {n} ({name}): link customization to source "
            f"(so {group} {sockets[0]}'s name is what the desk shows)",
            _const(1), STAGE_NAMES,
        ))
        # Both sockets of a stereo pair, so the name is right whichever
        # one the surface reads and whichever way the pair is later split.
        for socket in sockets:
            targets.append(WriteTarget(
                f"/io/in/{group}/{socket}/name", "s",
                f"{strip_label} {n} ({name}): name on source {group} {socket}",
                _const(name), STAGE_SOURCE_LABEL,
            ))
            if col is not None:
                targets.append(WriteTarget(
                    f"/io/in/{group}/{socket}/col", "i",
                    f"{strip_label} {n} ({name}): colour on source {group} {socket}",
                    _const(col), STAGE_SOURCE_LABEL,
                ))
            if channel.get("icon") is not None:
                targets.append(WriteTarget(
                    f"/io/in/{group}/{socket}/icon", "i",
                    f"{strip_label} {n} ({name}): icon on source {group} {socket}",
                    _const(channel["icon"]), STAGE_SOURCE_LABEL,
                ))
    else:
        # Either the source has no name/col/icon leaf at all (BUS, MAIN,
        # MTX, OFF -- PDF pp.40-43), or the socket is shared and cannot
        # speak for this strip alone. Both mean: break the link and let the
        # strip's own name, written above, be the one displayed.
        targets.append(WriteTarget(
            f"{base}/clink", "i",
            f"{strip_label} {n} ({name}): unlink customization from source "
            f"({why}, so the strip carries its own name)",
            _const(0), STAGE_NAMES,
        ))
        # The strip's own col/icon are already written unconditionally
        # further up; on the unlinked path they are simply the ones that
        # end up visible.

    processing = channel["processing"]

    # Phantom power lives on the physical SOURCE the strip is patched to,
    # not on the strip itself (wing-console-model.md) -- this is why it
    # must be built AFTER the patch target above (STAGE_PHANTOM >
    # STAGE_PATCH): if the patch itself is wrong, phantom would otherwise
    # land on the wrong physical socket with no way to notice from this
    # write alone. Unaffected by bank -- ch and aux strips share the same
    # physical source vocabulary.
    #
    # On EVERY socket of the patch: a stereo pair is two
    # sources, each with its own 48V, and writing only the first left the
    # second condenser of every pair silent. Each socket gets its own
    # input-list row's value (`inferred.socket_phantom`).
    per_socket = inferred.socket_phantom(channel)
    phantom_wanted = any(on for _socket, on in per_socket)
    if group in _VPH_CAPABLE_GROUPS:
        one_value = inferred.pair_phantom_is_inferred(channel)
        for i, (socket, on) in enumerate(per_socket):
            why = (" (one phantom value for the pair, read as both sockets')"
                   if one_value and i else "")
            targets.append(WriteTarget(
                f"/io/in/{group}/{socket}/vph", "i",
                f"{strip_label} {n} ({name}): phantom power on {group} {socket}{why}",
                _const(1 if on else 0), STAGE_PHANTOM,
            ))
    elif phantom_wanted:
        warnings.append(
            f"{strip_label} {n} ({name!r}): phantom power requested but patched to group {group!r}, "
            f"which has no confirmed phantom-power address (.vph only confirmed for "
            f"{', '.join(sorted(_VPH_CAPABLE_GROUPS))}) -- not written"
        )

    # Head-amp gain: same "lives on the physical SOURCE,
    # not the strip" shape as phantom above, and depends on the patch write
    # for the same reason (STAGE_PHANTOM), so it's built right alongside
    # phantom rather than down with the rest of `processing` below. Reuses
    # _VPH_CAPABLE_GROUPS rather than a separate constant: confirmed
    # against the Compact parameter map that `.g`
    # exists for exactly the same groups as `.vph` (A/B/C/LCL) and no
    # others -- the same physical mic/line inputs that carry phantom power
    # also carry a head amp, which lines up with wing-console-model.md's
    # own "gain/phantom/mute/polarity/..." grouping for a physical source.
    #
    # On EVERY socket of the patch, like phantom and width: a stereo pair
    # is two sources and the desk holds a gain on each. Once the pair is in
    # stereo mode the desk carries the first socket's gain onto the second
    # (every pair in the captures on file reads the same on both), so a
    # plan that wrote only the first left the second reading that value
    # without the plan having named it. The reset to initialized then
    # counted the second socket as its own to put back to 0, and a preview
    # taken straight after an apply proposed it, again and again. The plan
    # now states both, so both are the plan's, whether or not the desk
    # links them.
    gain_db = processing.get("gain_db")
    if gain_db is not None:
        if group in _VPH_CAPABLE_GROUPS:
            for i, socket in enumerate(sockets):
                why = " (the pair's second socket carries the same gain)" if i else ""
                targets.append(WriteTarget(
                    f"/io/in/{group}/{socket}/g", "f",
                    f"{strip_label} {n} ({name}): head-amp gain on {group} {socket}{why}",
                    _const(float(gain_db)), STAGE_PHANTOM,
                ))
        else:
            warnings.append(
                f"{strip_label} {n} ({name!r}): head-amp gain requested but patched to group {group!r}, "
                f"which has no confirmed head-amp-gain address (.g only confirmed for "
                f"{', '.join(sorted(_VPH_CAPABLE_GROUPS))}) -- not written"
            )

    # Stereo/mono width, same "lives on the source, not the strip" shape
    # as phantom -- also depends on the patch already having landed, so
    # this stays at STAGE_PHANTOM alongside it, not its own earlier stage.
    stereo_wanted = bool(channel["source"]["stereo"])
    wing_mode = "ST" if stereo_wanted else "M"
    if group in _MODE_CAPABLE_GROUPS:
        for socket in sockets:
            targets.append(WriteTarget(
                f"/io/in/{group}/{socket}/mode", "s",
                f"{strip_label} {n} ({name}): {wing_mode} width on {group} {socket}",
                _const(wing_mode), STAGE_PHANTOM,
            ))
    else:
        warnings.append(
            f"{strip_label} {n} ({name!r}): patched to group {group!r}, which has no confirmed stereo/mono "
            f"width address (.mode only confirmed for {', '.join(sorted(_MODE_CAPABLE_GROUPS))}) -- not written"
        )

    # The processing the plan states in its own typed fields, and then
    # the preset values `build` resolved into it.
    # Built in that order and merged BY ADDRESS: an address the plan's own
    # processing writes is never also written from the preset -- the plan
    # wins, and `build`/`verify` have already said so at INFO.
    explicit = _channel_processing_targets(channel, bank, base, warnings)
    targets.extend(_ordered_processing(explicit + _preset_write_targets(
        channel, bank, base, {t.address for t in explicit}, warnings)))

    dca_names = channel.get("dca") or []
    mute_names = channel.get("mute_group") or []
    if dca_names or mute_names:
        missing_dca = [d for d in dca_names if d not in dca_index]
        missing_mute = [m for m in mute_names if m not in mute_group_index]
        for missing in missing_dca:
            warnings.append(f"{strip_label} {n} ({name!r}): DCA {missing!r} has no console index in this plan -- membership not written for it")
        for missing in missing_mute:
            warnings.append(f"{strip_label} {n} ({name!r}): mute group {missing!r} has no console index in this plan -- membership not written for it")
        dca_idxs = [dca_index[d] for d in dca_names if d in dca_index]
        mute_idxs = [mute_group_index[m] for m in mute_names if m in mute_group_index]
        if dca_idxs or mute_idxs:
            targets.append(WriteTarget(
                f"{base}/tags", "s", f"{strip_label} {n} ({name}): DCA/mute-group tags",
                lambda current, d=dca_idxs, m=mute_idxs: _merge_tags(current, d, m),
                STAGE_TAGS,
            ))

    for send in channel.get("bus_sends", []):
        bus_name = send["bus"]
        bidx = bus_index.get(bus_name)
        if bidx is None:
            warnings.append(f"{strip_label} {n} ({name!r}): send to bus {bus_name!r}, which has no console index in this plan -- send not written")
            continue
        send_base = f"{base}/send/{bidx}"
        targets.append(WriteTarget(f"{send_base}/on", "i", f"{strip_label} {n} ({name}): send to {bus_name} on", _const(1), STAGE_SENDS))
        level = send.get("level_db")
        if level is not None:
            targets.append(WriteTarget(f"{send_base}/lvl", "f", f"{strip_label} {n} ({name}): send to {bus_name} level", _const(float(level)), STAGE_SENDS))
        wing_mode = _SEND_MODE_TO_WING.get(send.get("mode"))
        if wing_mode is not None:
            targets.append(WriteTarget(f"{send_base}/mode", "s", f"{strip_label} {n} ({name}): send to {bus_name} mode", _const(wing_mode), STAGE_SENDS))
        elif send.get("mode") is not None:
            warnings.append(f"{strip_label} {n} ({name!r}): send to {bus_name!r} has unrecognized mode {send['mode']!r} -- mode not written")

    # A channel routed straight to Main, no bus and no DCA at
    # all (the plan's channel["main_routes"], from a "## Processing"
    # "X routes directly to Main" statement). Distinct from bus_sends
    # above (`ch.{n}/send/{bus}`, a channel feeding a BUS) and from a
    # bus's own `bus.{n}/main/{m}` routing (_bus_write_targets below,
    # this module's separate FEED-from-a-bus case) -- this is the
    # channel's own `ch.{n}/main/{m}` node, confirmed present with
    # exactly on/lvl/pre (see MAIN_ROUTE_LEVEL_DEFAULT_DB above).
    #
    # **The list is the complete statement of this strip's direct Main
    # routing** (2026-09-27). Every Main the desk has is written: ON for
    # each listed route, OFF for every other. A factory WING ships every
    # strip -- ch and aux alike -- on Main 1 (console_facts.
    # FACTORY_STRIP_MAIN_INDEX), so writing only the listed routes left a
    # channel with `main_routes: []` ("reaches Main only through a mix bus,
    # or not at all") on Main 1 as well: the festival's click track on the
    # PA, and its drums and vocals on Main twice, directly and through
    # their busses. A dry run could not see it, because the address was
    # never in the write set. Not a judgement call: the plan says the strip
    # does not route there, and a desk left routing it is a patch that
    # does not work.
    listed_mains: set[int] = set()
    for route in channel.get("main_routes", []):
        route_index = route["index"]
        listed_mains.add(route_index)
        main_base = f"{base}/main/{route_index}"
        targets.append(WriteTarget(f"{main_base}/on", "i", f"{strip_label} {n} ({name}): routed directly to Main {route_index}", _const(1), STAGE_ROUTING))
        targets.append(WriteTarget(f"{main_base}/lvl", "f", f"{strip_label} {n} ({name}): direct Main {route_index} level", _const(MAIN_ROUTE_LEVEL_DEFAULT_DB), STAGE_ROUTING))
        targets.append(WriteTarget(f"{main_base}/pre", "i", f"{strip_label} {n} ({name}): direct Main {route_index} pre/post-fader", _const(MAIN_ROUTE_PRE_DEFAULT), STAGE_ROUTING))
    for main_index in facts.main_indices():
        if main_index in listed_mains:
            continue
        targets.append(WriteTarget(
            f"{base}/main/{main_index}/on", "i",
            f"{strip_label} {n} ({name}): NOT routed directly to Main {main_index} -- the plan lists no direct route there",
            _const(0), STAGE_ROUTING))

    if set_fader_levels:
        # Job 3: a strip this plan builds gets its starting state --
        # exactly what the conventions stated (channel["fader"], which
        # reaches the plan from a "## Processing" rule), or unity/
        # unmuted when they stated nothing -- so soundcheck can verify
        # signal actually flows. See the module docstring. Both banks
        # carry fdr/mute (confirmed key list for aux, same as ch), so
        # this isn't bank-conditional the way flt is.
        targets.extend(_fader_targets(base, f"{strip_label} {n} ({name})", channel.get("fader")))

    return targets


def _group_name_targets(plan: dict, warnings: list[str],
                        set_fader_levels: bool = True) -> list[WriteTarget]:
    targets: list[WriteTarget] = []
    for name, entry in plan.get("dcas", {}).items():
        idx = entry["index"]
        if idx > facts.CAPACITY["dca"]:
            warnings.append(f"DCA {name!r} (index {idx}) exceeds this console's capacity ({facts.CAPACITY['dca']}) -- not applying")
            continue
        targets.append(WriteTarget(f"/dca/{idx}/name", "s", f"DCA {idx}: name", _const(name), STAGE_NAMES))
        # A created DCA starts with its fader at unity. That reached the plan
        # (`fader: {fader_db: 0}`) and never the
        # desk -- apply wrote a DCA's name and nothing else. A DCA is a
        # strip with a fader and a mute like a bus, and takes the same
        # starting level: the plan's, else unity, unmuted.
        if set_fader_levels:
            targets.extend(_fader_targets(f"/dca/{idx}", f"DCA {idx} ({name})", entry.get("fader")))
    for name, entry in plan.get("mute_groups", {}).items():
        idx = entry["index"]
        if idx > facts.CAPACITY["mgrp"]:
            warnings.append(f"mute group {name!r} (index {idx}) exceeds this console's capacity ({facts.CAPACITY['mgrp']}) -- not applying")
            continue
        targets.append(WriteTarget(f"/mgrp/{idx}/name", "s", f"mute group {idx}: name", _const(name), STAGE_NAMES))
    return targets


def bus_col(entry: dict) -> int | None:
    """The desk's 1..18 colour index for a bus plan entry, or None.

    `col` (set by hand) wins; otherwise the stated colour name `color` is
    resolved through `console_facts.colour_index`, the same mapping a
    channel's `color` takes. None when neither is stated, or when the name
    is not one of the desk's eighteen. Shared by apply and step 04's
    `bus_display`, so the chip shows the colour apply writes."""
    col = entry.get("col")
    if isinstance(col, int) and not isinstance(col, bool):
        return col
    return facts.colour_index(entry.get("color"))


def _bus_write_targets(
    plan: dict, dca_index: dict[str, int], mute_group_index: dict[str, int],
    warnings: list[str], set_fader_levels: bool,
) -> list[WriteTarget]:
    targets: list[WriteTarget] = []
    for name, entry in plan.get("busses", {}).items():
        idx = entry["index"]
        if idx > facts.CAPACITY["bus"]:
            warnings.append(f"bus {name!r} (index {idx}) exceeds this console's capacity ({facts.CAPACITY['bus']}) -- not applying")
            continue
        targets.append(WriteTarget(f"/bus/{idx}/name", "s", f"bus {idx} ({name}): name", _const(name), STAGE_NAMES))
        # Confirmed OSC addresses (bus.{n}.col int [1..18],
        # bus.{n}.icon int [0..999]). None means unstated.
        # `col` wins when set; otherwise the colour NAME the conventions
        # stated (`color`) resolves through the measured palette, exactly
        # as a channel's does. A name the desk lacks resolves to None and
        # writes nothing -- verify's `bus.colour-not-writable` says so.
        col = bus_col(entry)
        if col is not None:
            targets.append(WriteTarget(f"/bus/{idx}/col", "i", f"bus {idx} ({name}): color", _const(col), STAGE_NAMES))
        if entry.get("icon") is not None:
            targets.append(WriteTarget(f"/bus/{idx}/icon", "i", f"bus {idx} ({name}): icon", _const(entry["icon"]), STAGE_NAMES))
        # A bus's own mono/stereo width -- confirmed OSC
        # address /bus/{n}/busmono (int [0..1]) in the parameter map.
        # Never None by the time it reaches here: `_build_write_targets`
        # decides an unstated width first (`inferred.with_decisions`:
        # the mono/stereo decision may not be left to
        # whatever the desk had). The guard stays for a caller that
        # builds bus targets without going through it.
        if entry.get("mono") is not None:
            targets.append(WriteTarget(
                f"/bus/{idx}/busmono", "i", f"bus {idx} ({name}): mono width",
                _const(1 if entry["mono"] else 0), STAGE_ROUTING,
            ))
        # A bus can state BOTH a main route AND a dedicated
        # output at once (Festival_STANDALONE.snap's VOCALS bus:
        # bus.7.main.1.on=true, plus io.out.A.44/io.out.SC.4 both
        # sourcing from it) -- every destination the plan states gets
        # written, not just one. `destinations` is authoritative when
        # non-empty; an older/generated plan that only sets the singular
        # `destination` still applies exactly as before.
        destinations = entry.get("destinations")
        if not destinations:
            single = entry.get("destination")
            destinations = [single] if single is not None else []
        listed_mains: set[int] = set()
        for destination in destinations:
            if destination["type"] == "main":
                # Which of the console's up to 4 Mains -- the plan now
                # states it (destination["index"]); an older plan that
                # only says {"type": "main"} defaults to 1, same value
                # this module always hardcoded before the plan carried an
                # index at all.
                main_index = destination.get("index", 1)
                listed_mains.add(main_index)
                targets.append(WriteTarget(f"/bus/{idx}/main/{main_index}/on", "i", f"bus {idx} ({name}): routed to Main {main_index}", _const(1), STAGE_ROUTING))
            elif destination["type"] == "dedicated_output":
                # A dedicated output can itself fan out to
                # several physical sockets at once -- `patches` (plural)
                # is authoritative when non-empty; `patch` (singular)
                # covers a plan that only ever set one. Plans from before
                # the rename to `patch`/`patches` say `sockets`/`socket`: plan_compat reads both.
                for socket in plan_compat.output_patches(destination):
                    group = socket["group"]
                    for position, sock in enumerate(socket["sockets"]):
                        targets.append(WriteTarget(f"/io/out/{group}/{sock}/grp", "s", f"bus {idx} ({name}): output {group} {sock} source", _const("BUS"), STAGE_ROUTING))
                        targets.append(WriteTarget(f"/io/out/{group}/{sock}/in", "i", f"bus {idx} ({name}): output {group} {sock} channel", _const(_output_slot(idx, position)), STAGE_ROUTING))
                # else: no physical socket to write. verify_plan refuses such a
                # plan up front (bus.unresolved-destination), so reaching here
                # means --skip-verify.
            else:
                # Schema allows other destination types (currently "matrix")
                # that this module has no confirmed write path for -- there is
                # no documented `bus.{n}` -> matrix routing node anywhere in
                # the console model notes, and inventing one would
                # be exactly the guess this project refuses to make elsewhere.
                # A bus feeding a Matrix is expressed elsewhere now (the matrix's own outputs[name].fed_by), so this branch is
                # legacy-schema defense, not a live path -- say so rather
                # than silently doing nothing.
                warnings.append(
                    f"bus {name!r}: destination type {destination['type']!r} is recorded in the plan "
                    "but this module has no confirmed way to write it yet -- routing not applied"
                )
        # **The destinations are the complete statement of this bus's
        # direct Main routing**, as `main_routes` is for a
        # strip (`_channel_write_targets`). Every Main the desk has is
        # written: ON above for each listed one, OFF here for the rest. A
        # factory WING ships bus 9-16 on Main 1
        # (console_facts.FACTORY_BUS_MAIN_ON_FROM), so writing only the
        # listed Mains left a monitor or FX bus the plan puts on 9-16 on
        # the PA as well. Not a judgement call: the plan says the bus does
        # not route there. Written even when `destinations` is empty
        # (--skip-verify past bus.no-destination): the plan still lists no
        # Main for it.
        for main_index in facts.main_indices():
            if main_index in listed_mains:
                continue
            shipped_on = facts.factory_bus_main_on(idx, main_index)
            targets.append(WriteTarget(
                f"/bus/{idx}/main/{main_index}/on", "i",
                f"bus {idx} ({name}): NOT routed to Main {main_index} -- the plan lists no route there"
                + (f" (the desk ships bus {facts.FACTORY_BUS_MAIN_ON_FROM}-{facts.CAPACITY['bus']} on it)" if shipped_on else ""),
                _const(0), STAGE_ROUTING))
        # If destinations is empty: verify_plan already refused this plan
        # (bus.no-destination) unless --skip-verify was passed -- no route
        # is switched ON either way (the OFF writes above still go out),
        # but that's independent of the bus's OWN starting fader/mute
        # below: /bus/{idx}/fdr and /bus/{idx}/mute exist on real hardware
        # regardless of whether this run could resolve where the bus's
        # signal goes, so an unresolved destination must not silently skip
        # Job 3 for this bus too.

        # A bus can be a DCA/mute-group member in its own right (confirmed against Festival_STANDALONE.snap: its MONITORS mute
        # group holds busses, not channels) -- same tags mechanism as a
        # channel, same merge helper, so nothing else here changes.
        bus_dca_names = entry.get("dca") or []
        bus_mute_names = entry.get("mute_group") or []
        if bus_dca_names or bus_mute_names:
            missing_dca = [d for d in bus_dca_names if d not in dca_index]
            missing_mute = [m for m in bus_mute_names if m not in mute_group_index]
            for missing in missing_dca:
                warnings.append(f"bus {name!r}: DCA {missing!r} has no console index in this plan -- membership not written for it")
            for missing in missing_mute:
                warnings.append(f"bus {name!r}: mute group {missing!r} has no console index in this plan -- membership not written for it")
            dca_idxs = [dca_index[d] for d in bus_dca_names if d in dca_index]
            mute_idxs = [mute_group_index[m] for m in bus_mute_names if m in mute_group_index]
            if dca_idxs or mute_idxs:
                targets.append(WriteTarget(
                    f"/bus/{idx}/tags", "s", f"bus {idx} ({name}): DCA/mute-group tags",
                    lambda current, d=dca_idxs, m=mute_idxs: _merge_tags(current, d, m),
                    STAGE_TAGS,
                ))

        if set_fader_levels:
            targets.extend(_fader_targets(f"/bus/{idx}", f"bus {idx} ({name})", entry.get("fader")))

        # The bus's own EQ/tilt. Outside the
        # set_fader_levels guard above on purpose -- `--no-faders` is about
        # not moving levels on a live desk, and an EQ curve is a starting
        # state like a name or a route, not a level.
        proc_targets, proc_warnings = _strip_processing_targets(
            f"/bus/{idx}", "bus", f"bus {idx} ({name})", entry.get("processing"))
        warnings.extend(proc_warnings)
        # The bus preset and the effect it inserts, in the
        # order the desk needs them -- the engine's model, then the
        # parameters that model has, then the bus's own processing, then
        # the insert pointed at the engine and switched on.
        fx_targets, insert_targets = _bus_fx_targets(name, entry, idx, warnings)
        preset_targets = _bus_preset_targets(
            name, entry, idx, {t.address for t in proc_targets}, warnings)
        targets.extend(fx_targets)
        targets.extend(_ordered_processing(proc_targets + preset_targets))
        targets.extend(insert_targets)
    return targets


def _bus_preset_targets(name: str, entry: dict, idx: int, explicit: set[str],
                        warnings: list[str]) -> list[WriteTarget]:
    """A bus preset's processing values (`busses[X].preset_values.leaves`,
    `atoo/bus_presets.py`) as writes at `STAGE_PROCESSING` -- the
    channel preset's rules (`_preset_write_targets`) on the bus allow-list:
    nothing off it, nothing untyped, nothing the bus's own typed processing
    already writes."""
    from atoo import bus_presets

    values = bus_presets.preset_values(entry)
    if values is None:
        if entry.get("preset"):
            warnings.append(
                f"bus {idx} ({name!r}): names bus preset {entry['preset']!r}, but the plan "
                "carries none of its values -- neither its processing nor its effect is written; "
                "rebuild with --presets, or run `atoo presets --expand` on the plan")
        return []
    leaves = values.get("leaves") if isinstance(values.get("leaves"), dict) else {}
    preset = values.get("preset") or entry.get("preset") or "?"
    targets: list[WriteTarget] = []
    for address in leaves:
        full = f"/bus/{idx}/{address}"
        if full in explicit:
            continue
        why = bus_presets.leaf_refusal(address)
        value = None
        if why is None:
            value, why = bus_presets.coerce_leaf(address, leaves[address])
        if why is not None:
            warnings.append(f"bus {idx} ({name!r}): bus preset {preset!r} value at {address} not "
                            f"written -- {why}")
            continue
        targets.append(WriteTarget(
            full, bus_presets.leaf_osc(address), f"bus {idx} ({name}): preset {preset} {address}",
            _const(value), STAGE_PROCESSING))
    return targets


def _bus_fx_targets(name: str, entry: dict, idx: int,
                    warnings: list[str]) -> tuple[list[WriteTarget], list[WriteTarget]]:
    """`(engine writes, insert writes)` for each effect a bus preset
    inserts: `/fx/{e}/mdl`, then each parameter, and then
    `/bus/{idx}/{point}/ins` = `FX{e}` and `/bus/{idx}/{point}/on` = 1.

    The insert is switched ON whatever the preset was saved with: an FX
    bus with its effect bypassed is silent (build said so at INFO,
    `fx.insert-switched-on`). An effect verify refuses -- a model no engine
    offers, an engine that cannot hold it, no engine at all -- writes
    nothing, insert included, and says why; a single parameter value the
    engine has no choice for is left out, and said."""
    from atoo import bus_presets, fx_engines

    engine_writes: list[WriteTarget] = []
    insert_writes: list[WriteTarget] = []
    label = f"bus {idx} ({name})"
    for ins in bus_presets.inserts(entry):
        point, model, engine = ins.get("point"), ins.get("model"), ins.get("engine")
        if point not in facts.INSERT_POINTS["bus"]:
            warnings.append(f"{label}: insert point {point!r} is not one a bus has -- not written")
            continue
        if not fx_engines.is_known_model(model):
            warnings.append(f"{label}: effect {model!r} is offered by no FX engine -- not loaded, "
                            "and the insert is not set")
            continue
        if not isinstance(engine, int) or engine not in fx_engines.engines_for(model):
            warnings.append(f"{label}: {model} has no usable engine in the plan "
                            f"({'none allocated' if engine is None else f'FX{engine}'}) -- not "
                            "loaded, and the insert is not set")
            continue
        engine_writes.append(WriteTarget(
            fx_engines.engine_address(engine), "s", f"{label}: FX{engine} effect {model}",
            _const(model), STAGE_PROCESSING))
        for param, raw in (ins.get("parameters") or {}).items():
            if not fx_engines.is_engine_parameter(param):
                continue
            value, why, _ = fx_engines.coerce_param(param, raw)
            if why is not None:
                warnings.append(f"{label}: FX{engine} {model} {param} not written -- {why}")
                continue
            osc, _ = fx_engines.param_type(param, raw)
            engine_writes.append(WriteTarget(
                fx_engines.engine_address(engine, param), osc,
                f"{label}: FX{engine} {model} {param}", _const(value), STAGE_PROCESSING))
        word = "pre-insert" if point == "preins" else "post-insert"
        insert_writes.append(WriteTarget(
            f"/bus/{idx}/{point}/ins", "s", f"{label}: {word} -> FX{engine} ({model})",
            _const(fx_engines.insert_value(engine)), STAGE_PROCESSING))
        insert_writes.append(WriteTarget(
            f"/bus/{idx}/{point}/on", "i", f"{label}: {word} on"
            + (" (the preset was saved bypassed)" if ins.get("saved_on") is False else ""),
            _const(1), STAGE_PROCESSING))
    return engine_writes, insert_writes


_OUTPUT_KIND_TO_WING_GRP = {"main": "MAIN", "matrix": "MTX"}


def bus_indices(plan: dict) -> dict[str, int]:
    """Each bus's console index, by name -- the number every `/bus/{n}`
    write and every channel's send to that bus is addressed by. The one
    place it is read: `_build_write_targets` writes by it, and step 04's
    table (`webui._bus_display`) draws it, so the page cannot show a
    different number from the one apply writes."""
    return {name: e["index"] for name, e in (plan.get("busses") or {}).items()
            if isinstance(e, dict) and isinstance(e.get("index"), int)}


def desk_label(kind: str, index: int, bank: str = "ch") -> str:
    """How the desk itself labels an object: a channel by its number
    ("3", or "Aux 3" on the aux bank), a bus "B3", a Main "M1" and a
    Matrix "MX1" -- the WING's own spelling (`console_facts.
    TALK_DESTINATIONS`: B1..B16, MX1..MX8, M1..M4; `/send/MX{m}`)."""
    if kind == "channel":
        return f"Aux {index}" if bank == "aux" else str(index)
    prefix = {"bus": "B", "main": "M", "matrix": "MX"}.get(kind)
    if prefix is None:
        raise ValueError(f"no desk label for {kind!r}")
    return f"{prefix}{index}"


def _declared_output_patches(plan: dict) -> dict[tuple[str, int], tuple[str, int]]:
    """Every physical output socket this plan states a bus/Main/Matrix
    routes to, and what it routes it to: `{(group, socket): (grp, in)}`.
    Two callers need exactly this set to tell "the console has
    physical routing this plan never asked for" apart from "the console
    matches the plan" -- `audit.py`'s CV009 rule (read-only, reports),
    and `_clean_write_targets` below (`apply --clean-output-sockets`,
    opt-in, actually disconnects it). Mirrors the socket-walking shape of
    `_bus_write_targets`/the output-entries loop below (the
    multi-socket fan-out, the `_output_slot` L/R math) closely
    enough that neither caller can quietly disagree with what a normal
    apply run would actually write, but deliberately NOT implemented by
    calling `_build_write_targets` itself -- that function assumes a
    fully-resolved plan (e.g. every channel's patch has a socket), an
    invariant neither caller has any need to require just to answer a
    question about output routing, and a partial/unresolved plan is
    exactly the kind `audit` in particular is often run against.
    Malformed entries (bad shapes from a fixture or a plan mid-edit) are
    skipped, not raised -- a caller checking what a plan declares is not
    a place to crash over a shape it doesn't need."""
    declared: dict[tuple[str, int], tuple[str, int]] = {}

    def record(group: object, socket_numbers: object, wing_grp: str, index: object) -> None:
        if not isinstance(group, str) or not isinstance(socket_numbers, list) or not isinstance(index, int):
            return
        for position, sock in enumerate(socket_numbers):
            if isinstance(sock, int):
                declared[(group, sock)] = (wing_grp, _output_slot(index, position))

    for name, bus in (plan.get("busses") or {}).items():
        # `isinstance`, not `bus or {}`: a truthy non-dict (a bare LIST,
        # which an archived smallband plan from a small local model really
        # has for a *dca* entry, so the shape is not hypothetical) sails
        # through `or` and then raises AttributeError on `.get` -- which
        # this function's own docstring promises it does not do. It was found
        # through the amend path: an amend reads an arbitrary already-applied plan off
        # disk, including one a model produced on a bad night.
        if not isinstance(bus, dict):
            continue
        idx = bus.get("index")
        if not isinstance(idx, int):
            continue
        destinations = bus.get("destinations")
        if not destinations:
            single = bus.get("destination")
            destinations = [single] if single is not None else []
        for destination in destinations:
            if not isinstance(destination, dict) or destination.get("type") != "dedicated_output":
                continue
            for socket in plan_compat.output_patches(destination):
                if isinstance(socket, dict):
                    record(socket.get("group"), socket.get("sockets"), "BUS", idx)

    for name, out in (plan.get("outputs") or {}).items():
        if not isinstance(out, dict):
            continue  # same non-dict guard as the bus loop above
        wing_grp = _OUTPUT_KIND_TO_WING_GRP.get(out.get("kind"))
        index = out.get("index")
        if wing_grp is None or not isinstance(index, int):
            continue
        for socket in plan_compat.output_patches(out):
            if isinstance(socket, dict):
                record(socket.get("group"), socket.get("sockets"), wing_grp, index)

    return declared


# --------------------------------------------------------------------------
# Expansion bays: is there anything in the slot this plan patches from?
#
# --------------------------------------------------------------------------
#
# `console_facts.INPUT_SOCKETS` bounds CRD and MOD at 64 each, and that is
# an ADDRESS SPACE, not an inventory: the firmware answers
# `/io/in/MOD/1..64` on a console with an empty module bay, which is how
# every WING leaves the factory (`/$syscfg/opt_mod` defaults to `NONE`).
# So `MOD 1` verifies clean, applies clean, reads back `MOD` -- and the
# channel is silent. Measured on a Compact, 2026-09-21, and
# recorded as `console_facts.UNFITTED_BAY_PATCH_IS_ACCEPTED`: the desk
# accepts the patch with no error, no refusal and no clamp.
#
# **Why the check lives on this side of the wire and not in
# `verify_plan`.** Verification is offline by contract (FR-1.2, and
# `verify_plan`'s own module docstring: "Everything it checks comes from
# console_facts.py ... or from the input list itself"). Nothing in a plan
# or an input list states what is in a bay, and inventing a plan field
# for it would mean trusting a human-entered claim about hardware over
# the hardware -- which is precisely the mistake the patch-model
# cross-check exists to prevent, one layer up. The desk answers this
# itself, for free, on two read-only
# leaves, at the one moment Atoo is holding a connection to the desk
# the plan is about. So `verify_plan` says out loud that it did not check
# this (`patch.expansion-bay-not-checked`) and these two functions do the
# checking here, where the answer is certain.

def plan_expansion_bay_use(plan: dict) -> dict[str, list[str]]:
    """Every place this plan depends on an expansion bay having hardware
    in it: `{"MOD": ["channel 'Kick' from MOD 1", ...]}`.

    Both directions count. An input patched from an empty card bay is a
    silent channel; a Main routed to an empty one is a mix going nowhere,
    and the desk accepts and reads back both. Groups other than CRD/MOD
    are not bays at all and never appear here.

    Malformed entries are skipped rather than raised, for the same reason
    `_declared_output_patches` skips them: a caller asking "what does
    this plan need plugged in" is not a place to crash over a shape it
    does not need, and `verify_plan` reports those shapes properly.
    """
    use: dict[str, list[str]] = {}

    def note(group: object, where: str) -> None:
        if isinstance(group, str) and group in facts.EXPANSION_BAY_ADDRESSES:
            use.setdefault(group, []).append(where)

    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        patch = ch.get("patch")
        if not isinstance(patch, dict):
            continue
        sockets = [s for s in (patch.get("sockets") or []) if isinstance(s, int)]
        shown = "+".join(str(s) for s in sockets) or "?"
        note(patch.get("group"), f"channel {ch.get('name')!r} from {patch.get('group')} {shown}")
        # An alternate from an empty bay is a patch that cannot
        # work either -- the strip goes silent the moment it is switched.
        alt = ch.get("alt_patch")
        if isinstance(alt, dict):
            alt_sockets = [s for s in (alt.get("sockets") or []) if isinstance(s, int)]
            note(alt.get("group"), f"channel {ch.get('name')!r}'s alternate from "
                                   f"{alt.get('group')} {'+'.join(map(str, alt_sockets)) or '?'}")

    for (group, socket), _target in _declared_output_patches(plan).items():
        note(group, f"an output routed to {group} {socket}")

    return use


def read_fitted_bays(console, groups=None) -> dict[str, object]:
    """Ask the desk what is in each expansion bay:
    `{"CRD": "WLIVE", "MOD": "NONE"}`.

    A bay whose address did not answer, or answered something that is not
    a single string, maps to `None` -- "the desk did not say", which is
    not the same claim as "empty" and must not be treated as one.

    `groups` limits it to the bays a caller actually cares about, which is
    worth doing: these are ordinary GETs, and a console that does not
    implement the leaf costs a full timeout-and-retry apiece. A plan that
    touches no bay should pay nothing, so `apply` passes the bays its plan
    uses and skips the call entirely when there are none.
    """
    fitted: dict[str, object] = {}
    for group, address in facts.EXPANSION_BAY_ADDRESSES.items():
        if groups is not None and group not in groups:
            continue
        reply = console.get(address)
        args = getattr(reply, "args", None) if reply is not None else None
        fitted[group] = args[0] if isinstance(args, list) and len(args) == 1 else None
    return fitted


def unfitted_bays_the_plan_needs(bay_use: dict[str, list[str]],
                                 fitted: dict[str, object]) -> dict[str, list[str]]:
    """The intersection that is a refusal: of the bays this plan uses
    (`plan_expansion_bay_use`), the ones the desk has just reported empty
    (`read_fitted_bays`).

    Only an explicit `NONE` counts (`console_facts.bay_is_empty`). A bay
    the desk did not answer for, or answered with a card name this table
    has never heard of, is left alone -- an apply is not refused on a
    reading we could not make.
    """
    return {
        group: where
        for group, where in bay_use.items()
        if facts.bay_is_empty(fitted.get(group))
    }


def sockets_missing_on_model(plan: dict, console_model: str, *,
                             output_sockets=None) -> list[str]:
    """Every socket this plan patches that `console_model`'s panel does not
    have, one readable line each: `"LCL 20 (input) -- channel 'Vox';
    LCL inputs are 1..8 on a WING (full-size console)"`.

    The question `apply` asks when the desk turns out to be a different
    WING model from the one the plan was built for (`check_desk_model`):
    can this plan physically be patched on THIS desk? Every place a plan
    names a socket is walked, with the same per-model bounds `verify_plan`
    uses, so the two can never disagree about which jacks a model has:

    * a channel's input patch (`input_socket_limit`);
    * a USER PATCH slot's source in `user_sources`
      (`user_source_index_limit` -- it addresses the very same jacks);
    * every physical output a bus, Main or Matrix routes to
      (`_declared_output_patches`, what an apply actually writes;
      `output_socket_limit`).

    Only `MODEL_VARIANT_GROUPS` (LCL, AUX) differ between models. The
    expansion bays, AES50, StageCONNECT, USB and the rest hang off the one
    mainboard all three share, so they bound identically on every model --
    a bay's contents are a fact about the RIG, checked separately against
    the desk's own inventory (`unfitted_bays_the_plan_needs`). Walking them
    anyway costs nothing and means a socket beyond even the address space
    is named here too, rather than assumed to have been caught elsewhere.

    Malformed entries are skipped, as `plan_expansion_bay_use` skips them:
    `verify_plan` is where a bad shape is reported.

    `output_sockets`, when given, is the `(group, socket)` outputs to check
    INSTEAD of every output `plan` routes. `amend` passes the ones it will
    actually write: a new output whose socket the applied plan
    already routes is not written, and the check is over what is written.
    """
    label = facts.CONSOLE_MODELS[console_model]["label"]
    missing: list[str] = []

    def bound(group: str, limit: int, direction: str) -> str:
        if limit == 0:
            return f"the {label} has no {group} {direction}s at all"
        return f"{group} {direction}s are 1..{limit} on a {label}"

    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        for key, whose in (("patch", ""), ("alt_patch", "'s alternate")):
            patch = ch.get(key)
            if not isinstance(patch, dict) or not isinstance(patch.get("group"), str):
                continue
            group = patch["group"]
            limit = facts.input_socket_limit(group, console_model)
            for n in patch.get("sockets") or []:
                if isinstance(n, int) and not isinstance(n, bool) and n > limit:
                    missing.append(f"{group} {n} (input) -- channel {ch.get('name')!r}{whose}; "
                                   f"{bound(group, limit, 'input')}")

    for entry in plan.get("user_sources") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
            continue
        slot = entry.get("slot")
        if facts.user_slot_kind(slot) != facts.USER_PATCH:
            continue
        group, index = entry["source"].get("group"), entry["source"].get("index")
        limit = facts.user_source_index_limit(slot, group, console_model)
        if (limit is not None and isinstance(index, int) and not isinstance(index, bool)
                and index > limit):
            missing.append(f"{group} {index} (input) -- the source of USR {slot}; "
                           f"{bound(group, limit, 'input')}")

    outputs = _declared_output_patches(plan) if output_sockets is None else output_sockets
    for group, n in sorted(outputs):
        limit = facts.output_socket_limit(group, console_model)
        if n > limit:
            missing.append(f"{group} {n} (output) -- {bound(group, limit, 'output')}")

    return missing


#: `DeskModelCheck.outcome` values. `SAME_MODEL` and `NOT_CHECKED` say
#: nothing; the other three each carry one finding.
SAME_MODEL = "same-model"
NOT_CHECKED = "not-checked"
CROSS_MODEL = "cross-model"
SOCKETS_MISSING = "sockets-missing"
DESK_MODEL_UNMEASURED = "desk-model-unmeasured"


@dataclass
class DeskModelCheck:
    """What `check_desk_model` concluded about the desk on the line versus
    the plan about to be written to it. See that function."""

    outcome: str
    #: The model the plan is checked for: `--console-model` if given,
    #: else the plan's `meta.console_model`. None if neither states one.
    plan_model: str | None
    #: The `CONSOLE_MODELS` key the desk's `/?` reply resolved to, or None.
    desk_model: str | None
    #: The `<model>` field of that reply exactly as sent -- the string to
    #: add to `IDENTITY_MODEL_ALIASES` when `desk_model` is None.
    desk_token: str | None
    missing: list[str] = field(default_factory=list)
    severity: str | None = None
    code: str | None = None
    message: str | None = None

    @property
    def refuses(self) -> bool:
        return self.outcome == SOCKETS_MISSING

    @property
    def verify_against(self) -> str | None:
        """The model the pre-flight verify must be (re-)run against before
        writing, when that differs from the one it already ran against:
        the DESK's, for a cross-model apply -- the gate checks what is
        actually being written to. None otherwise."""
        return self.desk_model if self.outcome == CROSS_MODEL else None

    def to_journal(self) -> dict:
        return {
            "outcome": self.outcome, "plan_model": self.plan_model,
            "desk_model": self.desk_model, "desk_token": self.desk_token,
            "missing": list(self.missing), "severity": self.severity,
            "code": self.code, "message": self.message,
        }


def check_desk_model(plan: dict, plan_model: str | None, identity_args,
                     address: str, *, skip_verify: bool = False,
                     output_sockets=None) -> DeskModelCheck:
    """The cross-check, graded by the rule that a
    judgement call is not an impossible patch.

    Until 2026-09-24 any difference between the plan's model and the
    desk's was a refusal, which made a common workflow impossible --
    generating a plan and applying it to more than one console, say a
    primary Compact and a backup Rack (both have similar I/O) --
    although every socket a Compact plan can name exists
    on a Rack. So, in order:

    * **Same model** -- nothing to say.
    * **Different models, and a socket the plan patches is not on the
      desk's panel** (`sockets_missing_on_model`) -- ERROR, refuse. That
      is the physical case: a patch to a jack that is not there.
    * **Different models, every socket present** -- INFO, and proceed.
      The caller re-runs the pre-flight verify against the DESK's model
      (`verify_against`), as `--console-model <desk>` does, so the gate
      still refuses on anything that is really wrong for this desk.
    * **The desk's model cannot be resolved** -- a token nobody has
      measured (`IDENTITY_MODEL_ALIASES`), or none at all. WARNING, and
      proceed: sockets were checked against the plan's own model only,
      and a confirmed run still reads every write back and proves it. It
      used to go unannounced, which is the defect: an inferred value that
      does not announce itself. The token is kept on
      the result for the journal.
    * **The plan states no model** -- `verify_plan` has already refused
      that unless `--skip-verify` was passed, and with it there is no
      panel to compare against. Not checked, as before.

    Deliberately independent of `--skip-verify`: that flag is a judgement
    about the plan's findings, and this is a fact about the hardware. It
    changes only what the INFO says -- with it, no verify runs against
    either model, and the INFO must not claim one did.

    `output_sockets` is passed straight to `sockets_missing_on_model`:
    `amend` hands this check only the sockets it writes.
    """
    desk_model = facts.model_from_identity(identity_args)
    desk_token = facts.identity_model_token(identity_args)
    base = dict(plan_model=plan_model, desk_model=desk_model, desk_token=desk_token)

    if desk_model is None:
        if desk_token:
            said = (f"calls itself {desk_token!r}, a model name Atoo has never measured "
                    "on a real desk")
        else:
            reply = ",".join(str(a) for a in identity_args or ()) or "an empty reply"
            said = f"stated no model in its identity reply ({reply!r})"
        if plan_model is not None:
            checked = (f"Sockets were checked against the plan's own model only, the "
                       f"{facts.CONSOLE_MODELS[plan_model]['label']}")
        else:
            checked = "The plan states no model either, so no socket was checked against a panel"
        return DeskModelCheck(
            DESK_MODEL_UNMEASURED, **base, severity="warning",
            code="apply.desk-model-unmeasured",
            message=(f"{address} {said}, so it cannot tell which WING this is. "
                     f"{checked}; a confirmed apply still reads every write back from the "
                     f"desk and proves it landed. The desk's own token is recorded in the "
                     f"journal (desk.model_token) -- once the model is known it is one line "
                     f"in console_facts.IDENTITY_MODEL_ALIASES."))

    if plan_model is None:
        return DeskModelCheck(NOT_CHECKED, **base)
    if plan_model == desk_model:
        return DeskModelCheck(SAME_MODEL, **base)
    plan_label = facts.CONSOLE_MODELS[plan_model]["label"]
    desk_label = facts.CONSOLE_MODELS[desk_model]["label"]
    missing = sockets_missing_on_model(plan, desk_model, output_sockets=output_sockets)
    if missing:
        lines = "\n".join(f"  - {m}" for m in missing)
        names = list(dict.fromkeys(m.split(" (", 1)[0] for m in missing))
        named = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
        return DeskModelCheck(
            SOCKETS_MISSING, **base, missing=missing, severity="error",
            code="apply.socket-missing-on-desk",
            # The last line stands on its own: the Apply screen's dock
            # shows a failed run by its last line (`ApplyRun._failure_finding`).
            message=(f"This plan is for a {plan_label}, but {address} is a {desk_label}, and "
                     f"{len(missing)} socket(s) the plan patches do not exist on the "
                     f"{desk_label}:\n{lines}\n"
                     f"Refusing to apply: {named} {'does' if len(names) == 1 else 'do'} not "
                     f"exist on the {desk_label} at {address}. Rebuild for this desk "
                     f"(--console-model {desk_model}), or repatch to sockets it has."))
    return DeskModelCheck(
        CROSS_MODEL, **base, severity="info", code="apply.cross-model",
        message=(f"This plan is for a {plan_label}, but {address} is a {desk_label}. Every "
                 f"socket the plan patches exists on this desk, so it is applied as it stands"
                 + ("; --skip-verify was passed, so the plan was not verified against either "
                    "model." if skip_verify else
                    f", with the pre-flight verify re-run against {desk_model} -- the desk "
                    f"being written to.")))


def _clean_write_targets(plan: dict, clean_output_sockets: dict[str, int]) -> list[WriteTarget]:
    """Opt-in clean-up of undeclared output sockets (deliberately not the default): for every
    physical output socket in `clean_output_sockets` (`{group: count}`, the same
    "no confirmed default" shape `audit.py`'s `read_console_state` takes
    -- there is no safe guess at how many sockets a given rig actually
    has) that this plan does NOT declare via `_declared_output_patches`,
    disconnect it (`.grp = "OFF"`) rather than leave whatever was there.

    Deliberately writes only `.grp`, never `.in` -- WING's own model
    already treats `.grp = OFF` as fully disconnected (confirmed:
    `console_facts`/`wing-console-model.md`'s `.grp` enum), so `.in`
    becomes meaningless the moment `.grp` is OFF, and inventing a value
    for it here would be a write this project has no basis for.

    These targets go through EXACTLY the same machinery as every other
    `WriteTarget` in `apply_plan`'s main loop -- baseline read, skip if
    already OFF (`skipped_no_change`), dry-run preview, readback
    verification, abort-on-socket-error -- rather than a second, bespoke
    write path. A socket already OFF costs one baseline GET and nothing
    else; nothing here writes to any address `_build_write_targets`
    itself would also target, since cleaning is defined as exactly the
    complement of `_declared_output_patches`."""
    declared = _declared_output_patches(plan)
    targets: list[WriteTarget] = []
    for group, count in clean_output_sockets.items():
        for n in range(1, count + 1):
            if (group, n) in declared:
                continue
            targets.append(WriteTarget(
                f"/io/out/{group}/{n}/grp", "s",
                f"--clean-output-sockets: {group} {n} disconnected (no bus or output in the plan routes here)",
                _const("OFF"), STAGE_ROUTING,
            ))
    return targets


# --------------------------------------------------------------------------
# A full apply: the strips the plan does not build, and talkback's assign
# --------------------------------------------------------------------------
#
# Sixpiece's build showed a channel 24 named
# MUSIC duplicating aux 1, and the answer is to unpatch any channels that
# are not in the plan, simply by unpatching from the source. The plan
# built ch 1-23, so
# ch 24 kept the factory patch (ch N <- LCL N), LCL 24 -- and apply had
# just named LCL 23/24 "MUSIC" for aux 1's stereo pair. An unnamed strip
# shows its source's name, so ch 24 read MUSIC, and it really was
# listening to the music.
#
# So a FULL apply writes `/{ch|aux}/{n}/in/conn/grp` OFF for every strip
# the plan does not build, across the desk's whole bank
# (`console_facts.CAPACITY`). Only the source: not the name, the fader,
# the mute or anything else -- the strip is not ours, and the one thing
# that makes it dangerous is that it listens to a socket the plan uses.
# Written exactly as an unpatched instructed strip's is
# (`_channel_write_targets`), through the same loop: baseline read, a
# strip already OFF skipped (`skipped_no_change`), readback, journal --
# so `undo` puts each one back on the socket it had.
#
# **Never from amend, patch or undo** (D14: they touch only strips they
# own). `apply_plan` adds these only when its caller passes
# `full_apply=True`, which only `atoo apply` does, and refuses
# `full_apply` together with a `target_filter` or `extra_targets` -- the
# two things that mark a scoped run.
#
# The same full apply disconnects (`/io/out/{group}/{n}/grp` OFF, nothing
# else) every output socket on the desk's own panel that no bus, Main or
# Matrix of the plan is patched to (`undeclared_outputs`). The desk ships
# with local outputs patched, the reset to initialized puts that back, and the
# plan is the complete statement of where the desk's outputs go: leaving
# them sends a Main or a bus to jacks the plan never mentions, and the audit
# would call them leftovers. Only the panel; a stage box's or a card's
# outputs exist when something is fitted, so they are the plan's to patch
# (`--clean-output-sockets` reaches them). Announced once, at INFO.
#
# The same full apply sets Setup -> Audio's talkback assign
# (`/cfg/talk/assign`, `list [OFF, CH40, AUX8]`) to the strip the plan
# builds as the talk mic, when that strip is ch 40 or aux 8 -- the only two
# the desk's talkback can use. A plan with no talkback strip sets it OFF:
# a full apply makes the desk the plan, and the
# plan has no talkback -- the same full apply unpatches ch 40 and aux 8
# when it does not build them, so a hand-set assign would point at a strip
# with no input anyway. Undo puts it back. A talkback strip anywhere else is
# `verify_plan`'s WARNING (`talkback.unassignable`), never moved.


def _built_strips(plan: dict) -> set[tuple[str, int]]:
    return {(c.get("bank") or "ch", c.get("channel")) for c in plan.get("channels") or []
            if isinstance(c, dict)}


def unbuilt_strips(plan: dict) -> dict[str, list[int]]:
    """`{"ch": [24, ..., 40], "aux": [3, ..., 7]}`: every input strip on
    the desk (`console_facts.CAPACITY`) the plan does not build."""
    built = _built_strips(plan)
    return {bank: [n for n in range(1, facts.CAPACITY[bank] + 1) if (bank, n) not in built]
            for bank in ("ch", "aux")}


def strips_label(strips: dict[str, list[int]]) -> str:
    """`{"ch": [24..40], "aux": [3..7]}` -> "ch 24-40, aux 3-7"."""
    from atoo.finding_groups import _ranges

    return ", ".join(f"{bank} {_ranges(numbers)}" for bank, numbers in strips.items() if numbers)


def talkback_strips(plan: dict) -> list[dict]:
    """The plan's channel entries whose name or input reads as talkback
    (`console_facts.is_talkback_name`), in plan order."""
    return [c for c in plan.get("channels") or []
            if isinstance(c, dict)
            and facts.is_talkback_name(c.get("name"), (c.get("source") or {}).get("input"))]


def talkback_assign(plan: dict) -> tuple[str, dict] | None:
    """`("AUX8", <the aux 8 entry>)`: the value `/cfg/talk/assign` takes
    for this plan, and the strip it names -- the first talkback strip on
    ch 40 or aux 8. None when the plan builds no talkback strip there."""
    for entry in talkback_strips(plan):
        value = facts.TALK_ASSIGN_STRIPS.get((entry.get("bank") or "ch", entry.get("channel")))
        if value is not None:
            return value, entry
    return None


def _strip_words(entry: dict) -> str:
    return f"{entry.get('bank') or 'ch'} {entry.get('channel')} {entry.get('name')!r}"


_UNBUILT_DESCRIPTION = "not in this plan, unpatched (OFF)"
_UNDECLARED_OUTPUT_DESCRIPTION = "no bus or output in this plan is patched here, disconnected (OFF)"
_TALK_ASSIGN_DESCRIPTION = "talkback assign"
_NO_TALKBACK = "no talkback strip on ch 40 or aux 8 in this plan"


def _full_apply_model(plan: dict, model: str | None) -> str | None:
    """The console model a full apply works to: the desk's when the caller
    knows it, else the one the plan records. None when neither is a model
    this tool knows the panel of."""
    from atoo.verify_plan import resolve_console_model

    resolved = resolve_console_model(plan, model)
    return resolved if resolved in facts.CONSOLE_MODELS else None


def undeclared_outputs(plan: dict, model: str | None) -> dict[str, list[int]]:
    """`{"LCL": [3, 4, ..., 8]}`: the output sockets on the model's own panel
    (`console_facts.CONSOLE_MODELS`) that no bus, Main or Matrix of the plan
    is patched to. Only the panel: a stage box or a card has outputs only
    when something is fitted, and those are the plan's to patch. Empty when
    the model is unknown."""
    model = _full_apply_model(plan, model)
    if model is None:
        return {}
    declared = _declared_output_patches(plan)
    found = {group: [n for n in range(1, count + 1) if (group, n) not in declared]
             for group, count in facts.CONSOLE_MODELS[model]["outputs"].items() if count}
    return {group: numbers for group, numbers in found.items() if numbers}


def full_apply_targets(plan: dict, model: str | None = None) -> list[WriteTarget]:
    """The writes a full apply makes beyond the plan's own strips: OFF on
    every unbuilt strip's input, OFF on every panel output socket the plan
    does not patch, and talkback's assign. See the section comment above.
    `model` is the desk's console model (the plan's own is used without it)."""
    targets = [
        WriteTarget(f"/{bank}/{n}/in/conn/grp", "s", f"{bank} {n}: {_UNBUILT_DESCRIPTION}",
                    _const("OFF"), STAGE_PATCH)
        for bank, numbers in unbuilt_strips(plan).items() for n in numbers
    ]
    targets += [
        WriteTarget(f"/io/out/{group}/{n}/grp", "s", f"{group} {n}: {_UNDECLARED_OUTPUT_DESCRIPTION}",
                    _const("OFF"), STAGE_ROUTING)
        for group, numbers in undeclared_outputs(plan, model).items() for n in numbers
    ]
    talk = talkback_assign(plan)
    if talk is not None:
        value, entry = talk
        targets.append(WriteTarget(
            facts.TALK_ASSIGN, "s",
            f"{_TALK_ASSIGN_DESCRIPTION}: {_strip_words(entry)}",
            _const(value), STAGE_ROUTING))
    else:
        targets.append(WriteTarget(
            facts.TALK_ASSIGN, "s", f"{_TALK_ASSIGN_DESCRIPTION}: {_NO_TALKBACK}",
            _const("OFF"), STAGE_ROUTING))
    return targets


def outputs_label(outputs: dict[str, list[int]]) -> str:
    """`{"LCL": [3..8]}` -> "LCL 3-8"."""
    from atoo.finding_groups import _ranges

    return ", ".join(f"{group} {_ranges(numbers)}" for group, numbers in outputs.items() if numbers)


def full_apply_notes(plan: dict, model: str | None = None) -> list[tuple[str, str]]:
    """What a full apply of `plan` will do beyond its own strips, said from
    the plan alone (no desk) -- Apply's pre-flight. `_full_apply_run_notes`
    says the same from a run's records, knowing which strips already read
    OFF. One `(code, "INFO ...")` per subject: `apply.unbuilt-strips`,
    `apply.undeclared-outputs`, `apply.talkback-assign`."""
    notes = []
    label = strips_label(unbuilt_strips(plan))
    if label:
        notes.append(("apply.unbuilt-strips",
                      f"INFO {label}: not in this plan, unpatched from their sources so none "
                      "listens to a socket the plan uses (a strip already unpatched is left as "
                      "it is)"))
    outputs = outputs_label(undeclared_outputs(plan, model))
    if outputs:
        notes.append(("apply.undeclared-outputs",
                      f"INFO output {outputs}: no bus or output in this plan is patched there, so "
                      "each is disconnected rather than left on what the desk came with or an "
                      "earlier show put there (a socket already off is left as it is)"))
    talk = talkback_assign(plan)
    if talk is not None:
        value, entry = talk
        notes.append(("apply.talkback-assign",
                      f"INFO talkback assign (Setup -> Audio) set to {value}: "
                      f"{_strip_words(entry)} is the plan's talkback strip"))
    else:
        notes.append(("apply.talkback-assign",
                      f"INFO talkback assign (Setup -> Audio) set to OFF: {_NO_TALKBACK}"))
    return notes


def _full_apply_run_notes(records: list[WriteRecord]) -> list[str]:
    """`full_apply_notes` from a run's records: which unbuilt strips and
    unpatched output sockets this run unpatched or disconnected (or, in a
    preview, would), and how many already read OFF."""
    notes = []

    def changes(r: WriteRecord) -> bool:
        return (r.status in ("match", "mismatch")
                or (r.status == "dry_run" and r.would_change))

    outputs = [r for r in records if r.description.endswith(_UNDECLARED_OUTPUT_DESCRIPTION)]
    if outputs:
        moved_outputs: dict[str, list[int]] = {}
        for r in outputs:
            if changes(r):
                group, n = r.address.split("/")[3:5]
                moved_outputs.setdefault(group, []).append(int(n))
        already = sum(1 for r in outputs if r.status == "skipped_no_change"
                      or (r.status == "dry_run" and not r.would_change))
        label = outputs_label(moved_outputs)
        tail = f"; {already} more already read disconnected" if already else ""
        if label:
            notes.append(f"INFO output {label}: no bus or output in this plan is patched there, so "
                         f"each is disconnected rather than left on what the desk came with or an "
                         f"earlier show put there{tail}")
        else:
            notes.append(f"INFO {already} output socket(s) the plan does not patch already read "
                         "disconnected -- nothing to disconnect")
    unbuilt = [r for r in records if r.description.endswith(_UNBUILT_DESCRIPTION)]
    if unbuilt:
        moved: dict[str, list[int]] = {"ch": [], "aux": []}
        for r in unbuilt:
            if changes(r):
                bank, n = r.address.split("/")[1:3]
                moved[bank].append(int(n))
        already = sum(1 for r in unbuilt if r.status == "skipped_no_change"
                      or (r.status == "dry_run" and not r.would_change))
        label = strips_label(moved)
        tail = f"; {already} more already read unpatched" if already else ""
        if label:
            notes.append(f"INFO {label}: not in this plan, unpatched from their sources so none "
                         f"listens to a socket the plan uses{tail}")
        else:
            notes.append(f"INFO {already} strip(s) not in this plan already read unpatched "
                         "-- nothing to unpatch")
    for r in records:
        if r.description.startswith(f"{_TALK_ASSIGN_DESCRIPTION}: "):
            strip = r.description[len(_TALK_ASSIGN_DESCRIPTION) + 2:]
            was = ("already" if r.status == "skipped_no_change"
                   or (r.status == "dry_run" and not r.would_change)
                   else f"was {r.prior_value!r}")
            why = strip if strip == _NO_TALKBACK else f"{strip} is the plan's talkback strip"
            notes.append(f"INFO talkback assign (Setup -> Audio) set to {r.intended_value} "
                         f"({was}): {why}")
    return notes


# --------------------------------------------------------------------------
# Returning a dropped channel's strip to free
# --------------------------------------------------------------------------
#
# Given the choice of "report it", "mute it" and "return it to
# free", whether this is for a rebuild of the plan or an amend, the
# answer is to return it to free: channels are not an unlimited resource
# and the tool should do what the engineer is asking for.
#
# So a channel the rebuild dropped has its strip muted, put back on its
# factory input patch (or OFF, see
# `release_patch_decision`; decided 2026-09-24), and its name, colour and
# icon blanked -- on
# the SOURCE as well as the strip,
# because with `clink` on that is where the name the desk displays lives.
# The end state is the reading an untouched strip gives
# (`console_facts.FACTORY_STRIP_*`, measured), so the next person
# allocating a strip finds it genuinely free rather than nearly free.
#
# **This function decides only WHAT a release writes. It never decides
# WHETHER one is allowed.** That question -- is this strip still the one
# our plan put there, or has somebody taken it over since -- is answered
# in `atoo/amend.py` against a fresh read of the desk, and nothing
# reaches here that has not passed it. The split is deliberate: a strip
# that is not ours must not be cleared, and the check that establishes
# ownership has to see the console, which this module's target builders
# never do.
#
# Two rules shape the write set, and both are "undo exactly what we did":
#
# 1. **Only the leaves this plan's own build would have written.** A plan
#    that never stated an icon never wrote one, so a release does not
#    blank an icon somebody else set. The branches below mirror
#    `_channel_write_targets`'s, read off the SAME channel entry, which is
#    what keeps the two in step.
# 2. **Never a socket something still uses.** `keep_sockets` is every
#    input socket the plan that remains still patches -- one jack feeding
#    a strip that is going and a strip that is staying is an ordinary
#    request (`atoo/domain/knowledge.md`), and clearing its label
#    would take the name off a channel nobody asked to remove.
#
# `fdr` and `mute` are written, and both are documented exceptions to the
# fader/mute rule in the module docstring rather than oversights: neither
# value is a level this module chose. `fdr` goes to -inf, the reading of
# an untouched strip (`console_facts.FACTORY_STRIP_FADER_DB`); `mute`
# brackets the clear and ends off, as an untouched strip is. The
# instruction behind both is the engineer's own removal of the channel.


def _released_tags(current: object, dca_indices: list[int],
                   mute_group_indices: list[int]) -> str:
    """`{base}/tags` with THIS channel's DCA and mute-group tokens taken
    out, and anything else left exactly where it is.

    The mirror image of `_merge_tags`, and subtractive for the same
    reason that one is additive: the field is shared, and a strip may
    carry a token this plan never put there. Removing only our own is the
    difference between returning a strip to free and wiping a field.
    """
    ours = {f"#D{i}" for i in dca_indices} | {f"#M{i}" for i in mute_group_indices}
    kept = [token for token in str(current or "").split(",")
            if token.strip() and token.strip() not in ours]
    return ",".join(kept)


def _model_words(console_model: str | None) -> str:
    """`a WING Compact` / `a console of unstated model`, for a sentence."""
    model = facts.CONSOLE_MODELS.get(console_model or "")
    if model is None:
        return ("a console whose model nobody stated" if not console_model
                else f"a console of unknown model {console_model!r}")
    return f"a {model['label']}"


def release_patch_decision(
        channel: dict, *, console_model: str | None,
        claimed_sockets: dict[tuple[str, int], str] | None = None,
) -> tuple[tuple[str, int] | None, str]:
    """What a released strip's input patch goes back to: `(socket, why)`
    to restore its factory patch, or `(None, why)` to write OFF.

    `why` is a sentence for a person, and it always comes back, because
    either answer is a choice the engineer should be able to see
    (an inferred value that does not announce itself is the
    defect). `amend.plan_amendment` puts it in the review at INFO;
    `release_write_targets` makes the same call for the wire. One
    function, so the review and the write cannot disagree.

    Of three options, off a Compact session where a freed channel 19 did
    not look like an initialized one, the choice is the factory patch,
    unless the plan uses that socket, otherwise OFF. Ch 19 goes back to
    LCL 19 and looks exactly like an initialized channel, glyph included.
    If the rebuilt plan now uses LCL 19 for something else, it stays OFF
    rather than double-patching the socket, and an INFO says so.

    The factory socket comes from
    `console_facts.measured_factory_input_patch` -- **measured data only**.
    `factory_input_patch()`'s channel-n-from-LCL-n fallback is right for
    reading occupancy and wrong for a write: on a model nobody measured it
    can name a socket the panel does not have. OFF is the answer there,
    and OFF is the answer when the factory leaves this strip unpatched.

    `claimed_sockets` maps every socket something else needs to a
    description of what -- a channel of the rebuilt plan, or a strip the
    desk read showed patched to it. A claimed factory socket is left OFF.
    """
    bank = channel.get("bank", "ch")
    n = channel.get("channel")
    label = f"{bank}:{n}"
    model = _model_words(console_model)
    socket, reason = facts.measured_factory_input_patch(console_model, bank, n)
    if socket is None:
        if reason == facts.FACTORY_PATCH_NONE:
            return None, (f"{model} leaves {label} unpatched from the factory, so OFF is its "
                          "factory patch")
        if reason == facts.FACTORY_PATCH_NO_SUCH_SOCKET:
            return None, (f"its measured factory socket is not on the panel of {model} -- "
                          "left unpatched (OFF) rather than patched to a socket that is not "
                          "there")
        return None, (f"nobody has measured which socket {label} comes from on {model} "
                      "straight from the factory -- left unpatched (OFF) rather than patched "
                      "to a guessed socket that may not exist on this desk")
    claimant = (claimed_sockets or {}).get(socket)
    if claimant is not None:
        return None, (f"its factory socket {socket[0]} {socket[1]} is used by {claimant} -- "
                      "left unpatched (OFF) rather than patching one socket to two strips")
    return socket, (f"patched back to {socket[0]} {socket[1]}, its factory socket on {model} "
                    "(measured), so it looks exactly like an initialized channel")


def release_write_targets(channels: list[dict], *,
                          dca_index: dict[str, int] | None = None,
                          mute_group_index: dict[str, int] | None = None,
                          bus_index: dict[str, int] | None = None,
                          keep_sockets: set[tuple[str, int]] | None = None,
                          shared_sockets: dict[tuple[str, int], list[str]] | None = None,
                          console_model: str | None = None,
                          claimed_sockets: dict[tuple[str, int], str] | None = None,
                          warnings: list[str] | None = None) -> list[WriteTarget]:
    """The writes that return each of `channels` -- entries from the plan
    that BUILT them -- to the reading an untouched strip gives.

    Ordered within each strip rather than by `stage`, because the order is
    the safety: mute before anything else so the strip is silent for the
    rest of it, phantom down while the patch still says which socket it is
    on, the source label cleared next, and only then the patch goes back
    to what the factory left there.

    **The patch goes back to the factory's, not to OFF** (decided
    2026-09-24; `release_patch_decision`). A Compact's channel 19 returns
    to LCL 19 -- and with `clink` back on it shows that socket's glyph,
    which is the whole of what made a freed strip look different from an
    initialized one. It is OFF instead when the model's factory patch was
    never measured (`console_model` absent or unmeasured -- never the
    identity fallback, which can name a socket the panel lacks), when the
    factory leaves the strip unpatched, or when the socket is claimed:
    `claimed_sockets` (socket -> what uses it) and `keep_sockets` both
    count, so a caller that passes only the latter is still never handed a
    double patch.

    **The mute is a bracket, not an end state**. `mute` is
    written ON first and OFF again as the strip's very last address, so
    nothing pops on the way out and nothing is left behind: an untouched
    WING strip is UNMUTED, and a muted one is not what the next person
    allocating a strip expects to find. Its sends are off and its patch
    is the factory's (or OFF), which is exactly how an initialized strip
    arrives. Two records for
    one address is deliberate and `undo.py` reverses them correctly,
    because it reverses in reverse journal order and reads the desk
    afresh at each step.

    **`fdr` goes to -inf, the factory reading, just before the closing
    unmute**. Never to any other value: picking a
    level for a strip no plan is building is still the one thing this
    module must never do. See the module docstring for why restoring the
    factory patch made the factory fader necessary.

    **The processing block is cleared too** (from the first
    hardware run: a strip "returned to free" came back still carrying the
    plan's 120Hz high-pass). What gets cleared is derived from the BUILD
    -- `_channel_write_targets` is run over the same applied-plan entry
    and every target it produces at `STAGE_PROCESSING` is written back to
    the reading an untouched strip gives
    (`console_facts.FACTORY_STRIP_PROCESSING`). Deriving it rather than
    listing it is what keeps the bound exact in both directions: **undo
    what this plan wrote, never more** -- processing the plan never
    stated is somebody else's and is never generated here -- and a
    processing leaf this project learns next is covered without anybody
    remembering to add it to a second list.

    **Head-amp gain is deliberately out of scope**, and stays out. It
    lives on the physical SOURCE rather than the strip
    (`/io/in/{grp}/{n}/g`, built at `STAGE_PHANTOM`, so the stage filter
    above excludes it by construction), it is shared by every strip on a
    split, and nobody has said what a freed socket's gain should read.
    Leaving it is the conservative direction: a gain nobody moved is a
    gain the next person can see, where a gain this tool invented is one
    they cannot account for.
    """
    keep_sockets = set(keep_sockets or ())
    shared_sockets = shared_sockets or {}
    # What a factory socket must not be restored onto: everything the
    # caller named, and every socket the kept plan patches, whether or not
    # the caller also named it.
    claims: dict[tuple[str, int], str] = {
        socket: "a strip the plan keeps" for socket in keep_sockets}
    claims.update(claimed_sockets or {})
    dca_index = dca_index or {}
    mute_group_index = mute_group_index or {}
    bus_index = bus_index or {}
    warnings = warnings if warnings is not None else []
    targets: list[WriteTarget] = []
    for channel in channels:
        n = channel.get("channel")
        name = channel.get("name")
        bank = channel.get("bank", "ch")
        if bank not in ("ch", "aux") or not isinstance(n, int):
            warnings.append(
                f"cannot return {name!r} to free: its entry in the applied plan does not name a "
                f"{('bank' if bank not in ('ch', 'aux') else 'strip number')} this tool can "
                "address -- nothing was written for it")
            continue
        base = f"/{bank}/{n}"
        label = f"{bank}:{n}"
        was = f"{label} (was {name!r})"

        # 1. Silent first.
        targets.append(WriteTarget(
            f"{base}/mute", "i", f"returned to free: {was} muted",
            _const(1), STAGE_FADER_MUTE))

        patch = channel.get("patch") or {}
        group, sockets = patch.get("group"), [
            s for s in (patch.get("sockets") or []) if isinstance(s, int)]
        col = channel.get("col")
        if col is None:
            col = facts.colour_index(channel.get("color"))
        icon = channel.get("icon")

        if isinstance(group, str) and sockets:
            # Mirrors `_channel_write_targets`: the socket carried this
            # strip's customization only when the group has the leaves for
            # it and the socket was this strip's alone.
            is_shared = any((group, s) in shared_sockets for s in sockets)
            for socket in sockets:
                if (group, socket) in keep_sockets:
                    warnings.append(
                        f"{was} is being returned to free, but {group} {socket} still feeds a "
                        "strip the plan keeps -- the socket's own name, colour, icon and "
                        "phantom are left exactly as they are")
                    continue
                # 2. Phantom down while the patch still says where it is.
                if group in _VPH_CAPABLE_GROUPS:
                    targets.append(WriteTarget(
                        f"/io/in/{group}/{socket}/vph", "i",
                        f"returned to free: phantom power off on {group} {socket} ({was})",
                        _const(0), STAGE_PHANTOM))
                # 3. The label the desk actually displays.
                if group in facts.NAMEABLE_INPUT_GROUPS and not is_shared:
                    targets.append(WriteTarget(
                        f"/io/in/{group}/{socket}/name", "s",
                        f"returned to free: name cleared on source {group} {socket} ({was})",
                        _const(facts.FACTORY_SOURCE_NAME), STAGE_SOURCE_LABEL))
                    if col is not None:
                        targets.append(WriteTarget(
                            f"/io/in/{group}/{socket}/col", "i",
                            f"returned to free: colour cleared on source {group} {socket} ({was})",
                            _const(facts.FACTORY_SOURCE_COLOUR_INDEX), STAGE_SOURCE_LABEL))
                    if icon is not None:
                        targets.append(WriteTarget(
                            f"/io/in/{group}/{socket}/icon", "i",
                            f"returned to free: icon cleared on source {group} {socket} ({was})",
                            _const(facts.factory_source_icon(group)), STAGE_SOURCE_LABEL))
            # 4. The patch, back to what the factory left there:
            # the measured factory socket when
            # nothing else claims it, OFF otherwise. Where OFF sat, and for
            # the same reason: last of the socket-side writes, so phantom
            # and the label above were cleared while the patch still said
            # which socket was ours. Both halves are written for a restore,
            # `.grp` first as the build does; `.in` is the number the desk
            # shows (the GET offset is corrected on read, never here). OFF
            # is `.grp` alone, as `_clean_write_targets` writes it: WING
            # treats OFF as fully disconnected, so `.in` is meaningless
            # afterwards.
            factory, why = release_patch_decision(
                channel, console_model=console_model, claimed_sockets=claims)
            if factory is not None:
                targets.append(WriteTarget(
                    f"{base}/in/conn/grp", "s",
                    f"returned to free: {was} back on its factory patch {factory[0]} {factory[1]}",
                    _const(factory[0]), STAGE_PATCH))
                targets.append(WriteTarget(
                    f"{base}/in/conn/in", "i",
                    f"returned to free: {was} back on its factory patch {factory[0]} {factory[1]}",
                    _const(factory[1]), STAGE_PATCH))
            else:
                targets.append(WriteTarget(
                    f"{base}/in/conn/grp", "s", f"returned to free: {was} unpatched -- {why}",
                    _const("OFF"), STAGE_PATCH))
        # The alternate this plan wrote goes back to the factory reading,
        # OFF (every initialized snapshot on disk), `.altgrp` alone as OFF
        # always is. Only when the plan stated one: otherwise the desk's
        # alternate was never ours.
        if isinstance(channel.get("alt_patch"), dict):
            targets.append(WriteTarget(
                f"{base}/in/conn/altgrp", "s", f"returned to free: {was} alternate patch cleared",
                _const(facts.ALT_PATCH_OFF), STAGE_PATCH))

        # 5. The strip's own customization, back to the factory reading.
        targets.append(WriteTarget(
            f"{base}/name", "s", f"returned to free: {was} name cleared",
            _const(facts.FACTORY_STRIP_NAME), STAGE_NAMES))
        if col is not None:
            targets.append(WriteTarget(
                f"{base}/col", "i", f"returned to free: {was} colour cleared",
                _const(facts.FACTORY_STRIP_COLOUR_INDEX), STAGE_NAMES))
        if icon is not None:
            targets.append(WriteTarget(
                f"{base}/icon", "i", f"returned to free: {was} icon cleared",
                _const(facts.FACTORY_STRIP_ICON), STAGE_NAMES))
        # `clink` back ON, which is the factory setting. A build writes 0
        # for a strip sharing its socket; leaving that behind would be a
        # strip that looks free and quietly ignores the source it is next
        # patched to.
        targets.append(WriteTarget(
            f"{base}/clink", "i",
            f"returned to free: {was} relinked to its source (the factory setting)",
            _const(1), STAGE_NAMES))

        # 6. Off the DCAs and mute groups this plan put it in, and out of
        # the busses it fed. Both are what `audit.is_in_use` reads after
        # the name and the patch, so a strip left in the Horns DCA with
        # two sends up is not free by this project's own definition --
        # and it is visibly not free, because the DCA still moves it.
        # Measured against an untouched strip of the A13 capture:
        # `tags=''` and no bus send on.
        dca_idxs = [dca_index[d] for d in (channel.get("dca") or []) if d in dca_index]
        mute_idxs = [mute_group_index[m] for m in (channel.get("mute_group") or [])
                     if m in mute_group_index]
        if dca_idxs or mute_idxs:
            targets.append(WriteTarget(
                f"{base}/tags", "s",
                f"returned to free: {was} taken out of "
                + ", ".join([f"DCA {i}" for i in dca_idxs]
                            + [f"mute group {i}" for i in mute_idxs]),
                lambda current, d=dca_idxs, m=mute_idxs: _released_tags(current, d, m),
                STAGE_TAGS))
        for send in channel.get("bus_sends") or []:
            bidx = bus_index.get(send.get("bus"))
            if bidx is None:
                continue
            targets.append(WriteTarget(
                f"{base}/send/{bidx}/on", "i",
                f"returned to free: {was} no longer sends to bus {bidx}",
                _const(0), STAGE_SENDS))
        # The direct Main routes, back to the factory's: Main 1 ON, every
        # other Main OFF (console_facts.FACTORY_STRIP_MAIN_INDEX) --
        # written for every Main whether or not the plan routed it,
        # because the build writes every Main too (`_channel_write_targets`
        # switches off each one the plan did not list). A free strip on
        # Main 1 is how the desk ships, not a route anyone chose; its fader
        # goes to -inf below, as an untouched strip's does.
        for index in facts.main_indices():
            on = facts.factory_strip_main_on(index)
            targets.append(WriteTarget(
                f"{base}/main/{index}/on", "i",
                f"returned to free: {was} "
                + (f"back on Main {index}, the factory routing" if on
                   else f"no longer routed direct to Main {index}"),
                _const(on), STAGE_ROUTING))

        # 7. The processing block this plan's own build wrote, back to the
        # reading an untouched strip gives.
        targets.extend(_release_processing_targets(
            channel, was, dca_index=dca_index, mute_group_index=mute_group_index,
            bus_index=bus_index, shared_sockets=shared_sockets, warnings=warnings))

        # 8. The fader to the factory reading, -inf -- BEFORE the unmute,
        # so the strip is silent by level before it stops being silent by
        # mute. With the factory patch restored, a
        # strip left unmuted at the plan's level would carry a stray source
        # on its factory jack to Main 1. This is not a level chosen for a
        # show; it is the reading an untouched strip gives, like every
        # other value this function writes.
        targets.append(WriteTarget(
            f"{base}/fdr", "f",
            f"returned to free: {was} fader to -inf, as an untouched strip reads",
            _const(facts.FACTORY_STRIP_FADER_DB), STAGE_FADER_MUTE))

        # 9. And out of mute, last. See this function's docstring: the
        # mute at step 1 is a bracket around the clear, not part of what
        # "free" means. An untouched WING strip is unmuted.
        targets.append(WriteTarget(
            f"{base}/mute", "i",
            f"returned to free: {was} unmuted -- an untouched strip is not a muted one",
            _const(0), STAGE_FADER_MUTE))
    return targets


def _release_processing_targets(channel: dict, was: str, *,
                                dca_index: dict[str, int],
                                mute_group_index: dict[str, int],
                                bus_index: dict[str, int],
                                shared_sockets: dict[tuple[str, int], list[str]],
                                warnings: list[str]) -> list[WriteTarget]:
    """Undo the PROCESSING the plan's own build wrote on this strip, and
    nothing else.

    The set is taken from the build rather than restated: this runs
    `_channel_write_targets` over the very entry that built the strip and
    keeps the targets at `STAGE_PROCESSING` -- the `flt`, `in/set`, `eq`
    and `peq` leaves. Every one of them gets the reading an untouched
    strip gives, measured across all 48 strips of
    the A8 initialized snapshot of 2026-09-23
    (`console_facts.FACTORY_STRIP_PROCESSING`).

    Three consequences of deriving it this way, all of them the point:

    * A plan that stated no processing writes no processing targets, so
      there is nothing here to clear -- a filter somebody else set is
      never touched.
    * Head-amp gain, phantom and stereo width are built at
      `STAGE_PHANTOM`, not `STAGE_PROCESSING`, so they are excluded by
      construction rather than by a rule someone has to remember. Phantom
      is cleared above, on its own terms; gain is deliberately left (see
      `release_write_targets`).
    * A leaf with no measured factory reading is **warned about, not
      guessed at**. Writing a value nobody measured onto a strip this
      tool has just called free would be the same species of defect as
      leaving the filter on.
    """
    bank = channel.get("bank", "ch")
    base = f"/{bank}/{channel.get('channel')}"
    try:
        built = _channel_write_targets(
            channel, dca_index, mute_group_index, bus_index, [], True, shared_sockets)
    except (KeyError, TypeError, ValueError) as exc:
        warnings.append(
            f"cannot work out what processing to clear for {was}: its entry in the applied "
            f"plan does not build ({exc!r}) -- the strip's processing is left as it is")
        return []
    targets: list[WriteTarget] = []
    for target in built:
        if target.stage != STAGE_PROCESSING:
            continue
        if not target.address.startswith(base + "/"):
            # Processing lives on the strip. Anything else arriving at
            # this stage is a change in `_channel_write_targets` this
            # function has not been told about, and a release is not the
            # place to find out what it does.
            warnings.append(
                f"not clearing {target.address} for {was}: it is written at the processing "
                "stage but does not belong to the strip, and a release only ever undoes the "
                "strip's own processing")
            continue
        leaf = target.address[len(base) + 1:]
        value = facts.factory_strip_processing(leaf, bank)
        if value is facts.NO_FACTORY_READING:
            warnings.append(
                f"cannot return {target.address} to free for {was}: this plan wrote it, and "
                "nothing has measured what an untouched strip reads there -- it is left as the "
                "plan set it, so the strip is not completely clear")
            continue
        targets.append(WriteTarget(
            target.address, target.value_type,
            f"returned to free: {was} {leaf} back to the untouched reading",
            _const(value), STAGE_PROCESSING))
    return targets


def _dedupe_by_address(targets: list[WriteTarget], warnings: list[str]) -> list[WriteTarget]:
    """One write per address, and a warning when two of them disagreed.

    Two strips sharing an input socket each emit that socket's phantom and
    stereo-mode write, because each strip is built independently and both
    are correct about their own strip. There is one preamp, so the second
    write silently overwrites the first -- and if the plan asked for 48V on
    one strip and not the other, nothing said so. From
    `atoo/domain/knowledge.md`: *"An input list asking for 48V on one
    of them and not the other is asking for something the hardware cannot
    do."* This is where that stops being silent.

    The first target for an address wins, which keeps the order the write
    plan's stages established. A later duplicate carrying the SAME value is
    dropped without comment (two strips agreeing about their shared socket
    is not news); one carrying a different value is dropped with a warning
    naming both.
    """
    seen: dict[str, WriteTarget] = {}
    kept: list[WriteTarget] = []
    for target in targets:
        first = seen.get(target.address)
        if first is None:
            seen[target.address] = target
            kept.append(target)
            continue
        try:
            a, b = first.compute_value(None), target.compute_value(None)
        except Exception:  # a value that needs a real prior read; cannot compare
            a = b = None
        if a != b:
            warnings.append(
                f"{target.address}: two writes disagree -- {first.description!r} wants {a!r} and "
                f"{target.description!r} wants {b!r}. There is only one of this parameter, so "
                f"{a!r} is what will be written. If those strips share an input socket, they "
                f"share its head amp, and the plan is asking for something the hardware cannot do."
            )
    return kept


def _shared_source_sockets(plan: dict) -> dict[tuple[str, int], list[str]]:
    """Sockets fed to more than one channel strip, mapped to the names of
    the strips sharing them.

    One physical input feeding two strips is a normal request, not a
    mistake -- `atoo/domain/knowledge.md` has the two reasons an
    engineer asks for it (a separate strip for monitors; one socket reused
    between acts at a festival). What it breaks is naming: the desk shows
    a strip the name of the SOCKET it is patched to, and one socket cannot
    carry two names.

    So a shared socket is the one case where the strips have to carry
    their own names, and this is what tells `_channel_write_targets` which
    those are: the channel and source customization are unlinked and
    the channels customized separately, while the source is given some
    kind of composite name.
    """
    occupants: dict[tuple[str, int], list[str]] = {}
    for channel in plan.get("channels", []):
        patch = channel.get("patch") or {}
        group = patch.get("group")
        if group not in facts.NAMEABLE_INPUT_GROUPS:
            continue
        for socket in patch.get("sockets") or []:
            occupants.setdefault((group, socket), []).append(str(channel.get("name", "")))
    return {key: names for key, names in occupants.items() if len(names) > 1}


def _composite_source_name(names: list[str]) -> str:
    """A name for a socket that feeds several strips.

    Joined with "/" and cut to the console's 16 characters. "Kick" and
    "Kick IEM" become "Kick/Kick IEM"; anything longer is truncated rather
    than silently rejected by the desk, because a socket label that is
    approximately right beats one the console refuses.

    Deliberately not clever. The strips carry the precise names; this is
    the label on the jack, and its job is to stop someone wondering which
    of the two the socket belongs to.
    """
    joined = "/".join(dict.fromkeys(n for n in names if n))
    return joined[:facts.NAME_MAX_CHARS]


def _shared_source_name_targets(shared: dict[tuple[str, int], list[str]],
                                warnings: list[str]) -> list[WriteTarget]:
    """One name per shared socket, written once rather than fought over by
    each strip that uses it."""
    targets: list[WriteTarget] = []
    for (group, socket), names in sorted(shared.items()):
        composite = _composite_source_name(names)
        warnings.append(
            f"{group} {socket} feeds {len(names)} strips ({', '.join(names)}) -- they share one "
            f"head amp, so gain and phantom are common to all of them. Each strip is named "
            f"directly and the socket is labelled {composite!r}."
        )
        targets.append(WriteTarget(
            f"/io/in/{group}/{socket}/name", "s",
            f"source {group} {socket}: shared by {len(names)} strips",
            _const(composite), STAGE_SOURCE_LABEL,
        ))
    return targets


def _build_write_targets(plan: dict, set_fader_levels: bool) -> tuple[list[WriteTarget], list[str]]:
    # A bus width or send mode the plan left null is DECIDED before
    # anything is built -- on a copy, by the same deterministic rule
    # `generate_plan` and `verify_plan` use (`inferred.py`), so a plan
    # written before that rule, or edited by hand since, writes exactly
    # the value verify's INFO said it would. amend builds through here
    # too, so both halves of its diff are decided the same way.
    plan = inferred.with_decisions(plan)
    warnings: list[str] = []
    dca_index = {name: e["index"] for name, e in plan.get("dcas", {}).items()}
    mute_group_index = {name: e["index"] for name, e in plan.get("mute_groups", {}).items()}
    bus_index = bus_indices(plan)

    shared = _shared_source_sockets(plan)

    targets: list[WriteTarget] = []
    targets.extend(_group_name_targets(plan, warnings, set_fader_levels))
    targets.extend(_bus_write_targets(plan, dca_index, mute_group_index, warnings, set_fader_levels))
    for channel in plan.get("channels", []):
        targets.extend(_channel_write_targets(channel, dca_index, mute_group_index, bus_index, warnings, set_fader_levels, shared))
    targets.extend(_shared_source_name_targets(shared, warnings))

    for output_name, output_entry in plan.get("outputs", {}).items():
        # A Main/Matrix can fan out to SEVERAL physical sockets
        # at once (TOURING_260821_MIX.snap's Main feeds USB 47/48, CRD
        # 31/32 AND REC 1/2 simultaneously) -- `patches` (plural) is
        # authoritative when non-empty; `patch` (singular) covers a plan
        # that only ever set the one, and plan_compat reads the older
        # `sockets`/`socket` spelling of both.
        sockets = plan_compat.output_patches(output_entry)
        # The plan now states which internal source feeds this Output
        # entry -- kind ("main"/"matrix") + index, confirmed against a real
        # show file's io.out.*.grp/in in use (MAIN/1, MAIN/2, MTX/9,
        # MTX/11, BUS/1, MON/1, LCL/21, USB/1). No name is special-cased
        # anymore: an engineer's own free-text Output name ("FOH",
        # "Broadcast", ...) works the same as "Main"/"Matrix" as long as
        # the plan states kind+index; an entry that states neither is
        # warned about, never guessed at from its name.
        kind = output_entry.get("kind")
        index = output_entry.get("index")
        wing_grp = _OUTPUT_KIND_TO_WING_GRP.get(kind)
        if not sockets:
            pass  # no patch: no physical routing to write (verify_plan's WARNING `output.no-patch`); its fader, processing and fed_by below still go out
        elif wing_grp is not None and index is not None:
            for socket in sockets:
                for position, sock in enumerate(socket["sockets"]):
                    targets.append(WriteTarget(f"/io/out/{socket['group']}/{sock}/grp", "s", f"output {output_name} ({socket['group']} {sock}): source", _const(wing_grp), STAGE_ROUTING))
                    targets.append(WriteTarget(f"/io/out/{socket['group']}/{sock}/in", "i", f"output {output_name} ({socket['group']} {sock}): {kind} channel", _const(_output_slot(index, position)), STAGE_ROUTING))
        else:
            warnings.append(
                f"output {output_name!r}: not applied -- the plan doesn't identify which internal "
                "source (a Main index or a Matrix index -- kind+index) feeds it, only a physical "
                "socket and free text -- not guessed from the name"
            )

        # Its name, on the internal object. Main and matrix bus names in the
        # plan were not being set -- a bus's name was written
        # (`_bus_write_targets`), an output's never was. The plan's key IS the name ("Phones",
        # "Matrix 1"), written whether or not a socket is patched: a
        # Matrix used as the phones source is found on the desk by it.
        if wing_grp is not None and index is not None:
            targets.append(WriteTarget(
                f"{'/main' if kind == 'main' else '/mtx'}/{index}/name", "s",
                f"output {output_name} ({kind} {index}): name", _const(output_name), STAGE_NAMES))

        # A Main/Matrix's own starting fader/mute lives on the internal
        # object itself (/main/{n}, /mtx/{n}) -- independent of whether
        # this entry's PHYSICAL output socket could be resolved above, so
        # an unresolved socket must not silently skip Job 3 for an
        # otherwise fully-identified Main/Matrix.
        if set_fader_levels and wing_grp is not None and index is not None:
            out_base = f"/main/{index}" if kind == "main" else f"/mtx/{index}"
            targets.extend(_fader_targets(out_base, f"output {output_name} ({kind} {index})", output_entry.get("fader")))

        # A Main's or a Matrix's own EQ/tilt, on that
        # same internal object -- and, like the bus's above, independent of
        # --no-faders. An output whose kind/index the plan never states has
        # no internal object to write to at all; the warning for that is
        # already raised above, so this stays silent rather than doubling it.
        if kind is not None and index is not None:
            eq_strip = facts.OUTPUT_KIND_TO_EQ_STRIP.get(kind)
            if eq_strip is not None:
                proc_targets, proc_warnings = _strip_processing_targets(
                    f"/main/{index}" if kind == "main" else f"/mtx/{index}",
                    eq_strip, f"output {output_name} ({kind} {index})",
                    output_entry.get("processing"))
                targets.extend(proc_targets)
                warnings.extend(proc_warnings)

        # What FEEDS a matrix's input. A matrix has no per-
        # source routing table of its own (confirmed against docs/
        # reference/wing-compact-raw-walk-20260908.json: /mtx/{n} exposes
        # only insert/processing leaves) -- a Main or a bus feeds it via a
        # send on the SOURCE object, /main/{n}/send/MX{m} or /bus/{n}/
        # send/MX{m}, each confirmed with exactly on/lvl/pre, same shape
        # as a channel's direct-to-main route above. The grammar has no
        # phrasing yet for this send's own level/pre-post (only THAT it
        # feeds, and from where), so this reuses the same documented
        # unity/post-fader default.
        fed_by = output_entry.get("fed_by")
        if kind == "matrix" and index is not None and fed_by is not None:
            source_base = None
            if fed_by["type"] == "main":
                source_base = f"/main/{fed_by['index']}"
                source_desc = f"Main {fed_by['index']}"
            elif fed_by["type"] == "bus":
                bidx = bus_index.get(fed_by["name"])
                if bidx is None:
                    warnings.append(
                        f"output {output_name!r}: fed by bus {fed_by['name']!r}, which has no "
                        "console index in this plan -- feed not applied"
                    )
                else:
                    source_base = f"/bus/{bidx}"
                    source_desc = f"bus {fed_by['name']}"
            if source_base is not None:
                send_base = f"{source_base}/send/MX{index}"
                targets.append(WriteTarget(f"{send_base}/on", "i", f"{source_desc}: feed to matrix {output_name} on", _const(1), STAGE_ROUTING))
                targets.append(WriteTarget(f"{send_base}/lvl", "f", f"{source_desc}: feed to matrix {output_name} level", _const(MAIN_ROUTE_LEVEL_DEFAULT_DB), STAGE_ROUTING))
                targets.append(WriteTarget(f"{send_base}/pre", "i", f"{source_desc}: feed to matrix {output_name} pre/post-fader", _const(MAIN_ROUTE_PRE_DEFAULT), STAGE_ROUTING))

    # Last, over the whole write set (review 2026-09-28, R19): it used to
    # run before the outputs loop above, so a socket a bus's dedicated
    # output and an `outputs` entry both claimed (reachable with
    # --skip-verify) was written twice, with no warning.
    targets = _dedupe_by_address(targets, warnings)
    targets.sort(key=lambda t: t.stage)
    return targets, warnings


def _format_for_node_command(value_type: str, value: object) -> str | None:
    text = str(value)
    if value_type == "s" and any(c in text for c in _UNSAFE_NODE_COMMAND_CHARS):
        return None
    return text


def _extract_reply_value(reply, value_type: str, address: str = "") -> tuple[object, str | None]:
    """Pull the value this project actually cares about out of a GET
    reply. The actual extraction (which argument to trust out of a
    multi-arg reply, e.g. fader's [raw-text, raw fraction, real dB value])
    lives on `OscReply.value()` in console.py now -- shared with
    `audit.py`'s `read_console_state`, which needed the identical logic
    rather than its own naive `args[0]`. This wrapper adds the
    `reply is None` case, which a method on `reply` itself can't handle,
    and the index-base correction below.

    `address` drives `console_facts.correct_readback_index`:
    WING's GET reply for a patch connector is one less than the value its
    SET takes, so a reply has to be corrected before anything compares it
    to an intended value. Defaulted to "" -- and therefore to no
    correction -- so a caller that has no address cannot accidentally get
    one applied.

    Correcting HERE rather than at the comparison covers both reads that
    matter, and the second one is the one that hurt: `apply` reads an
    address before deciding whether to write it at all, and on the
    2026-09-18 run that uncorrected baseline read hid **five genuinely
    wrong physical patches** behind a false "already correct, skip". The 20
    false MISMATCH lines were noise; this was the failure
    direction that actually costs a show.
    """
    if reply is None:
        return None, "no_reply"
    value, error = reply.value(value_type)
    if error is None:
        value = facts.correct_readback_index(address, value)
    return value, error


# A float leaf whose readback steps are coarser than the 2% below, as a
# relative tolerance, keyed by the end of the address. Release
# times: sixpiece's apply of 2026-09-29 read gate/rel 551.6 back as
# 565.0 and dyn/rel 275.0 as 267.3 -- 2.4-2.8%, the nearest step each
# time, and all ten were journalled as MISMATCHes. 3% covers the worst
# seen; it is still under one step, so no distinct value is swallowed.
_REL_TOLERANCE = {"gate/rel": 0.03, "dyn/rel": 0.03}

# A float leaf the desk will not hold below a floor: it stores the floor
# instead, so a value under it IS the floor. `in/set/dly` in metres reads
# 0.1 on a fresh strip and after a write of 0.0 (the same run: 21 presets
# asked for 0.0, every one read back 0.1 and was called a MISMATCH).
_DESK_FLOOR = {"in/set/dly": 0.1}


# A stage box's own preamp gain, read back after a write. An
# apply of 2026-10-09 through a Behringer stage box on AES50 A: all 16
# gains read back half a dB high -- 20.0 asked, 20.5 held; 0.0 asked,
# 0.5 held. The box sets its own preamps and answers on its own steps,
# which are not the desk's (every earlier run, with nothing on AES50,
# read 20.0 back as 20.0). Within half a dB the box has set the gain, as
# near as it can. Only on a READBACK: whether a write is needed at all is
# still decided exactly, so a desk that CAN hold 20.0 is never left at
# 19.5 because the two were "close" -- the 2026-09-22 Q lesson below.
_STAGE_BOX_GAIN_RE = re.compile(r"^/io/in/[ABC]/\d+/g$")
_STAGE_BOX_GAIN_TOLERANCE_DB = 0.5


def _keyed(table: dict, address: str | None):
    """`table`'s entry for the address that ends with one of its keys."""
    address = str(address or "")
    return next((v for k, v in table.items() if address.endswith("/" + k)), None)


def _values_equal(value_type: str, a: object, b: object, address: str | None = None,
                  *, readback: bool = False) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if value_type == "f":
        try:
            if readback and _STAGE_BOX_GAIN_RE.match(str(address or "")):
                return abs(float(a) - float(b)) <= _STAGE_BOX_GAIN_TOLERANCE_DB + 1e-9
            floor = _keyed(_DESK_FLOOR, address)
            if floor is not None:
                a, b = max(float(a), floor), max(float(b), floor)
            rel_tol = _keyed(_REL_TOLERANCE, address)
            if rel_tol is not None:
                return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=0.02)
            # WING's fader/log parameters are stepped (e.g. flt.lcf: 641
            # steps over 20-2000Hz), so a value read back after a write is
            # the nearest step, not bit-identical to what was sent --
            # exact equality would report every single write as a
            # mismatch. The RELATIVE tolerance is what does that work, and
            # 2% covers every stepped readback observed on hardware: the
            # worst across three real journals is 19.6Hz on a 5000Hz band.
            #
            # The absolute floor is only there for values at or near zero,
            # where a relative tolerance degenerates. It used to be 0.5,
            # and that was wrong in a way that cost a silent failure.
            #
            # 2026-09-22, the A3 run: `/ch/1/eq/1q` asked for Q=1.4
            # against a prior of 0.998. |1.4 - 0.998| = 0.402 < 0.5, so
            # this function said "already correct", `apply` SKIPPED THE
            # WRITE, and the journal reported `skipped_no_change`. Same
            # for band 4's Q. Two stated values never reached the desk and
            # nothing said so. Q is `0.44..10 in 181 steps` (PDF p.49) --
            # about 0.05 per step -- so a 0.5 floor swallowed ten steps of
            # a parameter whose whole range is under ten. Gain is 0.1 per
            # step and fared no better in principle.
            #
            # 0.02 is set from the data rather than from taste: the worst
            # genuine Q readback error in those journals is 0.002, and
            # re-scoring all 1900+ float writes across the 2026-09-18,
            # A1 and A3 journals at this tolerance changes exactly the two
            # broken verdicts and nothing else.
            return math.isclose(float(a), float(b), rel_tol=0.02, abs_tol=0.02)
        except (TypeError, ValueError):
            return a == b
    if value_type == "s" and a != b and isinstance(a, str) and isinstance(b, str):
        # A list choice whose tokens are numbers -- a compressor's ratio
        # ("5.0"), a filter's slope ("24") -- is one choice however it is
        # spelled: "5" and "5.0" name the same entry. A preset carries
        # `dyn.ratio` as a bare number and the desk lists it as "5.0". Only when BOTH sides read as numbers, so a
        # name or an enum word is still compared exactly.
        try:
            return math.isfinite(float(a)) and float(a) == float(b)
        except ValueError:
            return False
    return a == b


def _write_target(console, target: WriteTarget, value) -> tuple[str, str | None]:
    """Send one write. Returns (method, ack) -- ack is "OK", a console
    error token, "no_ack_path" (set_param truly has nothing to check), or
    None if the node write got no reply at all (timeout/transport).

    Raises OSError if the reply is a genuine socket-level
    failure (host/network unreachable, connection refused, ...) rather
    than returning an ack string for it -- a dead connection isn't a
    per-write outcome, it means every remaining target will fail
    identically, and `apply_plan()`'s loop needs one thing to catch to
    stop the whole run rather than record that hundreds of times. A
    DECODE_ERROR (bytes arrived but didn't parse) stays a soft per-write
    ack, same as before -- it says nothing about whether the connection
    itself is alive. `console.set_param()`'s own `sendto()` already
    raises OSError natively on the same class of failure -- nothing new
    needed there, it propagates through this function unchanged, so both
    paths converge on the exact same exception type.

    No fdr/mute value whitelist here (the old rule's assertion) -- what
    keeps this module from mixing is structural, not a check against a
    fixed literal: `_fader_starting_target`/`_mute_starting_target` are
    the only functions that ever build one of these WriteTargets, and
    both source their value only from a plan entry's own stated
    `fader` or this module's documented default. See the module
    docstring's fader/mute section."""
    node_address, key = target.address.rsplit("/", 1)
    text = _format_for_node_command(target.value_type, value)
    if text is not None:
        reply = console.set_node(node_address, f"{key}={text}")
        if reply is None:
            return "node", None
        if reply.is_socket_error:
            raise OSError(reply.args[0] if reply.args else "socket error")
        if reply.is_transport_error:
            return "node", f"transport_error: {reply.args}"
        return "node", (reply.error or "OK")
    console.set_param(target.address, value, target.value_type)
    return "param", "no_ack_path"


@dataclass
class _PendingCheck:
    """One written address whose readback disagreed, held back for the
    reconciliation pass at the end of the run (`_recheck_disagreements`).

    `mark` is the console's datagram count taken BEFORE the write: no
    reply received at or before it can say anything about this write, so
    it is the guard that keeps a duplicate of the pre-write value from
    being read as confirmation."""

    record: WriteRecord
    target: WriteTarget
    intended_value: object
    mark: int


def _reply_mark(console) -> int:
    """The console client's monotonic datagram count, or 0 for a client
    that doesn't keep one. Read through getattr because `console` is a
    structural duck type, not an interface -- tests substitute their own
    (see apply_plan's docstring)."""
    return getattr(console, "datagrams_received", 0)


def _late_confirmation(console, target: WriteTarget, intended_value, after: int):
    """The drained datagram that proves this write landed, or None.

    A reply the client discarded because it answered a
    different request is still an addressed statement about the address
    it names, and on the unacked (`set_param`) path that is often the
    only place the console says the write landed: it answers the readback
    with the pre-write value and pushes the new one a datagram or two
    later, by which time the client is reading the next address. Consult
    it and the round trip that would otherwise be needed disappears.

    Three conditions, and all three are needed for this to be incapable
    of inventing a match:

    1. The datagram names THIS address. `console.late_reply` will not
       offer one filed under any other (a lesson from the first live runs).
    2. It arrived after `after`, the datagram count from before the
       write. The console duplicates pre-write replies too.
    3. Its value equals the intended value under the same comparison
       every other verdict in this module uses. A late datagram carrying
       anything else settles nothing and is left where it is.

    A console that never accepted the write never emits such a datagram,
    so there is nothing for this to find -- which is the property
    `test_a_write_the_console_never_accepted_is_still_a_mismatch` pins
    down."""
    lookup = getattr(console, "late_reply", None)
    if lookup is None:
        return None
    reply = lookup(target.address, after=after)
    if reply is None:
        return None
    value, error = _extract_reply_value(reply, target.value_type, target.address)
    if error is not None or not _values_equal(target.value_type, value, intended_value,
                                                target.address, readback=True):
        return None
    consume = getattr(console, "use_late_reply", None)
    if consume is not None:
        consume(target.address)
    return reply


def _adopt_reply(pending: _PendingCheck, value, source: str) -> bool:
    """Rewrite one record's verdict to "the write landed", recording
    which reading settled it. Returns whether it did.

    This is the only function in this module that can turn a recorded
    failure into a pass, so it re-checks the value itself rather than
    trusting its callers to have done it. Belt and braces on purpose:
    every path into it already compares, and a later edit that adds one
    which doesn't must not be able to fabricate a match."""
    if not _values_equal(pending.target.value_type, value, pending.intended_value,
                         pending.target.address, readback=True):
        return False
    pending.record.readback_value = value
    pending.record.status = "match"
    pending.record.readback_source = source
    return True


def _prefetch_baselines(console, targets: list[WriteTarget], known: dict,
                        phase) -> dict[str, object]:
    """`{address: reply}` for every preview target's baseline the reset's
    read did not already give (`known`), read with up to the console's
    window of requests in flight (`console.read_in_windows`).

    Only for a preview: it writes nothing, so a value read now is the
    value the loop would have read when it reached the target. Each
    address is asked once, and `phase` counts every target that reads it
    as its reply comes in -- so the progress line moves while the read
    does, and names an address that goes unanswered."""
    from atoo import console as osc

    wanted: dict[str, list[WriteTarget]] = {}
    for target in targets:
        if target.address not in known:
            wanted.setdefault(target.address, []).append(target)
    out: dict[str, object] = {}
    for address, reply in osc.read_in_windows(console, list(wanted),
                                              on_start=phase.start_address):
        out[address] = reply
        for target in wanted[address]:
            phase.start_address(address)
            _, error = _extract_reply_value(reply, target.value_type, address)
            phase.finish_address(answered=error is None)
        if reply is not None and reply.is_socket_error:
            break
    return out


def _recheck_disagreements(console, pending: list[_PendingCheck], *,
                           phases=None) -> str | None:
    """Second look at every address whose readback disagreed, once the
    rest of the run has gone by. Returns a warning to record, or None.

    This is what replaced the immediate re-read plus a 0.1s sleep that
    earlier versions used. The sleep was a guess at how long the
    console needs; this waits as long as the remainder of the run takes,
    costs no sleep at all, and -- for the case the hardware actually
    shows -- costs no round trip either, because the console has already
    said what we need to know and the client kept it.

    Order matters, and it is three passes rather than one because a GET
    returns the FIRST matching datagram in the queue, which may itself be
    a stale copy with a newer one behind it:

    1. Consult the drained datagrams. Free, and this is the pass that
       resolves `/ch/7/tags` from the 2026-09-21 A1 run.
    2. For whatever is left, one ordinary re-read each -- the same single
       re-read as before, just deferred to a point where the race is long
       over. Bounded by the number of disagreements (1 in 670 addresses
       on that run), never paid per write.
    3. Consult the drained datagrams once more: pass 2's reads drain
       whatever the console had queued up, including for other addresses.

    A verdict only ever moves from mismatch/unreadable to match here,
    never the other way: a re-read that disagrees again leaves the
    original reading standing, exactly as the immediate re-read did."""
    unsettled = []
    for check in pending:
        reply = _late_confirmation(console, check.target, check.intended_value, check.mark)
        if reply is None:
            unsettled.append(check)
            continue
        value, _ = _extract_reply_value(reply, check.target.value_type, check.target.address)
        if not _adopt_reply(check, value, "late_reply"):
            unsettled.append(check)

    still_unsettled = []
    lost_connection = False
    # Pass 2 is the only one that asks the desk anything.
    phase = phases.start(RECHECK_PHASE, len(unsettled)) if phases and unsettled else None
    for check in unsettled:
        if phase is not None:
            phase.start_address(check.target.address)
        reply = console.get(check.target.address)
        if phase is not None:
            phase.finish_address(answered=reply is not None and not reply.is_transport_error)
        if reply is not None and reply.is_socket_error:
            # The writes are all done and journalled; there is nothing
            # left to abort. Stop re-checking, leave the verdicts as
            # recorded (the conservative direction), and say so.
            lost_connection = True
            still_unsettled.append(check)
            break
        value, error = _extract_reply_value(reply, check.target.value_type, check.target.address)
        if error is not None or not _adopt_reply(check, value, "recheck"):
            still_unsettled.append(check)
    if phase is not None:
        phase.finish()

    if not lost_connection:
        for check in still_unsettled:
            reply = _late_confirmation(console, check.target, check.intended_value, check.mark)
            if reply is None:
                continue
            value, _ = _extract_reply_value(reply, check.target.value_type, check.target.address)
            _adopt_reply(check, value, "late_reply")

    if lost_connection:
        # Counted over `pending`, not over what this pass got through
        # before the socket died -- the addresses it never reached are
        # exactly the ones nobody re-checked either.
        unresolved = sum(1 for check in pending if check.record.status != "match")
        return (
            f"lost the connection to the console while re-checking "
            f"{unresolved} address(es) whose readback disagreed -- their "
            "verdicts above are the reading taken at write time."
        )
    return None


#: What each long stretch of `apply_plan` is called on the progress line. Plain words, so whoever is watching can tell which step is
#: the slow one. A write is read back as soon as it is sent, so the write
#: phases name both.
PREVIEW_PHASE = "reading the desk for the preview"
RESET_WRITE_PHASE = "resetting to initialized, reading each back"
#: The plan's own stretch looks at every setting it states and sends only
#: those the desk does not already hold, so its count is of settings looked
#: at, and its summary line says how many of them were written.
WRITE_PHASE = "checking each setting, writing what differs"
RECHECK_PHASE = "reading back again what disagreed"


def apply_plan(
    plan: dict,
    console,
    *,
    dry_run: bool = True,
    journal_path: str | None = None,
    set_fader_levels: bool = True,
    clean_output_sockets: dict[str, int] | None = None,
    target_filter: Callable[[WriteTarget], bool] | None = None,
    journal_scope: dict | None = None,
    extra_targets: list[WriteTarget] | None = None,
    desk: dict | None = None,
    model_check: dict | None = None,
    full_apply: bool = False,
    initialize: bool | None = None,
    init_model: str | None = None,
    init_token: str | None = None,
    phases=None,
) -> ApplyResult:
    """Apply a plan (a generated plan.json, per plan_schema) to a live
    console, or preview it without changing anything.

    FR-X.2: `dry_run` defaults to True. Writing anything at all requires
    the caller to explicitly pass `dry_run=False` -- there is no other way
    to arm this function, on purpose.

    FR-X.1: every address this function might write is also read back,
    in both modes -- dry_run reads the CURRENT value so its preview shows
    a real before/after, not just the plan's intended value in isolation.

    FR-X.3: when `journal_path` is given, every address this run touched
    (both modes) is written there as JSON -- address, prior value,
    intended value, actual readback, ack, and a timestamp -- enough to
    reverse a real apply without re-reading the console afterward, since
    prior_value was captured before this run changed anything.

    `set_fader_levels` (default True): when true, every channel/aux
    strip, bus, and Main/Matrix output this plan builds also gets `fdr`
    and `mute` set to whatever the conventions stated (channel/bus/output
    entry's own `fader`) or this module's documented default
    (unity, unmuted) when they stated nothing -- see the module
    docstring's fader/mute section for the full "stated vs invented"
    reasoning and why this is right here specifically, not a general
    "this tool mixes now". An amend (`atoo/amend.py`) leaves this
    **True** and scopes the run with `target_filter` instead: the strips
    it adds want their stated starting state exactly as a full build's do,
    and the strips it must not touch have no address generated for them
    at all. Whichever way it's set, `fdr`/`mute` are only ever built by
    `_fader_starting_target`/`_mute_starting_target` from the plan's own
    value or the documented default -- never a value this function
    invents on its own (see `_fader_targets`).

    `console` is any object exposing WingConsole's get/set_param/set_node
    methods (atoo.console.WingConsole satisfies this structurally;
    tests substitute a fake with the same three methods -- see
    tests/test_apply.py -- there is deliberately no isinstance check).
    `late_reply`/`use_late_reply`/`datagrams_received` are
    consulted through getattr and simply not used by a console object
    that lacks them, so an older or narrower double still works.

    Per-address `status` values: "dry_run" (preview only, nothing sent),
    "skipped_no_change" (current value already matches the plan, nothing
    sent), "unreadable" / "unreadable_skipped" (the baseline GET itself
    failed -- writing without a known prior value would break FR-X.3, so
    this function refuses to write past that point for this address),
    "match" (written and read back equal to intended, within tolerance),
    "mismatch" (written but the readback disagrees -- reported by
    address with expected vs actual, never swallowed, per the brief).
    **Selectors.** A value governed by a selector this run
    changes (`preset_expand.governs`: `in/set/dly` under `in/set/dlymode`,
    `dyn/*` under `dyn/mdl`, ...) is never `skipped_no_change`. Its
    baseline is read just BEFORE the selector is written -- the desk
    re-reads it when the selector lands, so a reading taken afterwards
    proves nothing -- and it is written and read back after the selector
    whatever that baseline said. Its record carries `forced_by`, the
    selector's address, and `_selector_notes` says how many at INFO. The
    build orders every strip's processing selectors, values, switches
    (`_ordered_processing`), so a governed value always comes after its
    selector.

    A "mismatch"/"unreadable" verdict reached during the loop is not
    final: every one of them is re-examined by `_recheck_disagreements`
    once the run is over, and `WriteRecord.readback_source` records
    which reading settled any that changed.

    A "dry_run" record deliberately does NOT split into "would change" and
    "already correct" statuses -- a preview asked the console but never
    asked it to do anything, and a preview-only twin of
    `skipped_no_change` would give the journal two vocabularies to keep in
    step. The question is answered on demand instead, by
    `WriteRecord.would_change`, which calls the same `_values_equal` this
    loop calls two branches down: one comparison, one place.

    A genuine socket-level failure (host/network unreachable, connection
    refused, ...) on any read or write stops the whole run immediately
    rather than recording it as an ordinary per-address
    "unreadable" outcome -- unlike a single WING error token or a
    decode hiccup, a socket error almost always means every remaining
    address will fail identically, so there is nothing to gain and a
    lot of noise to produce by ploughing on through the rest of a
    600-address plan. `ApplyResult.aborted`/`abort_reason` carry this;
    `records` holds only the addresses actually evaluated before the
    connection died, never a placeholder for the ones that weren't.

    `clean_output_sockets` (default None): opt-in
    ONLY -- a decision of 2026-09-19: option B must be turned on, not the
    default. None (the default) behaves exactly as
    before this existed: this function only ever writes an address the
    plan itself names. Given `{group: count}` (the same shape `audit.py`'s
    `read_console_state(output_sockets=...)` already takes, since there is
    no safe default socket count either place), every physical output
    socket in that range this plan doesn't declare a route for
    (`_declared_output_patches`) gets a `.grp = "OFF"` target appended
    alongside the plan's own -- see `_clean_write_targets`'s docstring for
    why only `.grp`, and why it's safe to just append these rather than
    build a separate write pass: an already-OFF socket costs one baseline
    read and nothing else (`skipped_no_change`), and cleaning is defined
    as the exact complement of what the plan itself already targets, so
    there is never a duplicate write to the same address.

    `target_filter` (default None): a predicate over
    `WriteTarget`. When given, every target it rejects is dropped BEFORE
    the loop -- not read, not written, not journalled -- so this function
    never so much as sends a GET to an address the caller does not own.
    This is how `atoo/amend.py` writes only the strips an amend is
    adding while a show is running, and it is the mechanism FR-2.2 is
    satisfied by: "shall not modify any parameter belonging to a channel
    not named in the delta" is kept by never generating the address, not
    by a flag that suppresses some of its leaves. None (the default)
    leaves the full-build path byte-for-byte as it was.

    `journal_scope` (default None): recorded verbatim in the journal as
    `scope`, and carried on `ApplyResult.scope`. A full build passes
    nothing, because the answer is "everything". An amend passes
    `{"strips": ["ch:21", "ch:22", "ch:23"], "grants": {...}}`, so the
    journal can answer what the run was ALLOWED to touch and not only
    what it happened to touch -- the difference between a proof and a
    coincidence when the two are read back weeks later.

    `extra_targets` (default None): writes the plan itself
    cannot produce, because they are about an object the plan no longer
    contains. `amend` uses it for exactly one thing -- returning a strip
    the rebuild dropped to free (`release_write_targets`) -- and the
    targets still go through `target_filter`, the baseline read, the
    readback proof and the journal like every other write here. There is
    no second write path and no second arming: a release happens on the
    same `dry_run=False` as everything else in the run, or not at all.

    `desk` / `model_check` (default None): recorded verbatim in the
    journal, like `journal_scope`. `desk` is which console this run was
    pointed at, carrying the model token it sent; `model_check` is what
    `check_desk_model` said about that desk against this plan, when it
    said anything. Neither changes what is written.

    `full_apply` (default False, 2026-10-02): this run writes the WHOLE
    show, so it also unpatches every strip the plan does not build and
    sets talkback's assign to the plan's talkback strip
    (`full_apply_targets`; see the section comment above it), with one
    INFO line each. Only `atoo apply` passes it -- the Apply page runs
    that command. `amend`, `patch` and `undo` never do (D14: they touch
    only strips they own), and passing it with `target_filter` or
    `extra_targets`, the marks of a scoped run, is refused.

    `initialize` (default None): True, before the plan's writes,
    reset the desk to `init_model`'s initialized capture -- read it by node
    dump, write only what differs, never a leaf the run writes itself, and
    never anything on `initialize.SKIP_LIST`. See `atoo/initialize.py`.
    Only with `full_apply`. A model with no capture (the WING Rack), or an
    unresolved desk (`init_model` None; `init_token` is what it called
    itself), is a WARNING, and the plan is written without the reset. The
    reset's writes go through this same loop -- baseline (taken from the
    read, not asked for again), write, readback, journal -- so undo
    reverses them with the rest of the run, and one INFO line counts them
    by area and says how long it took. False is a full apply whose caller
    chose not to (`apply --no-init`), said at INFO; None says nothing.

    `phases` (default None): a `progress.Phases`, told of each
    long stretch of the run as it happens -- the reset's read
    (`initialize.READ_PHASE`), then either the preview's read
    (`PREVIEW_PHASE`) or the reset's writes and the plan's writes
    (`RESET_WRITE_PHASE`, `WRITE_PHASE`; each write is read back as it
    goes), then the second look at what disagreed (`RECHECK_PHASE`).
    None is silent. It changes nothing that is read, written or journalled.
    """
    from atoo.progress import NO_PHASES

    phases = NO_PHASES if phases is None else phases
    if full_apply and (target_filter is not None or extra_targets):
        raise ValueError("full_apply is a whole-show apply: it cannot be scoped by "
                         "target_filter or extra_targets")
    if initialize and not full_apply:
        raise ValueError("initialize resets the whole desk: it is only part of a full_apply")
    targets, warnings = _build_write_targets(plan, set_fader_levels)
    if full_apply:
        # Re-sorted by stage (stable, so the plan's own order within a
        # stage is kept): the unpatches belong with the other patches.
        targets = sorted(targets + full_apply_targets(plan, init_model), key=lambda t: t.stage)
    if clean_output_sockets:
        # A socket a full apply already disconnects is not written twice.
        already = {t.address for t in targets}
        targets = targets + [t for t in _clean_write_targets(plan, clean_output_sockets)
                             if t.address not in already]
    if extra_targets:
        # Appended AFTER the stage sort and BEFORE the filter. After the
        # sort because these carry their own order and it is a safety
        # order, not a dependency order (see `release_write_targets`);
        # before the filter because default-deny has to govern them too --
        # a caller whose scope does not grant its own extra target is a
        # caller whose scope is wrong, and the run should come out empty
        # rather than write it anyway.
        targets = targets + list(extra_targets)
    if target_filter is not None:
        # Filtered HERE, before the loop -- so a target this run does not
        # own is never read, never written and never journalled. A filter
        # applied any later would still have sent a GET to an address
        # belonging to somebody else's strip, and "we only read it" is not
        # a distinction worth having to explain at 6pm.
        targets = [t for t in targets if target_filter(t)]

    # The reset to initialized, before the plan's writes.
    reset = None
    reset_phase = 0
    known: dict[str, tuple[object, str | None]] = {}
    if initialize is False and full_apply:
        from atoo import initialize as init

        warnings = warnings + [init.NO_INIT_NOTE]
    if initialize:
        from atoo import initialize as init

        capture = init.load_capture(init_model)
        if capture is None:
            warnings = warnings + [init.no_capture_warning(init_model, init_token)]
        else:
            reset = init.plan_reset(console, capture, targets, phases=phases)
            if reset.abort_reason is not None:
                return _finish(ApplyResult(
                    dry_run=dry_run, writes=[], journal_path=journal_path, warnings=warnings,
                    aborted=True, abort_reason=reset.abort_reason,
                    replies_discarded=getattr(console, "replies_discarded", 0),
                    replies_used=getattr(console, "replies_used", 0),
                    scope=journal_scope, desk=desk, model_check=model_check))
            targets, reset_phase = init.combine(reset, targets)
            known = reset.known
    reset_started = time.monotonic()
    reset_seconds: float | None = None

    records: list[WriteRecord] = []
    pending: list[_PendingCheck] = []
    abort_reason: str | None = None
    # Governed values whose baseline was read BEFORE their
    # selector was written (address -> that reply), and which selector
    # forces each one to be written (address -> selector address).
    pre_read: dict[str, object] = {}
    forced_by: dict[str, str] = {}

    # What the run is doing, phase by phase. A target is done
    # when the next one starts (or the loop ends): the loop body has a
    # `continue` for every outcome, and this keeps the count out of each.
    phase = None
    in_flight = False
    records_before = 0

    # A preview writes nothing, so every baseline it reads can
    # be read up front, several requests in flight -- and the loop below
    # takes each from here instead of asking. A real run reads each one
    # just before its write, as it always has.
    prefetched = None
    if dry_run and targets and getattr(console, "window", 1) > 1:
        phase = phases.start(PREVIEW_PHASE, len(targets))
        prefetched = _prefetch_baselines(console, targets, known, phase)

    # Where the records of the phase in progress begin, so that when it ends
    # its summary can say how many of its settings were actually written.
    phase_first = 0
    phase_checks_more = False

    def finish_phase() -> None:
        if phase is None:
            return
        if phase_checks_more:
            phase.written = sum(1 for r in records[phase_first:]
                                if r.status in ("match", "mismatch", "unreadable"))
        phase.finish()

    def step_done() -> None:
        nonlocal in_flight
        if in_flight:
            last = records[-1] if len(records) > records_before else None
            phase.finish_address(answered=last is None
                                 or not last.status.startswith("unreadable"))
            in_flight = False

    for index, target in enumerate(targets):
        step_done()
        if (index == 0 and prefetched is None) or (
                not dry_run and reset is not None and index == reset_phase):
            finish_phase()
            phase_first = len(records)
            phase_checks_more = False
            if dry_run:
                phase = phases.start(PREVIEW_PHASE, len(targets))
            elif reset is not None and index < reset_phase:
                phase = phases.start(RESET_WRITE_PHASE, reset_phase, writes=True)
            else:
                phase = phases.start(WRITE_PHASE, len(targets) - index, writes=True)
                phase_checks_more = True
        if prefetched is not None and target.address in prefetched:
            # Counted by the phase as its reply came in.
            in_flight = False
        else:
            phase.start_address(target.address)
            in_flight = True
        records_before = len(records)
        if index == reset_phase and reset is not None and reset_seconds is None:
            reset_seconds = time.monotonic() - reset_started
        if prefetched is not None and target.address in prefetched:
            prior_reply = prefetched[target.address]
        elif target.address in pre_read:
            prior_reply = pre_read.pop(target.address)
        elif target.address in known:
            # The reset's baseline, from the read it was decided on
            #  -- asking again would double the read.
            prior_reply = None
        else:
            prior_reply = console.get(target.address)
        if prior_reply is not None and prior_reply.is_socket_error:
            abort_reason = prior_reply.args[0] if prior_reply.args else "socket error"
            break
        if prior_reply is None and target.address in known:
            prior_value, read_error = known.pop(target.address)
        else:
            prior_value, read_error = _extract_reply_value(
                prior_reply, target.value_type, target.address)
        timestamp = datetime.now(timezone.utc).isoformat()
        # Computed even when the baseline read failed (prior_value is None
        # in that case) -- a literal target ignores its input entirely, so
        # the preview stays useful; only the tags merge (_merge_tags)
        # actually depends on a real prior value, and it degrades to
        # "start from no existing tags" the same way a fresh channel would.
        intended_value = target.compute_value(prior_value)

        # A value governed by a selector this run changed was read under
        # the OLD selector, and a value that exists only
        # under the new one could not be read at all: sixpiece's apply
        # of 2026-09-29 switched ch 16-22's gate/mdl GATE -> PSE and then
        # skipped gate/depth, gate/fast and gate/peak as unreadable -- 21
        # preset values that never reached the desk. There was nothing to
        # read because there was nothing there; the write goes ahead, with
        # no prior (undo restores the selector, which takes the value away
        # again), and its readback under the new selector decides it. The
        # preview says the same: a change, forced by the selector.
        if read_error is not None and target.address not in forced_by:
            records.append(WriteRecord(
                address=target.address, description=target.description, value_type=target.value_type,
                method=None, ack=None,
                prior_value=None, intended_value=intended_value, readback_value=None,
                status="unreadable" if dry_run else "unreadable_skipped",
                timestamp=timestamp,
            ))
            continue

        forced = forced_by.get(target.address)
        unchanged = _values_equal(target.value_type, prior_value, intended_value, target.address)

        if dry_run:
            records.append(WriteRecord(
                address=target.address, description=target.description, value_type=target.value_type,
                method=None, ack=None,
                prior_value=prior_value, intended_value=intended_value, readback_value=None,
                status="dry_run", timestamp=timestamp, forced_by=forced,
            ))
            if not unchanged:
                # The preview says what the real run will do: a selector
                # that would change forces its governed values too.
                for governed in _governed_later(targets, index):
                    forced_by.setdefault(governed.address, target.address)
            continue

        if unchanged and forced is None:
            records.append(WriteRecord(
                address=target.address, description=target.description, value_type=target.value_type,
                method=None, ack=None,
                prior_value=prior_value, intended_value=intended_value, readback_value=prior_value,
                status="skipped_no_change", timestamp=timestamp,
            ))
            continue

        # This selector is about to change, and the desk will
        # re-read every value it governs. Read those values' baselines NOW,
        # under the selector they were set under -- that is the prior an
        # undo must restore -- and mark each one to be written after the
        # selector whatever its baseline says, so the run proves it landed.
        governed_values = _governed_later(targets, index)
        present = (_leaves_present(console, target.address)
                   if any(g.address not in known for g in governed_values) else None)
        for governed in governed_values:
            if governed.address in forced_by:
                continue
            if governed.address in known:
                # Its baseline was read before anything was written.
                forced_by[governed.address] = target.address
                continue
            if present is not None and governed.address not in present:
                # Not on the desk under the old selector (a PSE gate's
                # depth, under GATE), so there is no baseline to read --
                # and asking would cost the full timeout and its retries:
                # sixpiece's apply of 2026-09-29 spent 63 of its 65
                # seconds on 21 such reads, 3 s each.
                pre_read[governed.address] = None
                forced_by[governed.address] = target.address
                continue
            reply = console.get(governed.address)
            if reply is not None and reply.is_socket_error:
                abort_reason = reply.args[0] if reply.args else "socket error"
                break
            pre_read[governed.address] = reply
            forced_by[governed.address] = target.address
        if abort_reason is not None:
            break

        # The mark goes here, before the write: any datagram the client
        # receives from now on is a candidate answer to THIS write, and
        # anything it already had is not (see `_late_confirmation`).
        mark = _reply_mark(console)
        try:
            method, ack = _write_target(console, target, intended_value)
        except OSError as exc:
            abort_reason = str(exc)
            break
        # Read back -- and when the readback disagrees, do NOT conclude
        # anything yet. This is a race, confirmed twice on hardware.
        # `set_param` is fire-and-forget: the protocol gives it no ack, so
        # there is nothing to wait on before reading, and the console
        # answers the read from the value it held BEFORE the write, then
        # pushes the new one as its own datagram a moment later:
        #
        #   SET (no-ack) /bus/10/name = 'VOX Delay'
        #   GET /bus/10/name -> ''            <- the reply we believed
        #   GET /bus/11/name -> '' for /bus/10/name    (stale, discarded)
        #   GET /bus/11/name -> 'VOX Delay' for /bus/10/name  (stale, discarded)
        #
        # (from the A1 raw log of 2026-09-21.
        # `/ch/7/tags` on the 21:00 run of the same night does it one
        # worse: the readback AND an immediate re-read both answered '',
        # and the value arrives in two datagrams drained during
        # `/ch/8/tags`.)
        #
        # The write had landed both times; the journal called both a
        # MISMATCH. Those are the only writes in the run that took the
        # unacked path, because `_UNSAFE_NODE_COMMAND_CHARS` sends any
        # value containing a space, comma or equals through `set_param` --
        # 'VOX Delay' has a space, '#D7,#M1' has a comma.
        #
        # A false mismatch is not harmless here. It is the tool crying
        # wolf about its own central claim, and the exit code is non-zero,
        # so a script cannot tell one from the real thing.
        #
        # So: consult the datagrams the client drained (free), and if they do not settle it, hold the address back for
        # `_recheck_disagreements` after the loop rather than spending a
        # round trip and a sleep here, in the middle of the race.
        readback_reply = console.get(target.address)
        readback_value, readback_error = _extract_reply_value(
            readback_reply, target.value_type, target.address)
        readback_source = None
        disagrees = readback_error is not None or not _values_equal(
            target.value_type, readback_value, intended_value, target.address, readback=True)
        if disagrees and not (readback_reply is not None and readback_reply.is_socket_error):
            late = _late_confirmation(console, target, intended_value, mark)
            if late is not None:
                readback_reply = late
                readback_value, readback_error = _extract_reply_value(
                    late, target.value_type, target.address)
                readback_source = "late_reply"

        if readback_reply is not None and readback_reply.is_socket_error:
            abort_reason = (
                f"{readback_reply.args[0] if readback_reply.args else 'socket error'} "
                f"(the write to {target.address} was sent -- whether it landed is unknown)"
            )
            break
        if readback_error is not None:
            status = "unreadable"
        elif _values_equal(target.value_type, readback_value, intended_value, target.address,
                           readback=True):
            status = "match"
        else:
            status = "mismatch"
        record = WriteRecord(
            address=target.address, description=target.description, value_type=target.value_type,
            method=method, ack=ack,
            prior_value=prior_value, intended_value=intended_value, readback_value=readback_value,
            status=status, timestamp=timestamp, readback_source=readback_source,
            forced_by=forced,
        )
        records.append(record)
        if status in ("mismatch", "unreadable"):
            pending.append(_PendingCheck(
                record=record, target=target, intended_value=intended_value, mark=mark))

    step_done()
    finish_phase()

    if pending and abort_reason is None:
        recheck_warning = _recheck_disagreements(console, pending, phases=phases)
        if recheck_warning is not None:
            warnings = warnings + [recheck_warning]

    if reset is not None and reset_seconds is None:
        reset_seconds = time.monotonic() - reset_started
    warnings = (warnings + _fixed_default_notes(records) + _selector_notes(records)
                + _stage_box_gain_notes(records))
    if full_apply:
        warnings = warnings + _full_apply_run_notes(records)
    if reset is not None:
        from atoo import initialize as init

        warnings = warnings + init.run_notes(reset, records, dry_run=dry_run,
                                             write_seconds=reset_seconds)

    return _finish(ApplyResult(
        dry_run=dry_run, writes=records, journal_path=journal_path, warnings=warnings,
        aborted=abort_reason is not None, abort_reason=abort_reason,
        replies_discarded=getattr(console, "replies_discarded", 0),
        replies_used=getattr(console, "replies_used", 0),
        scope=journal_scope, desk=desk, model_check=model_check,
    ))


def _finish(result: ApplyResult) -> ApplyResult:
    if result.journal_path is not None:
        _write_journal(result.journal_path, result)
    return result


def _leaves_present(console, selector: str) -> set[str] | None:
    """The addresses under `selector`'s node as the desk holds them now,
    from one node dump -- or None when that cannot be known (no dump on
    this console, the desk did not answer, or a dump that does not even
    list the selector itself), in which case every value is read on its
    own, as before. Only ABSENCE is taken from the dump: a value it lists
    is still read by GET, so its baseline is typed exactly as ever."""
    dump_node = getattr(console, "node_dump", None)
    if not callable(dump_node):
        return None
    node = selector.rpartition("/")[0]
    try:
        dump = dump_node(node)
    except OSError:
        return None
    if not dump:
        return None
    from atoo import console as osc
    try:
        leaves = set(osc.parse_node_dump(node, dump))
    except osc.NodeDumpError:
        return None
    return leaves if selector in leaves else None


def _governed_later(targets: list[WriteTarget], index: int) -> list[WriteTarget]:
    """The targets after `targets[index]` whose value that target governs
    (`preset_expand.governs`) -- empty unless it is a
    selector. Only LATER targets: the build orders every strip's
    processing selectors first (`_ordered_processing`), so a governed
    value never precedes its selector in a run."""
    from atoo import preset_expand

    selector = targets[index].address
    if preset_expand.write_order(selector) != preset_expand.SELECTOR:
        return []
    return [t for t in targets[index + 1:] if preset_expand.governs(selector, t.address)]


def _selector_notes(records: list[WriteRecord]) -> list[str]:
    """One INFO line for the governed values this run wrote only because
    their selector changed -- a write the reader would
    otherwise take for a redundant one, since the plan's value and the
    baseline agreed."""
    forced = [r for r in records if r.forced_by is not None]
    if not forced:
        return []
    same = [r for r in forced
            if _values_equal(r.value_type, r.prior_value, r.intended_value, r.address)]
    selectors = sorted({r.forced_by for r in forced})
    shown = ", ".join(selectors[:4]) + (f" and {len(selectors) - 4} more" if len(selectors) > 4 else "")
    extra = (f"; {len(same)} of them already read the plan's value under the old selector, "
             "which the desk re-reads when the selector changes" if same else "")
    return [
        f"INFO {len(forced)} value(s) written and read back after their selector changed "
        f"({shown}){extra} -- their prior is the reading taken before the selector was written"]


def _stage_box_gain_notes(records: list[WriteRecord]) -> list[str]:
    """One INFO line for the stage-box gains that were set but read back
    on the box's own steps, not the value asked for (see
    `_STAGE_BOX_GAIN_TOLERANCE_DB`) -- a match, but not silently one."""
    held = [r for r in records if r.status == "match" and _STAGE_BOX_GAIN_RE.match(r.address)
            and r.readback_value is not None
            and not _values_equal(r.value_type, r.readback_value, r.intended_value, r.address)]
    if not held:
        return []
    shown = ", ".join(f"{r.address.split('/')[3]} {r.address.split('/')[4]}: "
                      f"{_format_db(r.intended_value)} asked, {_format_db(r.readback_value)} held"
                      for r in held[:3]) + (f" and {len(held) - 3} more" if len(held) > 3 else "")
    return [f"INFO {len(held)} stage-box preamp gain(s) read back on the box's own steps, "
            f"within {_STAGE_BOX_GAIN_TOLERANCE_DB} dB of the plan ({shown}) -- the box sets its "
            "own preamps over AES50 and holds the nearest step it has"]


def _format_db(value: object) -> str:
    try:
        return f"{float(value):g} dB"
    except (TypeError, ValueError):
        return str(value)


def _fixed_default_notes(records: list[WriteRecord]) -> list[str]:
    """INFO lines for the fixed defaults this run writes on every plan,
    once each rather than once per strip (review 2026-09-28).

    * C2 (R8): every strip the plan builds is put back on its MAIN input
      (`altsrc = 0`). Decision: keep it -- a show apply means
      stage inputs live -- and say how many, and how many were on their
      alternate when read, so a desk parked on its alternates for a
      virtual soundcheck is not flipped back without a line saying so.
    * C4: a direct Main route and a Matrix feed are written at unity,
      post-fader (`MAIN_ROUTE_LEVEL_DEFAULT_DB`, `MAIN_ROUTE_PRE_DEFAULT`)
      -- documented defaults, not per-plan choices, but the level and tap
      of every such route. Announced here, in apply's report, where the
      value is written, and not in verify's findings: verify reports what
      a plan decided, and this is apply's own constant.
    """
    notes: list[str] = []
    alt = [r for r in records if r.address.endswith("/in/set/altsrc")]
    if alt:
        on_alt = [r for r in alt if r.prior_value == 1]
        read = (f"; {len(on_alt)} of them read as on their alternate before this run"
                if on_alt else "")
        notes.append(
            f"INFO {len(alt)} strip(s) set to their main input (not their alternate){read} -- "
            "a show apply means stage inputs live")
    main_routes = sum(1 for r in records
                      if ": direct Main " in r.description and r.description.endswith(" level"))
    matrix_feeds = sum(1 for r in records
                       if ": feed to matrix " in r.description and r.description.endswith(" level"))
    if main_routes or matrix_feeds:
        what = " and ".join(part for part in (
            f"{main_routes} direct Main route(s)" if main_routes else "",
            f"{matrix_feeds} Matrix feed(s)" if matrix_feeds else "") if part)
        notes.append(
            f"INFO {what} set to unity ({MAIN_ROUTE_LEVEL_DEFAULT_DB:g} dB), post-fader -- "
            "apply's documented default; the conventions have no phrasing for a route's own "
            "level or tap")
    return notes


def _write_journal(path: str, result: ApplyResult) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": result.dry_run,
        "writes": [
            {
                "address": w.address,
                "description": w.description,
                # The OSC type tag, so a journal can be
                # re-scored with the same type-aware comparison the run
                # used rather than guessing from the JSON value's shape.
                "value_type": w.value_type,
                "method": w.method,
                "ack": w.ack,
                "prior_value": w.prior_value,
                "intended_value": w.intended_value,
                "readback_value": w.readback_value,
                "status": w.status,
                "timestamp": w.timestamp,
                "readback_source": w.readback_source,
                # Which selector forced this value's write --
                # absent (not null) when none did, so a journal of a run
                # with no selector change is byte-for-byte the old shape.
                **({"forced_by": w.forced_by} if w.forced_by is not None else {}),
            }
            for w in result.writes
        ],
        "warnings": result.warnings,
        "replies_discarded": result.replies_discarded,
        "replies_used": result.replies_used,
    }
    if result.scope is not None:
        payload["scope"] = result.scope
    if result.desk is not None:
        payload["desk"] = result.desk
    if result.model_check is not None:
        payload["model_check"] = result.model_check
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
