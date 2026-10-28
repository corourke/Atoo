"""ACTIVE in a watch condition's Channel cell, and the one "active" the fixed
rules share.

`ACTIVE ALL BUS · muted == true` alerts on a muted bus only while the bus is
active: on the open show's sheets, or in use on the desk. The word may stand
anywhere in the cell, in any case, and is written back first. The fixed rules
that ask whether a strip is in use (L002, R001, R002, ...) count a strip on
the sheets as in use too. Every state here is built in the test.
"""

from __future__ import annotations

import json

import pytest

from atoo import audit
from atoo.audit import ConsoleState, Severity, is_active, on_sheets, sheet_bases
from atoo.watch_conditions import (
    TargetError, build_watch_rules, canonical_target, explain_condition,
    merge_drafted_conditions, parse_target, row_problems,
)


# ----------------------------------------------------------------------
# The word, wherever it stands
# ----------------------------------------------------------------------


@pytest.mark.parametrize("cell", ["ACTIVE ALL BUS", "ALL ACTIVE BUS", "ALL BUS ACTIVE",
                                  "active all bus", "  Active   ALL  bus "])
def test_active_is_read_in_any_position_and_written_first(cell):
    target = parse_target(cell)
    assert target.active and target.all_of_kind and target.bank == "bus"
    assert target.canonical == "ACTIVE ALL BUS" == canonical_target(cell)


@pytest.mark.parametrize("cell, canonical, bases", [
    ("ACTIVE CH 1-24", "ACTIVE CH 1-24", 24),
    ("active dca 1-8", "ACTIVE DCA 1-8", 8),
    ("bus 3 active", "ACTIVE BUS 3", 1),
    ("ACTIVE MTX 2", "ACTIVE MTX 2", 1),
])
def test_active_with_a_position_or_a_range(cell, canonical, bases):
    target = parse_target(cell)
    assert target.active and target.canonical == canonical and len(target.bases()) == bases


def test_active_and_the_same_target_without_it_are_two_targets():
    assert parse_target("ACTIVE ALL BUS").key != parse_target("ALL BUS").key


@pytest.mark.parametrize("cell", ["ACTIVE", "active", " Active "])
def test_a_cell_that_is_only_active_is_refused_saying_it_needs_a_strip(cell):
    with pytest.raises(TargetError, match="names no strip -- ACTIVE goes with a strip, a range "
                                          "or ALL and a kind"):
        parse_target(cell)
    assert "names no strip" in row_problems(_cond(cell))["channel"]


def test_active_is_the_word_even_beside_a_name_and_the_reading_is_said():
    """`Kick active` could be a channel named that: ACTIVE is taken as the
    word, the editor shows which reading, and Save writes ACTIVE first."""
    target = parse_target("Kick active")
    assert target.active and target.is_name and target.text == "Kick"
    checked = row_problems(_cond("Kick active"))
    assert checked["active"] is True and checked["canonical"] == "ACTIVE Kick"
    assert "watches the strip named 'Kick' while it is active" in checked["note"]
    assert canonical_target("Kick active") == "ACTIVE Kick"
    # A strip named "Active" is watched by its position: "BUS Active" leaves
    # a bare kind word, refused saying why.
    with pytest.raises(TargetError, match="a strip named Active is watched by its position"):
        parse_target("BUS Active")


def test_the_i_sentence_says_what_active_means():
    assert explain_condition(_cond("ACTIVE ALL BUS")).startswith(
        "Alerts as an error when any active BUS is muted. Active: on this show's sheets, or "
        "in use on the desk.")
    assert "Active:" not in explain_condition(_cond("ALL BUS"))


# ----------------------------------------------------------------------
# One condition, three busses: on the sheets, on the desk, neither
# ----------------------------------------------------------------------

#: Bus 2 is on the show's sheets only (nothing on the desk says so), bus 3 is
#: in use on the desk only (named there), bus 4 is neither. All three muted.
_PLAN = {"channels": [], "busses": {"Drums": {"index": 2, "destination": None}},
         "dcas": {}, "mute_groups": {}, "outputs": {}}


def _bus_state() -> ConsoleState:
    values: dict = {}
    for n in (2, 3, 4):
        values.update({f"/bus/{n}/name": "", f"/bus/{n}/mute": 1, f"/bus/{n}/fdr": 0.0})
    values["/bus/3/name"] = "Wedges"
    return ConsoleState(values, console_model="wing-compact")


def _cond(channel: str, **over) -> dict:
    return {"id": "bus-muted", "description": "A bus is muted", "channel": channel,
            "field": "muted", "operator": "==", "value": True, "severity": "error", **over}


def _fired(state: ConsoleState, channel: str = "ACTIVE ALL BUS") -> list[str]:
    [rule] = build_watch_rules([_cond(channel)])
    return sorted(f.addresses[0].rsplit("/", 1)[0] for f in rule.check(state)
                  if f.severity is Severity.ERROR)


def test_with_a_show_open_it_fires_on_the_sheets_and_the_desk_not_on_neither():
    assert _fired(on_sheets(_bus_state(), _PLAN)) == ["/bus/2", "/bus/3"]


def test_with_no_show_open_only_the_desk_counts():
    assert _fired(_bus_state()) == ["/bus/3"]


def test_without_active_every_bus_fires():
    assert _fired(_bus_state(), "ALL BUS") == ["/bus/2", "/bus/3", "/bus/4"]


def test_a_strip_that_becomes_active_mid_show_is_picked_up_at_the_next_pass():
    state = _bus_state()
    assert "/bus/4" not in _fired(state)
    state.values["/bus/4/name"] = "Spare"
    assert "/bus/4" in _fired(state)


def test_watch_binds_the_shows_sheets_to_every_rule(tmp_path):
    """Watch (the command line and the page) binds its rules with
    `with_plan_rules`, which lays the plan's sheets on every state."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_PLAN))
    rules = audit.with_plan_rules(build_watch_rules([_cond("ACTIVE ALL BUS")]), plan_path)
    [rule] = [r for r in rules if r.id == "WATCH:bus-muted"]
    fired = sorted(f.addresses[0] for f in rule.check(_bus_state())
                   if f.severity is Severity.ERROR)
    assert fired == ["/bus/2/mute", "/bus/3/mute"]


def test_an_active_name_target_is_checked_only_while_active():
    state = ConsoleState({"/ch/5/name": "Kick", "/ch/5/mute": 1}, console_model="wing-compact")
    [rule] = build_watch_rules([_cond("ACTIVE Kick")])
    findings = rule.check(state)
    assert [f for f in findings if f.severity is Severity.ERROR]       # named: in use
    assert [f for f in findings if f.severity is Severity.INFO
            and "watches the strip named 'Kick' while it is active" in f.detail]


# ----------------------------------------------------------------------
# Active on the desk, by kind
# ----------------------------------------------------------------------


def _desk(values: dict) -> ConsoleState:
    return ConsoleState(dict(values), console_model="wing-compact")


def test_a_dca_or_mute_group_is_active_with_a_member():
    state = _desk({"/ch/1/tags": "#D2,#M3", "/ch/2/tags": ""})
    assert is_active(state, "/dca/2") and is_active(state, "/mgrp/3")
    assert not is_active(state, "/dca/1") and not is_active(state, "/mgrp/1")


@pytest.mark.parametrize("values, active", [
    ({"/ch/1/main/2/on": 1}, True),                                     # a route into it
    ({"/main/2/send/MX1/on": 1}, True),                                 # it feeds a Matrix
    ({"/io/out/LCL/3/grp": "MAIN", "/io/out/LCL/3/in": 3}, True),       # patched out (L of 2)
    ({"/ch/1/main/2/on": 0, "/main/2/send/MX1/on": 0,
      "/io/out/LCL/3/grp": "OFF", "/io/out/LCL/3/in": 3}, False),       # neither
])
def test_a_main_is_active_with_a_send_in_or_a_route_out(values, active):
    assert is_active(_desk(values), "/main/2") is active


@pytest.mark.parametrize("values, active", [
    ({"/bus/1/send/MX3/on": 1}, True),                                  # a send into it
    ({"/io/out/LCL/6/grp": "MTX", "/io/out/LCL/6/in": 6}, True),        # patched out (R of 3)
    ({"/bus/1/send/MX3/on": 0, "/io/out/LCL/6/grp": "OFF", "/io/out/LCL/6/in": 6}, False),
])
def test_a_matrix_is_active_with_a_send_in_or_a_route_out(values, active):
    assert is_active(_desk(values), "/mtx/3") is active


def test_the_sheets_make_any_kind_active():
    plan = {"channels": [{"channel": 7, "bank": "aux"}, {"channel": 12}],
            "busses": {"B": {"index": 9}}, "dcas": {"D": {"index": 4}},
            "mute_groups": {"M": {"index": 2}},
            "outputs": {"PA": {"kind": "main", "index": 1}, "Fill": {"kind": "matrix", "index": 5}}}
    assert sheet_bases(plan) == {"/aux/7", "/ch/12", "/bus/9", "/dca/4", "/mgrp/2", "/main/1",
                                 "/mtx/5"}
    state = on_sheets(_desk({}), plan)
    assert all(is_active(state, base) for base in sheet_bases(plan))
    assert not is_active(state, "/ch/13")


# ----------------------------------------------------------------------
# The fixed rules read the same "active"
# ----------------------------------------------------------------------


def _ids(state: ConsoleState, rule_id: str) -> list[str]:
    [rule] = [r for r in audit.DEFAULT_RULES if r.id == rule_id]
    return [f.addresses[0] for f in rule.check(state)]


def test_l002_fader_at_floor_on_a_strip_on_the_sheets_only():
    state = _desk({"/ch/4/name": "", "/ch/4/mute": 0, "/ch/4/fdr": -144.0})
    assert _ids(state, "L002") == []
    assert _ids(on_sheets(state, {"channels": [{"channel": 4}]}), "L002")


def test_r001_a_bus_on_the_sheets_only_with_no_inputs():
    state = _desk({"/bus/6/name": "", "/ch/1/send/6/on": 0})
    assert _ids(state, "R001") == []
    assert _ids(on_sheets(state, {"busses": {"Fx": {"index": 6}}}), "R001") == ["/bus/6/name"]


def test_r002_a_bus_on_the_sheets_only_with_no_output():
    values = {"/bus/6/name": "", "/bus/6/main/1/on": 0}
    values.update({f"/io/out/LCL/{n}/grp": "OFF" for n in range(1, 9)})
    values.update({f"/io/out/LCL/{n}/in": 1 for n in range(1, 9)})
    state = _desk(values)
    assert _ids(state, "R002") == []
    assert _ids(on_sheets(state, {"busses": {"Fx": {"index": 6}}}), "R002") == ["/bus/6/name"]


def test_run_audit_with_a_plan_reads_its_sheets():
    state = _desk({"/bus/6/name": "", "/ch/1/send/6/on": 0})
    assert "R001" not in {f.rule_id for f in audit.run_audit(state)}
    assert "R001" in {f.rule_id for f in audit.run_audit(state, plan={"busses": {"Fx": {
        "index": 6, "destination": None}}})}


# ----------------------------------------------------------------------
# A drafted condition, and the watch notes
# ----------------------------------------------------------------------


def test_a_drafted_active_condition_is_not_a_duplicate_of_the_one_without_it():
    existing = {"watch_conditions": [dict(_cond("ALL BUS"), id="mine")]}
    document, report = merge_drafted_conditions(existing, [_cond("active all bus")])
    channels = [c["channel"] for c in document["watch_conditions"]]
    assert channels == ["ALL BUS", "ACTIVE ALL BUS"] and tuple(report.added) == ("bus-muted",)
    existing = {"watch_conditions": [dict(_cond("ACTIVE ALL BUS"), id="mine")]}
    document, report = merge_drafted_conditions(existing, [_cond("ALL BUS")])
    assert tuple(report.added) == ("bus-muted",)


def test_with_no_show_the_watch_note_says_active_is_the_desk_alone():
    from atoo.watch import no_plan_note
    assert "a strip counts as active only when the desk reads it in use" in no_plan_note().detail


def test_the_watch_page_writes_active_back_and_offers_it():
    """The page's own asset carries the new key and wording: a Python test
    cannot otherwise see what the browser reads."""
    from conftest import require_fastapi_testclient
    from atoo.webui import create_app

    fastapi_testclient = require_fastapi_testclient()

    with fastapi_testclient.TestClient(create_app()) as c:
        js = c.get("/static/watch.js").text
        checked = c.post("/api/watch-conditions/check",
                         json={"watch_conditions": [_cond("all bus active")]}).json()
    assert "check.position || check.scoped || check.active" in js
    assert "ACTIVE ALL BUS" in js
    [row] = checked["rows"]
    assert row["active"] is True and row["canonical"] == "ACTIVE ALL BUS"
    assert "Active: on this show's sheets, or in use on the desk." in row["explanation"]


def test_an_active_condition_names_what_the_active_test_reads():
    from atoo.watch_conditions import condition_address_patterns
    plain = set(condition_address_patterns(_cond("ALL BUS")))
    active = set(condition_address_patterns(_cond("ACTIVE ALL BUS")))
    assert plain < active
    import re
    for address in ("/ch/3/tags", "/ch/3/in/conn/grp", "/bus/2/main/1/on",
                    "/main/1/send/MX2/on", "/io/out/LCL/4/grp"):
        assert any(re.match(p, address) for p in active), address
