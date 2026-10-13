"""C004: a channel switched to its alternate input patch (slice 1 -- read and audit).

Grounded in A7, run on a WING Compact on 2026-09-21
(`archive/examples/console-runs/2026-09-21/A7-*`): three OSC captures of channel 1
with no alternate, an AES50 alternate and a WLIVE-card alternate, and the
desk's own snapshot of the WLIVE case. Nothing here is a guessed encoding.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    console_read_plan,
    run_audit,
)
from atoo.console import decode_message

ROOT = Path(__file__).resolve().parents[1]
A7 = ROOT / "tests" / "fixtures" / "console-runs" / "2026-09-21"
INITIALIZED_COMPACT = ROOT / "tests" / "fixtures" / "console-runs" / "Initialized-Compact.snap"

_REPLY_LINE = re.compile(r"^(\S+) -> OscReply\(.*raw=(b'.*')\)$")


def _captured_replies(path: Path) -> dict[str, object]:
    """`{address: decoded reply}` from an A7 capture -- **only where the
    reply is for the address that was asked**. That session had the
    reply-matching defect (a GET answered by its neighbour's reply), and a
    test built on a mismatched line would be testing the defect."""
    replies = {}
    for line in path.read_text().splitlines():
        m = _REPLY_LINE.match(line)
        if not m:
            continue
        reply = decode_message(ast.literal_eval(m.group(2)))
        if reply.address == m.group(1):
            replies[m.group(1)] = reply
    return replies


def _state_from_capture(path: Path) -> ConsoleState:
    replies = _captured_replies(path)
    values = {"/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1}
    for address, value_type in (("/ch/1/in/set/altsrc", "i"),
                                ("/ch/1/in/conn/altgrp", "s")):
        value, error = replies[address].value(value_type)
        assert error is None
        values[address] = value
    return ConsoleState(values)


def _state_from_snap(path: Path) -> ConsoleState:
    """The strip leaves C004 and its label read, off a console-written
    `.snap` -- already in SET-value form, so no readback correction."""
    ae = json.loads(path.read_text())["ae_data"]
    values: dict[str, object] = {}
    for bank in ("ch", "aux"):
        for n, strip in (ae.get(bank) or {}).items():
            base = f"/{bank}/{n}"
            inp = strip.get("in") or {}
            conn, sets = inp.get("conn") or {}, inp.get("set") or {}
            values[f"{base}/name"] = strip.get("name", "")
            values[f"{base}/in/conn/grp"] = conn.get("grp")
            values[f"{base}/in/conn/in"] = conn.get("in")
            values[f"{base}/in/conn/altgrp"] = conn.get("altgrp")
            values[f"{base}/in/set/altsrc"] = int(bool(sets.get("altsrc")))
    return ConsoleState(values, console_model="wing-compact")


def _sp_c004(state: ConsoleState):
    return [f for f in run_audit(state) if f.rule_id == "C004"]


# -- the read ------------------------------------------------------------


def test_the_read_asks_for_the_switch_and_the_alternate_group_on_every_strip():
    asked = {a for a, _ in console_read_plan()}
    for bank, count in (("ch", 40), ("aux", 8)):
        for n in range(1, count + 1):
            assert f"/{bank}/{n}/in/set/altsrc" in asked
            assert f"/{bank}/{n}/in/conn/altgrp" in asked


def test_the_alternate_socket_number_is_not_read():
    """`in/conn/altin` is presumed to carry `in/conn/in`'s readback offset
    and has not been measured (`console_facts`'s not-corrected list). An
    uncorrected socket number in a finding would be a wrong number stated
    as fact, so it is not asked for at all."""
    assert not [a for a, _ in console_read_plan() if a.endswith("/altin")]


# -- the rule, on hardware values ----------------------------------------


def test_the_captured_wlive_alternate_is_reported_with_its_group():
    """A7-with-WLIVE-alt: channel 1 switched to an alternate on the WLIVE
    card (`CRD`). The desk replied `,sfi '1' 1.0 1` for the switch."""
    [finding] = _sp_c004(_state_from_capture(A7 / "A7-with-WLIVE-alt.txt"))
    assert finding.severity == "warning"
    assert finding.addresses == ("/ch/1/in/set/altsrc", "/ch/1/in/conn/altgrp")
    assert "alternate patch from CRD" in finding.message
    assert "A 1" in finding.message


def test_the_captured_board_with_no_alternate_says_nothing():
    assert _sp_c004(_state_from_capture(A7 / "A7-no-alts.txt")) == []


def test_the_desks_own_snapshot_of_the_same_setup_agrees():
    """The WLIVE case again, from the snapshot the desk wrote rather than
    from OSC: exactly one strip on its alternate, and it is channel 1."""
    findings = _sp_c004(_state_from_snap(A7 / "A7-ch1-with-WLIVE-alt.snap"))
    assert [f.addresses[0] for f in findings] == ["/ch/1/in/set/altsrc"]


def test_a_factory_desk_has_no_strip_on_its_alternate():
    """FR-4.7: a factory Compact reports nothing, and this rule must not be
    the one that breaks that."""
    assert _sp_c004(_state_from_snap(INITIALIZED_COMPACT)) == []


# -- the rule, on the edges ----------------------------------------------


def test_an_alternate_switched_on_with_no_alternate_patch_says_so():
    state = ConsoleState({"/aux/3/in/set/altsrc": 1, "/aux/3/in/conn/altgrp": "OFF",
                          "/aux/3/in/conn/grp": "USB", "/aux/3/in/conn/in": 3})
    [finding] = _sp_c004(state)
    assert "set to OFF" in finding.message
    assert "USB 3" in finding.message


def test_an_unread_switch_is_silent_not_clean():
    """Any capture made before this rule: no `altsrc` in it at all. The
    rule says nothing, rather than a finding either way."""
    state = ConsoleState({"/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
                          "/ch/1/in/conn/altgrp": "CRD"})
    assert _sp_c004(state) == []


def test_it_is_a_hazard_so_a_plan_that_never_mentions_the_strip_keeps_it():
    rule = next(r for r in DEFAULT_RULES if r.id == "C004")
    assert rule.scope == "hazard"
    state = ConsoleState({"/ch/30/in/set/altsrc": 1, "/ch/30/in/conn/altgrp": "CRD"})
    plan = {"meta": {"console_model": "wing-compact"}, "channels": {}}
    assert [f.rule_id for f in run_audit(state, plan=plan) if f.rule_id == "C004"] == ["C004"]
