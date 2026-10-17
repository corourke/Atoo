"""R009 (Feedback Loop) and R010 (Feedback Loop Held Closed): a channel or aux
patched from a bus, Main or Matrix whose signal comes back round to it.

A bus sends only to Mains and Matrices and a Main only to Matrices, so the
console's own routing cannot loop; a strip that takes an internal signal as
its input and sends or routes back to it can. Desks are built in the test;
the live-read test uses a frozen factory capture, never a show bundle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    RuleScope,
    console_read_plan,
    feedback_loops,
    objects_reaching_a_physical_output,
    read_console_state,
    run_audit,
    socket_groups_to_read,
)
from atoo.diagnostics import Severity
from atoo.watch import watch
from tests.snap_desk import SnapDesk, snap_values

INITIALIZED_COMPACT = (Path(__file__).parent / "fixtures" / "console-runs"
                       / "Initialized-Compact.snap")


def _rule(rule_id):
    return next(r for r in DEFAULT_RULES if r.id == rule_id)


def _takes(strip, group, socket, name="", **extra) -> dict[str, object]:
    """`strip` named `name` and patched from an internal `group` socket,
    with every switch it has read off and at the floor (the factory's)."""
    v: dict[str, object] = {
        f"{strip}/name": name, f"{strip}/in/conn/grp": group, f"{strip}/in/conn/in": socket,
        f"{strip}/in/set/altsrc": 0, f"{strip}/in/conn/altgrp": "OFF",
    }
    v.update(extra)
    return v


def _send(strip, bus, *, on=1, lvl=0.0) -> dict[str, object]:
    return {f"{strip}/send/{bus}/on": on, f"{strip}/send/{bus}/lvl": lvl}


def _mtx_send(base, matrix, *, on=1, lvl=0.0) -> dict[str, object]:
    return {f"{base}/send/MX{matrix}/on": on, f"{base}/send/MX{matrix}/lvl": lvl}


def _state(*parts) -> ConsoleState:
    values: dict[str, object] = {}
    for part in parts:
        values.update(part)
    return ConsoleState(values, console_model="wing-compact")


def _loops(state, rule_id=None):
    findings = [f for f in run_audit(state) if f.rule_id in ({rule_id} if rule_id else {"R009", "R010"})]
    return findings


# --------------------------------------------------------------------------
# The rows
# --------------------------------------------------------------------------


def test_an_open_loop_is_an_error_and_a_held_one_a_warning_about_any_strip():
    r009, r010 = _rule("R009"), _rule("R010")
    assert (r009.severity, r010.severity) == (Severity.ERROR, Severity.WARNING)
    assert r009.category == r010.category == "routing"
    assert r009.scope is r010.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# A strip that feeds the object it takes
# --------------------------------------------------------------------------


def test_a_channel_sending_to_the_bus_it_takes_is_an_error_naming_the_loop():
    state = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3),
                   {"/bus/3/name": "Wedge"})
    [f] = _loops(state)
    assert f.rule_id == "R009" and f.severity is Severity.ERROR
    assert f.message.startswith(
        'CH 12 "FX Return" takes BUS 3 "Wedge" (patched from BUS 5, its left side); '
        "CH 12 sends to BUS 3. ")
    assert "patch CH 12 from another source" in f.message
    assert f.addresses == ("/ch/12/in/conn/grp", "/ch/12/in/conn/in",
                           "/ch/12/send/3/on", "/ch/12/send/3/lvl")


@pytest.mark.parametrize("socket,bus,side", [(1, 1, "left"), (2, 1, "right"), (5, 3, "left"),
                                             (6, 3, "right"), (32, 16, "right")])
def test_an_internal_group_has_two_sockets_per_object(socket, bus, side):
    [f] = _loops(_state(_takes("/ch/2", "BUS", socket), _send("/ch/2", bus)))
    assert f"takes BUS {bus}" in f.message and f"BUS {socket}, its {side} side" in f.message


def test_an_aux_routed_to_the_main_it_takes_is_an_error():
    state = _state(_takes("/aux/3", "MAIN", 1, "Return"), {"/aux/3/main/1/on": 1})
    [f] = _loops(state)
    assert f.rule_id == "R009"
    assert f.message.startswith(
        'AUX 3 "Return" takes MAIN 1 (patched from MAIN 1, its left side); AUX 3 routes to MAIN 1. ')


def test_a_strip_sending_to_the_matrix_it_takes_is_an_error():
    state = _state(_takes("/ch/9", "MTX", 3, "Rec"), _mtx_send("/ch/9", 2))
    [f] = _loops(state)
    assert f.message.startswith('CH 9 "Rec" takes MTX 2 (patched from MTX 3, its left side); '
                                "CH 9 sends to MTX 2. ")


def test_a_strip_patched_from_a_physical_socket_is_not_looking_at_an_internal_signal():
    state = _state(_takes("/ch/12", "LCL", 5), _send("/ch/12", 3), {"/ch/12/main/1/on": 1})
    assert _loops(state) == []


# --------------------------------------------------------------------------
# Through other busses, Mains, Matrices and strips
# --------------------------------------------------------------------------


def test_a_loop_through_a_bus_and_a_main_is_named_hop_by_hop():
    state = _state(_takes("/ch/5", "MAIN", 1, "Return"), _send("/ch/5", 5),
                   {"/bus/5/name": "Wedge", "/bus/5/main/1/on": 1})
    [f] = _loops(state)
    assert f.rule_id == "R009"
    assert f.message.startswith(
        'CH 5 "Return" takes MAIN 1 (patched from MAIN 1, its left side); '
        'CH 5 sends to BUS 5 "Wedge"; BUS 5 routes to MAIN 1. ')


def test_a_loop_through_a_bus_a_main_and_a_matrix():
    state = _state(_takes("/ch/5", "MTX", 1, "Rec"), _send("/ch/5", 2),
                   {"/bus/2/main/1/on": 1}, _mtx_send("/main/1", 1))
    [f] = _loops(state)
    assert ("CH 5 sends to BUS 2; BUS 2 routes to MAIN 1; MAIN 1 sends to MTX 1. "
            in f.message)


def test_the_shortest_path_back_is_the_one_named():
    """Bus 2 reaches Matrix 1 directly and through Main 1: the direct hop is
    the loop named."""
    state = _state(_takes("/ch/5", "MTX", 1), _send("/ch/5", 2), _mtx_send("/bus/2", 1),
                   {"/bus/2/main/1/on": 1}, _mtx_send("/main/1", 1))
    [f] = _loops(state)
    assert "CH 5 sends to BUS 2; BUS 2 sends to MTX 1. " in f.message and "MAIN" not in f.message


def test_a_loop_through_two_strips_is_reported_once_naming_both():
    """CH 1 takes BUS 4 and feeds BUS 3; CH 2 takes BUS 3 and feeds BUS 4."""
    state = _state(_takes("/ch/1", "BUS", 7, "A"), _send("/ch/1", 3),
                   _takes("/ch/2", "BUS", 5, "B"), _send("/ch/2", 4))
    [f] = _loops(state)
    assert f.rule_id == "R009"
    assert f.message.count(" takes BUS ") == 2
    assert 'CH 1 "A"' in f.message and 'CH 2 "B"' in f.message
    assert len(feedback_loops(state)) == 1


def test_two_separate_loops_are_two_findings():
    state = _state(_takes("/ch/1", "BUS", 1), _send("/ch/1", 1),
                   _takes("/ch/2", "BUS", 3), _send("/ch/2", 2))
    assert sorted(f.addresses[0] for f in _loops(state)) == ["/ch/1/in/conn/grp", "/ch/2/in/conn/grp"]


def test_a_strip_with_two_legs_back_has_a_finding_for_each():
    state = _state(_takes("/ch/1", "MAIN", 1), {"/ch/1/main/1/on": 1}, _send("/ch/1", 2),
                   {"/bus/2/main/1/on": 1})
    assert len(_loops(state)) == 2


# --------------------------------------------------------------------------
# Not a loop: the patch alone, or a path that does not come back
# --------------------------------------------------------------------------


def test_a_strip_that_takes_a_bus_and_sends_to_other_things_is_not_a_loop():
    """An FX return, the ordinary use: it takes bus 3 and goes to the Main
    and to another bus."""
    state = _state(_takes("/ch/12", "BUS", 5), _send("/ch/12", 4), {"/ch/12/main/1/on": 1},
                   {"/bus/4/main/1/on": 1}, _mtx_send("/main/1", 1))
    assert _loops(state) == []


def test_a_bus_that_cannot_return_to_a_bus_is_no_loop():
    """A strip taking BUS 3 whose signal reaches Main 1 and Matrix 1: the
    console's routing never carries a Main or a Matrix back into a bus."""
    state = _state(_takes("/ch/12", "BUS", 5), {"/ch/12/main/1/on": 1}, _mtx_send("/ch/12", 1))
    assert _loops(state) == []


def test_a_factory_strip_with_its_sends_off_and_at_the_floor_is_not_a_loop():
    """A send is off at the floor from the factory: nobody built it, so it
    is not a leg, and every strip taking an internal signal is not a loop."""
    state = _state(_takes("/ch/12", "BUS", 5), _send("/ch/12", 3, on=0, lvl=-144.0))
    assert _loops(state) == []


def test_a_route_to_a_main_that_is_off_is_not_a_leg():
    """A route's level reads 0 dB whether it is on or off, so an off route
    cannot be told from one never made."""
    state = _state(_takes("/aux/3", "MAIN", 1), {"/aux/3/main/1/on": 0, "/aux/3/main/1/lvl": 0.0})
    assert _loops(state) == []


# --------------------------------------------------------------------------
# One fault, one row: R009 when every leg is open, R010 when one is closed
# --------------------------------------------------------------------------


def test_a_send_at_the_floor_holds_the_loop_closed_and_says_so():
    state = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3, lvl=-144.0))
    [f] = _loops(state)
    assert f.rule_id == "R010" and f.severity is Severity.WARNING
    assert "CH 12 sends to BUS 3 (at the floor)" in f.message
    assert "feeds back the moment it is opened" in f.message


def test_a_switched_off_send_with_a_level_holds_it_closed_and_says_so():
    state = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3, on=0, lvl=-6.0))
    [f] = _loops(state)
    assert f.rule_id == "R010" and "CH 12 sends to BUS 3 (switched off)" in f.message


def test_one_closed_leg_among_open_ones_makes_it_a_warning():
    state = _state(_takes("/ch/5", "MAIN", 1), _send("/ch/5", 5, on=1),
                   {"/bus/5/main/1/on": 1}, _mtx_send("/main/1", 1, lvl=-144.0),
                   _takes("/ch/6", "MTX", 1), _send("/ch/6", 5))
    ids = sorted(f.rule_id for f in _loops(state))
    assert ids == ["R009", "R010"]   # CH 5's loop is open; CH 6's goes through the floored leg
    [held] = _loops(state, "R010")
    assert "MAIN 1 sends to MTX 1 (at the floor)" in held.message


def test_a_loop_is_never_both_an_error_and_a_warning():
    state = _state(_takes("/ch/12", "BUS", 5), _send("/ch/12", 3))
    assert [f.rule_id for f in _loops(state)] == ["R009"]
    state = _state(_takes("/ch/12", "BUS", 5), _send("/ch/12", 3, on=0))
    assert [f.rule_id for f in _loops(state)] == ["R010"]


def test_an_open_path_wins_over_a_closed_one_between_the_same_strip_and_object():
    state = _state(_takes("/ch/12", "BUS", 5), _send("/ch/12", 3),
                   _takes("/ch/13", "BUS", 5), _send("/ch/13", 3, lvl=-144.0))
    assert sorted(f.rule_id for f in _loops(state)) == ["R009", "R010"]


# -- silent when unread ------------------------------------------------------


def test_a_strip_whose_patch_was_never_read_is_silent():
    state = _state(_send("/ch/12", 3))
    assert _loops(state) == []


def test_a_leg_whose_switch_was_never_read_is_silent():
    state = _state(_takes("/ch/12", "BUS", 5), {"/ch/12/send/3/lvl": 0.0})
    assert _loops(state) == []


def test_a_level_that_was_not_read_is_not_counted_as_the_floor():
    state = _state(_takes("/ch/12", "BUS", 5), {"/ch/12/send/3/on": 1})
    assert [f.rule_id for f in _loops(state)] == ["R009"]


# -- what belongs to the alternate input -------------------------------------


def test_a_strip_on_its_alternate_input_is_not_judged():
    state = _state(_takes("/ch/12", "BUS", 5, **{"/ch/12/in/set/altsrc": 1,
                                                  "/ch/12/in/conn/altgrp": "CRD"}),
                   _send("/ch/12", 3))
    assert _loops(state) == []


def test_the_engaged_global_switch_hands_a_strip_with_an_alternate_away():
    v = _takes("/ch/12", "BUS", 5, **{"/ch/12/in/conn/altgrp": "CRD"})
    state = _state(v, _send("/ch/12", 3), {console_facts.GLOBAL_ALT_SWITCH: 1})
    assert _loops(state) == []
    state = _state(v, _send("/ch/12", 3), {console_facts.GLOBAL_ALT_SWITCH: 0})
    assert [f.rule_id for f in _loops(state)] == ["R009"]


# --------------------------------------------------------------------------
# Under a plan, and the read
# --------------------------------------------------------------------------


def test_under_a_plan_the_loop_stands():
    """No plan states a loop, and a plan that asks for one has asked for a
    hazard; the patch it states is CV005's to compare."""
    plan = {"channels": [{"bank": "ch", "channel": 12, "name": "FX Return", "fader": {},
                          "patch": {"group": "BUS", "sockets": [5]}}], "busses": {}}
    state = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3))
    assert [f.rule_id for f in run_audit(state, plan=plan) if f.rule_id in {"R009", "R010"}] == ["R009"]


def test_every_address_a_finding_cites_is_already_in_the_read():
    plan = {address for address, _ in console_read_plan(
        input_sockets={"LCL": 24}, output_sockets={"LCL": 8})}
    state = _state(_takes("/ch/12", "BUS", 5), _send("/ch/12", 3),
                   _takes("/aux/3", "MAIN", 1), {"/aux/3/main/1/on": 1},
                   _takes("/ch/5", "MTX", 1), _send("/ch/5", 2), {"/bus/2/main/1/on": 1},
                   _mtx_send("/main/1", 1, lvl=-144.0))
    findings = _loops(state)
    assert len(findings) == 3
    for finding in findings:
        assert set(finding.addresses) <= plan, set(finding.addresses) - plan


def test_the_routing_graph_the_output_rules_walk_is_unchanged_by_the_legs():
    """R002, R005 and R006 count a send that is on, wherever its level
    sits: a Matrix fed at the floor is still routed to a socket."""
    values = {
        "/bus/1/name": "A", "/bus/1/main/1/on": 0, "/bus/1/send/MX1/on": 1,
        "/bus/1/send/MX1/lvl": -144.0, "/bus/2/name": "B", "/bus/2/send/MX1/on": 0,
        "/bus/2/send/MX1/lvl": -6.0,
        "/io/out/LCL/1/grp": "MTX", "/io/out/LCL/1/in": 1,
    }
    reaching = objects_reaching_a_physical_output(ConsoleState(values))
    assert "bus:1" in reaching and "bus:2" not in reaching


# --------------------------------------------------------------------------
# Watch: a loop opens, and closes
# --------------------------------------------------------------------------


def test_watch_says_a_loop_opened_and_a_loop_closed():
    closed = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3, on=0))
    opened = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3))
    clear = _state(_takes("/ch/12", "BUS", 5, "FX Return"), _send("/ch/12", 3, on=0, lvl=-144.0))
    feed = iter([clear, closed, opened, closed, clear])
    events = list(watch(lambda: next(feed), rules=list(DEFAULT_RULES), interval=0,
                        max_iterations=5, sleep=lambda _s: None))
    ids = lambda findings: sorted(f.rule_id for f in findings if f.rule_id in {"R009", "R010"})  # noqa: E731
    assert ids(events[0].all_findings) == []
    assert ids(events[1].new_findings) == ["R010"]
    assert (ids(events[2].new_findings), ids(events[2].cleared_findings)) == (["R009"], ["R010"])
    assert (ids(events[3].new_findings), ids(events[3].cleared_findings)) == (["R010"], ["R009"])
    assert ids(events[4].cleared_findings) == ["R010"]


# --------------------------------------------------------------------------
# A real read, and the frozen captures
# --------------------------------------------------------------------------


def test_a_live_read_takes_the_patch_and_the_legs_from_the_dumps_and_the_rule_speaks():
    """A factory Compact with channel 3 patched from the left side of bus 3
    and sending to it, read the way Watch reads it: node dumps, with the
    desk reading `in/conn/in` back one low as it does."""
    values = dict(snap_values(INITIALIZED_COMPACT))
    values.update({"/ch/3/name": "FX Return", "/ch/3/in/conn/grp": "BUS", "/ch/3/in/conn/in": 5,
                   "/ch/3/send/3/on": 1, "/ch/3/send/3/lvl": 0.0})
    desk = SnapDesk(values)
    inputs, outputs = socket_groups_to_read("wing-compact")
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    assert state.patch("/ch/3") == ("BUS", 5)
    [f] = [f for f in run_audit(state) if f.rule_id in {"R009", "R010"}]
    assert f.rule_id == "R009" and f.message.startswith('CH 3 "FX Return" takes BUS 3')


CAPTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.snap"))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_no_frozen_capture_has_a_feedback_loop(capture):
    """No desk on file has a strip patched from an internal signal at all
    (their patches are local, AES50, USB, card, module and player sockets),
    so there is no loop and nothing for the rule to get wrong: 0 findings on
    all seven."""
    values = snap_values(capture)
    state = ConsoleState(values)
    assert [f for f in run_audit(state) if f.rule_id in {"R009", "R010"}] == []
    assert not [a for a, v in values.items()
                if a.endswith("/in/conn/grp") and v in {"BUS", "MAIN", "MTX"}]


def test_the_same_capture_with_a_strip_patched_from_its_own_bus_does_report_it():
    """The captures' silence is the rule's reading of them, not the rule's
    blindness: patch a strip of a set-up desk from a bus and send it back."""
    values = dict(snap_values(Path(__file__).parent / "fixtures" / "console-runs" / "Church-Full.snap"))
    values.update({"/ch/1/in/conn/grp": "BUS", "/ch/1/in/conn/in": 1,
                   "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": 0.0})
    findings = [f for f in run_audit(ConsoleState(values)) if f.rule_id in {"R009", "R010"}]
    assert [f.rule_id for f in findings] == ["R009"]
