"""A reply schema the API refuses is asked again without it, not a failed
build (ai_provider.ClaudeProvider.complete; slice C of
docs/developer/build-cost-reduction.md made the generator's schema large, and
the API's structured-output compiler has unpublished complexity limits)."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from atoo.ai_provider import AIProviderError, ClaudeProvider
from tests.test_role_effort import _Response, _sse

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}},
          "required": ["a"], "additionalProperties": False}


def _refusal(body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api", 400, "Bad Request", {},
                                  io.BytesIO(body.encode()))


def _wire(monkeypatch, first_error):
    sent = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        sent.append(body)
        if len(sent) == 1 and first_error is not None:
            raise first_error
        return _Response(_sse(json.dumps({"a": "ok"})))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    return sent


def test_a_refused_schema_is_asked_again_without_it(monkeypatch, capsys):
    sent = _wire(monkeypatch, _refusal(
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"output_config.format.schema: schema is too complex"}}'))
    provider = ClaudeProvider(api_key="k")
    assert json.loads(provider.complete(system="s", user="u",
                                        response_schema=SCHEMA)) == {"a": "ok"}
    assert len(sent) == 2
    assert "format" in sent[0]["output_config"]
    assert "format" not in (sent[1].get("output_config") or {})
    assert "INFO the API refused the reply schema" in capsys.readouterr().err


def test_any_other_400_still_fails(monkeypatch):
    sent = _wire(monkeypatch, _refusal(
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"model: unknown model"}}'))
    with pytest.raises(AIProviderError, match="unknown model"):
        ClaudeProvider(api_key="k").complete(system="s", user="u",
                                             response_schema=SCHEMA)
    assert len(sent) == 1


def test_a_call_with_no_schema_is_never_retried(monkeypatch):
    sent = _wire(monkeypatch, _refusal('{"error":{"message":"json_schema whatever"}}'))
    with pytest.raises(AIProviderError):
        ClaudeProvider(api_key="k").complete(system="s", user="u")
    assert len(sent) == 1


def test_a_400_that_only_happens_to_say_schema_is_not_retried(monkeypatch):
    """Review 2026-09-28, R22: the unconstrained retry is for the API
    refusing the reply schema itself (`output_config`/`format`/the JSON
    schema), not for any 400 whose text contains the word "schema"."""
    sent = _wire(monkeypatch, _refusal(
        '{"type":"error","error":{"type":"invalid_request_error",'
        '"message":"max_tokens: 200000 > 128000, the maximum for this model '
        '(see the request schema in the API reference)"}}'))
    with pytest.raises(AIProviderError, match="max_tokens"):
        ClaudeProvider(api_key="k").complete(system="s", user="u",
                                             response_schema=SCHEMA)
    assert len(sent) == 1


@pytest.mark.parametrize("message", [
    "output_config.format.schema: schema is too complex",
    "output_config.format: unsupported keyword 'patternProperties'",
    "json_schema: nesting too deep",
    "The compiled grammar for this schema is too large",
    "Schema is too complex for compilation",
])
def test_the_schemas_own_refusals_are_all_retried(monkeypatch, message):
    sent = _wire(monkeypatch, _refusal(json.dumps(
        {"type": "error", "error": {"type": "invalid_request_error", "message": message}})))
    ClaudeProvider(api_key="k", show_progress=False).complete(
        system="s", user="u", response_schema=SCHEMA)
    assert len(sent) == 2


def test_a_name_that_does_not_resolve_says_there_is_no_internet(monkeypatch):
    import socket

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided, or not known"))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AIProviderError, match="no internet connection right now"):
        ClaudeProvider(api_key="k").complete(system="s", user="u")


def test_any_other_network_error_keeps_its_own_words(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AIProviderError) as err:
        ClaudeProvider(api_key="k").complete(system="s", user="u")
    assert "no internet" not in str(err.value)


def test_haiku_is_never_sent_a_reply_schema(monkeypatch):
    sent = _wire(monkeypatch, None)
    ClaudeProvider(api_key="k", model="claude-haiku-4-5").complete(
        system="s", user="u", response_schema=SCHEMA)
    assert "format" not in (sent[0].get("output_config") or {})


def test_other_models_still_get_the_reply_schema(monkeypatch):
    sent = _wire(monkeypatch, None)
    ClaudeProvider(api_key="k", model="claude-sonnet-5").complete(
        system="s", user="u", response_schema=SCHEMA)
    assert "format" in sent[0]["output_config"]
