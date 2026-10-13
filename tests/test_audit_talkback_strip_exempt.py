"""T002, and the talkback strip left out of CH001 / L002.

T001's first run on hardware (2026-09-25, the Compact) also reported
ch 40 "TALKBACK" as in no DCA (CH001) and fader at floor (L002) --
the talk mic's strip, kept out of the mix on purpose. The maintainer: exempt it,
and say so once. Fixtures are built by hand; no capture has talkback set up.
"""

from __future__ import annotations

import pytest

from atoo import console_facts
from atoo.audit import ConsoleState, is_in_use, run_audit, talkback_strip


def _strip(base: str, name: str) -> dict:
    # An in-use strip: named, unmuted, fader at the floor, in no DCA.
    return {f"{base}/name": name, f"{base}/mute": 0, f"{base}/fdr": -144.0,
            f"{base}/tags": "", f"{base}/in/conn/grp": "LCL", f"{base}/in/conn/in": 1}


def _desk(assign: str) -> ConsoleState:
    values: dict = {console_facts.TALK_ASSIGN: assign}
    values.update(_strip("/ch/40", "TALKBACK"))
    values.update(_strip("/ch/39", "Tom 3"))
    values.update(_strip("/aux/8", "TB aux"))
    return ConsoleState(values)


def _hits(state: ConsoleState, rule: str) -> set[str]:
    return {a for f in run_audit(state) if f.rule_id == rule for a in f.addresses}


def test_fixture_strips_are_in_use():
    state = _desk("CH40")
    assert all(is_in_use(state, b) for b in ("/ch/40", "/ch/39", "/aux/8"))


@pytest.mark.parametrize("assign,talk,other", [("CH40", "/ch/40", "/aux/8"),
                                              ("AUX8", "/aux/8", "/ch/40")])
def test_the_talkback_strip_is_skipped_and_nothing_else_is(assign, talk, other):
    state = _desk(assign)
    assert talkback_strip(state) == talk
    no_dca = _hits(state, "CH001")
    floor = _hits(state, "L002")
    assert talk not in no_dca and f"{talk}/fdr" not in floor
    # A band strip on the same desk is still judged.
    assert "/ch/39" in no_dca and "/ch/39/fdr" in floor
    assert other in no_dca and f"{other}/fdr" in floor


@pytest.mark.parametrize("assign,talk", [("CH40", "/ch/40"), ("AUX8", "/aux/8")])
def test_the_exemption_announces_itself_once(assign, talk):
    notes = [f for f in run_audit(_desk(assign)) if f.rule_id == "T002"]
    assert len(notes) == 1
    [note] = notes
    assert note.severity.value == "info"
    assert talk in note.addresses and assign in note.message


def test_talkback_off_exempts_nothing_and_says_nothing():
    state = _desk("OFF")
    assert talkback_strip(state) is None
    assert "/ch/40" in _hits(state, "CH001")
    assert "/ch/40/fdr" in _hits(state, "L002")
    assert not [f for f in run_audit(state) if f.rule_id == "T002"]


def test_unread_assign_exempts_nothing():
    state = _desk("CH40")
    del state.values[console_facts.TALK_ASSIGN]
    assert talkback_strip(state) is None
    assert "/ch/40" in _hits(state, "CH001")
