"""The audit report as a person reads it.

Two things an engineer at a desk should not have to translate:

* **a strip named by its OSC address** -- `/ch/3 (Vocal)` -- where the
  desk and everyone at it says `CH 3`;
* **one rule repeated once per strip** -- five `L002` entries, one
  after the other, for five channels with their faders at the floor.

So findings name strips as `CH 3 "Vocal"` (the shape Watch's own
findings already use), and `audit`/`watch` print one entry per rule. The
findings themselves are not merged: every one is still its own
`Diagnostic` with its own addresses, and the counts line counts them.
"""

from __future__ import annotations

import re

from atoo.audit import (
    ConsoleState, strip_label, position_label, render_findings, rule_groups, shared_sentence,
)
from atoo.diagnostics import Diagnostic, Severity
from atoo.watch import WatchEvent, render_event


def _at_floor(position: str, name: str) -> Diagnostic:
    return Diagnostic.audit(
        "L002", Severity.INFO, "levels", "Active Strip Fader At Floor",
        f'{position} "{name}" is unmuted and in use, but its own fader is at -144dB.', ())


def _dead_send(position: str, level: int) -> Diagnostic:
    return Diagnostic.audit(
        "L001", Severity.WARNING, "levels", "Send On But Near-Silent",
        f"{position}'s send to BUS 1 is on at {level}dB -- audible in principle, "
        "in practice dead.", ())


# -- naming a strip -----------------------------------------------------------


def test_a_strip_is_named_by_its_position_on_the_desk():
    assert position_label("/ch/3") == "CH 3"
    assert position_label("/aux/2") == "AUX 2"
    assert position_label("/bus/12") == "BUS 12"
    assert position_label("/main/1") == "MAIN 1"
    assert position_label("/mtx/4") == "MTX 4"
    assert position_label("/dca/1") == "DCA 1"
    assert position_label("/mgrp/1") == "MGRP 1"


def test_anything_that_is_not_a_strip_comes_back_as_given():
    assert position_label("/io/in/LCL/9") == "/io/in/LCL/9"
    assert position_label("/cfg/talk/assign") == "/cfg/talk/assign"


def test_a_named_strip_quotes_its_name_after_its_position():
    state = ConsoleState({"/ch/3/name": "Vocal", "/bus/2/name": ""})
    assert strip_label(state, "/ch/3") == 'CH 3 "Vocal"'
    assert strip_label(state, "/bus/2") == "BUS 2"


# -- one entry per rule -------------------------------------------------------


def test_one_rule_on_five_strips_is_one_entry_naming_all_five():
    findings = [_at_floor(f"CH {n}", name) for n, name in
                [(3, "Vocal"), (4, "Vocal"), (5, "Bass"), (6, "Bass DI"), (7, "Playback")]]
    text = render_findings(findings)

    assert text.startswith("Audit findings: 5 info.\n")
    assert text.count("L002") == 1
    assert ('[INFO] L002 Active Strip Fader At Floor (5)\n'
            '  CH 3 "Vocal", CH 4 "Vocal", CH 5 "Bass", CH 6 "Bass DI", CH 7 "Playback"\n'
            '  Each is unmuted and in use, but its own fader is at -144dB.\n') in text


def test_a_rule_that_fired_once_reads_as_it_always_has():
    text = render_findings([_at_floor("CH 3", "Vocal")])
    assert '[INFO] L002 Active Strip Fader At Floor\n  CH 3 "Vocal" is unmuted' in text
    assert "(1)" not in text and "Each" not in text


def test_sentences_that_differ_past_the_strip_are_each_kept_under_one_heading():
    """A level is a value a person acts on: it is never summarised away."""
    text = render_findings([_dead_send('CH 2 "Snare"', -105), _dead_send('CH 9 "Tom"', -110)])
    assert text.count("L001") == 1
    assert "[WARNING] L001 Send On But Near-Silent (2)\n" in text
    assert "-105dB" in text and "-110dB" in text
    assert "Each" not in text


def test_a_long_list_of_strips_wraps_rather_than_running_off_the_screen():
    findings = [_at_floor(f"CH {n}", f"Input {n}") for n in range(1, 25)]
    lines = render_findings(findings).splitlines()
    assert all(len(line) <= 80 for line in lines)
    item_lines = [line.strip() for line in lines if '"Input ' in line]
    assert len(item_lines) > 1
    # ...between strips, never inside one: `CH 6` and its name stay together.
    for line in item_lines:
        for piece in line.rstrip(",").split(", "):
            assert re.fullmatch(r'CH \d+ "Input \d+"', piece), piece


def test_severity_is_part_of_the_group():
    a = _at_floor("CH 3", "Vocal")
    b = Diagnostic.audit("L002", Severity.WARNING, a.category, a.title, a.detail, ())
    assert len(rule_groups([a, b])) == 2


def test_grouping_is_display_only():
    findings = [_at_floor("CH 3", "Vocal"), _at_floor("CH 4", "Vocal")]
    before = list(findings)
    render_findings(findings)
    assert findings == before
    assert shared_sentence(findings) == (['CH 3 "Vocal"', 'CH 4 "Vocal"'],
                                         " is unmuted and in use, but its own fader is at -144dB.")


# -- watch's NEW / CLEARED lines group the same way ---------------------------


def test_watch_reports_one_line_per_rule_that_started_tripping():
    new = [_at_floor("CH 3", "Vocal"), _at_floor("CH 4", "Vocal")]
    text = render_event(WatchEvent(1, "T", new, new, []))
    assert text.splitlines()[1:] == [
        '  NEW     [INFO] L002 Active Strip Fader At Floor (2): CH 3 "Vocal", CH 4 "Vocal" '
        "-- each is unmuted and in use, but its own fader is at -144dB."]


def test_watch_keeps_one_finding_on_one_line():
    gone = [_dead_send('CH 2 "Snare"', -105)]
    text = render_event(WatchEvent(1, "T", [], [], gone))
    assert text.splitlines()[1] == (
        '  CLEARED [WARNING] L001 Send On But Near-Silent: CH 2 "Snare"\'s send to BUS 1 '
        "is on at -105dB -- audible in principle, in practice dead.")
