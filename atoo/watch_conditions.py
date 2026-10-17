"""FR-6.5: operator-authored "watch conditions" -- structured, deterministic
alert rules, distinct from `atoo.audit`'s fixed structural rule
catalogue (`DEFAULT_RULES`). Where `DEFAULT_RULES` catches things this
project has decided are *always* worth flagging (a bus with no inputs, a
DCA closed over active members, ...), a watch condition lets an operator
say something true only of THIS show: "the crowd mic must never be
unmuted, and its fader must always be all the way down."

**Drafted or hand-written, evaluated identically.** A show
bundle's build proposes a watchlist and merges it into `DIR/watch.json`
(`cli._draft_watchlist_into_bundle`), but nothing in this module knows or
cares which conditions a model suggested: a draft goes through
`parse_watch_conditions` before it reaches disk, exactly as a file read
from disk does. The two schema additions that merge needs are the optional
per-condition `source` and the top-level `drafted` list -- see
`merge_drafted_conditions`, which is also where the merge rules are
written down.

**Structured, not plain-English (the own resolved framing).**
Watch has to run without AI available, which means structured rules:
the user or some other deterministic process or AI model could write
the file once the format is defined. This module is that structured format and its
evaluator -- zero AI anywhere in this file or in the runtime path that
uses it. Plain-English/AI-assisted authoring is a deliberately separate,
later concern (see the issue), not attempted here.

**Field vocabulary: `muted`, `fader_db`, `dca`, `mute_group`, `patch`,
`send_on`, `send_db`, `send_mode`, `phantom`.** `muted` and `fader_db` are
scalar -- a plain `field <operator> value` comparison. `dca`, `mute_group` and `patch` are a different
SHAPE of question ("is channel X a member of DCA Y", "is channel X
patched to AES50-A 12"), and they carry it on the existing two operators
rather than inventing a third: **`==` asserts
membership, `!=` asserts non-membership.**

    "field": "dca", "operator": "==", "value": "Drums"
        -> fires when the channel is NOT in the DCA named Drums
    "field": "mute_group", "operator": "!=", "value": "FX"
        -> fires when the channel IS in the mute group named FX

Same "assertion violated -> finding" polarity as every scalar field: the
condition states what should be true, a `Finding` is it not being true.

`value` is a group NAME for `dca`/`mute_group`, resolved against live
state the way `audit.diff_against_plan` resolves DCA/mute-group identity
(`audit.strip_group_membership`, shared with it rather than
reimplemented) -- a name matching zero or more than one live group is
skipped that cycle. For `patch` it is a socket, written exactly the way
an input list's `patch` column writes one and the way CV005 prints
one -- `"AES50-A 12"`, `"LCL 3"`, `"AES 1"` -- because it is the same
vocabulary, parsed by the same `input_list.parse_socket_spec`. The AES50
network is spelled out on purpose: `"AES 1"` (AES/EBU) and `"AES50-A 1"`
are different sockets. A socket number past that group's own count
(`console_facts.INPUT_SOCKETS`) is a load-time error rather than a rule
that can never fire.

The membership/patch fields accept **`==` and `!=` only** -- an ordering
operator against a group name is refused at load time, not silently
turned into a string comparison.

**Sends and phantom.** Four fields say something true of one show that
the fixed rules cannot know: "the click stays on in every in-ear mix", "the
drummer's in-ear send for Kick stays above -10", "48V stays on for the
overheads".

    "field": "send_on",   "bus": "BUS 5-8",  "operator": "==", "value": true
    "field": "send_db",   "bus": "BUS Drums IEM", "operator": ">", "value": -10
    "field": "send_mode", "bus": "BUS 1-4",  "operator": "==", "value": "pre"
    "field": "phantom",                      "operator": "==", "value": true

- **`send_on`** (boolean), **`send_db`** (a dB level, every operator) and
  **`send_mode`** (`"pre"`, `"post"` or `"group"`, `==`/`!=`) are about the
  strip's send to the bus named by the **`bus`** key, which these three
  need and no other field takes. `bus` is written the way `channel` is: a
  bus's name, `BUS 5`, a range `BUS 5-8`, `ALL BUS`, or a kind and a name
  (`BUS Drums`); and, as a position, `MTX 3` (a Matrix) or `MAIN 1` (a
  route to a Main, which has a switch and no level or mode, so only
  `send_on` takes it). A bus's name is matched against the names last read,
  case-insensitively, and a name matching none or two skips that cycle. A
  Main's and a Matrix's names are not read, so those are written by position.
  Only a channel or an aux has sends of this kind.
- **`phantom`** (boolean) is the 48V on the socket the strip is patched to
  and, for a stereo source, the socket after it: each must satisfy the
  condition. A strip patched to a group with no head amp (a card, USB), an
  unpatched strip, and one on its alternate input have nothing to compare
  and are skipped.

Every address these read is read already -- a strip's sends, its Main
routes, the patch and each socket's `vph` -- so they cost no request. They
reuse the audit's own resolvers (`audit.strip_source_sockets` for the
sockets a strip hears), and a finding cites the strip's position and name
as every other one does, once per violating strip, listing the buses or
sockets that break it.

**No new console reads.** `audit.read_console_state`'s `STRIP_FIELDS`
already walks `tags`, `in/conn/grp` and `in/conn/in` for every strip, so
every field above is answerable from the state `atoo watch` polls
today -- this vocabulary costs no extra OSC traffic per cycle. The positions add none either: `console_read_plan` already reads
`mute` and `fdr` on every bus, Main, Matrix and DCA, and `name` on every
bus and DCA. It does not read a Main's or a Matrix's name, which is why a
finding about one cites its position alone. A scoped name (`BUS Drums`,
below) adds none per cycle either: it is resolved once, against the names
the first reading already carries, and a Main's or a Matrix's names --
not polled -- are read once at Start for it and never again
(`start_name_addresses`).

**The polled names are themselves refreshed, not read every cycle**
(`watch.refreshing_names`): a live watch reads them on its
first reading and every `watch.DEFAULT_NAME_REFRESH` readings, and the
readings between carry the last ones read. So a bare name, and a DCA or
mute group named in a `dca`/`mute_group` condition, is matched against
names at most that many readings old; W001 says so at INFO.

**File format** (JSON; see this module's tests for worked examples):

    {
      "watch_conditions": [
        {
          "id": "crowd-mic-never-muted",
          "description": "Crowd Mic must never be muted",
          "channel": "Crowd Mic",
          "field": "muted",
          "operator": "==",
          "value": false,
          "severity": "error"
        }
      ]
    }

**`channel` names the target: a strip name, or a
position, a range, a whole kind, or a kind and a name.** See
`parse_target`.

- A bare **name** is resolved against live `ConsoleState` case-insensitively
  across every strip base `atoo.audit.strip_bases` returns (`/ch/{n}`
  and `/aux/{n}` -- channels and auxes only; a bus, DCA, Main or Matrix
  is reached by position) -- see `_resolve_channel_base` (the
  `diff_against_plan` resolves identity from the PLAN's own `bank`/
  `channel` keys directly, which doesn't apply here: this module has no
  plan, only a channel name and live state).
- A **position**: `CH 10` (also `CHN`/`CHAN`), `AUX 3`, `BUS 3`, `MAIN 1`,
  `MTX 3` (also `MATRIX`), `DCA 14`. Case-insensitive, the space
  optional. A **range**: `DCA 10-16`. A **whole kind**: `ALL AUX`. Each is
  normalised to one display spelling (`CH 10`, `DCA 10-16`, `ALL AUX`):
  `canonical_target`, which the merge keys on and the editor writes back.
- A **scoped name**: a kind word, a space and a name
  -- `BUS Drums`, `CH Kick`, `AUX Tracks`, `DCA Vocals`, `MAIN PA`, `MTX
  Delay` -- is "the one strip of that kind named that". The kind word is
  normalised (`bus drums` -> `BUS drums`); the name keeps its spelling and
  matches case-insensitively. **It is resolved ONCE**, against the
  session's first reading, to a position, and every cycle after that
  watches the position (`_resolve_scoped`): the resolution is announced
  at INFO (`BUS Drums resolved to BUS 1 at Start; ...`); a name that
  matches no strip of its kind, or more than one, is a WARNING and is not
  watched until Watch starts again. A Main's and a Matrix's names are not
  polled, so they are read once at Start for this
  (`start_name_addresses`, `read_names_at_start`).
- A kind word followed by a **digit** stays a position attempt: `BUS 2
  Track` and `Aux 2 Keys` are refused, and the message says to write the
  position (`BUS 2`).
- **Precedence:** text that parses as one of those forms IS that form, even
  when a channel is named "CH 10" or "BUS Drums"; the check says so at
  INFO (`_name_overlaps`) -- each cycle for a position, once at Start for
  a scoped name, whose INFO says to write `CH BUS Drums` to watch that
  channel. Anything else is a bare name, as before.
- **`Main` alone is `MAIN 1`**, the main L/R, at INFO
  (`main_default_note`): the one bare kind word with a conventional
  reading. `BUS`, `AUX`, `CH`, `DCA` and `MTX` alone stay refused.
- **One finding per violating strip.** A range or whole-kind condition
  checks each strip it covers and reports each that breaks it, citing
  the strip's position and its name when it has one (`CH 3 "Kick"
  (/ch/3)`). A strip whose field was never read is skipped, as a name's
  is -- so `ALL AUX` on a state with no aux in it reports nothing.
- **Refused at load, because no console can satisfy them:** a malformed
  spelling (`CH`, `BUS -`, `DCA 3-`, `BUS 2 Track`); a position outside
  `console_facts.CAPACITY` (`CH 41`, `MAIN 5`); a backwards range (`DCA
  16-10`); and a field that does not exist for the kind -- `patch` on
  anything but a channel or aux (only they have an input patch),
  `dca`/`mute_group` on a DCA (it has no tags) or on a bus, Main or
  Matrix (they do carry tags on the desk, but `watch` does not poll them,
  so the condition could never fire). The same holds for a scoped name of
  that kind (`patch` on `DCA Vocals`). See `_FIELD_BANKS`. The Watch
  editor asks the server the same question per row (`row_problems`,
  `POST /api/watch-conditions/check`), so it refuses exactly this.

**Evaluation semantics.** Each condition states a DESIRED relationship
(`field <operator> value` should hold). A `Finding` fires when live state
does NOT satisfy it -- i.e. this evaluates `live_value <operator> value`
and produces a `Finding` when that's `False`. Same "assertion violated ->
finding" polarity every rule in `audit.py` already uses.

Silently skipped, no `Finding`, no crash, no finding about the skip
itself (same "a different, not-yet-built check" precedent
`audit._resolve_single_index_by_name`'s callers already established for
an unresolved DCA/mute-group name):

- `channel` is a bare name that resolves to zero live strips, or more
  than one (ambiguous/duplicate name). (A SCOPED name that does so is not
  silent: it is a WARNING at Start, above.)
- The condition's `field` was never read into `ConsoleState` at all (e.g.
  `state.mute(base)` is `None` because `/ch/3/mute` was never read) -- a
  missing read is not evidence of a violation.

Everything else -- an unknown `field`, a bad `operator`, `field`/
`operator` incompatibility (`muted`, a bool, paired with a numeric-only
operator), a missing required key, a bad `severity` -- is a LOAD-TIME
error (`WatchConditionsError`), not a silent no-op: this is a config file
a human or tool wrote, and a typo in it deserves a clear error.
"""

from __future__ import annotations

import json
import operator as _operator
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from atoo.audit import (
    AuditRule, ConsoleState, Finding, Severity, bus_indices, strip_bases,
    strip_group_membership, strip_source_sockets,
)
from atoo.console_facts import CAPACITY, INPUT_SOCKETS, PHANTOM_CAPABLE_GROUPS
from atoo.input_list import format_socket, parse_socket_spec
from atoo.diagnostics import Diagnostic
from atoo.watch import watch_note

# Every key a watch condition must carry. Same "unknown key is an ERROR,
# not a shrug" stance `critic_expectations.py` takes: a checking tool that
# silently ignores a misspelled field is worse than no checking tool.
_REQUIRED_KEYS = frozenset({"id", "description", "channel", "field", "operator", "value", "severity"})

# Optional keys. `bus` names where a send goes, and the send fields need it
# (`_bus_problem`). `source` records who wrote a condition
# -- "drafted" for one a build proposed, "hand" (the default, and what an
# absent key means) for one a person wrote. Nothing in the evaluator reads
# it; it exists so `atoo ui` and a human reading the file can tell a
# machine's suggestion from their own decision. Absent rather than filled
# in on load, so a file a person wrote by hand stays byte-for-byte theirs.
SOURCE_HAND = "hand"
SOURCE_DRAFTED = "drafted"
_SOURCES = frozenset({SOURCE_HAND, SOURCE_DRAFTED})
_OPTIONAL_KEYS = frozenset({"source", "bus"})

# Top-level, beside "watch_conditions": every id any build has ever
# drafted into this file. It is what makes a DELETION stick -- see
# merge_drafted_conditions, which cannot otherwise tell a rule you removed
# on purpose from one that was never proposed.
DRAFTED_KEY = "drafted"

# The scalar fields (a live reading compared to a stated value) and the
# relational ones (membership in a named group, or which
# physical socket a strip is patched to). The split matters twice over:
# relational fields take a STRING value and accept `==`/`!=` only.
_SCALAR_FIELDS = frozenset({"muted", "fader_db"})
_GROUP_FIELDS = frozenset({"dca", "mute_group"})
_RELATIONAL_FIELDS = _GROUP_FIELDS | {"patch"}
# A send is judged per target and 48V per socket, so neither reduces to one
# reading per strip (`_assess_send`, `_assess_phantom`). The send fields also
# need the `bus` key.
_SEND_FIELDS = frozenset({"send_on", "send_db", "send_mode"})
_PHANTOM_FIELD = "phantom"
_ALLOWED_FIELDS = _SCALAR_FIELDS | _RELATIONAL_FIELDS | _SEND_FIELDS | {_PHANTOM_FIELD}

# The fields whose value is a boolean, and so take `==` and `!=` only.
_BOOLEAN_FIELDS = frozenset({"muted", "send_on", _PHANTOM_FIELD})
# `send_mode`'s values, as the plan writes a send's mode
# (`apply._SEND_MODE_TO_WING`), and the words the desk reads back.
_SEND_MODES = {"pre": "PRE", "post": "POST", "group": "GRP"}
_SEND_MODE_FACT = {"PRE": "pre-fader", "POST": "post-fader", "GRP": "in group mode"}

_OPERATORS: dict[str, Callable[[object, object], bool]] = {
    "==": _operator.eq,
    "!=": _operator.ne,
    ">": _operator.gt,
    "<": _operator.lt,
    ">=": _operator.ge,
    "<=": _operator.le,
}

# `muted` is a bool -- ordering operators on a bool are almost certainly a
# mistake (what would "muted > true" mean?), so they're refused at load
# time rather than left to produce a technically-defined-but-nonsensical
# answer at runtime.
_BOOL_COMPATIBLE_OPERATORS = frozenset({"==", "!="})

# The relational fields answer a yes/no question, so the same two
# operators carry them -- and for the same reason, `"dca" > "Drums"` is
# refused at load time rather than quietly doing a string comparison
# nobody asked for. `!=` means is not a member of.
_EQUALITY_ONLY_FIELDS = _RELATIONAL_FIELDS | {"send_mode"}

# --------------------------------------------------------------------------
# Targets: what a condition's `channel` names.
# --------------------------------------------------------------------------

# Every spelling of a strip kind a position target may use, upper-cased,
# -> the console bank it means. One canonical word per bank (below) is
# what the target is normalised to and what a finding prints.
_KIND_WORDS: dict[str, str] = {
    "CH": "ch", "CHN": "ch", "CHAN": "ch",
    "AUX": "aux",
    "BUS": "bus",
    "MAIN": "main",
    "MTX": "mtx", "MATRIX": "mtx",
    "DCA": "dca",
}
CANONICAL_KIND_WORD: dict[str, str] = {
    "ch": "CH", "aux": "AUX", "bus": "BUS", "main": "MAIN", "mtx": "MTX", "dca": "DCA",
}
# The banks a position target can name, in display order.
TARGET_BANKS = tuple(CANONICAL_KIND_WORD)

# After a kind word, a digit or a hyphen marks an attempted POSITION
# (`CH 10`, `DCA 3-`), and anything else a SCOPED NAME (`BUS Drums`, `CH
# Kick`; 2026-10-01). Until scoped names existed, `CH x` and `DCA
# Drums` were refused as malformed positions, and `Main Vox` was a bare
# name; now all three are scoped names.

_KIND_ALT = "|".join(sorted(_KIND_WORDS, key=len, reverse=True))
_POSITION_RE = re.compile(rf"^({_KIND_ALT})\s*(\d+)$", re.IGNORECASE)
_RANGE_RE = re.compile(rf"^({_KIND_ALT})\s*(\d+)\s*-\s*(\d+)$", re.IGNORECASE)
_ALL_RE = re.compile(rf"^ALL\s+({_KIND_ALT})$", re.IGNORECASE)
_KIND_PREFIX_RE = re.compile(rf"^({_KIND_ALT})(?=$|[\s\d-])\s*(.*)$", re.IGNORECASE)
_ALL_PREFIX_RE = re.compile(r"^ALL(?:\s+(\S+))?$", re.IGNORECASE)

_TARGET_HELP = ("write a position as CH 10, AUX 3, BUS 3, MAIN 1, MTX 3 or DCA 14 "
                "(CHN, CHAN and MATRIX are read too), a range as DCA 10-16, every strip "
                "of a kind as ALL AUX, one strip of a kind by its name as BUS Drums -- "
                "or a channel's or aux's name")


class TargetError(ValueError):
    """A `channel` that is an attempted position, range or whole-kind
    target and cannot work: malformed, out of the console's range, or a
    backwards range. The message says which, and is what both the loader
    and the Watch editor show."""


@dataclass(frozen=True)
class Target:
    """What a condition's `channel` names.

    `bank` is None for a NAME, resolved against live state as it always
    was. Otherwise it is the console bank (`"ch"`, `"aux"`, `"bus"`,
    `"main"`, `"mtx"`, `"dca"`) and `first`..`last` the positions, both
    inclusive; `all_of_kind` marks `ALL AUX`, which covers the bank's
    whole `console_facts.CAPACITY`."""
    text: str
    bank: str | None = None
    first: int | None = None
    last: int | None = None
    all_of_kind: bool = False
    #: A SCOPED name's name part (`BUS Drums` -> `"Drums"`), as the user
    #: spelled it; None for every other form. With `bank` set and no
    #: positions, the target is "the one strip of that kind named this",
    #: resolved once per session (`_resolve_scoped`).
    name: str | None = None
    #: `Main` on its own, read as `MAIN 1` (`main_default_note`).
    defaulted: bool = False

    @property
    def is_name(self) -> bool:
        """A BARE name (`Kick`): resolved across channels and auxes."""
        return self.bank is None

    @property
    def is_scoped(self) -> bool:
        """A kind word and a name (`BUS Drums`)."""
        return self.bank is not None and self.name is not None

    @property
    def is_position(self) -> bool:
        """A position, a range or a whole kind (`CH 10`, `DCA 1-4`, `ALL AUX`)."""
        return self.bank is not None and self.name is None

    @property
    def canonical(self) -> str:
        """The one display spelling: `CH 10`, `DCA 10-16`, `ALL AUX`,
        `BUS Drums` (the kind word normalised, the name as written); a
        bare name is returned stripped and otherwise as written."""
        if self.bank is None:
            return self.text.strip()
        word = CANONICAL_KIND_WORD[self.bank]
        if self.name is not None:
            return f"{word} {self.name}"
        if self.all_of_kind:
            return f"ALL {word}"
        if self.first == self.last:
            return f"{word} {self.first}"
        return f"{word} {self.first}-{self.last}"

    @property
    def key(self) -> str:
        """What two targets are compared by: the canonical spelling, and a
        name lower-cased because names resolve case-insensitively --
        `bus drums` and `BUS Drums` are one target, `BUS Drums` and `DCA
        Drums` are two."""
        if self.bank is None:
            return self.canonical.lower()
        if self.name is not None:
            return f"{CANONICAL_KIND_WORD[self.bank]} {self.name.lower()}"
        return self.canonical

    def bases(self) -> list[str]:
        """Every strip base a position target covers, in order. A name,
        bare or scoped, has none until live state resolves it
        (`_resolve_channel_base`, `_resolve_scoped`)."""
        if self.bank is None or self.name is not None:
            return []
        return [f"/{self.bank}/{n}" for n in range(self.first, self.last + 1)]


def parse_target(text: str) -> Target:
    """Read a condition's `channel`. Raises `TargetError`
    for an attempted position that cannot work. A kind word followed by
    a space and anything not beginning with a digit or a hyphen is a
    SCOPED name (`BUS Drums`, `CH Kick`, `MAIN PA`); anything else that
    does not look like a position is a bare name.

    **Precedence.** Text that parses as a position, range, whole-kind or
    scoped form IS that form, even when some channel happens to be named
    "CH 10" or "BUS Drums"; the check says so at INFO when it sees the
    overlap live (`_name_overlaps`).

    **Refused, because no console could satisfy them:** a bare kind word
    (`CH`, `ALL`, `BUS`); a kind word followed by a digit or a hyphen that
    is not a clean number or range (`DCA 3-`, `CH 3x`, `BUS -`, `BUS 2
    Track` -- the last says to write `BUS 2`); a position of 0 or past the
    bank's `console_facts.CAPACITY` (`CH 41`, every WING model having 40);
    a backwards range (`DCA 16-10`); `ALL` with a word that is nearly a
    kind (`ALL AUXES`)."""
    stripped = text.strip()

    m = _ALL_RE.match(stripped)
    if m:
        bank = _KIND_WORDS[m.group(1).upper()]
        return Target(text, bank, 1, CAPACITY[bank], all_of_kind=True)

    m = _RANGE_RE.match(stripped)
    if m:
        bank = _KIND_WORDS[m.group(1).upper()]
        first, last = int(m.group(2)), int(m.group(3))
        word = CANONICAL_KIND_WORD[bank]
        _check_position(bank, first, stripped)
        _check_position(bank, last, stripped)
        if last < first:
            raise TargetError(
                f"{stripped!r} is a backwards range -- write the lower position first, "
                f"e.g. {word} {last}-{first}")
        return Target(text, bank, first, last)

    m = _POSITION_RE.match(stripped)
    if m:
        bank = _KIND_WORDS[m.group(1).upper()]
        n = int(m.group(2))
        _check_position(bank, n, stripped)
        return Target(text, bank, n, n)

    m = _ALL_PREFIX_RE.match(stripped)
    if m:
        word = (m.group(1) or "").upper()
        if not word:
            raise TargetError(f"{stripped!r} names no kind of strip -- {_TARGET_HELP}")
        if any(word.startswith(k) for k in _KIND_WORDS):
            raise TargetError(f"{stripped!r} is not a kind this console has -- {_TARGET_HELP}")
        return Target(text)  # "All Vox": a name

    m = _KIND_PREFIX_RE.match(stripped)
    if m:
        bank = _KIND_WORDS[m.group(1).upper()]
        word, rest = CANONICAL_KIND_WORD[bank], m.group(2)
        if not rest:
            if bank == "main":
                # An error of judgement is not an error of patching: `Main`
                # alone has a conventional reading -- the main L/R, MAIN
                # 1 -- and refusing it refuses the whole watch.json. Read
                # it so, and say so at INFO (`main_default_note`). No
                # other kind has a conventional default, so `BUS`, `AUX`,
                # `CH`, `DCA` and `MTX` alone stay refused.
                return Target(text, "main", 1, 1, defaulted=True)
            raise TargetError(f"{stripped!r} has no position or name -- {_TARGET_HELP}")
        if rest[0].isdigit() or rest[0] == "-":
            # Decision 3: a kind word and a digit is
            # a position attempt, so `BUS 2 Track` is refused rather than
            # read as the bus named "2 Track". Say what it most likely meant.
            lead = re.match(r"(\d+)\s+\S", rest)
            if lead and 1 <= int(lead.group(1)) <= CAPACITY[bank]:
                raise TargetError(
                    f"{stripped!r} begins like a position but is not a well-formed one "
                    f"(a name after a kind word cannot begin with a number) -- to watch "
                    f"that strip, write its position, {word} {int(lead.group(1))}")
            raise TargetError(f"{stripped!r} begins like a position but is not a "
                              f"well-formed one (a name after a kind word cannot begin "
                              f"with a number or a hyphen) -- {_TARGET_HELP}")
        # A scoped name: the kind word normalised, the name as written.
        return Target(text, bank, name=rest)
    return Target(text)


def _check_position(bank: str, n: int, text: str) -> None:
    top = CAPACITY[bank]
    if not 1 <= n <= top:
        word = CANONICAL_KIND_WORD[bank]
        raise TargetError(f"{text!r}: {word} {n} does not exist -- a WING has "
                          f"{word} 1-{top}")


def canonical_target(text: str) -> str:
    """`ch10` -> `CH 10`; a name, or text that does not parse at all, is
    returned exactly as written, so normalising a file never edits a
    name. Never raises -- for writing and display, not validation."""
    try:
        target = parse_target(text)
    except TargetError:
        return text
    return text if target.is_name else target.canonical


def main_default_note(target: Target) -> str | None:
    """The INFO for a bare `Main` read as `MAIN 1`, or None."""
    if not target.defaulted:
        return None
    return (f"{target.text.strip()!r} read as MAIN 1 (the main L/R) -- write MAIN 1 to "
            f"make it explicit")


def target_key(text: str) -> str:
    """A target's spelling-independent key: `ch 10` and `CH10` are one
    target, `Kick` and `kick` are one name. (A merge goes further and
    compares the strips a target covers: `covered_strips`.)"""
    try:
        return parse_target(text).key
    except TargetError:
        return text.strip().lower()


# field -> the banks that field can be asked of, and why not of the rest.
# Patch is an INPUT patch: only a channel and an aux have one. Membership
# lives in a strip's `/tags`, and `audit.STRIP_FIELDS` reads tags for
# channels and auxes only -- a bus, Main and Matrix do carry tags on the
# desk, but `watch` does not poll them, so a membership condition on one
# could never fire; and a DCA has no tags at all.
_FIELD_BANKS: dict[str, frozenset[str]] = {
    "muted": frozenset(TARGET_BANKS),
    "fader_db": frozenset(TARGET_BANKS),
    "dca": frozenset({"ch", "aux"}),
    "mute_group": frozenset({"ch", "aux"}),
    "patch": frozenset({"ch", "aux"}),
    # Only a channel or an aux has sends of the kind these fields read, and
    # an input patch to put 48V on.
    "send_on": frozenset({"ch", "aux"}),
    "send_db": frozenset({"ch", "aux"}),
    "send_mode": frozenset({"ch", "aux"}),
    "phantom": frozenset({"ch", "aux"}),
}


def _field_bank_problem(field: str, target: Target) -> str | None:
    """Why `field` cannot be asked of `target`'s kind, or None."""
    if target.bank is None or target.bank in _FIELD_BANKS[field]:
        return None
    word = CANONICAL_KIND_WORD[target.bank]
    if field == "patch" or field == _PHANTOM_FIELD:
        why = f"a {word} has no input patch"
    elif field in _SEND_FIELDS:
        why = f"a {word} has no sends of this kind"
    elif target.bank == "dca":
        why = "a DCA cannot itself be a member of a DCA or a mute group"
    else:
        why = (f"watch does not read a {word}'s tags, where membership lives, so "
               f"this could never be checked")
    return (f"field {field!r} does not apply to {target.canonical}: {why} -- "
            f"{word} conditions take 'muted' or 'fader_db'")


# --------------------------------------------------------------------------
# The `bus` key: where a send goes.
# --------------------------------------------------------------------------

# The banks a send can go to: a bus, a Matrix, or a route to a Main.
_SEND_BANKS = ("bus", "mtx", "main")
_BUS_HELP = ("write a bus's name, a position such as BUS 5, a range BUS 5-8, ALL BUS, a kind "
             "and a name such as BUS Drums, or MTX 3 or MAIN 1 for a Matrix or a Main")


def _bus_problem(field: str, bus: object) -> str | None:
    """Why the `bus` key is wrong for `field`, or None. The three send
    fields need it and name where the send goes; no other field takes it.
    The target is read with `parse_target`, as `channel` is."""
    if field not in _SEND_FIELDS:
        return None if bus is None else (
            f"key 'bus' only applies to {', '.join(sorted(_SEND_FIELDS))}, not to {field!r}")
    if not isinstance(bus, str) or not bus.strip():
        return (f"field {field!r} needs a 'bus' key naming where the send goes -- {_BUS_HELP}")
    try:
        target = parse_target(bus)
    except TargetError as exc:
        return f"'bus' {exc}"
    if target.is_name:
        return None
    if target.bank not in _SEND_BANKS:
        word = CANONICAL_KIND_WORD[target.bank]
        return (f"'bus' {bus.strip()!r} is a {word}, which a strip does not send to -- {_BUS_HELP}")
    word = CANONICAL_KIND_WORD[target.bank]
    if target.is_scoped and target.bank != "bus":
        return (f"'bus' {bus.strip()!r}: watch does not read a {word}'s name, so write its "
                f"position, e.g. {word} 1")
    if target.bank == "main" and field != "send_on":
        return (f"field {field!r} does not apply to {target.canonical}: a route to a Main has "
                f"a switch and no level or mode -- use 'send_on'")
    if target.bank == "mtx" and field == "send_mode":
        return (f"field 'send_mode' does not apply to {target.canonical}: only a send to a "
                f"bus is pre or post fader")
    return None


def parse_patch_value(text: str) -> tuple[str, int] | None:
    """`"AES50-A 12"` -> `("A", 12)`; `"LCL 3"` -> `("LCL", 3)`. None if
    it isn't a socket this console could have.

    **The grammar is `input_list.parse_socket_spec`, not a new one.** A
    watch condition's `patch` value is the same thing an input list's
    `patch` column holds and the same thing CV005 prints, so it is
    written the same way -- "AES50-A 12", with the network spelled out.
    The alternative is a confusion this project has already measured:
    "AES 1" is AES/EBU socket 1 and "AES50-A 1" is a different socket
    entirely, and a 14B model substituted one for the other on 19
    channels in a row (see `console_facts.GROUP_ALIASES`).

    The one check `parse_socket_spec` doesn't do is range: a socket
    number past that group's own count (`INPUT_SOCKETS`) is refused here,
    because a condition naming a socket that cannot exist would be a rule
    that silently never fires -- the failure mode this module refuses to
    ship."""
    parsed = parse_socket_spec(text)
    if parsed is None:
        return None
    group, socket = parsed
    if group not in INPUT_SOCKETS or not 1 <= socket <= INPUT_SOCKETS[group]:
        return None
    return group, socket

# field -> the ConsoleState accessor that reads it for a given strip base.
# Scalar fields only; the relational ones don't reduce to one reading (see
# `_satisfied`).
_FIELD_READERS: dict[str, Callable[[ConsoleState, str], object | None]] = {
    "muted": lambda state, base: state.mute(base),
    "fader_db": lambda state, base: state.fader_db(base),
}

# field -> the address suffix(es) a resulting Finding cites. Membership
# lives in the strip's own `/tags` string, and a patch in the two
# `in/conn` addresses `ConsoleState.patch` reads together -- both cite
# what a reader would actually go and look at.
_FIELD_ADDRESSES: dict[str, tuple[str, ...]] = {
    "muted": ("mute",),
    "fader_db": ("fdr",),
    "dca": ("tags",),
    "mute_group": ("tags",),
    "patch": ("in/conn/grp", "in/conn/in"),
}

# field -> the address families evaluating a condition on that field
# READS, as regexes over a whole address (the read-scope work;
# `atoo.watch_scope` is where they are used, and where the rest of
# this vocabulary is defined).
#
# **Wider than `_FIELD_ADDRESSES` above, and for two reasons.** That table
# says which addresses a resulting `Finding` CITES, on the one strip the
# condition resolved to. This one says which addresses the evaluator has
# to have READ, and:
#
# 1. `_resolve_channel_base` matches the condition's `channel` against
#    EVERY strip's `/name` -- so every strip's name is read, whichever
#    one the condition turns out to be about. A read that skipped them
#    would resolve nothing and the condition would silently never fire.
# 2. A group name is resolved to an index through the GROUP's own `/name`
#    (`audit.strip_group_membership` -> `_resolve_single_index_by_name`),
#    which is an address on `/dca/{n}` or `/mgrp/{n}`, not on the strip.
#
# Nothing here depends on which strip the condition names, because that
# is a fact about live state and a read plan is built before any state
# has been read.
_FIELD_READ_PATTERNS: dict[str, tuple[str, ...]] = {
    "muted": (r"^/{bank}/\d+/mute$",),
    "fader_db": (r"^/{bank}/\d+/fdr$",),
    "dca": (r"^/{bank}/\d+/tags$", r"^/dca/\d+/name$"),
    "mute_group": (r"^/{bank}/\d+/tags$", r"^/mgrp/\d+/name$"),
    "patch": (r"^/{bank}/\d+/in/conn/(?:grp|in)$",),
    # 48V: the socket each strip is patched to, the alternate patch and the
    # switch that decide whether it is heard, and each jack's 48V and width
    # (a stereo source takes the next socket).
    "phantom": (r"^/{bank}/\d+/in/conn/(?:grp|in)$",
                r"^/{bank}/\d+/in/(?:conn/altgrp|set/altsrc)$",
                r"^/io/altsw$",
                r"^/io/in/(?!USR/)[A-Za-z0-9]+/\d+/(?:vph|mode)$"),
}

# A send's own leaf, per field, and where it sits for each kind of target:
# a bus, a Matrix, or a route to a Main (which has a switch only).
_SEND_LEAF = {"send_on": "on", "send_db": "lvl", "send_mode": "mode"}
_SEND_PATTERNS = {
    "bus": r"^/{bank}/\d+/send/\d+/{leaf}$",
    "mtx": r"^/{bank}/\d+/send/MX\d+/{leaf}$",
    "main": r"^/{bank}/\d+/main/\d+/on$",
}

# The strip banks a NAME resolves across (`_resolve_channel_base`).
_NAME_BANKS = r"(?:ch|aux)"

# Read by every condition whatever its field or target --
# `_resolve_channel_base` for a name, and for a position target the
# overlap INFO (`_name_overlaps`), which asks whether a channel or aux is
# NAMED like the position.
_CHANNEL_RESOLUTION_PATTERN = rf"^/{_NAME_BANKS}/\d+/name$"


def _bus_target(cond: dict) -> Target:
    """The parsed `bus` of a validated send condition."""
    return parse_target(cond["bus"])


def condition_address_patterns(cond: dict) -> tuple[str, ...]:
    """Every address family evaluating `cond` reads, as regexes over a
    whole address.

    `cond` is one validated condition (`parse_watch_conditions`), so its
    `field` is one of `_ALLOWED_FIELDS` and its `channel` parses, and this
    never has to guess. A position or scoped target reads its
    own bank's field and name -- `/dca/{n}/fdr` and `/dca/{n}/name` for
    `DCA 1-4` or `DCA Vocals` -- where a bare name reads the channel and
    aux banks. (A scoped `MAIN`/`MTX` name's `/name` is in no poll's plan
    at all: it is read once at Start, `start_name_addresses`.)
    `atoo.watch_scope` uses it to work out what a scoped `watch`
    read would have to fetch; see that module for why an address wrongly
    omitted is the failure this project cares most about avoiding."""
    target = parse_target(cond["channel"])
    bank = _NAME_BANKS if target.is_name else target.bank
    patterns = [_CHANNEL_RESOLUTION_PATTERN]
    if not target.is_name:
        patterns.append(rf"^/{bank}/\d+/name$")
    field = cond["field"]
    if field in _SEND_FIELDS:
        # The send itself, and the buses' names, which label a finding and
        # resolve a bus named by its name.
        bus_bank = _bus_target(cond).bank or "bus"
        patterns.append(_SEND_PATTERNS[bus_bank].replace("{leaf}", _SEND_LEAF[field]))
        patterns.append(r"^/bus/\d+/name$")
    else:
        patterns += _FIELD_READ_PATTERNS[field]
    return tuple(dict.fromkeys(p.replace("{bank}", bank) for p in patterns))


class WatchConditionsError(ValueError):
    """The watch-conditions file itself is wrong -- bad JSON, an unknown or
    missing key, a bad operator/field/severity value, field/operator
    incompatibility. Distinct from a condition simply not resolving
    against a particular live state (channel not found, field not read),
    which is not an error, just nothing to report this poll cycle."""


def _fail(source: str, where: str, message: str) -> None:
    raise WatchConditionsError(f"{source}: {where}: {message}")


def _value_problem(field: str, value: object) -> str | None:
    """Why `value` is not one `field` can take, or None. `field` is
    already known to be one of `_ALLOWED_FIELDS`."""
    if field in _BOOLEAN_FIELDS:
        if not isinstance(value, bool):
            return f"field {field!r} needs a boolean 'value', got {value!r}"
    elif field in ("fader_db", "send_db"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"field {field!r} needs a numeric 'value', got {value!r}"
    elif field == "send_mode":
        if value not in _SEND_MODES:
            return (f"field 'send_mode' needs a 'value' of {', '.join(repr(m) for m in _SEND_MODES)}, "
                    f"got {value!r}")
    elif field in _GROUP_FIELDS:
        if not isinstance(value, str) or not value.strip():
            return (f"field {field!r} needs a group NAME as a non-empty string 'value' "
                    f"(resolved against live state, not an index), got {value!r}")
    elif field == "patch":
        if not isinstance(value, str) or not value.strip():
            return (f"field 'patch' needs a socket as a non-empty string 'value' "
                    f"like \"AES50-A 12\" or \"LCL 3\", got {value!r}")
        if parse_patch_value(value) is None:
            return (f"field 'patch' value {value!r} is not a socket this console could have "
                    f"-- write it the way an input list's patch column does, e.g. "
                    f"\"AES50-A 12\", \"LCL 3\", \"AES 1\", \"SC 24\"; known groups: "
                    f"{', '.join(f'{format_socket(g, 1)}..{n}' for g, n in sorted(INPUT_SOCKETS.items()))}")
    return None


def row_problems(cond: object) -> dict:
    """The Watch editor's inline check: what is wrong with
    one table row, by the cell it belongs to -- `{"channel": msg,
    "field": msg, "value": msg}`, each key present only when that cell
    is wrong -- plus, when the channel parses, `"canonical"` (the
    target's display spelling), `"position"` (a position, range or ALL
    form) and `"scoped"` (a kind and a name, `BUS Drums`). The editor
    writes `canonical` back into the cell for either of the last two. A
    send field's `bus` cell is checked the same way: `"bus"` when it is
    wrong, `"bus_canonical"` when it is fine, which the editor writes back.

    The SAME rules `_validate_condition` refuses a file with, called from
    the same helpers, so the editor cannot accept what the loader will
    refuse (`POST /api/watch-conditions/check`). It does not repeat what
    the table's own controls already prevent (an operator a field does
    not take) or what Save checks across rows (a duplicate id)."""
    out: dict = {}
    if not isinstance(cond, dict):
        return {"row": "not a condition object"}
    channel = cond.get("channel")
    target: Target | None = None
    if not isinstance(channel, str) or not channel.strip():
        out["channel"] = ("needs a strip: a name, a position such as CH 10, DCA 1-4, "
                          "ALL AUX, or a kind and a name such as BUS Drums")
    else:
        try:
            target = parse_target(channel)
            out["canonical"] = target.canonical
            out["position"] = target.is_position
            out["scoped"] = target.is_scoped
            note = main_default_note(target)
            if note:
                # Not a refusal: the cell is rewritten to `canonical` and
                # the note shown under it, not in red.
                out["note"] = note
        except TargetError as exc:
            out["channel"] = str(exc)
    field = cond.get("field")
    if field not in _ALLOWED_FIELDS:
        out["field"] = f"unknown field {field!r} -- expected one of {sorted(_ALLOWED_FIELDS)}"
        return out
    value_problem = _value_problem(field, cond.get("value"))
    if value_problem:
        out["value"] = value_problem
    if target is not None:
        bank_problem = _field_bank_problem(field, target)
        if bank_problem:
            out["field"] = bank_problem
    bus = cond.get("bus")
    bus_problem = _bus_problem(field, bus)
    if bus_problem:
        out["bus"] = bus_problem
    elif field in _SEND_FIELDS:
        out["bus_canonical"] = canonical_target(bus)
    return out


def _validate_condition(cond: object, source: str, index: int) -> dict:
    where = f"watch_conditions[{index}]"
    if not isinstance(cond, dict):
        _fail(source, where, f"must be an object, got {type(cond).__name__}")

    missing = _REQUIRED_KEYS - set(cond)
    if missing:
        _fail(source, where, f"missing required key(s) {', '.join(sorted(missing))}")
    unknown = set(cond) - _REQUIRED_KEYS - _OPTIONAL_KEYS
    if unknown:
        _fail(source, where, f"unknown key(s) {', '.join(sorted(unknown))} -- "
                              f"known keys: {', '.join(sorted(_REQUIRED_KEYS | _OPTIONAL_KEYS))}")
    if "source" in cond and cond["source"] not in _SOURCES:
        _fail(source, where,
              f"unknown source {cond['source']!r} -- expected one of {sorted(_SOURCES)}")

    cond_id = cond["id"]
    if not isinstance(cond_id, str) or not cond_id.strip():
        _fail(source, where, f"'id' must be a non-empty string, got {cond_id!r}")
    where = f"watch_conditions[{index}] ({cond_id!r})"

    if not isinstance(cond["description"], str) or not cond["description"].strip():
        _fail(source, where, f"'description' must be a non-empty string, got {cond['description']!r}")

    channel = cond["channel"]
    if not isinstance(channel, str) or not channel.strip():
        _fail(source, where, f"'channel' must be a non-empty string, got {channel!r}")
    try:
        target = parse_target(channel)
    except TargetError as exc:
        _fail(source, where, f"'channel' {exc}")

    field = cond["field"]
    if field not in _ALLOWED_FIELDS:
        _fail(source, where, f"unknown field {field!r} -- expected one of {sorted(_ALLOWED_FIELDS)}")

    operator_ = cond["operator"]
    if operator_ not in _OPERATORS:
        _fail(source, where, f"unknown operator {operator_!r} -- expected one of {sorted(_OPERATORS)}")

    if field in _BOOLEAN_FIELDS and operator_ not in _BOOL_COMPATIBLE_OPERATORS:
        _fail(source, where,
              f"field {field!r} is a boolean and only supports "
              f"{sorted(_BOOL_COMPATIBLE_OPERATORS)}, not {operator_!r}")
    if field in _EQUALITY_ONLY_FIELDS and operator_ not in _BOOL_COMPATIBLE_OPERATORS:
        _fail(source, where,
              f"field {field!r} asks a yes/no question and only supports "
              f"{sorted(_BOOL_COMPATIBLE_OPERATORS)} ('==' asserts it holds, '!=' asserts "
              f"it does not), not {operator_!r}")

    value_problem = _value_problem(field, cond["value"])
    if value_problem:
        _fail(source, where, value_problem)

    bank_problem = _field_bank_problem(field, target)
    if bank_problem:
        _fail(source, where, bank_problem)

    bus_problem = _bus_problem(field, cond.get("bus"))
    if bus_problem:
        _fail(source, where, bus_problem)

    severity = cond["severity"]
    try:
        Severity(severity)
    except ValueError:
        # `critical` was a real severity until 2026-09-23 and was dropped
        # because nothing ever emitted one. A watch.json written before
        # that is the one file on disk that can still carry it, so say
        # what to change rather than only that the value is unknown --
        # and refuse rather than silently reading it as `error`, because
        # a severity nobody re-read is a severity nobody chose.
        hint = (" -- `critical` is no longer a severity; use \"error\", which blocks "
                "exactly the same way") if severity == "critical" else ""
        _fail(source, where,
              f"unknown severity {severity!r} -- expected one of "
              f"{[s.value for s in Severity]}{hint}")

    return cond


def parse_watch_conditions(text: str, source: str = "<string>") -> list[dict]:
    """Parse and validate a watch-conditions JSON document's text. Raises
    `WatchConditionsError` on the first problem found -- bad JSON, no
    top-level `watch_conditions` list, or any condition entry that fails
    `_validate_condition`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WatchConditionsError(f"{source}: not valid JSON -- {exc}") from exc

    if not isinstance(data, dict) or "watch_conditions" not in data:
        raise WatchConditionsError(
            f"{source}: expected a top-level object with a \"watch_conditions\" list"
        )
    conditions = data["watch_conditions"]
    if not isinstance(conditions, list):
        raise WatchConditionsError(f"{source}: \"watch_conditions\" must be a list")

    validated: list[dict] = []
    seen_ids: set[str] = set()
    for i, cond in enumerate(conditions):
        validated_cond = _validate_condition(cond, source, i)
        cond_id = validated_cond["id"]
        if cond_id in seen_ids:
            raise WatchConditionsError(f"{source}: duplicate condition id {cond_id!r}")
        seen_ids.add(cond_id)
        validated.append(validated_cond)
    return validated


def salvage_drafted_conditions(document: object, source: str = "<watch-conditions draft>"
                               ) -> tuple[list[dict], list[str]]:
    """A model's drafted watchlist, kept as far as it can be.

    A hand-written file is refused whole on its first problem
    (`parse_watch_conditions`): its author is there to fix it. A draft
    has no author to ask, and one extra key on one condition cost the
    Demo its whole watchlist. So, per the INFO principle:

    * a key no condition has (the model's own "index") is **dropped**,
      and said -- the condition is complete without it;
    * a condition still unusable after that is **refused on its own**,
      and said, and the others are kept;
    * a later condition repeating an earlier one's id is refused the same
      way.

    Returns `(conditions, notes)`: the validated conditions, and one line
    per key dropped or condition refused. Raises `WatchConditionsError`
    only when `document` is no watchlist at all (no `watch_conditions`
    list) -- then there is nothing to keep."""
    if not isinstance(document, dict) or not isinstance(document.get("watch_conditions"), list):
        raise WatchConditionsError(
            f"{source}: expected a top-level object with a \"watch_conditions\" list")
    known = _REQUIRED_KEYS | _OPTIONAL_KEYS
    kept: list[dict] = []
    notes: list[str] = []
    seen_ids: set[str] = set()
    for i, cond in enumerate(document["watch_conditions"]):
        where = f"watch_conditions[{i}]"
        if isinstance(cond, dict):
            label = f"{where} ({cond.get('id')!r})" if cond.get("id") else where
            unknown = sorted(set(cond) - known)
            if unknown:
                cond = {k: v for k, v in cond.items() if k in known}
                notes.append(f"{label}: dropped unknown key(s) {', '.join(unknown)} -- not a "
                             f"field a watch condition has (known keys: {', '.join(sorted(known))})")
        try:
            validated = _validate_condition(cond, source, i)
        except WatchConditionsError as exc:
            notes.append(f"refused {str(exc).removeprefix(source + ': ')} -- the condition "
                         "is left out, the others are kept")
            continue
        if validated["id"] in seen_ids:
            notes.append(f"refused {where}: duplicate condition id {validated['id']!r} -- the "
                         "first is kept")
            continue
        seen_ids.add(validated["id"])
        kept.append(validated)
    return kept, notes


def load_watch_conditions(path: str | Path) -> list[dict]:
    """Read and validate a watch-conditions JSON file. Raises `OSError` if
    the file can't be read, `WatchConditionsError` if its contents are
    invalid -- the same split `critic_expectations.load_critic_expectations`
    makes between "couldn't read it" (left to the caller/OSError) and "read
    it, but it's wrong" (this module's own exception)."""
    p = Path(path)
    return parse_watch_conditions(p.read_text(encoding="utf-8"), source=str(p))


# --------------------------------------------------------------------------
# Merging a drafted watchlist into one that already exists.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeReport:
    """What `merge_drafted_conditions` did, so the build can say it out loud.

    Every list holds condition ids. `overlaps` is the one thing here that
    is a caution rather than a record of an action.
    """
    added: tuple[str, ...] = ()
    #: Drafted ids an existing condition already uses. Yours was kept
    #: exactly as written -- a draft never edits a rule you have.
    kept: tuple[str, ...] = ()
    #: Drafted ids a previous build already proposed and you deleted. Not
    #: re-added, which is the whole reason DRAFTED_KEY is written down.
    dismissed: tuple[str, ...] = ()
    #: (new id, existing id) pairs asking about the same channel and field
    #: under different ids. Both survive -- ids are the identity here --
    #: but they can contradict each other, so they are worth naming.
    overlaps: tuple[tuple[str, str], ...] = ()
    #: (drafted id, existing id) pairs where the draft says what a condition
    #: already in the file says -- the same strips, field, operator and
    #: value, whatever the ids, the spelling of the target or the wording of
    #: the description. The draft's is not added.
    duplicates: tuple[tuple[str, str], ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.added)


#: What two conditions are compared by when a draft is merged: the strips
#: they cover (`covered_strips`), the field (with the bus, for a send), the
#: operator and the value. Not
#: the id, the description or the severity -- a model names the same rule
#: differently each time it is asked, and a severity is the person's call.
MEANING = "the same strips, field, operator and value"

_PLAN_BANK_KINDS = {"main": "main", "matrix": "mtx"}


def covered_strips(channel: str, plan: dict | None) -> frozenset:
    """The strips a condition's `channel` names, as `(bank, number)` pairs,
    so that `Kick`, `CH 1` and `kick` -- or `MAIN PA` and `MAIN 1`, or `DCA
    Vocals` and `DCA 1-5` -- can be compared as the same strip or a part of
    one. A position, range or `ALL` form is its own strips; a name is looked
    up in `plan` (case-insensitively, within its kind). A name the plan does
    not settle -- absent from it, or on two strips of the kind -- stays a
    `("name", text)` pair, which equals only the same name."""
    try:
        target = parse_target(channel)
    except TargetError:
        return frozenset({("name", channel.strip().lower())})
    if target.is_position:
        return frozenset((target.bank, n) for n in range(target.first, target.last + 1))
    name = (target.name if target.is_scoped else target.text).strip().lower()
    found: set[tuple[str, int]] = set()
    plan = plan or {}
    banks = {target.bank} if target.is_scoped else {"ch", "aux"}
    for entry in plan.get("channels") or []:
        if isinstance(entry, dict) and entry.get("bank", "ch") in banks \
                and str(entry.get("name") or "").strip().lower() == name \
                and isinstance(entry.get("channel"), int):
            found.add((entry.get("bank", "ch"), entry["channel"]))
    if target.is_scoped and target.bank in ("bus", "dca"):
        section = plan.get("busses" if target.bank == "bus" else "dcas") or {}
        for obj_name, obj in section.items():
            if str(obj_name).strip().lower() == name and isinstance(obj, dict) \
                    and isinstance(obj.get("index"), int):
                found.add((target.bank, obj["index"]))
    if target.is_scoped and target.bank in ("main", "mtx"):
        for obj_name, obj in (plan.get("outputs") or {}).items():
            if str(obj_name).strip().lower() == name and isinstance(obj, dict) \
                    and _PLAN_BANK_KINDS.get(obj.get("kind")) == target.bank \
                    and isinstance(obj.get("index"), int):
                found.add((target.bank, obj["index"]))
    if len(found) == 1:
        return frozenset(found)
    return frozenset({("name", f"{target.bank or ''} {name}".strip())})


def _bus_key(cond: dict) -> str:
    """Where a send condition's send goes, spelled independently of case and
    form (`bus 5` and `BUS5` are one); empty for every other field."""
    bus = cond.get("bus")
    return target_key(bus) if isinstance(bus, str) else ""


def _meaning_key(cond: dict) -> tuple:
    value = cond["value"]
    if isinstance(value, str):
        value = value.strip().lower()
    elif not isinstance(value, bool):
        value = float(value)
    return (cond["field"], _bus_key(cond), cond["operator"], value)


def merge_drafted_conditions(existing: dict | None, drafted: list[dict],
                             plan: dict | None = None) -> tuple[dict, MergeReport]:
    """Fold a freshly drafted watchlist into the one already on disk.

    The merge is chosen over the refuse /
    overwrite / write-alongside options originally offered. It is
    **purely additive**, keyed on `id`:

    * a drafted id that is new is added;
    * a drafted id that already exists leaves YOUR condition untouched --
      a rebuild never rewrites a rule you tuned;
    * a drafted condition that says what one already in the file says is
      not added, whatever its id (`MEANING`). Ids are what a model makes
      up afresh each time; the rule is what the person already has. With
      the `plan`, a name is looked up in it, so `MAIN PA` and `MAIN 1` are
      one strip, and a drafted `DCA Vocals` is covered by a `DCA 1-5` of
      the same field, operator and value. This holds among the drafted
      conditions themselves too;
    * a condition the draft no longer proposes is kept -- a rule you wrote
      about something the model didn't think to watch is exactly the one
      worth keeping.

    So nothing a person wrote can be lost here, which was the property the
    "write `watch.draft.json` alongside" option existed to protect, without
    leaving two files to reconcile by hand.

    The one case pure addition gets wrong is **deletion**: a drafted rule
    you removed on purpose is, in the file, indistinguishable from one that
    was never drafted, so the next build would cheerfully put it back. That
    is what `DRAFTED_KEY` is for -- every id ever drafted is recorded, so a
    drafted id that is absent from the conditions reads as "removed" rather
    than "missing", and stays gone.

    `existing` is the parsed document (not the list) or None when there is
    no file yet. Returns the document to write and a `MergeReport`; the
    input is never mutated.
    """
    existing = existing or {}
    conditions = [dict(c) for c in existing.get("watch_conditions") or []]
    ever_drafted = {str(i) for i in existing.get(DRAFTED_KEY) or []}

    by_id = {c["id"]: c for c in conditions}
    # meaning -> [(id, strips)] of the conditions in the file, for the
    # duplicate check below, and field -> the same, for the overlap caution;
    # drafted ones join both as they are added. Names are compared as the
    # strips they are in the plan, case-insensitively (names resolve that
    # way at evaluation time), and positions in their canonical spelling, so
    # `ch 10` and `CH10` are the same strip.
    by_meaning: dict[tuple, list[tuple[str, frozenset]]] = {}
    by_field: dict[tuple[str, str], list[tuple[str, frozenset]]] = {}
    for c in conditions:
        strips = covered_strips(str(c["channel"]), plan)
        by_meaning.setdefault(_meaning_key(c), []).append((c["id"], strips))
        by_field.setdefault((c["field"], _bus_key(c)), []).append((c["id"], strips))

    added: list[str] = []
    kept: list[str] = []
    dismissed: list[str] = []
    overlaps: list[tuple[str, str]] = []
    duplicates: list[tuple[str, str]] = []

    for cond in drafted:
        cond_id = cond["id"]
        if cond_id in by_id:
            kept.append(cond_id)
            continue
        if cond_id in ever_drafted:
            dismissed.append(cond_id)
            continue
        strips = covered_strips(str(cond["channel"]), plan)
        same = by_meaning.get(_meaning_key(cond), [])
        if strips and strips <= frozenset().union(*(s for _, s in same)):
            twin = next(i for i, s in same if s & strips)
            duplicates.append((cond_id, twin))
            continue
        rival = next((i for i, s in by_field.get((cond["field"], _bus_key(cond)), [])
                      if s & strips), None)
        if rival is not None:
            overlaps.append((cond_id, rival))
        entry = dict(cond)
        entry["source"] = SOURCE_DRAFTED
        # A drafted position is written in its canonical spelling; a name
        # stays exactly as the model spelled it (it matches the plan's).
        entry["channel"] = canonical_target(str(cond["channel"]))
        if isinstance(entry.get("bus"), str):
            entry["bus"] = canonical_target(entry["bus"])
        conditions.append(entry)
        by_id[cond_id] = entry
        by_meaning.setdefault(_meaning_key(cond), []).append((cond_id, strips))
        by_field.setdefault((cond["field"], _bus_key(cond)), []).append((cond_id, strips))
        added.append(cond_id)

    document = dict(existing)
    document["watch_conditions"] = conditions
    # Union, never a replacement: an id drafted by an older build and since
    # deleted has to stay recorded or the deletion stops sticking.
    # A duplicate is not recorded: it was never put in the file, and if the
    # rule it duplicated is deleted later, the draft may propose it again.
    skipped = {new_id for new_id, _ in duplicates}
    document[DRAFTED_KEY] = sorted(
        ever_drafted | {c["id"] for c in drafted if c["id"] not in skipped})
    return document, MergeReport(tuple(added), tuple(kept), tuple(dismissed), tuple(overlaps),
                                 tuple(duplicates))


# --------------------------------------------------------------------------
# Evaluation: turn validated conditions into AuditRules that plug into the
# existing atoo.audit/atoo.watch machinery unchanged.
# --------------------------------------------------------------------------


def _resolve_channel_base(state: ConsoleState, name: str) -> str | None:
    """The one live strip base (`/ch/{n}` or `/aux/{n}`, from
    `strip_bases`) whose `/name` matches `name` case-insensitively -- None
    if zero or more than one match. Mirrors `audit._resolve_single_index_
    by_name`'s "ambiguous or unknown -- skip silently" precedent, adapted
    from index resolution (a DCA/mute-group name against a fixed
    `base_fmt`) to strip-base resolution (bases discovered dynamically,
    spanning two banks)."""
    target = name.strip().lower()
    matches = [
        base for base in strip_bases(state)
        if (live_name := state.name(base)) is not None
        and live_name.strip().lower() == target
    ]
    return matches[0] if len(matches) == 1 else None


def _live_patch(state: ConsoleState, base: str) -> tuple[str, int] | None | str:
    """The strip's live patch, distinguishing NEVER READ from genuinely
    UNPATCHED -- `ConsoleState.patch` collapses both to None, and they are
    not the same thing to a watch condition. Never read is nothing to say;
    patched to nothing really does violate `patch == "AES50-A 12"`.

    Returns the sentinel `"unread"` for the first case, `None` for
    unpatched, and `(group, socket)` otherwise."""
    if state.text(f"{base}/in/conn/grp") is None:
        return "unread"
    return state.patch(base)


def _satisfied(
    state: ConsoleState, base: str, field: str, op_symbol: str, expected: object
) -> bool | None:
    """Does the condition's stated relationship hold against live state?
    `None` -- neither True nor False -- when this state cannot answer
    (field never read, group name unresolvable); the caller reports
    nothing in that case, per the module docstring."""
    if field in _SCALAR_FIELDS:
        live = _FIELD_READERS[field](state, base)
        if live is None:
            return None  # never read -- not evidence of a violation
        return _OPERATORS[op_symbol](live, expected)

    if field in _GROUP_FIELDS:
        # `==` asserts membership, `!=` asserts non-membership. `strip_group_membership` is
        # `audit.diff_against_plan`'s own resolver, so an unknown or ambiguous group name
        # is skipped here
        # exactly as it is there.
        member = strip_group_membership(state, base, field, str(expected))
        if member is None:
            return None
        return member if op_symbol == "==" else not member

    live_patch = _live_patch(state, base)
    if live_patch == "unread":
        return None
    matches = live_patch == parse_patch_value(str(expected))
    return matches if op_symbol == "==" else not matches


def _violation_detail(
    state: ConsoleState, base: str, cond: dict, label: str
) -> str:
    """The sentence a `Finding` carries: the strip, what it IS, and the
    condition's own description -- `DCA 1 "DRUMS" is muted -- DCAs should
    not be muted.` (say what is wrong, in the
    engineer's words, and nothing else). The condition's id, operator and
    wanted value are not repeated: the description says what was wanted,
    and the finding's addresses and rule id carry the rest."""
    field, op_symbol, expected = cond["field"], cond["operator"], cond["value"]

    if field == "muted":
        fact = "is muted" if _FIELD_READERS[field](state, base) else "is not muted"
    elif field == "fader_db":
        live = _FIELD_READERS[field](state, base)
        level = "-inf" if live is None or live == float("-inf") else f"{live:g}"
        fact = f"has its fader at {level} dB"
    elif field in _GROUP_FIELDS:
        kind = "DCA" if field == "dca" else "mute group"
        fact = (f"is not in {kind} {expected!s}" if op_symbol == "=="
                else f"is in {kind} {expected!s}")
    else:
        live_patch = _live_patch(state, base)
        fact = ("is unpatched" if live_patch is None
                else f"is patched to {format_socket(*live_patch)}")
    return _sentence(label, fact, cond)


def _sentence(label: str, fact: str, cond: dict) -> str:
    """`CH 1 "Kick" is patched to LCL 1 -- Kick must stay patched to LCL 5.`:
    the strip, what it is, and the condition's own description."""
    description = cond["description"].strip()
    if description and description[-1] not in ".!?":
        description += "."
    return f"{label} {fact} -- {description}"


@dataclass(frozen=True)
class _Verdict:
    """A send or phantom condition judged on one strip: whether it holds,
    and when it does not, what the strip is doing and the addresses that
    show it."""
    holds: bool
    fact: str = ""
    addresses: tuple[str, ...] = ()


def _and_join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _send_candidates(state: ConsoleState, target: Target) -> list[tuple[str, int]]:
    """The `(kind, index)` pairs a send condition's `bus` names: a position,
    a range or `ALL` as written, and a bus's name (bare, or after the kind
    word `BUS`) as the one bus that has it among the names last read, or
    none when no bus or more than one does."""
    if target.is_name or target.is_scoped:
        wanted = (target.name if target.is_scoped else target.text).strip().lower()
        matches = [i for i in bus_indices(state)
                   if (name := state.name(f"/bus/{i}")) is not None
                   and name.strip().lower() == wanted]
        return [("bus", matches[0])] if len(matches) == 1 else []
    return [(target.bank, n) for n in range(target.first, target.last + 1)]


def _send_address(base: str, kind: str, index: int, leaf: str) -> str:
    """A strip's send to a bus or a Matrix, or its route to a Main (which has
    a switch and nothing else)."""
    if kind == "main":
        return f"{base}/main/{index}/on"
    return f"{base}/send/{'MX' if kind == 'mtx' else ''}{index}/{leaf}"


def _assess_send(state: ConsoleState, base: str, cond: dict, target: Target) -> _Verdict | None:
    """`send_on`, `send_db` or `send_mode` on one strip, over every bus the
    condition's `bus` covers. None when none of those sends was read. The
    strip breaks the condition when any send it covers does."""
    field, op_symbol, expected = cond["field"], cond["operator"], cond["value"]
    leaf = _SEND_LEAF[field]
    reader = {"send_on": state.flag, "send_db": state.number, "send_mode": state.text}[field]
    wanted = _SEND_MODES[expected] if field == "send_mode" else expected
    answered = False
    broken: list[tuple[str, int, object, str]] = []
    for kind, index in _send_candidates(state, target):
        address = _send_address(base, kind, index, leaf)
        live = reader(address)
        if live is None:
            continue
        answered = True
        if not _OPERATORS[op_symbol](live, wanted):
            broken.append((kind, index, live, address))
    if not answered:
        return None
    if not broken:
        return _Verdict(True)
    noun = "route" if broken[0][0] == "main" else "send"
    plural = "s" if len(broken) > 1 else ""
    labels = [_position_label(state, f"/{kind}/{index}") for kind, index, _live, _a in broken]
    if field == "send_on":
        fact = (f"has its {noun}{plural} to {_and_join(labels)} switched "
                f"{'on' if broken[0][2] else 'off'}")
    elif field == "send_db":
        shown = [f"{label} at {'-inf' if live == float('-inf') else f'{live:g}'} dB"
                 for label, (_k, _i, live, _a) in zip(labels, broken)]
        fact = f"has its {noun}{plural} to {_and_join(shown)}"
    else:
        shown = [f"{label} {_SEND_MODE_FACT.get(live, str(live).lower())}"
                 for label, (_k, _i, live, _a) in zip(labels, broken)]
        fact = f"has its {noun}{plural} to {_and_join(shown)}"
    return _Verdict(False, fact, tuple(address for _k, _i, _l, address in broken))


def _assess_phantom(state: ConsoleState, base: str, cond: dict) -> _Verdict | None:
    """`phantom` on one strip: the 48V of each socket it hears
    (`audit.strip_source_sockets`) must satisfy the condition. None for an
    unpatched strip, one on its alternate input, a group with no head amp,
    and when any of its sockets' 48V was not read."""
    op_symbol, expected = cond["operator"], cond["value"]
    sockets = strip_source_sockets(state, base)
    if not sockets or sockets[0][0] not in PHANTOM_CAPABLE_GROUPS:
        return None
    readings = [(group, socket, state.input_phantom(group, socket)) for group, socket in sockets]
    if any(live is None for _g, _s, live in readings):
        return None
    broken = [(group, socket, live) for group, socket, live in readings
              if not _OPERATORS[op_symbol](live, expected)]
    if not broken:
        return _Verdict(True)
    where = _and_join([format_socket(group, socket) for group, socket, _live in broken])
    return _Verdict(False, f"has 48V {'on' if broken[0][2] else 'off'} at {where}",
                    tuple(f"/io/in/{group}/{socket}/vph" for group, socket, _live in broken))


def _position_label(state: ConsoleState, base: str) -> str:
    """`CH 10 "Kick"`, or `MAIN 1` for a strip with no
    name in this state -- a Main's and a Matrix's names are not polled,
    and a factory strip's name is empty. A range or ALL
    finding cites the strip's position, and its name when it has one."""
    _, bank, n = base.split("/")
    name = (state.name(base) or "").strip()
    named = f' "{name}"' if name else ""
    return f"{CANONICAL_KIND_WORD[bank]} {n}{named}"


def _name_overlaps(state: ConsoleState, target: Target) -> list[str]:
    """Channel and aux bases whose live name reads as this position or
    scoped target -- spelled as written (`ch10`, `bus drums`) or
    canonically (`CH 10`, `BUS drums`), case-insensitively. The position
    or scoped form wins; this is how the overlap announces
    itself."""
    spellings = {target.text.strip().lower(), target.canonical.lower()}
    return [base for base in strip_bases(state)
            if (live := state.name(base)) is not None and live.strip().lower() in spellings]


# --------------------------------------------------------------------------
# Scoped names (`BUS Drums`): resolved ONCE, then watched by position.
# --------------------------------------------------------------------------
#
# Names need not be read every cycle, since that is an expensive
# operation. So a scoped name is matched
# against the strip names of the session's FIRST reading -- the baseline
# Start takes -- and the position it matched is what every later cycle
# evaluates. A rename or a move after Start is not followed until Watch is
# started again, and the INFO announcing the resolution says so. Nothing
# about this adds a per-cycle read: the channel, aux, bus and DCA names
# are in the poll already (`audit.console_read_plan`), and a Main's or a
# Matrix's, which are not, are read once at Start by the session's
# provider (`start_name_addresses`, `read_names_at_start`).

# Banks whose `/name` the poll does not read (`audit.console_read_plan`
# reads `mute` and `fdr` only on a Main and a Matrix), so a scoped name on
# one needs its bank's names read once at Start.
_UNPOLLED_NAME_BANKS = frozenset({"main", "mtx"})


def start_name_addresses(conditions: list[dict]) -> list[str]:
    """The `/name` addresses a session must read ONCE at Start for these
    conditions' scoped names to resolve, beyond what the poll reads: every
    Main's (`/main/1..4/name`) when a condition names `MAIN <name>`, every
    Matrix's when one names `MTX <name>`, nothing otherwise. One bank's
    worth however many conditions name it."""
    banks = set()
    for cond in conditions:
        target = parse_target(cond["channel"])
        if target.is_scoped and target.bank in _UNPOLLED_NAME_BANKS:
            banks.add(target.bank)
    return [f"/{bank}/{n}/name" for bank in TARGET_BANKS if bank in banks
            for n in range(1, CAPACITY[bank] + 1)]


def read_names_at_start(
    provider: Callable[[], ConsoleState],
    read_name: Callable[[str], str | None],
    addresses: list[str],
) -> Callable[[], ConsoleState]:
    """`provider`, with `addresses` (`start_name_addresses`) read ONCE
    through `read_name` and added to the FIRST state it returns -- the one
    every scoped condition resolves against. Later states are returned
    untouched: these names are never re-read. An address already in the
    state, or one `read_name` answers None for, is left out."""
    first = True

    def wrapped() -> ConsoleState:
        nonlocal first
        state = provider()
        if first and addresses:
            extra = {}
            for address in addresses:
                if address in state.values:
                    continue
                value = read_name(address)
                if value is not None:
                    extra[address] = value
            if extra:
                state = replace(state, values={**state.values, **extra})
        first = False
        return state

    return wrapped


def console_name_reader(console) -> Callable[[str], str | None]:
    """A `read_name` for `read_names_at_start` over a live
    `atoo.console.WingConsole`: one GET per address, the text it
    holds, or None when the desk did not answer."""
    def read(address: str) -> str | None:
        reply = console.get(address)
        if reply is None:
            return None
        value, error = reply.value("s")
        return None if error is not None or value is None else str(value)
    return read


@dataclass(frozen=True)
class _Resolution:
    """What a scoped name resolved to at Start: the base and its live
    name, or None; and the INFO/WARNING notes that say so
    (`watch.WatchNote`), returned by the condition's check every cycle so
    they are shown for the life of the session -- by `atoo watch`
    at their severity, and by the Watch page in the status line under
    its header rather than in the alert table."""
    base: str | None
    live_name: str | None
    notes: tuple[Finding, ...]


def _resolve_scoped(state: ConsoleState, target: Target, cond: dict) -> _Resolution:
    """Match `target`'s name against the names of every strip of its kind
    in `state`, case-insensitively. One match is the strip watched,
    announced at INFO. None, or more than one, is a WARNING and nothing is
    watched -- an ambiguous name is a target nobody can say is right, so
    the warning names the positions and the engineer writes the one meant.
    A bank none of whose names was read at all is a WARNING of its own:
    "no name was read" and "nothing is called that" are different facts."""
    rule_id = f"WATCH:{cond['id']}"
    description = cond["description"]
    word = CANONICAL_KIND_WORD[target.bank]
    shown = target.canonical
    wanted = target.name.strip().lower()
    later = "It is tried again the next time Watch starts."

    notes: list[Finding] = []
    overlaps = _name_overlaps(state, target)

    # Decision 2: the scoped form wins over a
    # channel or aux literally named "BUS Drums", and says so.
    for base in overlaps:
        _, bank, n = base.split("/")
        literal = state.name(base).strip()
        notes.append(watch_note(Diagnostic.audit(
            rule_id, Severity.INFO, "watch", description,
            f"{target.text.strip()!r} is read as the {word} named {target.name!r}, not as "
            f"the strip named {literal!r} at {base} -- a kind word followed by a name is "
            f"that form. To watch that strip, write {CANONICAL_KIND_WORD[bank]} {literal} "
            f"or {CANONICAL_KIND_WORD[bank]} {n}.",
            (f"{base}/name",),
        ), "Read as written",
            f"{shown} is the {word}, not {CANONICAL_KIND_WORD[bank]} {n} {literal!r}"))

    candidates = [f"/{target.bank}/{n}" for n in range(1, CAPACITY[target.bank] + 1)]
    read = [base for base in candidates if state.name(base) is not None]
    if not read:
        notes.append(watch_note(Diagnostic.audit(
            rule_id, Severity.WARNING, "watch", description,
            f"{shown}: no {word} name could be read at Start, so the condition "
            f"{cond['id']!r} is not watched. {later}",
            (),
        ), "Not watched", f"{cond['id']} ({shown}: no {word} name read)"))
        return _Resolution(None, None, tuple(notes))

    matches = [base for base in read if state.name(base).strip().lower() == wanted]
    if not matches:
        notes.append(watch_note(Diagnostic.audit(
            rule_id, Severity.WARNING, "watch", description,
            f"{shown} matches no {word} at Start -- none is named {target.name!r} -- so "
            f"the condition {cond['id']!r} is not watched. {later}",
            (),
        ), "Not watched", f"{cond['id']} ({shown}: no such {word})"))
        return _Resolution(None, None, tuple(notes))
    if len(matches) > 1:
        positions = [f"{word} {base.split('/')[2]}" for base in matches]
        notes.append(watch_note(Diagnostic.audit(
            rule_id, Severity.WARNING, "watch", description,
            f"{shown} matches {len(matches)} strips at Start -- "
            f"{', '.join(positions)} are each named {target.name!r} -- so the condition "
            f"{cond['id']!r} is not watched. Write the position you mean instead "
            f"({' or '.join(positions)}).",
            tuple(f"{base}/name" for base in matches),
        ), "Not watched", f"{cond['id']} ({shown}: {' and '.join(positions)} share the name)"))
        return _Resolution(None, None, tuple(notes))

    base = matches[0]
    position = f"{word} {base.split('/')[2]}"
    notes.append(watch_note(Diagnostic.audit(
        rule_id, Severity.INFO, "watch", description,
        f"{shown} resolved to {position} at Start; a rename or move after Start is not "
        f"followed until Watch restarts.",
        (f"{base}/name",),
    ), "Resolved at Start", f"{shown} \u2192 {position}"))
    return _Resolution(base, state.name(base).strip(), tuple(notes))


def _make_check(cond: dict) -> Callable[[ConsoleState], list[Finding]]:
    channel_name = cond["channel"]
    target = parse_target(channel_name)
    field = cond["field"]
    op_symbol = cond["operator"]
    expected = cond["value"]
    severity = Severity(cond["severity"])
    rule_id = f"WATCH:{cond['id']}"
    description = cond["description"]
    addresses = _FIELD_ADDRESSES.get(field, ())
    bus_target = parse_target(cond["bus"]) if field in _SEND_FIELDS else None

    def judge(state: ConsoleState, base: str) -> _Verdict | None:
        if bus_target is not None:
            return _assess_send(state, base, cond, bus_target)
        return _assess_phantom(state, base, cond)

    def finding_for(state: ConsoleState, base: str, label: str) -> list[Finding]:
        if field in _SEND_FIELDS or field == _PHANTOM_FIELD:
            verdict = judge(state, base)
            if verdict is None or verdict.holds:
                return []
            return [Diagnostic.audit(
                rule_id, severity, "watch", description,
                _sentence(label, verdict.fact, cond), verdict.addresses)]
        holds = _satisfied(state, base, field, op_symbol, expected)
        if holds is None:
            # Live state can't answer this cycle (field never read, group
            # name unresolvable) -- a missing answer is not a violation.
            return []
        if holds:
            return []  # desired relationship holds -- nothing to report
        return [Diagnostic.audit(
            rule_id, severity, "watch", description,
            _violation_detail(state, base, cond, label),
            tuple(f"{base}/{suffix}" for suffix in addresses),
        )]

    # A scoped name's resolution, made on this check's first call -- the
    # session's first reading -- and kept for every call after it.
    resolution: _Resolution | None = None

    def check(state: ConsoleState) -> list[Finding]:
        nonlocal resolution
        if target.is_scoped:
            if resolution is None:
                resolution = _resolve_scoped(state, target, cond)
            findings = list(resolution.notes)
            if resolution.base is not None:
                findings += finding_for(state, resolution.base,
                                        _position_label(state, resolution.base))
            return findings

        if target.is_name:
            base = _resolve_channel_base(state, channel_name)
            if base is None:
                # Zero or ambiguous matches -- a different, not-yet-built
                # check (see module docstring); not evidence of a violation.
                return []
            return finding_for(state, base, _position_label(state, base))

        findings: list[Finding] = []
        note = main_default_note(target)
        if note:
            findings.append(watch_note(Diagnostic.audit(
                rule_id, Severity.INFO, "watch", description,
                f"{note} (condition {cond['id']!r}).", ("/main/1/name",)),
                "Read as written", f"{target.text.strip()} \u2192 MAIN 1"))
        # The position form wins over a strip that happens to
        # be named the same, and says so rather than silently watching
        # something other than what the engineer may have meant.
        for base in _name_overlaps(state, target):
            findings.append(watch_note(Diagnostic.audit(
                rule_id, Severity.INFO, "watch", description,
                f"{channel_name!r} is read as the position {target.canonical}, not as the "
                f"strip named {state.name(base)!r} at {base} -- a target that parses as a "
                f"position, range or ALL form is that form. Rename the strip, or the "
                f"condition {cond['id']!r} watches {target.canonical} as written.",
                (f"{base}/name",),
            ), "Read as written",
                f"{target.canonical} is the position, not the strip named {state.name(base)!r}"))
        # One finding per violating strip, each citing its own position.
        for base in target.bases():
            findings += finding_for(state, base, _position_label(state, base))
        return findings

    return check


def build_watch_rules(conditions: list[dict]) -> list[AuditRule]:
    """One `AuditRule` per validated condition (as returned by
    `load_watch_conditions`/`parse_watch_conditions`), `category="watch"`
    -- distinct from `DEFAULT_RULES`'s built-in categories (routing,
    configuration, channels, naming, levels). Each rule's `check` resolves
    the condition's `channel` against live state, reads its `field`, and
    fires a `Finding` exactly when the condition's desired relationship
    does not hold (see module docstring's "Evaluation semantics")."""
    return [
        AuditRule(
            id=f"WATCH:{cond['id']}",
            severity=Severity(cond["severity"]),
            category="watch",
            title=cond["description"],
            description=cond["description"],
            check=_make_check(cond),
        )
        for cond in conditions
    ]
