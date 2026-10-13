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
]})


def _conditions() -> list[dict]:
    return parse_watch_conditions(CONDITIONS_JSON, source="<test>")


def _rules():
    return list(DEFAULT_RULES) + build_watch_rules(_conditions())


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
    # Matrix 4, fed by bus 4, is the phones' source. Drop the
    # source from a scope and R006 calls it unpatched.
    values["/bus/4/send/MX4/on"], values["/bus/4/send/MX4/lvl"] = 1, 0.0
    values["/cfg/mon/1/src"] = "MTX.4"
    # The watch conditions: muted when it must not be, fader over its cap,
    # patched somewhere other than LCL 9.
    values["/ch/10/name"], values["/ch/10/mute"], values["/ch/10/fdr"] = "Crowd Mic", 1, -5.0
    values["/ch/10/in/conn/grp"], values["/ch/10/in/conn/in"] = "LCL", 11
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


def test_a_compact_plan_is_6143_addresses_and_the_scope_is_3823(scoped):
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
    and the two monitor sources, which the output-side rules read."""
    assert len(scoped.full) == 6143
    assert len(scoped.plan) == 3823


def test_only_the_two_unread_families_are_dropped(scoped):
    """Exactly two address families are dropped, and each is stated in
    `watch_scope`'s docstring: a strip send's `mode`/`pon`, and a DCA's
    mute. Anything else showing up here is an address some rule reads."""
    strip_send_extras = re.compile(r"^/(?:ch|aux)/\d+/send/(?:\d+|MX\d+)/(?:mode|pon)$")
    dca_mute = re.compile(r"^/dca/\d+/mute$")
    dropped = scoped.dropped
    unexpected = [a for a in dropped
                  if not strip_send_extras.match(a) and not dca_mute.match(a)]
    assert unexpected == []
    assert len(dropped) == 2304 + 16


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
])
def test_each_condition_field_keeps_what_evaluating_it_reads(field, expected):
    """Every strip's `/name` too, not just the named channel's:
    `_resolve_channel_base` matches the condition's channel against all of
    them, so a scope that kept one strip's name would resolve nothing."""
    value = {"muted": False, "fader_db": -10.0, "dca": "Drums",
             "mute_group": "FX", "patch": "LCL 3"}[field]
    operator = "<=" if field == "fader_db" else "=="
    conditions = parse_watch_conditions(json.dumps({"watch_conditions": [{
        "id": "c", "description": "d", "channel": "Crowd Mic", "field": field,
        "operator": operator, "value": value, "severity": "warning"}]}))
    result = watch_scope.scoped_read_plan(
        rules=build_watch_rules(conditions), conditions=conditions, **COMPACT)
    assert expected <= result.addresses
    # And nothing beyond the field's own families: `/ch/40/name` yes,
    # `/ch/40/fdr` only when the field is fader_db.
    assert "/ch/40/name" in result.addresses
    if field != "fader_db":
        assert "/ch/40/fdr" not in result.addresses


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
    assert missing == {"R007"}
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
    ("T001", "/cfg/talk/assign"),
    ("CH001", "/ch/4/tags"),
    ("CH002", "/dca/1/fdr"),
    ("CH002", "/dca/1/name"),
    ("CH002", "/ch/4/tags"),
    ("CH003", "/mgrp/2/mute"),
    ("CH003", "/mgrp/2/name"),
    ("CH003", "/ch/5/tags"),
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


def test_dropping_a_send_mode_changes_nothing(full_state, scoped):
    """The converse, and the reason the scope is worth having: the 2,320
    addresses it drops really are read by nothing."""
    rules = _rules()
    for address in ("/ch/8/send/4/mode", "/ch/8/send/4/pon", "/dca/1/mute"):
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
    which is why it settles rather than solves #196."""
    conditions = _conditions()
    result = watch_scope.scoped_read_plan(
        rules=build_watch_rules(conditions), conditions=conditions, **COMPACT)
    assert len(result.plan) == 312
    assert result.per_leaf_seconds < watch_scope.RESPONSIVENESS_BUDGET_SECONDS[0]


def test_scope_report_names_every_scope_and_its_verdict():
    text = watch_scope.scope_report()
    assert "full read plan (no scoping)" in text
    assert "DEFAULT_RULES + realistic watchlist" in text
    assert "OVER the 3-4s budget" in text
    assert "6143" in text and "3823" in text
