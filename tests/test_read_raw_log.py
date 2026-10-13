"""`audit`/`watch --raw-log FILE`: the literal request/reply log, for a read.

`apply` and `undo` have had `--raw-log`; the two commands
that only READ did not, and an earlier change needs exactly that -- eight
addresses go unanswered on a full-size WING and cost 24s of a 47s read,
and which eight is not knowable from a dump, because a dump leaves out
what never answered.

What matters, and each has a test:

1. The file reaches `WingConsole`, so the console's own logging writes
   to it from the identity exchange onward.
2. It is LINE-BUFFERED: a line is on disk while the read is still going.
   The read this is for is the slow one somebody stops with Ctrl-C, and
   a block-buffered log would lose its tail exactly then.
3. Without the flag, nothing is opened -- the absent case.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo import audit
from atoo.audit import ConsoleState
from atoo.cli import main
from atoo.console import OscReply

DEMO = Path(__file__).parent / "fixtures" / "audit_demo_state.json"


class _LoggingConsole:
    """A `WingConsole` stand-in that logs the way the real one does: one
    line per exchange, written to the `raw_log` it was handed."""

    received = []

    def __init__(self, ip, port=2223, timeout=1.0, raw_log=None):
        self.raw_log = raw_log
        _LoggingConsole.received.append(raw_log)

    def _log(self, line):
        if self.raw_log is not None:
            self.raw_log.write(line + "\n")

    def identity(self):
        self._log("-> /?  <- WING,192.0.2.16,Fake,wing-compact,SN,3.1-0")
        return OscReply(address="/?", typetag="s",
                        args=["WING,192.0.2.16,Fake,wing-compact,SN,3.1-0"])

    def get(self, address):
        self._log(f"-> {address}  <- (no reply)")
        return None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _fake_desk(monkeypatch, on_read=None):
    import atoo.console as console_module
    _LoggingConsole.received = []
    monkeypatch.setattr(console_module, "WingConsole", _LoggingConsole)
    values = json.loads(DEMO.read_text())

    def read(console, **kwargs):
        console.get("/ch/1/name")
        if on_read is not None:
            on_read()
        return ConsoleState(dict(values), console_model="wing-compact")

    monkeypatch.setattr(audit, "read_console_state", read)


def test_audit_raw_log_records_the_identity_exchange_and_the_read(monkeypatch, tmp_path, capsys):
    log = tmp_path / "raw.log"
    _fake_desk(monkeypatch)
    main(["audit", "--console", "192.0.2.16", "--raw-log", str(log), "--no-progress"])

    text = log.read_text()
    assert "-> /?" in text, "the identity exchange is the first thing a raw log is for"
    assert "-> /ch/1/name" in text
    assert _LoggingConsole.received[0].closed, "audit must close the log it opened"


def test_the_log_is_on_disk_while_the_read_is_still_running(monkeypatch, tmp_path, capsys):
    """Line buffering, pinned: read the FILE mid-read, not the handle."""
    log = tmp_path / "raw.log"
    seen_mid_read = []
    _fake_desk(monkeypatch, on_read=lambda: seen_mid_read.append(log.read_text()))
    main(["audit", "--console", "192.0.2.16", "--raw-log", str(log), "--no-progress"])

    assert seen_mid_read and "-> /ch/1/name" in seen_mid_read[0], (
        "a line written during the read must already be on disk -- a stopped "
        "read would otherwise lose it")


def test_the_log_appends_rather_than_replacing(monkeypatch, tmp_path, capsys):
    """A second run is evidence too; a raw log is never truncated."""
    log = tmp_path / "raw.log"
    log.write_text("an earlier run\n")
    _fake_desk(monkeypatch)
    main(["audit", "--console", "192.0.2.16", "--raw-log", str(log), "--no-progress"])
    assert log.read_text().startswith("an earlier run\n")


def test_without_the_flag_no_log_is_opened(monkeypatch, tmp_path, capsys):
    _fake_desk(monkeypatch)
    main(["audit", "--console", "192.0.2.16", "--no-progress"])
    assert _LoggingConsole.received == [None]


def test_watch_takes_the_flag_too(monkeypatch, tmp_path, capsys):
    import atoo.watch as watch_module
    log = tmp_path / "raw.log"
    _fake_desk(monkeypatch)
    # One pass is enough to prove the wiring; the loop itself is watch's,
    # and it is a generator of events -- this one yields none.
    def one_pass(state_provider, **kwargs):
        state_provider()
        return iter(())

    monkeypatch.setattr(watch_module, "watch", one_pass, raising=False)
    main(["watch", "--console", "192.0.2.16", "--raw-log", str(log),
          "--count", "1", "--no-progress", "--interval", "0"])
    assert _LoggingConsole.received and _LoggingConsole.received[0] is not None
    assert "-> /?" in log.read_text()
