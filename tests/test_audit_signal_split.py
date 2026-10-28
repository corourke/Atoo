"""R012 (Signal Splits And Recombines) and R013 (Signal Split Asked For): one
strip reaching the same Main or Matrix by two routes.

Desks and plans are built in the test; nothing here reads a show bundle.
"""

from __future__ import annotations

import json
import time

from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    RuleScope,
    planned_routing_legs,
    run_audit,
    split_path_rules,
    split_paths,
    with_plan_rules,
)
from atoo.diagnostics import Severity


def _rule(rule_id):
    return next(r for r in DEFAULT_RULES if r.id == rule_id)


def _strip(base, name, *, mute=0, **legs) -> dict[str, object]:
    v: dict[str, object] = {f"{base}/name": name, f"{base}/mute": mute}
    for key, on in legs.items():
        if key.startswith("main"):
            v[f"{base}/main/{key[4:]}/on"] = on
        elif key.startswith("mtx"):
            v[f"{base}/send/MX{key[3:]}/on"] = on
            v[f"{base}/send/MX{key[3:]}/lvl"] = 0.0
        else:
            v[f"{base}/send/{key[3:]}/on"] = on
            v[f"{base}/send/{key[3:]}/lvl"] = 0.0
    return v


def _bus(index, name, *, mute=0, mains=(), matrices=()) -> dict[str, object]:
    base = f"/bus/{index}"
    v: dict[str, object] = {f"{base}/name": name, f"{base}/mute": mute}
    for m in mains:
        v[f"{base}/main/{m}/on"] = 1
    for x in matrices:
        v[f"{base}/send/MX{x}/on"] = 1
        v[f"{base}/send/MX{x}/lvl"] = 0.0
    return v


def _main(index, *, matrices=(), mute=0) -> dict[str, object]:
    v: dict[str, object] = {f"/main/{index}/mute": mute, f"/main/{index}/fdr": 0.0}
    for x in matrices:
        v[f"/main/{index}/send/MX{x}/on"] = 1
        v[f"/main/{index}/send/MX{x}/lvl"] = 0.0
    return v


def _state(*parts) -> ConsoleState:
    values: dict[str, object] = {}
    for part in parts:
        values.update(part)
    return ConsoleState(values, console_model="wing-compact")


def _split(state, rule_id="R012", plan=None):
    return [f for f in run_audit(state, plan=plan) if f.rule_id == rule_id]


# --------------------------------------------------------------------------
# The rows
# --------------------------------------------------------------------------


def test_the_split_is_a_warning_and_its_announcement_an_info():
    r012, r013 = _rule("R012"), _rule("R013")
    assert (r012.severity, r013.severity) == (Severity.WARNING, Severity.INFO)
    assert r012.category == r013.category == "routing"
    assert r012.scope is r013.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# What is a split
# --------------------------------------------------------------------------


def test_a_direct_route_and_a_route_through_a_bus_to_one_main_is_reported_once_by_name():
    state = _state(_strip("/ch/1", "Kick", main1=1, bus1=1), _bus(1, "Drums", mains=(1,)),
                   _main(1))
    [finding] = _split(state)
    assert finding.severity is Severity.WARNING
    assert finding.message.startswith(
        'CH 1 "Kick" reaches MAIN 1 twice: directly, and through BUS 1 "Drums".')
    assert "/ch/1/main/1/on" in finding.addresses and "/bus/1/main/1/on" in finding.addresses


def test_two_busses_that_reach_one_main_is_parallel_processing_and_is_still_reported():
    state = _state(_strip("/ch/1", "Kick", bus1=1, bus2=1),
                   _bus(1, "Drums", mains=(1,)), _bus(2, "Drums Comp", mains=(1,)), _main(1))
    [finding] = _split(state)
    assert ('reaches MAIN 1 twice: through BUS 1 "Drums", and through BUS 2 "Drums Comp"'
            in finding.message)


def test_a_matrix_fed_directly_and_through_a_bus_is_a_split_at_the_matrix():
    state = _state(_strip("/ch/1", "Kick", mtx1=1, bus1=1), _bus(1, "Drums", matrices=(1,)))
    [finding] = _split(state)
    assert 'CH 1 "Kick" reaches MTX 1 twice: directly, and through BUS 1 "Drums"' in finding.message


def test_three_routes_are_named_each_hop_by_hop():
    state = _state(_strip("/ch/1", "Kick", main1=1, bus1=1, bus2=1),
                   _bus(1, "Drums", mains=(1,)), _bus(2, "Comp", mains=(1,)), _main(1))
    [finding] = _split(state)
    assert "three times: directly; through BUS 1" in finding.message
    assert '; and through BUS 2 "Comp"' in finding.message


def test_routes_that_share_their_last_hop_are_reported_where_they_met_not_again_downstream():
    state = _state(_strip("/ch/1", "Kick", main1=1, bus1=1), _bus(1, "Drums", mains=(1,)),
                   _main(1, matrices=(1,)))
    [split] = split_paths(state)
    assert split.destination == "main:1"
    assert len(_split(state)) == 1


def test_a_strip_with_one_route_to_each_destination_is_not_a_split():
    state = _state(_strip("/ch/1", "Kick", main1=1, bus1=1), _bus(1, "Drums", mains=(2,)),
                   _main(1), _main(2))
    assert _split(state) == []


def test_a_leg_that_is_off_or_at_the_floor_is_not_a_route():
    off = _state(_strip("/ch/1", "Kick", main1=1, bus1=0), _bus(1, "Drums", mains=(1,)), _main(1))
    assert _split(off) == []
    floor = _state(_strip("/ch/1", "Kick", main1=1, bus1=1), _bus(1, "Drums", mains=(1,)),
                   _main(1), {"/ch/1/send/1/lvl": -144.0})
    assert _split(floor) == []


def test_a_muted_bus_is_still_a_route_and_the_finding_says_it_is_muted():
    state = _state(_strip("/ch/1", "Kick", main1=1, bus1=1), _bus(1, "Drums", mains=(1,), mute=1),
                   _main(1))
    [finding] = _split(state)
    assert 'BUS 1 "Drums" is muted, so the signal through it is silent now and joins the moment' \
        in finding.message


def test_a_leg_whose_switch_was_never_read_is_not_a_route():
    values = _strip("/ch/1", "Kick", main1=1, bus1=1)
    state = _state(values, _bus(1, "Drums"), _main(1))
    assert _split(state) == []


# --------------------------------------------------------------------------
# Unless the plan asked for it
# --------------------------------------------------------------------------


def _parallel_state():
    return _state(_strip("/ch/1", "Kick", bus1=1, bus2=1),
                  _bus(1, "Drums", mains=(1,)), _bus(2, "Drums Comp", mains=(1,)), _main(1))


def _parallel_plan(*, with_comp_destination=True):
    comp = {"index": 2, "destinations": ([{"type": "main", "index": 1}]
                                         if with_comp_destination else [])}
    return {
        "channels": [{"channel": 1, "bank": "ch", "name": "Kick",
                      "bus_sends": [{"bus": "Drums", "level_db": 0.0},
                                    {"bus": "Drums Comp", "level_db": 0.0}],
                      "main_routes": []}],
        "busses": {"Drums": {"index": 1, "destinations": [{"type": "main", "index": 1}]},
                   "Drums Comp": comp},
        "outputs": {},
    }


def test_with_no_plan_nothing_can_have_been_asked_for_so_it_reports_and_r013_is_silent():
    state = _parallel_state()
    assert len(_split(state)) == 1
    assert _split(state, "R013") == []


def test_a_plan_that_states_every_leg_stands_r012_down_and_r013_says_so():
    state, plan = _parallel_state(), _parallel_plan()
    assert _split(state, plan=plan) == []
    [note] = _split(state, "R013", plan=plan)
    assert note.severity is Severity.INFO
    assert 'CH 1 "Kick" reaches MAIN 1 by more than one route' in note.message
    assert "asked for" in note.message


def test_a_plan_that_leaves_one_leg_out_still_reports_and_says_which_it_does_not_state():
    state, plan = _parallel_state(), _parallel_plan(with_comp_destination=False)
    [finding] = _split(state, plan=plan)
    assert 'the plan does not include the route BUS 2 "Drums Comp" to MAIN 1' in finding.message
    assert _split(state, "R013", plan=plan) == []


def test_a_direct_route_the_plan_never_lists_is_not_asked_for():
    state = _state(_strip("/ch/1", "Kick", main1=1, bus1=1), _bus(1, "Drums", mains=(1,)),
                   _main(1))
    plan = _parallel_plan()
    [finding] = _split(state, plan=plan)
    assert "the plan does not include the route" in finding.message


def test_with_no_plan_in_hand_the_message_says_so_and_does_not_tell_the_user_to_rebuild():
    [finding] = _split(_parallel_state())
    assert "Atoo has no plan it could read for this show" in finding.message
    assert "run it with the show's plan" in finding.message
    assert "rebuild" not in finding.message
    assert "leg" not in finding.message.lower()


def test_with_a_plan_that_lacks_a_route_the_advice_is_the_chosen_wording_and_names_the_route():
    [partial] = _split(_parallel_state(), plan=_parallel_plan(with_comp_destination=False))
    assert ("If this is intended, state the purpose of the parallel bus in your conventions "
            "or instructions and rebuild; if not, switch one of the routes off.") in partial.message
    assert "no plan" not in partial.message
    assert "leg" not in partial.message.lower()
    [note] = _split(_parallel_state(), "R013", plan=_parallel_plan())
    assert "leg" not in note.message.lower()


def test_watch_rules_for_a_plan_that_cannot_be_read_leave_r012_with_the_no_plan_message(tmp_path):
    rules = with_plan_rules(DEFAULT_RULES, tmp_path / "missing.plan.json")
    [finding] = [f for rule in rules for f in rule.check(_parallel_state()) if rule.id == "R012"]
    assert "has no plan it could read" in finding.message


def test_planned_routing_legs_are_the_strips_sends_and_routes_busses_destinations_and_matrix_feeds():
    plan = {
        "channels": [{"channel": 3, "bank": "aux", "bus_sends": [{"bus": "Fx"}, {"bus": "Nope"}],
                      "main_routes": [{"index": 2}]}, {"channel": 1}],
        "busses": {"Fx": {"index": 4, "destination": {"type": "main"}},
                   "Out": {"index": 5, "destination": {"type": "dedicated_output"}}},
        "outputs": {"Delay": {"kind": "matrix", "index": 1,
                              "fed_by": {"type": "bus", "name": "Fx"}},
                    "Fill": {"kind": "matrix", "index": 2, "fed_by": {"type": "main", "index": 1}},
                    "Main": {"kind": "main", "index": 1}},
    }
    assert planned_routing_legs(plan) == {
        ("/aux/3", "bus:4"), ("/aux/3", "main:2"), ("bus:4", "main:1"),
        ("bus:4", "mtx:1"), ("main:1", "mtx:2")}


# --------------------------------------------------------------------------
# Watch, and the cost
# --------------------------------------------------------------------------


def test_watch_runs_both_rules_from_the_default_set_and_binds_them_to_the_plan(tmp_path):
    assert {"R012", "R013"} <= {r.id for r in DEFAULT_RULES}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_parallel_plan()), encoding="utf-8")
    rules = with_plan_rules(DEFAULT_RULES, plan_path)
    state = _parallel_state()
    findings = [f for rule in rules for f in rule.check(state) if rule.id in ("R012", "R013")]
    assert [f.rule_id for f in findings] == ["R013"]


def test_binding_to_a_plan_leaves_every_other_rule_as_it_was():
    bound = split_path_rules(DEFAULT_RULES, _parallel_plan())
    assert [r.id for r in bound] == [r.id for r in DEFAULT_RULES]
    assert all(a is b for a, b in zip(bound, DEFAULT_RULES)
               if a.id not in ("R012", "R013", "R014"))


def test_a_full_desk_of_48_strips_by_16_busses_costs_well_under_a_second():
    parts = [_main(1), _main(2)]
    for b in range(1, 17):
        parts.append(_bus(b, f"Bus {b}", mains=(1, 2), matrices=(1, 2)))
    for n in range(1, 41):
        legs = {f"bus{b}": 1 for b in range(1, 17)}
        parts.append(_strip(f"/ch/{n}", f"Ch {n}", main1=1, **legs))
    for n in range(1, 9):
        parts.append(_strip(f"/aux/{n}", f"Aux {n}", main1=1, bus1=1, bus2=1))
    state = _state(*parts)
    start = time.perf_counter()
    findings = _split(state)
    elapsed = time.perf_counter() - start
    assert len(findings) >= 48
    assert elapsed < 1.0


# --------------------------------------------------------------------------
# A plan rebuilt under a running Watch is noticed
# --------------------------------------------------------------------------


def test_a_plan_changed_on_disk_after_start_is_said_at_info_and_a_touch_is_not(tmp_path):
    import os

    from atoo.watch import PLAN_CHANGED_RULE_ID, plan_changed_watcher

    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_parallel_plan(with_comp_destination=False)), encoding="utf-8")
    notes = plan_changed_watcher(path)
    assert notes() == []
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert notes() == []
    path.write_text(json.dumps(_parallel_plan()), encoding="utf-8")
    [note] = notes()
    assert note.rule_id == PLAN_CHANGED_RULE_ID and note.severity is Severity.INFO
    assert "Stop Watch and start it again" in note.message
    assert len(notes()) == 1


def test_a_plan_that_is_deleted_or_appears_after_start_is_said_too(tmp_path):
    from atoo.watch import plan_changed_watcher

    path = tmp_path / "plan.json"
    absent = plan_changed_watcher(path)
    assert absent() == []
    path.write_text("{}", encoding="utf-8")
    assert len(absent()) == 1
    present = plan_changed_watcher(path)
    assert present() == []
    path.unlink()
    assert len(present()) == 1


def test_watch_carries_the_plan_changed_note_every_pass_from_the_session_notes(tmp_path):
    from atoo.watch import PLAN_CHANGED_RULE_ID, plan_changed_watcher, watch

    path = tmp_path / "plan.json"
    path.write_text("{}", encoding="utf-8")
    notes = plan_changed_watcher(path)
    cycle = iter(range(3))

    def provider():
        if next(cycle) == 1:
            path.write_text('{"changed": true}', encoding="utf-8")
        return _parallel_state()

    events = list(watch(provider, rules=list(DEFAULT_RULES), max_iterations=3,
                        sleep=lambda _s: None, session_notes=notes))
    seen = [any(f.rule_id == PLAN_CHANGED_RULE_ID for f in e.all_findings) for e in events]
    assert seen == [False, True, True]
    assert [f.rule_id for f in events[1].new_findings].count(PLAN_CHANGED_RULE_ID) == 1


def test_the_watch_page_session_carries_the_note_once_started_against_a_plan(tmp_path):
    from atoo.watch import PLAN_CHANGED_RULE_ID, plan_changed_watcher
    from atoo.webui import WatchSession

    path = tmp_path / "plan.json"
    path.write_text("{}", encoding="utf-8")
    session = WatchSession()
    assert session._session_notes() == []
    session._plan_changed = plan_changed_watcher(path)
    assert session._session_notes() == []
    path.write_text('{"rebuilt": true}', encoding="utf-8")
    assert [n.rule_id for n in session._session_notes()] == [PLAN_CHANGED_RULE_ID]
    session._halt()
    assert session._session_notes() == []
