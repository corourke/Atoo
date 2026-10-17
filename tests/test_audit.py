"""FR-4/FR-5 proof of concept: rule engine + signal graph, all offline --
no console connection needed (mirrors FR-1.2's "no console present" spirit
for the audit side). Every ConsoleState here is a hand-built address map,
the same substrate a live `read_console_state()` walk produces."""

import pytest

from atoo.audit import (
    ConsoleState,
    DCA_LOW_FADER_DB,
    DEFAULT_RULES,
    FADER_FLOOR_DB,
    FADER_TOLERANCE_DB,
    HEAD_AMP_GAIN_TOLERANCE_DB,
    build_signal_graph,
    diff_against_plan,
    read_console_state,
    render_coverage,
    render_findings,
    render_trace,
    run_audit,
    strip_group_membership,
    trace_signal_path,
)
from atoo.console import OscReply
from atoo.diagnostics import Severity


def _rule_ids(findings):
    return {f.rule_id for f in findings}


def test_no_findings_on_empty_state():
    assert run_audit(ConsoleState({})) == []
    assert render_findings([]) == "No findings -- every rule in this audit passed."


def test_bus_no_inputs():
    state = ConsoleState({
        "/bus/1/name": "Drums",
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        # ch1 doesn't send to bus 1 at all
    })
    findings = run_audit(state)
    assert "R001" in _rule_ids(findings)


def test_bus_no_inputs_clean_when_fed():
    state = ConsoleState({
        "/bus/1/name": "Drums",
        "/ch/1/name": "Kick",
        "/ch/1/send/1/on": 1,
        "/bus/1/main/1/on": 1,
    })
    assert "R001" not in _rule_ids(run_audit(state))


def test_bus_no_output():
    state = ConsoleState({
        "/bus/1/name": "Drums",
        "/ch/1/name": "Kick",
        "/ch/1/send/1/on": 1,
        # no /bus/1/main/*/on, no io.out patched from BUS 1
        # a socket the read DID cover, patched to nothing.
        # Without it this state says nothing about the output patch at
        # all, and the rule now declines to answer rather than asserting
        # a negative from addresses nobody asked for.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    findings = run_audit(state)
    assert "R002" in _rule_ids(findings)


def test_bus_no_output_clean_with_dedicated_output():
    state = ConsoleState({
        "/bus/1/name": "Monitor 1",
        "/ch/1/send/1/on": 1,
        "/io/out/LCL/3/grp": "BUS", "/io/out/LCL/3/in": 1,
    })
    assert "R002" not in _rule_ids(run_audit(state))


def test_matrix_orphan():
    state = ConsoleState({
        "/io/out/LCL/5/grp": "MTX", "/io/out/LCL/5/in": 1,
        "/mtx/1/mute": 0,
        # no channel send.MX1.on
    })
    findings = run_audit(state)
    assert "R003" in _rule_ids(findings)


def test_matrix_orphan_clean_when_fed():
    state = ConsoleState({
        "/io/out/LCL/5/grp": "MTX", "/io/out/LCL/5/in": 1,
        "/ch/1/send/MX1/on": 1,
    })
    assert "R003" not in _rule_ids(run_audit(state))


def test_main_patched_but_unfed():
    state = ConsoleState({
        "/io/out/LCL/1/grp": "MAIN", "/io/out/LCL/1/in": 1,
        "/main/1/mute": 0,
    })
    findings = run_audit(state)
    assert "R004" in _rule_ids(findings)


def test_main_not_patched():
    state = ConsoleState({
        "/ch/1/main/1/on": 1,
        # no io.out entry sourcing MAIN 1
        # a socket the read DID cover, patched to nothing.
        # Without it this state says nothing about the output patch at
        # all, and the rule now declines to answer rather than asserting
        # a negative from addresses nobody asked for.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    findings = run_audit(state)
    assert "R005" in _rule_ids(findings)


def test_main_fully_wired_is_clean():
    state = ConsoleState({
        "/ch/1/main/1/on": 1,
        "/io/out/LCL/1/grp": "MAIN", "/io/out/LCL/1/in": 1,
    })
    findings = run_audit(state)
    assert "R004" not in _rule_ids(findings)
    assert "R005" not in _rule_ids(findings)


def test_a_main_that_reaches_the_pa_through_a_matrix_is_clean():
    """Found on hardware 2026-09-22 (A5), as an ERROR against a correct
    show.

    `examples/conventions.md`: *"Main should be the full mix, EQed so it
    sounds good for a recording. Send to Matrix 1. Matrix 1 takes its feed
    from Main and gets EQed to correct for the room. Patch output to
    internal XLRs 7 and 8."* Main deliberately has no socket of its own.

    That is not an edge case -- it is how you EQ for the room without
    touching the mix you are recording -- so this rule was reporting most
    real desks as broken."""
    state = ConsoleState({
        "/ch/1/main/1/on": 1,
        "/main/1/send/MX1/on": 1,
        "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
    })
    assert "R005" not in _rule_ids(run_audit(state))


def test_a_main_feeding_an_unpatched_matrix_is_still_reported():
    """One more hop, not unlimited faith. If the matrix goes nowhere
    either, the mix still reaches no loudspeaker and that is the whole
    point of the rule."""
    state = ConsoleState({
        "/ch/1/main/1/on": 1,
        "/main/1/send/MX1/on": 1,
        # MX1 patched to nothing
        # a socket the read DID cover, patched to nothing.
        # Without it this state says nothing about the output patch at
        # all, and the rule now declines to answer rather than asserting
        # a negative from addresses nobody asked for.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    assert "R005" in _rule_ids(run_audit(state))


def test_a_main_whose_matrix_send_is_off_is_still_reported():
    """The send has to be ON. A matrix that is patched but not fed by this
    Main does not carry it anywhere."""
    state = ConsoleState({
        "/ch/1/main/1/on": 1,
        "/main/1/send/MX1/on": 0,
        "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
    })
    assert "R005" in _rule_ids(run_audit(state))


def test_phantom_on_unpatched_socket():
    state = ConsoleState({"/io/in/LCL/3/vph": 1})
    findings = run_audit(state)
    assert "C001" in _rule_ids(findings)


def test_phantom_clean_when_patched():
    state = ConsoleState({
        "/io/in/LCL/3/vph": 1,
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 3,
    })
    assert "C001" not in _rule_ids(run_audit(state))


def test_shared_physical_input():
    state = ConsoleState({
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "LCL", "/ch/2/in/conn/in": 1,
    })
    findings = run_audit(state)
    assert "C002" in _rule_ids(findings)


def test_channel_not_in_any_dca():
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    })
    findings = run_audit(state)
    assert "CH001" in _rule_ids(findings)


def test_channel_in_dca_is_clean():
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/ch/1/tags": "#D1",
    })
    assert "CH001" not in _rule_ids(run_audit(state))


def test_dca_fader_closed_with_active_members():
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/tags": "#D1",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/dca/1/fdr": -144.0,
    })
    findings = run_audit(state)
    assert "CH002" in _rule_ids(findings)


def test_dca_open_is_clean():
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/tags": "#D1",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/dca/1/fdr": 0.0,
    })
    assert "CH002" not in _rule_ids(run_audit(state))


def test_mute_group_silencing_routed_member():
    state = ConsoleState({
        "/ch/1/tags": "#M1",
        "/ch/1/send/1/on": 1,
        "/mgrp/1/mute": 1,
    })
    findings = run_audit(state)
    assert "CH003" in _rule_ids(findings)


def test_mute_group_off_is_clean():
    state = ConsoleState({
        "/ch/1/tags": "#M1",
        "/ch/1/send/1/on": 1,
        "/mgrp/1/mute": 0,
    })
    assert "CH003" not in _rule_ids(run_audit(state))


def test_duplicate_channel_names():
    state = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Vox"})
    findings = run_audit(state)
    assert "N001" in _rule_ids(findings)


def test_distinct_channel_names_are_clean():
    state = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Kick"})
    assert "N001" not in _rule_ids(run_audit(state))


def test_duplicate_bus_names():
    state = ConsoleState({"/bus/1/name": "Mix", "/bus/2/name": "Mix"})
    findings = run_audit(state)
    assert "N002" in _rule_ids(findings)


def test_duplicate_name_messages_name_their_objects_readably():
    """The message noun is a separate argument from the rule title, and
    nothing asserted that it is the right word.

    `_rule_duplicate_names` takes (title, noun, ...) precisely so the two
    can differ -- N001 is titled "Duplicate Channel/Aux Names" and
    "channel/auxs" is not a word. Mutating either noun on `main` left all
    1574 tests passing, so the split was load-bearing and unpinned: a
    later edit could quietly restore "2 buss share the name", which is
    what N002 printed on every real duplicate before the split.
    """
    chans = next(f for f in run_audit(ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Vox"}))
                 if f.rule_id == "N001")
    assert "2 channel/aux strips share the name" in chans.message

    busses = next(f for f in run_audit(ConsoleState({"/bus/1/name": "Mix", "/bus/2/name": "Mix"}))
                  if f.rule_id == "N002")
    assert "2 busses share the name" in busses.message


def test_send_on_but_near_silent():
    state = ConsoleState({
        "/ch/1/send/1/on": 1,
        "/ch/1/send/1/lvl": -110.0,
    })
    findings = run_audit(state)
    assert "L001" in _rule_ids(findings)


def test_send_at_unity_is_clean():
    state = ConsoleState({
        "/ch/1/send/1/on": 1,
        "/ch/1/send/1/lvl": 0.0,
    })
    assert "L001" not in _rule_ids(run_audit(state))


def test_send_fully_off_is_not_near_silent():
    # Exactly the -144 floor is "properly off", not "forgotten" -- a
    # different state than the near-silent band this rule targets.
    state = ConsoleState({
        "/ch/1/send/1/on": 1,
        "/ch/1/send/1/lvl": -144.0,
    })
    assert "L001" not in _rule_ids(run_audit(state))


def test_active_strip_fader_at_floor():
    state = ConsoleState({
        "/ch/1/mute": 0,
        "/ch/1/fdr": -144.0,
        "/ch/1/send/1/on": 1,
    })
    findings = run_audit(state)
    assert "L002" in _rule_ids(findings)


def test_muted_strip_at_floor_is_not_flagged_by_l002():
    # Deliberately muted and parked: not a forgotten fader.
    state = ConsoleState({
        "/ch/1/mute": 1,
        "/ch/1/fdr": -144.0,
        "/ch/1/send/1/on": 1,
    })
    assert "L002" not in _rule_ids(run_audit(state))


def test_every_default_rule_has_a_unique_id():
    ids = [r.id for r in DEFAULT_RULES]
    assert len(ids) == len(set(ids))


def test_render_findings_cites_rule_id():
    state = ConsoleState({"/ch/1/name": "Vox", "/ch/2/name": "Vox"})
    text = render_findings(run_audit(state))
    assert "N001" in text


# --------------------------------------------------------------------------
# Signal graph / trace (FR-5)
# --------------------------------------------------------------------------


def _healthy_state():
    return ConsoleState({
        "/ch/5/in/conn/grp": "LCL", "/ch/5/in/conn/in": 3,
        "/ch/5/mute": 0, "/ch/5/fdr": 0.0,
        "/ch/5/send/2/on": 1, "/ch/5/send/2/lvl": 0.0,
        "/bus/2/mute": 0, "/bus/2/fdr": 0.0,
        "/bus/2/main/1/on": 1,
        "/io/out/LCL/1/grp": "MAIN", "/io/out/LCL/1/in": 1,
    })


def test_trace_healthy_path_reaches_output():
    g = build_signal_graph(_healthy_state())
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert result.reachable
    assert result.path[0] == "input:LCL:3"
    assert result.path[-1] == "output:LCL:1"
    assert "OK" in render_trace(result)


def test_trace_breaks_on_muted_channel():
    state = _healthy_state()
    state.values["/ch/5/mute"] = 1
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert not result.reachable
    assert result.path[-1] == "strip:/ch/5"
    assert "muted" in result.break_reason
    assert "BROKEN" in render_trace(result)


def test_trace_breaks_on_send_off():
    state = _healthy_state()
    state.values["/ch/5/send/2/on"] = 0
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert not result.reachable
    assert "send" in result.break_reason and "off" in result.break_reason


def test_trace_reports_no_path_when_nothing_connects():
    state = ConsoleState({"/ch/5/in/conn/grp": "LCL", "/ch/5/in/conn/in": 3})
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert not result.reachable
    assert "no routing path exists" in result.break_reason


def test_trace_breaks_on_bus_muted():
    state = _healthy_state()
    state.values["/bus/2/mute"] = 1
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert not result.reachable
    assert result.path[-1] == "bus:2"
    assert "muted" in result.break_reason


def test_trace_pon_keeps_pre_send_open_on_muted_channel():
    """A muted channel with a PRE-mode send whose .pon ("pre
    always on") is set still traces as reachable -- .pon keeps a pre-fader
    send alive on real hardware precisely so a muted vocal can still feed
    IEMs/monitors."""
    state = _healthy_state()
    state.values["/ch/5/mute"] = 1
    state.values["/ch/5/send/2/mode"] = "PRE"
    state.values["/ch/5/send/2/pon"] = 1
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert result.reachable
    assert "OK" in render_trace(result)


def test_trace_pon_does_not_bypass_mute_for_post_mode_send():
    """.pon only protects pre-fader taps -- a POST-mode send with .pon set
    on a muted channel is still closed."""
    state = _healthy_state()
    state.values["/ch/5/mute"] = 1
    state.values["/ch/5/send/2/mode"] = "POST"
    state.values["/ch/5/send/2/pon"] = 1
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert not result.reachable
    assert result.path[-1] == "strip:/ch/5"
    assert "muted" in result.break_reason


def test_trace_pon_does_not_bypass_fader_floor():
    """.pon bypasses only the mute gate, not the strip's fader-floor
    gate -- a PRE send with .pon set is still closed if the strip's own
    fader is at the floor."""
    state = _healthy_state()
    state.values["/ch/5/mute"] = 1
    state.values["/ch/5/fdr"] = FADER_FLOOR_DB
    state.values["/ch/5/send/2/mode"] = "PRE"
    state.values["/ch/5/send/2/pon"] = 1
    g = build_signal_graph(state)
    result = trace_signal_path(g, "input:LCL:3", "output:LCL:1")
    assert not result.reachable
    assert result.path[-1] == "strip:/ch/5"
    assert "floor" in result.break_reason


# --------------------------------------------------------------------------
# Conventions diff (FR-4.1, first slice: an earlier change) -- `diff_against_plan`
# compares live state against what a compiled plan says a channel should
# be, for five plan-channel fields. A plan channel entry here is built
# with the same shape as plan_schema.py's EXAMPLE_CHANNEL, trimmed to just
# what each test needs.
# --------------------------------------------------------------------------


def _plan_channel(**overrides) -> dict:
    entry = {
        "channel": 1, "bank": "ch", "name": "Kick", "color": None,
        "source": {"input": "Kick", "type": "Mic", "model": "", "stereo": False, "phantom": False},
        # No patch stated by default -- individual tests set this when
        # they actually want CV005 in play, same "null means no
        # assertion" rule as every other field here.
        "patch": {"group": None, "sockets": [], "stated": False},
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": None, "muted": None},
        "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
        "provenance": {},
    }
    entry.update(overrides)
    return entry


def _diff_rule_ids(findings):
    return {f.rule_id for f in findings}


def test_diff_mute_mismatch_cites_provenance():
    plan = {"channels": [_plan_channel(
        fader={"fader_db": None, "muted": True},
        provenance={"fader": "Drums convention: kick starts muted at top of show"},
    )]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/mute": 0})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV001"}
    assert "Drums convention" in findings[0].detail


def test_diff_mute_match_is_clean():
    plan = {"channels": [_plan_channel(fader={"fader_db": None, "muted": True})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/mute": 1})
    assert diff_against_plan(state, plan) == []


def test_diff_fader_mismatch_beyond_tolerance():
    plan = {"channels": [_plan_channel(fader={"fader_db": -6.0, "muted": None})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/fdr": -6.0 - FADER_TOLERANCE_DB - 0.1})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV002"}


def test_diff_fader_mismatch_within_tolerance_is_clean():
    plan = {"channels": [_plan_channel(fader={"fader_db": -6.0, "muted": None})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/fdr": -6.0 - FADER_TOLERANCE_DB + 0.1})
    assert diff_against_plan(state, plan) == []


def test_diff_dca_membership_mismatch():
    plan = {"channels": [_plan_channel(dca=["Drums"])]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/dca/1/name": "Drums",
        # ch1 has no "#D1" tag -- plan says it should belong to Drums
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV003"}


def test_diff_dca_membership_match_is_clean():
    plan = {"channels": [_plan_channel(dca=["Drums"])]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/tags": "#D1",
        "/dca/1/name": "Drums",
    })
    assert diff_against_plan(state, plan) == []


def test_diff_dca_name_not_resolved_is_silent():
    """A plan DCA name that matches no live DCA (or more than one) is a
    different, not-yet-built check -- skip without crashing or reporting
    anything about the name mismatch itself."""
    plan = {"channels": [_plan_channel(dca=["Nonexistent Group"])]}
    state = ConsoleState({"/ch/1/name": "Kick", "/dca/1/name": "Drums"})
    assert diff_against_plan(state, plan) == []


def test_diff_mute_group_membership_mismatch():
    plan = {"channels": [_plan_channel(mute_group=["Drums"])]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/mgrp/1/name": "Drums",
        # ch1 has no "#M1" tag -- plan says it should belong to Drums
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV004"}


def test_diff_mute_group_membership_match_is_clean():
    plan = {"channels": [_plan_channel(mute_group=["Drums"])]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/tags": "#M1",
        "/mgrp/1/name": "Drums",
    })
    assert diff_against_plan(state, plan) == []


def test_diff_patch_mismatch():
    plan = {"channels": [_plan_channel(patch={"group": "A", "sockets": [5], "stated": True})]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 7,
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV005"}


def test_diff_patch_match_is_clean():
    plan = {"channels": [_plan_channel(patch={"group": "A", "sockets": [5], "stated": True})]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 5,
    })
    assert diff_against_plan(state, plan) == []


def test_diff_null_plan_field_produces_no_finding_even_when_live_is_surprising():
    # fader.muted is None (the conventions didn't say) -- CV001 compares
    # only a stated mute, so it says nothing. CV017 does:
    # apply writes an unstated mute OFF (`console_facts.MUTED_DEFAULT`), so a
    # muted channel is muted against the plan as applied.
    plan = {"channels": [_plan_channel(fader={"fader_db": None, "muted": None})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/mute": 1})
    assert _diff_rule_ids(diff_against_plan(state, plan)) == {"CV017"}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/mute": 0})
    assert diff_against_plan(state, plan) == []


def test_diff_skips_channel_whose_base_was_never_read():
    plan = {"channels": [_plan_channel(fader={"fader_db": None, "muted": True})]}
    state = ConsoleState({})  # /ch/1/name never read at all
    assert diff_against_plan(state, plan) == []


# --------------------------------------------------------------------------
# Conventions diff, the extension: bus_sends, main_routes, and a
# narrow slice of processing -- CV006/007/008. Same fixture helper and
# silent-skip discipline as CV001-005 above.
# --------------------------------------------------------------------------


def test_diff_bus_send_match_is_clean():
    plan = {"channels": [_plan_channel(
        bus_sends=[{"bus": "Drums", "mode": "pre", "level_db": -6.0}],
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/bus/1/name": "Drums",
        "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": -6.0, "/ch/1/send/1/mode": "PRE",
    })
    assert diff_against_plan(state, plan) == []


def test_diff_bus_send_level_mismatch():
    plan = {"channels": [_plan_channel(
        bus_sends=[{"bus": "Drums", "mode": None, "level_db": -6.0}],
        provenance={"bus_sends": "Busses: Drums (pre, -6dB)"},
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/bus/1/name": "Drums",
        "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": -6.0 - FADER_TOLERANCE_DB - 0.1,
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV006"}
    assert "Busses: Drums" in findings[0].detail  # plan provenance is cited


def test_diff_bus_send_off_mismatch():
    plan = {"channels": [_plan_channel(
        bus_sends=[{"bus": "Drums", "mode": None, "level_db": None}],
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/bus/1/name": "Drums",
        "/ch/1/send/1/on": 0,  # plan states a send, live shows it off
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV006"}
    assert "reads off" in findings[0].detail


def test_diff_bus_send_mode_mismatch():
    plan = {"channels": [_plan_channel(
        bus_sends=[{"bus": "Drums", "mode": "post", "level_db": None}],
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/bus/1/name": "Drums",
        "/ch/1/send/1/on": 1, "/ch/1/send/1/mode": "PRE",
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV006"}
    assert "mode" in findings[0].detail


def test_diff_bus_send_unresolved_bus_name_is_silent():
    """A plan bus name that matches no live bus (or more than one) is a
    different, not-yet-built check -- skip without crashing or reporting
    anything about the name mismatch itself, same precedent as DCA/
    mute-group name resolution."""
    plan = {"channels": [_plan_channel(
        bus_sends=[{"bus": "Nonexistent Bus", "mode": "pre", "level_db": 0.0}],
    )]}
    state = ConsoleState({"/ch/1/name": "Kick", "/bus/1/name": "Drums"})
    assert diff_against_plan(state, plan) == []


def test_diff_main_route_match_is_clean():
    plan = {"channels": [_plan_channel(main_routes=[{"index": 1}])]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/main/1/on": 1})
    assert diff_against_plan(state, plan) == []


def test_diff_main_route_mismatch():
    plan = {"channels": [_plan_channel(main_routes=[{"index": 1}])]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/main/1/on": 0})
    findings = diff_against_plan(state, plan)
    # That route was Kick's only planned path, so CV016 says it and CV007
    # stands down: a strip cut off from everything is one row.
    assert _diff_rule_ids(findings) == {"CV016"}


def test_diff_main_route_the_plan_does_not_list_but_the_desk_has_on():
    """2026-09-27: `main_routes` is the complete statement of a strip's
    direct Main routing, and apply switches every unlisted Main off. A
    planned channel still on the factory's Main 1 -- a desk applied before
    that fix, or touched since -- is the click on the PA."""
    plan = {"channels": [_plan_channel(main_routes=[])]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/main/1/on": 1,
                          "/ch/1/main/2/on": 0})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV007"}
    assert findings[0].addresses == ("/ch/1/main/1/on",)
    assert "no direct route" in findings[0].detail


def test_diff_main_route_unlisted_and_off_is_clean():
    plan = {"channels": [_plan_channel(main_routes=[{"index": 2}])]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/main/1/on": 0,
                          "/ch/1/main/2/on": 1, "/ch/1/main/3/on": 0})
    assert diff_against_plan(state, plan) == []


def test_diff_main_route_unread_is_not_a_finding():
    plan = {"channels": [_plan_channel(main_routes=[])]}
    state = ConsoleState({"/ch/1/name": "Kick"})
    assert diff_against_plan(state, plan) == []


def test_diff_processing_trim_match_is_clean():
    plan = {"channels": [_plan_channel(processing={"hpf_hz": None, "preset": None, "trim_db": 3.0})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/in/set/trim": 3.0})
    assert diff_against_plan(state, plan) == []


def test_diff_processing_trim_mismatch():
    plan = {"channels": [_plan_channel(processing={"hpf_hz": None, "preset": None, "trim_db": 3.0})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/in/set/trim": 3.0 - FADER_TOLERANCE_DB - 0.1})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV008"}
    assert "trim" in findings[0].detail


def test_diff_processing_invert_mismatch():
    plan = {"channels": [_plan_channel(processing={"hpf_hz": None, "preset": None, "invert": True})]}
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/in/set/inv": 0})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV008"}
    assert "invert" in findings[0].detail


def test_diff_processing_gain_db_mismatch_on_vph_capable_group():
    plan = {"channels": [_plan_channel(
        patch={"group": "A", "sockets": [5], "stated": True},
        processing={"hpf_hz": None, "preset": None, "gain_db": 20.0},
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 5,
        "/io/in/A/5/g": 20.0 + HEAD_AMP_GAIN_TOLERANCE_DB + 1.0,
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV008"}
    assert "gain" in findings[0].detail


def test_diff_processing_gain_db_silent_when_group_not_vph_capable():
    """gain_db is stated and clearly contradicted, but the channel is
    patched to a group with no confirmed head-amp-gain address (only
    LCL/A/B/C carry `.g`, apply.py's _VPH_CAPABLE_GROUPS) -- skip
    silently, same discipline as an unresolved name."""
    plan = {"channels": [_plan_channel(
        patch={"group": "USB", "sockets": [1], "stated": True},
        processing={"hpf_hz": None, "preset": None, "gain_db": 20.0},
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "USB", "/ch/1/in/conn/in": 1,
    })
    assert diff_against_plan(state, plan) == []


def test_diff_processing_filter_family_is_diffed_with_the_readback_tolerance():
    """hpf_hz/hi_cut_hz/tilt_db (the {base}/flt/* family) are compared: a
    wildly contradicting live reading is one finding per filter, naming the
    leaf, and a reading at the desk's nearest step is not a finding.
    `tests/test_audit_processing_plan.py` has the rest."""
    plan = {"channels": [_plan_channel(
        processing={"hpf_hz": 80.0, "preset": None, "hi_cut_hz": 12000.0, "tilt_db": 3.0},
    )]}
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/flt/lcf": 500.0, "/ch/1/flt/hcf": 2000.0, "/ch/1/flt/tilt": -3.0,
    })
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV008"}
    assert [f.addresses for f in findings] == [("/ch/1/flt/lcf",), ("/ch/1/flt/hcf",),
                                                ("/ch/1/flt/tilt",)]
    near = ConsoleState({"/ch/1/name": "Kick", "/ch/1/flt/lcf": 80.5, "/ch/1/flt/hcf": 12018.0,
                         "/ch/1/flt/tilt": 3.0})
    assert diff_against_plan(near, plan) == []


# --------------------------------------------------------------------------
# diff_against_plan -- an earlier change: undeclared/stray physical output patches.
# The maintainer's real finding: Drums/Drums Comp (busses 5/6) reached local
# outputs 5/6 on a real console with neither the plan nor apply.py ever
# having asked for it -- CV009 exists to catch exactly this.
# --------------------------------------------------------------------------


def _bus_with_dedicated_output(index: int, group: str, sockets: list[int]) -> dict:
    return {
        "index": index,
        "destinations": [{
            "type": "dedicated_output", "label": None,
            "socket": {"group": group, "sockets": sockets},
            "sockets": [{"group": group, "sockets": sockets}],
        }],
    }


def test_diff_undeclared_output_patch_is_flagged():
    """A physical socket carrying real routing (not OFF) that no bus or
    output in the plan claims at all -- the exact shape of the maintainer's
    Drums/Drums Comp finding."""
    plan = {"channels": [], "busses": {}, "outputs": {}}
    state = ConsoleState({"/io/out/LCL/5/grp": "BUS", "/io/out/LCL/5/in": 9})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV009"}
    assert "LCL 5" in findings[0].detail
    assert "no bus or output in the plan" in findings[0].detail


def test_diff_declared_output_patch_match_is_clean():
    """MON2 (bus index 2), single-socket dedicated output at LCL 2 --
    the slot math says that's raw `in=3` (2*2-1), not 2."""
    plan = {"channels": [], "busses": {"MON2": _bus_with_dedicated_output(2, "LCL", [2])}, "outputs": {}}
    state = ConsoleState({"/io/out/LCL/2/grp": "BUS", "/io/out/LCL/2/in": 3})
    assert diff_against_plan(state, plan) == []


def test_diff_declared_output_patch_mismatch_is_flagged():
    """Same MON2 bus, but the console reads a different bus's slot --
    exactly what a stale/overwritten patch looks like."""
    plan = {"channels": [], "busses": {"MON2": _bus_with_dedicated_output(2, "LCL", [2])}, "outputs": {}}
    state = ConsoleState({"/io/out/LCL/2/grp": "BUS", "/io/out/LCL/2/in": 5})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV009"}
    assert "routes this socket to BUS 3" in findings[0].detail
    assert "reads BUS 5" in findings[0].detail


def test_diff_output_socket_never_read_produces_no_finding():
    """A physical socket the caller never asked `read_console_state` to
    walk (no confirmed default socket count, per that function's own
    docstring) simply isn't in `state` at all -- silently skipped, not
    reported as a mismatch against nothing."""
    plan = {"channels": [], "busses": {"MON2": _bus_with_dedicated_output(2, "LCL", [2])}, "outputs": {}}
    state = ConsoleState({})
    assert diff_against_plan(state, plan) == []


def test_diff_unpatched_output_socket_produces_no_finding():
    """grp == OFF (or simply never patched) isn't "stray routing" -- the
    socket carries nothing, so there's nothing to flag even if the plan
    never mentions it either."""
    plan = {"channels": [], "busses": {}, "outputs": {}}
    state = ConsoleState({"/io/out/LCL/9/grp": "OFF"})
    assert diff_against_plan(state, plan) == []


def test_diff_undeclared_output_patch_via_output_entry():
    """The same rule covers a Main/Matrix `## Outputs` entry, not just a
    bus's own dedicated output -- Matrix 1's L slot (2*1-1=1) declared at
    LCL 7, console reads LCL 8 (Matrix 1's R slot, 2*1=2) instead."""
    plan = {"channels": [], "busses": {}, "outputs": {
        "Matrix": {"kind": "matrix", "index": 1, "socket": {"group": "LCL", "sockets": [7]},
                   "sockets": [{"group": "LCL", "sockets": [7]}]},
    }}
    state = ConsoleState({"/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 2})
    findings = diff_against_plan(state, plan)
    assert _diff_rule_ids(findings) == {"CV009"}
    assert "routes this socket to MTX 1" in findings[0].detail


def test_diff_stereo_output_socket_gets_differentiated_lr_values():
    """A stereo destination's two sockets must be checked against
    DIFFERENT expected values, not the same one duplicated --
    LCL 7 (position 0, L) and LCL 8 (position 1, R) of Matrix 1."""
    plan = {"channels": [], "busses": {}, "outputs": {
        "Matrix": {"kind": "matrix", "index": 1, "socket": {"group": "LCL", "sockets": [7, 8]},
                   "sockets": [{"group": "LCL", "sockets": [7, 8]}]},
    }}
    state = ConsoleState({
        "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
        "/io/out/LCL/8/grp": "MTX", "/io/out/LCL/8/in": 2,
    })
    assert diff_against_plan(state, plan) == []


def test_diff_output_patch_check_does_not_crash_on_an_unresolved_channel_patch():
    """The bug this rule's own implementation had to route around: calling
    apply.py's full write-target builder against a plan with an
    unresolved channel patch (patch.sockets == [], perfectly normal for a
    plan mid-generation) used to raise IndexError. This is exactly what
    _plan_channel()'s own default patch looks like -- every other test in
    this file already exercises it without a socket, so this just asserts
    the output-patch rule specifically survives it too."""
    plan = {"channels": [_plan_channel()], "busses": {}, "outputs": {}}
    state = ConsoleState({"/ch/1/name": "Kick"})
    assert diff_against_plan(state, plan) == []


# --------------------------------------------------------------------------
# read_console_state -- an earlier change: a live console reply is multi-arg, not a
# bare value, and reading args[0] unconditionally broke on any reply whose
# first argument isn't the type this project actually wants.
# --------------------------------------------------------------------------

class FakeConsole:
    """Replies exactly the way real WING hardware does for a leaf read:
    a multi-arg reply for fader/level ("fader"-type, `,sff`) and enum-ish
    string fields (`,sfi` for e.g. mute), a single-arg reply for a plain
    string/int otherwise. `replies` is address -> OscReply, addresses not
    present answer with a transport error (mirrors an unreachable/absent
    node) rather than crashing the test."""

    def __init__(self, replies: dict[str, OscReply]):
        self.replies = replies

    def get(self, address: str) -> OscReply | None:
        return self.replies.get(
            address, OscReply(address=address, typetag="SOCKET_ERROR", args=[])
        )


def test_read_console_state_reads_a_fader_at_negative_infinity():
    # Confirmed shape (Behringer's WING_Remote-Protocols-3.1-03.pdf
    # p21, and this project's own parameter map, which documents "-oo"
    # as WING's own notation for -infinity dB): a fader/level reply is
    # `,sff` -- [raw-text, raw fraction, real dB value]. At -infinity,
    # the raw-text argument is literally the string "-oo", which a naive
    # `args[0]` read handed straight to `float()`, crashing with
    # "could not convert string to float: '-oo'" the moment a real
    # console had a muted/fully-down channel -- exactly what happened on
    # the first live `atoo ui`/`atoo audit` run against real
    # hardware.
    console = FakeConsole({
        "/ch/1/fdr": OscReply(address="/ch/1/fdr", typetag="sff", args=["-oo", 0.0, -144.0]),
    })
    state = read_console_state(console, channels=1, aux=0, buses=0, mains=0,
                                matrices=0, dcas=0, mute_groups=0)
    assert state.number("/ch/1/fdr") == -144.0


def test_read_console_state_reads_ordinary_multi_arg_replies_correctly():
    console = FakeConsole({
        "/ch/1/name": OscReply(address="/ch/1/name", typetag="s", args=["Kick"]),
        "/ch/1/mute": OscReply(address="/ch/1/mute", typetag="sfi", args=["1", 1.0, 1]),
        "/ch/1/fdr": OscReply(address="/ch/1/fdr", typetag="sff", args=["-2.0", 0.7, -2.0]),
        "/ch/1/tags": OscReply(address="/ch/1/tags", typetag="s", args=["#D1"]),
        "/ch/1/in/conn/grp": OscReply(address="/ch/1/in/conn/grp", typetag="s", args=["A"]),
        "/ch/1/in/conn/in": OscReply(address="/ch/1/in/conn/in", typetag="i", args=[5]),
    })
    state = read_console_state(console, channels=1, aux=0, buses=0, mains=0,
                                matrices=0, dcas=0, mute_groups=0)
    assert state.text("/ch/1/name") == "Kick"
    assert state.flag("/ch/1/mute") is True
    assert state.number("/ch/1/fdr") == -2.0
    assert state.text("/ch/1/tags") == "#D1"
    assert state.text("/ch/1/in/conn/grp") == "A"
    # The console REPORTS 5 for a connector it would accept a 6
    # for, so a ConsoleState holds 6 -- the socket the desk is really on.
    # Every consumer of this state (CV005's patch diff, the `patch`
    # watch condition, the Watch UI) was one lower than the truth before
    # this correction; see console_facts.correct_readback_index.
    assert state.number("/ch/1/in/conn/in") == 6


def test_read_console_state_skips_an_address_the_console_errors_on():
    console = FakeConsole({})  # every address answers SOCKET_ERROR
    state = read_console_state(console, channels=1, aux=0, buses=0, mains=0,
                                matrices=0, dcas=0, mute_groups=0)
    assert state.get("/ch/1/name") is None


# --- Strip_group_membership, shared with watch conditions -----


def test_strip_group_membership_reads_the_tag_for_each_kind():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1,#M3",
        "/dca/1/name": "Drums", "/dca/2/name": "FX",
        "/mgrp/3/name": "Band", "/mgrp/4/name": "Wireless",
    })
    assert strip_group_membership(state, "/ch/1", "dca", "Drums") is True
    assert strip_group_membership(state, "/ch/1", "dca", "FX") is False
    assert strip_group_membership(state, "/ch/1", "mute_group", "Band") is True
    assert strip_group_membership(state, "/ch/1", "mute_group", "Wireless") is False


def test_strip_group_membership_matches_group_names_case_insensitively():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1", "/dca/1/name": "Drums",
    })
    assert strip_group_membership(state, "/ch/1", "dca", "drums") is True


def test_strip_group_membership_is_none_when_the_name_does_not_resolve():
    # Neither True nor False: an unknown or ambiguous group name is a
    # different, not-yet-built check, the same precedent every name
    # resolution in this module follows. A caller must not read None as a
    # violation.
    unknown = ConsoleState({"/ch/1/tags": "#D1", "/dca/1/name": "Drums"})
    assert strip_group_membership(unknown, "/ch/1", "dca", "Guitars") is None
    ambiguous = ConsoleState({
        "/ch/1/tags": "#D1", "/dca/1/name": "Drums", "/dca/2/name": "Drums",
    })
    assert strip_group_membership(ambiguous, "/ch/1", "dca", "Drums") is None


def test_strip_group_membership_rejects_an_unknown_kind():
    state = ConsoleState({"/ch/1/tags": "#D1", "/dca/1/name": "Drums"})
    with pytest.raises(ValueError, match="unknown group kind"):
        strip_group_membership(state, "/ch/1", "bus_send", "Drums")


# --------------------------------------------------------------------------
# The 2026-09-23 catalogue reconciliation: predicates that changed with
# the maintainer's hand edit of docs/developer/audit-rules.md.
# --------------------------------------------------------------------------


def test_a_bus_reaching_an_output_through_main_and_a_matrix_is_clean():
    """R002, *"no route to a physical output (either directly, through
    a Main bus or through a Matrix bus or any other indirect
    combination.)"* -- three hops, which is `examples/conventions.md`'s
    own rig: a bus into Main, Main into Matrix 1, Matrix 1 out to the
    XLRs. One hop reported it as a bus going nowhere."""
    state = ConsoleState({
        "/bus/1/name": "Drums", "/bus/1/main/1/on": 1,
        "/main/1/send/MX1/on": 1,
        "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
    })
    assert "R002" not in _rule_ids(run_audit(state))


def test_a_bus_into_a_main_that_goes_nowhere_is_still_reported():
    """Not unlimited faith in a Main: drop the Matrix patch and the mix
    still reaches no loudspeaker."""
    state = ConsoleState({
        "/bus/1/name": "Drums", "/bus/1/main/1/on": 1,
        "/main/1/send/MX1/on": 1,
        # MX1 patched to nothing
        # a socket the read DID cover, patched to nothing.
        # Without it this state says nothing about the output patch at
        # all, and the rule now declines to answer rather than asserting
        # a negative from addresses nobody asked for.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    assert "R002" in _rule_ids(run_audit(state))


def test_bus_output_reachability_does_not_spin_on_a_cycle():
    """A bus into a Main, the Main into a Matrix, and -- however it got
    there -- routing that leads back. The fixpoint adds a node once and
    never revisits it, so this terminates rather than hanging the audit."""
    state = ConsoleState({
        "/bus/1/name": "Drums", "/bus/1/main/1/on": 1, "/bus/1/send/MX1/on": 1,
        "/main/1/send/MX1/on": 1, "/main/2/send/MX1/on": 1,
        "/bus/2/name": "Ring", "/bus/2/main/1/on": 1, "/bus/2/main/2/on": 1,
        # A socket the read DID cover, patched to nothing.
        # Without it this state says nothing about the output patch at
        # all, and the rule now declines to answer rather than asserting
        # a negative from addresses nobody asked for.
        "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0,
    })
    assert "R002" in _rule_ids(run_audit(state))


def test_a_muted_bus_that_is_properly_patched_is_not_a_bus_with_no_output():
    """R002 asks whether the ROUTING exists, not whether signal is
    flowing -- which is why it does not reuse the signal graph, whose
    edges close on a mute. A muted bus reaching the PA is L002's
    business at most, never "this bus goes nowhere"."""
    state = ConsoleState({
        "/bus/2/name": "MON1", "/bus/2/mute": 1, "/bus/2/fdr": 0.0,
        "/io/out/LCL/3/grp": "BUS", "/io/out/LCL/3/in": 3,
    })
    assert "R002" not in _rule_ids(run_audit(state))


def test_phantom_on_a_socket_feeding_a_user_patch_is_not_flagged():
    """C001, *"patched to no channel or user patch"*. A condenser going
    straight into a USER PATCH slot -- no strip in between -- still needs
    its 48V."""
    state = ConsoleState({
        "/io/in/LCL/9/vph": 1,
        "/io/in/USR/25/user/grp": "LCL", "/io/in/USR/25/user/in": 9,
    })
    assert "C001" not in _rule_ids(run_audit(state))


def test_phantom_on_a_socket_a_user_patch_does_not_take_is_still_flagged():
    state = ConsoleState({
        "/io/in/LCL/9/vph": 1,
        "/io/in/USR/25/user/grp": "LCL", "/io/in/USR/25/user/in": 4,
    })
    assert "C001" in _rule_ids(run_audit(state))


def _stereo_pair(mode_odd, *, odd=5, mode_even=None):
    """A strip patched to A `odd`, 48V on both sockets of the pair, and
    the source width `apply` writes (`mode_odd` on the odd socket, the
    same on the even one unless told otherwise)."""
    values = {
        "/ch/7/in/conn/grp": "A", "/ch/7/in/conn/in": odd,
        f"/io/in/A/{odd}/vph": 1, f"/io/in/A/{odd + 1}/vph": 1,
    }
    if mode_odd is not None:
        values[f"/io/in/A/{odd}/mode"] = mode_odd
        values[f"/io/in/A/{odd + 1}/mode"] = mode_even or mode_odd
    return ConsoleState(values)


@pytest.mark.parametrize("mode", ["ST", "M/S"])
def test_phantom_on_the_even_socket_of_a_stereo_source_is_not_flagged(mode):
    """A stereo strip names only the odd socket of its pair;
    the even one is taken because the source is in a two-socket width.
    The Demo show's overheads -- OH L/OH R on A 5-6, both condensers --
    read as 48V on an unpatched A 6 on a correctly applied desk."""
    assert "C001" not in _rule_ids(run_audit(_stereo_pair(mode)))


def test_phantom_on_the_socket_after_a_mono_source_is_still_flagged():
    findings = [f for f in run_audit(_stereo_pair("M")) if f.rule_id == "C001"]
    assert [f.addresses for f in findings] == [("/io/in/A/6/vph",)]


def test_phantom_after_a_source_whose_width_was_never_read_is_still_flagged():
    """No width read is no evidence of a pair: the rule says what it saw."""
    assert "C001" in _rule_ids(run_audit(_stereo_pair(None)))


def test_a_stereo_width_on_an_even_socket_does_not_take_the_next_one():
    """WING pairs are odd-even (`console_facts.STEREO_PAIR_RULE`): a strip
    patched to A 6 in ST is A 5-6, never A 6-7."""
    state = _stereo_pair("ST", odd=6)
    findings = [f for f in run_audit(state) if f.rule_id == "C001"]
    assert [f.addresses for f in findings] == [("/io/in/A/7/vph",)]


def test_a_user_signal_slot_does_not_excuse_phantom_on_a_socket():
    """USR 1-24 are USER SIGNALS, whose source is a STRIP, not a jack
    (`docs/reference/wing-console-model.md`) -- so `grp: CH, in: 9` is
    channel 9, and says nothing at all about LCL 9."""
    state = ConsoleState({
        "/io/in/LCL/9/vph": 1,
        "/io/in/USR/1/user/grp": "LCL", "/io/in/USR/1/user/in": 9,
    })
    assert "C001" in _rule_ids(run_audit(state))


def test_the_usr_group_is_not_counted_as_a_physical_socket():
    """It lives in `/io/in` and the audit reads it, but there is no such
    jack on any panel -- `render_coverage` must not claim to have read
    thirty-two of them."""
    state = ConsoleState({
        "/io/in/LCL/1/vph": 0,
        "/io/in/USR/25/user/grp": "LCL", "/io/in/USR/25/user/in": 1,
    })
    assert "USR" not in render_coverage(state)
    assert "LCL 1" in render_coverage(state)


def _dca_at(fader_db):
    return ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1", "/ch/1/send/1/on": 1,
        "/dca/1/name": "Drums", "/dca/1/fdr": fader_db,
    })


def test_sp_ch002s_threshold_is_the_one_the_catalogue_states():
    """*"A DCA's fader is set low (<= -20dB)..."*. Spelled out rather than
    read off the constant, so that moving the constant moves this test's
    verdict instead of moving its expectation with it."""
    assert DCA_LOW_FADER_DB == -20.0


def test_a_dca_twenty_db_down_with_active_members_is_reported():
    """The threshold was the floor (-144dB), which only ever caught a DCA
    pulled all the way off. A DCA at -20 is inaudible in the mix it
    controls and every member under it looks perfectly normal."""
    assert "CH002" in _rule_ids(run_audit(_dca_at(-20.0)))
    assert "CH002" in _rule_ids(run_audit(_dca_at(-40.0)))


def test_a_dca_just_above_the_threshold_is_not_reported():
    assert "CH002" not in _rule_ids(run_audit(_dca_at(-19.0)))
    assert "CH002" not in _rule_ids(run_audit(_dca_at(0.0)))


def test_a_low_dca_whose_members_are_all_untouched_is_not_reported():
    """The members have to be in use. A DCA pulled down over factory
    strips is a DCA over nothing."""
    state = ConsoleState({
        "/ch/1/tags": "#D1", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/ch/1/main/1/on": 1,
        "/dca/1/name": "Drums", "/dca/1/fdr": -40.0,
    })
    assert "CH002" not in _rule_ids(run_audit(state))


def test_a_mute_group_silencing_only_untouched_strips_is_not_reported():
    """CH003, *"silencing active members"*. It used to say "routed",
    and on a factory WING that is every strip on the desk."""
    state = ConsoleState({
        "/mgrp/1/name": "Band", "/mgrp/1/mute": 1,
        "/ch/1/tags": "#M1", "/ch/1/main/1/on": 1,
    })
    assert "CH003" not in _rule_ids(run_audit(state))


def test_a_mute_group_silencing_a_named_strip_is_reported():
    state = ConsoleState({
        "/mgrp/1/name": "Band", "/mgrp/1/mute": 1,
        "/ch/1/name": "Kick", "/ch/1/tags": "#M1", "/ch/1/main/1/on": 1,
    })
    findings = [f for f in run_audit(state) if f.rule_id == "CH003"]
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO


def test_a_near_silent_matrix_send_is_reported():
    """L001 is *"ANY send"* now. It walked a strip's bus sends alone,
    so a Matrix feed left at -110dB was checked by nobody."""
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/send/MX1/on": 1, "/ch/1/send/MX1/lvl": -110.0,
    })
    findings = [f for f in run_audit(state) if f.rule_id == "L001"]
    assert [f.addresses for f in findings] == [("/ch/1/send/MX1/lvl",)]
    assert "MTX 1" in findings[0].detail


def test_a_near_silent_matrix_send_from_a_main_is_reported():
    """The source can be a Main, which is how `examples/conventions.md`'s
    own rig feeds its Matrix."""
    state = ConsoleState({
        "/main/1/fdr": 0.0,
        "/main/1/send/MX1/on": 1, "/main/1/send/MX1/lvl": -110.0,
    })
    findings = [f for f in run_audit(state) if f.rule_id == "L001"]
    assert [f.addresses for f in findings] == [("/main/1/send/MX1/lvl",)]


def test_a_send_at_the_floor_is_still_off_on_purpose():
    """Unchanged, and worth keeping honest while the rule widens: the
    floor is a deliberate "off", not a forgotten send."""
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/send/MX1/on": 1, "/ch/1/send/MX1/lvl": FADER_FLOOR_DB,
    })
    assert "L001" not in _rule_ids(run_audit(state))


def test_duplicate_names_across_the_two_input_banks_are_one_finding():
    """N001 is *"Duplicate Channel/Aux Names"* -- the aux bank is a
    bank of input strips and a collision between the banks is the same
    collision."""
    state = ConsoleState({"/ch/1/name": "Talkback", "/aux/2/name": "Talkback"})
    findings = [f for f in run_audit(state) if f.rule_id == "N001"]
    assert len(findings) == 1
    assert findings[0].title == "Duplicate Channel/Aux Names"
    assert set(findings[0].addresses) == {"/ch/1/name", "/aux/2/name"}


def test_a_shared_factory_default_name_is_not_a_duplicate():
    """N002 is *"the same NON-DEFAULT name"*, and N001 has said so
    since it was written. Two objects both showing the desk's own label
    for one of them is not a collision an operator has to go and fix; two
    objects an operator called the same thing is."""
    default = ConsoleState({"/bus/1/name": "BUS 3", "/bus/2/name": "BUS 3"})
    assert "N002" not in _rule_ids(run_audit(default))
    named = ConsoleState({"/bus/1/name": "Mix", "/bus/2/name": "Mix"})
    assert "N002" in _rule_ids(run_audit(named))

    default_strips = ConsoleState({"/ch/1/name": "CH07", "/aux/2/name": "CH07"})
    assert "N001" not in _rule_ids(run_audit(default_strips))


# --- A plan states a bus and DCA fader, and something diffs it ---


def test_a_stated_bus_fader_that_the_desk_contradicts_is_reported():
    state = ConsoleState({"/bus/1/name": "MON1", "/bus/1/fdr": 0.0, "/bus/1/mute": 0})
    plan = {"channels": [], "busses": {"MON1": {"index": 1, "fader": {"fader_db": -144}}}}
    findings = diff_against_plan(state, plan)
    assert [f.rule_id for f in findings] == ["CV011"]
    assert findings[0].addresses == ("/bus/1/fdr",)


def test_a_stated_bus_mute_that_the_desk_contradicts_is_reported():
    state = ConsoleState({"/bus/1/name": "MON1", "/bus/1/mute": 0})
    plan = {"channels": [], "busses": {"MON1": {"index": 1, "fader": {"muted": True}}}}
    assert [f.rule_id for f in diff_against_plan(state, plan)] == ["CV010"]


def test_a_stated_dca_fader_that_the_desk_contradicts_is_reported():
    state = ConsoleState({"/dca/1/name": "Drums", "/dca/1/fdr": 0.0, "/dca/1/mute": 0})
    plan = {"channels": [], "dcas": {"Drums": {"index": 1, "fader": {"fader_db": -144}}}}
    findings = diff_against_plan(state, plan)
    assert [f.rule_id for f in findings] == ["CV013"]
    assert findings[0].addresses == ("/dca/1/fdr",)


def test_a_stated_dca_mute_that_the_desk_contradicts_is_reported():
    state = ConsoleState({"/dca/1/name": "Drums", "/dca/1/mute": 0})
    plan = {"channels": [], "dcas": {"Drums": {"index": 1, "fader": {"muted": True}}}}
    assert [f.rule_id for f in diff_against_plan(state, plan)] == ["CV012"]


def test_a_group_fader_within_tolerance_is_not_a_contradiction():
    """Same quantisation reasoning as CV002's, same constant."""
    state = ConsoleState({"/bus/1/name": "MON1", "/bus/1/fdr": -6.0 + FADER_TOLERANCE_DB / 2})
    plan = {"channels": [], "busses": {"MON1": {"index": 1, "fader": {"fader_db": -6.0}}}}
    assert diff_against_plan(state, plan) == []


def test_a_group_fader_the_plan_does_not_state_is_compared_against_nothing():
    """The same "only fields the plan actually states" rule the channel
    checks follow -- a null is not an assertion."""
    state = ConsoleState({"/bus/1/name": "MON1", "/bus/1/fdr": 0.0, "/bus/1/mute": 0})
    plan = {"channels": [], "busses": {"MON1": {"index": 1, "fader": {"fader_db": None, "muted": None}}}}
    assert diff_against_plan(state, plan) == []


def test_a_group_whose_live_state_was_never_read_is_skipped_silently():
    state = ConsoleState({})
    plan = {"channels": [], "dcas": {"Drums": {"index": 1, "fader": {"fader_db": -144, "muted": False}}}}
    assert diff_against_plan(state, plan) == []


def test_a_group_fader_finding_cites_the_plans_own_provenance():
    state = ConsoleState({"/bus/1/name": "MON1", "/bus/1/fdr": 0.0})
    plan = {"channels": [], "busses": {"MON1": {
        "index": 1, "fader": {"fader_db": -144},
        "provenance": "Busses: 'Leave bus faders all the way down'",
    }}}
    assert "Leave bus faders all the way down" in diff_against_plan(state, plan)[0].detail


def test_a_malformed_group_entry_does_not_crash_the_diff():
    """Same discipline as `_declared_output_patches`: a read-only question
    about what a plan claims is not a place to raise over a shape it does
    not need. `archive/examples/archive/` holds a generated plan whose DCA entry
    is a bare list."""
    state = ConsoleState({"/bus/1/name": "MON1", "/bus/1/fdr": 0.0})
    plan = {
        "channels": [],
        # an entry with no index, one whose `fader` is not an object, a
        # None, and the bare list `archive/examples/archive/smallband.gemma3:4b.
        # plan.json` really carries
        "busses": {"NoIndex": {"fader": {"fader_db": 0}}, "BadFader": {"index": 1, "fader": 3}},
        "dcas": {"Drums": None, "Guitars": ["Guitars"]},
    }
    assert diff_against_plan(state, plan) == []
