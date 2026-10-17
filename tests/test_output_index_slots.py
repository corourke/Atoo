"""An output's stated `index` is a slot the desk has taken.

Before this, allocation read an explicit Main/Matrix slot from the output's
NAME only ("Main 2"). An output stating `index: 2` under any other name was
invisible to it, so an unnumbered sibling could be handed the same slot:
two Mains at index 2, Main 1 patched to nothing, and verify passing it.

Every plan here is built in the test (never from a bundle on disk).
"""

from __future__ import annotations

import copy

import pytest

from atoo.allocate import allocate_console_indices
from atoo.verify_plan import Severity, verify_plan


KICK = {"channel": 1, "bank": "ch", "name": "Kick",
        "source": {"input": "Kick", "type": "Mic", "model": "", "stereo": False,
                   "phantom": False},
        "patch": {"group": "A", "sockets": [1], "stated": True},
        "dca": [], "mute_group": [], "bus_sends": [], "main_routes": []}


def _outputs_plan(outputs: dict, busses: dict | None = None) -> dict:
    return {"channels": [copy.deepcopy(KICK)], "dcas": {}, "mute_groups": {},
            "busses": copy.deepcopy(busses or {}),
            "outputs": copy.deepcopy(outputs),
            "meta": {"console_model": "wing-compact"}}


# --------------------------------------------------------------------------
# Allocation sees a stated index
# --------------------------------------------------------------------------

def test_an_unnumbered_main_never_takes_a_siblings_stated_index():
    plan = _outputs_plan({
        "FOH": {"kind": "main", "index": 2,
                "patch": {"group": "LCL", "sockets": [1, 2]}},
        "Broadcast": {"kind": "main",
                      "patch": {"group": "LCL", "sockets": [3, 4]}},
    })
    allocate_console_indices(plan, console_model="wing-compact")
    assert plan["outputs"]["FOH"]["index"] == 2
    assert plan["outputs"]["Broadcast"]["index"] == 1
    basis = plan["outputs"]["Broadcast"]["inferred"][0]["basis"]
    assert "first free" in basis


def test_an_unnumbered_matrix_never_takes_a_siblings_stated_index():
    plan = _outputs_plan({
        "Fill": {"kind": "matrix", "index": 2},
        "Delay": {"kind": "matrix"},
        "Lobby": {"kind": "matrix", "index": 1},
        "Stream": {"kind": "matrix"},
    })
    allocate_console_indices(plan, console_model="wing-compact")
    got = [plan["outputs"][n]["index"] for n in ("Fill", "Delay", "Lobby", "Stream")]
    assert got == [2, 3, 1, 4]


def test_a_stated_index_wins_over_a_slot_in_the_name():
    """"Main 2" under `index: 3`: the field is what apply writes, so it is
    the slot taken; an unnumbered sibling gets Main 1, not 3."""
    plan = _outputs_plan({"Main 2": {"kind": "main", "index": 3},
                          "Stream": {"kind": "main"}})
    allocate_console_indices(plan, console_model="wing-compact")
    assert plan["outputs"]["Main 2"]["index"] == 3
    assert plan["outputs"]["Stream"]["index"] == 1


def test_a_bus_routed_to_main_goes_to_a_main_the_plan_carries():
    """The default Main sees the stated indices too: with Mains at 2
    and 3 a plain "routes to main" is Main 2, not a Main 1 nothing feeds."""
    plan = _outputs_plan(
        {"FOH": {"kind": "main", "index": 2}, "Stream": {"kind": "main", "index": 3}},
        busses={"FX": {"destination": {"type": "main"},
                       "destinations": [{"type": "main"}]}})
    allocate_console_indices(plan, console_model="wing-compact")
    assert plan["busses"]["FX"]["destination"]["index"] == 2
    assert plan["busses"]["FX"]["destinations"][0]["index"] == 2
# --------------------------------------------------------------------------
# Verify refuses two outputs of one kind on one index
# --------------------------------------------------------------------------

def _codes(plan: dict) -> set[str]:
    return {f.code for f in verify_plan(plan).findings}


def _two_mains_on_one_index() -> dict:
    return _outputs_plan({
        "FOH": {"kind": "main", "index": 2,
                "patch": {"group": "LCL", "sockets": [1, 2]}},
        "Broadcast": {"kind": "main", "index": 2,
                      "patch": {"group": "LCL", "sockets": [3, 4]}},
    })


def test_verify_refuses_two_mains_sharing_an_index():
    result = verify_plan(_two_mains_on_one_index())
    dup = [f for f in result.findings if f.code == "output.index-duplicated"]
    assert len(dup) == 1
    assert dup[0].severity == Severity.ERROR
    assert "FOH" in dup[0].message and "Broadcast" in dup[0].message
    assert not result.ok


def test_verify_allows_a_main_and_a_matrix_on_the_same_number():
    plan = _outputs_plan({
        "FOH": {"kind": "main", "index": 1,
                "patch": {"group": "LCL", "sockets": [1, 2]}},
        "Fill": {"kind": "matrix", "index": 1, "fed_by": {"type": "main", "index": 1},
                 "patch": {"group": "LCL", "sockets": [3, 4]}},
    })
    assert "output.index-duplicated" not in _codes(plan)


# --------------------------------------------------------------------------
# verify_plan never raises on a malformed `outputs` shape
# --------------------------------------------------------------------------

@pytest.mark.parametrize("patch", [
    [{"group": "LCL", "sockets": [1]}],
    "LCL 1",
    7,
])
def test_verify_reports_rather_than_raises_on_a_malformed_output_patch(patch):
    plan = _outputs_plan({"FOH": {"kind": "main", "index": 1, "patch": patch}})
    result = verify_plan(plan)  # must not raise
    assert result.findings, "a malformed patch is reported, not passed"


@pytest.mark.parametrize("outputs", [
    {"FOH": None},
    {"FOH": ["main"]},
    {"FOH": {"kind": "main", "index": 1, "patches": ["LCL 1", None]}},
])
def test_verify_never_raises_on_a_malformed_output_entry(outputs):
    verify_plan(_outputs_plan(outputs))
