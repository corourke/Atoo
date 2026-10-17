"""FR-4/FR-5 proof of concept: audit a console's *live* state against
deterministic structural rules, and trace a signal path across it.

A deterministic rule engine built against the console itself rather than
an exported file or a partial read, and grounded only in addresses this
project has independently confirmed (FR-1.5) -- never in a channel's name text. FR-4.3 makes that a
requirement, not a style choice: "Atoo's audit must not need to
guess what a channel *is*." A rule that would need to infer "this is
probably a kick mic" from a name string doesn't belong here; every rule
below reads only routing, patch, mute/fader and membership facts.

Both the rule engine and the signal-graph tracer (FR-5) consume the same
substrate, `ConsoleState` -- a flat OSC address -> value mapping. It can
come from a live console (`read_console_state`, over `atoo.console`)
or be built by hand / loaded from a JSON fixture, which is how a novice
operator can try this against a worked example with no console attached
at all (`starter/audit-demo/audit_demo_state.json`, which `atoo init` copies; `docs/user/audit.md`).

**A live read is the slowest thing this project does**, and an earlier change is
what that cost: 6,032 serial OSC round trips for a WING Compact reading
its own panel, printing nothing at all until it finished. Two things
came out of it, and `console_read_plan` is the hinge of both -- it builds
the whole address list *before* anything is fetched. A read that knows
its own total can report `read 1200/6195 (19%)` while it works
(`atoo.progress`), and a read that has its addresses in hand can
fetch them by node instead of by leaf (`read_console_state(bulk=True)`,
323 requests instead of 6,143 on a Compact, pipelined eight in flight
). Neither is optional any more: the
first because a tool that cannot be told apart from a hung one gets
killed, the second since A11 found the two paths agreeing on every value
 and the CLI made it the default -- `--per-leaf` is the way
back. A live watch reads less again on most passes: names, which a dump
never carries, are read at Start and on a refresh and handed back in
between (`read_console_state(names=...)`).

**And an earlier change found that most of the wall time was not work at all.**
A11 on hardware: 998.6s for a full per-leaf read, of which **960s** was
three-second timeouts on 320 addresses the console does not have --
`mode` and `pon` on a bus's and a Main's send, which only a *strip's*
send carries (`console_facts.SEND_LEAVES`, `send_fields_for` below). The
plan no longer asks for them, so a read was 5,712 addresses, every one of
which the desk answers -- 5,808 once an earlier change added each strip's
alternate-patch group and switch (C004), and 6,112
added every insert point and what each FX slot holds (E001-003), and
6,113 since its comms half added `/cfg/talk/assign` (T001), 6,114
since the global alternate switch `/io/altsw` (C005), and
6,138 since an earlier change read each phantom-capable socket's width
(`/io/in/{grp}/{n}/mode`, C001), 6,143
read three AES50 link states and two monitor sources, 6,167 since each
local socket's own mute (`/io/in/{grp}/{n}/mute`, C007), and 6,195 since the width of
each bus, Main and Matrix (`busmono`, R011 and CV020). What is left is the real
work, and A11 measured that too: **~39s per-leaf, ~4s by node dump** on 2026-09-22, and
118.8s against 4.8s on 2026-09-24, the run that made the node dump the default. Those 320 were never
values any rule could have had -- nothing is being read less thoroughly,
which is the distinction that matters.

**Proof of concept, not FR-4/FR-5 in full.** Twenty-one rules across
seven categories -- deliberately narrow, since every rule here has to be
defensible from a confirmed address rather than a plausible guess. The
sixth, `effects`, is the first half: E001-003 read each strip's
insert points and what each FX slot holds (`console_facts.INSERT_POINTS`). The seventh,
`communications`, is its other half: T001, talkback assigned to a
strip and routed nowhere (`console_facts.TALK_*`). Listenback is left
out on purpose (nothing confirmed can tell it from a monitor mix);
talkback sharing a strip with a band input needs the plan, so it is
CV014 in the conventions diff.

**What "in use" means (the catalogue's "Vocabulary Rules", 2026-09-23).**
`is_in_use()` is the one definition every rule that needs one reads:
*named, input patched, or has sends -- and, for a bus, receiving sends --
with whatever the console patches and routes by itself excluded unless
something else says otherwise.* The exclusions are the point. A factory
WING Compact (`tests/fixtures/console-runs/Initialized-Compact.snap`) routes all
forty channels and all eight auxes to Main 1, patches channels 1-24 from
their own local sockets and its two media auxes from the USB and media
players, so without them every strip on an untouched desk reads as in use
and this rule set reports 97 findings on a board nobody has plugged
anything into. With them it reports **none at all**.

**And "named" means named where the desk puts a name**. A WING strip is
*linked to its source socket out of the box
(`clink`, protocol PDF p.48), so a name a human types on the channel
screen lands on `/io/in/{grp}/{n}/name` and the strip's own `name` stays
empty. A channel 20 named "Podium" by hand left `/ch/20/name` reading
blank; sitting on its factory patch, the strip classified as *free*.
`is_in_use()` reads the socket too now -- discounting the labels the desk
ships with, `'USB 1/2'` on USB and `'2TR'` on PLAY, or an untouched
Compact's two media auxes would read as somebody's work. A live read
fetches those socket names in a second pass, because which socket to ask
about is not knowable until the patch has been read
(`source_name_addresses`). This is still whether a strip is named and
what the name is, never what the channel *is* (FR-4.3).

**The same second pass asks what is fitted in an expansion bay**, but only for a bay something on the desk is patched from or
routed to (`expansion_bay_addresses`). A WING accepts and reads back a
patch from `MOD` with no module fitted, and the channel is silent; C003
is the finding. A desk that uses neither bay pays nothing for it, and a
state that never read the bay -- any capture made before this -- leaves
the rule silent rather than calling the patch clean.

Which patches the console made by itself is a fact about the model, and
it is measured per model in `console_facts.FACTORY_INPUT_PATCHES` -- on
the Compact and the full-size WING. Any other model falls back to the
channel-n-from-LCL-n identity alone, which is the direction that reports
too much rather than too little. `ConsoleState.console_model` is how a
reading says which desk it came off.

**Rule scope.** A structural rule knows nothing about a
plan, which is right until there is one. `run_audit(state, plan=...)`
scopes the result two ways -- it drops a convention-scoped finding about
an object the plan never mentions, and it stands any rule down where the
plan STATES the parameter that rule is complaining about, because a
conventions-diff rule below already checks that parameter against what
was asked for. Both are counted and reported, never silently applied
(`ScopedAudit.summary()`), and neither does anything without a plan. See
the "Plan scope" section and `RuleScope` for the per-rule table.

FR-4.1's conventions-diff audit (comparing live state against a
*compiled plan*, so a finding can cite "this contradicts your Drums
convention" instead of just a structural fact) is now PARTIALLY
covered, not done: `diff_against_plan()` compares eight plan-channel
fields that already have a direct live-state counterpart -- mute,
fader level, DCA membership, mute-group membership, patch, bus sends
(on/level/mode), direct-to-Main routes, and a channel's or aux's processing
(trim, balance, invert, head-amp gain, and the high-pass, hi-cut, tilt and
EQ the plan states) -- plus a bus's and a DCA's own fader and mute,
which nothing compared at all until `plan_schema.DCA_SCHEMA`
gave a DCA somewhere to state one. The filters and the EQ are `log`
controls, compared with `apply`'s own readback tolerance (2%) rather than the
fader's half a decibel, and read only when `audit --plan` states them
(`plan_processing_read_addresses`). Deliberately still NOT diffed: the
compressor (no schema), a bus's, Main's or Matrix's EQ, and a channel's
PreSend EQ.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Mapping

# Reused rather than re-derived, so the diff and the write path this
# module never touches can't quietly drift apart: the plan
# send-mode text -> WING enum mapping, and the physical-source groups
# confirmed to carry a head-amp-gain address at all. Both are apply.py's
# own source of truth, imported read-only -- this module writes nothing.
# `_declared_output_patches` too, so "what does the plan
# declare for /io/out/*" can never independently drift from what
# apply.py would actually write (it shares apply.py's own `_output_slot`
# L/R slot arithmetic). Deliberately not the whole of
# `_build_write_targets` -- that function assumes a fully-resolved plan
# (e.g. a channel's patch always has a socket), an invariant this
# module's own audit fixtures don't have to hold, so pulling in the
# entire write path here would make an audit crash on exactly the kind
# of partial/unresolved plan an audit is often run against.
from atoo import console_facts, diagnostics, inferred
from atoo.diagnostics import Diagnostic, Severity
from atoo.apply import (
    _SEND_MODE_TO_WING, _VPH_CAPABLE_GROUPS, _channel_processing_targets, _declared_output_patches,
    _values_equal, eq_band_leaves,
)
from atoo.input_list import format_socket
# "which console is this plan for" has one answer, `verify_plan`'s, and an
# audit given a plan needs the same one: the factory-patch table is keyed
# by model, so a second reading of `meta.console_model` here would be a
# second place for it to go wrong.
from atoo.verify_plan import resolve_console_model

# WING represents -inf as literally -144 on the wire (FR-X.3a, confirmed
# against a real saved show). A fader sitting here is "off" regardless of
# mute state -- the one numeric constant every rule and the signal graph
# share, so a change to this doesn't need hunting through both.
FADER_FLOOR_DB = -144.0

# A send left "on" but pulled to within 44dB of the floor without actually
# being at the floor reads as forgotten, not a deliberate near-silent mix
# choice. The threshold is this project's own: the idea is a send that is
# "on" but essentially dead.
NEAR_SILENT_THRESHOLD_DB = -100.0

# CH002's "low": a DCA's fader is set
# low (<= -20dB) while it controls at least one active member. It was
# the floor (-144dB) until 2026-09-23, which only ever caught a DCA pulled
# all the way off; a DCA sitting 20dB down is already inaudible in the mix
# it controls, and the members underneath it look perfectly normal. Named
# rather than written into the predicate because the number is a judgement
# about audibility, not a fact about the console, and the next person to
# argue with it should find it here.
DCA_LOW_FADER_DB = -20.0

# --------------------------------------------------------------------------
# What "in use" means (the catalogue's "Vocabulary Rules" section)
# --------------------------------------------------------------------------
#
# *"An 'in-use' or 'active' channel, aux or bus is one that is named, input
# patched, or has sends (default output patching of channels to LCL inputs
# or busses to Main 1 don't count, unless also named or input patched, or
# is receiving sends.)"*
#
# Both exclusions are load-bearing, and both were measured off
# `tests/fixtures/console-runs/Initialized-Compact.snap`, a factory-initialized
# WING Compact:
#
#   bank  count  named  input-patched   main/1/on  main/2-4/on  sends on
#   ch       40      0  24 (LCL 1..24)         40            0         0
#   aux       8      0   2 (USB 1, PLAY 1)      8            0         0
#   bus      16      0   0                      8            0         0
#
# Without them every strip on a desk nobody has touched reads as "in use",
# which is what made CH001 and L002 fire dozens of times on an empty
# board.
#
# **The patch exclusion is per model, and it lives in
# `console_facts.FACTORY_INPUT_PATCHES`** -- the module where measured
# hardware facts belong, beside the panel counts. It used to be the
# `LCL n` identity written into this file, which left the two auxes above
# reading as in use on an untouched Compact; the rule was broadened
# (2026-09-23) rather than naming a third default: any factory-default
# patch, whatever the source, so a
# Full or a Rack with different defaults cannot bring the noise back.

# The Main a factory WING routes every strip and half its busses to. A
# deliberate route to Main 1 and a board straight out of the box are
# indistinguishable at this address, so it never counts as activity on its
# own; Main 2-4 are off from the factory, so they do.
DEFAULT_MAIN_INDEX = 1

_DCA_TAG_RE = re.compile(r"^#D(\d+)$")
_MUTE_GROUP_TAG_RE = re.compile(r"^#M(\d+)$")


class RuleScope(str, Enum):
    """Whose business is this rule, when a plan is supplied?

    A structural rule knows nothing about a plan -- it reads the desk and
    reports what it finds. That is right with no plan in hand, and wrong
    the moment there is one: an INFO about an aux strip belonging to no
    DCA, on a strip the show never mentions, is a claim about somebody
    else's mix. From the A5 run: there is no need to
    report on channels that are not in the plan.

    A `str` mixin for the same reason `Severity` is one -- `RuleScope.
    HAZARD == "hazard"` is True, and `json.dumps` needs no encoder.

    - `HAZARD` -- reported about any object on the desk, planned or not.
      48V live on a socket nobody patched does not care whose strip it
      is; neither does a mix that reaches no loudspeaker. **This is the
      default**, because guessing wrong in this direction only makes the
      report longer, and guessing wrong the other way hides something
      real. Note L002: a routed, unmuted, silent strip that is *not*
      part of your show is the classic why-can't-I-hear-it, so "outside
      the plan" is the case that makes it MORE worth saying, not less.
      A hazard can still stand down under the second mechanism below --
      the two are independent, and that is what separates L002's
      nineteen planned-and-stated firings from its twenty-nine others.
    - `CONVENTION` -- "this is not set up the way strips are usually set
      up". Meaningful about a strip the plan claims; noise about one it
      does not. Withheld (and counted) for objects outside the plan.
    - `PAIRWISE` -- the finding is about a *relationship* between two or
      more objects, not about one of them: a duplicate name is a
      collision, not a property. "Both outside the plan" is noise; "one
      of yours and one of theirs" is exactly the collision that bites at
      a desk, so it is reported when ANY participant is in the plan.
      Mechanically that is the same test `CONVENTION` gets -- named
      separately because the reasoning is different and because leaving
      it implicit is how a later edit turns "any" into "all" without
      anyone noticing.
    """

    HAZARD = "hazard"
    CONVENTION = "convention"
    PAIRWISE = "pairwise"

    __str__ = str.__str__


# The two reasons a finding can be withheld, and the words the summary
# line uses for them. Never silent: whatever is withheld is counted and
# said out loud (`ScopedAudit.summary()`), because a shorter list that
# cannot be told apart from a healthy desk is worse than a long one.
WITHHELD_OUTSIDE_PLAN = "about an object the plan never mentions"
WITHHELD_PLAN_STATES = "about a parameter the plan states"

# The summary's own rule id. Not in DEFAULT_RULES -- it is produced by the
# scoping pass rather than by a check over console state -- but it carries
# a rule id for the same reason every other finding does: FR-4.3, a
# finding cites the thing that produced it, and a user filters on a code.
SCOPE_SUMMARY_RULE_ID = "S001"


# --------------------------------------------------------------------------
# Console state: a flat address -> value map, plus typed accessors over the
# confirmed address shapes apply.py already writes (same scheme, so a value
# read here and a value apply.py wrote are always talking about the same
# address).
# --------------------------------------------------------------------------


@dataclass
class ConsoleState:
    """address -> value, exactly as read back from a live console (or
    assembled by hand). No interpretation happens at construction time --
    every rule and the graph builder decide what a given address means.

    `console_model` is the one thing here that is not an address: which
    WING this reading came off, when that is known. It matters because
    some readings mean different things on different models -- the factory
    input patches `is_in_use()` discounts are measured per model
    (`console_facts.FACTORY_INPUT_PATCHES`), and `/ch/20` on `LCL 20` is an
    untouched Compact but a patch somebody made on a Full, whose factory
    LCL run stops at 8. **None is a real
    answer, not a default to be filled in**: a state loaded from a JSON
    file names no console, and every consumer has to behave sanely without
    it. `read_console_state` fills it from the model the desk stated on
    `/?`; `run_audit` fills it from the plan when one is supplied and the
    state is silent.
    """

    values: dict[str, object] = field(default_factory=dict)
    console_model: str | None = None
    # Address families a live read stopped asking for after
    # `UNANSWERED_FAMILY_CUTOFF` of them went unanswered while the desk
    # was still answering -- family pattern -> the addresses never asked.
    # Not values: those addresses are unknown, exactly like one that
    # timed out, and nothing reads a default into their absence.
    unasked_families: dict[str, list[str]] = field(default_factory=dict)
    # When this reading took its names from an earlier one
    # rather than asking for them again, how often a live watch re-reads
    # them -- every this many readings. None (every state but a watch's
    # between refreshes, and every state with `--name-refresh 1`) means
    # the names were read with everything else. Not a value either: it
    # is what `watch.watch` turns into the one INFO, W001, that tells
    # the engineer a rename waits for the next refresh.
    name_refresh: int | None = None
    # The strips whose clip ERROR stands, and what the clip
    # monitor says about itself. Not values either -- they come from the
    # console's meter stream (`atoo.metering`), not from a read. Empty and
    # None for every state but a live watch's, so `audit` and every
    # captured state are untouched, and L003 says nothing about them.
    clips: tuple = ()
    clip_status: object = None

    def get(self, address: str, default=None):
        return self.values.get(address, default)

    def flag(self, address: str) -> bool | None:
        """0/1-shaped parameters (mute, send.on, main.on) -- None if the
        address wasn't read at all, distinct from a confirmed 0."""
        v = self.values.get(address)
        if v is None:
            return None
        return bool(int(v))

    def number(self, address: str) -> float | None:
        v = self.values.get(address)
        if v is None:
            return None
        return float(v)

    def text(self, address: str) -> str | None:
        v = self.values.get(address)
        return None if v is None else str(v)

    def mute(self, base: str) -> bool | None:
        return self.flag(f"{base}/mute")

    def fader_db(self, base: str) -> float | None:
        return self.number(f"{base}/fdr")

    def name(self, base: str) -> str | None:
        return self.text(f"{base}/name")

    def tags(self, base: str) -> str:
        return self.text(f"{base}/tags") or ""

    def patch(self, base: str) -> tuple[str, int] | None:
        grp = self.text(f"{base}/in/conn/grp")
        n = self.number(f"{base}/in/conn/in")
        if not grp or grp == "OFF" or n is None:
            return None
        return grp, int(n)

    def on_alternate_input(self, base: str) -> bool | None:
        """Is this strip listening to its ALTERNATE input patch rather than
        its main one (`in/set/altsrc`)? None if never read."""
        return self.flag(console_facts.ALT_PATCH_SELECTED.replace("/ch/{n}", base))

    def alternate_group(self, base: str) -> str | None:
        """The alternate patch's group (`'CRD'`, `'A'`), or None when it is
        `OFF` or was never read. The socket number is not read at all --
        see `STRIP_FIELDS`."""
        grp = self.text(console_facts.ALT_PATCH_GROUP.replace("/ch/{n}", base))
        if not grp or grp == console_facts.ALT_PATCH_OFF:
            return None
        return grp

    def fx_model(self, slot: int) -> str | None:
        """What is loaded in FX slot `slot` (`'VSS3'`, `'NONE'`), or None
        if it was never read."""
        return self.text(console_facts.FX_MODEL.replace("{n}", str(slot)))

    def inserts(self, base: str) -> list[tuple[str, int | None, bool | None]]:
        """Every insert point on this strip that was read, as
        `(point, slot, on)` -- `slot` is the FX slot number it names, or
        None for `NONE` (`console_facts.INSERT_POINTS`). A
        point whose `ins` was never read is left out rather than reported
        empty."""
        bank = base.split("/")[1]
        found = []
        for point in console_facts.INSERT_POINTS.get(bank, ()):
            ins = self.text(f"{base}/{point}/ins")
            if ins is None:
                continue
            m = re.fullmatch(r"FX(\d+)", ins)
            found.append((point, int(m.group(1)) if m else None,
                          self.flag(f"{base}/{point}/on")))
        return found

    def output_source(self, group: str, socket: int) -> tuple[str, int] | None:
        """What internal object (a BUS/MAIN/MTX index) feeds this physical
        output socket -- None if unpatched (`.grp` is "OFF" or unread)."""
        grp = self.text(f"/io/out/{group}/{socket}/grp")
        n = self.number(f"/io/out/{group}/{socket}/in")
        if not grp or grp == "OFF" or n is None:
            return None
        return grp, int(n)

    def input_phantom(self, group: str, socket: int) -> bool | None:
        return self.flag(f"/io/in/{group}/{socket}/vph")

    def input_muted(self, group: str, socket: int) -> bool | None:
        """Is this input socket's own mute on (`/io/in/{grp}/{n}/mute`)?
        None if it was never read."""
        return self.flag(f"/io/in/{group}/{socket}/mute")

    def input_mode(self, group: str, socket: int) -> str | None:
        """The source's own width (`/io/in/{grp}/{n}/mode`: `M`, `ST` or
        `M/S`), or None if it was never read."""
        return self.text(f"/io/in/{group}/{socket}/mode")


# --------------------------------------------------------------------------
# Discovery: which strips/busses/etc. are present in this state, found by
# scanning the addresses actually there rather than requiring the caller to
# pre-declare a console model. A rule works the same against a full live
# walk of a WING Compact and a four-line offline fixture.
# --------------------------------------------------------------------------


def _indices(state: ConsoleState, pattern: str) -> list[int]:
    rx = re.compile(pattern)
    found = set()
    for addr in state.values:
        m = rx.match(addr)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def strip_bases(state: ConsoleState) -> list[str]:
    """Every `/ch/{n}` and `/aux/{n}` this state has anything recorded
    for -- the two input-strip banks (`wing-console-model.md`), addressed
    identically for every rule in this module."""
    bases = [f"/ch/{n}" for n in _indices(state, r"^/ch/(\d+)/")]
    bases += [f"/aux/{n}" for n in _indices(state, r"^/aux/(\d+)/")]
    return bases


def bus_indices(state: ConsoleState) -> list[int]:
    return _indices(state, r"^/bus/(\d+)/")


def main_indices(state: ConsoleState) -> list[int]:
    return _indices(state, r"^/main/(\d+)/")


def matrix_indices(state: ConsoleState) -> list[int]:
    return _indices(state, r"^/mtx/(\d+)/")


def dca_indices(state: ConsoleState) -> list[int]:
    return _indices(state, r"^/dca/(\d+)/")


def mute_group_indices(state: ConsoleState) -> list[int]:
    return _indices(state, r"^/mgrp/(\d+)/")


def output_sockets(state: ConsoleState) -> list[tuple[str, int]]:
    """Every `/io/out/{group}/{n}` this state read, regardless of whether
    it's actually patched to anything."""
    rx = re.compile(r"^/io/out/([A-Za-z0-9]+)/(\d+)/")
    found = set()
    for addr in state.values:
        m = rx.match(addr)
        if m:
            found.add((m.group(1), int(m.group(2))))
    return sorted(found)


def output_patch_was_read(state: ConsoleState) -> bool:
    """Did this reading ask the desk about its output patch at all?

    An earlier change, and the distinction is the whole point: *"we looked and
    there is no route"* is a finding; *"we never looked"* is a gap in the
    read. R002 and R005 both answer "does this object reach a
    physical output", and both answer it from `/io/out/*` -- so on a state
    with no `/io/out/*` in it at all they were not finding a dead bus,
    they were asserting a negative from addresses nobody requested.
    Both were seen, as a WARNING and an ERROR, on a correctly
    patched full-size WING on 2026-09-24, because the desk states
    `wing-fullsize` and no socket groups were derived for it.

    **Not the same as "every socket was read".** A read that covered LCL
    but not A/B/C can still miss a route, and this deliberately says True
    for it: partial coverage is reported by `render_coverage` rather than
    used to silence a rule, because silencing on *any* gap would hide the
    real fault R002 exists for. The line is drawn where
    `render_coverage` already draws it -- no output sockets at all.
    """
    return bool(output_sockets(state))


def input_sockets(state: ConsoleState) -> list[tuple[str, int]]:
    """Every physical input socket this state read anything about.

    `USR` is excluded: its 56 entries are the console's own user
    signal/patch layer, not jacks (the console model notes).
    They live in the `/io/in` address space and `read_console_state` reads
    them for C001, but they carry no 48V and counting them would have
    `render_coverage` claim the audit read thirty-two sockets that do not
    exist on any panel."""
    rx = re.compile(r"^/io/in/([A-Za-z0-9]+)/(\d+)/")
    found = set()
    for addr in state.values:
        m = rx.match(addr)
        if m and m.group(1) != "USR":
            found.add((m.group(1), int(m.group(2))))
    return sorted(found)


def output_source_object(state: ConsoleState, group: str, socket: int) -> tuple[str, int] | None:
    """Which bus/Main/Matrix -- by its own number -- feeds this physical
    output socket, or None if nothing does.

    `ConsoleState.output_source` returns the raw pair the desk stores, and
    the number in it is a SLOT, not an object index: an earlier change, confirmed
    on a real console and again by the factory snapshot, gives every
    internal object a fixed two-slot pair, `2*index - 1` for its L/mono
    feed and `2*index` for its R. `apply._output_slot` is where that math
    is written down for the write path; this is its inverse, for the read
    path.

    Read `tests/fixtures/console-runs/Initialized-Compact.snap` for why it
    matters: a factory Compact patches local outs 1-6 from `BUS 1, 3, 5,
    7, 9, 11` -- busses **1 to 6**, each on its L slot -- and outs 7-8
    from `MAIN 1, 2`, which is Main 1's L and R, not Mains 1 and 2. Read
    as indices, that desk has a Main 2 patched to a jack with nothing
    feeding it, and R004 says so.

    CV009 deliberately does NOT go through here: it compares what the
    plan declared against what the desk holds, and both sides of that
    comparison are raw slots.
    """
    raw = state.output_source(group, socket)
    if raw is None:
        return None
    kind, slot = raw
    return kind, (slot + 1) // 2


def _output_node(state: ConsoleState, group: str, socket: int) -> str | None:
    """`output_source_object` as a signal-graph node id."""
    src = output_source_object(state, group, socket)
    if src is None:
        return None
    return {"BUS": f"bus:{src[1]}", "MAIN": f"main:{src[1]}", "MTX": f"mtx:{src[1]}"}.get(src[0])


@dataclass(frozen=True)
class _Leg:
    """One hop of the signal graph: a switch that carries `source`'s signal
    on to `target` (node ids, `bus:3`, or a strip's base address for the
    first hop of a path).

    `state` is `open` (switched on, and above the floor where the level is
    read), `floor` (switched on and pulled to the floor) or `off` (switched
    off with a level set, which is what a send somebody built and switched
    off looks like: a send is off at the floor from the factory). A switch
    that is off with no level is not a leg at all."""

    source: str
    target: str
    state: str
    addresses: tuple[str, ...]

    @property
    def on(self) -> bool:
        return self.state != "off"


def _leg(state: ConsoleState, source: str, target: str, switch: str,
         level: str | None = None) -> _Leg | None:
    """The leg `switch` makes between `source` and `target`, or None when
    there is none or it was not read. `level` is the send's level address;
    a route to a Main has none in the read, so it passes None and is a leg
    only when it is on."""
    on = state.flag(switch)
    if on is None:
        return None
    lvl = state.number(level) if level else None
    at_floor = lvl is not None and lvl <= FADER_FLOOR_DB
    addresses = (switch, level) if level else (switch,)
    if on:
        return _Leg(source, target, "floor" if at_floor else "open", addresses)
    if lvl is not None and not at_floor:
        return _Leg(source, target, "off", addresses)
    return None


def _routing_legs(state: ConsoleState) -> list[_Leg]:
    """Where each bus/Main can send its signal next -- bus -> Main, bus ->
    Matrix, Main -> Matrix -- with each leg's state kept, so that a loop
    can be told open from one a switch or a floor is holding closed."""
    legs: list[_Leg] = []
    for idx in bus_indices(state):
        base = f"/bus/{idx}"
        for m in main_route_targets(state, base):
            legs.append(_leg(state, f"bus:{idx}", f"main:{m}", f"{base}/main/{m}/on"))
        for x in matrix_send_targets(state, base):
            legs.append(_leg(state, f"bus:{idx}", f"mtx:{x}", f"{base}/send/MX{x}/on",
                             f"{base}/send/MX{x}/lvl"))
    for idx in _referenced_main_indices(state):
        base = f"/main/{idx}"
        for x in matrix_send_targets(state, base):
            legs.append(_leg(state, f"main:{idx}", f"mtx:{x}", f"{base}/send/MX{x}/on",
                             f"{base}/send/MX{x}/lvl"))
    return [leg for leg in legs if leg is not None]


def _routing_edges(state: ConsoleState) -> dict[str, set[str]]:
    """Where each bus/Main can send its signal next, counting only routing
    that is switched ON -- bus -> Main, bus -> Matrix, Main -> Matrix."""
    edges: dict[str, set[str]] = {}
    for leg in _routing_legs(state):
        if leg.on:
            edges.setdefault(leg.source, set()).add(leg.target)
    return edges


def objects_reaching_a_physical_output(state: ConsoleState) -> set[str]:
    """Every bus/Main/Matrix node id with SOME route to a physical output
    socket -- directly, through a Main, through a Matrix, or any longer
    combination of those (R002, R005, R006).

    Deliberately not `build_signal_graph` + `trace_signal_path`, though
    the shape is nearly the same. Those answer *"is signal flowing right
    now"*: their edges close on a mute or a fader at the floor, so a
    muted bus that is perfectly well patched would come back unreachable
    and R002 would report it as going nowhere. The question here is
    whether the routing EXISTS, which is a different one -- L002 and
    the mute rules own the other.

    A reverse fixpoint rather than a walk per bus: it answers for every
    object at once, and it cannot spin on a cycle (a bus sending to a
    Matrix that feeds a Main that feeds the bus) because a node is only
    ever added, never revisited once in.
    """
    reaching = set()
    for group, socket in output_sockets(state):
        node = _output_node(state, group, socket)
        if node is not None:
            reaching.add(node)
    # A monitor output's source reaches the phones jack (or
    # the monitor speakers) without a socket patched to it.
    reaching |= set(monitor_source_nodes(state))
    edges = _routing_edges(state)
    changed = True
    while changed:
        changed = False
        for source, targets in edges.items():
            if source not in reaching and targets & reaching:
                reaching.add(source)
                changed = True
    return reaching


def matrix_feed_bases(state: ConsoleState) -> list[str]:
    """Every object that can send to a Matrix: the two strip banks, the
    busses and the Mains.

    A Matrix has no inputs of its own -- it is fed by a SEND
    on whatever feeds it, and `plan_schema.py` puts that send on a Bus or
    a Main for every matrix this project's plans build. Rules that asked
    "is this matrix fed" used to walk `strip_bases()` alone, which is the
    one source a plan here never uses, so the answer was always no.
    The case is a house convention such as *"Matrix 1 takes its
    feed from Main"*.
    """
    return (strip_bases(state)
            + [f"/bus/{i}" for i in bus_indices(state)]
            + [f"/main/{i}" for i in main_indices(state)])


def send_targets(state: ConsoleState, base: str) -> list[int]:
    """Bus indices `base` (a strip) has a `/send/{n}/on` address for."""
    rx = re.compile(re.escape(base) + r"/send/(\d+)/on$")
    return sorted(int(m.group(1)) for a in state.values if (m := rx.match(a)))


def matrix_send_targets(state: ConsoleState, base: str) -> list[int]:
    rx = re.compile(re.escape(base) + r"/send/MX(\d+)/on$")
    return sorted(int(m.group(1)) for a in state.values if (m := rx.match(a)))


def main_route_targets(state: ConsoleState, base: str) -> list[int]:
    """Main indices `base` (a strip OR a bus) has a `/main/{n}/on`
    address for -- the same field name serves a channel's direct-to-Main
    route (FR-1.11) and a bus's own destination (FR-1.9), same shape."""
    rx = re.compile(re.escape(base) + r"/main/(\d+)/on$")
    return sorted(int(m.group(1)) for a in state.values if (m := rx.match(a)))


def _is_active_name(name: str | None) -> bool:
    """A name that says something, as opposed to blank or a WING factory
    default (`CH01`, `AUX03`, ...) -- used only to decide "does this look
    like it's in use", never to guess what it's *for*."""
    if not name or not name.strip():
        return False
    return not re.match(r"^(CH|AUX|BUS|MAIN|MTX|DCA)\s*0*\d+$", name.strip(), re.IGNORECASE)


# --------------------------------------------------------------------------
# Where a name a human typed actually lives
# --------------------------------------------------------------------------
#
# Channel 20 was named "Podium" by hand on a Compact on 2026-09-22,
# and the screen showed it. Our own read came back with
# `/ch/20/name` **empty**. The snapshot taken in the same session
# (A13, board with Podium) says
# where the name went:
#
#     /io/in/LCL/20/name = 'Podium'
#     /ch/20:  name='',  clink=True,  conn={'grp': 'LCL', 'in': 20}
#
# `clink` -- "Link Customization to Source", protocol PDF p.48, and ON
# from the factory -- makes a strip *display* the name, colour and icon of
# the socket it is patched to while its own stay blank. So a strip read
# only at `{base}/name` reads as unnamed however plainly a person named
# it. Channel 20 was also sitting on `LCL 20`, a Compact's factory patch,
# so the patch arm discounted it too and `is_in_use` called it free.
#
# It stayed invisible because `apply.py` writes the name to the socket
# AND to the strip, so `/ch/1/name` is `'Kick'` on every desk this project
# has ever built: **the only desks we had audited were ones we set up
# ourselves.** The first time a human named a channel on a board we then
# read, we got it wrong.
#
# This is still FR-4.3-clean. It reads *whether* a strip is named, and
# what the name is for collision purposes; it never infers what a channel
# **is** from the words in it.

# Names a socket carries because the desk shipped it that way, not because
# anybody typed them. Measured off the A13 snapshot above and off
# `Initialized-Compact.snap`: a Compact's `USB 1` and `USB 2` both read
# `'USB 1/2'`, `PLAY 1` and `PLAY 2` both read `'2TR'`, and every `LCL`,
# `A`, `B` and `C` socket reads `''`. Without this, `/aux/1` and `/aux/2`
# -- which every WING ships patched to USB and PLAY -- would read as
# somebody's work on an untouched desk, and `a8-audit-initialized-board.sh`
# would stop reporting zero.
FACTORY_SOURCE_LABELS: dict[str, frozenset[str]] = {
    "USB": frozenset({"USB 1/2"}),
    "PLAY": frozenset({"2TR"}),
}

# The general form of the same thing, and an inference rather than a
# measurement: a label that is the socket's own group and number
# ("LCL 20", "USB 1/2", "AES 3") is the desk describing itself. Stated so
# it can be argued with; a real name that happens to look like one is the
# cost, and "AES 3" as a channel name is not a thing anyone types.
_FACTORY_SOURCE_LABEL_RE = re.compile(
    r"^(LCL|AUX|AES50-?[ABC]|[ABC]|SC|USB|CRD|MOD|PLAY|AES|USR|OSC)\s*\d*(\s*/\s*\d+)?$",
    re.IGNORECASE,
)


def is_factory_source_label(group: str, name: str | None) -> bool:
    """Is this socket name the desk's own label rather than somebody's?

    See `FACTORY_SOURCE_LABELS`. Blank counts, because a blank name is the
    absence of one.
    """
    if not name or not name.strip():
        return True
    text = name.strip()
    if text in FACTORY_SOURCE_LABELS.get(group.upper(), ()):
        return True
    return bool(_FACTORY_SOURCE_LABEL_RE.match(text))


def source_name_address(state: ConsoleState, base: str) -> str | None:
    """`/io/in/{grp}/{socket}/name` for whatever this strip is patched to,
    or None when it is patched to nothing.

    Deliberately **not** conditioned on `clink`: this is the address to go
    and read, and a state that has not read `clink` yet does not know
    whether it needs the answer. `source_is_named` is where the flag is
    consulted.
    """
    patch = state.patch(base)
    if patch is None:
        return None
    return f"/io/in/{patch[0]}/{patch[1]}/name"


def source_name_addresses(state: ConsoleState,
                          bases: list[str] | None = None) -> list[tuple[str, str]]:
    """The **second pass** of a read: the source-socket name of every
    strip the first pass found patched somewhere, with its OSC type.

    It cannot be part of `console_read_plan` (or of
    `amend.occupancy_read_plan`), because which socket to ask about is not
    knowable until the patch has been read. **Up to one extra address per
    patched strip, and nothing at all for an unpatched one** -- 26 on a
    factory Compact, whose 24 LCL-patched channels and two media auxes are
    all it has patched.

    Deduplicated: one socket feeding two strips is a normal request
    (`atoo/domain/knowledge.md`), and asking twice would be a round
    trip spent on an answer already in hand.

    `bases` defaults to every strip this state has anything recorded for.
    `read_console_state` lets it default; `amend.source_name_addresses`
    passes the strips its own scoped read walked, whether or not they
    answered.
    """
    wanted: list[tuple[str, str]] = []
    seen: set[str] = set()
    for base in (strip_bases(state) if bases is None else bases):
        address = source_name_address(state, base)
        if address is None or address in seen:
            continue
        seen.add(address)
        wanted.append((address, "s"))
    return wanted


def custom_link_addresses(state: ConsoleState,
                          bases: list[str] | None = None) -> list[tuple[str, str]]:
    """The third part of a read's **second pass**:
    `{base}/clink` for every strip the first pass found patched
    somewhere.

    `clink` -- "Link Customization to Source", protocol PDF p.48 -- is the
    switch that decides whether the strip displays the socket's name or
    its own. `source_is_named` and `effective_name` both consult it, and
    both already behave correctly for all three of its readings; until
    this existed the audit simply never took one, so it was permanently
    in the "unread, assume ON, but never let the assumption overrule a
    name we did read on the strip" branch. That branch is right for the
    case it was written for and wrong on a desk somebody else named, where
    the strip leaf can be stale and the socket is what the surface shows:

        /ch/4  name='Acoustic'  clink=1  ->  A 11, named 'Acoustic'
        /ch/7  name='Acoustic'  clink=1  ->  A  9, named 'Acoustic 2'

    (the A17 full-size capture of 2026-09-23.) With `clink` unread those are two strips called
    'Acoustic' and N001 reports a collision that is not on the desk.

    **Per PATCHED strip, not per strip.** `source_is_named` answers False
    for an unpatched strip without ever looking at `clink`, so an
    unpatched strip's flag is an address whose answer no rule can use.
    That makes this 26 addresses on a factory Compact rather than 48
    (5,834 -> 5,860, +0.45%), and 42 on the full-size WING above. It was first
    costed at one address per strip *whether patched or not* and
    declined; scoped to the patched ones it is the cheaper half of a
    second pass this read already makes.

    Same reason as `source_name_addresses` for not being in
    `console_read_plan`: whether to ask is not knowable until the patch
    has been read. No deduplication -- unlike a socket name, the flag is
    per strip, and two strips off one socket can differ on it.
    """
    wanted: list[tuple[str, str]] = []
    for base in (strip_bases(state) if bases is None else bases):
        if state.patch(base) is not None:
            wanted.append((f"{base}/clink", "i"))
    return wanted


def expansion_bays_in_use(state: ConsoleState) -> dict[str, list[str]]:
    """Every expansion bay (`CRD`, `MOD`) something on this desk depends
    on, mapped to the addresses that depend on it: a strip's input patch
    (`/ch/40/in/conn/grp`) or a physical output socket's source
    (`/io/out/MOD/1/grp`). The read-side counterpart of
    `apply.plan_expansion_bay_use`, which asks the same of a plan.

    An output socket on a bay counts only when something is patched to
    it -- an unpatched socket on an empty bay is not a fault.
    """
    use: dict[str, list[str]] = {}
    for base in strip_bases(state):
        patch = state.patch(base)
        if patch is not None and patch[0] in console_facts.EXPANSION_BAY_ADDRESSES:
            use.setdefault(patch[0], []).append(f"{base}/in/conn/grp")
    for group, socket in output_sockets(state):
        if (group in console_facts.EXPANSION_BAY_ADDRESSES
                and state.output_source(group, socket) is not None):
            use.setdefault(group, []).append(f"/io/out/{group}/{socket}/grp")
    return use


def expansion_bay_addresses(state: ConsoleState) -> list[tuple[str, str]]:
    """The rest of a read's **second pass**: what is fitted
    in each bay the first pass found something patched from or routed to.

    Same reason as `source_name_addresses` for not being in
    `console_read_plan`: whether to ask is not knowable until the patches
    have been read. At most two addresses, and none at all on a desk that
    uses neither bay -- which is every factory WING, so the count a
    factory Compact reads does not move. `apply.read_fitted_bays` makes
    the same choice for the same reason: a plan that touches no bay pays
    nothing.
    """
    return [(console_facts.EXPANSION_BAY_ADDRESSES[group], "s")
            for group in sorted(expansion_bays_in_use(state))]


def talkback_addresses(state: ConsoleState) -> list[tuple[str, str]]:
    """The rest of a read's **second pass**: where TALK A and
    TALK B are routed, asked only when the first pass found talkback
    assigned to a strip (`/cfg/talk/assign` not `OFF`).

    Fifty-six switches, and none at all on a desk whose talkback is
    unassigned -- which is every factory WING and every capture on disk,
    so a factory Compact's read grows by the one `assign` address and no
    more. Same shape as `expansion_bay_addresses`: whether to ask is not
    knowable until the first pass has answered.
    """
    assign = state.text(console_facts.TALK_ASSIGN)
    if assign is None or assign == console_facts.TALK_OFF:
        return []
    return [(console_facts.talk_destination(button, dest), "i")
            for button in console_facts.TALK_BUTTONS
            for dest in console_facts.TALK_DESTINATIONS]


_DEVICE_ON_PORT = "the desk reports a device on it"


def aes50_ports_in_use(state: ConsoleState) -> dict[str, str]:
    """Every AES50 port (`A`, `B`, `C`) this reading says is in use,
    mapped to how it knows: the desk reports a device on it
    (`/$stat/{port}/stat` anything but `-`), or a strip takes its input
    from it. Either is enough: the status leaf (`OK`, `ERR`
    or `UPD`; `-` is an empty port) is the desk's own word, and a strip patched from AES50-A is a stage box on AES50-A
    whatever the status leaf said (or if it was never read, as in every
    capture)."""
    used: dict[str, str] = {}
    for port in console_facts.AES50_PORTS:
        status = state.text(console_facts.aes50_status_address(port))
        if status in console_facts.AES50_DEVICE_STATES:
            used[port] = _DEVICE_ON_PORT
    for base in strip_bases(state):
        patch = state.patch(base)
        if patch is not None and patch[0] in console_facts.AES50_PORTS:
            used.setdefault(patch[0], "a strip takes its input from it")
    return used


def _output_group_was_read(state: ConsoleState, group: str) -> bool:
    prefix = f"/io/out/{group}/"
    return any(address.startswith(prefix) for address in state.values)


def aes50_output_addresses(state: ConsoleState) -> list[tuple[str, str]]:
    """The rest of a read's **second pass**: the output patch
    of every AES50 port in use (`aes50_ports_in_use`) whose outputs the
    first pass did not read.

    A WING stores an output patch on the socket, so the only way to see a
    bus patched to a stage box's output is to read that port's outputs.
    Not in `console_read_plan` for the same reason as the socket names:
    whether to ask is not knowable until the first pass has answered.
    Every socket the port's address space has (48), because the device on
    it does not say how many outputs it has; none at all on a desk with
    nothing on AES50, so a factory Compact's read does not move. Only
    when output sockets were read at all: a read that asked for no output
    patch is not made to ask for one here.
    """
    if not output_sockets(state):
        return []
    wanted: list[tuple[str, str]] = []
    for port in sorted(aes50_ports_in_use(state)):
        if _output_group_was_read(state, port):
            continue
        for n in range(1, console_facts.OUTPUT_SOCKETS[port] + 1):
            wanted.append((f"/io/out/{port}/{n}/grp", "s"))
            wanted.append((f"/io/out/{port}/{n}/in", "i"))
    return wanted


def unread_output_groups_in_use(state: ConsoleState) -> dict[str, str]:
    """AES50 ports the DESK reports a device on whose outputs this reading
    does not hold: the groups a route could go to that nobody looked at. Empty after any live read, which reads them
    in its second pass.

    The desk's own status only, not a strip patched from the port, which
    the read follows anyway. A capture from before that read holds no status,
    and holds inputs from stage boxes whose outputs nobody read; standing
    R002 down on all of those would hide the real fault it exists for
    on every old capture (a partial read is declared,
    not used to silence a rule). So those keep the verdict they had."""
    used = aes50_ports_in_use(state)
    return {port: why for port, why in used.items()
            if why == _DEVICE_ON_PORT and not _output_group_was_read(state, port)}


def monitor_source_nodes(state: ConsoleState) -> dict[str, str]:
    """Signal-graph node -> the monitor-source address that selects it:
    the bus, Main or Matrix each of the desk's two monitor outputs (the
    phones and the monitor speakers) listens to. A source
    chosen there reaches a physical output -- the phones jack -- with no
    socket patched to it, which is how a phones Matrix is meant to be."""
    nodes: dict[str, str] = {}
    for address in console_facts.MONITOR_SOURCES:
        text = state.text(address)
        m = console_facts.MONITOR_SOURCE_RE.match(text or "")
        if m is None:
            continue
        kind = {"MAIN": "main", "MTX": "mtx", "BUS": "bus"}.get(m.group(1))
        if kind is not None:
            nodes.setdefault(f"{kind}:{int(m.group(2))}", address)
    return nodes


def source_is_named(state: ConsoleState, base: str) -> bool | None:
    """Does the SOURCE this strip displays carry somebody's name?

    `True` yes, `False` no, and **`None` when the answer could not be
    established** -- a patched, linked strip whose socket name was never
    read. None is the reading that makes "Podium" safe: the strip's own
    name is blank and its patch is the factory's, so every other signal
    says free, and only this one can say otherwise. Not knowing it is
    therefore not knowing whether the strip is free, which is what
    `amend.strip_occupancy` turns into UNKNOWN. `is_in_use` returns a
    bool and cannot say "unknown", so there None is simply not evidence
    of use -- the caller that must not guess is the caller that has to
    check for None.

    `clink` unread is treated as ON, because ON is the factory setting and
    because the conservative direction here is to go and look at the
    socket rather than to skip the check. A full read
    takes the reading rather than leaning on that assumption -- but the
    assumption stays, because a state assembled by hand, a capture taken
    before that, and `amend`'s own scoped plans all still reach here
    without it.
    """
    address = source_name_address(state, base)
    if address is None:
        return False  # nothing patched: no source to be named
    if state.flag(f"{base}/clink") is False:
        # Unlinked on purpose -- `apply.py` does this for a socket shared
        # between strips. The strip's own name is the one that shows, and
        # the strip's own name has already been consulted.
        return False
    if address not in state.values:
        return None
    patch = state.patch(base)
    return not is_factory_source_label(patch[0], state.text(address))


def effective_name(state: ConsoleState, base: str) -> str | None:
    """The name a person standing at the desk sees on this strip -- the
    socket's when the strip is linked to it, its own otherwise.

    This is the name for **collision** purposes (N001) and the one a
    finding quotes (`strip_label`), and it is a judgement where the two
    readings disagree. The rule:

    - A strip's own active name wins when `clink` was **never read**. The
      flag is assumed ON for "is anything here at all", because assuming
      ON sends us to look at one more address; letting that same
      assumption *overrule a name we actually read on the strip* is a
      different thing entirely. `apply.py` switches `clink` off for a
      socket shared between two strips and names each strip separately,
      so without this a shared input would report two strips colliding on
      the socket's one name.
    - Where `clink` was read and is ON, the socket's name wins, because
      that is what the desk is displaying.
    - Where `clink` was read and is OFF, the strip is genuinely using its
      own name and that is what wins (`source_is_named` returns False and
      this returns before the branches above).
    - A socket carrying the desk's own label (`'USB 1/2'`) is not a name
      and never wins.

    **The rule is unchanged; what changed in an earlier change is that
    the audit now takes a reading.** `read_console_state` reads `clink`
    for every patched strip in its second pass
    (`custom_link_addresses`), so an audit lands in the second or third
    branch like a scoped occupancy read does, instead of being
    permanently stuck in the first. That first branch is right for the
    case it was written for -- an assumption must not overrule a real
    reading -- and wrong on a desk somebody else named, where the strip
    leaf is stale and the socket carries the truth. It is the Podium
    inverted: there the strip was blank and the socket held the name;
    here the strip is populated but out of date and the socket still
    holds it.
    """
    own = state.name(base)
    if not source_is_named(state, base):
        return own
    if state.flag(f"{base}/clink") is None and _is_active_name(own):
        return own
    return state.text(source_name_address(state, base))


def name_address(state: ConsoleState, base: str) -> str:
    """Which address `effective_name` took its answer from -- so a finding
    can point the engineer at the thing it actually read."""
    name = effective_name(state, base)
    source = source_name_address(state, base)
    if source is not None and name is not None and name == state.text(source) \
            and name != state.name(base):
        return source
    return f"{base}/name"


def _is_default_input_patch(base: str, patch: tuple[str, int] | None,
                            console_model: str | None = None) -> bool:
    """Is this the patch the desk already had before anybody touched it?

    The answer is a fact about the model, so it comes from
    `console_facts.factory_input_patch()` rather than from a constant
    here: a Compact ships channels 1-24 from their own LCL socket, `/aux/1`
    from USB 1 and `/aux/2` from PLAY 1, and a Full or a Rack will ship
    something else. `console_model` is whatever the state knows -- the
    model the desk stated on `/?`, or the one the plan names; None means
    nobody said, and `console_facts` falls back to the channel-n-from-
    LCL-n identity alone, which is the reading that hides nothing.

    Judgement call, stated so it can be argued with: "the default patch"
    is read *narrowly*, as that exact pair. Any other patch counts as a
    patch, including `/ch/3` on LCL 7 and `/ch/3` on AES50-A 3. A real
    show that genuinely puts channel 3 on LCL 3 will also have named it,
    and the "or named" arm catches that.
    """
    m = re.match(r"^/(ch|aux|bus)/(\d+)$", base)
    if m is None:
        return False
    return console_facts.is_factory_input_patch(
        console_model, m.group(1), int(m.group(2)), patch)


def _has_sends(state: ConsoleState, base: str) -> bool:
    """Does this object send anywhere it was not sending from the factory?

    Every send and route the object carries -- bus sends, Matrix sends and
    direct Main routes -- except a route to Main 1, which a factory WING
    switches on for every strip and for half the busses."""
    if any(state.flag(f"{base}/send/{b}/on") for b in send_targets(state, base)):
        return True
    if any(state.flag(f"{base}/send/MX{m}/on") for m in matrix_send_targets(state, base)):
        return True
    return any(
        state.flag(f"{base}/main/{m}/on")
        for m in main_route_targets(state, base)
        if m != DEFAULT_MAIN_INDEX
    )


def _receives_sends(state: ConsoleState, idx: int) -> bool:
    """Is anything sending into bus `idx`? The one arm of the in-use test
    that makes sense for a bus and not for a strip."""
    sources = strip_bases(state) + [f"/bus/{i}" for i in bus_indices(state) if i != idx]
    return any(state.flag(f"{b}/send/{idx}/on") for b in sources)


def is_in_use(state: ConsoleState, base: str) -> bool:
    """The catalogue's "in-use"/"active": named, input patched, or sending
    -- and, for a bus, receiving sends.

    Serves `/ch/{n}`, `/aux/{n}` and `/bus/{n}` alike, which is what the
    vocabulary rule asks for; it used to be strips only. Never a guess at
    what kind of source a strip carries (FR-4.3) -- only whether it is
    named, not what the name says.

    **"Named" means named where the desk puts a name**.
    A WING strip is linked to its source socket by default, so a name a
    human types lands on `/io/in/{grp}/{n}/name` and `{base}/name` stays
    empty -- see `source_is_named`, which is the arm that reads it and the
    one thing standing between this function and calling somebody's live
    "Podium" channel free. `amend.py` carried that arm privately; this is now the single
    definition and `amend.strip_occupancy` calls it here.

    An unread socket name is **not** evidence of an unnamed strip. This
    function has only a bool to say it with, so a caller for whom the
    difference matters -- an amendment about to write to the strip --
    asks `source_is_named` for the None (`amend.StripStatus`, UNKNOWN,
    never free).

    Which patches are the factory's own depends on the console model, so
    the answer can differ between two identical readings taken off
    different desks -- `state.console_model` is what decides, and a state
    that does not know says so rather than guessing (see
    `_is_default_input_patch`).
    """
    if _is_active_name(state.name(base)):
        return True
    if source_is_named(state, base):
        return True
    patch = state.patch(base)
    if patch is not None and not _is_default_input_patch(base, patch, state.console_model):
        return True
    if _has_sends(state, base):
        return True
    m = re.match(r"^/bus/(\d+)$", base)
    return m is not None and _receives_sends(state, int(m.group(1)))


def _dca_members(state: ConsoleState) -> dict[int, list[str]]:
    members: dict[int, list[str]] = {}
    for base in strip_bases(state):
        for token in state.tags(base).split(","):
            m = _DCA_TAG_RE.match(token.strip())
            if m:
                members.setdefault(int(m.group(1)), []).append(base)
    return members


def _mute_group_members(state: ConsoleState) -> dict[int, list[str]]:
    members: dict[int, list[str]] = {}
    for base in strip_bases(state):
        for token in state.tags(base).split(","):
            m = _MUTE_GROUP_TAG_RE.match(token.strip())
            if m:
                members.setdefault(int(m.group(1)), []).append(base)
    return members


# The word the desk prints for each bank, so a finding names a strip the
# way an engineer says it -- `CH 3`, not `/ch/3`. The same words Watch's
# position targets use (`watch_conditions.CANONICAL_KIND_WORD`, which
# imports this module and so cannot be imported here); a mute group,
# which no watch target names, is `MGRP`.
BANK_WORD = {"ch": "CH", "aux": "AUX", "bus": "BUS", "main": "MAIN", "mtx": "MTX",
             "dca": "DCA", "mgrp": "MGRP"}


def position_label(base: str) -> str:
    """`/ch/3` -> `CH 3`, `/mgrp/1` -> `MGRP 1`: the strip's position, as
    the desk labels it. Anything that is not `/<bank>/<n>` comes back as
    given."""
    parts = base.split("/")
    if len(parts) != 3 or parts[0] or parts[1] not in BANK_WORD:
        return base
    return f"{BANK_WORD[parts[1]]} {parts[2]}"


def strip_label(state: ConsoleState, base: str) -> str:
    """`CH 20 "Podium"` -- the position, and the name the desk is showing
    for it, which on a linked strip is the SOCKET's (`effective_name`).
    A finding that says `CH 20` and nothing else, about a strip the
    engineer can see is called Podium, reads as a finding about some other
    desk. The same shape Watch's own findings use
    (`watch_conditions._position_label`), so one strip reads the same in
    both. This was the OSC address, `/ch/20 (Podium)`, which
    is not how anyone at a desk names a strip."""
    name = effective_name(state, base)
    position = position_label(base)
    return f'{position} "{name}"' if name else position


def _referenced_main_indices(state: ConsoleState) -> list[int]:
    """Every Main index this state mentions -- via the Main object's own
    addresses (`/main/{n}/...`, always present on a live console
    regardless of use), a strip/bus route into it, or an output socket
    patched from it. A Main fed only by a route, with none of its own
    addresses ever read (a partial/offline state), still needs to be
    checked -- that's exactly what R004/R005 exist to catch."""
    found = set(main_indices(state))
    for base in strip_bases(state) + [f"/bus/{i}" for i in bus_indices(state)]:
        found.update(main_route_targets(state, base))
    for g, n in output_sockets(state):
        src = output_source_object(state, g, n)
        if src is not None and src[0] == "MAIN":
            found.add(src[1])
    return sorted(found)


def _referenced_matrix_indices(state: ConsoleState) -> list[int]:
    """Same idea as `_referenced_main_indices`, for Matrix objects."""
    found = set(matrix_indices(state))
    for base in matrix_feed_bases(state):
        found.update(matrix_send_targets(state, base))
    for g, n in output_sockets(state):
        src = output_source_object(state, g, n)
        if src is not None and src[0] == "MTX":
            found.add(src[1])
    return sorted(found)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


# Both come from atoo.diagnostics now: an audit finding
# and a build-time diagnostic are the same kind of object -- severity, a
# stable code, the thing it concerns, a message -- and the Setup UI
# has to show both streams in one view. `Finding` stays as the
# name this module and its three consumers (`watch.py`,
# `watch_conditions.py`, `webui.py`) were written against; it is the
# canonical type, not a parallel one. Constructions go through
# `Diagnostic.audit()`, which keeps this module's (rule_id, severity,
# category, title, detail, addresses) argument order.
Finding = Diagnostic

SEVERITY_ORDER = diagnostics.SEVERITY_ORDER


@dataclass
class AuditRule:
    """id, severity and category are fixed per rule -- FR-4.3's "findings
    shall cite the specific rule that was violated" means a Finding always
    carries the id of the rule that produced it, never a category
    reconstructed after the fact.

    `scope` is the same kind of per-rule constant: whether
    this rule has anything to say about an object the plan never mentions.
    It is consulted only when a plan is supplied; with no plan everything
    is in scope, because there is nothing to be outside of.

    `judges` names the parameter this rule's verdict rests on, as address
    suffixes relative to the object the finding is about -- `"fdr"`,
    `"tags#D"`. It exists for the second, independent half: **a
    structural rule stands down where the plan STATES the parameter it is
    complaining about**, because a conventions-diff rule (CV*) already
    checks that parameter against what was asked for, and the plan is the
    better authority whenever it speaks. Left empty -- which is the usual
    case -- the judged parameter is read off the finding's own
    `addresses`, which is exact even when the address carries an index the
    rule cannot know in advance (`/ch/1/send/3/lvl`). Set it only where
    the address a finding cites is coarser than the parameter it actually
    judged: CH001 cites the strip but judges its DCA tags.
    """

    id: str
    severity: Severity
    category: str
    title: str
    description: str
    check: Callable[[ConsoleState], list[Finding]]
    scope: RuleScope = RuleScope.HAZARD
    judges: tuple[str, ...] = ()


def run_audit(
    state: ConsoleState,
    rules: list[AuditRule] | None = None,
    *,
    plan: dict | None = None,
) -> list[Finding]:
    """Every rule in `rules` (default `DEFAULT_RULES`) against `state`.

    With `plan`, the result is scoped to what the plan is actually about
    and carries one extra INFO finding,
    `SCOPE_SUMMARY_RULE_ID`, counting what was withheld and why -- so a
    shorter report can always be told apart from a healthy desk. Without
    one, nothing is withheld and no summary appears.

    A caller that wants the withheld findings themselves rather than a
    count -- the Setup UI, or the dirty-board diff -- should call
    `apply_plan_scope()` and read `ScopedAudit.withheld`.

    A plan is also the second place the console model can come from
    (`meta.console_model`, `verify_plan.resolve_console_model`), and the
    rules need it to tell a factory patch from a patch somebody made. The
    state wins where it has one -- it was read off the desk itself, which
    beats what a file claims -- and the plan fills the gap for the offline
    case, `atoo audit --state <file> --plan <file>`.
    """
    plan_model = resolve_console_model(plan) if plan else None
    if state.console_model is None and plan_model:
        state = replace(state, console_model=plan_model)
    rule_list = list(rules) if rules is not None else DEFAULT_RULES
    findings: list[Finding] = []
    for rule in rule_list:
        findings.extend(rule.check(state))
    if plan is not None:
        scoped = apply_plan_scope(state, findings, plan, rule_list)
        findings = list(scoped.findings)
        summary = scoped.summary()
        if summary is not None:
            findings.append(summary)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    return findings


# --------------------------------------------------------------------------
# Rules -- routing (6)
# --------------------------------------------------------------------------


def _rule_bus_no_inputs(state: ConsoleState) -> list[Finding]:
    findings = []
    for idx in bus_indices(state):
        base = f"/bus/{idx}"
        if not is_in_use(state, base):
            continue
        fed = any(state.flag(f"{b}/send/{idx}/on") for b in strip_bases(state))
        if not fed:
            findings.append(Diagnostic.audit(
                "R001", Severity.WARNING, "routing", "Bus No Inputs",
                f"{strip_label(state, base)} is in use but no strip has an active send to it.",
                (f"{base}/name",),
            ))
    return findings


def _rule_bus_no_output(state: ConsoleState) -> list[Finding]:
    findings = []
    # One hop was not enough. The catalogue asks for *"no route to a
    # physical output (either directly, through a Main bus or through a
    # Matrix bus or any other indirect combination)"* -- the same class of
    # blindness fixed in R005 and in R003, and the same
    # rig trips all three: a monitor bus into Main, Main into Matrix 1,
    # Matrix 1 out to the XLRs.
    # Every answer this rule can give rests on `/io/out/*`,
    # so a state that holds none of it cannot be asked the question. Not
    # a quiet pass -- `render_coverage`/`coverage_caveat` name this rule
    # as unchecked, and `audit` and `watch` both print that.
    # Nor can a read that left an AES50 port in use unread --
    # the route may well be there. R007 says so instead, at INFO.
    if not output_patch_was_read(state) or unread_output_groups_in_use(state):
        return findings
    for base in _busses_reaching_nothing(state):
        findings.append(Diagnostic.audit(
            "R002", Severity.WARNING, "routing", "Bus No Output",
            f"{strip_label(state, base)} is in use but has no route to a physical output -- "
            f"not directly, not through a Main, and not through a Matrix.",
            (f"{base}/name",),
        ))
    return findings


def _busses_reaching_nothing(state: ConsoleState) -> list[str]:
    """R002's subjects: every in-use bus with no route out among the
    sockets read."""
    reaching = objects_reaching_a_physical_output(state)
    return [f"/bus/{idx}" for idx in bus_indices(state)
            if is_in_use(state, f"/bus/{idx}") and f"bus:{idx}" not in reaching]


def _mains_reaching_nothing(state: ConsoleState) -> list[str]:
    """R005's subjects: every fed Main with no route out."""
    reaching = objects_reaching_a_physical_output(state)
    out = []
    for idx in _referenced_main_indices(state):
        if _main_is_fed(state, idx) and f"main:{idx}" not in reaching:
            out.append(f"/main/{idx}")
    return out


def _matrices_reaching_nothing(state: ConsoleState) -> list[str]:
    """R006's subjects: every fed Matrix patched to no socket read and
    not a monitor source."""
    reaching = objects_reaching_a_physical_output(state)
    return [f"/mtx/{idx}" for idx in _referenced_matrix_indices(state)
            if _matrix_is_fed(state, idx) and f"mtx:{idx}" not in reaching]


def _rule_route_unchecked(state: ConsoleState) -> list[Finding]:
    """R007: what R002, R005 and R006 would have
    called unrouted, on a reading that left an AES50 port in use unread.

    *"Reaches no physical output"* is a claim about every output, and a
    reading that holds none of AES50-A's, with a stage box on AES50-A,
    cannot make it: a rig's six monitor busses were patched there. The
    three rules stand down and this says, once per object, that the route
    could not be checked and where it might be. INFO, because nothing is
    known to be wrong. Every live read since then reads those ports in its
    second pass, so this fires on a capture or a hand-built state, not on
    a desk read today.
    """
    unread = unread_output_groups_in_use(state)
    if not unread or not output_patch_was_read(state):
        return []
    read = summarise_sockets(output_sockets(state))
    where = "; ".join(f"AES50-{port} ({why})"
                      for port, why in sorted(unread.items()))
    subjects = ([(b, strip_label(state, b), f"{b}/name") for b in _busses_reaching_nothing(state)]
                + [(b, position_label(b), b) for b in _mains_reaching_nothing(state)]
                + [(b, position_label(b), b) for b in _matrices_reaching_nothing(state)])
    findings = []
    for _base, label, address in subjects:
        findings.append(Diagnostic.audit(
            "R007", Severity.INFO, "routing", "Output Route Not Checked",
            f"{label} reaches none of the output sockets read ({read}), but the outputs of "
            f"{where} were not read, so whether it reaches an output there could not be "
            f"checked.",
            (address,),
        ))
    return findings


def monitored_strips(state: ConsoleState) -> set[str]:
    """The aux strips a monitor output listens to (`/cfg/mon/{1,2}/src` is
    `AUX.n`): heard on the phones or the monitor speakers with no send or
    route of their own."""
    found = set()
    for address in console_facts.MONITOR_SOURCES:
        m = console_facts.MONITOR_SOURCE_RE.match(state.text(address) or "")
        if m is not None and m.group(1) == "AUX":
            found.add(f"/aux/{int(m.group(2))}")
    return found


_STRIP_ROUTE_RE = re.compile(r"^(/(?:ch|aux)/\d+)/(?:send/(MX)?(\d+)|main/(\d+))/on$")


def strip_route_addresses(state: ConsoleState) -> dict[str, list[str] | None]:
    """Every strip's switches that send its signal on -- a send to each
    bus, a send to each Matrix and a route to each Main -- as `{strip:
    addresses}`; a strip any of whose switches was never read maps to
    None.

    The switches expected are what the desk has (every bus, Matrix and
    Main this state knows) joined with whatever the strip itself carries.
    All three kinds have to be present: a state with no Main in it has not
    been asked where the strip goes, and "nothing is switched on" would be
    a claim about switches nobody looked at. One pass over the state, not
    one per strip."""
    carried: dict[str, tuple[set[int], set[int], set[int]]] = {
        base: (set(), set(), set()) for base in strip_bases(state)}
    for address in state.values:
        m = _STRIP_ROUTE_RE.match(address)
        if m is None or m.group(1) not in carried:
            continue
        buses, matrices, mains = carried[m.group(1)]
        if m.group(4) is not None:
            mains.add(int(m.group(4)))
        elif m.group(2):
            matrices.add(int(m.group(3)))
        else:
            buses.add(int(m.group(3)))
    desk_buses = set(bus_indices(state))
    desk_matrices = set(matrix_indices(state))
    desk_mains = set(main_indices(state))
    routes: dict[str, list[str] | None] = {}
    for base, (buses, matrices, mains) in carried.items():
        buses, matrices, mains = buses | desk_buses, matrices | desk_matrices, mains | desk_mains
        if not (buses and matrices and mains):
            routes[base] = None
            continue
        addresses = ([f"{base}/send/{i}/on" for i in sorted(buses)]
                     + [f"{base}/send/MX{i}/on" for i in sorted(matrices)]
                     + [f"{base}/main/{i}/on" for i in sorted(mains)])
        routes[base] = None if any(a not in state.values for a in addresses) else addresses
    return routes


def _rule_strip_reaches_nothing(state: ConsoleState,
                                planned_routed: frozenset = frozenset()) -> list[Finding]:
    """R008: a channel or aux that is in use, unmuted and above the floor,
    with no bus send, Matrix send or Main route switched on.

    This is where a path starts. R002, R005 and R006 name the bus, Main or
    Matrix whose signal reaches no output, and count the strip's send as
    what feeds it, so a strip that feeds only such an object is theirs and
    is not repeated here. This reports the strip with nothing on at all.

    Not reported, because another rule or a decision owns it: a muted strip
    (silent on purpose), a strip at the floor (L002), the talk mic (T002),
    an aux a monitor output listens to, and a strip in `planned_routed`
    (the plan routes it, so CV016 judges it). A strip any of whose switches
    was never read is left alone.

    A USER SIGNAL can take a strip out of the desk with no send or route;
    those slots are not read, which is why the finding says what it
    checked -- no bus, Matrix or Main -- and not that no output is reached.
    """
    findings = []
    talk = talkback_strip(state)
    heard = monitored_strips(state)
    for base, addresses in strip_route_addresses(state).items():
        if addresses is None or base == talk or base in planned_routed or base in heard:
            continue
        if state.mute(base) or any(state.flag(a) for a in addresses):
            continue
        fdr = state.fader_db(base)
        if fdr is not None and fdr <= FADER_FLOOR_DB:
            continue
        if not is_in_use(state, base):
            continue
        findings.append(Diagnostic.audit(
            "R008", Severity.WARNING, "routing", "Strip Reaches Nothing",
            f"{strip_label(state, base)} is in use, unmuted and above the floor, but it has no "
            f"bus send, no Matrix send and no Main route switched on, so its signal goes "
            f"nowhere. Switch a send or a Main route on, or mute the strip if it is not wanted.",
            tuple(addresses),
        ))
    return findings


def _rule_matrix_orphan(state: ConsoleState) -> list[Finding]:
    findings = []
    outputs = output_sockets(state)
    for idx in _referenced_matrix_indices(state):
        base = f"/mtx/{idx}"
        patched_out = any(output_source_object(state, g, n) == ("MTX", idx) for g, n in outputs)
        if not patched_out:
            continue
        # A Matrix fed from a Main or a Bus is not an orphan -- and that
        # is how a matrix is normally fed, not an edge case.
        # This walked `strip_bases()` only, which no plan this project
        # builds ever uses as a matrix source, so the rule was one hop
        # short in exactly the way R005 below was.
        if not _matrix_is_fed(state, idx):
            findings.append(Diagnostic.audit(
                "R003", Severity.WARNING, "routing", "Matrix Orphan",
                f"{position_label(base)} is patched to a physical output but nothing sends "
                f"to it -- no channel, no bus and no Main.",
                (f"{base}",),
            ))
    return findings


def _matrix_is_fed(state: ConsoleState, idx: int) -> bool:
    """Does anything have a send switched ON into Matrix `idx` -- a strip,
    a bus or a Main? R003 and R006 ask it from opposite
    ends, so they share one answer."""
    return any(idx in matrix_send_targets(state, b) and state.flag(f"{b}/send/MX{idx}/on")
               for b in matrix_feed_bases(state))


def _rule_matrix_unpatched(state: ConsoleState) -> list[Finding]:
    """R003's mirror image -- a Matrix that IS fed and has
    lost its output.

    The live-desk half. `verify` refuses a plan that patches two
    objects to one output, but a desk never records that two things
    wanted a socket: each `/io/out/{group}/{n}` holds one source, so by
    the time `audit` reads it only the winner is there. A bus that lost
    is R002 and a Main that lost is R005; a Matrix that lost was
    nothing at all.

    A WARNING, not R005's ERROR, by the catalogue's own test -- *can
    the show go on?* A Matrix has no outputs of its own to reach through,
    so the only case where this stops the show is a Matrix carrying the
    PA, and then the Main or bus feeding it reaches nothing either and
    R005/R002 already say so. What is left is the recording or
    broadcast feed: silence on the thing nobody listens to during the
    show, which is worth knowing at soundcheck and stops nothing.
    """
    findings = []
    # An earlier change, as in R002 and R005: "reaches no physical output"
    # is a claim about the output patch, and a read that never asked for
    # it has no standing to make it.
    if not output_patch_was_read(state) or unread_output_groups_in_use(state):
        return findings
    # The finding names the output sockets it looked at, because a partial
    # read still fires (as R002 does) and a Matrix is exactly the object
    # that goes out on a card: on the A17/A18 full-size desk Matrix 6 is
    # patched to MOD 36-37, the audit read only LCL and AUX outputs, and a
    # bare "patched to no physical output" would have been untrue.
    #
    # A Matrix chosen as a monitor output's source (the phones)
    # is meant to have no socket, and `objects_reaching_a_physical_output`
    # counts it as reaching one.
    read = summarise_sockets(output_sockets(state))
    for base in _matrices_reaching_nothing(state):
        findings.append(Diagnostic.audit(
            "R006", Severity.WARNING, "routing", "Matrix Fed But Not Patched",
            f"{position_label(base)} has an active send feeding it but is patched to none of the "
            f"output sockets read ({read}), and no monitor output listens to it.",
            (f"{base}",),
        ))
    return findings


def _rule_main_unfed(state: ConsoleState) -> list[Finding]:
    findings = []
    outputs = output_sockets(state)
    for idx in _referenced_main_indices(state):
        base = f"/main/{idx}"
        patched_out = any(output_source_object(state, g, n) == ("MAIN", idx) for g, n in outputs)
        if not patched_out:
            continue
        fed = any(
            idx in main_route_targets(state, b) and state.flag(f"{b}/main/{idx}/on")
            for b in strip_bases(state) + [f"/bus/{i}" for i in bus_indices(state)]
        )
        if not fed:
            findings.append(Diagnostic.audit(
                "R004", Severity.WARNING, "routing", "Main Patched But Unfed",
                f"{position_label(base)} is patched to a physical output but nothing sends to it.",
                (f"{base}",),
            ))
    return findings


def _rule_main_unpatched(state: ConsoleState) -> list[Finding]:
    findings = []
    # An earlier change, exactly as in R002 above: "it reaches no physical
    # output" is a claim about the output patch, and a read that never
    # asked for the output patch has no standing to make it.
    if not output_patch_was_read(state) or unread_output_groups_in_use(state):
        return findings
    for base in _mains_reaching_nothing(state):
        # A Main can reach the PA through a Matrix instead of going
        # straight out, and that is standard practice rather than an edge
        # case: it is how you EQ for the room without touching the mix you
        # are recording. A typical house convention says exactly that --
        # *"Main should be the full mix, EQed so it sounds good for a
        # recording. Send to Matrix 1. Matrix 1 takes its feed from Main
        # and gets EQed to correct for the room. Patch output to internal
        # XLRs 7 and 8."*
        #
        # This rule only looked one hop and reported a correct show as an
        # ERROR (2026-09-22, A5). It would have fired on every desk fed
        # through a matrix, which is most of them. Both hops now come from
        # `objects_reaching_a_physical_output`, which R002 shares, so
        # the two cannot disagree about what "reaches an output" means.
        findings.append(Diagnostic.audit(
            "R005", Severity.ERROR, "routing", "Main Not Patched",
            f"{position_label(base)} has active sends feeding it, but it reaches no physical output -- "
            f"not directly, and not through a Matrix that is patched either.",
            (f"{base}",),
        ))
    return findings


# A strip's input can be an internal signal: `in/conn/grp` reads `BUS`,
# `MAIN` or `MTX`, and `in/conn/in` the socket. Each object has two sockets,
# as it has two output slots (`output_source_object`): `2N-1` is object N's
# left side and `2N` its right.
_INTERNAL_INPUT_KINDS = {"BUS": "bus", "MAIN": "main", "MTX": "mtx"}


def internal_input_source(state: ConsoleState, base: str) -> tuple[str, str, int] | None:
    """`(node id, group, socket)` for a channel or aux whose live main input
    is a bus, Main or Matrix (`bus:3`, `main:1`, `mtx:2`), or None.

    A strip on its alternate input, or one that may be following the engaged
    global alternate switch, is not judged: the alternate's socket is not
    read."""
    patch = state.patch(base)
    if patch is None or patch[0] not in _INTERNAL_INPUT_KINDS or state.on_alternate_input(base):
        return None
    if state.flag(console_facts.GLOBAL_ALT_SWITCH) and state.alternate_group(base) is not None:
        return None
    group, socket = patch
    return f"{_INTERNAL_INPUT_KINDS[group]}:{(socket + 1) // 2}", group, socket


def _strip_legs(state: ConsoleState, base: str) -> list[_Leg]:
    """Each bus send, Matrix send and Main route of a strip, as legs."""
    legs = [_leg(state, base, f"bus:{b}", f"{base}/send/{b}/on", f"{base}/send/{b}/lvl")
            for b in send_targets(state, base)]
    legs += [_leg(state, base, f"mtx:{x}", f"{base}/send/MX{x}/on", f"{base}/send/MX{x}/lvl")
             for x in matrix_send_targets(state, base)]
    legs += [_leg(state, base, f"main:{m}", f"{base}/main/{m}/on")
             for m in main_route_targets(state, base)]
    return [leg for leg in legs if leg is not None]


@dataclass(frozen=True)
class FeedbackLoop:
    """A cycle in the signal graph: `hops` runs from the strip that takes an
    internal signal, through everything that carries it on, back to that
    signal. A hop is `("takes", strip, node, group, socket)` or a `_Leg`."""

    strip: str
    hops: tuple

    @property
    def legs(self) -> list[_Leg]:
        return [hop for hop in self.hops if isinstance(hop, _Leg)]

    @property
    def open(self) -> bool:
        return all(leg.state == "open" for leg in self.legs)


def feedback_loops(state: ConsoleState) -> list[FeedbackLoop]:
    """Every feedback loop on the desk, each once.

    A loop is a strip patched from a bus, Main or Matrix whose signal comes
    back to that object: through its own send or route, or through other
    busses, Mains, Matrices and strips that take an internal signal. It is
    found on the graph R002, R005 and R006 walk (`_routing_legs`), with each
    such strip an edge from the object it takes to everything it feeds.

    Per strip and per leg it feeds, the shortest path back along open legs
    is the loop if there is one, otherwise the shortest along any legs. A
    loop reached from each strip that takes part is reported once."""
    takers = {base: source for base in strip_bases(state)
              if (source := internal_input_source(state, base)) is not None}
    if not takers:
        return []
    strip_legs = {base: _strip_legs(state, base) for base in takers}
    edges: dict[str, list[tuple[tuple, _Leg]]] = {}
    for leg in _routing_legs(state):
        edges.setdefault(leg.source, []).append(((), leg))
    for base, (node, group, socket) in takers.items():
        for leg in strip_legs[base]:
            edges.setdefault(node, []).append((("takes", base, node, group, socket), leg))

    def back_to(start: str, goal: str, allowed: tuple[str, ...]):
        queue = deque([(start, ())])
        seen = {start}
        while queue:
            node, path = queue.popleft()
            if node == goal:
                return path
            for via, leg in edges.get(node, ()):
                if leg.state in allowed and leg.target not in seen:
                    seen.add(leg.target)
                    queue.append((leg.target, path + ((via,) if via else ()) + (leg,)))
        return None

    loops: dict[frozenset, FeedbackLoop] = {}
    for base, (node, group, socket) in takers.items():
        first = ("takes", base, node, group, socket)
        for leg in strip_legs[base]:
            tail = None
            for allowed in (("open",), ("open", "floor", "off")):
                if leg.state in allowed:
                    tail = back_to(leg.target, node, allowed)
                if tail is not None:
                    break
            if tail is None:
                continue
            hops = (first, leg) + tail
            key = frozenset(hop if isinstance(hop, _Leg) else hop[:2] for hop in hops)
            loops.setdefault(key, FeedbackLoop(base, hops))
    return sorted(loops.values(), key=lambda loop: (loop.strip, _loop_addresses(loop)))


def _loop_text(state: ConsoleState, loop: FeedbackLoop) -> str:
    """The loop hop by hop: `CH 12 "FX Return" takes BUS 3 (patched from BUS
    5, its left side); CH 12 sends to BUS 3`. A closed leg says what is
    holding it closed."""
    mentioned: set[str] = set()

    def name(node: str) -> str:
        if node.startswith("/"):
            base = node
        else:
            kind, number = node.split(":")
            base = f"/{kind}/{number}"
        text = (position_label(base) if base in mentioned or base.startswith(("/main/", "/mtx/"))
                else strip_label(state, base))
        mentioned.add(base)
        return text

    parts = []
    for hop in loop.hops:
        if isinstance(hop, _Leg):
            verb = "routes to" if hop.target.startswith("main:") else "sends to"
            note = {"off": " (switched off)", "floor": " (at the floor)"}.get(hop.state, "")
            parts.append(f"{name(hop.source)} {verb} {name(hop.target)}{note}")
        else:
            _tag, strip, node, group, socket = hop
            side = "left" if socket % 2 else "right"
            parts.append(f"{name(strip)} takes {name(node)} (patched from {group} {socket}, "
                         f"its {side} side)")
    return "; ".join(parts)


def _loop_addresses(loop: FeedbackLoop) -> tuple[str, ...]:
    addresses: list[str] = []
    for hop in loop.hops:
        if isinstance(hop, _Leg):
            addresses.extend(hop.addresses)
        else:
            addresses.extend((f"{hop[1]}/in/conn/grp", f"{hop[1]}/in/conn/in"))
    return tuple(dict.fromkeys(addresses))


def _rule_feedback_loop(state: ConsoleState) -> list[Finding]:
    """R009: a feedback loop with every leg open. ERROR: it howls the moment
    there is audio in it, and no setting makes it work."""
    return [Diagnostic.audit(
        "R009", Severity.ERROR, "routing", "Feedback Loop",
        f"{_loop_text(state, loop)}. The signal comes back round to what the strip takes, "
        f"so this feeds back as soon as there is audio in it. Switch off the send or route "
        f"that closes it, or patch {position_label(loop.strip)} from another source.",
        _loop_addresses(loop),
    ) for loop in feedback_loops(state) if loop.open]


def _rule_feedback_loop_held_closed(state: ConsoleState) -> list[Finding]:
    """R010: the same loop as R009 with a leg switched off or at the floor.
    WARNING: it is silent today and feeds back the moment the leg is opened."""
    return [Diagnostic.audit(
        "R010", Severity.WARNING, "routing", "Feedback Loop Held Closed",
        f"{_loop_text(state, loop)}. This is silent only because of the closed leg marked "
        f"above, and feeds back the moment it is opened. Remove the send or route, or patch "
        f"{position_label(loop.strip)} from another source.",
        _loop_addresses(loop),
    ) for loop in feedback_loops(state) if not loop.open]


# --------------------------------------------------------------------------
# Rules -- configuration (6)
# --------------------------------------------------------------------------


# A USER PATCH takes a physical jack straight into the console's own
# routing layer with no strip in between (USR 1..24 are USER SIGNALS,
# whose source is a strip; USR 25..56 are USER PATCHES, whose source is
# a jack). Only the second half
# consumes a socket, so only the second half answers C001's question.
USER_PATCH_SLOTS = range(25, 57)


# --------------------------------------------------------------------------
# R011: a stereo bus, Main or Matrix heard on one side
# --------------------------------------------------------------------------
#
# Each bus, Main and Matrix owns two output slots, `2N-1` for its left side and
# `2N` for its right (`output_source_object` is the inverse of the slot math).
# A stereo object puts a different signal on each, so when every output it is
# patched to uses the same slot, whatever is panned to the other side goes
# nowhere. A stereo object into one speaker is a one-sided mix, so this is a
# WARNING; the finding says how to dismiss it when the mono feed is meant.

_WIDTH_KINDS = (("BUS", "bus"), ("MAIN", "main"), ("MTX", "mtx"))
_WIDTH_PREFIX = dict(_WIDTH_KINDS)


def _main_is_fed(state: ConsoleState, idx: int) -> bool:
    """Does a strip or a bus route to Main `idx`, switched on?"""
    return any(
        idx in main_route_targets(state, b) and state.flag(f"{b}/main/{idx}/on")
        for b in strip_bases(state) + [f"/bus/{i}" for i in bus_indices(state)]
    )


def output_patch_sides(state: ConsoleState) -> dict[tuple[str, int], list[tuple[str, int, str]]]:
    """`(kind, index)` -> `(group, socket, "L" or "R")` for every output
    socket the state read that a bus, Main or Matrix feeds: the left side of
    object N is slot `2N-1`, the right `2N`."""
    sides: dict[tuple[str, int], list[tuple[str, int, str]]] = {}
    for group, socket in output_sockets(state):
        raw = state.output_source(group, socket)
        if raw is None or raw[0] not in _WIDTH_PREFIX:
            continue
        kind, slot = raw
        sides.setdefault((kind, (slot + 1) // 2), []).append(
            (group, socket, "L" if slot % 2 else "R"))
    return sides


def _width_object_in_use(state: ConsoleState, kind: str, idx: int) -> bool:
    if kind == "BUS":
        return is_in_use(state, f"/bus/{idx}")
    if kind == "MAIN":
        return _main_is_fed(state, idx)
    return _matrix_is_fed(state, idx)


def _rule_stereo_one_side(state: ConsoleState, declared: frozenset = frozenset()) -> list[Finding]:
    """R011. `declared` is the output sockets a plan states (`(group, socket)`
    pairs), which it leaves to the plan: an object is skipped when every
    socket it is patched to is one of them."""
    # "The other side is not patched" is a claim about every output socket,
    # so a reading that never asked for the output patch, or left an AES50
    # port in use unread, has no standing to make it.
    if not output_patch_was_read(state) or unread_output_groups_in_use(state):
        return []
    sides = output_patch_sides(state)
    read = summarise_sockets(output_sockets(state))
    findings = []
    for kind, idx in sorted(sides, key=lambda key: ([k for k, _ in _WIDTH_KINDS].index(key[0]), key[1])):
        base = f"/{_WIDTH_PREFIX[kind]}/{idx}"
        if state.flag(f"{base}/busmono") is not False:
            continue
        patches = sides[(kind, idx)]
        used = {side for _g, _s, side in patches}
        if len(used) != 1 or not _width_object_in_use(state, kind, idx):
            continue
        if all((g, s) in declared for g, s, _side in patches):
            continue
        heard, lost = ("left", "right") if used == {"L"} else ("right", "left")
        where = ", ".join(format_socket(g, s) for g, s, _side in sorted(patches))
        addresses = tuple(a for g, s, _side in sorted(patches)
                          for a in (f"/io/out/{g}/{s}/grp", f"/io/out/{g}/{s}/in"))
        findings.append(Diagnostic.audit(
            "R011", Severity.WARNING, "routing", "Stereo Output Patched On One Side",
            f"{strip_label(state, base)} is stereo but is patched on its {heard} side only "
            f"({where}), among the output sockets read ({read}), so anything panned {lost} is "
            f"not heard on an output. If a mono feed is meant, set it mono and this goes away; "
            f"if not, patch its {lost} side as well.",
            addresses,
        ))
    return findings


def user_patch_sources(state: ConsoleState) -> set[tuple[str, int]]:
    """Every physical input socket a USER PATCH slot takes its source from.

    `/io/in/USR/{n}/user/in` reads back one low per-leaf, like every other
    patch connector. A16 measured it on 2026-09-23 and it is in
    `console_facts._READBACK_INDEX_OFFSETS`, so a per-leaf read arrives here
    already corrected and a node-dump read never needed it. Before that,
    this read LCL 5 as LCL 4, and C001 blamed the wrong jack.
    """
    sources: set[tuple[str, int]] = set()
    for slot in USER_PATCH_SLOTS:
        group = state.text(f"/io/in/USR/{slot}/user/grp")
        number = state.number(f"/io/in/USR/{slot}/user/in")
        if group and group != "OFF" and number is not None:
            sources.add((group, int(number)))
    return sources


#: Source widths that take two sockets, the odd one and the next
#: (`/io/in/{grp}/{n}/mode`). `M/S` is a mid-side pair: two sockets, one
#: stereo signal, the same as `ST` for whether the even socket is in use.
TWO_SOCKET_INPUT_MODES = frozenset({"ST", "M/S"})


def input_pair_sockets(state: ConsoleState, group: str, socket: int) -> list[int]:
    """The sockets a strip patched to `socket` hears: that one, and the next
    when the source is stereo. A stereo strip names only the odd socket of
    its pair in `in/conn/in`; the even one is taken because the source width
    (`/io/in/{grp}/{n}/mode`) is a two-socket one. WING pairs are always
    odd-even, so only an odd socket carries its neighbour."""
    legs = [socket]
    if socket % 2 == 1 and state.input_mode(group, socket) in TWO_SOCKET_INPUT_MODES:
        legs.append(socket + 1)
    return legs


def strip_source_sockets(state: ConsoleState, base: str) -> list[tuple[str, int]]:
    """The physical input sockets the strip hears now, `(group, socket)`
    each: its patch and, for a stereo source, the next socket. Empty when the
    strip is unpatched, is switched to its alternate input, or may be
    following the engaged global alternate switch: the alternate's socket is
    not read, so what the strip hears is not known."""
    patch = state.patch(base)
    if patch is None or state.on_alternate_input(base):
        return []
    if state.flag(console_facts.GLOBAL_ALT_SWITCH) and state.alternate_group(base) is not None:
        return []
    group, socket = patch
    return [(group, leg) for leg in input_pair_sockets(state, group, socket)]


def _rule_phantom_unpatched(state: ConsoleState, judged: frozenset = frozenset()) -> list[Finding]:
    """C001. `judged` is the sockets a plan comparison already speaks for
    (`phantom_judgements`), which it leaves to that comparison."""
    findings = []
    patched = {state.patch(b) for b in strip_bases(state)}
    patched.discard(None)
    # A stereo strip names only the odd socket of its pair in
    # `in/conn/in`; the even one is taken because the SOURCE is in a
    # two-socket width (`/io/in/{grp}/{n}/mode`, which `apply` writes on
    # both sockets). WING pairs are always odd-even
    # (`console_facts.STEREO_PAIR_RULE`), so only an odd socket can carry its
    # neighbour. Without this the right-hand mic of every stereo condenser
    # pair read as 48V on an unpatched socket on a correctly applied desk.
    patched |= {(group, leg) for group, socket in patched
                for leg in input_pair_sockets(state, group, socket)}
    # *"Phantom power is enabled on a physical input that is patched to no
    # channel or user patch."* A condenser feeding a USER PATCH slot --
    # straight into a Matrix, a monitor feed or a recording leg with no
    # strip of its own -- needs its 48V exactly as much as one on a
    # channel, and the rule used to call it a fault.
    patched |= user_patch_sources(state)
    for group, socket in input_sockets(state):
        if (state.input_phantom(group, socket) and (group, socket) not in patched
                and (group, socket) not in judged):
            findings.append(Diagnostic.audit(
                "C001", Severity.WARNING, "configuration", "Phantom Power On Unpatched Socket",
                f"48V is on for {format_socket(group, socket)} but nothing is patched to it -- "
                f"no channel, no aux and no user patch.",
                (f"/io/in/{group}/{socket}/vph",),
            ))
    return findings


def _rule_shared_input(state: ConsoleState) -> list[Finding]:
    """Named strips, not bare addresses. "LCL 1 feeds /ch/1
    and /ch/2" is a fact the engineer then has to go and look up; "feeds
    /ch/1 (Kick) and /ch/2 (Kick Sub)" is the same finding readable at the
    desk -- and on a board somebody else set up those names live on the
    socket, so until `effective_name` existed this rule could not have
    printed them."""
    findings = []
    by_socket: dict[tuple[str, int], list[str]] = {}
    for base in strip_bases(state):
        p = state.patch(base)
        if p is not None:
            by_socket.setdefault(p, []).append(base)
    for (group, socket), bases in by_socket.items():
        if len(bases) > 1:
            findings.append(Diagnostic.audit(
                "C002", Severity.INFO, "configuration", "Shared Physical Input",
                f"{format_socket(group, socket)} feeds more than one strip: "
                f"{', '.join(strip_label(state, b) for b in bases)}.",
                tuple(bases),
            ))
    return findings


def _rule_patched_from_empty_bay(state: ConsoleState) -> list[Finding]:
    """An earlier change, the deferred half. *"A channel is patched from,
    or an output routed to, an expansion bay the desk reports empty."*

    `apply` refuses to create this (`apply.unfitted_bays_the_plan_needs`);
    this is the same check against the desk in front of you -- a show
    applied before that refusal existed, patched by hand, or a card pulled
    after the show went in. The desk accepts the patch and reads it back
    (`console_facts.UNFITTED_BAY_PATCH_IS_ACCEPTED`), so nothing else says
    so.

    ERROR because it is a physical setting that cannot work: "a patch
    into an empty bay" is the standard example of one. **Silent, not
    clean, when the bay was never read** -- `bay_is_empty` says "empty"
    only on the literal `NONE`, so a state without the reading, or with a
    card name this table has never met, produces nothing here.
    """
    findings = []
    for group, addresses in sorted(expansion_bays_in_use(state).items()):
        bay_address = console_facts.EXPANSION_BAY_ADDRESSES[group]
        reported = state.get(bay_address)
        if not console_facts.bay_is_empty(reported):
            continue
        for address in addresses:
            if address.startswith("/io/out/"):
                _, _, _, out_group, out_socket = address.split("/")[:5]
                what = (f"output {format_socket(out_group, int(out_socket))} has a source "
                        f"patched to it")
            else:
                base = address.split("/in/conn/", 1)[0]
                patch = state.patch(base)
                what = f"{strip_label(state, base)} is patched from {format_socket(group, patch[1])}"
            findings.append(Diagnostic.audit(
                "C003", Severity.ERROR, "configuration", "Patch Uses An Empty Expansion Bay",
                f"{what}, but {bay_address} reports {reported!r}: there is nothing "
                f"in that bay, so no audio passes. The desk accepts and shows this "
                f"patch without complaint.",
                (address, bay_address),
            ))
    return findings


def _rule_on_alternate_input(state: ConsoleState, virtual_soundcheck: bool = False) -> list[Finding]:
    """A WING channel carries two input patches and a
    per-channel switch between them (`console_facts.ALT_PATCH_*`,
    A7 on hardware, 2026-09-21). The alternate is how virtual soundcheck
    works -- record the show to the WLIVE card, play it back into the
    channels the next day -- and **a channel left on its alternate is a
    channel not hearing the stage**, while its main patch, which is all
    any other check here reads, still looks exactly right.

    WARNING, not ERROR: this is a working setting somebody chose, and
    during a virtual soundcheck it is the correct one. But it is never the
    state a show starts in, it is invisible from the main patch, and the
    cost of missing it is a silent channel at doors -- so it is said out
    loud rather than left to INFO. A hazard, reported on any strip: whose
    strip it is does not change what it hears.

    With `virtual_soundcheck` (Watch's switch, `virtual_soundcheck_rules`)
    the engineer has said the alternate is on purpose, so every strip is
    still named but at INFO, with that as the reason.

    Silent when the switch was never read (any capture made before this
    rule), rather than calling the channel clean.
    """
    findings = []
    for base in strip_bases(state):
        if not state.on_alternate_input(base):
            continue
        main = state.patch(base)
        main_text = format_socket(*main) if main else "nothing"
        alt = state.alternate_group(base)
        alt_text = (f"its alternate patch from {alt}" if alt else
                    "its alternate patch, which is set to OFF")
        if virtual_soundcheck:
            severity = Severity.INFO
            advice = ("Virtual soundcheck is on, so this is expected; if the show is live, "
                      "switch it back on the desk and turn virtual soundcheck off.")
        else:
            severity = Severity.WARNING
            advice = ("After a virtual soundcheck this is a channel that does "
                      "not hear the stage; switch it back on the desk if the show is live.")
        findings.append(Diagnostic.audit(
            "C004", severity, "configuration", "Channel On Its Alternate Input",
            f"{strip_label(state, base)} is listening to {alt_text}, not its main patch "
            f"({main_text}). {advice}",
            (f"{base}/in/set/altsrc", f"{base}/in/conn/altgrp"),
        ))
    return findings


def _rule_global_alternate_switch(state: ConsoleState, virtual_soundcheck: bool = False) -> list[Finding]:
    """The console's GLOBAL alternate switch (`/io/altsw`) is
    engaged: every strip set to follow it is on its alternate input, with
    no strip's own `altsrc` saying so -- which is why C004 cannot see
    it. One finding for the desk, never one per strip.

    What 1 means is INFERRED, not measured (`console_facts.
    GLOBAL_ALT_SWITCH`): the only snapshot reading `true` was saved after
    the switch was flipped, and nothing has shown which strips then
    moved. Which strips follow it (`in/set/srcauto`, inferred) is not
    understood either, so the finding does not name any. Silent when the
    switch was never read.

    With `virtual_soundcheck` it is reported at INFO, as C004 is.
    """
    if not state.flag(console_facts.GLOBAL_ALT_SWITCH):
        return []
    if virtual_soundcheck:
        severity = Severity.INFO
        advice = ("Virtual soundcheck is on, so this is expected; if the show is live, "
                  "switch it back on the desk and turn virtual soundcheck off.")
    else:
        severity = Severity.WARNING
        advice = "After a virtual soundcheck, switch it back on the desk if the show is live."
    return [Diagnostic.audit(
        "C005", severity, "configuration", "Global Alternate Switch Engaged",
        "The console's global alternate-input switch is engaged (/io/altsw = 1). Every strip "
        f"set to follow it (Input Select: Global) is listening to its alternate input, which "
        f"no strip's own switch shows. {advice} "
        "(What 1 means is inferred from one flip, not measured.)",
        (console_facts.GLOBAL_ALT_SWITCH,),
    )]


#: The rules a virtual soundcheck turns down to INFO.
VIRTUAL_SOUNDCHECK_RULE_IDS = ("C004", "C005")


def virtual_soundcheck_rules(rules) -> list[AuditRule]:
    """`rules` with C004 and C005 reporting at INFO: the engineer has said
    the alternate inputs are on purpose (a virtual soundcheck). Every strip
    on its alternate is still named, and the finding says why it is not a
    warning; the other rules are untouched. Watch swaps these in while its
    Virtual soundcheck switch is on and the originals back when it is off,
    so a strip left on its alternate is a WARNING again at once."""
    out = []
    for rule in rules:
        if rule.id == "C004":
            rule = replace(rule, severity=Severity.INFO,
                           check=lambda state: _rule_on_alternate_input(state, True))
        elif rule.id == "C005":
            rule = replace(rule, severity=Severity.INFO,
                           check=lambda state: _rule_global_alternate_switch(state, True))
        out.append(rule)
    return out


def _rule_strip_has_no_source(state: ConsoleState) -> list[Finding]:
    """C006: a channel or aux that is in use -- named, or sending somewhere
    other than the factory's Main 1 -- with nothing patched to its main
    input (`in/conn/grp` is `OFF`).

    The other end of R008's path: R008 asks where a strip's signal goes,
    this asks whether the strip has one. A named strip with its fader up
    and its sends on carries silence when no socket feeds it, and its
    overview looks finished.

    Left to others: a strip on its alternate input (C004 says so, whether
    the alternate is a group or `OFF`), a strip that may be following the
    engaged global alternate switch (C005) and has an alternate patch, and
    the talk mic (T002). Muted and at the floor are not exemptions: a show
    built from conventions starts every fader at the floor, and a patch
    lost before the faders come up is the fault this exists to catch.
    Silent when the group was never read.
    """
    findings = []
    talk = talkback_strip(state)
    global_alternate = bool(state.flag(console_facts.GLOBAL_ALT_SWITCH))
    for base in strip_bases(state):
        if base == talk:
            continue
        if state.text(f"{base}/in/conn/grp") not in ("OFF", ""):
            continue  # patched, or never read
        if state.on_alternate_input(base) or (
                global_alternate and state.alternate_group(base) is not None):
            continue
        if not is_in_use(state, base):
            continue
        why = ("named" if _is_active_name(state.name(base))
               else "sending somewhere")
        findings.append(Diagnostic.audit(
            "C006", Severity.WARNING, "configuration", "Strip In Use Has No Source",
            f"{strip_label(state, base)} is in use ({why}) but nothing is patched to it, "
            f"so it has no source. Patch an input to it on the desk, or pull its fader down "
            f"and clear its name and sends if the strip is not wanted.",
            (f"{base}/in/conn/grp",),
        ))
    return findings


def _rule_input_socket_muted(state: ConsoleState) -> list[Finding]:
    """C007: a channel or aux in use whose source socket is muted at the
    socket (`/io/in/{grp}/{n}/mute`), or -- for a stereo source -- one of
    whose two sockets is muted and the other is not.

    A WING input socket has a mute of its own. A muted socket silences
    every strip patched to it and nothing on the strip shows it: the
    strip's own mute is off and its fader is up. WARNING: it is a mute
    somebody made, so it is not a setting that cannot work, but it is
    invisible where the engineer looks and the strip is in use.

    A stereo source is two sockets, the odd one named by the patch and the
    next one taken with it (the pairing C001 uses). Silent for a socket
    whose mute was never read, for a strip on its alternate input (C004
    speaks) and for one that may be following the engaged global alternate
    switch (C005). The talk mic is skipped (T002).
    """
    findings = []
    talk = talkback_strip(state)
    for base in strip_bases(state):
        sockets = strip_source_sockets(state, base)
        if base == talk or not sockets:
            continue
        group, socket = sockets[0]
        legs = [leg for _group, leg in sockets]
        muted = [state.input_muted(group, leg) for leg in legs]
        if any(flag is None for flag in muted) or not any(muted):
            continue
        if not is_in_use(state, base):
            continue
        label = strip_label(state, base)
        if all(muted):
            where = (format_socket(group, socket) if len(legs) == 1
                     else f"{format_socket(group, socket)}-{legs[-1]}")
            verb = "is" if len(legs) == 1 else "are both"
            message = (f"{label} is fed from {where}, which {verb} muted at the socket. "
                       f"Nothing on the strip shows it; unmute the input on the desk.")
        else:
            silent = format_socket(group, next(leg for leg, flag in zip(legs, muted) if flag))
            message = (f"{label} is a stereo source on {format_socket(group, socket)}-{legs[-1]}, "
                       f"and {silent} is muted at the socket while the other is not, so one "
                       f"side of it is silent. Unmute the input on the desk.")
        findings.append(Diagnostic.audit(
            "C007", Severity.WARNING, "configuration", "Strip's Input Socket Muted",
            message,
            (f"{base}/in/conn/grp",
             *(f"/io/in/{group}/{leg}/mute" for leg in legs)),
        ))
    return findings


def _number_runs(numbers: list[int]) -> str:
    """[1, 2, 3, 5] -> "1-3, 5": a list of socket numbers, as a person
    would read it off a patch bay."""
    runs: list[list[int]] = []
    for n in sorted(set(numbers)):
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def aes50_port_dependents(state: ConsoleState) -> dict[str, tuple[list[str], list[int]]]:
    """AES50 port -> (the strips taking their input from it, the output
    sockets on it that carry a source), for every port something depends on.

    A strip counts by its main patch, so one switched to its alternate input
    (C004 speaks) or one that may be following the engaged global alternate
    switch (C005) is left out: the alternate's socket number is not read, so
    where such a strip listens is not known. An output counts only when a
    source is patched to it, as for an empty expansion bay. Every strip is
    counted, the talk mic's included: a talk mic on a dead stage box is as
    silent as any other."""
    global_alternate = bool(state.flag(console_facts.GLOBAL_ALT_SWITCH))
    found: dict[str, tuple[list[str], list[int]]] = {}
    for base in strip_bases(state):
        patch = state.patch(base)
        if patch is None or patch[0] not in console_facts.AES50_PORTS:
            continue
        if state.on_alternate_input(base):
            continue
        if global_alternate and state.alternate_group(base) is not None:
            continue
        found.setdefault(patch[0], ([], []))[0].append(base)
    for group, socket in output_sockets(state):
        if group in console_facts.AES50_PORTS and state.output_source(group, socket) is not None:
            found.setdefault(group, ([], []))[1].append(socket)
    return found


def _dependents_text(state: ConsoleState, strips: list[str], outputs: list[int]) -> str:
    """"CH 1 "Kick" and CH 2 "Snare" take their input from it, and
    outputs 1-6 on it carry a source" -- what a dead AES50 port takes down."""
    parts = []
    if strips:
        shown = [strip_label(state, base) for base in strips[:6]]
        if len(strips) > 6:
            shown.append(f"{len(strips) - 6} more")
        who = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + f" and {shown[-1]}"
        parts.append(f"{who} {'takes its' if len(strips) == 1 else 'take their'} input from it")
    if outputs:
        parts.append(f"output{'' if len(outputs) == 1 else 's'} {_number_runs(outputs)} on it "
                     f"{'carries' if len(outputs) == 1 else 'carry'} a source")
    return " and ".join(parts)


def _aes50_link(state: ConsoleState, port: str) -> str | None:
    """The status the desk read for an AES50 port, or None when it was never
    read or is a word the desk's list does not have: the rules about the
    link say nothing for a port they have no word on."""
    status = state.text(console_facts.aes50_status_address(port))
    return status if status in ("-", *console_facts.AES50_DEVICE_STATES) else None


def _rule_aes50_cannot_carry_patch(state: ConsoleState) -> list[Finding]:
    """C008: an AES50 port whose link carries no audio -- it reads `-` (no
    stage box on it) or `ERR` (a link error) -- while a strip takes its
    input from it or an output on it carries a source.

    A stage box whose link has failed silences every input and output on it
    at once, and nothing on the strips shows it: the patch is as it was
    set. ERROR, as C003 is for an empty expansion bay: the desk accepts the
    patch and no audio passes, so it is a setting that cannot work. A port
    nothing depends on is not reported here (C009 reports one in error).
    Silent when the port's status was never read -- a live read takes it
    whenever it reads output sockets -- and for a status the desk's list
    does not have. One finding per port, naming what is on it.
    """
    findings = []
    dependents = aes50_port_dependents(state)
    for port in console_facts.AES50_PORTS:
        link = _aes50_link(state, port)
        if link not in ("-", "ERR") or port not in dependents:
            continue
        strips, outputs = dependents[port]
        what = _dependents_text(state, strips, outputs)
        address = console_facts.aes50_status_address(port)
        if link == "-":
            message = (f"AES50-{port} reads '-', so no stage box is on "
                       f"it, but {what}. No audio can pass: connect the stage box, or "
                       f"patch these elsewhere.")
        else:
            message = (f"AES50-{port} reports a link error (ERR), and "
                       f"{what}. No audio passes while the link is in error: check the cable "
                       f"and the stage box.")
        findings.append(Diagnostic.audit(
            "C008", Severity.ERROR, "configuration", "AES50 Port Cannot Carry Its Patch",
            message, (address,),
        ))
    return findings


def _rule_aes50_link_not_ok(state: ConsoleState) -> list[Finding]:
    """C009: a stage box on an AES50 port whose link is not `OK` and which
    C008 does not already report: one reading `UPD` (updating), or one in
    error (`ERR`) that nothing is patched from or to.

    WARNING: neither is a setting that cannot work. An update finishes on
    its own, and a link in error with nothing on it loses nothing yet; but
    a stage box that passes no audio is worth knowing about before doors,
    and the strips patched to one that is updating are silent until it is
    done. What `ERR` and `UPD` mean is the desk's own wording, read from
    the status list and not yet confirmed against a stage box. Silent when
    the status was never read and for a port that reads `OK` or `-`.
    """
    findings = []
    dependents = aes50_port_dependents(state)
    for port in console_facts.AES50_PORTS:
        link = _aes50_link(state, port)
        if link not in ("UPD", "ERR") or (link == "ERR" and port in dependents):
            continue
        name = f"AES50-{port}"
        what = _dependents_text(state, *dependents.get(port, ([], [])))
        if link == "UPD":
            message = (f"{name} reports UPD: the stage box on it is updating"
                       + (f", and {what}. Those carry no audio until it finishes."
                          if what else ". Nothing is patched from it or to it yet."))
        else:
            message = (f"{name} reports a link error (ERR) on a stage box that nothing is "
                       f"patched from or to. Nothing in the show is lost yet, but the link "
                       f"will not carry audio: check the cable and the stage box.")
        findings.append(Diagnostic.audit(
            "C009", Severity.WARNING, "configuration", "AES50 Stage Box Link Not OK",
            message, (console_facts.aes50_status_address(port),),
        ))
    return findings


# --------------------------------------------------------------------------
# Rules -- effects (3)
# --------------------------------------------------------------------------


def insert_bases(state: ConsoleState) -> list[str]:
    """Every object that can carry an insert point, in the order a desk
    lists them: channels, auxes, busses, Mains, Matrices."""
    return (strip_bases(state)
            + [f"/bus/{n}" for n in bus_indices(state)]
            + [f"/main/{n}" for n in main_indices(state)]
            + [f"/mtx/{n}" for n in matrix_indices(state)])


#: How a WING labels its two insert points on screen.
_INSERT_POINT_NAMES = {"preins": "pre-insert", "postins": "post-insert"}


def _fx_text(state: ConsoleState, slot: int) -> str:
    return f"FX{slot} ({state.fx_model(slot)})"


def _rule_insert_on_empty_slot(state: ConsoleState) -> list[Finding]:
    """An insert switched ON that names an FX slot with nothing
    loaded in it (`mdl == NONE`). Somebody meant this strip to be
    processed -- a reverb on a bus, a de-esser on a vocal -- and the desk
    is doing nothing to it, while the strip's insert button looks lit.

    WARNING: the strip still passes audio, so the show can go on, but what
    the engineer hears is not what the strip says it is doing. Typically
    a slot cleared or reloaded after the insert was set, or a scene that
    recalled inserts without the FX. Silent when the slot's model was
    never read, rather than calling it empty.
    """
    findings = []
    for base in insert_bases(state):
        for point, slot, on in state.inserts(base):
            if not on or slot is None or state.fx_model(slot) != console_facts.FX_EMPTY:
                continue
            findings.append(Diagnostic.audit(
                "E001", Severity.WARNING, "effects", "Insert On An Empty FX Slot",
                f"{strip_label(state, base)}'s {_INSERT_POINT_NAMES[point]} is on and names FX{slot}, "
                f"which has no effect loaded. Nothing is processing this strip; "
                f"load the effect into FX{slot} or point the insert at the slot "
                f"that has it.",
                (f"{base}/{point}/on", f"{base}/{point}/ins",
                 console_facts.FX_MODEL.replace("{n}", str(slot))),
            ))
    return findings


def _rule_fx_not_inserted(state: ConsoleState) -> list[Finding]:
    """An FX slot with an effect loaded that
    no insert point on the desk names. WING has no FX send/return: an
    effect nobody inserts is an effect nobody hears.

    INFO: it costs nothing but a slot, and a loaded-but-idle effect is a
    common leftover from a previous show. Said because the other reading
    -- a reverb the engineer set up and then never patched in -- sounds
    like a dry mix and is hard to find by ear. Silent unless insert points
    were read at all, so a capture made before this rule cannot call
    every loaded slot orphaned.
    """
    named: set[int] = set()
    read_any = False
    for base in insert_bases(state):
        for _point, slot, _on in state.inserts(base):
            read_any = True
            if slot is not None:
                named.add(slot)
    if not read_any:
        return []
    findings = []
    for slot in range(1, console_facts.FX_SLOTS + 1):
        model = state.fx_model(slot)
        if model is None or model == console_facts.FX_EMPTY or slot in named:
            continue
        findings.append(Diagnostic.audit(
            "E002", Severity.INFO, "effects", "FX Loaded But Not Inserted",
            f"{_fx_text(state, slot)} has an effect loaded, but no channel, aux, "
            f"bus, Main or Matrix inserts it, so nothing is heard through it.",
            (console_facts.FX_MODEL.replace("{n}", str(slot)),),
        ))
    return findings


def _rule_insert_switched_off(state: ConsoleState) -> list[Finding]:
    """An effect bypassed from the strip: the bypass is the
    STRIP's insert switch, not a field on the slot -- `/fx/{n}` has none.
    A strip naming a slot with an effect loaded, with its insert switched
    off.

    INFO, and a convention rather than a hazard: bypassing an effect is
    something an engineer does on purpose, mid-show, all the time. Before
    a show it is worth one line -- a vocal reverb bus with its insert off
    returns the dry vocal -- but only about a strip the plan is about.
    """
    findings = []
    for base in insert_bases(state):
        for point, slot, on in state.inserts(base):
            if on is not False or slot is None:
                continue
            model = state.fx_model(slot)
            if model is None or model == console_facts.FX_EMPTY:
                continue
            findings.append(Diagnostic.audit(
                "E003", Severity.INFO, "effects", "FX Inserted But Switched Off",
                f"{strip_label(state, base)}'s {_INSERT_POINT_NAMES[point]} names {_fx_text(state, slot)}, "
                f"but the insert is switched off, so the effect is bypassed.",
                (f"{base}/{point}/on", f"{base}/{point}/ins"),
            ))
    return findings


# --------------------------------------------------------------------------
# Rules -- communications (1)
# --------------------------------------------------------------------------


def _rule_talkback_goes_nowhere(state: ConsoleState) -> list[Finding]:
    """Talkback is assigned
    to a strip (`/cfg/talk/assign` is `CH40` or `AUX8`), and neither TALK
    A nor TALK B is routed to a single bus, Matrix or Main. Somebody set
    talkback up, and pressing either button reaches nobody -- which the
    engineer finds out when the band does not answer.

    WARNING: the show can go on without talkback, but the one person who
    needs it to work is the one who cannot hear that it does not. Gated on
    `assign` because an unassigned talkback with no destinations is the
    factory state, not a fault. Silent unless all 56 switches were read,
    rather than calling an unread one off.
    """
    assign = state.text(console_facts.TALK_ASSIGN)
    if assign is None or assign == console_facts.TALK_OFF:
        return []
    switches = [console_facts.talk_destination(button, dest)
                for button in console_facts.TALK_BUTTONS
                for dest in console_facts.TALK_DESTINATIONS]
    flags = [state.flag(address) for address in switches]
    if any(flag is None for flag in flags) or any(flags):
        return []
    return [Diagnostic.audit(
        "T001", Severity.WARNING, "communications", "Talkback Goes Nowhere",
        f"Talkback is assigned to {assign}, but neither TALK A nor TALK B is "
        f"routed to any bus, Matrix or Main, so pressing either reaches nobody. "
        f"Pick TALK A's destinations (and TALK B's, if it is used) on the "
        f"desk's talkback page.",
        (console_facts.TALK_ASSIGN,
         console_facts.talk_destination("A", "B1"),
         console_facts.talk_destination("B", "B1")),
    )]


# The strip each `/cfg/talk/assign` value puts the talk mic on.
_TALKBACK_BASES = {"CH40": "/ch/40", "AUX8": "/aux/8"}


def talkback_strip(state: ConsoleState) -> str | None:
    """The base address of the strip talkback is assigned to (`/ch/40` or
    `/aux/8`), or None when talkback is OFF or `assign` was never read.

    That strip is the talk mic, and a talk mic is kept out of the mix on
    purpose: fader down, in no DCA, no send or route, no jack patched.
    CH001, L002, R008, C006 and C007 skip it, and T002 says so once (T001's first run
    on the Compact flagged both on ch 40 "TALKBACK")."""
    return _TALKBACK_BASES.get(state.text(console_facts.TALK_ASSIGN))


def _rule_talkback_strip_exempt(state: ConsoleState) -> list[Finding]:
    """T002: the talkback strip is in use, so CH001, L002, R008, C006 and C007
    would have judged it as a band strip. They skip it; this is the one
    line that says they did, rather than the exemption being silent."""
    base = talkback_strip(state)
    if base is None or not is_in_use(state, base):
        return []
    return [Diagnostic.audit(
        "T002", Severity.INFO, "communications", "Talkback Strip Left Out Of Mix Checks",
        f"{strip_label(state, base)} is the strip talkback is assigned to "
        f"({state.text(console_facts.TALK_ASSIGN)}), so it is treated as the talk mic: "
        f"'in no DCA' (CH001), 'fader at floor' (L002), 'sends nowhere' (R008), 'nothing "
        f"patched' (C006) and 'socket muted' (C007) are not reported for it.",
        (console_facts.TALK_ASSIGN, base),
    )]


# --------------------------------------------------------------------------
# Rules -- channels (4)
# --------------------------------------------------------------------------


def _rule_channel_no_dca(state: ConsoleState) -> list[Finding]:
    findings = []
    all_members = {b for members in _dca_members(state).values() for b in members}
    talk = talkback_strip(state)
    for base in strip_bases(state):
        if base == talk:
            continue  # the talk mic, kept out of DCAs on purpose (T002)
        if is_in_use(state, base) and base not in all_members:
            findings.append(Diagnostic.audit(
                "CH001", Severity.INFO, "channels", "Channel Not In Any DCA",
                f"{strip_label(state, base)} is in use but belongs to no DCA group.",
                (base,),
            ))
    return findings


def _rule_dca_low_with_members(state: ConsoleState) -> list[Finding]:
    findings = []
    for idx, members in _dca_members(state).items():
        base = f"/dca/{idx}"
        active_members = [m for m in members if is_in_use(state, m)]
        if not active_members:
            continue
        fdr = state.fader_db(base)
        if fdr is not None and fdr <= DCA_LOW_FADER_DB:
            where = "at the floor" if fdr <= FADER_FLOOR_DB else f"at {fdr:g}dB"
            findings.append(Diagnostic.audit(
                "CH002", Severity.WARNING, "channels", "DCA Fader Low With Active Members",
                f"{strip_label(state, base)} is {where} ({DCA_LOW_FADER_DB:g}dB or lower) but controls "
                f"{len(active_members)} active member(s): "
                f"{', '.join(strip_label(state, m) for m in active_members)}.",
                (f"{base}/fdr",),
            ))
    return findings


def _rule_mute_group_silencing(state: ConsoleState) -> list[Finding]:
    findings = []
    for idx, members in _mute_group_members(state).items():
        base = f"/mgrp/{idx}"
        if not state.mute(base):
            continue
        # *"An engaged mute group is silencing active members."* The test
        # used to be "routed", which on a factory WING is every strip on
        # the desk -- `main/1/on` ships on. `is_in_use` is the catalogue's
        # own definition and excludes exactly that.
        active_members = [m for m in members if is_in_use(state, m)]
        if active_members:
            findings.append(Diagnostic.audit(
                "CH003", Severity.INFO, "channels", "Mute Group Active, Silencing Routed Members",
                f"{strip_label(state, base)} is engaged and is silencing {len(active_members)} "
                f"active member(s): {', '.join(strip_label(state, m) for m in active_members)}.",
                (f"{base}/mute",),
            ))
    return findings


def planned_dca_mutes(plan: dict) -> frozenset:
    """The DCAs whose mute the plan judges, as console bases: every DCA it
    declares with an index. A DCA it leaves unmuted is CV017's when it is
    muted on the desk, and one it states muted is the setting it asked for
    (CV012 reports the other direction)."""
    return frozenset(
        f"/dca/{entry['index']}"
        for entry in (plan.get("dcas") or {}).values()
        if isinstance(entry, dict) and isinstance(entry.get("index"), int))


def _rule_dca_muted_with_members(state: ConsoleState,
                                 planned: frozenset = frozenset()) -> list[Finding]:
    """CH004: a DCA whose own mute is on while it controls at least one
    active member -- CH002's DCA, but the mute switch rather than the fader.

    A muted DCA silences everything under it, and the members show nothing:
    each strip's mute is off and its fader is up. INFO, as CH003 is for a
    mute group: pressing a DCA's mute is a deliberate act, and the DCA strip
    shows it lit, so this says what the press is silencing rather than
    calling it a fault. The members are the ones CH002 counts (`_dca_members`
    and `is_in_use`).

    `planned` is the DCAs a plan judges (`planned_dca_mutes`): under a plan
    CV017 reports a muted DCA the plan leaves unmuted, and a DCA the plan
    states muted is as asked, so the rule says nothing about either. A DCA
    whose mute was never read is not called muted.
    """
    findings = []
    for idx, members in _dca_members(state).items():
        base = f"/dca/{idx}"
        if base in planned or not state.mute(base):
            continue
        active_members = [m for m in members if is_in_use(state, m)]
        if active_members:
            findings.append(Diagnostic.audit(
                "CH004", Severity.INFO, "channels", "DCA Muted, Silencing Active Members",
                f"{strip_label(state, base)} is muted and is silencing {len(active_members)} "
                f"active member(s): {', '.join(strip_label(state, m) for m in active_members)}.",
                (f"{base}/mute",),
            ))
    return findings


# --------------------------------------------------------------------------
# Rules -- naming (2)
# --------------------------------------------------------------------------


def _rule_duplicate_names(
    title: str, noun: str, rule_id: str, bases: list[str], state: ConsoleState
) -> list[Finding]:
    """`_is_active_name` is what makes both rules say "non-default": a
    factory WING names every bus `BUS 3` and every channel `CH07`, so a
    comparison over raw names would report sixteen colliding busses on a
    desk nobody has touched.

    The name compared is `effective_name`, not `{base}/name`.
    Two strips a person named identically on the desk have blank strip
    names and their names on their sockets, so a comparison over the strip
    leaf alone cannot see the collision at all -- which is the whole
    failure mode on a board somebody else set up. The cited address is the
    one the name was read from, socket or strip, so the engineer is sent
    to the thing this rule looked at."""
    by_name: dict[str, list[tuple[str, str]]] = {}
    for base in bases:
        name = effective_name(state, base)
        if _is_active_name(name):
            by_name.setdefault(name, []).append((base, name_address(state, base)))
    findings = []
    for name, dupes in by_name.items():
        addresses = sorted({address for _, address in dupes})
        # Two strips fed by ONE socket read the same name because it is
        # the same name, in one place, not two things called the same
        # thing -- a festival split or a monitor feed, which C002
        # reports as what it is. A collision needs two sources.
        if len(dupes) > 1 and len(addresses) > 1:
            findings.append(Diagnostic.audit(
                rule_id, Severity.WARNING, "naming", title,
                f"{len(dupes)} {noun} share the name {name!r}: "
                f"{', '.join(position_label(base) for base, _ in dupes)}.",
                tuple(addresses),
            ))
    return findings


def _rule_duplicate_channel_names(state: ConsoleState) -> list[Finding]:
    return _rule_duplicate_names(
        "Duplicate Channel/Aux Names", "channel/aux strips", "N001", strip_bases(state), state)


def _rule_duplicate_bus_names(state: ConsoleState) -> list[Finding]:
    return _rule_duplicate_names(
        "Duplicate Bus Names", "busses", "N002",
        [f"/bus/{i}" for i in bus_indices(state)], state)


# --------------------------------------------------------------------------
# Rules -- levels (2)
# --------------------------------------------------------------------------


def _rule_dead_send(state: ConsoleState) -> list[Finding]:
    """*"ANY send is enabled and pulled to within 44dB of the floor..."* --
    a channel's or aux's send to a bus, and every Matrix send there is,
    including the ones a Bus and a Main carry. Strip sends to a bus were
    all this looked at, which left a Matrix feed pulled to -110dB entirely
    unchecked."""
    findings = []
    sources = (strip_bases(state)
               + [f"/bus/{i}" for i in bus_indices(state)]
               + [f"/main/{i}" for i in main_indices(state)])
    for base in sources:
        sends = ([(f"{base}/send/{n}", f"BUS {n}") for n in send_targets(state, base)]
                 + [(f"{base}/send/MX{n}", f"MTX {n}") for n in matrix_send_targets(state, base)])
        for send_base, where in sends:
            if not state.flag(f"{send_base}/on"):
                continue
            lvl = state.number(f"{send_base}/lvl")
            if lvl is not None and FADER_FLOOR_DB < lvl <= NEAR_SILENT_THRESHOLD_DB:
                findings.append(Diagnostic.audit(
                    "L001", Severity.WARNING, "levels", "Send On But Near-Silent",
                    f"{strip_label(state, base)}'s send to {where} is on at {lvl:g}dB -- audible in "
                    "principle, in practice dead.",
                    (f"{send_base}/lvl",),
                ))
    return findings


def _rule_fader_floor_while_active(state: ConsoleState,
                                   planned_floor: frozenset = frozenset()) -> list[Finding]:
    """*"An unmuted, active channel, aux or bus's own fader sits at the
    floor."*

    "Active" was "routed anywhere", and on a factory WING that is every
    strip on the desk and half the busses, because `main/1/on` ships on --
    twenty-nine of the A5 run's forty-eight findings were that and nothing
    else. It is `is_in_use` now: the lever is what 'actively routed' is taken to
    mean, not whether to hide the rule.

    `planned_floor` is the strips the show's plan itself puts
    at the floor (`planned_floor_strips`): a fader down because the
    conventions say "start every channel fader all the way down" is the
    plan obeyed, not a hazard, and Watch -- which runs no CV002 to
    compare it -- must not list twelve of them on a clean desk."""
    findings = []
    talk = talkback_strip(state)
    for base in strip_bases(state) + [f"/bus/{i}" for i in bus_indices(state)]:
        if base == talk:
            continue  # the talk mic, fader down on purpose (T002)
        if base in planned_floor:
            continue  # the plan put it there
        if state.mute(base):
            continue  # already silent on purpose; not this rule's concern
        fdr = state.fader_db(base)
        if fdr is None or fdr > FADER_FLOOR_DB:
            continue
        if is_in_use(state, base):
            findings.append(Diagnostic.audit(
                "L002", Severity.INFO, "levels", "Active Strip Fader At Floor",
                f"{strip_label(state, base)} is unmuted and in use, but its own fader is at "
                f"{FADER_FLOOR_DB:g}dB.",
                (f"{base}/fdr",),
            ))
    return findings


def _seconds(value: float) -> str:
    """`1.2 s`, `48 s`: the clip finding's times."""
    return f"{value:.1f} s" if value < 10 else f"{value:.0f} s"


def _rule_clipped(state: ConsoleState) -> list[Finding]:
    """L003: a strip clipped within the last minute.

    Product decision, 2026-10-13: *"throw up an ERROR that lasts for about a minute
    if any channel or bus clips ... Reset the one minute timer if the
    channel or bus clips again."* Distortion is not a matter of taste; it
    is the setting that cannot work. The clips come from the console's
    meter stream (`atoo.metering`), which a live watch reads beside its
    passes; the rule only words what the clip monitor reports, and is
    silent on any state that carries none -- `audit` and every captured
    state. One finding per strip: both sides of a stereo strip, and all
    four of its level words, are one.

    The finding's key is its rule and strip, so a second clip inside the
    minute is the same finding with the timer moved on, and the sentence
    says where the timer stands: that is how the restart is seen."""
    findings = []
    for clip in state.clips:
        label = strip_label(state, clip.base)
        said = f"{label} clipped"
        if clip.count > 1:
            said += f" {clip.count} times"
            if clip.longest is not None:
                said += f", the longest for about {_seconds(clip.longest)}"
        elif clip.longest is not None:
            said += f" for about {_seconds(clip.longest)}"
        findings.append(Diagnostic.audit(
            "L003", Severity.ERROR, "levels", "Clipped",
            f"{said}; the last was {_seconds(clip.ago)} ago. This clears in "
            f"{_seconds(max(clip.remaining, 0.0))} unless it clips again.",
            (f"{clip.base}/clip",),
        ))
    return findings


# **The audit-rule catalogue is the specification for this list,
# and this list follows it** -- id, severity, scope and title are pinned
# together by the catalogue test, so a row edited in the catalogue and
# not here is a failing test rather than a quiet disagreement. The
# one-line rationale for each scope sits next to it here as well, because
# the next person to add a rule reads this list.
#
# `scope` itself is under review: it may not be the right
# solution to the problem of seeing unhelpful errors. The alternative is a predicate precise enough
# that it does not fire on a console nobody has touched -- R001 below
# is the worked example.
DEFAULT_RULES: list[AuditRule] = [
    # NOT a convention, though it was until 2026-09-23: on an
    # initialized console the busses are not named, so we should indeed
    # be checking that any bus with a name has inputs, and not
    # suppress this. The predicate is "in use" now rather than "named",
    # which is wider and still keeps it off a factory desk.
    AuditRule("R001", Severity.WARNING, "routing", "Bus No Inputs",
              "An in-use bus receives no channel/aux sends.", _rule_bus_no_inputs,
              scope=RuleScope.HAZARD),
    AuditRule("R002", Severity.WARNING, "routing", "Bus No Output",
              "An in-use bus has no route to a physical output, direct or indirect.", _rule_bus_no_output,
              scope=RuleScope.CONVENTION),
    # A matrix feeding a physical output with nothing in it is wrong on
    # any desk; so is a mix with nowhere to go, and an output with no
    # source is dead air at the venue.
    AuditRule("R003", Severity.WARNING, "routing", "Matrix Orphan",
              "A Matrix is patched to a physical output but nothing sends to it.", _rule_matrix_orphan,
              scope=RuleScope.HAZARD),
    AuditRule("R004", Severity.WARNING, "routing", "Main Patched But Unfed",
              "A Main is patched to a physical output but nothing sends to it.", _rule_main_unfed,
              scope=RuleScope.HAZARD),
    AuditRule("R005", Severity.ERROR, "routing", "Main Not Patched",
              "A Main has active sends feeding it but reaches no physical output.", _rule_main_unpatched,
              scope=RuleScope.HAZARD),
    # R003's mirror image, and the Matrix counterpart of
    # R005 -- but a WARNING, because the case that would stop the show
    # (a Matrix carrying the PA) is already R005's or R002's ERROR
    # on whatever feeds it. See `_rule_matrix_unpatched`.
    AuditRule("R006", Severity.WARNING, "routing", "Matrix Fed But Not Patched",
              "A Matrix has an active send feeding it but is patched to no physical output.",
              _rule_matrix_unpatched, scope=RuleScope.HAZARD),
    # R002/R005/R006 stand down when an AES50 port in use
    # was not read, and this says what they could not check. A hazard
    # rule, as theirs are: it is about the reading, not about the plan.
    AuditRule("R007", Severity.INFO, "routing", "Output Route Not Checked",
              "A bus, Main or Matrix reaches none of the output sockets read, and an AES50 "
              "port in use was not read, so the route could not be checked.",
              _rule_route_unchecked, scope=RuleScope.HAZARD),
    # The start of the path: R002, R005 and R006 name the object whose
    # signal reaches no output, and this names the strip whose own switches
    # send it nowhere. A hazard, as they are; under a plan it stands down
    # for a strip whose planned routes CV016 judges, the way the "plan
    # states the parameter" half of the scope works.
    AuditRule("R008", Severity.WARNING, "routing", "Strip Reaches Nothing",
              "A channel or aux that is in use, unmuted and up has no bus send, Matrix send or "
              "Main route switched on.",
              _rule_strip_reaches_nothing, scope=RuleScope.HAZARD, judges=("routes",)),
    # A loop does not care whose strip it is, and no plan states one. Two ids
    # because the catalogue gives a rule one severity, and because Watch
    # should say a loop opened: the WARNING clears and the ERROR appears.
    AuditRule("R009", Severity.ERROR, "routing", "Feedback Loop",
              "A channel or aux takes a bus, Main or Matrix as its input and its signal comes "
              "back round to it, every leg open.",
              _rule_feedback_loop, scope=RuleScope.HAZARD),
    AuditRule("R010", Severity.WARNING, "routing", "Feedback Loop Held Closed",
              "The same loop with a leg switched off or at the floor: silent today, feeding "
              "back the moment it is opened.",
              _rule_feedback_loop_held_closed, scope=RuleScope.HAZARD),
    # A one-sided mix is worth a warning, and the finding says how to dismiss
    # it when the mono feed is meant. A hazard-scope rule that cites the
    # output sockets it judged, so a plan that declares them stands it down.
    AuditRule("R011", Severity.WARNING, "routing", "Stereo Output Patched On One Side",
              "A stereo bus, Main or Matrix in use whose output patches all use the same side of "
              "its pair, so anything panned to the other side is not heard.",
              _rule_stereo_one_side, scope=RuleScope.HAZARD),
    # 48V does not care whose strip it is -- the issue's own example of
    # why this is not simply "filter by plan membership".
    AuditRule("C001", Severity.WARNING, "configuration", "Phantom Power On Unpatched Socket",
              "48V is enabled on a physical input patched to no channel or user patch.",
              _rule_phantom_unpatched, scope=RuleScope.HAZARD),
    # Deliberate often enough that it is INFO already. `judges` because
    # the finding cites the strips, but what it actually judged is where
    # each of them is patched -- and a plan that states both patches asked
    # for the sharing (the monitor-split case desk run A6 applied,
    # 2026-09-21), with CV005 checking each one against the plan.
    AuditRule("C002", Severity.INFO, "configuration", "Shared Physical Input",
              "More than one channel or aux sources from the same physical input socket.",
              _rule_shared_input, scope=RuleScope.CONVENTION, judges=("in/conn",)),
    # A hazard: a silent channel does not care whose it is. `judges`
    # names a key no plan ever states, because the one parameter a plan
    # could state here -- the patch (`in/conn`, as C002 judges it) --
    # is exactly what CV005 would call correct. The plan asking for
    # MOD 1 does not put a module in the bay. Left to default, the key
    # would be `in/conn/grp`, which no plan states today either; the
    # explicit key is so it cannot start to.
    AuditRule("C003", Severity.ERROR, "configuration", "Patch Uses An Empty Expansion Bay",
              "A channel is patched from, or an output routed to, an expansion bay the desk reports empty.",
              _rule_patched_from_empty_bay, scope=RuleScope.HAZARD, judges=("expansion-bay",)),
    # A hazard for the same reason C003 is: a channel that does not hear
    # the stage does not care whose it is. No plan states which of the two
    # patches is live, so nothing stands it down.
    AuditRule("C004", Severity.WARNING, "configuration", "Channel On Its Alternate Input",
              "A channel or aux is switched to its alternate input patch rather than its main one.",
              _rule_on_alternate_input, scope=RuleScope.HAZARD),
    # The desk-wide half of C004: one switch, one finding. A hazard
    # for the same reason, and no plan states it.
    AuditRule("C005", Severity.WARNING, "configuration", "Global Alternate Switch Engaged",
              "The console's global alternate-input switch is engaged.",
              _rule_global_alternate_switch, scope=RuleScope.HAZARD),
    # The other end of R008's path: a strip in use that nothing is patched to.
    # A hazard for the same reason. `judges` is the strip's patch, which a
    # plan that states it asked for and CV005 compares against the desk.
    AuditRule("C006", Severity.WARNING, "configuration", "Strip In Use Has No Source",
              "A channel or aux that is in use has nothing patched to its main input.",
              _rule_strip_has_no_source, scope=RuleScope.HAZARD, judges=("in/conn",)),
    # The socket's own mute, which the strip does not show: a hazard, as a
    # silent channel does not care whose it is, and no plan states it.
    AuditRule("C007", Severity.WARNING, "configuration", "Strip's Input Socket Muted",
              "A channel or aux in use is patched to an input socket that is muted at the "
              "socket, or to one leg of a stereo source whose other leg is not.",
              _rule_input_socket_muted, scope=RuleScope.HAZARD),
    # The AES50 link, which the read takes for every port and which nothing
    # used. Hazards: a stage box that passes no audio does not care whose
    # show it is, and no plan states a link's health.
    AuditRule("C008", Severity.ERROR, "configuration", "AES50 Port Cannot Carry Its Patch",
              "A strip takes its input from an AES50 port, or an output on it carries a source, "
              "while the port reads '-' or ERR.",
              _rule_aes50_cannot_carry_patch, scope=RuleScope.HAZARD),
    AuditRule("C009", Severity.WARNING, "configuration", "AES50 Stage Box Link Not OK",
              "A stage box reads UPD, or ERR with nothing patched to it.",
              _rule_aes50_link_not_ok, scope=RuleScope.HAZARD),
    # Hazards, because a lit insert doing nothing and a loaded
    # effect nobody hears do not care whose strip it is. No plan states an
    # insert, so nothing stands either down.
    AuditRule("E001", Severity.WARNING, "effects", "Insert On An Empty FX Slot",
              "A strip's insert is switched on but names an FX slot with no effect loaded.",
              _rule_insert_on_empty_slot, scope=RuleScope.HAZARD),
    AuditRule("E002", Severity.INFO, "effects", "FX Loaded But Not Inserted",
              "An FX slot has an effect loaded that no strip's insert names.",
              _rule_fx_not_inserted, scope=RuleScope.HAZARD),
    # Bypassing an effect is a mixing decision; about a strip the show
    # never mentions it is somebody else's.
    AuditRule("E003", Severity.INFO, "effects", "FX Inserted But Switched Off",
              "A strip's insert names a loaded FX slot but is switched off.",
              _rule_insert_switched_off, scope=RuleScope.CONVENTION),
    # The comms half. A hazard: talkback that reaches nobody does
    # not care whose show it is, and no plan states talkback.
    AuditRule("T001", Severity.WARNING, "communications", "Talkback Goes Nowhere",
              "Talkback is assigned to a strip, but neither TALK A nor TALK B is routed "
              "to any bus, Matrix or Main.",
              _rule_talkback_goes_nowhere, scope=RuleScope.HAZARD),
    # Not a fault: the one line saying CH001 and L002 skipped the
    # talk mic's strip, so the exemption is never silent.
    AuditRule("T002", Severity.INFO, "communications", "Talkback Strip Left Out Of Mix Checks",
              "The strip talkback is assigned to is in use; CH001, L002, R008, C006 and C007 skip it.",
              _rule_talkback_strip_exempt, scope=RuleScope.HAZARD),
    # The finding that prompted an earlier change: 29 of the A5 run's 30 INFO
    # findings were this rule on strips the show never mentions.
    AuditRule("CH001", Severity.INFO, "channels", "Channel Not In Any DCA",
              "An in-use channel/aux belongs to no DCA group.", _rule_channel_no_dca,
              scope=RuleScope.CONVENTION, judges=("tags#D",)),
    # Something active is being silenced and nobody meant it. The
    # threshold is DCA_LOW_FADER_DB, not the floor: a DCA 20dB down is
    # already inaudible and its members still look normal.
    AuditRule("CH002", Severity.WARNING, "channels", "DCA Fader Low With Active Members",
              "A DCA's fader is low while it controls active members.", _rule_dca_low_with_members,
              scope=RuleScope.HAZARD),
    AuditRule("CH003", Severity.INFO, "channels", "Mute Group Active, Silencing Routed Members",
              "An engaged mute group is silencing active members.", _rule_mute_group_silencing,
              scope=RuleScope.HAZARD),
    # CH003's twin for a DCA's mute switch, which CH002 (the fader) does not
    # read and CV017 reads only against a plan. A hazard, as CH003 is: a DCA
    # silencing the band does not care whose band it is.
    AuditRule("CH004", Severity.INFO, "channels", "DCA Muted, Silencing Active Members",
              "A DCA's mute is on while it controls active members.", _rule_dca_muted_with_members,
              scope=RuleScope.HAZARD),
    # A duplicate name is about a pair, not a strip -- see RuleScope.
    AuditRule("N001", Severity.WARNING, "naming", "Duplicate Channel/Aux Names",
              "More than one channel/aux shares the same non-default name.", _rule_duplicate_channel_names,
              scope=RuleScope.PAIRWISE),
    AuditRule("N002", Severity.WARNING, "naming", "Duplicate Bus Names",
              "More than one bus shares the same non-default name.", _rule_duplicate_bus_names,
              scope=RuleScope.PAIRWISE),
    # A forgotten send on a strip you did not plan is their business. On
    # one you did, the send level is stated and CV006 owns it.
    AuditRule("L001", Severity.WARNING, "levels", "Send On But Near-Silent",
              "Any send is enabled but pulled to within 44dB of the floor without being fully off.",
              _rule_dead_send, scope=RuleScope.CONVENTION),
    # **A hazard, and the one row where that is worth spelling out.** A
    # routed, unmuted, silent strip is the classic why-can't-I-hear-it,
    # and on a strip that is NOT part of your show it is the single most
    # useful thing this rule ever says -- withholding it is the failure
    # direction that hides something real.
    #
    # This rule fired 48 times in the A5 run. Nineteen were planned
    # channels whose faders the plan itself put on the floor (conventions
    # say "leave all faders all the way down", the plan states fader_db:
    # -144, apply wrote it and read it back) -- those go because CV002
    # owns that comparison and does it against what was asked for, i.e.
    # mechanism 2, which applies whatever a rule's scope is. The other
    # twenty-nine were `/ch/21`-`/ch/40` and `/aux/1`-`/aux/8` with no
    # name and no patch, "actively routed" only because WING ships with
    # `main/1/on = 1`, and those go too -- not by hiding them, but
    # because `is_in_use` no longer calls a factory default a route.
    AuditRule("L002", Severity.INFO, "levels", "Active Strip Fader At Floor",
              "An unmuted, in-use channel, aux or bus's own fader sits at the floor.",
              _rule_fader_floor_while_active, scope=RuleScope.HAZARD),
    # The one rule whose evidence is not an address: the console's meter
    # stream. A hazard about any strip, planned or not -- a
    # clipped unplanned channel is distorting the PA all the same.
    AuditRule("L003", Severity.ERROR, "levels", "Clipped",
              "A channel, aux, bus, main or matrix clipped within the last minute "
              "(a live watch only; it reads the console's meters).",
              _rule_clipped, scope=RuleScope.HAZARD),
]


# --------------------------------------------------------------------------
# Plan scope: two independent mechanisms that decide what a
# structural rule still has to say once a plan is in hand. Neither one
# changes anything when no plan is supplied -- everything is in scope,
# because there is nothing to be outside of.
#
# **1. Is this object the plan's business?** A finding about a strip the
# plan never mentions is a different claim from a finding about one it
# does, and `RuleScope` records per rule which of those claims the rule is
# entitled to make.
#
# **2. Does the plan STATE the parameter the rule is complaining about?**
# The more valuable half, and not plan membership at all. From the A5 run
# (the A5 audit-rules run of 2026-09-21): L002
# fired on nineteen planned channels *because the plan asked for it* --
# the house conventions say "leave all faders all the way down", the
# plan states `fader_db: -144`, apply wrote it and read it back, and the
# audit then called each one a fault. Those strips are IN the plan, so
# mechanism 1 suppresses none of them. Stated generally:
#
#   > When a plan is supplied, a structural rule is silent about any
#   > parameter the plan states, because a conventions-diff rule (CV*)
#   > already checks that parameter against what was asked for.
#
# The "because" is load-bearing, and it is what `plan_stated_parameters()`
# is built to preserve: it reports exactly the (object, parameter) pairs
# `diff_against_plan()` actually compares, no more. A plan states a bus's
# fader too, but nothing diffs bus faders yet -- so L002 on a bus does
# NOT stand down, because standing it down would mean nobody checks that
# fader at all. When `diff_against_plan` grows a check, this function
# grows the matching key with it, and the two stay honest together.
# --------------------------------------------------------------------------


# The console object an address belongs to: the strip/bus/main/matrix/
# DCA/mute-group it hangs off, or the physical socket. `/ch/1/send/3/lvl`
# is about `/ch/1`; `/io/in/A/1/vph` is about that socket. Anchored, so
# `/main/1` can never swallow `/main/10`.
_SUBJECT_RES = (
    re.compile(r"^(/(?:ch|aux|bus|main|mtx|dca|mgrp)/\d+)"),
    re.compile(r"^(/io/(?:in|out)/[A-Za-z0-9]+/\d+)"),
)


def finding_subjects(finding: Finding) -> tuple[str, ...]:
    """Which console objects a finding is about, recovered from the
    `addresses` it already carries rather than by re-parsing
    its prose or touching fourteen rule bodies. Order-preserving and
    de-duplicated; empty for a finding that cites no address, which is
    treated as "in scope" everywhere below."""
    subjects: list[str] = []
    for address in finding.addresses:
        for rx in _SUBJECT_RES:
            m = rx.match(address)
            if m:
                if m.group(1) not in subjects:
                    subjects.append(m.group(1))
                break
    return tuple(subjects)


@dataclass(frozen=True)
class PlanScope:
    """What a compiled plan claims, in the vocabulary a finding speaks.

    `objects` -- every console object the plan names: its channels, its
    busses/DCAs/mute-groups (by the index the plan itself declares, and by
    live-name resolution, whichever resolves -- the union, so an ambiguity
    keeps a finding rather than hiding it), its Mains and Matrices, the
    input sockets it patches and the output sockets it declares.

    `stated` -- object -> the parameter keys the plan states a value for,
    spelled as address suffixes (`"fdr"`, `"send/3/lvl"`, `"in/set/trim"`)
    plus two that are finer than an address because a plan can state one
    without the other: `"tags#D"` (DCA membership) and `"tags#M"`
    (mute-group membership) both live at `{base}/tags`.
    """

    objects: frozenset[str] = frozenset()
    stated: dict[str, frozenset[str]] = field(default_factory=dict)

    def claims(self, subject: str) -> bool:
        return subject in self.objects

    def states(self, subject: str, key: str) -> bool:
        return key in self.stated.get(subject, frozenset())


def _plan_group_indices(state: ConsoleState, entries: dict, live_indices: list[int], base_fmt: str) -> set[int]:
    """Indices for a plan's named busses/DCAs/mute-groups: the `index` the
    plan declares, plus whatever that name resolves to on the live desk.
    The union rather than either alone -- a plan that says bus 5 and a
    desk whose bus 5 is named something else are both "claimed", and the
    conservative direction here is to claim more, not less."""
    found: set[int] = set()
    for name, entry in (entries or {}).items():
        idx = (entry or {}).get("index") if isinstance(entry, dict) else None
        if isinstance(idx, int):
            found.add(idx)
        live = _resolve_single_index_by_name(state, name, live_indices, base_fmt)
        if live is not None:
            found.add(live)
    return found


def plan_scope(state: ConsoleState, plan: dict) -> PlanScope:
    """Everything `apply_plan_scope` needs to know about a plan: which
    objects it claims, and which parameters it states for each.

    Malformed entries are skipped rather than raised, the same discipline
    `_declared_output_patches` follows -- a read-only question about what
    a plan claims is not a place to crash over a shape it does not need.
    """
    objects: set[str] = set()
    stated: dict[str, set[str]] = {}

    def state_param(subject: str, key: str) -> None:
        stated.setdefault(subject, set()).add(key)

    for entry in plan.get("channels", []) or []:
        if not isinstance(entry, dict) or "bank" not in entry or "channel" not in entry:
            continue
        base = f"/{entry['bank']}/{entry['channel']}"
        objects.add(base)

        # Each block below mirrors one CV* check in
        # `diff_against_plan`, and states a key only under exactly the
        # condition that check uses to decide it has something to compare.
        fader = entry.get("fader") or {}
        if fader.get("muted") is not None:
            state_param(base, "mute")                       # CV001
        if fader.get("fader_db") is not None:
            state_param(base, "fdr")                        # CV002
        if entry.get("dca"):
            state_param(base, "tags#D")                     # CV003
        if entry.get("mute_group"):
            state_param(base, "tags#M")                     # CV004

        patch = entry.get("patch") or {}
        sockets = patch.get("sockets") or []
        if patch.get("group") and sockets:
            state_param(base, "in/conn")                    # CV005
            for sock in sockets:
                if isinstance(sock, int):
                    objects.add(f"/io/in/{patch['group']}/{sock}")

        for send in entry.get("bus_sends", []) or []:        # CV006
            if not isinstance(send, dict):
                continue
            bus_name = send.get("bus")
            if not bus_name:
                continue
            bidx = _resolve_single_index_by_name(state, bus_name, bus_indices(state), "/bus/{}")
            if bidx is None:
                continue  # unresolved: diff_against_plan skips it, so nothing is stated
            state_param(base, f"send/{bidx}/on")
            if send.get("level_db") is not None:
                state_param(base, f"send/{bidx}/lvl")
            if _SEND_MODE_TO_WING.get(send.get("mode")) is not None:
                state_param(base, f"send/{bidx}/mode")

        # CV016 judges every strip the plan routes somewhere, so R008
        # stands down for it: the plan, not the structural rule, says
        # whether that strip's routes are right.
        if planned_routes(plan, entry):
            state_param(base, "routes")

        # CV007. Every Main, not only the listed ones: the list is the
        # complete statement of a strip's direct Main routing, and apply
        # writes each Main it leaves out as OFF (2026-09-27).
        for main_index in console_facts.main_indices():
            state_param(base, f"main/{main_index}/on")

        processing = entry.get("processing") or {}           # CV008
        for plan_field, suffix in (("trim_db", "in/set/trim"),
                                   ("balance_db", "in/set/bal"),
                                   ("invert", "in/set/inv")):
            if processing.get(plan_field) is not None:
                state_param(base, suffix)
        for target in planned_processing_leaves(entry):         # CV008, filters and EQ
            state_param(base, target.address[len(base) + 1:])
        if processing.get("gain_db") is not None:
            live_patch = state.patch(base)
            if live_patch is not None and live_patch[0] in _VPH_CAPABLE_GROUPS:
                state_param(f"/io/in/{live_patch[0]}/{live_patch[1]}", "g")

    # CV019 compares 48V on the socket each strip is patched to, so C001
    # stands down there rather than say it twice.
    for _base, group, socket, _wanted in phantom_judgements(state, plan):
        state_param(f"/io/in/{group}/{socket}", "vph")
    for idx in _plan_group_indices(state, plan.get("busses") or {}, bus_indices(state), "/bus/{}"):
        objects.add(f"/bus/{idx}")
    for idx in _plan_group_indices(state, plan.get("dcas") or {}, dca_indices(state), "/dca/{}"):
        objects.add(f"/dca/{idx}")

    # An earlier change, and it is only honest because steps 1 and 2 are
    # done: `_diff_group_faders` now compares these, so a structural rule
    # may go quiet about them. Until it did, standing L002 down on a
    # stated bus fader (or CH002 on a stated DCA fader) would have
    # meant nobody checked that fader at all.
    for plan_key, base_fmt in (("busses", "/bus/{}"), ("dcas", "/dca/{}")):
        for entry in (plan.get(plan_key) or {}).values():
            if not isinstance(entry, dict) or not isinstance(entry.get("index"), int):
                continue
            fader = entry.get("fader")
            if not isinstance(fader, dict):
                continue
            base = base_fmt.format(entry["index"])
            if fader.get("muted") is not None:
                state_param(base, "mute")               # CV010 / CV012
            if fader.get("fader_db") is not None:
                state_param(base, "fdr")                # CV011 / CV013
    # CV015 compares a planned FX bus's insert and engine,
    # so E001/E003 stand down there rather than say it twice.
    for _name, index, point, engine, _model in planned_fx_inserts(plan):
        state_param(f"/bus/{index}", f"{point}/on")
        state_param(f"/bus/{index}", f"{point}/ins")
        state_param(f"/fx/{engine}", "mdl")
    # CH004 reports a muted DCA, and CV017 (or the planned mute itself)
    # already says what the plan wants of every DCA it declares.
    for dca in planned_dca_mutes(plan):
        state_param(dca, "mute")
    for idx in _plan_group_indices(state, plan.get("mute_groups") or {}, mute_group_indices(state), "/mgrp/{}"):
        objects.add(f"/mgrp/{idx}")

    for out in (plan.get("outputs") or {}).values():
        if not isinstance(out, dict):
            continue
        idx = out.get("index")
        kind = {"main": "/main", "matrix": "/mtx", "bus": "/bus"}.get(out.get("kind"))
        if kind and isinstance(idx, int):
            objects.add(f"{kind}/{idx}")
        fed_by = out.get("fed_by") or {}
        fed_kind = {"main": "/main", "matrix": "/mtx", "bus": "/bus"}.get(fed_by.get("type"))
        if fed_kind and isinstance(fed_by.get("index"), int):
            objects.add(f"{fed_kind}/{fed_by['index']}")

    # CV009's own set, shared with `apply --clean-output-sockets` so
    # "what does this plan claim about /io/out/*" is computed in one place.
    for group, socket in _declared_output_patches(plan):
        subject = f"/io/out/{group}/{socket}"
        objects.add(subject)
        state_param(subject, "grp")
        state_param(subject, "in")

    return PlanScope(
        objects=frozenset(objects),
        stated={k: frozenset(v) for k, v in stated.items()},
    )


@dataclass(frozen=True)
class WithheldFinding:
    """A finding the plan put out of scope, and which of the two
    mechanisms did it. Kept, never dropped -- the caller decides whether
    to count it, show it behind a flag, or hand it to a dirty-board diff."""

    finding: Finding
    reason: str


@dataclass
class ScopedAudit:
    findings: list[Finding]
    withheld: list[WithheldFinding]

    def summary(self) -> Finding | None:
        """One finding that says what is not being shown, or None when
        nothing was withheld.

        Suppression must never be silent: a shorter list that
        cannot be told apart from a healthy desk is worse than a long one.
        This is shaped as a `Finding` rather than a line printed by one
        renderer so that every consumer of an audit -- the CLI, the Setup
        UI, a JSON dump -- shows it without being taught to."""
        if not self.withheld:
            return None
        by_rule: dict[str, dict[str, int]] = {}
        for item in self.withheld:
            reasons = by_rule.setdefault(item.finding.rule_id, {})
            reasons[item.reason] = reasons.get(item.reason, 0) + 1
        parts = []
        for rule_id in sorted(by_rule):
            reasons = by_rule[rule_id]
            why = ", ".join(f"{n} {reason}" for reason, n in sorted(reasons.items()))
            parts.append(f"{sum(reasons.values())} {rule_id} ({why})")
        return Diagnostic.audit(
            SCOPE_SUMMARY_RULE_ID, Severity.INFO, "scope", "Findings Withheld From This Report",
            f"{len(self.withheld)} finding(s) are not listed above because a plan was supplied: "
            + "; ".join(parts)
            + ". Re-run the same audit with no plan to see every finding the rules produced.",
        )


def _judged_keys(finding: Finding, rule: AuditRule | None) -> dict[str, set[str]]:
    """Which parameter each of a finding's subjects was judged on.

    Read off the finding's own addresses unless the rule overrides it --
    an address that IS the subject (`/ch/1`, cited by R003 and friends)
    yields the empty key, which no plan ever states, so such a finding
    never stands down by accident."""
    subjects = finding_subjects(finding)
    if rule is not None and rule.judges:
        return {subject: set(rule.judges) for subject in subjects}
    keys: dict[str, set[str]] = {subject: set() for subject in subjects}
    for address in finding.addresses:
        for subject in subjects:
            if address == subject:
                keys[subject].add("")
            elif address.startswith(subject + "/"):
                keys[subject].add(address[len(subject) + 1:])
    return keys


def apply_plan_scope(
    state: ConsoleState,
    findings: list[Finding],
    plan: dict,
    rules: list[AuditRule] | None = None,
) -> ScopedAudit:
    """Split `findings` into what a plan-carrying report should say and
    what it should only count.

    A finding whose `rule_id` is not in `rules` is always kept -- that
    covers the conventions-diff findings (CV*, already plan-scoped by
    construction: they exist only because the plan spoke), watch-condition
    rules, and any caller's own rule that predates `scope`.
    """
    by_id = {rule.id: rule for rule in (rules if rules is not None else DEFAULT_RULES)}
    scope = plan_scope(state, plan)

    kept: list[Finding] = []
    withheld: list[WithheldFinding] = []
    for finding in findings:
        rule = by_id.get(finding.rule_id)
        subjects = finding_subjects(finding)
        if rule is None or not subjects:
            kept.append(finding)
            continue

        # Mechanism 2 first, and for every scope: a hazard rule has no
        # more business second-guessing a parameter the plan states than a
        # convention rule does. A finding stands down only when EVERY
        # parameter it judged, on EVERY object it names, is one the plan
        # states -- so a collision between a planned strip and an
        # unplanned one is still reported.
        judged = _judged_keys(finding, rule)
        if all(keys and all(scope.states(subject, key) for key in keys)
               for subject, keys in judged.items()):
            withheld.append(WithheldFinding(finding, WITHHELD_PLAN_STATES))
            continue

        # Mechanism 1. Hazards are about the whole desk by definition;
        # convention and pairwise rules speak only where the plan does.
        # Both need one participant in the plan, for the reason
        # `RuleScope` gives: "one of yours and one of theirs" is the
        # collision that bites.
        if rule.scope is not RuleScope.HAZARD and not any(scope.claims(s) for s in subjects):
            withheld.append(WithheldFinding(finding, WITHHELD_OUTSIDE_PLAN))
            continue

        kept.append(finding)

    return ScopedAudit(findings=kept, withheld=withheld)


# --------------------------------------------------------------------------
# Conventions diff (FR-4.1, an earlier change first slice + the extension):
# compare live state against what the compiled PLAN says a channel should
# be -- distinct from the structural rules above, which never look at a
# plan at all. Eight plan-channel fields covered here, each of which
# already has a direct live-state counterpart and an existing accessor
# above: mute, fader level, DCA membership, mute-group membership, patch,
# plus bus sends, direct-to-Main routes, and processing: trim, balance,
# invert, head-amp gain, and the filters and EQ.
# Still NOT covered: the compressor (no plan schema), a bus's EQ and a
# channel's PreSend EQ. Left for a follow-up rather than guessed at.
#
# Same rule as cli.py's expectations-check output ("Only fields the plan
# actually states are compared -- a null fader is not an assertion about
# where the fader should be"): a null/missing/empty plan field produces no
# finding at all here either -- not a "matches trivially" finding and not
# a "missing" warning. Same for a plan channel whose live `base` was never
# read into `state` at all, and for a DCA/mute-group/bus name that doesn't
# resolve to exactly one live index -- skip silently, don't crash, and
# don't invent a finding about the name mismatch itself (that's a
# different, not-yet-built check).
# --------------------------------------------------------------------------

# WING's fader is a 1024-step quantized control over -oo..10dB
# (the Compact parameter map's `/ch/{n}.fdr`), not
# a continuous value -- a plan's `fader_db` and a live readback can differ
# by a fraction of a dB from quantization/rounding alone even when they
# mean the same setting. 0.5dB is comfortably wider than that per-step
# gap across the range shows actually sit in, so this catches a real
# contradiction (a fader left at unity when the plan calls for -6dB)
# without flagging harmless rounding noise. Chosen, not derived --
# revisit if a real console proves it too loose or too tight.
FADER_TOLERANCE_DB = 0.5

# A channel's send to a bus (`{base}/send/{n}/lvl`) is confirmed in
# the Compact parameter map as the exact same
# "fader" type, 1024-step, -oo..10dB parameter as the strip's own fader
# (`{base}/fdr`) -- so FADER_TOLERANCE_DB's reasoning, and value, applies
# unchanged; no separate constant for it. Channel trim (`{base}/in/set/
# trim`, "lin", 361 steps over -18..+18dB => ~0.1dB/step) and balance
# (`{base}/in/set/bal`, "lin", 181 steps over -9..+9dB => ~0.1dB/step) are
# both finer-grained than the fader's own range, so FADER_TOLERANCE_DB is
# comfortably wider than either's per-step gap too -- reused directly for
# both rather than adding two more constants with the same value.

# Head-amp gain (`/io/in/{group}/{socket}/g`) is a much coarser control
# than any of the above -- confirmed in the parameter map as "lin" with as
# few as 20 steps over a ~47.5dB range on LCL (~2.4dB/step, the analog
# preamp's own physical detents), versus 98 steps over ~48.5dB on A/B/C
# (~0.5dB/step). Reusing FADER_TOLERANCE_DB here would false-positive on
# every LCL-patched channel from quantization alone, so this gets its own,
# wider tolerance -- sized to LCL's coarsest confirmed step (the worst
# case across every VPH-capable group) plus margin. Chosen, not derived
# from a real console reading -- revisit if hardware proves it wrong.
HEAD_AMP_GAIN_TOLERANCE_DB = 3.0


def planned_processing_leaves(entry: dict) -> list:
    """The filter and EQ leaves a plan channel states, as the write targets
    `apply` builds from the same fields (`address`, `value_type`,
    `compute_value`): the high-pass, hi-cut and tilt (each with its on
    switch) and a channel's or aux strip's EQ. Asking `apply` rather than
    reading the plan's fields again is what keeps the leaf names, the
    "a stated value implies the switch is on" rule and the aux strip's
    missing filter node the same on both sides.

    Trim, balance, invert and head-amp gain are not here: they have their
    own tolerances above."""
    bank = entry.get("bank", "ch")
    if bank not in ("ch", "aux") or not isinstance(entry.get("channel"), int):
        return []
    base = f"/{bank}/{entry['channel']}"
    targets = _channel_processing_targets({"name": "", **entry}, bank, base, [])
    return [t for t in targets if t.address.startswith((f"{base}/flt/", f"{base}/eq/"))]


def plan_processing_read_addresses(plan: dict | None) -> list[tuple[str, str]]:
    """Every filter and EQ leaf the plan states, with the type each is read
    as -- what `audit --plan` adds to a read (`console_read_plan(extra=...)`)
    so `diff_against_plan` has something to compare. They sit in the strip's
    own node (`/ch/{n}`, `/aux/{n}`), which a node dump already fetches, so
    this is no extra request; and only the leaves a plan states are asked
    for, so an audit with no plan, or Watch, reads nothing more."""
    found: dict[str, str] = {}
    for entry in (plan or {}).get("channels") or []:
        if isinstance(entry, dict):
            for target in planned_processing_leaves(entry):
                found.setdefault(target.address, target.value_type)
    return list(found.items())


#: The three filters of a channel's `flt` node, each as (name in a finding,
#: on switch, value leaf, unit).
_FILTERS = (("high-pass", "flt/lc", "flt/lcf", "Hz"),
            ("hi-cut", "flt/hc", "flt/hcf", "Hz"),
            ("tilt", "flt/tf", "flt/tilt", "dB"))
_EQ_UNITS = {"f": "Hz", "g": "dB", "q": ""}


def _shown(value: object, unit: str = "") -> str:
    """A leaf's value as a finding quotes it: `100.2Hz`, `on`, `PEQ`."""
    if isinstance(value, str):
        return value
    number = float(value)
    return f"{number:.0f}{unit}" if abs(number) >= 1000 else f"{number:.4g}{unit}"


def _differs(state: ConsoleState, address: str, value_type: str, wanted: object) -> object:
    """The live value at `address` when it is not what the plan wants, by
    `apply`'s own readback comparison (a float within 2% relative or 0.02
    absolute -- the desk holds the nearest step of a `log` control -- and a
    switch or list choice exactly); None when it matches or was not read."""
    live = state.get(address)
    if live is None or _values_equal(value_type, wanted, live, address):
        return None
    return live


def _processing_leaf_findings(state: ConsoleState, entry: dict, base: str, label: str,
                              provenance: dict) -> list[Finding]:
    """CV008 for the high-pass, hi-cut, tilt and EQ the plan states on this
    strip (`planned_processing_leaves`), against the leaves the read took.

    A stated filter implies it is on, as `apply` writes it, so a filter that
    reads off is a finding of its own and its frequency is not then
    compared. The EQ is grouped for the reader: one finding per band naming
    every leaf that differs, and one for the EQ's switch, model and mix.
    A leaf that was not read is not compared."""
    wanted = {t.address: (t.value_type, t.compute_value(None))
              for t in planned_processing_leaves(entry)}
    if not wanted:
        return []
    cite = _cite(provenance, "processing")
    findings: list[Finding] = []

    def finding(message: str, addresses: list[str]) -> None:
        findings.append(Diagnostic.audit(
            "CV008", Severity.WARNING, "conventions", "Processing Contradicts Plan",
            f"{label}: {message}{cite}", tuple(addresses)))

    for name, switch, leaf, unit in _FILTERS:
        value_address = f"{base}/{leaf}"
        if value_address not in wanted:
            continue
        value = wanted[value_address][1]
        switch_address = f"{base}/{switch}"
        live_switch = state.get(switch_address)
        if live_switch is not None and _differs(state, switch_address, "i", 1) is not None:
            finding(f"plan says the {name} is on at {_shown(value, unit)}; live console has it off.",
                    [switch_address])
            continue
        live = _differs(state, value_address, "f", value)
        if live is not None:
            finding(f"plan says the {name} is {_shown(value, unit)}, live console reads "
                    f"{_shown(live, unit)} (tolerance 2%).", [value_address])

    eq_strip = entry.get("bank", "ch")
    for band in console_facts.eq_band_ids(eq_strip):
        freq_leaf, gain_leaf, q_leaf, shape_leaf = eq_band_leaves(band)
        parts: list[str] = []
        addresses: list[str] = []
        for leaf, kind, word in ((freq_leaf, "f", "frequency"), (gain_leaf, "g", "gain"),
                                 (q_leaf, "q", "Q"), (shape_leaf, "shape", "shape")):
            address = f"{base}/eq/{leaf}" if leaf else None
            if address not in wanted:
                continue
            value_type, want = wanted[address]
            live = _differs(state, address, value_type, want)
            if live is not None:
                unit = _EQ_UNITS.get(kind, "")
                parts.append(f"{word} {_shown(want, unit)} but {_shown(live, unit)} live")
                addresses.append(address)
        if parts:
            finding(f"EQ band {band}: plan says {'; '.join(parts)} (tolerance 2%).", addresses)

    parts, addresses = [], []
    for leaf, word, unit in (("on", "EQ", ""), ("mdl", "model", ""), ("mix", "mix", "%")):
        address = f"{base}/eq/{leaf}"
        if address not in wanted:
            continue
        value_type, want = wanted[address]
        live = _differs(state, address, value_type, want)
        if live is not None:
            if leaf == "on":
                parts.append(f"the EQ {'on' if want else 'off'} but it is "
                             f"{'on' if live else 'off'} live")
            else:
                parts.append(f"{word} {_shown(want, unit)} but {_shown(live, unit)} live")
            addresses.append(address)
    if parts:
        finding(f"plan says {'; '.join(parts)}.", addresses)
    return findings


def _cite(provenance: dict | None, field: str) -> str:
    """The plan's own provenance text for `field`, parenthesized -- so a
    finding reads like "this contradicts your Drums convention," per the
    issue's own framing, rather than just "expected X, got Y." Empty
    string when the plan carries no provenance for this field (free-form
    and optional per plan_schema.py), never a placeholder like "(none)"."""
    text = provenance.get(field) if isinstance(provenance, dict) else None
    return f" (plan provenance: {text})" if text else ""


def _resolve_single_index_by_name(
    state: ConsoleState, name: str, indices: list[int], base_fmt: str
) -> int | None:
    """The one live index (of `indices`, addressed via `base_fmt.format(n)`)
    whose `/name` matches `name` case-insensitively -- None if zero or
    more than one match. An ambiguous or unknown plan name is a different,
    not-yet-built check; this function's callers skip it silently."""
    matches = [
        n for n in indices
        if (live_name := state.name(base_fmt.format(n))) is not None
        and live_name.strip().lower() == name.strip().lower()
    ]
    return matches[0] if len(matches) == 1 else None


# The two tag-encoded group memberships a strip can carry, each as
# (which indices exist, how a group of that kind is addressed, which tag
# token marks membership). One table so `diff_against_plan`'s CV003/
# CV004 and `watch_conditions`'s membership fields decide
# membership from the same place instead of two that can drift apart.
_GROUP_KINDS: dict[str, tuple[Callable[[ConsoleState], list[int]], str, re.Pattern]] = {
    "dca": (lambda state: dca_indices(state), "/dca/{}", _DCA_TAG_RE),
    "mute_group": (lambda state: mute_group_indices(state), "/mgrp/{}", _MUTE_GROUP_TAG_RE),
}


def _live_group_indices(state: ConsoleState, base: str, tag_re: re.Pattern) -> set[int]:
    """Every group index of one kind that `base`'s live `/tags` string
    claims membership of -- `"#D1,#M3"` yields `{1}` for the DCA tag."""
    return {
        int(m.group(1))
        for token in state.tags(base).split(",")
        if (m := tag_re.match(token.strip()))
    }


def _is_group_member(
    state: ConsoleState, base: str, name: str, indices: list[int],
    base_fmt: str, tag_re: re.Pattern,
) -> bool | None:
    """Whether `base`'s live tags show it in the group called `name` --
    None when `name` doesn't resolve to exactly one live group, which is
    not evidence either way (see `_resolve_single_index_by_name`)."""
    idx = _resolve_single_index_by_name(state, name, indices, base_fmt)
    if idx is None:
        return None
    return idx in _live_group_indices(state, base, tag_re)


def strip_group_membership(
    state: ConsoleState, base: str, kind: str, name: str
) -> bool | None:
    """Is the strip at `base` a member of the DCA (`kind="dca"`) or mute
    group (`kind="mute_group"`) whose live name is `name`?

    `None` -- not False -- when the answer isn't knowable from this state:
    `name` matches zero live groups of that kind, or more than one
    (ambiguous), the same "a different, not-yet-built check" precedent
    every name resolution in this module follows. A caller must treat
    None as "nothing to say this cycle", never as a violation.

    Membership lives in the strip's own `/tags` string (`"#D1,#M3"`), not
    on the group object, so this reads `base`'s tags and resolves `name`
    to an index to compare against -- the console is index-based where
    the plan and an operator's watch conditions are both name-based."""
    if kind not in _GROUP_KINDS:
        raise ValueError(f"unknown group kind {kind!r} -- expected one of {sorted(_GROUP_KINDS)}")
    indices_of, base_fmt, tag_re = _GROUP_KINDS[kind]
    return _is_group_member(state, base, name, indices_of(state), base_fmt, tag_re)


def _missing_group_memberships(
    state: ConsoleState, base: str, names: list[str], indices: list[int],
    base_fmt: str, tag_re: re.Pattern,
) -> list[str]:
    """Of `names` (a plan channel's `dca` or `mute_group` list), the ones
    that resolve to a real live index but whose tag isn't on `base` --
    i.e. the plan asserts membership the live console doesn't show. A name
    that doesn't resolve to exactly one live index is silently excluded,
    not reported as missing."""
    return [
        name for name in names
        if _is_group_member(state, base, name, indices, base_fmt, tag_re) is False
    ]


# `diff_against_plan` walked `plan["channels"]` and nothing
# else per object, so two things a plan states reached the console through
# `apply` and were then compared against nothing: a BUS's own fader/mute
# (`docs/user/demo/touringband/plan.json` states one for every bus it declares),
# and -- once `plan_schema.DCA_SCHEMA` gained the field -- a DCA's.
#
# Both gaps were load-bearing beyond the missing check itself, because
# the stand-down rests on "a conventions-diff rule already checks this
# parameter". Nothing did, so `L002` could not stand down on a bus
# (`tests/test_audit_scope.py` pinned that, deliberately) and `CH002`
# could not stand down at all. Filling them here is what lets
# `plan_scope()` state the keys, and only then.
#
# **New rule ids rather than reusing CV001/CV002 with a non-channel
# subject** -- the decision the issue left open. A rule id is what a user
# filters a report on and what the catalogue documents a row of, and "a
# DCA is 40dB down from where you asked" is a different thing to go and
# look at from "channel 12's fader is". Reuse would also have meant one
# catalogue row whose "Plan field" cell had to name three different
# objects. The cost is four rows instead of two; `_group_fader_gaps` below
# is why it is not four copies of the same code.


def _group_fader_gaps(state: ConsoleState, plan: dict, plan_key: str, base_fmt: str, noun: str):
    """Yield `(label, cite, base, kind, planned, live)` for every stated
    bus/DCA `fader.muted`/`fader.fader_db` the live desk disagrees with --
    the same comparison CV001/CV002 make for a channel, the same
    "only fields the plan actually states" rule, and the same silent skip
    when the object's live state was never read.

    Split out from the four emit sites below so the comparison is written
    once; those sites stay literal because `tests/test_audit_catalogue.py`
    reads this module's CV ids and titles straight out of the AST, and
    a rule whose id is a variable is a rule the catalogue can no longer be
    checked against.
    """
    for name, entry in (plan.get(plan_key) or {}).items():
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        fader = entry.get("fader")
        if not isinstance(idx, int) or not isinstance(fader, dict):
            continue
        base = base_fmt.format(idx)
        # A plan's `provenance` on a bus/DCA is one free string, not the
        # per-field dict a channel carries -- `_cite` wants the dict
        # shape, so give it one keyed the way it asks.
        provenance = entry.get("provenance")
        cite = _cite({"fader": provenance} if isinstance(provenance, str) else provenance, "fader")
        label = f'{position_label(base)} "{name}"'

        muted = fader.get("muted")
        live_muted = state.mute(base)
        # Only a planned mute found off; the other direction
        # is CV017's.
        if muted is True and live_muted is False:
            yield label, cite, base, "mute", muted, live_muted

        fader_db = fader.get("fader_db")
        live_db = state.fader_db(base)
        if (fader_db is not None and live_db is not None
                and abs(float(fader_db) - live_db) > FADER_TOLERANCE_DB):
            yield label, cite, base, "fdr", float(fader_db), live_db


def _diff_group_faders(state: ConsoleState, plan: dict) -> list[Finding]:
    findings: list[Finding] = []
    for label, cite, base, kind, planned, live in _group_fader_gaps(
            state, plan, "busses", "/bus/{}", "bus"):
        if kind == "mute":
            findings.append(Diagnostic.audit(
                "CV010", Severity.WARNING, "conventions", "Bus Mute Contradicts Plan",
                f"{label}: plan says muted={planned!r}, live console reads muted={live!r}." + cite,
                (f"{base}/mute",),
            ))
        else:
            findings.append(Diagnostic.audit(
                "CV011", Severity.WARNING, "conventions", "Bus Fader Level Contradicts Plan",
                f"{label}: plan says {planned:g}dB, live console reads {live:g}dB "
                f"(tolerance {FADER_TOLERANCE_DB:g}dB)." + cite,
                (f"{base}/fdr",),
            ))
    for label, cite, base, kind, planned, live in _group_fader_gaps(
            state, plan, "dcas", "/dca/{}", "DCA"):
        if kind == "mute":
            findings.append(Diagnostic.audit(
                "CV012", Severity.WARNING, "conventions", "DCA Mute Contradicts Plan",
                f"{label}: plan says muted={planned!r}, live console reads muted={live!r}." + cite,
                (f"{base}/mute",),
            ))
        else:
            findings.append(Diagnostic.audit(
                "CV013", Severity.WARNING, "conventions", "DCA Fader Level Contradicts Plan",
                f"{label}: plan says {planned:g}dB, live console reads {live:g}dB "
                f"(tolerance {FADER_TOLERANCE_DB:g}dB)." + cite,
                (f"{base}/fdr",),
            ))
    return findings


# The plan strip each `/cfg/talk/assign`
# value takes for the talk mic, as a plan channel's (bank, channel).
_TALKBACK_STRIPS = {value: strip for strip, value in console_facts.TALK_ASSIGN_STRIPS.items()}
# A plan entry on that strip whose name reads as talkback IS the talk mic,
# which is where it belongs -- `console_facts.is_talkback_name`, the same
# reading `apply` sets `assign` by, so the two cannot disagree about
# which strip is the talk mic.


def _diff_talkback_strip(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV014: talkback is assigned to CH40 (or AUX8), and the plan puts
    an ordinary input on channel 40 (or aux 8), so the talk mic and a band
    input share one strip.

    A plan comparison rather than a structural rule, because a desk read on
    its own cannot tell a talk mic somebody patched and named on ch 40 from
    a band input; the plan can. Silent when `assign` is OFF or unread, when
    the plan leaves that strip empty, and when the plan's own entry there
    is named as talkback -- that entry is the talk mic, not a clash.
    """
    assign = state.text(console_facts.TALK_ASSIGN)
    strip = _TALKBACK_STRIPS.get(assign)
    if strip is None:
        return []
    findings: list[Finding] = []
    for entry in plan.get("channels", []):
        if (entry.get("bank"), entry.get("channel")) != strip:
            continue
        if console_facts.is_talkback_name(entry.get("name"), (entry.get("source") or {}).get("input")):
            continue
        bank, idx = strip
        findings.append(Diagnostic.audit(
            "CV014", Severity.WARNING, "conventions", "Talkback Strip Holds A Plan Input",
            f"Talkback is assigned to {assign}, and the plan puts {entry.get('name')!r} on "
            f"{bank} {idx}, so the talk mic and that input share one strip. Move the input "
            f"off {bank} {idx}, or set talkback's assign to OFF or the other strip on the "
            f"desk's talkback page.",
            (console_facts.TALK_ASSIGN, f"/{bank}/{idx}/name"),
        ))
    return findings


# --------------------------------------------------------------------------
# CV015: an FX bus's effect, as its bus preset planned it
# --------------------------------------------------------------------------

FX_INSERT_RULE_ID = "CV015"
FX_INSERT_TITLE = "FX Bus Effect Contradicts Plan"


def planned_fx_inserts(plan: dict) -> list[tuple[str, int, str, int, str]]:
    """`(bus name, bus index, insert point, engine, model)` for every effect
    a plan's bus presets load (`busses[X].preset_values.inserts`) that has
    an engine -- what `apply` writes and switches on."""
    out = []
    for name, entry in (plan.get("busses") or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get("index"), int):
            continue
        values = entry.get("preset_values")
        inserts = values.get("inserts") if isinstance(values, dict) else None
        for ins in inserts or []:
            if (isinstance(ins, dict) and isinstance(ins.get("engine"), int)
                    and isinstance(ins.get("model"), str)
                    and ins.get("point") in console_facts.INSERT_POINTS["bus"]):
                out.append((name, entry["index"], ins["point"], ins["engine"], ins["model"]))
    return out


def fx_insert_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV015: an FX bus whose effect is not what its bus
    preset planned -- the insert names another engine (or none), the
    insert is switched off (bypassed: an FX bus with its effect bypassed
    is silent), or the engine holds another model. WARNING.

    Run by `diff_against_plan` (an audit with a plan) and, through
    `fx_insert_rule`, by Watch when the show bundle has a plan: Watch runs
    no other plan diff, and this is the one an operator needs mid-show.
    Silent for whatever was not read."""
    findings = []
    for name, index, point, engine, model in planned_fx_inserts(plan):
        base = f"/bus/{index}"
        live_ins = state.text(f"{base}/{point}/ins")
        live_on = state.flag(f"{base}/{point}/on")
        live_model = state.fx_model(engine)
        word = _INSERT_POINT_NAMES[point]
        problems = []
        named = None
        if live_ins is not None:
            m = re.fullmatch(r"FX(\d+)", live_ins)
            named = int(m.group(1)) if m else None
            if named != engine:
                problems.append(f"its {word} names {live_ins}, not FX{engine}")
        if live_on is False and (live_ins is None or named == engine):
            problems.append(f"its {word} is switched off, so the {model} is bypassed and the "
                            f"bus returns nothing")
        if live_model is not None and live_model != model:
            problems.append(f"FX{engine} holds {live_model}, not {model}")
        if not problems:
            continue
        findings.append(Diagnostic.audit(
            "CV015", Severity.WARNING, "conventions", "FX Bus Effect Contradicts Plan",
            f"{strip_label(state, base)}: the plan loads {model} into FX{engine} and inserts it "
            f"on this bus, switched on (its bus preset); " + "; ".join(problems) + ".",
            (f"{base}/{point}/on", f"{base}/{point}/ins",
             console_facts.FX_MODEL.replace("{n}", str(engine))),
        ))
    return findings


# --------------------------------------------------------------------------
# CV016 and CV017: drift from the plan that Watch notices
# --------------------------------------------------------------------------
#
# Watching a Compact with the sixpiece plan on 2026-10-12: Kick was
# taken out of its two busses, and the Vocals bus muted, and Watch said
# nothing. The structural rules judge what is wrong on ANY desk, and a
# channel sending nowhere or a muted bus is a perfectly good desk state
# between songs; what makes either worth a row is that the plan said
# otherwise. So both are bound to the plan, like CV015, and run by
# `audit --plan`, `atoo watch` and the Watch page when the show has
# one. Both are WARNINGs -- see each function for why not an ERROR.

ROUTE_DRIFT_RULE_ID = "CV016"
ROUTE_DRIFT_TITLE = "Planned Routes All Off"
MUTE_DRIFT_RULE_ID = "CV017"
MUTE_DRIFT_TITLE = "Muted Against Plan"


def _desk_bus_label(state: ConsoleState, index: int, plan_name: str) -> str:
    """A bus as the desk shows it: its name there, else the plan's."""
    return effective_name(state, f"/bus/{index}") or plan_name


def planned_routes(plan: dict, entry: dict) -> list[tuple[str, str, int]]:
    """`(kind, plan name, index)` for every route a plan channel is meant
    to carry signal down: each bus send whose planned level is above the
    floor (or unstated -- apply writes such a send on, at unity), and each
    direct Main route. A send planned AT the floor is a monitor send left
    for the engineer to bring up, which the plan does not expect to carry
    anything yet."""
    busses = plan.get("busses") or {}
    routes: list[tuple[str, str, int]] = []
    for send in entry.get("bus_sends") or []:
        if not isinstance(send, dict):
            continue
        bus = busses.get(send.get("bus"))
        idx = bus.get("index") if isinstance(bus, dict) else None
        level = send.get("level_db")
        if not isinstance(idx, int):
            continue
        if isinstance(level, (int, float)) and level <= FADER_FLOOR_DB:
            continue
        routes.append(("bus", send["bus"], idx))
    for route in entry.get("main_routes") or []:
        idx = route.get("index") if isinstance(route, dict) else None
        if isinstance(idx, int):
            routes.append(("main", f"Main {idx}", idx))
    return routes


def _route_state(state: ConsoleState, base: str, kind: str, idx: int) -> str | None:
    """`"carries"`, `"off"`, `"at the floor"`, or None when unread."""
    if kind == "main":
        on = state.flag(f"{base}/main/{idx}/on")
        if on is None:
            return None
        return "carries" if on else "off"
    on = state.flag(f"{base}/send/{idx}/on")
    if on is None:
        return None
    if not on:
        return "off"
    lvl = state.number(f"{base}/send/{idx}/lvl")
    return "at the floor" if lvl is not None and lvl <= FADER_FLOOR_DB else "carries"


def _other_live_routes(state: ConsoleState, base: str, planned: set[tuple[str, int]]) -> list[str]:
    """Where else, on the desk, this strip's signal still goes: any send
    on and above the floor, any Main route on, that the plan did not
    expect to carry."""
    live = []
    for idx in send_targets(state, base):
        if ("bus", idx) in planned or _route_state(state, base, "bus", idx) != "carries":
            continue
        live.append(effective_name(state, f"/bus/{idx}") or position_label(f"/bus/{idx}"))
    for idx in matrix_send_targets(state, base):
        on = state.flag(f"{base}/send/MX{idx}/on")
        lvl = state.number(f"{base}/send/MX{idx}/lvl")
        if on and (lvl is None or lvl > FADER_FLOOR_DB):
            live.append(position_label(f"/mtx/{idx}"))
    for idx in main_route_targets(state, base):
        if ("main", idx) not in planned and state.flag(f"{base}/main/{idx}/on"):
            live.append(position_label(f"/main/{idx}"))
    return live


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def route_drift_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV016: see `_route_drift`."""
    return [finding for _base, _routes, finding in _route_drift(state, plan)]


def _route_drift(state: ConsoleState, plan: dict) -> list[tuple[str, list, Finding]]:
    """`(base, planned routes, finding)` for each strip CV016 reports.

    CV016: a channel the plan routes somewhere, every
    one of whose planned routes is off or at the floor on the desk.

    *"Kick: the plan sends it to Drums and Drums Comp; neither send is
    on."* Every planned route, not any one: a single send switched off is
    CV006 in a full `audit --plan`, and mid-show a channel moved from
    one bus to another on purpose is the engineer's call. A channel whose
    every planned path is cut has left the mix the plan built, which is
    the thing worth a row at the desk. Monitor sends the plan leaves at
    the floor are not planned paths (`planned_routes`); if the strip still
    reaches something the plan did not route, the finding says so rather
    than claiming silence.

    A WARNING, not an ERROR: the show goes on (the PA still works), and a
    channel pulled out on purpose -- a spare mic, a song without it -- is
    a normal desk state the plan could not know about. Silent for any
    channel whose planned routes were not all read."""
    findings = []
    for entry in plan.get("channels") or []:
        if not isinstance(entry, dict) or entry.get("bank") not in ("ch", "aux"):
            continue
        if not isinstance(entry.get("channel"), int):
            continue
        base = f"/{entry['bank']}/{entry['channel']}"
        routes = planned_routes(plan, entry)
        if not routes:
            continue
        states = [_route_state(state, base, kind, idx) for kind, _name, idx in routes]
        if any(s is None for s in states) or "carries" in states:
            continue
        names = [_desk_bus_label(state, idx, name) if kind == "bus"
                 else position_label(f"/main/{idx}")
                 for kind, name, idx in routes]
        sends = [n for (kind, _, _), n in zip(routes, names) if kind == "bus"]
        mains = [n for (kind, _, _), n in zip(routes, names) if kind == "main"]
        what = []
        if sends:
            what.append(f"sends it to {_join(sends)}")
        if mains:
            what.append(f"routes it to {_join(mains)}")
        if all(s == "off" for s in states):
            if len(routes) == 1:
                verdict = "that route is off" if mains else "that send is off"
            elif len(routes) == 2:
                verdict = "neither is on" if mains else "neither send is on"
            else:
                verdict = "none of them is on"
        else:
            verdict = "; ".join(f"{n} is {s}" for n, s in zip(names, states))
        elsewhere = _other_live_routes(state, base, {(k, i) for k, _n, i in routes})
        tail = (f" It still reaches {_join(elsewhere)}, which the plan does not route it to."
                if elsewhere else " Its signal reaches nothing the plan routes it to.")
        addresses = tuple(f"{base}/main/{idx}/on" if kind == "main" else f"{base}/send/{idx}/on"
                          for kind, _name, idx in routes)
        findings.append((base, routes, Diagnostic.audit(
            "CV016", Severity.WARNING, "conventions", "Planned Routes All Off",
            f"{strip_label(state, base)}: the plan {' and '.join(what)}; {verdict}." + tail,
            addresses,
        )))
    return findings


def _routes_cv016_names(drift: list[tuple[str, list, Finding]]) -> dict[str, frozenset]:
    """For each strip CV016 reports, the `(kind, plan index)` of the routes
    its finding names: the ones CV006 and CV007 leave to it, so a strip
    cut off from everything is one row."""
    return {base: frozenset((kind, idx) for kind, _name, idx in routes)
            for base, routes, _finding in drift}


def planned_unmuted(state: ConsoleState, plan: dict) -> list[tuple[str, str]]:
    """`(base, plan name)` for every object the plan leaves unmuted: each
    plan channel, bus and DCA whose `fader.muted` is not true (apply
    writes such an object unmuted, `console_facts.MUTED_DEFAULT`), and each Main
    and Matrix the plan routes into or declares as an output, unless its
    output entry says muted. The talk mic is not in it: it is muted by
    design between talks (T002), and a plan has no way to say so."""
    out: list[tuple[str, str]] = []
    talk = talkback_strip(state)

    def unmuted(entry: dict) -> bool:
        fader = entry.get("fader")
        return not (isinstance(fader, dict) and fader.get("muted") is True)

    for entry in plan.get("channels") or []:
        if not isinstance(entry, dict) or entry.get("bank") not in ("ch", "aux"):
            continue
        if not isinstance(entry.get("channel"), int) or not unmuted(entry):
            continue
        base = f"/{entry['bank']}/{entry['channel']}"
        if base == talk or console_facts.is_talkback_name(
                entry.get("name"), (entry.get("source") or {}).get("input")):
            continue
        out.append((base, str(entry.get("name") or "")))
    for key, fmt in (("busses", "/bus/{}"), ("dcas", "/dca/{}")):
        for name, entry in (plan.get(key) or {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("index"), int) and unmuted(entry):
                out.append((fmt.format(entry["index"]), name))

    mains: dict[int, str] = {}
    matrices: dict[int, str] = {}
    stated_muted: set[str] = set()
    for name, entry in (plan.get("busses") or {}).items():
        dest = entry.get("destination") if isinstance(entry, dict) else None
        if isinstance(dest, dict) and dest.get("type") == "main" and isinstance(dest.get("index"), int):
            mains.setdefault(dest["index"], "")
    for entry in plan.get("channels") or []:
        for route in (entry.get("main_routes") or []) if isinstance(entry, dict) else []:
            if isinstance(route, dict) and isinstance(route.get("index"), int):
                mains.setdefault(route["index"], "")
    for name, entry in (plan.get("outputs") or {}).items():
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        fed = entry.get("fed_by") or {}
        if fed.get("type") == "main" and isinstance(fed.get("index"), int):
            mains.setdefault(fed["index"], "")
        if not isinstance(idx, int):
            continue
        target = {"main": mains, "matrix": matrices}.get(entry.get("kind"))
        if target is None:
            continue
        target[idx] = name
        if not unmuted(entry):
            stated_muted.add(f"/{'main' if entry.get('kind') == 'main' else 'mtx'}/{idx}")
    for idx, name in sorted(mains.items()):
        if f"/main/{idx}" not in stated_muted:
            out.append((f"/main/{idx}", name))
    for idx, name in sorted(matrices.items()):
        if f"/mtx/{idx}" not in stated_muted:
            out.append((f"/mtx/{idx}", name))
    return out


def mute_drift_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV017: a channel, bus, DCA, Main or Matrix the plan
    leaves unmuted, muted on the desk. Cleared the moment it is unmuted,
    as every Watch row is.

    A WARNING, not an ERROR. A muted Main, or the Vocals bus muted
    mid-song, silences the show, and that is serious -- but a mute is also
    the engineer's most ordinary deliberate act: a channel muted between
    songs, the FX busses muted for a speech, a band muted for the walk-in.
    An ERROR would fire on all of those, every night, and the engineer
    would learn to ignore the colour. A WARNING row that names what is
    muted is seen at a glance and costs nothing when it was meant. An
    engineer who wants a particular mute to be an ERROR has the watch
    condition for it (`"field": "muted"`, `"severity": "error"`).

    Only one direction: a mute the plan asked for, found off, is
    CV001/CV010/CV012's in a full `audit --plan` and is not
    drift worth a row mid-show. Silent for whatever was not read."""
    findings = []
    for base, name in planned_unmuted(state, plan):
        if state.mute(base) is not True:
            continue
        if base.startswith(("/ch/", "/aux/")):
            label = strip_label(state, base)
        else:
            desk_name = (effective_name(state, base)
                         if base.startswith(("/bus/", "/dca/")) else None)
            shown = desk_name or name
            # A plan's "Main 1" / "Matrix 1" is the position again, not a name.
            if shown and re.fullmatch(r"(?i)(main|matrix|mtx)\s*\d+", shown.strip()):
                shown = ""
            label = f'{position_label(base)} "{shown}"' if shown else position_label(base)
        findings.append(Diagnostic.audit(
            "CV017", Severity.WARNING, "conventions", "Muted Against Plan",
            f"{label} is muted on the desk; the plan leaves it unmuted.",
            (f"{base}/mute",),
        ))
    return findings


# --------------------------------------------------------------------------
# CV019: 48V against the plan
# --------------------------------------------------------------------------
#
# The plan states phantom for every channel and `apply` writes it, on the
# socket each of the strip's patch sockets names. C001 says 48V is on where
# nothing is patched; this says it is wrong where something is: a condenser
# with 48V off is silent, and 48V on at a source the plan says must not
# have it can damage one. It is bound to the plan like CV015 to CV017, and
# run by `audit --plan`, `atoo watch` and the Watch page.

PHANTOM_RULE_ID = "CV019"
PHANTOM_TITLE = "Phantom Contradicts Plan"


def phantom_judgements(state: ConsoleState, plan: dict) -> list[tuple[str, str, int, bool]]:
    """`(base, group, socket, 48V wanted)` for each socket CV019 compares.

    A plan channel that states a boolean `source.phantom`, patched on the
    desk to a group with a head amp: its first socket takes `source.phantom`
    and, where the plan puts the strip on two sockets (a stereo pair), the
    next socket takes the pair's own value (`inferred.socket_phantom`, which
    is what `apply` writes). The socket is the one the strip is patched to
    now, because that is what it hears; a strip moved off the plan's patch
    is CV005's as well. Nothing for an unpatched strip or one patched to a
    group with no `vph`."""
    out: list[tuple[str, str, int, bool]] = []
    for entry in plan.get("channels") or []:
        if not isinstance(entry, dict) or entry.get("bank") not in ("ch", "aux"):
            continue
        source = entry.get("source")
        if (not isinstance(entry.get("channel"), int) or not isinstance(source, dict)
                or not isinstance(source.get("phantom"), bool)):
            continue
        base = f"/{entry['bank']}/{entry['channel']}"
        live = state.patch(base)
        if live is None or live[0] not in console_facts.PHANTOM_CAPABLE_GROUPS:
            continue
        group, first = live
        for offset, (_socket, wanted) in enumerate(inferred.socket_phantom(entry)[:2]):
            out.append((base, group, first + offset, wanted))
    return out


def phantom_drift_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV019: 48V on the desk against the plan, one finding per socket.

    A WARNING either way. A condenser without 48V is silent, a patch that
    does not work; 48V on at a source the plan says must not have it can
    damage a ribbon mic. The plan states which is which, so nothing here is
    guessed from a name and there is nothing to announce at INFO. Silent
    for a socket whose `vph` was not read."""
    findings = []
    for base, group, socket, wanted in phantom_judgements(state, plan):
        live = state.input_phantom(group, socket)
        if live is None or live == wanted:
            continue
        where = format_socket(group, socket)
        if wanted:
            message = (f"{strip_label(state, base)}: the plan has 48V on at {where}; the desk has it "
                       "off, so a condenser patched there is silent.")
        else:
            message = (f"{strip_label(state, base)}: the plan has no 48V at {where}; the desk has it "
                       "on, which can damage a source that does not want it.")
        findings.append(Diagnostic.audit(
            "CV019", Severity.WARNING, "conventions", "Phantom Contradicts Plan",
            message, (f"/io/in/{group}/{socket}/vph",),
        ))
    return findings


# --------------------------------------------------------------------------
# CV020: a bus's width against the plan
# --------------------------------------------------------------------------
#
# The plan decides every bus's width (`busses[*].mono`) and `apply` writes it to
# `/bus/{n}/busmono`. The width changes what an output jack carries, so a bus
# left at the other width is a patch that does not do what the plan meant.
# Bound to the plan like CV019, and run by `audit --plan`, `atoo watch` and the
# Watch page. A plan states a width for a bus and for nothing else.

BUS_WIDTH_RULE_ID = "CV020"
BUS_WIDTH_TITLE = "Bus Width Contradicts Plan"


def bus_width_judgements(plan: dict) -> list[tuple[str, int, bool]]:
    """`(plan name, desk index, planned mono)` for each bus the plan gives an
    index and a boolean `mono`."""
    out = []
    for name, entry in (plan.get("busses") or {}).items():
        if (isinstance(entry, dict) and isinstance(entry.get("index"), int)
                and isinstance(entry.get("mono"), bool)):
            out.append((name, entry["index"], entry["mono"]))
    return out


def bus_width_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV020: a bus whose width on the desk is not the plan's, one finding
    per bus. A WARNING: the plan states the width, so nothing is inferred,
    and the wrong one changes the signal on a jack. Silent for a width that
    was not read."""
    findings = []
    for name, index, planned_mono in bus_width_judgements(plan):
        base = f"/bus/{index}"
        live_mono = state.flag(f"{base}/busmono")
        if live_mono is None or live_mono == planned_mono:
            continue
        label = f'{position_label(base)} "{_desk_bus_label(state, index, name)}"'
        if planned_mono:
            message = (f"{label}: the plan has this bus mono; the desk has it stereo, so an output "
                       "patched to its left side carries only the left of the mix and anything "
                       "panned right is lost.")
        else:
            message = (f"{label}: the plan has this bus stereo; the desk has it mono, so its left "
                       "and right outputs carry the same signal and the panning is lost.")
        findings.append(Diagnostic.audit(
            "CV020", Severity.WARNING, "conventions", "Bus Width Contradicts Plan",
            message, (f"{base}/busmono",),
        ))
    return findings


# --------------------------------------------------------------------------
# CV021 and CV022: talkback against the plan's monitor mixes
# --------------------------------------------------------------------------
#
# T001 says talkback reaches nobody. It cannot say talkback reaches some mixes
# and not others, because a desk read does not say which busses are monitor
# mixes and the audit never guesses that from a name. The plan does say: it
# feeds a monitor mix to an output socket and to no Main, and sends into it
# pre-fader. TALK A and TALK B each have one destination switch per bus
# (`/cfg/talk/{A,B}/B1..B16`), so whether talkback reaches a mix is two
# switches already read when talkback is assigned.

TALKBACK_MONITOR_RULE_ID = "CV021"
TALKBACK_MONITOR_TITLE = "Talkback Misses A Monitor Mix"
TALKBACK_MONITORS_NOTE_RULE_ID = "CV022"
TALKBACK_MONITORS_NOTE_TITLE = "Monitor Mixes Talkback Was Checked Against"

#: A plan send mode that is not pre-fader.
_NOT_PRE_FADER = frozenset({"post", "group"})

#: The talkback destinations that are busses (`B1..B16`).
_TALK_BUSSES = tuple(d for d in console_facts.TALK_DESTINATIONS if d.startswith("B"))


def planned_monitor_busses(plan: dict) -> list[tuple[str, int]]:
    """`(plan name, desk index)` for each bus the plan builds as a monitor mix.

    A monitor mix is how the plan builder already recognises one
    (`inferred._is_monitor_bus`): the bus feeds an output socket and no Main.
    It is not one when the plan lists sends into it and every one of them is
    stated post-fader (or in group mode): a feed on its own output that
    follows the fader is a sub or a recording feed, not a mix a performer
    listens to. A send whose mode is not stated is read as the plan builder
    decides it for such a bus, pre-fader. Only busses talkback can reach
    (B1..B16) are returned."""
    modes: dict[str, set] = {}
    for entry in plan.get("channels") or []:
        if not isinstance(entry, dict):
            continue
        for send in entry.get("bus_sends") or []:
            if isinstance(send, dict) and send.get("bus"):
                modes.setdefault(send["bus"], set()).add(send.get("mode"))
    found = []
    for name, bus in (plan.get("busses") or {}).items():
        if not (isinstance(bus, dict) and isinstance(bus.get("index"), int)
                and 1 <= bus["index"] <= len(_TALK_BUSSES) and inferred._is_monitor_bus(bus)):
            continue
        stated = modes.get(name, set())
        if stated and stated <= _NOT_PRE_FADER:
            continue
        found.append((name, bus["index"]))
    return sorted(found, key=lambda item: item[1])


def _talk_reaches(state: ConsoleState, index: int) -> bool | None:
    """Whether TALK A or TALK B is routed to bus `index`: True when either
    switch is on, False when both are off, None when either was not read and
    neither is on."""
    flags = [state.flag(console_facts.talk_destination(button, f"B{index}"))
             for button in console_facts.TALK_BUTTONS]
    if any(flags):
        return True
    return None if any(flag is None for flag in flags) else False


def _talkback_nowhere(state: ConsoleState) -> bool:
    """T001's case: every destination switch was read and none is on."""
    flags = [state.flag(console_facts.talk_destination(button, dest))
             for button in console_facts.TALK_BUTTONS
             for dest in console_facts.TALK_DESTINATIONS]
    return all(flag is not None for flag in flags) and not any(flags)


def _talkback_monitor_judgements(state: ConsoleState, plan: dict) -> list[tuple[str, int, bool]]:
    """`(plan name, desk index, reached)` for each planned monitor mix talkback
    can be judged against. Empty when talkback is unassigned or unread, when
    the plan builds no monitor mix, and when talkback reaches nowhere at all
    (T001 says that once)."""
    assign = state.text(console_facts.TALK_ASSIGN)
    if assign is None or assign == console_facts.TALK_OFF or _talkback_nowhere(state):
        return []
    out = []
    for name, index in planned_monitor_busses(plan):
        reached = _talk_reaches(state, index)
        if reached is not None:
            out.append((name, index, reached))
    return out


def talkback_monitor_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV021: talkback is assigned and reaches some destination, but a monitor
    mix the plan builds has neither TALK A's nor TALK B's switch on. One
    finding per mix, so each clears when its own switch is put right.

    A WARNING like T001: the show goes on, but whoever listens to that mix
    cannot hear the engineer, which is found out when the band does not
    answer. Which busses are monitor mixes is the plan's (`planned_monitor_busses`),
    never a bus's name, and CV022 says which were taken."""
    findings = []
    assign = state.text(console_facts.TALK_ASSIGN)
    for name, index, reached in _talkback_monitor_judgements(state, plan):
        if reached:
            continue
        base = f"/bus/{index}"
        label = f'{position_label(base)} "{_desk_bus_label(state, index, name)}"'
        findings.append(Diagnostic.audit(
            "CV021", Severity.WARNING, "conventions", "Talkback Misses A Monitor Mix",
            f"Talkback is assigned to {assign} and reaches other mixes, but not {label}, a "
            f"monitor mix the plan builds: neither TALK A nor TALK B is routed to it, so whoever "
            f"listens to that mix cannot hear you. Switch B{index} on in TALK A's (or TALK B's) "
            f"destinations on the desk's talkback page.",
            (console_facts.talk_destination("A", f"B{index}"),
             console_facts.talk_destination("B", f"B{index}")),
        ))
    return findings


def talkback_monitors_note_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV022: the one line saying which busses CV021 took for monitor mixes
    and why, because that is an inference from the plan and not something the
    desk states. INFO; silent whenever CV021 has nothing to judge."""
    judged = _talkback_monitor_judgements(state, plan)
    if not judged:
        return []
    names = ", ".join(
        f'{position_label(f"/bus/{index}")} "{_desk_bus_label(state, index, name)}"'
        for name, index, _reached in judged)
    reached = sum(1 for *_rest, ok in judged if ok)
    return [Diagnostic.audit(
        "CV022", Severity.INFO, "conventions", "Monitor Mixes Talkback Was Checked Against",
        f"Talkback reaches {reached} of the {len(judged)} monitor mixes the plan builds: {names}. "
        f"A bus is taken for a monitor mix when the plan feeds it to an output socket and to no "
        f"Main, and does not send into it post-fader only; a mix the plan builds another way is "
        f"not checked.",
        (console_facts.TALK_ASSIGN,),
    )]


# --------------------------------------------------------------------------
# CV006, CV007 and CV018 in Watch: the plan's sends and routes
# --------------------------------------------------------------------------
#
# CV006 and CV007 compare what the plan states for a channel's sends and
# Main routes with the desk, and had run only in `audit --plan`: a monitor
# send flipped post-fader mid-show, or one IEM's click send switched off,
# went unreported. Watch binds them to the plan as it binds CV016. CV018 is
# their twin, the route the plan does NOT have.


def _plan_strips(plan: dict):
    """`(entry, base)` for every plan channel and aux with a position."""
    for entry in plan.get("channels") or []:
        if (isinstance(entry, dict) and entry.get("bank") in ("ch", "aux")
                and isinstance(entry.get("channel"), int)):
            yield entry, f"/{entry['bank']}/{entry['channel']}"


def bus_send_drift_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV006 as Watch runs it: a send the plan states that is off on the
    desk, or in the other pre/post mode. Not the level (`level=False`):
    it is what the engineer rides at soundcheck, and `audit --plan` keeps
    comparing it."""
    cut_off = _routes_cv016_names(_route_drift(state, plan))
    findings: list[Finding] = []
    for entry, base in _plan_strips(plan):
        findings.extend(_diff_bus_sends(
            state, entry, base, strip_label(state, base), entry.get("provenance") or {},
            level=False, spoken_for=cut_off.get(base, frozenset())))
    return findings


def main_route_drift_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV007 as Watch runs it: a listed Main route that is off, and a Main
    the plan does not list that is on."""
    cut_off = _routes_cv016_names(_route_drift(state, plan))
    findings: list[Finding] = []
    for entry, base in _plan_strips(plan):
        findings.extend(_diff_main_routes(
            state, entry, base, strip_label(state, base), entry.get("provenance") or {},
            spoken_for=cut_off.get(base, frozenset())))
    return findings


def _planned_send_indices(state: ConsoleState, plan: dict, entry: dict) -> set[int]:
    """The busses a plan channel lists a send to, as live indices: the
    plan's own `index` for the bus, and whatever its name resolves to on
    the desk. Both, as `plan_scope` takes both -- an ambiguity keeps a
    send out of CV018 rather than putting it in."""
    busses = plan.get("busses") or {}
    found: set[int] = set()
    for send in entry.get("bus_sends") or []:
        name = send.get("bus") if isinstance(send, dict) else None
        if not name:
            continue
        bus = busses.get(name)
        if isinstance(bus, dict) and isinstance(bus.get("index"), int):
            found.add(bus["index"])
        live = _resolve_single_index_by_name(state, name, bus_indices(state), "/bus/{}")
        if live is not None:
            found.add(live)
    return found


def _live_send_level(state: ConsoleState, send_base: str) -> float | None:
    """The level of a send that is on and above the floor; None when it is
    off, at the floor, or either leaf was not read."""
    if not state.flag(f"{send_base}/on"):
        return None
    level = state.number(f"{send_base}/lvl")
    return level if level is not None and level > FADER_FLOOR_DB else None


def planned_bus_mains(entry: dict) -> set[int]:
    """The Mains a plan bus lists a route to: its `destinations`, else the
    single `destination` (a main destination without an index is Main 1,
    as `apply` writes it)."""
    destinations = entry.get("destinations") or []
    if not destinations and isinstance(entry.get("destination"), dict):
        destinations = [entry["destination"]]
    return {d.get("index", 1) for d in destinations
            if isinstance(d, dict) and d.get("type") == "main"}


def unplanned_route_findings(state: ConsoleState, plan: dict) -> list[Finding]:
    """CV018: a send or route that is on, which the plan does
    not have. A planned channel's send to a bus its `bus_sends` does not
    name, or to any Matrix (the plan states no strip-to-Matrix send), that
    is on and above the floor; and a planned bus's route to a Main its
    destinations do not list. A channel's unlisted Main route is CV007's.

    A WARNING, a judgement: the engineer may have added the send on
    purpose after the build, and a row costs nothing when it was meant. It
    is not an INFO because a send nobody listed is how a click reaches the
    PA, and not an ERROR because adding a send is an ordinary act. Silent
    for whatever was not read."""
    findings: list[Finding] = []
    for entry, base in _plan_strips(plan):
        label = strip_label(state, base)
        planned = _planned_send_indices(state, plan, entry)
        for idx in send_targets(state, base):
            send_base = f"{base}/send/{idx}"
            level = _live_send_level(state, send_base)
            if idx in planned or level is None:
                continue
            findings.append(Diagnostic.audit(
                "CV018", Severity.WARNING, "conventions", "Send Or Route Not In Plan",
                f"{label}: a send to {strip_label(state, f'/bus/{idx}')} is on at {level:g}dB; "
                "the plan has no send from this channel to that bus.",
                (f"{send_base}/on",),
            ))
        for idx in matrix_send_targets(state, base):
            send_base = f"{base}/send/MX{idx}"
            level = _live_send_level(state, send_base)
            if level is None:
                continue
            findings.append(Diagnostic.audit(
                "CV018", Severity.WARNING, "conventions", "Send Or Route Not In Plan",
                f"{label}: a send to {position_label(f'/mtx/{idx}')} is on at {level:g}dB; "
                "the plan has no send from this channel to a Matrix.",
                (f"{send_base}/on",),
            ))
    for name, bus in (plan.get("busses") or {}).items():
        if not isinstance(bus, dict) or not isinstance(bus.get("index"), int):
            continue
        base = f"/bus/{bus['index']}"
        planned_mains = planned_bus_mains(bus)
        label = strip_label(state, base)
        if effective_name(state, base) is None:
            label = f'{position_label(base)} "{name}"'
        for main_index in main_route_targets(state, base):
            if main_index in planned_mains or not state.flag(f"{base}/main/{main_index}/on"):
                continue
            findings.append(Diagnostic.audit(
                "CV018", Severity.WARNING, "conventions", "Send Or Route Not In Plan",
                f"{label}: routed to {position_label(f'/main/{main_index}')} on the desk; "
                "the plan lists no route from this bus to it.",
                (f"{base}/main/{main_index}/on",),
            ))
    return findings


def planned_floor_strips(plan: dict) -> frozenset:
    """The channels, auxes and busses `plan` puts at the floor
    (`fader_db` at or below `FADER_FLOOR_DB`), as console bases:
    `{"/ch/1", "/bus/5"}`. Malformed entries are skipped."""
    out = set()
    for entry in plan.get("channels") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("channel"), int):
            continue
        db = (entry.get("fader") or {}).get("fader_db")
        if isinstance(db, (int, float)) and db <= FADER_FLOOR_DB:
            out.add(f"/{entry.get('bank') or 'ch'}/{entry['channel']}")
    for entry in (plan.get("busses") or {}).values():
        if not isinstance(entry, dict) or not isinstance(entry.get("index"), int):
            continue
        db = (entry.get("fader") or {}).get("fader_db")
        if isinstance(db, (int, float)) and db <= FADER_FLOOR_DB:
            out.add(f"/bus/{entry['index']}")
    return frozenset(out)


def fader_floor_rule(plan: dict) -> AuditRule:
    """L002 bound to `plan`: silent on a strip the plan itself puts at
    the floor, the same rule on every other."""
    base = next(rule for rule in DEFAULT_RULES if rule.id == "L002")
    floor = planned_floor_strips(plan)
    return replace(base, check=lambda state: _rule_fader_floor_while_active(state, floor))


def planned_routed_strips(plan: dict) -> frozenset:
    """The channels and auxes `plan` routes somewhere (`planned_routes`),
    as console bases: the strips CV016 judges."""
    out = set()
    for entry in plan.get("channels") or []:
        if (isinstance(entry, dict) and entry.get("bank") in ("ch", "aux")
                and isinstance(entry.get("channel"), int) and planned_routes(plan, entry)):
            out.add(f"/{entry['bank']}/{entry['channel']}")
    return frozenset(out)


def strip_reaches_nothing_rule(plan: dict) -> AuditRule:
    """R008 bound to `plan`: silent on a strip the plan routes, where
    CV016 says it, the same rule on every other."""
    base = next(rule for rule in DEFAULT_RULES if rule.id == "R008")
    routed = planned_routed_strips(plan)
    return replace(base, check=lambda state: _rule_strip_reaches_nothing(state, routed))


def dca_muted_rule(plan: dict) -> AuditRule:
    """CH004 bound to `plan`: silent on a DCA the plan judges, where CV017
    says it, the same rule on every other."""
    base = next(rule for rule in DEFAULT_RULES if rule.id == "CH004")
    planned = planned_dca_mutes(plan)
    return replace(base, check=lambda state: _rule_dca_muted_with_members(state, planned))


def _read_plan(plan_path) -> "dict | None":
    import json as _json
    from pathlib import Path as _Path

    try:
        plan = _json.loads(_Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return plan if isinstance(plan, dict) else None


def with_plan_rules(rules, plan_path) -> list[AuditRule]:
    """`rules` as Watch runs them on a show whose bundle has a plan: L002,
    R008, C001, CH004 and R011 bound to the plan (`fader_floor_rule`,
    `strip_reaches_nothing_rule`, `phantom_unpatched_rule`, `dca_muted_rule`,
    `stereo_one_side_rule`),
    then the plan-bound rules (`plan_watch_rules`). An unreadable plan leaves
    `rules` as they are."""
    plan = _read_plan(plan_path)
    if plan is None:
        return list(rules)
    bound = [fader_floor_rule(plan) if rule.id == "L002"
             else strip_reaches_nothing_rule(plan) if rule.id == "R008"
             else phantom_unpatched_rule(plan) if rule.id == "C001"
             else stereo_one_side_rule(plan) if rule.id == "R011"
             else dca_muted_rule(plan) if rule.id == "CH004"
             else rule for rule in rules]
    return bound + plan_watch_rules(plan_path)


def plan_watch_rules(plan_path) -> list[AuditRule]:
    """The plan-bound rules Watch adds when its show bundle has a plan:
    CV015 when the plan loads an effect, CV016 when it
    routes a channel anywhere, CV017, the
    send and route checks CV006, CV007 and CV018, and CV021 and CV022 when it
    builds a monitor mix. An unreadable
    plan adds none -- Watch watches a console, and a broken plan.json is
    Build's to report."""
    import json as _json
    from pathlib import Path as _Path

    try:
        plan = _json.loads(_Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(plan, dict):
        return []
    rules = [fx_insert_rule(plan), route_drift_rule(plan), mute_drift_rule(plan),
             bus_send_drift_rule(plan), main_route_drift_rule(plan),
             unplanned_route_rule(plan), phantom_drift_rule(plan), bus_width_rule(plan),
             talkback_monitor_rule(plan), talkback_monitors_note_rule(plan)]
    return [rule for rule in rules if rule is not None]


def route_drift_rule(plan: dict) -> AuditRule | None:
    """CV016 as a rule Watch can run, bound to `plan`; None when the
    plan routes no channel anywhere."""
    if not any(planned_routes(plan, e) for e in plan.get("channels") or []
               if isinstance(e, dict)):
        return None
    return AuditRule(
        ROUTE_DRIFT_RULE_ID, Severity.WARNING, "conventions", ROUTE_DRIFT_TITLE,
        "A channel the plan routes somewhere has every planned send and Main route off or "
        "at the floor on the desk.",
        lambda state: route_drift_findings(state, plan), scope=RuleScope.CONVENTION)


def mute_drift_rule(plan: dict) -> AuditRule:
    """CV017 as a rule Watch can run, bound to `plan`."""
    return AuditRule(
        MUTE_DRIFT_RULE_ID, Severity.WARNING, "conventions", MUTE_DRIFT_TITLE,
        "A channel, bus, DCA, Main or Matrix the plan leaves unmuted is muted on the desk.",
        lambda state: mute_drift_findings(state, plan), scope=RuleScope.CONVENTION)


def phantom_drift_rule(plan: dict) -> AuditRule | None:
    """CV019 as a rule Watch can run, bound to `plan`; None when no plan
    channel states a phantom."""
    if not any(isinstance(e, dict) and isinstance((e.get("source") or {}).get("phantom"), bool)
               for e in plan.get("channels") or []):
        return None
    return AuditRule(
        PHANTOM_RULE_ID, Severity.WARNING, "conventions", PHANTOM_TITLE,
        "48V on a socket is not what the plan states for the channel patched to it.",
        lambda state: phantom_drift_findings(state, plan), scope=RuleScope.CONVENTION)


def stereo_one_side_rule(plan: dict) -> AuditRule:
    """R011 bound to `plan`: silent on an object whose every output socket
    the plan declares (the plan asked for the patch), the same rule on every
    other. `audit --plan` does this through the plan's scope; Watch has no
    scope, so it is bound here as C001 is."""
    base = next(rule for rule in DEFAULT_RULES if rule.id == "R011")
    declared = frozenset(_declared_output_patches(plan))
    return replace(base, check=lambda state: _rule_stereo_one_side(state, declared))


def phantom_unpatched_rule(plan: dict) -> AuditRule:
    """C001 bound to `plan`: silent on a socket CV019 judges, the same rule
    on every other."""
    base = next(rule for rule in DEFAULT_RULES if rule.id == "C001")
    return replace(base, check=lambda state: _rule_phantom_unpatched(
        state, frozenset((g, s) for _b, g, s, _w in phantom_judgements(state, plan))))

def bus_width_rule(plan: dict) -> AuditRule | None:
    """CV020 as a rule Watch can run, bound to `plan`; None when the plan
    states no bus width."""
    if not bus_width_judgements(plan):
        return None
    return AuditRule(
        BUS_WIDTH_RULE_ID, Severity.WARNING, "conventions", BUS_WIDTH_TITLE,
        "A bus is mono or stereo on the desk where the plan states the other.",
        lambda state: bus_width_findings(state, plan), scope=RuleScope.CONVENTION)


def talkback_monitor_rule(plan: dict) -> AuditRule | None:
    """CV021 as a rule Watch can run, bound to `plan`; None when the plan
    builds no monitor mix."""
    if not planned_monitor_busses(plan):
        return None
    return AuditRule(
        TALKBACK_MONITOR_RULE_ID, Severity.WARNING, "conventions", TALKBACK_MONITOR_TITLE,
        "Talkback is assigned and reaches some destination, but a monitor mix the plan builds "
        "has neither TALK A's nor TALK B's switch on.",
        lambda state: talkback_monitor_findings(state, plan), scope=RuleScope.CONVENTION)


def talkback_monitors_note_rule(plan: dict) -> AuditRule | None:
    """CV022 as a rule Watch can run, bound to `plan`; None when the plan
    builds no monitor mix."""
    if not planned_monitor_busses(plan):
        return None
    return AuditRule(
        TALKBACK_MONITORS_NOTE_RULE_ID, Severity.INFO, "conventions",
        TALKBACK_MONITORS_NOTE_TITLE,
        "Which busses talkback was checked against, taken from the plan.",
        lambda state: talkback_monitors_note_findings(state, plan), scope=RuleScope.CONVENTION)


def bus_send_drift_rule(plan: dict) -> AuditRule | None:
    """CV006 as a rule Watch can run, bound to `plan`; None when the plan
    states no send."""
    if not any(isinstance(e, dict) and e.get("bus_sends") for e in plan.get("channels") or []):
        return None
    return AuditRule(
        "CV006", Severity.WARNING, "conventions", "Bus Send Contradicts Plan",
        "A send the plan states is off on the desk, or in the other pre/post mode.",
        lambda state: bus_send_drift_findings(state, plan), scope=RuleScope.CONVENTION)


def main_route_drift_rule(plan: dict) -> AuditRule | None:
    """CV007 as a rule Watch can run, bound to `plan`; None when the plan
    has no channel."""
    if not any(True for _ in _plan_strips(plan)):
        return None
    return AuditRule(
        "CV007", Severity.WARNING, "conventions", "Main Route Contradicts Plan",
        "A channel's direct Main route the plan lists is off, or one it does not list is on.",
        lambda state: main_route_drift_findings(state, plan), scope=RuleScope.CONVENTION)


def unplanned_route_rule(plan: dict) -> AuditRule | None:
    """CV018 as a rule Watch can run, bound to `plan`; None when the plan
    has no channel and no bus."""
    if not any(True for _ in _plan_strips(plan)) and not plan.get("busses"):
        return None
    return AuditRule(
        "CV018", Severity.WARNING, "conventions", "Send Or Route Not In Plan",
        "A send to a bus or Matrix, or a bus's route to a Main, is on and the plan does not "
        "have it.",
        lambda state: unplanned_route_findings(state, plan), scope=RuleScope.CONVENTION)


def fx_insert_rule(plan: dict) -> AuditRule | None:
    """CV015 as a rule Watch can run, bound to `plan`; None when the
    plan loads no effect."""
    if not planned_fx_inserts(plan):
        return None
    return AuditRule(
        FX_INSERT_RULE_ID, Severity.WARNING, "conventions", FX_INSERT_TITLE,
        "An FX bus whose insert is off, names another engine, or whose engine holds another "
        "model than its bus preset planned.",
        lambda state: fx_insert_findings(state, plan), scope=RuleScope.CONVENTION)


def _diff_bus_sends(
    state: ConsoleState, entry: dict, base: str, label: str, provenance: dict,
    *, level: bool, spoken_for: frozenset = frozenset(),
) -> list[Finding]:
    """CV006 for one plan channel: each send the plan states,
    against the desk's switch, level and pre/post mode.

    Each entry names a bus by NAME (the plan is name-based, the console is
    index-based), so it goes through the same `_resolve_single_index_by_name`
    every DCA/mute-group name uses -- an unresolved or ambiguous bus name is
    skipped silently, not reported as a name mismatch.

    `level=False` is what Watch runs: a send level is what the engineer
    rides at soundcheck, so only the switch and pre/post can be a row.
    A value that was not read is not a contradiction. `spoken_for` is the
    `(kind, plan index)` of routes CV016 already names for this strip, whose
    off switch is then said once, by it."""
    findings: list[Finding] = []
    for send in entry.get("bus_sends") or []:
        bus_name = send.get("bus") if isinstance(send, dict) else None
        if not bus_name:
            continue
        bidx = _resolve_single_index_by_name(state, bus_name, bus_indices(state), "/bus/{}")
        if bidx is None:
            continue
        send_base = f"{base}/send/{bidx}"

        # A stated send implies it should be on -- apply.py always
        # writes on=1 for any stated send (there's no "stated but off"
        # concept in the plan), so a live "off" reading contradicts the
        # plan regardless of what mode/level say.
        if state.flag(f"{send_base}/on") is False and ("bus", bidx) not in spoken_for:
            findings.append(Diagnostic.audit(
                "CV006", Severity.WARNING, "conventions", "Bus Send Contradicts Plan",
                f"{label}: plan states a send to {bus_name}, live console reads off."
                + _cite(provenance, "bus_sends"),
                (f"{send_base}/on",),
            ))

        level_db = send.get("level_db")
        if level and level_db is not None:
            live_lvl = state.number(f"{send_base}/lvl")
            if live_lvl is not None and abs(float(level_db) - live_lvl) > FADER_TOLERANCE_DB:
                findings.append(Diagnostic.audit(
                    "CV006", Severity.WARNING, "conventions", "Bus Send Contradicts Plan",
                    f"{label}: plan says send to {bus_name} is {level_db:g}dB, live console "
                    f"reads {live_lvl:g}dB (tolerance {FADER_TOLERANCE_DB:g}dB)."
                    + _cite(provenance, "bus_sends"),
                    (f"{send_base}/lvl",),
                ))

        mode = send.get("mode")
        if mode is not None:
            # apply.py's own source of truth for this mapping
            # (_SEND_MODE_TO_WING), imported rather than re-derived --
            # an unrecognized plan mode resolves to None here exactly
            # as it does there, and is skipped rather than compared
            # against nothing.
            wing_mode = _SEND_MODE_TO_WING.get(mode)
            live_mode = state.text(f"{send_base}/mode")
            if wing_mode is not None and live_mode is not None and live_mode != wing_mode:
                findings.append(Diagnostic.audit(
                    "CV006", Severity.WARNING, "conventions", "Bus Send Contradicts Plan",
                    f"{label}: plan says send to {bus_name} mode is {mode!r} "
                    f"({wing_mode}), live console reads {live_mode}."
                    + _cite(provenance, "bus_sends"),
                    (f"{send_base}/mode",),
                ))
    return findings


def _diff_main_routes(
    state: ConsoleState, entry: dict, base: str, label: str, provenance: dict,
    *, spoken_for: frozenset = frozenset(),
) -> list[Finding]:
    """CV007 for one plan channel: each direct Main route the
    plan lists, against the desk, and each Main it does not list.

    The route is already a live index, so no name resolution step is
    needed, unlike `bus_sends`. `spoken_for` is as in `_diff_bus_sends`."""
    findings: list[Finding] = []
    for route in entry.get("main_routes") or []:
        route_index = route.get("index") if isinstance(route, dict) else None
        if route_index is None or ("main", route_index) in spoken_for:
            continue
        main_base = f"{base}/main/{route_index}"
        if state.flag(f"{main_base}/on") is False:
            findings.append(Diagnostic.audit(
                "CV007", Severity.WARNING, "conventions", "Main Route Contradicts Plan",
                f"{label}: plan says this channel routes directly to Main {route_index}, "
                f"live console reads off." + _cite(provenance, "main_routes"),
                (f"{main_base}/on",),
            ))
    # And the other half: `main_routes` is the COMPLETE
    # statement of a strip's direct Main routing, and apply switches
    # every unlisted Main off. A factory WING ships every strip on
    # Main 1, so a planned channel still reading ON at a Main the plan
    # does not list is a desk that was never told -- the click on the
    # PA, or a drum on Main twice, directly and through its bus. Only
    # a live ON is reported: a Main that did not answer says nothing.
    listed_mains = {r.get("index") for r in entry.get("main_routes") or []
                    if isinstance(r, dict)}
    for main_index in main_route_targets(state, base):
        if main_index in listed_mains:
            continue
        main_base = f"{base}/main/{main_index}"
        if state.flag(f"{main_base}/on"):
            findings.append(Diagnostic.audit(
                "CV007", Severity.WARNING, "conventions", "Main Route Contradicts Plan",
                f"{label}: plan lists no direct route from this channel to Main "
                f"{main_index}, live console reads on." + _cite(provenance, "main_routes"),
                (f"{main_base}/on",),
            ))
    return findings


def diff_against_plan(state: ConsoleState, plan: dict) -> list[Finding]:
    """FR-4.1 (an earlier change first slice + the extension): walk
    `plan.get("channels", [])` and compare each plan channel's stated
    mute/fader/DCA/mute-group/patch/bus-send/main-route/processing fields
    against `state`, the same live substrate the structural rules above
    read. See this section's own header comment for what's covered and
    what's deliberately deferred.

    All findings here use Severity.WARNING -- a documented, deliberate
    simplification (real per-field severity nuance, e.g. a patch
    mismatch plausibly mattering more than a 0.6dB fader gap, is left for
    later rather than invented here)."""
    findings: list[Finding] = []
    drift = _route_drift(state, plan)
    cut_off = _routes_cv016_names(drift)
    for entry in plan.get("channels", []):
        base = f"/{entry['bank']}/{entry['channel']}"
        if state.name(base) is None:
            continue  # this plan channel's live state was never read
        provenance = entry.get("provenance") or {}
        label = strip_label(state, base)

        fader = entry.get("fader") or {}
        muted = fader.get("muted")
        # Only the mute the plan asked for, found off. A mute
        # the plan did not ask for is CV017's, which Watch runs too.
        if muted is True:
            live_muted = state.mute(base)
            if not live_muted:
                findings.append(Diagnostic.audit(
                    "CV001", Severity.WARNING, "conventions", "Mute Contradicts Plan",
                    f"{label}: plan says muted={muted!r}, live console reads "
                    f"muted={live_muted!r}." + _cite(provenance, "fader"),
                    (f"{base}/mute",),
                ))

        fader_db = fader.get("fader_db")
        if fader_db is not None:
            live_db = state.fader_db(base)
            if live_db is None or abs(float(fader_db) - live_db) > FADER_TOLERANCE_DB:
                live_text = "unread" if live_db is None else f"{live_db:g}dB"
                findings.append(Diagnostic.audit(
                    "CV002", Severity.WARNING, "conventions", "Fader Level Contradicts Plan",
                    f"{label}: plan says {fader_db:g}dB, live console reads {live_text} "
                    f"(tolerance {FADER_TOLERANCE_DB:g}dB)." + _cite(provenance, "fader"),
                    (f"{base}/fdr",),
                ))

        dca_names = entry.get("dca") or []
        if dca_names:
            missing = _missing_group_memberships(
                state, base, dca_names, dca_indices(state), "/dca/{}", _DCA_TAG_RE)
            if missing:
                findings.append(Diagnostic.audit(
                    "CV003", Severity.WARNING, "conventions", "DCA Membership Contradicts Plan",
                    f"{label}: plan says it belongs to DCA(s) {', '.join(sorted(missing))}, but "
                    "live tags don't show that membership." + _cite(provenance, "dca"),
                    (f"{base}/tags",),
                ))

        mute_group_names = entry.get("mute_group") or []
        if mute_group_names:
            missing = _missing_group_memberships(
                state, base, mute_group_names, mute_group_indices(state), "/mgrp/{}", _MUTE_GROUP_TAG_RE)
            if missing:
                findings.append(Diagnostic.audit(
                    "CV004", Severity.WARNING, "conventions", "Mute Group Membership Contradicts Plan",
                    f"{label}: plan says it belongs to mute group(s) {', '.join(sorted(missing))}, "
                    "but live tags don't show that membership." + _cite(provenance, "mute_group"),
                    (f"{base}/tags",),
                ))

        patch = entry.get("patch") or {}
        group = patch.get("group")
        sockets = patch.get("sockets") or []
        if group and sockets:
            expected = (group, int(sockets[0]))
            live_patch = state.patch(base)
            if live_patch != expected:
                # Printed the way an input list writes it
                # ("AES50-A 12"), not "A12" -- the operator has to be able
                # to paste this back into the column it came from.
                live_text = "unpatched" if live_patch is None else format_socket(*live_patch)
                findings.append(Diagnostic.audit(
                    "CV005", Severity.WARNING, "conventions", "Patch Contradicts Plan",
                    f"{label}: plan says patched to {format_socket(*expected)}, live console "
                    f"reads {live_text}." + _cite(provenance, "patch"),
                    (f"{base}/in/conn/grp", f"{base}/in/conn/in"),
                ))

        # Bus sends and direct Main routes (FR-1.11).
        findings.extend(_diff_bus_sends(
            state, entry, base, label, provenance, level=True,
            spoken_for=cut_off.get(base, frozenset())))
        findings.extend(_diff_main_routes(
            state, entry, base, label, provenance,
            spoken_for=cut_off.get(base, frozenset())))

        # Processing: trim, balance, invert and head-amp gain, each with
        # its own tolerance below. The high-pass, hi-cut, tilt and EQ are
        # compared after this block, by `_processing_leaf_findings`.
        processing = entry.get("processing") or {}

        trim_db = processing.get("trim_db")
        if trim_db is not None:
            live_trim = state.number(f"{base}/in/set/trim")
            if live_trim is None or abs(float(trim_db) - live_trim) > FADER_TOLERANCE_DB:
                live_text = "unread" if live_trim is None else f"{live_trim:g}dB"
                findings.append(Diagnostic.audit(
                    "CV008", Severity.WARNING, "conventions", "Processing Contradicts Plan",
                    f"{label}: plan says trim is {trim_db:g}dB, live console reads {live_text} "
                    f"(tolerance {FADER_TOLERANCE_DB:g}dB)." + _cite(provenance, "processing"),
                    (f"{base}/in/set/trim",),
                ))

        balance_db = processing.get("balance_db")
        if balance_db is not None:
            live_bal = state.number(f"{base}/in/set/bal")
            if live_bal is None or abs(float(balance_db) - live_bal) > FADER_TOLERANCE_DB:
                live_text = "unread" if live_bal is None else f"{live_bal:g}dB"
                findings.append(Diagnostic.audit(
                    "CV008", Severity.WARNING, "conventions", "Processing Contradicts Plan",
                    f"{label}: plan says balance is {balance_db:g}dB, live console reads "
                    f"{live_text} (tolerance {FADER_TOLERANCE_DB:g}dB)." + _cite(provenance, "processing"),
                    (f"{base}/in/set/bal",),
                ))

        invert = processing.get("invert")
        if invert is not None:
            live_invert = state.flag(f"{base}/in/set/inv")
            if bool(invert) != bool(live_invert):
                findings.append(Diagnostic.audit(
                    "CV008", Severity.WARNING, "conventions", "Processing Contradicts Plan",
                    f"{label}: plan says invert={invert!r}, live console reads "
                    f"invert={live_invert!r}." + _cite(provenance, "processing"),
                    (f"{base}/in/set/inv",),
                ))

        gain_db = processing.get("gain_db")
        if gain_db is not None:
            # Head-amp gain lives on the physical SOURCE, not the strip
            # (same as apply.py's own write) -- needs the live patch to
            # know which group/socket, and only groups apply.py has a
            # confirmed `.g` address for (_VPH_CAPABLE_GROUPS) carry one.
            # Unpatched, or patched to a group outside that set: skip
            # silently, same discipline as an unresolved bus/DCA/
            # mute-group name.
            patch_info = state.patch(base)
            if patch_info is not None and patch_info[0] in _VPH_CAPABLE_GROUPS:
                group, socket = patch_info
                live_gain = state.number(f"/io/in/{group}/{socket}/g")
                if live_gain is None or abs(float(gain_db) - live_gain) > HEAD_AMP_GAIN_TOLERANCE_DB:
                    live_text = "unread" if live_gain is None else f"{live_gain:g}dB"
                    findings.append(Diagnostic.audit(
                        "CV008", Severity.WARNING, "conventions", "Processing Contradicts Plan",
                        f"{label}: plan says head-amp gain on {group} {socket} is {gain_db:g}dB, "
                        f"live console reads {live_text} (tolerance {HEAD_AMP_GAIN_TOLERANCE_DB:g}dB)."
                        + _cite(provenance, "processing"),
                        (f"/io/in/{group}/{socket}/g",),
                    ))

        # The filters and the EQ: a `log` parameter holds the nearest step
        # of its control, so each leaf is compared with `apply`'s own
        # readback tolerance rather than the fader's.
        findings.extend(_processing_leaf_findings(state, entry, base, label, provenance))

    findings.extend(_diff_group_faders(state, plan))
    findings.extend(_diff_talkback_strip(state, plan))
    findings.extend(fx_insert_findings(state, plan))
    findings.extend(finding for _base, _routes, finding in drift)
    findings.extend(mute_drift_findings(state, plan))
    findings.extend(unplanned_route_findings(state, plan))
    findings.extend(phantom_drift_findings(state, plan))
    findings.extend(bus_width_findings(state, plan))
    findings.extend(talkback_monitor_findings(state, plan))
    findings.extend(talkback_monitors_note_findings(state, plan))

    # Undeclared/stray physical output patches. Not per-channel
    # like everything above -- a single global pass over every output
    # socket `state` actually read (only sockets the caller told
    # `read_console_state` about via `output_sockets=`, per that
    # function's own "no confirmed default" reasoning). Confirmed real on
    # a real console: two busses (Drums/Drums Comp) patched to
    # local outputs 5/6 that neither `apply.py` nor the plan itself ever
    # asked for -- this rule is what would have caught that the moment it
    # happened instead of days later in a `.snap` diff.
    declared = _declared_output_patches(plan)
    for group, socket in output_sockets(state):
        live = state.output_source(group, socket)
        if live is None:
            continue  # unpatched (.grp == OFF, or never read) -- nothing to flag
        expected = declared.get((group, socket))
        if expected is None:
            findings.append(Diagnostic.audit(
                "CV009", Severity.WARNING, "conventions", "Undeclared Physical Output Patch",
                f"{format_socket(group, socket)} is patched to {live[0]} {live[1]} on the live console, but "
                "no bus or output in the plan routes anywhere to this socket -- likely leftover "
                "from an earlier apply, a different show, or manual patching.",
                (f"/io/out/{group}/{socket}/grp", f"/io/out/{group}/{socket}/in"),
            ))
        elif live != expected:
            findings.append(Diagnostic.audit(
                "CV009", Severity.WARNING, "conventions", "Undeclared Physical Output Patch",
                f"{format_socket(group, socket)}: plan routes this socket to {expected[0]} {expected[1]}, "
                f"live console reads {live[0]} {live[1]} instead.",
                (f"/io/out/{group}/{socket}/grp", f"/io/out/{group}/{socket}/in"),
            ))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id))
    return findings


# --------------------------------------------------------------------------
# Signal graph (FR-5): patch, strip, bus, main, matrix and output as nodes;
# mute/fader/routing as edge conditions (FR-5.2). Every edge type here maps
# to a confirmed, readable parameter (FR-5.3), including .pon ("pre always
# on", wing-console-model.md): a PRE-mode send with .pon set stays open
# even if the strip itself is muted, since .pon only bypasses the mute
# gate -- a .pon send with the strip's fader at the floor still closes.
# --------------------------------------------------------------------------


@dataclass
class Edge:
    target: str
    open: bool
    reason: str | None  # why it's closed, if it is


@dataclass
class SignalGraph:
    edges: dict[str, list[Edge]] = field(default_factory=dict)

    def add(self, source: str, target: str, open_: bool, reason: str | None = None) -> None:
        self.edges.setdefault(source, []).append(Edge(target, open_, reason))

    def neighbors(self, node: str) -> list[Edge]:
        return self.edges.get(node, [])


def build_signal_graph(state: ConsoleState) -> SignalGraph:
    g = SignalGraph()

    for base in strip_bases(state):
        p = state.patch(base)
        if p is not None:
            g.add(f"input:{p[0]}:{p[1]}", f"strip:{base}", True)

        muted = bool(state.mute(base))
        fdr = state.fader_db(base)
        fader_open = fdr is None or fdr > FADER_FLOOR_DB
        fader_reason = None if fader_open else f"{base}'s fader is at the floor ({FADER_FLOOR_DB:g}dB)"
        strip_open = (not muted) and fader_open
        strip_reason = f"{base} is muted" if muted else fader_reason

        def _send_gate(send_addr: str) -> tuple[bool, str | None]:
            """A PRE-mode send with .pon ("pre always on") set stays open
            even while the strip is muted -- .pon bypasses only the mute
            gate, so the strip's own fader-floor state still applies
            (wing-console-model.md)."""
            if state.text(f"{send_addr}/mode") == "PRE" and bool(state.flag(f"{send_addr}/pon")):
                return fader_open, fader_reason
            return strip_open, strip_reason

        for bus_idx in send_targets(state, base):
            send_addr = f"{base}/send/{bus_idx}"
            send_on = bool(state.flag(f"{send_addr}/on"))
            lvl = state.number(f"{send_addr}/lvl")
            eff_strip_open, eff_strip_reason = _send_gate(send_addr)
            send_open = send_on and (lvl is None or lvl > FADER_FLOOR_DB) and eff_strip_open
            if not send_on:
                reason = f"{base}'s send to bus {bus_idx} is off"
            elif lvl is not None and lvl <= FADER_FLOOR_DB:
                reason = f"{base}'s send to bus {bus_idx} is at the floor"
            else:
                reason = eff_strip_reason
            g.add(f"strip:{base}", f"bus:{bus_idx}", send_open, reason)

        for mtx_idx in matrix_send_targets(state, base):
            send_addr = f"{base}/send/MX{mtx_idx}"
            send_on = bool(state.flag(f"{send_addr}/on"))
            lvl = state.number(f"{send_addr}/lvl")
            eff_strip_open, eff_strip_reason = _send_gate(send_addr)
            send_open = send_on and (lvl is None or lvl > FADER_FLOOR_DB) and eff_strip_open
            if not send_on:
                reason = f"{base}'s send to matrix {mtx_idx} is off"
            elif lvl is not None and lvl <= FADER_FLOOR_DB:
                reason = f"{base}'s send to matrix {mtx_idx} is at the floor"
            else:
                reason = eff_strip_reason
            g.add(f"strip:{base}", f"mtx:{mtx_idx}", send_open, reason)

        for main_idx in main_route_targets(state, base):
            route_on = bool(state.flag(f"{base}/main/{main_idx}/on"))
            route_open = route_on and strip_open
            reason = None if route_open else (f"{base}'s route to Main {main_idx} is off" if not route_on else strip_reason)
            g.add(f"strip:{base}", f"main:{main_idx}", route_open, reason)

    def _matrix_send_edges(base: str, source_node: str, source_open: bool,
                           source_reason: str | None) -> None:
        """A Bus and a Main each reach a Matrix by a send, the
        same shape and the same gating as the strip sends above. Without
        these edges `--trace` could not follow a mix to a PA hung off a
        matrix -- which is how you EQ for a room, and what
        house conventions describe."""
        for mtx_idx in matrix_send_targets(state, base):
            send_addr = f"{base}/send/MX{mtx_idx}"
            send_on = bool(state.flag(f"{send_addr}/on"))
            lvl = state.number(f"{send_addr}/lvl")
            send_open = send_on and (lvl is None or lvl > FADER_FLOOR_DB) and source_open
            if not send_on:
                reason = f"{base}'s send to matrix {mtx_idx} is off"
            elif lvl is not None and lvl <= FADER_FLOOR_DB:
                reason = f"{base}'s send to matrix {mtx_idx} is at the floor"
            else:
                reason = source_reason
            g.add(source_node, f"mtx:{mtx_idx}", send_open, reason)

    for idx in bus_indices(state):
        base = f"/bus/{idx}"
        muted = bool(state.mute(base))
        fdr = state.fader_db(base)
        bus_open = (not muted) and (fdr is None or fdr > FADER_FLOOR_DB)
        bus_reason = f"{base} is muted" if muted else (f"{base}'s fader is at the floor" if fdr is not None and fdr <= FADER_FLOOR_DB else None)
        for main_idx in main_route_targets(state, base):
            route_on = bool(state.flag(f"{base}/main/{main_idx}/on"))
            route_open = route_on and bus_open
            reason = None if route_open else (f"{base}'s route to Main {main_idx} is off" if not route_on else bus_reason)
            g.add(f"bus:{idx}", f"main:{main_idx}", route_open, reason)
        _matrix_send_edges(base, f"bus:{idx}", bus_open, bus_reason)

    for idx in main_indices(state):
        base = f"/main/{idx}"
        muted = bool(state.mute(base))
        fdr = state.fader_db(base)
        main_open = (not muted) and (fdr is None or fdr > FADER_FLOOR_DB)
        main_reason = f"{base} is muted" if muted else (
            f"{base}'s fader is at the floor" if fdr is not None and fdr <= FADER_FLOOR_DB else None)
        _matrix_send_edges(base, f"main:{idx}", main_open, main_reason)

    for group, socket in output_sockets(state):
        # `output_source_object`, not `ConsoleState.output_source`: the
        # number on the socket is a slot in an object's L/R pair, so a
        # trace to a bus other than the first followed nothing at all.
        source_node = _output_node(state, group, socket)
        if source_node is not None:
            g.add(source_node, f"output:{group}:{socket}", True)

    return g


def _shortest_path(g: SignalGraph, start: str, end: str) -> list[str] | None:
    if start == end:
        return [start]
    seen = {start}
    queue: deque[list[str]] = deque([[start]])
    while queue:
        path = queue.popleft()
        for edge in g.neighbors(path[-1]):
            if edge.target in seen:
                continue
            new_path = path + [edge.target]
            if edge.target == end:
                return new_path
            seen.add(edge.target)
            queue.append(new_path)
    return None


@dataclass
class TraceResult:
    start: str
    end: str
    reachable: bool
    path: list[str]
    break_reason: str | None


def trace_signal_path(g: SignalGraph, start: str, end: str) -> TraceResult:
    """FR-5.1: report the first break in the path, not every parameter
    along the way. Picks the shortest structural route between `start`
    and `end` (node ids like "input:LCL:3", "strip:/ch/12", "bus:5",
    "main:1", "mtx:2", "output:LCL:1") and walks its edges in order,
    stopping at the first one that isn't open."""
    path = _shortest_path(g, start, end)
    if path is None:
        return TraceResult(start, end, False, [start], f"no routing path exists from {start} to {end} at all")

    walked = [path[0]]
    for i in range(len(path) - 1):
        edges = g.neighbors(path[i])
        edge = next(e for e in edges if e.target == path[i + 1])
        if not edge.open:
            return TraceResult(start, end, False, walked, edge.reason or f"{path[i]} -> {path[i + 1]} is closed")
        walked.append(edge.target)
    return TraceResult(start, end, True, walked, None)


# --------------------------------------------------------------------------
# Narrative rendering (FR-6.3/FR-4.4): plain text, legible without
# translating an OSC address by hand.
# --------------------------------------------------------------------------


# A finding's own opening words, when they name one strip: `CH 3 "Vocal"`,
# `BUS 2`, followed by the rest of the sentence (` is in use but ...`).
_ITEM_THEN_REST = re.compile(
    r'^(?P<item>(?:' + "|".join(BANK_WORD.values()) + r') \d+(?: "[^"]*")?)(?P<rest> .+)$',
    re.S)

# How wide a grouped entry's list of strips runs before it wraps.
_ITEMS_WIDTH = 76


def rule_groups(findings: list[Finding]) -> list[list[Finding]]:
    """The findings, one list per (severity, rule), in the order the first
    of each was given -- `run_audit` sorts by both, so this is report
    order. Display only: what a person reads is grouped, the findings are
    not."""
    groups: dict[tuple, list[Finding]] = {}
    for f in findings:
        groups.setdefault((f.severity, f.rule_id, f.title), []).append(f)
    return list(groups.values())


def shared_sentence(group: list[Finding]) -> tuple[list[str], str] | None:
    """`(['CH 3 "Vocal"', 'CH 4 "Vocal"'], " is in use but belongs to no
    DCA group.")` when every finding in `group` opens on the strip it is
    about and then says the same thing about it -- or None, when the
    sentences differ past the strip (a level, a socket) and each has to be
    read on its own."""
    if len(group) < 2:
        return None
    matches = [_ITEM_THEN_REST.match(f.detail) for f in group]
    if not all(matches):
        return None
    rests = {m["rest"] for m in matches}
    if len(rests) != 1:
        return None
    return [m["item"] for m in matches], rests.pop()


def _item_lines(items: list[str]) -> list[str]:
    """`items` joined with commas, wrapped at `_ITEMS_WIDTH` between
    items, never inside one -- `CH 6` and `"Bass"` stay on one line."""
    lines: list[str] = []
    current = ""
    for i, item in enumerate(items):
        piece = item + ("," if i < len(items) - 1 else "")
        if current and len(current) + 1 + len(piece) > _ITEMS_WIDTH:
            lines.append(current)
            current = piece
        else:
            current = f"{current} {piece}" if current else piece
    if current:
        lines.append(current)
    return lines


def _render_rule_group(group: list[Finding]) -> list[str]:
    """One rule's entry. A rule that fired once reads as it always has:

        [INFO] CH001 Channel Not In Any DCA
          CH 3 "Vocal" is in use but belongs to no DCA group.

    A rule that fired on several strips says so once, with
    the strips listed and the sentence they share said once:

        [INFO] CH001 Channel Not In Any DCA (5)
          CH 3 "Vocal", CH 4 "Vocal", CH 5 "Bass", CH 6 "Bass DI", CH 7 "Playback"
          Each is in use but belongs to no DCA group.

    and, where the sentences differ past the strip (a level, a socket),
    each on its own line under the one heading. Nothing is dropped: every
    finding's text is in the entry, and the findings themselves are
    unchanged -- this is display only, like `finding_groups` for the
    build's notes."""
    first = group[0]
    heading = f"[{first.severity.value.upper()}] {first.rule_id} {first.title}"
    if len(group) == 1:
        return [heading, f"  {first.detail}"]
    heading += f" ({len(group)})"
    shared = shared_sentence(group)
    if shared is not None:
        items, rest = shared
        return [heading] + [f"  {line}" for line in _item_lines(items)] + [f"  Each{rest}"]
    return [heading] + [f"  {f.detail}" for f in group]


def render_findings(findings: list[Finding]) -> str:
    """The audit report as `audit` and `watch` print it: a count line,
    then one entry per rule (`_render_rule_group`). Counts are per finding,
    not per entry, so they still add up to what the rules produced."""
    if not findings:
        return "No findings -- every rule in this audit passed."

    counts = {s: 0 for s in Severity}
    for f in findings:
        counts[f.severity] += 1
    lines = [
        "Audit findings: "
        + ", ".join(f"{counts[s]} {s.value}" for s in Severity if counts[s]) + ".",
        "",
    ]
    for group in rule_groups(findings):
        lines += _render_rule_group(group)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_trace(result: TraceResult) -> str:
    if result.reachable:
        return f"OK: {result.start} reaches {result.end} via " + " -> ".join(result.path)
    return (
        f"BROKEN: {result.start} does not reach {result.end}.\n"
        f"  Reached: {' -> '.join(result.path)}\n"
        f"  First break: {result.break_reason}"
    )


# --------------------------------------------------------------------------
# Live reading (FR-4.2): read every address this module's rules and graph
# can use, computed from the console's own object counts rather than a
# fixed, vendor-dictated list. Physical input/output socket counts vary by
# console and cabling, so they're passed in explicitly rather than guessed
# -- pass what your show's input list / conventions actually reference
# (or, on a full walk, whatever the Compact parameter map
# reports for this hardware).
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Six rules can only answer for sockets the audit went and read
# --------------------------------------------------------------------------
#
# Every rule that asks a question about a physical socket -- R003,
# R004, CV009 on the output side, C001 on the input side -- can
# only answer for sockets `read_console_state` was told to read, and its
# `input_sockets`/`output_sockets` default to none at all. That default is
# well argued (a walk of the address tree is not a measurement of the
# hardware, `console_facts`' own opening comment) but nothing ever passed
# the flag, so every audit run against real hardware so far has been a
# silent partial audit: four rules dead, and two more -- R002, R005
# -- reporting a correctly patched desk as faulty because they could not
# see the patch.
#
# So the default moves from "nothing" to "everything we can actually
# justify reading", from the two sources that know:
#
#   * the DESK, which states its own model on `/?` -- `panel_for()` turns
#     that into the real socket counts of that model's panel (pp. 11-12 of
#     the protocol PDF), which is inventory rather than address space;
#   * the PLAN, when one is given, which names every socket it patches --
#     including the stage boxes on AES50 that no model table can know
#     about, because they are a fact about tonight's rig.
#
# What is deliberately NOT here: the `INPUT_SOCKETS`/`OUTPUT_SOCKETS`
# address space. Reading A/B/C blind would be 288 sockets per direction
# that nothing has confirmed exist, and `console_facts` says in as many
# words that using those numbers as a physical bound is the mistake.

def socket_groups_to_read(
    console_model: str | None = None,
    plan: dict | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """`(input_sockets, output_sockets)` for `read_console_state`, derived
    from the console model the desk stated and the plan in hand.

    Either argument may be absent: with neither, the answer is two empty
    dicts and the caller reads no sockets, which is exactly the old
    behaviour. An unrecognised model contributes nothing rather than
    raising -- unlike `verify_plan`, an audit with no model can still do
    most of its job, and a hard stop here would break `audit --console`
    against a desk whose model string we have not met.

    A group's count is the highest socket number worth reading, capped by
    the address space so that a plan naming socket 900 asks for no reads
    past where the firmware answers.
    """
    inputs: dict[str, int] = {}
    outputs: dict[str, int] = {}

    def claim(into: dict[str, int], group: object, socket: object, ceiling: dict[str, int]) -> None:
        if not isinstance(group, str) or not isinstance(socket, int) or socket < 1:
            return
        limit = ceiling.get(group)
        if limit is None or socket > limit:
            return
        into[group] = max(into.get(group, 0), socket)

    if console_model:
        try:
            panel = console_facts.panel_for(console_model)
        except console_facts.UnknownConsoleModel:
            panel = None
        if panel is not None:
            for group, count in panel["inputs"].items():
                if count:
                    inputs[group] = max(inputs.get(group, 0), count)
            for group, count in panel["outputs"].items():
                if count:
                    outputs[group] = max(outputs.get(group, 0), count)

    if plan:
        for channel in plan.get("channels") or []:
            patch = (channel or {}).get("patch") or {}
            for socket in patch.get("sockets") or []:
                claim(inputs, patch.get("group"), socket, console_facts.INPUT_SOCKETS)
        for (group, socket) in _declared_output_patches(plan):
            claim(outputs, group, socket, console_facts.OUTPUT_SOCKETS)

    return inputs, outputs


def summarise_sockets(sockets: list[tuple[str, int]]) -> str:
    """`[("LCL", 1), ..., ("LCL", 8), ("AUX", 1)]` as `"AUX 1, LCL 1-8"`
    -- the form the coverage line prints and R006 quotes."""
    counts: dict[str, int] = {}
    for group, number in sockets:
        counts[group] = max(counts.get(group, 0), number)
    # Spelled as `format_socket` spells a socket ("AES50-A 1-48", never
    # "A 1-48"), since an earlier change put AES50 groups in this line.
    def spelled(group: str) -> str:
        return format_socket(group, 1).rsplit(" ", 1)[0]

    return ", ".join(f"{spelled(group)} 1" if n == 1 else f"{spelled(group)} 1-{n}"
                     for group, n in sorted(counts.items()))


def render_coverage(state: ConsoleState, *, from_capture: bool = False) -> str:
    """One paragraph saying which physical sockets the state in hand
    covers, and -- when it covers none -- which rules therefore did not
    run. Also, any expansion bay something is patched
    from whose fitted-card reading is not in the state: a capture made
    before C003 existed, where that rule's silence is not a verdict.

    Printed rather than raised as a `Finding` on purpose: an INFO finding
    would flow into `audit`'s exit code, `watch`'s conditions and the
    Watch UI's counts, and those are settled contracts. This is a
    status line about the reading, not a fact about the desk.
    """
    # A capture cannot be widened by a flag -- it holds whatever was
    # captured -- so the advice differs even though the gap is the same.
    how = ("A capture holds only the addresses it was taken with, and no flag here "
           "can widen it; a live run derives its socket groups from the model the "
           "desk states and from --plan."
           if from_capture else
           "Name the sockets with --input-sockets/--output-sockets (e.g. "
           "--output-sockets LCL=8) to check them.")
    # A bay something is patched from, whose reading is not
    # in hand, is C003 staying silent -- which must not read as clean.
    unread_bays = [
        f"{group} ({', '.join(addresses)}) is in use but "
        f"{console_facts.EXPANSION_BAY_ADDRESSES[group]} was not read"
        for group, addresses in sorted(unread_expansion_bays(state).items())]
    bay_note = ([f"Expansion bay {'; '.join(unread_bays)}: C003 (Patch Uses An "
                 f"Empty Expansion Bay) could not check it."] if unread_bays else [])

    read_in = summarise_sockets(input_sockets(state))
    read_out = summarise_sockets(output_sockets(state))
    if not read_in and not read_out:
        return "\n".join(bay_note + [
            "Physical sockets read: none. R002 (Bus No Output), R003 (Matrix "
            "Orphan), R004 (Main Patched But Unfed), R005 (Main Not Patched), "
            "R006 (Matrix Fed But Not Patched), R011 (Stereo Output Patched On "
            "One Side), CV009 (Undeclared Physical "
            "Output Patch), C008 (AES50 Port Cannot Carry Its Patch), C009 (AES50 "
            "Stage Box Link Not OK), C001 (Phantom Power On Unpatched Socket) and C007 (Strip's "
            "Input Socket Muted) could not be checked -- with no output patch in hand, "
            "\"reaches no physical output\" is a question nobody asked rather than an "
            "answer.\n" + how])
    lines = [f"Physical sockets read: in {read_in or 'none'}; out {read_out or 'none'}."]
    if not read_out:
        lines.append("With no output sockets read, R002, R003, R004, R005, "
                     "R006, R011, CV009, C008 and C009 could not be checked. " + how)
    elif not read_in:
        lines.append("With no input sockets read, C001 and C007 could not be checked. " + how)
    return "\n".join(bay_note + lines)


# Every rule whose verdict is read off `/io/out/*`. R002 and R005
# are in here: they were the two that fired anyway.
# R006 was born with the same guard.
OUTPUT_SIDE_RULE_IDS = ("R002", "R003", "R004", "R005", "R006", "R011", "CV009", "C008", "C009")


def unanswerable_rule_ids(state: ConsoleState) -> tuple[str, ...]:
    """Which rules this reading cannot be asked, in catalogue order.

    The single place the "what did this read not cover" question is
    answered, so `render_coverage`'s paragraph, `coverage_caveat`'s one
    line and the rules' own guards cannot drift apart (an earlier change was
    exactly that drift: the paragraph knew, the rules did not)."""
    dark: list[str] = []
    if not output_patch_was_read(state):
        dark.extend(OUTPUT_SIDE_RULE_IDS)
    if not input_sockets(state):
        dark.extend(("C001", "C007"))
    if unread_expansion_bays(state):
        dark.append("C003")
    return tuple(dark)


def unread_expansion_bays(state: ConsoleState) -> dict[str, list[str]]:
    """`expansion_bays_in_use` less the bays whose fitted-card reading is
    actually in hand -- i.e. the bays C003 had to stay silent about."""
    return {group: addresses
            for group, addresses in expansion_bays_in_use(state).items()
            if console_facts.EXPANSION_BAY_ADDRESSES[group] not in state.values}


def coverage_caveat(state: ConsoleState) -> str | None:
    """`render_coverage` in one line, or None when the read covered
    everything its rules need.

    `audit` prints the paragraph; `watch` prints this. The difference is
    not tone but where it is read: `watch` output is read at a desk,
    mid-show, between change events, and a five-line status paragraph
    repeated there is a paragraph that gets skipped. What must survive
    the shortening is the list of rule ids, because that is the part an
    engineer acts on -- "R002 is dark" tells him to go and look at the
    output patch himself.
    """
    dark = unanswerable_rule_ids(state)
    if not dark:
        return None
    causes = []
    if not output_patch_was_read(state):
        causes.append("no output sockets read")
    if not input_sockets(state):
        causes.append("no input sockets read")
    if unread_expansion_bays(state):
        causes.append("an expansion bay in use not read")
    listed = (dark[0] if len(dark) == 1
              else ", ".join(dark[:-1]) + " and " + dark[-1])
    return f"Coverage: {', '.join(causes)} -- {listed} could not be checked."

# --------------------------------------------------------------------------
# The address plan, and the two ways to fetch it
# --------------------------------------------------------------------------
#
# `console_read_plan` is every (address, value_type) a live read asks
# for, built BEFORE any of it is fetched. That ordering is the whole
# point: a read that knows its own total can say `read 1200/6143 (19%)`
# while it works, and a read that cannot is indistinguishable from a
# hung one -- which is how an earlier change started, and how a correct `watch`
# run got killed on 2026-09-22.
#
# It also replaced a guess. `cli.ESTIMATED_LIVE_READ_ADDRESSES` was a
# hand-maintained 5,928 that went stale every time this plan grew; the
# real number for a Compact reading its own panel is 6,195, and it is
# now counted rather than remembered. (It was 6,032 --
# 320 of those were addresses the desk does not have and has never
# answered, so the number of VALUES a read came back with did not change
# -- and 5,712 until an earlier change added the alternate patch, 5,808 until
# an earlier change added the insert points and FX slots, 6,112 until its comms
# half added `/cfg/talk/assign`, 6,113 until an earlier change added `/io/altsw`,
# 6,114 until an earlier change added the socket widths, and 6,138 until an earlier change added three AES50 link states and two monitor sources.)

# (address suffix, value_type) -- types confirmed against
# the Compact parameter map ("fader"/"log" types
# both read as "f" per OscReply.value()'s float-reply handling; plain
# "int" reads as "i"; "list"/string enums read as "s").
# `in/conn/altgrp` and `in/set/altsrc` are the alternate input patch's
# group and the switch between the two patches (C004;
# `console_facts.ALT_PATCH_*`). `in/conn/altin`, the alternate's socket
# number, is deliberately NOT read: it is presumed to carry the same
# readback offset as `in/conn/in` and has not been measured, and no rule
# needs the number to say that a channel is not on its main patch.
STRIP_FIELDS = (("name", "s"), ("mute", "i"), ("fdr", "f"),
                ("tags", "s"), ("in/conn/grp", "s"), ("in/conn/in", "i"),
                ("in/conn/altgrp", "s"), ("in/set/altsrc", "i"))
SEND_FIELDS = (("on", "i"), ("lvl", "f"), ("mode", "s"), ("pon", "i"))


def insert_fields(bank: str, base: str) -> list[tuple[str, str]]:
    """Each insert point this bank has (`console_facts.INSERT_POINTS`):
    its switch and the FX slot it names, an earlier change. Four leaves on a
    channel, bus, Main or Matrix; two on an aux, which has no post-insert.
    Both ride inside the object's own node dump (the PDF's `/ch/1` dump
    carries `.preins.on=0,ins=NONE`), so the default node-dump read pays
    nothing for them. They joined the read after the A11 run that
    compared the two read paths on hardware, so they are the one part of
    it not yet compared both ways on a desk."""
    return [(f"{base}/{point}/{leaf}", value_type)
            for point in console_facts.INSERT_POINTS.get(bank, ())
            for leaf, value_type in (("on", "i"), ("ins", "s"))]


def send_fields_for(bank: str) -> tuple[tuple[str, str], ...]:
    """`SEND_FIELDS` less the leaves a send on this bank does not have.

    A strip's send carries `mode` and `pon`; a bus's and a Main's do not
    (`console_facts.SEND_LEAVES`, measured in A11 -- see that table).
    Asking anyway is not a harmless extra request: an address the desk
    never answers costs three seconds, and there were 320 of them, 96% of
    the wall time of a full read on real hardware.

    **This is a narrowing of the request list, not of coverage.** These
    addresses do not exist on the console, so nothing is being declined
    and no rule loses an input -- no rule ever read a bus's or a Main's
    send `mode`/`pon`, because the desk never returned one to read. That
    distinction matters (an earlier change was the opposite case, an audit
    quietly reading LESS than its rules needed), so it is stated here and
    in the console model notes rather than left to be
    re-derived from a diff.
    """
    return tuple((suffix, value_type) for suffix, value_type in SEND_FIELDS
                 if console_facts.send_has_leaf(bank, suffix))


def console_read_plan(
    *,
    channels: int = 40,
    aux: int = 8,
    buses: int = 16,
    mains: int = 4,
    matrices: int = 8,
    dcas: int = 16,
    mute_groups: int = 8,
    fx_slots: int = console_facts.FX_SLOTS,
    input_sockets: dict[str, int] | None = None,
    output_sockets: dict[str, int] | None = None,
    extra: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
) -> list[tuple[str, str]]:
    """Exactly the addresses this module's rules and graph consume, with
    the OSC value type each one is read as, in the order they are read.

    Pure: it contacts nothing. `read_console_state` fetches it,
    `cli.watch_cmd` counts it to tell the user what they are waiting
    for, and desk script A11 (`a11-read-speed.sh`) measures against
    it.

    `extra` is addresses beyond the rules' own, each as `(address, type)`:
    `plan_processing_read_addresses` gives the filter and EQ leaves a plan
    states, which `audit --plan` reads for CV008 (the strip's own node
    dump carries them, so they are no extra request). Nothing, by default.

    **Not quite all of them.** A read has a second pass
    this list cannot contain: the name of each socket a strip turns out to
    be patched to, which is where a name a human typed on a WING actually
    lives (`source_name_addresses`). Which socket to ask about is not
    knowable before the patch has been read, so purity and completeness
    cannot both hold here -- purity wins, the second pass is up to one
    address per *patched* strip (26 on a factory Compact, 6,143 -> 6,169),
    and a progress bar counting this plan grows its own total when the
    second pass starts rather than printing 101%.

    **`clink` is not in `STRIP_FIELDS` either, and since an earlier change it is
    in the second pass instead.** In `STRIP_FIELDS` it would be one
    address per strip whether or not that strip is patched; in the second
    pass it is one per *patched* strip, which is the only kind whose flag
    any rule can use (`custom_link_addresses`, and `source_is_named`,
    which answers False for an unpatched strip without consulting it).
    Leaving it unread was costed at 48 addresses and declined;
    scoped this way it is 26 on a factory Compact, and what it buys is
    `effective_name` getting out of its "assume ON, but never overrule
    the strip leaf" branch -- the branch that reported two differently
    named channels on a live full-size WING as a duplicate.
    """
    plan: list[tuple[str, str]] = []

    for bank, count in (("ch", channels), ("aux", aux)):
        strip_send_fields = send_fields_for(bank)
        for n in range(1, count + 1):
            base = f"/{bank}/{n}"
            for suffix, value_type in STRIP_FIELDS:
                plan.append((f"{base}/{suffix}", value_type))
            for bus_idx in range(1, buses + 1):
                for suffix, value_type in strip_send_fields:
                    plan.append((f"{base}/send/{bus_idx}/{suffix}", value_type))
            for mtx_idx in range(1, matrices + 1):
                for suffix, value_type in strip_send_fields:
                    plan.append((f"{base}/send/MX{mtx_idx}/{suffix}", value_type))
            for main_idx in range(1, mains + 1):
                plan.append((f"{base}/main/{main_idx}/on", "i"))
            plan.extend(insert_fields(bank, base))

    bus_send_fields = send_fields_for("bus")
    for idx in range(1, buses + 1):
        base = f"/bus/{idx}"
        for suffix, value_type in (("name", "s"), ("mute", "i"), ("fdr", "f"),
                                   ("busmono", "i")):
            plan.append((f"{base}/{suffix}", value_type))
        for main_idx in range(1, mains + 1):
            plan.append((f"{base}/main/{main_idx}/on", "i"))
        # A Matrix is fed by a SEND on its source object, and
        # `apply.py` writes that send on a Bus and on a Main as readily as
        # on a strip (`apply.py`'s matrix loop, `plan_schema.py`: "a SEND
        # on that source ... never a field on the matrix itself"). Until
        # this read existed, `send/MX*` was fetched for `/ch` and `/aux`
        # only -- so the audit could not see a matrix fed the way this
        # project's own plans feed one, and R005's matrix hop
        # had nothing to walk.
        #
        # `on` and `lvl` only. A bus's send to a matrix has no
        # `mode` and no `pon` -- see `send_fields_for` and
        # `console_facts.SEND_LEAVES`. Asking for them cost 256 timeouts a
        # read, and none of them was ever a value any rule could have had.
        for mtx_idx in range(1, matrices + 1):
            for suffix, value_type in bus_send_fields:
                plan.append((f"{base}/send/MX{mtx_idx}/{suffix}", value_type))
        plan.extend(insert_fields("bus", base))

    main_send_fields = send_fields_for("main")
    for idx in range(1, mains + 1):
        plan.append((f"/main/{idx}/mute", "i"))
        plan.append((f"/main/{idx}/fdr", "f"))
        plan.append((f"/main/{idx}/busmono", "i"))
        for mtx_idx in range(1, matrices + 1):
            for suffix, value_type in main_send_fields:
                plan.append((f"/main/{idx}/send/MX{mtx_idx}/{suffix}", value_type))
        plan.extend(insert_fields("main", f"/main/{idx}"))
    for idx in range(1, matrices + 1):
        plan.append((f"/mtx/{idx}/mute", "i"))
        plan.append((f"/mtx/{idx}/fdr", "f"))
        plan.append((f"/mtx/{idx}/busmono", "i"))
        plan.extend(insert_fields("mtx", f"/mtx/{idx}"))
    for idx in range(1, dcas + 1):
        plan.append((f"/dca/{idx}/name", "s"))
        plan.append((f"/dca/{idx}/mute", "i"))
        plan.append((f"/dca/{idx}/fdr", "f"))
    for idx in range(1, mute_groups + 1):
        plan.append((f"/mgrp/{idx}/name", "s"))
        plan.append((f"/mgrp/{idx}/mute", "i"))
    # What each FX slot holds -- the other half of every
    # insert above. Not in `BULK_NODE_DEPTH`: a slot's dump carries every
    # parameter of whatever effect is loaded, sizes nobody has measured,
    # for the one leaf a rule reads. Sixteen per-leaf reads instead.
    for idx in range(1, fx_slots + 1):
        plan.append((console_facts.FX_MODEL.replace("{n}", str(idx)), "s"))
    # Which strip talkback uses (T001). Where TALK A and B
    # are routed is asked in the second pass, and only if this is not OFF
    # (`talkback_addresses`) -- 56 switches a factory desk never needs.
    plan.append((console_facts.TALK_ASSIGN, "s"))
    # The global alternate-input switch (C005): one leaf.
    plan.append((console_facts.GLOBAL_ALT_SWITCH, "i"))

    # USER PATCHES (`/io/in/USR/{25..56}/user`): which physical jack feeds each user-patch
    # slot, with no
    # strip in between. C001 needs them -- a jack feeding a user patch
    # is a jack in use, and the rule called its 48V a fault until it could
    # see them.
    #
    # Read only when input sockets were asked for, which costs nothing and
    # keeps one contract: with no input sockets there is no socket for
    # C001 to judge, so the answer would go nowhere. The USR count is a
    # console fact rather than a cabling one (56 slots,
    # `console_facts.INPUT_SOCKETS`), so it is not itself a flag.
    if input_sockets:
        for n in USER_PATCH_SLOTS:
            plan.append((f"/io/in/USR/{n}/user/grp", "s"))
            plan.append((f"/io/in/USR/{n}/user/in", "i"))

    # Phantom power only where there is a head amp to carry
    # it (`console_facts.PHANTOM_CAPABLE_GROUPS` -- LCL and A/B/C). A
    # full-size WING's panel has eight AUX inputs, line-level jacks with
    # no preamp, and the parameter map has no `vph` under `/io/in/AUX`.
    # Asking for `/io/in/AUX/1..8/vph` anyway was A18's eight unanswered
    # addresses: 24s of a 47s read, and none of them a value C001
    # could have judged, since a socket with no 48V cannot have it on.
    # The group is still covered: its socket names arrive in the second
    # pass whenever a strip is patched to it.
    for group, count in (input_sockets or {}).items():
        if group not in console_facts.PHANTOM_CAPABLE_GROUPS:
            continue
        for n in range(1, count + 1):
            plan.append((f"/io/in/{group}/{n}/vph", "i"))
            # The source's width: C001 needs it to know
            # that a stereo strip patched to socket n also takes n+1.
            # In the same `/io/in/{grp}/{n}` node as `vph`, so a dump
            # read costs nothing more.
            plan.append((f"/io/in/{group}/{n}/mode", "s"))
            # The socket's own mute (C007): a muted socket silences every
            # strip patched to it, and the strip shows nothing. In the same
            # node as `vph` and `mode`, so a dump read asks nothing more.
            plan.append((f"/io/in/{group}/{n}/mute", "i"))
    for group, count in (output_sockets or {}).items():
        for n in range(1, count + 1):
            plan.append((f"/io/out/{group}/{n}/grp", "s"))
            plan.append((f"/io/out/{group}/{n}/in", "i"))
    # An earlier change, read only when output sockets are, by the same
    # contract as the USER PATCHES above: each is an answer to "does this
    # object reach an output", which nothing asks without an output patch.
    # Which AES50 ports have a device on them -- the second pass reads the
    # outputs of each (`aes50_output_addresses`) -- and what the two
    # monitor outputs listen to (`monitor_source_nodes`). Five leaves.
    if output_sockets:
        for port in console_facts.AES50_PORTS:
            plan.append((console_facts.aes50_status_address(port), "s"))
        for address in console_facts.MONITOR_SOURCES:
            plan.append((address, "s"))

    # What a plan states that no rule reads without one (`extra`): the filter
    # and EQ leaves `audit --plan` compares. Appended after everything else,
    # and never an address already in the plan.
    known = {address for address, _ in plan}
    for address, value_type in extra:
        if address not in known:
            known.add(address)
            plan.append((address, value_type))

    return plan


# How deep the node whose dump covers an address sits, per address root. `/ch/1/send/3/lvl` is covered by a dump of `/ch/1` --
# depth 2 -- and `/io/out/LCL/5/grp` by a dump of `/io/out/LCL/5`, depth
# 4. Object level and no higher: the protocol PDF (p23) warns that a node
# too large to fit a 32kB datagram comes back as an error instead, and a
# channel dump is already ~2.2kB, so `/ch` (40 of them) would not fit.
BULK_NODE_DEPTH = {
    "ch": 2, "aux": 2, "bus": 2, "main": 2, "mtx": 2, "dca": 2, "mgrp": 2,
    "io": 4,
}

# Leaves NEVER taken from a node dump, however well the dump parsed.
#
# A dump is flat text -- `name=Kick,mute=0,` -- and `name` and `tags` are
# the only leaves this project reads that hold FREE TEXT a human typed.
# What WING does with a comma inside one is not documented and has not
# been seen on hardware; if it does not quote it, `name=Vox, Lead` splits
# into a name of "Vox" and an item this parser rejects, and the whole
# node falls back. Worse, a name of the exact shape `Kick,mute=1` would
# parse as two valid items and silently corrupt a neighbour.
#
# The cost of excluding them is 136 extra per-leaf reads on a Compact
# (88 names + 48 tags), against 5,868 addresses saved. The cost of not
# excluding them is a report that states a value nobody set, from the
# tool whose entire claim is that its values are real. `a11-read-speed.sh`
# measures the hazard on real hardware -- it parses the names out of the
# dumps and says whether they agree with the per-leaf reads -- without
# any value here depending on the answer.
DUMP_UNSAFE_LEAVES = ("name", "tags")


def bulk_node_for(address: str) -> str | None:
    """The node whose `,s *` dump covers `address`, or None if this
    address must be read on its own."""
    if address.endswith(DUMP_UNSAFE_LEAVES):
        leaf = address.rsplit("/", 1)[-1]
        if leaf in DUMP_UNSAFE_LEAVES:
            return None
    parts = [p for p in address.split("/") if p]
    depth = BULK_NODE_DEPTH.get(parts[0] if parts else "")
    if depth is None or len(parts) <= depth:
        return None
    return "/" + "/".join(parts[:depth])


def group_plan_by_node(plan: list[tuple[str, str]]) -> tuple[
        dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """`(node -> its addresses, addresses with no node)`, preserving order."""
    by_node: dict[str, list[tuple[str, str]]] = {}
    alone: list[tuple[str, str]] = []
    for address, value_type in plan:
        node = bulk_node_for(address)
        if node is None:
            alone.append((address, value_type))
        else:
            by_node.setdefault(node, []).append((address, value_type))
    return by_node, alone


# --------------------------------------------------------------------------
# A family of addresses the desk does not answer
# --------------------------------------------------------------------------
#
# Two earlier failures -- 320 phantom send leaves on a Compact and eight
# AUX `vph` on a full-size -- are one shape: a whole family of sibling addresses the
# model does not have, each costing `(retries + 1) x timeout` -- 3s at the
# defaults. Both were fixed by correcting the read plan, which stays the
# real fix. This is the backstop for the next model we meet, whose
# missing family nobody has measured yet: it bounds what that costs.
#
# **A family** is an address with every run of digits replaced by `{n}`:
# `/io/in/AUX/3/vph` and `/io/in/AUX/7/vph` are `/io/in/AUX/{n}/vph`;
# `/bus/2/send/MX4/mode` is `/bus/{n}/send/MX{n}/mode`. Letters are kept,
# so LCL's `vph` and AUX's are different families -- the group is exactly
# what differs between one model's panel and another's.
#
# **The cut-off is 3.** Once three of a family have gone unanswered and
# none has answered, the read confirms the desk is still there -- one
# re-read of the last address that DID answer -- and, if it answers,
# stops asking for the rest of the family. Three rather than one or two
# because a single dropped datagram on a busy network must not cost a
# family; three in a row, with the desk answering its neighbours, is a
# pattern. It bounds a missing family at 9s instead of 3s per member:
# The 320 would have been 3 x 4 families = 12 timeouts, 36s rather
# than 960s.
#
# **What it never does:** skip a family any member of which has answered
# (so no address that answers is ever skipped once its family has shown
# it exists), or skip anything when the desk has stopped answering
# altogether -- a failed liveness check means the link, not the family,
# and the read carries on exactly as before. The skipped addresses are
# unknown, never "off": they are not in `values`, the same as an address
# that timed out, and the read says which families it stopped asking for,
# at INFO, in its end-of-read summary.
UNANSWERED_FAMILY_CUTOFF = 3

_FAMILY_DIGITS = re.compile(r"\d+")


def address_family(address: str) -> str:
    """`/io/in/AUX/3/vph` -> `/io/in/AUX/{n}/vph`. See above."""
    return _FAMILY_DIGITS.sub("{n}", address)


class UnansweredFamilies:
    """Bookkeeping for the cut-off above, for one read.

    `should_ask(address)` before each request, `record(address, answered)`
    after it. `alive` is how to ask the desk whether it is still there:
    a callable that re-reads one address and says whether it answered.
    """

    def __init__(self, alive: Callable[[str], bool],
                 cutoff: int = UNANSWERED_FAMILY_CUTOFF) -> None:
        self.cutoff = cutoff
        self._alive = alive
        self._answered: set[str] = set()
        self._missed: dict[str, int] = {}
        self._last_answered: str | None = None
        self.cut: set[str] = set()
        self.unasked: dict[str, list[str]] = {}

    def should_ask(self, address: str) -> bool:
        family = address_family(address)
        if family in self.cut:
            self.unasked.setdefault(family, []).append(address)
            return False
        return True

    def record(self, address: str, answered: bool) -> None:
        family = address_family(address)
        if answered:
            self._answered.add(family)
            self._last_answered = address
            return
        if family in self._answered:
            return
        self._missed[family] = self._missed.get(family, 0) + 1
        if self._missed[family] < self.cutoff or self._last_answered is None:
            return
        probe = self._last_answered
        if self._alive(probe):
            self.cut.add(family)
        else:
            # The desk itself went quiet. Not this family's fault, and not
            # worth another liveness check until something answers again.
            self._last_answered = None


def is_name_address(address: str) -> bool:
    """Whether `address` is a name -- `/ch/3/name`, `/dca/2/name`,
    `/io/in/LCL/5/name` -- and so one a live watch reads at Start and on
    each refresh rather than every reading."""
    return address.rsplit("/", 1)[-1] == "name"


def _take_known_name(values: dict[str, object], names: Mapping[str, object],
                     address: str) -> bool:
    """If `address` is a name already in hand, copy it into `values`
    (when it was answered) and say so: the caller does not ask for it."""
    if not is_name_address(address) or address not in names:
        return False
    known = names[address]
    if known is not None:
        values[address] = known
    return True


def names_read(state: ConsoleState, plan: list[tuple[str, str]]) -> dict[str, object]:
    """Every name a full reading of `plan` asked for, from `state`: the
    plan's own name addresses plus the second pass's source-socket names
    (`source_name_addresses`), each mapped to the text read or to None
    when the desk did not answer it. What `read_console_state(names=...)`
    takes, so a later reading neither asks for these again nor
    mistakes an unanswered one for one it has not tried."""
    asked = [address for address, _ in plan if is_name_address(address)]
    asked += [address for address, _ in source_name_addresses(state)]
    return {address: state.values.get(address) for address in asked}


def read_console_state(
    console,
    *,
    channels: int = 40,
    aux: int = 8,
    buses: int = 16,
    mains: int = 4,
    matrices: int = 8,
    dcas: int = 16,
    mute_groups: int = 8,
    fx_slots: int = console_facts.FX_SLOTS,
    input_sockets: dict[str, int] | None = None,
    output_sockets: dict[str, int] | None = None,
    console_model: str | None = None,
    progress=None,
    bulk: bool = False,
    names: Mapping[str, object] | None = None,
    extra: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
) -> ConsoleState:
    """Walk exactly the addresses this module's rules/graph consume, over
    an already-connected `atoo.console.WingConsole`. Confirmed WING
    Compact defaults for the fixed-count objects (`atoo/compiler.py`'s
    own CONSOLE_*_CAPACITY constants); physical socket counts have no such
    confirmed default (they depend on the model and any expansion cards),
    so `input_sockets`/`output_sockets` default to none read at all rather
    than a guessed number -- pass e.g. `{"LCL": 20}` for what your rig
    actually has.

    That library default is unchanged, but it is no longer what a CLI run
    gets: `socket_groups_to_read()` above derives the groups from the
    model the desk states and the plan in hand, and the CLI passes them
    (nothing ever passed this argument, so four rules had
    never once run against real hardware).

    `console_model` rides along on the returned state, because what counts
    as a factory-default patch is a fact about the model
    (`console_facts.FACTORY_INPUT_PATCHES`). It costs no extra OSC traffic
    to know: every online command opens with the `/?` identity request,
    and `WingConsole.identity()` remembers the model the desk named there,
    so the default here is to ask the console object what it was already
    told. Pass it explicitly to override, or when the console object is
    not a `WingConsole`.

    `progress` is a `atoo.progress.ReadProgress` (or anything with
    its two methods). This read is 6,143 addresses on a
    Compact -- then one serial round trip each; by default now 323
    requests, pipelined eight in flight -- and it used to print
    nothing at all for the whole of them, which at the desk is
    indistinguishable from a hang. Optional here so the
    library stays quiet by default; the CLI always passes one.

    `bulk=True` fetches most of those addresses with node dumps instead
    -- one `,s *` query per object rather than one GET per leaf, 323
    requests instead of 6,143 on a Compact (protocol PDF p24-25, and
    `atoo.console.parse_node_dump`). It changes where a value comes
    from, which is the one thing this tool may not get wrong, so it was
    held to a hardware comparison before anything used it by default.
    Every leaf a dump does not carry, and every leaf in
    `DUMP_UNSAFE_LEAVES`, is still read on its own, so a missing leaf is
    never mistaken for a default; a dump that does not parse falls back
    to per-leaf for that node.

    A11 has run that comparison three times. The first
    (2026-09-22) found eight disagreements,
    all `/aux/{n}/in/conn/in`, and the second 32, all
    `/io/in/USR/{n}/user/in` -- both the per-leaf read one low, both now
    in `console_facts._READBACK_INDEX_OFFSETS`. The third
    (desk run A11, session 2026-09-24-1045) found **5,860
    values each way, 0 on one side only, 0 differing**, 4.8s against
    118.8s. So the CLI (`cli._console_read_kwargs`) and the
    Watch page (`webui._DEFAULT_READ_KWARGS`) pass `bulk=True`, with
    `--per-leaf` as the way back. The 304 insert/FX-slot addresses an earlier change added after that run are the next run's to compare.

    **This function's own default stays `bulk=False`, on purpose.**
    Desk script A11 (`a11-read-speed.sh`) -- the comparison itself --
    calls it with no `bulk` argument as its per-leaf side. Flip the
    default and that harness compares the dump with itself and reports a
    zero that proves nothing. `tests/test_read_path_default.py` pins it.

    `names` is the names already in hand: address -> the
    text read for it, or None when it was asked and not answered
    (`names_read`). Every name address in it -- a strip's, a bus's, a
    DCA's, a mute group's, and a source socket's in the second pass -- is
    taken from it instead of asked again, and drops out of the progress
    total. A name address NOT in it is read as usual, which is what a
    socket a strip was patched to since the last refresh needs. A live
    watch passes it on every reading between refreshes
    (`watch.refreshing_names`), saving 88 requests on a Compact; None,
    the default, reads every name, which is what every other caller
    wants. Only names: `tags`, `clink` and everything else are read every
    time.
    """
    if console_model is None:
        console_model = getattr(console, "console_model", None)
    values: dict[str, object] = {}
    plan = console_read_plan(
        channels=channels, aux=aux, buses=buses, mains=mains,
        matrices=matrices, dcas=dcas, mute_groups=mute_groups,
        fx_slots=fx_slots,
        input_sockets=input_sockets, output_sockets=output_sockets, extra=extra)
    if names is not None:
        # The names in hand go straight into the reading and
        # out of the plan, so neither path asks for them nor counts them.
        plan = [(address, value_type) for address, value_type in plan
                if not _take_known_name(values, names, address)]

    # Bound what a family of addresses this model does not
    # have can cost. The liveness check re-reads an address that already
    # answered, outside the progress count -- it is not part of the plan.
    families = UnansweredFamilies(lambda address: console.get(address) is not None)

    def finished() -> ConsoleState:
        return ConsoleState(values, console_model=console_model,
                            unasked_families=dict(families.unasked))

    # Imported here, not at module scope: `atoo.console` is the
    # network layer and this module is imported by `atoo build`,
    # which never opens a socket. Same reason `cli.py` imports it lazily.
    from atoo import console as osc

    def on_start(address: str) -> None:
        if progress is not None:
            progress.start_address(address)

    def read_all(pairs) -> None:
        """Every `(address, type)` in `pairs`, with up to the console's
        window of GETs in flight (`osc.read_in_windows`; one
        at a time for a window of 1, as this always was)."""
        pairs = list(pairs)
        replies = osc.read_in_windows(console, [address for address, _ in pairs],
                                      should_ask=families.should_ask, on_start=on_start)
        for (address, value_type), (_address, reply) in zip(pairs, replies):
            take(address, value_type, reply)

    def take(address: str, value_type: str, reply) -> None:
        # A naive `reply.args[0]` broke on any multi-arg reply
        # where the first argument isn't the value this project wants --
        # confirmed on real hardware for a fader/level at -infinity dB,
        # whose `,sff` reply's raw-text first argument is the literal
        # string "-oo" (also WING's own notation for it in the parameter
        # map's schema), not a float `args[0]` can be blindly handed to.
        # `OscReply.value()` (console.py) is the same extraction apply.py
        # already relies on for write verification -- shared here rather
        # than reimplemented, so both call sites trust one confirmed rule.
        if reply is osc.SKIPPED:
            # A family the desk has shown it does not have.
            # Not asked, so not a value -- unknown, as if it had timed out.
            if progress is not None and hasattr(progress, "skip_address"):
                progress.skip_address(address, address_family(address))
            return
        if progress is not None:
            progress.finish_address(answered=reply is not None)
        families.record(address, reply is not None)
        if reply is None:
            return
        value, error = reply.value(value_type)
        if error is None:
            # An earlier change, and the same correction `apply._extract_reply_value`
            # makes: WING's GET reply for a patch connector is one less than
            # the value its SET takes. `in/conn/in` is in STRIP_FIELDS above,
            # so every consumer of a ConsoleState saw that off-by-one --
            # CV005's patch diff, the `patch` watch condition, and the
            # Watch UI. Reported as a socket number one lower than the desk
            # really has, which for a watch condition asserting a patch is a
            # false alert, and for the conventions diff a false difference.
            values[address] = console_facts.correct_readback_index(address, value)

    def read_source_names() -> None:
        """The second pass: the name on every socket a
        strip turned out to be patched to.

        It cannot be in `console_read_plan`, which is pure and knows no
        patches -- which socket to ask about is not knowable until the
        first pass has read one. Up to one address per **patched** strip,
        deduplicated, and nothing at all for an unpatched one: 26 on a
        factory Compact (24 LCL channels plus the two media auxes), 6,143
        -> 6,169. That is the price of seeing a strip somebody named by
        hand, which reads as blank at `{base}/name` on a WING -- see
        `source_is_named`.

        Plus, what is fitted in any expansion bay the
        first pass found something patched from or routed to
        (`expansion_bay_addresses`): at most two more, and none on a
        factory desk.

        Plus, where TALK A and TALK B are routed -- 56
        switches, asked only when talkback is assigned to a strip
        (`talkback_addresses`), so none on a factory desk.

        Plus, `clink` for each of those same patched
        strips (`custom_link_addresses`) -- another 26 on a factory
        Compact, 5,834 -> 5,860. Without it `effective_name` can only
        ever take its "flag never read" branch, which prefers a strip's
        own name however stale, and N001 called two differently named
        channels on a live full-size WING a duplicate.

        Plus, the output patch of every AES50 port
        the desk reports a device on (or a strip takes its input from)
        that the first pass did not read (`aes50_output_addresses`): 96
        per port in use, none on a desk with nothing on AES50.

        Read per leaf even under `bulk`: `name` is in
        `DUMP_UNSAFE_LEAVES`, so a node dump would not have carried it
        anyway.
        """
        first = ConsoleState(values, console_model=console_model)
        sources = (source_name_addresses(first)
                   + custom_link_addresses(first)
                   + expansion_bay_addresses(first)
                   + talkback_addresses(first)
                   + aes50_output_addresses(first))
        if names is not None:
            sources = [(address, value_type) for address, value_type in sources
                       if not _take_known_name(values, names, address)]
        if progress is not None and hasattr(progress, "add_total"):
            progress.add_total(len(sources))
        read_all(sources)

    if not bulk:
        read_all(plan)
        read_source_names()
        return finished()

    by_node, alone = group_plan_by_node(plan)
    if progress is not None:
        progress.set_total(len(by_node) + len(alone))
    dumps = osc.node_dumps(console, list(by_node), on_start=lambda node: on_start(node + " (node)"))
    for (node, wanted), (_node, dump) in zip(by_node.items(), dumps):
        parsed: dict[str, str] = {}
        if dump is not None:
            try:
                parsed = osc.parse_node_dump(node, dump)
            except osc.NodeDumpError:
                # A dump this parser will not guess at costs the node's
                # leaves one round trip each, and nothing else. See
                # `parse_node_dump`: half a dump is worse than none.
                parsed = {}
        if progress is not None:
            progress.finish_address(answered=dump is not None)
        for address, value_type in wanted:
            text = parsed.get(address)
            if text is None:
                # Absent from the dump is NOT "unset" and NOT a default:
                # it is a leaf the dump did not mention, and the only
                # honest thing to do with it is go and ask.
                alone.append((address, value_type))
                if progress is not None:
                    progress.add_total()
                continue
            value, error = osc.value_from_dump_text(text, value_type)
            if error is None:
                # Deliberately NOT `correct_readback_index`: a dump
                # carries the text form, which is already the number the
                # desk shows. See `console.value_from_dump_text`.
                values[address] = value
            else:
                alone.append((address, value_type))
                if progress is not None:
                    progress.add_total()

    read_all(alone)

    read_source_names()
    return finished()
