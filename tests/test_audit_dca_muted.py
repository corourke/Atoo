"""CH004 (DCA Muted, Silencing Active Members): a DCA's mute silences every
strip under it, and nothing on those strips shows it.

CH002 reads a DCA's fader and CH003 an engaged mute group; a muted DCA
reported nothing unless a plan said the DCA should be unmuted (CV017). The
desks and plans are built here; the live-read and capture tests use frozen
captures, never a show bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.audit import (
    DEFAULT_RULES,
    WITHHELD_PLAN_STATES,
    ConsoleState,
    RuleScope,
    apply_plan_scope,
    console_read_plan,
    diff_against_plan,
    plan_scope,
    read_console_state,
    run_audit,
    socket_groups_to_read,
    with_plan_rules,
)
from atoo.diagnostics import Severity
from atoo.watch import present_findings, watch
from atoo.watch_conditions import build_watch_rules, parse_watch_conditions
from tests.snap_desk import SnapDesk, snap_values

INITIALIZED_COMPACT = (Path(__file__).parent / "fixtures" / "console-runs"
                       / "Initialized-Compact.snap")


def _rule():
    return next(r for r in DEFAULT_RULES if r.id == "CH004")


def _desk(*, muted=(2,), name="Band", **extra) -> dict[str, object]:
    """DCA 2 over three strips: Bass and Gtr (named, so in use) and a
    spare that is not. DCAs in `muted` have their mute on; DCA 1 is up."""
    v: dict[str, object] = {
        "/dca/1/name": "Drums", "/dca/1/mute": 0, "/dca/1/fdr": 0.0,
        "/dca/2/name": name, "/dca/2/mute": int(2 in muted), "/dca/2/fdr": 0.0,
        "/ch/6/name": "Bass", "/ch/6/tags": "#D2",
        "/ch/7/name": "Gtr", "/ch/7/tags": "#D2,#M1",
        "/ch/8/name": "", "/ch/8/tags": "#D2",
        "/ch/8/in/conn/grp": "LCL", "/ch/8/in/conn/in": 8,
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1",
    }
    v.update(extra)
    return v


def _state(values) -> ConsoleState:
    return ConsoleState(values, console_model="wing-compact")


def _found(values) -> list:
    return _rule().check(_state(values))


def _ids(values, **kwargs) -> list[str]:
    return [f.rule_id for f in run_audit(_state(values), **kwargs)]


# --------------------------------------------------------------------------
# The row
# --------------------------------------------------------------------------


def test_the_rule_is_an_info_about_any_dca_like_its_mute_group_twin():
    rule, twin = _rule(), next(r for r in DEFAULT_RULES if r.id == "CH003")
    assert rule.severity is twin.severity is Severity.INFO
    assert rule.category == twin.category == "channels"
    assert rule.scope is twin.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# A muted DCA over active members
# --------------------------------------------------------------------------


def test_a_muted_dca_over_active_members_names_the_dca_and_the_members():
    [f] = _found(_desk())
    assert f.rule_id == "CH004" and f.severity is Severity.INFO
    assert f.message == ('DCA 2 "Band" is muted and is silencing 2 active member(s): '
                         'CH 6 "Bass", CH 7 "Gtr".')
    assert f.addresses == ("/dca/2/mute",)


def test_a_member_that_is_not_in_use_is_not_counted():
    [f] = _found(_desk())
    assert "CH 8" not in f.message


def test_an_unmuted_dca_is_quiet():
    assert _found(_desk(muted=())) == []


def test_a_muted_dca_over_nothing_in_use_is_quiet():
    """A spare DCA muted, or one with no member at all, silences nothing
    anybody is using."""
    v = _desk(muted=(2,))
    for ch in ("/ch/6", "/ch/7"):
        v[f"{ch}/name"] = ""
    assert _found(v) == []
    assert _found({"/dca/3/mute": 1, "/dca/3/name": "Spare"}) == []


def test_two_muted_dcas_are_two_findings():
    v = _desk()
    v["/dca/1/mute"] = 1
    assert sorted(f.addresses[0] for f in _found(v)) == ["/dca/1/mute", "/dca/2/mute"]


def test_an_unnamed_dca_is_still_named_by_its_position():
    [f] = _found(_desk(name=""))
    assert f.message.startswith("DCA 2 is muted and is silencing")


def test_an_aux_member_counts_like_a_channel():
    v = _desk()
    v.update({"/aux/3/name": "Click", "/aux/3/tags": "#D2"})
    [f] = _found(v)
    assert 'AUX 3 "Click"' in f.message and "3 active member(s)" in f.message


# -- silent when unread ------------------------------------------------------


def test_a_dca_whose_mute_was_never_read_is_not_called_muted():
    v = _desk(muted=())
    del v["/dca/2/mute"]
    assert _found(v) == []


# --------------------------------------------------------------------------
# One fault, one row: what the neighbouring rules own
# --------------------------------------------------------------------------


def test_the_fader_is_ch002s_and_the_mute_is_ch004s():
    """A DCA pulled down and muted is two settings, each undone on its own:
    unmuting does not bring the band back while the fader is at the floor."""
    v = _desk()
    v["/dca/2/fdr"] = -144.0
    found = [f for f in run_audit(_state(v)) if f.rule_id in {"CH002", "CH004"}]
    assert sorted((f.rule_id, f.addresses) for f in found) == [
        ("CH002", ("/dca/2/fdr",)), ("CH004", ("/dca/2/mute",))]


def test_a_fader_low_dca_that_is_not_muted_is_ch002s_alone():
    v = _desk(muted=())
    v["/dca/2/fdr"] = -144.0
    assert [i for i in _ids(v) if i in {"CH002", "CH004"}] == ["CH002"]


def test_a_mute_group_is_ch003s_and_a_dca_is_ch004s():
    v = _desk()
    v.update({"/mgrp/1/name": "Band", "/mgrp/1/mute": 1})
    found = [f for f in run_audit(_state(v)) if f.rule_id in {"CH003", "CH004"}]
    assert sorted((f.rule_id, f.addresses) for f in found) == [
        ("CH003", ("/mgrp/1/mute",)), ("CH004", ("/dca/2/mute",))]


def test_an_engaged_mute_group_alone_is_not_ch004s():
    v = _desk(muted=())
    v.update({"/mgrp/1/name": "Band", "/mgrp/1/mute": 1})
    assert [i for i in _ids(v) if i in {"CH003", "CH004"}] == ["CH003"]


# --------------------------------------------------------------------------
# Under a plan: CV017 owns a DCA the plan declares
# --------------------------------------------------------------------------


def _plan(**dcas) -> dict:
    return {"channels": [], "busses": {}, "mute_groups": {}, "outputs": {}, "dcas": dcas}


def _audit_plan(values, plan) -> list[str]:
    """What `audit --plan` reports: the structural rules scoped to the plan
    and the conventions diff."""
    state = _state(values)
    return [f.rule_id for f in run_audit(state, plan=plan) + diff_against_plan(state, plan)
            if f.rule_id in {"CH004", "CV012", "CV017"}]


def test_a_dca_the_plan_leaves_unmuted_is_cv017s_alone():
    plan = _plan(Band={"index": 2})                       # no fader block: unmuted
    assert _audit_plan(_desk(), plan) == ["CV017"]
    plan = _plan(Band={"index": 2, "fader": {"fader_db": 0, "muted": False}})
    assert _audit_plan(_desk(), plan) == ["CV017"]


def test_a_dca_the_plan_states_muted_is_as_asked_and_nobody_reports_it():
    plan = _plan(Band={"index": 2, "fader": {"muted": True}})
    assert _audit_plan(_desk(), plan) == []
    # ... and found unmuted, it is the plan's comparison (CV012) that speaks.
    assert _audit_plan(_desk(muted=()), plan) == ["CV012"]


def test_a_dca_the_plan_never_mentions_is_still_ch004s():
    plan = _plan(Drums={"index": 1})
    assert _audit_plan(_desk(), plan) == ["CH004"]
    assert _audit_plan(_desk(), {"channels": [], "busses": {}}) == ["CH004"]


def test_the_stand_down_is_counted_not_silent():
    plan = _plan(Band={"index": 2})
    state = _state(_desk())
    scoped = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    assert [(w.finding.rule_id, w.reason) for w in scoped.withheld
            if w.finding.rule_id == "CH004"] == [("CH004", WITHHELD_PLAN_STATES)]
    assert "CH004" in scoped.summary().message


def test_plan_scope_states_the_mute_of_every_dca_the_plan_declares():
    scope = plan_scope(_state(_desk()), _plan(Band={"index": 2}, Drums={"index": 1}))
    assert scope.states("/dca/2", "mute") and scope.states("/dca/1", "mute")
    assert not scope.states("/dca/3", "mute")


def test_a_plan_entry_without_an_index_judges_nothing():
    assert _audit_plan(_desk(), _plan(Band={"fader": {}})) == ["CH004"]


def _plan_file(tmp_path, plan) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_watch_binds_the_rule_to_the_plan_so_cv017_alone_speaks(tmp_path):
    rules = with_plan_rules(DEFAULT_RULES, _plan_file(tmp_path, _plan(Band={"index": 2})))
    ids = [f.rule_id for f in run_audit(_state(_desk()), rules)
           if f.rule_id in {"CH004", "CV017"}]
    assert ids == ["CV017"]
    # A DCA beyond the plan has no CV017, and is CH004's.
    v = _desk()
    v.update({"/dca/3/name": "Extra", "/dca/3/mute": 1, "/ch/9/name": "Pad", "/ch/9/tags": "#D3"})
    found = [(f.rule_id, f.addresses) for f in run_audit(_state(v), rules)
             if f.rule_id in {"CH004", "CV017"}]
    assert sorted(found) == [("CH004", ("/dca/3/mute",)), ("CV017", ("/dca/2/mute",))]


def test_watch_without_a_plan_leaves_the_rule_as_it_is(tmp_path):
    assert with_plan_rules(DEFAULT_RULES, tmp_path / "missing.json") == list(DEFAULT_RULES)


# --------------------------------------------------------------------------
# Watch: the finding appears and clears
# --------------------------------------------------------------------------


def _run_watch(sequence, rules):
    feed = iter(_state(v) for v in sequence)
    return list(watch(lambda: next(feed), rules=rules, interval=0,
                      max_iterations=len(sequence), sleep=lambda _s: None))


def test_watch_raises_a_dca_muted_mid_show_and_clears_it_when_unmuted():
    events = _run_watch([_desk(muted=()), _desk(), _desk(muted=())], list(DEFAULT_RULES))
    assert "CH004" not in [f.rule_id for f in events[0].all_findings]
    assert [f.rule_id for f in events[1].new_findings] == ["CH004"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CH004"]


def test_watch_under_a_plan_raises_cv017_for_a_planned_dca_and_ch004_for_the_rest(tmp_path):
    rules = with_plan_rules(DEFAULT_RULES, _plan_file(tmp_path, _plan(Band={"index": 2})))
    extra = {"/dca/3/name": "Extra", "/dca/3/mute": 0, "/ch/9/name": "Pad", "/ch/9/tags": "#D3"}
    quiet = _desk(muted=(), **extra)
    planned_muted = _desk(**extra)
    both = _desk(**{**extra, "/dca/3/mute": 1})
    events = _run_watch([quiet, planned_muted, both, quiet], rules)
    assert [f.rule_id for f in events[1].new_findings] == ["CV017"]
    assert [f.rule_id for f in events[2].new_findings] == ["CH004"]
    assert sorted(f.rule_id for f in events[3].cleared_findings) == ["CH004", "CV017"]


def test_a_watch_condition_on_the_same_dca_mute_takes_the_row_and_names_ch004():
    """One fault, one row: the engineer's own condition about the Band DCA's
    mute is the row, and the built-in is named under it."""
    condition = {"id": "band-live", "description": "The Band DCA is never muted",
                 "channel": "DCA Band", "field": "muted", "operator": "==", "value": False,
                 "severity": "error"}
    rules = list(DEFAULT_RULES) + build_watch_rules(
        parse_watch_conditions(json.dumps({"watch_conditions": [condition]})))
    shown = present_findings(run_audit(_state(_desk()), rules))
    assert [(f.rule_id, f.severity) for f in shown.alerts
            if f.rule_id in {"CH004", "WATCH:band-live"}] == [("WATCH:band-live", Severity.ERROR)]
    [also] = [g for group in shown.folded.values() for g in group if g.rule_id == "CH004"]
    assert also.addresses == ("/dca/2/mute",)


# --------------------------------------------------------------------------
# The read: nothing new is asked
# --------------------------------------------------------------------------


def test_the_dca_mute_is_in_the_read_plan_already():
    plan = dict(console_read_plan(input_sockets={}))
    assert [plan[f"/dca/{n}/mute"] for n in (1, 16)] == ["i", "i"]
    assert len([a for a in plan if a.startswith("/dca/") and a.endswith("/mute")]) == 16


def test_a_live_read_takes_the_dca_mute_from_the_dump_and_the_rule_speaks():
    """A factory Compact with DCA 6 muted over a named strip, read the way
    Watch reads it: node dumps, no per-leaf ask for any DCA mute."""
    values = dict(snap_values(INITIALIZED_COMPACT))
    values.update({"/dca/6/name": "Keys", "/dca/6/mute": 1,
                   "/ch/3/name": "Pad", "/ch/3/tags": "#D6"})
    desk = SnapDesk(values)
    inputs, outputs = socket_groups_to_read("wing-compact")
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    assert state.flag("/dca/6/mute") is True
    assert not [a for a in desk.gets if a.startswith("/dca/") and a.endswith("/mute")]
    [f] = [f for f in run_audit(state) if f.rule_id == "CH004"]
    assert f.message == 'DCA 6 "Keys" is muted and is silencing 1 active member(s): CH 3 "Pad".'


# --------------------------------------------------------------------------
# The frozen captures: no false positive
# --------------------------------------------------------------------------

CAPTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.snap"))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_no_frozen_capture_has_a_muted_dca_over_active_members(capture):
    """Factory desks and the desks somebody had set up (a church's
    full-size among them) have no DCA muted, and the full-size captures
    hold every DCA's mute to be judged: 0 findings on all seven."""
    values = snap_values(capture)
    if len(values) > 100:
        assert all(f"/dca/{n}/mute" in values for n in range(1, 17))
    assert _rule().check(ConsoleState(values)) == []


def test_the_same_captures_with_a_dca_muted_do_report_it():
    """The captures' silence is the rule's, not the fixture's: mute the
    DCA a set-up desk's strips sit under and the rule speaks."""
    values = dict(snap_values(Path(__file__).parent / "fixtures" / "console-runs" / "Church-Full.snap"))
    members = {n for n in range(1, 17)
               if any(f"#D{n}" in str(values.get(f"/ch/{c}/tags", "")).split(",")
                      and values.get(f"/ch/{c}/name") for c in range(1, 41))}
    assert members, "the capture should have a DCA with a named member"
    values[f"/dca/{min(members)}/mute"] = 1
    assert len(_rule().check(ConsoleState(values))) == 1
