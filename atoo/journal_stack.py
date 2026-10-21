"""One time-ordered journal stack per bundle.

Journals used to be keyed by **kind and location** rather than by
**time**: `apply --show DIR --confirm` overwrote `DIR/apply-journal.json`,
`amend --show` overwrote `DIR/amend-journal.json`, and `undo FILE` wrote
`FILE-stem.undo.json` over whatever was there. Two consequences, one of
them a hazard:

1. **An apply could be undone out from under a later amend.** `undo`'s
   guard is per address -- it reverses an address only where the desk
   still holds what the journal says we wrote -- and that guard cannot
   see a *later* journal. Apply writes ch 1-19, an amend then adds
   ch 21-23 and touches nothing in 1-19, so every address in the apply
   journal still reads exactly what apply put there, the guard passes on
   all of them, and the whole show comes off the desk under the horn
   section. `tests/test_journal_stack.py` reproduces it.
2. **Each kind kept exactly one.** A second amend overwrote the first
   amend's journal, and the step before last was simply gone.

Every apply or amend is timestamped, and
the last n actions kept, regardless of type, such that each undo walks us
back one step in time. It makes no sense to undo an apply
out from under a subsequent amend. So it is one virtual journal,
one arm button, and one undo button.

## What is on disk

    my-show/
      plan.json                                    the last build (only `build` writes it)
      journals/
        index.json                                   the listing, so a UI need not parse journals
        20260924T054016.101288Z-apply-S100231.json   the stack itself, one file per write
        20260924T055233.004121Z-apply-S100587.json
        20260924T061502.774310Z-amend-S100231.json
        20260924T062011.930451Z-undo-S100231.json

The entry filename is a UTC timestamp to the microsecond, the kind, and
**the desk the run wrote to** (`entry_name`, `desk_token`): its serial, or
-- only for a desk that states none -- the address it was reached at. The
UTC stamp comes first, so a **lexicographic sort is a chronological sort**
and no reader has to open a file to order the stack. The token is
sanitised to `[A-Za-z0-9.]` (an IPv6 colon or a hostname's hyphen becomes
`_`, so the `-` separators stay unambiguous), and an address carries
`_port<N>` only when the desk was reached on a port other than WING's
fixed 2223. The serial, not the IP, because the IP is wrong the moment the
desk moves from the home network to the gig network. An entry recorded
before this change is named `<stamp>-<kind>.json`, and is read, listed,
sorted and undone exactly as before (`parse_entry_name`).

**`journals/` is the only record**. Before that,
each confirmed apply, amend and patch was also copied over a top-level
`apply-journal.json`, `amend-journal.json` or `patch-journal.json`, the
newest of its kind; nothing writes those any more. A confirmed run in a
bundle writes its journal straight into `journals/`, named for the desk it
reached (`new_entry_path`), and `record` indexes it in place. Only a
`--journal PATH` the operator chose explicitly is written elsewhere; that
file is copied in, and keeps the same bytes as its entry.

A bundle with no `journals/` directory has recorded nothing: `entries()`
answers with an empty list, `find()` with None, and `atoo undo --show`
says there is nothing to undo. Until 2026-10-02 it fell back to a
top-level `apply-journal.json` an earlier version had written; the last
bundle that had one was cleaned up, and the fallback went
with it. A top-level copy that a bundle made in between still holds is
neither read nor reported.
`atoo undo <a journal file>` reads any journal by its path, and one
that carries a `stack_entry` block resolves to the entry it copies.
Nothing migrates anything.

## The stack, and why an undo is not a position on it

Every confirmed `apply`, `amend` and `undo` is recorded, **including a
run that aborted partway** -- `undo.py`'s docstring is explicit that a
partial journal "is the most important one to be able to reverse -- it is
the one nobody planned for". An aborted UNDO is the one case recorded
without popping what it reversed: it reached some addresses and not
others, so the run underneath still stands and stays the top (`_live`),
and the next `undo --show` finishes it.

`undo` **pops**. Asked whether a second press should step back two or
redo the first, the choice was *steps back two*, so after undoing the
amend the top of the stack is the apply. The undo's own journal is still
written and still recorded -- it is a set of writes, and FR-X.3 gets no
exception, and it is the only file that carries the `_refusal_record`
rows for the addresses undo declined to touch -- but it is **never a
forward step and never the pop target**. That falls out of what the file
already is: `undo._restore` deliberately inverts `prior_value` and
`intended_value`, so an undo journal is the *mirror* of the entry above
it, not a new position.

So `_live()` walks the entries oldest-first, pushes anything that is not
an undo, and for an undo **removes the entry it reversed**. Undoing an
undo (the CLI-only redo: `atoo undo <the .undo.json>`) therefore
cancels a pop and puts that entry back on the stack, which is right --
the desk is once again in the state that entry left it in.

## Why there is an index

The Apply screen draws one row per entry: timestamp, kind, the one-line
summary, and a mismatch count. A real apply journal is 707 records and
several hundred KB; parsing every one of them to draw a list would make
opening the screen cost the whole stack. `index.json` holds those four
things per entry and is written once, when the entry is recorded.

It is a **cache, not the record**: `entries()` drops rows whose file is
gone and parses any journal file the index has never seen, so a stack
copied without its index, or an entry written by another version, is
listed rather than lost. The journals are the evidence; the index is
only how they are found quickly.

## The plan an amend replaced -- entries recorded

**No run replaces `plan.json`**: only a build writes it,
and what a patch or an amend put on a desk is that desk's entry's
`desk_plan` (below). What follows is how entries recorded in between behave, and they
must still undo correctly, so all of it stays.

A confirmed `amend --show DIR` replaced `DIR/plan.json` with the amended
show, so that `verify`, `watch` and the next amend read what is actually
on the desk -- before this, a second amend from the same rebuild saw the
strips the first one had filled as somebody else's and placed the same
channels again. The choice (2026-09-24) was to replace the file rather than
add an applied-plan file beside it, **and to keep the plan it replaced in
that amend's journal entry, so undo puts it back.**

So an entry whose run replaced `plan.json` carries a `bundle_plan` block
(`PLAN_BLOCK`): the replaced file's exact text, its sha256, and the sha256
of the file the run wrote. It is embedded in the entry, not written as a
sibling file, which keeps every rule above intact -- an entry is still one
file, pruning still deletes one file, and `listing()` still reads only the
index.

Undoing the entry puts `replaced` back **only while `plan.json` still
hashes to `written_sha256`**. If the operator has rebuilt the plan since,
their build is theirs and is left alone, with a warning. The undo that does
put it back carries its own `bundle_plan` block, the mirror image -- which
is how the redo (`atoo undo <the .undo.json>`) re-installs the amended
plan under exactly the same rule, without a special case.

## Which desk an entry wrote to

One plan can be applied to more than one console -- a primary Compact
and a backup Rack, say. The stack is still one per
bundle, but "the newest write" now has to mean the newest write **to the
desk on the line**, or this happens:

1. apply the plan to the primary, then to the backup;
2. press Undo while connected to the primary;
3. the top of the stack is the backup's apply, undo's per-address guard
   passes on every address (the primary holds the same values), and the
   primary is reversed.

So every entry records the desk it wrote to: `stack_entry.desk`, and the
same block in its index row (whose `serial` and `address` are also
columns of their own). `desk_from_identity` builds it from the `/?` reply
(`WING,<ip>,<name>,<model>,<serial>,<firmware>`) plus the address the
command connected to. Both are recorded: the serial is the identity and
names the file, the address is where the run reached it.

## Journals and undo are strict to the desk; apply and amend are not

The journal is per desk, for both apply and amend: undo can only apply
against the correct desk and the correct journal. The serial number is the
identity. Journals and undo are tracked strictly to the specific desk,
while apply and subsequent amends are relatively permissive, to allow for
multiple desks or the IP number changing on the desk (say, going from a
home network to a gig network).

So **a desk is its serial** (`same_desk`): two blocks that both state one
are the same desk exactly when the serials match, whatever their
addresses -- the same serial at a new IP is the same desk, and undo says
so at INFO naming both addresses (`desk_moved`); a different serial is a
different desk even at the same IP (the backup brought up on the
primary's address). Only when a side states no serial is the address
compared. Undo pops and accepts only entries recorded on the connected
desk, and there is no override flag -- the `--other-desk` is gone,
because there is no legitimate reason to reverse desk A's journal onto
desk B.

`top`, `above`, `positions` and `listing(desk=...)` take an optional `desk`
and answer for that desk alone -- entries recorded on another desk are
neither popped nor counted as "later". With no desk (`None`: nothing
configured, or an offline `--state` preview) they answer for the whole
stack, as before.

Apply and amend are permissive: apply writes to any desk, and amend finds
the connected desk's own applied plan by serial (below), falling back to
`plan.json`, with an INFO, for a desk that has no entry yet.

**An entry recorded before journals named their desk carries no desk**, and counts as being on
whichever desk is connected (`on_desk`): the single-desk assumption was
true when it was written, there is nothing recorded to be strict against,
and refusing it would strand the one undo those runs have. Undo's own
per-address guard still applies to it. `atoo undo` says so at INFO
when it relies on it, because an inferred value
announces itself.

## The plan each entry left on its desk

`plan.json` is the bundle's LATEST show: after amending the
primary it is the amended show. But the backup has not been amended, and an
amend of the backup that read `plan.json` as "what is on this desk" called
the primary's new strips its own and reported "Nothing to add". So every
confirmed apply and amend entry also embeds **the plan it left on its desk**
(`DESK_PLAN_BLOCK`, `desk_plan`): the applied plan for an apply, the
effective plan for an amend (for an amend that aborted partway, the plan
it started from, because it at least describes everything that
was there before). `desk_plan()` reads the connected desk's newest standing
entry's copy, which is what `amend --show` and `patch --show` compare
against. Because it is
per entry, an undo that pops a desk's amend puts that desk's applied plan
back to the one beneath it with no bookkeeping of its own. Embedded, like
`bundle_plan`: an entry is still one file, and pruning and the index need
no new case.

## A change

A `patch` entry -- a change typed in plain English -- carries its change
(`CHANGE_BLOCK`: its number on this bundle's stack, its short name, and the
text), in the entry and in its index row, so a listing reads as a list of
changes (`change 3: Add horns on A 21-23`). `changes_on_desk` is the changes
and amends standing on a desk above its newest apply: what a full apply
would replace, and what `replaced_changes_diagnostic` warns about.

## Pruning: the newest five, and never what a desk still depends on

The builds, journals, and logs
directories are continually pruned to a max of 5 entries each. So `record` keeps `keep_limit()`
entries (`prune.KEEP`, five; `index.json` is not an entry) and deletes the
rest, in the same call that rewrites the index -- the index never names a
deleted file. Until then the limit was 200, so that nothing ever pruned.

Five is small enough that WHICH five matters, because the stack is not a
list of independent files: an undo means something only next to the entry
it reversed, and "what is on this desk now" is the desk's newest standing
write, however old. So `_prune` deletes oldest first, but prefers, in
order: writes that no longer stand (an entry an undo popped, an undo a redo
reversed), then undos, then standing writes. And it takes no deletion that
would change any answer about a kept entry -- which writes stand, the order
of the stack, which undo reversed what -- or that would remove any desk's
newest standing write (`_needed`, the entry `top` pops and `desk_plan`
reads). Each candidate is tried against the whole stack and checked, so
the rule cannot drift from `_live`. If nothing more can safely go, more
than five are kept: losing the one that says what is on a desk is the
mistake that cannot be undone.

A standing write that IS pruned is still on its desk. It is remembered as a
row in `index.json`'s `pruned` list (`PRUNED_KEY`): enough to name it, never
enough to reverse it. Two things read those rows:

* **undo stops above them** (`undo_floor`). Undoing a desk's last kept
  write would leave the desk holding a pruned one, which no journal
  records: `amend` and `patch` would compare against the wrong plan, and
  nothing could undo further. So `atoo undo` refuses that step, and
  undo reaches back at most five writes. A redo whose entry was pruned is
  refused for the same reason (`pruned_target`).
* **a full apply's warning still counts them** (`changes_on_desk`), marked
  "(journal pruned)".

`record` hands back the rows it pruned this time (`Entry.pruned_now`), and
the commands say so at INFO: from then on undo cannot reach them. The index
also keeps the highest change number handed out (`HIGHEST_CHANGE_KEY`), so
a pruned stack never numbers two changes the same. A change whose journal
is pruned cannot be promoted (`promote` needs its saved plan).

This module does the ordering, reading and pruning. `atoo/bundle.py`
stays what it is -- pure path resolution, which is why the `journals/`
name lives there and nothing else about the stack does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from atoo.bundle import JOURNALS, PLAN

#: What `index.json` is called inside `journals/`. Never an entry: the
#: scan below skips it by name, so a stack directory is self-describing
#: without a manifest of what is and is not a journal.
INDEX = "index.json"

#: The kinds that can be recorded. `undo` is a kind but not a stack
#: position -- see the module docstring.
KINDS = ("apply", "amend", "patch", "undo")

#: The kinds that change a show already on a desk without replacing it: an
#: amend (from a rebuilt plan) and a patch (a typed change).
#: Neither writes plan.json any more -- only a build does -- so what they
#: put on a desk is recorded by the desk's journal alone, and a full apply
#: that would replace them says so first (`changes_on_desk`).
CHANGE_KINDS = ("amend", "patch")

#: The top-level key in `index.json` listing the entries pruning deleted
#: while their writes still stood on a desk -- see "Pruning" in the module
#: docstring. Rows, not journals: enough to say what is on a desk below the
#: kept window, never enough to reverse it.
PRUNED_KEY = "pruned"

#: The top-level key in `index.json` holding the highest change number this
#: bundle has handed out, so a pruned stack never hands one out twice.
HIGHEST_CHANGE_KEY = "highest_change_number"


def _now() -> datetime:
    """Indirected so a test can pin the clock -- two records in the same
    microsecond is otherwise unreachable, and it is exactly the case a
    filename-is-the-order scheme has to get right."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Entry:
    """One journal on the stack, as the listing draws it.

    `summary` and `mismatches` come from the index, so a caller that only
    wants the four columns never opens `path`."""

    id: str
    path: Path
    kind: str
    #: ISO-8601 UTC -- the journal's own `generated_at` where it has one,
    #: which is when the run finished, not when it was filed.
    timestamp: str
    summary: str
    mismatches: int
    writes: int
    #: For an undo entry: the id of the entry it reversed, where that
    #: entry is one of ours. None for an undo of a journal from outside
    #: this bundle, and for every other kind.
    undo_of: str | None = None
    #: Set by `listing()`: the undo entry that popped this one, if any.
    undone_by: str | None = None
    #: Set by `listing()`: this is the entry `atoo undo` would pop.
    is_top: bool = False
    #: The run stopped partway (a connection lost mid-run). For an undo it
    #: decides the stack: a PARTIAL reversal is recorded, linked to what it
    #: was reversing, and does not pop it -- see `_live`.
    aborted: bool = False
    #: The desk this run wrote to (`desk_from_identity`), or None for an
    #: entry recorded before entries named their desk -- which counts as
    #: being on whichever desk is connected (`on_desk`).
    desk: dict | None = None
    #: Set by `listing(desk=...)`: this entry was written to that desk (or
    #: names none). None when the listing was asked for no desk at all.
    on_this_desk: bool | None = None
    #: For a patch entry: `{"number", "name", "text"}` -- the change the
    #: engineer typed, its short name and its number on this bundle's stack
    #: (`patch.change_block`), so the journal reads as a list of changes.
    change: dict | None = None
    #: This row stands for a journal `_prune` deleted while its writes still
    #: stood on its desk: it is read from `index.json`'s `pruned` rows, has
    #: no file, and can be named but never undone or promoted.
    pruned: bool = False
    #: Set on the entry `record` returns: the `index.json` rows of the
    #: journals this record pruned while their writes still stood on a desk
    #: -- what the caller says at INFO, because undo can no longer reach them.
    pruned_now: tuple = ()

    @property
    def serial(self) -> str | None:
        """The serial of the desk this entry wrote to -- its identity, and
        what its file name carries -- or None (a desk that stated none, or
        an entry that recorded no desk)."""
        return (self.desk or {}).get("serial") or None

    @property
    def address(self) -> str | None:
        """The address the desk this entry wrote to was reached at, or None
        for an entry that recorded no desk."""
        return (self.desk or {}).get("address") or None


class JournalStackError(Exception):
    """A stack that cannot be read or written, phrased for a user."""


def stack_dir(bundle_dir: str | Path) -> Path:
    """`<bundle>/journals` -- whether or not anything is there yet."""
    return Path(bundle_dir) / JOURNALS


def keep_limit() -> int:
    """How many entries `journals/` keeps: `prune.KEEP` (five), shared with
    `builds/` and `logs/`. Read at call time, so a test can lower it."""
    from atoo import prune
    return prune.KEEP


# ---------------------------------------------------------------------------
# Desks -- which console an entry wrote to
# ---------------------------------------------------------------------------

def _identity_fields(identity_args) -> list[str]:
    fields: list[str] = []
    for arg in identity_args or ():
        fields.extend(str(arg).split(","))
    return [f.strip() for f in fields]


def desk_from_identity(identity_args, address: str | None = None,
                       port: int | None = None) -> dict | None:
    """The `desk` block an entry records, from a `/?` reply and the address
    the command connected to.

    WING answers `WING,<ip>,<name>,<model>,<serial>,<firmware>`
    (`console.WingConsole.identity`). Positional, because that is the
    reply's shape; a field that is missing or blank is None rather than a
    guess. `model` is the `CONSOLE_MODELS` key when the desk's spelling is
    one we have measured (`console_facts.model_from_identity`), else the
    raw token. `model_token` is always the raw token, exactly as the desk
    spelled it -- so an entry says unambiguously whether its model was
    recognised (`model != model_token` for a translated spelling such as
    `wing-fullsize`; an unmeasured token is left as it came), and a run
    against a desk nobody has captured hands back the string to add to
    `console_facts.IDENTITY_MODEL_ALIASES`.

    `identity_args` may be None -- a desk the command reached but did not
    ask, or a test double -- and the block is then the address alone. None
    when there is neither an identity nor an address: nothing is known.
    """
    from atoo import console_facts

    fields = _identity_fields(identity_args)

    def field(index: int) -> str | None:
        return fields[index] or None if len(fields) > index else None

    address = (str(address).strip() or None) if address is not None else None
    if not fields and address is None:
        return None
    raw_model = field(3)
    model = console_facts.model_from_identity(identity_args) if fields else None
    return {
        "serial": field(4),
        "name": field(2),
        "model": model or raw_model,
        "model_token": raw_model,
        "address": address or field(1),
        "port": port,
        "firmware": field(5),
    }


#: WING's OSC port. An address alone means this port, and a file name
#: spells the port only when it is some other one.
DEFAULT_PORT = 2223


def _endpoint(desk: dict) -> tuple[str, int]:
    port = desk.get("port")
    try:
        port = int(port) if port not in (None, "") else DEFAULT_PORT
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    return str(desk.get("address")), port


def same_desk(a: dict | None, b: dict | None) -> bool:
    """Are two desk blocks the same console?

    **The serial is the desk** whenever both carry one: it survives the
    desk being given a new address (the home network to the gig network --
    `desk_moved` names that case, and undo says so at INFO), and two desks
    swapped onto the same address (the backup brought up on the primary's
    IP) are still two desks. Only when one side has no serial is the address
    (and port) compared, which is the best that is known about a desk that
    states none. Neither: not the same -- two blocks that share nothing
    cannot be shown to be one desk.
    """
    if not a or not b:
        return False
    if a.get("serial") and b.get("serial"):
        return a["serial"] == b["serial"]
    if a.get("address") and b.get("address"):
        return _endpoint(a) == _endpoint(b)
    return False


def desk_moved(recorded: dict | None, desk: dict | None) -> bool:
    """The same console (both state the same serial), reached at a
    different address from the one the journal recorded. Allowed -- it is
    the same desk -- and said at INFO, naming both addresses."""
    if not recorded or not desk:
        return False
    return bool(recorded.get("serial") and desk.get("serial")
                and recorded["serial"] == desk["serial"]
                and recorded.get("address") and desk.get("address")
                and _endpoint(recorded) != _endpoint(desk))


def on_desk(entry: Entry, desk: dict | None) -> bool:
    """Does `entry` count as written to `desk`?

    True for every entry when no desk is known (`desk` None: the question
    is the whole stack's, as before per-desk history existed), and for an
    entry that names no desk -- one recorded before entries did, when the
    single-desk assumption was true. The caller says so at INFO. Otherwise
    `same_desk`."""
    if desk is None or entry.desk is None:
        return True
    return same_desk(entry.desk, desk)


def describe_desk(desk: dict | None) -> str:
    """One phrase naming a desk, for a refusal or a listing: its name and
    model, its serial, and where it was reached."""
    if not desk:
        return "an unrecorded desk"
    head = " ".join(str(x) for x in (desk.get("name"), f"({desk['model']})"
                                     if desk.get("model") else None) if x)
    parts = []
    if desk.get("serial"):
        parts.append(f"serial {desk['serial']}")
    else:
        parts.append("no serial")
    where = desk.get("address")
    if where and desk.get("port"):
        where = f"{where}:{desk['port']}"
    text = (head + " " if head else "") + ", ".join(parts)
    return text + (f", at {where}" if where else "")


# ---------------------------------------------------------------------------
# Summarising a journal
# ---------------------------------------------------------------------------

#: Statuses an undo journal carries for an address it did NOT write --
#: `undo._refusal_record` puts the verdict in `status` verbatim. Mapped
#: to the words `UndoResult.summary()` uses, so the stack row and the
#: terminal say the same thing about the same run.
_UNDO_REFUSALS = {
    "refused_changed_since": "refused (changed since)",
    "refused_unreadable": "refused (unreadable)",
    "unreversible_no_prior": "unreversible (no prior value)",
    "already_restored": "already back",
}


def summarize(journal: dict, kind: str) -> tuple[str, int, int]:
    """`(one-line summary, mismatch count, records)` for one journal.

    For an apply or an amend this is `ApplyResult.summary()`'s first line
    -- reused rather than paraphrased, exactly as `webui._apply_payload`
    reuses it, so a row in the stack and a line in a terminal can never
    word the same run differently.

    An undo journal gets its own sentence. Running it through
    `ApplyResult.summary()` would print "APPLIED: ..." over a file whose
    whole content is reversals and refusals, and would count the
    refusal rows as addresses that were evaluated for writing.
    """
    rows = journal.get("writes") or []
    mismatches = sum(1 for r in rows if r.get("status") == "mismatch")
    if kind == "undo":
        reversed_count = sum(1 for r in rows if r.get("status") == "match")
        parts = [f"{reversed_count} reversed"]
        if mismatches:
            parts.append(f"{mismatches} did NOT land")
        for status, words in _UNDO_REFUSALS.items():
            count = sum(1 for r in rows if r.get("status") == status)
            if count:
                parts.append(f"{count} {words}")
        return "UNDONE: " + ", ".join(parts) + ".", mismatches, len(rows)

    from atoo.apply import ApplyResult, WriteRecord

    writes = [
        WriteRecord(
            address=r.get("address", ""), description=r.get("description", ""),
            value_type=r.get("value_type", "s"), method=r.get("method"), ack=r.get("ack"),
            prior_value=r.get("prior_value"), intended_value=r.get("intended_value"),
            readback_value=r.get("readback_value"), status=r.get("status", ""),
            timestamp=r.get("timestamp", ""), readback_source=r.get("readback_source"),
        )
        for r in rows
    ]
    result = ApplyResult(
        dry_run=bool(journal.get("dry_run")), writes=writes,
        aborted=bool(journal.get("aborted")),
        abort_reason=journal.get("abort_reason"),
    )
    line = result.summary().splitlines()[0]
    # An amend's row carries its scope, because "which strips was this
    # run allowed to touch" is the first question anyone asks of a
    # journal written mid-show (`ApplyResult.scope`) and an
    # address count alone cannot tell two amends apart on a listing.
    scope = journal.get("scope")
    if kind in CHANGE_KINDS and isinstance(scope, dict):
        strips = [str(x) for x in (scope.get("strips") or [])]
        released = [str(x) for x in (scope.get("released") or [])]
        parts = []
        if strips:
            parts.append(", ".join(strips))
        if released:
            parts.append("returned to free: " + ", ".join(released))
        renumbered = scope.get("renumbered") or []
        if renumbered:
            parts.append(f"renumbered {len(renumbered)} strip(s): "
                         + ", ".join(str(x) for x in renumbered[:3])
                         + (", ..." if len(renumbered) > 3 else ""))
        if parts:
            line += "  (scope: " + "; ".join(parts) + ")"
    return line, mismatches, len(rows)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JournalStackError(f"couldn't read journal {path}: {exc.strerror}") from exc
    except ValueError as exc:
        raise JournalStackError(f"journal {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise JournalStackError(f"journal {path} is not a JSON object")
    return payload


#: The longest desk token a file name carries. A hostname could be
#: anything; a file name cannot.
_TOKEN_MAX = 64

#: `<stamp>[-<n>]-<kind>[-<desk>].json`. The stamp is fixed-width, so the
#: names sort by it; `<n>` is the same-microsecond tiebreak; `<desk>` is
#: absent on an entry recorded before entries carried their desk's address.
_ENTRY_NAME = re.compile(
    r"^(?P<stamp>\d{8}T\d{6}\.\d{6}Z)(?:-(?P<n>\d+))?-(?P<kind>" + "|".join(KINDS)
    + r")(?:-(?P<desk>[A-Za-z0-9._]+))?\.json$")


def _sanitize(text: str) -> str:
    token = re.sub(r"[^A-Za-z0-9.]", "_", text.strip())[:_TOKEN_MAX]
    if not token.strip("."):
        token = token.replace(".", "_") or "_"
    return token


def desk_token(desk: dict | None) -> str | None:
    """The part of an entry's file name that names its desk: **its serial**,
    or -- only for a desk that states none -- the address it was reached
    at, plus `_port<N>` when that is not WING's 2223. Anything that is not
    `[A-Za-z0-9.]` becomes `_` (an IPv6 colon, a hostname's hyphen -- `-`
    is the name's own separator). None when nothing is known, and the entry
    is then named as one from before this was."""
    if not desk:
        return None
    if desk.get("serial"):
        return _sanitize(str(desk["serial"]))
    if not desk.get("address"):
        return None
    token = _sanitize(str(desk["address"]))
    _address, port = _endpoint(desk)
    if port != DEFAULT_PORT:
        token += f"_port{port}"
    return token


def parse_entry_name(name: str) -> dict | None:
    """`{"stamp", "n", "kind", "desk"}` for an entry's file name, or None
    for a name this module did not write. `desk` is the sanitised serial
    (or address) token (`desk_token`), or None for a name from before
    entries carried one -- which parses, sorts and lists exactly as it
    always did."""
    match = _ENTRY_NAME.match(name)
    return match.groupdict() if match else None


def entry_name(kind: str, when: datetime, desk: dict | None = None,
               suffix: int | None = None) -> str:
    """The file name an entry is recorded under -- see "What is on disk"."""
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    token = desk_token(desk)
    return (f"{stamp}" + (f"-{suffix}" if suffix else "") + f"-{kind}"
            + (f"-{token}" if token else "") + ".json")


def _entry_id(directory: Path, kind: str, when: datetime, desk: dict | None = None) -> str:
    candidate = entry_name(kind, when, desk)
    # Two records inside the same microsecond is vanishingly unlikely and
    # completely unacceptable: the loser would be silently overwritten,
    # which is the bug this module exists to fix.
    suffix = 1
    while (directory / candidate).exists():
        suffix += 1
        candidate = entry_name(kind, when, desk, suffix)
    return candidate


def record(bundle_dir: str | Path, kind: str, journal_path: str | Path,
           *, undo_of: str | None = None, extra: dict | None = None,
           desk: dict | None = None) -> Entry:
    """Put one journal on the bundle's stack and return its entry.

    `journal_path` is the file the run just wrote. If it is already
    inside `journals/` -- where every bundle run writes -- it is indexed in place; otherwise (a
    `--journal PATH` the operator named) it is copied in and the original
    is left where they asked for it.

    Either way the journal gains a `stack_entry` block naming its id, its
    kind and -- for an undo -- the entry it reversed, and a file outside
    the stack is rewritten with the same bytes so that the path somebody
    typed resolves to the same entry the stack knows about.

    `extra` is merged into the journal's top level before either copy is
    written -- today only `bundle_plan` (see `PLAN_BLOCK`), the plan.json
    an amend replaced. It goes into the entry itself rather than a file
    beside it, so pruning, the index and `listing()` need no new case:
    an entry is still exactly one file, and the listing still parses
    none of them.

    `desk` is the console the run wrote to (`desk_from_identity`). It goes
    into `stack_entry`, the index row and -- its serial, or its address when
    it states none -- the entry's file name, and is what lets `top(desk=...)` walk back one desk's history when
    one bundle has been applied to two. None records no desk, which reads
    exactly as an entry from before this existed (`on_desk`); a live run
    always has one.

    `extra` may also carry `desk_plan` (`DESK_PLAN_BLOCK`), the plan the run
    left on its desk.
    """
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a journal kind; known: {list(KINDS)}")
    source = Path(journal_path)
    directory = stack_dir(bundle_dir)
    payload = _read_json(source)

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise JournalStackError(
            f"couldn't create {directory}: {exc.strerror}") from exc

    in_place = source.parent.resolve() == directory.resolve()
    if in_place:
        entry_id = source.name
        entry_path = source
    else:
        entry_id = _entry_id(directory, kind, _now(), desk)
        entry_path = directory / entry_id

    for key, value in (extra or {}).items():
        payload[key] = value
    payload["stack_entry"] = {
        "id": entry_id,
        "kind": kind,
        "recorded_at": _now().isoformat(),
        **({"undo_of": undo_of} if undo_of else {}),
        **({"desk": desk} if desk else {}),
    }
    serialized = json.dumps(payload, indent=2)
    try:
        entry_path.write_text(serialized, encoding="utf-8")
        if not in_place:
            # The operator's own --journal file carries the same bytes,
            # `stack_entry` included: it is the same run, not a summary
            # of it, and `find()` resolves it by that id.
            source.write_text(serialized, encoding="utf-8")
    except OSError as exc:
        raise JournalStackError(
            f"couldn't write journal entry {entry_path}: {exc.strerror}") from exc

    summary, mismatches, writes = summarize(payload, kind)
    entry = Entry(
        id=entry_id, path=entry_path, kind=kind,
        timestamp=str(payload.get("generated_at") or payload["stack_entry"]["recorded_at"]),
        summary=summary, mismatches=mismatches, writes=writes, undo_of=undo_of,
        aborted=bool(payload.get("aborted")), desk=desk or None,
        change=_change_of(payload),
    )
    lost = _rewrite_index(directory,
                          [e for e in _scan(directory) if e.id != entry_id] + [entry])
    if lost:
        entry = replace(entry, pruned_now=tuple(lost))
    return entry


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _change_of(payload: dict) -> dict | None:
    """The `change` block a patch entry carries, or None."""
    block = payload.get(CHANGE_BLOCK) if isinstance(payload, dict) else None
    return block if isinstance(block, dict) else None


def _row(entry: Entry) -> dict:
    return {
        "id": entry.id, "kind": entry.kind, "timestamp": entry.timestamp,
        "summary": entry.summary, "mismatches": entry.mismatches,
        "writes": entry.writes, "undo_of": entry.undo_of, "aborted": entry.aborted,
        "desk": entry.desk, "serial": entry.serial, "address": entry.address,
        "change": entry.change,
    }


def _entry_from_row(directory: Path, row: dict) -> Entry | None:
    entry_id = row.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        return None
    path = directory / entry_id
    if not path.is_file():
        return None                       # the file is the record; the row is not
    return Entry(
        id=entry_id, path=path, kind=str(row.get("kind") or _kind_from_name(entry_id)),
        timestamp=str(row.get("timestamp") or ""),
        summary=str(row.get("summary") or ""),
        mismatches=int(row.get("mismatches") or 0),
        writes=int(row.get("writes") or 0),
        undo_of=row.get("undo_of") or None,
        aborted=bool(row.get("aborted")),
        desk=row.get("desk") if isinstance(row.get("desk"), dict) else None,
        change=row.get("change") if isinstance(row.get("change"), dict) else None,
    )


def _kind_from_name(name: str) -> str:
    """The kind an entry's file name states -- `<stamp>-<kind>-<desk>.json`
    now, `<stamp>-<kind>.json` before entries carried their desk's address.
    Asked only of a file whose own `stack_entry` does not say."""
    parsed = parse_entry_name(name)
    if parsed is not None:
        return parsed["kind"]
    stem = name[:-len(".json")] if name.endswith(".json") else name
    for kind in KINDS:
        if stem.endswith("-" + kind) or f"-{kind}-" in stem:
            return kind
    return "apply"


def _entry_from_file(path: Path) -> Entry | None:
    """A journal the index has never seen -- parsed, which is the slow
    path this module exists to avoid, and taken only for files the index
    does not cover."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    block = payload.get("stack_entry") if isinstance(payload.get("stack_entry"), dict) else {}
    kind = str(block.get("kind") or _kind_from_name(path.name))
    summary, mismatches, writes = summarize(payload, kind)
    return Entry(
        id=path.name, path=path, kind=kind,
        timestamp=str(payload.get("generated_at") or block.get("recorded_at") or ""),
        summary=summary, mismatches=mismatches, writes=writes,
        undo_of=block.get("undo_of") or None,
        aborted=bool(payload.get("aborted")),
        desk=block.get("desk") if isinstance(block.get("desk"), dict) else None,
        change=_change_of(payload),
    )


def _scan(directory: Path) -> list[Entry]:
    """Every entry in the stack, oldest first, index-first and parsing
    only what the index does not cover."""
    if not directory.is_dir():
        return []
    try:
        index = json.loads((directory / INDEX).read_text(encoding="utf-8"))
        rows = index.get("entries") if isinstance(index, dict) else None
    except (OSError, ValueError):
        rows = None
    found: dict[str, Entry] = {}
    for row in rows or []:
        if isinstance(row, dict):
            entry = _entry_from_row(directory, row)
            if entry is not None:
                found[entry.id] = entry
    try:
        names = sorted(p.name for p in directory.iterdir()
                       if p.is_file() and p.name != INDEX and p.name.endswith(".json"))
    except OSError:
        names = []
    for name in names:
        if name in found:
            continue
        entry = _entry_from_file(directory / name)
        if entry is not None:
            found[entry.id] = entry
    # The filename IS the order (UTC to the microsecond), so this needs
    # no clock and no file read; `timestamp` is what a row displays, not
    # what it sorts by, because a journal copied in from elsewhere
    # carries the `generated_at` of the run rather than of the filing.
    return [found[name] for name in sorted(found)]


def _read_index(directory: Path) -> dict:
    try:
        index = json.loads((directory / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return index if isinstance(index, dict) else {}


def _desk_key(desk: dict | None):
    """What groups a desk's history for pruning's bookkeeping: its serial,
    else its endpoint, else None (an entry that names no desk)."""
    if not desk:
        return None
    if desk.get("serial"):
        return ("serial", str(desk["serial"]))
    if desk.get("address"):
        return ("address",) + _endpoint(desk)
    return None


def _needed(stack: list[Entry]) -> set[str]:
    """The entries pruning may never delete: for every desk, the newest
    write still standing on it -- what `top` pops and what `desk_plan` reads
    as the plan on that desk now -- and the whole stack's newest (`top` with
    no desk)."""
    ids: set[str] = set()
    if stack:
        ids.add(stack[-1].id)
    for desk in [e.desk for e in stack if e.desk]:
        mine = [e for e in stack if on_desk(e, desk)]
        if mine:
            ids.add(mine[-1].id)
        named = [e for e in stack if e.desk is not None and same_desk(e.desk, desk)]
        if named:
            ids.add(named[-1].id)
    return ids


def _prune(ordered: list[Entry], keep: int) -> tuple[list[Entry], list[Entry]]:
    """`(kept, deleted)`, each oldest first: at most `keep` entries kept,
    chosen so the kept stack says exactly what the whole one does.

    The rule (see "Pruning" in the module docstring): delete the oldest
    entries first, in this order of preference -- writes that no longer
    stand (an entry an undo popped, an undo a redo reversed), then undos,
    then standing writes -- and never a deletion that would change the
    answer for an entry that is kept: which writes stand, the order of the
    stack, which undo reversed what, or any desk's newest standing write
    (`_needed`). Each candidate deletion is tried against the whole stack
    and taken only if all of that still holds. When nothing more can go
    safely, more than `keep` are kept rather than lose one that matters."""
    if keep <= 0 or len(ordered) <= keep:
        return list(ordered), []
    full_stack, full_reversed = _live(ordered)
    needed = _needed(full_stack)
    full_order = [e.id for e in full_stack]

    def safe(kept_ids: set[str]) -> bool:
        if not needed <= kept_ids:
            return False
        trial = [e for e in ordered if e.id in kept_ids]
        stack, reversed_now = _live(trial)
        if [e.id for e in stack] != [i for i in full_order if i in kept_ids]:
            return False
        for entry_id in kept_ids:
            by = full_reversed.get(entry_id)
            if (by if by in kept_ids else None) != reversed_now.get(entry_id):
                return False
        return True

    dead = [e for e in ordered if e.id in full_reversed]
    undos = [e for e in ordered if e.kind == "undo" and e.id not in full_reversed]
    standing = [e for e in ordered if e.kind != "undo" and e.id not in full_reversed]
    kept_ids = {e.id for e in ordered}
    for candidate in dead + undos + standing:
        if len(kept_ids) <= keep:
            break
        trial = kept_ids - {candidate.id}
        if safe(trial):
            kept_ids = trial
    kept = [e for e in ordered if e.id in kept_ids]
    deleted = [e for e in ordered if e.id not in kept_ids]
    return kept, deleted


def _trim_pruned(rows: list[dict], kept_stack: list[Entry]) -> list[dict]:
    """The `pruned` rows still worth keeping, per desk: every one from that
    desk's newest standing apply on (what a full apply would replace,
    `changes_on_desk`), and always at least the newest -- which is what
    tells `undo_floor` that something stands beneath the kept window. Once
    a kept apply on that desk sits above them all, only that one marker is
    needed."""
    groups: dict = {}
    for row in rows:
        groups.setdefault(_desk_key(row.get("desk")), []).append(row)
    out: list[dict] = []
    for key, group in groups.items():
        group.sort(key=lambda r: str(r.get("id")))
        if any(e.kind == "apply" and _desk_key(e.desk) == key for e in kept_stack):
            out.append(group[-1])
            continue
        applies = [i for i, r in enumerate(group) if r.get("kind") == "apply"]
        out.extend(group[applies[-1] if applies else 0:])
    return sorted(out, key=lambda r: str(r.get("id")))


def _rewrite_index(directory: Path, all_entries: list[Entry]) -> list[dict]:
    """Prune, then write the index. Pruning is here, with the write, so
    the index can never name a file this call has just deleted.

    Returns the rows of the journals deleted while their writes still stood
    on a desk -- the caller says so at INFO. Those rows are also kept in
    the index (`PRUNED_KEY`), with the highest change number handed out
    (`HIGHEST_CHANGE_KEY`)."""
    ordered = sorted(all_entries, key=lambda e: e.id)
    previous = _read_index(directory)
    _stack, reversed_all = _live(ordered)
    kept, deleted = _prune(ordered, keep_limit())
    for stale in deleted:
        try:
            stale.path.unlink()
        except OSError:
            pass                      # a journal we cannot delete is not a failure
    lost = [_row(e) for e in deleted if e.kind != "undo" and e.id not in reversed_all]
    old_rows = [r for r in previous.get(PRUNED_KEY) or [] if isinstance(r, dict)]
    kept_stack, _ = _live(kept)
    pruned = _trim_pruned(old_rows + lost, kept_stack)
    numbers = [n for n in ([previous.get(HIGHEST_CHANGE_KEY)]
                           + [(e.change or {}).get("number") for e in ordered])
               if isinstance(n, int)]
    payload = {
        "note": "A cache of atoo/journal_stack.py. The journals are the record; "
                "delete this and it is rebuilt by reading them -- except `pruned`, the "
                "writes still on a desk whose journals were pruned (only the newest "
                f"{keep_limit()} entries are kept), which is kept only here.",
        "entries": [_row(e) for e in kept],
    }
    if pruned:
        payload[PRUNED_KEY] = pruned
    if numbers:
        payload[HIGHEST_CHANGE_KEY] = max(numbers)
    try:
        (directory / INDEX).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass                              # the scan still works without it
    return lost


def pruned_rows(bundle_dir: str | Path) -> list[dict]:
    """The `index.json` rows for writes still on a desk whose journals were
    pruned, oldest first -- see "Pruning" in the module docstring."""
    rows = _read_index(stack_dir(bundle_dir)).get(PRUNED_KEY) or []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def _pruned_entries(bundle_dir: str | Path) -> list[Entry]:
    directory = stack_dir(bundle_dir)
    out = []
    for row in pruned_rows(bundle_dir):
        out.append(Entry(
            id=str(row["id"]), path=directory / str(row["id"]),
            kind=str(row.get("kind") or "apply"), timestamp=str(row.get("timestamp") or ""),
            summary=str(row.get("summary") or ""), mismatches=int(row.get("mismatches") or 0),
            writes=int(row.get("writes") or 0), aborted=bool(row.get("aborted")),
            desk=row.get("desk") if isinstance(row.get("desk"), dict) else None,
            change=row.get("change") if isinstance(row.get("change"), dict) else None,
            pruned=True,
        ))
    return out


def undo_floor(bundle_dir: str | Path, desk: dict | None) -> Entry | None:
    """The pruned write that stops `desk`'s top from being undone, or None.

    Undoing the top hands "what is on this desk" to the write beneath it.
    When that write is still in `journals/`, all is well. When the top is
    the last of this desk's writes still on disk and an older one was
    pruned while it still stood, the desk would be left holding a write no
    journal records: `amend` and `patch` would compare against the wrong
    plan, and nothing could undo further. So undo stops there -- at most
    `keep_limit()` steps back -- and this names the newest such pruned
    write, for the refusal."""
    stack, _popped = _live(_scan(stack_dir(bundle_dir)))
    mine = [e for e in stack if on_desk(e, desk)]
    if len(mine) != 1:
        return None
    below = [e for e in _pruned_entries(bundle_dir)
             if on_desk(e, desk) and (e.desk is None or on_desk(mine[0], e.desk))]
    return below[-1] if below else None


def pruned_target(bundle_dir: str | Path, entry: Entry) -> str | None:
    """For an undo entry: the id of the entry it reversed, when that
    entry's journal has been pruned -- so a redo (reversing this undo) would
    put writes back on the desk that no journal on the stack records. None
    otherwise."""
    if entry.kind != "undo" or not entry.undo_of:
        return None
    present = {e.id for e in _scan(stack_dir(bundle_dir))}
    return None if entry.undo_of in present else entry.undo_of


def entries(bundle_dir: str | Path) -> list[Entry]:
    """Every recorded journal, oldest first. `[]` for a bundle that has
    never had one -- a bundle from before this existed, or one nobody has
    applied yet."""
    return _scan(stack_dir(bundle_dir))


def _live(all_entries: list[Entry]) -> tuple[list[Entry], dict[str, str]]:
    """`(the stack, {entry id: the undo that reversed it})`.

    Two different questions are answered here, and keeping them apart is
    what makes the redo work:

    * **Which entries still stand on the desk** -- every kind, undos
      included, since an undo's own writes are as real as any other's.
      This is `standing` below, and it is what "has this been reversed?"
      means.
    * **Which entries are stack POSITIONS** -- apply and amend only. An
      undo is the mirror of the entry above it, never a new position, so
      it is never what the next `undo` pops (a second press
      "steps back two").

    Oldest first: everything is pushed as standing; a position is also
    pushed onto the stack; and an undo reverses its target, which drops
    that target from both. When the target is itself an undo, dropping
    it puts the entry THAT undo had reversed back on the desk -- which
    is exactly what the CLI-only redo (`atoo undo <the .undo.json>`)
    does to the console.
    """
    stack: list[Entry] = []
    standing: set[str] = set()
    reversed_by: dict[str, str] = {}
    by_id = {e.id: e for e in all_entries}

    def restore(entry: Entry) -> None:
        standing.add(entry.id)
        reversed_by.pop(entry.id, None)
        if entry.kind != "undo" and all(e.id != entry.id for e in stack):
            stack.append(entry)

    for entry in all_entries:
        restore(entry)
        if entry.kind != "undo":
            continue
        if entry.aborted:
            # A PARTIAL reversal: the connection went partway through, so
            # some of the target's writes are back and some still stand.
            # It is recorded -- it is a set of writes, and the only file
            # naming which addresses it reached -- but it does not pop the
            # target. The next `undo --show` lands on the same entry and
            # finishes it; undo's per-address guard counts what is already
            # back as `already_restored` rather than refusing it.
            continue
        target = by_id.get(entry.undo_of) if entry.undo_of else None
        if target is None or target.id not in standing:
            # An undo of a journal from outside this stack, or of one
            # that had already been reversed: nothing here to drop.
            continue
        standing.discard(target.id)
        reversed_by[target.id] = entry.id
        stack = [e for e in stack if e.id != target.id]
        if target.kind == "undo":
            back = by_id.get(target.undo_of) if target.undo_of else None
            if back is not None and back.id not in standing:
                restore(back)
    return stack, reversed_by


def listing(bundle_dir: str | Path, desk: dict | None = None) -> list[Entry]:
    """The stack as a UI draws it: **newest first**, every recorded entry
    including the undos, each carrying `is_top` and `undone_by`.

    One index read and no journal parsing, which is the point -- the
    Apply screen's row is timestamp, kind, `summary` and `mismatches`,
    and the top row is the one `atoo undo` would reverse.

    With a `desk`, `is_top` marks **that desk's** newest standing write --
    the one `atoo undo --show` pops while that desk is on the line --
    and every row says whether it is `on_this_desk`. Without one, the top
    is the whole stack's and `on_this_desk` is None.
    """
    all_entries = _scan(stack_dir(bundle_dir))
    stack, popped_by = _live(all_entries)
    mine = [e for e in stack if on_desk(e, desk)]
    top_id = mine[-1].id if mine else None
    rows = []
    for entry in all_entries:
        rows.append(Entry(
            id=entry.id, path=entry.path, kind=entry.kind, timestamp=entry.timestamp,
            summary=entry.summary, mismatches=entry.mismatches, writes=entry.writes,
            undo_of=entry.undo_of, undone_by=popped_by.get(entry.id),
            is_top=entry.id == top_id, aborted=entry.aborted, desk=entry.desk,
            on_this_desk=None if desk is None else on_desk(entry, desk),
            change=entry.change,
        ))
    rows.reverse()
    return rows


def top(bundle_dir: str | Path, desk: dict | None = None) -> Entry | None:
    """The entry `atoo undo` pops: the newest write that is still
    standing on the desk. `None` for an empty stack, and for one where
    everything has already been reversed.

    With a `desk`, the newest standing write **on that desk** -- an entry
    recorded on another desk is neither popped nor in the way. Without one,
    the whole stack's newest, which is what it was before entries named
    their desk."""
    stack, _popped = _live(_scan(stack_dir(bundle_dir)))
    mine = [e for e in stack if on_desk(e, desk)]
    return mine[-1] if mine else None


def find(bundle_dir: str | Path, journal_path: str | Path) -> Entry | None:
    """The stack entry a path names, or None if it is not one of ours.

    Matched on the `stack_entry.id` written into the journal itself, so
    a copy -- a `--journal PATH` file -- resolves to the entry it copies,
    and a copy of a journal from another bundle resolves to nothing
    rather than to whatever entry it happens to resemble.
    """
    path = Path(journal_path)
    directory = stack_dir(bundle_dir)
    all_entries = {e.id: e for e in _scan(directory)}
    if not all_entries:
        return None
    if path.parent.resolve() == directory.resolve() and path.name in all_entries:
        return all_entries[path.name]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    block = payload.get("stack_entry") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        return None
    return all_entries.get(block.get("id"))


def reversed_by(bundle_dir: str | Path, entry: Entry) -> str | None:
    """The id of the undo that reversed `entry`, or None if its writes
    still stand. Asked of any kind: an undo entry that has itself been
    undone is a redo that has already happened, and re-running it would
    reverse a reversal nobody has since made."""
    _stack, undone = _live(_scan(stack_dir(bundle_dir)))
    return undone.get(entry.id)


def positions(bundle_dir: str | Path, desk: dict | None = None) -> list[Entry]:
    """Every stack position whose writes still stand, oldest first -- the
    whole of what a journal from UNDER the stack would be reaching beneath.

    `above` answers that for an entry on the stack. This answers it for a
    journal that is not: one copied in from elsewhere, or written before
    this bundle had a stack. It is not newer than anything recorded here,
    so everything live is above it.

    With a `desk`, only the positions on that desk: what is standing on
    another console is not underneath anything on this one."""
    stack, _popped = _live(_scan(stack_dir(bundle_dir)))
    return [e for e in stack if on_desk(e, desk)]


def above(bundle_dir: str | Path, entry: Entry, desk: dict | None = None) -> list[Entry]:
    """The live entries newer than `entry`, oldest first -- what a
    reversal of `entry` would be reaching underneath.

    Empty when `entry` is the top, and empty when `entry` is not on the
    stack at all (it has already been reversed, which is a different
    thing to say about it and is said separately).

    With a `desk`, only the newer entries on that desk. `entry` itself is
    placed on the whole stack either way."""
    stack, _popped = _live(_scan(stack_dir(bundle_dir)))
    ids = [e.id for e in stack]
    if entry.id not in ids:
        return []
    return [e for e in stack[ids.index(entry.id) + 1:] if on_desk(e, desk)]


def new_entry_path(bundle_dir: str | Path, kind: str, desk: dict | None = None) -> Path:
    """Where a confirmed run in a bundle writes its journal: straight into
    `journals/`, so `record` indexes it in place (there is
    no top-level copy any more). Named for `desk`, like every entry, so a
    caller asks once the desk has answered. The directory is created;
    nothing else is written."""
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a journal kind; known: {list(KINDS)}")
    directory = stack_dir(bundle_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise JournalStackError(f"couldn't create {directory}: {exc.strerror}") from exc
    return directory / _entry_id(directory, kind, _now(), desk)


# ---------------------------------------------------------------------------
# The plan.json an amend replaced
# ---------------------------------------------------------------------------

#: The top-level key an entry carries when the run behind it replaced the
#: bundle's `plan.json`. See "The plan an amend replaced" in the module
#: docstring.
PLAN_BLOCK = "bundle_plan"


def plan_sha256(data: bytes) -> str:
    """The hash `bundle_plan` records -- of the exact bytes on disk, not of
    the parsed plan, because the question it answers is "is this still the
    FILE we wrote", and a rebuild that happens to produce an identical plan
    is still the operator's file."""
    return hashlib.sha256(data).hexdigest()


def plan_block(replaced: bytes, written: bytes) -> dict:
    """The `bundle_plan` block for a run that is about to replace
    `plan.json`'s `replaced` bytes with `written`.

    `replaced` is kept as text, not as a parsed plan, so that putting it
    back is byte-identical -- the operator's own file, formatting and all.
    `surrogateescape` round-trips any byte a file could hold through JSON,
    so even a plan.json that is not valid UTF-8 comes back unchanged."""
    return {
        "note": "The bundle's plan.json as it was before this run replaced it. "
                "`atoo undo` puts it back, but only while plan.json still "
                "hashes to written_sha256 -- a plan rebuilt since is left alone.",
        "path": PLAN,
        "replaced": replaced.decode("utf-8", "surrogateescape"),
        "replaced_sha256": plan_sha256(replaced),
        "written_sha256": plan_sha256(written),
    }


def saved_plan(entry: Entry) -> dict | None:
    """The `bundle_plan` block `entry` carries, or None when its run did not
    replace `plan.json` -- an apply, an amend that aborted or ran with no
    bundle plan to replace, an undo that left the plan alone, or any entry
    recorded.

    A block whose `replaced` text no longer hashes to `replaced_sha256` is
    treated as absent: restoring a plan we cannot vouch for is worse than
    restoring none, and the caller says so either way."""
    try:
        payload = json.loads(entry.path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    block = payload.get(PLAN_BLOCK) if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        return None
    replaced = block.get("replaced")
    if not (isinstance(replaced, str) and isinstance(block.get("written_sha256"), str)
            and isinstance(block.get("replaced_sha256"), str)):
        return None
    if plan_sha256(saved_plan_bytes(block)) != block["replaced_sha256"]:
        return None
    return block


def saved_plan_bytes(block: dict) -> bytes:
    """The replaced plan.json, exactly as it was on disk."""
    return str(block["replaced"]).encode("utf-8", "surrogateescape")


# ---------------------------------------------------------------------------
# The plan each entry left on its desk
# ---------------------------------------------------------------------------

#: The top-level key an apply or amend entry carries: the plan that run left
#: on the desk it wrote to. See "The plan each entry left on its desk" in the
#: module docstring.
DESK_PLAN_BLOCK = "desk_plan"


def desk_plan_block(plan: dict, left_by: str) -> dict:
    """The `desk_plan` block for an entry. `left_by` says which plan it is,
    in words a person reading the journal can check: "the applied plan",
    "the effective plan" (an amend), or "the plan it started from" (an
    amend that aborted partway)."""
    return {
        "note": "The plan this run left on the desk it wrote to -- what `atoo amend "
                "--show` compares against when this is that desk's newest write. The "
                "bundle's plan.json is the latest show, which may be another desk's.",
        "left_by": left_by,
        "plan": plan,
    }


def desk_plan(bundle_dir: str | Path, desk: dict | None) -> tuple[Entry | None, dict | None]:
    """`(entry, plan)`: the newest write still standing on `desk`, and the
    plan it left there -- what `amend --show` reads as "the applied plan".

    `desk`'s by `same_desk` -- the serial, so the desk's plan is found after
    it has moved networks -- and only entries that NAME a desk: a legacy
    entry that names none counts as any desk's for undo, but saying it left
    a plan on this particular console would be a guess. So:

    * `(None, None)` -- no desk, or no standing write recorded on it;
    * `(entry, None)` -- its newest write predates saved plans (or
      a legacy entry), so the caller falls back to `plan.json` and says so;
    * `(entry, plan)` -- the plan.
    """
    if desk is None:
        return None, None
    stack, _popped = _live(_scan(stack_dir(bundle_dir)))
    mine = [e for e in stack if e.desk is not None and same_desk(e.desk, desk)]
    if not mine:
        return None, None
    newest = mine[-1]
    try:
        payload = json.loads(newest.path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return newest, None
    block = payload.get(DESK_PLAN_BLOCK) if isinstance(payload, dict) else None
    plan = block.get("plan") if isinstance(block, dict) else None
    return newest, plan if isinstance(plan, dict) else None


# ---------------------------------------------------------------------------
# Changes -- what a patch entry records
# ---------------------------------------------------------------------------

#: The top-level key a patch entry carries: `{"number", "name", "text"}`.
CHANGE_BLOCK = "change"


def change_label(block: dict | None) -> str:
    """`change 3: Add horns on A 21-23`."""
    if not isinstance(block, dict):
        return "change"
    number, name = block.get("number"), block.get("name") or ""
    return f"change {number}: {name}" if number else f"change: {name}"


def next_change_number(bundle_dir: str | Path) -> int:
    """The number the next change recorded in this bundle takes: one more
    than the highest any recorded entry carries. Highest, not a count, so a
    pruned stack never hands out a number twice -- which is also why the
    index keeps the highest number ever handed out (`HIGHEST_CHANGE_KEY`):
    once the entry that carried it is pruned, nothing else remembers it."""
    numbers = [e.change.get("number") for e in _scan(stack_dir(bundle_dir)) if e.change]
    numbers += [(r.get("change") or {}).get("number") for r in pruned_rows(bundle_dir)
                if isinstance(r.get("change"), dict)]
    numbers.append(_read_index(stack_dir(bundle_dir)).get(HIGHEST_CHANGE_KEY))
    return max([n for n in numbers if isinstance(n, int)], default=0) + 1


def changes_on_desk(bundle_dir: str | Path, desk: dict | None,
                    plan_bytes: bytes | None = None) -> list[Entry]:
    """The changes a full apply to `desk` would replace, oldest first.

    Every amend and patch still standing on that desk above its newest
    standing apply (all of them, for a desk no apply has reached -- a show
    built up one change at a time). Neither writes plan.json any more, so each is on the desk and NOT in plan.json -- except an
    amend recorded before that decision, which did replace plan.json: while
    plan.json still hashes to what that amend wrote (`plan_bytes`), its
    content is in plan.json and it is left out.

    `desk` None (no console named) answers for the whole stack, as `top`
    does.

    A write whose journal was pruned while it still stood (`pruned_rows`)
    is still on the desk, so it is counted too, marked `pruned`: it is
    older than every kept write on its desk, so it goes underneath them."""
    stack, _popped = _live(_scan(stack_dir(bundle_dir)))
    mine = ([e for e in _pruned_entries(bundle_dir) if on_desk(e, desk)]
            + [e for e in stack if on_desk(e, desk)])
    applies = [i for i, e in enumerate(mine) if e.kind == "apply"]
    after = mine[applies[-1] + 1:] if applies else mine
    current = plan_sha256(plan_bytes) if plan_bytes is not None else None
    out: list[Entry] = []
    for entry in after:
        if entry.kind not in CHANGE_KINDS:
            continue
        if entry.kind == "amend" and current is not None:
            block = saved_plan(entry)
            if block is not None and block.get("written_sha256") == current:
                continue
        out.append(entry)
    return out


def replaced_changes_diagnostic(bundle_dir: str | Path, desk: dict | None):
    """The WARNING a full apply gives before it replaces changes that are
    not in plan.json (decision 7), or None when there are none.

    A WARNING, not an error: a full apply replacing ad-hoc
    changes is expected -- it is how a rebuilt show goes back on the desk --
    but it should be seen before it happens, not discovered at soundcheck.
    Shared by `atoo apply` and the Apply screen's pre-flight, so the two
    say the same thing about the same desk."""
    from atoo.diagnostics import Diagnostic, Severity

    plan = Path(bundle_dir) / PLAN
    try:
        plan_bytes = plan.read_bytes()
    except OSError:
        plan_bytes = None
    try:
        changes = changes_on_desk(bundle_dir, desk, plan_bytes)
    except (JournalStackError, OSError):
        return None
    if not changes:
        return None

    # A change `patch --promote` already kept is in instructions.md (and
    # input.csv) but not yet in plan.json -- it is until the rebuilt show
    # is built and applied -- so it is still listed, and marked, so the
    # engineer can see which ones a rebuild will bring back by itself.
    from atoo.promote import promoted_ids   # promote imports this module
    promoted = promoted_ids(bundle_dir)

    def name(entry: Entry) -> str:
        gone = " (journal pruned)" if entry.pruned else ""
        if entry.change:
            label = change_label(entry.change)
            return (f"{label} (promoted)" if entry.id in promoted else label) + gone
        return f"an amend from a rebuilt plan ({entry.id}){gone}"

    names = [name(e) for e in changes]
    shown = "; ".join(names[:6]) + (f"; and {len(names) - 6} more" if len(names) > 6 else "")
    on = f"on this desk ({describe_desk(desk)})" if desk else "on this desk"
    kept = sum(1 for e in changes if e.id in promoted)
    kept_text = (f" {kept} of them {'is' if kept == 1 else 'are'} already promoted into "
                 "instructions.md: rebuild, and apply the rebuilt plan, to put "
                 f"{'it' if kept == 1 else 'them'} in {PLAN}." if kept else "")
    return Diagnostic(
        severity=Severity.WARNING, code="apply.replaces-changes",
        # What an apply actually does to each kind of change (checked
        # against a desk, 2026-09-26): it writes the plan's own strips and
        # nothing else, so a channel a change DROPPED comes back, and one a
        # change ADDED is left on its strip -- untracked, which the next
        # patch reads as somebody else's. "Patch it back on" would place a
        # second copy of an added channel, so the fix does not say that.
        message=(f"a full apply replaces {len(changes)} change(s) {on} that are not in "
                 f"{PLAN}: {shown}. The apply writes the plan as built: a channel a change "
                 "dropped comes back, and a channel a change added stays on its strip but "
                 "is no longer tracked -- the next patch treats that strip as somebody "
                 f"else's.{kept_text}"),
        where=PLAN, source="apply",
        fix=("to keep a change for good, `atoo patch --promote <change>` puts it in "
             "instructions.md and input.csv -- then rebuild; to take an added channel off "
             "the desk, undo that change before the apply; to drop a channel again after "
             "the apply, patch the drop again."),
    )


def describe(entry: Entry) -> str:
    """One line naming an entry, for a refusal message: enough to find
    the file and to know what is in it -- and, where it was recorded, the
    desk it wrote to, since a bundle applied to two desks has two
    histories on one stack."""
    line = f"{entry.timestamp or entry.id}  {entry.kind}  {entry.summary}"
    if entry.change:
        line = (f"{entry.timestamp or entry.id}  {entry.kind}  {change_label(entry.change)}"
                f"  {entry.summary}")
    if entry.desk:
        line += f"  [on {describe_desk(entry.desk)}]"
    return line


__all__ = [
    "CHANGE_BLOCK", "CHANGE_KINDS", "DEFAULT_PORT", "DESK_PLAN_BLOCK",
    "Entry", "INDEX", "change_label", "changes_on_desk", "next_change_number",
    "replaced_changes_diagnostic",
    "JournalStackError", "KINDS", "PLAN_BLOCK", "above", "describe",
    "describe_desk", "desk_from_identity", "desk_moved", "desk_plan", "desk_plan_block",
    "desk_token", "entries", "entry_name", "find", "keep_limit", "listing",
    "new_entry_path", "on_desk", "HIGHEST_CHANGE_KEY", "PRUNED_KEY",
    "parse_entry_name", "plan_block", "plan_sha256", "positions", "pruned_rows",
    "pruned_target", "record", "reversed_by", "same_desk", "saved_plan",
    "saved_plan_bytes", "stack_dir", "summarize", "top", "undo_floor",
]
