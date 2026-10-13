"""`apply`, `undo` and `patch` say what they are doing while they read and
write a desk.

At the desk on 2026-10-12, `apply --confirm` printed its verify block and
then nothing until it finished -- the reset's read alone took 39.6s -- and
was taken for a hang: the failure, on the command #185 never
reached. Each long phase now reports on **stderr** through
`atoo/progress.py`, named so the slow one can be told apart, and
`--no-progress` silences it. Nothing on stdout and nothing in the journal
changes.

The desk is `tests/snap_desk.SnapDesk` built from the frozen initialized
Compact capture (it answers node dumps, so the reset reads the way it does
on hardware), and the plan is the frozen sixpiece copy under
`tests/fixtures/`. Nothing here reads `examples/`.
"""

from __future__ import annotations

import io
import json
import re
import shutil
from pathlib import Path

import pytest

import atoo.console as console_module
from atoo import apply as apply_module
from atoo import cli, initialize, undo
from atoo.apply import apply_plan
from atoo.progress import NO_PHASES, Phases
from tests.snap_desk import SnapDesk, snap_values
from tests.test_apply import FakeConsole

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CAPTURE = FIXTURES / "console-runs" / "Initialized-Compact.snap"
SIXPIECE = FIXTURES / "sixpiece_2026-10-02.plan.json"

READ = initialize.READ_PHASE
PREVIEW = apply_module.PREVIEW_PHASE
RESET = apply_module.RESET_WRITE_PHASE
WRITE = apply_module.WRITE_PHASE
RECHECK = apply_module.RECHECK_PHASE


@pytest.fixture
def desk(monkeypatch):
    """An initialized Compact with one setting off its initialized value,
    so the reset has a write to make, standing in for `WingConsole`."""
    values = snap_values(CAPTURE)
    values["/ch/30/name"] = "OLD SHOW"
    made = SnapDesk(values)
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: made)
    return made


@pytest.fixture
def plan(tmp_path) -> Path:
    path = tmp_path / "plan.json"
    shutil.copy(SIXPIECE, path)
    return path


def _apply(plan: Path, *extra: str) -> int:
    return cli.main(["apply", "--plan", str(plan), "--console", "198.51.100.9",
                     "--skip-verify", *extra])


def _summary(err: str, label: str) -> str | None:
    """The line a phase ends with: "  <label>: N of N <noun> in Xs"."""
    for line in err.splitlines():
        if line.startswith(f"  {label}: "):
            return line
    return None


def _progress_lines(err: str, label: str) -> list[str]:
    """The lines a phase prints while it runs (a pipe: plain lines)."""
    return [line for line in err.splitlines()
            if re.match(rf"  {re.escape(label)} \d+/\d+ \(\d+%\) \d+s -- ", line)]


# ======================================================================
# apply
# ======================================================================


def test_a_preview_says_it_is_reading_the_desk_for_the_reset_then_for_the_preview(
        desk, plan, capsys):
    assert _apply(plan) == 0
    err = capsys.readouterr().err
    # While it runs: the address in flight, phase by phase, in order.
    assert _progress_lines(err, READ) and _progress_lines(err, PREVIEW)
    assert err.index(READ) < err.index(PREVIEW)
    # As it ends: the count and the time. The reset's read counts its
    # requests -- the node dumps it sent, and the GETs.
    read = _summary(err, READ)
    assert read is not None
    assert re.search(r": (\d+) of \1 addresses in \d+\.\ds$", read)
    assert _summary(err, PREVIEW) is not None
    # A preview writes nothing, and does not say it does.
    assert RESET not in err and WRITE not in err


def test_the_reset_read_counts_every_request_it_sends(desk, plan, capsys):
    """The denominator is the request count, not the leaf count: the
    pipe's lines are spaced over the read the desk actually sees."""
    assert _apply(plan) == 0
    err = capsys.readouterr().err
    match = re.search(r": (\d+) of (\d+) addresses", _summary(err, READ))
    assert match.group(1) == match.group(2)
    # Every dump this run sent was the reset's, and each is one request.
    assert len(desk.dumps) > 0
    assert int(match.group(1)) >= len(desk.dumps)
    # The same count the reset's INFO line gives, from `DeskRead.requests`.
    assert f"({int(match.group(1)):,} requests)" in err
    # About twenty lines, not two: the spacing follows the restated total.
    assert len(_progress_lines(err, READ)) >= 10


def test_a_confirmed_apply_names_the_reset_read_the_reset_writes_and_the_plan_writes(
        desk, plan, tmp_path, capsys):
    assert _apply(plan, "--confirm", "--journal", str(tmp_path / "j.json")) == 0
    err = capsys.readouterr().err
    for label in (READ, RESET, WRITE):
        assert _summary(err, label) is not None, label
    assert err.index(READ) < err.index(RESET) < err.index(WRITE)
    # The reset wrote the one setting that was off its initialized value.
    assert re.search(r": 1 of 1 settings in \d+\.\ds$", _summary(err, RESET))
    assert _progress_lines(err, WRITE)
    # A write phase's verdicts are the run's report, not this line's.
    after_write = err[err.index(_summary(err, WRITE)):].splitlines()[1:2]
    assert not any("answered" in line for line in after_write)
    assert PREVIEW not in err


def _stdout_and_journal(plan: Path, journal: Path, *extra: str, capsys):
    capsys.readouterr()
    code = _apply(plan, "--confirm", "--journal", str(journal), *extra)
    captured = capsys.readouterr()
    rows = json.loads(journal.read_text())["writes"]
    # The run's own timings and the journal's path differ between two runs.
    out = re.sub(r"\d+(\.\d+)?s\b", "<t>", captured.out).replace(journal.name, "<journal>")
    return code, out, [{k: v for k, v in r.items() if k != "timestamp"} for r in rows], \
        captured.err


def test_progress_changes_nothing_on_stdout_or_in_the_journal(monkeypatch, plan, tmp_path,
                                                              capsys):
    def fresh_desk():
        values = snap_values(CAPTURE)
        values["/ch/30/name"] = "OLD SHOW"
        made = SnapDesk(values)
        monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: made)

    fresh_desk()
    loud = _stdout_and_journal(plan, tmp_path / "loud.json", capsys=capsys)
    fresh_desk()
    quiet = _stdout_and_journal(plan, tmp_path / "quiet.json", "--no-progress", capsys=capsys)
    assert loud[0] == quiet[0] == 0
    assert loud[1] == quiet[1]
    assert loud[2] == quiet[2]
    # And the phases are on stderr, never on stdout.
    for label in (READ, RESET, WRITE):
        assert label in loud[3] and label not in loud[1]


def test_no_progress_silences_every_phase(desk, plan, tmp_path, capsys):
    assert _apply(plan, "--confirm", "--journal", str(tmp_path / "j.json"),
                  "--no-progress") == 0
    err = capsys.readouterr().err
    for label in (READ, PREVIEW, RESET, WRITE, RECHECK):
        assert label not in err, label


# ======================================================================
# The second look at what disagreed
# ======================================================================


def test_the_re_read_of_what_disagreed_is_a_phase_of_its_own():
    plan = json.loads(SIXPIECE.read_text())
    targets, _ = apply_module._build_write_targets(plan, True)
    state = {}
    for t in targets:
        try:
            state[t.address] = (t.compute_value(None), t.value_type)
        except Exception:
            continue
    name = next(t for t in targets if t.address.endswith("/name"))
    state[name.address] = ("SOMETHING ELSE", "s")
    console = FakeConsole(state)
    console.reject_writes_to = {name.address}
    stream = io.StringIO()
    result = apply_plan(plan, console, dry_run=False,
                        phases=Phases(stream=stream, isatty=False))
    assert [r.status for r in result.writes if r.address == name.address] == ["mismatch"]
    err = stream.getvalue()
    # Every write whose readback disagreed is asked once more (the rejected
    # name among them), and the phase says how many.
    assert re.search(rf"  {re.escape(RECHECK)}: (\d+) of \1 addresses in \d+\.\ds", err)
    assert err.index(WRITE) < err.index(RECHECK)


def test_apply_plan_is_silent_without_phases(capsys):
    plan = json.loads(SIXPIECE.read_text())
    apply_plan(plan, FakeConsole({}), dry_run=True)
    apply_plan(plan, FakeConsole({}), dry_run=True, phases=NO_PHASES)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


# ======================================================================
# undo
# ======================================================================


def test_undo_says_what_it_is_doing_and_no_progress_silences_it(desk, plan, tmp_path, capsys):
    journal = tmp_path / "j.json"
    assert _apply(plan, "--confirm", "--journal", str(journal), "--no-progress") == 0
    capsys.readouterr()

    cli.main(["undo", str(journal), "--console", "198.51.100.9"])
    err = capsys.readouterr().err
    assert _summary(err, undo.PREVIEW_PHASE) is not None
    assert undo.RESTORE_PHASE not in err

    cli.main(["undo", str(journal), "--console", "198.51.100.9", "--confirm",
              "--journal", str(tmp_path / "undo.json")])
    captured = capsys.readouterr()
    restore = _summary(captured.err, undo.RESTORE_PHASE)
    assert restore is not None and re.search(r"settings in \d+\.\ds$", restore)
    assert undo.RESTORE_PHASE not in captured.out
    # A selector the apply changed: its governed values are read first.
    assert _summary(captured.err, undo.EARLY_PHASE) is not None
    assert captured.err.index(undo.EARLY_PHASE) < captured.err.index(undo.RESTORE_PHASE)

    cli.main(["undo", str(journal), "--console", "198.51.100.9", "--no-progress"])
    err = capsys.readouterr().err
    for label in (undo.EARLY_PHASE, undo.PREVIEW_PHASE, undo.RESTORE_PHASE):
        assert label not in err


def test_an_undo_previewed_from_a_state_file_reads_no_desk_and_says_nothing(
        desk, plan, tmp_path, capsys):
    journal = tmp_path / "j.json"
    assert _apply(plan, "--confirm", "--journal", str(journal), "--no-progress") == 0
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"/ch/1/name": "Kick"}))
    capsys.readouterr()
    cli.main(["undo", str(journal), "--state", str(state)])
    assert undo.PREVIEW_PHASE not in capsys.readouterr().err


# ======================================================================
# patch
# ======================================================================


def test_a_confirmed_patch_names_its_proof_reads_and_its_writes(tmp_path, monkeypatch, capsys):
    from tests import test_patch

    console = test_patch.DeskConsole(test_patch._seed(test_patch.applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    fake = test_patch.FakeProvider(response=test_patch._reply(test_patch.horns_change_set()))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    show = test_patch._bundle(tmp_path)

    assert cli.main(["patch", "--show", str(show), test_patch.HORNS_TEXT,
                     "--console", "198.51.100.9", "--confirm"]) == 0
    captured = capsys.readouterr()
    before = "reading the untouched strips, before writing"
    after = "reading the untouched strips, after writing"
    for label in (before, WRITE, after):
        assert _summary(captured.err, label) is not None, label
        assert label not in captured.out
    assert captured.err.index(before) < captured.err.index(WRITE) < captured.err.index(after)
