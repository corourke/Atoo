"""Watch's Virtual soundcheck switch: C004 (a channel on its alternate input)
and C005 (the global alternate switch) report at INFO while the engineer says a
virtual soundcheck is under way, and are warnings again the moment it is off.

The alternate is how a virtual soundcheck works, so during one these two rows
are noise; at the end of it a strip left on its alternate is the thing to catch
before doors. The switch is the session's alone: off at every Start, nothing
stored. The desks are built here; the Chromium half is in
`test_webui_watch_virtual_soundcheck.py`.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from atoo.audit import (
    DEFAULT_RULES, ConsoleState, Severity, run_audit, virtual_soundcheck_rules,
)
from atoo.cli import main
from atoo.watch import (
    VIRTUAL_SOUNDCHECK_RULE_ID, WatchNote, finding_key, present_findings,
    virtual_soundcheck_note, watch,
)


def _desk(*, alt=(1, 2), glob=False, **more) -> ConsoleState:
    """A small desk: ch 1 Kick and ch 2 Snare patched from A 1 and A 2, each
    set to its alternate (a WLIVE card) when its number is in `alt`."""
    v: dict[str, object] = {"/io/altsw": 1 if glob else 0}
    for n, name in ((1, "Kick"), (2, "Snare"), (3, "Bass")):
        base = f"/ch/{n}"
        v[f"{base}/name"] = name
        v[f"{base}/in/conn/grp"], v[f"{base}/in/conn/in"] = "A", n
        v[f"{base}/in/conn/altgrp"] = "CRD"
        v[f"{base}/in/set/altsrc"] = 1 if n in alt else 0
    v.update(more)
    return ConsoleState(v, console_model="wing-compact")


def _alt(findings):
    return [f for f in findings if f.rule_id in {"C004", "C005"}]


# --------------------------------------------------------------------------
# The rules at INFO
# --------------------------------------------------------------------------


def test_without_the_switch_a_channel_on_its_alternate_is_a_warning():
    findings = _alt(run_audit(_desk()))
    assert [(f.rule_id, f.severity) for f in findings] == [
        ("C004", Severity.WARNING), ("C004", Severity.WARNING)]
    assert "not hear the stage; switch it back on the desk if the show is live" in findings[0].message


def test_with_the_switch_every_strip_is_still_named_at_info_and_the_reason_is_in_the_row():
    rules = virtual_soundcheck_rules(DEFAULT_RULES)
    findings = _alt(run_audit(_desk(), rules))
    assert [(f.rule_id, f.severity) for f in findings] == [
        ("C004", Severity.INFO), ("C004", Severity.INFO)]
    assert [f.addresses for f in findings] == [
        ("/ch/1/in/set/altsrc", "/ch/1/in/conn/altgrp"),
        ("/ch/2/in/set/altsrc", "/ch/2/in/conn/altgrp")]
    assert findings[0].message == (
        'CH 1 "Kick" is listening to its alternate patch from CRD, not its main patch (AES50-A 1). '
        "Virtual soundcheck is on, so this is expected; if the show is live, switch it back on "
        "the desk and turn virtual soundcheck off.")
    assert 'CH 2 "Snare"' in findings[1].message


def test_the_global_alternate_switch_is_info_too():
    state = _desk(alt=(), glob=True)
    [warning] = _alt(run_audit(state))
    assert warning.severity == Severity.WARNING and warning.rule_id == "C005"
    [info] = _alt(run_audit(state, virtual_soundcheck_rules(DEFAULT_RULES)))
    assert (info.rule_id, info.severity) == ("C005", Severity.INFO)
    assert "Virtual soundcheck is on, so this is expected" in info.message
    assert info.addresses == ("/io/altsw",)


def test_silent_when_the_switch_was_never_read_in_either_mode():
    state = ConsoleState({"/ch/1/name": "Kick"})
    assert _alt(run_audit(state)) == []
    assert _alt(run_audit(state, virtual_soundcheck_rules(DEFAULT_RULES))) == []


def test_a_desk_on_its_main_inputs_says_nothing_in_either_mode():
    state = _desk(alt=())
    assert _alt(run_audit(state)) == []
    assert _alt(run_audit(state, virtual_soundcheck_rules(DEFAULT_RULES))) == []


def test_only_c004_and_c005_change_and_the_originals_are_untouched():
    rules = virtual_soundcheck_rules(DEFAULT_RULES)
    assert [r.id for r in rules] == [r.id for r in DEFAULT_RULES]
    changed = {new.id for new, old in zip(rules, DEFAULT_RULES) if new is not old}
    assert changed == {"C004", "C005"}
    assert {r.id: r.severity for r in rules if r.id in changed} == {
        "C004": Severity.INFO, "C005": Severity.INFO}
    assert {r.id: r.severity for r in DEFAULT_RULES if r.id in changed} == {
        "C004": Severity.WARNING, "C005": Severity.WARNING}
    # every other finding on the same desk is the same with the switch on
    state = _desk(**{"/ch/3/in/conn/grp": "OFF"})
    other = lambda fs: [f for f in fs if f.rule_id not in {"C004", "C005"}]  # noqa: E731
    assert other(run_audit(state, rules)) == other(run_audit(state))


def test_the_finding_key_counts_the_severity_so_a_regrade_is_a_change():
    on = _alt(run_audit(_desk(), virtual_soundcheck_rules(DEFAULT_RULES)))[0]
    off = _alt(run_audit(_desk()))[0]
    assert on.addresses == off.addresses and finding_key(on) != finding_key(off)


# --------------------------------------------------------------------------
# The note: the state is never hidden
# --------------------------------------------------------------------------


def test_the_note_is_an_info_watch_note_that_says_what_the_switch_does():
    note = virtual_soundcheck_note()
    assert isinstance(note, WatchNote)
    assert (note.rule_id, note.severity) == (VIRTUAL_SOUNDCHECK_RULE_ID, Severity.INFO)
    assert note.title == "Virtual soundcheck is on"
    assert "C004" in note.message and "C005" in note.message and "at INFO" in note.message
    shown = present_findings([note])
    assert shown.alerts == [] and shown.notes == [note]      # status line, not a row
    assert (note.group, note.summary) == ("Virtual soundcheck", "on, alternate inputs at INFO")


# --------------------------------------------------------------------------
# A watch sequence
# --------------------------------------------------------------------------


def test_a_switch_turned_on_then_off_mid_watch_regrades_the_rows_at_once():
    """Baseline: two warnings. Virtual soundcheck on: the warnings clear, two
    INFO rows are new. Off: the INFO rows clear and the two warnings are new
    in that very pass."""
    rules = list(DEFAULT_RULES)
    plan = {1: virtual_soundcheck_rules(DEFAULT_RULES), 3: list(DEFAULT_RULES)}
    states = iter([_desk()] * 5)
    count = 0

    def provider():
        nonlocal count
        if count in plan:
            rules[:] = plan[count]
        count += 1
        return next(states)

    events = list(watch(provider, rules=rules, interval=0, max_iterations=5, sleep=lambda _s: None))
    grade = lambda fs: sorted((f.rule_id, f.severity.value) for f in fs)  # noqa: E731
    assert grade(_alt(events[0].all_findings)) == [("C004", "warning")] * 2
    assert grade(events[1].cleared_findings) == [("C004", "warning")] * 2
    assert grade(events[1].new_findings) == [("C004", "info")] * 2
    assert events[2].new_findings == [] and events[2].cleared_findings == []
    assert grade(events[3].cleared_findings) == [("C004", "info")] * 2
    assert grade(events[3].new_findings) == [("C004", "warning")] * 2


def test_a_strip_put_back_while_the_switch_is_on_clears_its_row():
    rules = virtual_soundcheck_rules(DEFAULT_RULES)
    states = iter([_desk(), _desk(alt=(2,))])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=2,
                        sleep=lambda _s: None))
    assert [f.addresses[0] for f in events[1].cleared_findings] == ["/ch/1/in/set/altsrc"]


def test_the_note_rides_every_cycle_while_the_caller_gives_it():
    rules = virtual_soundcheck_rules(DEFAULT_RULES)
    on = [True, True, False]
    seen = iter(on)
    states = iter([_desk()] * 3)

    def notes():
        return [virtual_soundcheck_note()] if next(seen) else []

    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=3,
                        sleep=lambda _s: None, session_notes=notes))
    ids = [[f.rule_id for f in e.all_findings if f.rule_id == VIRTUAL_SOUNDCHECK_RULE_ID]
           for e in events]
    assert ids == [["W003"], ["W003"], []]
    assert events[1].new_findings == []                      # the same note, not news
    assert [f.rule_id for f in events[2].cleared_findings] == ["W003"]


# --------------------------------------------------------------------------
# atoo watch --virtual-soundcheck
# --------------------------------------------------------------------------


@pytest.fixture
def state_file(tmp_path):
    path = tmp_path / "alt.state.json"
    path.write_text(json.dumps(_desk().values), encoding="utf-8")
    return path


def test_the_command_line_flag_reports_the_alternate_inputs_at_info(state_file, capsys):
    assert main(["watch", "--state-sequence", str(state_file), "--count", "1",
                 "--virtual-soundcheck"]) == 0
    out = capsys.readouterr().out
    assert "[INFO] C004 Channel On Its Alternate Input (2)" in out
    assert "[WARNING] C004" not in out
    assert "[INFO] W003 Virtual soundcheck is on" in out


def test_without_the_flag_they_are_warnings_and_there_is_no_note(state_file, capsys):
    main(["watch", "--state-sequence", str(state_file), "--count", "1"])
    out = capsys.readouterr().out
    assert "[WARNING] C004 Channel On Its Alternate Input (2)" in out
    assert "W003" not in out


def test_the_flag_is_in_the_help(capsys):
    from atoo.cli import WATCH_DESCRIPTION

    assert "--virtual-soundcheck" in WATCH_DESCRIPTION
    with pytest.raises(SystemExit):
        main(["watch", "--help"])
    out = capsys.readouterr().out
    assert "--virtual-soundcheck" in out and "C004" in out and "W003" in out


# --------------------------------------------------------------------------
# The Watch page's server half
# --------------------------------------------------------------------------


def _wait(predicate, what, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


class _Session:
    """A `WatchSession` over a fixed desk, with its payloads collected."""

    def __init__(self, base_rules=None):
        from atoo.webui import WatchSession

        self.session = WatchSession()
        self.loop = asyncio.new_event_loop()
        self.payloads: list[dict] = []
        self.queue = self.session.subscribe(self.loop)
        self.base_rules = base_rules

    def start(self, **kwargs):
        self.session.start(self.loop, lambda: (lambda: _desk(), None), 0.05, "test",
                           rules=self.base_rules, **kwargs)

    def events(self):
        while True:
            try:
                self.payloads.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return [p for p in self.payloads if p.get("type") == "event"]

    def latest(self):
        self.loop.run_until_complete(asyncio.sleep(0.05))
        events = self.events()
        return events[-1] if events else None

    def close(self):
        self.session.stop()
        self.loop.close()


@pytest.fixture
def live():
    s = _Session()
    yield s
    s.close()


def _grades(payload):
    return sorted((f["rule_id"], f["severity"]) for f in payload["all_findings"]
                  if f["rule_id"] == "C004")


def _until(live, condition, what):
    def check():
        event = live.latest()
        return event is not None and condition(event)
    _wait(check, what)
    return live.latest()


def test_a_watch_started_with_the_switch_on_reports_info_and_carries_the_note(live):
    live.start(virtual_soundcheck=True)
    assert live.session.status()["virtual_soundcheck"] is True
    event = _until(live, lambda e: e["baseline"] or True, "a reading")
    assert _grades(event) == [("C004", "info")] * 2
    assert [n["rule_id"] for n in event["notes"]] == ["W003"]
    assert event["notes"][0]["group"] == "Virtual soundcheck"


def test_a_watch_starts_with_the_switch_off_by_default(live):
    live.start()
    assert live.session.status()["virtual_soundcheck"] is False
    event = _until(live, lambda e: True, "a reading")
    assert _grades(event) == [("C004", "warning")] * 2
    assert event["notes"] == []


def test_turning_it_on_and_off_regrades_the_rows_and_new_findings_say_so(live):
    live.start()
    _until(live, lambda e: True, "the baseline")
    assert live.session.set_virtual_soundcheck(True) is True
    assert live.session.status()["virtual_soundcheck"] is True
    on = _until(live, lambda e: _grades(e) == [("C004", "info")] * 2, "the rows at INFO")
    assert [n["rule_id"] for n in on["notes"]] == ["W003"]

    assert live.session.set_virtual_soundcheck(False) is True
    _until(live, lambda e: _grades(e) == [("C004", "warning")] * 2, "the rows back at WARNING")
    news = [f for p in live.events() for f in p["new_findings"]
            if f["rule_id"] == "C004" and f["severity"] == "warning"]
    assert news, "a strip still on its alternate must be NEW as a warning when it is turned off"
    assert live.latest()["notes"] == []


def test_stopping_forgets_the_switch_so_the_next_start_is_off(live):
    live.start(virtual_soundcheck=True)
    _until(live, lambda e: True, "a reading")
    live.session.stop()
    assert live.session.status()["virtual_soundcheck"] is False
    live.start()
    assert live.session.status()["virtual_soundcheck"] is False


def test_a_press_with_no_watch_running_changes_nothing(live):
    assert live.session.set_virtual_soundcheck(True) is False
    assert live.session.status()["virtual_soundcheck"] is False


def test_saving_the_watch_list_keeps_the_switch(live):
    live.start(virtual_soundcheck=True)
    _until(live, lambda e: True, "a reading")
    assert live.session.replace_rules(list(DEFAULT_RULES), "watch.json") is True
    _until(live, lambda e: _grades(e) == [("C004", "info")] * 2, "the rows still at INFO")
    assert live.session.set_virtual_soundcheck(False)
    _until(live, lambda e: _grades(e) == [("C004", "warning")] * 2, "the rows at WARNING")


def test_the_endpoints_carry_the_switch(monkeypatch):
    from conftest import require_fastapi_testclient

    from atoo import webui

    client_cls = require_fastapi_testclient().TestClient
    monkeypatch.setattr(webui, "demo_provider_factory", lambda: (lambda: _desk(), None))
    with client_cls(webui.create_app()) as client:
        assert client.post("/api/console", json={"demo": True}).status_code == 200
        refused = client.post("/api/watch/virtual-soundcheck", json={"on": True})
        assert refused.status_code == 409 and "no watch is running" in refused.json()["error"]
        assert client.get("/api/status").json()["virtual_soundcheck"] is False
        started = client.post("/api/watch/start", json={"interval": 0.5,
                                                          "virtual_soundcheck": True})
        try:
            assert started.json()["virtual_soundcheck"] is True
            assert client.get("/api/status").json()["virtual_soundcheck"] is True
            off = client.post("/api/watch/virtual-soundcheck", json={"on": False})
            assert off.json()["virtual_soundcheck"] is False
        finally:
            stopped = client.post("/api/watch/stop")
        assert stopped.json()["virtual_soundcheck"] is False


# --------------------------------------------------------------------------
# The served page (the Python suite cannot see the browser)
# --------------------------------------------------------------------------


def test_the_served_page_and_script_carry_the_switch():
    from conftest import require_fastapi_testclient

    from atoo.webui import create_app

    with require_fastapi_testclient().TestClient(create_app()) as client:
        html = client.get("/").text
        js = client.get("/static/watch.js").text
    for id_ in ("watch-virtual", "vs-pill"):
        assert f'id="{id_}"' in html
        assert f'el("{id_}")' in js
    assert 'id="vs-pill" class="state is-warn" hidden' in html
    assert 'role="switch"' in html[html.index('id="watch-virtual"') - 80:html.index('id="watch-virtual"') + 200]
    assert "<span>Virtual soundcheck</span>" in html
    # The switch rides Start, is told to a running watch, and is forgotten at Stop.
    start = js[js.index('startBtn.addEventListener("click"'):js.index('stopBtn.addEventListener("click"')]
    assert "virtual_soundcheck: virtualSoundcheck" in start[:start.index('fetch("/api/watch/start"')]
    assert '"/api/watch/virtual-soundcheck"' in js
    stop = js[js.index('stopBtn.addEventListener("click"'):]
    assert "virtualSoundcheck = false;" in stop[:stop.index("setRunningUI(false)")]
    # A finding re-graded is another row, as the server counts it.
    key = js[js.index("function findingKey("):]
    assert 'f.addresses.join(",") + "|" + f.severity' in key[:key.index("}")]
    # Never stored on this device.
    assert "localStorage" not in js[js.index("let virtualSoundcheck"):js.index("function connectWs")]
