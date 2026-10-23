"""A provider call that fails or is refused says one thing -- that the AI isn't
responding -- and then the provider's own reason, whichever provider and
whichever failure. Nothing here is specific to a spend limit:
the over-limit 400 is just a 400 with a body. No network, no key: `urlopen`
is replaced by a host that returns each failure class."""

import io
import json
import socket
import urllib.error

import pytest

from atoo import cli
from atoo.ai_provider import (AI_NOT_RESPONDING, AIProviderError, ApiKeyProvider,
                              ClaudeProvider, OllamaProvider)

KEY = "sk-secret-key-0123456789"
OVER_LIMIT = ('{"type":"error","error":{"type":"invalid_request_error","message":'
              '"You have reached your specified workspace API usage limits."}}')


def _http(code, body):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(body.encode()))
    return urlopen


def _raises(exc):
    def urlopen(req, timeout=None):
        raise exc
    return urlopen


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _reply(lines):
    return lambda req, timeout=None: _Reply("".join(f"{ln}\n" for ln in lines).encode())


PROVIDERS = {
    "claude": lambda: ClaudeProvider(api_key=KEY, show_progress=False),
    "api": lambda: ApiKeyProvider(api_key=KEY, base_url="https://host.example", model="m",
                                  show_progress=False),
    "ollama": lambda: OllamaProvider(model="m", show_progress=False, num_ctx=8192),
}

CLASSES = {
    "over-limit-400": (_http(400, OVER_LIMIT), "HTTP 400", "usage limits"),
    "401": (_http(401, '{"error":{"message":"invalid x-api-key"}}'), "HTTP 401", "invalid x-api-key"),
    "429": (_http(429, '{"error":{"message":"rate limited"}}'), "HTTP 429", "rate limited"),
    "500": (_http(500, "upstream exploded"), "HTTP 500", "upstream exploded"),
    "connection": (_raises(urllib.error.URLError(ConnectionRefusedError("refused"))), "refused", ""),
    "timeout": (_raises(TimeoutError("timed out")), "timed out", ""),
}


@pytest.mark.parametrize("name", PROVIDERS)
@pytest.mark.parametrize("failure", CLASSES)
def test_every_failure_class_says_the_ai_isnt_responding_and_why(monkeypatch, name, failure):
    urlopen, status, text = CLASSES[failure]
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("atoo.ai_provider.OllamaProvider._model_context_ceiling",
                        lambda self: None, raising=False)
    with pytest.raises(AIProviderError) as caught:
        PROVIDERS[name]().complete(system="s", user="u")
    message = str(caught.value)
    first, _, rest = message.partition("\n")
    assert first == AI_NOT_RESPONDING
    assert status in rest and text in rest
    assert KEY not in message


def test_a_key_the_provider_echoes_back_is_hidden(monkeypatch):
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        _http(401, f'{{"error":{{"message":"bad key {KEY}"}}}}'))
    with pytest.raises(AIProviderError) as caught:
        PROVIDERS["claude"]().complete(system="s", user="u")
    assert KEY not in str(caught.value) and "[key hidden]" in str(caught.value)


def test_an_empty_reply_is_not_responding(monkeypatch):
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        _reply(['data: {"type":"message_stop"}']))
    with pytest.raises(AIProviderError, match="isn't responding"):
        PROVIDERS["claude"]().complete(system="s", user="u")


def test_a_stream_error_event_is_not_responding(monkeypatch):
    event = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen",
                        _reply([f"data: {json.dumps(event)}"]))
    with pytest.raises(AIProviderError) as caught:
        PROVIDERS["claude"]().complete(system="s", user="u")
    assert "isn't responding" in str(caught.value) and "Overloaded" in str(caught.value)


@pytest.mark.parametrize("code", [400, 401, 429, 500])
def test_no_error_is_retried_but_a_400_naming_an_optional_field(monkeypatch, code):
    """The only retries are a 400 that names a field the host may not know
    (`api`) or the reply schema itself (Claude); every other status is one
    call. The over-limit 400 names neither, so it is one call too."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _http(code, OVER_LIMIT if code == 400 else "no")(req)

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", urlopen)
    for make in (PROVIDERS["claude"], PROVIDERS["api"]):
        calls.clear()
        with pytest.raises(AIProviderError):
            make().complete(system="s", user="u", response_schema={"type": "object"})
        assert len(calls) == 1


TIER_CAP = ('{"type":"error","error":{"type":"rate_limit_error","message":"Your organization '
            'has reached its spend limit.","details":{"error_code":"enforced_spend_limit_reached"}}}')


@pytest.mark.parametrize("name", ["claude", "api"])
def test_an_org_spend_cap_429_with_no_retry_after_is_one_call_with_its_details(monkeypatch, name):
    """The 429 carries `error.details.error_code` and no retry-after header:
    the reason keeps the nested details word for word, and nothing waits or
    asks again (this module has no retry-on-429 loop, before or after)."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append(1)
        return _http(429, TIER_CAP)(req)

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("atoo.ai_provider.time.sleep",
                        lambda s: pytest.fail("a 429 must not wait and retry"), raising=False)
    with pytest.raises(AIProviderError) as caught:
        PROVIDERS[name]().complete(system="s", user="u")
    message = str(caught.value)
    assert message.startswith(AI_NOT_RESPONDING + "\n")
    assert "HTTP 429" in message and "enforced_spend_limit_reached" in message
    assert len(calls) == 1
