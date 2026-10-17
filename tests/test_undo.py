"""Tests for atoo/undo.py -- reversing an apply from its journal.

No console is available (or wanted): `FakeConsole` from test_apply serves
canned replies and records every write, which is exactly enough to test
the thing that matters here -- **that an address somebody else has
changed since our write is refused rather than reversed**.

Two of these tests are mutation-checked, and say so at their own
docstrings: the guard itself (`test_an_address_changed_by_somebody_else_
is_refused`) and the choice of `_values_equal` over `!=` for it
(`test_a_float_within_stepped_tolerance_is_not_refused`). A test that
still passes when the behaviour it names is broken is not a test, and
both were run against a deliberately broken `undo.py` before being
committed -- see the PR body for what was mutated and what failed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import undo as undo_engine
from atoo.apply import WriteRecord, apply_plan
from atoo.console import OscReply
from atoo.undo import (
    ALREADY_RESTORED,
    REFUSED_CHANGED,
    REFUSED_UNREADABLE,
    REVERSAL_MISMATCH,
    REVERSED,
    UNREVERSIBLE_NO_PRIOR,
    WOULD_REVERSE,
    UndoError,
    load_journal,
    parse_only,
    undo_from_journal,
)
from tests.test_apply import FakeConsole, compiled

CONSOLE_RUNS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "console-runs"
#: A real 707-address run off the maintainer's Compact, 2026-09-22 -- the first
#: journal carrying `value_type`, which is what makes it
#: usable as an undo fixture at all. Never modified by these tests; it is
#: an irreplaceable hardware capture and is only ever read.
REAL_JOURNAL = CONSOLE_RUNS / "2026-09-22-2136" / "A1-apply-journal.json"


def row(address, prior, intended, *, value_type="s", status="match", readback=...,
        description="a write"):
    return {
        "address": address, "description": description, "value_type": value_type,
        "method": "node", "ack": "OK",
        "prior_value": prior, "intended_value": intended,
        "readback_value": intended if readback is ... else readback,
        "status": status, "timestamp": "2026-09-23T00:00:00+00:00", "readback_source": None,
    }


def journal(*rows, dry_run=False, scope=None):
    j = {"generated_at": "2026-09-23T00:00:00+00:00", "dry_run": dry_run,
         "writes": list(rows), "warnings": [], "replies_discarded": 0, "replies_used": 0}
    if scope is not None:
        j["scope"] = scope
    return j


def raw(address, value):
    """The value a real console's wire reply carries for `value`.

    `apply._extract_reply_value` corrects a GET reply for the handful of
    addresses whose reply is one less than the value their SET takes
    (`col`, `in/conn/in`). `FakeConsole` stores and returns
    what it was given, so a fixture seeded straight from a journal's
    already-corrected `readback_value` would be corrected a second time
    and read one too high. This undoes the correction so the fake behaves
    like the desk the journal came off.
    """
    from atoo.console_facts import readback_index_offset

    offset = readback_index_offset(address)
    if offset and isinstance(value, int) and not isinstance(value, bool):
        return value - offset
    return value


class DeskConsole(FakeConsole):
    """`FakeConsole`, plus the readback index offset.

    A real WING answers a GET for `col` / `in/conn/in` one LOWER than the
    value its SET took, which is why `apply._extract_reply_value` corrects
    every reply on the way in. `FakeConsole` stores whatever it was sent
    and hands it straight back, so that correction lands on a value that
    never carried the offset and the address reads one too high --
    harmless in the apply tests, and fatal to a fixture built from a real
    journal, where those addresses are a seventh of the run. This stores
    the raw wire value the desk would, and is used wherever a test's
    console has to behave like the one a journal came off.
    """

    def set_node(self, address: str, command: str):
        reply = super().set_node(address, command)
        key, _, _text = command.partition("=")
        self._store_raw(f"{address}/{key}")
        return reply

    def set_param(self, address: str, value, value_type: str = "f") -> None:
        super().set_param(address, value, value_type)
        self._store_raw(address)

    def _store_raw(self, address: str) -> None:
        held = self.state.get(address)
        if held is None:
            return
        self.state[address] = (raw(address, held[0]), held[1])


def console_holding(**addresses):
    """A FakeConsole whose state is {address: (value, type)}, spelled with
    `/` swapped for `__` so it can be passed as keyword arguments."""
    return FakeConsole({a.replace("__", "/"): v for a, v in addresses.items()})


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def test_an_address_changed_by_somebody_else_is_refused():
    """THE test this module exists for, and the one that was
    mutation-checked hardest.

    Two addresses, both written by our run. Between the apply and the
    undo, somebody renames the second one at the desk. Reversing it would
    put OUR run's history over THEIR change -- so it is refused and
    reported, and the console still holds their value afterwards.

    **Mutation**: making undo's "still ours" comparison always true
    (`if False:` in place of the guard) reverses `/ch/2/name` to `''` and
    fails this test on both the verdict and the console's own state.
    """
    console = console_holding(
        __ch__1__name=("Kick", "s"),
        __ch__2__name=("Somebody Else's Vocal", "s"),
    )
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"),
                row("/ch/2/name", "", "Snare")),
        console, dry_run=False)

    by_address = {s.address: s for s in result.steps}
    assert by_address["/ch/1/name"].verdict == REVERSED
    assert by_address["/ch/2/name"].verdict == REFUSED_CHANGED
    assert by_address["/ch/2/name"].current_value == "Somebody Else's Vocal"
    # The refusal is not merely a label: their value is still on the desk.
    assert console.state["/ch/2/name"] == ("Somebody Else's Vocal", "s")
    assert console.state["/ch/1/name"] == ("", "s")
    assert "/ch/2/name" not in [a for a, _ in console.set_node_calls]


def test_a_float_within_stepped_tolerance_is_not_refused():
    """The `_values_equal`-vs-`!=` choice, against a real
    hardware journal rather than a hand-made one.

    `/ch/1/flt/lcf` on the 2026-09-22 A1 run: apply asked for 40.0Hz and
    the desk read back 39.90524673461914, because WING's log parameters
    are stepped and 40.0 is not one of the steps. The console still holds
    39.905 at undo time -- it has not been touched -- so this address IS
    still ours and MUST be reversed.

    **Mutation**: replacing the guard's `_values_equal(...)` with
    `current != record.intended_value` makes 39.905 != 40.0 true, the
    address is refused as "changed since", and this test fails. Fifteen
    addresses in that one journal do it, so plain inequality would make
    undo untrustworthy on exactly the float addresses it most needs.
    """
    real = json.loads(REAL_JOURNAL.read_text())
    lcf = next(w for w in real["writes"] if w["address"] == "/ch/1/flt/lcf")
    assert lcf["intended_value"] == 40.0 and lcf["readback_value"] != 40.0

    console = FakeConsole({"/ch/1/flt/lcf": (lcf["readback_value"], "f")})
    result = undo_from_journal(journal(lcf), console, dry_run=False)

    step, = result.steps
    assert step.verdict == REVERSED, (
        f"a stepped float readback was treated as somebody else's change: {step.verdict}")
    assert console.state["/ch/1/flt/lcf"][0] == pytest.approx(lcf["prior_value"])


def test_the_guard_reads_the_console_rather_than_trusting_the_journal():
    """The journal says `match`; the desk says otherwise. The desk wins.

    A journal is a record of what happened then, not a claim about now,
    and an undo that trusted it would clobber every change made since.
    """
    console = console_holding(__ch__1__name=("Moved On", "s"))
    result = undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console, dry_run=False)
    assert result.steps[0].verdict == REFUSED_CHANGED
    assert console.set_node_calls == []


def test_an_address_already_back_at_its_prior_value_is_not_a_refusal():
    """Idempotence. Running undo twice must finish the job, not produce a
    page of alarming refusals -- and "already back" is genuinely a
    different fact from "somebody else moved it", so it is counted
    apart."""
    console = console_holding(__ch__1__name=("Kick", "s"))
    j = journal(row("/ch/1/name", "", "Kick"))
    first = undo_from_journal(j, console, dry_run=False)
    assert first.steps[0].verdict == REVERSED

    second = undo_from_journal(j, console, dry_run=False)
    assert second.steps[0].verdict == ALREADY_RESTORED
    assert second.refused == []
    assert "already back" in second.summary()


def test_a_prior_value_that_was_never_readable_is_reported_never_invented():
    console = console_holding(__ch__1__name=("Kick", "s"))
    result = undo_from_journal(
        journal(row("/ch/1/name", None, "Kick", status="unreadable")), console, dry_run=False)
    step, = result.steps
    assert step.verdict == UNREVERSIBLE_NO_PRIOR
    assert console.set_node_calls == []
    assert console.state["/ch/1/name"] == ("Kick", "s")
    assert "1 unreversible (no prior value)" in result.summary()


def test_an_address_that_cannot_be_read_now_is_refused_not_guessed():
    """No current reading means no way to tell whether it is still ours,
    and the conservative answer to that is to leave it alone."""
    console = FakeConsole({})  # every address answers NODE NOT FOUND
    result = undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console, dry_run=False)
    assert result.steps[0].verdict == REFUSED_UNREADABLE
    assert console.set_node_calls == []


# ---------------------------------------------------------------------------
# What is a candidate
# ---------------------------------------------------------------------------

def test_a_dry_run_journal_is_refused_rather_than_reversing_nothing():
    with pytest.raises(UndoError) as exc:
        undo_engine.load_journal(_write(journal(
            row("/ch/1/name", "", "Kick", status="dry_run"), dry_run=True)))
    assert "DRY RUN" in str(exc.value)
    assert "nothing to reverse" in str(exc.value)


def test_skipped_no_change_records_have_nothing_to_reverse():
    console = console_holding(__ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"))
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"),
                row("/ch/2/name", "Snare", "Snare", status="skipped_no_change")),
        console, dry_run=False)
    assert [s.address for s in result.steps] == ["/ch/1/name"]
    assert result.never_written == 1
    assert console.state["/ch/2/name"] == ("Snare", "s")


def test_a_mismatch_record_whose_write_never_landed_reverses_nothing():
    """`mismatch` means the write went out and the desk did not take it.
    The desk therefore still holds the prior value, which is where this
    undo wants it -- so the honest verdict is "already back", not a
    reversal and not a refusal."""
    console = console_holding(__ch__7__tags=("", "s"))
    result = undo_from_journal(
        journal(row("/ch/7/tags", "", "#D7", status="mismatch", readback="")),
        console, dry_run=False)
    assert result.steps[0].verdict == ALREADY_RESTORED
    assert console.set_node_calls == []


# ---------------------------------------------------------------------------
# Order, preview, journalling
# ---------------------------------------------------------------------------

def test_reversal_runs_in_reverse_journal_order():
    """apply.py's STAGE_* ordering exists because phantom power targets
    the socket a channel was just patched to. Unwinding has to undo the
    last thing first."""
    console = console_holding(
        __ch__1__in__conn__grp=("A", "s"),
        __io__in__A__1__vph=(1, "i"),
    )
    result = undo_from_journal(
        journal(row("/ch/1/in/conn/grp", "LCL", "A"),
                row("/io/in/A/1/vph", 0, 1, value_type="i")),
        console, dry_run=False)
    assert [s.address for s in result.steps] == ["/io/in/A/1/vph", "/ch/1/in/conn/grp"]
    assert [a for a, _ in console.set_node_calls] == ["/io/in/A/1", "/ch/1/in/conn"]


def test_the_preview_shows_what_it_would_restore_and_what_it_would_refuse():
    """And writes nothing. A refusal list that only appears after the
    write has happened is worthless."""
    console = console_holding(
        __ch__1__name=("Kick", "s"),
        __ch__2__name=("Somebody Else's Vocal", "s"),
        __ch__3__name=("Hat", "s"),
    )
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"),
                row("/ch/2/name", "", "Snare"),
                row("/ch/3/name", None, "Hat")),
        console)

    assert console.set_node_calls == [] and console.set_param_calls == []
    preview = result.preview()
    assert "RESTORE   /ch/1/name: 'Kick' -> ''" in preview
    assert "REFUSE    /ch/2/name" in preview and "Somebody Else's Vocal" in preview
    assert "NO PRIOR  /ch/3/name" in preview
    assert result.summary().startswith("DRY RUN: 1 would be reversed")
    assert [s.verdict for s in result.steps] == [
        UNREVERSIBLE_NO_PRIOR, REFUSED_CHANGED, WOULD_REVERSE]


def test_the_summary_counts_the_three_apart():
    console = console_holding(
        __ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"),
        __ch__3__name=("Moved", "s"), __ch__4__name=("Also Moved", "s"),
        __ch__5__name=("Hat", "s"),
    )
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare"),
                row("/ch/3/name", "", "Tom"), row("/ch/4/name", "", "Floor"),
                row("/ch/5/name", None, "Hat")),
        console, dry_run=False)
    assert result.summary().splitlines()[0] == (
        "UNDONE: 2 reversed, 2 refused (changed since), 1 unreversible (no prior value).")


def test_a_reversal_that_did_not_land_is_reported_as_one():
    console = console_holding(__ch__1__name=("Kick", "s"))
    console.reject_writes_to.add("/ch/1/name")
    result = undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console, dry_run=False)
    assert result.steps[0].verdict == REVERSAL_MISMATCH
    assert "did NOT land" in result.summary()


def test_a_reversal_the_console_answers_late_is_still_proved():
    """The unacked path's read-after-write race is `apply`'s
    machinery, reached here rather than reimplemented -- so a reversal to
    a value containing a space, which must go out via set_param, is
    settled by the drained datagram exactly as an apply's write is."""
    console = console_holding(__bus__10__name=("VOX Delay", "s"))
    console.answer_late.add("/bus/10/name")
    result = undo_from_journal(
        journal(row("/bus/10/name", "Old Name", "VOX Delay")), console, dry_run=False)
    assert result.steps[0].verdict == REVERSED
    assert result.steps[0].record.readback_source in ("late_reply", "recheck")


def test_the_undo_is_journalled_and_undoing_that_journal_is_the_redo(tmp_path):
    """Journal the undo, and redo falls out of the same mechanism rather
    than needing one of its own."""
    console = console_holding(__ch__1__name=("Kick", "s"))
    undo_journal = tmp_path / "apply-journal.undo.json"
    undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console,
                      dry_run=False, journal_path=str(undo_journal))
    assert console.state["/ch/1/name"] == ("", "s")

    written = json.loads(undo_journal.read_text())
    assert written["dry_run"] is False
    entry, = written["writes"]
    # The undo's own journal is a journal of ITS writes: prior is what the
    # apply had put there, intended is what the undo restored.
    assert (entry["prior_value"], entry["intended_value"]) == ("Kick", "")
    assert entry["status"] == "match"

    redo = undo_from_journal(load_journal(str(undo_journal)), console, dry_run=False)
    assert redo.steps[0].verdict == REVERSED
    assert console.state["/ch/1/name"] == ("Kick", "s")


def test_the_undo_journal_records_what_it_refused(tmp_path):
    """A record of what a run declined to touch is exactly as
    load-bearing as a record of what it wrote -- and its status is
    outside `WRITTEN_STATUSES`, so a redo of that journal correctly finds
    nothing to do for it."""
    console = console_holding(__ch__1__name=("Theirs", "s"))
    path = tmp_path / "undo.json"
    undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console,
                      dry_run=False, journal_path=str(path))
    entry, = json.loads(path.read_text())["writes"]
    assert entry["status"] == REFUSED_CHANGED
    assert entry["status"] not in undo_engine.WRITTEN_STATUSES

    redo = undo_from_journal(load_journal(str(path)), console, dry_run=False)
    assert redo.steps == [] and redo.never_written == 1


def test_a_dry_run_writes_no_journal(tmp_path):
    console = console_holding(__ch__1__name=("Kick", "s"))
    path = tmp_path / "undo.json"
    undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console, journal_path=str(path))
    assert not path.exists()


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------

def test_only_unwinds_half_a_run():
    console = console_holding(__ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"))
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare")),
        console, dry_run=False, only=parse_only("ch:2"))
    assert [s.address for s in result.steps] == ["/ch/2/name"]
    assert result.not_selected == 1
    assert console.state["/ch/1/name"] == ("Kick", "s")
    assert console.state["/ch/2/name"] == ("", "s")


def test_only_takes_an_address_prefix_too():
    assert parse_only("/io/in/A/5") == ["/io/in/A/5"]
    assert parse_only("ch:21, aux:3,bus:4") == ["/ch/21", "/aux/3", "/bus/4"]
    assert parse_only("CH:07") == ["/ch/7"]


def test_only_refuses_a_selector_it_does_not_understand():
    with pytest.raises(UndoError) as exc:
        parse_only("channel 21")
    assert "ch:21" in str(exc.value)


def test_only_does_not_match_a_neighbouring_strip_by_prefix():
    """`ch:2` must not select `/ch/21/...`."""
    console = console_holding(__ch__2__name=("Snare", "s"), __ch__21__name=("Horn", "s"))
    result = undo_from_journal(
        journal(row("/ch/2/name", "", "Snare"), row("/ch/21/name", "", "Horn")),
        console, dry_run=False, only=parse_only("ch:2"))
    assert [s.address for s in result.steps] == ["/ch/2/name"]


def test_an_amend_journals_own_scope_is_the_default_selection():
    """`ApplyResult.scope` records what the amend was ALLOWED to touch,
    which is the right default for what an undo of it may touch -- and it
    is the GRANTS, not the strips: an amend that adds ch:21 also writes
    the socket it patched, which is granted but sits under no strip
    label."""
    scope = {"strips": ["ch:21"],
             "grants": {"/ch/21": "new channel 'Horn 1'",
                        "/io/in/A/5": "the socket channel 21 is patched to"}}
    console = console_holding(
        __ch__21__name=("Horn 1", "s"), __io__in__A__5__name=("Horn 1", "s"))
    result = undo_from_journal(
        journal(row("/ch/21/name", "", "Horn 1"), row("/io/in/A/5/name", "", "Horn 1"),
                scope=scope),
        console, dry_run=False)
    assert sorted(s.address for s in result.steps) == ["/ch/21/name", "/io/in/A/5/name"]
    assert result.selection_source == "this journal's own scope"
    assert result.not_selected == 0
    assert "selection: /ch/21, /io/in/A/5" in result.preview()


def test_only_overrides_the_journals_scope():
    scope = {"strips": ["ch:21"], "grants": {"/ch/21": "new", "/io/in/A/5": "its socket"}}
    console = console_holding(
        __ch__21__name=("Horn 1", "s"), __io__in__A__5__name=("Horn 1", "s"))
    result = undo_from_journal(
        journal(row("/ch/21/name", "", "Horn 1"), row("/io/in/A/5/name", "", "Horn 1"),
                scope=scope),
        console, dry_run=False, only=parse_only("ch:21"))
    assert [s.address for s in result.steps] == ["/ch/21/name"]
    assert result.selection_source == "--only"


# ---------------------------------------------------------------------------
# Offline preview, bad input, aborted runs
# ---------------------------------------------------------------------------

def test_a_preview_can_be_reviewed_offline_from_a_capture():
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare")),
        state={"/ch/1/name": "Kick", "/ch/2/name": "Somebody Else"})
    assert [s.verdict for s in result.steps] == [REFUSED_CHANGED, WOULD_REVERSE]


def test_a_capture_can_never_arm_a_write():
    with pytest.raises(UndoError) as exc:
        undo_from_journal(journal(row("/ch/1/name", "", "Kick")),
                          state={"/ch/1/name": "Kick"}, dry_run=False)
    assert "cannot arm a write" in str(exc.value)


def test_a_file_that_is_not_a_journal_is_refused(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"channels": []}))
    with pytest.raises(UndoError) as exc:
        load_journal(str(path))
    assert "not an apply journal" in str(exc.value)


def test_a_journal_from_an_aborted_run_is_partial_and_reverses_what_is_there(tmp_path):
    """The most important journal to be able to reverse: nobody planned
    for it. Built here by actually aborting an `apply_plan` run mid-way
    (the socket-error path), not by hand-writing what one looks
    like."""
    from atoo.apply import _build_write_targets

    plan = compiled("smallband")
    console = DeskConsole({})
    # Seed every address the plan touches so the run gets going, then kill
    # the connection on one of them.
    targets, _ = _build_write_targets(plan, True)
    for t in targets:
        console.state[t.address] = ("", "s") if t.value_type == "s" else (0, t.value_type)
    victim = targets[12].address
    console.get_overrides[victim] = (
        1, OscReply(address=victim, typetag="SOCKET_ERROR",
                    args=["OSError: [Errno 65] No route to host"]))

    path = tmp_path / "apply-journal.json"
    applied = apply_plan(plan, console, dry_run=False, journal_path=str(path))
    assert applied.aborted and 0 < len(applied.writes) < len(targets)

    partial = load_journal(str(path))
    console.get_overrides.clear()
    result = undo_from_journal(partial, console, dry_run=False)
    written = [w for w in applied.writes if w.status in undo_engine.WRITTEN_STATUSES]
    assert len(result.steps) == len(written)
    assert not result.refused and not result.failed
    for record in written:
        from atoo.console_facts import correct_readback_index
        assert correct_readback_index(
            record.address, console.state[record.address][0]) == record.prior_value


def test_a_real_hardware_journal_reverses_address_for_address():
    """The 707-address A1 run off the maintainer's Compact, 2026-09-22. Every
    address is seeded at the value the desk actually read back, so this
    is the whole run coming back through the guard at once -- 394 written
    addresses, 313 that were never written, and the fifteen stepped
    floats that plain inequality would refuse."""
    real = json.loads(REAL_JOURNAL.read_text())
    written = [w for w in real["writes"] if w["status"] in undo_engine.WRITTEN_STATUSES]
    console = DeskConsole({w["address"]: (raw(w["address"], w["readback_value"]),
                                          w["value_type"]) for w in written})
    result = undo_from_journal(real, console, dry_run=False)

    assert len(result.steps) == len(written) == 394
    assert result.never_written == 313
    assert not result.refused, [s.address for s in result.refused]
    assert not result.unreversible
    assert len(result.reversed_steps) == 394
    from atoo.console_facts import correct_readback_index
    for w in written:
        now = correct_readback_index(w["address"], console.state[w["address"]][0])
        assert now == pytest.approx(w["prior_value"]), w["address"]


def test_a_real_hardware_journal_refuses_what_somebody_else_moved():
    """Same journal, but three addresses have been changed at the desk
    since. Those three are refused; the other 391 still come back."""
    real = json.loads(REAL_JOURNAL.read_text())
    written = [w for w in real["writes"] if w["status"] in undo_engine.WRITTEN_STATUSES]
    console = DeskConsole({w["address"]: (raw(w["address"], w["readback_value"]),
                                          w["value_type"]) for w in written})
    moved = [w for w in written if w["value_type"] == "s"][:3]
    for w in moved:
        console.state[w["address"]] = ("Their Change", "s")

    result = undo_from_journal(real, console, dry_run=False)
    assert sorted(s.address for s in result.refused) == sorted(w["address"] for w in moved)
    assert len(result.reversed_steps) == 391
    for w in moved:
        assert console.state[w["address"]] == ("Their Change", "s")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TMP = []


def _write(payload) -> str:
    import tempfile
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    _TMP.append(handle.name)
    return handle.name


def test_journal_records_default_value_type_for_a_pre_142_journal():
    """A journal written before `value_type` existed (three of the real
    captures in examples/console-runs/ are) still loads. `"s"` is the
    conservative default: a string compares exactly, so such a journal's
    float addresses are more likely to be refused than wrongly
    reversed."""
    old = json.loads((CONSOLE_RUNS / "2026-09-21-2100" / "A1-apply-journal.json").read_text())
    assert all("value_type" not in w for w in old["writes"])
    records = undo_engine.journal_records(old)
    assert {r.value_type for r in records} == {"s"}
    assert isinstance(records[0], WriteRecord)


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_cli_previews_offline_and_exits_clean(tmp_path, capsys):
    from atoo.cli import main

    journal_file = tmp_path / "apply-journal.json"
    journal_file.write_text(json.dumps(journal(
        row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare"))))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"/ch/1/name": "Kick", "/ch/2/name": "Somebody Else"}))

    assert main(["undo", str(journal_file), "--state", str(state)]) == 0
    out = capsys.readouterr().out
    assert "RESTORE   /ch/1/name" in out
    assert "REFUSE    /ch/2/name" in out
    assert "DRY RUN: 1 would be reversed, 1 refused (changed since)." in out
    assert "no console was contacted" in out


def test_cli_writes_the_run_as_json_for_a_preview_and_for_a_confirmed_run(
        tmp_path, capsys, monkeypatch):
    """`--result-json FILE`: what a page draws. A preview's rows say what
    would go back and what would not; a confirmed run's say what did."""
    from atoo import cli

    journal_file = tmp_path / "apply-journal.json"
    journal_file.write_text(json.dumps(journal(
        row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare"))))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"/ch/1/name": "Kick", "/ch/2/name": "Somebody Else"}))
    preview = tmp_path / "preview.json"
    assert cli.main(["undo", str(journal_file), "--state", str(state),
                     "--result-json", str(preview)]) == 0
    data = json.loads(preview.read_text())
    assert data["dry_run"] is True and data["outcome"] == "differs"
    assert {r["address"]: r["verdict"] for r in data["rows"]} == {
        "/ch/1/name": "goes-back", "/ch/2/name": "changed-since"}

    console = console_holding(__ch__1__name=("Kick", "s"), __ch__2__name=("Theirs", "s"))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    done = tmp_path / "done.json"
    assert cli.main(["undo", str(journal_file), "--console", "198.51.100.1", "--confirm",
                     "--result-json", str(done)]) == 2
    data = json.loads(done.read_text())
    assert data["dry_run"] is False and data["outcome"] == "partly-undone"
    assert {r["address"]: r["verdict"] for r in data["rows"]} == {
        "/ch/2/name": "changed-since", "/ch/1/name": "went-back"}


def test_cli_still_records_a_confirmed_undo_when_the_result_file_cannot_be_written(
        tmp_path, capsys, monkeypatch):
    from atoo import cli

    journal_file = tmp_path / "apply-journal.json"
    journal_file.write_text(json.dumps(journal(row("/ch/1/name", "", "Kick"))))
    console = console_holding(__ch__1__name=("Kick", "s"))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    missing = tmp_path / "no-such-folder" / "result.json"
    assert cli.main(["undo", str(journal_file), "--console", "198.51.100.1", "--confirm",
                     "--result-json", str(missing)]) == 0
    assert "--result-json" in capsys.readouterr().err
    assert (tmp_path / "apply-journal.undo.json").exists(), "the reversal is still journalled"


def test_cli_refuses_state_plus_confirm(tmp_path, capsys):
    """There is no second arming control, and --state cannot be the
    first: a capture says nothing about what the desk holds now."""
    from atoo.cli import main

    journal_file = tmp_path / "j.json"
    journal_file.write_text(json.dumps(journal(row("/ch/1/name", "", "Kick"))))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"/ch/1/name": "Kick"}))
    assert main(["undo", str(journal_file), "--state", str(state), "--confirm"]) == 1
    assert "cannot arm a write" in capsys.readouterr().err


def test_cli_exits_2_when_the_console_is_not_fully_back(tmp_path, capsys, monkeypatch):
    from atoo import cli

    journal_file = tmp_path / "apply-journal.json"
    journal_file.write_text(json.dumps(journal(
        row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare"))))
    console = console_holding(__ch__1__name=("Kick", "s"), __ch__2__name=("Theirs", "s"))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)

    assert cli.main(["undo", str(journal_file), "--console", "198.51.100.1", "--confirm"]) == 2
    out = capsys.readouterr().out
    assert "UNDONE: 1 reversed, 1 refused (changed since)." in out
    # The undo's own journal, beside the one it reversed and never over it.
    assert (tmp_path / "apply-journal.undo.json").exists()
    assert journal_file.read_text() == json.dumps(journal(
        row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare")))
    assert "undoing THAT file is the redo" in out


def test_cli_refuses_a_dry_run_journal(tmp_path, capsys):
    from atoo.cli import main

    journal_file = tmp_path / "preview.json"
    journal_file.write_text(json.dumps(journal(
        row("/ch/1/name", "", "Kick", status="dry_run"), dry_run=True)))
    assert main(["undo", str(journal_file), "--console", "198.51.100.1"]) == 1
    assert "nothing to reverse" in capsys.readouterr().err


def test_cli_needs_a_console_or_a_capture(tmp_path, capsys, monkeypatch):
    from atoo.cli import main

    monkeypatch.setenv("ATOO_CONSOLE", "")
    monkeypatch.setattr("atoo.config.config_path", lambda: tmp_path / "nope.config")
    journal_file = tmp_path / "j.json"
    journal_file.write_text(json.dumps(journal(row("/ch/1/name", "", "Kick"))))
    assert main(["undo", str(journal_file)]) == 2
    assert "--state FILE to work from an offline capture instead" in capsys.readouterr().err


def test_a_connection_that_dies_mid_undo_journals_what_it_got_through(tmp_path):
    """`apply` aborts the whole run on a socket error and so
    does this. The addresses already reversed are journalled; the one the
    socket died on is not claimed either way, because nothing knows."""
    console = console_holding(
        __ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"), __ch__3__name=("Hat", "s"))
    # /ch/1 is reversed last (reverse order), and its baseline read is the
    # third get() this run makes of that address... simpler: kill the very
    # first read, of /ch/3.
    console.get_overrides["/ch/2/name"] = (
        1, OscReply(address="/ch/2/name", typetag="SOCKET_ERROR",
                    args=["OSError: [Errno 65] No route to host"]))
    path = tmp_path / "undo.json"
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare"),
                row("/ch/3/name", "", "Hat")),
        console, dry_run=False, journal_path=str(path))

    assert result.aborted and "No route to host" in result.abort_reason
    assert [s.address for s in result.steps] == ["/ch/3/name"]
    assert console.state["/ch/3/name"] == ("", "s")
    assert console.state["/ch/1/name"] == ("Kick", "s")  # never reached
    assert [w["address"] for w in json.loads(path.read_text())["writes"]] == ["/ch/3/name"]
    assert "ABORTED" in result.summary()


# ---------------------------------------------------------------------------
# The run as data: `UndoResult.to_dict()`, which a page draws
# ---------------------------------------------------------------------------

def test_the_run_as_data_has_one_row_per_address_and_one_word_for_the_whole():
    """A preview over four addresses -- one that goes back, one that is
    already back, one somebody has moved and one the apply never read a
    prior value for -- comes out as four rows with their own verdicts, the
    counts, and `differs` for the run: not `safe`."""
    console = console_holding(
        __ch__1__name=("Kick", "s"),
        __ch__2__name=("Somebody Else's Vocal", "s"),
        __ch__3__name=("", "s"),
        __ch__4__name=("Bass", "s"),
    )
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick", description="ch 1 (Kick): name"),
                row("/ch/2/name", "", "Snare", description="ch 2 (Snare): name"),
                row("/ch/3/name", "", "", description="ch 3: name"),
                row("/ch/4/name", None, "Bass", status="unreadable",
                    description="ch 4 (Bass): name")),
        console, dry_run=True)
    data = result.to_dict()
    assert data["dry_run"] is True and data["outcome"] == "differs"
    by_address = {r["address"]: r for r in data["rows"]}
    assert {a: r["verdict"] for a, r in by_address.items()} == {
        "/ch/1/name": "goes-back", "/ch/2/name": "changed-since",
        "/ch/3/name": "already-back", "/ch/4/name": "no-earlier-value"}
    moved = by_address["/ch/2/name"]
    assert moved["strip"] == "ch:2" and moved["strip_name"] == "Snare"
    assert moved["control"] == "name"
    # What the run wrote, what is on the desk now, what an undo would put back.
    assert (moved["written"], moved["now"], moved["goes_back_to"]) == (
        "Snare", "Somebody Else's Vocal", "")
    assert data["counts"]["goes-back"] == 1 and data["counts"]["changed-since"] == 1
    assert data["counts"]["total"] == 4
    assert json.loads(json.dumps(data)) == data, "it has to be plain JSON"
    assert "DRY RUN" in data["summary"]


def test_a_preview_that_puts_everything_back_is_safe_and_an_empty_one_has_nothing_to_undo():
    console = console_holding(__ch__1__name=("Kick", "s"))
    safe = undo_from_journal(journal(row("/ch/1/name", "", "Kick")), console, dry_run=True)
    assert safe.to_dict()["outcome"] == "safe"
    nothing = undo_from_journal(journal(), console, dry_run=True)
    assert nothing.to_dict()["outcome"] == "nothing-to-undo"
    assert nothing.to_dict()["rows"] == []


def test_a_confirmed_run_that_left_something_is_partly_undone_not_undone():
    console = console_holding(
        __ch__1__name=("Kick", "s"), __ch__2__name=("Somebody Else's Vocal", "s"))
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare")),
        console, dry_run=False)
    data = result.to_dict()
    assert data["outcome"] == "partly-undone"
    assert {r["verdict"] for r in data["rows"]} == {"went-back", "changed-since"}
    clean = undo_from_journal(journal(row("/ch/1/name", "", "Kick")),
                              console_holding(__ch__1__name=("Kick", "s")), dry_run=False)
    assert clean.to_dict()["outcome"] == "undone"


@pytest.mark.parametrize("address, strip", [
    ("/ch/21/eq/1/g", "ch:21"), ("/aux/3/name", "aux:3"), ("/bus/4/fdr", "bus:4"),
    ("/main/1/name", "main:1"), ("/mtx/2/name", "mtx:2"), ("/dca/6/name", "dca:6"),
    ("/mgrp/2/name", "mgrp:2"), ("/io/in/A/21/col", "A 21"),
    ("/io/out/A/3/name", "out A 3"), ("/cfg/talk/A/on", "/cfg/talk"),
])
def test_an_address_is_labelled_by_the_object_it_belongs_to(address, strip):
    assert undo_engine.strip_of(address) == strip


def test_a_description_gives_up_the_strips_name_and_the_control():
    assert undo_engine.split_description("ch 21 (Trumpet): patch socket") == (
        "Trumpet", "patch socket")
    assert undo_engine.split_description("bus 'Horns': send level") == ("Horns", "send level")
    assert undo_engine.split_description("ch 3: HPF") == ("", "HPF")
    assert undo_engine.split_description("a write") == ("", "a write")
