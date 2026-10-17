"""CV019: 48V against what the plan states, in `audit --plan` and in Watch.

The plan states phantom for every channel (`source.phantom`, and
`pair_phantom` for a stereo pair's second socket) and `apply` writes it, but
nothing compared the desk's `vph` with it: a condenser with 48V off, which is
silent, and 48V on at a source the plan says must not have it both went
unreported. C001 covers only 48V on a socket nobody patched.

The plan and the desk are built here.
"""

from __future__ import annotations

import json

import pytest

from atoo.audit import (
    DEFAULT_RULES, WITHHELD_PLAN_STATES, ConsoleState, Severity, apply_plan_scope,
    diff_against_plan, phantom_drift_findings, phantom_drift_rule, plan_scope,
    run_audit, with_plan_rules,
)
from atoo.watch import watch


def _channel(n, name, *, phantom, group="A", sockets=None, stereo=False, **source):
    return {
        "channel": n, "bank": "ch", "name": name,
        "source": {"input": name, "type": "Mic", "model": "", "stereo": stereo,
                   "phantom": phantom, **source},
        "patch": {"group": group, "sockets": sockets or [n], "stated": True},
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": None, "muted": None}, "dca": [], "mute_group": [],
        "bus_sends": [], "main_routes": [{"index": 1}],
    }


PLAN = {
    "busses": {}, "dcas": {}, "mute_groups": {}, "outputs": {},
    "channels": [
        _channel(1, "Kick", phantom=True),                           # a condenser, A 1
        _channel(2, "Snare", phantom=False),                         # a dynamic, A 2
        _channel(3, "OH", phantom=True, sockets=[5, 6], stereo=True,
                 pair_input="OH R", pair_phantom=False),             # a pair, one leg powered
        _channel(4, "Keys", phantom=False, sockets=[8, 9], stereo=True),  # one value for the pair
        _channel(5, "Click", phantom=True, group="USB", sockets=[1]),     # no head amp
        _channel(6, "Room", phantom=True, group="LCL", sockets=[1]),
    ],
}


def _desk(**changes) -> ConsoleState:
    """The rig as `apply` leaves it: 48V where the plan wants it, patched
    where the plan says, the pair's width stereo."""
    v: dict[str, object] = {}
    for entry in PLAN["channels"]:
        base = f"/ch/{entry['channel']}"
        patch = entry["patch"]
        v[f"{base}/name"] = entry["name"]
        v[f"{base}/in/conn/grp"], v[f"{base}/in/conn/in"] = patch["group"], patch["sockets"][0]
        v[f"{base}/mute"] = 0
        if patch["group"] == "USB":
            continue
        for socket, wanted in zip(patch["sockets"], _wanted(entry)):
            v[f"/io/in/{patch['group']}/{socket}/vph"] = 1 if wanted else 0
            v[f"/io/in/{patch['group']}/{socket}/mode"] = "ST" if entry["source"]["stereo"] else "M"
    v.update(changes)
    return ConsoleState(v, console_model="wing-compact")


def _wanted(entry):
    first = entry["source"]["phantom"]
    pair = entry["source"].get("pair_phantom")
    return [first, pair if isinstance(pair, bool) else first][: len(entry["patch"]["sockets"])]


def _cv019(state, plan=PLAN):
    return [f for f in phantom_drift_findings(state, plan)]


# --------------------------------------------------------------------------
# Firing
# --------------------------------------------------------------------------


def test_a_desk_set_up_as_the_plan_says_raises_nothing():
    assert _cv019(_desk()) == []
    assert [f for f in diff_against_plan(_desk(), PLAN) if f.rule_id == "CV019"] == []


def test_a_condenser_with_its_48v_off_is_a_warning_naming_the_strip_and_socket():
    [finding] = _cv019(_desk(**{"/io/in/A/1/vph": 0}))
    assert (finding.rule_id, finding.severity) == ("CV019", Severity.WARNING)
    assert finding.message == (
        'CH 1 "Kick": the plan has 48V on at AES50-A 1; the desk has it off, so a '
        "condenser patched there is silent.")
    assert finding.addresses == ("/io/in/A/1/vph",)


def test_48v_on_at_a_source_the_plan_says_must_not_have_it_is_a_warning():
    [finding] = _cv019(_desk(**{"/io/in/A/2/vph": 1}))
    assert finding.severity == Severity.WARNING
    assert finding.message == (
        'CH 2 "Snare": the plan has no 48V at AES50-A 2; the desk has it on, which can '
        "damage a source that does not want it.")


def test_each_socket_of_a_stereo_pair_has_its_own_value():
    """OH: the plan powers the first leg and not the second."""
    both = _cv019(_desk(**{"/io/in/A/5/vph": 0, "/io/in/A/6/vph": 1}))
    assert [f.addresses for f in both] == [("/io/in/A/5/vph",), ("/io/in/A/6/vph",)]
    assert "no 48V at AES50-A 6" in both[1].message


def test_a_pair_the_plan_gives_one_value_is_read_as_both_sockets():
    """`apply` writes `source.phantom` to both when there is no `pair_phantom`."""
    [finding] = _cv019(_desk(**{"/io/in/A/9/vph": 1}))
    assert "no 48V at AES50-A 9" in finding.message


def test_the_strip_is_judged_on_the_socket_it_is_patched_to_now():
    """Kick moved to A 3: the desk's 48V there is what it hears."""
    state = _desk(**{"/ch/1/in/conn/in": 3, "/io/in/A/3/vph": 0})
    [finding] = _cv019(state)
    assert finding.addresses == ("/io/in/A/3/vph",)


# --------------------------------------------------------------------------
# Silent
# --------------------------------------------------------------------------


def test_silent_when_the_socket_was_not_read():
    values = dict(_desk().values)
    del values["/io/in/A/1/vph"]
    assert _cv019(ConsoleState(values)) == []


def test_silent_for_a_strip_patched_to_a_group_with_no_head_amp():
    """Click is on USB: nothing there has 48V to compare."""
    assert _cv019(_desk(**{"/io/in/USB/1/vph": 0})) == []


def test_silent_for_an_unpatched_strip():
    assert _cv019(_desk(**{"/ch/1/in/conn/grp": "OFF"})) == []


@pytest.mark.parametrize("source", [{"input": "Kick"}, {"input": "Kick", "phantom": None}])
def test_silent_when_the_plan_does_not_state_a_phantom(source):
    plan = {"channels": [{**PLAN["channels"][0], "source": source}]}
    assert _cv019(_desk(**{"/io/in/A/1/vph": 0}), plan) == []
    assert phantom_drift_rule(plan) is None


def test_silent_about_a_strip_the_plan_never_mentions():
    state = _desk(**{"/ch/9/name": "Spare", "/ch/9/in/conn/grp": "A", "/ch/9/in/conn/in": 40,
                     "/io/in/A/40/vph": 1})
    assert _cv019(state) == []


# --------------------------------------------------------------------------
# One socket, once: C001 stands down
# --------------------------------------------------------------------------


def _broken_pair() -> ConsoleState:
    """Keys' pair with the source width left mono, so C001 reads the even
    socket as unpatched; the plan has no 48V there and the desk does."""
    return _desk(**{"/io/in/A/8/mode": "M", "/io/in/A/9/vph": 1})


def test_without_a_plan_c001_says_it():
    assert [f.rule_id for f in run_audit(_broken_pair()) if f.rule_id in {"C001", "CV019"}] == ["C001"]


def test_with_a_plan_the_socket_is_reported_once_by_cv019():
    state = _broken_pair()
    findings = run_audit(state, plan=PLAN) + diff_against_plan(state, PLAN)
    assert [f.rule_id for f in findings if f.rule_id in {"C001", "CV019"}] == ["CV019"]
    scoped = apply_plan_scope(state, run_audit(state), PLAN, DEFAULT_RULES)
    assert [(w.finding.rule_id, w.reason) for w in scoped.withheld
            if w.finding.rule_id == "C001"] == [("C001", WITHHELD_PLAN_STATES)]


def test_c001_still_says_a_socket_nothing_patched_that_the_plan_does_not_judge():
    state = _desk(**{"/io/in/A/20/vph": 1})
    findings = run_audit(state, plan=PLAN)
    assert [f.addresses for f in findings if f.rule_id == "C001"] == [("/io/in/A/20/vph",)]


def test_plan_scope_states_vph_only_on_the_sockets_it_compares():
    scope = plan_scope(_desk(), PLAN)
    assert scope.states("/io/in/A/1", "vph") and scope.states("/io/in/A/6", "vph")
    assert not scope.states("/io/in/A/7", "vph")
    assert not scope.states("/io/in/USB/1", "vph")


def test_watch_binds_cv019_and_quiets_c001_for_the_sockets_it_judges(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    rules = with_plan_rules(DEFAULT_RULES, path)
    assert "CV019" in {r.id for r in rules}
    ids = [f.rule_id for f in run_audit(_broken_pair(), rules) if f.rule_id in {"C001", "CV019"}]
    assert ids == ["CV019"]
    # ... and a stray 48V nobody patched is still C001's.
    stray = run_audit(_desk(**{"/io/in/A/20/vph": 1}), rules)
    assert [f.rule_id for f in stray if f.rule_id in {"C001", "CV019"}] == ["C001"]


# --------------------------------------------------------------------------
# Watch: the finding appears and clears
# --------------------------------------------------------------------------


def test_watch_raises_a_condenser_losing_48v_and_clears_it(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    rules = with_plan_rules(DEFAULT_RULES, path)
    states = iter([_desk(), _desk(**{"/io/in/A/1/vph": 0}), _desk()])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings] == ["CV019"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CV019"]
