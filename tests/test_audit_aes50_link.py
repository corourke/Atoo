"""C008 (Stage Box Not Connected Or In Error), C009 (AES50 Stage Box Link Not OK)
and C010 (AES50 Stage Box Firmware Needs Updating): a stage box whose link is
down, in error with nothing patched, or reading UPD, firmware the desk wants
updated (said at INFO only).

A read takes each AES50 port's status (`/$stat/{A,B,C}/stat`: `-`, `OK`, `ERR`,
`UPD`) and used it only to choose which outputs to read. A stage box whose link
has failed takes every input and output on it silent at once, and nothing on a
strip shows it. Desks are built in the test; the live-read tests use a frozen
factory capture, never a show bundle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    RuleScope,
    aes50_port_dependents,
    coverage_caveat,
    read_console_state,
    render_coverage,
    run_audit,
    socket_groups_to_read,
    unanswerable_rule_ids,
)
from atoo.diagnostics import Severity
from atoo.watch import watch
from tests.snap_desk import SnapDesk, snap_values

FIXTURES = Path(__file__).parent / "fixtures"
INITIALIZED_COMPACT = FIXTURES / "console-runs" / "Initialized-Compact.snap"
IDS = {"C008", "C009", "C010"}


def _rule(rule_id):
    return next(r for r in DEFAULT_RULES if r.id == rule_id)


def _strip(base, name, group, socket, **extra) -> dict[str, object]:
    v: dict[str, object] = {
        f"{base}/name": name, f"{base}/in/conn/grp": group, f"{base}/in/conn/in": socket,
        f"{base}/in/set/altsrc": 0, f"{base}/in/conn/altgrp": "OFF",
    }
    v.update(extra)
    return v


def _out(port, socket, source=("BUS", 1)) -> dict[str, object]:
    return {f"/io/out/{port}/{socket}/grp": source[0], f"/io/out/{port}/{socket}/in": source[1]}


def _state(*parts, **status) -> ConsoleState:
    """A desk from `parts`, with the AES50 statuses `status` names
    (`A="ERR"`) and `-` for the others, as a desk with no stage box reads."""
    values: dict[str, object] = {f"/$stat/{port}/stat": "-" for port in "ABC"}
    for part in parts:
        values.update(part)
    for port, word in status.items():
        values[f"/$stat/{port}/stat"] = word
    # An output socket on the port is read, so the reading holds output sockets.
    values.setdefault("/io/out/LCL/1/grp", "OFF")
    values.setdefault("/io/out/LCL/1/in", 0)
    return ConsoleState(values, console_model="wing-compact")


def _found(state, *rule_ids):
    return [f for f in run_audit(state) if f.rule_id in (set(rule_ids) or IDS)]


# --------------------------------------------------------------------------
# The rows
# --------------------------------------------------------------------------


def test_a_dead_link_under_a_patch_is_an_error_and_an_unsettled_one_a_warning():
    c008, c009 = _rule("C008"), _rule("C009")
    assert (c008.severity, c009.severity) == (Severity.ERROR, Severity.WARNING)
    assert c008.category == c009.category == "configuration"
    assert c008.scope is c009.scope is RuleScope.HAZARD


# --------------------------------------------------------------------------
# C008: a port that carries nothing, with something depending on it
# --------------------------------------------------------------------------


def test_a_strip_patched_from_a_port_with_no_stage_box_is_an_error():
    state = _state(_strip("/ch/1", "Kick", "A", 1))
    [f] = _found(state)
    assert (f.rule_id, f.severity, f.title) == ("C008", Severity.ERROR, "Stage Box Not Connected")
    assert f.message == ("Stage box AES50 port A appears to not be connected and can not carry "
                         'the input of CH 1 "Kick".')
    assert f.addresses == ("/$stat/A/stat",)


def test_a_link_in_error_under_two_strips_names_them_and_says_the_audio_is_lost():
    state = _state(_strip("/ch/1", "Kick", "B", 1), _strip("/ch/2", "Snare", "B", 2), B="ERR")
    [f] = _found(state)
    assert (f.rule_id, f.severity, f.title) == ("C008", Severity.ERROR, "Stage Box Link Error")
    assert f.message == ("Stage box AES50 port B reports a link error and can not carry the "
                         'inputs of CH 1 "Kick" and CH 2 "Snare".')


def test_an_output_that_carries_a_source_counts_and_the_outputs_are_read_as_runs():
    state = _state({f"/io/out/A/{n}/grp": "OFF" for n in range(1, 11)},
                   _out("A", 1), _out("A", 2), _out("A", 3), _out("A", 5), _out("C", 1, ("MAIN", 1)),
                   A="OK", C="ERR")
    [f] = _found(state)
    assert f.message == ("Stage box AES50 port C reports a link error and can not carry "
                         "output AES50-C 1.")
    state = _state(_out("A", 1), _out("A", 2), _out("A", 3), _out("A", 5), A="-")
    [f] = _found(state)
    assert f.message == ("Stage box AES50 port A appears to not be connected and can not carry "
                         "outputs AES50-A 1-3, 5.")


def test_strips_and_outputs_on_a_port_are_named_together():
    state = _state(_strip("/ch/7", "Wedge Mic", "A", 3), _out("A", 6))
    [f] = _found(state)
    assert f.message == ("Stage box AES50 port A appears to not be connected and can not carry "
                         'the input of CH 7 "Wedge Mic" or output AES50-A 6.')


def test_a_port_with_many_strips_names_six_and_counts_the_rest():
    parts = [_strip(f"/ch/{n}", f"In {n}", "A", n) for n in range(1, 10)]
    [f] = _found(_state(*parts, A="ERR"))
    assert 'CH 6 "In 6" and 3 more.' in f.message
    assert "CH 7" not in f.message


def test_each_port_is_its_own_finding_and_the_key_is_its_status_address():
    state = _state(_strip("/ch/1", "Kick", "A", 1), _strip("/ch/2", "Snare", "C", 1), C="ERR")
    findings = _found(state)
    assert [(f.rule_id, f.addresses) for f in findings] == [
        ("C008", ("/$stat/A/stat",)), ("C008", ("/$stat/C/stat",))]


# --------------------------------------------------------------------------
# C009: a stage box in error that nothing depends on; C010: UPD
# --------------------------------------------------------------------------


def _upd_state(*parts, live=None, model="wing-compact", device="S16", **status):
    state = _state(*parts, {"/$stat/A/dev": device}, A="UPD", **status)
    return ConsoleState(state.values, console_model=model, live_strips=live)


def test_upd_is_never_a_warning_or_an_error_only_info():
    """A healthy Behringer S32 passing audio reads UPD on
    a full-size WING. UPD is stage-box firmware the desk wants updated; the
    link still passes audio, so it does not raise a hazard."""
    c010 = _rule("C010")
    assert (c010.severity, c010.category, c010.scope, c010.title) == (
        Severity.INFO, "configuration", RuleScope.HAZARD,
        "AES50 Stage Box Firmware Needs Updating")
    strip = _strip("/ch/4", "Bass", "A", 4)
    for live in (None, frozenset(), frozenset({"/ch/4"})):
        findings = run_audit(_upd_state(strip, live=live))
        assert not [f for f in findings if f.severity in (Severity.WARNING, Severity.ERROR)
                    and f.rule_id in IDS]
        [f] = [f for f in findings if f.rule_id in IDS]
        assert (f.rule_id, f.severity) == ("C010", Severity.INFO)
        assert f.addresses == ("/$stat/A/stat",)


def test_upd_with_nothing_patched_says_so():
    [f] = _found(_upd_state(device=""))
    assert f.message == ("AES50-A reports UPD: the desk flags the stage box's firmware as older "
                         "than it expects. Audio can still pass, but preamp remote control and "
                         "dual-port A/B need current stage-box firmware; update the box. Nothing "
                         "is patched from it.")


@pytest.mark.parametrize("model", ["wing", "wing-compact", "wing-rack"])
@pytest.mark.parametrize("device", ["S16", "S32", "SD16", "SD8", "Stage Connect", ""])
def test_upd_is_one_info_line_for_every_console_and_stage_box_and_never_lists_channels(model, device):
    parts = [_strip(f"/ch/{n}", f"In {n}", "A", n) for n in range(1, 19)] + [_out("A", 3)]
    live = frozenset(f"/ch/{n}" for n in range(1, 10))
    [f] = _found(_upd_state(*parts, live=live, model=model, device=device))
    assert (f.rule_id, f.severity) == ("C010", Severity.INFO)
    assert "9 of the 18 strips patched from it are carrying signal, so it is passing audio" in f.message
    assert "carry no audio" not in f.message and "CH 1" not in f.message


def test_upd_names_the_device_and_says_its_firmware_needs_updating():
    """A full-size WING with a healthy S32 on AES50-A, port B
    unplugged: `/$stat/A/dev "S32"`, `stat "UPD"`. UPD is the desk flagging
    the stage box's firmware as older than it expects."""
    strip = _strip("/ch/4", "Bass", "A", 4)
    [f] = _found(_upd_state(strip, live=frozenset({"/ch/4"}), model="wing", device="S32",
                            B="-"))
    assert (f.rule_id, f.severity, f.title) == (
        "C010", Severity.INFO, "AES50 Stage Box Firmware Needs Updating")
    assert f.message == ("AES50-A (S32) reports UPD: the desk flags the stage box's firmware as "
                         "older than it expects. Audio can still pass, but preamp remote control "
                         "and dual-port A/B need current stage-box firmware; update the box. 1 of "
                         "the 1 strips patched from it is carrying signal, so it is passing "
                         "audio.")


def test_upd_with_no_signal_or_no_meters_does_not_claim_the_box_is_down():
    strip = _strip("/ch/4", "Bass", "A", 4)
    [f] = _found(_upd_state(strip, live=frozenset()))
    assert "None of the 1 strips patched from it is carrying signal just now; that may only " \
           "be a quiet stage." in f.message
    [f] = _found(_upd_state(strip, live=None))
    assert "The meters are not being read" in f.message and "no audio" not in f.message


def test_a_link_in_error_with_nothing_patched_is_a_warning_not_an_error():
    [f] = _found(_state(B="ERR"))
    assert (f.rule_id, f.severity) == ("C009", Severity.WARNING)
    assert f.message == ("AES50-B reports a link error (ERR) on a stage box that nothing is "
                         "patched from or to. Nothing in the show is lost yet, but the link will "
                         "not carry audio: check the cable and the stage box.")


def test_a_link_in_error_under_a_patch_is_one_finding_not_two():
    state = _state(_strip("/ch/1", "Kick", "A", 1), A="ERR")
    assert [f.rule_id for f in _found(state)] == ["C008"]


# --------------------------------------------------------------------------
# Silent
# --------------------------------------------------------------------------


def test_a_healthy_link_is_silent():
    assert _found(_state(_strip("/ch/1", "Kick", "A", 1), _out("A", 1), A="OK")) == []


def test_a_port_with_nothing_on_it_and_nothing_patched_is_silent():
    """A stage box that is simply not connected is not an error."""
    assert _found(_state()) == []


def test_silent_when_the_status_was_never_read():
    values = {**_strip("/ch/1", "Kick", "A", 1), **_out("A", 1),
              "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0}
    state = ConsoleState(values, console_model="wing-compact")
    assert _found(state) == []


def test_silent_for_a_status_the_desks_list_does_not_have():
    state = _state(_strip("/ch/1", "Kick", "A", 1), A="LOCKED")
    assert _found(state) == []


def test_an_unpatched_output_is_not_a_dependent():
    state = _state({"/io/out/A/1/grp": "OFF", "/io/out/A/1/in": 0})
    assert _found(state) == []


def test_a_strip_patched_to_a_local_socket_is_not_affected_by_an_aes50_port_in_error():
    assert [f.rule_id for f in _found(_state(_strip("/ch/1", "Kick", "LCL", 1), A="ERR"))] == ["C009"]


def test_a_strip_on_its_alternate_input_is_left_to_c004():
    state = _state(_strip("/ch/1", "Kick", "A", 1, **{"/ch/1/in/set/altsrc": 1}))
    assert _found(state, "C008") == []
    assert "C004" in {f.rule_id for f in run_audit(state)}


def test_a_strip_that_may_follow_the_global_alternate_switch_is_left_to_c005():
    state = _state(_strip("/ch/1", "Kick", "A", 1, **{"/ch/1/in/conn/altgrp": "CRD"}),
                   {console_facts.GLOBAL_ALT_SWITCH: 1})
    assert _found(state, "C008") == []
    assert "C005" in {f.rule_id for f in run_audit(state)}


def test_an_empty_expansion_bay_stays_c003s():
    """C003 owns `CRD` and `MOD`: a strip patched from an empty card slot is
    its finding alone."""
    state = _state(_strip("/ch/1", "Kick", "CRD", 1), {"/cards/$type": "NONE"})
    assert [f.rule_id for f in run_audit(state) if f.rule_id in {"C003", "C008", "C009"}] == ["C003"]


def test_the_routing_rules_do_not_know_the_link_is_down_and_c008_is_what_says_it():
    """A bus patched to a dead stage box's output still reads as routed to
    R002, R005 and R006 -- they follow sockets, not links -- so the finding is
    new, not a duplicate."""
    state = _state({"/bus/1/name": "Wedge", "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": 0.0,
                    **_strip("/ch/1", "Kick", "LCL", 1)},
                   _out("A", 1, ("BUS", 1)), A="ERR")
    ids = {f.rule_id for f in run_audit(state)}
    assert "C008" in ids and not ids & {"R002", "R005", "R006", "R007"}


def test_the_dependents_are_the_strips_by_main_patch_and_the_outputs_with_a_source():
    state = _state(_strip("/ch/2", "Snare", "B", 4), _strip("/aux/1", "Cue", "B", 5),
                   _out("B", 9), {"/io/out/B/10/grp": "OFF", "/io/out/B/10/in": 0})
    [(port, (strips, outputs))] = aes50_port_dependents(state).items()
    assert (port, sorted(strips), outputs) == ("B", ["/aux/1", "/ch/2"], [9])


# --------------------------------------------------------------------------
# A plan does not change a hazard
# --------------------------------------------------------------------------


def test_under_a_plan_a_strip_the_plan_never_names_is_still_reported():
    plan = {"channels": [{"channel": 9, "bank": "ch", "name": "Other",
                          "patch": {"group": "LCL", "sockets": [9]}}]}
    state = _state(_strip("/ch/1", "Kick", "A", 1))
    assert [f.rule_id for f in run_audit(state, plan=plan) if f.rule_id in IDS] == ["C008"]


# --------------------------------------------------------------------------
# What a read that took no output sockets says
# --------------------------------------------------------------------------


def test_a_read_with_no_output_sockets_names_c008_and_c009_as_not_checked():
    state = ConsoleState({"/ch/1/name": "Kick", "/io/in/LCL/1/vph": 0}, console_model="wing-compact")
    assert {"C008", "C009", "C010"} <= set(unanswerable_rule_ids(state))
    assert "C008" in coverage_caveat(state) and "C009" in coverage_caveat(state)
    assert "R006, R011, CV009, C008, C009 and C010 could not be checked" in render_coverage(state)
    nothing = ConsoleState({"/ch/1/name": "Kick"}, console_model="wing-compact")
    assert "C008 (Stage Box Not Connected Or In Error), C009 (AES50 Stage Box Link Not OK)" in \
        render_coverage(nothing)
    with_outputs = ConsoleState({"/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
                                 "/io/in/LCL/1/vph": 0}, console_model="wing-compact")
    assert not {"C008", "C009"} & set(unanswerable_rule_ids(with_outputs))


# --------------------------------------------------------------------------
# Watch: a link fails, recovers, fails again, updates
# --------------------------------------------------------------------------


def test_watch_says_a_link_failed_and_that_it_recovered():
    parts = (_strip("/ch/1", "Kick", "A", 1), _out("A", 2))
    feed = iter([_state(*parts, A="OK"), _state(*parts, A="ERR"), _state(*parts, A="ERR"),
                 _state(*parts, A="UPD"), _state(*parts, A="OK"), _state(*parts, A="-")])
    events = list(watch(lambda: next(feed), rules=list(DEFAULT_RULES), interval=0,
                        max_iterations=6, sleep=lambda _s: None))
    ids = lambda findings: sorted(f.rule_id for f in findings if f.rule_id in IDS)  # noqa: E731
    assert ids(events[0].all_findings) == []
    assert (ids(events[1].new_findings), ids(events[1].cleared_findings)) == (["C008"], [])
    assert (ids(events[2].new_findings), ids(events[2].cleared_findings)) == ([], [])
    assert ids(events[2].all_findings) == ["C008"]
    assert (ids(events[3].new_findings), ids(events[3].cleared_findings)) == (["C010"], ["C008"])
    assert (ids(events[4].new_findings), ids(events[4].cleared_findings)) == ([], ["C010"])
    assert (ids(events[5].new_findings), ids(events[5].cleared_findings)) == (["C008"], [])


# --------------------------------------------------------------------------
# A real read, and the frozen captures
# --------------------------------------------------------------------------


def _read(values, **kw):
    desk = SnapDesk(values)
    inputs, outputs = socket_groups_to_read("wing-compact")
    return read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True, **kw)


def test_a_live_read_takes_the_status_and_the_rule_speaks():
    """A factory Compact with channel 3 patched from AES50-A 1 and the desk
    reporting a link error on A, read the way Watch reads it: node dumps. The
    second pass reads A's outputs because a strip is patched from it."""
    values = dict(snap_values(INITIALIZED_COMPACT))
    values.update({"/ch/3/name": "Vox", "/ch/3/in/conn/grp": "A", "/ch/3/in/conn/in": 1,
                   "/$stat/A/stat": "ERR", "/$stat/B/stat": "-", "/$stat/C/stat": "-"})
    state = _read(values)
    assert state.text("/$stat/A/stat") == "ERR"
    [f] = [f for f in run_audit(state) if f.rule_id in IDS]
    assert f.rule_id == "C008" and f.message == (
        'Stage box AES50 port A reports a link error and can not carry the input of CH 3 "Vox".')


def test_a_live_read_of_a_healthy_stage_box_is_silent():
    values = dict(snap_values(INITIALIZED_COMPACT))
    values.update({"/ch/3/name": "Vox", "/ch/3/in/conn/grp": "A", "/ch/3/in/conn/in": 1,
                   "/$stat/A/stat": "OK", "/$stat/B/stat": "-", "/$stat/C/stat": "-"})
    assert [f for f in run_audit(_read(values)) if f.rule_id in IDS] == []


CAPTURES = sorted(FIXTURES.rglob("*.snap"))


def _ports_in_use(values) -> list[str]:
    """The AES50 ports a capture's strips are patched from, or whose outputs
    carry a source."""
    return sorted({v for a, v in values.items() if a.endswith("/in/conn/grp") and v in ("A", "B", "C")}
                  | {a.split("/")[3] for a, v in values.items()
                     if a.startswith("/io/out/") and a.endswith("/grp")
                     and a.split("/")[3] in ("A", "B", "C") and v != "OFF"})


def _with_status(values, **status):
    out = dict(values)
    out.update({f"/$stat/{port}/stat": status.get(port, "-") for port in "ABC"})
    return ConsoleState(out)


def _link_findings(state):
    """C008 and C009 alone: the whole rule set on a full capture takes seconds."""
    return [f for rule_id in sorted(IDS) for f in _rule(rule_id).check(state)]


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_no_frozen_capture_has_a_link_to_report(capture):
    """Seven captures of real desks, none holding an AES50 status (a snapshot
    does not carry it), so there is nothing for either rule to read and the
    answer on each is 0 findings. That is silence, not a verdict -- the next
    two tests give each capture a status and count the findings."""
    values = snap_values(capture)
    assert _link_findings(ConsoleState(values)) == []
    assert not [a for a in values if a.startswith("/$stat/")]


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_a_frozen_capture_with_its_stage_boxes_reading_ok_has_no_false_positive(capture):
    """Four of the seven have strips and outputs on AES50 stage boxes. With the
    desk reading OK on the ports they use (and `-` on the others, as a desk
    with nothing there does), 0 findings on all seven: no false positive."""
    values = snap_values(capture)
    state = _with_status(values, **{port: "OK" for port in _ports_in_use(values)})
    assert _link_findings(state) == []


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_the_same_capture_with_each_port_in_error_says_so_once_per_port(capture):
    """The rule is not blind on these desks: a link in error under a port a
    capture's strips or outputs depend on is one ERROR for that port, and a
    port nothing is patched to is a WARNING."""
    values = snap_values(capture)
    used = _ports_in_use(values)
    findings = _link_findings(_with_status(values, A="ERR", B="ERR", C="ERR"))
    assert sorted((f.rule_id, f.addresses) for f in findings) == sorted(
        ("C008" if port in used else "C009", (f"/$stat/{port}/stat",)) for port in "ABC")


def test_a_capture_with_its_stage_boxes_unplugged_reports_each_port_once_in_the_whole_audit():
    """Church-Full has 19 strips on AES50-A, outputs on A 33-40 and on B
    25-32. With the desk reading `-` on every port, as it would with the boxes
    unplugged, the whole rule set reports two ERRORs naming them."""
    values = dict(snap_values(FIXTURES / "console-runs" / "Church-Full.snap"))
    findings = [f for f in run_audit(_with_status(values)) if f.rule_id in IDS]
    assert [(f.rule_id, f.severity, f.addresses) for f in findings] == [
        ("C008", Severity.ERROR, ("/$stat/A/stat",)), ("C008", Severity.ERROR, ("/$stat/B/stat",))]
    assert " and 13 more or outputs AES50-A 33-40." in findings[0].message
    # The maintainer's own sentence, from this desk (2026-10-25).
    assert findings[1].message == ("Stage box AES50 port B appears to not be connected and can "
                                   "not carry outputs AES50-B 25-32.")
