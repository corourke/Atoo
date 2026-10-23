"""An edit that would also move other objects' addresses is refused, and the
refusal is the question (decided).

*"When an explicit edit would also move or re-address other objects the user
did not name, Atoo must refuse and ask first; it never writes with a
WARNING."* The refusal names the other objects and addresses and says how to
go ahead; a change that names those objects too is carried out, as any
explicit instruction is.

No edit the frozen show can be given reaches this arm by a bus field alone (a
bus's own addresses are all under `/bus/n/`), so the first tests simulate the
consequence the way `test_patch_edit.py` does; the real case, a strip repatched
onto a socket a running strip uses, is in `test_patch_edit.py`.
"""

from __future__ import annotations

import pytest

from atoo import amend, patch
from atoo.amend import ChangeKind
from test_amend import applied_plan, occupancy

MODELS = ["wing-compact", "wing-full", "wing-rack"]


@pytest.fixture
def spill(monkeypatch):
    """Setting the Kick's high-pass to 90 also moves the Snare's filter."""
    real = amend._target_map

    def spilled(plan):
        out = real(plan)
        kick = next(c for c in plan["channels"] if c["name"] == "Kick")
        if kick["processing"]["hpf_hz"] == 90:
            old = out["/ch/2/flt/lcf"]
            out["/ch/2/flt/lcf"] = amend.apply_module.WriteTarget(
                old.address, old.value_type, old.description,
                amend.apply_module._const(222.0), old.stage)
        return out

    monkeypatch.setattr(amend, "_target_map", spilled)


def _review(model: str, *modifies: dict):
    change_set = patch.empty_change_set("hpf")
    change_set["modify"] = list(modifies)
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    return patch.plan_patch(plan, patch.validate_change_set(change_set), occupancy(),
                            console_model=model, text="HPF 90 on the kick")


KICK = {"object": "channel", "name": "Kick", "change": "HPF 90",
        "fields": {"processing.hpf_hz": 90}}
SNARE = {"object": "channel", "name": "Snare", "change": "snare blue",
         "fields": {"color": "Blue"}}


@pytest.mark.parametrize("model", MODELS)
def test_an_edit_that_would_move_an_object_the_change_does_not_name_is_refused_and_asks(
        model, spill):
    amendment, merge = _review(model, KICK)
    [refused] = [c for c in amendment.changes if c.kind is ChangeKind.REFUSED]
    assert "/ch/2/flt/lcf" in refused.reason
    assert "channel 'Snare' (ch:2)" in refused.reason          # the other object, in words
    assert "name channel 'Snare' (ch:2) in the change as well" in refused.reason
    assert "needs a rebuild" not in refused.reason
    assert amendment.blocked
    assert not [w for w in amendment.warnings if "also rewrites" in w]   # no WARNING-and-write
    assert amend.amendment_targets(amendment).to_write == []


@pytest.mark.parametrize("model", MODELS)
def test_a_change_that_names_the_other_object_too_is_carried_out(model, spill):
    amendment, merge = _review(model, KICK, SNARE)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    written = {t.address for t in amend.amendment_targets(amendment).to_write}
    assert "/ch/2/flt/lcf" in written and "/ch/1/flt/lcf" in written
