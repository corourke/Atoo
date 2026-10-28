"""Switching a running bus's preset.

"Put the Vox Verb preset on the Drums bus" is an instruction. The bus
preset's values are expanded over the running bus as a build expands them,
its effect goes into an FX engine nothing else on the desk inserts, exactly
the addresses that change are written (the bus's own and that engine's), what
the old preset set and the new one does not reads as initialized, and Undo
restores every address. Refused only for what cannot be: a preset the library
does not have, or an effect no free engine can hold.

The library is the frozen one under `tests/fixtures/channel_presets`: "Mix
Bus" (processing only), "Vox Verb" (a V-REV on the pre-insert, saved from
FX5) and "Snare Verb" (a GATED, saved from FX8). The Drums bus is bus 5 and
carries "Mix Bus".
"""

from __future__ import annotations

import copy

import pytest

from atoo import amend, cli, initialize, patch
from atoo.amend import ChangeKind
from atoo.console import OscReply
from atoo.presets import PresetLibrary
from test_amend import occupancy
from test_patch_exactness import ModelDesk, _seed_free
from test_patch import _bundle, _patch, _reply
from test_patch_preset_values import LIBRARY, _change_set, _channel, _modify, preset_plan
from atoo.ai_provider import FakeProvider

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _switch(plan: dict, preset, model: str = "wing-compact", bus: str = "Drums"):
    change_set = _change_set(_modify(bus, {"preset": preset}, "bus"))
    amendment, merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                        presets=PresetLibrary(LIBRARY))
    return amendment, merge, amend.amendment_targets(amendment)


@pytest.mark.parametrize("model", MODELS)
def test_a_bus_preset_switch_writes_its_values_and_loads_its_effect(model):
    plan = preset_plan()
    old = plan["busses"]["Drums"]["preset_values"]["leaves"]
    amendment, merge, targets = _switch(plan, "Vox Verb", model)
    assert not amendment.blocked and not merge.refused
    assert not [c for c in amendment.changes if c.kind in (ChangeKind.MODIFIED,
                                                           ChangeKind.REFUSED)]
    drums = merge.plan["busses"]["Drums"]
    assert drums["preset"] == "Vox Verb"
    values = drums["preset_values"]
    assert values["preset"] == "Vox Verb"
    [insert] = values["inserts"]
    assert (insert["point"], insert["model"], insert["engine"]) == ("preins", "V-REV", 5)
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    # Every bus leaf the new preset sets that differs from the old is written ...
    for leaf, value in values["leaves"].items():
        if old.get(leaf) != value:
            assert writes.get(f"/bus/5/{leaf}") == value, leaf
    # ... one the old set and the new does not reads as initialized ...
    for leaf in [lf for lf in old if lf not in values["leaves"]]:
        initial = {x.address: x.value for x in initialize.freed_leaves(model, f"/bus/5/{leaf}")}
        if f"/bus/5/{leaf}" in initial:
            assert writes[f"/bus/5/{leaf}"] == initial[f"/bus/5/{leaf}"]
    # ... the effect is loaded into FX5 and inserted, switched on ...
    assert writes["/fx/5/mdl"] == "V-REV"
    assert writes["/bus/5/preins/ins"] == "FX5" and writes["/bus/5/preins/on"] == 1
    # ... and nothing but the bus and its engine is touched.
    assert all(a.startswith(("/bus/5/", "/fx/5/")) for a in writes), sorted(writes)


def test_the_preview_says_which_leaves_move_and_where_the_effect_goes():
    _a, merge, _t = _switch(preset_plan(), "Vox Verb")
    [said] = [i for i in merge.infos if "replaces the old one's" in i]
    assert said.startswith("bus 'Drums': the bus preset 'Vox Verb' (FX Vox Verb.bus) replaces "
                           "the old one's processing values and effects; its V-REV goes into "
                           "FX5;")
    assert "; the leaves that move: " in said and "dyn/thr" in said
    assert any("FX5 -- the engine the preset was saved from" in i for i in merge.infos)
    assert "bus 'Drums': FX5 was judged free from the plan on the desk alone -- the occupancy " \
        "read covers strips, not FX engines" in merge.infos


def test_the_same_bus_preset_changes_nothing():
    _a, _m, targets = _switch(preset_plan(), "Mix Bus")
    assert not targets.to_write


def test_a_bus_preset_the_library_does_not_have_is_refused_with_the_reason():
    _a, merge, targets = _switch(preset_plan(), "No Such Verb")
    [refused] = merge.refused
    assert "has no bus preset of that name" in refused.reason
    assert not targets.to_write


def test_an_effect_no_free_engine_can_hold_is_refused_naming_the_engines():
    """Every engine (FX1-8) is inserted by another strip already: the GATED
    has nowhere to go, which is a physical limit."""
    plan = preset_plan()
    others = [n for n in plan["busses"] if n != "Drums"][:8]
    for engine, name in enumerate(others, start=1):
        plan["busses"][name]["inserts"] = [{"point": "postins", "model": "ST-DL",
                                            "engine": engine, "parameters": {}}]
    _a, merge, targets = _switch(plan, "Snare Verb")
    [refused] = merge.refused
    assert refused.reason == ("the bus preset 'Snare Verb' inserts GATED on its pre-insert, and "
                              "every FX engine that can hold it (FX1-8) is already in use on "
                              "the desk")
    assert not targets.to_write
    assert merge.plan["busses"]["Drums"]["preset"] == "Mix Bus"


def test_an_engine_another_bus_inserts_is_left_to_it():
    """The preset was saved from FX5, which another bus holds: it goes into
    the next free engine instead, and FX5 is not touched."""
    plan = preset_plan()
    plan["busses"]["VOX Reverb"]["inserts"] = [{"point": "preins", "model": "HALL",
                                                "engine": 5, "parameters": {}}]
    _a, merge, targets = _switch(plan, "Vox Verb")
    assert not merge.refused
    [insert] = merge.plan["busses"]["Drums"]["preset_values"]["inserts"]
    assert insert["engine"] not in (5, None)
    writes = {t.address for t in targets.to_write}
    assert not [a for a in writes if a.startswith("/fx/5/")]
    assert f"/fx/{insert['engine']}/mdl" in writes


def test_taking_the_bus_preset_off_resets_what_it_set():
    _a, merge, targets = _switch(preset_plan(), None)
    assert not merge.refused
    assert "preset_values" not in merge.plan["busses"]["Drums"]
    assert targets.to_write and all(t.address.startswith("/bus/5/") for t in targets.to_write)


def test_a_channel_with_no_preset_takes_one():
    """A running channel the build gave no preset is given one: its values are
    expanded and written, as a switch's are."""
    plan = preset_plan()
    assert "preset_values" not in _channel(plan, "HH")["processing"]
    change_set = _change_set(_modify("HH", {"processing.preset": "HiHat"}))
    amendment, merge = patch.plan_patch(plan, change_set, occupancy(), console_model="wing-full",
                                        presets=PresetLibrary(LIBRARY))
    assert not merge.refused
    values = _channel(merge.plan, "HH")["processing"]["preset_values"]
    assert values["preset"] == "HiHat" and values["leaves"]
    slot = _channel(merge.plan, "HH")["channel"]
    writes = {t.address for t in amend.amendment_targets(amendment).to_write}
    assert writes and all(a.startswith(f"/ch/{slot}/") for a in writes)


# -- Apply, then Undo, on a fake desk: every address back --------------------------------

#: What each FX model holds of its own on the fake desk: switching the engine's
#: model drops the old model's parameters and shows the new one's at defaults.
_FX_ONLY = {"ST-DL": {"time": (350.0, "f"), "fb": (30.0, "f")},
            "V-REV": {"fxmix": (100.0, "f"), "pdel": (10, "i"), "dcy": (2.0, "f"),
                      "lmult": (1.0, "f"), "hmult": (1.0, "f"), "mod": (50, "i"),
                      "lc": (100.0, "f"), "hc": (10000.0, "f"), "out": ("FRONT", "s"),
                      "trans": (0, "i")}}


class FxDesk(ModelDesk):
    """`ModelDesk`, whose FX engines also drop a model's own parameters when
    the model changes, as the real desk does."""

    def _fx_gone(self, address: str) -> bool:
        parts = address.split("/")
        if len(parts) != 4 or parts[1] != "fx":
            return False
        model = self.state.get(f"/fx/{parts[2]}/mdl", ("NONE",))[0]
        others = {leaf for m, leaves in _FX_ONLY.items() if m != model for leaf in leaves}
        return parts[3] in others and parts[3] not in _FX_ONLY.get(model, {})

    def _reply_to(self, address):
        if self._fx_gone(address):
            return OscReply(address=address, typetag="s", args=["NODE NOT FOUND"])
        return super()._reply_to(address)

    def _fx_switch(self, address, before, after):
        parts = address.split("/")
        if before == after or len(parts) != 4 or parts[1] != "fx" or parts[3] != "mdl":
            return
        for model, leaves in _FX_ONLY.items():
            if model != after:
                for leaf in leaves:
                    self.state.pop(f"/fx/{parts[2]}/{leaf}", None)
        for leaf, value in _FX_ONLY.get(after, {}).items():
            self.state.setdefault(f"/fx/{parts[2]}/{leaf}", value)

    def set_param(self, address, value, value_type="f"):
        before = self.state.get(address, (None, None))[0]
        super().set_param(address, value, value_type)
        self._fx_switch(address, before, value)

    def set_node(self, address, command):
        key, _, text = command.partition("=")
        before = self.state.get(f"{address}/{key}", (None, None))[0]
        reply = super().set_node(address, command)
        self._fx_switch(f"{address}/{key}", before, text)
        return reply


@pytest.mark.parametrize("model", MODELS)
def test_apply_then_undo_puts_every_address_back(model, tmp_path, monkeypatch, capsys):
    plan = preset_plan()
    plan["meta"]["console_model"] = model
    state = _seed_free(plan)
    # FX5 holds a delay nobody's plan inserts, with its own time and feedback.
    state["/fx/5/mdl"] = ("ST-DL", "s")
    state["/fx/5/time"] = (420.0, "f")
    state["/fx/5/fb"] = (25.0, "f")
    state["/bus/5/preins/ins"] = ("NONE", "s")
    state["/bus/5/preins/on"] = (0, "i")
    console = FxDesk(state)
    console.close = lambda: None
    change_set = patch.empty_change_set("Vox Verb on Drums")
    change_set["modify"] = [{"object": "bus", "name": "Drums", "change": "Vox Verb preset",
                             "fields": {"preset": "Vox Verb"}}]
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(patch.validate_change_set(change_set))))
    show = _bundle(tmp_path, plan=plan)
    before = copy.deepcopy(console.state)
    assert _patch(show, text="Put the Vox Verb preset on the Drums bus.", confirm=True) == 0, \
        capsys.readouterr()
    applied = capsys.readouterr()
    console.patch_output = applied.out + applied.err
    assert console.state["/fx/5/mdl"] == ("V-REV", "s")
    assert console.state["/bus/5/preins/ins"][0] == "FX5"
    assert "/fx/5/time" not in console.state
    code = cli.main(["undo", "--show", str(show), "--console", "198.51.100.9", "--confirm"])
    out = capsys.readouterr()
    assert code == 0, out
    differing = {a: (before.get(a), console.state.get(a))
                 for a in set(before) | set(console.state) if console.state.get(a) != before.get(a)}
    assert differing == {}, differing


def test_an_effect_moved_to_another_engine_leaves_the_old_one_as_the_desk_has_it():
    """Vox Verb (V-REV in FX5) to Snare Verb (GATED, saved from FX8): FX8 is
    loaded and inserted, and FX5 is left holding the reverb, inserted nowhere --
    nothing is written to it."""
    _a, first, _t = _switch(preset_plan(), "Vox Verb")
    amendment, merge, targets = _switch(first.plan, "Snare Verb")
    assert not merge.refused
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/fx/8/mdl"] == "GATED" and writes["/bus/5/preins/ins"] == "FX8"
    assert not [a for a in writes if a.startswith("/fx/5/")]
    assert ("bus 'Drums': FX5 is no longer inserted on it; it keeps the old preset's effect "
            "and its values, inserted nowhere, as the desk has it") in amendment.infos


def test_the_worked_example_in_the_patch_guide_runs(tmp_path, capsys):
    """`docs/user/patch.md`'s "A bus preset on a running bus": the Demo's Vox
    Verb bus switched to Snare Verb, offline, from a copy of the Demo show."""
    import shutil
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    show = tmp_path / "demo-show"
    shutil.copytree(root / "starter" / "demo-show", show)
    code = cli.main(["patch", "--show", str(show), "--change-set",
                     str(root / "docs/user/demo/demo-show/snare-verb.change-set.json"),
                     "--state", str(root / "atoo/web/demo_states/before.json")])
    out = capsys.readouterr()
    assert code == 0, out
    text = out.out + out.err
    assert "/fx/8/mdl: bus 7 (Vox Verb): FX8 effect GATED" in text
    assert "/bus/7/preins/ins: bus 7 (Vox Verb): pre-insert -> FX8 (GATED)" in text
    assert "FX5 is no longer inserted on it" in text
