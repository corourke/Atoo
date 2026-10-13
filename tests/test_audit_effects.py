"""An earlier change, the effects half: E001-003, over the strip inserts and
the FX slots they name (`console_facts.INSERT_POINTS`, `FX_MODEL`).

The fixtures are built by hand, one per rule. The one capture that has
values for all of this -- A17, a full-size WING with all sixteen slots
loaded and inserted -- is scored as it was read, and then broken one
setting at a time. That capture is the evidence the address model rests
on, so a rule that fires on it as captured would be a rule that is wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import console_facts
from atoo.audit import ConsoleState, console_read_plan, run_audit
from atoo.diagnostics import Severity

CAPTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "console-runs"
A17 = CAPTURES / "2026-09-23-1921" / "A17-wing-full.snap"
INITIALIZED = CAPTURES / "Initialized-Compact.snap"

EFFECTS = ("E001", "E002", "E003")


def _effects(state: ConsoleState, plan: dict | None = None) -> list:
    return [f for f in run_audit(state, plan=plan) if f.rule_id in EFFECTS]


def _ids(findings) -> list[str]:
    return sorted(f.rule_id for f in findings)


def _empty_desk(**overrides) -> ConsoleState:
    """Every insert point and slot a Compact read asks for, all empty and
    off, plus `overrides`."""
    values: dict[str, object] = {}
    for address, _ in console_read_plan():
        if address.endswith("ins/ins") or address.endswith("/mdl"):
            values[address] = console_facts.FX_EMPTY
        elif address.endswith("ins/on"):
            values[address] = 0
    values.update(overrides)
    return ConsoleState(values)


# -- the read ---------------------------------------------------------------


def test_the_read_asks_for_every_insert_point_and_every_slot():
    plan = {a for a, _ in console_read_plan()}
    for point in ("preins", "postins"):
        for leaf in ("on", "ins"):
            assert f"/ch/40/{point}/{leaf}" in plan
            assert f"/bus/16/{point}/{leaf}" in plan
            assert f"/main/4/{point}/{leaf}" in plan
            assert f"/mtx/8/{point}/{leaf}" in plan
    # An aux has a pre-insert and no post-insert (the parameter map).
    assert "/aux/8/preins/ins" in plan
    assert "/aux/8/postins/ins" not in plan
    assert {f"/fx/{n}/mdl" for n in range(1, 17)} <= plan
    assert "/fx/17/mdl" not in plan


# -- each rule, fired and not ----------------------------------------------


def test_a_factory_desk_says_nothing():
    assert _effects(_empty_desk()) == []


def test_sp_e001_an_insert_on_that_names_an_empty_slot():
    state = _empty_desk(**{"/ch/3/preins/on": 1, "/ch/3/preins/ins": "FX4",
                           "/ch/3/name": "Lead Vox"})
    [f] = _effects(state)
    assert f.rule_id == "E001"
    assert f.severity == Severity.WARNING
    assert 'CH 3 "Lead Vox"' in f.detail and "FX4" in f.detail
    assert "/fx/4/mdl" in f.addresses


def test_sp_e001_is_silent_when_the_insert_is_off_or_the_slot_is_loaded():
    off = _empty_desk(**{"/ch/3/preins/on": 0, "/ch/3/preins/ins": "FX4"})
    # Nor E003: a switched-off insert on an EMPTY slot bypasses nothing.
    assert _effects(off) == []
    loaded = _empty_desk(**{"/ch/3/preins/on": 1, "/ch/3/preins/ins": "FX4",
                            "/fx/4/mdl": "DE-S2"})
    assert _effects(loaded) == []


def test_sp_e001_reaches_a_main_and_a_matrix_post_insert():
    state = _empty_desk(**{"/main/1/postins/on": 1, "/main/1/postins/ins": "FX9",
                           "/mtx/2/postins/on": 1, "/mtx/2/postins/ins": "FX10"})
    assert sorted(f.addresses[0] for f in _effects(state)) == [
        "/main/1/postins/on", "/mtx/2/postins/on"]


def test_sp_e002_a_loaded_slot_nothing_inserts():
    [f] = _effects(_empty_desk(**{"/fx/2/mdl": "HALL"}))
    assert f.rule_id == "E002"
    assert f.severity == Severity.INFO
    assert "FX2 (HALL)" in f.detail


def test_sp_e002_is_silent_once_any_strip_names_the_slot_even_bypassed():
    state = _empty_desk(**{"/fx/2/mdl": "HALL", "/bus/5/preins/ins": "FX2"})
    # Named, so not orphaned -- but switched off, which is E003's.
    assert _ids(_effects(state)) == ["E003"]


def test_sp_e003_a_loaded_slot_on_a_switched_off_insert():
    state = _empty_desk(**{"/fx/6/mdl": "VSS3", "/bus/11/preins/ins": "FX6",
                           "/bus/11/name": "Vox Verb"})
    [f] = _effects(state)
    assert f.rule_id == "E003"
    assert 'BUS 11 "Vox Verb"' in f.detail and "FX6 (VSS3)" in f.detail


# -- silent, not clean, on what was never read ------------------------------


def test_nothing_fires_on_a_state_that_never_read_an_insert():
    # Every capture made before this rule: slots, no inserts. E002
    # would otherwise call every loaded slot orphaned.
    state = ConsoleState({"/fx/1/mdl": "HALL", "/ch/1/name": "Kick"})
    assert _effects(state) == []


def test_an_insert_naming_a_slot_that_was_never_read_says_nothing():
    state = ConsoleState({"/ch/1/preins/on": 1, "/ch/1/preins/ins": "FX1"})
    assert _effects(state) == []


def test_an_insert_whose_switch_was_never_read_is_not_called_off():
    state = ConsoleState({"/ch/1/preins/ins": "FX1", "/fx/1/mdl": "HALL"})
    assert _effects(state) == []


# -- plan scope -------------------------------------------------------------


def test_sp_e003_is_withheld_about_a_strip_the_plan_never_mentions():
    state = _empty_desk(**{"/fx/6/mdl": "VSS3", "/ch/30/preins/ins": "FX6",
                           "/ch/1/preins/on": 1, "/ch/1/preins/ins": "FX7"})
    plan = {"channels": [{"channel": 1, "name": "Kick"}]}
    # E001 on /ch/1 is a hazard and stays; E003 on /ch/30 goes.
    assert _ids(_effects(state, plan)) == ["E001"]
    assert _ids(_effects(state)) == ["E001", "E003"]


# -- the hardware capture ---------------------------------------------------


def _state_from_snap(path: Path) -> ConsoleState:
    """The insert points, slots and names of a `.snap`, as the addresses
    `read_console_state` asks for. A `.snap` is the desk's own node tree,
    so `ae_data["bus"]["11"]["preins"]["ins"]` is `/bus/11/preins/ins`."""
    ae = json.loads(path.read_text())["ae_data"]
    values: dict[str, object] = {}
    for bank, points in console_facts.INSERT_POINTS.items():
        for n, obj in (ae.get(bank) or {}).items():
            if obj.get("name"):
                values[f"/{bank}/{n}/name"] = obj["name"]
            for point in points:
                node = obj.get(point) or {}
                if "ins" in node:
                    values[f"/{bank}/{n}/{point}/ins"] = node["ins"]
                    values[f"/{bank}/{n}/{point}/on"] = int(node["on"])
    for n, slot in (ae.get("fx") or {}).items():
        values[f"/fx/{n}/mdl"] = slot["mdl"]
    return ConsoleState(values)


@pytest.fixture(scope="module")
def a17() -> ConsoleState:
    return _state_from_snap(A17)


def test_a17_as_captured_is_clean_and_really_does_use_every_slot(a17):
    """Sixteen loaded slots, each inserted once, all switched on -- so the
    capture exercises every code path that decides NOT to fire."""
    assert all(a17.fx_model(n) not in (None, "NONE") for n in range(1, 17))
    named = sorted(slot for base in {a.rsplit("/", 2)[0] for a in a17.values
                                     if a.endswith("ins/ins")}
                   for _, slot, on in a17.inserts(base) if slot and on)
    assert named == list(range(1, 17))
    assert _effects(a17) == []


def test_a17_with_its_vocal_reverb_slot_cleared(a17):
    # Bus 11's pre-insert is FX4 (BPLATE). Empty the slot.
    state = ConsoleState({**a17.values, "/fx/4/mdl": "NONE"})
    [f] = _effects(state)
    assert f.rule_id == "E001"
    assert f.addresses[0] == "/bus/11/preins/on"


def test_a17_with_one_insert_switched_off(a17):
    state = ConsoleState({**a17.values, "/bus/11/preins/on": 0})
    assert _ids(_effects(state)) == ["E003"]


def test_a17_with_one_insert_pointed_elsewhere(a17):
    # /ch/4's pre-insert (FX15) cleared: FX15 is loaded and now orphaned.
    state = ConsoleState({**a17.values, "/ch/4/preins/ins": "NONE"})
    [f] = _effects(state)
    assert f.rule_id == "E002" and "FX15" in f.detail


def test_an_initialized_compact_is_clean():
    assert _effects(_state_from_snap(INITIALIZED)) == []
