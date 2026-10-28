"""A plan's sends on their source (desk sheets piece 2): a
channel's `matrix_sends`, a bus's `bus_sends` and `matrix_sends`, a Main's
`matrix_sends`. Apply writes them, verify checks what they name, and audit
and Watch follow them. Plans are built in the test.
"""

from __future__ import annotations

import copy

import jsonschema

from atoo import plan_compat
from atoo.apply import _build_write_targets
from atoo.audit import (
    ConsoleState, planned_routing_legs, planned_routes, unplanned_route_findings,
    bus_send_drift_findings, route_drift_rule,
)
from atoo.plan_schema import GENERATION_SCHEMA, PLAN_SCHEMA
from atoo.render import render_plan
from atoo.verify_plan import verify_plan


def _plan() -> dict:
    """A Kick on the Drums bus, which sends on to a Broadcast bus; the Kick
    also straight to an IEM Matrix, pre; Main 1 into the PA Matrix."""
    return {
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Kick",
            "source": {"input": "Kick", "stereo": False, "phantom": False},
            "patch": {"group": "LCL", "sockets": [1], "stated": True},
            "processing": {"hpf_hz": None, "preset": None},
            "fader": {"fader_db": None, "muted": None}, "dca": [], "mute_group": [],
            "bus_sends": [{"bus": "Drums", "mode": "post", "level_db": 0.0}],
            "main_routes": [],
            "matrix_sends": [{"matrix": "Drum IEM", "mode": "pre", "level_db": -6.0}],
        }],
        "busses": {
            "Drums": {"index": 1, "destination": {"type": "main", "index": 1},
                      "destinations": [{"type": "main", "index": 1}], "mono": False,
                      "bus_sends": [{"bus": "Broadcast", "mode": "post"}]},
            "Broadcast": {"index": 8, "mono": False, "destination": {
                "type": "dedicated_output", "label": "Broadcast",
                "patch": {"group": "LCL", "sockets": [3, 4]}}},
        },
        "outputs": {
            "Main": {"kind": "main", "index": 1, "patch": None,
                     "matrix_sends": [{"matrix": "PA", "mode": "post"}]},
            "PA": {"kind": "matrix", "index": 1, "patch": {"group": "LCL", "sockets": [7, 8]}},
            "Drum IEM": {"kind": "matrix", "index": 6, "patch": {"group": "LCL", "sockets": [5, 6]}},
        },
        "dcas": {}, "mute_groups": {},
        "meta": {"console_model": "wing-compact"},
    }


# -- the schema ---------------------------------------------------------------------


def test_the_plan_schema_holds_them_and_the_models_does_not():
    jsonschema.validate(_plan(), PLAN_SCHEMA)
    channel = GENERATION_SCHEMA["properties"]["channels"]["items"]["properties"]
    assert "matrix_sends" not in channel


def test_a_matrix_is_fed_by_every_send_that_names_it():
    feeds = plan_compat.matrix_feeds(_plan())
    assert feeds["PA"] == [("main", "Main", "post")]
    assert feeds["Drum IEM"] == [("channel", "Kick", "pre")]


def test_render_lists_every_feed():
    text = render_plan(_plan(), [])
    assert "Fed by: Main (post)" in text and "Fed by: Kick (pre)" in text


# -- apply ------------------------------------------------------------------------


def _targets(plan):
    targets, _warnings = _build_write_targets(plan, True)
    return {t.address: t.compute_value(None) for t in targets}


def test_apply_writes_each_send_on_its_source():
    written = _targets(_plan())
    assert written["/ch/1/send/MX6/on"] == 1
    assert written["/ch/1/send/MX6/lvl"] == -6.0
    assert written["/ch/1/send/MX6/mode"] == "PRE"
    assert (written["/bus/1/send/8/on"], written["/bus/1/send/8/pre"]) == (1, 0)
    assert written["/bus/1/send/8/lvl"] == 0.0, "an unstated level is unity on a built plan"
    assert (written["/main/1/send/MX1/on"], written["/main/1/send/MX1/pre"]) == (1, 0)


def test_a_captured_plan_leaves_the_sends_level_and_tap_to_the_desk():
    plan = _plan()
    plan["meta"]["made_from"] = "snap"
    plan["busses"]["Drums"]["bus_sends"] = [{"bus": "Broadcast", "mode": None}]
    written = _targets(plan)
    assert written["/bus/1/send/8/on"] == 1
    assert "/bus/1/send/8/lvl" not in written and "/bus/1/send/8/pre" not in written


# -- verify -------------------------------------------------------------------------


def _codes(plan):
    result = verify_plan(plan)
    return {(f.code, f.where) for f in result.errors}


def test_verify_refuses_a_send_to_something_the_plan_does_not_have():
    plan = _plan()
    plan["channels"][0]["matrix_sends"] = [{"matrix": "Nowhere"}]
    plan["busses"]["Drums"]["bus_sends"].append({"bus": "Drums"})
    plan["outputs"]["PA"]["matrix_sends"] = [{"matrix": "Drum IEM"}]
    codes = _codes(plan)
    assert ("reference.dangling", "channels[Kick].matrix_sends[0]") in codes
    assert ("reference.dangling", "busses[Drums].bus_sends[1]") in codes
    assert ("reference.dangling", "outputs[PA].matrix_sends") in codes


def test_a_bus_that_only_sends_on_feeds_something():
    plan = _plan()
    plan["busses"]["Drums"].update(destination=None, destinations=[])
    assert not any(code == "bus.no-destination" for code, _where in _codes(plan))


def test_a_channel_reaches_main_through_a_bus_sending_to_a_bus():
    plan = _plan()
    plan["channels"][0]["matrix_sends"] = []
    plan["busses"]["Drums"].update(destination=None, destinations=[])
    plan["busses"]["Broadcast"]["destinations"] = [{"type": "main", "index": 1}]
    warnings = {f.code for f in verify_plan(plan).warnings}
    assert "routing.channel-misses-main" not in warnings
    assert "routing.channel-reaches-nothing" not in warnings


def test_a_send_to_a_matrix_reaches_an_output():
    plan = _plan()
    plan["channels"][0]["bus_sends"] = []
    assert "routing.channel-reaches-nothing" not in {f.code for f in verify_plan(plan).warnings}


# -- audit and Watch ---------------------------------------------------------------


def _desk(**changes) -> ConsoleState:
    values = {
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": 0.0, "/ch/1/send/1/mode": "POST",
        "/ch/1/send/MX6/on": 1, "/ch/1/send/MX6/lvl": -6.0, "/ch/1/send/MX6/mode": "PRE",
        "/bus/1/name": "Drums", "/bus/1/main/1/on": 1, "/bus/1/send/8/on": 1,
        "/bus/8/name": "Broadcast", "/main/1/send/MX1/on": 1, "/mtx/6/name": "Drum IEM",
    }
    values.update(changes)
    return ConsoleState(values, console_model="wing-compact")


def test_the_sends_are_legs_the_plan_states():
    legs = planned_routing_legs(_plan())
    assert {("/ch/1", "mtx:6"), ("bus:1", "bus:8"), ("main:1", "mtx:1")} <= legs


def test_a_planned_matrix_send_is_not_a_send_the_plan_lacks():
    assert unplanned_route_findings(_desk(), _plan()) == []
    plan = _plan()
    plan["channels"][0]["matrix_sends"] = []
    [row] = unplanned_route_findings(_desk(), plan)
    assert "MTX 6" in row.message


def test_a_planned_matrix_send_switched_off_is_cv006():
    findings = bus_send_drift_findings(_desk(**{"/ch/1/send/MX6/on": 0}), _plan())
    assert ['CH 1 "Kick": plan states a send to MTX 6 "Drum IEM", live console reads off.'] == [
        f.message for f in findings]


def test_cv016_counts_a_matrix_send_among_the_planned_routes():
    plan = _plan()
    assert ("mtx", "Drum IEM", 6) in planned_routes(plan, plan["channels"][0])
    off = _desk(**{"/ch/1/send/1/on": 0, "/ch/1/send/MX6/on": 0})
    rows = route_drift_rule(plan).check(off)
    assert rows and "MTX 6" in rows[0].message
