"""`atoo watch --findings-log FILE`: a header, one JSON line per
pass, a footer on a clean stop; flushed every pass; read-only; no key.

Offline, over the same hand-built states the other Watch tests use; the CLI
tests run `watch --state-sequence` end to end.
"""

from __future__ import annotations

import io
import json

import pytest

from atoo.audit import DEFAULT_RULES, ConsoleState
from atoo.cli import main
from atoo.findings_log import FORMAT, FindingsLog, header_line
from atoo.watch import watch

CLEAN = {"/ch/1/name": "Vox", "/ch/1/tags": "#D1", "/ch/2/name": "Gtr", "/ch/2/tags": "#D2"}
DUPLICATE = {**CLEAN, "/ch/2/name": "Vox"}


class CountingSink(io.StringIO):
    """A file that counts flushes and keeps what had been flushed."""

    def __init__(self):
        super().__init__()
        self.flushes = 0
        self.flushed_text: list[str] = []

    def flush(self):
        self.flushes += 1
        self.flushed_text.append(self.getvalue())

    def close(self):           # keep the text readable after the log closes
        pass


def _run(states, sink):
    log = FindingsLog(sink, header_line(install={"version": "x"}, console="192.0.2.9",
                                        identity=["WING,192.0.2.9,desk,wing-fullsize,SN,3.1:1"],
                                        plan=None, conditions=None, started="t-start"),
                      clock=lambda: "t-end")
    feed = iter(states)
    events = list(watch(lambda: ConsoleState(next(feed)), rules=list(DEFAULT_RULES), interval=0,
                        max_iterations=len(states), sleep=lambda _s: None,
                        clock=iter(f"t{n}" for n in range(99)).__next__))
    for event, values in zip(events, states):
        log.record(event, ConsoleState(values))
    log.close("finished")
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def test_header_then_one_line_per_pass_then_a_footer():
    lines = _run([CLEAN, DUPLICATE, DUPLICATE, CLEAN], CountingSink())
    assert [line["type"] for line in lines] == ["header", "pass", "pass", "pass", "pass", "footer"]
    header = lines[0]
    assert header["format"] == FORMAT and header["console"] == "192.0.2.9"
    assert header["console_identity"] == ["WING,192.0.2.9,desk,wing-fullsize,SN,3.1:1"]
    assert header["plan"] == "no plan" and header["started"] == "t-start"
    assert lines[-1] == {"type": "footer", "stopped": "t-end", "passes": 4, "reason": "finished"}


def test_findings_appear_in_order_and_a_cleared_one_is_recorded():
    _, base, appeared, steady, cleared, _ = _run([CLEAN, DUPLICATE, DUPLICATE, CLEAN], CountingSink())
    assert [p["pass"] for p in (base, appeared, steady, cleared)] == [0, 1, 2, 3]
    assert base["baseline"] and base["findings"] == [] and base["appeared"] == []
    [new] = appeared["appeared"]
    assert new["severity"] and new["message"] and "code" in new
    assert appeared["findings"] == [new] and appeared["finding_count"] == 1
    assert steady["changed"] is False and "findings" not in steady and steady["finding_count"] == 1
    assert cleared["cleared"] == [new] and cleared["findings"] == []


def test_every_line_is_flushed_when_written():
    sink = CountingSink()
    _run([CLEAN, DUPLICATE], sink)
    assert sink.flushes == 4                        # header, two passes, footer
    assert sink.flushed_text[0].count("\n") == 1    # the header was on disk before pass 0
    assert sink.flushed_text[1].count("\n") == 2


def test_no_footer_when_abandoned():
    sink = CountingSink()
    log = FindingsLog(sink, {"type": "header"})
    log.abandon()
    assert [json.loads(line)["type"] for line in sink.getvalue().splitlines()] == ["header"]


def test_the_meters_and_what_the_desk_did_not_answer_are_in_the_line():
    from atoo.metering import ClipStatus, StripClip

    state = ConsoleState({}, clip_status=ClipStatus(True, "on", "..."),
                         clips=(StripClip("/ch/3", 2, 4.0, 56.0),),
                         live_strips=frozenset({"/ch/1", "/ch/2"}),
                         unasked_families={"/ch/{n}/x": ["/ch/1/x", "/ch/2/x"]})
    sink = CountingSink()
    log = FindingsLog(sink, {"type": "header"})
    feed = iter([{}])
    [event] = watch(lambda: next(feed) and None or ConsoleState({}), rules=[], interval=0,
                    max_iterations=1, sleep=lambda _s: None)
    log.record(event, state)
    line = json.loads(sink.getvalue().splitlines()[1])
    assert line["meters"] == {"listening": True, "summary": "on",
                              "clipped": [{"strip": "/ch/3", "count": 2, "seconds_ago": 4.0}],
                              "strips_with_signal": 2}
    assert line["unanswered"]["unasked"] == {"/ch/{n}/x": 2}


def test_every_pass_records_the_raw_aes50_words_so_a_flapping_status_is_a_timeline():
    """The S32's link light flashed red while the desk read UPD.
    The log keeps `/$stat/{A,B,C}/stat` and `dev` as the desk said them each
    pass, whatever a rule made of them."""
    def desk(stat):
        return {**CLEAN, "/$stat/A/stat": stat, "/$stat/A/dev": "S32",
                "/$stat/B/stat": "-", "/$stat/B/dev": ""}

    lines = _run([desk("UPD"), desk("OK"), desk("UPD")], CountingSink())
    passes = [line for line in lines if line["type"] == "pass"]
    assert [p["aes50"]["A"]["stat"] for p in passes] == ["UPD", "OK", "UPD"]
    assert all(p["aes50"]["A"]["dev"] == "S32" for p in passes)
    assert passes[0]["aes50"]["B"] == {"stat": "-", "dev": ""}
    assert "C" not in passes[0]["aes50"]
    assert all("aes50" not in p for p in _run([CLEAN], CountingSink()) if p["type"] == "pass")


# ---- the command ------------------------------------------------------------


def _states(tmp_path):
    paths = []
    for name, values in (("a.json", CLEAN), ("b.json", DUPLICATE)):
        (tmp_path / name).write_text(json.dumps(values))
        paths.append(str(tmp_path / name))
    return ",".join(paths)


def test_watch_writes_the_log_and_never_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-1102")
    log = tmp_path / "found.jsonl"
    main(["watch", "--state-sequence", _states(tmp_path), "--count", "2", "--interval", "0",
          "--findings-log", str(log)])
    text = log.read_text()
    assert "SECRET" not in text and "sk-ant" not in text
    lines = [json.loads(line) for line in text.splitlines()]
    assert [line["type"] for line in lines] == ["header", "pass", "pass", "footer"]
    assert lines[0]["atoo"]["version"] and lines[0]["console"] is None
    assert lines[2]["appeared"]
    assert lines[3]["reason"] == "finished"
    # Appended: a second run adds a header and passes after the first.
    main(["watch", "--state-sequence", _states(tmp_path), "--count", "1", "--interval", "0",
          "--findings-log", str(log)])
    assert [json.loads(line)["type"] for line in log.read_text().splitlines()].count("header") == 2


def test_ctrl_c_still_writes_the_footer(tmp_path, monkeypatch):
    from atoo import watch as watch_module

    real = watch_module.watch

    def interrupted(provider, **kw):
        for event in real(provider, **kw):
            yield event
            raise KeyboardInterrupt

    monkeypatch.setattr(watch_module, "watch", interrupted)
    log = tmp_path / "found.jsonl"
    main(["watch", "--state-sequence", _states(tmp_path), "--interval", "0",
          "--findings-log", str(log)])
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [line["type"] for line in lines] == ["header", "pass", "footer"]
    assert lines[-1]["reason"] == "Ctrl-C"


def test_an_unwritable_log_stops_before_the_watch_starts(tmp_path, capsys):
    code = main(["watch", "--state-sequence", _states(tmp_path), "--count", "1", "--interval", "0",
                 "--findings-log", str(tmp_path / "no" / "such" / "dir" / "log")])
    assert code == 1
    assert "--findings-log" in capsys.readouterr().err


# ---- the Watch page's "Save findings" ----------------------------


def test_the_watch_page_saves_the_session_as_the_same_log():
    pytest.importorskip("fastapi")
    import time

    from conftest import require_fastapi_testclient

    from atoo.webui import create_app

    testclient = require_fastapi_testclient()
    with testclient.TestClient(create_app()) as client:
        assert client.get("/api/watch/findings-log").status_code == 404       # nothing started yet
        page = client.get("/").text
        assert 'id="watch-save-findings"' in page and "/api/watch/findings-log" in page
        client.post("/api/console", json={"demo": True})
        assert client.post("/api/watch/start",
                           json={"source": "console", "interval": 0.05}).status_code == 200
        deadline = time.time() + 20
        lines = []
        while time.time() < deadline:
            lines = [json.loads(line) for line in client.get("/api/watch/findings-log").text.splitlines()]
            if sum(1 for line in lines if line["type"] == "pass") >= 2:
                break
            time.sleep(0.1)
        client.post("/api/watch/stop")
        response = client.get("/api/watch/findings-log")
        assert "attachment" in response.headers["content-disposition"]
        lines = [json.loads(line) for line in response.text.splitlines()]
    assert lines[0]["type"] == "header" and lines[0]["format"] == FORMAT
    assert [line["pass"] for line in lines if line["type"] == "pass"][:2] == [0, 1]
    assert lines[-1]["type"] == "footer"
