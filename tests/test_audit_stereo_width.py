"""R011 (a stereo bus, Main or Matrix heard on one side) and CV020 (a bus's
width against the plan).

Each bus, Main and Matrix owns two output slots, `2N-1` for its left side and
`2N` for its right. A stereo object puts a different signal on each, so when
every output it is patched to uses the same slot, whatever is panned to the
other side goes nowhere. The plan decides every bus's width and `apply` writes
it to `/bus/{n}/busmono`, and nothing read it back.

The desks and plans are built here; the capture tests use frozen captures,
never a show bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.audit import (
    DEFAULT_RULES, WITHHELD_PLAN_STATES, ConsoleState, Severity, apply_plan_scope,
    bus_width_findings, bus_width_rule, console_read_plan, diff_against_plan,
    read_console_state, run_audit, socket_groups_to_read, unanswerable_rule_ids,
    with_plan_rules,
)
from atoo.watch import watch
from tests.snap_desk import SnapDesk, snap_values

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURES = sorted(FIXTURES.rglob("*.snap"))


def _r011(state):
    return next(r for r in DEFAULT_RULES if r.id == "R011").check(state)


def _desk(**changes) -> ConsoleState:
    """A stereo bus 3 named Wedge that a strip sends to, patched on its left
    slot (`2*3-1 = 5`) to LCL 3 -- a stage wedge on a stereo bus."""
    v: dict[str, object] = {
        "/bus/3/name": "Wedge", "/bus/3/mute": 0, "/bus/3/fdr": 0.0, "/bus/3/busmono": 0,
        "/ch/1/name": "Kick", "/ch/1/send/3/on": 1, "/ch/1/send/3/lvl": 0.0,
        "/io/out/LCL/3/grp": "BUS", "/io/out/LCL/3/in": 5,
        "/io/out/LCL/4/grp": "OFF", "/io/out/LCL/4/in": 0,
    }
    v.update(changes)
    return ConsoleState(v, console_model="wing-compact")


# --------------------------------------------------------------------------
# R011: firing
# --------------------------------------------------------------------------


def test_a_stereo_bus_patched_on_its_left_slot_only_is_a_warning_naming_the_bus_and_socket():
    [finding] = _r011(_desk())
    assert (finding.rule_id, finding.severity) == ("R011", Severity.WARNING)
    assert finding.message.startswith(
        'BUS 3 "Wedge" is stereo but is patched on its left side only (LCL 3), among the output '
        "sockets read (LCL 1-4)")
    assert "anything panned right is not heard" in finding.message
    assert "If a mono feed is meant, set it mono and this goes away" in finding.message
    assert "patch its right side as well" in finding.message
    assert finding.addresses == ("/io/out/LCL/3/grp", "/io/out/LCL/3/in")


def test_the_right_slot_alone_is_the_right_side():
    state = _desk(**{"/io/out/LCL/3/in": 6})
    [finding] = _r011(state)
    assert "patched on its right side only (LCL 3)" in finding.message
    assert "anything panned left is not heard" in finding.message


def test_the_same_side_on_two_sockets_is_still_one_side():
    state = _desk(**{"/io/out/LCL/4/grp": "BUS", "/io/out/LCL/4/in": 5})
    [finding] = _r011(state)
    assert "(LCL 3, LCL 4)" in finding.message
    assert finding.addresses == ("/io/out/LCL/3/grp", "/io/out/LCL/3/in",
                                 "/io/out/LCL/4/grp", "/io/out/LCL/4/in")


def test_a_stereo_main_in_use_patched_left_only_fires():
    state = _desk(**{"/main/1/busmono": 0, "/ch/1/main/1/on": 1,
                     "/io/out/LCL/4/grp": "MAIN", "/io/out/LCL/4/in": 1})
    [finding] = [f for f in _r011(state) if f.message.startswith("MAIN 1")]
    assert "MAIN 1 is stereo but is patched on its left side only (LCL 4)" in finding.message


def test_a_stereo_matrix_that_is_fed_and_patched_right_only_fires():
    state = _desk(**{"/mtx/2/busmono": 0, "/ch/1/send/MX2/on": 1,
                     "/io/out/LCL/4/grp": "MTX", "/io/out/LCL/4/in": 4})
    [finding] = [f for f in _r011(state) if f.message.startswith("MTX 2")]
    assert "MTX 2 is stereo but is patched on its right side only (LCL 4)" in finding.message


def test_findings_come_in_the_order_bus_main_matrix():
    state = _desk(**{"/main/1/busmono": 0, "/ch/1/main/1/on": 1,
                     "/mtx/2/busmono": 0, "/ch/1/send/MX2/on": 1,
                     "/io/out/LCL/5/grp": "MTX", "/io/out/LCL/5/in": 3,
                     "/io/out/LCL/4/grp": "MAIN", "/io/out/LCL/4/in": 1})
    assert [f.message.split()[0] for f in _r011(state)] == ["BUS", "MAIN", "MTX"]


# --------------------------------------------------------------------------
# R011: silent
# --------------------------------------------------------------------------


def test_silent_for_a_stereo_pair_patched_on_both_sides():
    state = _desk(**{"/io/out/LCL/4/grp": "BUS", "/io/out/LCL/4/in": 6})
    assert _r011(state) == []


def test_silent_for_a_side_on_each_of_two_sockets_that_are_not_adjacent():
    state = _desk(**{"/io/out/LCL/4/grp": "BUS", "/io/out/LCL/4/in": 6,
                     "/io/out/LCL/3/grp": "BUS", "/io/out/LCL/3/in": 5})
    assert _r011(state) == []


def test_silent_for_a_mono_bus():
    assert _r011(_desk(**{"/bus/3/busmono": 1})) == []


def test_silent_when_the_width_was_not_read():
    values = dict(_desk().values)
    del values["/bus/3/busmono"]
    assert _r011(ConsoleState(values)) == []


def test_silent_for_a_bus_nothing_uses():
    """A factory desk patches local outs 1-6 from the left slot of busses
    1-6, every one of them stereo and none of them in use."""
    values = dict(_desk().values)
    values.update({"/bus/3/name": "", "/ch/1/send/3/on": 0})
    assert _r011(ConsoleState(values)) == []


def test_silent_for_a_main_or_matrix_nothing_feeds():
    state = _desk(**{"/main/1/busmono": 0, "/mtx/2/busmono": 0,
                     "/io/out/LCL/4/grp": "MAIN", "/io/out/LCL/4/in": 1,
                     "/io/out/LCL/5/grp": "MTX", "/io/out/LCL/5/in": 3})
    assert [f for f in _r011(state) if not f.message.startswith("BUS")] == []


def test_silent_for_an_object_patched_nowhere():
    """That is R002's, R005's and R006's to say."""
    assert _r011(_desk(**{"/io/out/LCL/3/grp": "OFF", "/io/out/LCL/3/in": 0})) == []


def test_silent_on_a_reading_with_no_output_patch():
    values = {a: v for a, v in _desk().values.items() if not a.startswith("/io/out/")}
    assert _r011(ConsoleState(values)) == []
    assert "R011" in unanswerable_rule_ids(ConsoleState(values))


def test_silent_when_an_aes50_port_in_use_was_not_read():
    """The other side may be patched on a stage box nobody looked at."""
    state = _desk(**{"/$stat/A/stat": "OK"})
    assert _r011(state) == []


# --------------------------------------------------------------------------
# R011: the plan stands it down for an output it declares
# --------------------------------------------------------------------------

PLAN = {
    "channels": [],
    "busses": {
        "Wedge": {"index": 3, "mono": False,
                  "destination": {"type": "dedicated_output",
                                  "patches": [{"group": "LCL", "sockets": [3]}]}},
    },
    "outputs": {}, "dcas": {}, "mute_groups": {},
}


def test_a_plan_that_declares_the_socket_asked_for_it():
    state = _desk()
    scoped = apply_plan_scope(state, run_audit(state), PLAN, DEFAULT_RULES)
    assert [f.rule_id for f in scoped.findings if f.rule_id == "R011"] == []
    assert [(w.finding.rule_id, w.reason) for w in scoped.withheld
            if w.finding.rule_id == "R011"] == [("R011", WITHHELD_PLAN_STATES)]


def test_a_plan_that_declares_another_socket_leaves_it_standing():
    plan = json.loads(json.dumps(PLAN))
    plan["busses"]["Wedge"]["destination"]["patches"][0]["sockets"] = [7]
    state = _desk()
    scoped = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    assert [f.rule_id for f in scoped.findings if f.rule_id == "R011"] == ["R011"]


def test_a_bus_the_plan_never_mentions_is_still_judged():
    """The rule is a hazard: a desk the plan only partly describes."""
    plan = {"channels": [], "busses": {}, "outputs": {}, "dcas": {}, "mute_groups": {}}
    state = _desk()
    scoped = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    assert [f.rule_id for f in scoped.findings if f.rule_id == "R011"] == ["R011"]


def test_watch_binds_r011_to_the_plan_the_way_audit_plan_scopes_it(tmp_path):
    """Watch has no plan scope, so the rule is bound: the declared wedge is
    quiet, and a stereo bus the plan never declared is still a row."""
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    rules = with_plan_rules(DEFAULT_RULES, path)
    assert [f for f in run_audit(_desk(), rules) if f.rule_id == "R011"] == []
    stray = _desk(**{"/bus/5/name": "Fills", "/bus/5/busmono": 0, "/ch/1/send/5/on": 1,
                     "/io/out/LCL/4/grp": "BUS", "/io/out/LCL/4/in": 9})
    [finding] = [f for f in run_audit(stray, rules) if f.rule_id == "R011"]
    assert finding.message.startswith('BUS 5 "Fills" is stereo')


# --------------------------------------------------------------------------
# R011 in Watch: the finding appears and clears
# --------------------------------------------------------------------------


def test_watch_raises_a_bus_losing_its_right_side_and_clears_it():
    pair = {"/io/out/LCL/4/grp": "BUS", "/io/out/LCL/4/in": 6}
    states = iter([_desk(**pair), _desk(), _desk(**pair)])
    events = list(watch(lambda: next(states), rules=DEFAULT_RULES, interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings if f.rule_id == "R011"] == ["R011"]
    assert [f.rule_id for f in events[2].cleared_findings if f.rule_id == "R011"] == ["R011"]


# --------------------------------------------------------------------------
# What it adds to a read
# --------------------------------------------------------------------------


def test_the_read_asks_for_the_width_of_every_bus_main_and_matrix():
    plan = dict(console_read_plan())
    for kind, count in (("bus", 16), ("main", 4), ("mtx", 8)):
        for n in range(1, count + 1):
            assert plan[f"/{kind}/{n}/busmono"] == "i"
    assert sum(1 for a in plan if a.endswith("/busmono")) == 28


def test_a_node_dump_read_gets_the_widths_without_a_request_of_their_own():
    """The widths sit in the object nodes the read already dumps, so the
    default read asks for no more than before."""
    desk = SnapDesk(snap_values(FIXTURES / "console-runs" / "Initialized-Compact.snap"))
    inputs, outputs = socket_groups_to_read("wing-compact")
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    assert state.flag("/bus/1/busmono") is False
    assert state.flag("/main/1/busmono") is False
    assert state.flag("/mtx/1/busmono") is False
    assert not [a for a in desk.gets if a.endswith("/busmono")]


# --------------------------------------------------------------------------
# The frozen captures
# --------------------------------------------------------------------------


@pytest.mark.parametrize("capture", [c for c in CAPTURES if c.name.startswith("Initialized")],
                         ids=lambda p: p.name)
def test_a_factory_desk_has_no_stereo_object_heard_on_one_side(capture):
    """Local outs 1-6 come from the left slot of stereo busses 1-6, and none
    is in use."""
    values = snap_values(capture)
    assert values["/bus/1/busmono"] in (0, False)
    assert _r011(ConsoleState(values)) == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_every_finding_on_a_capture_is_a_stereo_bus_on_one_wedge_and_nothing_else(capture):
    """Counts on the seven captures: 0 on both factory desks, on the church's
    and on the full-size desk, 2 on the board with the podium (busses 5 and 6)
    and 6 on the one with an alternate input (busses 1-6): in each, a
    stereo bus in use on the left slot of one local output."""
    findings = _r011(ConsoleState(snap_values(capture)))
    expected = {"A7-ch1-with-WLIVE-alt.snap": 6, "A13-board-with-podium.snap": 2}.get(capture.name, 0)
    assert len(findings) == expected
    for finding in findings:
        assert finding.severity == Severity.WARNING
        assert finding.message.startswith("BUS ")
        assert "patched on its left side only (LCL " in finding.message


# --------------------------------------------------------------------------
# CV020: a bus's width against the plan
# --------------------------------------------------------------------------

WIDTH_PLAN = {
    "channels": [],
    "busses": {
        "Wedge": {"index": 3, "mono": True},
        "Mix": {"index": 5, "mono": False},
        "Verb": {"index": 6, "mono": None},
    },
}


def _widths(wedge=1, mix=0, **more) -> ConsoleState:
    v = {"/bus/3/busmono": wedge, "/bus/5/busmono": mix, "/bus/6/busmono": 0,
         "/bus/3/name": "Wedge", "/bus/5/name": "Mix"}
    v.update(more)
    return ConsoleState(v)


def test_a_bus_set_up_as_the_plan_says_raises_nothing():
    assert bus_width_findings(_widths(), WIDTH_PLAN) == []
    assert [f for f in diff_against_plan(_widths(), WIDTH_PLAN) if f.rule_id == "CV020"] == []


def test_a_mono_bus_reading_stereo_is_a_warning():
    [finding] = bus_width_findings(_widths(wedge=0), WIDTH_PLAN)
    assert (finding.rule_id, finding.severity) == ("CV020", Severity.WARNING)
    assert finding.message == (
        'BUS 3 "Wedge": the plan has this bus mono; the desk has it stereo, so an output patched '
        "to its left side carries only the left of the mix and anything panned right is lost.")
    assert finding.addresses == ("/bus/3/busmono",)


def test_a_stereo_bus_reading_mono_is_a_warning():
    [finding] = bus_width_findings(_widths(mix=1), WIDTH_PLAN)
    assert finding.message == (
        'BUS 5 "Mix": the plan has this bus stereo; the desk has it mono, so its left and right '
        "outputs carry the same signal and the panning is lost.")


def test_silent_when_the_width_was_not_read():
    values = dict(_widths(wedge=0).values)
    del values["/bus/3/busmono"]
    assert bus_width_findings(ConsoleState(values), WIDTH_PLAN) == []


def test_silent_for_a_bus_the_plan_gives_no_width():
    """Verb states none, and its desk width is whatever it is."""
    assert bus_width_findings(_widths(**{"/bus/6/busmono": 1}), WIDTH_PLAN) == []


def test_the_label_falls_back_to_the_plans_name_for_a_bus_the_desk_leaves_unnamed():
    values = dict(_widths(wedge=0).values)
    values["/bus/3/name"] = ""
    [finding] = bus_width_findings(ConsoleState(values), WIDTH_PLAN)
    assert finding.message.startswith('BUS 3 "Wedge": ')


def test_audit_with_a_plan_reports_cv020_beside_the_other_comparisons():
    findings = diff_against_plan(_widths(wedge=0), WIDTH_PLAN)
    assert [f.rule_id for f in findings if f.rule_id == "CV020"] == ["CV020"]


def test_a_plan_that_states_no_width_binds_no_watch_rule():
    assert bus_width_rule({"busses": {"Verb": {"index": 6, "mono": None}}}) is None
    assert bus_width_rule({"busses": {}}) is None


def test_a_width_the_plan_and_the_desk_disagree_on_is_cv020s_and_r011_stands_down():
    """The plan makes the wedge mono on one socket; the desk has it stereo.
    CV020 says the width, and R011 stays quiet because the plan declares
    the socket."""
    plan = json.loads(json.dumps(PLAN))
    plan["busses"]["Wedge"]["mono"] = True
    state = _desk()
    findings = run_audit(state, plan=plan) + diff_against_plan(state, plan)
    assert [f.rule_id for f in findings if f.rule_id in {"R011", "CV020"}] == ["CV020"]


def test_watch_binds_cv020_and_raises_a_bus_flipped_to_stereo_then_clears_it(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(WIDTH_PLAN), encoding="utf-8")
    rules = with_plan_rules(DEFAULT_RULES, path)
    assert "CV020" in {r.id for r in rules}
    states = iter([_widths(), _widths(wedge=0), _widths()])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings] == ["CV020"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CV020"]
