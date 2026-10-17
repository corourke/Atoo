"""Build progress you can read, and a Stop button (
"Is there any way to show progress updates from the build step or get
progressive output? It would be nice to be able to stop it if things are
going haywire.").

Three things are under test, and each against a REAL socket where the
claim is about sockets:

- **Stop ends the model call.** A stand-in model server on 127.0.0.1
  (`_StandIn`) streams slowly, with a long silent stretch first, and
  records when the client hangs up. Stopping in the silence, before the
  headers, and mid-writing must each end the call within a couple of
  seconds -- the provider's own timeout is 30s here, so a stop that only
  set a flag for the stream loop to notice would fail these by waiting.
- **A stopped build writes nothing.** Driven through `POST /api/build/run`
  and `POST /api/build/stop` against the real `atoo build`, the
  bundle is compared byte for byte, and no `.partial.json` file may appear
  anywhere. A second build afterwards runs to the end.
- **The live view is bounded and tolerant.** The tail never exceeds
  `TAIL_CHARS`; the outline of a truncated plan never raises, and its
  names are always a prefix of the finished document's.

No test here reaches a real model, and none reads a bundle under
`examples/`: the plan the stand-in streams is `tests/fixtures`'.
"""

from __future__ import annotations

import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import REAL_PLANS, require_fastapi_testclient
from atoo import generate
from atoo.ai_provider import (ApiKeyProvider, ClaudeProvider, FakeProvider,
                                   OllamaProvider, provider_from_env)
from atoo.progress import (TAIL_CHARS, BuildStopped, ModelCallProgress, StopSignal,
                                model_progress_listener, stop_scope, stopped_message)
from atoo.stream_outline import StreamOutline, outline_of

FIXTURES = Path(__file__).parent / "fixtures"
PLAN_TEXT = json.dumps({"unassigned_inputs": [],
                        **{k: v for k, v in REAL_PLANS["touringband"].items() if k != "meta"}},
                       indent=2)


# ---------------------------------------------------------------------------
# A slow model server with a long silence, that notices a hang-up
# ---------------------------------------------------------------------------


def _peer_closed(sock) -> bool:
    readable, _, _ = select.select([sock], [], [], 0)
    if not readable:
        return False
    try:
        return sock.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


class _StandIn:
    """`kind` is the wire format: "api" (OpenAI-compatible SSE), "claude"
    (Anthropic SSE) or "ollama" (NDJSON). `header_delay` is silence BEFORE
    the response headers (a local model loading); `gap` is silence after
    them (thinking). Events land in `self.events`, in order."""

    def __init__(self, kind="api", *, text=PLAN_TEXT, header_delay=0.0, gap=0.0,
                 chunk=60, delay=0.02, replies=None, mid_usage=False):
        self.kind, self.text = kind, text
        # "claude" only: a message_delta with the CUMULATIVE output count
        # after every chunk, as the Messages API may send mid-stream.
        self.mid_usage = mid_usage
        self.header_delay, self.gap, self.chunk, self.delay = header_delay, gap, chunk, delay
        self.replies = replies or {}
        self.events: list[str] = []
        self.requests: list[dict] = []
        self._done = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer._serve(self, body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self._done.set()
        self.server.shutdown()
        self.server.server_close()

    def wait_for(self, event: str, timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(e.startswith(event) for e in self.events):
                return
            time.sleep(0.01)
        raise AssertionError(f"the stand-in never reached {event!r}: {self.events}")

    def _silence(self, handler, seconds: float, name: str) -> bool:
        """Wait `seconds`, watching for a hang-up. False if the client left."""
        self.events.append(name)
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._done.is_set():
            if _peer_closed(handler.connection):
                self.events.append(f"closed in {name}")
                return False
            time.sleep(0.01)
        return True

    def _reply_for(self, body) -> str:
        system = body.get("system") or body["messages"][0]["content"]
        for marker, reply in self.replies.items():
            if system == marker:
                return reply
        return self.text

    def _serve(self, handler, body):
        text = self._reply_for(body)
        if self.header_delay and not self._silence(handler, self.header_delay, "before headers"):
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "application/x-ndjson" if self.kind == "ollama"
                            else "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()

        def send(line: str):
            data = line.encode()
            handler.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            handler.wfile.flush()

        def sse(obj):
            send(f"data: {json.dumps(obj) if not isinstance(obj, str) else obj}\n\n")

        try:
            if self.kind == "api":
                sse({"choices": [{"delta": {"role": "assistant"}}]})
            elif self.kind == "claude":
                sse({"type": "message_start", "message": {"usage": {"input_tokens": 100}}})
                sse({"type": "content_block_start", "index": 0,
                     "content_block": {"type": "thinking", "thinking": ""}})
            if self.gap and not self._silence(handler, self.gap, "gap"):
                return
            if self.kind == "claude":
                sse({"type": "content_block_start", "index": 1,
                     "content_block": {"type": "text", "text": ""}})
            self.events.append("writing")
            for i in range(0, len(text), self.chunk):
                if _peer_closed(handler.connection) or self._done.is_set():
                    self.events.append(f"closed while writing at {i}")
                    return
                piece = text[i:i + self.chunk]
                if self.kind == "api":
                    sse({"choices": [{"delta": {"content": piece}}]})
                elif self.kind == "claude":
                    sse({"type": "content_block_delta", "index": 1,
                         "delta": {"type": "text_delta", "text": piece}})
                    if self.mid_usage:
                        sse({"type": "message_delta", "delta": {},
                             "usage": {"output_tokens": 5000 + i}})
                else:
                    send(json.dumps({"message": {"content": piece}, "done": False}) + "\n")
                time.sleep(self.delay)
            if self.kind == "api":
                sse({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
                sse("[DONE]")
            elif self.kind == "claude":
                sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                     "usage": {"output_tokens": 50}})
                sse({"type": "message_stop"})
            else:
                send(json.dumps({"message": {"content": ""}, "done": True,
                                 "done_reason": "stop", "eval_count": 50}) + "\n")
            handler.wfile.write(b"0\r\n\r\n")
            handler.wfile.flush()
            self.events.append("completed")
        except (BrokenPipeError, ConnectionResetError):
            self.events.append("closed while writing (broken pipe)")


@pytest.fixture
def standin():
    made = []

    def make(*args, **kwargs):
        server = _StandIn(*args, **kwargs)
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


def _provider(kind: str, url: str):
    # A 30s socket timeout: a stop that waited for the read to time out
    # would blow every "within 3 seconds" below.
    if kind == "api":
        return ApiKeyProvider(api_key="k", model="standin", base_url=url, timeout=30,
                              show_progress=False)
    if kind == "claude":
        return ClaudeProvider(api_key="k", model="standin", base_url=url, timeout=30,
                              show_progress=False)
    return OllamaProvider(model="standin", base_url=url, timeout=30, num_ctx=8192,
                          show_progress=False)


def _call_in_thread(provider, signal):
    """`provider.complete` in a thread under `signal`, as the web UI's
    build runner makes it. Returns (thread, outcome dict, snapshots)."""
    outcome: dict = {}
    seen: list[dict] = []

    def run():
        try:
            with stop_scope(signal), model_progress_listener(seen.append):
                outcome["text"] = provider.complete(system="s", user="u", label="generator")
        except BaseException as exc:  # noqa: BLE001 -- the outcome IS the test
            outcome["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome, seen


# ---------------------------------------------------------------------------
# Stop ends the model call -- per provider, per moment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind, moment", [
    ("api", "gap"), ("api", "before headers"), ("api", "writing"),
    ("claude", "gap"), ("claude", "writing"),
    ("ollama", "before headers"), ("ollama", "writing"),
])
def test_stop_ends_the_call_and_closes_the_connection(standin, kind, moment):
    """The call ends within a couple of seconds whatever it was doing --
    including the silent stretch, where the stream loop is blocked in a
    read and has nothing to notice a flag with -- and the SERVER sees the
    hang-up. That is what stops the spend: a request abandoned in a
    thread would run on, and bill, to the end."""
    server = standin(kind, header_delay=20 if moment == "before headers" else 0,
                     gap=20 if moment == "gap" else 0,
                     delay=0.05 if moment == "writing" else 0.0)
    if kind == "ollama":
        # Ollama is asked for its context ceiling first; answer nothing
        # useful (a 501 is "unknown"), which is today's fallback.
        pass
    signal = StopSignal()
    thread, outcome, seen = _call_in_thread(_provider(kind, server.url), signal)
    server.wait_for(moment)
    if moment == "writing":
        time.sleep(0.3)   # some text has arrived
    started = time.monotonic()
    signal.stop()
    thread.join(3.0)
    assert not thread.is_alive(), "the call was still running 3s after Stop"
    assert time.monotonic() - started < 3.0
    assert isinstance(outcome.get("exc"), BuildStopped), outcome
    assert "text" not in outcome, "a stopped call must never return text"
    server.wait_for("closed", timeout=3.0)
    assert seen and seen[-1]["stage"] == "stopped"


def test_claude_reports_the_real_running_count_and_it_is_true_at_stop(standin):
    """`message_delta`'s usage is cumulative: mid-call the snapshot takes
    the real output count, not the character estimate, and the count at
    the moment of Stop is the real one."""
    server = standin("claude", chunk=40, delay=0.03, mid_usage=True)
    signal = StopSignal()
    thread, outcome, seen = _call_in_thread(_provider("claude", server.url), signal)
    server.wait_for("writing")
    deadline = time.time() + 5
    while time.time() < deadline and not any(
            s.get("stage") == "writing" and s.get("estimated") is False for s in seen):
        time.sleep(0.05)
    live = [s for s in seen if s.get("stage") == "writing" and s.get("estimated") is False]
    assert live, "no mid-call snapshot carried the provider's own count"
    assert live[-1]["total_output_tokens"] >= 5000
    signal.stop()
    thread.join(3.0)
    assert isinstance(outcome.get("exc"), BuildStopped)
    end = seen[-1]
    assert end["stage"] == "stopped" and end["estimated"] is False
    assert end["total_output_tokens"] >= live[-1]["total_output_tokens"]


def test_the_claude_request_asks_for_text_not_tools(standin):
    """The plan arrives as `text_delta`, not as tool arguments: the request
    carries no tools, so eager tool-input streaming does not apply."""
    server = standin("claude", text="{}", chunk=10)
    thread, outcome, _ = _call_in_thread(_provider("claude", server.url), StopSignal())
    thread.join(5.0)
    assert outcome.get("text") == "{}"
    assert "tools" not in server.requests[0] and "tool_choice" not in server.requests[0]
    assert server.requests[0]["stream"] is True


def test_a_call_started_after_the_stop_never_reaches_the_server(standin):
    server = standin("api")
    signal = StopSignal()
    signal.stop()
    thread, outcome, _ = _call_in_thread(_provider("api", server.url), signal)
    thread.join(3.0)
    assert isinstance(outcome.get("exc"), BuildStopped)
    assert server.requests == []


def test_without_a_stop_signal_the_call_completes_unchanged(standin):
    """The stoppable path is only taken under a stop signal; with one that
    is never fired, a call streams to the end as before."""
    server = standin("api", text='{"channels": []}', chunk=4)
    thread, outcome, seen = _call_in_thread(_provider("api", server.url), StopSignal())
    thread.join(5.0)
    assert outcome.get("text") == '{"channels": []}'
    assert seen[-1]["stage"] == "done"


def test_a_stop_is_not_swallowed_by_the_critic_or_the_watchlist_draft():
    """Both catch `Exception` so a failed pass never stops a build. A stop
    is not a failed pass: it must get past them, or the build carries on
    and writes plan.json."""
    signal = StopSignal()
    signal.stop()
    with stop_scope(signal):
        with pytest.raises(BuildStopped):
            generate.critique_plan("conv", "csv", {"channels": []}, provider=FakeProvider(response="{}"))
        with pytest.raises(BuildStopped):
            generate.draft_watch_conditions({"channels": []}, "conv",
                                            provider=FakeProvider(response="{}"))


def test_the_fake_provider_stops_mid_stream_too():
    signal = StopSignal()
    provider = FakeProvider(response="x" * 100, stream_chunks=50, chunk_delay=0.05)
    thread, outcome, seen = _call_in_thread(provider, signal)
    time.sleep(0.3)
    signal.stop()
    thread.join(2.0)
    assert isinstance(outcome.get("exc"), BuildStopped)
    assert seen[-1]["stage"] == "stopped"


# ---------------------------------------------------------------------------
# The live view: bounded, tolerant
# ---------------------------------------------------------------------------


def test_the_tail_is_bounded():
    progress = ModelCallProgress("generator", "m", enabled=False, listener=None, ticker=False)
    for i in range(400):
        progress.add_text(25, f"{i:04d}-" + "y" * 20)
    tail = progress.snapshot()["tail"]
    assert len(tail) == TAIL_CHARS
    assert tail.endswith("0399-" + "y" * 20)
    assert progress.snapshot()["output_chars"] == 400 * 25, "the count is still the whole reply"


def test_the_thinking_line_is_the_latest_line_and_bounded():
    progress = ModelCallProgress("generator", "m", enabled=False, listener=None, ticker=False)
    progress.add_thinking(10, "**Reading the input list**\n\nFirst pass.\n")
    progress.add_thinking(10, "**Putting the horns on DCA Vocals**\n")
    assert progress.snapshot()["thinking_line"] == "Putting the horns on DCA Vocals"
    progress.add_thinking(1000, "z" * 1000)
    assert len(progress.snapshot()["thinking_line"]) <= 240


def test_the_outline_of_a_truncated_plan_never_raises_and_only_grows():
    """Every prefix of a real plan, cut anywhere -- mid-key, mid-escape,
    mid-number: no exception, and each part's names so far are the start
    of the finished document's."""
    text = "Here is the plan:\n```json\n" + PLAN_TEXT + "\n```"
    final = {part["name"]: part for part in outline_of(text)["sections"]}
    assert set(final) >= {"channels", "busses", "dcas"}
    assert final["channels"]["count"] == len(REAL_PLANS["touringband"]["channels"])
    assert final["busses"]["names"][:3] == list(REAL_PLANS["touringband"]["busses"])[:3]
    for cut in range(0, len(text), 11):
        outline = outline_of(text[:cut])
        if outline is None:
            continue
        for part in outline["sections"]:
            whole = final[part["name"]]["names"]
            assert whole[:len(part["names"])] == part["names"] or \
                part["count"] > len(part["names"]), (cut, part)


def test_the_outline_reads_the_item_being_written():
    cut = PLAN_TEXT.index('"bus_sends"', PLAN_TEXT.index('"name": "F VOX 1"'))
    item = outline_of(PLAN_TEXT[:cut + 40])["item"]
    assert item["section"] == "channels" and item["name"] == "F VOX 1"
    assert item["field"] == "bus_sends"


def test_the_outline_is_the_same_in_chunks_as_whole():
    streamed = StreamOutline()
    for i in range(0, len(PLAN_TEXT), 7):
        streamed.feed(PLAN_TEXT[i:i + 7])
    assert streamed.snapshot() == outline_of(PLAN_TEXT)


@pytest.mark.parametrize("text", ["", "no json here", '{"a": "\\u00', '{"x": [1, 2, {"y"',
                                  '}}}]]]', '{"channels": [{"name": "Kick\\"s'])
def test_the_outline_tolerates_anything(text):
    outline_of(text)
    StreamOutline().feed(text)


def test_the_outline_is_small_enough_to_poll():
    big = {"channels": [{"name": f"Channel number {i} " + "w" * 80} for i in range(500)]}
    snap = outline_of(json.dumps(big))
    assert len(json.dumps(snap)) < 6000


# ---------------------------------------------------------------------------
# Thinking summaries (a judgement call, announced, and switchable off)
# ---------------------------------------------------------------------------


def _claude_payload(monkeypatch, capsys, **kwargs):
    import io

    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(req, timeout=None):
        sent.update(json.loads(req.data))
        return Resp(b'data: {"type": "content_block_delta", "delta": '
                    b'{"type": "text_delta", "text": "ok"}}\n\n'
                    b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}\n\n')

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)
    provider = ClaudeProvider(api_key="k", **kwargs)
    provider.complete(system="s", user="u")
    provider.complete(system="s", user="u")
    return sent, capsys.readouterr().err


def test_thinking_summaries_are_requested_and_not_announced(monkeypatch, capsys):
    """Requested by default -- and, being the default, not printed
    (FR-X.15c, 2026-09-30: a header INFO line that says nothing actionable
    is noise). ATOO_AI_THINKING_SUMMARIES=0 still turns it off (tested
    below)."""
    sent, err = _claude_payload(monkeypatch, capsys)
    assert sent["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "INFO thinking summaries requested" not in err
    assert "INFO thinking" not in err


def test_a_summary_is_shown_as_the_thinking_line_and_never_counted():
    """A summary is a few sentences for minutes of reasoning: counting its
    characters as thinking tokens would understate the spend a hundredfold.
    It is the line the page shows; the count stays unknown until the
    usage arrives."""
    progress = ModelCallProgress("generator", "m", enabled=False, listener=None,
                                 ticker=False)
    progress.add_thinking_summary("**Checking the busses**\n\nThe conventions ask for six.")
    snap = progress.snapshot()
    assert snap["thinking_line"] == "The conventions ask for six."
    assert snap["thinking_tokens"] is None and snap["thinking_chars"] == 0
    assert snap["stage"] == "thinking"
    assert "The conventions ask for six." in progress.line()


def test_claude_feeds_summaries_to_the_thinking_line(monkeypatch):
    import io

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    raw = b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in [
        {"type": "content_block_start", "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta",
         "delta": {"type": "thinking_delta", "thinking": "Laying out the horns."}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "{}"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 4000}},
    ])
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: Resp(raw))
    seen = []
    with model_progress_listener(seen.append):
        ClaudeProvider(api_key="k", show_progress=False).complete(system="s", user="u")
    end = seen[-1]
    assert end["thinking_line"] == "Laying out the horns."
    assert end["thinking_chars"] == 0, "a summary is not the thinking's size"
    assert end["thinking_tokens"] > 3900, "the real spend comes from the usage"


def test_thinking_summaries_can_be_turned_off(monkeypatch, capsys):
    monkeypatch.setenv("ATOO_AI_PROVIDER", "claude")
    monkeypatch.setenv("ATOO_AI_API_KEY", "k")
    monkeypatch.setenv("ATOO_AI_THINKING_SUMMARIES", "0")
    assert provider_from_env().thinking_summaries is False
    sent, err = _claude_payload(monkeypatch, capsys, thinking_summaries=False)
    assert "thinking" not in sent
    assert "INFO thinking summaries" not in err


def test_thinking_summaries_are_not_forced_on_a_model_that_would_think_differently(
        monkeypatch, capsys):
    """Where omitting `thinking` means no thinking, sending it would turn
    thinking on -- a change in cost, not in display. Not sent; said."""
    sent, err = _claude_payload(monkeypatch, capsys, model="an-older-claude-model")
    assert "thinking" not in sent
    assert "INFO thinking summaries not requested" in err


def test_the_api_stream_setting_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ATOO_AI_PROVIDER", "api")
    monkeypatch.setenv("ATOO_AI_API_KEY", "k")
    assert provider_from_env().stream is True
    monkeypatch.setenv("ATOO_AI_STREAM", "off")
    assert provider_from_env().stream is False


# ---------------------------------------------------------------------------
# The whole of it: `POST /api/build/stop` against the real `atoo build`
# ---------------------------------------------------------------------------

fastapi_testclient = require_fastapi_testclient()

HOUSE = "# house-rules.md\n\n## Inputs\nPatch input sockets per the input list.\n"


def _bundle(tmp_path) -> Path:
    directory = tmp_path / "show"
    directory.mkdir()
    (directory / "input.csv").write_text((FIXTURES / "touringband.csv").read_text())
    (directory / "watch.json").write_text(json.dumps({"watch_conditions": [{
        "id": "Kick", "description": "Kick", "channel": "Kick", "field": "muted",
        "operator": "==", "value": True, "severity": "warning"}]}, indent=2) + "\n")
    return directory


def _bytes(directory: Path) -> dict:
    """Every file's bytes, EXCEPT `builds/` -- an earlier change: a stop (or
    a failure) now writes its own build-log file there on purpose
    (`_write_build_log`'s `STOPPED`/`FAILED`), so it is the one thing "a
    stopped build writes nothing" no longer means. `plan.json`,
    `watch.json` and everything else in the bundle are still covered."""
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in sorted(directory.rglob("*"))
            if p.is_file() and "builds" not in p.relative_to(directory).parts}


def _wait(c, predicate, timeout=15.0):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = c.get("/api/build/status").json()
        if predicate(status):
            return status
        time.sleep(0.05)
    raise AssertionError(f"timed out; last status: {json.dumps(status)[:2000]}")


@pytest.fixture
def stop_app(tmp_path, monkeypatch, standin):
    """A shell on a copy-made bundle, whose builds talk to a stand-in."""
    from atoo.webui import create_app

    server = standin("api", replies={
        generate.critic_system(): json.dumps({"findings": []}),
        generate.watchlist_system(): json.dumps({"watch_conditions": []}),
    })
    monkeypatch.setenv("ATOO_AI_PROVIDER", "api")
    monkeypatch.setenv("ATOO_AI_API_KEY", "k")
    monkeypatch.setenv("ATOO_AI_MODEL", "standin")
    monkeypatch.setenv("ATOO_AI_BASE_URL", server.url)
    directory = _bundle(tmp_path)
    house = tmp_path / "house-rules.md"
    house.write_text(HOUSE)
    app = create_app(initial_bundle=str(directory), initial_conventions=str(house))
    with fastapi_testclient.TestClient(app) as c:
        yield c, server, directory


def _assert_stopped_and_untouched(c, server, directory, before, tmp_path):
    status = _wait(c, lambda s: s["state"] != "running")
    assert status["state"] == "stopped", status["log"]
    assert status["exit_code"] == 130
    assert status["findings"] == [], "a stop is not a failure finding"
    message = status["stopped"]["message"]
    assert message.startswith("Stopped by you after ")
    assert message.endswith("Nothing was written to the show; plan.json is unchanged.")
    assert status["stopped"]["changed"] == []
    assert _bytes(directory) == before, "a stopped build left the bundle changed"
    assert not list(tmp_path.rglob("*.partial*")), "a stop must not save a partial reply"
    assert not Path("generation.partial.json").exists()
    server.wait_for("closed", timeout=3.0)
    assert any("Stopped by you" in line for line in status["log"])
    return status


def test_stop_in_the_silent_stretch_writes_nothing(stop_app, tmp_path):
    c, server, directory = stop_app
    server.gap = 30
    before = _bytes(directory)
    assert c.post("/api/build/run", json={"console_model": "wing-compact"}).status_code == 200
    server.wait_for("gap")
    r = c.post("/api/build/stop", json={"expected_bundle": str(directory)})
    assert r.status_code == 200 and r.json()["stop_requested"] is True
    started = time.monotonic()
    status = _assert_stopped_and_untouched(c, server, directory, before, tmp_path)
    assert time.monotonic() - started < 5
    assert status["progress"]["stage"] == "stopped"


def test_stop_mid_writing_writes_nothing_and_the_live_view_had_names(stop_app, tmp_path):
    c, server, directory = stop_app
    server.delay = 0.05
    before = _bytes(directory)
    c.post("/api/build/run", json={"console_model": "wing-compact"})
    def channels(status):
        outline = (status["progress"] or {}).get("outline") or {}
        parts = {part["name"]: part for part in outline.get("sections") or []}
        return parts.get("channels", {}).get("names", [])

    live = _wait(c, lambda s: len(channels(s)) >= 3)
    names = channels(live)
    assert names[:3] == [ch["name"] for ch in REAL_PLANS["touringband"]["channels"][:3]]
    assert 0 < len(live["progress"]["tail"]) <= TAIL_CHARS
    assert c.post("/api/build/stop", json={}).status_code == 200
    _assert_stopped_and_untouched(c, server, directory, before, tmp_path)


def test_a_build_after_a_stop_runs_to_the_end(stop_app, tmp_path):
    c, server, directory = stop_app
    server.gap = 30
    c.post("/api/build/run", json={"console_model": "wing-compact"})
    server.wait_for("gap")
    c.post("/api/build/stop")
    _wait(c, lambda s: s["state"] == "stopped")

    server.gap = 0
    server.delay = 0
    assert c.post("/api/build/run", json={"console_model": "wing-compact"}).status_code == 200
    status = _wait(c, lambda s: s["state"] != "running")
    assert status["state"] == "done", status["log"]
    assert status["stopped"] is None and status["stop_requested"] is False
    assert (directory / "plan.json").is_file()


def test_stop_with_nothing_running_is_a_409(stop_app):
    c, _, _ = stop_app
    r = c.post("/api/build/stop")
    assert r.status_code == 409
    assert r.json()["error"] == "no build is running -- nothing to stop"


def test_stop_from_a_page_showing_another_bundle_is_refused(stop_app, tmp_path):
    c, server, directory = stop_app
    server.gap = 30
    c.post("/api/build/run", json={"console_model": "wing-compact"})
    server.wait_for("gap")
    r = c.post("/api/build/stop", json={"expected_bundle": str(tmp_path / "elsewhere")})
    assert r.status_code == 409 and r.json()["stale"] == "bundle"
    assert c.get("/api/build/status").json()["state"] == "running"
    c.post("/api/build/stop")
    _wait(c, lambda s: s["state"] == "stopped")


def test_stop_answers_this_machine_only(stop_app):
    """The same `_setup_only`
    refusal every other Setup write gives a machine on the LAN."""
    from atoo.webui import create_app

    with fastapi_testclient.TestClient(create_app(), client=("203.0.113.20", 5000),
                                       headers={"host": "203.0.113.5:8420"}) as phone:
        r = phone.post("/api/build/stop")
    assert r.status_code == 403
    assert "answers only" in r.json()["error"]


def test_the_page_offers_stop_and_the_live_view():
    """The Python suite cannot see the browser; this is the crude guard
    between a renamed field and a silently blank live view."""
    from atoo.webui import create_app

    with fastapi_testclient.TestClient(create_app()) as c:
        js = c.get("/static/setup.js").text
        html = c.get("/").text
    for needle in ("/api/build/stop", "run-stop-btn", "stop_requested", "run.stopped",
                   "p.outline", "p.tail", "p.thinking_line", "run-live-tail"):
        assert needle in js, needle
    for needle in ('id="run-stop-btn"', 'id="run-stopped"', 'id="run-live"',
                   'id="run-live-tail"', 'id="run-live-sections"'):
        assert needle in html, needle


def test_the_model_output_is_folded_closed_by_default():
    """The default view is the
    latest message, in a box held at two lines; what the model has
    written is a closed <details>, like Raw output."""
    import re

    from atoo.webui import create_app

    with fastapi_testclient.TestClient(create_app()) as c:
        html = c.get("/").text
        css = c.get("/static/styles.css").text
        js = c.get("/static/setup.js").text
    written = re.search(r'<details[^>]*id="run-live-written"[^>]*>', html)
    assert written and " open" not in written.group(0)
    # The name list lives inside the fold, not beside it.
    fold = html[written.start():html.index("</details>", written.start())]
    assert 'id="run-live-sections"' in fold
    raw = re.search(r'<details[^>]*id="run-live-raw"[^>]*>', html)
    assert raw and " open" not in raw.group(0)
    # Both message lines sit in the fixed box, and the box is two lines tall.
    last = html[html.index('id="run-live-last"'):written.start()]
    assert 'id="run-live-thinking"' in last and 'id="run-live-now"' in last
    assert re.search(r"\.run-live-last\s*\{[^}]*(?<![-\w])height:\s*calc\(2 \* 1\.4em\)", css)
    assert "run-live-written-summary" in js


# ---------------------------------------------------------------------------
# The terminal: Ctrl-C says the same thing, without a traceback
# ---------------------------------------------------------------------------


def test_ctrl_c_during_a_build_is_a_clean_stop(tmp_path, monkeypatch, capsys):
    from atoo.cli import main

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: object())
    monkeypatch.setattr("atoo.generate.generate_plan", interrupted)
    directory = _bundle(tmp_path)
    house = tmp_path / "house-rules.md"
    house.write_text(HOUSE)
    before = _bytes(directory)
    code = main(["build", "--show", str(directory), "--conventions", str(house),
                 "--console-model", "wing-compact"])
    err = capsys.readouterr().err
    assert code == 130
    assert "Stopped by you (Ctrl-C) after" in err
    assert "Nothing was written to the show; plan.json is unchanged." in err
    assert "Traceback" not in err
    assert _bytes(directory) == before
    # A stop this early (before any plan, so nothing to hang
    # a pointer on) still gets its own build-log file, with the outcome.
    logs = list((directory / "builds").glob("*.json"))
    assert len(logs) == 1
    logged = json.loads(logs[0].read_text())
    assert logged["outcome"] == {"status": "stopped", "reason": "Ctrl-C"}


def test_a_stop_after_the_last_model_call_still_writes_nothing(tmp_path, monkeypatch,
                                                               stub_build, capsys):
    """Stop pressed while the build verifies -- after the generator's
    call, before plan.json is written. No model call is left to raise it,
    so the write itself checks."""
    from atoo import cli

    stub_build("touringband")
    signal = StopSignal()
    real_verify = cli.verify_plan

    def verify_then_stop(*args, **kwargs):
        signal.stop()
        return real_verify(*args, **kwargs)

    monkeypatch.setattr("atoo.cli.verify_plan", verify_then_stop)
    directory = _bundle(tmp_path)
    house = tmp_path / "house-rules.md"
    house.write_text(HOUSE)
    before = _bytes(directory)
    with stop_scope(signal):
        code = cli.main(["build", "--show", str(directory), "--conventions", str(house),
                         "--console-model", "wing-compact"])
    assert code == 130
    assert "Nothing was written to the show; plan.json is unchanged." in capsys.readouterr().err
    assert _bytes(directory) == before
    # Stopped after the last model call, before plan.json --
    # still gets its own build-log file (reason "stopped by you", the
    # `BuildStopped` default message).
    logs = list((directory / "builds").glob("*.json"))
    assert len(logs) == 1
    logged = json.loads(logs[0].read_text())
    assert logged["outcome"] == {"status": "stopped", "reason": "stopped by you"}


def test_the_stop_sentence_says_what_did_land():
    assert stopped_message(134, []) == ("Stopped by you after 2m 14s. Nothing was written to the show; "
                                        "plan.json is unchanged.")
    assert stopped_message(5, ["plan.json"]).endswith(
        "plan.json was already written before the stop; nothing else was changed.")
