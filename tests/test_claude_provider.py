"""ClaudeProvider wire-format tests.

No network: every test drives urllib through a stub. The contract under
test is "does this module build the request Anthropic's Messages API
expects and read the reply correctly", not "is the model any good" --
same policy as the rest of ai_provider.py's tests.

The shape differences from the OpenAI-compatible ApiKeyProvider are all
failures rather than cosmetics, so each gets its own test.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from atoo.ai_provider import (
    AIProviderError,
    ApiKeyProvider,
    ClaudeProvider,
    provider_from_env,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def as_sse(reply: dict) -> bytes:
    """A non-streaming reply, rendered as the SSE stream it arrives as.

    The provider streams (a plan is minutes of generation), so the wire
    format under test is Server-Sent Events. Tests still describe a reply
    the readable way -- blocks and a stop_reason -- and this turns it into
    the event sequence Anthropic actually sends.
    """
    lines = ['data: {"type":"message_start","message":{"id":"msg_1"}}']
    for i, block in enumerate(reply.get("content", [])):
        kind = block.get("type")
        lines.append(json_event({"type": "content_block_start", "index": i,
                                 "content_block": {"type": kind}}))
        if kind == "text":
            lines.append(json_event({
                "type": "content_block_delta", "index": i,
                "delta": {"type": "text_delta", "text": block.get("text", "")}}))
        elif kind == "thinking":
            lines.append(json_event({
                "type": "content_block_delta", "index": i,
                "delta": {"type": "thinking_delta",
                          "thinking": block.get("thinking", "")}}))
        lines.append(json_event({"type": "content_block_stop", "index": i}))

    delta: dict = {"stop_reason": reply.get("stop_reason")}
    if "stop_details" in reply:
        delta["stop_details"] = reply["stop_details"]
    lines.append(json_event({"type": "message_delta", "delta": delta}))
    lines.append(json_event({"type": "message_stop"}))
    return ("\n\n".join(lines) + "\n\n").encode()


def json_event(payload: dict) -> str:
    return "data: " + json.dumps(payload)


@pytest.fixture
def capture(monkeypatch):
    """Replaces urlopen; records the request and returns a canned stream."""
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.headers.items()}
        seen["body"] = json.loads(req.data)
        seen["timeout"] = timeout
        raw = seen.get("raw")
        return _Response(raw if raw is not None else as_sse(seen["reply"]))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    seen["reply"] = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}
    return seen


def test_request_matches_the_messages_api_shape(capture):
    ClaudeProvider(api_key="sk-test", model="claude-opus-5").complete(
        system="SYS", user="USER"
    )

    assert capture["url"] == "https://api.anthropic.com/v1/messages"
    assert capture["headers"]["x-api-key"] == "sk-test"
    assert capture["headers"]["anthropic-version"] == "2023-06-01"
    # not Authorization: Bearer -- that is the OpenAI-compatible provider
    assert "authorization" not in capture["headers"]

    body = capture["body"]
    assert body["model"] == "claude-opus-5"
    # top-level, not a message; one block carrying the cache breakpoint (a
    # user message that is a plain string has none of its own)
    assert body["system"] == [{"type": "text", "text": "SYS",
                               "cache_control": {"type": "ephemeral"}}]
    assert body["messages"] == [{"role": "user", "content": "USER"}]
    assert body["max_tokens"] == 128000                  # required; the model's own limit
    assert body["output_config"] == {"effort": "medium"}
    assert body["stream"] is True                        # see _Progress


def test_no_sampling_parameters_are_sent(capture):
    """The current models return 400 for temperature/top_p/top_k.

    ApiKeyProvider sends `temperature: 0`; copying that here would make
    every request fail, so this is a regression test rather than a style
    preference."""
    ClaudeProvider(api_key="k").complete(system="s", user="u")
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in capture["body"]


def test_the_openai_provider_still_sends_temperature(monkeypatch):
    """...and the two providers stay different on purpose."""
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _Response(json.dumps(
            {"choices": [{"message": {"content": "hi"}}]}).encode())

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    ApiKeyProvider(api_key="k", model="m").complete(system="s", user="u")
    assert seen["body"]["temperature"] == 0


def test_text_is_concatenated_across_blocks(capture):
    """The reply is a list of blocks, not choices[0].message.content, and
    thinking blocks sit alongside the text ones."""
    capture["reply"] = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "...reasoning..."},
            {"type": "text", "text": '{"channels": '},
            {"type": "text", "text": "[]}"},
        ],
    }
    out = ClaudeProvider(api_key="k").complete(system="s", user="u")
    assert out == '{"channels": []}'


def test_truncation_is_reported_not_returned(capture):
    """stop_reason max_tokens means the JSON is cut off.

    Returning it would surface as a parse error in extract.py and send
    whoever reads it hunting for a malformed reply that is really just
    incomplete."""
    capture["reply"] = {"stop_reason": "max_tokens",
                        "content": [{"type": "text", "text": '{"channels": [{"chan'}]}
    with pytest.raises(AIProviderError, match="truncated"):
        ClaudeProvider(api_key="k").complete(system="s", user="u")


def test_refusal_names_its_category(capture):
    capture["reply"] = {
        "stop_reason": "refusal",
        "stop_details": {"type": "refusal", "category": "cyber", "explanation": "nope"},
        "content": [],
    }
    with pytest.raises(AIProviderError, match="declined.*cyber"):
        ClaudeProvider(api_key="k").complete(system="s", user="u")


def test_http_error_body_reaches_the_message(monkeypatch):
    """A bare 'HTTP 400' sends the reader to the wrong place; the body says
    which parameter the model actually rejected."""
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"temperature: unsupported"}}'))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AIProviderError, match="temperature: unsupported"):
        ClaudeProvider(api_key="k").complete(system="s", user="u")


def test_empty_content_is_an_error_not_an_empty_string(capture):
    capture["reply"] = {"stop_reason": "end_turn", "content": [{"type": "thinking",
                                                                "thinking": "hm"}]}
    with pytest.raises(AIProviderError, match="returned no text"):
        ClaudeProvider(api_key="k").complete(system="s", user="u")


def test_env_accepts_the_conventional_anthropic_key():
    p = provider_from_env({"ATOO_AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-a"})
    assert isinstance(p, ClaudeProvider)
    assert (p.api_key, p.model) == ("sk-a", "claude-sonnet-5-5")


def test_atoo_key_wins_over_the_generic_one():
    p = provider_from_env({"ATOO_AI_PROVIDER": "claude",
                           "ATOO_AI_API_KEY": "sk-specific",
                           "ANTHROPIC_API_KEY": "sk-generic"})
    assert p.api_key == "sk-specific"


@pytest.mark.parametrize("env,match", [
    ({"ATOO_AI_PROVIDER": "claude"}, "needs an API key"),
    ({"ATOO_AI_PROVIDER": "claude", "ATOO_AI_API_KEY": "k",
      "ATOO_AI_EFFORT": "turbo"}, "not one of"),
    ({"ATOO_AI_PROVIDER": "claude", "ATOO_AI_API_KEY": "k",
      "ATOO_AI_MAX_TOKENS": "lots"}, "must be an integer"),
    ({"ATOO_AI_PROVIDER": "nope"}, "expected 'ollama', 'claude' or 'api'"),
])
def test_env_misconfiguration_is_refused_with_a_reason(env, match):
    with pytest.raises(AIProviderError, match=match):
        provider_from_env(env)


def test_claude_is_the_default():
    """2026-10-01: Claude is the default; Ollama is chosen explicitly."""
    from atoo.ai_provider import ClaudeProvider, OllamaProvider
    assert isinstance(provider_from_env({"ANTHROPIC_API_KEY": "k"}), ClaudeProvider)
    assert isinstance(provider_from_env({"ATOO_AI_PROVIDER": "ollama"}), OllamaProvider)


# ---------------------------------------------------------------------------
# OllamaProvider context sizing
#
# Ollama's default num_ctx is 4096 whatever the model supports, and it
# truncates silently. These pin the fix: a prompt this project actually
# sends must never be sized into a window that cannot hold it.
# ---------------------------------------------------------------------------

def test_ollama_sends_an_explicit_num_ctx(monkeypatch):
    """The whole point. Leaving it unset means Ollama's 4096."""
    from atoo.ai_provider import OllamaProvider

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _Response(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    OllamaProvider(model="m").complete(system="s" * 4000, user="u" * 4000)

    assert "num_ctx" in seen["body"]["options"]
    assert seen["body"]["options"]["num_ctx"] > 4096
    assert seen["body"]["options"]["num_predict"] == -1


def test_auto_num_ctx_fits_every_real_fixture():
    """The reason the default is auto rather than a constant: the smallest
    and largest example shows differ by ~4k tokens of requirement, so any
    fixed number is wrong at one end."""
    from atoo import generate
    from atoo.ai_provider import CHARS_PER_TOKEN, OllamaProvider

    provider = OllamaProvider(model="m")
    root = Path(__file__).parent / "fixtures"

    for stem in ("smallband", "fullband", "touringband", "festival"):
        conv = (root / f"{stem}.md").read_text()
        csv = (root / f"{stem}.csv").read_text()
        user = generate.generator_user(conv, csv, conventions_name=f"{stem}.md",
                                       input_name=f"{stem}.csv")
        chosen = provider._auto_num_ctx(generate.generator_system("wing-compact"), user)
        prompt_tokens = (len(generate.generator_system("wing-compact")) + len(user)) / CHARS_PER_TOKEN

        # room for the prompt itself, with the answer still to come
        assert chosen > prompt_tokens * 2, f"{stem}: {chosen} leaves no room to answer"
        assert chosen <= provider.num_ctx_ceiling


def test_chars_per_token_estimate_runs_high_not_low():
    """Measured 3.71 chars/token on the touringband prompt (the server
    logged task.n_tokens = 4739 for 17,595 chars). The constant must sit
    below that, so estimates overshoot -- under-sizing truncates silently,
    over-sizing only costs memory."""
    from atoo.ai_provider import CHARS_PER_TOKEN
    assert CHARS_PER_TOKEN < 3.71


def test_an_explicit_num_ctx_is_respected(monkeypatch):
    """For tight RAM: KV cache grows linearly with this."""
    from atoo.ai_provider import OllamaProvider

    seen = {}
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: (
                            seen.update(body=json.loads(req.data)),
                            _Response(json.dumps({"message": {"content": "ok"}}).encode()))[1])
    OllamaProvider(model="m", num_ctx=8192).complete(system="s", user="u")
    assert seen["body"]["options"]["num_ctx"] == 8192


def test_env_num_ctx_unset_means_auto():
    from atoo.ai_provider import OllamaProvider
    p = provider_from_env({"ATOO_AI_PROVIDER": "ollama"})
    assert isinstance(p, OllamaProvider)
    assert p.num_ctx is None

    p = provider_from_env({"ATOO_AI_PROVIDER": "ollama", "ATOO_AI_NUM_CTX": "8192"})
    assert p.num_ctx == 8192

    with pytest.raises(AIProviderError, match="must be an integer"):
        provider_from_env({"ATOO_AI_PROVIDER": "ollama", "ATOO_AI_NUM_CTX": "big"})


def test_env_num_predict_unset_means_unlimited(monkeypatch):
    """Unset must stay -1 (today's "run until the model stops"
    behavior), not a new sentinel -- this knob is opt-in, not a new default
    that could truncate a legitimately large show's plan."""
    from atoo.ai_provider import OllamaProvider

    p = provider_from_env({"ATOO_AI_PROVIDER": "ollama"})
    assert isinstance(p, OllamaProvider)
    assert p.num_predict == -1

    seen = {}
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: (
                            seen.update(body=json.loads(req.data)),
                            _Response(json.dumps({"message": {"content": "ok"}}).encode()))[1])
    p.complete(system="s", user="u")
    assert seen["body"]["options"]["num_predict"] == -1


def test_env_num_predict_set_caps_the_reply(monkeypatch):
    """A set value must reach OllamaProvider.num_predict and, from there,
    the request's num_predict option -- the actual knob an earlier change asks for,
    so a stuck model gets a fast, actionable error instead of running
    until num_ctx."""
    from atoo.ai_provider import OllamaProvider

    p = provider_from_env({"ATOO_AI_PROVIDER": "ollama", "ATOO_AI_NUM_PREDICT": "256"})
    assert isinstance(p, OllamaProvider)
    assert p.num_predict == 256

    seen = {}
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: (
                            seen.update(body=json.loads(req.data)),
                            _Response(json.dumps({"message": {"content": "ok"}}).encode()))[1])
    p.complete(system="s", user="u")
    assert seen["body"]["options"]["num_predict"] == 256


def test_env_num_predict_bad_value_raises():
    with pytest.raises(AIProviderError, match="ATOO_AI_NUM_PREDICT must be an integer"):
        provider_from_env({"ATOO_AI_PROVIDER": "ollama", "ATOO_AI_NUM_PREDICT": "big"})


# ---------------------------------------------------------------------------
# OllamaProvider real context ceiling
#
# num_ctx above is only a REQUEST; Ollama honors it only up to what the
# model was actually trained with, and silently runs with less when the
# request exceeds that -- no error, just a done_reason=="length" truncation
# after a real wait. The bug report: raising ATOO_AI_NUM_CTX from
# 16,000 to 64,000 against gemma2 (hard ceiling 8,192) produced
# byte-identical output both times. These pin the fix: query Ollama's
# /api/show for the model's real ceiling, once per provider, and either
# clamp-and-warn or fail fast before wasting a request that's already
# provably doomed.
# ---------------------------------------------------------------------------

def _show_reply(architecture: str, context_length: int) -> bytes:
    """A /api/show response shaped the way Ollama actually sends it: the
    ceiling lives under an architecture-PREFIXED key inside model_info,
    never a fixed name."""
    return json.dumps({
        "model_info": {
            "general.architecture": architecture,
            f"{architecture}.context_length": context_length,
        },
    }).encode()


def _route_urlopen(*, show_response: bytes | None = None, show_error: Exception | None = None,
                   chat_response: bytes | None = None):
    """A fake urlopen that answers /api/show and /api/chat differently,
    and records every URL it was asked for -- so a test can assert /api/chat
    was never reached, or that /api/show was reached only once."""
    calls: list[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if req.full_url.endswith("/api/show"):
            if show_error is not None:
                raise show_error
            return _Response(show_response)
        return _Response(chat_response or json.dumps({"message": {"content": "ok"}}).encode())

    return fake_urlopen, calls


def test_a_ceiling_larger_than_requested_changes_nothing(monkeypatch, capsys):
    """The common case: model can hold what was asked for. No clamp, no
    warning -- today's request goes out exactly as it always has."""
    from atoo.ai_provider import OllamaProvider

    fake, calls = _route_urlopen(show_response=_show_reply("llama", 131072))
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)

    out = OllamaProvider(model="llama3.1", num_ctx=8192).complete(system="s", user="u")

    assert out == "ok"
    assert "/api/show" in calls[0]
    assert "warning" not in capsys.readouterr().err


def test_a_smaller_ceiling_clamps_and_warns_but_still_completes(monkeypatch, capsys):
    """The model can't hold the requested window but the prompt itself
    comfortably fits under the real one -- clamp, warn naming both
    numbers, and let generation proceed."""
    from atoo.ai_provider import OllamaProvider

    fake, _calls = _route_urlopen(show_response=_show_reply("gemma2", 8192))
    seen = {}

    def spy(req, timeout=None):
        resp = fake(req, timeout=timeout)
        if req.full_url.endswith("/api/chat"):
            seen["body"] = json.loads(req.data)
        return resp

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", spy)

    out = OllamaProvider(model="gemma2", num_ctx=64000).complete(
        system="s" * 100, user="u" * 100)

    assert out == "ok"
    assert seen["body"]["options"]["num_ctx"] == 8192   # clamped, not 64000
    err = capsys.readouterr().err
    assert "64,000" in err and "8,192" in err
    assert "gemma2" in err


def test_a_prompt_too_big_for_the_clamped_ceiling_fails_before_any_request(monkeypatch, capsys):
    """The prompt alone can't fit even after clamping -- fail fast, name
    the real limit and the estimated size, and never reach /api/chat: no
    point spending a real request on a doomed one."""
    from atoo.ai_provider import OllamaProvider

    fake, calls = _route_urlopen(show_response=_show_reply("gemma2", 8192))
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)

    with pytest.raises(AIProviderError, match="cannot fit"):
        OllamaProvider(model="gemma2", num_ctx=64000).complete(
            system="s" * 15000, user="u" * 15000)

    assert all(url.endswith("/api/show") for url in calls)
    assert calls   # /api/show was in fact attempted


@pytest.mark.parametrize("show_response,show_error", [
    (None, urllib.error.URLError("connection refused")),           # network failure
    (b"not json at all", None),                                    # malformed body
    (json.dumps({}).encode(), None),                                # no model_info at all
    (json.dumps({"model_info": {}}).encode(), None),                # no architecture
    (json.dumps({"model_info": {"general.architecture": "gemma2"}}).encode(), None),
    # architecture present, but no ARCH.context_length -- old Ollama or a
    # model Ollama doesn't have full info for
])
def test_an_unresolvable_ceiling_falls_back_to_todays_behavior(monkeypatch, capsys,
                                                                show_response, show_error):
    from atoo.ai_provider import OllamaProvider

    fake, _calls = _route_urlopen(show_response=show_response, show_error=show_error)
    seen = {}

    def spy(req, timeout=None):
        resp = fake(req, timeout=timeout)
        if req.full_url.endswith("/api/chat"):
            seen["body"] = json.loads(req.data)
        return resp

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", spy)

    out = OllamaProvider(model="gemma2", num_ctx=64000).complete(system="s", user="u")

    assert out == "ok"
    assert seen["body"]["options"]["num_ctx"] == 64000   # unchanged -- no ceiling to compare to
    assert "warning" not in capsys.readouterr().err


def test_api_show_is_queried_once_per_provider_not_once_per_request(monkeypatch):
    """complete() can be called many times against the same instance
    (generator + critic passes, repeated extraction calls) -- /api/show
    must answer once, not once per call."""
    from atoo.ai_provider import OllamaProvider

    fake, calls = _route_urlopen(show_response=_show_reply("llama", 131072))
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)

    provider = OllamaProvider(model="llama3.1", num_ctx=8192)
    provider.complete(system="s", user="u")
    provider.complete(system="s", user="u")

    show_calls = [url for url in calls if url.endswith("/api/show")]
    chat_calls = [url for url in calls if url.endswith("/api/chat")]
    assert len(show_calls) == 1
    assert len(chat_calls) == 2


# ---------------------------------------------------------------------------
# OllamaProvider truncation
#
# Ollama's stream carries its own "done_reason" on the final line: "stop"
# for a natural finish, "length" when num_ctx or num_predict ran out mid-
# generation. Before this, that field was read nowhere -- a truncated reply
# went straight into json_repair, which patches the JSON closed and hides
# exactly which keys the model never got to write. The bug report was that
# repaired-but-truncated plan failing schema validation with "missing
# required field 'outputs'" and no hint why.
# ---------------------------------------------------------------------------

def _ollama_stream(*, chunks: list[str], done_reason: str) -> bytes:
    lines = [json.dumps({"message": {"content": c}, "done": False}) for c in chunks]
    lines.append(json.dumps({"message": {"content": ""}, "done": True,
                             "done_reason": done_reason}))
    return ("\n".join(lines) + "\n").encode()


def test_ollama_truncated_reply_is_a_clear_error_not_a_schema_puzzle(monkeypatch):
    from atoo.ai_provider import OllamaProvider

    monkeypatch.setattr(
        "atoo.ai_provider.urllib.request.urlopen",
        lambda req, timeout=None: _Response(
            _ollama_stream(chunks=["partial plan..."], done_reason="length")),
    )
    with pytest.raises(AIProviderError, match="cut off.*done_reason 'length'") as excinfo:
        OllamaProvider(model="m", num_ctx=8192).complete(system="s", user="u")
    # The partial reply is kept, same contract as every other truncation
    # path in this module -- it is the only evidence of how far generation got.
    assert excinfo.value.partial_text == "partial plan..."


def test_ollama_natural_stop_is_not_treated_as_truncation(monkeypatch):
    from atoo.ai_provider import OllamaProvider

    monkeypatch.setattr(
        "atoo.ai_provider.urllib.request.urlopen",
        lambda req, timeout=None: _Response(
            _ollama_stream(chunks=["{}"], done_reason="stop")),
    )
    assert OllamaProvider(model="m").complete(system="s", user="u") == "{}"


def test_ollama_http_error_body_reaches_the_message(monkeypatch):
    """A bare 'HTTP 404' sends the reader looking in the wrong place --
    Ollama's own body says the model tag hasn't been pulled, same fix
    ClaudeProvider's own HTTPError branch already applies."""
    from atoo.ai_provider import OllamaProvider

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {},
            io.BytesIO(b'{"error":"model \'gemma3:4b\' not found, try pulling it first"}'))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AIProviderError, match="not found, try pulling it first"):
        OllamaProvider(model="gemma3:4b", num_ctx=8192).complete(system="s", user="u")


# ---------------------------------------------------------------------------
# OllamaProvider streaming
#
# A real run generated 8142 tokens over an hour and then timed out, leaving
# nothing at all to look at -- there was no way to tell whether the model
# had been producing a sensible plan slowly or repeating itself forever.
# These pin the fix.
# ---------------------------------------------------------------------------

def _ndjson(*events):
    return "\n".join(json.dumps(e) for e in events).encode()


def test_streamed_chunks_are_accumulated(monkeypatch):
    from atoo.ai_provider import OllamaProvider

    body = _ndjson(
        {"message": {"content": '{"chan'}, "done": False},
        {"message": {"content": 'nels": '}, "done": False},
        {"message": {"content": "[]}"}, "done": True},
    )
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(body))
    assert OllamaProvider(model="m").complete(system="s", user="u") == '{"channels": []}'


def test_a_timeout_mid_stream_keeps_what_arrived(monkeypatch):
    """The whole point: a partial tells you whether it was looping."""
    from atoo.ai_provider import AIProviderError, OllamaProvider

    class _DyingStream(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            yield json.dumps({"message": {"content": "{"}, "done": False}).encode()
            yield json.dumps({"message": {"content": '"channels": ['}, "done": False}).encode()
            raise TimeoutError("timed out")

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _DyingStream())

    with pytest.raises(AIProviderError) as excinfo:
        OllamaProvider(model="m").complete(system="s", user="u")

    assert excinfo.value.partial_text == '{"channels": ['
    assert "after 14 characters" in str(excinfo.value)


def test_an_error_event_in_the_stream_is_raised(monkeypatch):
    from atoo.ai_provider import AIProviderError, OllamaProvider

    body = _ndjson({"error": "model requires more system memory"})
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(body))
    with pytest.raises(AIProviderError, match="more system memory"):
        OllamaProvider(model="m").complete(system="s", user="u")


def test_an_empty_reply_is_an_error_not_an_empty_string(monkeypatch):
    from atoo.ai_provider import AIProviderError, OllamaProvider

    body = _ndjson({"message": {"content": ""}, "done": True})
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Response(body))
    with pytest.raises(AIProviderError, match="empty reply"):
        OllamaProvider(model="m").complete(system="s", user="u")


def test_the_request_asks_for_a_stream(monkeypatch):
    from atoo.ai_provider import OllamaProvider

    seen = {}

    def fake(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _Response(_ndjson({"message": {"content": "ok"}, "done": True}))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)
    OllamaProvider(model="m").complete(system="s", user="u")
    assert seen["body"]["stream"] is True


def test_an_unsendable_schema_is_dropped_rather_than_sent(capture, capsys):
    """The first real hosted run died on HTTP 400: `output_config.format`
    takes a SUBSET of JSON Schema, and `minimum`/`maximum` on an integer is
    outside it. The plan schema goes further out of bounds than that -- its
    name-keyed maps have no expression in the subset at all -- so nothing is
    sent, and the run carries on instead of failing.

    Quietly: the reply is validated locally against the
    full schema either way, so a note saying so was noise on every build."""
    from atoo.ai_provider import ClaudeProvider
    from atoo.plan_schema import GENERATION_SCHEMA

    ClaudeProvider(api_key="sk-test").complete(
        system="SYS", user="USER", response_schema=GENERATION_SCHEMA)

    assert "format" not in capture["body"]["output_config"]
    assert "structured-output" not in capsys.readouterr().err


def test_a_mid_stream_error_is_raised_not_returned(capture):
    """A stream that fails after the 200 carries its error as an event.
    There is no exception to catch and nothing else marks the reply as
    incomplete -- returning what arrived would look like a short plan."""
    capture["raw"] = (
        json_event({"type": "content_block_start", "index": 0,
                    "content_block": {"type": "text"}}) + "\n\n" +
        json_event({"type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": '{"channels": ['}}) + "\n\n" +
        json_event({"type": "error",
                    "error": {"type": "overloaded_error", "message": "Overloaded"}}) + "\n\n"
    ).encode()

    with pytest.raises(AIProviderError) as exc:
        ClaudeProvider(api_key="k").complete(system="s", user="u")
    assert "overloaded_error" in str(exc.value)
    assert exc.value.partial_text == '{"channels": ['


def test_a_dropped_connection_keeps_what_arrived(capture, monkeypatch):
    """Minutes of generation are worth examining even when the last chunk
    never came. An empty error message makes the failure unexaminable."""
    class _Truncated(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            yield (json_event({"type": "content_block_delta", "index": 0,
                               "delta": {"type": "text_delta",
                                         "text": '{"channels": [{"name"'}}) + "\n").encode()
            raise TimeoutError("read timed out")

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        lambda req, timeout=None: _Truncated())
    with pytest.raises(AIProviderError) as exc:
        ClaudeProvider(api_key="k").complete(system="s", user="u")
    assert exc.value.partial_text == '{"channels": [{"name"'


def test_progress_is_quiet_when_stderr_is_not_a_terminal(capture, capsys):
    """One line, not a thousand carriage returns, when output is a log."""
    ClaudeProvider(api_key="k").complete(system="s", user="u")
    err = capsys.readouterr().err
    # The INFO line about thinking summaries is a one-off announcement of
    # a decision, not progress.
    progress = [line for line in err.splitlines() if not line.startswith("INFO ")]
    assert len(progress) <= 1
    assert "\r" not in err


def test_an_immediate_line_prints_before_anything_streams_back(capture, capsys):
    """The gap this closes: from "the call started" to "the first byte
    arrived" (connection, TLS, the model deciding to start) can itself be
    tens of seconds, and nothing printed there before -- update() only
    ever fires once a delta has actually arrived. A run with no output yet
    was indistinguishable from a hung one."""
    ClaudeProvider(api_key="k").complete(system="s", user="u")
    err = capsys.readouterr().err
    assert "sending, waiting for the first reply" in err


def test_the_progress_and_usage_lines_are_labelled_by_role(capture, capsys):
    """Two calls against the same model print identical lines without a
    label -- exactly what a real generate-then-critique run does. Nothing
    said which was which."""
    capture["raw"] = _usage_stream(100, 200, "hello")
    # The critic on the generator's model here (it runs on Haiku by
    # default, docs/developer/build-cost-reduction.md), so that the line has
    # a model AND an effort to name.
    ClaudeProvider(api_key="k", model="claude-sonnet-5", role_models={},
                   show_progress=True).complete(system="s", user="u", label="critic")
    err = capsys.readouterr().err
    # ...and by the effort it ran at, since the critic has its own.
    assert "claude-sonnet-5 (critic, effort medium)" in err
    # (a one-letter system prompt is below the model's cache minimum, said)
    assert "100 in (prefix ~" in err and "-token minimum, not cached), 200 out" in err


def _usage_stream(input_tokens: int, output_tokens: int, text: str) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in [
        {"type": "message_start",
         "message": {"id": "m", "usage": {"input_tokens": input_tokens}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": text}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": output_tokens}},
    ]).encode()


def test_usage_names_the_spend_and_where_it_went(capture, capsys):
    """A run that spends 32,000 output tokens and returns 6,000 tokens of
    plan has 26,000 tokens of thinking behind it, billed and never shown.
    Without this the two runs are indistinguishable on screen, and the
    first sign of a runaway is the invoice."""
    capture["raw"] = _usage_stream(5_700, 32_000, "x" * 20_000)
    ClaudeProvider(api_key="k", model="claude-sonnet-5",
                   show_progress=True).complete(system="s", user="u")

    err = capsys.readouterr().err
    assert "5,700 in, 32,000 out" in err
    assert "thinking, not returned" in err
    assert "$0.33" in err          # 5.7k @ $2/M + 32k @ $10/M


def test_a_reply_that_is_mostly_answer_is_not_blamed_on_thinking(capture, capsys):
    capture["raw"] = _usage_stream(5_700, 6_000, "x" * 20_000)
    ClaudeProvider(api_key="k", model="claude-sonnet-5",
                   show_progress=True).complete(system="s", user="u")
    assert "thinking, not returned" not in capsys.readouterr().err


def test_an_unpriced_model_reports_tokens_and_no_dollars(capture, capsys):
    """A stale price printed with confidence is worse than no price."""
    capture["raw"] = _usage_stream(100, 200, "hello")
    ClaudeProvider(api_key="k", model="claude-something-new",
                   show_progress=True).complete(system="s", user="u")
    err = capsys.readouterr().err
    assert "100 in, 200 out" in err
    assert "$" not in err


def test_the_default_ceiling_is_the_models_own_output_limit():
    """64,000 cut the 38-row festival build off ~900 tokens short
    (docs/developer/plan-output-compaction.md); the default is now each
    model's maximum, Haiku's 64K below the others' 128K, and an explicit
    ATOO_AI_MAX_TOKENS is used exactly as given."""
    env = {"ATOO_AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-test"}
    assert provider_from_env({**env}).max_tokens == 128000
    assert provider_from_env({**env, "ATOO_AI_MODEL": "claude-sonnet-5"}).max_tokens == 128000
    assert provider_from_env({**env, "ATOO_AI_MODEL": "claude-haiku-4-5"}).max_tokens == 64000
    assert provider_from_env({**env, "ATOO_AI_MAX_TOKENS": "32000"}).max_tokens == 32000
    assert provider_from_env({**env, "ATOO_AI_MAX_TOKENS": " "}).max_tokens == 128000
    assert ClaudeProvider(api_key="k", model="claude-haiku-4-5").max_tokens == 64000
