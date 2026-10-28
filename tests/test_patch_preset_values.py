"""`atoo patch` on a show built with presets: an edit to a running channel or
bus is not refused for carrying the values its preset was expanded into.

A built plan holds `processing.preset_values` on a channel and
`preset_values` on a bus (`preset_expand`, `bus_presets`). The shape a
MODEL is asked for leaves them out, and the edited entry used to be checked
against that shape -- so every edit to a running channel of such a show was
refused with "'Snare'.processing.preset_values: not a field this format
has". These tests hold three things:

* an edit of any kind goes through, and the expanded values are the plan's
  own, unmoved, afterwards;
* a field the format truly lacks, and the expanded values themselves, are
  still refused;
* it holds on the command line, in the browser, and on every plan in
  `tests/fixtures/` that carries a preset's values.

The plan is built here from the frozen applied show and the frozen preset
library; nothing reads a bundle under `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import cli, journal_stack, patch, preset_expand
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from atoo.presets import PresetLibrary
from test_amend import DeskConsole, applied_plan, horn, occupancy
from test_amend_plan_json import _seed

FIXTURES = Path(__file__).parent / "fixtures"
LIBRARY = FIXTURES / "channel_presets"


def preset_plan() -> dict:
    """The frozen applied show with a preset named on Kick, Snare and the
    Drums bus, expanded the way a build expands them."""
    plan = applied_plan()
    by_name = {c["name"]: c for c in plan["channels"]}
    by_name["Kick"]["processing"]["preset"] = "Kick In"
    by_name["Snare"]["processing"]["preset"] = "Snare"
    by_name["Snare"]["fader"]["fader_db"] = -6.0
    plan["busses"]["Drums"]["preset"] = "Mix Bus"
    preset_expand.expand_plan(plan, PresetLibrary(LIBRARY))
    return plan


def _channel(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


def _modify(name: str, fields: dict, obj: str = "channel") -> dict:
    return {"object": obj, "name": name, "change": "as typed", "fields": fields}


def _change_set(*modify: dict) -> dict:
    change_set = patch.empty_change_set("Edits")
    change_set["modify"] = list(modify)
    return patch.validate_change_set(change_set)


def _review(plan: dict, change_set: dict, text: str = ""):
    return patch.plan_patch(plan, change_set, occupancy(), text=text)


def _refusals(amendment) -> list:
    return [c for c in amendment.changes if c.kind is ChangeKind.REFUSED]


def test_the_fixture_plan_really_carries_the_expanded_values():
    plan = preset_plan()
    assert _channel(plan, "Snare")["processing"]["preset_values"]["leaves"]
    assert plan["busses"]["Drums"]["preset_values"]["leaves"]
    assert _channel(plan, "Kick")["processing"]["preset_values"]["leaves"]
    assert "preset_values" not in _channel(plan, "BassDI")["processing"]


# ======================================================================
# Every kind of edit goes through
# ======================================================================

EDITS = {
    "rename": ({"name": "Test Vox"}, "rename channel 2 to Test Vox"),
    "fader": ({"fader.fader_db": -10.0}, "set the Snare fader to -10dB"),
    "mute": ({"fader.muted": True}, "mute the Snare"),
    "high-pass": ({"processing.hpf_hz": 100}, "HPF 100 on the Snare"),
    "gain": ({"processing.gain_db": 12}, "Snare gain 12"),
    "color": ({"color": "Blue"}, "Snare blue"),
    "dca": ({"dca": ["Band"]}, "Snare in the Band DCA"),
    "mute group": ({"mute_group": []}, "Snare out of every mute group"),
    "send": ({"bus_sends": [{"bus": "MON1", "mode": "pre", "level_db": -5.0}]},
             "Snare in MON1 at -5"),
    "move": ({"patch": {"group": "A", "sockets": [30], "stated": True}}, "move the Snare to A 30"),
}


@pytest.mark.parametrize("fields,text", EDITS.values(), ids=EDITS.keys())
def test_an_edit_of_a_channel_that_carries_preset_values_is_not_refused(fields, text):
    plan = preset_plan()
    amendment, merge = _review(plan, _change_set(_modify("Snare", fields)), text)
    assert _refusals(amendment) == []
    assert not amendment.blocked
    assert [e.path.split(".")[0] for e in merge.edits] == [next(iter(fields)).split(".")[0]]


@pytest.mark.parametrize("fields,text", EDITS.values(), ids=EDITS.keys())
def test_the_expanded_values_are_the_plans_own_afterwards(fields, text):
    plan = preset_plan()
    _amendment, merge = _review(plan, _change_set(_modify("Snare", fields)), text)
    before = _channel(plan, "Snare")
    after = next(c for c in merge.plan["channels"] if c["channel"] == before["channel"])
    assert after["processing"]["preset_values"] == before["processing"]["preset_values"]
    assert _channel(merge.plan, "Kick") == _channel(plan, "Kick")


def test_an_edit_of_a_bus_that_carries_preset_values_is_not_refused():
    plan = preset_plan()
    amendment, merge = _review(
        plan, _change_set(_modify("Drums", {"fader.fader_db": -4.0}, obj="bus")),
        "Drums bus fader -4")
    assert _refusals(amendment) == []
    assert merge.plan["busses"]["Drums"]["preset_values"] == plan["busses"]["Drums"]["preset_values"]
    assert [e.path for e in merge.edits] == ["fader.fader_db"]


def test_adding_and_removing_channels_beside_preset_channels_is_not_refused():
    plan = preset_plan()
    change_set = patch.empty_change_set("Horns")
    change_set["add"]["channels"] = [horn(20, "Trumpet", 21)]
    change_set["drop"]["channels"] = ["Snare"]
    amendment, merge = _review(plan, patch.validate_change_set(change_set))
    assert _refusals(amendment) == []
    kinds = {c.kind for c in amendment.changes}
    assert ChangeKind.ADDED in kinds and ChangeKind.RELEASED in kinds
    assert _channel(merge.plan, "Kick") == _channel(plan, "Kick")


def test_restating_the_whole_processing_object_does_not_drop_the_expanded_values():
    plan = preset_plan()
    snare = _channel(plan, "Snare")
    restated = {k: v for k, v in snare["processing"].items() if k != "preset_values"}
    restated["hpf_hz"] = 90
    amendment, merge = _review(plan, _change_set(_modify("Snare", {"processing": restated})))
    assert _refusals(amendment) == []
    assert [e.path for e in merge.edits] == ["processing.hpf_hz"]
    assert _channel(merge.plan, "Snare")["processing"]["preset_values"] == \
        snare["processing"]["preset_values"]


# ======================================================================
# What is still refused
# ======================================================================


@pytest.mark.parametrize("fields,words", [
    ({"processing.foo": 1}, "processing.foo: not a field this format has"),
    ({"processing.hpf_hz": 5}, "hpf_hz"),
    ({"processing.preset_values": None}, "the build's own record"),
    ({"processing.preset_values.leaves": {}}, "the build's own record"),
])
def test_a_field_the_format_lacks_and_the_expanded_values_themselves_are_still_refused(
        fields, words):
    plan = preset_plan()
    amendment, merge = _review(plan, _change_set(_modify("Snare", fields)))
    [refused] = _refusals(amendment)
    assert words in refused.reason
    assert amendment.blocked
    assert _channel(merge.plan, "Snare") == _channel(plan, "Snare")


def test_the_expanded_values_of_a_bus_are_not_a_setting_either():
    plan = preset_plan()
    amendment, _m = _review(
        plan, _change_set(_modify("Drums", {"preset_values": {}}, obj="bus")))
    [refused] = _refusals(amendment)
    assert "the build's own record" in refused.reason


def test_a_bus_preset_switch_with_no_library_loaded_is_held_saying_why():
    """With no preset library there are no values to write: the switch is
    held, the plan unchanged, and the reason given. (With one, the bus
    preset is switched, its effect included: `test_patch_bus_preset_switch.py`,
    an earlier change.)"""
    plan = preset_plan()
    amendment, merge = _review(plan, _change_set(_modify("Drums", {"preset": "Vocal"}, obj="bus")))
    assert _refusals(amendment) == [] and merge.edits == []
    [held] = [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert held.reason == ("preset -> 'Vocal' -- not written: no preset library is loaded to "
                           "read the preset's values from")
    assert merge.plan["channels"] == plan["channels"]
    for field in ("preset", "preset_values"):
        assert merge.plan["busses"]["Drums"][field] == plan["busses"]["Drums"][field]


# ======================================================================
# Every plan in tests/fixtures/ that carries a preset's values
# ======================================================================


def _plans_with_preset_values() -> list[Path]:
    found = []
    for path in sorted(FIXTURES.rglob("*.json")):
        text = path.read_text()
        if "preset_values" not in text:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("channels"), list):
            found.append(path)
    return found


PLANS = _plans_with_preset_values()


def test_the_sweep_finds_plans():
    assert len(PLANS) >= 5


@pytest.mark.parametrize("path", PLANS, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_every_kind_of_edit_works_on_a_fixture_plan_with_preset_values(path):
    plan = json.loads(path.read_text())
    channel = next(c for c in plan["channels"]
                   if isinstance(c, dict) and c.get("channel") is not None
                   and (c.get("processing") or {}).get("preset_values"))
    name = channel["name"]
    edits = [
        (_modify(name, {"name": "Renamed"}), ""),
        (_modify(name, {"fader.fader_db": -10.0}), "set the fader to -10"),
        (_modify(name, {"fader.muted": True}), "mute it"),
        (_modify(name, {"processing.hpf_hz": 100}), ""),
        (_modify(name, {"dca": []}), ""),
    ]
    bus = next((n for n, b in (plan.get("busses") or {}).items()
                if isinstance(b, dict) and b.get("preset_values")), None)
    if bus:
        edits.append((_modify(bus, {"fader.fader_db": -4.0}, obj="bus"), "bus fader -4"))
    for modify, text in edits:
        amendment, merge = patch.plan_patch(plan, _change_set(modify), [], text=text)
        assert _refusals(amendment) == [], (path.name, modify["fields"])
        assert merge.edits, (path.name, modify["fields"])


# ======================================================================
# `atoo patch`, end to end, on the simulated desk
# ======================================================================

TEXT = "rename channel 2 to Test Vox"


@pytest.fixture
def desk(monkeypatch):
    console = DeskConsole(_seed(preset_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


@pytest.fixture
def model(monkeypatch):
    fake = FakeProvider(response=json.dumps(_change_set(
        _modify("Snare", {"name": "Test Vox"}))))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


def _bundle(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(preset_plan(), indent=4) + "\n")
    return show


def _patch(show, text, *extra, confirm=False):
    return cli.main(["patch", "--show", str(show), text, "--console", "198.51.100.9",
                     "--no-progress", *(["--confirm"] if confirm else []), *extra])


def _leaves_written(console) -> set[str]:
    return {a for a, _v, _t in console.set_param_calls} | {
        f"{a}/{command.partition('=')[0]}" for a, command in console.set_node_calls}


def test_the_desk_holds_the_presets_values_before_the_patch(desk):
    assert any(address.startswith("/ch/2/gate/") for address in desk.state)


def test_patch_renames_a_preset_channel_writes_only_the_name_and_undoes(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _patch(show, TEXT, confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "REFUSED" not in out and "not a field this format has" not in out
    assert "EDITED" in out and "name" in out and "0 changed" in out
    assert desk.state["/ch/2/name"][0] == "Test Vox"
    written = _leaves_written(desk)
    assert "/ch/2/name" in written
    assert not any(a.startswith(("/ch/2/gate", "/ch/2/eq", "/ch/2/dyn", "/ch/2/peq"))
                   for a in written), sorted(written)
    assert (show / "plan.json").read_bytes() == before
    [entry] = journal_stack.entries(show)
    left = json.loads(entry.path.read_text())[journal_stack.DESK_PLAN_BLOCK]["plan"]
    assert _channel(left, "Test Vox")["processing"]["preset_values"] == \
        _channel(preset_plan(), "Snare")["processing"]["preset_values"]

    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert desk.state["/ch/2/name"][0] == "Snare"


def test_patch_sets_the_fader_of_a_preset_channel(tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify("Snare", {"fader.fader_db": -10.0})))
    show = _bundle(tmp_path)
    assert _patch(show, "set the Snare fader to -10dB", confirm=True) == 0, capsys.readouterr()
    assert desk.state["/ch/2/fdr"][0] == pytest.approx(-10.0)
    assert _leaves_written(desk) == {"/ch/2/fdr"}


def test_patch_still_refuses_a_field_the_format_lacks_and_says_what_it_is(
        tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify("Snare", {"processing.foo": 1})))
    show = _bundle(tmp_path)
    assert _patch(show, "foo the snare", confirm=True) == 2
    out = capsys.readouterr().out
    assert "not a field this format has" in out
    assert _leaves_written(desk) == set()
