"""Scoped watch-target names (follow-up to an earlier change, the maintainer 2026-10-01):
`BUS Drums`, `CH Kick`, `MAIN PA` -- "the strip of that kind named this",
resolved ONCE at Start to a position and watched by position after that.

Every state here is built in the test -- nothing is read from
`examples/`.
"""

from __future__ import annotations

import json

import pytest

from atoo.audit import ConsoleState, Severity, console_read_plan
from atoo.watch import watch
from atoo.watch_conditions import (
    WatchConditionsError,
    build_watch_rules,
    canonical_target,
    condition_address_patterns,
    merge_drafted_conditions,
    parse_target,
    parse_watch_conditions,
    read_names_at_start,
    row_problems,
    start_name_addresses,
    target_key,
)


def _cond(**overrides):
    base = {
        "id": "c1", "description": "test condition", "channel": "BUS Drums",
        "field": "muted", "operator": "==", "value": False, "severity": "error",
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


def _state(**extra):
    values = {
        "/ch/1/name": "Kick", "/ch/1/mute": 1, "/ch/1/fdr": 0.0,
        "/ch/2/name": "Snare", "/ch/2/mute": 0, "/ch/2/fdr": 0.0,
        "/aux/1/name": "Tracks", "/aux/1/mute": 1, "/aux/1/fdr": 0.0,
        "/bus/1/name": "Drums", "/bus/1/mute": 1, "/bus/1/fdr": 0.0,
        "/bus/2/name": "Mon 1", "/bus/2/mute": 0, "/bus/2/fdr": 0.0,
        "/bus/3/name": "Mon 2", "/bus/3/mute": 0, "/bus/3/fdr": 0.0,
        "/bus/4/name": "Mon 2", "/bus/4/mute": 0, "/bus/4/fdr": 0.0,
        "/main/1/mute": 1, "/main/1/fdr": 0.0,
        "/dca/1/name": "Drums", "/dca/1/mute": 0, "/dca/1/fdr": -20.0,
        "/dca/2/name": "Vocals", "/dca/2/mute": 0, "/dca/2/fdr": 5.0,
    }
    values.update(extra)
    return ConsoleState(values=values)


def _split(findings):
    return ([f for f in findings if f.severity == Severity.INFO],
            [f for f in findings if f.severity == Severity.WARNING],
            [f for f in findings if f.severity not in (Severity.INFO, Severity.WARNING)])


# ======================================================================
# Parsing and normalisation
# ======================================================================


@pytest.mark.parametrize("text, bank, name, canonical", [
    ("BUS Drums", "bus", "Drums", "BUS Drums"),
    ("bus drums", "bus", "drums", "BUS drums"),
    ("CH Kick", "ch", "Kick", "CH Kick"),
    ("chan  Kick", "ch", "Kick", "CH Kick"),
    ("Chn Kick", "ch", "Kick", "CH Kick"),
    ("AUX Tracks", "aux", "Tracks", "AUX Tracks"),
    ("DCA Vocals", "dca", "Vocals", "DCA Vocals"),
    ("MAIN PA", "main", "PA", "MAIN PA"),
    ("matrix Delay", "mtx", "Delay", "MTX Delay"),
    ("MTX Delay Left", "mtx", "Delay Left", "MTX Delay Left"),
    ("  BUS Drums  ", "bus", "Drums", "BUS Drums"),
])
def test_a_kind_word_and_a_name_is_a_scoped_name(text, bank, name, canonical):
    target = parse_target(text)
    assert target.is_scoped and not target.is_name and not target.is_position
    assert (target.bank, target.name) == (bank, name)
    assert target.canonical == canonical
    assert canonical_target(text) == canonical
    assert target.bases() == []


def test_the_kind_word_is_normalised_and_the_name_keeps_its_spelling():
    assert canonical_target("bus drums") == "BUS drums"
    assert canonical_target("Bus DRUMS") == "BUS DRUMS"


def test_the_key_compares_names_case_insensitively_within_a_kind():
    assert target_key("bus drums") == target_key("BUS Drums") == target_key("Bus  DRUMS")
    assert target_key("BUS Drums") != target_key("DCA Drums")
    assert target_key("BUS Drums") != target_key("Drums")


@pytest.mark.parametrize("text, reason", [
    ("BUS", "has no position or name"),
    ("bus ", "has no position or name"),
    ("BUS -", "begins like a position"),
    ("BUS -Drums", "begins like a position"),
    ("BUS 2 Track", "write its position, BUS 2"),
    ("Aux 2 Keys", "write its position, AUX 2"),
    ("DCA 3 Vox", "write its position, DCA 3"),
])
def test_a_malformed_scoped_name_is_refused(text, reason):
    with pytest.raises(WatchConditionsError, match=reason):
        _parse(_cond(channel=text))
    assert reason in row_problems(_cond(channel=text))["channel"]


@pytest.mark.parametrize("text", ["Drums", "Kick", "Lead Vox", "Busy", "All Vox"])
def test_a_bare_name_keeps_its_meaning(text):
    target = parse_target(text)
    assert target.is_name and not target.is_scoped
    assert canonical_target(text) == text


@pytest.mark.parametrize("channel", ["BUS Drums", "MAIN PA", "MTX Delay", "DCA Vocals"])
def test_patch_is_refused_on_a_scoped_name_of_a_kind_without_one(channel):
    with pytest.raises(WatchConditionsError, match="has no input patch"):
        _parse(_cond(channel=channel, field="patch", value="LCL 1"))


def test_membership_is_refused_on_a_scoped_dca_and_bus():
    with pytest.raises(WatchConditionsError, match="cannot itself be a member"):
        _parse(_cond(channel="DCA Vocals", field="dca", value="Drums"))
    with pytest.raises(WatchConditionsError, match="does not read"):
        _parse(_cond(channel="BUS Drums", field="mute_group", value="FX"))


@pytest.mark.parametrize("field, operator, value", [
    ("muted", "==", False), ("fader_db", "<=", 0), ("dca", "==", "Drums"),
    ("mute_group", "!=", "FX"), ("patch", "==", "LCL 1"),
])
def test_every_field_applies_to_a_scoped_channel_or_aux(field, operator, value):
    _parse(_cond(channel="CH Kick", field=field, operator=operator, value=value))
    _parse(_cond(channel="AUX Tracks", field=field, operator=operator, value=value))


def test_row_problems_says_scoped_and_gives_the_canonical_spelling():
    assert row_problems(_cond(channel="bus Drums")) == {
        "canonical": "BUS Drums", "position": False, "scoped": True}


def test_merge_treats_two_spellings_of_a_scoped_name_as_one_target():
    existing = {"watch_conditions": [_cond(id="mine", channel="bus drums")]}
    drafted = _parse(_cond(id="theirs", channel="BUS Drums", value=True),
                     _cond(id="other", channel="DCA drums"))
    document, report = merge_drafted_conditions(existing, drafted)
    assert report.overlaps == (("theirs", "mine"),)
    # A drafted scoped name is written with its kind word normalised and
    # its name as drafted; yours is left exactly as you wrote it.
    assert [c["channel"] for c in document["watch_conditions"]] == [
        "bus drums", "BUS Drums", "DCA drums"]


def test_merge_normalises_only_the_kind_word_of_a_drafted_scoped_name():
    document, _ = merge_drafted_conditions(None, _parse(_cond(id="d", channel="matrix delay")))
    assert document["watch_conditions"][0]["channel"] == "MTX delay"


# ======================================================================
# Resolution at Start: found / not found / ambiguous / overlap
# ======================================================================


def test_a_scoped_name_resolves_and_says_so_at_info():
    findings = _run(_state(), _cond(channel="BUS Drums"))
    info, warnings, _ = _split(findings)
    assert warnings == []
    assert [f.addresses for f in info] == [("/bus/1/name",)]
    assert info[0].detail == ("BUS Drums resolved to BUS 1 at Start; a rename or move "
                              "after Start is not followed until Watch restarts.")
    assert info[0].rule_id == "WATCH:c1"


def test_the_name_matches_case_insensitively():
    findings = _run(_state(), _cond(channel="dca VOCALS", field="fader_db",
                                    operator="<=", value=0))
    assert "DCA VOCALS resolved to DCA 2" in findings[0].detail
    assert findings[1].addresses == ("/dca/2/fdr",)


def test_a_bus_dca_with_the_same_name_resolve_within_their_own_kind():
    findings = _run(_state(),
                    _cond(id="b", channel="BUS Drums", field="muted", value=True),
                    _cond(id="d", channel="DCA Drums", field="fader_db",
                          operator=">=", value=0))
    info = [f for f in findings if f.severity == Severity.INFO]
    assert [f.addresses for f in info] == [("/bus/1/name",), ("/dca/1/name",)]


def test_a_name_matching_no_strip_of_its_kind_is_a_warning_and_is_not_watched():
    findings = _run(_state(), _cond(channel="BUS Horns"))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.WARNING
    assert "BUS Horns matches no BUS at Start" in f.detail
    assert "not watched" in f.detail and "next time Watch starts" in f.detail


def test_a_channel_name_does_not_satisfy_a_bus_scope():
    # "Kick" is a channel; there is no BUS named Kick.
    findings = _run(_state(), _cond(channel="BUS Kick"))
    assert [f.severity for f in findings] == [Severity.WARNING]


def test_an_ambiguous_name_is_a_warning_naming_the_positions_and_is_not_watched():
    findings = _run(_state(), _cond(channel="BUS Mon 2", field="muted", value=True))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.WARNING
    assert "BUS 3, BUS 4 are each named 'Mon 2'" in f.detail
    assert "(BUS 3 or BUS 4)" in f.detail
    assert f.addresses == ("/bus/3/name", "/bus/4/name")


def test_a_kind_none_of_whose_names_was_read_is_its_own_warning():
    findings = _run(_state(), _cond(channel="MAIN PA"))
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARNING
    assert "no MAIN name could be read at Start" in findings[0].detail


def test_the_scoped_form_wins_over_a_channel_named_like_it_and_says_so():
    state = _state(**{"/ch/5/name": "BUS Drums", "/ch/5/mute": 0})
    findings = _run(state, _cond(channel="BUS Drums", field="muted", value=False))
    info, warnings, errors = _split(findings)
    assert warnings == []
    overlap = [f for f in info if f.addresses == ("/ch/5/name",)]
    assert len(overlap) == 1
    assert "read as the BUS named 'Drums'" in overlap[0].detail
    assert "write CH BUS Drums or CH 5" in overlap[0].detail
    # And the bus is what is watched: muted, so the condition fires on it.
    real = [f for f in findings if f.addresses == ("/bus/1/mute",)]
    assert len(real) == 1


def test_a_channel_literally_named_with_a_kind_word_is_reached_with_ch():
    state = _state(**{"/ch/5/name": "Main Vox", "/ch/5/mute": 1})
    findings = _run(state, _cond(channel="CH Main Vox"))
    assert [f.addresses for f in findings] == [("/ch/5/name",), ("/ch/5/mute",)]


# ======================================================================
# Evaluation against the resolved position
# ======================================================================


def test_a_finding_cites_the_resolved_position_and_name():
    findings = _run(_state(), _cond(channel="BUS Drums", field="muted", value=False))
    real = [f for f in findings if f.severity != Severity.INFO]
    assert len(real) == 1
    assert real[0].addresses == ("/bus/1/mute",)
    assert real[0].detail.startswith('BUS 1 "Drums" is muted -- ')
    assert real[0].severity == Severity.ERROR  # the condition's own


def test_nothing_but_the_info_when_the_condition_holds():
    findings = _run(_state(), _cond(channel="BUS Drums", field="muted", value=True))
    assert [f.severity for f in findings] == [Severity.INFO]


def test_a_scoped_channel_takes_membership_and_patch():
    state = _state(**{"/ch/1/tags": "#D1", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1})
    findings = _run(state,
                    _cond(id="d", channel="CH Kick", field="dca", value="Vocals"),
                    _cond(id="p", channel="CH Kick", field="patch", value="LCL 2"))
    real = [f for f in findings if f.severity != Severity.INFO]
    assert [(f.rule_id, f.addresses) for f in real] == [
        ("WATCH:d", ("/ch/1/tags",)),
        ("WATCH:p", ("/ch/1/in/conn/grp", "/ch/1/in/conn/in"))]


# ======================================================================
# Once at Start: never re-resolved, never re-read
# ======================================================================


def test_a_rename_after_start_is_not_followed():
    rule, = build_watch_rules(_parse(_cond(channel="BUS Drums", field="muted", value=False)))
    first = rule.check(_state())
    assert any(f.addresses == ("/bus/1/mute",) for f in first)
    # After Start: Drums moved to bus 2, and bus 1 renamed. The rule
    # still watches BUS 1, and still reports the Start resolution.
    moved = _state(**{"/bus/1/name": "Spare", "/bus/2/name": "Drums", "/bus/2/mute": 1})
    later = rule.check(moved)
    assert [f.addresses for f in later] == [("/bus/1/name",), ("/bus/1/mute",)]
    # Labelled with what the desk calls it now: the strip watched is
    # BUS 1, and its name today is Spare.
    assert later[1].detail.startswith('BUS 1 "Spare" is muted -- ')


def test_a_name_not_found_at_start_is_not_retried_each_cycle():
    rule, = build_watch_rules(_parse(_cond(channel="BUS Horns", field="muted", value=False)))
    assert [f.severity for f in rule.check(_state())] == [Severity.WARNING]
    appeared = _state(**{"/bus/5/name": "Horns", "/bus/5/mute": 1})
    assert [f.severity for f in rule.check(appeared)] == [Severity.WARNING]
    # A fresh Start (new rules) does pick it up.
    fresh, = build_watch_rules(_parse(_cond(channel="BUS Horns", field="muted", value=False)))
    assert [f.addresses for f in fresh.check(appeared)] == [("/bus/5/name",), ("/bus/5/mute",)]


def test_the_findings_do_not_churn_across_cycles():
    """The resolution INFO is the same finding every cycle, so watch()
    reports it once in the baseline and never as new or cleared."""
    rules = build_watch_rules(_parse(_cond(channel="BUS Drums", field="muted", value=True)))
    states = iter([_state(), _state(**{"/bus/1/name": "Renamed"}), _state()])
    events = list(watch(lambda: next(states), rules=rules, max_iterations=3,
                        sleep=lambda _s: None, clock=lambda: "t"))
    assert any("resolved to BUS 1" in f.detail for f in events[0].all_findings)
    for event in events[1:]:
        assert event.new_findings == [] and event.cleared_findings == []


def test_main_and_matrix_names_are_read_once_at_start_and_never_again():
    conds = _parse(_cond(id="m", channel="MAIN PA"), _cond(id="x", channel="MTX Delay"),
                   _cond(id="m2", channel="main pa", field="fader_db", operator="<=", value=0),
                   _cond(id="b", channel="BUS Drums"))
    addresses = start_name_addresses(conds)
    assert addresses == ([f"/main/{n}/name" for n in range(1, 5)]
                         + [f"/mtx/{n}/name" for n in range(1, 9)])

    asked: list[str] = []
    desk = {"/main/1/name": "PA", "/mtx/3/name": "Delay"}

    def read_name(address):
        asked.append(address)
        return desk.get(address)

    provider = read_names_at_start(lambda: _state(**{"/mtx/3/mute": 0}), read_name, addresses)
    rules = build_watch_rules(conds)
    findings_by_cycle = []
    for _ in range(4):
        state = provider()
        findings_by_cycle.append([f for r in rules for f in r.check(state)])
    # Every address once, on the first cycle; none after.
    assert asked == addresses
    # The first state carried the names; the later ones do not.
    assert "/main/1/name" not in provider().values
    resolved = [f.detail for f in findings_by_cycle[-1] if "resolved to" in f.detail]
    assert resolved == [
        "MAIN PA resolved to MAIN 1 at Start; a rename or move after Start is not followed "
        "until Watch restarts.",
        "MTX Delay resolved to MTX 3 at Start; a rename or move after Start is not followed "
        "until Watch restarts.",
        "MAIN pa resolved to MAIN 1 at Start; a rename or move after Start is not followed "
        "until Watch restarts.",
        "BUS Drums resolved to BUS 1 at Start; a rename or move after Start is not followed "
        "until Watch restarts.",
    ]
    # MAIN 1 is muted in every state: the condition keeps firing on it.
    assert any(f.addresses == ("/main/1/mute",) for f in findings_by_cycle[-1])


def test_no_start_reads_when_no_scoped_name_needs_them():
    conds = _parse(_cond(channel="BUS Drums"), _cond(id="p", channel="MAIN 1"),
                   _cond(id="n", channel="Kick"))
    assert start_name_addresses(conds) == []


def test_the_poll_reads_no_main_or_matrix_name():
    """The per-cycle read set is the one `audit.console_read_plan` builds,
    and this feature leaves it alone: no Main or Matrix name is in it."""
    plan = {address for address, _ in console_read_plan()}
    assert not any(a.startswith(("/main/", "/mtx/")) and a.endswith("/name") for a in plan)


def test_a_scoped_target_reads_its_own_banks_names():
    patterns = condition_address_patterns(_parse(_cond(channel="DCA Vocals",
                                                       field="fader_db", operator="<=",
                                                       value=0))[0])
    assert r"^/dca/\d+/name$" in patterns
    assert r"^/dca/\d+/fdr$" in patterns


def test_the_console_name_reader_asks_once_per_address_and_skips_silence():
    from atoo.console import OscReply
    from atoo.watch_conditions import console_name_reader

    class Desk:
        def __init__(self):
            self.asked = []

        def get(self, address):
            self.asked.append(address)
            if address == "/main/1/name":
                return OscReply(address, ",s", ["PA"])
            return None  # no answer

    desk = Desk()
    read = console_name_reader(desk)
    assert read("/main/1/name") == "PA"
    assert read("/main/2/name") is None
    assert desk.asked == ["/main/1/name", "/main/2/name"]


# ======================================================================
# Coordinator's review: bare `Main`
# ======================================================================


def test_bare_main_is_read_as_main_1_with_an_info():
    target = parse_target("Main")
    assert target.is_position and (target.bank, target.first, target.last) == ("main", 1, 1)
    assert canonical_target("main") == "MAIN 1"
    assert target_key("Main") == target_key("MAIN 1")
    findings = _run(_state(), _cond(channel="Main", field="muted", value=False))
    info = [f for f in findings if f.severity == Severity.INFO]
    assert len(info) == 1
    assert "'Main' read as MAIN 1 (the main L/R) -- write MAIN 1 to make it explicit" \
        in info[0].detail
    # MAIN 1 is muted in this state: the condition fires on it.
    assert [f.addresses for f in findings if f.severity == Severity.ERROR] == [
        ("/main/1/mute",)]


def test_bare_main_is_a_note_not_a_refusal_in_the_editor():
    problems = row_problems(_cond(channel="Main"))
    assert "channel" not in problems
    assert problems["canonical"] == "MAIN 1" and problems["position"] is True
    assert problems["note"].startswith("'Main' read as MAIN 1")


@pytest.mark.parametrize("text", ["BUS", "AUX", "CH", "DCA", "MTX", "Matrix"])
def test_no_other_bare_kind_word_has_a_default(text):
    with pytest.raises(WatchConditionsError, match="has no position or name"):
        _parse(_cond(channel=text))


def test_a_watch_file_saying_main_loads():
    """A frozen copy of `examples/touringband/watch.json` (2026-10-01),
    which says `"channel": "Main"` and was refused from an earlier change on."""
    from pathlib import Path

    from atoo.watch_conditions import load_watch_conditions

    path = Path(__file__).parent / "fixtures" / "touringband.watch.json"
    conditions = load_watch_conditions(path)
    mains = [c for c in conditions if c["channel"] == "Main"]
    assert mains
    assert all(parse_target(c["channel"]).canonical == "MAIN 1" for c in mains)


def test_a_scoped_name_matching_no_strip_of_its_kind_is_not_watched():
    """No fallback to a channel named the whole string (removed 2026-10-01,
    backwards compatibility is not a goal): `MAIN Vox` means
    the Main named Vox, and a channel called "Main Vox" is `CH Main Vox`."""
    state = _state(**{"/ch/3/name": "Main Vox", "/ch/3/mute": 1,
                      "/main/1/name": "PA"})
    findings = _run(state, _cond(channel="Main Vox"))
    assert Severity.WARNING in [f.severity for f in findings]
    assert not any(f.addresses == ("/ch/3/mute",) for f in findings)


def test_the_scoped_strip_wins_over_a_channel_named_the_whole_string():
    state = _state(**{"/ch/3/name": "BUS Drums", "/ch/3/mute": 0})
    findings = _run(state, _cond(channel="BUS Drums"))
    assert any("read as the BUS named 'Drums'" in f.detail for f in findings)
    assert not any("matched no" in f.detail for f in findings)
    assert any(f.addresses == ("/bus/1/mute",) for f in findings)


def test_two_channels_named_the_whole_string_change_nothing():
    state = _state(**{"/ch/3/name": "Bus Mic", "/ch/4/name": "Bus Mic"})
    findings = _run(state, _cond(channel="BUS Mic"))
    assert [f.severity for f in findings].count(Severity.WARNING) == 1
    assert not any("matched no" in f.detail for f in findings)
