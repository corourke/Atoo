"""CV014, talkback assigned to CH40 or
AUX8 while the plan puts an ordinary input on that strip.

Every capture on disk has talkback unassigned, so the desk is built by
hand here, and so is the plan -- no bundle under `examples/` is read.
"""

from __future__ import annotations

import pytest

from atoo import console_facts
from atoo.audit import ConsoleState, diff_against_plan
from atoo.diagnostics import Severity


def _plan(bank: str, channel: int, name: str, source_input: str | None = None) -> dict:
    return {"channels": [{
        "bank": bank, "channel": channel, "name": name,
        "source": {"input": source_input or name, "stereo": False, "phantom": False},
    }]}


def _desk(assign: str | None) -> ConsoleState:
    values: dict[str, object] = {"/ch/40/name": "", "/aux/8/name": ""}
    if assign is not None:
        values[console_facts.TALK_ASSIGN] = assign
    return ConsoleState(values)


def _cv014(state: ConsoleState, plan: dict) -> list:
    return [f for f in diff_against_plan(state, plan) if f.rule_id == "CV014"]


@pytest.mark.parametrize("assign,bank,channel", [("CH40", "ch", 40), ("AUX8", "aux", 8)])
def test_a_band_input_on_the_talkback_strip_is_a_warning(assign, bank, channel):
    [f] = _cv014(_desk(assign), _plan(bank, channel, "Tom 3"))
    assert f.severity == Severity.WARNING
    assert f.category == "conventions"
    assert assign in f.message and "'Tom 3'" in f.message
    assert console_facts.TALK_ASSIGN in f.addresses


@pytest.mark.parametrize("assign,bank,channel", [
    ("CH40", "aux", 8),   # talkback on ch 40, the plan's input on aux 8
    ("AUX8", "ch", 40),
    ("CH40", "ch", 39),
])
def test_an_input_on_a_different_strip_is_not_a_clash(assign, bank, channel):
    assert _cv014(_desk(assign), _plan(bank, channel, "Tom 3")) == []


@pytest.mark.parametrize("assign", ["OFF", None])
def test_unassigned_or_unread_talkback_is_silent(assign):
    assert _cv014(_desk(assign), _plan("ch", 40, "Tom 3")) == []


@pytest.mark.parametrize("name,source_input", [
    ("Talkback", None), ("Talk Mic", None), ("TB", None), ("T/B", None),
    ("FOH Comms", "Talkback SM58"),   # named by its source, not its strip
])
def test_the_talk_mic_itself_on_the_talkback_strip_is_where_it_belongs(name, source_input):
    assert _cv014(_desk("CH40"), _plan("ch", 40, name, source_input)) == []


@pytest.mark.parametrize("name", ["Tabla", "Bass DI", "Stable Pad", "Outboard Synth", "Stalk"])
def test_names_that_merely_contain_the_letters_still_fire(name):
    assert len(_cv014(_desk("CH40"), _plan("ch", 40, name))) == 1
