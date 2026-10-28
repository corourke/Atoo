"""A watch condition states when to alert.

It fires when it is true. `dca` and `mute_group` take `in` and `not in`. A
watch.json carries `"version": 2`; one without it was written when a
condition stated what should hold, the opposite meaning, and is refused with
how to convert it -- including a one-liner that does it in place. The
desks are built in the test.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys

import pytest

from atoo import capture
from atoo.audit import ConsoleState
from atoo.watch_conditions import (
    FORMAT_VERSION,
    WatchConditionsError,
    build_watch_rules,
    explain_condition,
    load_watch_conditions,
    merge_drafted_conditions,
    new_document,
    parse_watch_conditions,
)


def _cond(**overrides) -> dict:
    base = {"id": "c", "description": "Kick is wrong", "channel": "Kick", "field": "muted",
            "operator": "==", "value": True, "severity": "warning"}
    base.update(overrides)
    return base


def _fires(state: ConsoleState, **overrides) -> bool:
    conditions = parse_watch_conditions(json.dumps(new_document([_cond(**overrides)])))
    [rule] = build_watch_rules(conditions)
    return bool(rule.check(state))


KICK = {"/ch/1/name": "Kick", "/ch/1/mute": 1, "/ch/1/fdr": -20.0, "/ch/1/tags": "#D1",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1, "/dca/1/name": "Drums",
        "/mgrp/1/name": "FX"}


@pytest.mark.parametrize("overrides, fires", [
    # The issue's own three examples.
    ({"field": "muted", "operator": "==", "value": True}, True),
    ({"field": "patch", "operator": "!=", "value": "LCL 5"}, True),
    ({"field": "fader_db", "operator": "<", "value": -10}, True),
    # ... and their opposites stay quiet.
    ({"field": "muted", "operator": "==", "value": False}, False),
    ({"field": "patch", "operator": "!=", "value": "LCL 1"}, False),
    ({"field": "fader_db", "operator": ">=", "value": -10}, False),
    # Membership in words.
    ({"field": "dca", "operator": "in", "value": "Drums"}, True),
    ({"field": "dca", "operator": "not in", "value": "Drums"}, False),
    ({"field": "mute_group", "operator": "not in", "value": "FX"}, True),
    ({"field": "mute_group", "operator": "in", "value": "FX"}, False),
])
def test_a_condition_fires_when_it_is_true(overrides, fires):
    assert _fires(ConsoleState(dict(KICK)), **overrides) is fires


def test_the_sentence_reads_the_same_way_round_as_the_condition():
    assert explain_condition(_cond(field="fader_db", operator="<", value=-10)).startswith(
        "Alerts as a warning when the channel or aux named Kick has its fader below -10 dB.")
    assert explain_condition(_cond(field="dca", operator="not in", value="Drums")).startswith(
        "Alerts as a warning when the channel or aux named Kick is not in DCA Drums.")
    assert explain_condition(_cond(field="muted", operator="==", value=True)).startswith(
        "Alerts as a warning when the channel or aux named Kick is muted.")


@pytest.mark.parametrize("operator, meant", [("==", "not in"), ("!=", "in")])
def test_the_old_spelling_on_a_group_field_is_refused_saying_how_to_write_it(operator, meant):
    with pytest.raises(WatchConditionsError) as raised:
        parse_watch_conditions(json.dumps(new_document([
            _cond(field="dca", operator=operator, value="Drums")])))
    message = str(raised.value)
    assert "field 'dca' takes 'in' or 'not in'" in message
    assert f"meant {operator!r} as {meant!r}" in message


def test_in_is_only_for_membership():
    with pytest.raises(WatchConditionsError, match="'in' and 'not in' are for dca and mute_group"):
        parse_watch_conditions(json.dumps(new_document([_cond(operator="in")])))


OLD = {"watch_conditions": [
    {"id": "kick-unmuted", "description": "Kick stays unmuted", "channel": "Kick",
     "field": "muted", "operator": "==", "value": False, "severity": "error"},
    {"id": "kick-fader", "description": "Kick fader stays above -40", "channel": "Kick",
     "field": "fader_db", "operator": ">=", "value": -40, "severity": "warning"},
    {"id": "kick-in-drums", "description": "Kick stays in Drums", "channel": "Kick",
     "field": "dca", "operator": "==", "value": "Drums", "severity": "warning"},
    {"id": "kick-out-of-fx", "description": "Kick stays out of FX", "channel": "Kick",
     "field": "mute_group", "operator": "!=", "value": "FX", "severity": "info"},
]}


def test_a_file_without_the_mark_is_refused_naming_it_and_saying_what_changed(tmp_path):
    path = tmp_path / "my show" / "watch.json"
    path.parent.mkdir()
    path.write_text(json.dumps(OLD, indent=2))
    with pytest.raises(WatchConditionsError) as raised:
        load_watch_conditions(path)
    message = str(raised.value)
    assert message.startswith(f"{path}: has no \"version\": 2")
    assert "A condition now states when to alert: it fires when it is true." in message
    assert ("== and != swap, < becomes >=, >= becomes <, <= becomes >, > becomes <=; on dca "
            "and mute_group, == becomes \"not in\" and != becomes \"in\"") in message
    assert message.rstrip().endswith(shlex.quote(str(path)))


def test_the_one_liner_in_the_refusal_converts_the_file_in_place(tmp_path):
    path = tmp_path / "watch.json"
    path.write_text(json.dumps(OLD, indent=2))
    with pytest.raises(WatchConditionsError) as raised:
        load_watch_conditions(path)
    command = str(raised.value).splitlines()[-1].strip()
    assert command.startswith("python3 -c ")
    # Run it as a shell would, with this interpreter standing in for python3.
    argv = shlex.split(command)
    subprocess.run([sys.executable, *argv[1:]], check=True)
    converted = load_watch_conditions(path)
    assert [(c["operator"], c["value"]) for c in converted] == [
        ("!=", False), ("<", -40), ("not in", "Drums"), ("in", "FX")]
    assert json.loads(path.read_text())["version"] == FORMAT_VERSION
    # Kick is muted, at -20 dB, in Drums and in no mute group. Converted, the
    # file alerts where the old one did: on the mute, and on nothing else.
    rules = build_watch_rules(converted)
    assert [r.id for r in rules if r.check(ConsoleState(dict(KICK)))] == ["WATCH:kick-unmuted"]
    # Put Kick in FX and take it out of Drums, and those two alert as well.
    moved = ConsoleState(dict(KICK, **{"/ch/1/tags": "#M1"}))
    assert sorted(r.id for r in rules if r.check(moved)) == [
        "WATCH:kick-in-drums", "WATCH:kick-out-of-fx", "WATCH:kick-unmuted"]


def test_a_version_this_atoo_does_not_know_is_refused():
    with pytest.raises(WatchConditionsError, match="\"version\" is 3"):
        parse_watch_conditions(json.dumps({"version": 3, "watch_conditions": []}))


def test_everything_that_writes_a_watch_json_writes_the_mark(tmp_path):
    assert json.loads(capture.EMPTY_WATCH) == new_document()
    document, _report = merge_drafted_conditions(None, [_cond(id="drafted")], plan=None)
    assert document["version"] == FORMAT_VERSION
    assert list(document)[0] == "version"
    # A file merged into keeps its own keys and gets the mark.
    old_style = {"watch_conditions": [], "drafted": ["gone"]}
    document, _report = merge_drafted_conditions(old_style, [], plan=None)
    assert document["version"] == FORMAT_VERSION and document["drafted"] == ["gone"]
