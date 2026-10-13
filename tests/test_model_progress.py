"""Progress while a model call runs (the maintainer, 2026-09-25: "Show me progress
while build is running").

A real build in the Setup UI printed a "sending" line and then nothing for
several minutes: the provider's progress only ran on a terminal, and the
page's build log is not one. These tests pin what replaced it --
`progress.ModelCallProgress` -- without calling any model:

- the stream loop only COUNTS; everything visible happens on a tick, so
  a thousand deltas are not a thousand writes;
- a pipe gets sparse plain lines (a stage change, or the interval), a
  terminal one redrawn line, and a listener a structured snapshot;
- thinking that is not streamed (the default on current Claude models)
  is reported as unknown until the call ends, not as zero;
- each provider feeds it from its own stream shape.
"""

from __future__ import annotations

import io
import json
import threading

import pytest

from atoo import progress as progress_mod
from atoo.ai_provider import (
    CHARS_PER_TOKEN,
    ApiKeyProvider,
    ClaudeProvider,
    FakeProvider,
    OllamaProvider,
)
from atoo.progress import (
    ModelCallProgress,
    _pipe_interval,
    current_model_listener,
    model_progress_listener,
)


class Stream(io.StringIO):
    def __init__(self, isatty=False):
        super().__init__()
        self._isatty = isatty
        self.writes: list[str] = []

    def isatty(self):
        return self._isatty

    def write(self, text):
        self.writes.append(text)
        return super().write(text)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(stream=None, clock=None, **kw):
    kw.setdefault("ticker", False)
    kw.setdefault("listener", None)
    return ModelCallProgress("generator", "claude-sonnet-5",
                             stream=stream if stream is not None else Stream(),
                             clock=clock or Clock(), wall=lambda: 5000.0,
                             chars_per_token=CHARS_PER_TOKEN, **kw)


# ---- cadence -----------------------------------------------------------


def test_the_stream_loop_only_counts_it_never_writes():
    """The whole reason for the ticker: per-token output is what a log of
    carriage returns -- or a page log flooded with lines -- is made of."""
    out = Stream()
    p = make(out)
    before = len(out.writes)
    for _ in range(5000):
        p.add_text(3)
    assert len(out.writes) == before, "a delta wrote something; only tick() may"
    assert p.text_chars == 15000


def test_a_pipe_gets_a_line_on_a_stage_change_and_then_on_the_interval():
    out, clock = Stream(isatty=False), Clock()
    p = make(out, clock)
    assert out.getvalue().splitlines() == [
        "claude-sonnet-5 (generator): sending, waiting for the first reply... "
        "(a progress line every 10-60s -- stderr is not a terminal)"]

    # Ticking twice a second for 9.5s while waiting: nothing new yet.
    for _ in range(19):
        clock.now += 0.5
        p.tick()
    assert len(out.getvalue().splitlines()) == 1

    clock.now += 0.5          # 10s: the interval line
    p.tick()
    assert out.getvalue().splitlines()[-1] == \
        "  claude-sonnet-5 (generator): waiting for the first reply -- 10s"

    p.thinking_started()      # a stage change is news at once
    clock.now += 0.5
    p.tick()
    assert out.getvalue().splitlines()[-1] == \
        "  claude-sonnet-5 (generator): thinking -- 10s, not streamed (counted when the call ends)"

    lines_before = len(out.getvalue().splitlines())
    for _ in range(40):       # another 20s, ticking every 0.5s
        clock.now += 0.5
        p.tick()
    # 10s interval in the first minute: two more lines, not forty.
    assert len(out.getvalue().splitlines()) - lines_before == 2
    assert "\r" not in out.getvalue()


def test_the_pipe_interval_widens_as_the_call_runs():
    """About 14 lines for a five-minute hosted build, about 54 for a
    forty-minute local one -- inside the 200 the page keeps."""
    assert _pipe_interval(5) == 10.0
    assert _pipe_interval(120) == 30.0
    assert _pipe_interval(900) == 60.0

    out, clock = Stream(isatty=False), Clock()
    p = make(out, clock)
    p.thinking_started()
    for _ in range(40 * 60 * 2):  # forty minutes of ticks
        clock.now += 0.5
        p.tick()
    lines = out.getvalue().splitlines()
    assert 40 <= len(lines) <= 70, len(lines)


def test_a_terminal_line_never_wraps(monkeypatch):
    """A wrapped line cannot be redrawn with a carriage return; every tick
    would leave a copy behind."""
    monkeypatch.setenv("COLUMNS", "40")
    out, clock = Stream(isatty=True), Clock()
    p = make(out, clock)
    p.thinking_started()
    clock.now += 0.5
    p.tick()
    drawn = out.writes[-1]
    assert drawn.startswith("\r") and len(drawn) - 1 <= 39


def test_a_terminal_gets_one_redrawn_line_and_it_is_cleared_at_the_end(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    out, clock = Stream(isatty=True), Clock()
    p = make(out, clock)
    assert out.getvalue() == "claude-sonnet-5 (generator): sending, waiting for the first reply...\n"
    p.add_text(3400)
    for _ in range(6):
        clock.now += 0.5
        p.tick()
    body = out.getvalue().split("\n", 1)[1]
    assert "\n" not in body, "a terminal line is redrawn, never appended"
    assert body.count("\r") == 6
    assert "writing -- 3s, ~1,000 tokens of output so far" in body
    p.finish()
    assert out.getvalue().endswith("\r")
    assert out.getvalue().rstrip("\r").endswith(" ")


def test_disabled_writes_nothing_but_still_tells_a_listener():
    """`show_progress=False` silences stderr; the Setup UI's listener is a
    separate consumer and still hears about the call."""
    out, seen = Stream(), []
    p = make(out, enabled=False, listener=seen.append)
    p.add_text(10)
    p.tick()
    p.finish()
    assert out.getvalue() == ""
    assert [e["event"] for e in seen] == ["start", "update", "end"]


# ---- the snapshot -------------------------------------------------------


def test_thinking_that_is_not_streamed_is_unknown_not_zero():
    """With display omitted a thinking block streams with empty text. Zero
    would be a false number; None says "counted when the call ends"."""
    seen = []
    p = make(listener=seen.append)
    assert seen[-1]["stage"] == "waiting" and seen[-1]["thinking_tokens"] == 0
    p.thinking_started()
    p.tick()
    snap = seen[-1]
    assert snap["stage"] == "thinking"
    assert snap["thinking_tokens"] is None
    assert snap["thinking_streamed"] is False
    assert snap["estimated"] is True

    p.add_text(int(1000 * CHARS_PER_TOKEN))
    p.finish(usage={"input_tokens": 17830, "output_tokens": 57615})
    end = seen[-1]
    assert end["event"] == "end" and end["stage"] == "done"
    assert end["estimated"] is False
    assert end["input_tokens"] == 17830
    assert end["total_output_tokens"] == 57615
    assert end["output_tokens"] == 1000
    assert end["thinking_tokens"] == 56615


def test_streamed_thinking_is_counted_as_it_arrives():
    seen = []
    p = make(listener=seen.append)
    p.add_thinking(int(500 * CHARS_PER_TOKEN))
    p.tick()
    assert seen[-1]["stage"] == "thinking"
    assert seen[-1]["thinking_tokens"] == 500
    assert seen[-1]["thinking_streamed"] is True


def test_a_failed_call_ends_failed_and_finish_is_idempotent():
    seen = []
    p = make(listener=seen.append)
    p.finish(ok=False)
    p.finish(ok=True)
    assert [e["event"] for e in seen] == ["start", "end"]
    assert seen[-1]["stage"] == "failed"


def test_a_listener_that_raises_costs_the_display_not_the_call():
    def boom(_event):
        raise RuntimeError("the page went away")

    p = make(listener=boom)
    p.add_text(5)
    p.tick()
    p.finish()


# ---- the listener's scope and the ticker --------------------------------


def test_the_listener_is_this_threads_and_nobody_elses():
    """The server runs a build in one worker thread while a watch loop
    runs in another; only the build's calls are the build's progress."""
    seen, other = [], []

    def elsewhere():
        other.append(current_model_listener())

    with model_progress_listener(seen.append):
        assert current_model_listener() is not None
        t = threading.Thread(target=elsewhere)
        t.start()
        t.join()
        p = ModelCallProgress("critic", "m", stream=Stream(), ticker=False)
        p.finish()
    assert other == [None]
    assert current_model_listener() is None
    assert [e["label"] for e in seen] == ["critic", "critic"]


def test_the_ticker_keeps_time_moving_while_the_socket_is_silent(monkeypatch):
    """No delta arrives for minutes during unstreamed thinking; the ticker
    is what keeps reporting then."""
    monkeypatch.setattr(progress_mod, "MODEL_TICK", 0.01)
    seen = []
    done = threading.Event()

    def listen(event):
        seen.append(event)
        if event["event"] == "update" and len(seen) > 5:
            done.set()

    p = ModelCallProgress("generator", "m", stream=Stream(), listener=listen)
    p.thinking_started()
    assert done.wait(5), "the ticker never ticked"
    p.finish()
    assert seen[-1]["event"] == "end"
    count = len(seen)
    threading.Event().wait(0.05)
    assert len(seen) == count, "the ticker kept running after finish()"


def test_the_ticker_writes_where_the_calling_thread_would(monkeypatch):
    """The web UI routes a build's stderr by thread; the ticker's own
    thread must still reach the build's log (`for_current_thread`)."""
    monkeypatch.setattr(progress_mod, "MODEL_TICK", 0.01)
    captured = Stream()

    class Routed:
        def isatty(self):
            return False

        def write(self, text):
            raise AssertionError("written through the router, not the resolved stream")

        def flush(self):
            pass

        def for_current_thread(self):
            return captured

    p = ModelCallProgress("generator", "m", stream=Routed(), listener=None)
    p.thinking_started()
    for _ in range(200):
        if "thinking" in captured.getvalue():
            break
        threading.Event().wait(0.01)
    p.finish()
    assert "m (generator): thinking -- 0s" in captured.getvalue()


# ---- the providers feed it ----------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _sse(*events) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def test_claude_reports_thinking_from_the_block_start_and_the_real_spend_at_the_end(monkeypatch):
    """Display omitted: the thinking block has no text, only a start. The
    usage block at the end is what says how much it cost."""
    raw = _sse(
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 120}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "abc"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": "x" * 340}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 900}},
    )
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    seen = []
    with model_progress_listener(seen.append):
        ClaudeProvider(api_key="k", model="claude-sonnet-5",
                       show_progress=False).complete(system="s", user="u", label="generator")
    end = seen[-1]
    assert end["event"] == "end" and end["stage"] == "done"
    assert end["label"] == "generator" and end["model"] == "claude-sonnet-5"
    assert end["thinking_seen"] is True and end["thinking_streamed"] is False
    assert end["input_tokens"] == 120 and end["total_output_tokens"] == 900
    assert end["output_chars"] == 340
    assert end["thinking_tokens"] == 900 - int(340 / CHARS_PER_TOKEN)


def test_claude_truncation_ends_the_call_failed(monkeypatch):
    raw = _sse(
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "{"}},
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
    )
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    seen = []
    with model_progress_listener(seen.append), pytest.raises(Exception):
        ClaudeProvider(api_key="k", show_progress=False).complete(system="s", user="u")
    assert seen[-1]["stage"] == "failed"


def test_ollama_counts_its_thinking_field_and_reports_its_own_token_counts(monkeypatch):
    events = [
        {"message": {"content": "", "thinking": "hmm " * 50}, "done": False},
        {"message": {"content": '{"a": 1}'}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 4739, "eval_count": 812},
    ]
    raw = ("\n".join(json.dumps(e) for e in events) + "\n").encode()
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    seen = []
    with model_progress_listener(seen.append):
        text = OllamaProvider(model="llama3.1", num_ctx=8192, show_progress=False,
                              ).complete(system="s", user="u", label="critic")
    assert text == '{"a": 1}', "thinking is counted, never returned as the reply"
    end = seen[-1]
    assert end["thinking_chars"] == 200 and end["output_chars"] == 8
    assert end["input_tokens"] == 4739 and end["total_output_tokens"] == 812


def test_the_api_key_provider_reads_a_host_that_ignores_stream(monkeypatch, capsys):
    """It asks to stream now (2026-09-26, the live view). A host that
    ignores that and answers with one JSON body is read as one: the reply
    and the usage arrive, and the snapshot says it did not stream."""
    body = json.dumps({"choices": [{"message": {"content": "hello"}}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 2}}).encode()
    sent = {}

    def fake(req, timeout=None):
        sent.update(json.loads(req.data))
        return _Response(body)

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)
    seen = []
    with model_progress_listener(seen.append):
        assert ApiKeyProvider(api_key="k", model="gpt", show_progress=False).complete(
            system="s", user="u", label="generator") == "hello"
    assert sent["stream"] is True
    assert capsys.readouterr().err == ""
    assert seen[-1]["streams"] is False
    assert seen[-1]["stage"] == "done" and seen[-1]["total_output_tokens"] == 2
    assert seen[-1]["tail"] == "hello"


def test_the_api_key_provider_streams_text_reasoning_and_usage(monkeypatch):
    """The OpenAI-compatible event stream: text deltas are the reply and
    the live tail; `reasoning_content` is thinking, never the reply; the
    usage chunk at the end is the real spend."""
    raw = b"".join([
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":"Laying out drums first."}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"{\\"channels\\": [{\\"name\\": \\"Kick\\"}"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"]}"}}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":50,"completion_tokens":20}}\n\n',
        b"data: [DONE]\n\n",
    ])
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    seen = []
    with model_progress_listener(seen.append):
        text = ApiKeyProvider(api_key="k", model="m", show_progress=False).complete(
            system="s", user="u", label="generator")
    assert text == '{"channels": [{"name": "Kick"}]}'
    end = seen[-1]
    assert end["streams"] is True and end["stage"] == "done"
    assert end["thinking_line"] == "Laying out drums first."
    assert end["outline"]["sections"][0]["names"] == ["Kick"]
    assert end["input_tokens"] == 50 and end["total_output_tokens"] == 20


def test_the_api_key_provider_records_streamed_reasoning_in_its_build_log(monkeypatch):
    """An OpenAI-compatible host sends its reasoning as
    `reasoning_content` deltas and no summary. Those lines are the only
    record of its thinking, so they reach `build_log[label]["notes"]`
    exactly as a Claude summary's do -- split on newlines across deltas."""
    raw = b"".join([
        b'data: {"choices":[{"delta":{"reasoning_content":"Laying out drums"}}]}\n\n',
        b'data: {"choices":[{"delta":{"reasoning_content":" first.\\nThen the toms."}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"{}"}}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":50,"completion_tokens":20,'
        b'"completion_tokens_details":{"reasoning_tokens":12}}}\n\n',
        b"data: [DONE]\n\n",
    ])
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    provider = ApiKeyProvider(api_key="k", model="m", show_progress=False)
    assert provider.complete(system="s", user="u", label="generator") == "{}"
    entry = provider.build_log["generator"]
    assert [n["text"] for n in entry["notes"]] == ["Laying out drums first.", "Then the toms."]
    assert entry["usage"]["reasoning_tokens_as_reported"] == 12


def test_ollama_records_its_thinking_field_in_its_build_log(monkeypatch):
    events = [
        {"message": {"content": "", "thinking": "Weighing HOST.\nSpeech"}, "done": False},
        {"message": {"content": "", "thinking": " gets 120 Hz."}, "done": False},
        {"message": {"content": "{}"}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 10, "eval_count": 5},
    ]
    raw = ("\n".join(json.dumps(e) for e in events) + "\n").encode()
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    provider = OllamaProvider(model="llama3.1", num_ctx=8192, show_progress=False)
    provider.complete(system="s", user="u", label="critic")
    assert [n["text"] for n in provider.build_log["critic"]["notes"]] == [
        "Weighing HOST.", "Speech gets 120 Hz."]


def test_claude_with_thinking_display_omitted_records_no_notes(monkeypatch):
    """The other side of #340: Claude with display omitted streams empty
    thinking deltas, and those must not become blank notes."""
    raw = _sse(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": ""}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": "{}"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 9}},
    )
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(raw))
    provider = ClaudeProvider(api_key="k", model="claude-sonnet-5", show_progress=False)
    provider.complete(system="s", user="u", label="generator")
    assert provider.build_log["generator"]["notes"] == []


def test_the_api_key_provider_retries_without_stream_options_once(monkeypatch):
    """A host that streams but refuses `stream_options` is asked again
    without it, rather than failing every build."""
    import urllib.error
    bodies = []

    def fake(req, timeout=None):
        payload = json.loads(req.data)
        bodies.append(payload)
        if "stream_options" in payload:
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {},
                                         io.BytesIO(b'{"error": "unknown field stream_options"}'))
        return _Response(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)
    assert ApiKeyProvider(api_key="k", model="m", show_progress=False).complete(
        system="s", user="u") == "ok"
    assert len(bodies) == 2 and "stream_options" not in bodies[1]


def test_the_fake_provider_streams_only_when_asked(capsys):
    """Every existing caller of FakeProvider gets what it always got,
    instantly and silently. `stream_chunks` opts in."""
    seen = []
    with model_progress_listener(seen.append):
        assert FakeProvider(response="abc").complete(system="s", user="u") == "abc"
    assert seen == [] and capsys.readouterr().err == ""

    with model_progress_listener(seen.append):
        out = FakeProvider(response="x" * 100, stream_chunks=4, thinking_chars=40).complete(
            system="s", user="u", label="generator")
    assert out == "x" * 100
    assert seen[0]["event"] == "start" and seen[-1]["event"] == "end"
    assert seen[-1]["thinking_chars"] == 40 and seen[-1]["output_chars"] == 100
    assert "fake (generator): sending" in capsys.readouterr().err


# -- build log (docs/developer/build-lessons-2026-09-27.md, part C) -----------


def test_thinking_summary_lines_become_build_log_notes():
    """A streamed summary is split into distinct lines, each recorded
    with its elapsed seconds, and never counted as thinking tokens."""
    progress = ModelCallProgress("generator", "claude-sonnet-5", enabled=False, ticker=False)
    progress.add_thinking_summary("Considering sockets.\n")
    progress.add_thinking_summary("We should patch LCL first.\nConsidering toms.\n")
    progress.finish(ok=True, usage={"input_tokens": 100, "output_tokens": 200})
    notes = progress.build_log_notes()
    assert [n["text"] for n in notes] == [
        "Considering sockets.", "We should patch LCL first.", "Considering toms."]
    assert all(isinstance(n["t"], float) for n in notes)
    # A summary is shown, never counted -- the real spend is `output_tokens`.
    assert progress.thinking_chars == 0


def test_a_note_still_arriving_without_a_trailing_newline_is_flushed_at_the_end():
    progress = ModelCallProgress("critic", "claude-sonnet-5", enabled=False, ticker=False)
    progress.add_thinking_summary("Weighing HOST's category")
    progress.finish(ok=True)
    assert [n["text"] for n in progress.build_log_notes()] == ["Weighing HOST's category"]


def test_build_log_notes_are_bounded_in_count_and_length():
    progress = ModelCallProgress("generator", "claude-sonnet-5", enabled=False, ticker=False)
    for i in range(progress_mod.BUILD_LOG_MAX_NOTES + 20):
        progress.add_thinking_summary(f"note {i}\n")
    progress.add_thinking_summary("x" * (progress_mod.BUILD_LOG_NOTE_CHARS + 50) + "\n")
    progress.finish(ok=True)
    notes = progress.build_log_notes()
    assert len(notes) == progress_mod.BUILD_LOG_MAX_NOTES
    assert all(len(n["text"]) <= progress_mod.BUILD_LOG_NOTE_CHARS for n in notes)


def test_usage_summary_carries_model_effort_and_cost_and_leaves_unknowns_none():
    progress = ModelCallProgress("generator", "claude-sonnet-5", enabled=False, ticker=False,
                                 effort="high")
    progress.finish(ok=True, usage={"input_tokens": 10, "output_tokens": 20})
    usage = progress.usage_summary(cost=0.42)
    assert usage == {
        "input": 10, "output": 20, "reasoning_tokens_as_reported": None,
        "thinking": 20, "thinking_source": "estimated",
        "model": "claude-sonnet-5", "effort": "high", "cost": 0.42,
    }


def test_usage_summary_estimates_claude_thinking_the_way_the_usage_line_does():
    """Claude reports no separate reasoning count, so the build
    log carries the same subtraction the usage line prints -- output total
    less the text received -- and says it is an estimate."""
    progress = ModelCallProgress("generator", "claude-sonnet-5", enabled=False, ticker=False,
                                 chars_per_token=3.4)
    progress.add_thinking_summary("Laying out drums.\n")
    progress.add_text(3400, "x" * 3400)
    progress.finish(ok=True, usage={"input_tokens": 10, "output_tokens": 5000})
    usage = progress.usage_summary()
    assert usage["thinking"] == 4000 and usage["thinking_source"] == "estimated"
    assert usage["reasoning_tokens_as_reported"] is None


def test_usage_summary_prefers_a_reported_reasoning_count():
    progress = ModelCallProgress("generator", "m", enabled=False, ticker=False,
                                 chars_per_token=3.4)
    progress.add_text(34, "x" * 34)
    progress.finish(ok=True, usage={"input_tokens": 10, "output_tokens": 500,
                                    "reasoning_tokens": 123})
    usage = progress.usage_summary()
    assert usage["thinking"] == 123 and usage["thinking_source"] == "reported"


def test_usage_summary_leaves_thinking_unknown_when_nothing_says():
    """Thinking seen but never streamed, and no usage reported: unknown,
    which is not zero."""
    progress = ModelCallProgress("generator", "claude-sonnet-5", enabled=False, ticker=False)
    progress.thinking_started()
    progress.finish(ok=False)
    usage = progress.usage_summary()
    assert usage["thinking"] is None and usage["thinking_source"] is None


def test_fake_provider_with_summarized_thinking_produces_a_build_log():
    """A fake streaming provider that emits summary deltas, exactly as
    `atoo.ai_provider.ClaudeProvider` does when `display:
    "summarized"` is requested, produces `provider.build_log` with
    notes, times and usage -- no real model call."""
    provider = FakeProvider(
        response="x" * 40, stream_chunks=4, chunk_delay=0,
        thinking_text="Considering sockets.\nPatching LCL first.\n",
        summarized_thinking=True, model="claude-sonnet-5",
    )
    provider.complete(system="s", user="u", label="generator")
    assert "generator" in provider.build_log
    entry = provider.build_log["generator"]
    texts = [n["text"] for n in entry["notes"]]
    assert "Considering sockets." in texts and "Patching LCL first." in texts
    assert entry["usage"]["model"] == "claude-sonnet-5"
