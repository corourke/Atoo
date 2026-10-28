"""FR-6.5: operator-authored watch conditions -- structured, deterministic
alert rules distinct from `atoo.audit`'s DEFAULT_RULES. Mirrors
`tests/test_audit.py`'s style (hand-built `ConsoleState` fixtures, no
console connection needed) for evaluation, and
`tests/test_critic_expectations.py`'s style for the loader's error
paths."""

from __future__ import annotations

import json

import pytest

from atoo.audit import ConsoleState, Severity
from atoo.watch_conditions import (
    WatchConditionsError,
    build_watch_rules,
    load_watch_conditions,
    parse_watch_conditions,
)


def _doc(*conditions):
    return json.dumps({"version": 2, "watch_conditions": list(conditions)})


def _condition(**overrides):
    base = {
        "id": "crowd-mic-muted",
        "description": "Crowd Mic must never be muted",
        "channel": "Crowd Mic",
        "field": "muted",
        "operator": "!=",
        "value": False,
        "severity": "error",
    }
    base.update(overrides)
    return base


# --- loading -----------------------------------------------------------


def test_valid_file_loads_correctly():
    conditions = parse_watch_conditions(_doc(_condition()))
    assert len(conditions) == 1
    assert conditions[0]["id"] == "crowd-mic-muted"


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        load_watch_conditions(tmp_path / "does-not-exist.json")


def test_invalid_json_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="not valid JSON"):
        parse_watch_conditions("not json at all", source="test.json")


def test_missing_watch_conditions_key_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="watch_conditions"):
        parse_watch_conditions(json.dumps({"something_else": []}), source="test.json")


def test_watch_conditions_not_a_list_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="must be a list"):
        parse_watch_conditions(json.dumps({"version": 2, "watch_conditions": {"id": "x"}}), source="test.json")


def test_unknown_field_is_a_clear_error():
    # `dca` was this test's example of an unknown field
    # made it a real one -- `gain` is chosen here because nothing has
    # asked for head-amp gain conditions yet (see the module docstring's
    # "still not covered" list), so it stays a genuine unknown.
    with pytest.raises(WatchConditionsError, match="unknown field"):
        parse_watch_conditions(_doc(_condition(field="gain")))


def test_invalid_operator_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="unknown operator"):
        parse_watch_conditions(_doc(_condition(operator="~=")))


def test_muted_with_numeric_operator_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="only supports"):
        parse_watch_conditions(_doc(_condition(field="muted", operator="<=", value=True)))


@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
def test_muted_rejects_every_numeric_only_operator(op):
    with pytest.raises(WatchConditionsError, match="only supports"):
        parse_watch_conditions(_doc(_condition(field="muted", operator=op, value=True)))


def test_missing_required_key_is_a_clear_error():
    cond = _condition()
    del cond["severity"]
    with pytest.raises(WatchConditionsError, match="missing required key"):
        parse_watch_conditions(_doc(cond))


def test_unknown_key_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="unknown key"):
        parse_watch_conditions(_doc(_condition(extra_field="nope")))


def test_invalid_severity_is_a_clear_error():
    with pytest.raises(WatchConditionsError, match="unknown severity"):
        parse_watch_conditions(_doc(_condition(severity="urgent")))


def test_the_retired_critical_severity_says_what_to_change():
    """`critical` was valid until 2026-09-23. A watch.json on disk is the
    only file that can still carry it, so the refusal names the
    replacement rather than only saying the value is unknown -- and it
    refuses rather than reading it as `error`, because a severity nobody
    re-read is a severity nobody chose."""
    with pytest.raises(WatchConditionsError, match="critical.*no longer a severity.*use \"error\""):
        parse_watch_conditions(_doc(_condition(severity="critical")))


def test_muted_value_must_be_bool():
    with pytest.raises(WatchConditionsError, match="boolean"):
        parse_watch_conditions(_doc(_condition(field="muted", value=1)))


def test_fader_db_value_must_be_numeric():
    with pytest.raises(WatchConditionsError, match="numeric"):
        parse_watch_conditions(_doc(_condition(
            field="fader_db", operator="!=", value="loud", channel="Crowd Mic",
        )))


def test_fader_db_rejects_bool_value():
    # bool is a subclass of int in Python -- must not sneak past the
    # "numeric" check for fader_db.
    with pytest.raises(WatchConditionsError, match="numeric"):
        parse_watch_conditions(_doc(_condition(field="fader_db", operator="!=", value=True)))


def test_duplicate_ids_are_a_clear_error():
    with pytest.raises(WatchConditionsError, match="duplicate"):
        parse_watch_conditions(_doc(_condition(), _condition(description="second one")))


def test_load_watch_conditions_reads_a_real_file(tmp_path):
    path = tmp_path / "conditions.json"
    path.write_text(_doc(_condition()))
    conditions = load_watch_conditions(path)
    assert conditions[0]["channel"] == "Crowd Mic"


# --- evaluation ----------------------------------------------------------


def test_muted_condition_fires_when_channel_is_muted():
    state = ConsoleState({"/ch/1/name": "Crowd Mic", "/ch/1/mute": 1})
    rules = build_watch_rules([_condition()])
    findings = rules[0].check(state)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "WATCH:crowd-mic-muted"
    assert f.severity == Severity.ERROR
    assert f.category == "watch"
    assert "Crowd Mic" in f.detail


def test_muted_condition_does_not_fire_when_channel_is_not_muted():
    state = ConsoleState({"/ch/1/name": "Crowd Mic", "/ch/1/mute": 0})
    rules = build_watch_rules([_condition()])
    assert rules[0].check(state) == []


def test_fader_db_condition_fires_on_mismatch():
    cond = _condition(
        id="crowd-mic-fader-down", description="Crowd Mic fader must be at floor",
        field="fader_db", operator="!=", value=-144.0, severity="warning",
    )
    state = ConsoleState({"/ch/1/name": "Crowd Mic", "/ch/1/fdr": -20.0})
    rules = build_watch_rules([cond])
    findings = rules[0].check(state)
    assert len(findings) == 1
    assert findings[0].severity == Severity.WARNING


def test_fader_db_condition_does_not_fire_when_matching():
    cond = _condition(
        id="crowd-mic-fader-down", description="Crowd Mic fader must be at floor",
        field="fader_db", operator="!=", value=-144.0, severity="warning",
    )
    state = ConsoleState({"/ch/1/name": "Crowd Mic", "/ch/1/fdr": -144.0})
    rules = build_watch_rules([cond])
    assert rules[0].check(state) == []


def test_channel_name_resolved_case_insensitively():
    state = ConsoleState({"/ch/1/name": "CROWD mic", "/ch/1/mute": 1})
    rules = build_watch_rules([_condition()])
    assert len(rules[0].check(state)) == 1


def test_zero_matching_channels_is_no_finding_no_crash():
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/mute": 1})
    rules = build_watch_rules([_condition()])
    assert rules[0].check(state) == []


def test_ambiguous_duplicate_channel_name_is_no_finding_no_crash():
    state = ConsoleState({
        "/ch/1/name": "Crowd Mic", "/ch/1/mute": 1,
        "/aux/1/name": "Crowd Mic", "/aux/1/mute": 1,
    })
    rules = build_watch_rules([_condition()])
    assert rules[0].check(state) == []


def test_field_never_read_is_no_finding_no_crash():
    # /ch/1/mute was never read into ConsoleState at all -- a missing
    # read, not evidence of a violation.
    state = ConsoleState({"/ch/1/name": "Crowd Mic"})
    rules = build_watch_rules([_condition()])
    assert rules[0].check(state) == []


# --- Membership and patch fields ------------------------------
#
# `==` asserts the relationship holds ("is a member of", "is patched to"),
# `!=` asserts it does not -- the maintainer's call. A finding is the
# assertion being violated, the same polarity as every scalar field above.


def _dca_state(tags="#D1", *, dca_name="Drums"):
    return ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": tags,
        "/dca/1/name": dca_name,
    })


def _member_condition(**overrides):
    base = {
        "id": "kick-stays-in-drums",
        "description": "Kick must stay in the Drums DCA",
        "channel": "Kick",
        "field": "dca",
        "operator": "not in",
        "value": "Drums",
        "severity": "warning",
    }
    base.update(overrides)
    return base


def test_dca_membership_does_not_fire_when_channel_is_a_member():
    rules = build_watch_rules([_member_condition()])
    assert rules[0].check(_dca_state("#D1")) == []


def test_dca_membership_fires_when_channel_is_not_a_member():
    findings = build_watch_rules([_member_condition()])[0].check(_dca_state("#D2,#M1"))
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "WATCH:kick-stays-in-drums"
    assert f.severity == Severity.WARNING
    assert f.addresses == ("/ch/1/tags",)
    assert f.detail == 'CH 1 "Kick" is not in DCA Drums -- Kick must stay in the Drums DCA.'


def test_dca_membership_fires_on_an_untagged_channel():
    # An empty `/tags` is a real, readable answer -- "in no groups" -- not
    # an unread field, so `== "Drums"` is genuinely violated.
    findings = build_watch_rules([_member_condition()])[0].check(_dca_state(""))
    assert len(findings) == 1


def test_dca_non_membership_fires_when_channel_is_a_member():
    cond = _member_condition(
        id="kick-out-of-fx", description="Kick must not be in the FX DCA",
        operator="==", value="FX",
    )
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D2",
        "/dca/1/name": "Drums", "/dca/2/name": "FX",
    })
    findings = build_watch_rules([cond])[0].check(state)
    assert len(findings) == 1
    assert findings[0].detail.startswith('CH 1 "Kick" is in DCA FX -- ')


def test_dca_non_membership_does_not_fire_when_channel_is_not_a_member():
    cond = _member_condition(operator="==", value="FX")
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D1",
        "/dca/1/name": "Drums", "/dca/2/name": "FX",
    })
    assert build_watch_rules([cond])[0].check(state) == []


def test_mute_group_membership_reads_the_mgrp_tag():
    cond = _member_condition(
        id="kick-in-band-mutes", description="Kick must be in the Band mute group",
        field="mute_group", operator="not in", value="Band",
    )
    in_group = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#M3",
        "/mgrp/3/name": "Band",
    })
    out_of_group = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "#D3",  # a DCA tag, not a mute group
        "/mgrp/3/name": "Band",
    })
    assert build_watch_rules([cond])[0].check(in_group) == []
    findings = build_watch_rules([cond])[0].check(out_of_group)
    assert len(findings) == 1
    assert 'is not in mute group Band -- ' in findings[0].detail


def test_unresolvable_group_name_is_no_finding_no_crash():
    # Nothing live is called "Drums" -- per the maintainer's an earlier change note, skipped
    # this cycle rather than reported, the same precedent an unresolvable
    # channel name already follows.
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/tags": "", "/dca/1/name": "Guitars"})
    assert build_watch_rules([_member_condition()])[0].check(state) == []


def test_ambiguous_group_name_is_no_finding_no_crash():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/tags": "",
        "/dca/1/name": "Drums", "/dca/2/name": "Drums",
    })
    assert build_watch_rules([_member_condition()])[0].check(state) == []


def test_strip_that_was_never_walked_is_no_finding_no_crash():
    # `/ch/1/tags` was never read: ConsoleState.tags() returns "" for both
    # "unread" and "no groups", so this asserts the deliberate choice --
    # an unread tags string reads as "in no groups", which DOES violate a
    # membership assertion. Documented here so the behaviour is a decision
    # rather than an accident: `read_console_state` always reads `tags`
    # for every strip it walks, so an unread tags string means the strip
    # itself was never walked, and then the channel name wouldn't resolve
    # either.
    state = ConsoleState({"/dca/1/name": "Drums"})
    assert build_watch_rules([_member_condition()])[0].check(state) == []


def _patch_condition(**overrides):
    base = {
        "id": "kick-on-lcl5",
        "description": "Kick must stay patched to LCL 5",
        "channel": "Kick",
        "field": "patch",
        "operator": "!=",
        "value": "LCL 5",
        "severity": "error",
    }
    base.update(overrides)
    return base


def test_patch_condition_does_not_fire_when_patch_matches():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 5,
    })
    assert build_watch_rules([_patch_condition()])[0].check(state) == []


def test_patch_condition_fires_when_patched_elsewhere():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 7,
    })
    findings = build_watch_rules([_patch_condition()])[0].check(state)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.ERROR
    assert f.addresses == ("/ch/1/in/conn/grp", "/ch/1/in/conn/in")
    assert "is patched to LCL 7 -- " in f.detail


def test_patch_condition_fires_when_unpatched():
    # "OFF" is a real reading -- patched to nothing genuinely violates
    # `patch == "LCL5"`, unlike a field that was never read.
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "OFF", "/ch/1/in/conn/in": 0,
    })
    findings = build_watch_rules([_patch_condition()])[0].check(state)
    assert len(findings) == 1
    assert "unpatched" in findings[0].detail


def test_patch_condition_with_unread_patch_is_no_finding_no_crash():
    state = ConsoleState({"/ch/1/name": "Kick"})
    assert build_watch_rules([_patch_condition()])[0].check(state) == []


def test_patch_non_membership_fires_when_patched_there():
    cond = _patch_condition(
        id="kick-off-lcl1", description="Kick must not be on LCL 1",
        operator="==", value="LCL 1",
    )
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    })
    findings = build_watch_rules([cond])[0].check(state)
    assert len(findings) == 1
    assert "is patched to LCL 1 -- " in findings[0].detail


def test_patch_value_is_case_insensitive_on_the_group():
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 5,
    })
    assert build_watch_rules([_patch_condition(value="lcl 5")])[0].check(state) == []


@pytest.mark.parametrize("written,grp,socket", [
    # The maintainer's own vocabulary, 2026-09-20 -- the spelling an input list's
    # socket column uses, because it IS that vocabulary (FR-1.5), not a
    # second one invented for this field.
    ("AES50-A 12", "A", 12),
    ("AES50-B 33", "B", 33),
    ("LCL 1", "LCL", 1),
    ("AES 2", "AES", 2),
    ("USB 30", "USB", 30),
    ("CRD 64", "CRD", 64),
    ("SC 24", "SC", 24),
])
def test_patch_accepts_every_socket_spelling_an_input_list_accepts(written, grp, socket):
    cond = _patch_condition(value=written)
    parse_watch_conditions(_doc(cond))  # loads without error
    matching = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": grp, "/ch/1/in/conn/in": socket,
    })
    assert build_watch_rules([cond])[0].check(matching) == []


def test_aes_ebu_and_aes50_are_not_the_same_socket():
    # The confusion this spelling exists to prevent: a 14B model
    # substituted one for the other on 19 channels in a row
    # (console_facts.GROUP_ALIASES). "AES 1" must never match AES50-A 1.
    on_aes50_a1 = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
    })
    cond = _patch_condition(value="AES 1")
    findings = build_watch_rules([cond])[0].check(on_aes50_a1)
    assert len(findings) == 1
    assert "is patched to AES50-A 1 -- " in findings[0].detail


# --- Load-time rejections for the new fields ------------------


@pytest.mark.parametrize("field", ["dca", "mute_group", "patch"])
@pytest.mark.parametrize("operator", [">", "<", ">=", "<="])
def test_relational_fields_reject_ordering_operators(field, operator):
    value = "LCL5" if field == "patch" else "Drums"
    # dca and mute_group take `in`/`not in`; patch takes == and !=.
    with pytest.raises(WatchConditionsError,
                       match="yes/no question|takes 'in' or 'not in'"):
        parse_watch_conditions(_doc(_condition(
            field=field, operator=operator, value=value,
        )))


@pytest.mark.parametrize("field", ["dca", "mute_group"])
@pytest.mark.parametrize("value", [1, True, None, "", "   "])
def test_group_fields_need_a_non_empty_string_name(field, value):
    with pytest.raises(WatchConditionsError, match="group NAME"):
        parse_watch_conditions(_doc(_condition(field=field, operator="not in", value=value)))


@pytest.mark.parametrize("value", [
    "LCL", "5", "LCL 5x", "NOPE 5", "LCL 0", "LCL 25", "",
    "LCL5",       # no space -- not how an input list writes it
    "A 1",        # bare AES50 network -- must be written "AES50-A 1"
    "AES50-D 1",  # there are three AES50 networks, not four
])
def test_patch_value_must_be_a_socket_this_console_could_have(value):
    # "LCL 25" is past the WING's 24 local XLRs; "NOPE" is not a group at
    # all. Either would be a rule that can never fire, which is worse
    # than a load error.
    with pytest.raises(WatchConditionsError, match="patch"):
        parse_watch_conditions(_doc(_condition(field="patch", value=value)))


def test_all_five_fields_load():
    conditions = parse_watch_conditions(_doc(
        _condition(id="a", field="muted", value=False),
        _condition(id="b", field="fader_db", value=-144.0),
        _condition(id="c", field="dca", operator="not in", value="Drums"),
        _condition(id="d", field="mute_group", operator="in", value="Band"),
        _condition(id="e", field="patch", value="LCL 5"),
    ))
    assert [c["field"] for c in conditions] == [
        "muted", "fader_db", "dca", "mute_group", "patch",
    ]
