"""A bus preset on a MIX bus -- the Horns bus, the maintainer's desk test 13 (2026-10-12).

An earlier change built bus presets for FX busses: a reverb loaded into an engine
and inserted. The starter conventions now give every mix bus the "Mix
Bus" preset too (a compressor, no effect), so the same path must carry a
preset that has processing and no insert: expanded into the plan, written
and read back, verified without an error, and given no engine.

Frozen inputs only: `tests/fixtures/channel_presets/Mix Bus.bus` (a copy
of `starter/presets/Mix Bus.bus`) and the plan in
`tests/fixtures/preset-test.plan.json`, whose bus 8 is a mix bus called
Horns.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from atoo import apply, bus_presets, preset_expand, undo
from atoo.verify_plan import verify_plan

sys.path.insert(0, str(Path(__file__).parent))
from test_apply import FakeConsole  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PRESETS = FIXTURES / "channel_presets"
HORNS = 8           # the fixture plan's Horns mix bus
VOX_REVERB = 9      # its FX bus


@pytest.fixture
def library(tmp_path):
    from atoo.presets import PresetLibrary

    for name in ("Mix Bus.bus", "FX Vox Verb.bus"):
        shutil.copy(PRESETS / name, tmp_path / name)
    return PresetLibrary(tmp_path)


def plan_with(library, **presets) -> tuple[dict, list]:
    plan = json.loads((FIXTURES / "preset-test.plan.json").read_text())
    for bus, preset in presets.items():
        plan["busses"][bus]["preset"] = preset
    findings = preset_expand.expand_plan(plan, library)
    return plan, findings


def codes(findings, severity=None):
    return [f.code for f in findings
            if severity is None or getattr(f.severity, "value", f.severity) == severity]


# -- build ---------------------------------------------------------------------

def test_a_mix_bus_takes_the_preset_processing_and_no_engine(library):
    plan, findings = plan_with(library, Horns="Mix Bus")
    values = plan["busses"]["Horns"]["preset_values"]
    assert values["preset"] == "Mix Bus" and values["file"] == "Mix Bus.bus"
    leaves = values["leaves"]
    # The compressor is what the preset is for.
    assert (leaves["dyn/on"], leaves["dyn/mdl"], leaves["dyn/thr"]) == (1, "COMP", -20.0)
    assert leaves["dyn/ratio"] == "5.0"
    # Never the bus's width, routing, level or name.
    assert not [a for a in leaves if a.split("/")[0] in ("busmono", "main", "fdr", "name", "mute")]
    assert values["inserts"] == []
    assert "fx.engine-allocated" not in codes(findings)
    assert "fx.insert-switched-on" not in codes(findings)
    (summary,) = [f for f in findings if f.code == "preset.bus-expanded"]
    assert "Horns: 'Mix Bus'" in summary.message and "FX" not in summary.message.split(": ", 1)[1]


def test_a_mix_bus_preset_leaves_the_fx_bus_its_engine(library):
    plan, _ = plan_with(library, Horns="Mix Bus", Drums="Mix Bus", **{"VOX Reverb": "Vox Verb"})
    assert plan["busses"]["Horns"]["preset_values"]["inserts"] == []
    assert plan["busses"]["VOX Reverb"]["preset_values"]["inserts"][0]["engine"] == 5


# -- verify --------------------------------------------------------------------

def test_verify_says_what_a_mix_bus_preset_writes_and_raises_nothing(library):
    plan, _ = plan_with(library, Horns="Mix Bus", Vocals="Mix Bus")
    result = verify_plan(plan, presets=library)
    mine = [f for f in result.findings if "Horns" in (f.where or "") or "Vocals" in (f.where or "")]
    assert not [f for f in mine if f.severity in ("error", "warning")], mine
    (summary,) = [f for f in result.findings if f.code == "preset.bus-expanded"]
    assert summary.severity == "info"
    n = len(plan["busses"]["Horns"]["preset_values"]["leaves"])
    assert f"Vocals: 'Mix Bus' ({n})" in summary.message
    assert f"Horns: 'Mix Bus' ({n})" in summary.message
    assert summary.message.startswith("2 bus(ses)")
    # No effect, so no insert line.
    assert "fx.inserts" not in codes(result.findings)


def test_verify_counts_only_the_values_it_will_write(library):
    plan, _ = plan_with(library, Horns="Mix Bus")
    leaves = plan["busses"]["Horns"]["preset_values"]["leaves"]
    n = len(leaves)
    leaves["busmono"] = 1          # off the allow-list: refused, and not counted
    result = verify_plan(plan, presets=library)
    assert "preset.leaf-not-written" in codes(result.findings, "warning")
    (summary,) = [f for f in result.findings if f.code == "preset.bus-expanded"]
    assert f"Horns: 'Mix Bus' ({n})" in summary.message


def test_verify_still_warns_when_a_mix_bus_preset_was_not_expanded(library):
    plan, _ = plan_with(library)
    plan["busses"]["Horns"]["preset"] = "Mix Bus"
    assert "preset.not-expanded" in codes(verify_plan(plan, presets=library).findings, "warning")


# -- apply ---------------------------------------------------------------------

def _bus_targets(plan, index):
    targets, warnings = apply._build_write_targets(plan, True)
    return [t for t in targets if t.address.startswith(f"/bus/{index}/")], targets, warnings


def test_apply_writes_the_compressor_and_no_effect_or_insert(library):
    plan, _ = plan_with(library, Horns="Mix Bus")
    mine, everything, warnings = _bus_targets(plan, HORNS)
    by_address = {t.address: t for t in mine}
    for address, value in (("dyn/on", 1), ("dyn/thr", -20.0), ("dyn/mdl", "COMP"),
                           ("eq/on", 1)):
        target = by_address[f"/bus/{HORNS}/{address}"]
        assert target.stage == apply.STAGE_PROCESSING
        assert target.compute_value(None) == value
        assert "preset Mix Bus" in target.description
    assert not [a for a in by_address if "/preins/" in a or "/postins/" in a]
    assert not [t for t in everything if t.address.startswith("/fx/")]
    assert not [w for w in warnings if f"bus {HORNS}" in w]


def _desk_for(plan) -> FakeConsole:
    targets, _ = apply._build_write_targets(plan, True)
    blank = {"s": "NONE", "i": 0, "f": 0.0}
    return FakeConsole({t.address: (blank[t.value_type], t.value_type) for t in targets})


def test_apply_reads_back_the_mix_bus_preset_and_undo_takes_it_off(library, tmp_path):
    plan, _ = plan_with(library, Horns="Mix Bus")
    desk = _desk_for(plan)
    journal_path = tmp_path / "journal.json"
    result = apply.apply_plan(plan, desk, dry_run=False, journal_path=str(journal_path))
    rows = [r for r in result.writes if "preset Mix Bus" in (r.description or "")]
    assert len(rows) == len(plan["busses"]["Horns"]["preset_values"]["leaves"])
    assert all(r.status in ("match", "skipped_no_change") for r in rows), \
        [(r.address, r.status) for r in rows if r.status not in ("match", "skipped_no_change")]
    assert desk.state[f"/bus/{HORNS}/dyn/thr"][0] == -20.0
    assert desk.state[f"/bus/{HORNS}/dyn/on"][0] == 1

    undo.undo_from_journal(json.loads(journal_path.read_text()), desk, dry_run=False)
    assert desk.state[f"/bus/{HORNS}/dyn/thr"][0] == 0.0
    assert desk.state[f"/bus/{HORNS}/dyn/on"][0] == 0


# -- patch: a change that adds a mix bus --------------------------------------

def test_patch_expands_a_new_mix_bus_preset(library):
    plan, _ = plan_with(library)
    plan["busses"]["Horns"]["preset"] = "Mix Bus"
    findings = bus_presets.expand_added_busses(plan, ["Horns"], library)
    assert plan["busses"]["Horns"]["preset_values"]["leaves"]["dyn/on"] == 1
    assert plan["busses"]["Horns"]["preset_values"]["inserts"] == []
    assert codes(findings) == ["preset.bus-expanded"]


# -- audit and Watch -----------------------------------------------------------

def test_a_mix_bus_preset_adds_no_fx_watch_rule(library, tmp_path):
    from atoo.audit import plan_watch_rules

    plan, _ = plan_with(library, Horns="Mix Bus", Drums="Mix Bus")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert "CV015" not in [r.id for r in plan_watch_rules(path)]
