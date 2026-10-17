"""Which Main a bus is summed into announces itself.

A bus `destination: {"type": "main"}` with no number used to get an index
from allocation silently: no marker, no INFO. Which of up to four Mains a
monitor or FX bus feeds is a choice, and a choice announces itself.
Plans are built in the test.
"""

from __future__ import annotations

import copy

from atoo import inferred
from atoo.allocate import allocate_console_indices

KICK = {"channel": 1, "bank": "ch", "name": "Kick",
        "source": {"input": "Kick", "type": "Mic", "model": "", "stereo": False,
                   "phantom": False},
        "patch": {"group": "A", "sockets": [1], "stated": True},
        "dca": [], "mute_group": [], "bus_sends": [], "main_routes": []}


def _plan(outputs: dict) -> dict:
    return {"channels": [copy.deepcopy(KICK)], "dcas": {}, "mute_groups": {},
            "busses": {"FX": {"destination": {"type": "main"}, "mono": False}},
            "outputs": copy.deepcopy(outputs), "meta": {"console_model": "wing-compact"}}


def _info(plan):
    return [d for d in inferred.inferred_diagnostics(plan) if d.code == "inferred.bus-main-index"]


def test_allocation_marks_the_main_it_chose_and_verify_says_so():
    plan = _plan({"FOH": {"kind": "main", "index": 2}, "Stream": {"kind": "main", "index": 3}})
    allocate_console_indices(plan, console_model="wing-compact")
    bus = plan["busses"]["FX"]
    assert bus["destination"]["index"] == 2
    marker = [m for m in bus["inferred"] if m["field"] == "destination.index"]
    assert marker and marker[0]["by"] == "fallback"
    assert "lowest-numbered, Main 2" in marker[0]["basis"]
    found = _info(plan)
    assert len(found) == 1 and "summed into Main 2" in found[0].message
    assert found[0].where == "busses[FX]"


def test_an_output_named_main_is_preferred_and_named():
    plan = _plan({"Stream": {"kind": "main", "index": 1}, "Main": {"kind": "main", "index": 3}})
    allocate_console_indices(plan, console_model="wing-compact")
    assert plan["busses"]["FX"]["destination"]["index"] == 3
    assert "named 'Main' is Main 3" in _info(plan)[0].message


def test_a_stated_main_number_is_left_alone_and_silent():
    plan = _plan({"FOH": {"kind": "main", "index": 1}})
    plan["busses"]["FX"]["destination"]["index"] = 1
    allocate_console_indices(plan, console_model="wing-compact")
    assert "inferred" not in plan["busses"]["FX"]
    assert _info(plan) == []


def test_a_plan_never_built_is_decided_the_same_way_by_verify():
    """No allocation ran (a hand-written plan): verify still reports the
    Main apply will write, from the same rule, on a copy."""
    plan = _plan({})
    found = _info(plan)
    assert len(found) == 1
    assert "no Main output, so Main 1" in found[0].message
    assert "index" not in plan["busses"]["FX"]["destination"], "the plan itself is not touched"
