"""A watch condition's `channel` may name a strip by POSITION
(`CH 10`, `DCA 14`), a RANGE (`DCA 10-16`) or a WHOLE KIND (`ALL AUX`),
as well as by name.

Every state here is built in the test -- nothing is read from
`examples/` (CLAUDE.md, "A bundle under examples/ is a living example").
"""

from __future__ import annotations

import json

import pytest

from atoo.audit import ConsoleState, Severity
from atoo.console_facts import CAPACITY
from atoo.watch_conditions import (
    TargetError,
    WatchConditionsError,
    build_watch_rules,
    canonical_target,
    condition_address_patterns,
    merge_drafted_conditions,
    parse_target,
    parse_watch_conditions,
    row_problems,
    target_key,
)


def _cond(**overrides):
    base = {
        "id": "c1", "description": "test condition", "channel": "CH 1",
        "field": "muted", "operator": "==", "value": False, "severity": "warning",
    }
    base.update(overrides)
    return base


def _parse(*conds):
    return parse_watch_conditions(json.dumps({"watch_conditions": list(conds)}))


def _run(state, *conds):
    findings = []
    for rule in build_watch_rules(_parse(*conds)):
        findings += rule.check(state)
    return findings


# ======================================================================
# Parsing and normalisation
# ======================================================================


@pytest.mark.parametrize("text, canonical", [
    ("CH 10", "CH 10"), ("ch10", "CH 10"), ("Chn 10", "CH 10"), ("CHAN 10", "CH 10"),
    ("  ch 10  ", "CH 10"),
    ("AUX 3", "AUX 3"), ("aux3", "AUX 3"),
    ("BUS 3", "BUS 3"), ("bus16", "BUS 16"),
    ("MAIN 3", "MAIN 3"), ("main 4", "MAIN 4"),
    ("MTX 3", "MTX 3"), ("MATRIX 3", "MTX 3"), ("matrix8", "MTX 8"),
    ("DCA 14", "DCA 14"), ("dca 1", "DCA 1"),
])
def test_a_position_parses_case_insensitively_with_the_space_optional(text, canonical):
    target = parse_target(text)
    assert not target.is_name
    assert target.canonical == canonical
    assert canonical_target(text) == canonical


@pytest.mark.parametrize("text, canonical, bases", [
    ("DCA 10-16", "DCA 10-16", [f"/dca/{n}" for n in range(10, 17)]),
    ("dca10 - 12", "DCA 10-12", ["/dca/10", "/dca/11", "/dca/12"]),
    ("ch 1-3", "CH 1-3", ["/ch/1", "/ch/2", "/ch/3"]),
    ("DCA 3-3", "DCA 3", ["/dca/3"]),
])
def test_a_range_covers_both_ends(text, canonical, bases):
    target = parse_target(text)
    assert target.canonical == canonical
    assert target.bases() == bases


@pytest.mark.parametrize("text, bank", [
    ("ALL AUX", "aux"), ("all main", "main"), ("ALL MATRIX", "mtx"), ("All ch", "ch"),
    ("ALL DCA", "dca"), ("ALL BUS", "bus"),
])
def test_all_of_a_kind_covers_the_consoles_whole_bank(text, bank):
    target = parse_target(text)
    assert target.all_of_kind
    assert target.bases() == [f"/{bank}/{n}" for n in range(1, CAPACITY[bank] + 1)]
    assert target.canonical.startswith("ALL ")


@pytest.mark.parametrize("text", [
    "Kick", "Lead Vox", "All Vox", "Chant", "Mains", "Busy", "Dcable", "MainVox",
])
def test_anything_that_is_not_a_position_is_a_name(text):
    target = parse_target(text)
    assert target.is_name
    assert target.bases() == []
    assert canonical_target(text) == text


@pytest.mark.parametrize("text, reason", [
    ("CH", "has no position"),
    ("dca", "has no position"),
    ("BUS", "has no position or name"),
    ("BUS -", "begins like a position"),
    ("BUS 2 Track", "write its position, BUS 2"),
    ("Aux 2 Keys", "write its position, AUX 2"),
    ("DCA 3-", "begins like a position"),
    ("CH 3x", "begins like a position"),
    ("AUX -2", "begins like a position"),
    ("ALL", "names no kind"),
    ("ALL AUXES", "not a kind"),
    ("CH 41", "CH 41 does not exist"),
    ("CH 0", "CH 0 does not exist"),
    ("AUX 9", "AUX 9 does not exist"),
    ("BUS 17", "BUS 17 does not exist"),
    ("MAIN 5", "MAIN 5 does not exist"),
    ("MTX 9", "MTX 9 does not exist"),
    ("DCA 17", "DCA 17 does not exist"),
    ("DCA 10-17", "DCA 17 does not exist"),
    ("DCA 16-10", "backwards range"),
])
def test_a_target_that_cannot_work_is_refused(text, reason):
    with pytest.raises(TargetError, match=reason):
        parse_target(text)
    with pytest.raises(WatchConditionsError, match=reason):
        _parse(_cond(channel=text))


def test_the_range_ceiling_is_the_console_facts():
    assert parse_target(f"CH {CAPACITY['ch']}").canonical == f"CH {CAPACITY['ch']}"
    with pytest.raises(TargetError):
        parse_target(f"CH {CAPACITY['ch'] + 1}")


def test_target_key_makes_spellings_of_one_target_equal():
    assert target_key("ch 10") == target_key("CH10") == target_key("Chan 10")
    assert target_key("Kick") == target_key("kick ")
    assert target_key("CH 10") != target_key("ch 10 vox")


# ======================================================================
# Fields that do not exist for a kind -- refused at load
# ======================================================================


@pytest.mark.parametrize("channel", ["BUS 1", "MAIN 1", "MTX 1", "DCA 1", "ALL DCA"])
def test_patch_is_refused_on_anything_without_an_input_patch(channel):
    with pytest.raises(WatchConditionsError, match="has no input patch"):
        _parse(_cond(channel=channel, field="patch", value="LCL 1"))


@pytest.mark.parametrize("field", ["dca", "mute_group"])
def test_membership_is_refused_on_a_dca(field):
    with pytest.raises(WatchConditionsError, match="cannot itself be a member"):
        _parse(_cond(channel="DCA 3", field=field, value="Drums"))


@pytest.mark.parametrize("channel", ["BUS 1", "MAIN 1-2", "ALL MTX"])
def test_membership_on_a_bus_main_or_matrix_is_refused_as_unread(channel):
    with pytest.raises(WatchConditionsError, match="does not read"):
        _parse(_cond(channel=channel, field="dca", value="Drums"))


@pytest.mark.parametrize("channel", ["CH 1", "AUX 1-4", "ALL CH"])
@pytest.mark.parametrize("field, operator, value", [
    ("muted", "==", False), ("fader_db", "<=", 0), ("dca", "==", "Drums"),
    ("mute_group", "!=", "FX"), ("patch", "==", "LCL 1"),
])
def test_every_field_applies_to_a_channel_or_aux(channel, field, operator, value):
    _parse(_cond(channel=channel, field=field, operator=operator, value=value))


@pytest.mark.parametrize("channel", ["BUS 1", "MAIN 1", "MTX 1", "DCA 1-16"])
@pytest.mark.parametrize("field, operator, value", [("muted", "==", False), ("fader_db", "<=", 0)])
def test_mute_and_fader_apply_to_every_kind(channel, field, operator, value):
    _parse(_cond(channel=channel, field=field, operator=operator, value=value))


def test_a_name_still_takes_every_field():
    _parse(_cond(channel="Lead Vox", field="patch", value="LCL 1"))


# ======================================================================
# Evaluation against a ConsoleState built here
# ======================================================================


def _state():
    return ConsoleState(values={
        "/ch/1/name": "Kick", "/ch/1/mute": 1, "/ch/1/fdr": 0.0, "/ch/1/tags": "#D1",
        "/ch/2/name": "", "/ch/2/mute": 0, "/ch/2/fdr": -10.0, "/ch/2/tags": "",
        "/aux/1/name": "Track L", "/aux/1/mute": 1, "/aux/1/fdr": 0.0,
        "/aux/2/name": "", "/aux/2/mute": 0, "/aux/2/fdr": 0.0,
        "/aux/3/name": "Track R", "/aux/3/mute": 1, "/aux/3/fdr": 0.0,
        "/bus/1/name": "Drums", "/bus/1/mute": 0, "/bus/1/fdr": 5.0,
        "/main/1/mute": 1, "/main/1/fdr": 0.0,
        "/mtx/2/mute": 0, "/mtx/2/fdr": -3.0,
        "/dca/1/name": "Drums", "/dca/1/mute": 0, "/dca/1/fdr": 0.0,
        "/dca/2/name": "", "/dca/2/mute": 0, "/dca/2/fdr": -20.0,
        "/dca/4/name": "Vox", "/dca/4/mute": 0, "/dca/4/fdr": 2.0,
    })


def test_a_single_position_is_checked():
    findings = _run(_state(), _cond(channel="MAIN 1", field="muted", value=False))
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "WATCH:c1"
    assert f.addresses == ("/main/1/mute",)
    assert f.detail.startswith("MAIN 1 is muted -- ")


def test_all_of_a_kind_gives_one_finding_per_violating_strip_with_its_name():
    findings = _run(_state(), _cond(channel="ALL AUX", field="muted", value=False))
    assert [f.addresses for f in findings] == [("/aux/1/mute",), ("/aux/3/mute",)]
    assert findings[0].detail.startswith('AUX 1 "Track L" is ')
    assert findings[1].detail.startswith('AUX 3 "Track R" is ')


def test_a_range_checks_each_strip_and_skips_the_ones_never_read():
    # DCA 3 was never read: skipped, not a violation.
    findings = _run(_state(), _cond(channel="DCA 1-4", field="fader_db",
                                    operator="<=", value=-10))
    assert [f.addresses for f in findings] == [("/dca/1/fdr",), ("/dca/4/fdr",)]
    assert findings[0].detail.startswith('DCA 1 "Drums" has its fader at ')
    assert findings[1].detail.startswith('DCA 4 "Vox" has its fader at ')


def test_a_strip_with_an_empty_name_is_cited_by_position_alone():
    findings = _run(_state(), _cond(channel="CH 2", field="fader_db", operator=">=", value=0))
    assert findings[0].detail.startswith("CH 2 has its fader at ")


def test_a_bus_and_a_matrix_by_position():
    findings = _run(_state(),
                    _cond(id="b", channel="bus1", field="fader_db", operator="<=", value=0),
                    _cond(id="m", channel="MATRIX 2", field="muted", value=True))
    assert [(f.rule_id, f.addresses) for f in findings] == [
        ("WATCH:b", ("/bus/1/fdr",)), ("WATCH:m", ("/mtx/2/mute",))]


def test_membership_and_patch_by_position():
    state = _state()
    state.values.update({"/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1})
    findings = _run(state,
                    _cond(id="d", channel="CH 1-2", field="dca", value="Drums"),
                    _cond(id="p", channel="CH 1", field="patch", operator="!=", value="LCL 1"))
    assert [(f.rule_id, f.addresses) for f in findings] == [
        ("WATCH:d", ("/ch/2/tags",)),
        ("WATCH:p", ("/ch/1/in/conn/grp", "/ch/1/in/conn/in"))]


def test_nothing_fires_when_every_strip_holds():
    assert _run(_state(), _cond(channel="ALL DCA", field="muted", value=False)) == []


def test_a_name_is_still_resolved_by_name():
    findings = _run(_state(), _cond(channel="kick", field="muted", value=False))
    assert [f.addresses for f in findings] == [("/ch/1/mute",)]
    assert findings[0].detail.startswith('CH 1 "Kick" is muted -- ')


# ======================================================================
# Precedence: a position wins over a strip named like one, and says so
# ======================================================================


def test_a_position_wins_over_a_strip_named_like_it_and_says_so_at_info():
    state = ConsoleState(values={
        "/ch/3/name": "CH 10", "/ch/3/mute": 1,
        "/ch/10/name": "Snare", "/ch/10/mute": 1,
    })
    findings = _run(state, _cond(channel="ch 10", field="muted", value=False))
    info = [f for f in findings if f.severity == Severity.INFO]
    real = [f for f in findings if f.severity != Severity.INFO]
    assert [f.addresses for f in real] == [("/ch/10/mute",)]
    assert len(info) == 1
    assert info[0].addresses == ("/ch/3/name",)
    assert "read as the position CH 10" in info[0].detail


def test_no_overlap_info_when_no_strip_is_named_like_the_position():
    findings = _run(_state(), _cond(channel="CH 1", field="muted", value=True))
    assert findings == []


# ======================================================================
# Merge, the editor's check, and the read scope
# ======================================================================


def test_merge_treats_two_spellings_of_a_position_as_one_target():
    existing = {"watch_conditions": [_cond(id="mine", channel="ch 10")]}
    drafted = _parse(_cond(id="theirs", channel="CH10"))
    document, report = merge_drafted_conditions(existing, drafted)
    assert report.overlaps == (("theirs", "mine"),)
    # A drafted position is written canonically; yours is left as you wrote it.
    channels = [c["channel"] for c in document["watch_conditions"]]
    assert channels == ["ch 10", "CH 10"]


def test_row_problems_names_the_cell_and_gives_the_canonical_spelling():
    assert row_problems(_cond(channel="dca1-4", field="fader_db", value=0)) == {
        "canonical": "DCA 1-4", "position": True, "scoped": False}
    assert "begins like a position" in row_problems(_cond(channel="BUS -"))["channel"]
    assert "has no input patch" in row_problems(
        _cond(channel="DCA 1", field="patch", value="LCL 1"))["field"]
    assert "not a socket" in row_problems(
        _cond(channel="Kick", field="patch", value="LCL 99"))["value"]
    assert row_problems(_cond(channel="Kick"))["position"] is False


@pytest.mark.parametrize("cond", [
    _cond(channel="BUS -"), _cond(channel="DCA 16-10"), _cond(channel="MAIN 9"),
    _cond(channel="BUS 1", field="patch", value="LCL 1"),
    _cond(channel="DCA 2", field="mute_group", value="FX"),
    _cond(channel="Kick", field="patch", value="LCL 99"),
])
def test_row_problems_refuses_exactly_what_the_loader_refuses(cond):
    problems = {k: v for k, v in row_problems(cond).items()
                if k not in ("canonical", "position", "scoped")}
    assert problems
    with pytest.raises(WatchConditionsError):
        _parse(cond)


def test_a_position_reads_its_own_banks_addresses():
    patterns = condition_address_patterns(_parse(_cond(channel="DCA 1-4", field="fader_db",
                                                       operator="<=", value=0))[0])
    assert r"^/dca/\d+/fdr$" in patterns
    assert r"^/dca/\d+/name$" in patterns
    # The overlap INFO reads every channel and aux name.
    assert r"^/(?:ch|aux)/\d+/name$" in patterns


def test_a_scoped_read_gives_the_same_findings_for_position_targets():
    """The `watch_scope` guarantee (an address wrongly omitted is a rule
    that silently stops firing), held for the new targets: the findings
    on a state restricted to the scoped plan equal those on the whole."""
    from atoo import audit
    from atoo.watch_scope import scoped_read_plan

    conds = _parse(
        _cond(id="a", channel="ALL DCA", field="fader_db", operator="<=", value=-10),
        _cond(id="b", channel="MAIN 1", field="muted", value=False),
        _cond(id="c", channel="ALL AUX", field="muted", value=False),
        _cond(id="d", channel="CH 1-2", field="dca", value="Drums"),
    )
    rules = build_watch_rules(conds)
    state = _state()
    scoped = scoped_read_plan(rules=rules, conditions=conds)
    kept = {address for address, _ in scoped.plan}
    narrowed = ConsoleState(values={a: v for a, v in state.values.items() if a in kept})
    full = audit.run_audit(state, rules=rules)
    assert full
    assert audit.run_audit(narrowed, rules=rules) == full
