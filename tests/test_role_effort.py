"""Per-role effort (2026-09-27) and per-role MODEL (2026-09-28): the
generator, the critic and the watchlist draft each run at their own
`output_config.effort`, and the two reading roles on their own model.

The maintainer's baseline festival build on Sonnet 5 spent $0.37 of the critic's
$0.46 thinking, to return ~450 tokens of findings. So the critic and the
watchlist default to `medium` while the generator stays at `high`, each
with its own setting, announced at INFO. The next measured build's critic
restated the generator's own note for a quarter of the bill, so both
reading roles now default to Haiku (docs/developer/build-cost-reduction.md),
with the same announcement naming the model.

No network: every request goes through a stubbed `urlopen` that records
the body it was sent and answers by the system prompt, so the effort on
each of a real `atoo build`'s three calls is read off the wire.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from atoo import generate
from atoo.ai_provider import (
    AIProviderError,
    ClaudeProvider,
    effort_levels,
    provider_from_env,
)
from atoo.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
GENERATED = Path(__file__).parent / "fixtures" / "touringband.generated.plan.json"
ENV = {"ATOO_AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-test"}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _sse(text: str) -> bytes:
    events = [
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 10}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": text}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 20}},
    ]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


@pytest.fixture
def wire(monkeypatch):
    """Every Claude request, by role: {role: request body}. Answers the
    generator with a real plan, the critic and the watchlist with nothing."""
    plan = json.loads(GENERATED.read_text())
    plan["outputs"]["Matrix"]["socket"] = {"group": "USB", "sockets": [40]}
    replies = {
        generate.critic_system(): ("critic", json.dumps({"findings": []})),
        generate.watchlist_system(): ("watchlist", json.dumps({"watch_conditions": []})),
    }
    sent: dict = {}

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        role, text = replies.get(body["system"][0]["text"], ("generator", json.dumps(plan)))
        sent[role] = body
        return _Response(_sse(text))

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    for key in ("ATOO_AI_EFFORT", "ATOO_AI_CRITIC_EFFORT",
                "ATOO_AI_WATCHLIST_EFFORT", "ATOO_AI_MODEL",
                "ATOO_AI_CRITIC_MODEL", "ATOO_AI_WATCHLIST_MODEL",
                "ATOO_AI_THINKING_BUDGET", "ATOO_AI_MAX_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    return sent


def _build(tmp_path) -> dict:
    """`atoo build --show DIR --critic`: all three calls. Returns the
    plan's meta."""
    show = tmp_path / "show"
    show.mkdir(exist_ok=True)   # a second build into the same bundle is a rebuild
    (show / "input.csv").write_text((FIXTURES / "touringband.csv").read_text())
    house = tmp_path / "house-rules.md"
    house.write_text((FIXTURES / "touringband.md").read_text())
    main(["build", "--show", str(show), "--conventions", str(house),
          "--console-model", "wing-compact", "--critic", "--skip-verify"])
    return json.loads((show / "plan.json").read_text())["meta"]


def _efforts(sent: dict) -> dict:
    return {role: (body.get("output_config") or {}).get("effort")
            for role, body in sent.items()}


def _models(sent: dict) -> dict:
    return {role: body["model"] for role, body in sent.items()}


def _one_model(monkeypatch, model: str = "claude-sonnet-5-5") -> None:
    """Every role on `model` -- the default shape since 2026-10-01, set
    explicitly so these effort tests do not depend on it."""
    monkeypatch.setenv("ATOO_AI_CRITIC_MODEL", model)
    monkeypatch.setenv("ATOO_AI_WATCHLIST_MODEL", model)


# ---------------------------------------------------------------------------
# The three calls of a real build
# ---------------------------------------------------------------------------

def _haiku_readers(monkeypatch) -> None:
    """The critic and the watchlist on Haiku 4.5 -- the default from
    2026-09-28 to 2026-10-01, set explicitly for the tests of how a role
    on a smaller, budget-thinking, effort-less model is treated."""
    monkeypatch.setenv("ATOO_AI_CRITIC_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("ATOO_AI_WATCHLIST_MODEL", "claude-haiku-4-5")


def test_defaults_every_role_on_sonnet_5_5(wire, tmp_path, capsys):
    """"Use Sonnet 5.5 medium for all stages." Every
    role on Sonnet 5.5 at `medium`, so the by-role line has nothing to say."""
    meta = _build(tmp_path)
    assert set(_models(wire).values()) == {"claude-sonnet-5-5"}
    assert _efforts(wire) == {"generator": "medium", "critic": "medium", "watchlist": "medium"}
    err = capsys.readouterr().err
    # One model at one effort for every role: the by-role line has
    # nothing to add, so it is not printed.
    assert not [line for line in err.splitlines()
                if line.startswith("INFO model and effort")]
    # FR-X.15c: summaries requested is the default, so it is not said.
    assert "INFO thinking summaries requested" not in err
    # Each usage line names its role's model and effort.
    assert "claude-sonnet-5-5 (generator, effort medium):" in err
    assert "claude-sonnet-5-5 (critic, effort medium):" in err
    assert "claude-sonnet-5-5 (watchlist, effort medium):" in err
    # One model: `meta.model` is it, and `meta.models` has nothing to add.
    assert meta["model"] == "claude-sonnet-5-5"
    assert "models" not in meta
    assert meta["effort"] == {"generator": "medium", "critic": "medium", "watchlist": "medium"}


def test_reading_roles_on_haiku_are_announced_and_sent_no_effort(wire, tmp_path,
                                                                 monkeypatch, capsys):
    """A reading role set to Haiku: named on the INFO line with "no
    effort", sent none, and recorded in `meta.models`."""
    _haiku_readers(monkeypatch)
    meta = _build(tmp_path)
    assert _models(wire) == {"generator": "claude-sonnet-5-5", "critic": "claude-haiku-4-5",
                             "watchlist": "claude-haiku-4-5"}
    assert _efforts(wire) == {"generator": "medium", "critic": None, "watchlist": None}
    err = capsys.readouterr().err
    info = [line for line in err.splitlines() if line.startswith("INFO model and effort")]
    assert info == [
        "INFO model and effort by role: "
        "generator claude-sonnet-5-5 at medium (ATOO_AI_MODEL, ATOO_AI_EFFORT); "
        "critic claude-haiku-4-5 no effort (ATOO_AI_CRITIC_MODEL, "
        "ATOO_AI_CRITIC_EFFORT); "
        "watchlist claude-haiku-4-5 no effort (ATOO_AI_WATCHLIST_MODEL, "
        "ATOO_AI_WATCHLIST_EFFORT)"]
    assert "INFO no effort sent" not in err
    assert "INFO thinking not enabled" not in err
    assert "claude-haiku-4-5 (critic):" in err
    assert meta["models"] == {"generator": "claude-sonnet-5-5", "critic": "claude-haiku-4-5",
                              "watchlist": "claude-haiku-4-5"}
    assert meta["effort"] == {"generator": "medium", "critic": None, "watchlist": None}


def test_the_reading_roles_back_on_the_generators_model(wire, tmp_path, monkeypatch, capsys):
    """Setting a role's model to the generator's puts it back where it
    was: the same model, at its own effort (`medium`)."""
    _one_model(monkeypatch)
    meta = _build(tmp_path)
    assert set(_models(wire).values()) == {"claude-sonnet-5-5"}
    assert _efforts(wire) == {"generator": "medium", "critic": "medium",
                              "watchlist": "medium"}
    err = capsys.readouterr().err
    assert not [line for line in err.splitlines()
                if line.startswith("INFO model and effort")]
    assert "claude-sonnet-5-5 (critic, effort medium):" in err
    # One model: nothing for `meta.models` to say.
    assert "models" not in meta
    assert meta["effort"] == {"generator": "medium", "critic": "medium", "watchlist": "medium"}


def test_a_blank_role_model_means_the_default(wire, tmp_path, monkeypatch):
    monkeypatch.setenv("ATOO_AI_CRITIC_MODEL", "   ")
    _build(tmp_path)
    assert _models(wire)["critic"] == "claude-sonnet-5-5"


def test_any_other_call_runs_on_the_generators_model():
    """A patch's "change" call, or an unlabelled one, constructs -- it is
    not a critic."""
    provider = provider_from_env({**ENV, "ATOO_AI_MODEL": "claude-sonnet-5"})
    assert provider.model_for("change") == "claude-sonnet-5"
    assert provider.model_for("") == "claude-sonnet-5"
    assert provider.model_for("critic") == "claude-sonnet-5-5"


def test_a_role_on_a_smaller_model_is_sent_that_models_ceiling(wire, tmp_path, monkeypatch):
    """Haiku stops at 64K. A 128K ceiling (the generator's default, or an
    explicit ATOO_AI_MAX_TOKENS) sent to it is a 400, not more room."""
    _haiku_readers(monkeypatch)
    _build(tmp_path)
    assert {r: b["max_tokens"] for r, b in wire.items()} == {
        "generator": 128000, "critic": 64000, "watchlist": 64000}
    wire.clear()
    monkeypatch.setenv("ATOO_AI_MAX_TOKENS", "100000")
    _build(tmp_path)
    assert {r: b["max_tokens"] for r, b in wire.items()} == {
        "generator": 100000, "critic": 64000, "watchlist": 64000}
    # ...and an explicit ceiling UNDER the role model's limit is kept.
    wire.clear()
    monkeypatch.setenv("ATOO_AI_MAX_TOKENS", "30000")
    _build(tmp_path)
    assert {r: b["max_tokens"] for r, b in wire.items()} == {
        "generator": 30000, "critic": 30000, "watchlist": 30000}


# ---------------------------------------------------------------------------
# Thinking on the budget models (Haiku 4.5)
# ---------------------------------------------------------------------------

def test_a_haiku_generator_thinks_on_a_budget_and_the_readers_do_not(wire, tmp_path,
                                                                    monkeypatch, capsys):
    """Haiku thinks only when given `budget_tokens`, and until 2026-09-28
    it never was. The generator gets the default budget; the critic and
    the watchlist, which select rather than construct, get none."""
    monkeypatch.setenv("ATOO_AI_MODEL", "claude-haiku-4-5")
    _haiku_readers(monkeypatch)
    _build(tmp_path)
    assert wire["generator"]["thinking"] == {"type": "enabled", "budget_tokens": 16000}
    assert "thinking" not in wire["critic"]
    assert "thinking" not in wire["watchlist"]
    err = capsys.readouterr().err
    assert err.count("INFO thinking enabled on claude-haiku-4-5 with a budget of 16,000 "
                     "tokens for the generator (ATOO_AI_THINKING_BUDGET; 0 turns it "
                     "off)") == 1


def test_the_budget_is_a_setting_and_zero_is_off(wire, tmp_path, monkeypatch):
    monkeypatch.setenv("ATOO_AI_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("ATOO_AI_THINKING_BUDGET", "4096")
    _build(tmp_path)
    assert wire["generator"]["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    wire.clear()
    monkeypatch.setenv("ATOO_AI_THINKING_BUDGET", "0")
    _build(tmp_path)
    assert "thinking" not in wire["generator"]


def test_the_budget_stays_under_the_ceiling(wire, tmp_path, monkeypatch):
    """`budget_tokens` must be below `max_tokens`, or the request is a 400."""
    monkeypatch.setenv("ATOO_AI_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("ATOO_AI_MAX_TOKENS", "8000")
    _build(tmp_path)
    assert wire["generator"]["thinking"] == {"type": "enabled", "budget_tokens": 7999}


@pytest.mark.parametrize("raw", ["abc", "500", "-1"])
def test_a_bad_budget_is_refused_naming_the_setting(raw):
    with pytest.raises(AIProviderError, match="ATOO_AI_THINKING_BUDGET"):
        provider_from_env({**ENV, "ATOO_AI_THINKING_BUDGET": raw})


def test_the_adaptive_models_take_no_budget(wire, tmp_path, monkeypatch):
    """Sonnet 5 thinks by itself; a budget there would be a 400. The
    summaries request stands, and the setting is ignored."""
    monkeypatch.setenv("ATOO_AI_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ATOO_AI_THINKING_BUDGET", "4096")
    _build(tmp_path)
    assert wire["generator"]["thinking"] == {"type": "adaptive", "display": "summarized"}


@pytest.mark.parametrize("var, role", [
    ("ATOO_AI_EFFORT", "generator"),
    ("ATOO_AI_CRITIC_EFFORT", "critic"),
    ("ATOO_AI_WATCHLIST_EFFORT", "watchlist"),
])
def test_each_setting_overrides_its_own_role_only(wire, tmp_path, monkeypatch, var, role):
    _one_model(monkeypatch)
    monkeypatch.setenv(var, "LOW")      # case-insensitive, as ATOO_AI_EFFORT was
    _build(tmp_path)
    expected = {"generator": "medium", "critic": "medium", "watchlist": "medium", role: "low"}
    assert _efforts(wire) == expected


def test_no_announcement_when_every_role_matches_the_generator(wire, tmp_path, monkeypatch,
                                                               capsys):
    _one_model(monkeypatch)
    # Since 2026-10-01 every role defaults to `medium`: one model, one
    # effort, nothing to announce.
    _build(tmp_path)
    assert set(_efforts(wire).values()) == {"medium"}
    assert "INFO model and effort by role" not in capsys.readouterr().err


def test_a_role_that_does_not_run_is_not_announced(capsys):
    provider = provider_from_env({**ENV, "ATOO_AI_CRITIC_EFFORT": "low"})
    assert provider.effort_announcement([]) is None
    assert provider.effort_announcement(["critic"]) == (
        "INFO model and effort by role: "
        "generator claude-sonnet-5-5 at medium (ATOO_AI_MODEL, ATOO_AI_EFFORT); "
        "critic claude-sonnet-5-5 at low (ATOO_AI_CRITIC_MODEL, "
        "ATOO_AI_CRITIC_EFFORT)")
    # Every role on one model at one effort (the default): nothing to say.
    assert ClaudeProvider(api_key="k").effort_announcement(["critic"]) is None


def test_any_other_call_runs_at_the_generators_effort():
    """A patch's "change" call, or an unlabelled one, is not a critic."""
    provider = provider_from_env({**ENV, "ATOO_AI_EFFORT": "xhigh",
                                  "ATOO_AI_CRITIC_MODEL": "claude-sonnet-5"})
    assert provider.effort_for("change") == "xhigh"
    assert provider.effort_for("") == "xhigh"
    assert provider.effort_for("critic") == "medium"
    # ...and None where the role's model takes none (Haiku).
    assert provider_from_env({**ENV, "ATOO_AI_CRITIC_MODEL": "claude-haiku-4-5"}
                             ).effort_for("critic") is None


# ---------------------------------------------------------------------------
# Refused: a value no model takes, or one this model does not
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("var", ["ATOO_AI_EFFORT", "ATOO_AI_CRITIC_EFFORT",
                                 "ATOO_AI_WATCHLIST_EFFORT"])
def test_an_invalid_value_is_refused_naming_the_setting(var):
    with pytest.raises(AIProviderError) as exc:
        provider_from_env({**ENV, var: "extreme"})
    message = str(exc.value)
    assert message.startswith(f"{var} 'extreme' is not one of")
    assert "low, medium, high, xhigh, max" in message


def test_a_level_this_model_does_not_take_is_refused_before_a_call():
    """Opus 4.5 takes low/medium/high only: xhigh there is a 400."""
    with pytest.raises(AIProviderError, match="ATOO_AI_CRITIC_EFFORT 'xhigh' is not a "
                                              "level claude-opus-4-5 accepts"):
        provider_from_env({**ENV, "ATOO_AI_MODEL": "claude-opus-4-5",
                           "ATOO_AI_CRITIC_MODEL": "claude-opus-4-5",
                           "ATOO_AI_CRITIC_EFFORT": "xhigh"})
    # Checked against the ROLE's model, not the generator's: the same
    # xhigh critic on Sonnet 5 under an Opus 4.5 generator is fine.
    provider_from_env({**ENV, "ATOO_AI_MODEL": "claude-opus-4-5",
                       "ATOO_AI_CRITIC_MODEL": "claude-sonnet-5",
                       "ATOO_AI_CRITIC_EFFORT": "xhigh"})
    # The defaults are levels every effort-taking model accepts.
    for model in ("claude-opus-4-5", "claude-opus-4-6", "claude-sonnet-4-6",
                  "claude-sonnet-5", "claude-opus-5"):
        provider_from_env({**ENV, "ATOO_AI_MODEL": model,
                           "ATOO_AI_CRITIC_MODEL": model,
                           "ATOO_AI_WATCHLIST_MODEL": model})


def test_level_table():
    assert effort_levels("claude-sonnet-5") == ("low", "medium", "high", "xhigh", "max")
    assert effort_levels("claude-sonnet-4-6") == ("low", "medium", "high", "max")
    assert effort_levels("claude-haiku-4-5") == ()


# ---------------------------------------------------------------------------
# Haiku 4.5: takes no effort at all
# ---------------------------------------------------------------------------

def test_haiku_is_sent_no_effort_for_any_role(wire, tmp_path, monkeypatch, capsys):
    """Haiku 4.5 refuses `effort` with a 400. None is sent, for any role --
    and a setting asking for one is not refused, since there is nothing
    to set: said once at INFO instead."""
    monkeypatch.setenv("ATOO_AI_MODEL", "claude-haiku-4-5")
    _haiku_readers(monkeypatch)
    monkeypatch.setenv("ATOO_AI_CRITIC_EFFORT", "max")
    meta = _build(tmp_path)
    assert _efforts(wire) == {"generator": None, "critic": None, "watchlist": None}
    for body in wire.values():
        assert "effort" not in json.dumps(body.get("output_config") or {})
    err = capsys.readouterr().err
    assert "INFO model and effort by role" not in err
    assert err.count("INFO no effort sent: claude-haiku-4-5") == 1
    assert "claude-haiku-4-5 (critic):" in err
    assert meta["effort"] == {"generator": None, "critic": None, "watchlist": None}


def test_the_progress_snapshot_carries_each_calls_effort(wire):
    """What the Setup page's build readout names on each chip."""
    from atoo.progress import model_progress_listener

    seen: list[dict] = []
    provider = provider_from_env({**ENV, "ATOO_AI_CRITIC_MODEL": "claude-haiku-4-5"})
    with model_progress_listener(seen.append):
        provider.complete(system=generate.critic_system(), user="u", label="critic")
    assert seen[-1]["label"] == "critic"
    # The critic's own model, and no effort, since Haiku takes none...
    assert seen[-1]["model"] == "claude-haiku-4-5"
    assert seen[-1]["effort"] == ""
    # ...and its effort once it runs on a model that has one.
    provider = provider_from_env({**ENV, "ATOO_AI_CRITIC_MODEL": "claude-opus-5"})
    with model_progress_listener(seen.append):
        provider.complete(system=generate.critic_system(), user="u", label="critic")
    assert seen[-1]["model"] == "claude-opus-5"
    assert seen[-1]["effort"] == "medium"


# ---------------------------------------------------------------------------
# Other providers ignore it, as before
# ---------------------------------------------------------------------------

def test_other_providers_take_no_effort_and_record_none(tmp_path, monkeypatch):
    monkeypatch.setenv("ATOO_AI_PROVIDER", "ollama")
    monkeypatch.setenv("ATOO_AI_CRITIC_EFFORT", "low")
    provider = provider_from_env()
    assert not hasattr(provider, "effort_for")
