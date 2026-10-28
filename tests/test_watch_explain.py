"""A watch condition in plain English: the sentence behind the "i" beside a
condition's ID. It is built from the condition's fields alone, served with
the conditions, and refused (None) for a condition that cannot work."""

from __future__ import annotations

import itertools
import json

import pytest

from conftest import require_fastapi_testclient
from atoo.watch_conditions import (
    _ALLOWED_FIELDS,
    _OPERATORS,
    explain_condition,
    parse_watch_conditions,
    row_problems,
)
from atoo.webui import create_app

fastapi_testclient = require_fastapi_testclient()


def _cond(**overrides):
    base = {"id": "c", "description": "SECRET WORDING", "channel": "CH 1",
            "field": "fader_db", "operator": "<", "value": -40, "severity": "error"}
    base.update(overrides)
    return base


NAMING = 'The alert names the strip by its number and its console name, such as {} 1 "Kick".'


@pytest.mark.parametrize("cond, expected", [
    (_cond(), "Alerts as an error when CH 1 has its fader below -40 dB. " + NAMING.format("CH")),
    (_cond(operator=">", severity="warning"),
     "Alerts as a warning when CH 1 has its fader above -40 dB. " + NAMING.format("CH")),
    (_cond(operator="<=", severity="info"),
     "Alerts as information when CH 1 has its fader at or below -40 dB. " + NAMING.format("CH")),
    (_cond(operator=">=", value=-10.5),
     "Alerts as an error when CH 1 has its fader at or above -10.5 dB. " + NAMING.format("CH")),
    (_cond(operator="!=", value=0),
     "Alerts as an error when CH 1 has its fader not at 0 dB. " + NAMING.format("CH")),
    (_cond(operator="==", value=0),
     "Alerts as an error when CH 1 has its fader at 0 dB. " + NAMING.format("CH")),
    (_cond(channel="DCA 1-5", field="muted", operator="!=", value=False, severity="warning"),
     "Alerts as a warning when any DCA from 1 to 5 is muted. " + NAMING.format("DCA")),
    (_cond(channel="CH 1", field="muted", operator="!=", value=True),
     "Alerts as an error when CH 1 is not muted. " + NAMING.format("CH")),
    (_cond(channel="CH 1", field="muted", operator="==", value=True),
     "Alerts as an error when CH 1 is muted. " + NAMING.format("CH")),
    (_cond(channel="Kick", field="muted", operator="!=", value=False),
     "Alerts as an error when the channel or aux named Kick is muted. " + NAMING.format("CH")),
    (_cond(channel="BUS Drums", field="muted", operator="!=", value=False),
     "Alerts as an error when the BUS named Drums is muted. " + NAMING.format("BUS")),
    (_cond(channel="ALL AUX", field="muted", operator="!=", value=False),
     "Alerts as an error when any AUX is muted. " + NAMING.format("AUX")),
    (_cond(channel="MAIN 1", field="muted", operator="!=", value=False),
     "Alerts as an error when MAIN 1 is muted. The alert names the strip by its number, "
     "such as MAIN 1; a MAIN's console name is not read."),
    (_cond(channel="MTX 2", field="fader_db"),
     "Alerts as an error when MTX 2 has its fader below -40 dB. The alert names the strip "
     "by its number, such as MTX 1; a MTX's console name is not read."),
    (_cond(field="dca", operator="not in", value="Drums"),
     "Alerts as an error when CH 1 is not in DCA Drums. " + NAMING.format("CH")),
    (_cond(field="mute_group", operator="in", value="Stage"),
     "Alerts as an error when CH 1 is in mute group Stage. " + NAMING.format("CH")),
    (_cond(channel="Kick", field="patch", operator="!=", value="lcl 5"),
     "Alerts as an error when the channel or aux named Kick is not patched to LCL 5. "
     + NAMING.format("CH")),
    (_cond(field="patch", operator="==", value="AES50-A 12"),
     "Alerts as an error when CH 1 is patched to AES50-A 12. " + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_on", operator="!=", value=True, bus="BUS 5"),
     "Alerts as an error when CH 3 has its send to BUS 5 switched off. " + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_on", operator="!=", value=False, bus="BUS 5-8"),
     "Alerts as an error when CH 3 has its send to any BUS from 5 to 8 switched on. "
     + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_on", operator="!=", value=True, bus="MAIN 1"),
     "Alerts as an error when CH 3 has its route to MAIN 1 switched off. " + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_db", operator="<", value=-10, bus="BUS Drums"),
     "Alerts as an error when CH 3 has its send to the BUS named Drums below -10 dB. "
     + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_db", operator="<", value=-10, bus="MTX 2"),
     "Alerts as an error when CH 3 has its send to MTX 2 below -10 dB. " + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_mode", operator="!=", value="pre", bus="BUS 1"),
     "Alerts as an error when CH 3 has its send to BUS 1 set to something other than "
     "pre-fader. " + NAMING.format("CH")),
    (_cond(channel="CH 3", field="send_mode", operator="==", value="group", bus="ALL BUS"),
     "Alerts as an error when CH 3 has its send to any BUS set in group mode. "
     + NAMING.format("CH")),
    (_cond(channel="ALL CH", field="phantom", operator="!=", value=False),
     "Alerts as an error when any CH has 48V on. " + NAMING.format("CH")
     + " Only a strip patched to a socket that carries 48V is checked."),
    (_cond(channel="CH 2", field="phantom", operator="!=", value=True),
     "Alerts as an error when CH 2 has 48V off. " + NAMING.format("CH")
     + " Only a strip patched to a socket that carries 48V is checked."),
])
def test_the_sentence_for_each_kind_of_condition(cond, expected):
    assert explain_condition(cond) == expected


def test_the_sentence_never_uses_the_descriptions_words():
    assert "SECRET" not in explain_condition(_cond())
    assert explain_condition(_cond()) == explain_condition(_cond(description="something else"))


_CHANNELS = ["CH 1", "DCA 1-5", "ALL AUX", "BUS Drums", "Kick", "MAIN 1", "MTX 2", "CH 9-12"]
_VALUES = [True, False, -40, 0.5, "pre", "post", "group", "Drums", "LCL 3", "", None, "bogus"]
_BUSES = [None, "BUS 5", "BUS 5-8", "ALL BUS", "BUS Drums", "MTX 3", "MAIN 1", "DCA 1", "bogus 9"]


def test_every_field_operator_combination_has_a_sentence_or_none_exactly_when_refused():
    """Across the whole vocabulary a condition has a sentence if and only
    if the loader accepts it: a malformed one has none, never a wrong one."""
    seen = {"sentence": 0, "none": 0}
    for channel, field, op, value, bus in itertools.product(
            _CHANNELS, sorted(_ALLOWED_FIELDS), sorted(_OPERATORS), _VALUES, _BUSES):
        cond = _cond(channel=channel, field=field, operator=op, value=value)
        if bus is not None:
            cond["bus"] = bus
        try:
            parse_watch_conditions(json.dumps({"version": 2, "watch_conditions": [cond]}))
            accepted = True
        except Exception:
            accepted = False
        sentence = explain_condition(cond)
        assert (sentence is not None) == accepted, (cond, sentence)
        seen["sentence" if accepted else "none"] += 1
        if accepted:
            assert sentence.startswith("Alerts as ")
            assert sentence.count(". ") + sentence.endswith(".") >= 2
    assert seen["sentence"] > 100 and seen["none"] > 100


@pytest.mark.parametrize("bad", [
    _cond(channel="CH 99"), _cond(channel="DCA 16-10"), _cond(channel=""), _cond(channel="CH"),
    _cond(field="bogus"), _cond(operator="~="), _cond(severity="critical"), _cond(severity=None),
    _cond(field="muted", operator="<=", value=True), _cond(field="dca", operator=">", value="x"),
    _cond(field="send_on", operator="!=", value=True),
    _cond(field="send_on", operator="!=", value=True, bus="CH 1"),
    _cond(field="fader_db", bus="BUS 1"), _cond(field="fader_db", value="loud"),
    _cond(field="patch", value="nowhere 1"), "not a condition", None,
])
def test_a_condition_that_cannot_work_has_no_sentence(bad):
    assert explain_condition(bad) is None


def _app_with(tmp_path, conditions):
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"version": 2, "watch_conditions": conditions}))
    return create_app(initial_watch_conditions_path=str(path))


def test_the_conditions_are_served_with_their_sentences(tmp_path):
    good = _cond(id="a", channel="DCA 1-5", field="muted", operator="!=", value=False)
    other = _cond(id="b")
    with fastapi_testclient.TestClient(_app_with(tmp_path, [good, other])) as c:
        body = c.get("/api/watch-conditions").json()
    assert body["explanations"] == [explain_condition(good), explain_condition(other)]


def test_the_inline_check_returns_the_sentence_only_for_a_row_that_works(tmp_path):
    good, bad = _cond(), _cond(channel="CH 99")
    with fastapi_testclient.TestClient(_app_with(tmp_path, [good])) as c:
        rows = c.post("/api/watch-conditions/check",
                      json={"version": 2, "watch_conditions": [good, bad]}).json()["rows"]
    assert rows[0]["explanation"] == explain_condition(good)
    assert "explanation" not in rows[1] and "channel" in rows[1]
    assert "explanation" not in row_problems(good)


def test_the_page_wires_the_info_icon_beside_the_id():
    with fastapi_testclient.TestClient(create_app()) as c:
        js = c.get("/static/watch.js").text
        shell = c.get("/static/shell.js").text
        css = c.get("/static/styles.css").text
    assert "wcMakeExplain" in js and "data-hover-open" in js
    assert "data.explanations" in js and "wcRowChecks[index]" in js
    assert 'aria-controls", "wc-explain-"' in js
    assert "explanation" in js
    assert "data-hover-open" in shell and "mouseover" in shell
    assert ".wc-explain" in css
    # The icon has its own room beside the ID box, so the Description box does
    # not cover it, and it is the info blue, a pixel larger than other help buttons.
    assert "#wc-table .wc-id-cell input { vertical-align: middle; width: calc(100% - 28px); }" in css
    assert "width: 19px; height: 19px; font-size: 12px" in css
    assert "color: var(--info-fg); border-color: var(--info-fg);" in css
