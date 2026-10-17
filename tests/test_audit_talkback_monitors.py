"""CV021 (talkback misses a monitor mix the plan builds) and CV022 (which
busses it took for monitor mixes), in `audit --plan` and in Watch.

T001 says talkback reaches nobody. Nothing said talkback reaches some mixes and
not the one a musician listens to. A desk read cannot say which busses are
monitor mixes, so the plan does: a bus it feeds to an output socket and to no
Main, unless every send it lists into the bus is post-fader.

The desks and plans are built here; the capture tests use frozen captures and a
frozen plan, never a show bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.audit import (
    DEFAULT_RULES, ConsoleState, Severity, console_read_plan, diff_against_plan,
    planned_monitor_busses, run_audit, talkback_monitor_findings, talkback_monitor_rule,
    talkback_monitors_note_findings, talkback_monitors_note_rule, with_plan_rules,
)
from atoo import console_facts
from atoo.cli import main
from atoo.watch import watch
from atoo.watch_scope import PLAN_RULE_IDS, RULE_ADDRESS_PATTERNS
from tests.snap_desk import snap_values

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURES = sorted(FIXTURES.rglob("*.snap"))


def _bus(index, *, main=False, socket=None):
    destination = ({"type": "main", "index": 1} if main
                   else {"type": "dedicated_output", "label": f"B{index}",
                         "patch": {"group": "LCL", "sockets": [socket or index], "stated": True}})
    return {"index": index, "destination": destination, "mono": True}


def _send(bus, mode):
    return {"bus": bus, "mode": mode, "level_db": 0.0}


def _plan(**busses) -> dict:
    return {
        "busses": {
            "Drummer": _bus(1), "Keys": _bus(2), "Guitar": _bus(3),
            "Drums": _bus(5, main=True),
            **busses,
        },
        "channels": [{"bank": "ch", "channel": 1, "name": "Kick", "bus_sends": [
            _send("Drummer", "pre"), _send("Keys", None), _send("Drums", "post")]}],
        "dcas": {}, "mute_groups": {}, "outputs": {},
    }


PLAN = _plan()


def _desk(a=(1, 2, 3), b=(), assign="CH40", **changes) -> ConsoleState:
    """A desk with talkback assigned to CH40 and TALK A routed to busses `a`,
    TALK B to busses `b`; every other destination off."""
    v: dict[str, object] = {console_facts.TALK_ASSIGN: assign,
                            "/bus/1/name": "Drummer", "/bus/2/name": "Keys",
                            "/bus/3/name": "Guitar"}
    for button, routed in (("A", a), ("B", b)):
        for dest in console_facts.TALK_DESTINATIONS:
            v[console_facts.talk_destination(button, dest)] = 0
        for n in routed:
            v[console_facts.talk_destination(button, f"B{n}")] = 1
    v.update(changes)
    return ConsoleState(v)


def _without(state: ConsoleState, *addresses) -> ConsoleState:
    return ConsoleState({k: v for k, v in state.values.items() if k not in addresses})


def _cv021(state, plan=PLAN):
    return talkback_monitor_findings(state, plan)


# --------------------------------------------------------------------------
# Which busses are monitor mixes
# --------------------------------------------------------------------------


def test_the_plans_monitor_mixes_are_the_busses_it_feeds_to_an_output_and_no_main():
    assert planned_monitor_busses(PLAN) == [("Drummer", 1), ("Keys", 2), ("Guitar", 3)]


def test_a_bus_on_its_own_output_fed_only_post_fader_is_not_a_monitor_mix():
    plan = _plan(Sub=_bus(4))
    plan["channels"][0]["bus_sends"].append(_send("Sub", "post"))
    assert ("Sub", 4) not in planned_monitor_busses(plan)
    plan["channels"][0]["bus_sends"].append(_send("Sub", "group"))
    assert ("Sub", 4) not in planned_monitor_busses(plan)


def test_one_pre_fader_send_makes_a_bus_a_monitor_mix():
    plan = _plan(Fill=_bus(4))
    plan["channels"][0]["bus_sends"] += [_send("Fill", "post"), _send("Fill", "pre")]
    assert ("Fill", 4) in planned_monitor_busses(plan)


def test_a_bus_with_no_planned_send_is_a_monitor_mix_the_plan_builds():
    assert ("Guitar", 3) in planned_monitor_busses(PLAN)


def test_a_bus_that_reaches_a_main_as_well_as_an_output_is_not_a_monitor_mix():
    plan = _plan()
    plan["busses"]["Guitar"]["destinations"] = [
        plan["busses"]["Guitar"]["destination"], {"type": "main", "index": 1}]
    assert ("Guitar", 3) not in planned_monitor_busses(plan)


def test_a_bus_talkback_has_no_destination_for_is_not_checked():
    assert planned_monitor_busses(_plan(Far=_bus(17))) == planned_monitor_busses(PLAN)


def test_a_name_is_never_what_makes_a_bus_a_monitor_mix():
    plan = _plan()
    plan["busses"]["Drums"] = {**plan["busses"]["Drums"], "index": 5}
    plan["busses"]["Monitor Fake"] = _bus(6, main=True)
    assert "Monitor Fake" not in {name for name, _ in planned_monitor_busses(plan)}


# --------------------------------------------------------------------------
# Firing
# --------------------------------------------------------------------------


def test_a_desk_with_talkback_on_every_monitor_mix_raises_nothing():
    assert _cv021(_desk()) == []
    assert [f for f in diff_against_plan(_desk(), PLAN) if f.rule_id == "CV021"] == []


def test_a_monitor_mix_talkback_misses_is_a_warning_naming_the_bus_and_the_switches():
    [finding] = _cv021(_desk(a=(1, 3)))
    assert (finding.rule_id, finding.severity) == ("CV021", Severity.WARNING)
    assert finding.message == (
        'Talkback is assigned to CH40 and reaches other mixes, but not BUS 2 "Keys", a monitor '
        "mix the plan builds: neither TALK A nor TALK B is routed to it, so whoever listens to "
        "that mix cannot hear you. Switch B2 on in TALK A's (or TALK B's) destinations on the "
        "desk's talkback page.")
    assert finding.addresses == ("/cfg/talk/A/B2", "/cfg/talk/B/B2")


def test_each_missing_mix_is_its_own_finding():
    findings = _cv021(_desk(a=(1,)))
    assert [f.addresses[0] for f in findings] == ["/cfg/talk/A/B2", "/cfg/talk/A/B3"]
    assert 'BUS 2 "Keys"' in findings[0].message and 'BUS 3 "Guitar"' in findings[1].message


def test_either_button_reaching_a_mix_is_enough():
    assert _cv021(_desk(a=(1,), b=(2, 3))) == []


def test_the_label_is_the_name_the_desk_shows_else_the_plans():
    state = _desk(a=(1, 3), **{"/bus/2/name": "Keys Wedge"})
    assert 'BUS 2 "Keys Wedge"' in _cv021(state)[0].message
    state = _without(_desk(a=(1, 3)), "/bus/2/name")
    assert 'BUS 2 "Keys"' in _cv021(state)[0].message


# --------------------------------------------------------------------------
# CV022: the inference is announced
# --------------------------------------------------------------------------


def test_cv022_says_which_busses_were_taken_and_how_many_talkback_reaches():
    [note] = talkback_monitors_note_findings(_desk(a=(1, 3)), PLAN)
    assert (note.rule_id, note.severity) == ("CV022", Severity.INFO)
    assert note.message == (
        'Talkback reaches 2 of the 3 monitor mixes the plan builds: BUS 1 "Drummer", BUS 2 '
        '"Keys", BUS 3 "Guitar". A bus is taken for a monitor mix when the plan feeds it to an '
        "output socket and to no Main, and does not send into it post-fader only; a mix the "
        "plan builds another way is not checked.")
    assert note.addresses == (console_facts.TALK_ASSIGN,)


def test_cv022_is_said_when_talkback_reaches_every_mix_too():
    [note] = talkback_monitors_note_findings(_desk(), PLAN)
    assert note.message.startswith("Talkback reaches 3 of the 3 monitor mixes")
    assert _cv021(_desk()) == []


def test_audit_with_a_plan_reports_both_beside_the_other_comparisons():
    findings = diff_against_plan(_desk(a=(1, 3)), PLAN)
    assert [f.rule_id for f in findings if f.rule_id in {"CV021", "CV022"}] == ["CV021", "CV022"]


# --------------------------------------------------------------------------
# Silent
# --------------------------------------------------------------------------


def test_silent_when_talkback_is_off():
    state = _desk(a=(), assign="OFF")
    assert _cv021(state) == [] and talkback_monitors_note_findings(state, PLAN) == []


def test_silent_when_the_assignment_was_not_read():
    state = _without(_desk(a=(1,)), console_facts.TALK_ASSIGN)
    assert _cv021(state) == [] and talkback_monitors_note_findings(state, PLAN) == []


def test_silent_when_the_plan_builds_no_monitor_mix():
    plan = {"busses": {"Drums": _bus(5, main=True)}, "channels": []}
    assert _cv021(_desk(a=(1,)), plan) == []
    assert talkback_monitors_note_findings(_desk(a=(1,)), plan) == []
    assert talkback_monitor_rule(plan) is None and talkback_monitors_note_rule(plan) is None
    assert talkback_monitor_rule({}) is None


def test_silent_for_a_bus_whose_switches_were_not_read_and_neither_is_on():
    state = _without(_desk(a=(1, 3)), "/cfg/talk/A/B2")
    assert _cv021(state) == []
    state = _without(_desk(a=(1, 3)), "/cfg/talk/A/B2", "/cfg/talk/B/B2")
    assert _cv021(state) == []
    assert 'BUS 1 "Drummer"' in talkback_monitors_note_findings(state, PLAN)[0].message
    assert 'BUS 2' not in talkback_monitors_note_findings(state, PLAN)[0].message


def test_a_switch_that_is_on_settles_a_bus_whose_other_switch_was_not_read():
    state = _without(_desk(a=(1, 2, 3)), "/cfg/talk/B/B2")
    assert _cv021(state) == []


def test_silent_and_t001s_when_talkback_reaches_nowhere_at_all():
    """All 56 switches read, none on: T001 says it once, not one row per mix."""
    state = _desk(a=())
    assert _cv021(state) == [] and talkback_monitors_note_findings(state, PLAN) == []
    t001 = next(r for r in DEFAULT_RULES if r.id == "T001").check(state)
    assert [f.rule_id for f in t001] == ["T001"]


def test_cv021_takes_over_the_moment_one_destination_is_on_and_t001_is_quiet():
    state = _desk(a=(), **{"/cfg/talk/A/M1": 1})
    assert [f.addresses[0] for f in _cv021(state)] == [
        "/cfg/talk/A/B1", "/cfg/talk/A/B2", "/cfg/talk/A/B3"]
    assert next(r for r in DEFAULT_RULES if r.id == "T001").check(state) == []


def test_silent_for_a_bus_the_plan_does_not_build():
    plan = {"busses": {"Drummer": _bus(1)}, "channels": []}
    assert _cv021(_desk(a=(1,)), plan) == []


# --------------------------------------------------------------------------
# audit --plan and Watch
# --------------------------------------------------------------------------


def test_audit_plan_on_the_command_line_names_the_missing_mix(tmp_path, capsys):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(PLAN), encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(_desk(a=(1, 3)).values), encoding="utf-8")
    main(["audit", "--state", str(state_path), "--plan", str(plan_path)])
    out = capsys.readouterr().out
    assert "[WARNING] CV021 Talkback Misses A Monitor Mix" in out
    assert 'not BUS 2 "Keys"' in out
    assert "[INFO] CV022 Monitor Mixes Talkback Was Checked Against" in out


def test_without_a_plan_the_audit_does_not_say_it(tmp_path, capsys):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(_desk(a=(1, 3)).values), encoding="utf-8")
    main(["audit", "--state", str(state_path)])
    out = capsys.readouterr().out
    assert "CV021" not in out and "CV022" not in out


def _watch_rules(tmp_path, plan=PLAN):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return with_plan_rules(DEFAULT_RULES, path)


def test_watch_binds_both_rules_from_a_plan_that_builds_a_monitor_mix(tmp_path):
    ids = {r.id for r in _watch_rules(tmp_path)}
    assert {"CV021", "CV022"} <= ids
    ids = {r.id for r in _watch_rules(tmp_path, {"busses": {}, "channels": []})}
    assert not {"CV021", "CV022"} & ids


def test_watch_raises_a_mix_talkback_loses_and_clears_it(tmp_path):
    """The sequence on the Watch page: talkback reaches every mix, B2 is switched
    off, then put back."""
    rules = _watch_rules(tmp_path)
    states = iter([_desk(), _desk(a=(1, 3)), _desk(a=(1, 3)), _desk()])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=4,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings if f.severity == Severity.WARNING] == ["CV021"]
    assert events[2].new_findings == []
    assert [f.rule_id for f in events[3].cleared_findings if f.severity == Severity.WARNING] == ["CV021"]


def test_watch_stays_quiet_when_talkback_is_turned_off(tmp_path):
    rules = _watch_rules(tmp_path)
    states = iter([_desk(a=(1, 3)), _desk(a=(), assign="OFF")])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=2,
                        sleep=lambda _s: None))
    assert {f.rule_id for f in events[1].cleared_findings} == {"CV021", "CV022"}
    assert not {f.rule_id for f in events[1].all_findings} & {"CV021", "CV022", "T001"}


# --------------------------------------------------------------------------
# The cost: no address is added
# --------------------------------------------------------------------------


def test_the_read_plan_is_unchanged_and_watch_reads_only_what_t001_and_the_names_read():
    assert {"CV021", "CV022"} <= set(PLAN_RULE_IDS)
    for rule_id in ("CV021", "CV022"):
        assert set(RULE_ADDRESS_PATTERNS[rule_id]) <= (
            set(RULE_ADDRESS_PATTERNS["T001"]) | set(RULE_ADDRESS_PATTERNS["N002"]))
    plan = console_read_plan()
    assert len(plan) == len({a for a, _ in plan})
    assert (console_facts.TALK_ASSIGN, "s") in plan


# --------------------------------------------------------------------------
# The frozen captures
# --------------------------------------------------------------------------

#: A frozen plan with six monitor mixes on busses 1-6.
FROZEN_PLAN = json.loads((FIXTURES / "sixpiece_2026-10-11.plan.json").read_text(encoding="utf-8"))


def _routed(values, missing=()):
    """The capture with talkback assigned and TALK A on every bus but `missing`
    (TALK B routed nowhere)."""
    values = dict(values)
    values[console_facts.TALK_ASSIGN] = "CH40"
    for dest in console_facts.TALK_DESTINATIONS:
        values[console_facts.talk_destination("B", dest)] = 0
    for n in range(1, 17):
        values[console_facts.talk_destination("A", f"B{n}")] = 0 if n in missing else 1
    return ConsoleState(values)


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_no_capture_raises_either_rule_as_it_stands(capture):
    """Seven captures, none with talkback assigned (the factory setting):
    0 findings of either rule on each."""
    state = ConsoleState(snap_values(capture))
    assert _cv021(state, FROZEN_PLAN) == []
    assert talkback_monitors_note_findings(state, FROZEN_PLAN) == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_a_capture_with_talkback_on_every_mix_is_healthy(capture):
    state = _routed(snap_values(capture))
    assert _cv021(state, FROZEN_PLAN) == []
    run = run_audit(state, [r for r in DEFAULT_RULES if r.id == "T001"])
    assert run == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_a_capture_with_one_mix_left_out_raises_exactly_that_mix(capture):
    state = _routed(snap_values(capture), missing=(4,))
    [finding] = _cv021(state, FROZEN_PLAN)
    assert finding.addresses == ("/cfg/talk/A/B4", "/cfg/talk/B/B4")
    assert finding.message.startswith("Talkback is assigned to CH40 and reaches other mixes, "
                                      "but not BUS 4 ")
