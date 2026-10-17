"""C007 (Strip's Input Socket Muted): a WING input socket has a mute of its
own, `/io/in/{grp}/{n}/mute`, which silences every strip patched to it and
shows nothing on the strip.

Desks are built in the test; the live-read tests use a frozen factory
capture, never a show bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    RuleScope,
    bulk_node_for,
    console_read_plan,
    read_console_state,
    run_audit,
    socket_groups_to_read,
)
from atoo.diagnostics import Severity
from atoo.watch import watch
from tests.snap_desk import SnapDesk, snap_values

INITIALIZED_COMPACT = (Path(__file__).parent / "fixtures" / "console-runs"
                       / "Initialized-Compact.snap")


def _rule():
    return next(r for r in DEFAULT_RULES if r.id == "C007")


def _desk(patch=("A", 3), *, name="Vox", muted=(), unmuted=(), mode=None, strip="/ch/3",
          **extra) -> dict[str, object]:
    """One strip patched to `patch`; every socket in `muted` has its mute
    on and every socket in `unmuted` has it read off."""
    group, socket = patch
    v: dict[str, object] = {
        f"{strip}/name": name, f"{strip}/mute": 0, f"{strip}/fdr": 0.0,
        f"{strip}/in/conn/grp": group, f"{strip}/in/conn/in": socket,
        f"{strip}/in/set/altsrc": 0, f"{strip}/in/conn/altgrp": "OFF",
    }
    for leg in muted:
        v[f"/io/in/{group}/{leg}/mute"] = 1
    for leg in unmuted:
        v[f"/io/in/{group}/{leg}/mute"] = 0
    if mode is not None:
        v[f"/io/in/{group}/{socket}/mode"] = mode
    v.update(extra)
    return v


def _found(values: dict) -> list:
    return _rule().check(ConsoleState(values, console_model="wing-compact"))


# --------------------------------------------------------------------------
# The row
# --------------------------------------------------------------------------


def test_the_rule_is_a_warning_about_any_strip():
    rule = _rule()
    assert rule.severity is Severity.WARNING
    assert rule.category == "configuration"
    assert rule.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# A muted socket under a strip in use
# --------------------------------------------------------------------------


def test_a_strip_fed_from_a_muted_socket_is_reported_naming_the_socket():
    [f] = _found(_desk(muted=(3,)))
    assert f.severity is Severity.WARNING
    assert f.message.startswith('CH 3 "Vox" is fed from AES50-A 3, which is muted at the socket.')
    assert f.addresses == ("/ch/3/in/conn/grp", "/io/in/A/3/mute")


@pytest.mark.parametrize("group,label", [("LCL", "LCL"), ("B", "AES50-B"), ("C", "AES50-C")])
def test_the_socket_is_named_the_way_an_input_list_writes_it(group, label):
    [f] = _found(_desk(patch=(group, 7), muted=(7,)))
    assert f"is fed from {label} 7, which" in f.message


def test_an_unmuted_socket_is_quiet():
    assert _found(_desk(unmuted=(3,))) == []


def test_an_aux_strip_is_judged_too():
    [f] = _found(_desk(strip="/aux/4", name="Click", muted=(3,)))
    assert 'AUX 4 "Click"' in f.message


def test_two_strips_on_one_muted_socket_are_two_findings():
    v = _desk(muted=(3,))
    v.update(_desk(strip="/ch/4", name="Vox DI", muted=(3,)))
    assert sorted(f.addresses[0] for f in _found(v)) == ["/ch/3/in/conn/grp", "/ch/4/in/conn/grp"]


def test_a_strip_not_in_use_is_not_judged():
    """Unnamed, on the factory patch, sending nowhere new: a spare strip
    on a socket somebody muted is nobody's silence."""
    v = _desk(patch=("LCL", 3), name="", muted=(3,))
    assert _found(v) == []


def test_a_named_strip_on_the_factory_patch_is_in_use():
    assert len(_found(_desk(patch=("LCL", 3), name="Vox", muted=(3,)))) == 1


def test_the_talkback_strip_is_exempt_and_t002_names_all_three_rules():
    v = _desk(patch=("LCL", 40), strip="/ch/40", name="Talk Mic", muted=(40,))
    v[console_facts.TALK_ASSIGN] = "CH40"
    state = ConsoleState(v, console_model="wing-compact")
    assert _rule().check(state) == []
    [t002] = [f for f in run_audit(state) if f.rule_id == "T002"]
    assert all(rule in t002.message for rule in ("R008", "C006", "C007"))


def test_a_strips_own_mute_is_not_this_rules_business():
    """The socket is muted and so is the strip; the finding is about the
    socket, which nothing on the strip would have shown."""
    v = _desk(muted=(3,))
    v["/ch/3/mute"] = 1
    assert len(_found(v)) == 1


# -- silent when unread ------------------------------------------------------


def test_a_socket_whose_mute_was_never_read_is_not_called_unmuted():
    assert _found(_desk()) == []


def test_a_group_whose_sockets_are_not_read_is_silent_but_would_work_if_they_were():
    """CRD, MOD, USB and the rest are not read, so a strip patched there
    says nothing; a state that does hold the leaf is judged all the same."""
    assert _found(_desk(patch=("MOD", 5))) == []
    assert len(_found(_desk(patch=("MOD", 5), muted=(5,)))) == 1


# -- stereo sources ----------------------------------------------------------


def test_a_stereo_source_with_both_legs_muted_is_one_finding():
    [f] = _found(_desk(patch=("A", 5), mode="ST", muted=(5, 6)))
    assert "is fed from AES50-A 5-6, which are both muted at the socket" in f.message
    assert f.addresses == ("/ch/3/in/conn/grp", "/io/in/A/5/mute", "/io/in/A/6/mute")


@pytest.mark.parametrize("muted,unmuted,leg", [((5,), (6,), "AES50-A 5"), ((6,), (5,), "AES50-A 6")])
def test_a_stereo_source_with_one_leg_muted_says_which_and_that_one_side_is_silent(
        muted, unmuted, leg):
    [f] = _found(_desk(patch=("A", 5), mode="ST", muted=muted, unmuted=unmuted))
    assert "is a stereo source on AES50-A 5-6" in f.message
    assert f"{leg} is muted at the socket while the other is not" in f.message
    assert "one side of it is silent" in f.message


def test_a_middle_side_source_is_stereo_too():
    [f] = _found(_desk(patch=("A", 5), mode="M/S", muted=(6,), unmuted=(5,)))
    assert "stereo source" in f.message


def test_a_stereo_source_whose_second_leg_was_never_read_is_silent():
    assert _found(_desk(patch=("A", 5), mode="ST", muted=(5,))) == []


def test_a_mono_source_does_not_look_at_the_next_socket():
    v = _desk(patch=("A", 5), mode="M", unmuted=(5,), **{"/io/in/A/6/mute": 1})
    assert _found(v) == []


def test_an_even_socket_never_lends_its_neighbour():
    """WING pairs are odd-even: a strip on socket 6 in ST is not a pair
    with 7."""
    v = _desk(patch=("A", 6), mode="ST", unmuted=(6,), **{"/io/in/A/7/mute": 1})
    assert _found(v) == []


# -- what belongs to another rule --------------------------------------------


def test_a_strip_on_its_alternate_input_is_c004s_to_report():
    v = _desk(muted=(3,))
    v["/ch/3/in/set/altsrc"] = 1
    v["/ch/3/in/conn/altgrp"] = "CRD"
    ids = [f.rule_id for f in run_audit(ConsoleState(v, console_model="wing-compact"))]
    assert "C004" in ids and "C007" not in ids


def test_the_engaged_global_switch_hands_a_strip_with_an_alternate_to_c005():
    v = _desk(muted=(3,))
    v["/ch/3/in/conn/altgrp"] = "CRD"
    v[console_facts.GLOBAL_ALT_SWITCH] = 1
    ids = [f.rule_id for f in run_audit(ConsoleState(v, console_model="wing-compact"))]
    assert "C005" in ids and "C007" not in ids
    v["/ch/3/in/conn/altgrp"] = "OFF"        # nowhere else to be listening
    assert len(_found(v)) == 1


def test_under_a_plan_the_finding_stands():
    """No plan states a socket's mute, so nothing stands the rule down."""
    plan = {"channels": [{"bank": "ch", "channel": 3, "name": "Vox", "fader": {},
                          "patch": {"group": "A", "sockets": [3]}}], "busses": {}}
    state = ConsoleState(_desk(muted=(3,)), console_model="wing-compact")
    assert [f.rule_id for f in run_audit(state, plan=plan) if f.rule_id == "C007"] == ["C007"]


# --------------------------------------------------------------------------
# Watch
# --------------------------------------------------------------------------


def test_watch_raises_a_socket_muted_mid_show_and_clears_it_when_unmuted():
    before = _desk(unmuted=(3,))
    after = _desk(muted=(3,))
    feed = iter(ConsoleState(v, console_model="wing-compact") for v in (before, after, before))
    events = list(watch(lambda: next(feed), rules=list(DEFAULT_RULES), interval=0,
                        max_iterations=3, sleep=lambda _s: None))
    assert "C007" not in [f.rule_id for f in events[0].all_findings]
    assert [f.rule_id for f in events[1].new_findings] == ["C007"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["C007"]


# --------------------------------------------------------------------------
# The read: one more leaf in a node already dumped
# --------------------------------------------------------------------------


def test_the_read_plan_asks_for_the_mute_of_the_groups_that_have_a_head_amp():
    plan = dict(console_read_plan(input_sockets={"LCL": 24, "A": 4, "MOD": 4}))
    assert plan["/io/in/LCL/24/mute"] == "i"
    assert plan["/io/in/A/4/mute"] == "i"
    assert not [a for a in plan if a.startswith("/io/in/MOD/") and a.endswith("/mute")]


def test_the_mute_rides_in_the_node_that_already_carries_phantom_and_width():
    """So a node-dump read pays no request for it."""
    for socket in (1, 24):
        node = bulk_node_for(f"/io/in/LCL/{socket}/mute")
        assert node == bulk_node_for(f"/io/in/LCL/{socket}/vph") == f"/io/in/LCL/{socket}"


def test_a_live_read_takes_the_mute_from_the_dump_and_the_rule_speaks():
    """A factory Compact with channel 3 named and its LCL 3 muted, read
    the way Watch reads it: node dumps, no per-leaf ask for any socket
    mute."""
    values = dict(snap_values(INITIALIZED_COMPACT))
    values["/ch/3/name"] = "Vox"
    values["/io/in/LCL/3/mute"] = 1
    desk = SnapDesk(values)
    inputs, outputs = socket_groups_to_read("wing-compact")
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    assert state.flag("/io/in/LCL/3/mute") is True
    assert not [a for a in desk.gets if a.startswith("/io/in/") and a.endswith("/mute")]
    [f] = [f for f in run_audit(state) if f.rule_id == "C007"]
    assert f.message.startswith('CH 3 "Vox" is fed from LCL 3, which is muted at the socket.')


def test_a_factory_desk_has_no_socket_muted_under_a_strip():
    state = ConsoleState(snap_values(INITIALIZED_COMPACT), console_model="wing-compact")
    assert _rule().check(state) == []


CAPTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.snap"))


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_no_frozen_capture_has_a_socket_muted_under_a_strip_in_use(capture):
    """Factory desks and the desks somebody had set up (a church's
    full-size among them) have no input socket muted under a channel in
    use, and every socket's mute is in these captures to be judged."""
    values = snap_values(capture)
    if len(values) > 100:
        assert "/io/in/LCL/1/mute" in values
    assert _rule().check(ConsoleState(values)) == []
