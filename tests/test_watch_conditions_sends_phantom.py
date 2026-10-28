"""Watch conditions about a strip's sends and its 48V: `send_on`, `send_db`,
`send_mode` and `phantom`.

The fixed rules cannot know the rules of one show: the click stays on in every
in-ear mix, the drummer's send for Kick stays above -10, the overheads keep
their 48V. A send condition names where the send goes in a `bus` key; the
phantom condition judges the socket (and, for a stereo source, the next one)
the strip is patched to. The desks are built here; the capture tests use frozen
captures, never a show bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.audit import ConsoleState, Severity, run_audit
from atoo.watch import watch
from atoo.watch_conditions import (
    WatchConditionsError, build_watch_rules, condition_address_patterns,
    merge_drafted_conditions, parse_watch_conditions, row_problems,
    salvage_drafted_conditions,
)
from tests.snap_desk import snap_values

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURES = sorted(FIXTURES.rglob("*.snap"))


def _cond(**changes) -> dict:
    cond = {"id": "c", "description": "The click stays on in every IEM", "channel": "Click",
            "field": "send_on", "bus": "BUS 5-6", "operator": "!=", "value": True,
            "severity": "error"}
    cond.update(changes)
    return {k: v for k, v in cond.items() if v is not None}


def _load(*conds) -> list[dict]:
    return parse_watch_conditions(json.dumps({"version": 2, "watch_conditions": list(conds)}), source="t.json")


def _refused(**changes) -> str:
    with pytest.raises(WatchConditionsError) as excinfo:
        _load(_cond(**changes))
    return str(excinfo.value)


def _findings(state, *conds):
    return [f for rule in build_watch_rules(_load(*conds)) for f in rule.check(state)]


def _desk(**changes) -> ConsoleState:
    """Two in-ear mixes (busses 5 and 6), a Click and a Kick sending to both,
    and a pair of overhead mics on LCL 3-4 and 6."""
    v: dict[str, object] = {
        "/bus/5/name": "Drum IEM", "/bus/6/name": "Bass IEM",
        "/ch/1/name": "Kick", "/ch/2/name": "Click",
        "/ch/1/send/5/on": 1, "/ch/1/send/5/lvl": -6.0, "/ch/1/send/5/mode": "PRE",
        "/ch/1/send/6/on": 1, "/ch/1/send/6/lvl": -6.0, "/ch/1/send/6/mode": "PRE",
        "/ch/2/send/5/on": 1, "/ch/2/send/5/lvl": 0.0, "/ch/2/send/5/mode": "PRE",
        "/ch/2/send/6/on": 1, "/ch/2/send/6/lvl": 0.0, "/ch/2/send/6/mode": "PRE",
        "/ch/2/main/1/on": 0,
        "/ch/3/name": "OH L", "/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 3,
        "/io/in/LCL/3/vph": 1, "/io/in/LCL/3/mode": "ST", "/io/in/LCL/4/vph": 1,
        "/ch/4/name": "Room", "/ch/4/in/conn/grp": "LCL", "/ch/4/in/conn/in": 6,
        "/io/in/LCL/6/vph": 1, "/io/in/LCL/6/mode": "M",
    }
    v.update(changes)
    return ConsoleState(v, console_model="wing-compact")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def test_the_new_fields_are_in_the_vocabulary_with_their_key():
    loaded = _load(_cond(), _cond(id="d", field="send_db", operator="<=", value=-10),
                   _cond(id="e", field="send_mode", value="pre"),
                   _cond(id="f", channel="CH 3-4", field="phantom", bus=None))
    assert [c["field"] for c in loaded] == ["send_on", "send_db", "send_mode", "phantom"]
    assert "bus" not in loaded[3]


@pytest.mark.parametrize("bus", ["BUS 5", "BUS 5-8", "ALL BUS", "Drum IEM", "BUS Drum IEM",
                                 "MTX 3", "MAIN 1", "Main"])
def test_a_bus_is_named_the_way_a_channel_is(bus):
    assert _load(_cond(bus=bus))[0]["bus"] == bus


def test_a_send_field_without_a_bus_is_refused_and_says_what_to_write():
    message = _refused(bus=None)
    assert "field 'send_on' needs a 'bus' key naming where the send goes" in message
    assert "BUS 5-8" in message


def test_the_bus_key_on_another_field_is_refused():
    message = _refused(field="phantom", bus="BUS 5")
    assert "key 'bus' only applies to send_db, send_mode, send_on, not to 'phantom'" in message
    assert "key 'bus' only applies" in _refused(field="muted", bus="BUS 5")


@pytest.mark.parametrize("bus,fragment", [
    ("BUS 17", "BUS 17 does not exist"),
    ("BUS 8-5", "backwards range"),
    ("DCA 1", "a DCA, which a strip does not send to"),
    ("CH 1", "a CH, which a strip does not send to"),
    ("MAIN PA", "watch does not read a MAIN's name, so write its position"),
    ("MTX Delay", "watch does not read a MTX's name, so write its position"),
    ("BUS 2 Track", "begins like a position"),
])
def test_a_bus_that_no_console_could_satisfy_is_refused(bus, fragment):
    assert fragment in _refused(bus=bus)


def test_a_route_to_a_main_has_a_switch_and_nothing_else():
    assert "a route to a Main has a switch and no level or mode" in _refused(
        field="send_db", operator="<=", value=-10, bus="MAIN 1")
    assert "a route to a Main has a switch and no level or mode" in _refused(
        field="send_mode", value="pre", bus="MAIN 1")
    assert "only a send to a bus is pre or post fader" in _refused(
        field="send_mode", value="pre", bus="MTX 2")


@pytest.mark.parametrize("changes,fragment", [
    (dict(value="yes"), "field 'send_on' needs a boolean 'value'"),
    (dict(field="phantom", bus=None, value=1), "field 'phantom' needs a boolean 'value'"),
    (dict(field="send_db", operator=">=", value=True), "field 'send_db' needs a numeric 'value'"),
    (dict(field="send_db", operator=">=", value="-10"), "field 'send_db' needs a numeric 'value'"),
    (dict(field="send_mode", value="middle"),
     "field 'send_mode' needs a 'value' of 'pre', 'post', 'group'"),
])
def test_a_value_the_field_cannot_take_is_refused(changes, fragment):
    assert fragment in _refused(**changes)


@pytest.mark.parametrize("changes", [
    dict(operator="<="), dict(field="phantom", bus=None, operator=">"),
    dict(field="send_mode", value="pre", operator="<"),
])
def test_booleans_and_modes_take_equality_only(changes):
    message = _refused(**changes)
    assert "only supports" in message and "['!=', '==']" in message


def test_send_db_takes_every_operator():
    for operator in ("==", "!=", "<", "<=", ">", ">="):
        _load(_cond(field="send_db", operator=operator, value=-10))


@pytest.mark.parametrize("channel", ["BUS 1", "DCA 1", "MAIN 1", "MTX 1"])
@pytest.mark.parametrize("field", ["send_on", "phantom"])
def test_only_a_channel_or_an_aux_has_sends_or_a_socket(channel, field):
    message = _refused(channel=channel, field=field, bus="BUS 5" if field == "send_on" else None)
    assert f"field {field!r} does not apply to {channel}" in message


# --------------------------------------------------------------------------
# The Watch editor's row check
# --------------------------------------------------------------------------


def test_the_editor_row_check_says_what_the_loader_says_for_the_bus_cell():
    assert "needs a 'bus' key" in row_problems(_cond(bus=None))["bus"]
    assert "BUS 17 does not exist" in row_problems(_cond(bus="BUS 17"))["bus"]
    assert "bus" not in row_problems(_cond())
    assert "only applies" in row_problems(_cond(field="phantom"))["bus"]


def test_the_editor_row_check_returns_the_buss_one_spelling():
    assert row_problems(_cond(bus="bus5-6"))["bus_canonical"] == "BUS 5-6"
    assert row_problems(_cond(bus="Drum IEM"))["bus_canonical"] == "Drum IEM"
    assert "bus_canonical" not in row_problems(_cond(field="phantom", bus=None))


# --------------------------------------------------------------------------
# send_on
# --------------------------------------------------------------------------


def test_a_send_switched_off_names_the_strip_the_bus_and_the_description():
    state = _desk(**{"/ch/2/send/6/on": 0})
    [finding] = _findings(state, _cond())
    assert (finding.rule_id, finding.severity) == ("WATCH:c", Severity.ERROR)
    assert finding.message == ('CH 2 "Click" has its send to BUS 6 "Bass IEM" switched off -- '
                               "The click stays on in every IEM.")
    assert finding.addresses == ("/ch/2/send/6/on",)


def test_a_condition_the_desk_satisfies_says_nothing():
    assert _findings(_desk(), _cond()) == []


def test_a_strip_with_two_sends_off_is_one_finding_listing_both():
    state = _desk(**{"/ch/2/send/5/on": 0, "/ch/2/send/6/on": 0})
    [finding] = _findings(state, _cond())
    assert finding.message.startswith(
        'CH 2 "Click" has its sends to BUS 5 "Drum IEM" and BUS 6 "Bass IEM" switched off -- ')
    assert finding.addresses == ("/ch/2/send/5/on", "/ch/2/send/6/on")


def test_a_range_of_strips_is_one_finding_per_violating_strip():
    state = _desk(**{"/ch/1/send/5/on": 0, "/ch/2/send/6/on": 0})
    found = _findings(state, _cond(channel="CH 1-2"))
    assert [f.message.split(" has ")[0] for f in found] == ['CH 1 "Kick"', 'CH 2 "Click"']


def test_not_equal_asserts_the_send_is_not_on():
    state = _desk()
    [finding] = _findings(state, _cond(channel="Click", bus="BUS 5", operator="==", value=True,
                                       description="The click stays out of the drum IEM"))
    assert "switched on" in finding.message


def test_a_bus_named_by_its_name_or_its_kind_and_name():
    state = _desk(**{"/ch/2/send/6/on": 0})
    for bus in ("Bass IEM", "bass iem", "BUS Bass IEM"):
        [finding] = _findings(state, _cond(bus=bus))
        assert 'BUS 6 "Bass IEM"' in finding.message
    assert _findings(state, _cond(bus="Drum IEM")) == []


def test_all_bus_covers_every_bus_whose_send_was_read():
    state = _desk(**{"/ch/2/send/6/on": 0})
    [finding] = _findings(state, _cond(bus="ALL BUS"))
    assert finding.addresses == ("/ch/2/send/6/on",)


def test_a_route_to_a_main_and_a_send_to_a_matrix():
    state = _desk(**{"/ch/2/main/1/on": 1, "/ch/2/send/MX3/on": 0})
    [route] = _findings(state, _cond(bus="MAIN 1", value=False,
                                     description="The click stays off the PA"))
    assert route.message == ('CH 2 "Click" has its route to MAIN 1 switched on -- '
                             "The click stays off the PA.")
    assert route.addresses == ("/ch/2/main/1/on",)
    [matrix] = _findings(state, _cond(bus="MTX 3"))
    assert matrix.message.startswith('CH 2 "Click" has its send to MTX 3 switched off')
    assert matrix.addresses == ("/ch/2/send/MX3/on",)


def test_an_aux_has_sends_too():
    state = _desk(**{"/aux/1/name": "Tracks", "/aux/1/send/5/on": 0})
    [finding] = _findings(state, _cond(channel="AUX 1", bus="BUS 5"))
    assert finding.message.startswith('AUX 1 "Tracks" has its send to BUS 5 "Drum IEM"')


# --------------------------------------------------------------------------
# send_db and send_mode
# --------------------------------------------------------------------------


def test_a_send_level_below_the_floor_the_engineer_set():
    state = _desk(**{"/ch/1/send/5/lvl": -20.0})
    [finding] = _findings(state, _cond(
        channel="Kick", field="send_db", bus="Drum IEM", operator="<=", value=-10,
        description="Kick stays above -10 in the drummer's IEM", severity="warning"))
    assert finding.severity == Severity.WARNING
    assert finding.message == ('CH 1 "Kick" has its send to BUS 5 "Drum IEM" at -20 dB -- '
                               "Kick stays above -10 in the drummer's IEM.")
    assert finding.addresses == ("/ch/1/send/5/lvl",)


def test_send_db_over_a_range_lists_each_level_and_reads_minus_infinity():
    state = _desk(**{"/ch/1/send/5/lvl": -20.0, "/ch/1/send/6/lvl": float("-inf")})
    [finding] = _findings(state, _cond(channel="Kick", field="send_db", bus="BUS 5-6",
                                       operator="<=", value=-10))
    assert 'has its sends to BUS 5 "Drum IEM" at -20 dB and BUS 6 "Bass IEM" at -inf dB' in finding.message


def test_a_send_that_holds_the_level_says_nothing():
    assert _findings(_desk(), _cond(channel="Kick", field="send_db", bus="BUS 5-6",
                                    operator="<=", value=-10)) == []


def test_a_send_flipped_to_post_fader():
    state = _desk(**{"/ch/1/send/5/mode": "POST"})
    [finding] = _findings(state, _cond(channel="Kick", field="send_mode", bus="BUS 5-6",
                                       value="pre", description="IEM sends are pre-fader"))
    assert finding.message == ('CH 1 "Kick" has its send to BUS 5 "Drum IEM" post-fader -- '
                               "IEM sends are pre-fader.")
    assert finding.addresses == ("/ch/1/send/5/mode",)


def test_group_mode_reads_as_a_word():
    state = _desk(**{"/ch/1/send/5/mode": "GRP"})
    [finding] = _findings(state, _cond(channel="Kick", field="send_mode", bus="BUS 5", value="pre"))
    assert "in group mode" in finding.message


def test_send_mode_not_equal():
    state = _desk()
    [finding] = _findings(state, _cond(channel="Kick", field="send_mode", bus="BUS 5",
                                       operator="==", value="pre"))
    assert "pre-fader" in finding.message


# --------------------------------------------------------------------------
# Silent
# --------------------------------------------------------------------------


def test_silent_for_a_send_that_was_not_read():
    values = {a: v for a, v in _desk().values.items() if not a.startswith("/ch/2/send/6/")}
    assert _findings(ConsoleState(values), _cond()) == []


def test_silent_for_a_bus_no_name_or_two_names_match():
    assert _findings(_desk(**{"/ch/2/send/6/on": 0}), _cond(bus="Nothing Called This")) == []
    twin = _desk(**{"/ch/2/send/6/on": 0, "/bus/5/name": "Bass IEM"})
    assert _findings(twin, _cond(bus="Bass IEM")) == []


def test_silent_for_a_channel_named_twice_or_not_at_all():
    assert _findings(_desk(**{"/ch/2/send/6/on": 0}), _cond(channel="Nobody")) == []


def test_only_the_sends_read_are_judged_when_some_are_not():
    values = {a: v for a, v in _desk(**{"/ch/2/send/6/on": 0}).values.items()
              if a != "/ch/2/send/5/on"}
    [finding] = _findings(ConsoleState(values), _cond())
    assert finding.addresses == ("/ch/2/send/6/on",)


# --------------------------------------------------------------------------
# phantom
# --------------------------------------------------------------------------


def test_48v_off_on_the_socket_the_strip_is_patched_to():
    state = _desk(**{"/io/in/LCL/6/vph": 0})
    [finding] = _findings(state, _cond(
        channel="Room", field="phantom", bus=None,
        description="48V stays on for the room mic"))
    assert (finding.rule_id, finding.severity) == ("WATCH:c", Severity.ERROR)
    assert finding.message == ('CH 4 "Room" has 48V off at LCL 6 -- 48V stays on for the room mic.')
    assert finding.addresses == ("/io/in/LCL/6/vph",)


def test_a_stereo_source_is_judged_on_both_of_its_sockets():
    state = _desk(**{"/io/in/LCL/4/vph": 0})
    [finding] = _findings(state, _cond(channel="OH L", field="phantom", bus=None))
    assert finding.message.startswith('CH 3 "OH L" has 48V off at LCL 4 -- ')
    both = _desk(**{"/io/in/LCL/3/vph": 0, "/io/in/LCL/4/vph": 0})
    [finding] = _findings(both, _cond(channel="OH L", field="phantom", bus=None))
    assert "has 48V off at LCL 3 and LCL 4" in finding.message
    assert finding.addresses == ("/io/in/LCL/3/vph", "/io/in/LCL/4/vph")


def test_a_mono_source_does_not_borrow_the_next_socket():
    state = _desk(**{"/io/in/LCL/7/vph": 0})
    assert _findings(state, _cond(channel="Room", field="phantom", bus=None)) == []


def test_48v_that_must_not_be_on():
    state = _desk()
    [finding] = _findings(state, _cond(channel="Room", field="phantom", bus=None, value=False,
                                       description="No 48V on the room mic"))
    assert finding.message == 'CH 4 "Room" has 48V on at LCL 6 -- No 48V on the room mic.'


def test_phantom_over_a_range_is_one_finding_per_violating_strip():
    state = _desk(**{"/io/in/LCL/3/vph": 0, "/io/in/LCL/6/vph": 0})
    found = _findings(state, _cond(channel="CH 3-4", field="phantom", bus=None))
    assert [f.message.split(" has ")[0] for f in found] == ['CH 3 "OH L"', 'CH 4 "Room"']


@pytest.mark.parametrize("changes", [
    {"/ch/4/in/conn/grp": "USB"},                      # no head amp
    {"/ch/4/in/conn/grp": "OFF"},                      # unpatched
    {"/ch/4/in/set/altsrc": 1},                        # on its alternate input
    {"/io/altsw": 1, "/ch/4/in/conn/altgrp": "A"},     # may follow the global switch
])
def test_phantom_is_silent_where_there_is_nothing_to_compare(changes):
    state = _desk(**{"/io/in/LCL/6/vph": 0, **changes})
    assert _findings(state, _cond(channel="Room", field="phantom", bus=None)) == []


def test_phantom_is_silent_when_a_socket_was_not_read():
    values = {a: v for a, v in _desk().values.items() if a != "/io/in/LCL/4/vph"}
    values["/io/in/LCL/3/vph"] = 0
    assert _findings(ConsoleState(values), _cond(channel="OH L", field="phantom", bus=None)) == []


# --------------------------------------------------------------------------
# Watch: the finding appears and clears
# --------------------------------------------------------------------------


def test_watch_raises_a_send_switched_off_and_clears_it():
    rules = build_watch_rules(_load(_cond()))
    states = iter([_desk(), _desk(**{"/ch/2/send/6/on": 0}), _desk()])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings] == ["WATCH:c"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["WATCH:c"]


def test_watch_raises_48v_lost_and_clears_it():
    rules = build_watch_rules(_load(_cond(channel="Room", field="phantom", bus=None)))
    states = iter([_desk(), _desk(**{"/io/in/LCL/6/vph": 0}), _desk()])
    events = list(watch(lambda: next(states), rules=rules, interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings] == ["WATCH:c"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["WATCH:c"]


def test_a_condition_stands_beside_the_built_in_rules():
    from atoo.audit import DEFAULT_RULES

    rules = list(DEFAULT_RULES) + build_watch_rules(_load(_cond()))
    findings = run_audit(_desk(**{"/ch/2/send/6/on": 0}), rules)
    assert [f.rule_id for f in findings if f.rule_id.startswith("WATCH:")] == ["WATCH:c"]


# --------------------------------------------------------------------------
# What a scoped read must keep
# --------------------------------------------------------------------------


def test_the_addresses_a_send_condition_reads():
    [cond] = _load(_cond(field="send_db", operator="<=", value=-10, bus="BUS 5-6"))
    patterns = condition_address_patterns(cond)
    assert r"^/ch/\d+/send/\d+/lvl$" not in patterns  # `{bank}` is the bank of `channel`
    assert any("send" in p and "lvl" in p for p in patterns)
    assert r"^/bus/\d+/name$" in patterns
    [matrix] = _load(_cond(bus="MTX 3"))
    assert any(r"MX\d+" in p for p in condition_address_patterns(matrix))
    [main] = _load(_cond(bus="MAIN 1"))
    assert any("main" in p for p in condition_address_patterns(main))


def test_the_addresses_a_phantom_condition_reads():
    [cond] = _load(_cond(field="phantom", bus=None))
    joined = " ".join(condition_address_patterns(cond))
    for part in ("in/conn", "altsw", "vph", "mode"):
        assert part in joined


# --------------------------------------------------------------------------
# A draft is merged without calling two different sends the same
# --------------------------------------------------------------------------


def test_two_send_conditions_on_different_busses_are_not_duplicates():
    existing, _ = merge_drafted_conditions(None, _load(_cond(id="a", bus="BUS 5")))
    merged, report = merge_drafted_conditions(existing, _load(_cond(id="b", bus="BUS 6")))
    assert report.duplicates == () and report.added == ("b",)
    assert [c["id"] for c in merged["watch_conditions"]] == ["a", "b"]


def test_the_same_send_condition_in_another_spelling_is_a_duplicate():
    existing, _ = merge_drafted_conditions(None, _load(_cond(id="a", bus="BUS 5")))
    merged, report = merge_drafted_conditions(existing, _load(_cond(id="b", bus="bus5")))
    assert report.duplicates == (("b", "a"),) and report.added == ()


def test_a_drafted_bus_is_written_in_its_one_spelling():
    merged, _ = merge_drafted_conditions(None, _load(_cond(id="a", bus="bus 5-6")))
    assert merged["watch_conditions"][0]["bus"] == "BUS 5-6"
    assert merged["watch_conditions"][0]["source"] == "drafted"


def test_a_draft_keeps_the_bus_key_and_drops_one_it_does_not_know():
    document = {"version": 2, "watch_conditions": [{**_cond(), "index": 3}]}
    kept, notes = salvage_drafted_conditions(document)
    assert kept[0]["bus"] == "BUS 5-6" and "index" not in kept[0]
    assert notes and "dropped unknown key(s) index" in notes[0]


def test_a_draft_with_a_send_field_and_no_bus_is_refused_on_its_own():
    document = {"version": 2, "watch_conditions": [_cond(bus=None), _cond(id="ok", field="muted", bus=None,
                                                            value=False, channel="Kick")]}
    kept, notes = salvage_drafted_conditions(document)
    assert [c["id"] for c in kept] == ["ok"]
    assert any("needs a 'bus' key" in n for n in notes)


# --------------------------------------------------------------------------
# The drafter's prompt comes from the same vocabulary
# --------------------------------------------------------------------------


def test_the_drafters_prompt_names_every_field_and_the_bus_key():
    from atoo import generate, watch_conditions as wc

    prompt = generate.watchlist_system()
    for field in wc._ALLOWED_FIELDS:
        assert f"`{field}`" in prompt
    assert "`bus` — **only** on `send_on`, `send_db` and `send_mode`" in prompt
    assert "seven keys, and `bus` on a send field" in prompt
    assert "{fields}" not in prompt and "{operators}" not in prompt


def test_the_prompts_examples_pass_the_loader_that_will_check_a_draft():
    """Every JSON example the prompt shows a model must be a watchlist the
    loader accepts, or the prompt teaches a draft that will be refused."""
    import re
    from atoo import generate

    prompt = generate.watchlist_system()
    blocks = re.findall(r"```json\n(.*?)\n```", prompt, re.S)
    assert len(blocks) >= 2
    fields = set()
    for block in blocks:
        # A draft is the model's reply, not a file: it has no "version", and
        # is checked condition by condition, as a build checks it.
        loaded, notes = salvage_drafted_conditions(json.loads(block), source="the prompt")
        assert notes == []
        fields |= {c["field"] for c in loaded}
    assert {"send_on", "phantom"} <= fields


def test_the_prompt_asks_for_a_send_or_48v_condition_only_when_the_show_states_it():
    from atoo import generate

    prompt = generate.watchlist_system()
    assert "Draft one only when the" in prompt and "state the requirement" in prompt


# --------------------------------------------------------------------------
# The frozen captures: a factory desk breaks none of them
# --------------------------------------------------------------------------


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: p.name)
def test_the_conditions_agree_with_the_leaves_a_captured_desk_holds(capture):
    """Every strip, every bus, straight off a real desk's capture. A condition
    that no send is on fires for exactly the channels the capture has a send on
    (none, on a factory desk), and the 48V conditions agree with the `vph` the
    capture holds. Nothing is asserted about what is in a capture beyond what
    the evaluator is asked to agree with."""
    values = snap_values(capture)
    if len(values) < 100:
        pytest.skip("not a full console capture")
    state = ConsoleState(values)
    found = _findings(state, _cond(channel="ALL CH", bus="ALL BUS", value=False))
    expected = [n for n in range(1, 41)
                if any(values.get(f"/ch/{n}/send/{b}/on") for b in range(1, 17))]
    assert [f.message.split(" ")[1] for f in found] == [str(n) for n in expected]
    # 48V that is on where a condition says it should not be, on a socket a
    # strip is patched to.
    for finding in _findings(state, _cond(channel="ALL CH", field="phantom", bus=None,
                                          value=False)):
        assert " has 48V on at " in finding.message
        assert all(values[a] for a in finding.addresses)
