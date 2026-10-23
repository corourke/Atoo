"""atoo.ai_provider: the swappable-provider interface (FR-X.9).
Everything here runs offline -- no network, no live model -- via
FakeProvider and provider_from_env()'s pure dispatch logic. See
ai_provider.py's module docstring for why ApiKeyProvider/OllamaProvider's
actual HTTP calls are deliberately NOT exercised here."""

import pytest

from atoo.ai_provider import (
    AIProviderError,
    ApiKeyProvider,
    FakeProvider,
    OllamaProvider,
    provider_from_env,
)


def test_fake_provider_returns_configured_response():
    provider = FakeProvider(response="hello")
    assert provider.complete(system="sys", user="user text") == "hello"
    assert provider.calls == [("sys", "user text")]


def test_fake_provider_looks_up_by_exact_input():
    provider = FakeProvider(responses_by_input={"conventions text": '{"patch_order": []}'})
    assert provider.complete(system="sys", user="conventions text") == '{"patch_order": []}'


def test_fake_provider_raises_when_unconfigured():
    provider = FakeProvider()
    with pytest.raises(AIProviderError):
        provider.complete(system="sys", user="anything")


def test_provider_from_env_defaults_to_claude():
    # Changed 2026-10-01 (the maintainer): the default is Claude. It was Ollama
    # from 2026-09-10; with nothing set, a user got a local llama3.1 they
    # never chose. Ollama is one variable away.
    from atoo.ai_provider import ClaudeProvider, DEFAULT_MODEL
    provider = provider_from_env({"ANTHROPIC_API_KEY": "sk-test"})
    assert isinstance(provider, ClaudeProvider)
    assert provider.model == DEFAULT_MODEL


def test_the_default_with_no_key_says_both_ways_forward():
    with pytest.raises(AIProviderError, match=r"ANTHROPIC_API_KEY.*ATOO_AI_PROVIDER=ollama"):
        provider_from_env({})


def test_provider_from_env_selects_api_backend_explicitly():
    provider = provider_from_env({"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": "sk-test"})
    assert isinstance(provider, ApiKeyProvider)
    assert provider.api_key == "sk-test"
    assert provider.model == "gpt-4o-mini"
    assert provider.base_url == "https://api.openai.com"


def test_provider_from_env_respects_overrides():
    provider = provider_from_env({
        "ATOO_AI_PROVIDER": "api",
        "ATOO_AI_API_KEY": "sk-test",
        "ATOO_AI_MODEL": "gpt-4o",
        "ATOO_AI_BASE_URL": "https://my-proxy.example",
    })
    assert provider.model == "gpt-4o"
    assert provider.base_url == "https://my-proxy.example"


def test_provider_from_env_selects_ollama():
    provider = provider_from_env({"ATOO_AI_PROVIDER": "ollama"})
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama3.1"
    assert provider.base_url == "http://localhost:11434"


def test_provider_from_env_ollama_respects_overrides():
    provider = provider_from_env({
        "ATOO_AI_PROVIDER": "OLLAMA",
        "ATOO_AI_MODEL": "mistral",
        "ATOO_AI_BASE_URL": "http://otherhost:11434",
    })
    assert provider.model == "mistral"
    assert provider.base_url == "http://otherhost:11434"


def test_api_backend_raises_without_api_key():
    with pytest.raises(AIProviderError, match="ATOO_AI_API_KEY"):
        provider_from_env({"ATOO_AI_PROVIDER": "api"})


def test_provider_from_env_raises_on_unknown_backend():
    with pytest.raises(AIProviderError, match="unknown ATOO_AI_PROVIDER"):
        provider_from_env({"ATOO_AI_PROVIDER": "carrier-pigeon"})


# -- pricing an OpenAI-compatible host -------------------------

def _api_env(**extra):
    return {"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": "sk-test", **extra}


def test_api_prices_come_from_the_environment():
    provider = provider_from_env(_api_env(ATOO_AI_PRICE_IN="0.2", ATOO_AI_PRICE_OUT="0.5"))
    assert provider.price == (0.2, 0.5)


def test_api_with_no_price_set_has_no_price():
    provider = provider_from_env(_api_env())
    assert provider.price is None


@pytest.mark.parametrize("only", ["ATOO_AI_PRICE_IN", "ATOO_AI_PRICE_OUT"])
def test_one_price_without_the_other_is_refused(only):
    with pytest.raises(AIProviderError, match=r"ATOO_AI_PRICE_IN and ATOO_AI_PRICE_OUT go together"):
        provider_from_env(_api_env(**{only: "1"}))


@pytest.mark.parametrize("bad", ["cheap", "-1", "nan", "inf", "$2"])
def test_a_price_that_is_not_a_number_of_dollars_is_refused(bad):
    with pytest.raises(AIProviderError, match=r"ATOO_AI_PRICE_IN must be a number"):
        provider_from_env(_api_env(ATOO_AI_PRICE_IN=bad, ATOO_AI_PRICE_OUT="1"))
