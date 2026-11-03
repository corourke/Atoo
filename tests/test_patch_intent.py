"""`atoo patch --intent`: the same review as any change, with an intent compiled
by code between the model and the merge (`atoo/intent.py`). The desk is
`test_amend.DeskConsole`, seeded from the frozen applied show; a `FakeProvider`
answers with an intent. Nothing reads `examples/`.
"""

from __future__ import annotations

import json

from atoo import cli, journal_stack
from atoo.ai_provider import FakeProvider
from test_patch import HORNS_TEXT, _bundle, _patch, _writes, desk  # noqa: F401  (fixtures)

import pytest

HORNS_INTENT = {"name": "Horns for tonight", "notes": [], "ops": [
    {"op": "add_channel", "name": "Trumpet", "patch": {"group": "A", "first": 21},
     "dca": ["Horns"], "mute_group": ["Band"]},
    {"op": "add_channel", "name": "Trombone", "patch": {"group": "A", "first": 22},
     "dca": ["Horns"], "mute_group": ["Band"]},
    {"op": "add_channel", "name": "Sax", "patch": {"group": "A", "first": 23},
     "dca": ["Horns"], "mute_group": ["Band"]}]}


@pytest.fixture
def model(monkeypatch):
    fake = FakeProvider(response=json.dumps(HORNS_INTENT))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


def test_an_intent_is_reviewed_like_any_change_and_writes_nothing(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _patch(show, "--intent") == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "Change: Horns for tonight" in out and "3 added" in out
    assert "the socket the change named" in out            # A 21-23 were typed
    assert _writes(desk) == [] and (show / "plan.json").read_bytes() == before
    assert journal_stack.entries(show) == []


def test_the_model_is_asked_for_an_intent_not_a_change_set(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    assert _patch(show, "--intent") == 0, capsys.readouterr()
    [(system, user)] = model.calls
    assert "INTENT" in system and "CHANGE SET" not in system
    assert model.labels == ["intent"] and "ops" in model.schemas[0]["properties"]
    assert HORNS_TEXT in user and "READ-ONLY" not in user
    assert '"preset_values"' not in user                  # a slice of the desk, not the plan


def test_a_socket_the_compiler_chooses_is_announced_once_and_as_atoos(tmp_path, desk, model, capsys):
    model.response = json.dumps({"name": "Add Trumpet", "notes": [], "ops": [
        {"op": "add_channel", "name": "Trumpet", "dca": ["Horns"]}]})
    show = _bundle(tmp_path)
    assert _patch(show, "--intent", text="add a trumpet in a Horns DCA") == 0, capsys.readouterr()
    out = capsys.readouterr().out
    said = [line for line in out.splitlines() if "'Trumpet'" in line and "no socket" in line]
    assert len(said) == 1 and "the first the model picked" not in said[0]


def test_what_the_console_cannot_do_is_refused_with_the_reason_and_nothing_is_written(
        tmp_path, desk, model, capsys):
    model.response = json.dumps({"name": "Add Tamb", "notes": [], "ops": [
        {"op": "add_channel", "name": "Tamb", "patch": {"group": "A", "first": 49}}]})
    show = _bundle(tmp_path)
    assert _patch(show, "--intent", text='add a tambourine mic "Tamb" on A 49', confirm=True) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out and "A 49 does not exist" in out and "nothing was written" in out
    assert _writes(desk) == []


def test_the_change_set_it_saves_carries_what_was_asked_and_replays_the_same(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    saved = tmp_path / "saved.json"
    assert _patch(show, "--intent", "--save-change-set", str(saved)) == 0, capsys.readouterr()
    payload = json.loads(saved.read_text())
    assert payload["asked"]["picked_by"] == "Atoo" and payload["change"] == HORNS_TEXT
    capsys.readouterr()
    assert _patch(show, "--change-set", str(saved), text=None) == 0, capsys.readouterr()
    assert "3 added" in capsys.readouterr().out


def test_an_intent_file_is_compiled_with_no_model_at_all(tmp_path, desk, monkeypatch, capsys):
    monkeypatch.setattr(cli, "provider_from_env", lambda: pytest.fail("no model may be called"))
    intent_file = tmp_path / "horns.intent.json"
    intent_file.write_text(json.dumps(HORNS_INTENT))
    show = _bundle(tmp_path)
    assert _patch(show, "--intent-file", str(intent_file)) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "3 added" in out and "model call: none (--intent-file" in out
    assert _patch(show, "--intent-file", str(intent_file), "--intent") == 1
    assert "give one" in capsys.readouterr().err
    intent_file.write_text("{not json")
    assert _patch(show, "--intent-file", str(intent_file)) == 1
    assert "--intent-file" in capsys.readouterr().err
