"""Each provider either honours `response_schema` or pointedly ignores it
(review 2026-09-28, R17, R21).

`build --no-constrain` and `patch --no-constrain` are only meaningful where
a provider constrains decoding. This pins, per provider, what reaches the
wire with a schema and without one, so the `api` path cannot drift into
half-sending one -- and so `--help`'s claim that only `claude` and `ollama`
constrain stays true.
"""

from __future__ import annotations

import io
import json

from atoo.ai_provider import ApiKeyProvider, ClaudeProvider, OllamaProvider
from tests.test_role_effort import _sse

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}},
          "required": ["a"], "additionalProperties": False}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture(monkeypatch, body: bytes) -> list[dict]:
    sent: list[dict] = []

    def fake(req, timeout=None):
        sent.append(json.loads(req.data))
        return _Response(body)

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)
    return sent


def test_claude_constrains_to_the_schema_and_only_when_asked(monkeypatch):
    sent = _capture(monkeypatch, _sse('{"a": "ok"}'))
    provider = ClaudeProvider(api_key="k", show_progress=False)
    provider.complete(system="s", user="u", response_schema=SCHEMA)
    provider.complete(system="s", user="u")
    assert "format" in sent[0]["output_config"]
    assert "format" not in (sent[1].get("output_config") or {})


def test_ollama_constrains_to_the_schema_and_only_when_asked(monkeypatch):
    body = json.dumps({"message": {"content": '{"a": "ok"}'}, "done": True}).encode()
    sent = _capture(monkeypatch, body)
    provider = OllamaProvider(model="m", show_progress=False)
    provider.complete(system="s", user="u", response_schema=SCHEMA)
    provider.complete(system="s", user="u")
    chats = [body for body in sent if "messages" in body]   # not /api/show
    assert chats[0]["format"] == SCHEMA
    assert "format" not in chats[1]


def test_the_api_provider_never_sends_a_schema(monkeypatch):
    """OpenAI-compatible hosts differ in whether they take
    `response_format` and what they call it; guessing wrong is a 400 on
    every call. So the schema is never sent, and the request is identical
    with and without one -- which is why `--no-constrain` changes nothing
    on this provider, and `--help` says so."""
    body = json.dumps({"choices": [{"message": {"content": '{"a": "ok"}'}}]}).encode()
    sent = _capture(monkeypatch, body)
    provider = ApiKeyProvider(api_key="k", model="m", stream=False, show_progress=False)
    provider.complete(system="s", user="u", response_schema=SCHEMA)
    provider.complete(system="s", user="u")
    assert sent[0] == sent[1]
    assert not {"response_format", "format", "output_config"} & set(sent[0])
