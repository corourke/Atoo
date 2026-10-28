"""O2's real use case: the **amend** path (FR-2.1-FR-2.5).

This is also the back half of `atoo patch`, where the
change is typed in plain English and `atoo/patch.py` merges it onto
the plan on the desk before `plan_amendment` sees it (`by="the change"`).
And since then no confirmed run replaces `plan.json`: the effective plan is
recorded in the desk's journal entry instead (FR-2.8 as amended). Where
this docstring or the ones below speak of `plan.json` being replaced, they
describe the earlier behaviour, now superseded.

The horn section has turned up late in the setup window. The show is
already built on the desk, there is a mix on it, and **nothing already in
use may move**. What the user holds is an applied plan, a console and a
journal. What they need out is a **delta plan they review before it is
written**.

**This is a setup-and-rehearsal operation, not a mid-show one, and it is
not recommended as one.** Amend is not for use during a show. After the
board is patched, any good engineer saves a snapshot so a misstep isn't
catastrophic before the show starts, and during the show an engineer
would not be making configuration changes unless there was a problem.
So the stakes here are a reload from the engineer's own
snapshot, not a ruined night -- which is a reason to be accurate about
what this module does, and not a reason to be casual about it. A reload
costs the rehearsal window, and nobody thanks a tool for one.

`apply.py` is the full build: it writes every object the plan states, to
a desk that is assumed to be ours to define. This module is the other
half, and it is deliberately built *beside* that path rather than inside
it -- `apply_plan` is unchanged except for one new keyword pair
(`target_filter`/`journal_scope`), and every write still goes through the
same readback proof and the same journal.

The word is **amend**, not append: changes can add
or take away. The motivating case is the horn section arriving, but the
same operation covers a vocalist who has left, a keyboard rig that went
stereo, and a set of delay speakers dropped from the rider. What this
module writes is both halves: new objects are placed on free strips, and
a channel the rebuild dropped has its strip **returned to free** --
back on its factory input patch (or OFF, see below), name/colour/icon
cleared, the processing this plan set undone, and left UNMUTED (`ChangeKind.RELEASED`).
What it refuses to write is a strip already in use, including one that
was ours when the plan was applied and is somebody else's now.

## Four capabilities, in the order the flow uses them

1. **A scoped occupancy read** (`read_occupancy`, `strip_occupancy`).
   Which strips are ours, which are somebody else's, which are free.
   Four addresses per strip -- name, `clink`, and the two halves of the
   input patch -- and then the name of every socket a strip is patched
   to: about 200 on a Compact's 40+8 strips, against
   `audit.read_console_state`'s full sweep of some six thousand. The
   budget comes from the Build-page design ("~150 addresses
   and about four seconds"), and the reason is that a sit-down audit is
   not what is available when the horns walk in. It is over that budget
   because the mockup's figure predates knowing where a name lives --
   see `OCCUPANCY_STRIP_FIELDS`, which is the most important comment in
   this file.

   Two rules, and neither is negotiable.

   **An address we could not read is UNKNOWN, and unknown is not free.**
   OPTIONS-H states it as the rule this whole path stands on: *"33-40
   never answered and therefore occupied, not free -- an unread strip is
   not a safe strip."* `ConsoleState` already keeps that distinction
   (`flag()` returns None for an unread address, never a confirmed 0);
   `StripStatus` is where it becomes a decision.

   **A name a human types lands on the SOCKET, not the strip.** Measured
   2026-09-22 on a real desk, and it nearly cost this module its whole
   reason for existing: a strip named "Podium" by hand reads *empty* at
   `/ch/20/name`, carries the name at `/io/in/LCL/20/name`, and sits on
   its factory patch -- free by every other measure, and somebody's live
   channel in fact. **That reading is `audit.is_in_use`'s now, not this
   module's**: it is the catalogue's own definition of "in
   use" and had the identical blind spot, so the socket-name arm moved
   there and `strip_occupancy` calls it. What stays here is the part that
   is genuinely this module's: turning an *unread* socket name into
   UNKNOWN rather than into "not named".

2. **A delta plan** (`plan_amendment`). Given the applied plan, the
   occupancy read and an *amended* plan -- the same bundle rebuilt from
   the same conventions layers with the new requirement added -- work out
   which objects are new, place them on free strips **skipping occupied
   ones and never renumbering existing ones** (FR-2.1, FR-2.3, D8), and
   produce the `effective_plan` those writes come from.

   Identity is the **strip number**: channel strips are tracked by the
   channel number, not the input/output socket and not the name, because
   the channel strips are the limited resource on the board. The
   *source* still has to be matched
   by name to tell "this is the Kick we already applied" from "this is a
   new channel that happens to want slot 5", and that is what
   `_source_key` does -- but the thing being protected is the strip.

3. **A scoped apply** (`apply_amendment`). Writes only the new objects,
   with the same `--confirm` arming, the same readback proof and the same
   journal -- and the journal now records **its scope**
   (`{"strips": ["ch:21", "ch:22", "ch:23"], ...}`), because "what was
   this run allowed to touch" is the first question anyone asks of a
   journal written against a running desk and `apply.py`'s journal
   could not answer it. It records `released` alongside `strips`,
   because "we wrote this strip" and "we cleared this strip" are
   different answers to that question.

4. **The "what will NOT be written" set** (`AmendmentTargets.withheld`),
   computed and reviewable *before* anything is written. OPTIONS-H is
   explicit that **the target filter, not a fader flag, is the safety
   mechanism**, and the module docstring in `apply.py` that says
   otherwise is corrected in this PR. `set_fader_levels=False` suppresses
   `fdr`/`mute` and nothing else -- it would still rewrite an existing
   strip's name, patch, tags and every send. Filtering the targets is the
   only thing that satisfies FR-2.2's *"shall not modify **any**
   parameter belonging to a channel not named in the delta"*, and a
   strip the amend does not own never has an address generated for it at
   all.

   FR-2.2 also asks for a proof rather than a restraint: read every
   unrelated address before the delta and again after, and assert
   equality. `witness_addresses` / `read_witness` / `witness_changes`
   are that read, and the withheld set is exactly what it reads.

   **A preview does not run it, and a confirmed run reads it cheaply**
   (off A15's ~15 seconds on hardware). The two halves:

   * A preview writes nothing, so there is nothing for a before/after
     read to prove -- 672 addresses read twice, at 6.75ms each, to
     establish that a run which sent no packets moved no values was ~9.1s
     of a ~15s run. `witness_plan` reports the set and reads none of it.
     **It takes "is this a confirmed write" and "did the user skip the
     proof" as separate arguments on purpose**: making a preview cheap
     and weakening a real write's proof must not be the same switch.
   * A confirmed run keeps both passes and makes them cheap by fetching
     them through the node-dump path (`read_witness(bulk=True)`):
     ~10.3ms per *request* rather than per address, and A15's 672
     addresses live under 139 requests. 4.54s a pass becomes 1.43s.

   **The set is never narrowed to save time.** A smaller witness set is a
   weaker proof, and FR-2.2 exists precisely to make the stronger claim
   -- "not merely by not writing to it". What got faster is the read
   path, not the list.

**And before any of it is offered for arming, apply's pre-flight**
(`preflight`): `verify_plan` over the effective plan against
the desk's model, and the socket check over the sockets this amend
writes. A socket the desk does not have is refused by name, whatever
`--skip-verify` says -- it is the one kind of finding that counts as an
error of patching rather than of judgement.

## Three independent guards, because one is not enough

A prefix matcher is code, and code has bugs. So the scope is checked
three ways, and any one of them failing stops the run:

- `AmendScope.allows` is **default-deny**: an address is written only if
  it sits under a base this amendment explicitly granted, each grant
  carrying the reason it exists (`AmendScope.why`).
- `AmendmentTargets.collisions` re-derives the question from the other
  side: build the write targets **the applied plan itself would
  produce**, and intersect. An address both plans write is an address of
  a running strip, whatever the prefix matcher thinks. It is a blocking
  error, not a warning.
- The before/after witness read proves it on the actual desk.

## Removal: tracked state may be cleared, untracked state may not

What happens to a strip that is taken out of the plan but is still
patched and live was left open. The answer, chosen on
2026-09-23 between "report it", "mute it" and "return it to free", is
to return it to free, whether this is for a rebuild of the plan or an
amend: channels are not an unlimited resource and the tool should do
what the engineer is asking for.

So a dropped channel's strip is **returned to free** -- back on its
factory input patch, its
name, colour and icon cleared on the strip *and on the source socket*
(with `clink` on, the socket is where the name the desk shows lives), and
the `flt`/`in/set`/`eq`/`peq` processing this plan's own build wrote put
back to the reading an untouched strip gives. The end state is that
reading throughout (`console_facts.FACTORY_STRIP_*` and
`FACTORY_STRIP_PROCESSING`, measured off the A13 and A8 captures), so the
next person allocating a strip finds this one genuinely free rather than
nearly free.

**Two things the first hardware run corrected.** A15 on
2026-09-23 cleared a strip that came back still muted and still carrying
the plan's 120Hz high-pass -- neither of which is what an untouched strip
reads, and both of which the release's own success test ruled out.

* The **mute is an end state, written once**: OFF, last (an untouched WING
  strip is unmuted). It was a bracket, ON first; two writes to one address
  cannot be counted by a preview, so the fader goes to -inf first instead
  and silences the strip while the rest is cleared.
* The **processing block is cleared**, and the set is derived from the
  build rather than listed, so the bound stays exactly "undo what this
  plan wrote, never more" -- a filter the plan never stated is never
  generated, so there is nothing of somebody else's to clear.
* **Head-amp gain is out of scope and stays out.** It lives on the
  socket, it is shared by every strip on a split, and nobody has said
  what a freed socket's gain should read.

Its **fader goes to -inf**, the reading every
untouched strip gives, just before the closing unmute -- the one level
`apply.py` ever sets on a strip no plan is building, and not a choice:
once the strip is back on its factory socket and routed to Main 1, a
fader left at the plan's level would pass a stray source to the PA.

**The patch goes OFF** (decided 2026-10-20, matching a full apply's
reset: a strip no plan uses is left unpatched, so "free" means one thing
whichever way a strip got there). The patch it replaces, decided earlier
to return to the factory socket, is gone. The occupancy read still takes
a strip on its factory socket as free, so a desk initialized by hand
reads free too.

* Every release says which it did, at INFO, and why.
* A strip back on its factory patch reads **FREE** on the next occupancy
  read, because `audit.is_in_use` discounts the factory patch -- and
  `strip_occupancy` fills in the plan's model when the reading has none,
  as `audit.run_audit` does, so an offline replay agrees with the desk.

**The line the whole feature turns on is tracked versus untracked, and it
is not the same line as "the plan mentions it".** The plan mentioning the
strip is necessary and not sufficient -- the plan was applied some time
ago and people have been at the desk since. `release_refusal` checks the
fresh occupancy read against what the applied plan actually wrote, and
refuses on any disagreement: an address that did not answer, a patch we
did not make, a strip name we did not write, or a **source socket** name
we did not write. The channel 20 fails the last of those and
only the last of those, which is why it is there: blank at `/ch/20/name`,
sitting on the Compact's factory `LCL 20`, named 'Podium' at
`/io/in/LCL/20/name`. A refused removal is reported as
`ChangeKind.REMOVED` and the strip is not touched.

A plan applied to a dirty board leaves whatever it did not
mention -- is a **different** question and is not answered here. That one
is about untracked state, and the answer there is still "report".

## What is NOT built here, said plainly

- **Modifying an existing strip from a rebuild is refused, not written.**
  A strip whose source is unchanged but whose settings the amended plan
  alters (`ChangeKind.MODIFIED`) is precisely a strip already in use, and
  a rebuild names no fields, so D14 forbids touching it. It is reported so
  the engineer can see what a full re-apply would do, and skipped. A
  TYPED change (`atoo patch`) may edit a running
  object, but only in the fields it names: `FieldEdit` and `_plan_edits`,
  section 2b.
- **The occupancy read covers strips only.** Busses, DCAs, mute groups
  and output sockets are judged against the *applied plan* alone -- if
  the plan does not claim bus 9, this module treats bus 9 as available.
  That is stated at INFO on every amendment that adds one, because it is
  a weaker claim than the one made about a strip.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum

from atoo import apply as apply_module
from atoo import console_facts as facts
from atoo import audit
from atoo import plan_compat
from atoo.audit import ConsoleState, is_in_use, source_is_named
from atoo.verify_plan import resolve_console_model


#: The provenance of an output the plan did not know and a patch read off the
#: desk: its sockets were not read, so dropping it leaves
#: them patched as they are.
READ_FROM_DESK = "read from the desk: not built by Atoo"


# --------------------------------------------------------------------------
# 1. The scoped occupancy read
# --------------------------------------------------------------------------

# Four leaves per strip, and then one more per strip that is patched.
#
# `name` and the two halves of `in/conn` are what `audit.is_in_use` needs:
# it reads a strip as in use when it is named (discounting WING's factory
# `CH01`/`AUX03` labels) or patched to anything other than the patch the
# desk shipped with. Its third arm, "is it sending anywhere", would cost
# another 28 addresses per strip and turn a four-second read into a
# forty-second one, so it is left out -- see `occupancy_summary`, which
# says so out loud rather than leaving it for a reader of this comment.
#
# ## `clink`, and the strip whose name is not on the strip
#
# The fourth leaf is `clink`, and it is here because of a failure that
# would have been catastrophic and was very nearly invisible: **a name a
# human types on a WING lands on the SOURCE SOCKET, not the strip**, so a
# strip read only at `{base}/name` reads as unnamed however plainly a
# person named it. A real show's channel 20 was blank at `/ch/20/name`,
# carried `'Podium'` at `/io/in/LCL/20/name`, and sat on a Compact's
# factory patch -- free by every other measure, and somebody's live
# channel in fact.
#
# **The whole of that story, and the code, now live in `audit.py`**: `audit.source_is_named`, `audit.is_factory_source_label`
# and `audit.source_name_addresses`, because `audit.is_in_use` is the
# catalogue's own definition of "in use" and had exactly the same blind
# spot. This module kept a private copy for one PR while `audit.py` was
# claimed by another change; it does not any more, and `strip_occupancy`
# below calls the shared definition rather than a second one that can
# drift.
#
# What stays here is the *reading*: `clink` is per strip, so it is read
# rather than assumed -- `apply.py` deliberately sets it to 0 for a socket
# shared between two strips, and on those the strip's own name is the real
# one -- and for every strip that is patched, the source socket's name is
# read too (`source_name_addresses`, the second pass).
#
# **The audit now reads `clink` too**, in its own second pass
# and only for patched strips (`audit.custom_link_addresses`). This module
# keeps it in the FIRST pass because an occupancy read is four addresses
# per strip and the saving would be noise; an audit is 119, and there the
# distinction between a patched strip and a bare one is worth 22
# addresses. Same flag, same meaning, two read plans that can differ about
# when to ask without differing about the answer.
OCCUPANCY_STRIP_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "s"),
    ("clink", "i"),
    ("in/conn/grp", "s"),
    ("in/conn/in", "i"),
)

# The two banks of full input strips. Same order `audit.console_read_plan`
# walks them in, so two readings of the same desk are comparable.
OCCUPANCY_BANKS: tuple[str, ...] = ("ch", "aux")


class StripState(str, Enum):
    """What one strip is, as far as an amendment is concerned.

    A `str` mixin for the same reason `audit.Severity` and
    `audit.RuleScope` are: `StripState.FREE == "free"` is True and
    `json.dumps` needs no encoder.
    """

    #: Claimed by the applied plan. This show's own strip -- running.
    OURS = "ours"
    #: Not in the applied plan, and the desk says something is on it.
    THEIRS = "theirs"
    #: Read, not claimed, and the desk says nothing is on it.
    FREE = "free"
    #: At least one of its three addresses never answered. **Not free.**
    UNKNOWN = "unknown"

    __str__ = str.__str__


@dataclass(frozen=True)
class StripStatus:
    """One strip's verdict, with the reading it was reached from.

    `unread` is the whole point of this dataclass existing rather than a
    plain `dict[str, bool]`: it names the addresses that never answered,
    so a refusal can say *which* read failed rather than "something did".
    """

    base: str
    bank: str
    number: int
    state: StripState
    name: str | None
    patch: tuple[str, int] | None
    unread: tuple[str, ...] = ()
    #: The name on the SOURCE SOCKET this strip is patched to, when the
    #: strip is linked to it (`clink`). On a WING this is where a name a
    #: human typed actually lives, and on "Podium" it is the only place
    #: it lives -- see `OCCUPANCY_STRIP_FIELDS`.
    source_name: str | None = None
    #: Read in full, and nothing is on it -- no name, nothing on its socket,
    #: the factory patch -- whatever the verdict. Only interesting on an OURS
    #: strip: the applied plan claims it, and the desk says it is empty, so
    #: the plan may describe a different desk (`atoo amend` warns).
    reads_free: bool = False

    @property
    def available(self) -> bool:
        """May an amendment place a new object here?

        Only `FREE`. `OURS` is running, `THEIRS` is somebody else's, and
        `UNKNOWN` is the one that has to be got right: an address we
        could not read is not evidence of an empty strip, it is an
        absence of evidence, and OPTIONS-H's rule is that the absence
        counts as occupied.
        """
        return self.state is StripState.FREE

    @property
    def label(self) -> str:
        """`ch:21`, the form `--allow-strip` takes and the journal records."""
        return f"{self.bank}:{self.number}"


def occupancy_read_plan(*, channels: int = facts.CAPACITY["ch"],
                        aux: int = facts.CAPACITY["aux"]) -> list[tuple[str, str]]:
    """Exactly the addresses an occupancy read asks for, with the OSC type
    each is read as, in the order they are read.

    Pure -- it contacts nothing, the same contract
    `audit.console_read_plan` has, and for the same reason: the CLI
    counts it to tell the user what they are waiting for, and a test can
    assert the budget without a desk.
    """
    plan: list[tuple[str, str]] = []
    for bank, count in zip(OCCUPANCY_BANKS, (channels, aux)):
        for n in range(1, count + 1):
            for suffix, value_type in OCCUPANCY_STRIP_FIELDS:
                plan.append((f"/{bank}/{n}/{suffix}", value_type))
    return plan


def source_name_addresses(state: ConsoleState, *,
                          channels: int = facts.CAPACITY["ch"],
                          aux: int = facts.CAPACITY["aux"]) -> list[tuple[str, str]]:
    """The **second pass**: `/io/in/{grp}/{socket}/name` for every strip
    the first pass found patched somewhere.

    It cannot be part of `occupancy_read_plan`, because which socket to
    ask about is not knowable until the patch has been read. Up to one
    address per strip, so the whole read is 4 per strip plus at most 1 --
    240 on a Compact rather than 192, and in practice fewer, because an
    unpatched strip has no source to ask about.

    Deduplicated: one socket feeding two strips is a normal request
    (`atoo/domain/knowledge.md`), and asking twice would be a round
    trip spent on an answer already in hand.

    This is `audit.source_name_addresses` scoped to the
    strips a Compact-shaped occupancy read walks. The audit's full read
    needs the identical second pass and had none, and two functions that
    must produce the same address for the same patch are one function.
    This one stays because the two callers differ in what they know: an
    occupancy read knows the counts it asked for and must ask about a
    strip whose own leaves went unanswered too, while the audit can take
    the strips its state actually has.
    """
    return audit.source_name_addresses(
        state,
        [f"/{bank}/{n}" for bank, count in zip(OCCUPANCY_BANKS, (channels, aux))
         for n in range(1, count + 1)],
    )


def read_occupancy(console, *, channels: int = facts.CAPACITY["ch"],
                   aux: int = facts.CAPACITY["aux"],
                   console_model: str | None = None,
                   progress=None) -> ConsoleState:
    """Walk `occupancy_read_plan` over an already-connected console.

    Returns an ordinary `audit.ConsoleState`, so everything downstream --
    `is_in_use`, the Watch page, a state file saved for later -- reads it
    the same way it reads a full sweep. An address that does not answer
    is simply **absent** from `.values`, which is what makes the UNKNOWN
    verdict possible; nothing here ever fills in a default.

    Deliberately not a thin wrapper over `audit.read_console_state` with
    smaller counts: that function's address plan is the audit's, and
    trimming it by argument would still read 106 leaves per strip. This
    reads three. The one thing it does copy exactly is the value
    extraction -- `OscReply.value()` plus
    `console_facts.correct_readback_index`, because WING's GET reply for
    a patch connector is one less than the number its SET takes and a patch read without that correction is off by one.

    `console_model` rides along on the returned state for the same reason
    it does on a full read: which patch counts as the factory's own is a
    fact about the model (`console_facts.FACTORY_INPUT_PATCHES`), and
    reading `/ch/3` on `LCL 3` as "in use" on a Compact would refuse
    every free strip on the desk.
    """
    if console_model is None:
        console_model = getattr(console, "console_model", None)
    values: dict[str, object] = {}
    # Lazily, as `audit.py` imports it: the network layer.
    from atoo import console as osc

    def on_start(address: str) -> None:
        if progress is not None:
            progress.start_address(address)

    def read_all(pairs) -> None:
        # Up to the console's window of GETs in flight.
        pairs = list(pairs)
        replies = osc.read_in_windows(console, [address for address, _ in pairs],
                                      on_start=on_start)
        for (address, value_type), (_address, reply) in zip(pairs, replies):
            if progress is not None:
                progress.finish_address(answered=reply is not None)
            if reply is None:
                continue
            value, error = reply.value(value_type)
            if error is None:
                values[address] = facts.correct_readback_index(address, value)

    read_all(occupancy_read_plan(channels=channels, aux=aux))
    # Second pass -- the sockets the first pass found. See
    # `source_name_addresses`, and `OCCUPANCY_STRIP_FIELDS` for why a
    # strip's name is not enough on its own.
    sources = source_name_addresses(
        ConsoleState(values, console_model=console_model), channels=channels, aux=aux)
    if progress is not None and hasattr(progress, "add_total"):
        progress.add_total(len(sources))
    read_all(sources)
    return ConsoleState(values, console_model=console_model)


def _plan_strip_slots(plan: dict | None) -> set[tuple[str, int]]:
    """`{(bank, number)}` for every channel strip a plan claims."""
    slots: set[tuple[str, int]] = set()
    for channel in (plan or {}).get("channels", []) or []:
        if not isinstance(channel, dict):
            continue
        number = channel.get("channel")
        if isinstance(number, int):
            slots.add((str(channel.get("bank", "ch")), number))
    return slots


#: Is a socket name the desk's own label (`'USB 1/2'`, `'2TR'`) rather
#: than somebody's? `audit.is_factory_source_label`, re-exported under the
#: name this module introduced it with -- the definition moved to
#: `audit.py` with the rest of the socket-name arm, and the
#: factory labels it discounts are what keep an untouched Compact's two
#: media auxes from reading as occupied.
is_factory_source_label = audit.is_factory_source_label


def strip_occupancy(state: ConsoleState, applied_plan: dict | None = None, *,
                    channels: int = facts.CAPACITY["ch"],
                    aux: int = facts.CAPACITY["aux"]) -> list[StripStatus]:
    """One `StripStatus` per strip, in read order.

    The four verdicts, and why each is decided the way it is:

    - **OURS** -- the applied plan claims this strip. Decided from the
      plan, not from the desk, and it wins over every other reading: a
      strip this show built is this show's whether or not this read
      of it came back. (The desk's own answer is still carried on the
      status, so a caller can notice that a strip we claim reads as
      empty -- which is worth an eyebrow but is not this function's
      business.)
    - **UNKNOWN** -- any address this verdict depends on never answered,
      including the source socket's name for a patched strip. Checked
      before the desk's answer is interpreted, because interpreting a
      missing answer is exactly the mistake: `is_in_use` reads an unread
      name as "not named" and an unread patch as "not patched", which is
      indistinguishable from a genuinely empty strip.
    - **THEIRS** -- read in full, not ours, and `audit.is_in_use` says
      something is on it -- which includes the **source
      socket** this strip displays carrying somebody's name. A strip named
      `CH01` is not named and a Compact's channel 3 patched to `LCL 3` is
      not patched; channel 20 of the A13 capture is blank at `/ch/20/name`
      and named `'Podium'` on `/io/in/LCL/20/name`, and all three of those
      readings come from one definition rather than from this module's own
      copy of it. `audit.source_is_named` is still consulted separately
      here, for the one thing a bool cannot carry: **None**, the socket
      name that was never read, which is UNKNOWN and not free.
    - **FREE** -- read in full, not ours, nothing on it and nothing on
      the socket it shows.

    Which patch counts as the factory's is a fact about the model, and the
    state's own model wins; a state that never learned one (a `--state`
    file has no slot for it) takes the applied plan's `meta.console_model`,
    exactly as `audit.run_audit` does. Without that, a strip a release has
    just put back on its factory patch -- a Compact's `/aux/1` on USB 1 --
    would read as somebody's on a replay of the same desk, because the
    identity fallback does not know the media auxes.
    """
    if state.console_model is None and applied_plan:
        plan_model = resolve_console_model(applied_plan)
        if plan_model:
            state = replace(state, console_model=plan_model)
    claimed = _plan_strip_slots(applied_plan)
    statuses: list[StripStatus] = []
    for bank, count in zip(OCCUPANCY_BANKS, (channels, aux)):
        for n in range(1, count + 1):
            base = f"/{bank}/{n}"
            unread = tuple(
                f"{base}/{suffix}" for suffix, _ in OCCUPANCY_STRIP_FIELDS
                if f"{base}/{suffix}" not in state.values
            )
            name = state.name(base)
            patch = state.patch(base)
            source_named = source_is_named(state, base)
            source_name = None
            if patch is not None:
                source_name = state.text(f"/io/in/{patch[0]}/{patch[1]}/name")
                if source_named is None:
                    unread = unread + (f"/io/in/{patch[0]}/{patch[1]}/name",)
            reads_free = not unread and not (source_named or is_in_use(state, base))
            if (bank, n) in claimed:
                verdict = StripState.OURS
            elif unread:
                verdict = StripState.UNKNOWN
            elif source_named or is_in_use(state, base):
                verdict = StripState.THEIRS
            else:
                verdict = StripState.FREE
            statuses.append(StripStatus(
                base=base, bank=bank, number=n, state=verdict,
                name=name, patch=patch, unread=unread, source_name=source_name,
                reads_free=reads_free))
    return statuses


def claimed_but_empty(statuses: list[StripStatus]) -> list[StripStatus]:
    """The OURS strips the desk reads as empty -- the applied plan claims
    them and nothing is on them. A handful can be a strip the engineer
    cleared by hand; many usually mean the applied plan is not the one on
    this desk. The caller warns and does not refuse: the verdict stays OURS,
    so nothing is placed on them either way."""
    return [s for s in statuses if s.state is StripState.OURS and s.reads_free]


def occupancy_summary(statuses: list[StripStatus]) -> str:
    """One paragraph a person can read at a desk: how many strips are in
    each state, which are not free, and what this read did not ask.

    The "did not ask" line is not decoration. A read that covers three
    leaves per strip cannot see a strip that is routed but neither named
    nor patched, and a summary that does not say so reads exactly like a
    full sweep that found nothing.
    """
    by_state: dict[StripState, list[StripStatus]] = {}
    for status in statuses:
        by_state.setdefault(status.state, []).append(status)

    def names(state: StripState) -> str:
        return ", ".join(s.label for s in by_state.get(state, []))

    sockets = len({s.patch for s in statuses if s.patch is not None})
    lines = [
        f"{len(statuses)} strip(s) read over "
        f"{len(statuses) * len(OCCUPANCY_STRIP_FIELDS) + sockets} address(es): "
        + ", ".join(
            f"{len(by_state.get(state, []))} {state.value}"
            for state in (StripState.OURS, StripState.THEIRS,
                          StripState.FREE, StripState.UNKNOWN)
        ),
    ]
    for status in by_state.get(StripState.THEIRS, []):
        # Say WHERE the name was found. On a WING a strip somebody named
        # by hand is blank at its own `name` and carries it on the socket,
        # and an engineer looking at a refusal needs to be able to go and
        # look at the same thing the tool looked at.
        if status.source_name and not status.name:
            where = f"named {status.source_name!r} on its source {status.patch[0]} {status.patch[1]}"
        elif status.name:
            where = f"named {status.name!r}"
        else:
            where = "patched to something the desk did not ship with"
        lines.append(f"  in use by somebody else: {status.label} -- {where}")
    if by_state.get(StripState.UNKNOWN):
        lines.append(
            f"  never answered, therefore treated as OCCUPIED: {names(StripState.UNKNOWN)}")
    lines.append(
        "  this read asked each strip for its name, its link-to-source flag and its input "
        "patch, and asked every patched socket for ITS name -- which on a WING is where a "
        "name somebody typed actually lives. It did not ask what anything is routed to, so a "
        "strip that is routed somewhere but neither named nor patched reads as free here. "
        "`atoo audit` asks the rest.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 2. The delta plan
# --------------------------------------------------------------------------


class ChangeKind(str, Enum):
    """What the amendment found for one object, and whether it is written.

    Only `ADDED`, `RELEASED` and `EDITED` are ever written. Every other kind is
    computed so it can be *reviewed* -- the point of the flow is a delta
    the engineer reads before anything goes on the wire, and a change the
    tool silently declined to make is the thing they most need to see.
    """

    #: New object, placed on a free slot. Written.
    ADDED = "added"
    #: In the applied plan, gone from the rebuild, and the desk still
    #: reads as the strip this plan built -- so it is **written**: muted,
    #: back on its factory patch (or OFF), name/colour/icon cleared on the strip and on its
    #: source. The enum's value is the words the summary
    #: line uses, because "1 returned to free" is what an engineer
    #: reads, and "1 released" is not.
    RELEASED = "returned to free"
    #: Present in both plans, same slot, same settings. Nothing to do.
    UNCHANGED = "unchanged"
    #: Present in both plans, same slot, different settings. NOT written
    #: -- this is a strip already in use, and D14 forbids touching it.
    MODIFIED = "modified"
    #: A running object whose NAMED fields a typed change sets (`atoo
    #: patch`): "HPF 100 on the vocals", "move the sax
    #: to MON3". **Written** -- exactly the addresses those fields change
    #: (`FieldEdit`, `_plan_edits`), and not one other address of the
    #: object, which stays in FR-2.2's before/after proof like every
    #: unrelated strip. Only a typed change produces it: a rebuilt plan
    #: names no fields, so an amend's running strips are still MODIFIED.
    EDITED = "edited"
    #: In the applied plan, gone from the amended one, and NOT written --
    #: because the desk no longer reads as the strip this plan built, or
    #: did not answer. Somebody else's work, or an unknown; either way
    #: reported rather than cleared. The clean case is `RELEASED`, and
    #: the `Change`'s own reason says which reading refused this one.
    #: The value stays the plain word so the summary line reads
    #: "3 added, 1 returned to free, 1 removed" -- the distinction that
    #: matters is between the two kinds, not in a longer label.
    REMOVED = "removed"
    #: The same source, moved to a different slot by the rebuild. Refused
    #: -- FR-2.3, "rather than renumbering existing channels".
    RENUMBERED = "renumbered"
    #: New, and there was no free slot for it. Refused, by name (FR-2.3).
    UNPLACEABLE = "unplaceable"
    #: A running channel the change's explicit "insert" moves to the next
    #: strip down to make room: its whole strip is rewritten on the new
    #: number (`Amendment.shift_scope`), one verdict per strip so the review
    #: lists every strip that moves. Written. Only a typed change produces
    #: it; a rebuild that moved a strip is still RENUMBERED, and refused.
    SHIFTED = "shifted"
    #: A typed change (`atoo patch`) that asks for something that cannot be
    #: written -- a send to a bus that is neither on the desk nor added by
    #: the change, a drop of a channel nobody has, a field the object does
    #: not carry, a value out of range. Refused, and the whole change with
    #: it: a strip sent to nothing is a setting the desk cannot be left in
    #: (`patch.merge_change`).
    REFUSED = "refused"

    __str__ = str.__str__


#: The kinds that stop the amendment rather than merely being reported.
BLOCKING_KINDS = (ChangeKind.RENUMBERED, ChangeKind.UNPLACEABLE, ChangeKind.REFUSED)


@dataclass(frozen=True)
class Change:
    """One object's verdict. `where` is the human name ("Horn 1", "bus
    'Horns Wedge'"), `slot` the place it ended up, `proposed` the place
    the amended plan asked for -- the two differ exactly when placement
    had to skip an occupied strip, which is the case worth showing."""

    kind: ChangeKind
    kind_of_object: str  # "channel" | "bus" | "output" | "dca" | "mute group"
    where: str
    reason: str
    slot: str | None = None
    proposed: str | None = None
    #: Who proposed `proposed`: "the rebuild" for an amend, "the change" for
    #: a typed change (`atoo patch`).
    asked_by: str = "the rebuild"

    def line(self) -> str:
        moved = ""
        if self.slot and self.proposed and self.slot != self.proposed:
            moved = f" ({self.asked_by} asked for {self.proposed})"
        at = f" -> {self.slot}{moved}" if self.slot else ""
        # 16, because "RETURNED TO FREE" is the longest kind and the
        # column is what makes a review scannable.
        return f"{self.kind.value.upper():16} {self.kind_of_object} {self.where}{at}: {self.reason}"


#: `(plan key, word)` for the objects a typed change can edit in place.
EDITABLE_WORDS = {"channels": "channel", "busses": "bus", "dcas": "dca",
                  "mute_groups": "mute group", "outputs": "output"}


def format_value(path: str, value) -> str:
    """A field's value as a review line shows it: a patch as the socket it
    names ("A 5", "LCL 3+4"), unset as "(unset)", anything else as compact
    JSON -- cut short, because a review line is read, not parsed."""
    if value is None:
        return "(unset)"
    if path.split(".")[0] == "patch" and isinstance(value, dict) \
            and isinstance(value.get("group"), str):
        sockets = [str(x) for x in value.get("sockets") or []]
        return f"{value['group']} {'+'.join(sockets)}".strip()
    text = json.dumps(value, separators=(", ", ": "), default=str)
    return text if len(text) <= 120 else text[:117] + "..."


def describe_sends(old: list, new: list) -> str:
    """What differs between two `bus_sends` lists, send by send: "MON3
    level -144 -> -10; MON2 removed; Horns added (post, 0)"."""
    def by_bus(sends: list) -> dict:
        return {str(s.get("bus")): s for s in sends if isinstance(s, dict)}

    before, after = by_bus(old), by_bus(new)
    parts: list[str] = []
    for bus, send in after.items():
        was = before.get(bus)
        if was is None:
            parts.append(f"{bus} added ({send.get('mode') or 'mode unset'}, "
                         f"{format_value('level', send.get('level_db'))})")
            continue
        for leaf, label in (("level_db", "level"), ("mode", "mode")):
            if was.get(leaf) != send.get(leaf):
                parts.append(f"{bus} {label} {format_value(leaf, was.get(leaf))} -> "
                             f"{format_value(leaf, send.get(leaf))}")
    parts.extend(f"{bus} removed" for bus in before if bus not in after)
    return "; ".join(parts) or "unchanged"


@dataclass(frozen=True)
class FieldEdit:
    """One field of an object already on the desk that a typed change sets
    -- `processing.hpf_hz` on 'Lead Vox', `bus_sends`
    on 'T.Sax'. Made by `patch.merge_change`, which puts ONLY the fields the
    change names into the merged plan; `plan_amendment` turns each into the
    addresses its value changes, and nothing else of the object is written.

    `path` is dotted, to a leaf where the value is an object (`fader.
    fader_db`, not `fader`), so the review shows old -> new for exactly what
    moves. A list (`bus_sends`, `dca`) is one leaf: the whole list is the
    value."""

    key: str            # plan key: "channels", "busses", "dcas", "mute_groups", "outputs"
    name: str           # the object's name on the desk
    path: str
    old: object
    new: object
    #: "ch:12" for a channel -- a channel is identified by its strip, and a
    #: rename must not lose it. None for a named object.
    slot: str | None = None
    #: False once `plan_amendment` has found that no console address carries
    #: the field -- a mic model, or phantom on a socket group with no 48V
    #: address -- so the review does not say it acts on the desk.
    writes: bool = True

    @property
    def word(self) -> str:
        return EDITABLE_WORDS.get(self.key, "object")

    @property
    def moves_audio(self) -> bool:
        """A physical routing change on a running object: a channel's input
        patch, an output's socket, a bus's destination. It moves audio the
        moment it is written, so the review marks it before anything else."""
        top = self.path.split(".")[0]
        return ((self.key == "channels" and top == "patch")
                or (self.key == "outputs" and top in ("patch", "patches", "fed_by"))
                or (self.key == "busses" and top in ("destination", "destinations")))

    @property
    def switches_phantom(self) -> bool:
        """48V switched on or off on a strip already running. It moves no
        audio between strips, but it is a live hardware change at the
        socket (a pop in the PA, and on a passive ribbon it is damage), so
        the review says it the way it says a repatch."""
        return (self.key == "channels" and self.writes
                and self.path in ("source.phantom", "source.pair_phantom"))

    @property
    def live_marker(self) -> str:
        """The words a review puts in front of an edit that acts on the
        desk the moment it is written, or ''."""
        if self.moves_audio:
            return "MOVES AUDIO LIVE -- "
        return "SWITCHES 48V LIVE -- " if self.switches_phantom else ""

    def describe(self) -> str:
        """`path old -> new`, and for a send list the sends that differ,
        one by one -- a whole list printed twice hides the one level that
        moved."""
        if self.path == "bus_sends" and isinstance(self.old or [], list) \
                and isinstance(self.new or [], list):
            return "bus_sends: " + describe_sends(self.old or [], self.new or [])
        return (f"{self.path} {format_value(self.path, self.old)} -> "
                f"{format_value(self.path, self.new)}")

    def line(self) -> str:
        where = f"{self.word} {self.name!r}" + (f" on {self.slot}" if self.slot else "")
        return f"{self.live_marker}{where}: {self.describe()}"

    def to_json(self) -> dict:
        return {"object": self.word, "name": self.name, "slot": self.slot, "path": self.path,
                "old": self.old, "new": self.new, "moves_audio": self.moves_audio,
                "switches_phantom": self.switches_phantom, "line": self.line()}


class AmendScope:
    """Which addresses this amendment owns -- **default-deny**.

    Grants are *base addresses* with the reason each exists: `/ch/21`
    ("new channel 'Horn 1'"), `/io/in/A/5` ("the socket channel 21 is
    patched to"), `/main/1/send/MX3` ("the feed into the new matrix").
    An address is allowed when it equals a grant or sits directly under
    one, and is refused otherwise. Nothing is implicit, and the reason
    travels with the grant so a review can print *why* each address is
    about to be written rather than only that it is.

    Deliberately not a set of exact addresses: the addresses come from
    `apply._build_write_targets`, which grows a new leaf every time this
    project learns another parameter, and a scope that enumerated leaves
    would silently stop granting them. A scope that grants *objects*
    keeps working, and the thing being protected was always the object.
    """

    def __init__(self, grants: dict[str, str] | None = None):
        self._grants: dict[str, str] = dict(grants or {})

    def grant(self, base: str, reason: str) -> None:
        self._grants.setdefault(base, reason)

    @property
    def grants(self) -> dict[str, str]:
        return dict(self._grants)

    def why(self, address: str) -> str | None:
        """The reason this address is in scope, or None if it is not."""
        for base, reason in self._grants.items():
            if address == base or address.startswith(base + "/"):
                return reason
        return None

    def allows(self, target) -> bool:
        """True if this amendment may write `target` (a `WriteTarget`, or
        a bare address string). The signature takes the whole target
        rather than its address so a future scope can refuse by stage or
        description without every caller changing."""
        address = getattr(target, "address", target)
        return self.why(address) is not None

    def journal_entry(self, strips: list[str]) -> dict:
        """What `apply_plan` records in the journal as this run's scope.

        `strips` first and by itself, because that is the question --
        *which strips was this run allowed to touch* -- that a journal
        written against a running desk has to answer at a glance.
        """
        return {"strips": list(strips), "grants": self.grants}


# --------------------------------------------------------------------------
# 2a. Is this strip still ours? -- the question a removal turns on
# --------------------------------------------------------------------------

# WING's own label for a strip nobody has named: `CH01`, `AUX03`. Mirrors
# `audit._is_active_name`'s regex deliberately rather than importing it --
# that function is the audit's private business and answers a different
# question ("does this look in use"), while this one has to answer "is
# this the reading OUR write left behind, or somebody else's".
_FACTORY_STRIP_LABEL_RE = re.compile(r"^(CH|AUX|BUS|MAIN|MTX|DCA)\s*0*\d+$", re.IGNORECASE)


def _is_ours_or_blank(desk_name: str | None, expected: str | None) -> bool:
    """Is this name one we could have left here?

    True for a name we wrote, for blank, and for the desk's own factory
    label -- all three are readings a strip this plan built can give. Any
    other text is somebody's, and that is the whole of the check.
    """
    if desk_name is None or not desk_name.strip():
        return True
    text = desk_name.strip()
    if expected is not None and text == str(expected).strip():
        return True
    return bool(_FACTORY_STRIP_LABEL_RE.match(text))


def release_refusal(channel: dict, status: StripStatus | None, *,
                    shared_sockets: dict[tuple[str, int], list[str]] | None = None,
                    console_model: str | None = None) -> str | None:
    """Why this strip may **not** be returned to free, or None if it may.

    This is the safety property, and it is worth stating
    without hedging: **a tracked removal may be cleared; untracked state
    may never be.**

    "Tracked" is not "the applied plan mentions it". The plan mentioning
    it is necessary -- `plan_amendment` only ever asks this about a
    channel the applied plan built -- and it is not sufficient, because
    the plan was applied some time ago and the desk has been in front of
    people since. So the fresh occupancy read has to agree that the strip
    is *still* the one we left there. Every reading it took is checked
    against what the applied plan itself wrote, and anything else is a
    refusal:

    - **It did not answer.** An unread address is not evidence of an
      empty strip. OPTIONS-H's rule for placement -- "an unread strip is
      not a safe strip" -- is at least as binding when the write in
      question is a clear.
    - **It is patched somewhere our plan did not put it.** Somebody has
      repatched the strip, so whatever is on it now is not what we built.
      Unpatched is fine: that is a strip somebody has already freed. So
      is its **measured factory patch** (`console_model`), since
      2026-09-24 -- that is what a release now leaves, so a strip an
      earlier run returned to free partway reads that way, and refusing
      it would leave the job half done. Measured only, never the identity
      fallback: a refusal errs towards refusing. The source-name arm below
      still runs, so a Podium on its factory patch is still refused.
    - **Its name is not one we wrote.** Blank counts as ours, and so does
      the desk's own `CH01`; anything else is somebody's.
    - **Its SOURCE carries a name we did not write.** This is the arm the
      other three do not cover, and it is the one that matters. The channel 20 is blank at `/ch/20/name`, sitting on the
      Compact's factory `LCL 20` patch, and named 'Podium' only at
      `/io/in/LCL/20/name` -- because `clink` is on from the factory and a
      name a person types on the desk lands on the socket. A check that
      read only the strip would clear it.

    `shared_sockets` is `apply._shared_source_sockets(applied_plan)`: for
    a socket the applied plan gave to more than one strip, what we wrote
    there is the composite label, not this channel's own name, so that is
    what the socket is compared against.
    """
    bank = str(channel.get("bank", "ch"))
    number = channel.get("channel")
    label = f"{bank}:{number}"
    if status is None:
        return (f"{label} was not covered by the occupancy read, so nothing has established "
                "that the strip is still the one this plan built")
    if status.unread:
        return (f"{label} never answered at {', '.join(status.unread)} -- an unread strip is not "
                "a safe strip to clear")

    patch = channel.get("patch") or {}
    group = patch.get("group")
    sockets = [x for x in (patch.get("sockets") or []) if isinstance(x, int)]
    ours = (group, sockets[0]) if isinstance(group, str) and sockets else None
    factory, _ = facts.measured_factory_input_patch(console_model, bank, number) \
        if isinstance(number, int) else (None, None)
    if (status.patch is not None and ours is not None and status.patch != ours
            and status.patch != factory):
        return (f"{label} is patched to {status.patch[0]} {status.patch[1]}, and this plan "
                f"patched it to {ours[0]} {ours[1]} -- somebody has repatched the strip, so "
                "what is on it now is not what this plan built")
    if status.patch is not None and ours is None:
        return (f"{label} is patched to {status.patch[0]} {status.patch[1]}, and this plan's own "
                "entry for it states no patch -- nothing here can say whose that is")

    name = channel.get("name")
    if not _is_ours_or_blank(status.name, name):
        return (f"{label} is named {status.name!r} on the desk and this plan named it {name!r} -- "
                "somebody has renamed the strip")

    if status.patch is not None:
        shared = (shared_sockets or {}).get(status.patch)
        expected_source = (apply_module._composite_source_name(shared) if shared
                           else (name if status.patch == ours else None))
        if not (status.source_name is None
                or is_factory_source_label(status.patch[0], status.source_name)
                or _is_ours_or_blank(status.source_name, expected_source)):
            return (f"{label}'s source {status.patch[0]} {status.patch[1]} is named "
                    f"{status.source_name!r}, which this plan did not write there -- on a WING "
                    "that is where a name somebody types by hand lands, so the strip is in use "
                    "by somebody else")
    return None


def _source_key(channel: dict) -> str:
    """The identity used to recognise *the same source* across two plans.

    Not the identity of the strip -- that is the channel number -- but the
    answer to "is the Kick we already applied the same
    Kick this rebuild is talking about". Normalised the way
    `compare_plans._norm` normalises, and falling back to the strip name
    for a plan whose `source.input` is absent.
    """
    source = channel.get("source") or {}
    raw = source.get("input") or channel.get("name") or ""
    return re.sub(r"\s+", " ", str(raw)).strip().casefold()


def _channel_slot(channel: dict) -> tuple[str, int]:
    return (str(channel.get("bank", "ch")), int(channel["channel"]))


def _slot_label(slot: tuple[str, int]) -> str:
    return f"{slot[0]}:{slot[1]}"


#: Fields compared to decide UNCHANGED vs MODIFIED. Everything a channel
#: entry carries that `apply.py` turns into a write -- `provenance` and
#: the other bookkeeping are excluded on purpose, since a reworded
#: explanation is not a change to the desk.
_CHANNEL_COMPARED_FIELDS = (
    "name", "color", "col", "icon", "source", "patch", "alt_patch", "processing",
    "fader", "dca", "mute_group", "bus_sends", "main_routes",
)


def _channel_differs(a: dict, b: dict) -> bool:
    return any(a.get(f) != b.get(f) for f in _CHANNEL_COMPARED_FIELDS)


def _patched_sockets(plan: dict | None) -> set[tuple[str, int]]:
    """`{(group, socket)}` every channel in this plan patches from."""
    used: set[tuple[str, int]] = set()
    for channel in (plan or {}).get("channels", []) or []:
        if not isinstance(channel, dict):
            continue
        patch = channel.get("patch") or {}
        group = patch.get("group")
        if not isinstance(group, str):
            continue
        for socket in patch.get("sockets") or []:
            if isinstance(socket, int):
                used.add((group, socket))
    return used


def _indexed_names(plan: dict | None, key: str) -> dict[str, int]:
    """`{name: index}` for a plan's `dcas`/`mute_groups`/`busses` map,
    skipping any entry whose shape is not the one the schema states --
    an amendment is not the place to crash over a hand-edited plan."""
    out: dict[str, int] = {}
    for name, entry in ((plan or {}).get(key) or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("index"), int):
            out[str(name)] = entry["index"]
    return out


@dataclass
class Amendment:
    """The reviewable delta: what changes, where it lands, what it is
    allowed to touch, and what it refuses to do."""

    applied_plan: dict
    amended_plan: dict
    effective_plan: dict
    scope: AmendScope
    changes: list[Change] = field(default_factory=list)
    #: Strip labels this amendment writes to, in order -- the journal's
    #: `scope.strips`, and the arming prompt's own label.
    strips: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Choices this module made that the conventions did not state, said
    #: out loud so the engineer can correct their conventions next time
    #: (an inferred value that does not announce itself is the defect,
    #: not the inference).
    infos: list[str] = field(default_factory=list)
    #: The applied plan's own entries for the channels this amendment
    #: returns to free -- the entries that BUILT those strips, which is
    #: what `apply.release_write_targets` needs to undo exactly what was
    #: written and nothing more.
    releases: list[dict] = field(default_factory=list)
    #: Strip labels those entries sit on, in order -- the journal's
    #: `scope.released`, and the counterpart of `strips`.
    released: list[str] = field(default_factory=list)
    #: Addresses the releases own. Kept apart from `scope` on purpose: a
    #: released strip's addresses are ones the APPLIED plan also writes,
    #: which is exactly what `AmendmentTargets.collisions` refuses on, and
    #: the only way that guard keeps its meaning is if the deliberate
    #: overlap is named rather than folded into the additions' scope.
    release_scope: AmendScope = field(default_factory=AmendScope)
    #: Input sockets the plan that REMAINS still patches. A release never
    #: touches one of these, whoever else was on it.
    keep_sockets: set[tuple[str, int]] = field(default_factory=set)
    #: Which console this is, as far as the release is concerned: the
    #: model the desk stated on its read, else the applied plan's
    #: `meta.console_model` (`verify_plan.resolve_console_model`). Decides
    #: whether a released strip's factory patch is KNOWN -- measured -- or
    #: not, and so whether it goes back on it or goes OFF.
    console_model: str | None = None
    #: The named fields a typed change sets on objects already on the desk, one per leaf, in the order the change gave them.
    edits: list[FieldEdit] = field(default_factory=list)
    #: The exact addresses those edits write, each granted with the field
    #: that owns it. Kept apart from `scope` for the reason `release_scope`
    #: is: an edited address is one the APPLIED plan also writes, and the
    #: collision guard keeps its meaning only if that overlap is named.
    #: Exact addresses, never a strip's base -- an edit owns the leaves its
    #: fields change and nothing else on the strip.
    edit_scope: AmendScope = field(default_factory=AmendScope)
    #: The addresses a patch writes from what it read off the desk for an
    #: object the plan did not know (`patch._renumber_adopted_output`): the
    #: plan's own render of that object is not written beside them.
    read_from_desk: set = field(default_factory=set)
    #: Writes an edit needs that the effective plan cannot produce, because
    #: the edit takes something AWAY: a send the change removed is turned
    #: off, a high-pass it removed is switched off, a DCA it left is taken
    #: out of the strip's tags (`_vanished_target`).
    edit_extra: list = field(default_factory=list)
    #: Labels of the objects edited ("ch:12", "bus 'MON2'"), in order -- the
    #: journal's `scope.edited`.
    edited: list[str] = field(default_factory=list)
    #: Strips an explicit insert moves, `(name, old strip, new strip)` in
    #: strip order -- the journal's `scope.renumbered`.
    shifted: list[tuple[str, str, str]] = field(default_factory=list)
    #: The strips the insert rewrites: each one a moved channel lands on and
    #: each one the inserted channel takes, granted as `/ch/N`. Apart from
    #: `scope` for the reason `edit_scope` is: these strips' addresses are
    #: ones the APPLIED plan also writes (another channel stood there).
    shift_scope: AmendScope = field(default_factory=AmendScope)
    #: `(strip label, the applied plan's entry for the channel that stood on
    #: it)` for every rewritten strip that had an occupant -- what has to be
    #: cleared there where the new occupant states nothing
    #: (`shift_clear_targets`).
    shift_occupants: list[tuple[str, dict]] = field(default_factory=list)
    #: `(name, index, the applied plan's entry)` of each bus a typed change
    #: drops and the desk returns to free. Its addresses are
    #: granted in `release_scope`.
    freed_busses: list[tuple[str, int, dict]] = field(default_factory=list)
    #: `(plan key, name, index, the applied plan's entry)` of each DCA, mute
    #: group or output a typed change drops and the desk returns to free.
    freed_objects: list[tuple[str, str, int | None, dict]] = field(default_factory=list)

    @property
    def blocked(self) -> list[Change]:
        return [c for c in self.changes if c.kind in BLOCKING_KINDS]

    @property
    def additions(self) -> list[Change]:
        return [c for c in self.changes if c.kind is ChangeKind.ADDED]

    def allows(self, target) -> bool:
        """The target filter this amendment hands `apply_plan`: an address
        is written only if the additions own it or a release does."""
        return (self.scope.allows(target) or self.release_scope.allows(target)
                or self.edit_scope.allows(target) or self.shift_scope.allows(target))

    def journal_scope(self) -> dict:
        """What the journal records as this run's scope -- the strips it
        added to, the strips it returned to free, and every grant behind
        both. `released` is a separate key rather than more entries in
        `strips` because "we wrote this strip" and "we cleared this strip"
        are different answers to the question a journal gets asked."""
        entry = self.scope.journal_entry(self.strips)
        if self.released:
            entry["released"] = list(self.released)
            entry["grants"] = {**entry["grants"], **self.release_scope.grants}
        if self.freed_busses:
            entry["freed_busses"] = [f"bus:{i} (was {n!r})" for n, i, _e in self.freed_busses]
            entry["grants"] = {**entry["grants"], **self.release_scope.grants}
        if self.freed_objects:
            entry["freed_objects"] = [f"{_FREED_WORD[k]} {n!r}" + (f" ({i})" if i else "")
                                      for k, n, i, _e in self.freed_objects]
            entry["grants"] = {**entry["grants"], **self.release_scope.grants}
        if self.edited:
            # Which running objects this run changed, and exactly which of
            # their fields -- "what was this run allowed to touch" has a
            # narrower answer for an edited strip than for an added one.
            entry["edited"] = list(self.edited)
            entry["fields"] = [{"object": e.word, "name": e.name, "slot": e.slot,
                                "path": e.path, "old": e.old, "new": e.new}
                               for e in self.edits]
        if self.edited or self.edit_scope.grants:
            # A patch's writes on what the desk read and the plan does not
            # hold are granted here with no edit beside.
            entry["grants"] = {**entry["grants"], **self.edit_scope.grants}
        if self.shifted:
            # Which strips this run renumbered, as "name: ch:3 -> ch:4" --
            # the grants name the strips it rewrote, this says which
            # channel went where, so the journal reads as the change did.
            entry["renumbered"] = [f"{name}: {old} -> {new}" for name, old, new in self.shifted]
            entry["grants"] = {**entry["grants"], **self.shift_scope.grants}
        return entry

    def summary(self) -> str:
        lines = []
        counts: dict[ChangeKind, int] = {}
        for change in self.changes:
            counts[change.kind] = counts.get(change.kind, 0) + 1
        lines.append(", ".join(
            f"{counts[k]} {k.value}" for k in ChangeKind if counts.get(k)) or "nothing to do")
        for change in self.changes:
            if change.kind is not ChangeKind.UNCHANGED:
                lines.append("  " + change.line())
        if self.strips:
            lines.append(f"  writes to: {', '.join(self.strips)}")
        if self.released:
            lines.append(f"  returns to free: {', '.join(self.released)}")
        if self.edits:
            lines.append("  fields changed on objects already on the desk (only these; "
                         "nothing else on them is written):")
            for edit in self.edits:
                lines.append(f"    {edit.line()}")
        return "\n".join(lines)


#: `meta` key of an effective plan: `{placed strip: strip the rebuild
#: proposed}` for every channel an amend put somewhere other than where the
#: rebuild numbered it -- `{"ch:21": "ch:20"}` for a Trumpet the rebuild
#: numbered 20 when strip 20 was somebody else's.
#:
#: Why it has to exist: a confirmed bundle amend now writes the
#: effective plan to `plan.json`, and the next rebuild still numbers the
#: Trumpet 20, because `build` knows nothing of the desk. Without a record
#: of the placement, the next amend compares Trumpet-on-21 (applied) with
#: Trumpet-on-20 (rebuild), calls it RENUMBERED, and refuses -- every amend
#: after the first one that had to skip a strip, forever. With it, the pair
#: is recognised as the same channel on the strip an amend chose.
#:
#: In `meta` rather than the channel's `provenance`, because provenance is
#: prose a person reads (the Setup screen renders every value as text) and
#: this is a fact code reads back. The placed channel's
#: `provenance.channel` gets the prose version.
PLACEMENTS_META = "amend_placements"


def amend_placements(plan: dict | None) -> dict[str, str]:
    """A plan's `meta.amend_placements`, keeping only well-formed pairs --
    a hand-edited plan is not a reason to crash an amend."""
    meta = (plan or {}).get("meta")
    raw = meta.get(PLACEMENTS_META) if isinstance(meta, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _note_placement(effective: dict, placed: str, proposed: str,
                    by: str = "the rebuild") -> None:
    """Say on the channel itself, in the prose its `provenance` is for, why
    it is not on the number the rebuild gave it."""
    command = "`atoo patch`" if by == "the change" else "`atoo amend`"
    note = (f"placed on {placed} by {command}: {by} proposed {proposed}, "
            "which was not free")
    provenance = effective.get("provenance")
    if provenance is None:
        provenance = effective["provenance"] = {}
    if isinstance(provenance, dict):
        earlier = provenance.get("channel")
        provenance["channel"] = f"{earlier}; {note}" if earlier else note


def _leaves_slot(slot, applied_by_slot: dict, amended_by_source: dict, moving: set,
                 occupancy, console_model: str | None) -> bool:
    """Whether the running channel on `slot` leaves it in this change --
    dropped, or moved elsewhere -- and the desk still reads the strip as
    the one this plan built, so it is returned to free."""
    occupant = applied_by_slot.get(slot)
    if occupant is None:
        return False
    key = _source_key(occupant)
    if key in amended_by_source and key not in moving:
        return False
    status = next((s for s in occupancy if s.label == _slot_label(slot)), None)
    return release_refusal(occupant, status, console_model=console_model) is None


def plan_amendment(applied_plan: dict, amended_plan: dict,
                   occupancy: list[StripStatus], *,
                   allow_strips: set[str] | None = None,
                   console_model: str | None = None,
                   by: str = "the rebuild",
                   edits: list[FieldEdit] | None = None,
                   moved: set[str] | None = None,
                   renumbered: dict[str, str] | None = None,
                   inserted: dict[str, str] | None = None,
                   freed_busses: list[str] | None = None,
                   freed_objects: list[tuple[str, str]] | None = None,
                   explicit_drops: set[str] | None = None) -> Amendment:
    """Work out the delta between an applied plan and a rebuilt one, place
    the new objects on free strips, decide which dropped channels may be
    returned to free, and return the lot for review.

    `occupancy` is `strip_occupancy`'s output -- the desk's own answer.
    `allow_strips` is the per-strip override
    (`{"ch:20"}`): an occupied or unread strip the engineer can see and
    knows better about. It is per strip and never global, because "write
    anyway" as one switch is the failure this flow exists to prevent.

    Placement, stated so it can be argued with (and it is an inference,
    so it announces itself in `infos`): a new channel takes **the lowest
    available strip at or after the number the rebuild proposed**. At or
    after, rather than the lowest free strip anywhere, because a gap
    below the rebuild's own numbering is usually a gap the engineer left
    on purpose. When nothing at or after is available but something below
    is, it takes that instead rather than refusing -- a placed channel
    the engineer can move is better than a show that will not load, and
    FR-2.3's refusal is for *no slot at all*.

    A strip returned to free by this run is **not** offered as a slot to
    place something on in the same run: `occupancy` still reads it as
    OURS, because the applied plan claims it, and that stays true until
    the next read. Placing a new channel on a strip this run is in the
    middle of clearing would make the order of two write sets
    load-bearing, for one strip's worth of convenience.

    `console_model` is the model the desk stated (`ConsoleState.
    console_model`); absent, the applied plan's `meta.console_model` is
    used.

    `by` is who proposed the new plan, in the words every line of the review
    uses: "the rebuild" for an amend, "the change" for a typed change merged
    by `patch.merge_change`.

    `edits` are the named fields a typed change sets on objects already on
    the desk (`FieldEdit`). An edited channel is matched
    to the applied one by its STRIP, not its source, so a rename is still
    the same strip; any difference from the applied plan other than the
    edited fields is still MODIFIED, not written. What each edit writes is
    worked out by `_plan_edits`.

    `moved` are the source keys of channels a typed change both drops and
    adds again ("move Playback to Aux 8"). One of those whose new strip is
    not its old one is a move the change asked for by name, not a renumber
    the rebuild made by accident: its old strip is returned to free like any
    dropped channel, and it is placed on its new strip like any added one.

    `renumbered` and `inserted` are an explicit insert's two halves
    (`patch.merge_change`): `{old strip label: new strip label}` for each
    running channel that moves down to make room, and `{source key: strip
    label}` for each channel inserted into the room made. Both are the
    change's own words carried out, not a rebuild's accident: each moved
    channel is rewritten whole on its new strip (SHIFTED, never RENUMBERED),
    each inserted one is built on the strip the move vacated. A strip they
    land on that nothing stood on must be free on the desk, or the channel
    landing there is UNPLACEABLE and the whole change is blocked.

    `freed_busses` are the names of busses of the applied plan that a typed
    change drops: each is returned to free -- every leaf of
    it reads as an initialized bus (`apply.release_bus_write_targets`) --
    and its index, which the amended plan may give to a new bus, is not
    taken by it. Only a typed change names any; a rebuild that leaves a
    bus out writes nothing for it.

    `explicit_drops` are the source keys of channels the engineer's typed
    change drops by name. Such a drop is carried out even where
    `release_refusal` finds the desk no longer reads the strip as the one the
    plan built: what the strip holds now is said at WARNING, and Undo puts it
    back. A rebuild that merely leaves a channel out is a guard's business
    still -- it never names one.

    `freed_objects` are `(plan key, name)` of the DCAs, mute groups and
    outputs of the applied plan that a typed change drops: each is returned to free the same way
    (`apply.release_object_write_targets`), and its index -- and an output's
    sockets -- may be taken by a new one in the same change.
    """
    allow_strips = set(allow_strips or ())
    renumbered = dict(renumbered or {})
    inserted = dict(inserted or {})
    edits = list(edits or ())
    edited_slots: dict[str, set[str]] = {}
    for edit in edits:
        if edit.key == "channels" and edit.slot:
            edited_slots.setdefault(edit.slot, set()).add(edit.path.split(".")[0])
    console_model = resolve_console_model(applied_plan, console_model)
    changes: list[Change] = []
    warnings: list[str] = []
    infos: list[str] = []

    available: dict[str, list[int]] = {bank: [] for bank in OCCUPANCY_BANKS}
    for status in occupancy:
        if status.available or status.label in allow_strips:
            available.setdefault(status.bank, []).append(status.number)
            if not status.available:
                warnings.append(
                    f"{status.label} is {status.state.value} on the desk and was made available "
                    f"by an explicit --allow-strip override")
    # A strip the applied plan claims is never available, override or not.
    # `strip_occupancy` already says OURS for those, but this is the guard
    # that does not depend on the desk having answered -- a reading that
    # never happened must not be able to hand out a running strip.
    for bank, number in _plan_strip_slots(applied_plan):
        if number in available.get(bank, []):
            available[bank].remove(number)
            warnings.append(
                f"{bank}:{number} is claimed by the applied plan and is not available, "
                "whatever the desk or an override says")
    for bank in available:
        available[bank].sort()

    applied_channels = [c for c in applied_plan.get("channels", []) or [] if isinstance(c, dict)]
    amended_channels = [c for c in amended_plan.get("channels", []) or [] if isinstance(c, dict)]
    applied_by_slot = {_channel_slot(c): c for c in applied_channels if c.get("channel") is not None}
    applied_by_source = {_source_key(c): c for c in applied_channels}
    amended_by_source = {_source_key(c): c for c in amended_channels}
    moving = {key for key in (moved or ())
              if key in applied_by_source and key in amended_by_source
              and _channel_slot(applied_by_source[key]) != _channel_slot(amended_by_source[key])}

    effective_plan = copy.deepcopy(amended_plan)
    effective_channels = [c for c in effective_plan.get("channels", []) or [] if isinstance(c, dict)]

    scope = AmendScope()
    strips: list[str] = []
    applied_sockets = _patched_sockets(applied_plan)

    taken: set[tuple[str, int]] = set()
    #: Strips a moved channel lands on (label -> the channel), so a strip
    #: the same change frees says what lands on it.
    landings: dict[str, str] = {}
    shift_scope = AmendScope()
    shifted: list[tuple[str, str, str]] = []
    shift_occupants: list[tuple[str, dict]] = []
    by_state = {status.label: status for status in occupancy}
    for label in [*renumbered.values(), *inserted.values()]:
        bank, _, number = label.partition(":")
        if number.isdigit():
            # Spoken for: nothing else the change adds is placed here.
            taken.add((bank, int(number)))
            old_occupant = applied_by_slot.get((bank, int(number)))
            if old_occupant is not None:
                shift_occupants.append((label, old_occupant))
    # Where earlier amends put channels the rebuild numbered differently
    #  -- see `PLACEMENTS_META`.
    prior_placements = amend_placements(applied_plan)
    placements: dict[str, str] = {}
    for channel, effective in zip(amended_channels, effective_channels):
        key = _source_key(channel)
        where = repr(channel.get("name") or key)
        slot = _channel_slot(channel)
        if _slot_label(slot) in edited_slots and slot in applied_by_slot:
            # A running strip a typed change edits: the change's own
            # `EDITED` verdict comes from `_plan_edits`. Anything ELSE that
            # differs is not the change's to write.
            prior = applied_by_slot[slot]
            named = edited_slots[_slot_label(slot)]
            others = [f for f in _CHANNEL_COMPARED_FIELDS
                      if f not in named and prior.get(f) != channel.get(f)]
            if others:
                changes.append(Change(
                    ChangeKind.MODIFIED, "channel", where,
                    f"{', '.join(others)} differ from the applied plan as well as the "
                    "fields the change names -- not written, not even the named ones",
                    slot=_slot_label(slot)))
                edits = [e for e in edits if e.slot != _slot_label(slot)]
            continue
        prior = None if key in moving else applied_by_source.get(key)
        if prior is not None:
            prior_slot = _channel_slot(prior)
            if (prior_slot != slot
                    and prior_placements.get(_slot_label(prior_slot)) == _slot_label(slot)):
                # An earlier amend placed this channel off the number the
                # rebuild asks for, because that strip was not free, and
                # the rebuild -- which knows nothing of the desk -- still
                # asks for the same number. Not a renumber: nothing moved.
                # It stays where it is, in the effective plan too, and the
                # placement is carried forward for the amend after this.
                effective["bank"], effective["channel"] = prior_slot
                placements[_slot_label(prior_slot)] = _slot_label(slot)
                _note_placement(effective, _slot_label(prior_slot), _slot_label(slot), by)
                infos.append(
                    f"channel {where}: {by} numbers it {_slot_label(slot)}, and an "
                    f"earlier amend placed it on {_slot_label(prior_slot)} -- it stays there")
                slot = prior_slot
            if prior_slot != slot and renumbered.get(_slot_label(prior_slot)) == _slot_label(slot):
                landing = _slot_label(slot)
                if slot not in applied_by_slot and slot[1] not in available.get(slot[0], []):
                    state = by_state.get(landing)
                    changes.append(Change(
                        ChangeKind.UNPLACEABLE, "channel", where,
                        f"the change inserts a channel above it, which moves it to {landing}, "
                        f"and {landing} is not free on the desk"
                        + (f" ({state.state.value})" if state is not None else "")
                        + " -- nothing was moved, and nothing was written over somebody's strip",
                        slot=_slot_label(prior_slot), proposed=landing))
                    continue
                changes.append(Change(
                    ChangeKind.SHIFTED, "channel", where,
                    f"moves from {_slot_label(prior_slot)} to {landing} to make room for the "
                    "insert, and is rewritten whole on its new strip",
                    slot=landing))
                shift_scope.grant(f"/{slot[0]}/{slot[1]}",
                                  f"{where} moved to {landing} by the insert")
                shifted.append((str(channel.get("name") or key), _slot_label(prior_slot), landing))
            elif prior_slot != slot:
                changes.append(Change(
                    ChangeKind.RENUMBERED, "channel", where,
                    f"the applied plan has it on {_slot_label(prior_slot)} and {by} moved "
                    f"it to {_slot_label(slot)} -- an amend never renumbers a strip that is "
                    "already running. Re-plan deliberately, or put it back.",
                    slot=_slot_label(prior_slot), proposed=_slot_label(slot)))
            elif _channel_differs(prior, channel):
                changes.append(Change(
                    ChangeKind.MODIFIED, "channel", where,
                    "settings differ from the applied plan, and this strip is already in use -- "
                    "not written. A full build is how a running strip changes.",
                    slot=_slot_label(slot)))
            else:
                changes.append(Change(
                    ChangeKind.UNCHANGED, "channel", where, "already applied, unchanged",
                    slot=_slot_label(slot)))
            continue

        # A new source. Place it.
        bank = slot[0]
        free = [n for n in available.get(bank, []) if (bank, n) not in taken
                and (bank, n) not in applied_by_slot]
        at_or_after = [n for n in free if n >= slot[1]]
        if inserted.get(key) == _slot_label(slot):
            # The strip the insert made room on: a running channel stood
            # here and has moved down, so it is not "free" by the desk's
            # read, and is this channel's by the change's own words.
            placed = slot[1]
        elif key in moving and slot not in taken and _leaves_slot(
                slot, applied_by_slot, amended_by_source, moving, occupancy, console_model):
            # A channel the change moves onto a strip the same change frees
            # ("swap the Kick and the Snare"): written once, by
            # the channel that lands (`amendment_targets`).
            placed = slot[1]
        elif at_or_after:
            placed = at_or_after[0]
        elif free:
            placed = free[0]
            infos.append(
                f"channel {where}: nothing free at or after {_slot_label(slot)}, so it was "
                f"placed on {bank}:{placed}, below the number {by} proposed")
        else:
            changes.append(Change(
                ChangeKind.UNPLACEABLE, "channel", where,
                f"no free {bank} strip on this desk -- not placed, and nothing was renumbered "
                "to make room",
                proposed=_slot_label(slot)))
            continue
        taken.add((bank, placed))
        effective["channel"] = placed
        label = f"{bank}:{placed}"
        strips.append(label)
        if placed != slot[1]:
            infos.append(
                f"channel {where}: {by} proposed {_slot_label(slot)}, which is not free "
                f"-- placed on {label} instead, and nothing already on the desk moved")
            placements[label] = _slot_label(slot)
            _note_placement(effective, label, _slot_label(slot), by)
        changes.append(Change(
            ChangeKind.ADDED, "channel", where,
            "new channel, inserted here: the channels after it move down one strip"
            if key in inserted else
            f"moved here from {_slot_label(_channel_slot(applied_by_source[key]))}, and "
            "written whole on this strip" if key in moving else
            "new channel, placed on a free strip",
            slot=label, proposed=_slot_label(slot), asked_by=by))
        if key in moving:
            landings[label] = where
        if key in moving:
            infos.append(
                f"channel {where}: {by} drops it from "
                f"{_slot_label(_channel_slot(applied_by_source[key]))} and adds it again on "
                f"{label}, so it is moved: the old strip is returned to free and the "
                "channel is built on the new one")
        # An inserted channel's strip is one the applied plan also writes (the
        # channel that stood there has moved down), so it is granted with the
        # moved strips'; its sockets are new, and granted as any new channel's.
        (shift_scope if key in inserted else scope).grant(
            f"/{bank}/{placed}", f"new channel {where} on {label}")

        patch = effective.get("patch") or {}
        group = patch.get("group")
        own_sockets = (_patched_sockets({"channels": [applied_by_source[key]]})
                       if key in moving else set())
        for socket in patch.get("sockets") or []:
            if not isinstance(group, str) or not isinstance(socket, int):
                continue
            if (group, socket) in own_sockets:
                # The channel's own cable: only the strip moves.
                continue
            if (group, socket) in applied_sockets:
                warnings.append(
                    f"channel {where} is patched to {group} {socket}, which an already-applied "
                    "channel also uses. The socket's own name, color, phantom and head-amp gain "
                    "belong to that running strip and are NOT written -- the new strip carries "
                    "its own name instead.")
                continue
            scope.grant(f"/io/in/{group}/{socket}",
                        f"the input socket {label} is patched to")

    # Removals. A channel the rebuild dropped is returned to
    # free -- factory patch (or OFF), name/colour/icon/processing cleared, unmuted --
    # but ONLY when
    # the desk still reads as the strip this plan built. `release_refusal`
    # is that check and it is the whole safety of the feature; a strip
    # somebody has taken over since is reported and left exactly as it is.
    by_label = {status.label: status for status in occupancy}
    shared_applied = apply_module._shared_source_sockets(applied_plan)
    keep_sockets = _patched_sockets(effective_plan)
    releases: list[dict] = []
    released: list[str] = []
    release_scope = AmendScope()
    for channel in applied_channels:
        key = _source_key(channel)
        if key in amended_by_source and key not in moving:
            continue
        if channel.get("channel") is not None \
                and _slot_label(_channel_slot(channel)) in edited_slots:
            continue  # edited in place -- renamed, perhaps -- not dropped
        where = repr(channel.get("name") or key)
        slot = _channel_slot(channel)
        label = _slot_label(slot)
        refusal = release_refusal(channel, by_label.get(label), shared_sockets=shared_applied,
                                  console_model=console_model)
        found_there = None
        if refusal is not None and key in (explicit_drops or ()):
            # "Lose the MD vocal" is an instruction. The guard exists for a
            # rebuild that leaves a channel out; here the engineer named it.
            found_there = refusal
            status = by_label.get(label)
            held = (f"name {status.name!r}, patch "
                    f"{status.patch[0]} {status.patch[1]}" if status and status.patch
                    else f"name {status.name!r}, no patch" if status else "nothing read")
            warnings.append(
                f"WARNING: channel {where} on {label} was dropped by {by} and is returned to free, "
                f"although the desk no longer reads that strip as the one this plan built: "
                f"{refusal}. What it holds now ({held}) is cleared with the rest; Undo puts it "
                "back.")
            refusal = None
        if refusal is not None:
            changes.append(Change(
                ChangeKind.REMOVED, "channel", where,
                f"dropped by {by}, and NOT returned to free: {refusal}. Nothing was "
                "written to this strip -- go and look at it.",
                slot=label))
            continue
        reads_as = ("the desk still reads as the strip this plan built"
                    if found_there is None else
                    f"the desk does NOT read it as the strip this plan built ({found_there}), "
                    "and it is cleared because the change named it")
        changes.append(Change(
            ChangeKind.RELEASED, "channel", where,
            (f"moved off it by {by}, and channel {landings[label]} moves onto it: written "
             f"whole by {landings[label]}, and what {where} set there that {landings[label]} "
             "does not is cleared to the untouched reading"
             if label in landings else
             f"{'moved off it' if key in moving else 'dropped'} by {by}, and {reads_as} -- "
             "unpatched (OFF), left unmuted, and its name, "
             "color, icon, DCA/mute-group tags, bus sends and this plan's own processing "
             "cleared, on the source socket as well as the strip, so the next person to "
             "allocate a strip finds this one genuinely free"),
            slot=label))
        releases.append(channel)
        released.append(label)
        release_scope.grant(f"/{slot[0]}/{slot[1]}", f"returning channel {where} on {label} to free")
        patch = channel.get("patch") or {}
        group = patch.get("group")
        for socket in patch.get("sockets") or []:
            if not isinstance(group, str) or not isinstance(socket, int):
                continue
            if (group, socket) in keep_sockets:
                if key not in moving:
                    warnings.append(
                        f"channel {where} is being returned to free, but {group} {socket} "
                        f"still feeds a strip {by} keeps -- the socket's own name, color, "
                        "icon and phantom are left exactly as they are")
                continue
            release_scope.grant(f"/io/in/{group}/{socket}",
                                f"the input socket {label} was patched to")

    for channel, label in zip(releases, released):
        where = repr(channel.get("name") or _source_key(channel))
        patch = channel.get("patch") or {}
        if (isinstance(patch.get("group"), str)
                and any(isinstance(x, int) for x in patch.get("sockets") or [])):
            why = apply_module.release_patch_reason(channel)
        else:
            # The build never patched it, so the release does not either.
            why = "its patch is left as it is, because this plan never patched it"
        infos.append(
            f"channel {where} on {label} was dropped by {by} and is returned to free. "
            f"Patch: {why}. Its name, color, icon, DCA/mute-group tags, bus sends and the "
            "processing this plan set are all cleared -- the reading an untouched strip gives. "
            "Its direct Main routing goes back to the factory's too: Main 1 on, the other "
            "Mains off. "
            "Its FADER goes to -inf first, as an untouched strip reads, so a stray source on "
            "that socket is not heard while the rest is cleared, and it ends UNMUTED, because an "
            "untouched strip is not a muted one; the head-amp gain on its source is left "
            "alone: that belongs to the socket and is shared on a split.")

    freed: list[tuple[str, int, dict]] = []
    applied_busses = applied_plan.get("busses") if isinstance(applied_plan.get("busses"), dict) else {}
    for name in freed_busses or ():
        entry = applied_busses.get(name)
        index = entry.get("index") if isinstance(entry, dict) else None
        if not isinstance(index, int):
            continue
        freed.append((name, index, entry))
        changes.append(Change(
            ChangeKind.RELEASED, "bus", repr(name),
            f"dropped by {by}: bus {index} is returned to free -- every setting on it reads "
            "as an initialized bus (name, color, icon, width, fader, mute, EQ, dynamics, "
            "inserts, tags, routes to the Mains and matrices), the output it fed is "
            "unpatched, and the channels' sends into it are switched off",
            slot=f"bus:{index}"))
        release_scope.grant(f"/bus/{index}", f"returning bus {name!r} (bus {index}) to free")
        for group, socket in _bus_output_sockets(entry):
            # Granted even where a bus that stays (or a new one) feeds the
            # socket: `release_targets` leaves out what is written for it.
            release_scope.grant(f"/io/out/{group}/{socket}",
                                f"the output socket bus {name!r} fed")
        infos.append(
            f"bus {name!r} (bus {index}) was dropped by {by} and is returned to free: the "
            "bus reads as an initialized one on every WING model -- the values come from the "
            "initialized capture of this console model, and a bus strip reads the same in "
            "every capture measured. Its fader goes to -inf first, so it is silent by level "
            "while the rest is cleared. Undo puts every address back.")

    freed_other: list[tuple[str, str, int | None, dict]] = []
    for key, name in freed_objects or ():
        entry = (applied_plan.get(key) or {}).get(name)
        if not isinstance(entry, dict):
            continue
        index = entry.get("index") if isinstance(entry.get("index"), int) else None
        freed_other.append((key, name, index, entry))
        word = _FREED_WORD[key]
        root = {"dcas": "/dca", "mute_groups": "/mgrp"}.get(key)
        if key == "outputs" and index is not None and entry.get("kind") in ("main", "matrix"):
            root = "/main" if entry["kind"] == "main" else "/mtx"
        what = {"dcas": "its fader, mute, name, color and icon read as an initialized DCA's and "
                        "its members are taken off it",
                "mute_groups": "its name and mute read as an initialized mute group's and its "
                               "members are taken off it",
                "outputs": "the Main or Matrix behind it reads as an initialized one and the "
                           "socket it fed read as an initialized desk's"}[key]
        if key == "outputs" and entry.get("provenance") == READ_FROM_DESK:
            what = ("the Main or Matrix behind it reads as an initialized one; the sockets "
                    "it fed are not in the plan and stay patched as the desk has them")
        changes.append(Change(
            ChangeKind.RELEASED, word, repr(name),
            f"dropped by {by}: returned to free -- {what}"
            + (f" ({entry['kind']} {index})" if key == "outputs" and root else ""),
            slot=(f"{root.lstrip('/')}:{index}" if root and index else None)))
        if root and index is not None:
            release_scope.grant(f"{root}/{index}", f"returning {word} {name!r} to free")
        if key == "outputs":
            for group, socket in apply_module._output_entry_sockets(entry):
                release_scope.grant(f"/io/out/{group}/{socket}",
                                    f"the output socket {name!r} fed")
            fed_by = entry.get("fed_by")
            source = _fed_by_base(fed_by, applied_plan) if (
                isinstance(fed_by, dict) and entry.get("kind") == "matrix") else None
            if source and index is not None:
                release_scope.grant(f"{source}/send/MX{index}",
                                    f"the feed from {source} into dropped matrix {index}")
        infos.append(
            f"{word} {name!r} was dropped by {by} and is returned to free: it reads as an "
            "initialized one on every WING model -- the values come from the initialized "
            "capture of this console model. Undo puts every address back.")

    meta = effective_plan.get("meta")
    if placements:
        if not isinstance(meta, dict):
            meta = effective_plan["meta"] = {}
        meta[PLACEMENTS_META] = placements
    elif isinstance(meta, dict):
        meta.pop(PLACEMENTS_META, None)

    freed_names = {(k, n) for k, n, _i, _e in freed_other}
    _plan_new_groups(applied_plan, amended_plan, scope, changes, infos, freed=freed_names)
    _plan_new_busses(applied_plan, amended_plan, scope, changes, warnings, infos,
                     freed={name for name, _i, _e in freed})
    _plan_new_outputs(applied_plan, amended_plan, scope, changes, warnings, infos,
                      freed={n for k, n, _i, _e in freed_other if k == "outputs"})
    _plan_user_sources(applied_plan, amended_plan, scope, changes)

    edit_scope = AmendScope()
    edit_extra: list = []
    edited: list[str] = []
    if edits:
        edits, edit_extra, edited = _plan_edits(
            effective_plan, edits, occupancy, edit_scope, changes, warnings, infos,
            freed_busses={n: e for n, _i, e in freed}, console_model=console_model,
            freed_objects={(k, n): e for k, n, _i, e in freed_other})

    shifted.sort(key=lambda row: int(row[2].partition(":")[2]))
    return Amendment(
        applied_plan=applied_plan, amended_plan=amended_plan,
        effective_plan=effective_plan, scope=scope, changes=changes,
        strips=strips, warnings=warnings, infos=infos,
        releases=releases, released=released, release_scope=release_scope,
        keep_sockets=keep_sockets, console_model=console_model,
        edits=edits, edit_scope=edit_scope,
        edit_extra=edit_extra, edited=edited, shifted=shifted, shift_scope=shift_scope,
        shift_occupants=shift_occupants, freed_busses=freed, freed_objects=freed_other)


# --------------------------------------------------------------------------
# 2b. Editing the named fields of running objects
# --------------------------------------------------------------------------
#
# The rule for a typed change on a running strip, as scoped on
# 2026-09-28: a change may edit exactly the fields it names and
# no others. `patch.merge_change` enforces the first half -- the merged plan
# differs from the desk's only in the named fields. This is the second half:
# which ADDRESSES those fields own. It is worked out by difference rather
# than from a table of field -> address, for the reason `AmendScope` grants
# objects rather than leaves: `apply._build_write_targets` grows a leaf
# every time the project learns a parameter, and a table would silently stop
# covering it. Build the plan with the edits taken back out, build it again
# with one edit put in, and the addresses whose value moved are that edit's.
# Everything else of the object is withheld -- and so read before and after
# the write by FR-2.2's proof, which is the check that no unnamed field
# moved.


def get_path(obj, path: str):
    """The value at a dotted path, or None where any step is missing."""
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_path(obj: dict, path: str, value) -> None:
    """Set the value at a dotted path, making the objects on the way."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = current[part] = {}
        current = nxt
    current[parts[-1]] = copy.deepcopy(value)


def edited_object(plan: dict, edit: FieldEdit) -> dict | None:
    """The object an edit names, in `plan`: a channel by its strip, anything
    else by its name."""
    if edit.key == "channels":
        for channel in plan.get("channels") or []:
            if (isinstance(channel, dict) and channel.get("channel") is not None
                    and _slot_label(_channel_slot(channel)) == edit.slot):
                return channel
        return None
    entry = (plan.get(edit.key) or {}).get(edit.name)
    return entry if isinstance(entry, dict) else None


def edit_label(edit: FieldEdit) -> str:
    return edit.slot if edit.key == "channels" and edit.slot else f"{edit.word} {edit.name!r}"


def _stray_owners(addresses: list[str], plan: dict) -> list[str]:
    """The objects the `addresses` belong to, in words: `channel 'Kick' (ch:1)`,
    `bus 'Drums' (bus 5)`, or the console base when the plan has no name for it."""
    owners: list[str] = []
    for address in addresses:
        parts = address.split("/")
        base = "/".join(parts[:3])
        kind = parts[1] if len(parts) > 2 else ""
        number = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        who = None
        if kind in ("ch", "aux") and number is not None:
            channel = next((c for c in plan.get("channels") or []
                            if isinstance(c, dict) and str(c.get("bank", "ch")) == kind
                            and c.get("channel") == number), None)
            who = f"channel {channel.get('name')!r} ({kind}:{number})" if channel else \
                f"{kind}:{number}"
        elif kind in ("bus", "dca", "mgrp") and number is not None:
            key = {"bus": "busses", "dca": "dcas", "mgrp": "mute_groups"}[kind]
            name = next((n for n, e in (plan.get(key) or {}).items()
                         if isinstance(e, dict) and e.get("index") == number), None)
            word = {"bus": "bus", "dca": "DCA", "mgrp": "mute group"}[kind]
            who = f"{word} {name!r} ({kind} {number})" if name else f"{word} {number}"
        else:
            who = base
        if who not in owners:
            owners.append(who)
    return owners


def _own_bases(plan: dict, edit: FieldEdit) -> list[str]:
    """The console bases the edited object owns. An edit writing anywhere
    else, bar a socket (`/io/...`, checked separately), is a consequence of
    the named field: refused, naming those objects, unless the change names them
    too (decided)."""
    if edit.key == "channels":
        return [f"/{edit.slot.replace(':', '/')}"] if edit.slot else []
    obj = edited_object(plan, edit) or {}
    index = obj.get("index")
    if not isinstance(index, int):
        return []
    if edit.key == "outputs":
        kind = obj.get("kind")
        return [f"/main/{index}"] if kind == "main" else (
            [f"/mtx/{index}"] if kind == "matrix" else [])
    root = {"busses": "/bus", "dcas": "/dca", "mute_groups": "/mgrp"}.get(edit.key)
    return [f"{root}/{index}"] if root else []


def _engine_bases(*objs) -> list[str]:
    """`/fx/{e}` for every FX engine the strips `objs` insert: what an edit of
    a bus's preset (its `preset_values`) owns besides the bus, since the
    preset's effect is loaded into its engine."""
    from atoo import bus_presets

    return list(dict.fromkeys(
        f"/fx/{ins['engine']}" for obj in objs if isinstance(obj, dict)
        for ins in bus_presets.strip_inserts(obj)
        if isinstance(ins.get("engine"), int) and ins.get("model") is not None))


def _probe(target) -> tuple:
    """What a write target would write, as something comparable: its value
    for a few readings of the current value (`/ch/n/tags` is merged into
    what is there, so one reading is not enough to tell two apart)."""
    out: list = [target.value_type]
    for current in (None, "", "#D1,#M1,cue"):
        try:
            out.append(repr(target.compute_value(current)))
        except Exception as exc:  # noqa: BLE001
            out.append(f"!{type(exc).__name__}")
    return tuple(out)


def _target_map(plan: dict) -> dict[str, object]:
    targets, _warnings = apply_module._build_write_targets(plan, set_fader_levels=True)
    out: dict[str, object] = {}
    for target in targets:
        out.setdefault(target.address, target)
    return out


#: Leaves that switch something on. When an edit takes the thing away (a
#: send removed, the high-pass taken off), the plan no longer states the
#: address at all -- and a desk left as it is would keep it on. So it is
#: written OFF, and said.
_ENABLE_LEAVES = frozenset({"on", "lc", "hc", "tf", "inv"})


_SEND_TO = re.compile(r"^/(?:ch|aux)/\d+/send/(\d+)/\w+$")


def _vanished_target(address: str, before, edit: FieldEdit, label: str,
                     freed_indices: frozenset = frozenset(), console_model: str | None = None):
    """The write that takes away what an edit removed, or None when there is
    nothing safe to write (a frequency whose filter is now off, a socket's
    old name) -- which is said at INFO instead. A send into a bus the change
    returns to free (`freed_indices`) is cleared whole: its level, mode, pan
    and the rest read as an initialized desk has them, not only its switch."""
    leaf = address.rsplit("/", 1)[-1]
    if edit.path.endswith("preset_values"):
        # A leaf the old preset set and the new one does not:
        # the reading an initialized strip gives it -- unless the model
        # selector that governs it changes in the same edit. Then the desk
        # drops the old model's leaves itself (a write would find nothing
        # there), and the run journals their values so Undo can put them back.
        from atoo import initialize
        from atoo import preset_expand
        relative = "/".join(address.split("/")[3:])
        old_leaves = (edit.old or {}).get("leaves") if isinstance(edit.old, dict) else None
        new_leaves = (edit.new or {}).get("leaves") if isinstance(edit.new, dict) else None
        for selector in {k for k in {**(old_leaves or {}), **(new_leaves or {})}
                         if k.endswith("/mdl")}:
            if ((old_leaves or {}).get(selector) != (new_leaves or {}).get(selector)
                    and preset_expand.governs(selector, relative)):
                return None
        as_strip_1 = re.sub(r"^/(\w+)/\d+/", r"/\1/1/", address)
        cleared = [x for candidate in (address, as_strip_1)
                   for x in initialize.freed_leaves(console_model, candidate)
                   if x.address == candidate][:1]
        if cleared:
            return apply_module.WriteTarget(
                address, cleared[0].value_type,
                f"{label}: the old preset's {leaf} -> as initialized (the new preset sets none)",
                apply_module._const(cleared[0].value), before.stage)
    if edit.path in ("index", "kind"):
        # The object's old number, and every send, tag and route into it,
        # left by a renumber: the reading an initialized
        # desk gives, as a dropped object's are.
        from atoo import initialize
        as_first = re.sub(r"^/(\w+)/\d+/", r"/\1/1/", address)
        cleared = [x for candidate in (address, as_first)
                   for x in initialize.freed_leaves(console_model, candidate)
                   if x.address == candidate][:1]
        if cleared:
            return apply_module.WriteTarget(
                address, cleared[0].value_type,
                f"{label}: {leaf} on its old number -> as initialized (renumbered)",
                apply_module._const(cleared[0].value), before.stage)
    match = _SEND_TO.match(address)
    if match and int(match.group(1)) in freed_indices:
        from atoo import initialize
        cleared = initialize.freed_leaves(console_model, address)
        if len(cleared) == 1 and cleared[0].address == address:
            return apply_module.WriteTarget(
                address, cleared[0].value_type,
                f"{label}: send into a bus returned to free -> {leaf} as initialized",
                apply_module._const(cleared[0].value), before.stage)
    if leaf in _ENABLE_LEAVES and before.value_type == "i":
        return apply_module.WriteTarget(
            address, "i", f"{label}: {before.description} -> off ({edit.path} changed by "
            "the change)", apply_module._const(0), before.stage)
    if leaf == "tags":
        return apply_module.WriteTarget(
            address, "s", f"{label}: DCA/mute-group tags -> none ({edit.path} changed by the "
            "change)", lambda current: apply_module._merge_tags(current, [], []), before.stage)
    return None


def _plan_edits(effective_plan: dict, edits: list[FieldEdit], occupancy: list[StripStatus],
                edit_scope: AmendScope, changes: list[Change], warnings: list[str],
                infos: list[str], freed_busses: dict[str, dict] | None = None,
                console_model: str | None = None,
                freed_objects: dict[tuple[str, str], dict] | None = None) -> tuple[list[FieldEdit], list, list[str]]:
    """Grant each edit the exact addresses its value changes, and return
    `(edits written, extra write targets, labels of the edited objects)`.

    Refused (blocking), per edit: an object the plan does not have, and an
    edit whose value would move an address of some OTHER object -- a bus's
    width that changes every strip's send into it, say. That is a change to
    objects the change does not name, and the rule is named fields only.

    Withheld with a WARNING: an input or output socket another running strip
    or object uses. The socket's own name, colour, phantom and gain are that
    strip's, exactly as for a new channel on a taken socket."""
    reverted = copy.deepcopy(effective_plan)
    # A bus the change drops is not in the effective plan, but a send into it
    # that the change takes away is a send to a bus that was there: with the
    # bus put back, the edit's difference is the send's own addresses.
    freed_indices = frozenset(e["index"] for e in (freed_busses or {}).values()
                              if isinstance(e.get("index"), int))
    if freed_busses:
        reverted["busses"] = {**{n: e for n, e in freed_busses.items()
                                 if n not in (reverted.get("busses") or {})},
                              **(reverted.get("busses") or {})}
    for (key, name), entry in (freed_objects or {}).items():
        # Likewise a DCA or mute group the change drops: a strip's tag naming
        # it is a tag that was written, and the edit that takes it away is
        # the difference with the group put back.
        reverted[key] = {**{name: entry}, **(reverted.get(key) or {})}
    present: list[FieldEdit] = []
    for edit in edits:
        obj = edited_object(reverted, edit)
        if obj is None:
            changes.append(Change(
                ChangeKind.REFUSED, edit.word, repr(edit.name),
                f"the change sets its {edit.path}, and it is not in the plan on the desk",
                slot=edit.slot))
            continue
        set_path(obj, edit.path, edit.old)
        present.append(edit)
    base = _target_map(reverted)
    # What the change names: every edited object, and every bus, DCA, mute
    # group or output it drops. Their addresses are the engineer's own words.
    named_bases: set[str] = set()
    for named_edit in present:
        named_bases.update(_own_bases(reverted, named_edit))
    for freed_name, freed_entry in (freed_busses or {}).items():
        if isinstance(freed_entry.get("index"), int):
            named_bases.add(f"/bus/{freed_entry['index']}")
    for (freed_key, _n), freed_entry in (freed_objects or {}).items():
        index = freed_entry.get("index")
        root = {"dcas": "/dca", "mute_groups": "/mgrp"}.get(freed_key)
        if freed_key == "outputs":
            root = "/main" if freed_entry.get("kind") == "main" else "/mtx"
        if root and isinstance(index, int):
            named_bases.add(f"{root}/{index}")

    def named(address: str) -> bool:
        return any(address == b or address.startswith(b + "/") for b in named_bases)

    input_users: dict[tuple[str, int], list[tuple[str | None, str]]] = {}
    for channel in reverted.get("channels") or []:
        if not isinstance(channel, dict) or channel.get("channel") is None:
            continue
        label = _slot_label(_channel_slot(channel))
        patch = channel.get("patch") or {}
        for socket in patch.get("sockets") or []:
            if isinstance(patch.get("group"), str) and isinstance(socket, int):
                input_users.setdefault((patch["group"], socket), []).append(
                    (label, f"channel {channel.get('name')!r} on {label}"))
    for status in occupancy:
        if status.patch is not None:
            input_users.setdefault(tuple(status.patch), []).append(
                (status.label, f"{status.label} on the desk"))
    declared_out = _declared_output_sockets(reverted)

    def socket_clash(address: str, edit: FieldEdit) -> str | None:
        parts = address.strip("/").split("/")
        if len(parts) < 4 or parts[0] != "io" or not parts[3].isdigit():
            return None
        key = (parts[2], int(parts[3]))
        if parts[1] == "in":
            others = [what for slot, what in input_users.get(key, ())
                      if slot != edit.slot]
            return others[0] if others else None
        if parts[1] == "out" and key in declared_out:
            old = edited_object(reverted, edit) or {}
            own = set(_bus_output_sockets(old)) if edit.key == "busses" else {
                (clause.get("group"), n)
                for clause in plan_compat.output_patches(old) if isinstance(clause, dict)
                for n in clause.get("sockets") or []} if edit.key == "outputs" else set()
            return None if key in own else "another output of the plan on the desk"
        return None

    extra: dict[str, object] = {}
    written: list[FieldEdit] = []
    renumbered_together: set[tuple[str, str]] = set()
    for edit in present:
        label = edit_label(edit)
        variant = copy.deepcopy(reverted)
        set_path(edited_object(variant, edit), edit.path, edit.new)
        if edit.path in ("index", "kind"):
            # An output's kind and number are one move (a Matrix made Main
            # 2): both are set, and the object's addresses granted once.
            if (edit.key, edit.name) in renumbered_together:
                written.append(edit)
                continue
            renumbered_together.add((edit.key, edit.name))
            for other in present:
                if other is not edit and (other.key, other.name) == (edit.key, edit.name) \
                        and other.path in ("index", "kind"):
                    set_path(edited_object(variant, other), other.path, other.new)
        after = _target_map(variant)
        changed = [a for a, t in after.items() if a not in base or _probe(t) != _probe(base[a])]
        vanished = [a for a in base if a not in after]
        own = _own_bases(reverted, edit)
        if edit.path in ("index", "kind"):
            own = own + _own_bases(variant, edit)
        if edit.key == "busses" and edit.path == "preset_values":
            own = own + _engine_bases(edited_object(reverted, edit), edited_object(variant, edit))
        index = (edited_object(reverted, edit) or {}).get("index")
        feed = re.compile(rf"/send/MX{index}(/|$)") if edit.key == "outputs" else None

        def owned(address: str) -> bool:
            return (address.startswith("/io/")
                    or any(address == b or address.startswith(b + "/") for b in own)
                    or bool(feed and feed.search(address)))

        stray = [a for a in changed + vanished if not owned(a) and not named(a)]
        if stray and edit.path in ("index", "kind"):
            # A new number moves every send, tag and route into the object
            # with it, on objects the change does not name (item 2): the engineer named the number, so that is the
            # instruction.
            # Carried out, and every other object it moves is said.
            owners = _stray_owners(stray, reverted)
            infos.append(f"{label}: the new number moves {len(stray)} address(es) on "
                         f"{', '.join(owners)} with it -- the sends, tags and routes into it, "
                         "written on its new number and cleared on its old one")
            for address in stray:
                if address in changed:
                    edit_scope.grant(address, f"{label}: {edit.path}, moved with it")
            stray = []
        if stray:
            # Decision of 2026-10-22: an edit that would also move
            # or re-address objects the engineer did not name is REFUSED and
            # the refusal is the question; it never writes with a warning.
            # A change that names those objects too is the instruction.
            owners = _stray_owners(stray, reverted)
            shown = ", ".join(stray[:4]) + (f" and {len(stray) - 4} more" if len(stray) > 4 else "")
            changes.append(Change(
                ChangeKind.REFUSED, edit.word, repr(edit.name),
                f"setting its {edit.path} would also change {shown} -- {len(stray)} address(es) "
                f"on {', '.join(owners)}, which the change does not name. Nothing is moved that "
                f"you did not name: to go ahead, name {', '.join(owners)} in the change as well "
                "(say what you want done to each), and it is carried out", slot=edit.slot))
            continue
        held: dict[str, list[str]] = {}
        for address in changed:
            clash = socket_clash(address, edit)
            if clash:
                socket = "/".join(address.split("/")[:5])
                held.setdefault(f"{socket} (which {clash} also uses)", []).append(
                    address.rsplit("/", 1)[-1])
                continue
            edit_scope.grant(address, f"{label}: {edit.path}, named by the change")
        for socket, leaves in held.items():
            warnings.append(
                f"{edit.line()}: {socket} -- its {', '.join(leaves)} NOT written; a socket's "
                "own name, color, phantom and gain belong to the running strip on it")
        # An engine's model and parameters the bus's new preset no longer
        # sets are not written: an engine the bus still inserts, holding
        # another model now, drops the old model's parameters itself, and an
        # engine it no longer inserts keeps its effect, inserted nowhere.
        still = set(_engine_bases(edited_object(variant, edit)))
        for engine in sorted({"/".join(a.split("/")[:3]) for a in vanished
                              if a.startswith("/fx/")}):
            fx = "FX" + engine.rsplit("/", 1)[1]
            infos.append(f"{label}: {fx} " + (
                "holds the new preset's effect; the old effect's parameters go with its model"
                if engine in still else
                "is no longer inserted on it; it keeps the old preset's effect and its values, "
                "inserted nowhere, as the desk has it"))
        for address in vanished:
            if socket_clash(address, edit) or address.startswith("/fx/"):
                continue
            target = _vanished_target(address, base[address], edit, label, freed_indices,
                                      console_model)
            if target is None:
                infos.append(
                    f"{label}: with {edit.path} changed, the plan no longer states {address} "
                    f"({base[address].description}) -- left exactly as the desk has it")
                continue
            extra[address] = target
            edit_scope.grant(address, f"{label}: {edit.path}, taken away by the change")
        if not changed and not vanished:
            edit = replace(edit, writes=False)
            infos.append(f"{edit.line()} -- no console address carries it, so nothing is "
                         "written to the desk for it; it is kept (in the plan the journal "
                         "entry holds) only when the same change writes something else")
        if edit.moves_audio:
            warnings.append(
                f"{edit.line()}. This is a PHYSICAL patch change on something already "
                "running: it moves audio the moment it is written. Check what is plugged in "
                "where before you arm it.")
        if edit.switches_phantom and any(not socket_clash(a, edit) for a in changed):
            warnings.append(
                f"{edit.line()}. This switches phantom power on something already running, "
                "the moment it is written: 48V into a passive ribbon microphone destroys it, "
                "and an unbalanced or active line source can pop the PA. Check what is "
                "plugged in, and mute the strip, before you arm it.")
        written.append(edit)

    # Edits taken one at a time can each change an address that all of them
    # together take away: out of the DCA and out of the mute group empties
    # the tags. An address granted to an edit that the effective plan no
    # longer writes gets the same take-away write a single edit would.
    effective = _target_map(effective_plan)
    for address, reason in edit_scope.grants.items():
        if address in effective or address in extra or address not in base:
            continue
        mine = next((e for e in present
                     if reason.startswith(f"{edit_label(e)}: {e.path},")), present[0])
        target = _vanished_target(address, base[address], mine, edit_label(mine),
                                  freed_indices, console_model)
        if target is None:
            infos.append(f"{reason}: the changed plan no longer states {address} "
                         f"({base[address].description}) -- left exactly as the desk has it")
            continue
        extra[address] = target

    labels: list[str] = []
    for edit in written:
        label = edit_label(edit)
        if label in labels:
            continue
        labels.append(label)
        mine = [e for e in written if edit_label(e) == label]
        marker = next((e.live_marker for e in mine if e.live_marker), "")
        renumbered = [e for e in mine if e.path in ("index", "kind")]
        changes.append(Change(
            ChangeKind.EDITED, edit.word, repr(edit.name),
            marker + (
                f"renumbered ({', '.join(e.describe() for e in renumbered)}): written on its new "
                "number and cleared on its old one, with the sends, tags and routes into it -- "
                "every other object that moves is named below"
                if renumbered else
                f"only the field(s) the change names are written "
                f"({', '.join(e.path for e in mine)}); nothing else on this {edit.word} is "
                "touched, and the rest of it is in the untouched proof"), slot=edit.slot))
        infos.append(f"{label}: the change edits " + "; ".join(e.describe() for e in mine))
    # Each edit is weighed alone, so a renumber clears its old number even
    # where another object the same change renumbers lands on it (two busses
    # swapping numbers). The landing is the write, as for strips ("written
    # once, by the channel that lands"): a clear of an address the changed
    # plan still writes is not made.
    return written, [extra[a] for a in extra
                     if edit_scope.allows(a) and a not in effective], labels


#: `(plan key, console address root, human word)` for the two objects that
#: are nothing but a name and an index.
_GROUP_KINDS = (("dcas", "/dca", "dca"), ("mute_groups", "/mgrp", "mute group"))

#: What a freed DCA, mute group or output is called in a change's review.
_FREED_WORD = {"dcas": "dca", "mute_groups": "mute group", "outputs": "output"}


def _plan_new_groups(applied_plan: dict, amended_plan: dict, scope: AmendScope,
                     changes: list[Change], infos: list[str], *,
                     freed: set[tuple[str, str]] | frozenset = frozenset()) -> None:
    """DCAs and mute groups the rebuild added. `freed` are the `(key, name)`
    this run returns to free: their indices are free for a new one to take."""
    for key, root, word in _GROUP_KINDS:
        applied = _indexed_names(applied_plan, key)
        taken = {idx: name for name, idx in applied.items() if (key, name) not in freed}
        for name, index in _indexed_names(amended_plan, key).items():
            if name in applied and (key, name) not in freed:
                continue
            if index in taken:
                changes.append(Change(
                    ChangeKind.UNPLACEABLE, word, repr(name),
                    f"index {index} already belongs to {taken[index]!r} in the applied plan -- "
                    "not written",
                    proposed=f"{word}:{index}"))
                continue
            changes.append(Change(ChangeKind.ADDED, word, repr(name),
                                  f"new {word}", slot=f"{word}:{index}"))
            scope.grant(f"{root}/{index}", f"new {word} {name!r}")
            infos.append(
                f"{word} {name!r} (index {index}) was judged free from the applied plan alone -- "
                "the occupancy read covers strips, not groups")


def _plan_new_busses(applied_plan: dict, amended_plan: dict, scope: AmendScope,
                     changes: list[Change], warnings: list[str], infos: list[str], *,
                     freed: set[str] | frozenset = frozenset()) -> None:
    """`freed` are the busses this run returns to free: their indices, and the
    output sockets they fed, are free for a new bus to take."""
    applied = _indexed_names(applied_plan, "busses")
    taken = {idx: name for name, idx in applied.items() if name not in freed}
    declared_out = _declared_output_sockets(
        {**applied_plan, "busses": {n: e for n, e in (applied_plan.get("busses") or {}).items()
                                    if n not in freed}})
    for name, index in _indexed_names(amended_plan, "busses").items():
        if name in applied and name not in freed:
            continue
        if index in taken:
            changes.append(Change(
                ChangeKind.UNPLACEABLE, "bus", repr(name),
                f"index {index} already belongs to bus {taken[index]!r} in the applied plan -- "
                "not written", proposed=f"bus:{index}"))
            continue
        changes.append(Change(ChangeKind.ADDED, "bus", repr(name), "new bus",
                              slot=f"bus:{index}"))
        scope.grant(f"/bus/{index}", f"new bus {name!r}")
        infos.append(
            f"bus {name!r} (index {index}) was judged free from the applied plan alone -- the "
            "occupancy read covers strips, not busses")
        warnings.append(
            f"bus {name!r} is new, so no already-applied channel's send into it is written -- "
            "those are writes to running strips. Only the strips this amend adds will feed it.")
        entry = (amended_plan.get("busses") or {}).get(name) or {}
        # The FX engine a new bus's preset inserts is the new
        # bus's too -- unless a bus already on the desk inserts it, in
        # which case its effect is not loaded and the insert is not set.
        from atoo import bus_presets
        on_desk = bus_presets.claimed_engines(applied_plan)
        for ins in bus_presets.inserts(entry):
            engine = ins.get("engine")
            if not isinstance(engine, int):
                continue
            if engine in on_desk:
                warnings.append(
                    f"bus {name!r}: its effect {ins.get('model')} was given FX{engine}, which "
                    f"{on_desk[engine]} already uses -- not loaded, and the insert is not set")
                ins["engine"] = None
                continue
            scope.grant(f"/fx/{engine}", f"the FX engine new bus {name!r} inserts")
            infos.append(f"bus {name!r}: FX{engine} was judged free from the applied plan alone "
                         "-- the occupancy read covers strips, not FX engines")
        for group, socket in _bus_output_sockets(entry):
            if (group, socket) in declared_out:
                warnings.append(
                    f"bus {name!r} routes to output {group} {socket}, which the applied plan "
                    "already uses -- not written")
                continue
            scope.grant(f"/io/out/{group}/{socket}",
                        f"the output socket bus {name!r} feeds")


def _plan_new_outputs(applied_plan: dict, amended_plan: dict, scope: AmendScope,
                      changes: list[Change], warnings: list[str], infos: list[str], *,
                      freed: set[str] | frozenset = frozenset()) -> None:
    """Outputs the rebuild added -- the delay-speakers case.

    An output entry is two things at once: a physical socket, and an
    internal Main/Matrix that feeds it. They are granted separately,
    because the socket is almost always new and the internal object very
    often is not -- a second pair of delay speakers off Main 1 must not
    give this amendment the run of Main 1.
    """
    # An output this run returns to free (`freed`) is not on the desk any more:
    # its Main or Matrix and its sockets are free for a new output to take.
    applied_outputs = {
        str(name): entry for name, entry in (applied_plan.get("outputs") or {}).items()
        if isinstance(entry, dict) and str(name) not in freed
    }
    applied_internal = {
        (entry.get("kind"), entry.get("index")) for entry in applied_outputs.values()
    }
    declared_out = _declared_output_sockets(
        {**applied_plan, "outputs": {n: e for n, e in (applied_plan.get("outputs") or {}).items()
                                     if str(n) not in freed}})
    for name, entry in (amended_plan.get("outputs") or {}).items():
        if not isinstance(entry, dict) or str(name) in applied_outputs:
            continue
        kind, index = entry.get("kind"), entry.get("index")
        changes.append(Change(ChangeKind.ADDED, "output", repr(str(name)), "new output",
                              slot=f"{kind}:{index}" if kind and index else None))
        for socket_clause in plan_compat.output_patches(entry):
            if not isinstance(socket_clause, dict):
                continue
            group = socket_clause.get("group")
            for socket in socket_clause.get("sockets") or []:
                if not isinstance(group, str) or not isinstance(socket, int):
                    continue
                if (group, socket) in declared_out:
                    warnings.append(
                        f"output {name!r} uses socket {group} {socket}, which the applied plan "
                        "already routes -- not written")
                    continue
                scope.grant(f"/io/out/{group}/{socket}", f"the socket output {name!r} feeds")
        if kind in ("main", "matrix") and isinstance(index, int):
            root = "/main" if kind == "main" else "/mtx"
            if (kind, index) in applied_internal:
                warnings.append(
                    f"output {name!r} is fed by {kind} {index}, which the applied plan already "
                    f"uses -- {root}/{index}'s own fader, mute and EQ are NOT written, only the "
                    "new socket")
            else:
                scope.grant(f"{root}/{index}", f"the {kind} feeding new output {name!r}")
                infos.append(
                    f"{kind} {index} was judged free from the applied plan alone -- the "
                    "occupancy read covers strips, not mains and matrices")
            fed_by = entry.get("fed_by")
            if kind == "matrix" and isinstance(fed_by, dict):
                source = _fed_by_base(fed_by, amended_plan)
                if source is not None:
                    scope.grant(f"{source}/send/MX{index}",
                                f"the feed from {source} into new matrix {index}")
                    warnings.append(
                        f"output {name!r} is fed from {source}, an object that is already "
                        f"running. Exactly one node on it is written -- {source}/send/MX{index} "
                        "-- and nothing else about it is touched.")


def _plan_user_sources(applied_plan: dict, amended_plan: dict, scope: AmendScope,
                       changes: list) -> None:
    """The USR slots the amended plan defines (`user_sources`).
    A slot the applied plan did not define is new, and written, ahead of the
    channel or output that reads it (`apply.user_source_targets`). One it
    defined differently is a running slot, and is reported, not written, as
    a running strip is (D14); one it defined the same is left alone."""
    def by_slot(plan: dict) -> dict:
        return {e["slot"]: e for e in plan.get("user_sources") or []
                if isinstance(e, dict) and isinstance(e.get("slot"), int)}

    applied, amended = by_slot(applied_plan), by_slot(amended_plan)
    for slot, entry in sorted(amended.items()):
        source = entry.get("source") or {}
        words = f"{source.get('group')} {source.get('index')}"
        if slot not in applied:
            changes.append(Change(ChangeKind.ADDED, "USR slot", f"USR {slot}",
                                  f"new, from {words}", slot=f"usr:{slot}"))
            scope.grant(f"/io/in/USR/{slot}", f"new USR slot {slot}, from {words}")
        elif applied[slot] != entry:
            changes.append(Change(ChangeKind.MODIFIED, "USR slot", f"USR {slot}",
                                  f"defined differently (now from {words}); a slot already "
                                  "set on the desk is not changed by an amend",
                                  slot=f"usr:{slot}"))


def _fed_by_base(fed_by: dict, plan: dict) -> str | None:
    """The console base of whatever feeds a matrix, or None if the plan
    does not say (`apply.py` warns about that case; here it simply means
    there is nothing to grant)."""
    if fed_by.get("type") == "main" and isinstance(fed_by.get("index"), int):
        return f"/main/{fed_by['index']}"
    if fed_by.get("type") == "bus":
        index = _indexed_names(plan, "busses").get(str(fed_by.get("name")))
        if index is not None:
            return f"/bus/{index}"
    return None


def _bus_output_sockets(entry: dict) -> list[tuple[str, int]]:
    """`(group, socket)` for every physical socket a bus entry routes to."""
    out: list[tuple[str, int]] = []
    destinations = entry.get("destinations")
    if not destinations:
        single = entry.get("destination")
        destinations = [single] if isinstance(single, dict) else []
    for destination in destinations:
        if not isinstance(destination, dict) or destination.get("type") != "dedicated_output":
            continue
        for socket_clause in plan_compat.output_patches(destination):
            if not isinstance(socket_clause, dict):
                continue
            group = socket_clause.get("group")
            for socket in socket_clause.get("sockets") or []:
                if isinstance(group, str) and isinstance(socket, int):
                    out.append((group, socket))
    return out


def _declared_output_sockets(plan: dict) -> set[tuple[str, int]]:
    """Every physical output socket the applied plan already routes."""
    return set(apply_module._declared_output_patches(plan))


# --------------------------------------------------------------------------
# 3 & 4. The target filter, the "what will NOT be written" set, and the
#        scoped apply.
# --------------------------------------------------------------------------


@dataclass
class AmendmentTargets:
    """The partition: what this amend will write, and what it will not.

    Both halves come from **one** call to `apply._build_write_targets`
    over the effective plan, so the withheld set is not a second opinion
    about what a write would do -- it is literally the rest of the same
    list. That is what makes it usable as FR-2.2's witness: every address
    a full build of this plan would touch, minus the ones this amend
    owns, is exactly "every parameter of every unrelated channel".
    """

    to_write: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: The subset of `to_write` that returns a dropped channel's strip to
    #: free. A subset, not a separate list to be written by a
    #: separate path -- it goes on the wire through the same
    #: `apply_plan`, the same readback proof and the same journal -- but
    #: named apart because a clear is the change a reviewer most needs to
    #: see, and a count that folds it into "47 addresses" hides it.
    releases: list = field(default_factory=list)
    #: The subset of `to_write` that changes the named fields of objects
    #: already running -- named apart for the reason
    #: `releases` is: a write to a running strip is what a reviewer most
    #: needs to see, and a count that folds it in hides it.
    edits: list = field(default_factory=list)
    #: The subset of `to_write` that clears what a channel left behind on a
    #: strip an insert rewrites, where its new occupant states nothing of
    #: its own (`shift_clear_targets`). Named apart for the reason `releases`
    #: is.
    shift_clears: list = field(default_factory=list)
    #: Addresses that are in scope AND are written by the applied plan --
    #: the independent cross-check. Non-empty means the scope is wrong,
    #: and `apply_amendment` refuses rather than writing.
    collisions: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"{len(self.to_write)} address(es) will be written; "
            f"{len(self.withheld)} belonging to objects this amend does not own will NOT be.",
        ]
        if self.releases:
            lines.append(
                f"  {len(self.releases)} of them RETURN A STRIP TO FREE -- these CLEAR what is "
                "on the desk today:")
            for target in self.releases:
                lines.append(f"    {target.address}: {target.description}")
        if self.edits:
            lines.append(
                f"  {len(self.edits)} of them CHANGE A RUNNING OBJECT -- only the fields the "
                "change names:")
            for target in self.edits:
                lines.append(f"    {target.address}: {target.description}")
        if self.shift_clears:
            lines.append(
                f"  {len(self.shift_clears)} of them CLEAR what the channel that stood on a "
                "strip the insert rewrites left behind, where the channel that takes its "
                "place states nothing of its own:")
            for target in self.shift_clears:
                lines.append(f"    {target.address}: {target.description}")
        if self.collisions:
            lines.append(
                f"  REFUSING: {len(self.collisions)} address(es) in scope are also written by "
                "the applied plan:")
            for address in self.collisions[:10]:
                lines.append(f"    {address}")
        return "\n".join(lines)


def amendment_targets(amendment: Amendment) -> AmendmentTargets:
    """Split a full build of the effective plan into written and withheld.

    `set_fader_levels=True`, deliberately, and this is the reversal of a
    paragraph `apply.py` carried for months. The flag was written for
    this path and is the wrong mechanism for it twice over: it is global,
    so it would also suppress the fader and mute of the strips being
    *added* -- leaving a new horn channel at whatever level the last show
    left on it, which is the unsafe outcome, not the safe one -- and it
    suppresses only `fdr`/`mute` anyway, leaving an existing strip's
    name, patch, tags and every send exposed. OPTIONS-H says it directly:
    *"the target filter, not a fader flag, is the safety mechanism."*
    """
    targets, warnings = apply_module._build_write_targets(
        amendment.effective_plan, set_fader_levels=True)
    releases = release_targets(amendment, warnings=warnings)

    def owned(target) -> bool:
        return (amendment.scope.allows(target) or amendment.edit_scope.allows(target)
                or amendment.shift_scope.allows(target))

    shift_clears = shift_clear_targets(amendment, targets, warnings)
    # A clear an edit already writes (a renumbered bus's old send, on a strip
    # the insert moved): written once, by the edit.
    extra_addresses = {t.address for t in amendment.edit_extra}
    shift_clears = [t for t in shift_clears if t.address not in extra_addresses]
    # A strip a dropped channel leaves and another channel lands on in the
    # same change (an insert beside a drop) is written once, by
    # the channel that lands: the landing's own value is the clear.
    landed = {t.address for t in targets if owned(t)}
    releases = [t for t in releases if t.address not in landed]

    # An edit's addresses are the effective plan's own targets at exactly
    # the addresses `_plan_edits` granted, plus the writes that take away
    # what an edit removed (`edit_extra`, which the plan cannot produce).
    # An object a patch read off the desk and renumbered
    # is written at the values the desk read, not at what the plan's entry
    # for that same object renders (a name, a unity fader): its addresses
    # are written by those writes alone.
    read = amendment.read_from_desk
    edits = [t for t in targets if amendment.edit_scope.allows(t)
             and t.address not in read] + list(amendment.edit_extra)
    to_write = ([t for t in targets if owned(t) and t.address not in read]
                + releases + list(amendment.edit_extra) + shift_clears)
    withheld = [t for t in targets if not owned(t)]

    applied_targets, applied_warnings = apply_module._build_write_targets(
        amendment.applied_plan, set_fader_levels=True)
    applied_addresses = {t.address for t in applied_targets}
    # The collision guard keeps its meaning -- "an address of a strip this
    # amend was never supposed to touch" -- by excluding the overlap that
    # IS the point. A release deliberately writes addresses the applied
    # plan wrote; that is what returning a strip to free means. Everything
    # else overlapping the applied plan is still a refusal.
    # The same holds for an edit: its addresses are, by definition, ones the
    # applied plan writes -- but only the exact leaves its named fields own.
    collisions = sorted(
        {t.address for t in to_write if not amendment.release_scope.allows(t)
         and not amendment.edit_scope.allows(t) and not amendment.shift_scope.allows(t)}
        & applied_addresses)

    # Only the warnings the NEW objects caused. A build of the effective
    # plan warns about every strip in it, including nineteen that were
    # applied hours ago and are not this run's business -- printing those
    # in a review buries the one that is. Attributed by difference against the
    # applied plan's own warnings rather than by matching object names out
    # of free text, because the text is written for a person to read and
    # will keep changing.
    already_said = set(applied_warnings)
    ours = [w for w in warnings if w not in already_said]

    return AmendmentTargets(to_write=to_write, withheld=withheld,
                            warnings=ours, collisions=collisions, releases=releases,
                            edits=edits, shift_clears=shift_clears)


def release_targets(amendment: Amendment, *, warnings: list[str] | None = None) -> list:
    """The writes that return this amendment's dropped channels to free.

    One function, called by both `amendment_targets` (for the preview and
    the count) and `apply_amendment` (for the wire), so the addresses a
    reviewer was shown are the addresses that get written. Nothing reaches
    here that `release_refusal` has not cleared -- `Amendment.releases` is
    only ever filled by `plan_amendment`, and only for a strip the desk
    confirmed is still ours.
    """
    applied = amendment.applied_plan
    freed: list = []
    if amendment.freed_busses:
        # What the same run writes for another object -- a new bus reusing
        # the index -- is that object's, not a reset.
        built, _said = apply_module._build_write_targets(
            amendment.effective_plan, set_fader_levels=True)
        freed = apply_module.release_bus_write_targets(
            amendment.freed_busses, console_model=amendment.console_model,
            written={t.address for t in built},
            keep_outputs=_declared_output_sockets(amendment.effective_plan))
    if amendment.freed_objects:
        built, _said = apply_module._build_write_targets(
            amendment.effective_plan, set_fader_levels=True)
        freed += apply_module.release_object_write_targets(
            amendment.freed_objects, console_model=amendment.console_model,
            written={t.address for t in built},
            keep_outputs=_declared_output_sockets(amendment.effective_plan),
            plan=amendment.applied_plan)
    return freed + apply_module.release_write_targets(
        amendment.releases,
        # The APPLIED plan's indices, not the rebuild's: these have to be
        # the numbers this strip was actually written with, and a rebuild
        # that renumbered a DCA would otherwise clear the wrong tag.
        dca_index=_indexed_names(applied, "dcas"),
        mute_group_index=_indexed_names(applied, "mute_groups"),
        bus_index=_indexed_names(applied, "busses"),
        matrix_index=apply_module.matrix_indices(applied),
        keep_sockets=amendment.keep_sockets,
        shared_sockets=apply_module._shared_source_sockets(applied),
        console_model=amendment.console_model,
        warnings=warnings)


def shift_clear_targets(amendment: Amendment, built: list, warnings: list[str]) -> list:
    """What an insert must clear on the strips it rewrites.

    A moved channel is written whole on its new strip -- `built`, the build
    of the effective plan, already carries that. A build writes only what a
    plan states, though, and the strip it writes onto was the previous
    occupant's: a send the old occupant had, a DCA tag, a processing value,
    a fader it set would all stay on a strip that is now somebody else. So
    for each rewritten strip that had an occupant, the writes that return
    that occupant's strip to the reading an untouched one gives
    (`apply.release_write_targets`, the same ones a returned-to-free strip
    gets) are kept for every address the new occupant's own build does NOT
    write. Never the sockets: a socket belongs to the source, and the source
    moved with its channel, so `/io/in/...` is not here at all.
    """
    if not amendment.shift_occupants:
        return []
    written = {t.address for t in built}
    applied = amendment.applied_plan
    clears: list = []
    said: list[str] = []
    for label, occupant in amendment.shift_occupants:
        for target in apply_module.release_write_targets(
                [occupant],
                dca_index=_indexed_names(applied, "dcas"),
                mute_group_index=_indexed_names(applied, "mute_groups"),
                bus_index=_indexed_names(applied, "busses"),
                matrix_index=apply_module.matrix_indices(applied),
                keep_sockets=amendment.keep_sockets,
                shared_sockets=apply_module._shared_source_sockets(applied),
                console_model=amendment.console_model,
                warnings=said):
            if target.address.startswith(f"/{label.replace(':', '/')}/") \
                    and target.address not in written:
                clears.append(replace(target, description=target.description.replace(
                    "returned to free: ", "left by the channel the insert moved off it: ", 1)))
    # What the clear could not undo stays on the strip, and is said. The rest
    # of what a release says (a socket another strip keeps) is about returning
    # a strip to free, which this is not.
    warnings.extend("insert: " + w.replace("cannot return", "cannot clear", 1)
                    .replace(" to free for ", " for ", 1)
                    for w in dict.fromkeys(said) if w.startswith("cannot return "))
    return clears


def witness_addresses(targets: AmendmentTargets) -> list[tuple[str, str]]:
    """FR-2.2's proof set: `(address, value_type)` for every address a
    full build would have written and this amend will not.

    Read before the delta and again after; any value that moved is a
    write that escaped the filter. This is a stronger claim than "we did
    not generate that address", which is the claim the filter itself
    makes -- and FR-2.2 asks for the stronger one in as many words:
    *"not merely by not writing to it."*
    """
    seen: dict[str, str] = {}
    for target in targets.withheld:
        seen.setdefault(target.address, target.value_type)
    return sorted(seen.items())


@dataclass(frozen=True)
class WitnessPlan:
    """FR-2.2's proof set, and whether this run is going to read it.

    A preview's own witness read was costing nine of the
    fifteen seconds A15 took on hardware -- 672 addresses read twice, at
    6.75ms each, to establish that a run which sent no packets moved no
    values. That is a tautology, and this dataclass is where it stops
    being paid for.

    The set itself is computed either way, and reported either way: a
    preview should still tell the engineer what the proof *will* cover
    when they arm it. What a preview does not do is send 1,344 GETs to
    find out that nothing changed.
    """

    #: `(address, value_type)`, in read order. Always the full set --
    #: never narrowed to make a run faster. A smaller witness set is a
    #: weaker proof, and FR-2.2 exists to make the stronger claim.
    addresses: tuple[tuple[str, str], ...]
    #: Will the before/after passes actually run?
    read: bool
    #: Why not, when `read` is False. Empty when it is True.
    reason: str = ""

    def __len__(self) -> int:
        return len(self.addresses)

    def line(self) -> str:
        """The one line the CLI prints ahead of the write, whichever way
        this went. A preview says what the proof set *would be*, because
        "672 addresses will be read" is the thing the engineer is
        deciding about when they decide to arm."""
        if self.read:
            return (f"Untouched-strip proof: {len(self.addresses)} unrelated "
                    "address(es) will be read before and after to prove nothing else moved.")
        return (f"Untouched-strip proof: not run -- {self.reason}. The proof set is "
                f"{len(self.addresses)} unrelated address(es), read before and after on a "
                "--confirm run.")


def witness_plan(targets: AmendmentTargets, *, confirm: bool,
                 skip: bool = False) -> WitnessPlan:
    """Whether FR-2.2's before/after read runs on this amend, and over
    what.

    **Two arguments, deliberately not one**. The caller
    passes the two facts -- is this a real write, and did the user ask to
    skip the proof -- and this function decides; it is not handed a
    single `should_read` boolean it can be lied to with. That separation
    is the property worth having: **there is no argument a PREVIEW can
    set that turns the proof off for a CONFIRMED run.** Making a preview
    cheap and weakening a real write's proof must not be the same switch.

    * `confirm=False` -- a preview. It writes nothing, so there is
      nothing for the proof to prove: FR-2.2 is a claim about what an
      amend *did* to addresses it does not own, and an amend that sent no
      packets did nothing to any of them. The set is still computed and
      still reported.
    * `skip=True` -- the user passed `--skip-untouched-proof`. Their
      call, on a real write, and the one way to make a confirmed run skip
      it.

    The set is **never narrowed** to save time. Reading fewer addresses
    would be a weaker claim, and FR-2.2's whole point is the stronger one
    -- "not merely by not writing to it". What makes it cheap on a
    confirmed run is `read_witness`'s node-dump path, not a shorter list.
    """
    addresses = tuple(witness_addresses(targets))
    if not confirm:
        return WitnessPlan(addresses, False,
                           "this is a preview and nothing is written, so there is nothing "
                           "for a before/after read to prove")
    if skip:
        return WitnessPlan(addresses, False, "--skip-untouched-proof was passed")
    return WitnessPlan(addresses, True)


def witness_requests(witness, *, bulk: bool = True) -> int:
    """How many console round trips ONE witness pass costs, the way
    `read_witness` will actually do it.

    Pure -- it contacts nothing, the same contract `occupancy_read_plan`
    has. The CLI has no use for it; the test suite and the measurement of a witness pass
    do, because "is this inside the 3-4s budget" is a
    question about request counts and the two measured rates in
    `watch_scope.py`, and neither should have to be re-derived by hand.
    """
    addresses = getattr(witness, "addresses", witness)
    if not bulk:
        return len(addresses)
    by_node, alone = audit.group_plan_by_node(list(addresses))
    return len(by_node) + len(alone)


def read_witness(console, witness, *, progress=None,
                 bulk: bool = True) -> dict[str, object]:
    """Read every witness address. An address that does not answer is
    recorded as the sentinel `UNREAD`, never omitted -- "it did not answer
    before and it did not answer after" is a clean pass, and dropping it
    would let a strip that stopped answering halfway through look
    untouched.

    `witness` is a `WitnessPlan` or a bare `(address, value_type)` list.

    `bulk` (default **True**) fetches most of the set with
    node dumps -- one `,s *` query per object rather than one GET per
    leaf, the same path `audit.read_console_state(bulk=True)` uses.
    On A15's 672-address witness set that is **139 requests instead of
    672**, and at the A11-measured rates (`watch_scope`: 10.30ms per
    node-dump request against 6.75ms per leaf) it takes one pass from
    4.54s to 1.43s. It falls back to per-leaf for a console object with
    no `node_dump`, and for every leaf a dump did not carry.

    **Mixing the two paths across the before and after passes is safe,
    and A11 is why.** A dump carries the text form, which is already the
    number the desk shows; a per-leaf GET is offset by one for a handful
    of leaves and `console_facts.correct_readback_index` puts that back.
    A11 read a whole Compact both ways -- 5,712 values -- and found
    **eight** disagreements, all `/aux/{n}/in/conn/in`, which is now in
    that correction table. So the two paths agree address for address,
    and a leaf that comes out of a dump in one pass and a GET in the
    other cannot fake a MOVED.

    The set is never narrowed here either: `bulk` changes how the
    addresses are fetched, never which ones.
    """
    addresses = list(getattr(witness, "addresses", witness))
    values: dict[str, object] = {}
    # Imported here, not at module scope, for the reason `audit.py` gives:
    # `atoo.console` is the network layer and this module is imported
    # by code that never opens a socket.
    from atoo import console as osc

    def on_start(address: str) -> None:
        if progress is not None:
            progress.start_address(address)

    def read_leaves(pairs) -> None:
        # Up to the console's window of GETs in flight.
        pairs = list(pairs)
        replies = osc.read_in_windows(console, [address for address, _ in pairs],
                                      on_start=on_start)
        for (address, value_type), (_address, reply) in zip(pairs, replies):
            if progress is not None:
                progress.finish_address(answered=reply is not None)
            if reply is None:
                values[address] = UNREAD
                continue
            value, error = reply.value(value_type)
            values[address] = UNREAD if error is not None else facts.correct_readback_index(
                address, value)

    if not bulk or not hasattr(console, "node_dump"):
        read_leaves(addresses)
        return values

    by_node, alone = audit.group_plan_by_node(addresses)
    if progress is not None and hasattr(progress, "set_total"):
        progress.set_total(len(by_node) + len(alone))
    dumps = osc.node_dumps(console, list(by_node), on_start=lambda node: on_start(node + " (node)"))
    for (node, wanted), (_node, dump) in zip(by_node.items(), dumps):
        parsed: dict[str, str] = {}
        if dump is not None:
            try:
                parsed = osc.parse_node_dump(node, dump)
            except osc.NodeDumpError:
                # Half a dump is worse than none -- the node's leaves each
                # cost a round trip instead, and nothing else changes.
                parsed = {}
        if progress is not None:
            progress.finish_address(answered=dump is not None)
        for address, value_type in wanted:
            text = parsed.get(address)
            if text is None:
                alone.append((address, value_type))
                if progress is not None and hasattr(progress, "add_total"):
                    progress.add_total()
                continue
            value, error = osc.value_from_dump_text(text, value_type)
            if error is not None:
                alone.append((address, value_type))
                if progress is not None and hasattr(progress, "add_total"):
                    progress.add_total()
                continue
            # Deliberately NOT `correct_readback_index` -- see
            # `console.value_from_dump_text`, and this function's
            # docstring for why mixing the two paths is safe.
            values[address] = value

    read_leaves(alone)
    return values


class _Unread:
    """A value that was not read. Its own type rather than None, so it
    cannot be confused with a console that genuinely answered null."""

    def __repr__(self) -> str:
        return "UNREAD"

    def __eq__(self, other) -> bool:
        return isinstance(other, _Unread)

    def __hash__(self) -> int:
        return hash("UNREAD")


UNREAD = _Unread()


def witness_changes(before: dict[str, object], after: dict[str, object],
                    witness) -> list[str]:
    """Every witness address whose value moved across the delta, reported
    by address in read order -- the FR-2.2 assertion.

    Compared with `apply._values_equal`, the same type-aware comparison
    the write path uses, so a float that the desk rounds to its own step
    is not reported as a change (the lesson, one comparison in
    one place).
    """
    moved: list[str] = []
    for address, value_type in getattr(witness, "addresses", witness):
        was, now = before.get(address, UNREAD), after.get(address, UNREAD)
        if was is UNREAD or now is UNREAD:
            if not (was is UNREAD and now is UNREAD):
                moved.append(address)
            continue
        if not apply_module._values_equal(value_type, was, now, address):
            moved.append(address)
    return moved


class AmendRefused(Exception):
    """The amendment cannot be written as computed. Raised rather than
    returned because there is no partial version of this: an amend that
    touches one address it should not have is a worse failure than one
    that refuses to run."""


def apply_amendment(amendment: Amendment, console, *, dry_run: bool = True,
                    journal_path: str | None = None,
                    targets: AmendmentTargets | None = None,
                    desk: dict | None = None,
                    model_check: dict | None = None,
                    phases=None):
    """Write only the objects this amendment adds and the strips it
    returns to free, and prove it.

    Same `apply_plan` as a full build -- same `--confirm` arming through
    `dry_run`, same per-address readback, same journal -- with the target
    filter passed in and the scope recorded. Refuses outright (never
    partially) when the amendment is blocked, or when the independent
    collision check finds an address that both plans write.

    A strip being **returned to free** rides the same path,
    as `extra_targets`: journalled with its prior value, read back and
    proved like every other write, and behind the same single `--confirm`.
    There is deliberately no separate arming for a clear. OPTIONS-H:
    *"Exactly one screen in Atoo writes to a console. Two arming
    checkboxes on two screens is twice the surface for the failure Apply
    exists to prevent."* The thing that makes a clear safe is not a second
    switch the user learns to tick, it is `release_refusal` -- and a
    second switch would invite ticking it past a refusal.

    `desk` and `model_check` are journalled exactly as `apply` journals
    them (`apply_plan`'s own arguments): the desk block with its raw
    `model_token`, and what `preflight`'s `apply.check_desk_model` said
    when it said anything -- the cross-model INFO or the unmeasured-model
    WARNING.

    `phases` (a `progress.Phases`) is passed to `apply_plan`,
    which reports its read and write phases as they happen.
    """
    targets = targets or amendment_targets(amendment)
    if amendment.blocked:
        raise AmendRefused(
            "this amendment is blocked:\n"
            + "\n".join("  " + c.line() for c in amendment.blocked))
    if targets.collisions:
        raise AmendRefused(
            f"{len(targets.collisions)} address(es) in this amend's scope are also written by "
            "the applied plan, which means the scope is wrong:\n"
            + "\n".join(f"  {a}" for a in targets.collisions[:20]))
    return apply_module.apply_plan(
        amendment.effective_plan, console,
        dry_run=dry_run, journal_path=journal_path,
        target_filter=amendment.allows,
        extra_targets=targets.releases + list(amendment.edit_extra) + targets.shift_clears,
        journal_scope=amendment.journal_scope(),
        desk=desk, model_check=model_check, phases=phases,
    )


# --------------------------------------------------------------------------
# The pre-flight
# --------------------------------------------------------------------------
#
# `apply` verifies a plan before it writes, and also checks every
# socket it patches against the model the desk says it is. `amend` did
# neither: it used the desk's model only to pick a freed strip's factory
# patch, and would have written a new strip onto LCL 20 of a full-size WING
# (8 local inputs) without a word. That is the case
# which IS an error -- a socket that does not exist is a physical setting
# the desk cannot be left in -- so amend now asks the same two questions,
# with the same answers, before its preview is offered for arming.


def _written_output_sockets(amendment: Amendment) -> list[tuple[str, int]]:
    """`(group, socket)` for every physical output this amend writes: the
    `/io/out/{group}/{n}` grants `_plan_new_busses`/`_plan_new_outputs`
    made. An output socket the applied plan already routes was never
    granted, and is not written."""
    sockets: list[tuple[str, int]] = []
    for base in amendment.scope.grants:
        parts = base.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["io", "out"] and parts[3].isdigit():
            sockets.append((parts[2], int(parts[3])))
    return sockets


def _written_channels(amendment: Amendment) -> list[tuple[dict, str]]:
    """`(channel entry, what)` for every input socket this amend writes to:
    each new or repatched strip's own entry. A strip returned to free is
    written OFF, which names no socket."""
    written: list[tuple[dict, str]] = []
    new = set(amendment.strips)
    moved_to = {landing: name for name, _old, landing in amendment.shifted}
    for channel in amendment.effective_plan.get("channels") or []:
        if not isinstance(channel, dict) or not isinstance(channel.get("channel"), int):
            continue
        label = _slot_label(_channel_slot(channel))
        if label in new:
            written.append((channel, f"channel {channel.get('name')!r}, new on {label}"))
        elif label in moved_to:
            written.append((channel, f"channel {channel.get('name')!r}, moved to {label} "
                                     "by the insert"))
        elif any(e.key == "channels" and e.slot == label and e.path.split(".")[0] == "patch"
                 for e in amendment.edits):
            written.append((channel, f"channel {channel.get('name')!r} on {label}, "
                                     "repatched by the change"))
    return written


def written_sockets_missing(amendment: Amendment, console_model: str) -> list[dict]:
    """Every socket this amend WRITES that `console_model`'s panel does not
    have, as `{"socket": "LCL 20", "what": "channel 'Trumpet', new on
    ch:21", "line": ...}`.

    Only what is written, which is two things:

    * a new strip's input patch (and so the socket whose name, colour and
      phantom that strip carries);
    * every output socket a new bus or output is granted.

    The running strips are not here: amend does not write them, and the
    pre-flight verify of the whole effective plan is what looks at those.
    Each line is `apply.sockets_missing_on_model`'s own, so apply and amend
    word a missing socket identically and bound it by the same table.
    """
    missing: list[dict] = []

    def add(lines: list[str], what: str) -> None:
        for line in lines:
            missing.append({"socket": line.split(" (", 1)[0], "what": what,
                            "line": f"{line}; {what}"})

    for channel, what in _written_channels(amendment):
        add(apply_module.sockets_missing_on_model(
                {"channels": [channel]}, console_model, output_sockets=()), what)
    grants = amendment.scope.grants
    for group, n in sorted(_written_output_sockets(amendment)):
        add(apply_module.sockets_missing_on_model(
                {}, console_model, output_sockets=[(group, n)]),
            grants.get(f"/io/out/{group}/{n}") or "a new output")
    return missing


@dataclass
class Preflight:
    """What amend's pre-flight concluded, before anything is written. See `preflight`."""

    #: The model the sockets and the verify were checked against: the
    #: desk's, when it said one Atoo has measured, else the plan's.
    checked_against: str | None
    desk_model: str | None
    #: The rebuild's own `meta.console_model` -- the model the effective
    #: plan was built for.
    plan_model: str | None
    #: How the checked-against model is named in a sentence: "the WING
    #: Compact at 198.51.100.6", or where it came from when not the desk.
    where: str
    skip_verify: bool = False
    #: `verify_plan.VerifyResult` over the effective plan, or None with
    #: --skip-verify.
    verify: object = None
    #: `apply.DeskModelCheck` over the written sockets, or None offline.
    model_check: object = None
    missing: list[dict] = field(default_factory=list)
    #: The refusal, when there is one. Its last line stands on its own.
    refusal: str | None = None
    #: `amend.socket-missing-on-desk` or `amend.verify-failed`.
    refusal_code: str | None = None
    #: What the pre-flight chose on its own and says at INFO: how the input
    #: list was held to the plan.
    infos: list[str] = field(default_factory=list)

    @property
    def refuses(self) -> bool:
        return self.refusal is not None

    def journal_model_check(self) -> dict | None:
        """The `model_check` block for the journal, exactly as `apply`
        records one: only when the check said something, and never a
        socket refusal -- a refused amend writes no journal."""
        check = self.model_check
        if check is None or not check.message or check.refuses:
            return None
        return check.to_journal()

    def to_review(self) -> dict:
        verify = self.verify
        return {
            "checked_against": self.checked_against,
            "where": self.where,
            "desk_model": self.desk_model,
            "plan_model": self.plan_model,
            "skip_verify": self.skip_verify,
            "verified": verify is not None,
            "verify": None if verify is None else {
                "errors": [str(f) for f in verify.errors],
                "warnings": [str(f) for f in verify.warnings],
                "report": verify.report(),
            },
            "model_check": self.journal_model_check(),
            "missing": [m["line"] for m in self.missing],
            "refusal": self.refusal,
            "refusal_code": self.refusal_code,
            "infos": list(self.infos),
        }


def _named(missing: list[dict]) -> str:
    names = list(dict.fromkeys(f"{m['socket']} ({m['what']})" for m in missing))
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def preflight(amendment: Amendment, *, identity_args=None, address: str | None = None,
              skip_verify: bool = False, presets=None, what: str = "amend",
              rows=None, rows_name: str = "the input list", layers=None,
              aes50_devices: dict | None = None) -> Preflight:
    """`apply`'s two pre-flight checks, asked of an amend.

    `what` is "amend" or "change" (a typed change, `atoo patch`): only the words of a refusal differ -- "This change would patch
    1 socket(s)...", where "patch" keeps its meaning of socket routing.

    1. **The verify gate**, over the EFFECTIVE plan -- the rebuild with this
       amend's placements, which is what a confirmed bundle amend makes
       `plan.json` -- against the desk's model: errors block, warnings do
       not, exactly `apply`'s gate. `skip_verify` skips it, as `apply
       --skip-verify` does, for the same reason: the flag is a judgement
       about the plan's findings, and a finding the engineer already chose
       to write past with `apply --skip-verify` is still in every rebuild
       of that show, so without it the show could never be amended at all.
    2. **The socket check** (`apply.check_desk_model`, and
       `apply.sockets_missing_on_model` over `written_sockets_missing`),
       over the sockets this amend actually WRITES. A socket the desk does
       not have is refused, by name and naming the channel, **with or
       without `skip_verify`** -- that flag is about the plan; this is
       about the hardware. Unlike `apply`, the socket check runs on the
       same model too, not only across models: amend writes a handful of
       sockets, checking them costs nothing, and with `skip_verify` it is
       the only thing standing between a bad rebuild and the panel.
       A different model with every socket present proceeds with
       `check_desk_model`'s own INFO; a desk whose model Atoo has
       never measured proceeds with its WARNING, sockets checked against
       the plan's model.

    `rows` is the show's input list, when it has one: the verify then runs
    the checks that need it, and `reconcile.not-checked` appears only when
    there really is none. An amend is a rebuild and is held to the whole
    list, as a full build is. A change (`what="change"`) is not a rebuild,
    so it is held to the list as `verify_plan.rows_for_a_change` cuts it:
    the channels the change adds, or a previous change added, are checked
    against the change that made them rather than called invented, and rows
    the plan does not use are not called dropped. That choice is said at
    INFO in `Preflight.infos`, with `rows_name` for the file. `layers` are
    the texts a channel built from them is checked against, as `apply` finds
    them.

    `aes50_devices` is what the desk named on each AES50 port
    (`apply.read_aes50_devices`): a socket this amend writes past the end of
    the stage box on its port (A 17 on an S16) does not exist, and is
    refused in the same words and the same way as a socket the panel lacks.
    A box Atoo has no size for is said at INFO and left unchecked.

    `identity_args` is the desk's `/?` reply, or None offline (`amend
    --state`), when there is no desk to ask and the plan's model stands
    in -- said, in `where`.
    """
    from atoo.verify_plan import verify_plan

    plan_model = resolve_console_model(amendment.effective_plan)
    desk_model = facts.model_from_identity(identity_args) if identity_args is not None else None
    checked = desk_model or plan_model
    label = facts.CONSOLE_MODELS[checked]["label"] if checked in facts.CONSOLE_MODELS else None
    if desk_model is not None:
        where = f"the {label} at {address}"
    elif label is None:
        where = "no model at all -- neither the desk nor the plan states one"
    elif identity_args is not None:
        where = (f"the {label}, the plan's own model -- {address} did not say which WING "
                 "it is")
    elif address:
        where = f"the {label} the plan is for -- {address} was not asked its model"
    else:
        where = f"the {label} the plan is for (reviewed offline: no desk was asked)"
    result = Preflight(checked_against=checked, desk_model=desk_model, plan_model=plan_model,
                       where=where, skip_verify=skip_verify)

    checked_rows = rows
    if rows is not None and what == "change":
        from atoo.verify_plan import rows_for_a_change

        checked_rows, stand_ins, set_aside = rows_for_a_change(
            amendment.effective_plan, rows,
            changed={c.get("name") for c, _ in _written_channels(amendment)})
        unlisted = (f"; {len(stand_ins)} channel(s) of the changed plan are not on it "
                    f"({', '.join(stand_ins[:5])}{', ...' if len(stand_ins) > 5 else ''}) -- "
                    "added by this change, an earlier one or the conventions -- and are taken "
                    "as they stand, not called invented" if stand_ins else "")
        result.infos.append(
            f"{rows_name}: {len(checked_rows) - len(stand_ins)} of its {len(rows)} row(s) are "
            f"used by the changed plan and were checked as a full build checks them (stated "
            f"sockets and presets, phantom power against the microphone){unlisted}. A row the "
            "plan does not use is not called dropped: a change does not rebuild the show"
            + (f". For {', '.join(set_aside)} the change states a socket other than the one "
               f"{rows_name} does, and the change's stands" if set_aside else ""))
    elif rows is not None:
        result.infos.append(f"{rows_name}: {len(rows)} row(s), checked against the amended "
                            "plan as a full build checks them")
    if not skip_verify:
        result.verify = verify_plan(amendment.effective_plan, checked_rows, presets=presets,
                                    console_model=desk_model, layers=layers)

    if identity_args is not None:
        # The check, handed only what this amend writes -- so across
        # models its outcome, and the INFO or WARNING it words, is about
        # those sockets and nothing it leaves alone.
        written = {"channels": [channel for channel, _ in _written_channels(amendment)]}
        result.model_check = apply_module.check_desk_model(
            written, plan_model, identity_args, address or "the desk",
            skip_verify=skip_verify, output_sockets=_written_output_sockets(amendment))
    if checked in facts.CONSOLE_MODELS:
        result.missing = written_sockets_missing(amendment, checked)
    on_boxes: list[dict] = []
    if aes50_devices:
        written = {"channels": [channel for channel, _ in _written_channels(amendment)]}
        on_boxes = apply_module.box_sockets_missing(
            written, aes50_devices, output_sockets=_written_output_sockets(amendment))
        for row in on_boxes:
            result.missing.append({"socket": row["socket"], "what": row["what"],
                                   "line": row["line"], "box": row["box"]})
        for port, device in apply_module.unknown_boxes(aes50_devices).items():
            result.infos.append(
                f"AES50-{port} reports a {device!r}, and Atoo has no size recorded for it, so "
                f"the sockets written on {port} were not checked against the box")

    if result.missing:
        lines = "\n".join(f"  - {m['line']}" for m in result.missing)
        across = ""
        if desk_model is not None and plan_model not in (None, desk_model) \
                and plan_model in facts.CONSOLE_MODELS:
            across = (f"The rebuild is for a {facts.CONSOLE_MODELS[plan_model]['label']}; "
                      f"this desk is a {label}.\n")
        source = "the change" if what == "change" else "the rebuild"
        fix = (f"Rebuild for this desk (--console-model {desk_model}), or repatch to "
               "sockets it has." if across else f"Repatch {source} to sockets this desk has.")
        if on_boxes:
            # A socket past the end of a stage box does not exist on that box,
            # and the desk says nothing of it: said by the box, with its size.
            boxes = list(dict.fromkeys(row["box"] for row in on_boxes))
            only_boxes = len(on_boxes) == len(result.missing)
            where = ((", ".join(boxes[:-1]) + f" and {boxes[-1]}") if len(boxes) > 1
                     else boxes[0]) if only_boxes else f"{where} and its stage boxes"
            fix = f"Repatch {source} to sockets the box has."
        refusing = "Refusing to write this change" if what == "change" else "Refusing to amend"
        several = len({m["socket"] for m in result.missing}) > 1
        result.refusal = (
            f"This {what} would patch {len(result.missing)} socket(s) that do not exist on "
            f"{where}:\n{lines}\n{across}"
            f"{refusing}: {_named(result.missing)} {'do' if several else 'does'} not "
            f"exist on {where}. Nothing was written; --skip-verify does not change that. {fix}")
        result.refusal_code = ("amend.socket-missing-on-box" if on_boxes
                               and len(on_boxes) == len(result.missing)
                               else "amend.socket-missing-on-desk")
    elif result.verify is not None and result.verify.errors:
        if what == "change":
            result.refusal = (
                f"Refusing to write this change: the changed plan does not verify against "
                f"{where} -- {len(result.verify.errors)} error(s), listed above. Nothing was "
                "written. Say the change again, or pass --skip-verify if you have a reason to "
                "write it anyway (the sockets this change writes are checked either way).")
        else:
            result.refusal = (
                f"Refusing to amend: the amended plan does not verify against {where} -- "
                f"{len(result.verify.errors)} error(s), listed above. Nothing was written. Fix "
                "the rebuild, or pass --skip-verify if you have a reason to write it anyway "
                "(the sockets this amend writes are checked either way).")
        result.refusal_code = "amend.verify-failed"
    return result


# --------------------------------------------------------------------------
# The review, as data
# --------------------------------------------------------------------------


def review_payload(occupancy: list[StripStatus], amendment: Amendment,
                   targets: AmendmentTargets) -> dict:
    """Stages 1-3 of one amend, as the JSON `atoo amend --review-json`
    writes -- the Apply screen's Amend mode draws its review from it.

    **Nothing here decides anything.** Every verdict is one this module
    already reached -- `StripStatus.state`, `Change.kind`, the
    `AmendmentTargets` partition -- and every sentence is the one the
    command prints (`occupancy_summary`, `Amendment.summary`,
    `AmendmentTargets.summary`, `Change.line`), carried verbatim so the
    page and the terminal cannot word the same review differently. The
    page renders; the command judges.

    Two things are kept apart that a flat list would merge, because the
    page must not merge them:

    * `unknown` is its own state, never folded into `free`. An unread
      strip is not a safe strip (OPTIONS-H).
    * `name` and `source_name` are both carried. On a WING a name typed
      at the desk lands on the socket, so a strip whose own name is blank
      can be somebody's "Podium" -- the strip's own name is not the
      whole truth, and a review that showed only it would say "free".
    """
    return {
        "occupancy": [
            {
                "label": s.label,
                "bank": s.bank,
                "number": s.number,
                "state": s.state.value,
                "name": s.name,
                "source_name": s.source_name,
                "patch": list(s.patch) if s.patch is not None else None,
                "unread": list(s.unread),
            }
            for s in occupancy
        ],
        "occupancy_summary": occupancy_summary(occupancy),
        "changes": [
            {
                # The enum NAME, not its value: RELEASED's value is the
                # phrase "returned to free", and a page keying CSS off it
                # would be keying off prose.
                "kind": c.kind.name.lower(),
                "object": c.kind_of_object,
                "where": c.where,
                "reason": c.reason,
                "slot": c.slot,
                "proposed": c.proposed,
                "line": c.line(),
            }
            for c in amendment.changes
        ],
        "amendment_summary": amendment.summary(),
        "strips": list(amendment.strips),
        "released": list(amendment.released),
        # An explicit insert's renumbering: every strip that moves, where
        # from and where to, in strip order -- the page lists them all.
        "shifted": [{"name": name, "from": old, "to": new}
                    for name, old, new in amendment.shifted],
        # Each named field a change sets on something
        # already running, old -> new, with `moves_audio` for a physical
        # patch change -- the page marks those before anything else.
        "edited": list(amendment.edited),
        "edits": [e.to_json() for e in amendment.edits],
        "edit_targets": [{"address": t.address, "description": t.description}
                         for t in targets.edits],
        "infos": list(amendment.infos),
        "warnings": list(amendment.warnings),
        "blocked": bool(amendment.blocked),
        "collisions": list(targets.collisions),
        "to_write": [{"address": t.address, "description": t.description}
                     for t in targets.to_write],
        "releases": [{"address": t.address, "description": t.description}
                     for t in targets.releases],
        "shift_clears": [{"address": t.address, "description": t.description}
                         for t in targets.shift_clears],
        # Addresses only: this is the "what will NOT be written" set, and
        # it is hundreds long -- the page groups it by object.
        "withheld": [t.address for t in targets.withheld],
        "targets_summary": targets.summary(),
        "targets_warnings": list(targets.warnings),
        # Filled in by the command after the write, when FR-2.2's
        # before/after read has run (or has been reported as not run).
        "proof": None,
    }
