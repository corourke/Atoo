"""R008 (Strip Reaches Nothing) and C006 (Strip In Use Has No Source): the
two ends of a strip's path.

R002, R005 and R006 start at a bus, a Main or a Matrix. These start at the
channel or aux: does anything reach it (C006), and does its signal go
anywhere (R008). Every desk here is built in the test; nothing reads a
show bundle.
"""

from __future__ import annotations

import json

import pytest

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    RuleScope,
    apply_plan_scope,
    plan_watch_rules,
    run_audit,
    with_plan_rules,
)
from atoo.diagnostics import Severity
from atoo.watch import watch

BUSES = (1, 2, 3)
MATRICES = (1, 2)
MAINS = (1, 2)


def _desk(**extra) -> dict[str, object]:
    """A small desk with nothing set: three busses, two Mains and two
    Matrices; Bus 1 and Main 1 are patched to a local output, so they
    reach an output."""
    v: dict[str, object] = {}
    for b in BUSES:
        v[f"/bus/{b}/name"], v[f"/bus/{b}/mute"], v[f"/bus/{b}/fdr"] = "", 0, 0.0
        for m in MAINS:
            v[f"/bus/{b}/main/{m}/on"] = 0
    for m in MAINS:
        v[f"/main/{m}/mute"], v[f"/main/{m}/fdr"] = 0, 0.0
    for x in MATRICES:
        v[f"/mtx/{x}/mute"], v[f"/mtx/{x}/fdr"] = 0, 0.0
    v["/io/out/LCL/1/grp"], v["/io/out/LCL/1/in"] = "BUS", 1      # Bus 1, L slot
    v["/io/out/LCL/2/grp"], v["/io/out/LCL/2/in"] = "MAIN", 1     # Main 1, L slot
    v["/cfg/mon/1/src"], v["/cfg/mon/2/src"] = "OFF", "OFF"
    v.update(extra)
    return v


def _strip(v: dict, base: str, *, name: str = "", patch=("LCL", 30), mute: int = 0,
           fdr: float = 0.0, sends=(), matrices=(), mains=()) -> dict:
    """One strip with every send and route read and off, then the ones
    asked for switched on."""
    v[f"{base}/name"], v[f"{base}/mute"], v[f"{base}/fdr"] = name, mute, fdr
    v[f"{base}/in/conn/grp"] = patch[0] if patch else "OFF"
    v[f"{base}/in/conn/in"] = patch[1] if patch else 0
    v[f"{base}/in/set/altsrc"], v[f"{base}/in/conn/altgrp"] = 0, "OFF"
    for b in BUSES:
        v[f"{base}/send/{b}/on"] = 1 if b in sends else 0
    for x in MATRICES:
        v[f"{base}/send/MX{x}/on"] = 1 if x in matrices else 0
    for m in MAINS:
        v[f"{base}/main/{m}/on"] = 1 if m in mains else 0
    return v


def _state(values: dict) -> ConsoleState:
    return ConsoleState(values, console_model="wing-compact")


def _found(values: dict, rule_id: str, rules=None) -> list:
    return [f for f in run_audit(_state(values), rules) if f.rule_id == rule_id]


def _rule(rule_id: str):
    return next(r for r in DEFAULT_RULES if r.id == rule_id)


# --------------------------------------------------------------------------
# The rows
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rule_id,category", [("R008", "routing"), ("C006", "configuration")])
def test_the_rules_are_warnings_about_any_strip(rule_id, category):
    rule = _rule(rule_id)
    assert rule.severity is Severity.WARNING
    assert rule.category == category
    assert rule.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# R008: a strip whose switches send it nowhere
# --------------------------------------------------------------------------


def test_a_named_unmuted_strip_with_nothing_switched_on_reaches_nothing():
    v = _strip(_desk(), "/ch/7", name="Kick")
    [f] = _found(v, "R008")
    assert f.severity is Severity.WARNING
    assert f.category == "routing"
    assert 'CH 7 "Kick"' in f.message
    assert "no bus send" in f.message and "no Matrix send" in f.message
    assert "no Main route" in f.message
    # It cites every switch it looked at, so a second strip is a second
    # finding and a change to any one of them is a change to this one.
    assert set(f.addresses) == {
        *(f"/ch/7/send/{b}/on" for b in BUSES),
        *(f"/ch/7/send/MX{x}/on" for x in MATRICES),
        *(f"/ch/7/main/{m}/on" for m in MAINS),
    }


def test_an_aux_is_judged_the_same_way():
    v = _strip(_desk(), "/aux/3", name="Click")
    [f] = _found(v, "R008")
    assert 'AUX 3 "Click"' in f.message


def test_a_strip_in_use_only_by_its_patch_is_reported():
    """No name, nothing sending, but patched to something the factory did
    not: it is in use, and it goes nowhere."""
    v = _strip(_desk(), "/ch/30", name="", patch=("A", 4))
    [f] = _found(v, "R008")
    assert f.message.startswith("CH 30 is in use")


def test_each_strip_is_one_finding():
    v = _desk()
    _strip(v, "/ch/1", name="Kick")
    _strip(v, "/ch/2", name="Snare")
    _strip(v, "/ch/3", name="Hat", sends=(1,))
    findings = _found(v, "R008")
    assert sorted(f.addresses[0] for f in findings) == ["/ch/1/send/1/on", "/ch/2/send/1/on"]


@pytest.mark.parametrize("switch", [
    {"sends": (2,)}, {"matrices": (1,)}, {"mains": (2,)}, {"mains": (1,)},
])
def test_any_one_send_or_route_on_is_a_path(switch):
    v = _strip(_desk(), "/ch/7", name="Kick", **switch)
    assert _found(v, "R008") == []


def test_a_strip_that_feeds_a_bus_going_nowhere_is_the_busses_finding_not_its_own():
    """Bus 2 is in use and reaches no output: R002 says so, once. The
    strip feeding it is not repeated."""
    v = _strip(_desk(), "/ch/7", name="Kick", sends=(2,))
    assert [f.rule_id for f in run_audit(_state(v)) if f.rule_id in ("R002", "R008")] == ["R002"]


def test_a_strip_that_feeds_a_main_going_nowhere_is_the_mains_finding_not_its_own():
    v = _desk()
    v["/io/out/LCL/2/grp"] = "OFF"          # Main 1 loses its output
    _strip(v, "/ch/7", name="Kick", mains=(1,))
    ids = [f.rule_id for f in run_audit(_state(v))]
    assert "R005" in ids and "R008" not in ids


def test_a_strip_that_feeds_a_good_bus_is_quiet():
    v = _strip(_desk(), "/ch/7", name="Kick", sends=(1,))
    assert "R008" not in [f.rule_id for f in run_audit(_state(v))]


def test_the_verdict_does_not_need_the_output_patch():
    """The finding is about the strip's own switches, so a read that never
    asked for the output sockets still has standing to make it (unlike
    R002, which stands down)."""
    v = {a: x for a, x in _strip(_desk(), "/ch/7", name="Kick").items()
         if not a.startswith("/io/out/")}
    assert len(_found(v, "R008")) == 1


# -- what belongs to another rule or to a decision ---------------------------


def test_a_muted_strip_is_silent_on_purpose():
    v = _strip(_desk(), "/ch/7", name="Kick", mute=1)
    assert _found(v, "R008") == []


def test_a_strip_at_the_floor_is_l002s_finding():
    v = _strip(_desk(), "/ch/7", name="Kick", fdr=-144.0)
    ids = [f.rule_id for f in run_audit(_state(v))]
    assert "R008" not in ids
    assert "L002" in ids


def test_a_strip_that_is_not_in_use_is_not_judged():
    """Unnamed, unpatched, nothing sending: a spare strip."""
    v = _strip(_desk(), "/ch/7", name="", patch=None)
    assert _found(v, "R008") == []


def test_the_factory_patch_alone_does_not_make_a_strip_in_use():
    v = _strip(_desk(), "/ch/7", name="", patch=("LCL", 7))
    assert _found(v, "R008") == []


def test_the_talkback_strip_is_exempt_and_t002_says_so():
    v = _strip(_desk(), "/ch/40", name="Talk Mic", patch=None)
    v[console_facts.TALK_ASSIGN] = "CH40"
    ids = [f.rule_id for f in run_audit(_state(v))]
    assert "R008" not in ids and "C006" not in ids
    [t002] = _found(v, "T002")
    assert "R008" in t002.message and "C006" in t002.message


def test_an_aux_a_monitor_output_listens_to_is_heard():
    v = _strip(_desk(), "/aux/3", name="Cue")
    v["/cfg/mon/2/src"] = "AUX.3"
    assert _found(v, "R008") == []
    v["/cfg/mon/2/src"] = "AUX.4"       # another aux: this one still goes nowhere
    assert len(_found(v, "R008")) == 1


# -- silent when unread ------------------------------------------------------


def _without(values: dict, *addresses) -> dict:
    return {a: x for a, x in values.items() if a not in addresses}


@pytest.mark.parametrize("missing", [
    "/ch/7/send/3/on", "/ch/7/send/MX2/on", "/ch/7/main/2/on",
])
def test_one_switch_never_read_is_not_a_clean_answer(missing):
    v = _strip(_desk(), "/ch/7", name="Kick")
    assert len(_found(v, "R008")) == 1
    assert _found(_without(v, missing), "R008") == []


@pytest.mark.parametrize("kind", ["bus", "main", "mtx"])
def test_a_state_that_holds_none_of_a_kind_is_silent(kind):
    """Without a single Main in the reading, "no Main route is on" is a
    claim about switches nobody asked for."""
    v = _strip(_desk(), "/ch/7", name="Kick")
    if kind == "bus":
        keep = {a: x for a, x in v.items()
                if not a.startswith("/bus/") and "/send/" not in a.replace("/send/MX", "")}
    elif kind == "main":
        keep = {a: x for a, x in v.items()
                if not a.startswith("/main/") and "/main/" not in a}
    else:
        keep = {a: x for a, x in v.items()
                if not a.startswith("/mtx/") and "/send/MX" not in a}
    assert _found(keep, "R008") == []


def test_a_bus_the_desk_has_but_the_strip_was_not_asked_about_is_unread():
    v = _strip(_desk(), "/ch/7", name="Kick")
    v["/bus/4/name"] = ""           # the desk has a fourth bus; the strip's send to it was never read
    assert _found(v, "R008") == []


# -- plan --------------------------------------------------------------------

PLAN = {
    "channels": [
        {"bank": "ch", "channel": 1, "name": "Kick", "fader": {},
         "bus_sends": [{"bus": "Drums", "level_db": -3.0}], "main_routes": []},
    ],
    "busses": {"Drums": {"index": 1}},
}


def _planned_desk() -> dict:
    v = _desk()
    v["/bus/1/name"] = "Drums"
    _strip(v, "/ch/1", name="Kick")      # the plan routes it; every route is off
    _strip(v, "/ch/2", name="Snare")     # the plan does not mention it; also off
    return v


def test_under_a_plan_the_planned_strip_is_cv016s_and_the_other_is_still_r008s():
    state = _state(_planned_desk())
    findings = run_audit(state, plan=PLAN)
    reached = [f.message for f in findings if f.rule_id == "R008"]
    assert len(reached) == 1 and "CH 2" in reached[0]
    scoped = apply_plan_scope(state, run_audit(state), PLAN)
    assert [w.finding.addresses[0] for w in scoped.withheld if w.finding.rule_id == "R008"] == [
        "/ch/1/send/1/on"]


def test_watch_binds_the_rule_to_the_plan_the_same_way(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(PLAN), encoding="utf-8")
    rules = with_plan_rules(list(DEFAULT_RULES), plan_path)
    findings = run_audit(_state(_planned_desk()), rules)
    [reached] = [f for f in findings if f.rule_id == "R008"]
    assert "CH 2" in reached.message
    assert "CV016" in {r.id for r in plan_watch_rules(plan_path)}
    assert "CV016" in {f.rule_id for f in findings}


def test_watch_without_a_plan_keeps_the_stock_rule():
    findings = run_audit(_state(_planned_desk()), list(DEFAULT_RULES))
    assert len([f for f in findings if f.rule_id == "R008"]) == 2


# -- Watch -------------------------------------------------------------------


def _watch(states: list[dict]):
    feed = iter(_state(s) for s in states)
    return list(watch(lambda: next(feed), rules=list(DEFAULT_RULES), interval=0,
                      max_iterations=len(states), sleep=lambda _s: None))


def test_watch_raises_a_strip_cut_off_and_clears_it_when_it_is_sent_again():
    on = _strip(_desk(), "/ch/7", name="Kick", sends=(1,))
    off = _strip(_desk(), "/ch/7", name="Kick")
    events = _watch([on, off, on])
    assert "R008" not in [f.rule_id for f in events[0].all_findings]
    assert [f.rule_id for f in events[1].new_findings] == ["R008"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["R008"]


def test_watch_does_not_raise_a_strip_that_was_cut_off_while_muted():
    on = _strip(_desk(), "/ch/7", name="Kick", sends=(1,))
    off_muted = _strip(_desk(), "/ch/7", name="Kick", mute=1)
    events = _watch([on, off_muted])
    assert events[1].new_findings == []


# --------------------------------------------------------------------------
# C006: a strip in use that nothing is patched to
# --------------------------------------------------------------------------


def test_a_named_strip_with_nothing_patched_has_no_source():
    v = _strip(_desk(), "/ch/7", name="Kick", patch=None, sends=(1,))
    [f] = _found(v, "C006")
    assert f.severity is Severity.WARNING
    assert f.category == "configuration"
    assert 'CH 7 "Kick" is in use (named) but nothing is patched to it' in f.message
    assert f.addresses == ("/ch/7/in/conn/grp",)


def test_an_unnamed_strip_is_in_use_when_it_sends_somewhere_other_than_main_1():
    v = _strip(_desk(), "/ch/7", name="", patch=None, sends=(1,))
    [f] = _found(v, "C006")
    assert "(sending somewhere)" in f.message


def test_the_main_1_route_every_strip_ships_with_is_not_use():
    v = _strip(_desk(), "/ch/7", name="", patch=None, mains=(1,))
    assert _found(v, "C006") == []


def test_a_strip_that_is_not_in_use_has_nothing_to_be_missing():
    v = _strip(_desk(), "/ch/7", name="", patch=None)
    assert _found(v, "C006") == []


def test_a_patched_strip_has_a_source():
    v = _strip(_desk(), "/ch/7", name="Kick", patch=("A", 3))
    assert _found(v, "C006") == []


def test_a_strip_whose_patch_was_never_read_is_silent():
    v = _strip(_desk(), "/ch/7", name="Kick", patch=None)
    assert len(_found(v, "C006")) == 1
    assert _found(_without(v, "/ch/7/in/conn/grp"), "C006") == []


def test_a_muted_strip_or_one_at_the_floor_still_has_no_source():
    """A show built from conventions starts every fader at the floor; a
    patch lost before the faders come up is the fault this catches."""
    muted = _strip(_desk(), "/ch/7", name="Kick", patch=None, mute=1)
    down = _strip(_desk(), "/ch/7", name="Kick", patch=None, fdr=-144.0)
    assert len(_found(muted, "C006")) == 1
    assert len(_found(down, "C006")) == 1


def test_an_aux_is_judged_too():
    v = _strip(_desk(), "/aux/3", name="Click", patch=None)
    [f] = _found(v, "C006")
    assert 'AUX 3 "Click"' in f.message


def test_a_strip_on_its_alternate_input_is_c004s_to_report():
    v = _strip(_desk(), "/ch/7", name="Kick", patch=None)
    v["/ch/7/in/set/altsrc"] = 1            # on the alternate, which is OFF
    ids = [f.rule_id for f in run_audit(_state(v))]
    assert "C004" in ids and "C006" not in ids


def test_the_engaged_global_switch_hands_a_strip_with_an_alternate_to_c005():
    v = _strip(_desk(), "/ch/7", name="Kick", patch=None)
    v["/ch/7/in/conn/altgrp"] = "CRD"
    v[console_facts.GLOBAL_ALT_SWITCH] = 1
    ids = [f.rule_id for f in run_audit(_state(v))]
    assert "C005" in ids and "C006" not in ids
    # ... but a strip with no alternate has nowhere else to be listening.
    v["/ch/7/in/conn/altgrp"] = "OFF"
    assert len(_found(v, "C006")) == 1


def test_under_a_plan_that_states_the_patch_cv005_judges_it():
    plan = {"channels": [{"bank": "ch", "channel": 7, "name": "Kick", "fader": {},
                          "patch": {"group": "LCL", "sockets": [7]}}], "busses": {}}
    v = _strip(_desk(), "/ch/7", name="Kick", patch=None, sends=(1,))
    v.update(_strip({}, "/ch/8", name="Snare", patch=None, sends=(1,)))
    state = _state(v)
    scoped = apply_plan_scope(state, run_audit(state), plan)
    assert [f.addresses[0] for f in scoped.findings if f.rule_id == "C006"] == [
        "/ch/8/in/conn/grp"]
    assert [w.finding.addresses[0] for w in scoped.withheld if w.finding.rule_id == "C006"] == [
        "/ch/7/in/conn/grp"]


def test_watch_raises_a_strip_that_loses_its_patch_and_clears_it_when_repatched():
    patched = _strip(_desk(), "/ch/7", name="Kick", sends=(1,))
    unpatched = _strip(_desk(), "/ch/7", name="Kick", patch=None, sends=(1,))
    events = _watch([patched, unpatched, patched])
    assert "C006" not in [f.rule_id for f in events[0].all_findings]
    assert [f.rule_id for f in events[1].new_findings] == ["C006"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["C006"]


# --------------------------------------------------------------------------
# A desk nobody has touched says nothing
# --------------------------------------------------------------------------


def test_a_factory_desk_has_no_strip_reaching_nothing_or_without_a_source():
    """Every strip ships routed to Main 1; strips past the panel's own
    inputs ship unpatched and unused."""
    v = _desk()
    for n in range(1, 25):
        _strip(v, f"/ch/{n}", name="", patch=("LCL", n), mains=(1,))
    for n in range(25, 41):
        _strip(v, f"/ch/{n}", name="", patch=None, mains=(1,))
    ids = {f.rule_id for f in run_audit(_state(v))}
    assert not ids & {"R008", "C006"}


# --------------------------------------------------------------------------
# ... and real desks
# --------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from tests.snap_desk import snap_values  # noqa: E402

CAPTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.snap"))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_no_frozen_capture_has_a_strip_that_goes_nowhere(capture):
    """Four of these are desks somebody had set up (a church's full-size
    among them); none has a strip in use, unmuted and up, that goes
    nowhere."""
    assert _rule("R008").check(ConsoleState(snap_values(capture))) == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_the_only_strip_without_a_source_on_a_frozen_capture_is_a_named_placeholder(capture):
    """The factory captures have none. The church desk's capture has one:
    CH 39 "SRC SOLO", named, unpatched, its fader at the floor -- a
    placeholder, and the rule says so rather than guessing it is wanted."""
    found = _rule("C006").check(ConsoleState(snap_values(capture)))
    assert [f.addresses[0] for f in found] == (
        ["/ch/39/in/conn/grp"] if capture.name in ("Church-Full.snap", "A17-wing-full.snap") else [])


def test_a_real_strip_cut_off_or_unpatched_on_a_real_desk_is_found():
    """Take a strip that is plainly working on the church desk -- in use,
    unmuted, up, routed -- and cut it: the rule that should speak does,
    about that strip alone."""
    from atoo.audit import is_in_use, strip_bases

    capture = next(p for p in CAPTURES if p.name == "Church-Full.snap")
    values = snap_values(capture)
    state = ConsoleState(dict(values))

    def routes(base):
        return [a for a in values if a.startswith(f"{base}/")
                and (("/send/" in a or "/main/" in a) and a.endswith("/on"))]

    [base] = [b for b in strip_bases(state)
              if b.startswith("/ch/") and is_in_use(state, b) and not state.mute(b)
              and state.fader_db(b) is not None and state.fader_db(b) > -60
              and state.patch(b) is not None
              and any(state.flag(a) for a in routes(b))][:1]
    cut = dict(values)
    for address in routes(base):
        cut[address] = 0
    [reached] = _rule("R008").check(ConsoleState(cut))
    assert reached.addresses[0].startswith(base + "/")

    unpatched = dict(values)
    unpatched[f"{base}/in/conn/grp"] = "OFF"
    new = [f for f in _rule("C006").check(ConsoleState(unpatched))
           if f.addresses[0] != "/ch/39/in/conn/grp"]
    assert [f.addresses for f in new] == [(f"{base}/in/conn/grp",)]
