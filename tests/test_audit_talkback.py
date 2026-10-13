"""An earlier change, the comms half: T001, talkback assigned to a strip but
routed nowhere (`console_facts.TALK_*`).

Every capture on disk has talkback unassigned and every destination off
-- the factory state -- so the fixtures that fire the rule are built by
hand, and the captures are only asked to stay silent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES, ConsoleState, console_read_plan, read_console_state, run_audit,
    talkback_addresses,
)
from atoo.console import OscReply
from atoo.diagnostics import Severity

CAPTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "console-runs"

SWITCHES = [console_facts.talk_destination(b, d)
            for b in console_facts.TALK_BUTTONS
            for d in console_facts.TALK_DESTINATIONS]


def _talk(state: ConsoleState) -> list:
    return [f for f in run_audit(state) if f.rule_id == "T001"]


def _desk(assign: str = "CH40", **on) -> ConsoleState:
    values: dict[str, object] = {console_facts.TALK_ASSIGN: assign}
    values.update({address: 0 for address in SWITCHES})
    values.update({console_facts.talk_destination(*k.split("_")): v for k, v in on.items()})
    return ConsoleState(values)


# -- the rule ---------------------------------------------------------------


def test_assigned_talkback_routed_nowhere_is_a_warning():
    [f] = _talk(_desk("CH40"))
    assert f.severity == Severity.WARNING
    assert f.category == "communications"
    assert "CH40" in f.message
    assert console_facts.TALK_ASSIGN in f.addresses


@pytest.mark.parametrize("button,dest", [("A", "B3"), ("B", "MX8"), ("A", "M1"), ("B", "B16")])
def test_any_one_destination_on_either_button_is_enough(button, dest):
    assert _talk(_desk("AUX8", **{f"{button}_{dest}": 1})) == []


def test_unassigned_talkback_is_the_factory_state_not_a_fault():
    assert _talk(_desk("OFF")) == []


def test_silent_when_assign_was_never_read():
    state = _desk("CH40")
    del state.values[console_facts.TALK_ASSIGN]
    assert _talk(state) == []


def test_silent_not_clean_when_a_switch_was_never_read():
    state = _desk("CH40")
    del state.values[console_facts.talk_destination("B", "M4")]
    assert _talk(state) == []


def test_sp_t001_is_in_the_default_catalogue_as_a_hazard():
    [rule] = [r for r in DEFAULT_RULES if r.id == "T001"]
    assert rule.severity == Severity.WARNING
    assert rule.category == "communications"
    assert rule.scope.value == "hazard"


@pytest.mark.parametrize("snap", [
    "Initialized-Compact.snap",
    "2026-09-23-1921/A17-wing-full.snap",
])
def test_every_capture_on_disk_is_factory_talkback(snap):
    """The premise of the fixtures above: no capture has talkback set up.
    If one ever does, it is the evidence this rule is still missing and
    belongs in a test of its own."""
    talk = json.loads((CAPTURES / snap).read_text())["ae_data"]["cfg"]["talk"]
    assert talk["assign"] == "OFF"
    assert not any(talk[b][d] for b in "AB" for d in console_facts.TALK_DESTINATIONS)


# -- the read ---------------------------------------------------------------


def test_the_first_pass_asks_only_for_the_assignment():
    plan = [a for a, _ in console_read_plan()]
    assert plan.count(console_facts.TALK_ASSIGN) == 1
    assert not any(a.startswith("/cfg/talk/A") or a.startswith("/cfg/talk/B") for a in plan)


def test_the_second_pass_asks_for_the_routing_only_when_assigned():
    assert talkback_addresses(ConsoleState({console_facts.TALK_ASSIGN: "OFF"})) == []
    assert talkback_addresses(ConsoleState({})) == []
    asked = talkback_addresses(ConsoleState({console_facts.TALK_ASSIGN: "AUX8"}))
    assert [a for a, _ in asked] == SWITCHES
    assert len(asked) == 56


class _Desk:
    console_model = "wing-compact"

    def __init__(self, values):
        self.values = values
        self.asked = []

    def get(self, address):
        self.asked.append(address)
        if address not in self.values:
            return None
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address=address, typetag="s", args=[value])
        return OscReply(address=address, typetag="sfi", args=[str(value), 0.0, value])


_NOTHING_ELSE = dict(channels=0, aux=0, buses=0, mains=0, matrices=0,
                     dcas=0, mute_groups=0, fx_slots=0)


def test_a_live_read_of_assigned_talkback_fetches_its_routing_and_finds_it():
    desk = _Desk({console_facts.TALK_ASSIGN: "CH40", **{a: 0 for a in SWITCHES}})
    state = read_console_state(desk, **_NOTHING_ELSE)
    assert set(SWITCHES) <= set(desk.asked)
    assert [f.rule_id for f in _talk(state)] == ["T001"]


def test_a_live_read_of_unassigned_talkback_asks_nothing_more():
    desk = _Desk({console_facts.TALK_ASSIGN: "OFF"})
    read_console_state(desk, **_NOTHING_ELSE)
    # Plus the one global the read always asks, the alternate switch
    # (C005) -- nothing about talkback.
    assert desk.asked == [console_facts.TALK_ASSIGN, console_facts.GLOBAL_ALT_SWITCH]
