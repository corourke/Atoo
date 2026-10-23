"""The scoped read plan for `watch`, and the measurement that
says whether scoping alone gets a pass under the 3-4 second budget.

**The load-bearing test here is `test_scoping_changes_no_finding`, and the
one that makes it load-bearing is `test_mutating_the_scope_is_caught`.**
The first audits a full-plan state and the same state restricted to the
scoped plan and asserts the findings are byte-identical; the second
removes one address per rule from the scope and asserts the first would
have failed. A scope test that passes under mutation is not a test -- an
address wrongly omitted is a rule that silently stops firing, and for a
monitoring tool that is the worst available failure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atoo import audit, console_facts, watch_scope
from atoo.audit import ConsoleState, DEFAULT_RULES, run_audit
from atoo.watch_conditions import build_watch_rules, parse_watch_conditions

CAPTURE = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "console-runs"
           / "2026-09-22-2008" / "A11-read-speed.json")

COMPACT = watch_scope.COMPACT_PLAN_KWARGS


# --------------------------------------------------------------------------
# A full-plan console state on which EVERY rule in DEFAULT_RULES fires.
# Built rather than captured, because no capture on disk is a
# ConsoleState -- and because a fixture that exercises every rule is what
# makes the equivalence test mean something.
# --------------------------------------------------------------------------

_DEFAULTS = {
    "name": "", "mute": 0, "fdr": 0.0, "tags": "",
    "in/conn/grp": "OFF", "in/conn/in": 0,
    "in/conn/altgrp": "OFF", "in/set/altsrc": 0,
    "on": 0, "lvl": 0.0, "mode": "PRE", "pon": 0,
    "grp": "OFF", "in": 0, "vph": 0,
    "ins": "NONE", "mdl": "NONE",
    "assign": "OFF", "altsw": 0,
    # A factory desk's busses, Mains and Matrices are all stereo.
    "busmono": 0,
    # No device on any AES50 port; no monitor source.
    "stat": "-", "src": "OFF",
}

#: The watchlist the fixture state is built to trip, one condition per
#: field in the vocabulary.
CONDITIONS_JSON = json.dumps({"watch_conditions": [
    {"id": "crowd-never-muted", "description": "Crowd Mic must never be muted",
     "channel": "Crowd Mic", "field": "muted", "operator": "==", "value": False,
     "severity": "error"},
    {"id": "crowd-fader-capped", "description": "Crowd Mic fader stays under -10dB",
     "channel": "Crowd Mic", "field": "fader_db", "operator": "<=", "value": -10.0,
     "severity": "warning"},
    {"id": "bass-not-in-drums", "description": "Bass must not ride the Drums DCA",
     "channel": "Bass", "field": "dca", "operator": "!=", "value": "Drums",
     "severity": "warning"},
    {"id": "gtr-out-of-fx", "description": "Gtr must not be in the FX mute group",
     "channel": "Gtr", "field": "mute_group", "operator": "!=", "value": "FX",
     "severity": "warning"},
    {"id": "crowd-patch", "description": "Crowd Mic is on LCL 9",
     "channel": "Crowd Mic", "field": "patch", "operator": "==", "value": "LCL 9",
     "severity": "warning"},
    {"id": "piano-in-iem", "description": "Piano stays on in the drummer IEM",
     "channel": "Piano", "field": "send_on", "bus": "BUS 9", "operator": "==", "value": True,
     "severity": "error"},
    {"id": "piano-iem-level", "description": "Piano stays above -10 in the drummer IEM",
     "channel": "Piano", "field": "send_db", "bus": "BUS 9", "operator": ">=", "value": -10,
     "severity": "warning"},
    {"id": "piano-48v", "description": "48V stays on for the Piano",
     "channel": "Piano", "field": "phantom", "operator": "==", "value": True,
     "severity": "error"},
]})


def _conditions() -> list[dict]:
    return parse_watch_conditions(CONDITIONS_JSON, source="<test>")


#: Rules whose evidence is not an address, so a read plan has nothing to
#: scope for them: L003 reads the console's meter stream (`tests/test_clip_detection.py`). Their row in `watch_scope` is only the
#: names they quote.
_NOT_ADDRESS_RULES = frozenset({"L003"})


def _rules():
    return ([r for r in DEFAULT_RULES if r.id not in _NOT_ADDRESS_RULES]
            + build_watch_rules(_conditions()))


def _full_state() -> ConsoleState:
    """Every address in a Compact's read plan, valued so that each rule in
    `DEFAULT_RULES` and each watch condition above produces a finding."""
    values: dict[str, object] = {}
    for address, _ in audit.console_read_plan(**COMPACT):
        leaf = address.split("/", 3)[-1]
        for suffix, default in _DEFAULTS.items():
            if leaf.endswith(suffix):
                values[address] = default
                break
        else:  # pragma: no cover -- a new plan family with no default here
            raise AssertionError(f"no fixture default for {address}")

    # R001 (no strip sends to it) and R002 (no route out).
    values["/bus/1/name"] = "Monitors"
    # N002 -- two busses sharing a non-default name.
    values["/bus/2/name"] = values["/bus/3/name"] = "Wedge"
    # R003: a Matrix patched to a jack that nothing sends to. Output
    # slot 1 is Matrix 1's L feed (audit.output_source_object).
    values["/io/out/LCL/3/grp"], values["/io/out/LCL/3/in"] = "MTX", 1
    # R004: Main 2 (slot 3) patched out, nothing routed into it.
    values["/io/out/LCL/5/grp"], values["/io/out/LCL/5/in"] = "MAIN", 3
    # R005: Main 3 fed by a strip, reaching no output at all.
    values["/ch/1/main/3/on"] = 1
    # C001: 48V on a jack no strip and no user patch takes.
    values["/io/in/LCL/20/vph"] = 1
    # ... and NOT on the even socket of a stereo pair: a
    # strip on LCL 13 with the source in ST takes LCL 14 as well. Drop
    # the width from the scope and LCL 14 reads as unpatched.
    values["/ch/14/in/conn/grp"], values["/ch/14/in/conn/in"] = "LCL", 13
    values["/io/in/LCL/13/mode"] = values["/io/in/LCL/14/mode"] = "ST"
    values["/io/in/LCL/13/vph"] = values["/io/in/LCL/14/vph"] = 1
    # C002: two strips off one jack. Also makes both "in use".
    for base in ("/ch/2", "/ch/3"):
        values[f"{base}/in/conn/grp"], values[f"{base}/in/conn/in"] = "LCL", 5
    # CH001: named, so in use, and in no DCA.
    values["/ch/2/name"] = "Snare Top"
    # CH002: an active member of a DCA whose fader is 30dB down.
    values["/ch/4/name"], values["/ch/4/tags"] = "Bass", "#D1"
    values["/dca/1/name"], values["/dca/1/fdr"] = "Drums", -30.0
    # A second named DCA, so WATCH:bass-not-in-drums has to resolve
    # "Drums" among several rather than against the only one there is.
    values["/dca/2/name"] = "Vocals"
    # CH003: an engaged mute group silencing an active member.
    values["/ch/5/name"], values["/ch/5/tags"] = "Gtr", "#M2"
    values["/mgrp/2/name"], values["/mgrp/2/mute"] = "FX", 1
    # CH004: a muted DCA over an active member.
    values["/ch/13/name"], values["/ch/13/tags"] = "Pad", "#D3"
    values["/dca/3/name"], values["/dca/3/mute"] = "Keys", 1
    # N001 -- two strips sharing a non-default name.
    values["/ch/6/name"] = values["/ch/7/name"] = "Vox"
    # L001, on all three source banks a send can live on.
    values["/ch/8/name"] = "Talkback"
    values["/ch/8/send/4/on"], values["/ch/8/send/4/lvl"] = 1, -110.0
    values["/bus/4/send/MX2/on"], values["/bus/4/send/MX2/lvl"] = 1, -110.0
    values["/main/1/send/MX3/on"], values["/main/1/send/MX3/lvl"] = 1, -110.0
    # (Those two sends also make R006: Matrices 2 and 3 are fed and
    # patched to no output.)
    # L002, on a strip and on a bus.
    values["/ch/9/name"], values["/ch/9/fdr"] = "Keys", -144.0
    values["/bus/5/name"], values["/bus/5/fdr"] = "IEM", -144.0
    # C003: a channel patched from a module bay the desk reports empty.
    # The bay reading is second-pass, so it is in no read plan.
    values["/ch/11/in/conn/grp"], values["/ch/11/in/conn/in"] = "MOD", 1
    values["/$syscfg/opt_mod"] = "NONE"
    # C004: a channel left on its alternate input after a virtual
    # soundcheck, the alternate being the WLIVE card.
    values["/ch/12/in/set/altsrc"], values["/ch/12/in/conn/altgrp"] = 1, "CRD"
    # C005: the global alternate switch engaged.
    values["/io/altsw"] = 1
    # C007: a jack muted at the socket under two strips in use (the C002
    # pair above share LCL 5), and a stereo source on LCL 13/14 with the
    # left leg unmuted and the right muted.
    values["/io/in/LCL/5/mute"] = 1
    values["/io/in/LCL/14/mute"] = 1
    # ... and a strip with an alternate patch on a muted socket, handed to
    # C005 while the switch above is engaged; drop either and C007 speaks.
    values["/ch/20/name"], values["/ch/20/in/conn/altgrp"] = "Alt Mic", "A"
    values["/ch/20/in/conn/grp"], values["/ch/20/in/conn/in"] = "LCL", 18
    values["/io/in/LCL/18/mute"] = 1
    # E001: an insert switched on, naming an empty slot.
    values["/ch/13/preins/on"], values["/ch/13/preins/ins"] = 1, "FX1"
    # E002: a reverb loaded that nothing inserts.
    values["/fx/2/mdl"] = "HALL"
    # E003: a bus naming a loaded slot, its insert switched off.
    values["/bus/6/postins/ins"], values["/fx/3/mdl"] = "FX3", "PLATE"
    # T001: talkback assigned to a strip and routed nowhere. The 56
    # switches are second-pass, so they are in no read plan.
    values[console_facts.TALK_ASSIGN] = "CH40"
    # T002: the strip talkback is assigned to is in use (named).
    values["/ch/40/name"] = "Talk Mic"
    for button in console_facts.TALK_BUTTONS:
        for dest in console_facts.TALK_DESTINATIONS:
            values[console_facts.talk_destination(button, dest)] = 0
    # A stage box on AES50-A, and a named wedge bus patched to
    # its output 1 (slot 13 is bus 7's L). The A outputs are second-pass,
    # so they are in no read plan. Drop the port's status from a scope and
    # the bus reads as unrouted.
    values["/$stat/A/stat"] = "OK"
    for n in range(1, console_facts.OUTPUT_SOCKETS["A"] + 1):
        values[f"/io/out/A/{n}/grp"], values[f"/io/out/A/{n}/in"] = "OFF", 0
    values["/io/out/A/1/grp"], values["/io/out/A/1/in"] = "BUS", 13
    values["/bus/7/name"] = "Stage Wedge"
    values["/ch/15/send/7/on"], values["/ch/15/send/7/lvl"] = 1, 0.0
    # C008: a stage box on AES50-B in error, with a strip patched from it
    # and an output carrying a source. C009: AES50-C in error with nothing
    # patched. C010: AES50-A reading UPD.
    values["/$stat/A/stat"], values["/$stat/B/stat"], values["/$stat/C/stat"] = "UPD", "ERR", "ERR"
    for port in ("B", "C"):
        for n in range(1, console_facts.OUTPUT_SOCKETS[port] + 1):
            values[f"/io/out/{port}/{n}/grp"], values[f"/io/out/{port}/{n}/in"] = "OFF", 0
    values["/io/out/B/3/grp"], values["/io/out/B/3/in"] = "BUS", 3
    values["/ch/21/name"] = "Stage B In"
    values["/ch/21/in/conn/grp"], values["/ch/21/in/conn/in"] = "B", 1
    # Matrix 4, fed by bus 4, is the phones' source. Drop the
    # source from a scope and R006 calls it unpatched.
    values["/bus/4/send/MX4/on"], values["/bus/4/send/MX4/lvl"] = 1, 0.0
    values["/cfg/mon/1/src"] = "MTX.4"
    # R008: named strips with no send or route on are everywhere in this
    # state. The aux below is exempt only because a monitor output listens
    # to it; drop the monitor source from a scope and it is reported.
    values["/aux/3/name"], values["/cfg/mon/2/src"] = "Cue", "AUX.3"
    # C006 hands a strip with an alternate patch to C005 while the global
    # switch (above) is engaged; drop either from a scope and it is reported.
    values["/ch/16/name"], values["/ch/16/in/conn/altgrp"] = "Alt Strip", "A"
    # R009: a channel patched from bus 8's left side that sends to bus 8,
    # and an aux patched from Main 4's left side that routes to Main 4.
    values["/ch/17/name"] = "FX Return"
    values["/ch/17/in/conn/grp"], values["/ch/17/in/conn/in"] = "BUS", 15
    values["/ch/17/send/8/on"], values["/ch/17/send/8/lvl"] = 1, 0.0
    values["/aux/4/name"] = "Mix Return"
    values["/aux/4/in/conn/grp"], values["/aux/4/in/conn/in"] = "MAIN", 7
    values["/aux/4/main/4/on"] = 1
    # R010: the same, with the send held at the floor (Matrix 5 is a send
    # target nothing else here uses).
    values["/ch/18/name"] = "Rec Return"
    values["/ch/18/in/conn/grp"], values["/ch/18/in/conn/in"] = "MTX", 9
    values["/ch/18/send/MX5/on"], values["/ch/18/send/MX5/lvl"] = 1, -144.0
    # ... and a looped strip with an alternate patch, handed to C005 while
    # the global switch (above) is engaged; drop either and R009 speaks.
    values["/ch/19/name"], values["/ch/19/in/conn/altgrp"] = "Alt Return", "A"
    values["/ch/19/in/conn/grp"], values["/ch/19/in/conn/in"] = "BUS", 3
    values["/ch/19/send/2/on"], values["/ch/19/send/2/lvl"] = 1, 0.0
    # R011: a named bus, a Main a strip feeds and a Matrix a strip sends to,
    # all stereo, each patched on its left slot only (bus 6 = slot 11, Main 1
    # = slot 1, Matrix 7 = slot 13).
    values["/bus/6/name"] = "Side Fill"
    values["/io/out/LCL/1/grp"], values["/io/out/LCL/1/in"] = "BUS", 11
    values["/ch/5/main/1/on"] = 1
    values["/io/out/LCL/2/grp"], values["/io/out/LCL/2/in"] = "MAIN", 1
    values["/ch/1/send/MX7/on"] = 1
    values["/io/out/LCL/4/grp"], values["/io/out/LCL/4/in"] = "MTX", 13
    # R012: a strip routed to Main 4 directly and through bus 3, which is
    # routed to Main 4 as well.
    values["/ch/20/name"] = "Split Kick"
    values["/ch/20/main/4/on"], values["/ch/20/send/3/on"] = 1, 1
    values["/bus/3/main/4/on"] = 1
    # The watch conditions: muted when it must not be, fader over its cap,
    # patched somewhere other than LCL 9.
    values["/ch/10/name"], values["/ch/10/mute"], values["/ch/10/fdr"] = "Crowd Mic", 1, -5.0
    values["/ch/10/in/conn/grp"], values["/ch/10/in/conn/in"] = "LCL", 11
    # The send and phantom conditions: a Piano whose send to bus 9 is off and
    # low, patched to LCL 15 with no 48V.
    values["/ch/33/name"] = "Piano"
    values["/ch/33/send/9/lvl"] = -30.0
    values["/ch/33/in/conn/grp"], values["/ch/33/in/conn/in"] = "LCL", 15
    return ConsoleState(values)


_SOURCE_NAME_RE = re.compile(watch_scope.SOURCE_NAME)
_CUSTOM_LINK_RE = re.compile(watch_scope.CUSTOM_LINK)
_EXPANSION_BAY_RE = re.compile(watch_scope.EXPANSION_BAY)
# Only the routing is second-pass; `assign` is in the plan like anything else.
_TALK_ROUTING_RE = re.compile(r"^/cfg/talk/[AB]/")


def _restrict(state: ConsoleState, addresses, source_names: bool = False,
              expansion_bays: bool = False, talkback: bool = False) -> ConsoleState:
    """The same reading as `state`, with only `addresses` in it -- what a
    scoped read would have come back with.

    `source_names` models `read_console_state`'s **second pass**: input-socket names are in no read plan, because which socket to
    ask about is not knowable until the patch has been read, so a scope
    that needs them gets them on top of its `addresses` rather than
    through them. Pass `ScopedReadPlan.reads_source_names`. Leaving them
    out of a scope that reads them is what made C002 label a shared
    input `/ch/2` where the full read says `/ch/2 (Snare Top)`.

    `expansion_bays` is the other half of the same second pass: the fitted-card reading of a bay in use. Pass
    `ScopedReadPlan.reads_expansion_bays`.

    `talkback` is the third: where TALK A and B are routed.
    Pass `ScopedReadPlan.reads_talkback`."""
    keep = {a: v for a, v in state.values.items() if a in addresses}
    if source_names:
        # `clink` rides with the socket names: the same two
        # functions consult both, so a scope that gets one and not the
        # other is not a state any read produces.
        keep.update({a: v for a, v in state.values.items()
                     if _SOURCE_NAME_RE.match(a) or _CUSTOM_LINK_RE.match(a)})
    if expansion_bays:
        keep.update({a: v for a, v in state.values.items()
                     if _EXPANSION_BAY_RE.match(a)})
    if talkback:
        keep.update({a: v for a, v in state.values.items() if _TALK_ROUTING_RE.match(a)})
    # The AES50 half of the second pass needs no flag: it is
    # modelled the way `read_console_state` decides it, from what the
    # restricted reading itself holds -- the outputs of every port it says
    # is in use (`audit.aes50_output_addresses`). A scope that dropped the
    # port's status leaf therefore loses the port's outputs, as a real
    # scoped read would.
    wanted = {a for a, _ in audit.aes50_output_addresses(ConsoleState(keep))}
    keep.update({a: v for a, v in state.values.items() if a in wanted})
    return ConsoleState(keep, console_model=state.console_model)


@pytest.fixture(scope="module")
def full_state() -> ConsoleState:
    return _full_state()


@pytest.fixture(scope="module")
def scoped():
    return watch_scope.scoped_read_plan(rules=_rules(), conditions=_conditions(), **COMPACT)


# --------------------------------------------------------------------------
# The plan itself
# --------------------------------------------------------------------------


def test_the_scope_is_a_subsequence_of_the_full_plan(scoped):
    """Nothing invented: every scoped entry is a full-plan entry, in order.
    A read cannot be narrowed to an address the desk was never going to be
    asked for."""
    full = list(scoped.full)
    assert list(scoped.plan) == [entry for entry in full if entry in set(scoped.plan)]
    assert set(scoped.plan) <= set(full)
    assert len(scoped.plan) < len(full)


def test_a_compact_plan_is_6195_addresses_and_the_scope_is_3891(scoped):
    """The numbers an earlier change is answered with. They are pinned here so a
    plan change that moves them is visible rather than silent.

    5,712 and 3,392 until an earlier change added each strip's alternate-patch
    group and switch: 48 strips x 2 leaves, in both, because C004 is a
    default rule and reads them. 6,112 and 3,792 until the comms
    half added `/cfg/talk/assign` (T001) to both; 6,113 and 3,793 until
    the global alternate switch `/io/altsw` (C005) did; 6,114
    and 3,794 until an earlier change added each phantom-capable socket's width
    (`/io/in/{grp}/{n}/mode`, 24 on a Compact) for C001; 6,138 and
    3,818 until an earlier change added the three AES50 ports' link status
    and the two monitor sources, which the output-side rules read; 6,167 and
    3,847 since each local socket's own mute (C007), 24 on a Compact; 3,863
    since a DCA's mute (CH004), 16 on a Compact, which only the scope grows
    by: the full plan already held them; 6,195 and 3,891 since the width of
    each bus, Main and Matrix (`busmono`, R011): 28 on a Compact, in both."""
    assert len(scoped.full) == 6195
    assert len(scoped.plan) == 3891


def test_only_the_unread_send_family_is_dropped(scoped):
    """Exactly one address family is dropped, and it is stated in
    `watch_scope`'s docstring: a strip send's `mode`/`pon`. (A DCA's mute
    was the second until CH004 read it.) Anything else showing up here is
    an address some rule reads."""
    strip_send_extras = re.compile(r"^/(?:ch|aux)/\d+/send/(?:\d+|MX\d+)/(?:mode|pon)$")
    dropped = scoped.dropped
    unexpected = [a for a in dropped if not strip_send_extras.match(a)]
    assert unexpected == []
    assert len(dropped) == 2304


def test_every_default_rule_has_a_scope_entry():
    """A rule added to `DEFAULT_RULES` without a row in
    `RULE_ADDRESS_PATTERNS` still works -- it widens the scope to the whole
    plan -- but it silently throws the saving away, so it fails here
    instead."""
    assert (sorted(watch_scope.RULE_ADDRESS_PATTERNS)
            == sorted([rule.id for rule in DEFAULT_RULES] + list(watch_scope.PLAN_RULE_IDS)))


def test_the_plan_bound_fx_rule_keeps_every_address_it_reads(full_state):
    """CV015, the rule Watch adds when the show's plan loads
    an FX bus's effect, reports the same on a read scoped to it."""
    plan = {"busses": {"Vox Verb": {"index": 1, "preset_values": {"inserts": [
        {"point": "preins", "model": "V-REV", "parameters": {}, "engine": 5}]}}}}
    rule = audit.fx_insert_rule(plan)
    values = dict(full_state.values)
    values.update({"/bus/1/preins/ins": "FX5", "/bus/1/preins/on": 0, "/fx/5/mdl": "HALL"})
    state = ConsoleState(values)
    scoped = watch_scope.scoped_read_plan(rules=[rule], conditions=[], **COMPACT)
    assert not scoped.unscoped_rule_ids
    found = rule.check(state)
    assert found and "switched off" in found[0].message and "holds HALL" in found[0].message
    assert rule.check(_restrict(state, scoped.addresses)) == found


def _phantom_rule_and_state(full_state):
    """CV019 bound to a one-channel plan, and a state where that channel's
    condenser has no 48V on LCL 23."""
    plan = {"channels": [{"bank": "ch", "channel": 30, "name": "OH",
                          "source": {"input": "OH", "phantom": True},
                          "patch": {"group": "LCL", "sockets": [23]}}]}
    values = dict(full_state.values)
    values.update({"/ch/30/name": "OH", "/ch/30/in/conn/grp": "LCL", "/ch/30/in/conn/in": 23,
                   "/io/in/LCL/23/vph": 0})
    return audit.phantom_drift_rule(plan), ConsoleState(values)


def test_the_plan_bound_phantom_rule_keeps_every_address_it_reads(full_state):
    """CV019, the rule Watch adds when the show's plan states a phantom,
    reports the same on a read scoped to it."""
    rule, state = _phantom_rule_and_state(full_state)
    scoped = watch_scope.scoped_read_plan(rules=[rule], conditions=[], **COMPACT)
    assert not scoped.unscoped_rule_ids
    found = rule.check(state)
    assert found and "plan has 48V on at LCL 23" in found[0].message
    assert rule.check(_restrict(state, scoped.addresses, scoped.reads_source_names)) == found


@pytest.mark.parametrize("address", ["/ch/30/in/conn/in", "/ch/30/in/conn/grp",
                                     "/io/in/LCL/23/vph", "/ch/30/name"])
def test_dropping_a_phantom_rule_address_from_its_scope_is_caught(full_state, address):
    rule, state = _phantom_rule_and_state(full_state)
    scoped = watch_scope.scoped_read_plan(rules=[rule], conditions=[], **COMPACT)
    assert address in scoped.addresses
    assert rule.check(_restrict(state, scoped.addresses - {address},
                                scoped.reads_source_names)) != rule.check(state)


def _talkback_rules_and_state(full_state):
    """CV021 and CV022 bound to a plan with one monitor mix (bus 5), and a
    state where talkback is assigned, reaches a Main, and misses that mix."""
    plan = {"busses": {"Fill": {"index": 5, "destination": {
        "type": "dedicated_output", "patch": {"group": "LCL", "sockets": [5]}}}}}
    values = dict(full_state.values)
    values.update({"/cfg/talk/assign": "CH40", "/bus/5/name": "Fill Wedge",
                   "/cfg/talk/A/M1": 1})
    return (audit.talkback_monitor_rule(plan), audit.talkback_monitors_note_rule(plan),
            ConsoleState(values))


def test_the_plan_bound_talkback_rules_keep_every_address_they_read(full_state):
    """CV021 and CV022, the rules Watch adds when the show's plan builds a
    monitor mix, report the same on a read scoped to them. The destination
    switches are the second pass's, as T001's are."""
    warn, note, state = _talkback_rules_and_state(full_state)
    scoped = watch_scope.scoped_read_plan(rules=[warn, note], conditions=[], **COMPACT)
    assert not scoped.unscoped_rule_ids and scoped.reads_talkback
    found = warn.check(state) + note.check(state)
    assert [f.rule_id for f in found] == ["CV021", "CV022"]
    restricted = _restrict(state, scoped.addresses, scoped.reads_source_names,
                           scoped.reads_expansion_bays, scoped.reads_talkback)
    assert warn.check(restricted) + note.check(restricted) == found
    without = _restrict(state, scoped.addresses, scoped.reads_source_names,
                        scoped.reads_expansion_bays, False)
    assert warn.check(without) + note.check(without) != found


@pytest.mark.parametrize("address", ["/cfg/talk/assign", "/bus/5/name"])
def test_dropping_a_talkback_rule_address_from_its_scope_is_caught(full_state, address):
    warn, note, state = _talkback_rules_and_state(full_state)
    scoped = watch_scope.scoped_read_plan(rules=[warn, note], conditions=[], **COMPACT)
    assert address in scoped.addresses
    restricted = _restrict(state, scoped.addresses - {address}, scoped.reads_source_names,
                           scoped.reads_expansion_bays, scoped.reads_talkback)
    assert warn.check(restricted) + note.check(restricted) != warn.check(state) + note.check(state)


def _route_rules_and_state(full_state):
    """CV006, CV007 and CV018 bound to a small plan, and a state tripping
    each: ch 30 sends to Drums in the wrong mode with a second planned send
    off, ch 31 has a planned Main route off and an unlisted one on, ch 32
    sends to a Matrix the plan does not list (and to a bus, which CV018 ignores), and Wedge bus 11 is
    on a Main its destinations do not list."""
    plan = {
        "busses": {"Drums": {"index": 10, "destination": {"type": "main", "index": 1}},
                   "Wedge A": {"index": 11, "destination": {"type": "dedicated_output"}},
                   "Side": {"index": 12, "destination": {"type": "main", "index": 1}}},
        "channels": [
            {"bank": "ch", "channel": 30, "name": "Click",
             "bus_sends": [{"bus": "Drums", "mode": "post", "level_db": 0.0},
                           {"bus": "Wedge A", "mode": "pre", "level_db": 0.0}],
             "main_routes": []},
            {"bank": "ch", "channel": 31, "name": "Bass",
             "bus_sends": [{"bus": "Drums", "mode": "post", "level_db": 0.0}],
             "main_routes": [{"index": 2}]},
            {"bank": "ch", "channel": 32, "name": "Crowd", "bus_sends": [], "main_routes": []},
        ],
    }
    values = dict(full_state.values)
    values.update({
        "/bus/10/name": "Drums", "/bus/11/name": "Wedge A", "/bus/12/name": "Side Fill",
        "/ch/30/name": "Click", "/ch/31/name": "Bass", "/ch/32/name": "Crowd",
        "/ch/30/send/10/on": 1, "/ch/30/send/10/mode": "PRE", "/ch/30/send/10/lvl": 0.0,
        "/ch/30/send/11/on": 0, "/ch/30/send/11/lvl": 0.0,
        "/ch/31/send/10/on": 1, "/ch/31/send/10/lvl": 0.0, "/ch/31/send/10/mode": "POST",
        "/ch/31/main/2/on": 0, "/ch/31/main/3/on": 1,
        "/ch/32/send/11/on": 1, "/ch/32/send/11/lvl": -6.0,
        "/ch/32/send/MX2/on": 1, "/ch/32/send/MX2/lvl": -6.0,
        "/bus/11/main/2/on": 1, "/bus/12/main/1/on": 1, "/bus/12/main/2/on": 1,
    })
    return ({"CV006": audit.bus_send_drift_rule(plan), "CV007": audit.main_route_drift_rule(plan),
             "CV018": audit.unplanned_route_rule(plan)}, ConsoleState(values))


#: The address each plan-bound route rule depends on, per the rule alone.
ROUTE_RULE_MUTATIONS = [
    ("CV006", "/ch/30/send/10/mode"), ("CV006", "/ch/30/send/11/on"), ("CV006", "/bus/10/name"),
    ("CV007", "/ch/31/main/2/on"), ("CV007", "/ch/31/main/3/on"),
    ("CV018", "/ch/32/send/MX2/on"), ("CV018", "/ch/32/send/MX2/lvl"),
    ("CV018", "/bus/11/main/2/on"), ("CV018", "/bus/12/main/2/on"), ("CV018", "/bus/12/name"),
]


def test_the_plan_bound_route_rules_keep_every_address_they_read(full_state):
    """CV006, CV007 and CV018, which Watch binds to the show's plan,
    report the same on a read scoped to each."""
    rules, state = _route_rules_and_state(full_state)
    for rule_id, rule in rules.items():
        scoped = watch_scope.scoped_read_plan(rules=[rule], conditions=[], **COMPACT)
        assert not scoped.unscoped_rule_ids, rule_id
        found = rule.check(state)
        assert found, f"{rule_id} does not fire on the fixture"
        assert rule.check(_restrict(state, scoped.addresses)) == found


@pytest.mark.parametrize("rule_id,address", ROUTE_RULE_MUTATIONS,
                         ids=[f"{r}{a}" for r, a in ROUTE_RULE_MUTATIONS])
def test_dropping_a_route_rules_address_from_its_scope_is_caught(full_state, rule_id, address):
    rules, state = _route_rules_and_state(full_state)
    rule = rules[rule_id]
    scoped = watch_scope.scoped_read_plan(rules=[rule], conditions=[], **COMPACT)
    assert address in scoped.addresses
    assert rule.check(_restrict(state, scoped.addresses - {address})) != rule.check(state)


def test_only_the_bound_cv006_reads_a_sends_pre_post_mode():
    """The default rules still drop `mode`; CV006 bound to a plan keeps it."""
    mode = "/ch/30/send/10/mode"
    default = watch_scope.scoped_read_plan(**COMPACT)
    assert mode not in default.addresses
    rule = audit.bus_send_drift_rule(
        {"channels": [{"bank": "ch", "channel": 30, "bus_sends": [{"bus": "A"}]}]})
    assert mode in watch_scope.scoped_read_plan(rules=[rule], **COMPACT).addresses
    assert len(default.full) == 6195  # a Compact's read is not larger for it


def test_an_unknown_rule_widens_the_scope_to_everything():
    """The fail-safe direction. A rule this module has never heard of gets
    the whole plan and is named, rather than being quietly assumed to read
    nothing."""
    from atoo.audit import AuditRule, Severity

    mystery = AuditRule("ZZZ", Severity.INFO, "routing", "Mystery",
                        "unknown to watch_scope", lambda state: [])
    result = watch_scope.scoped_read_plan(rules=list(DEFAULT_RULES) + [mystery], **COMPACT)
    assert result.unscoped_rule_ids == ("ZZZ",)
    assert result.plan == result.full


def test_a_watch_rule_with_no_matching_condition_widens_the_scope():
    """`WATCH:*` rules are scoped from the CONDITION, not the rule, so a
    caller who passes the rules and forgets the conditions must get the
    whole plan rather than a scope built from the structural rules alone."""
    rules = build_watch_rules(_conditions())
    result = watch_scope.scoped_read_plan(rules=rules, conditions=[], **COMPACT)
    assert result.unscoped_rule_ids == tuple(r.id for r in rules)
    assert result.plan == result.full


@pytest.mark.parametrize("field,expected", [
    ("muted", {"/ch/1/name", "/ch/1/mute"}),
    ("fader_db", {"/ch/1/name", "/ch/1/fdr"}),
    ("dca", {"/ch/1/name", "/ch/1/tags", "/dca/1/name"}),
    ("mute_group", {"/ch/1/name", "/ch/1/tags", "/mgrp/1/name"}),
    ("patch", {"/ch/1/name", "/ch/1/in/conn/grp", "/ch/1/in/conn/in"}),
    ("send_on", {"/ch/1/name", "/ch/1/send/5/on", "/bus/5/name"}),
    ("send_db", {"/ch/1/name", "/ch/1/send/5/lvl", "/bus/5/name"}),
    ("send_mode", {"/ch/1/name", "/ch/1/send/5/mode", "/bus/5/name"}),
    ("phantom", {"/ch/1/name", "/ch/1/in/conn/grp", "/ch/1/in/conn/in", "/io/in/LCL/3/vph",
                 "/io/in/LCL/3/mode", "/io/altsw", "/ch/1/in/set/altsrc"}),
])
def test_each_condition_field_keeps_what_evaluating_it_reads(field, expected):
    """Every strip's `/name` too, not just the named channel's:
    `_resolve_channel_base` matches the condition's channel against all of
    them, so a scope that kept one strip's name would resolve nothing."""
    value = {"muted": False, "fader_db": -10.0, "dca": "Drums",
             "mute_group": "FX", "patch": "LCL 3", "send_on": True, "send_db": -10.0,
             "send_mode": "pre", "phantom": True}[field]
    operator = "<=" if field in ("fader_db", "send_db") else "=="
    extra = {"bus": "BUS 5"} if field.startswith("send_") else {}
    conditions = parse_watch_conditions(json.dumps({"watch_conditions": [{
        "id": "c", "description": "d", "channel": "Crowd Mic", "field": field,
        "operator": operator, "value": value, "severity": "warning", **extra}]}))
    result = watch_scope.scoped_read_plan(
        rules=build_watch_rules(conditions), conditions=conditions, **COMPACT)
    assert expected <= result.addresses
    # And nothing beyond the field's own families: `/ch/40/name` yes,
    # `/ch/40/fdr` only when the field is fader_db.
    assert "/ch/40/name" in result.addresses
    if field != "fader_db":
        assert "/ch/40/fdr" not in result.addresses
    # The send conditions name the bus, and a bus's name labels a finding.
    if field == "send_mode":
        assert "/ch/40/send/5/mode" in result.addresses


# --------------------------------------------------------------------------
# The test that matters: scoping drops no rule
# --------------------------------------------------------------------------


def test_the_fixture_state_trips_every_rule_watch_runs(full_state):
    """Guard on the guard. `test_scoping_changes_no_finding` compares two
    audits, and it proves nothing about a rule that did not fire in
    either. Every rule `watch` runs has to fire here."""
    fired = {f.rule_id for f in run_audit(full_state, _rules())}
    missing = {rule.id for rule in _rules()} - fired
    # R007 fires only where R002/R005/R006 stand down, so not in the
    # same state; `unchecked_state` below is its fixture.
    # R013 speaks only for a plan that states the split (`test_signal_split_rules`).
    assert missing == {"R007", "R013"}
    assert "R007" in {f.rule_id for f in run_audit(_unchecked_state(), _rules())}


def _unchecked_state() -> ConsoleState:
    """The fixture state as a read that skipped AES50-A would have it: the stage box reported, its outputs never read."""
    return ConsoleState({a: v for a, v in _full_state().values.items()
                         if not a.startswith("/io/out/A/")})


def test_scoping_changes_no_finding_where_a_route_was_not_checked(scoped):
    state = _unchecked_state()
    rules = _rules()
    restricted = _restrict(state, scoped.addresses, scoped.reads_source_names,
                           scoped.reads_expansion_bays, scoped.reads_talkback)
    assert run_audit(restricted, rules) == run_audit(state, rules)


def test_sp_r007_alone_keeps_every_address_it_reads():
    rule = _rule_by_id("R007")
    plan = watch_scope.scoped_read_plan(rules=[rule], conditions=_conditions(), **COMPACT)
    state = _unchecked_state()
    found = rule.check(state)
    assert found
    assert rule.check(_restrict(state, plan.addresses, plan.reads_source_names)) == found
    # ... and its port status is what it rests on.
    assert rule.check(_restrict(state, plan.addresses - {"/$stat/A/stat"},
                                plan.reads_source_names)) != found


def test_scoping_changes_no_finding(full_state, scoped):
    """The scoped plan is exactly what `watch`'s rules read: auditing the
    restricted state produces the identical findings, detail strings and
    cited addresses."""
    rules = _rules()
    assert run_audit(_restrict(full_state, scoped.addresses, scoped.reads_source_names, scoped.reads_expansion_bays, scoped.reads_talkback), rules) == run_audit(full_state, rules)


def _rule_by_id(rule_id: str):
    for rule in _rules():
        if rule.id == rule_id:
            return rule
    raise AssertionError(f"no rule {rule_id!r} in the set watch runs")


_ALL_RULES = _rules()


@pytest.mark.parametrize("rule", _ALL_RULES, ids=[r.id for r in _ALL_RULES])
def test_each_rule_alone_keeps_every_address_it_reads(full_state, rule):
    """Per rule, not per union -- **the coverage test an earlier change asked
    for**. Scope the plan to this one rule and it must still report
    exactly what it reported with the whole plan in hand.

    The union test above cannot do this job: a wrong row in
    `RULE_ADDRESS_PATTERNS` survives it whenever some *other* enabled rule
    happens to keep the same address, and then breaks the day somebody
    runs `watch` with a shorter rule set. Measured, not hypothetical --
    dropping `MGRP_NAME` from CH003's row passes the union test,
    because the `mute_group` watch condition keeps `/mgrp/{n}/name` too.
    """
    plan = watch_scope.scoped_read_plan(
        rules=[rule], conditions=_conditions(), **COMPACT)
    scope = plan.addresses
    if rule.id == "R007":
        pytest.skip("fires only where R002/R005/R006 stand down: "
                    "test_sp_r007_alone_keeps_every_address_it_reads")
    if rule.id == "R013":
        pytest.skip("fires only for a plan that states the split; "
                    "test_r013_reads_what_r012_reads")
    assert rule.check(full_state), f"{rule.id} does not fire on the fixture state"
    assert (rule.check(_restrict(full_state, scope, plan.reads_source_names, plan.reads_expansion_bays, plan.reads_talkback))
            == rule.check(full_state))


def test_scoping_changes_nothing_on_a_factory_desk(scoped):
    """The other end of the range: a state with nothing set. A factory
    Compact reports no findings at all (FR-4.7), and the scoped read has
    to reach that same answer rather than a different kind of silence."""
    quiet = ConsoleState({a: v for a, v in _full_state().values.items()})
    for address, _ in audit.console_read_plan(**COMPACT):
        leaf = address.split("/", 3)[-1]
        for suffix, default in _DEFAULTS.items():
            if leaf.endswith(suffix):
                quiet.values[address] = default
                break
    # The fixture's stage boxes are second-pass reads in no plan: a factory
    # desk has no device on any port and nothing patched to one.
    for address in list(quiet.values):
        if re.match(r"^/io/out/[ABC]/\d+/(?:grp|in)$", address):
            quiet.values[address] = "OFF" if address.endswith("/grp") else 0
    for n in (21, 22):
        quiet.values[f"/ch/{n}/in/conn/grp"], quiet.values[f"/ch/{n}/in/conn/in"] = "OFF", 0
    rules = _rules()
    assert run_audit(quiet, rules) == []
    assert run_audit(_restrict(quiet, scoped.addresses, scoped.reads_source_names, scoped.reads_expansion_bays, scoped.reads_talkback), rules) == []


def test_render_coverage_is_unchanged_by_scoping(full_state, scoped):
    """`watch_cmd` prints `render_coverage(first_state)` at the baseline,
    and it is a claim about which sockets were read -- so a scoped read
    that quietly stopped covering a socket group would make that line a
    lie while every rule still passed."""
    assert (audit.render_coverage(_restrict(full_state, scoped.addresses, scoped.reads_source_names, scoped.reads_expansion_bays, scoped.reads_talkback))
            == audit.render_coverage(full_state))


# One address per rule, chosen because that rule's finding depends on it.
# This is the mutation set: each entry, removed from the scope THAT RULE
# ALONE gets, must change what the rule reports.
MUTATIONS = [
    ("R001", "/bus/1/name"),
    ("R002", "/bus/1/name"),
    ("R003", "/io/out/LCL/3/grp"),
    ("R004", "/io/out/LCL/5/in"),
    ("R005", "/ch/1/main/3/on"),
    ("R006", "/bus/4/send/MX2/on"),
    ("R006", "/main/1/send/MX3/on"),
    # The stage box's status, and the phones' source.
    ("R002", "/$stat/A/stat"),
    ("R006", "/cfg/mon/1/src"),
    ("C001", "/io/in/LCL/20/vph"),
    ("C001", "/io/in/LCL/13/mode"),
    ("C002", "/ch/2/in/conn/grp"),
    ("C003", "/ch/11/in/conn/grp"),
    ("C004", "/ch/12/in/set/altsrc"),
    ("C004", "/ch/12/in/conn/altgrp"),
    ("R009", "/ch/17/in/conn/grp"),
    ("R009", "/ch/17/in/conn/in"),
    ("R009", "/ch/17/send/8/on"),
    ("R009", "/aux/4/main/4/on"),
    ("R009", "/aux/4/in/conn/grp"),
    ("R009", "/ch/17/name"),
    ("R009", "/io/altsw"),
    ("R009", "/ch/19/in/conn/altgrp"),
    ("R010", "/ch/18/in/conn/grp"),
    ("R010", "/ch/18/send/MX5/on"),
    ("R010", "/ch/18/send/MX5/lvl"),
    ("R010", "/ch/18/name"),
    ("R012", "/ch/20/main/4/on"),
    ("R012", "/ch/20/send/3/on"),
    ("R012", "/bus/3/main/4/on"),
    ("R011", "/bus/6/busmono"),
    ("R011", "/main/1/busmono"),
    ("R011", "/mtx/7/busmono"),
    ("R011", "/bus/6/name"),
    ("R011", "/io/out/LCL/1/in"),
    ("R011", "/io/out/LCL/2/grp"),
    ("R011", "/ch/5/main/1/on"),
    ("R011", "/ch/1/send/MX7/on"),
    ("C008", "/$stat/B/stat"),
    ("C008", "/ch/21/in/conn/grp"),
    ("C008", "/ch/21/in/conn/in"),
    ("C008", "/ch/21/name"),
    ("C009", "/$stat/C/stat"),
    ("C010", "/$stat/A/stat"),
    ("C007", "/io/in/LCL/5/mute"),
    ("C007", "/io/in/LCL/14/mute"),
    ("C007", "/io/in/LCL/13/mode"),
    ("C007", "/ch/2/in/conn/grp"),
    ("C007", "/io/altsw"),
    ("C007", "/ch/20/in/conn/altgrp"),
    ("T001", "/cfg/talk/assign"),
    # R008 and C006: the name that makes a strip in use, the mute and floor
    # that excuse it, the talk mic and the monitor source that exempt it,
    # the patch group, and the alternate that hands a strip to C004/C005.
    ("R008", "/ch/6/name"),
    ("R008", "/ch/10/mute"),
    ("R008", "/ch/9/fdr"),
    ("R008", "/cfg/talk/assign"),
    ("R008", "/cfg/mon/2/src"),
    ("C006", "/ch/6/in/conn/grp"),
    ("C006", "/cfg/talk/assign"),
    ("C006", "/io/altsw"),
    ("C006", "/ch/16/in/conn/altgrp"),
    ("CH001", "/ch/4/tags"),
    ("CH002", "/dca/1/fdr"),
    ("CH002", "/dca/1/name"),
    ("CH002", "/ch/4/tags"),
    ("CH003", "/mgrp/2/mute"),
    ("CH003", "/mgrp/2/name"),
    ("CH003", "/ch/5/tags"),
    ("CH004", "/dca/3/mute"),
    ("CH004", "/dca/3/name"),
    ("CH004", "/ch/13/tags"),
    ("N001", "/ch/6/name"),
    ("N002", "/bus/3/name"),
    ("L001", "/ch/8/send/4/lvl"),
    ("L001", "/bus/4/send/MX2/on"),
    ("L001", "/main/1/send/MX3/lvl"),
    ("L002", "/ch/9/fdr"),
    ("L002", "/bus/5/fdr"),
    ("WATCH:crowd-never-muted", "/ch/10/mute"),
    ("WATCH:crowd-never-muted", "/ch/10/name"),
    ("WATCH:crowd-patch", "/ch/10/in/conn/in"),
    ("WATCH:bass-not-in-drums", "/dca/1/name"),
    ("WATCH:bass-not-in-drums", "/ch/4/tags"),
    ("WATCH:gtr-out-of-fx", "/mgrp/2/name"),
    ("WATCH:gtr-out-of-fx", "/ch/5/tags"),
    ("WATCH:piano-in-iem", "/ch/33/send/9/on"),
    ("WATCH:piano-in-iem", "/ch/33/name"),
    ("WATCH:piano-iem-level", "/ch/33/send/9/lvl"),
    ("WATCH:piano-48v", "/io/in/LCL/15/vph"),
    ("WATCH:piano-48v", "/ch/33/in/conn/in"),
    ("WATCH:piano-48v", "/ch/33/in/conn/grp"),
]


@pytest.mark.parametrize("rule_id,address", MUTATIONS,
                         ids=[f"{r}{a}" for r, a in MUTATIONS])
def test_mutating_a_rules_own_scope_is_caught(full_state, rule_id, address):
    """Remove one address from the scope this rule alone gets, and the
    rule must report something different. Without this,
    `test_each_rule_alone_keeps_every_address_it_reads` would pass just as
    happily against a scope that kept nothing at all -- and the
    whole-rule-set version of it would pass against a wrong row in
    `RULE_ADDRESS_PATTERNS` whenever some other rule happened to keep the
    address, which is how a wrong row would reach a `watch` run with a
    shorter rule set.

    This is the test that fails under mutation. Dropping `MGRP_NAME` from
    CH003's row is caught here (`CH003` / `/mgrp/2/name`) and is NOT
    caught by the whole-rule-set equivalence test, because the
    `mute_group` watch condition keeps that family too.
    """
    rule = _rule_by_id(rule_id)
    plan = watch_scope.scoped_read_plan(
        rules=[rule], conditions=_conditions(), **COMPACT)
    scope = plan.addresses
    assert address in scope, f"{address} is not in {rule_id}'s own scope"
    assert (rule.check(_restrict(full_state, scope - {address},
                                 plan.reads_source_names,
                                 plan.reads_expansion_bays,
                                 plan.reads_talkback))
            != rule.check(full_state)), (
        f"dropping {address} changed nothing {rule_id} reports -- this fixture "
        f"does not actually pin that address, so the scope is unchecked for it")


def test_r013_reads_what_r012_reads():
    assert (watch_scope.RULE_ADDRESS_PATTERNS["R013"]
            == watch_scope.RULE_ADDRESS_PATTERNS["R012"])


def test_dropping_a_send_mode_changes_nothing(full_state, scoped):
    """The converse, and the reason the scope is worth having: the 2,320
    addresses it drops really are read by nothing."""
    rules = _rules()
    for address in ("/ch/8/send/4/mode", "/ch/8/send/4/pon"):
        assert address not in scoped.addresses
        widened = scoped.addresses | {address}
        assert (run_audit(_restrict(full_state, widened, True, True, True), rules)
                == run_audit(full_state, rules))


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------


def test_the_rates_come_from_the_a11_capture():
    """Not invented: both rates are the capture's own totals net of the
    320 addresses the desk does not answer, each of which costs
    `retries + 1` attempts at the 1.0s timeout -- 3.0s, and 320 x 3.0 =
    960.0s, which is the capture's own accounting of its wall time."""
    data = json.loads(CAPTURE.read_text())
    assert data["per_leaf"]["seconds"] == watch_scope.A11_PER_LEAF_SECONDS
    assert data["per_leaf"]["values"] == watch_scope.A11_PER_LEAF_ANSWERED
    assert data["node_dumps"]["seconds"] == watch_scope.A11_NODE_DUMP_SECONDS
    assert data["node_dumps"]["requests"] == watch_scope.A11_NODE_DUMP_REQUESTS
    assert data["plan_addresses"] - data["per_leaf"]["values"] == watch_scope.A11_UNANSWERED_ADDRESSES
    assert watch_scope.A11_TIMEOUT_SECONDS == 960.0
    assert round(watch_scope.PER_LEAF_SECONDS_PER_ADDRESS * 1000, 2) == 6.75
    assert round(watch_scope.NODE_DUMP_SECONDS_PER_REQUEST * 1000, 2) == 10.30


def test_scoping_does_not_get_a_full_watch_pass_under_the_budget(scoped):
    """The answer to the "cheaper thing to try first": **no**.
    Scoping takes a per-leaf pass from ~41s to ~26s, which is still six
    times the budget, and it saves the node-dump path nothing at all --
    the leaves it drops live inside object nodes the read still fetches."""
    budget = watch_scope.RESPONSIVENESS_BUDGET_SECONDS[1]
    assert scoped.per_leaf_seconds > budget
    full = watch_scope.ScopedReadPlan(scoped.full, scoped.full)
    assert scoped.node_dump_requests == full.node_dump_requests == 323
    assert scoped.node_dump_seconds == full.node_dump_seconds
    # An earlier change is what did move the node-dump path: names, not scope. A
    # watch pass between name refreshes skips the 88 name leaves -- ~3.3s
    # down to ~2.4s at A11's rates -- and the first pass and each refresh
    # stay at 323.
    assert full.node_dump_requests_between_refreshes == 235
    assert scoped.node_dump_requests_between_refreshes == 235


def test_watch_conditions_alone_would_fit_the_budget():
    """What scoping CAN buy, and the only thing it can: a `watch` running
    operator conditions and no structural rules reads 312 addresses, ~2.1s
    per-leaf. That is not the thing whose responsiveness was in question,
    which is why it settles rather than solves an earlier change."""
    # The five fields the vocabulary had when this was measured. The send and
    # phantom conditions read every strip's sends and each jack's 48V, which a
    # watch with no structural rules would have to fetch whole.
    conditions = [c for c in _conditions()
                  if c["field"] in ("muted", "fader_db", "dca", "mute_group", "patch")]
    result = watch_scope.scoped_read_plan(
        rules=build_watch_rules(conditions), conditions=conditions, **COMPACT)
    assert len(result.plan) == 312
    assert result.per_leaf_seconds < watch_scope.RESPONSIVENESS_BUDGET_SECONDS[0]


def test_scope_report_names_every_scope_and_its_verdict():
    text = watch_scope.scope_report()
    assert "full read plan (no scoping)" in text
    assert "DEFAULT_RULES + realistic watchlist" in text
    assert "OVER the 3-4s budget" in text
    assert "6195" in text and "3891" in text
