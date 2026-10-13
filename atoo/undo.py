"""Reverse an apply from its journal -- D6's "fully reversible", FR-X.3/FR-2.5.

**Read this with `atoo/journal_stack.py`.** This module answers one
question -- *is this address still the value our run wrote?* -- and it
answers it per address, against the desk, which is the right question
and is not the whole story. It cannot see a LATER journal: if an apply
wrote ch 1-19 and an amend then added ch 21-23, every address in the
apply journal still holds what the apply put there, every one of them
passes the guard below, and reversing that journal takes the show off the
desk under the amend. An earlier change fixed that a level up, where it belongs
-- the bundle keeps one time-ordered stack of every journalled write, and
`atoo undo` pops the top of it and refuses a journal that is no
longer the top. Nothing in this module changed; what changed is which
journal it is handed.

`apply.py` has recorded `prior_value` for every address it touched since
FR-X.3 was written, captured BEFORE the write, and until this module
existed nothing read one back. The brief promised the other half twice --
D6 ("every write logged with its prior value, **fully reversible**,
independent of console snapshots") and O2's success criterion ("every
write is journalled **and reversible**") -- and `docs/user/applying.md`
admitted the gap in as many words.

## Why this exists when the engineer already saves a snapshot

The maintainer, 2026-09-23: *"after the board is patched, any good engineer will
save a snapshot so a misstep isn't catastrophic before the show starts.
Still, the project description says 'journalled writes, full undo' so we
will eventually want to include those safety features."*

That is the whole argument for building it, and it is exactly what D6's
**"independent of console snapshots"** means. A snapshot reverses **the
whole desk to a moment**. An undo reverses **our run and nothing else**.
An engineer who has made three changes since we patched does not want the
other two thrown away to get rid of ours, and a snapshot cannot tell them
apart. Nor can a snapshot help at all when nobody remembered to save one
before the run -- the journal is written whether or not anyone thought
about it.

## The load-bearing guard: only reverse where we are still the last writer

Every reversal is preceded by a read of the address's CURRENT value, and
the address is reversed **only if that value is still the one this run
wrote** (`intended_value`). If it is not, somebody has changed it after
us -- another apply, WING-Edit, a hand on the surface -- and writing
`prior_value` over that would clobber their change with a value from our
run's history that nobody asked for. Those addresses are **reported and
refused**, never reversed. This is the direct analogue of `amend.py`'s
tracked/untracked rule at address granularity: we only own what we can
still prove we own.

The comparison is `apply._values_equal`, **never `!=`**.
WING's fader/log parameters are stepped, so a value read back after a
write is the nearest step rather than the number sent: on the maintainer's
631-address A1 run three `flt/lcf` addresses sat at 100.237Hz where the
plan said 100Hz, a difference the desk cannot represent. Plain inequality
here would turn every one of those into a phantom "changed since"
refusal, and undo would be least trustworthy on exactly the float
addresses it most needs to handle.

Two outcomes sit either side of that guard and are counted apart from it:

* **`prior_value` was never readable** (`null` -- the baseline GET failed,
  and `apply` wrote anyway only in the paths where it could). There is
  nothing to restore and this module will not invent a default. Reported
  as `unreversible_no_prior`.
* **the address already holds `prior_value`**. Somebody (or a previous
  run of this command) has already put it back. Nothing to do, and
  emphatically not a refusal -- this is what makes `undo` idempotent, so
  re-running after a partial reversal finishes the job instead of
  producing a page of alarming refusals.

## What is a candidate at all

Only records a write was actually SENT for -- `match`, `mismatch`, and
`unreadable` (written, but the readback itself failed). A
`skipped_no_change` was never written and has nothing to reverse; a
`dry_run` record is a preview of a write that never happened. A journal
whose whole run was a dry run is rejected outright with an explanation,
rather than appearing to work and reversing nothing.

Records are reversed in **reverse journal order**. `apply.py`'s stage
ordering exists because some addresses depend on another having landed
first (phantom power targets the socket a channel was just patched to);
unwinding has to respect it, and the only ordering a journal carries is
the one the run used.

**Except a strip's processing, which goes selectors, values, switches.** Reverse order put a value back before its selector --
`in/set/dly` before `in/set/dlymode` -- and the selector's restore then
made the desk re-read the value it had just been given. A22 (2026-09-28)
ended with the delay at 0.1 instead of the 0.5 it started at. So the
processing rows (`preset_expand.is_processing_address`) are re-sorted by
`preset_expand.write_order` among the positions they already hold, and
every other row keeps its reverse-journal place.

## A value its selector governs

A value the run's selector change governs (`preset_expand.governs`: `dly`
under `dlymode`, `dyn/thr` under `dyn/mdl`, ...) is read for the guard
**before** that selector is restored, because the restore changes what it
reads. It passes the guard if it still reads what the run wrote, or
already reads its prior; it is then written back to its prior **after**
the selector, whatever it reads by then, and read back.

That includes a value the journal records as `skipped_no_change`, when
its selector on the same strip was written by the run. A journal from
before the fix (A22's among them) skipped such a value against a baseline
read under the old selector, and its `prior_value` -- recorded for
skipped rows too -- is the reading the strip had before the run. Undo
writes it after the selector and says so at INFO, naming the addresses:
the apply never wrote them, but the run changed them all the same.

## The reversal is a write like any other

It goes through `apply._write_target` (the same set_node/set_param path
choice), is **read back** and proved, consults the same drained-datagram
machinery for the unacked path's read-after-write race
(`apply._late_confirmation`, `apply._recheck_disagreements`),
and is **journalled** -- as an ordinary apply journal, via
`apply._write_journal`. That last point is what makes an undo undoable:
`atoo undo <the undo's own journal>` is a redo, and there is no
separate mechanism for it.

On the stack that journal is kept but is **never a step
forward**: it pops the entry it reversed rather than becoming a new
position, so a second undo steps back two rather than redoing the first
(the maintainer's call). That is less a rule than a description of the file --
`_restore` below deliberately inverts `prior_value` and `intended_value`,
so an undo journal is the *mirror* of the entry above it. It is kept
because it is the only file carrying `_refusal_record` rows for the
addresses this run declined to touch (`refused_changed_since`,
`unreversible_no_prior`, `already_restored`), which exist nowhere else.

## A journal from a run that aborted

`apply` stops the whole run on a socket-level failure and
journals only the addresses it got through. Such a journal is partial by
construction and is the most important one to be able to reverse -- it is
the one nobody planned for. Nothing special is needed: the records that
are there are the writes that happened, and this module reverses those.
It goes on the stack like any other, which is why `cli.apply_cmd` records
it **before** it gives up on the aborted run rather than after.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from atoo import preset_expand
from atoo.apply import (
    ApplyResult,
    WriteRecord,
    WriteTarget,
    _const,
    _extract_reply_value,
    _late_confirmation,
    _PendingCheck,
    _recheck_disagreements,
    _reply_mark,
    _values_equal,
    _write_journal,
    _write_target,
)

#: Journal statuses for which a write was actually SENT to the console --
#: the only records that have anything to reverse. `mismatch` is in here
#: because the write went out: whether it landed is what the readback
#: disagreed about, and the guard below settles it by reading the desk
#: now rather than by trusting the verdict recorded then. `dry_run`,
#: `skipped_no_change` and `unreadable_skipped` are all "nothing was
#: sent" and are counted out.
WRITTEN_STATUSES = ("match", "mismatch", "unreadable")

#: Object prefixes `--only` understands, mapped to the address root each
#: one owns. Deliberately the same `bank:number` spelling `amend`'s
#: `--allow-strip` and the journal's own `scope.strips` use.
_ONLY_BANKS = {
    "ch": "/ch",
    "aux": "/aux",
    "bus": "/bus",
    "main": "/main",
    "mtx": "/mtx",
    "dca": "/dca",
}

_ONLY_RE = re.compile(r"^([a-z]+):(\d+)$")


class UndoError(Exception):
    """A journal that cannot be undone, with a message fit to print."""


@dataclass
class UndoStep:
    """One journalled write and what this run decided to do about it.

    `applied_value` is the journal's `intended_value` -- what our run put
    there, and therefore what the desk must still hold for the reversal
    to be ours to make. `restore_value` is its `prior_value`, what goes
    back."""

    address: str
    description: str
    value_type: str
    restore_value: object
    applied_value: object
    journal_status: str
    verdict: str
    current_value: object = None
    detail: str | None = None
    #: The journal row this step produced, for the undo's own journal.
    #: None for a step that produced no row (there are none today; the
    #: field exists so a future verdict can opt out).
    record: WriteRecord | None = None


#: Verdicts, in the order `summary()` reports them.
REVERSED = "reversed"
WOULD_REVERSE = "would_reverse"
ALREADY_RESTORED = "already_restored"
REFUSED_CHANGED = "refused_changed_since"
REFUSED_UNREADABLE = "refused_unreadable"
UNREVERSIBLE_NO_PRIOR = "unreversible_no_prior"
REVERSAL_MISMATCH = "reversal_mismatch"
REVERSAL_UNREADABLE = "reversal_unreadable"


@dataclass
class UndoResult:
    dry_run: bool
    source_journal: str
    steps: list[UndoStep] = field(default_factory=list)
    journal_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    #: Journal records that were never written (`skipped_no_change`,
    #: `dry_run`, `unreadable_skipped`) and so have nothing to reverse.
    #: A count, not a list: on a 631-address run most of a second apply's
    #: journal is `skipped_no_change` and naming them all buries the
    #: addresses that matter.
    never_written: int = 0
    #: Written records that `--only` (or the journal's own scope) left
    #: out of this run.
    not_selected: int = 0
    #: Which selectors decided `not_selected`, and where they came from --
    #: printed in the preview so "why is this address not in the list"
    #: is answerable without re-reading the command line.
    selection: list[str] = field(default_factory=list)
    selection_source: str = "the whole journal"
    aborted: bool = False
    abort_reason: str | None = None
    replies_discarded: int = 0
    replies_used: int = 0

    def of(self, *verdicts: str) -> list[UndoStep]:
        return [s for s in self.steps if s.verdict in verdicts]

    @property
    def reversed_steps(self) -> list[UndoStep]:
        return self.of(REVERSED)

    @property
    def refused(self) -> list[UndoStep]:
        return self.of(REFUSED_CHANGED, REFUSED_UNREADABLE)

    @property
    def unreversible(self) -> list[UndoStep]:
        return self.of(UNREVERSIBLE_NO_PRIOR)

    @property
    def failed(self) -> list[UndoStep]:
        """Reversals that were sent and did not prove out. A reversal
        that did not land is a value that did not land."""
        return self.of(REVERSAL_MISMATCH, REVERSAL_UNREADABLE)

    def preview(self) -> str:
        """Per address, what would be restored and what would be refused
        -- BEFORE anything is armed. A refusal list that only turns up
        after the write has happened is worthless."""
        lines = [f"Undo of {self.source_journal}"]
        if self.selection:
            lines.append(f"  selection: {', '.join(self.selection)} ({self.selection_source})")
        for step in self.steps:
            if step.verdict in (WOULD_REVERSE, REVERSED):
                lines.append(
                    f"  RESTORE   {step.address}: {step.applied_value!r} -> {step.restore_value!r}"
                    f"   ({step.description})")
            elif step.verdict == ALREADY_RESTORED:
                lines.append(
                    f"  NO CHANGE {step.address}: already back at {step.restore_value!r}")
            elif step.verdict == REFUSED_CHANGED:
                lines.append(
                    f"  REFUSE    {step.address}: we wrote {step.applied_value!r}, the console "
                    f"now reads {step.current_value!r} -- changed since, not ours to reverse")
            elif step.verdict == REFUSED_UNREADABLE:
                lines.append(
                    f"  REFUSE    {step.address}: could not read the current value "
                    f"({step.detail}), so there is no way to tell whether it is still ours")
            elif step.verdict == UNREVERSIBLE_NO_PRIOR:
                lines.append(
                    f"  NO PRIOR  {step.address}: the apply never read a prior value here, "
                    "so there is nothing to restore")
            elif step.verdict == REVERSAL_MISMATCH:
                lines.append(
                    f"  DID NOT LAND {step.address}: wrote {step.restore_value!r}, console "
                    f"reports {step.current_value!r}")
            elif step.verdict == REVERSAL_UNREADABLE:
                lines.append(
                    f"  DID NOT LAND {step.address}: wrote {step.restore_value!r}, could not "
                    f"read it back ({step.detail})")
        return "\n".join(lines)

    def summary(self, detail: bool = True) -> str:
        """The line an engineer reads: "41 reversed, 2 refused (changed
        since), 1 unreversible (no prior value)".

        `detail=False` drops the per-address lines beneath it, for a
        caller that has just printed `preview()` and would only be saying
        the same addresses twice."""
        parts = []
        if self.dry_run:
            parts.append(f"{len(self.of(WOULD_REVERSE))} would be reversed")
        else:
            parts.append(f"{len(self.reversed_steps)} reversed")
        if self.failed:
            parts.append(f"{len(self.failed)} did NOT land")
        if self.of(ALREADY_RESTORED):
            parts.append(f"{len(self.of(ALREADY_RESTORED))} already back")
        if self.of(REFUSED_CHANGED):
            parts.append(f"{len(self.of(REFUSED_CHANGED))} refused (changed since)")
        if self.of(REFUSED_UNREADABLE):
            parts.append(f"{len(self.of(REFUSED_UNREADABLE))} refused (unreadable)")
        if self.unreversible:
            parts.append(f"{len(self.unreversible)} unreversible (no prior value)")
        head = "DRY RUN: " if self.dry_run else "UNDONE: "
        lines = [head + ", ".join(parts) + "."]
        tail = []
        if self.never_written:
            tail.append(f"{self.never_written} journal record(s) were never written")
        if self.not_selected:
            tail.append(f"{self.not_selected} not selected")
        if tail:
            lines.append("  (" + "; ".join(tail) + ")")
        if not detail:
            return "\n".join(lines)
        if self.aborted:
            lines.insert(0, f"ABORTED: lost the connection to the console ({self.abort_reason}). "
                            "Everything reversed before that point is journalled below.")
        for step in self.failed:
            lines.append(f"  DID NOT LAND {step.address}: wrote {step.restore_value!r}, "
                         f"console reports {step.current_value!r}")
        for step in self.of(REFUSED_CHANGED):
            lines.append(f"  REFUSED {step.address}: we wrote {step.applied_value!r}, the console "
                         f"now reads {step.current_value!r}")
        for step in self.of(REFUSED_UNREADABLE):
            lines.append(f"  REFUSED {step.address}: could not read the current value "
                         f"({step.detail})")
        for step in self.unreversible:
            lines.append(f"  NO PRIOR VALUE {step.address}: nothing to restore")
        if self.warnings:
            lines.append(f"  {len(self.warnings)} warning(s), listed below")
        return "\n".join(lines)


def load_journal(path: str) -> dict:
    """Read a journal, or raise `UndoError` with a message fit to print.

    A journal from a dry run is refused HERE rather than producing an
    empty, successful-looking undo: "0 reversed" against a preview reads
    exactly like "0 reversed" against a run somebody else has already
    undone, and they call for completely different next steps."""
    try:
        with open(path, encoding="utf-8") as f:
            journal = json.load(f)
    except OSError as exc:
        raise UndoError(f"couldn't read journal {path!r}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise UndoError(f"journal {path!r} is not valid JSON: {exc}") from exc
    if not isinstance(journal, dict) or not isinstance(journal.get("writes"), list):
        raise UndoError(
            f"{path!r} is not an apply journal -- expected a JSON object with a 'writes' list "
            "(the file `atoo apply --confirm` writes).")
    if journal.get("dry_run"):
        raise UndoError(
            f"{path!r} is the journal of a DRY RUN: nothing was written, so there is nothing to "
            "reverse. The journal of a real apply is the one written when you passed --confirm.")
    return journal


def journal_records(journal: dict) -> list[WriteRecord]:
    """The journal's `writes` as `WriteRecord`s.

    `value_type` defaults to `"s"` for a journal written before issue
    #142 added the field: a string compares exactly, which is the
    conservative direction -- a float address in such a journal is more
    likely to be refused than wrongly reversed."""
    records = []
    for row in journal["writes"]:
        records.append(WriteRecord(
            address=row["address"],
            description=row.get("description", ""),
            value_type=row.get("value_type", "s"),
            method=row.get("method"),
            ack=row.get("ack"),
            prior_value=row.get("prior_value"),
            intended_value=row.get("intended_value"),
            readback_value=row.get("readback_value"),
            status=row.get("status", ""),
            timestamp=row.get("timestamp", ""),
            readback_source=row.get("readback_source"),
            forced_by=row.get("forced_by"),
        ))
    return records


def _is_selector_change(record: WriteRecord) -> bool:
    """A record of a selector our run actually changed -- the only kind
    whose restore makes the desk re-read the values it governs."""
    return (preset_expand.write_order(record.address) == preset_expand.SELECTOR
            and record.status in WRITTEN_STATUSES
            and not _values_equal(record.value_type, record.prior_value, record.intended_value,
                                   record.address))


def _restore_order(candidates: list[WriteRecord]) -> list[WriteRecord]:
    """Reverse journal order, with a strip's processing rows re-sorted by
    `preset_expand.write_order` -- selectors, then values, then switches
    -- among the positions they hold. Every other row keeps
    its place. Stable within a class, so two values keep their reverse
    journal order."""
    ordered = list(reversed(candidates))
    slots = [i for i, r in enumerate(ordered)
             if preset_expand.is_processing_address(r.address)]
    rows = sorted((ordered[i] for i in slots),
                  key=lambda r: preset_expand.write_order(r.address))
    for i, r in zip(slots, rows):
        ordered[i] = r
    return ordered


def parse_only(selectors: str) -> list[str]:
    """`--only ch:21,ch:22` / `--only /io/in/A/5` -> address roots.

    Two spellings, both of which a journal already contains: the
    `bank:number` strip label `amend --allow-strip` and the journal's own
    `scope.strips` use, and a bare address prefix for everything that has
    no strip label (a physical socket, a send, a card bay). An unknown
    bank is an error naming what is understood, never a silent match of
    nothing -- "it reversed nothing and said so cheerfully" is the one
    outcome a scoped undo must not have."""
    roots = []
    for raw in selectors.split(","):
        part = raw.strip()
        if not part:
            continue
        if part.startswith("/"):
            roots.append(part.rstrip("/"))
            continue
        match = _ONLY_RE.match(part.lower())
        if match is None or match.group(1) not in _ONLY_BANKS:
            raise UndoError(
                f"--only {part!r}: expected a strip label like 'ch:21' "
                f"({'/'.join(sorted(_ONLY_BANKS))}) or an address prefix like '/io/in/A/5'.")
        roots.append(f"{_ONLY_BANKS[match.group(1)]}/{int(match.group(2))}")
    if not roots:
        raise UndoError("--only was given nothing to select.")
    return roots


def address_under(address: str, roots: list[str]) -> bool:
    return any(address == root or address.startswith(root + "/") for root in roots)


def scope_roots(journal: dict) -> list[str]:
    """The address roots an amend journal's own `scope` records.

    `ApplyResult.scope` is `{"strips": [...], "grants": {base: reason}}`,
    and it is the **grants** that are the natural default selection, not
    the strips. An amend that adds `ch:21` also writes the socket it is
    patched to (`/io/in/A/5/...`), which is granted but is not under any
    strip label -- defaulting to `strips` would quietly leave the socket
    patched while claiming the run had been reversed."""
    scope = journal.get("scope")
    if not isinstance(scope, dict):
        return []
    grants = scope.get("grants")
    if not isinstance(grants, dict) or not grants:
        return []
    return [str(base).rstrip("/") for base in grants]


#: What each long stretch of `undo_from_journal` is called on the progress
#: line.
EARLY_PHASE = "reading the values a selector governs, before undoing"
PREVIEW_PHASE = "reading the desk for the undo preview"
RESTORE_PHASE = "putting back, reading each back"


class _ConsoleReader:
    """Reads the desk. `console` is the same structural duck type
    `apply_plan` takes -- get/set_param/set_node, plus the optional
    late-reply trio."""

    def __init__(self, console):
        self.console = console
        # A preview's reads, asked ahead with several in
        # flight. `_ahead` is what may be asked early, in walk order;
        # `_got` holds the replies until the walk reaches them.
        self._ahead: dict[str, int] = {}
        self._order: list[str] = []
        self._got: dict[str, object] = {}

    def read_ahead(self, addresses) -> None:
        """Let `current` ask for these addresses ahead of the walk -- a
        window of requests in flight at a time, the next batch fetched
        when the walk reaches one not yet asked. Only for a preview, which
        writes nothing, so a value read early is the value it would have
        read on reaching it; and only with a window above 1, so a window
        of 1 asks in exactly the order it always did."""
        if getattr(self.console, "window", 1) <= 1:
            return
        for address in addresses:
            if address not in self._ahead:
                self._ahead[address] = len(self._order)
                self._order.append(address)

    def _fetch_from(self, address: str) -> None:
        from atoo import console as osc

        start = self._ahead[address]
        batch = [a for a in self._order[start:start + 4 * self.console.window]
                 if a in self._ahead]
        for asked in batch:
            del self._ahead[asked]
        for asked, reply in osc.read_in_windows(self.console, batch):
            self._got[asked] = reply

    def current(self, address: str, value_type: str):
        if address in self._ahead:
            self._fetch_from(address)
        reply = (self._got.pop(address) if address in self._got
                 else self.console.get(address))
        if reply is not None and reply.is_socket_error:
            raise OSError(reply.args[0] if reply.args else "socket error")
        return _extract_reply_value(reply, value_type, address)


class _StateReader:
    """Reads a saved capture instead of a desk -- `audit --state`'s
    address->value shape, so an undo can be REVIEWED at the kitchen table
    with no console on the line.

    No index correction is applied to what it reads:
    `audit.read_console_state` has already run `correct_readback_index`
    over every value it writes into such a file, so
    correcting again here would read `col` and `in/conn/in` one too high.

    Preview only. `undo_from_journal` refuses to arm against one, because
    a value read from a file says nothing about what the desk holds now,
    which is the entire question the guard asks."""

    def __init__(self, values: dict):
        self.values = values

    def current(self, address: str, value_type: str):
        if address not in self.values:
            return None, "no_reply"
        value = self.values[address]
        if value_type == "f" and value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                pass
        return value, None


def undo_from_journal(
    journal: dict,
    console=None,
    *,
    dry_run: bool = True,
    only: list[str] | None = None,
    journal_path: str | None = None,
    state: dict | None = None,
    source_journal: str = "<journal>",
    phases=None,
) -> UndoResult:
    """Reverse the writes a journal records, or preview the reversal.

    `dry_run` defaults to True and there is **no second arming control**
    (OPTIONS-H: one screen writes). `state` gives an offline preview from
    a saved capture and may only be used with `dry_run=True`.

    `only` is a list of address roots (see `parse_only`). When it is None
    and the journal carries an amend's `scope`, that scope's grants are
    the default selection -- what the run was ALLOWED to touch is the
    right default for what an undo of it may touch.

    See the module docstring for the guard, the candidate statuses and
    the ordering. The result's own journal (`journal_path`) is an
    ordinary apply journal, so running this function over it is a redo.

    `phases` (a `progress.Phases`) is told of each long stretch
    as it happens: the early read of the values a selector governs
    (`EARLY_PHASE`), the main pass (`PREVIEW_PHASE` reads only; `RESTORE_PHASE`
    reads, writes and reads back), and apply's second look at what
    disagreed. None is silent, and it changes nothing that is read or written.
    """
    from atoo.progress import NO_PHASES

    phases = NO_PHASES if phases is None else phases
    if state is not None and not dry_run:
        raise UndoError("--state is a preview against a saved capture; it cannot arm a write. "
                        "Pass --console with --confirm to actually reverse anything.")
    if state is None and console is None:
        raise UndoError("undo needs either a console to read and write, or --state for a preview.")
    reader = _StateReader(state) if state is not None else _ConsoleReader(console)

    selection_source = "the whole journal"
    roots = only
    if roots is None:
        roots = scope_roots(journal) or None
        if roots:
            selection_source = "this journal's own scope"
    else:
        selection_source = "--only"

    result = UndoResult(dry_run=dry_run, source_journal=source_journal,
                        journal_path=journal_path,
                        selection=list(roots) if roots else [],
                        selection_source=selection_source)

    records = journal_records(journal)
    selected = [r for r in records
                if roots is None or address_under(r.address, roots)]
    selector_changes = [r for r in selected if _is_selector_change(r)]

    def governing(record: WriteRecord) -> WriteRecord | None:
        for selector in selector_changes:
            if preset_expand.governs(selector.address, record.address):
                return selector
        return None

    candidates = []
    # address -> the selector record whose restore re-reads it.
    governed_by: dict[str, WriteRecord] = {}
    # Old-journal rows: skipped by the apply, but under a selector it wrote.
    skipped_governed: set[int] = set()
    for record in records:
        in_scope = roots is None or address_under(record.address, roots)
        selector = governing(record) if in_scope else None
        if record.status not in WRITTEN_STATUSES:
            if record.status == "skipped_no_change" and selector is not None:
                skipped_governed.add(id(record))
            else:
                result.never_written += 1
                continue
        elif not in_scope:
            result.not_selected += 1
            continue
        if selector is not None:
            governed_by[record.address] = selector
        candidates.append(record)

    # Reverse order: apply.py's STAGE_* ordering exists because some
    # addresses depend on another having landed first, and unwinding has
    # to undo the last thing first for the same reason -- with a strip's
    # processing put back selectors first (see the module docstring).
    candidates = _restore_order(candidates)

    pending: list[_PendingCheck] = []
    abort_reason: str | None = None

    # A governed value's guard is read BEFORE anything is
    # restored, because restoring its selector changes what it reads.
    early: dict[str, tuple[object, str | None]] = {}
    early_wanted = [r for r in candidates
                    if r.address in governed_by and r.prior_value is not None]
    phase = phases.start(EARLY_PHASE, len(early_wanted)) if early_wanted else None
    for record in early_wanted:
        phase.start_address(record.address)
        try:
            early[record.address] = reader.current(record.address, record.value_type)
        except OSError as exc:
            abort_reason = str(exc)
            break
        phase.finish_address(answered=early[record.address][1] is None)
    if phase is not None:
        phase.finish()
    steps_by_address: dict[str, UndoStep] = {}
    restored_after_selector: list[str] = []

    # One step per candidate, done when the next one starts.
    walk = candidates if abort_reason is None else []
    if dry_run and hasattr(reader, "read_ahead"):
        # The reads the preview's walk makes for itself (a
        # governed value's comes from `early`, or from the walk's own
        # serial read), asked ahead several at a time.
        reader.read_ahead(r.address for r in walk
                          if r.prior_value is not None and r.address not in governed_by)
    phase = (phases.start(PREVIEW_PHASE if dry_run else RESTORE_PHASE, len(walk),
                          writes=not dry_run) if walk else None)
    in_flight = False
    for record in walk:
        if in_flight:
            phase.finish_address(answered=True)
        phase.start_address(record.address)
        in_flight = True
        selector = governed_by.get(record.address)
        selector_step = steps_by_address.get(selector.address) if selector is not None else None
        after_selector = selector_step is not None and selector_step.verdict in (
            WOULD_REVERSE, REVERSED, REVERSAL_MISMATCH, REVERSAL_UNREADABLE)
        if id(record) in skipped_governed and not after_selector:
            # Its selector is not being put back (refused, already back,
            # or out of the selection), so nothing re-reads this value:
            # it is the ordinary never-written row it always was.
            result.never_written += 1
            continue
        if after_selector:
            # `.get`: a value with no prior (it was not on the desk under
            # the old selector) has no early read, and `_restore_governed`
            # answers it as unreversible without looking at one.
            _restore_governed(record, selector, early.get(record.address, (None, None)),
                              console, dry_run,
                              result, pending, restored_after_selector,
                              skipped=id(record) in skipped_governed)
            if result.aborted:
                abort_reason = result.abort_reason
                break
            continue

        step = UndoStep(
            address=record.address, description=record.description,
            value_type=record.value_type, restore_value=record.prior_value,
            applied_value=record.intended_value, journal_status=record.status,
            # The verdict for the one case decided without reading the
            # desk at all; every other branch below overwrites it.
            verdict=UNREVERSIBLE_NO_PRIOR,
        )
        result.steps.append(step)

        if record.prior_value is None:
            # Never readable before the write, so there is nothing to put
            # back and this module will not invent a default (the issue's
            # own instruction, and D6's: a journal that could not record
            # the prior value cannot promise reversibility for it).
            continue

        try:
            current, read_error = reader.current(record.address, record.value_type)
        except OSError as exc:
            abort_reason = str(exc)
            result.steps.remove(step)
            break

        step.current_value = current
        steps_by_address[record.address] = step
        if read_error is not None:
            step.verdict = REFUSED_UNREADABLE
            step.detail = read_error
            continue

        if _values_equal(record.value_type, current, record.prior_value, record.address):
            # Already back where it started -- by a previous run of this
            # command, by somebody at the desk, or because the write
            # never actually landed. Not a refusal, and this is what
            # makes undo safe to re-run after a partial one.
            step.verdict = ALREADY_RESTORED
            if record.status == "mismatch":
                step.detail = "the apply journal already recorded this write as a mismatch"
            continue

        # THE GUARD. `_values_equal`, never `!=`: the desk
        # answers a stepped float with the nearest step, so exact
        # inequality would refuse the float addresses this most needs to
        # handle -- three flt/lcf addresses at 100.237Hz against a plan
        # asking for 100Hz on one real 631-address run.
        if not _values_equal(record.value_type, current, record.intended_value, record.address):
            step.verdict = REFUSED_CHANGED
            continue

        if dry_run:
            step.verdict = WOULD_REVERSE
            continue

        target = WriteTarget(
            address=record.address, value_type=record.value_type,
            description=f"undo: {record.description}",
            compute_value=_const(record.prior_value), stage=0,
        )
        _written, pend, abort_reason = _restore(console, target, record, step)
        if abort_reason is not None:
            # The connection died on this address. Mirror `apply_plan`:
            # drop the step rather than record a verdict for a write
            # whose fate is genuinely unknown -- `abort_reason` says so
            # in words, and inventing "reversed" or "did not land" here
            # would be a claim nothing supports.
            result.steps.remove(step)
            break
        if pend is not None:
            pending.append(pend)

    if in_flight:
        phase.finish_address(answered=True)
    if phase is not None:
        phase.finish()

    if restored_after_selector:
        verb = "would be" if dry_run else "were"
        result.warnings.append(
            f"INFO {len(restored_after_selector)} value(s) {verb} put back after the selector "
            "that governs them, although the apply journal records them as skipped_no_change: "
            "the apply changed their selector, so the desk re-read them, and this journal "
            "was written by an older Atoo, which did not write such values. Restored to the prior value "
            f"the journal recorded for each: {', '.join(restored_after_selector)}")

    if pending and abort_reason is None:
        warning = _recheck_disagreements(console, pending, phases=phases)
        if warning is not None:
            result.warnings.append(warning)
        for pend in pending:
            _settle(pend, result)

    result.aborted = abort_reason is not None
    result.abort_reason = abort_reason
    if console is not None:
        result.replies_discarded = getattr(console, "replies_discarded", 0)
        result.replies_used = getattr(console, "replies_used", 0)

    if journal_path is not None and not dry_run:
        # An ordinary apply journal, written by apply's own writer: that
        # is what makes the undo undoable, and a redo needs no mechanism
        # of its own. The refusals go in it too -- a record of what this
        # run declined to touch is exactly as load-bearing as a record of
        # what it wrote, and their statuses are outside WRITTEN_STATUSES
        # so a redo reads them as "nothing was sent here".
        rows = []
        for step in result.steps:
            if step.record is None:
                step.record = _refusal_record(step)
            rows.append(step.record)
        _write_journal(journal_path, ApplyResult(
            dry_run=False, writes=rows,
            journal_path=journal_path, warnings=result.warnings,
            aborted=result.aborted, abort_reason=result.abort_reason,
            replies_discarded=result.replies_discarded, replies_used=result.replies_used,
            scope={"undo_of": source_journal,
                   **({"selection": result.selection} if result.selection else {})},
        ))
    return result


def _restore_governed(record: WriteRecord, selector: WriteRecord, early, console,
                      dry_run: bool, result: UndoResult, pending: list,
                      restored_after_selector: list[str], *, skipped: bool) -> None:
    """Put back one value its selector governs, after that selector has
    been restored -- see the module docstring.

    `early` is the `(value, error)` read BEFORE any restore. The guard
    runs on it: the value must still read what the run wrote, or already
    read its prior (for a skipped row the two are the same value). It is
    then written whatever the desk reads now, since the selector's
    restore has just made the desk re-read it. `skipped` marks an
    old-journal row the apply never wrote."""
    step = UndoStep(
        address=record.address, description=record.description,
        value_type=record.value_type, restore_value=record.prior_value,
        applied_value=record.intended_value, journal_status=record.status,
        verdict=UNREVERSIBLE_NO_PRIOR,
    )
    result.steps.append(step)
    if record.prior_value is None:
        return
    current, read_error = early
    step.current_value = current
    if read_error is not None:
        step.verdict = REFUSED_UNREADABLE
        step.detail = read_error
        return
    if not (_values_equal(record.value_type, current, record.intended_value, record.address)
            or _values_equal(record.value_type, current, record.prior_value, record.address)):
        step.verdict = REFUSED_CHANGED
        return
    step.detail = f"put back after its selector {selector.address}"
    if skipped:
        restored_after_selector.append(record.address)
    if dry_run:
        step.verdict = WOULD_REVERSE
        return
    target = WriteTarget(
        address=record.address, value_type=record.value_type,
        description=f"undo: {record.description}",
        compute_value=_const(record.prior_value), stage=0,
    )
    _written, pend, abort_reason = _restore(console, target, record, step)
    if abort_reason is not None:
        result.steps.remove(step)
        result.aborted = True
        result.abort_reason = abort_reason
        return
    if pend is not None:
        pending.append(pend)


def _refusal_record(step: UndoStep) -> WriteRecord:
    """A journal row for an address this run did NOT write. `status`
    carries the verdict verbatim, which is outside `WRITTEN_STATUSES`, so
    reading this journal back as a redo correctly finds nothing to do
    here."""
    return WriteRecord(
        address=step.address, description=f"undo: {step.description}",
        value_type=step.value_type, method=None, ack=None,
        prior_value=step.current_value, intended_value=step.restore_value,
        readback_value=step.current_value, status=step.verdict,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _restore(console, target: WriteTarget, record: WriteRecord, step: UndoStep):
    """Send one reversal and prove it, exactly as `apply_plan`'s loop
    proves a write: readback, then the drained-datagram consultation for
    the unacked path's read-after-write race, then -- for
    anything still disagreeing -- a `_PendingCheck` for the deferred
    re-read at the end of the run. The logic is imported from `apply`,
    not copied: `_write_target`, `_late_confirmation`,
    `_extract_reply_value` and `_values_equal` are the same functions
    `apply_plan` calls.

    Returns `(journal row, pending check or None, abort reason or None)`.
    """
    value = record.prior_value
    mark = _reply_mark(console)
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        method, ack = _write_target(console, target, value)
    except OSError as exc:
        return None, None, str(exc)

    readback_reply = console.get(target.address)
    readback_value, readback_error = _extract_reply_value(
        readback_reply, target.value_type, target.address)
    readback_source = None
    disagrees = readback_error is not None or not _values_equal(
        target.value_type, readback_value, value, target.address)
    if disagrees and not (readback_reply is not None and readback_reply.is_socket_error):
        late = _late_confirmation(console, target, value, mark)
        if late is not None:
            readback_value, readback_error = _extract_reply_value(
                late, target.value_type, target.address)
            readback_reply = late
            readback_source = "late_reply"

    if readback_reply is not None and readback_reply.is_socket_error:
        return None, None, (
            f"{readback_reply.args[0] if readback_reply.args else 'socket error'} "
            f"(the reversal of {target.address} was sent -- whether it landed is unknown)")

    if readback_error is not None:
        status = "unreadable"
    elif _values_equal(target.value_type, readback_value, value, target.address):
        status = "match"
    else:
        status = "mismatch"

    written = WriteRecord(
        address=target.address, description=target.description, value_type=target.value_type,
        method=method, ack=ack,
        # The undo's own journal is a journal of ITS writes: what the
        # address held before THIS write (the value the apply put there)
        # is its prior_value, and the value being restored is its
        # intended_value. That is precisely what makes running `undo`
        # over this file a redo of the original apply.
        prior_value=record.intended_value, intended_value=value,
        readback_value=readback_value, status=status, timestamp=timestamp,
        readback_source=readback_source,
    )
    step.record = written
    step.current_value = readback_value
    step.verdict = {"match": REVERSED, "mismatch": REVERSAL_MISMATCH,
                    "unreadable": REVERSAL_UNREADABLE}[status]
    if status == "unreadable":
        step.detail = readback_error
    pending = None
    if status in ("mismatch", "unreadable"):
        pending = _PendingCheck(record=written, target=target, intended_value=value, mark=mark)
    return written, pending, None


def _settle(pend: _PendingCheck, result: UndoResult) -> None:
    """Carry `_recheck_disagreements`'s verdict back onto the step.

    That function rewrites the RECORD (it is apply's own machinery and
    knows nothing about undo steps), and only ever in the direction
    mismatch/unreadable -> match, so this re-reads the record rather than
    re-deciding anything."""
    for step in result.steps:
        if step.record is pend.record and pend.record.status == "match":
            step.verdict = REVERSED
            step.current_value = pend.record.readback_value
            step.detail = None
