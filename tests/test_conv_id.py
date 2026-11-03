"""The api provider's `x-grok-conv-id` is stable per show.

A host that caches the prompt prefix (xAI) keys its cache on this header.
It used to be random per process, so two commands on one show never shared
a cache. It is now a one-way hash of the show folder's resolved path, the
same for `build` and `patch` on the same show and different for another,
and it carries neither the path, nor anything in the show, nor the key.
With no show it is the same hash of the working folder: stable, not random.

The host here is the fake one `tests/test_api_structured.py` serves; the
show is a copy of the starter Demo show.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atoo import ai_provider, cli, patch
from atoo.ai_provider import AIProviderError, conv_id_for, provider_from_env
from tests.test_api_structured import _compile, host, ok  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
KEY = "sk-very-secret-key-1129"
ENV = {"ATOO_AI_PROVIDER": "api", "ATOO_AI_API_KEY": KEY}


@pytest.fixture
def shows(tmp_path):
    made = []
    for name in ("church", "tour"):
        shutil.copytree(ROOT / "starter" / "demo-show", tmp_path / name)
        made.append(tmp_path / name)
    return made


def test_the_same_show_gives_the_same_id_and_another_show_another(shows):
    church, tour = shows
    first = provider_from_env(ENV, show_dir=church).conv_id
    assert provider_from_env(ENV, show_dir=church).conv_id == first
    # A path to the same folder, spelled another way, is the same show.
    assert provider_from_env(ENV, show_dir=church / ".." / "church").conv_id == first
    assert provider_from_env(ENV, show_dir=tour).conv_id != first
    assert len(first) == 32 and int(first, 16) >= 0


def test_it_carries_no_key_no_path_and_nothing_from_the_show(shows):
    church, _tour = shows
    conv = provider_from_env(ENV, show_dir=church).conv_id
    plan_names = ("Kick", "Snare", "Lead Vox", "Keys L")
    for secret in (KEY, KEY[-8:], "church", str(church), *plan_names):
        assert secret.lower() not in conv.lower(), secret


def test_with_no_show_it_is_stable_not_random(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert provider_from_env(ENV).conv_id == provider_from_env(ENV).conv_id == conv_id_for(None)
    # A show is never the same id as running in its folder with no show.
    assert conv_id_for(tmp_path) != conv_id_for(None)


def test_two_commands_on_one_show_send_one_id_to_the_host(host, shows):
    church, tour = shows
    sent = []
    for show in (church, church, tour):
        h = host(ok(patch.empty_change_set("x")))
        _compile(h.provider(conv_id=conv_id_for(show)))
        sent.append(h.headers[0][ai_provider.CONV_ID_HEADER])
    assert sent[0] == sent[1] != sent[2]
    assert all(KEY not in s and "Authorization" not in s for s in sent)


@pytest.mark.parametrize("argv", [
    ["build", "--console-model", "wing-compact", "--conventions", "starter/conventions.md"],
    ["patch", "Add a vocal mic on LCL 9", "--state", "atoo/web/demo_states/before.json"],
])
def test_build_and_patch_hand_the_provider_their_show(argv, shows, monkeypatch, capsys):
    church, _tour = shows
    keyed = []

    def stand_in(provider, show):
        provider = real(provider, show)
        keyed.append(provider.conv_id)
        raise AIProviderError("no model in this test")

    real = cli.for_show
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(cli, "provider_from_env", lambda: provider_from_env(ENV))
    monkeypatch.setattr(cli, "for_show", stand_in)
    cli.main([*argv, "--show", str(church)])
    assert keyed == [conv_id_for(church)]


def test_a_provider_without_the_header_is_left_as_it_is(shows):
    church, _tour = shows
    fake = ai_provider.FakeProvider(response="{}")
    assert cli.for_show(fake, type("Show", (), {"directory": church})()) is fake
    assert not hasattr(fake, "conv_id")
