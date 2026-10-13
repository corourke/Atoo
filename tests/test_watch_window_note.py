"""A watch started from the page says what
`ATOO_CONSOLE_WINDOW` did, as `atoo watch` does on a terminal.

The CLI prints the line before it contacts the desk
(`cli._resolve_console_settings`); the Watch page is not a command, so the
same line is a session note (`watch.window_note`) on every frame, in the
status line under the Watch header with the other notes."""

from __future__ import annotations

import pytest

from conftest import require_fastapi_testclient

fastapi_testclient = require_fastapi_testclient()

from atoo import console, webui  # noqa: E402
from atoo.audit import ConsoleState  # noqa: E402
from atoo.diagnostics import Severity  # noqa: E402
from atoo.watch import WINDOW_NOTE_CODE, window_note  # noqa: E402


@pytest.mark.parametrize("environ, expected", [
    ({}, None),
    ({"ATOO_CONSOLE_WINDOW": "8"}, None),       # the default restated is not news
    ({"ATOO_CONSOLE_WINDOW": "1"},
     "Using console window 1 from ATOO_CONSOLE_WINDOW"),
    ({"ATOO_CONSOLE_WINDOW": "0"},
     "ATOO_CONSOLE_WINDOW='0' is not a whole number of at least 1 -- ignoring it "
     "(window 8)"),
])
def test_window_notice_is_the_cli_line(environ, expected):
    assert console.window_notice(environ) == expected


def test_window_note_is_an_info_session_note():
    note = window_note({"ATOO_CONSOLE_WINDOW": "2"})
    assert note.severity is Severity.INFO and note.rule_id == WINDOW_NOTE_CODE
    assert note.group == "Console window" and note.summary == "2, from ATOO_CONSOLE_WINDOW"
    assert note.detail == "Using console window 2 from ATOO_CONSOLE_WINDOW."
    rejected = window_note({"ATOO_CONSOLE_WINDOW": "many"})
    assert rejected.severity is Severity.INFO          # a warning would read "not watched"
    assert rejected.summary == "8 (ATOO_CONSOLE_WINDOW not taken as set)"
    assert window_note({}) is None


def _first_event(monkeypatch) -> dict:
    base = webui._load_demo_base()

    def factory(ip, *, port=2223, timeout=1.0, read_kwargs=None, name_refresh=1, **extra):
        return (lambda: ConsoleState(dict(base))), None

    monkeypatch.setattr(webui, "console_provider_factory", factory)
    with fastapi_testclient.TestClient(webui.create_app()) as client:
        r = client.post("/api/watch/start", json={"source": "console", "console": "192.0.2.1",
                                                  "interval": 0.05})
        assert r.status_code == 200, r.text
        try:
            with client.websocket_connect("/ws/watch") as ws:
                for _ in range(60):
                    payload = ws.receive_json()
                    if payload.get("type") == "event":
                        return payload
        finally:
            client.post("/api/watch/stop")
    raise AssertionError("no event")


def test_a_watch_from_the_page_carries_the_window_note(monkeypatch):
    monkeypatch.setenv("ATOO_CONSOLE_WINDOW", "3")
    notes = [n for n in _first_event(monkeypatch)["notes"] if n["rule_id"] == WINDOW_NOTE_CODE]
    assert len(notes) == 1
    assert notes[0]["severity"] == "info" and notes[0]["group"] == "Console window"
    assert notes[0]["detail"] == "Using console window 3 from ATOO_CONSOLE_WINDOW."


def test_a_watch_on_the_default_window_has_no_window_note(monkeypatch):
    monkeypatch.delenv("ATOO_CONSOLE_WINDOW", raising=False)
    assert not [n for n in _first_event(monkeypatch)["notes"]
                if n["rule_id"] == WINDOW_NOTE_CODE]
