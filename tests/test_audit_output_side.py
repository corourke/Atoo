"""The audit's output side: what a live read actually
covers, and the rules that depend on it.

Every hardware `audit` run this project has recorded read a console with
**zero physical sockets in it**, because `read_console_state`'s
`input_sockets`/`output_sockets` default to none and no caller ever
passed them. Four rules could not fire, two more reported a correctly
patched desk as faulty, and nothing in the report said so.

These tests cover the three halves of the fix that the Python suite can
see offline: the matrix-send reads a Main and a Bus need, the rules and
the signal graph learning that a Matrix is fed by a send on its source,
and the socket groups a run derives when it is told nothing.
"""

import json
from pathlib import Path

import pytest

from atoo.audit import (
    ConsoleState,
    build_signal_graph,
    read_console_state,
    render_coverage,
    run_audit,
    socket_groups_to_read,
    trace_signal_path,
)
from atoo.console import OscReply


def _rule_ids(findings):
    return {f.rule_id for f in findings}


class RecordingConsole:
    """Answers nothing, remembers every address asked for. The question
    here is *what a run reads*, which no reply can answer."""

    def __init__(self):
        self.addresses = []

    def get(self, address):
        self.addresses.append(address)
        return None


# --------------------------------------------------------------------------
# A Matrix is fed by a send on its source -- Main or Bus, not only a strip
# --------------------------------------------------------------------------


# `examples/conventions.md`, which is also the A5 hardware rig: *"Main
# should be the full mix... Send to Matrix 1. Matrix 1 takes its feed
# from Main... Patch output to internal XLRs 7 and 8."*
MAIN_FEEDS_MATRIX = {
    "/ch/1/main/1/on": 1,
    "/main/1/send/MX1/on": 1,
    "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
}


def test_a_matrix_fed_from_a_main_is_not_an_orphan():
    """The regression this issue's fix exists to prevent.

    R003's `fed` test walked `strip_bases()` alone -- the one source
    a plan built by this project never uses for a matrix. It was dead
    code on every hardware run so far (nothing read `/io/out/*`, so the
    rule returned early); the moment sockets ARE read it would have
    reported the shipped example rig as an ERROR. Same one-hop blindness
    an earlier change fixed in R005, in the rule directly above it."""
    assert "R003" not in _rule_ids(run_audit(ConsoleState(MAIN_FEEDS_MATRIX)))


def test_a_matrix_fed_from_a_bus_is_not_an_orphan():
    state = ConsoleState({
        "/bus/1/name": "Matrix feed",
        "/bus/1/send/MX1/on": 1,
        "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
    })
    assert "R003" not in _rule_ids(run_audit(state))


def test_a_matrix_nothing_feeds_is_still_an_orphan():
    """Not vacuous: drop the Main's send and the ERROR comes back."""
    state = dict(MAIN_FEEDS_MATRIX)
    del state["/main/1/send/MX1/on"]
    assert "R003" in _rule_ids(run_audit(ConsoleState(state)))


def test_a_matrix_whose_main_send_is_off_is_still_an_orphan():
    """The send has to be ON -- an address that exists but reads 0 is a
    matrix nothing reaches, which is exactly what the rule is for."""
    state = dict(MAIN_FEEDS_MATRIX, **{"/main/1/send/MX1/on": 0})
    assert "R003" in _rule_ids(run_audit(ConsoleState(state)))


def test_the_conventions_rig_is_clean_on_both_matrix_rules_at_once():
    """R005 and R003 are two halves of the same hop.
    Fixing either alone leaves the rig reporting an ERROR."""
    assert not (_rule_ids(run_audit(ConsoleState(MAIN_FEEDS_MATRIX)))
                & {"R003", "R005"})


# --------------------------------------------------------------------------
# R006 -- R003's mirror image: a Matrix fed and patched nowhere
# --------------------------------------------------------------------------


# The own reproduction, as a desk would hold it afterwards. Matrix
# 1 is fed from Main 1 and was patched to LCL 7-8; a stereo IEM bus took
# LCL 7-8. A socket stores one source, so only the bus is left -- and Main
# 1 still goes straight out on LCL 1-2, so R005 has nothing to say.
MATRIX_LOST_ITS_OUTPUT = {
    "/ch/1/main/1/on": 1,
    "/main/1/send/MX1/on": 1,
    "/io/out/LCL/1/grp": "MAIN", "/io/out/LCL/1/in": 1,
    "/io/out/LCL/2/grp": "MAIN", "/io/out/LCL/2/in": 2,
    "/bus/4/name": "IEM",
    "/ch/1/send/4/on": 1,
    "/io/out/LCL/7/grp": "BUS", "/io/out/LCL/7/in": 7,
    "/io/out/LCL/8/grp": "BUS", "/io/out/LCL/8/in": 8,
}


def test_a_fed_matrix_that_lost_its_output_is_reported():
    """The gap an earlier change names: until this rule, the case above audited clean."""
    findings = [f for f in run_audit(ConsoleState(MATRIX_LOST_ITS_OUTPUT))
                if f.rule_id == "R006"]
    assert [f.addresses for f in findings] == [("/mtx/1",)]
    assert findings[0].severity.value == "warning"


def test_the_finding_names_the_output_sockets_it_looked_at():
    """A partial read still fires, and a Matrix is the object that goes
    out on a card. On the A17/A18 full-size desk Matrix 6 is patched to
    MOD 36-37 while the audit read only LCL and AUX outputs -- so the
    finding says what it checked rather than claiming "no output" flat."""
    state = dict(MATRIX_LOST_ITS_OUTPUT, **{"/io/out/AUX/1/grp": "OFF", "/io/out/AUX/1/in": 0})
    [finding] = [f for f in run_audit(ConsoleState(state)) if f.rule_id == "R006"]
    assert finding.detail.endswith("output sockets read (AUX 1, LCL 1-8), and no monitor "
                                   "output listens to it.")


@pytest.mark.parametrize("feed", ["/ch/1/send/MX1/on", "/bus/1/send/MX1/on",
                                  "/main/1/send/MX1/on"])
def test_any_feed_makes_an_unpatched_matrix_a_finding(feed):
    """A strip, a bus or a Main -- the three sources R003 learned in
    all count, because they are the same `_matrix_is_fed`."""
    state = ConsoleState({feed: 1, "/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0})
    assert "R006" in _rule_ids(run_audit(state))


def test_a_fed_matrix_that_is_patched_is_clean():
    """Not vacuous: the conventions rig -- Main into Matrix 1, Matrix 1 out
    on LCL 7 -- is fed AND patched, and must stay silent."""
    assert "R006" not in _rule_ids(run_audit(ConsoleState(MAIN_FEEDS_MATRIX)))


def test_a_matrix_whose_only_send_is_off_is_not_fed():
    """An address that exists but reads 0 is not a feed, exactly as for
    R003 -- a factory desk carries every `send/MX{n}/on` switched off."""
    state = dict(MATRIX_LOST_ITS_OUTPUT, **{"/main/1/send/MX1/on": 0})
    assert "R006" not in _rule_ids(run_audit(ConsoleState(state)))


def test_sp_r006_stands_down_when_no_output_patch_was_read():
    """The guard, which R006 was born with: "patched to no
    output" is not a thing a read with no `/io/out/*` in it can say."""
    state = {k: v for k, v in MATRIX_LOST_ITS_OUTPUT.items()
             if not k.startswith("/io/out/")}
    assert "R006" not in _rule_ids(run_audit(ConsoleState(state)))
    assert "R006" in render_coverage(ConsoleState(state))


def test_sp_r003_and_sp_r006_never_both_fire_on_one_matrix():
    """Mirror images: R003 is patched-and-unfed, R006 is fed-and-unpatched.
    A patched Matrix reaches an output by definition, so the two cannot
    both be true of the same one."""
    for state in (MAIN_FEEDS_MATRIX, MATRIX_LOST_ITS_OUTPUT,
                  {"/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1}):
        by_matrix = {}
        for f in run_audit(ConsoleState(state)):
            if f.rule_id in ("R003", "R006"):
                by_matrix.setdefault(f.addresses, set()).add(f.rule_id)
        assert all(len(ids) == 1 for ids in by_matrix.values())


# --------------------------------------------------------------------------
# read_console_state reads those sends
# --------------------------------------------------------------------------


def test_read_console_state_reads_matrix_sends_on_mains_and_busses():
    """`apply.py` writes a matrix feed on `/main/{n}/send/MX{m}` and
    `/bus/{n}/send/MX{m}`; until an earlier change the audit read `send/MX*` for
    `/ch` and `/aux` only, so the matrix hop had nothing to walk.

    `on` and `lvl` are the whole of it. A bus's and a
    Main's send has no `mode` and no `pon` on the hardware, and the two
    leaves this once asked for were 320 unanswered addresses a read."""
    console = RecordingConsole()
    read_console_state(console, channels=0, aux=0, buses=2, mains=2,
                       matrices=2, dcas=0, mute_groups=0)
    asked = set(console.addresses)
    for suffix in ("on", "lvl"):
        assert f"/main/1/send/MX1/{suffix}" in asked
        assert f"/main/2/send/MX2/{suffix}" in asked
        assert f"/bus/1/send/MX1/{suffix}" in asked
        assert f"/bus/2/send/MX2/{suffix}" in asked
    for suffix in ("mode", "pon"):
        assert f"/main/1/send/MX1/{suffix}" not in asked
        assert f"/bus/1/send/MX1/{suffix}" not in asked


def test_a_strips_matrix_send_still_asks_for_mode_and_pon():
    """The control for the test above: the leaves a bus does not have are
    leaves a CHANNEL does, and the A11 dump of `/ch/1` carried all 106
    addresses a read wants from one. Dropping them everywhere would have
    been a much bigger and much quieter change."""
    console = RecordingConsole()
    read_console_state(console, channels=1, aux=1, buses=1, mains=0,
                       matrices=1, dcas=0, mute_groups=0)
    asked = set(console.addresses)
    for suffix in ("on", "lvl", "mode", "pon"):
        assert f"/ch/1/send/MX1/{suffix}" in asked
        assert f"/ch/1/send/1/{suffix}" in asked
        assert f"/aux/1/send/MX1/{suffix}" in asked


def test_read_console_state_still_reads_no_sockets_when_told_nothing():
    """The library default is deliberate and unchanged (a walk of the
    address tree is not a measurement of the hardware). An earlier change moves the
    DEFAULT the CLI passes, not this one."""
    console = RecordingConsole()
    read_console_state(console, channels=1, aux=0, buses=0, mains=0,
                       matrices=0, dcas=0, mute_groups=0)
    # `/io/altsw` (C005) is a console-wide switch, not a
    # socket; every `/io/in/...` and `/io/out/...` stays unread.
    assert not [a for a in console.addresses if a.startswith(("/io/in/", "/io/out/"))]


def test_a_matrix_send_read_from_a_console_reaches_the_rule():
    """End to end through the real reply path rather than a hand-built
    state -- the reads and the rule agree on the address."""
    console_replies = {
        "/main/1/send/MX1/on": OscReply(address="/main/1/send/MX1/on", typetag="sfi",
                                        args=["1", 1.0, 1]),
        "/io/out/LCL/7/grp": OscReply(address="/io/out/LCL/7/grp", typetag="s", args=["MTX"]),
        # 0, not 1: `/io/out/{G}/{n}/in` carries the +1 readback
        # offset, so a desk patched from MTX 1 answers 0.
        "/io/out/LCL/7/in": OscReply(address="/io/out/LCL/7/in", typetag="i", args=[0]),
    }

    class Replies:
        def get(self, address):
            return console_replies.get(
                address, OscReply(address=address, typetag="SOCKET_ERROR", args=[]))

    state = read_console_state(Replies(), channels=0, aux=0, buses=0, mains=1,
                               matrices=1, dcas=0, mute_groups=0,
                               output_sockets={"LCL": 8})
    assert state.flag("/main/1/send/MX1/on") is True
    assert "R003" not in _rule_ids(run_audit(state))


# --------------------------------------------------------------------------
# The signal graph follows a mix through a matrix
# --------------------------------------------------------------------------


def _trace(values, start, end):
    return trace_signal_path(build_signal_graph(ConsoleState(values)), start, end)


TRACE_RIG = {
    "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    "/ch/1/mute": 0, "/ch/1/fdr": 0.0,
    "/ch/1/main/1/on": 1,
    "/main/1/mute": 0, "/main/1/fdr": 0.0,
    "/main/1/send/MX1/on": 1, "/main/1/send/MX1/lvl": 0.0,
    "/mtx/1/mute": 0, "/mtx/1/fdr": 0.0,
    "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
}


def test_a_trace_follows_a_mix_through_a_matrix_to_the_pa():
    """Before an earlier change the graph had no `main:->mtx:` edge at all, so
    `audit --trace` answered "no routing path exists" for the standard
    way of EQing a room."""
    result = _trace(TRACE_RIG, "input:LCL:1", "output:LCL:7")
    assert result.reachable, result.break_reason
    assert "main:1" in result.path
    assert "mtx:1" in result.path


def test_a_trace_through_a_bus_fed_matrix_reaches_the_pa():
    values = {
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/ch/1/mute": 0, "/ch/1/fdr": 0.0,
        "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": 0.0,
        "/bus/1/mute": 0, "/bus/1/fdr": 0.0,
        "/bus/1/send/MX1/on": 1, "/bus/1/send/MX1/lvl": 0.0,
        "/io/out/LCL/7/grp": "MTX", "/io/out/LCL/7/in": 1,
    }
    result = _trace(values, "input:LCL:1", "output:LCL:7")
    assert result.reachable, result.break_reason


def test_a_trace_breaks_at_a_matrix_send_that_is_off():
    """The new edges are gated, not assumed open -- a break has to be
    reported at the send, with a reason naming it."""
    values = dict(TRACE_RIG, **{"/main/1/send/MX1/on": 0})
    result = _trace(values, "input:LCL:1", "output:LCL:7")
    assert not result.reachable
    assert "matrix 1" in (result.break_reason or "")


def test_a_trace_breaks_at_a_muted_main_feeding_a_matrix():
    values = dict(TRACE_RIG, **{"/main/1/mute": 1})
    result = _trace(values, "input:LCL:1", "output:LCL:7")
    assert not result.reachable
    assert "/main/1" in (result.break_reason or "")


# --------------------------------------------------------------------------
# Which socket groups a run reads when it is told nothing
# --------------------------------------------------------------------------


def test_no_model_and_no_plan_reads_no_sockets():
    """The old behaviour survives where there is genuinely nothing to go
    on -- `socket_groups_to_read` never guesses."""
    assert socket_groups_to_read(None, None) == ({}, {})


def test_the_model_supplies_its_panel():
    """`panel_for()` is inventory (protocol PDF pp. 11-12), unlike the
    `INPUT_SOCKETS` address space -- a Compact has 24 local inputs and 8
    local outputs and no local aux jacks at all."""
    inputs, outputs = socket_groups_to_read("wing-compact")
    assert inputs == {"LCL": 24}
    assert outputs == {"LCL": 8}
    assert "AUX" not in inputs and "AUX" not in outputs


def test_an_unrecognised_model_contributes_nothing_rather_than_raising():
    """Unlike `verify_plan`, an audit against an unfamiliar desk should
    still run -- it just cannot claim to know that desk's panel."""
    assert socket_groups_to_read("wing-lunchbox") == ({}, {})


def test_the_plan_supplies_the_stage_boxes_the_model_cannot_know():
    """AES50 sockets are a fact about tonight's rig, not about the
    console model, so only the plan can name them.

    **A plan patching channels up to AES50-A 20**, written out here rather
    than read from a bundle in `examples/`: what this test needs is one
    AES50 patch above the highest the console model knows about, and a
    file somebody rebuilds between shows is not the place to keep it."""
    plan = {"channels": [
        {"patch": {"group": "A", "sockets": [1]}},
        {"patch": {"group": "A", "sockets": [20]}},
        {"patch": {"group": "LCL", "sockets": [1]}},
    ]}
    inputs, outputs = socket_groups_to_read("wing-compact", plan)
    assert inputs["A"] == 20          # the highest AES50-A socket it patches
    assert inputs["LCL"] == 24        # still the panel's own count
    assert outputs["LCL"] == 8        # the Compact's own panel


def test_a_plan_socket_beyond_the_address_space_is_not_read():
    """A plan mid-edit should not send a run reading past where the
    firmware answers."""
    plan = {"channels": [{"patch": {"group": "LCL", "sockets": [900]}}]}
    inputs, _ = socket_groups_to_read(None, plan)
    assert inputs == {}


def test_a_plan_with_an_unknown_group_is_not_read():
    plan = {"channels": [{"patch": {"group": "NOPE", "sockets": [1]}}]}
    assert socket_groups_to_read(None, plan) == ({}, {})


# --------------------------------------------------------------------------
# Saying so out loud
# --------------------------------------------------------------------------


def test_coverage_names_the_rules_a_socketless_read_could_not_check():
    """A report that silently omits four rules reads exactly like a
    report that ran them and found nothing."""
    note = render_coverage(ConsoleState({"/ch/1/name": "Kick"}))
    assert "none" in note
    for rule_id in ("R003", "R004", "CV009", "C001"):
        assert rule_id in note
    assert "--output-sockets" in note


def test_coverage_lists_what_was_read():
    note = render_coverage(ConsoleState({
        "/io/in/LCL/1/vph": 0, "/io/in/LCL/24/vph": 0,
        "/io/out/LCL/8/grp": "OFF",
    }))
    assert "LCL 1-24" in note
    assert "LCL 1-8" in note
    assert "R003" not in note


def test_coverage_calls_out_a_half_read():
    note = render_coverage(ConsoleState({"/io/in/LCL/1/vph": 0}))
    assert "R003" in note and "CV009" in note
    assert "C001" not in note


def test_coverage_advice_differs_for_a_capture():
    """A state file cannot be widened by a flag -- it holds whatever was
    captured -- so telling its reader to pass `--output-sockets` would be
    advice that does nothing."""
    empty = ConsoleState({"/ch/1/name": "Kick"})
    live = render_coverage(empty)
    capture = render_coverage(empty, from_capture=True)
    assert "--output-sockets LCL=8" in live
    assert "--output-sockets LCL=8" not in capture
    assert "no flag here can widen it" in capture


def test_the_watch_page_derives_the_same_socket_groups_as_the_cli(monkeypatch):
    """The Watch page reads a console through its own factory, not
    through `cli._console_read_kwargs`. Without the same derivation four
    rules would go quiet in the browser only -- and
    `atoo/web/static/` is the one place the Python suite cannot
    see, so that drift would be invisible."""
    import atoo.console as console_module
    from atoo import webui

    reads = []

    class Desk:
        def __init__(self, ip, port=2223, timeout=1.0):
            pass

        def identity(self):
            return OscReply(address="/?", typetag="s",
                            args=["WING,198.51.100.1,DESK,wing-compact,SER,3.1"])

        def get(self, address):
            reads.append(address)
            return None

        def node_dump(self, node):
            # The Watch page reads by node dump. A dump
            # that never answers sends every leaf back to `get`, so
            # `reads` still lists every address the read wanted.
            return None

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", Desk)
    provider, close = webui.console_provider_factory("198.51.100.1")
    provider()
    close()

    # A Compact's own panel: local inputs 1-24, local outputs 1-8.
    assert "/io/in/LCL/24/vph" in reads
    assert "/io/out/LCL/8/grp" in reads
    assert "/io/in/LCL/25/vph" not in reads


def test_an_explicit_socket_count_still_wins_in_the_watch_page(monkeypatch):
    import atoo.console as console_module
    from atoo import webui

    reads = []

    class Desk:
        def __init__(self, ip, port=2223, timeout=1.0):
            pass

        def identity(self):
            return OscReply(address="/?", typetag="s",
                            args=["WING,198.51.100.1,DESK,wing-compact,SER,3.1"])

        def get(self, address):
            reads.append(address)
            return None

        def node_dump(self, node):
            # The Watch page reads by node dump. A dump
            # that never answers sends every leaf back to `get`, so
            # `reads` still lists every address the read wanted.
            return None

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", Desk)
    provider, close = webui.console_provider_factory(
        "198.51.100.1", read_kwargs={"output_sockets": {"A": 4}})
    provider()
    close()

    assert "/io/out/A/4/grp" in reads
    assert "/io/out/LCL/8/grp" not in reads   # replaced, not merged


def _audit_args(**overrides):
    import argparse

    base = dict(channels=40, aux=8, buses=16, mains=4, matrices=8, dcas=16,
                mute_groups=8, input_sockets=None, output_sockets=None,
                detected_console_model="wing-compact")
    base.update(overrides)
    return argparse.Namespace(**base)


def test_an_explicit_flag_beats_the_derived_socket_groups():
    from atoo.cli import _console_read_kwargs

    kwargs = _console_read_kwargs(_audit_args(output_sockets="A=48"))
    assert kwargs["output_sockets"] == {"A": 48}
    assert kwargs["input_sockets"] == {"LCL": 24}      # the other direction still derives


def test_the_derived_groups_reach_the_read_when_no_flag_is_given():
    from atoo.cli import _console_read_kwargs

    kwargs = _console_read_kwargs(_audit_args())
    assert kwargs["output_sockets"] == {"LCL": 8}
    assert kwargs["input_sockets"] == {"LCL": 24}


def test_a_desk_of_an_unknown_model_reads_no_sockets_and_does_not_crash():
    from atoo.cli import _console_read_kwargs

    kwargs = _console_read_kwargs(_audit_args(detected_console_model=None))
    assert kwargs["output_sockets"] == {}
    assert kwargs["input_sockets"] == {}
