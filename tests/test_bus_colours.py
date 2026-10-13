"""Bus colours stated in the conventions (the maintainer, 2026-09-28).

A bus carries a colour NAME, `color`, the same field a channel has: the
model writes it when the conventions state one ("FX busses are purple"),
leaves it null when they do not, and code maps it to the desk's 1..18
index -- apply writes `/bus/{n}/col`, step 04's chip is painted with it,
and a name the desk lacks is verify's `bus.colour-not-writable`.

Built on the frozen `tests/fixtures/touringband.plan.json`, never on a
bundle under `examples/` (CLAUDE.md, "A bundle under examples/ is a
living example").
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import apply, plan_compat, plan_schema, schema_check
from atoo.apply import apply_plan
from atoo.verify_plan import SEVERITY_WARNING, verify_plan
from atoo.webui import _bus_display
from tests.test_apply import FakeConsole, _seed_all

FIXTURE = Path(__file__).parent / "fixtures" / "touringband.plan.json"
BUS_CODE = "bus.colour-not-writable"


@pytest.fixture
def plan():
    plan = json.loads(FIXTURE.read_text())
    for bus in plan["busses"].values():
        bus.pop("col", None)
        bus.pop("color", None)
    return plan


def _two_busses(plan):
    names = sorted(plan["busses"], key=lambda n: plan["busses"][n]["index"])
    return names[0], names[1]


def _bus_col_targets(plan):
    targets, _ = apply._build_write_targets(plan, set_fader_levels=False)
    return {t.address: t.compute_value(None) for t in targets
            if t.address.startswith("/bus/") and t.address.endswith("/col")}


def test_a_bus_colour_name_is_valid_in_the_plan_and_generation_schemas(plan):
    first, _ = _two_busses(plan)
    plan["busses"][first]["color"] = "Purple"
    assert schema_check.validate(plan_compat.normalise_plan(plan), plan_schema.PLAN_SCHEMA) == []
    bus = {"destination": {"type": "main", "index": 1}, "color": "Purple"}
    assert schema_check.validate(bus, plan_schema.BUS_SCHEMA) == []
    assert schema_check.validate({**bus, "color": 12}, plan_schema.BUS_SCHEMA) != []


def test_a_bus_colour_is_stated_not_inferred():
    """The maintainer's decision: stated in the conventions, never decided. The
    `inferred` marker cannot name it."""
    assert "color" not in plan_schema.INFERABLE_FIELDS["bus"]
    prose = " ".join(plan_schema.schema_section().split())
    assert "color colour name ONLY if stated for this bus or its type" in prose
    assert "(a category's = its channels' colour); else null." in prose


def test_bus_colour_names_map_to_the_desk_index_and_apply_writes_them(plan):
    first, second = _two_busses(plan)
    plan["busses"][first]["color"] = "Purple"   # 12
    plan["busses"][second]["color"] = "white"   # 18 -- forgiving, like a channel's
    i1, i2 = plan["busses"][first]["index"], plan["busses"][second]["index"]
    assert _bus_col_targets(plan) == {f"/bus/{i1}/col": 12, f"/bus/{i2}/col": 18}

    console = FakeConsole(_seed_all(plan) | {f"/bus/{i1}/col": (-1, "i"), f"/bus/{i2}/col": (-1, "i")})
    result = apply_plan(plan, console, dry_run=False)
    written = {w.address: w.intended_value for w in result.writes if w.address.endswith("/col")
               and w.address.startswith("/bus/")}
    assert written == {f"/bus/{i1}/col": 12, f"/bus/{i2}/col": 18}
    assert console.state[f"/bus/{i1}/col"][0] == 12


def test_an_explicit_bus_col_beats_the_name(plan):
    first, _ = _two_busses(plan)
    plan["busses"][first]["color"] = "Red"   # would be 9
    plan["busses"][first]["col"] = 3
    idx = plan["busses"][first]["index"]
    assert _bus_col_targets(plan) == {f"/bus/{idx}/col": 3}


def test_an_unknown_bus_colour_is_reported_like_a_channels_and_not_written(plan):
    first, second = _two_busses(plan)
    plan["busses"][first]["color"] = "Gold"
    plan["busses"][second]["color"] = "Gold"
    assert _bus_col_targets(plan) == {}

    hits = [f for f in verify_plan(plan).findings if f.code == BUS_CODE]
    assert len(hits) == 1, "one finding for the plan, as for channels"
    hit = hits[0]
    assert hit.severity == SEVERITY_WARNING, "a colour must not block an apply"
    assert hit.where == "plan"
    assert "2 bus(ses)" in hit.message and "Gold" in hit.message
    assert first in hit.message and second in hit.message
    assert "Amber" in hit.message, "the finding lists what IS available"
    assert "strip.colour-not-writable" not in {f.code for f in verify_plan(plan).findings}


def test_a_known_bus_colour_or_an_explicit_col_draws_no_finding(plan):
    first, second = _two_busses(plan)
    plan["busses"][first]["color"] = "Purple"
    plan["busses"][second]["color"] = "Gold"
    plan["busses"][second]["col"] = 11
    assert BUS_CODE not in {f.code for f in verify_plan(plan).findings}


def test_an_old_plan_with_col_or_no_colour_loads_and_applies_unchanged(plan):
    """A plan from before bus `color` existed: `col` alone, or nothing."""
    first, _ = _two_busses(plan)
    assert schema_check.validate(plan_compat.normalise_plan(plan), plan_schema.PLAN_SCHEMA) == []
    assert _bus_col_targets(plan) == {}, "no colour stated, nothing written"
    assert BUS_CODE not in {f.code for f in verify_plan(plan).findings}

    old = copy.deepcopy(plan)
    old["busses"][first]["col"] = 13
    assert schema_check.validate(plan_compat.normalise_plan(old), plan_schema.PLAN_SCHEMA) == []
    assert _bus_col_targets(old) == {f"/bus/{old['busses'][first]['index']}/col": 13}


def test_bus_display_carries_the_colour_the_name_maps_to(plan):
    first, second = _two_busses(plan)
    names = list(plan["busses"])
    third = next(n for n in names if n not in (first, second))
    plan["busses"][first]["color"] = "Purple"
    plan["busses"][second]["color"] = "Gold"
    display = _bus_display(plan)
    assert display[first]["colour"] == {"index": 12, "name": "Purple", "stated": "Purple"}
    # The shape a channel's unwritable colour takes: the chip's tooltip
    # says it is not a desk colour.
    assert display[second]["colour"] == {"index": None, "name": None, "stated": "Gold"}
    assert display[third]["colour"] is None




def test_a_retired_bus_colour_name_is_written_and_announced(plan):
    """"Magenta" was Atoo's word for the desk's Pink (11) until A24.
    A bus still gets 11, and verify says so at INFO, under the bus code."""
    first, _ = _two_busses(plan)
    plan["busses"][first]["color"] = "Magenta"
    idx = plan["busses"][first]["index"]
    assert _bus_col_targets(plan) == {f"/bus/{idx}/col": 11}
    findings = verify_plan(plan).findings
    assert BUS_CODE not in {f.code for f in findings}
    hit = next(f for f in findings if f.code == "bus.colour-alias")
    assert hit.severity == "info"
    assert "'Magenta' is the desk's Pink (11)" in hit.message and first in hit.message
    assert _bus_display(plan)[first]["colour"] == {"index": 11, "name": "Pink", "stated": "Magenta"}
