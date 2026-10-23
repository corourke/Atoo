"""CV006, CV007 and CV018: the plan's sends and Main routes, in `audit --plan`
and in Watch.

CV006 (a planned send off, or in the other pre/post mode) and CV007 (a
Main route the plan lists that is off, or one it does not list that is on)
ran only in `audit --plan`; a monitor send flipped post-fader mid-show went
unreported. Watch binds them to the plan now, with CV018 beside them: a
send to a bus or Matrix, or a bus's route to a Main, that is on and that the
plan does not have.

The plan is a frozen copy (`tests/fixtures/sixpiece_2026-10-11.plan.json`,
never `examples/`), and the desk is built from it here the way `apply`
leaves one: each planned send on, at its level, in its mode, every other
send off, and every Main off but the ones the plan lists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.audit import (
    DEFAULT_RULES, ConsoleState, Severity, bus_send_drift_rule, diff_against_plan,
    main_route_drift_rule, plan_watch_rules, run_audit, unplanned_route_findings,
    unplanned_route_rule,
)
from atoo.watch import watch

PLAN_PATH = Path(__file__).parent / "fixtures" / "sixpiece_2026-10-11.plan.json"
PLAN = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
FLOOR = -144.0
ROUTE_IDS = {"CV006", "CV007", "CV018"}


def _desk() -> dict[str, object]:
    """The rig as `apply` leaves it: planned sends on in their mode and at
    their level, every other send off, only the planned Mains on."""
    v: dict[str, object] = {}
    busses = PLAN["busses"]
    for entry in PLAN["channels"]:
        base = f"/{entry['bank']}/{entry['channel']}"
        v[f"{base}/name"] = entry["name"]
        v[f"{base}/mute"] = 0
        for n in range(1, 17):
            v[f"{base}/send/{n}/on"], v[f"{base}/send/{n}/lvl"] = 0, FLOOR
            v[f"{base}/send/{n}/mode"] = "PRE"
        for x in range(1, 9):
            v[f"{base}/send/MX{x}/on"], v[f"{base}/send/MX{x}/lvl"] = 0, FLOOR
        for send in entry.get("bus_sends") or []:
            n = busses[send["bus"]]["index"]
            v[f"{base}/send/{n}/on"] = 1
            v[f"{base}/send/{n}/lvl"] = float(send["level_db"])
            v[f"{base}/send/{n}/mode"] = send["mode"].upper()
        routed = {r["index"] for r in entry.get("main_routes") or []}
        for m in range(1, 5):
            v[f"{base}/main/{m}/on"] = 1 if m in routed else 0
    for name, entry in busses.items():
        base = f"/bus/{entry['index']}"
        v[f"{base}/name"], v[f"{base}/mute"] = name, 0
        dest = entry["destination"]
        for m in range(1, 5):
            v[f"{base}/main/{m}/on"] = 1 if dest.get("type") == "main" and dest.get("index") == m else 0
    return v


def _state(**changes) -> ConsoleState:
    values = _desk()
    values.update(changes)
    return ConsoleState(values, console_model="wing-compact")


def _rules():
    return [rule for rule in plan_watch_rules(PLAN_PATH) if rule.id in ROUTE_IDS]


def _found(state: ConsoleState, rule_id: str) -> list:
    return [f for f in run_audit(state, _rules()) if f.rule_id == rule_id]


def _index(channel_name: str) -> tuple[str, dict]:
    entry = next(e for e in PLAN["channels"] if e["name"] == channel_name)
    return f"/{entry['bank']}/{entry['channel']}", entry


def _unlisted_bus(entry: dict) -> tuple[str, int]:
    """A bus this channel's plan entry does not send to."""
    listed = {s["bus"] for s in entry["bus_sends"]}
    name = next(n for n in PLAN["busses"] if n not in listed)
    return name, PLAN["busses"][name]["index"]


# --------------------------------------------------------------------------
# A desk set up exactly as planned raises none of the three
# --------------------------------------------------------------------------


def test_watch_binds_all_three_to_the_plan():
    assert {r.id for r in plan_watch_rules(PLAN_PATH)} >= ROUTE_IDS


def test_a_desk_set_up_as_the_plan_says_raises_none_of_them():
    assert _found(_state(), "CV006") == []
    assert _found(_state(), "CV007") == []
    assert _found(_state(), "CV018") == []
    assert [f for f in diff_against_plan(_state(), PLAN) if f.rule_id in ROUTE_IDS] == []


def test_riding_every_send_level_is_not_a_row_in_watch():
    """A send level is what the engineer rides at soundcheck, so Watch does
    not compare it; `audit --plan` still does."""
    values = _desk()
    for address in list(values):
        if address.endswith("/lvl") and values[address] > FLOOR:
            values[address] = values[address] - 6.0
    state = ConsoleState(values)
    assert _found(state, "CV006") == []
    ridden = [f for f in diff_against_plan(state, PLAN) if f.rule_id == "CV006"]
    assert ridden and all("tolerance" in f.message for f in ridden)


# --------------------------------------------------------------------------
# CV006 in Watch: the switch and pre/post
# --------------------------------------------------------------------------


def test_a_monitor_send_flipped_post_fader_is_a_warning():
    kick, entry = _index("Kick")
    mon1 = PLAN["busses"]["MON1"]["index"]
    [finding] = _found(_state(**{f"{kick}/send/{mon1}/mode": "POST"}), "CV006")
    assert finding.severity == Severity.WARNING
    assert finding.addresses == (f"{kick}/send/{mon1}/mode",)
    assert "plan says send to MON1 mode is 'pre' (PRE), live console reads POST" in finding.message
    assert finding.message.startswith('CH 1 "Kick":')


def test_one_planned_send_switched_off_is_a_warning_naming_it():
    kick, _ = _index("Kick")
    mon2 = PLAN["busses"]["MON2"]["index"]
    [finding] = _found(_state(**{f"{kick}/send/{mon2}/on": 0}), "CV006")
    assert finding.message.startswith('CH 1 "Kick": plan states a send to MON2, live console reads off.')
    assert finding.addresses == (f"{kick}/send/{mon2}/on",)


def test_a_send_that_did_not_answer_is_not_a_contradiction():
    kick, _ = _index("Kick")
    mon1 = PLAN["busses"]["MON1"]["index"]
    values = _desk()
    del values[f"{kick}/send/{mon1}/on"]
    del values[f"{kick}/send/{mon1}/mode"]
    assert _found(ConsoleState(values), "CV006") == []
    assert [f for f in diff_against_plan(ConsoleState(values), PLAN) if f.rule_id == "CV006"] == []


def test_a_plan_without_sends_adds_no_cv006_rule():
    plan = {"channels": [{"bank": "ch", "channel": 1, "bus_sends": [], "main_routes": []}]}
    assert bus_send_drift_rule(plan) is None


def test_a_send_cv016_already_reports_is_said_once():
    """Kick out of both its planned busses: CV016 names both, so CV006 does
    not add a row for each -- in Watch and in `audit --plan`."""
    drums, comp = PLAN["busses"]["Drums"]["index"], PLAN["busses"]["Drums Comp"]["index"]
    state = _state(**{f"/ch/1/send/{drums}/on": 0, f"/ch/1/send/{comp}/on": 0})
    ids = [f.rule_id for f in run_audit(state, list(DEFAULT_RULES) + plan_watch_rules(PLAN_PATH))
           if f.rule_id in {"CV006", "CV016"}]
    assert ids == ["CV016"]
    assert [f.rule_id for f in diff_against_plan(state, PLAN)
            if f.rule_id in {"CV006", "CV016"}] == ["CV016"]


def test_one_send_off_of_several_is_cv006_not_cv016():
    drums = PLAN["busses"]["Drums"]["index"]
    state = _state(**{f"/ch/1/send/{drums}/on": 0})
    assert [f.rule_id for f in diff_against_plan(state, PLAN)
            if f.rule_id in {"CV006", "CV016"}] == ["CV006"]


# --------------------------------------------------------------------------
# CV007 in Watch
# --------------------------------------------------------------------------


def test_a_listed_main_route_switched_off_is_cv007_when_the_strip_still_reaches_something():
    """With another planned route still on, CV016 does not speak, so the
    Main route that is off is CV007's."""
    plan = {"busses": {"Drums": {"index": 7, "destination": {"type": "main", "index": 1}}},
            "channels": [{"bank": "ch", "channel": 1, "name": "Bass",
                          "bus_sends": [{"bus": "Drums", "mode": "post", "level_db": 0.0}],
                          "main_routes": [{"index": 1}]}]}
    state = ConsoleState({"/ch/1/name": "Bass", "/bus/7/name": "Drums",
                          "/ch/1/send/7/on": 1, "/ch/1/send/7/lvl": 0.0, "/ch/1/main/1/on": 0})
    [finding] = main_route_drift_rule(plan).check(state)
    assert finding.rule_id == "CV007"
    assert finding.message == ('CH 1 "Bass": plan says this channel routes directly to Main 1, '
                               "live console reads off.")


def test_an_unlisted_main_reading_on_is_cv007():
    kick, _ = _index("Kick")
    [finding] = _found(_state(**{f"{kick}/main/1/on": 1}), "CV007")
    assert finding.severity == Severity.WARNING
    assert "plan lists no direct route from this channel to Main 1, live console reads on" in finding.message
    assert finding.addresses == (f"{kick}/main/1/on",)


def test_a_main_that_did_not_answer_is_not_a_finding():
    kick, _ = _index("Kick")
    values = _desk()
    del values[f"{kick}/main/1/on"]
    assert _found(ConsoleState(values), "CV007") == []


def test_a_listed_main_route_cv016_names_is_said_once():
    """Bass's only planned path is Main 1 (its INST Reverb send is at the
    floor, so not a planned path)."""
    bass, _ = _index("Bass")
    state = _state(**{f"{bass}/main/1/on": 0})
    ids = [f.rule_id for f in run_audit(state, list(DEFAULT_RULES) + plan_watch_rules(PLAN_PATH))
           if f.rule_id in {"CV007", "CV016"}]
    assert ids == ["CV016"]


# --------------------------------------------------------------------------
# CV018: a send or route the plan does not have
# --------------------------------------------------------------------------


MODELS = ["wing-compact", "wing", "wing-rack"]


@pytest.mark.parametrize("model", MODELS)
def test_a_send_to_a_bus_the_plan_does_not_list_raises_nothing(model):
    """Decided 2026-10-22: CV018 is not needed for sends to a bus."""
    crowd, entry = _index("Crowd")
    _name, n = _unlisted_bus(entry)
    values = _desk()
    values.update({f"{crowd}/send/{n}/on": 1, f"{crowd}/send/{n}/lvl": -6.0})
    state = ConsoleState(values, console_model=model)
    assert _found(state, "CV018") == []
    assert unplanned_route_findings(state, PLAN) == []


def test_the_click_opened_to_the_pa_bus_is_no_longer_a_finding():
    """A send into a bus that feeds Main 1 is not a Main route of the strip,
    so CV007 cannot see it either; the engineer added it and knows."""
    kick, entry = _index("Kick")
    inst = PLAN["busses"]["INST Reverb"]["index"]
    state = _state(**{f"{kick}/send/{inst}/on": 1, f"{kick}/send/{inst}/lvl": 0.0})
    assert _found(state, "CV018") == []
    assert _found(state, "CV007") == []


def test_a_planned_send_is_never_cv018_whatever_its_level():
    kick, _ = _index("Kick")
    mon1 = PLAN["busses"]["MON1"]["index"]
    assert _found(_state(**{f"{kick}/send/{mon1}/lvl": 0.0}), "CV018") == []


@pytest.mark.parametrize("model", MODELS)
def test_a_send_to_a_matrix_is_an_info_and_the_floor_is_not(model):
    kick, _ = _index("Kick")
    values = _desk()
    values.update({f"{kick}/send/MX2/on": 1, f"{kick}/send/MX2/lvl": -3.0})
    [finding] = _found(ConsoleState(values, console_model=model), "CV018")
    assert finding.severity == Severity.INFO
    assert finding.message == ('CH 1 "Kick": a send to MTX 2 is on at -3dB; '
                               "the plan has no send from this channel to a Matrix.")
    assert finding.addresses == (f"{kick}/send/MX2/on",)
    assert _found(_state(**{f"{kick}/send/MX2/on": 1}), "CV018") == []
    assert _found(_state(**{f"{kick}/send/MX2/on": 1, f"{kick}/send/MX2/lvl": FLOOR}), "CV018") == []


@pytest.mark.parametrize("model", MODELS)
def test_a_wedge_bus_summed_into_main_is_an_info(model):
    mon3 = PLAN["busses"]["MON3"]["index"]
    values = _desk()
    values[f"/bus/{mon3}/main/1/on"] = 1
    [finding] = _found(ConsoleState(values, console_model=model), "CV018")
    assert finding.severity == Severity.INFO
    assert finding.message == (f'BUS {mon3} "MON3": routed to MAIN 1 on the desk; '
                               "the plan lists no route from this bus to it.")
    assert finding.addresses == (f"/bus/{mon3}/main/1/on",)


def test_a_bus_on_the_main_the_plan_lists_is_clean_and_another_main_is_not():
    drums = PLAN["busses"]["Drums"]["index"]
    assert _found(_state(), "CV018") == []
    [finding] = _found(_state(**{f"/bus/{drums}/main/2/on": 1}), "CV018")
    assert "routed to MAIN 2" in finding.message


def test_a_bus_main_that_did_not_answer_is_not_a_finding():
    mon3 = PLAN["busses"]["MON3"]["index"]
    values = _desk()
    del values[f"/bus/{mon3}/main/1/on"]
    assert _found(ConsoleState(values), "CV018") == []


def test_a_bus_with_no_destination_listed_has_no_main_route_in_the_plan():
    """`apply` writes every Main off for such a bus, so one that is on is
    left over."""
    plan = {"busses": {"Wedge": {"index": 2}}}
    state = ConsoleState({"/bus/2/name": "Wedge", "/bus/2/main/1/on": 1, "/bus/2/main/2/on": 0})
    [finding] = unplanned_route_findings(state, plan)
    assert "routed to MAIN 1" in finding.message


def test_a_destination_without_an_index_is_main_1():
    plan = {"busses": {"PA": {"index": 2, "destination": {"type": "main"}}}}
    state = ConsoleState({"/bus/2/name": "PA", "/bus/2/main/1/on": 1})
    assert unplanned_route_findings(state, plan) == []


def test_the_plans_other_destinations_list_their_mains_too():
    plan = {"busses": {"PA": {"index": 2, "destinations": [
        {"type": "main", "index": 1}, {"type": "main", "index": 2},
        {"type": "dedicated_output", "patch": {"group": "LCL", "sockets": [1]}}]}}}
    state = ConsoleState({"/bus/2/main/1/on": 1, "/bus/2/main/2/on": 1, "/bus/2/main/3/on": 1})
    [finding] = unplanned_route_findings(state, plan)
    assert "MAIN 3" in finding.message


def test_a_bus_is_named_as_the_plan_names_it_when_the_desk_has_no_name():
    plan = {"busses": {"Wedge": {"index": 2}}}
    state = ConsoleState({"/bus/2/main/1/on": 1})
    [finding] = unplanned_route_findings(state, plan)
    assert finding.message.startswith('BUS 2 "Wedge":')


# --------------------------------------------------------------------------
# Silent when the plan is silent
# --------------------------------------------------------------------------


def test_a_strip_the_plan_never_mentions_is_not_judged():
    values = _desk()
    values["/ch/47/name"] = "Spare"
    values["/ch/47/send/1/on"], values["/ch/47/send/1/lvl"] = 1, 0.0
    values["/ch/47/main/1/on"] = 1
    state = ConsoleState(values)
    assert all(_found(state, rule_id) == [] for rule_id in ROUTE_IDS)


def test_a_bus_the_plan_never_mentions_is_not_judged():
    state = _state(**{"/bus/16/name": "Spare", "/bus/16/main/1/on": 1})
    assert _found(state, "CV018") == []


def test_a_plan_with_no_channels_and_no_busses_adds_none_of_them():
    assert main_route_drift_rule({"channels": []}) is None
    assert unplanned_route_rule({"channels": [], "busses": {}}) is None
    assert unplanned_route_rule({"busses": {"Wedge": {"index": 1}}}) is not None


# --------------------------------------------------------------------------
# audit --plan runs them, and plan scope does not withhold them
# --------------------------------------------------------------------------


def test_audit_with_a_plan_reports_the_twin_and_scope_withholds_nothing_of_it():
    from atoo.audit import apply_plan_scope

    kick, _ = _index("Kick")
    state = _state(**{f"{kick}/send/MX2/on": 1, f"{kick}/send/MX2/lvl": -3.0,
                      "/bus/9/main/2/on": 1})
    found = [f for f in diff_against_plan(state, PLAN) if f.rule_id == "CV018"]
    assert [f.severity for f in found] == [Severity.INFO, Severity.INFO]
    scoped = apply_plan_scope(state, run_audit(state, _rules()), PLAN, _rules())
    assert [f.rule_id for f in scoped.findings if f.rule_id == "CV018"] == ["CV018", "CV018"]
    assert not [w for w in scoped.withheld if w.finding.rule_id in ROUTE_IDS]


# --------------------------------------------------------------------------
# Watch: the finding appears and clears
# --------------------------------------------------------------------------


def _run(states):
    seq = iter(states)
    return list(watch(lambda: next(seq), rules=_rules(), interval=0, max_iterations=len(states),
                      sleep=lambda _s: None))


def test_watch_raises_a_flipped_send_and_clears_it_when_put_back():
    kick, _ = _index("Kick")
    mon1 = PLAN["busses"]["MON1"]["index"]
    events = _run([_state(), _state(**{f"{kick}/send/{mon1}/mode": "POST"}), _state()])
    assert [f.rule_id for f in events[1].new_findings] == ["CV006"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CV006"]


def test_watch_raises_a_matrix_send_as_an_info_and_clears_it():
    kick, _ = _index("Kick")
    opened = {f"{kick}/send/MX2/on": 1, f"{kick}/send/MX2/lvl": 0.0}
    events = _run([_state(), _state(**opened), _state()])
    assert [(f.rule_id, f.severity) for f in events[1].new_findings] == [("CV018", Severity.INFO)]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CV018"]


def test_watch_raises_a_direct_main_route_and_clears_it():
    kick, _ = _index("Kick")
    events = _run([_state(), _state(**{f"{kick}/main/1/on": 1}), _state()])
    assert [f.rule_id for f in events[1].new_findings] == ["CV007"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CV007"]


def test_the_findings_are_ordinary_rows_not_folded_under_another():
    from atoo.watch import present_findings

    kick, _ = _index("Kick")
    mon1 = PLAN["busses"]["MON1"]["index"]
    findings = run_audit(_state(**{f"{kick}/send/{mon1}/mode": "POST"}), _rules())
    shown = present_findings(findings)
    assert [f.rule_id for f in shown.alerts] == ["CV006"]
    assert shown.folded == {}
