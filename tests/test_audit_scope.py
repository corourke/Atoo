"""What a structural rule still has to say once a plan is in
hand.

Two independent mechanisms, tested independently because they suppress
different things and either one alone leaves the A5 run noisy:

1. **Plan membership.** A convention-scoped finding about an object the
   plan never mentions is a claim about somebody else's mix.
2. **A parameter the plan states.** The more valuable half, and not
   membership at all -- L002 fired on nineteen *planned* channels in
   the A5 run because the plan asked for exactly the fader it complained
   about. Membership scoping suppresses none of those.

Everything here is offline, the same hand-built `ConsoleState` maps the
rest of the audit suite uses.
"""

import pytest

from atoo.audit import (
    DEFAULT_RULES,
    SCOPE_SUMMARY_RULE_ID,
    WITHHELD_OUTSIDE_PLAN,
    WITHHELD_PLAN_STATES,
    ConsoleState,
    RuleScope,
    apply_plan_scope,
    diff_against_plan,
    finding_subjects,
    plan_scope,
    run_audit,
)
from atoo.diagnostics import Diagnostic, Severity


def _rule_ids(findings):
    return {f.rule_id for f in findings}


def _by_rule(findings):
    out = {}
    for f in findings:
        out.setdefault(f.rule_id, []).append(f)
    return out


def _channel(bank="ch", channel=1, **fields):
    """A compiled-plan channel entry with only the fields a test states --
    the plan schema's own "a null field is not an assertion" rule."""
    entry = {"bank": bank, "channel": channel}
    entry.update(fields)
    return entry


# --------------------------------------------------------------------------
# The per-rule scope canary used to live here, as a hand-written
# `APPROVED_SCOPES` dict. It moved to `tests/test_audit_catalogue.py` on
# 2026-09-23, which checks the same thing against
# `docs/developer/audit-rules.md` -- the document the maintainer actually edits, and
# therefore the real record of the decision. A second hand-written copy in
# this file would only have been a third place to forget.
#
# What stays here is the behaviour each scope produces, below.
# --------------------------------------------------------------------------


def test_a_new_rule_defaults_to_hazard():
    """The safe direction: a rule nobody classified stays visible. Getting
    this wrong the other way hides something real."""
    from atoo.audit import AuditRule

    rule = AuditRule("X999", Severity.WARNING, "test", "T", "d", lambda s: [])
    assert rule.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# No plan: nothing changes
# --------------------------------------------------------------------------


def _busy_unplanned_state():
    """One aux strip nobody planned: in use, in no DCA, routed with its
    fader on the floor. Exactly one convention finding about it
    (CH001) and one hazard (L002) -- which is the pair that makes
    the distinction visible."""
    return ConsoleState({
        "/aux/4/name": "Wedge Spare",
        "/aux/4/fdr": -144.0,
        "/aux/4/mute": 0,
        "/aux/4/main/1/on": 1,
    })


def test_with_no_plan_everything_is_in_scope():
    findings = run_audit(_busy_unplanned_state())
    assert {"CH001", "L002"} <= _rule_ids(findings)
    assert SCOPE_SUMMARY_RULE_ID not in _rule_ids(findings)


def test_run_audit_without_plan_is_byte_for_byte_what_it_always_was():
    state = _busy_unplanned_state()
    assert run_audit(state, plan=None) == run_audit(state)


# --------------------------------------------------------------------------
# Mechanism 1: plan membership
# --------------------------------------------------------------------------


def test_convention_finding_about_an_unplanned_strip_is_withheld():
    state = _busy_unplanned_state()
    plan = {"channels": [_channel(channel=1)]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "CH001" not in _rule_ids(result.findings)
    assert {w.finding.rule_id for w in result.withheld} == {"CH001"}
    assert {w.reason for w in result.withheld} == {WITHHELD_OUTSIDE_PLAN}


def test_the_same_finding_about_a_planned_strip_survives():
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/fdr": -144.0,
        "/ch/1/mute": 0,
        "/ch/1/main/1/on": 1,
    })
    # In the plan, but the plan says nothing about its fader or its DCA --
    # so neither rule can stand down, and both are about the show.
    plan = {"channels": [_channel(channel=1)]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert {"CH001", "L002"} <= _rule_ids(result.findings)
    assert result.withheld == []


# --------------------------------------------------------------------------
# L002 is a HAZARD, and the two halves of that are easy to confuse.
# These four pin the distinction directly, because getting it wrong the
# first time round is what sent this change back: the useful half of
# "routed, unmuted and silent" is precisely the strip that is NOT part of
# your show, and withholding it hides the classic why-can't-I-hear-it.
# --------------------------------------------------------------------------


def test_a_silent_routed_strip_outside_the_plan_is_still_reported():
    """The 29 findings of the A5 run's 48 that must NOT be withheld."""
    state = _busy_unplanned_state()
    plan = {"channels": [_channel(channel=1)]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "L002" in _rule_ids(result.findings)
    assert "L002" not in {w.finding.rule_id for w in result.withheld}


def test_a_silent_routed_strip_the_plan_put_on_the_floor_is_not():
    """The other 19. Same rule, same desk reading, opposite answer -- and
    the thing that separates them is the plan stating the fader, not the
    strip's membership."""
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/fdr": -144.0,
        "/ch/1/mute": 0,
        "/ch/1/main/1/on": 1,
    })
    plan = {"channels": [_channel(channel=1, fader={"fader_db": -144})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "L002" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "L002"] == [
        WITHHELD_PLAN_STATES
    ]


def test_both_halves_at_once_on_one_desk():
    """One planned channel whose fader the plan states, one unplanned
    strip at the floor: exactly one L002 survives, and it is the
    unplanned one."""
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/fdr": -144.0, "/ch/1/mute": 0, "/ch/1/main/1/on": 1,
        "/ch/30/name": "Somebody Elses", "/ch/30/fdr": -144.0, "/ch/30/mute": 0,
        "/ch/30/main/1/on": 1,
    })
    plan = {"channels": [_channel(channel=1, fader={"fader_db": -144})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    surviving = [f for f in result.findings if f.rule_id == "L002"]
    assert [f.addresses for f in surviving] == [("/ch/30/fdr",)]
    assert [w.finding.addresses for w in result.withheld if w.finding.rule_id == "L002"] == [
        ("/ch/1/fdr",)
    ]


def test_a_hazard_is_never_withheld_for_being_outside_the_plan():
    """Whatever else changes, no hazard-scoped rule may ever be withheld
    with the out-of-plan reason -- that is the whole meaning of the
    scope, and the invariant L002 broke."""
    state = ConsoleState({
        "/aux/4/name": "Wedge Spare", "/aux/4/fdr": -144.0, "/aux/4/mute": 0,
        "/aux/4/main/1/on": 1,
        "/io/in/LCL/9/vph": 1,
        "/mtx/2/name": "Lobby", "/io/out/LCL/5/grp": "MTX", "/io/out/LCL/5/in": 2,
        "/ch/1/name": "Kick",
    })
    plan = {"channels": [_channel(channel=1)]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    hazards = {r.id for r in DEFAULT_RULES if r.scope is RuleScope.HAZARD}
    withheld_hazards = {
        w.finding.rule_id for w in result.withheld
        if w.finding.rule_id in hazards and w.reason == WITHHELD_OUTSIDE_PLAN
    }
    assert withheld_hazards == set()
    # ...and the three hazards this desk actually trips are all present.
    assert {"L002", "C001", "R003"} <= _rule_ids(result.findings)


def test_a_hazard_is_reported_for_a_socket_the_plan_never_mentions():
    """The issue's own example: 48V does not care whose strip it is."""
    state = ConsoleState({
        "/io/in/LCL/9/vph": 1,
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    })
    plan = {"channels": [_channel(channel=1, patch={"group": "LCL", "sockets": [1]})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "C001" in _rule_ids(result.findings)


def test_an_unplanned_bus_stops_being_the_plans_business():
    """R002 only, since 2026-09-23. R001 is a hazard now.

    The maintainer: *"on an initialized console, the busses are not named, so we
    should indeed be checking that any bus with a name has inputs. We
    should not supress this."* A bus somebody named and then fed nothing
    is worth saying whoever named it -- the predicate's own "named" test
    is what keeps it quiet on a factory desk, and that is the whole
    argument against reaching for scope first.
    """
    state = ConsoleState({
        "/bus/9/name": "Somebody Elses Mix",
        "/ch/1/name": "Kick",
        # An output socket the read covered and nothing is
        # patched to, so R002's "no route to a physical output" is a
        # measurement here rather than an unasked question. Without it
        # the rule declines to answer and this test has no finding to
        # scope.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    plan = {"channels": [_channel(channel=1)], "busses": {"Drums": {"index": 1}}}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "R002" not in _rule_ids(result.findings)
    assert {w.finding.rule_id for w in result.withheld} >= {"R002"}
    assert "R001" in _rule_ids(result.findings)
    assert "R001" not in {w.finding.rule_id for w in result.withheld}


def test_a_bus_the_plan_declares_by_index_is_still_the_plans_business():
    state = ConsoleState({
        "/bus/9/name": "Vocals", "/ch/1/name": "Kick",
        # An output socket the read covered and nothing is
        # patched to, so R002's "no route to a physical output" is a
        # measurement here rather than an unasked question. Without it
        # the rule declines to answer and this test has no finding to
        # scope.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    plan = {"channels": [_channel(channel=1)], "busses": {"Vocals": {"index": 9}}}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert {"R001", "R002"} <= _rule_ids(result.findings)


def test_a_bus_whose_live_name_matches_the_plan_is_claimed_even_at_another_index():
    """The union, not either alone -- claiming more keeps a finding, and
    that is the safe direction."""
    state = ConsoleState({"/bus/9/name": "Vocals", "/ch/1/name": "Kick"})
    plan = {"channels": [_channel(channel=1)], "busses": {"Vocals": {"index": 2}}}
    scope = plan_scope(state, plan)
    assert "/bus/9" in scope.objects and "/bus/2" in scope.objects


# --------------------------------------------------------------------------
# Pairwise: a duplicate name is about a pair
# --------------------------------------------------------------------------


def _duplicate_name_state(second="/ch/30"):
    return ConsoleState({
        "/ch/1/name": "Kick",
        f"{second}/name": "Kick",
    })


def test_a_collision_between_two_unplanned_strips_is_noise():
    state = _duplicate_name_state()
    plan = {"channels": [_channel(channel=7)]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "N001" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "N001"] == [
        WITHHELD_OUTSIDE_PLAN
    ]


def test_a_collision_with_one_of_yours_and_one_of_theirs_is_reported():
    state = _duplicate_name_state()
    plan = {"channels": [_channel(channel=1)]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "N001" in _rule_ids(result.findings)


def test_shared_input_keeps_a_collision_with_an_unplanned_strip():
    """A5's real one: /ch/1 is the show's kick, /ch/20 is a leftover on the
    same socket. The plan states /ch/1's patch, but not /ch/20's, so the
    stand-down does not fire and the collision is still reported."""
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/20/name": "Kick IEM",
        "/ch/20/in/conn/grp": "A", "/ch/20/in/conn/in": 1,
    })
    plan = {"channels": [_channel(channel=1, patch={"group": "A", "sockets": [1]})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "C002" in _rule_ids(result.findings)


def test_shared_input_the_plan_asked_for_stands_down():
    """The monitor-split shape desk run A6 applied: both strips patched to
    one socket on purpose. CV005 checks each against the plan, so the
    structural note adds nothing."""
    state = ConsoleState({
        "/ch/1/name": "Kick In",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/name": "Kick Out",
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 1,
    })
    plan = {"channels": [
        _channel(channel=1, patch={"group": "A", "sockets": [1]}),
        _channel(channel=2, patch={"group": "A", "sockets": [1]}),
    ]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "C002" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "C002"] == [
        WITHHELD_PLAN_STATES
    ]


# --------------------------------------------------------------------------
# Mechanism 2: a rule stands down where the plan states the parameter
# --------------------------------------------------------------------------


def _fader_at_floor_state():
    return ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/fdr": -144.0,
        "/ch/1/mute": 0,
        "/ch/1/main/1/on": 1,
    })


def test_the_a5_case_a_planned_fader_the_plan_asked_to_be_down():
    """`examples/conventions.md`: "leave all faders all the way down". The
    plan states fader_db: -144, apply wrote it, and L002 then called it
    a fault on channel after channel -- all of them IN the plan."""
    state = _fader_at_floor_state()
    plan = {"channels": [_channel(channel=1, fader={"fader_db": -144, "muted": None})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "L002" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "L002"] == [
        WITHHELD_PLAN_STATES
    ]


def test_a_planned_strip_whose_fader_the_plan_does_not_state_is_still_reported():
    state = _fader_at_floor_state()
    plan = {"channels": [_channel(channel=1, fader={"fader_db": None, "muted": False})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "L002" in _rule_ids(result.findings)


def _stated_bus_fader_case():
    state = ConsoleState({
        "/bus/1/name": "MON1",
        "/bus/1/fdr": -144.0,
        "/bus/1/mute": 0,
        "/bus/1/main/1/on": 1,
        "/ch/1/name": "Kick", "/ch/1/send/1/on": 1,
    })
    plan = {
        "channels": [_channel(channel=1)],
        "busses": {"MON1": {"index": 1, "fader": {"fader_db": -144}}},
    }
    return state, plan


def test_a_bus_fader_the_plan_states_stands_down_now_that_sp_cv011_diffs_it():
    """An earlier change, the inversion of a test that used to assert the gap.

    The "because" in the general rule is load-bearing, and until #161 it
    was unsatisfied for a bus: a plan states a bus fader, `diff_against_plan`
    walked only `plan["channels"]`, so standing L002 down on a bus would
    have meant nobody checked that fader at all. `CV011 Bus Fader Level
    Contradicts Plan` checks it now, so the stand-down is earned."""
    state, plan = _stated_bus_fader_case()

    assert plan_scope(state, plan).states("/bus/1", "fdr")

    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    assert "L002" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "L002"] == [
        WITHHELD_PLAN_STATES
    ]


def test_the_bus_fader_sp_l002_stopped_reporting_is_the_one_sp_cv011_picks_up():
    """The other half of the same guarantee, and the reason the stand-down
    is not just a quieter report: the parameter is still checked, against
    what the plan asked for rather than against a structural rule of
    thumb. Move the desk away from the plan and a finding comes back --
    under the rule that owns the comparison."""
    state, plan = _stated_bus_fader_case()
    assert diff_against_plan(state, plan) == []   # desk agrees with the plan

    state.values["/bus/1/fdr"] = 0.0              # somebody rode it up
    findings = diff_against_plan(state, plan)
    assert [f.rule_id for f in findings] == ["CV011"]
    assert findings[0].addresses == ("/bus/1/fdr",)


def test_a_dca_fader_the_plan_states_stands_down_now_that_sp_cv013_diffs_it():
    """The second half of #161, and the one that needed a schema change
    first: a plan had nowhere to state a DCA fader at all, so CH002
    could never stand down -- seven of the A5 run's surviving warnings
    were DCAs at the floor on a desk set up exactly as its conventions
    describe."""
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1", "/ch/1/send/1/on": 1,
        "/dca/1/name": "Drums", "/dca/1/fdr": -144.0,
    })
    plan = {
        "channels": [_channel(channel=1, dca=["Drums"])],
        "dcas": {"Drums": {"index": 1, "fader": {"fader_db": -144}}},
    }
    assert plan_scope(state, plan).states("/dca/1", "fdr")

    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    assert "CH002" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "CH002"] == [
        WITHHELD_PLAN_STATES
    ]
    # ...and CV013 is what checks it instead.
    assert diff_against_plan(state, plan) == []
    state.values["/dca/1/fdr"] = 0.0
    assert [f.rule_id for f in diff_against_plan(state, plan)] == ["CV013"]


def test_a_dca_fader_the_plan_does_not_state_is_still_reported():
    """The gap #161 closed is a stated fader. A plan that declares a DCA
    and says nothing about its fader states nothing, so CH002 keeps
    its voice -- which is the whole reason `plan_scope` reports stated
    parameters rather than plan membership."""
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1", "/ch/1/send/1/on": 1,
        "/dca/1/name": "Drums", "/dca/1/fdr": -144.0,
    })
    plan = {
        "channels": [_channel(channel=1, dca=["Drums"])],
        "dcas": {"Drums": {"index": 1}},
    }
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    assert "CH002" in _rule_ids(result.findings)


def test_a_dca_membership_the_plan_states_stands_down():
    """CV003 owns the comparison; CH001 saying the same thing in
    weaker words is one finding too many."""
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/tags": "", "/dca/1/name": "Drums"})
    plan = {"channels": [_channel(channel=1, dca=["Drums"])]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "CH001" not in _rule_ids(result.findings)
    assert [w.reason for w in result.withheld if w.finding.rule_id == "CH001"] == [
        WITHHELD_PLAN_STATES
    ]


def test_a_mute_group_alone_does_not_stand_down_the_dca_rule():
    """Both live at `{base}/tags`, and a plan can state one without the
    other -- which is why the stated key is finer than the address."""
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/tags": "", "/mgrp/1/name": "Band"})
    plan = {"channels": [_channel(channel=1, mute_group=["Band"])]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    assert "CH001" in _rule_ids(result.findings)


def test_a_send_level_the_plan_states_stands_down_only_for_that_send():
    """The judged parameter carries the bus index, read off the finding's
    own address -- so a stated send to bus 1 says nothing about bus 2."""
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/bus/1/name": "Drums", "/bus/2/name": "MON1",
        "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": -110.0,
        "/ch/1/send/2/on": 1, "/ch/1/send/2/lvl": -110.0,
    })
    plan = {
        "channels": [_channel(channel=1, bus_sends=[{"bus": "Drums", "level_db": -110.0}])],
        "busses": {"Drums": {"index": 1}, "MON1": {"index": 2}},
    }
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)

    surviving = [f for f in result.findings if f.rule_id == "L001"]
    assert [f.addresses for f in surviving] == [("/ch/1/send/2/lvl",)]
    assert [w.finding.addresses for w in result.withheld if w.finding.rule_id == "L001"] == [
        ("/ch/1/send/1/lvl",)
    ]


def test_a_hazard_also_stands_down_on_a_parameter_the_plan_states():
    """Not a convention-only mechanism: the plan is the better authority
    whenever it speaks, whatever the rule's scope."""
    state = ConsoleState({
        "/io/in/LCL/9/vph": 1,
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    })
    plan = {"channels": [_channel(channel=1, patch={"group": "LCL", "sockets": [1]})]}
    from atoo.audit import AuditRule, _rule_phantom_unpatched

    rules = [
        r if r.id != "C001" else AuditRule(
            r.id, r.severity, r.category, r.title, r.description,
            _rule_phantom_unpatched, scope=RuleScope.HAZARD, judges=("vph",))
        for r in DEFAULT_RULES
    ]
    # Nothing states `vph`, so the hazard still stands: this asserts the
    # mechanism is reached, not that it fires.
    result = apply_plan_scope(state, run_audit(state, rules), plan, rules)
    assert "C001" in _rule_ids(result.findings)


# --------------------------------------------------------------------------
# Suppression is never silent
# --------------------------------------------------------------------------


def test_the_summary_counts_what_was_withheld_and_why():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/fdr": -144.0, "/ch/1/mute": 0, "/ch/1/main/1/on": 1,
        "/aux/4/name": "Spare", "/aux/4/fdr": -144.0, "/aux/4/mute": 0, "/aux/4/main/1/on": 1,
    })
    plan = {"channels": [_channel(channel=1, fader={"fader_db": -144})]}
    result = apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES)
    summary = result.summary()

    assert summary is not None
    assert summary.severity is Severity.INFO
    assert summary.rule_id == SCOPE_SUMMARY_RULE_ID
    assert str(len(result.withheld)) in summary.detail
    assert WITHHELD_PLAN_STATES in summary.detail
    assert WITHHELD_OUTSIDE_PLAN in summary.detail
    assert "L002" in summary.detail


def test_no_summary_when_nothing_was_withheld():
    state = ConsoleState({"/ch/1/name": "Kick"})
    plan = {"channels": [_channel(channel=1)]}
    assert apply_plan_scope(state, run_audit(state), plan, DEFAULT_RULES).summary() is None


def test_run_audit_with_a_plan_reports_the_withheld_count_in_line():
    state = _busy_unplanned_state()
    plan = {"channels": [_channel(channel=1)]}
    findings = run_audit(state, plan=plan)

    assert "CH001" not in _rule_ids(findings)
    assert "L002" in _rule_ids(findings)   # hazard: survives, see above
    assert SCOPE_SUMMARY_RULE_ID in _rule_ids(findings)
    summary = _by_rule(findings)[SCOPE_SUMMARY_RULE_ID][0]
    assert "1 finding(s)" in summary.detail
    assert "CH001" in summary.detail


def test_the_summary_renders_like_any_other_finding():
    from atoo.audit import render_findings

    state = _busy_unplanned_state()
    plan = {"channels": [_channel(channel=1)]}
    text = render_findings(run_audit(state, plan=plan))
    assert SCOPE_SUMMARY_RULE_ID in text
    assert "Findings Withheld From This Report" in text


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("addresses,expected", [
    (("/ch/1/fdr",), ("/ch/1",)),
    (("/ch/1/send/3/lvl",), ("/ch/1",)),
    (("/io/in/A/12/vph",), ("/io/in/A/12",)),
    (("/io/out/LCL/7/grp", "/io/out/LCL/7/in"), ("/io/out/LCL/7",)),
    (("/ch/3/name", "/ch/4/name"), ("/ch/3", "/ch/4")),
    (("/main/1",), ("/main/1",)),
    ((), ()),
])
def test_finding_subjects_reads_the_object_off_the_address(addresses, expected):
    finding = Diagnostic.audit("T001", Severity.INFO, "test", "T", "d", addresses)
    assert finding_subjects(finding) == expected


def test_main_1_does_not_swallow_main_10():
    state = ConsoleState({"/ch/1/name": "Kick"})
    plan = {"channels": [_channel(channel=1)], "outputs": {"Main 1": {"kind": "main", "index": 1}}}
    scope = plan_scope(state, plan)
    assert scope.claims("/main/1") and not scope.claims("/main/10")


def test_conventions_diff_findings_pass_through_untouched():
    """CV* are plan-scoped by construction -- they exist only because
    the plan spoke -- so the scoping pass must never touch them."""
    state = ConsoleState({"/ch/9/name": "Not in the plan"})
    cv = Diagnostic.audit("CV002", Severity.WARNING, "conventions", "Fader Level Contradicts Plan",
                          "…", ("/ch/9/fdr",))
    plan = {"channels": [_channel(channel=1)]}
    result = apply_plan_scope(state, [cv], plan, DEFAULT_RULES)

    assert result.findings == [cv]
    assert result.withheld == []


def test_a_finding_citing_no_address_is_always_kept():
    state = ConsoleState({})
    orphan = Diagnostic.audit("R005", Severity.ERROR, "routing", "Main Not Patched", "…", ())
    result = apply_plan_scope(state, [orphan], {"channels": []}, DEFAULT_RULES)
    assert result.findings == [orphan]


def test_plan_scope_survives_a_malformed_plan():
    """A partial or mid-edit plan is exactly the kind an audit gets run
    against; answering "what does this claim" is no place to crash."""
    state = ConsoleState({"/ch/1/name": "Kick"})
    plan = {
        "channels": [{"bank": "ch"}, None, _channel(channel=1, patch={"group": "A", "sockets": ["x"]})],
        "busses": {"Drums": None},
        "outputs": {"Main 1": {"kind": "main", "index": "one"}},
    }
    scope = plan_scope(state, plan)
    assert scope.claims("/ch/1")
