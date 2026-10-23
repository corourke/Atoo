"""Switching a running channel's preset.

"Use the Snare preset on the Kick" is an instruction. The new preset's values
are expanded over the running channel as a build expands them, exactly the
addresses that change are written, what the old preset set and the new one
does not goes back to what an initialized strip reads, and Undo restores them.
The library is the frozen one under `tests/fixtures/channel_presets`.
"""

from __future__ import annotations

import pytest

from atoo import amend, initialize, patch
from atoo.amend import ChangeKind
from atoo.presets import PresetLibrary
from test_amend import occupancy
from test_patch_preset_values import LIBRARY, _change_set, _channel, _modify, preset_plan

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _switch(plan: dict, name: str, preset, model: str = "wing-compact"):
    change_set = _change_set(_modify(name, {"processing.preset": preset}))
    amendment, merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                        presets=PresetLibrary(LIBRARY))
    return amendment, merge, amend.amendment_targets(amendment)


@pytest.mark.parametrize("model", MODELS)
def test_switching_a_running_preset_writes_the_new_values_and_resets_the_old_ones(model):
    plan = preset_plan()
    kick = _channel(plan, "Kick")
    old = kick["processing"]["preset_values"]["leaves"]
    amendment, merge, targets = _switch(plan, "Kick", "Snare", model)
    assert not amendment.blocked and not merge.refused
    assert not [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    new_kick = _channel(merge.plan, "Kick")
    assert new_kick["processing"]["preset"] == "Snare"
    new = new_kick["processing"]["preset_values"]
    assert new["preset"] == "Snare" and new["leaves"]
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    # every leaf the new preset sets that differs from the old is written ...
    for leaf, value in new["leaves"].items():
        address = f"/ch/1/{leaf}"
        if old.get(leaf) != value:
            assert writes.get(address) == value, address
    # ... a leaf the old one set and the new one does not reads as initialized
    gone = [leaf for leaf in old if leaf not in new["leaves"]]
    for leaf in gone:
        initial = {x.address: x.value for x in initialize.freed_leaves(model, f"/ch/1/{leaf}")}
        if f"/ch/1/{leaf}" in initial:
            assert writes[f"/ch/1/{leaf}"] == initial[f"/ch/1/{leaf}"]
    # nothing but Kick's own strip is touched
    assert all(a.startswith("/ch/1/") for a in writes), [a for a in writes if not a.startswith("/ch/1/")]
    assert any("replaces the old one's" in i for i in merge.infos)


def test_the_same_preset_changes_nothing():
    plan = preset_plan()
    amendment, merge, targets = _switch(plan, "Kick", "Kick In")
    assert not targets.to_write


def test_a_preset_the_library_does_not_have_is_refused_with_the_reason():
    amendment, merge, _t = _switch(preset_plan(), "Kick", "No Such Preset")
    [refused] = merge.refused
    assert "has no preset of that name" in refused.reason


def test_taking_the_preset_off_resets_what_it_set():
    plan = preset_plan()
    amendment, merge, targets = _switch(plan, "Kick", None)
    assert not amendment.blocked
    assert "preset_values" not in _channel(merge.plan, "Kick")["processing"]
    assert targets.to_write


@pytest.mark.parametrize("model", MODELS)
def test_a_leaf_the_old_preset_set_and_the_new_one_does_not_reads_as_initialized(
        model, monkeypatch):
    """Same gate model, but the new preset sets no `eq/4q`: the old preset's value
    for it goes back to what an initialized strip reads."""
    from atoo import preset_expand
    real = preset_expand.expand_channel

    def without_eq4q(channel, library):
        findings = real(channel, library)
        values = preset_expand.preset_values(channel)
        if values is not None:
            values["leaves"].pop("eq/4q", None)
        return findings

    plan = preset_plan()                      # built with the real expansion
    assert "eq/4q" in _channel(plan, "Kick")["processing"]["preset_values"]["leaves"]
    monkeypatch.setattr(preset_expand, "expand_channel", without_eq4q)
    amendment, merge, targets = _switch(plan, "Kick", "Snare", model)
    new = _channel(merge.plan, "Kick")["processing"]["preset_values"]["leaves"]
    assert "eq/4q" not in new
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    initial = {x.address: x.value for x in initialize.freed_leaves(model, "/ch/1/eq/4q")}
    assert initial and writes["/ch/1/eq/4q"] == initial["/ch/1/eq/4q"]


@pytest.mark.parametrize("model", MODELS)
def test_a_leaf_only_the_old_gate_model_has_is_not_written_but_left_to_undo(model):
    """GATE -> PSE: the desk drops the GATE model's own leaves (acc, att, ...)
    when the model changes, so nothing is written to them; the run journals their
    values (apply) and Undo restores them (`test_patch_exactness.py`)."""
    amendment, merge, targets = _switch(preset_plan(), "Kick", "Vocal", model)
    writes = {t.address for t in targets.to_write}
    assert "/ch/1/gate/mdl" in writes
    assert not writes & {f"/ch/1/gate/{leaf}" for leaf in
                         ("acc", "att", "hld", "range", "ratio", "rel")}
