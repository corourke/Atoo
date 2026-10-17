"""`audit --dump-state FILE`: save a live read so it can be audited again
offline.

Decided 2026-09-23. The A5 re-score had to be
reconstructed from a `.snap` and `2026-09-21/A0` is unusable, both for
want of the reading itself: `audit --state` could read a capture, and
nothing could write one.

What matters, and each has a test:

1. The file is exactly what `audit --state` reads, and replaying it gives
   the same report the live run printed.
2. It is written BEFORE the audit, so a rule that crashes cannot take the
   reading with it.
3. A destination that cannot be written is found before the desk is
   read, not after forty seconds of reading it.
4. `--state --dump-state` is refused: there is no live read to save.
5. The console model, which the format cannot carry, is said out loud.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import audit, cli
from atoo.audit import ConsoleState
from atoo.cli import main

DEMO = Path(__file__).parent / "fixtures" / "audit_demo_state.json"


class _Desk:
    """Stands in for an open `WingConsole`: only the context manager is
    used, because the read itself is replaced below."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def live(monkeypatch):
    """A live `audit --console` whose read returns the demo state, tagged
    with the model a real desk states on `/?`. Records whether the desk
    was ever read."""
    values = json.loads(DEMO.read_text())
    calls = []

    def read(console, **kwargs):
        calls.append(kwargs)
        return ConsoleState(dict(values), console_model="wing-compact")

    monkeypatch.setattr(cli, "_open_console", lambda args, raw_log=None: _Desk())
    monkeypatch.setattr(audit, "read_console_state", read)
    return values, calls


def _live_args(*more):
    return ["audit", "--console", "192.0.2.1", "--no-progress", *more]


def test_the_dump_is_the_state_file_format_and_replays_to_the_same_report(
        live, tmp_path, capsys):
    values, _ = live
    dump = tmp_path / "tonight.state.json"

    live_code = main(_live_args("--dump-state", str(dump)))
    live_out = capsys.readouterr().out

    assert json.loads(dump.read_text()) == values
    replay_code = main(["audit", "--state", str(dump)])
    replay_out = capsys.readouterr().out
    assert replay_code == live_code
    # The findings are identical. Only the coverage hint differs, and on
    # purpose: a capture cannot be re-read with more sockets, so it says so.
    assert (live_out.split("Physical sockets read")[0]
            == replay_out.split("Physical sockets read")[0])


def test_it_is_written_before_the_audit_runs(live, tmp_path, monkeypatch):
    dump = tmp_path / "d.json"

    def boom(*a, **k):
        raise RuntimeError("a rule fell over")

    monkeypatch.setattr(audit, "run_audit", boom)
    with pytest.raises(RuntimeError):
        main(_live_args("--dump-state", str(dump)))
    assert json.loads(dump.read_text()) == live[0]


def test_an_unwritable_destination_is_refused_before_the_desk_is_read(
        live, tmp_path, capsys):
    _, calls = live
    missing = tmp_path / "no-such-dir" / "d.json"
    assert main(_live_args("--dump-state", str(missing))) == 1
    assert calls == []
    assert "nothing was read" in capsys.readouterr().err


def test_an_existing_capture_is_replaced_whole(live, tmp_path):
    dump = tmp_path / "d.json"
    dump.write_text('{"/old": 1, "/stale/and/long": "x"}')
    main(_live_args("--dump-state", str(dump)))
    assert json.loads(dump.read_text()) == live[0]
    assert not (tmp_path / "d.json.tmp").exists()


def test_it_is_refused_with_state(tmp_path, capsys):
    dump = tmp_path / "d.json"
    assert main(["audit", "--state", str(DEMO), "--dump-state", str(dump)]) == 1
    assert "LIVE read" in capsys.readouterr().err
    assert not dump.exists()


def test_the_model_the_file_cannot_carry_is_named(live, tmp_path, capsys):
    main(_live_args("--dump-state", str(tmp_path / "d.json")))
    err = capsys.readouterr().err
    assert f"Saved {len(live[0])} addresses" in err
    assert "wing-compact" in err
    assert "--plan" in err
