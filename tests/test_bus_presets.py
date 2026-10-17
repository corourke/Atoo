"""Bus presets and the FX engines they load -- an earlier change.

The maintainer's decision (2026-10-12): effects on FX busses come from bus
presets saved on the desk. These tests freeze what they need: the two
`.bus` files in `tests/fixtures/channel_presets/` (copies of the
maintainer's own, `tests/fixtures/README.md`) and a plan built in the
test from `tests/fixtures/preset-test.plan.json`.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

from atoo import apply, bus_presets, fx_engines, preset_expand, undo
from atoo.presets import PresetLibrary, load_bus_preset
from atoo.verify_plan import verify_plan

sys.path.insert(0, str(Path(__file__).parent))
from test_apply import FakeConsole  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PRESETS = FIXTURES / "channel_presets"
REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def library(tmp_path):
    """The two bus presets alone, in a library of their own."""
    for name in ("FX Vox Verb.bus", "FX Snare Verb.bus"):
        shutil.copy(PRESETS / name, tmp_path / name)
    return PresetLibrary(tmp_path)


def fx_plan(**presets) -> dict:
    """preset-test's plan, its busses naming bus presets: `{bus: preset}`."""
    plan = json.loads((FIXTURES / "preset-test.plan.json").read_text())
    for bus, preset in presets.items():
        plan["busses"][bus]["preset"] = preset
    return plan


def expanded(library, **presets) -> dict:
    plan = fx_plan(**presets)
    preset_expand.expand_plan(plan, library)
    return plan


def codes(result, severity=None):
    return [f.code for f in result.findings if severity is None or f.severity == severity]


# -- the library ---------------------------------------------------------------

def test_a_bus_preset_carries_the_bus_processing_and_the_effect_it_inserts():
    preset = load_bus_preset(PRESETS / "FX Vox Verb.bus")
    assert preset.name == "Vox Verb"
    assert not preset.warnings
    # Processing only: never the width, routing, level, insert or identity.
    assert "dyn.thr" in preset.parameters and "eq.6g" in preset.parameters
    assert not [k for k in preset.parameters
                if k.split(".")[0] in ("busmono", "main", "send", "bus_feed", "preins",
                                       "postins", "fdr", "name", "mute", "in")]
    (insert,) = preset.inserts
    assert (insert.point, insert.model, insert.saved_engine, insert.saved_on) == (
        "preins", "V-REV", 5, False)
    assert insert.parameters["dcy"] == 1.5 and "mdl" not in insert.parameters


def test_bus_presets_are_a_name_space_of_their_own(library):
    assert [b.name for b in library.bus_presets()] == ["Snare Verb", "Vox Verb"]
    assert library.bus_get("vox verb").inserts[0].model == "V-REV"
    assert library.names() == []   # no `.chn`: a bus preset is not a channel preset


# -- the engines ---------------------------------------------------------------

def test_reverbs_and_delays_are_offered_by_engines_1_to_8_only():
    for model in ("V-REV", "HALL", "PLATE", "GATED", "ST-DL", "TAPE-DL"):
        assert fx_engines.engines_for(model) == list(range(1, 9)), model
    assert fx_engines.engines_for("LIMITER") == list(range(1, 17))
    assert not fx_engines.is_known_model("NONE")
    assert not fx_engines.is_known_model("NO-SUCH-VERB")


def test_allocation_keeps_the_saved_engine_moves_a_clash_and_saves_1_to_8():
    R = fx_engines.EngineRequest
    got = fx_engines.allocate([
        R("a", "bus A", "HALL", 5),        # takes 5 in pass 2 -- but B saved 5 too
        R("b", "bus B", "V-REV", 5),
        R("c", "bus C", "LIMITER", None),  # any engine: goes to 9-16
        R("d", "bus D", "PLATE", 12),      # 12 cannot hold a reverb
    ])
    assert got["a"].engine == 5 and "saved from" in got["a"].reason
    assert got["b"].engine == 1 and "already uses" in got["b"].reason
    assert got["c"].engine == 9
    assert got["d"].engine == 2 and "cannot hold PLATE" in got["d"].reason


def test_more_reverbs_than_engines_1_to_8_leaves_one_without():
    R = fx_engines.EngineRequest
    got = fx_engines.allocate([R(n, f"bus {n}", "HALL", None) for n in range(9)])
    assert [got[n].engine for n in range(9)] == [1, 2, 3, 4, 5, 6, 7, 8, None]
    assert "already in use" in got[8].reason


def test_a_parameter_the_map_types_one_way_takes_the_map_type():
    assert fx_engines.coerce_param("pdel", 20.0) == (20, None, True)
    assert fx_engines.coerce_param("hc", 12030) == (12030.0, None, True)
    # Not in the map (V-REV was never loaded when the desk was walked):
    # the saved value's own type.
    assert fx_engines.coerce_param("trans", False) == (0, None, False)
    assert fx_engines.coerce_param("out", "FRONT") == ("FRONT", None, False)
    # A list the desk spells: a choice it does not have is refused.
    value, why, _ = fx_engines.coerce_param("hq", "MEDIUM")
    assert value is None and "LOW, HIGH" in why


# -- build: expansion and allocation -------------------------------------------

def test_build_expands_the_bus_preset_and_allocates_its_engine(library):
    plan = fx_plan(**{"VOX Reverb": "Vox Verb", "Snare Verb": "Snare Verb"})
    findings = preset_expand.expand_plan(plan, library)
    vox = plan["busses"]["VOX Reverb"]["preset_values"]
    assert vox["file"] == "FX Vox Verb.bus"
    assert vox["leaves"]["dyn/ratio"] == "3.0"     # the desk's list token
    assert "busmono" not in vox["leaves"]
    (insert,) = vox["inserts"]
    assert (insert["model"], insert["engine"], insert["saved_on"]) == ("V-REV", 5, False)
    assert plan["busses"]["Snare Verb"]["preset_values"]["inserts"][0]["engine"] == 8
    by_code = {}
    for f in findings:
        by_code.setdefault(f.code, []).append(f.message)
    assert len(by_code["fx.engine-allocated"]) == 2
    assert any("FX5" in m and "saved from" in m for m in by_code["fx.engine-allocated"])
    # Saved bypassed: switched on, and said.
    (switched,) = by_code["fx.insert-switched-on"]
    assert "VOX Reverb" in switched and "bypassed" in switched
    assert any("mod, out, trans" in m for m in by_code["fx.parameter-typed-from-value"])


def test_two_busses_on_one_preset_get_two_engines(library):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb", "INST Reverb": "Vox Verb"})
    engines = [plan["busses"][b]["preset_values"]["inserts"][0]["engine"]
               for b in ("VOX Reverb", "INST Reverb")]
    assert engines == [5, 1]
    assert not codes(verify_plan(plan, presets=library), "error")


def test_a_bus_naming_no_preset_carries_none_and_an_old_one_is_dropped(library):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    plan["busses"]["VOX Reverb"]["preset"] = None
    preset_expand.expand_plan(plan, library)
    assert "preset_values" not in plan["busses"]["VOX Reverb"]


# -- verify ---------------------------------------------------------------------

def test_verify_reports_the_inserts_and_no_error(library):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    result = verify_plan(plan, presets=library)
    assert not codes(result, "error")
    (summary,) = [f for f in result.findings if f.code == "fx.inserts"]
    assert "VOX Reverb: V-REV on FX5 (saved bypassed, switched on)" in summary.message


@pytest.mark.parametrize("mutate, code", [
    (lambda i: i.update(engine=12), "fx.engine-not-offered"),   # a reverb on 9-16
    (lambda i: i.update(engine=17), "fx.engine-not-offered"),
    (lambda i: i.update(engine=None), "fx.no-engine"),
    (lambda i: i.update(model="NO-SUCH-VERB"), "fx.unknown-model"),
    (lambda i: i["parameters"].update(hq="MEDIUM"), "fx.value-not-offered"),
])
def test_verify_refuses_an_effect_the_desk_cannot_hold(library, mutate, code):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    mutate(plan["busses"]["VOX Reverb"]["preset_values"]["inserts"][0])
    assert code in codes(verify_plan(plan, presets=library), "error")


def test_verify_refuses_two_strips_on_one_engine(library):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb", "Snare Verb": "Snare Verb"})
    plan["busses"]["Snare Verb"]["preset_values"]["inserts"][0]["engine"] = 5
    result = verify_plan(plan, presets=library)
    assert "fx.engine-shared" in codes(result, "error")


def test_verify_warns_on_a_bus_preset_it_cannot_find_or_did_not_expand(library):
    plan = fx_plan(**{"VOX Reverb": "Vox Verbb"})
    preset_expand.expand_plan(plan, library)
    assert "preset.unknown" in codes(verify_plan(plan, presets=library), "warning")
    plan = fx_plan(**{"VOX Reverb": "Vox Verb"})
    assert "preset.not-expanded" in codes(verify_plan(plan, presets=library), "warning")
    assert "preset.no-library" in codes(verify_plan(plan, presets=None), "warning")


# -- apply ----------------------------------------------------------------------

def _bus_fx_targets(plan, bus_index):
    targets, warnings = apply._build_write_targets(plan, True)
    mine = [t for t in targets if t.address.startswith(("/fx/", f"/bus/{bus_index}/"))
            and t.stage == apply.STAGE_PROCESSING]
    return mine, warnings


def test_apply_writes_the_model_its_parameters_the_processing_then_the_insert(library):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    targets, warnings = _bus_fx_targets(plan, 9)
    addresses = [t.address for t in targets]
    assert addresses[0] == "/fx/5/mdl"
    assert targets[0].compute_value(None) == "V-REV"
    params = [a for a in addresses if a.startswith("/fx/5/") and a != "/fx/5/mdl"]
    assert len(params) == 10 and max(map(addresses.index, params)) < addresses.index("/bus/9/eq/mdl")
    assert addresses[-2:] == ["/bus/9/preins/ins", "/bus/9/preins/on"]
    assert targets[-2].compute_value(None) == "FX5"
    # Saved bypassed, written ON.
    assert targets[-1].compute_value(None) == 1
    types = {t.address: t.value_type for t in targets}
    assert types["/fx/5/pdel"] == "i" and types["/fx/5/dcy"] == "f" and types["/fx/5/out"] == "s"
    assert not [w for w in warnings if "bus 9" in w]


def test_apply_writes_no_effect_and_no_insert_for_an_engine_that_cannot_hold_it(library):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    plan["busses"]["VOX Reverb"]["preset_values"]["inserts"][0]["engine"] = 12
    targets, warnings = _bus_fx_targets(plan, 9)
    assert not [t for t in targets if t.address.startswith("/fx/") or "preins" in t.address]
    assert any("V-REV has no usable engine" in w for w in warnings)


def _desk_for(plan) -> FakeConsole:
    """A desk answering every address the plan writes, from a blank: FX5
    empty, every insert off."""
    targets, _ = apply._build_write_targets(plan, True)
    blank = {"s": "NONE", "i": 0, "f": 0.0}
    state = {t.address: (blank[t.value_type], t.value_type) for t in targets}
    state["/bus/9/preins/ins"] = ("NONE", "s")
    return FakeConsole(state)


def test_apply_reads_back_every_fx_write_and_undo_puts_the_model_back_first(library, tmp_path):
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    desk = _desk_for(plan)
    journal_path = tmp_path / "journal.json"
    result = apply.apply_plan(plan, desk, dry_run=False, journal_path=str(journal_path))
    fx = [r for r in result.writes if r.address.startswith("/fx/5/")
          or r.address.startswith("/bus/9/preins/")]
    assert fx and all(r.status in ("match", "skipped_no_change") for r in fx), \
        [(r.address, r.status) for r in fx if r.status not in ("match", "skipped_no_change")]
    assert desk.state["/fx/5/mdl"][0] == "V-REV"
    assert desk.state["/bus/9/preins/ins"][0] == "FX5"
    assert desk.state["/bus/9/preins/on"][0] == 1
    # Parameters whose baseline matched are still written: the model change
    # forces them (they were read under the old model).
    pdel = next(r for r in result.writes if r.address == "/fx/5/pdel")
    assert pdel.forced_by == "/fx/5/mdl" and pdel.status == "match"

    journal = json.loads(journal_path.read_text())
    undone = undo.undo_from_journal(journal, desk, dry_run=False)
    assert desk.state["/fx/5/mdl"][0] == "NONE"
    assert desk.state["/bus/9/preins/ins"][0] == "NONE"
    assert desk.state["/bus/9/preins/on"][0] == 0
    order = [step.address for step in undone.steps]
    fx_rows = [a for a in order if a.startswith("/fx/5/")]
    # The model first: the parameters it restores exist only under it.
    assert fx_rows[0] == "/fx/5/mdl", fx_rows[:3]


def test_amend_owns_the_engine_a_new_bus_inserts(library):
    from atoo import amend

    applied = expanded(library)
    amended = expanded(library, **{"VOX Reverb": "Vox Verb"})
    applied["busses"].pop("VOX Reverb")
    scope = amend.AmendScope()
    warnings, infos = [], []
    amend._plan_new_busses(applied, amended, scope, [], warnings, infos)
    assert scope.why("/fx/5/mdl") and scope.why("/bus/9/preins/on")
    assert any("FX5 was judged free" in i for i in infos)


def test_amend_does_not_load_an_engine_a_bus_on_the_desk_inserts(library):
    from atoo import amend

    applied = expanded(library, **{"Snare Verb": "Vox Verb"})          # FX5
    amended = expanded(library, **{"Snare Verb": "Vox Verb", "VOX Reverb": "Vox Verb"})
    amended["busses"]["VOX Reverb"]["preset_values"]["inserts"][0]["engine"] = 5
    applied["busses"].pop("VOX Reverb")
    scope = amend.AmendScope()
    warnings = []
    amend._plan_new_busses(applied, amended, scope, [], warnings, [])
    assert not scope.why("/fx/5/mdl")
    assert any("already uses" in w for w in warnings)
    assert amended["busses"]["VOX Reverb"]["preset_values"]["inserts"][0]["engine"] is None


def test_patch_gives_a_new_bus_an_engine_the_desk_leaves_free(library):
    plan = expanded(library, **{"Snare Verb": "Vox Verb"})            # FX5 on the desk
    plan["busses"]["VOX Reverb"]["preset"] = "Vox Verb"
    findings = bus_presets.expand_added_busses(plan, ["VOX Reverb"], library)
    assert plan["busses"]["VOX Reverb"]["preset_values"]["inserts"][0]["engine"] == 1
    assert plan["busses"]["Snare Verb"]["preset_values"]["inserts"][0]["engine"] == 5
    assert any(f.code == "fx.engine-allocated" and "already uses" in f.message for f in findings)


def test_a_plan_with_bus_preset_values_is_a_valid_plan(library):
    from atoo import plan_schema
    from atoo.schema_check import validate

    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    # Only this bus: the fixture predates other schema changes.
    assert not [e for e in validate(copy.deepcopy(plan), plan_schema.PLAN_SCHEMA)
                if "VOX Reverb" in e]
    plan["busses"]["VOX Reverb"]["preset_values"]["inserts"][0]["nonsense"] = 1
    assert [e for e in validate(copy.deepcopy(plan), plan_schema.PLAN_SCHEMA)
            if "VOX Reverb" in e]


def test_parameters_that_do_not_exist_under_the_old_model_are_still_written(library, tmp_path):
    """On a desk, an empty engine has none of V-REV's parameters: they are
    read as absent, written after the model anyway, and undo -- putting
    the model back -- takes them away again rather than restoring them."""
    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    seeded = _desk_for(plan)

    class EmptyEngineDesk(FakeConsole):
        """V-REV's parameters appear, with their types, when the model lands."""

        def set_node(self, address, command):
            if address == "/fx/5" and command == "mdl=V-REV":
                self.state.update({a: v for a, v in seeded.state.items()
                                   if a.startswith("/fx/5/")})
            return super().set_node(address, command)

    desk = EmptyEngineDesk({a: v for a, v in seeded.state.items()
                            if not a.startswith("/fx/5/") or a == "/fx/5/mdl"})
    journal_path = tmp_path / "journal.json"
    result = apply.apply_plan(plan, desk, dry_run=False, journal_path=str(journal_path))
    params = [r for r in result.writes if r.address.startswith("/fx/5/") and r.address != "/fx/5/mdl"]
    assert len(params) == 10
    assert all(r.status == "match" and r.prior_value is None and r.forced_by == "/fx/5/mdl"
               for r in params), [(r.address, r.status, r.prior_value) for r in params]
    undone = undo.undo_from_journal(json.loads(journal_path.read_text()), desk, dry_run=False)
    assert desk.state["/fx/5/mdl"][0] == "NONE"
    assert not undone.aborted if hasattr(undone, "aborted") else True


def test_a_full_apply_does_not_reset_the_engine_the_plan_loads(library):
    """Initialize (FR-X.3f) resets every engine to the capture -- except
    one the plan writes: its model is written once, as the plan's, and the
    capture's parameters for another model are not put under it."""
    from test_initialize import desk_with

    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    desk = desk_with({"/fx/5/mdl": "HALL", "/fx/6/mdl": "PLATE"})
    result = apply.apply_plan(plan, desk, dry_run=False, full_apply=True, initialize=True,
                              init_model="wing-compact")
    rows = [r for r in result.writes if r.address == "/fx/5/mdl"]
    assert [(r.intended_value, r.status) for r in rows] == [("V-REV", "match")]
    assert desk.values["/fx/5/mdl"] == "V-REV"
    assert desk.values["/fx/6/mdl"] == "NONE"     # an engine the plan does not use: reset
    assert desk.values["/bus/9/preins/ins"] == "FX5" and desk.values["/bus/9/preins/on"] == 1


# -- audit and Watch: CV015 ---------------------------------------------------

def _desk_as_applied(plan) -> dict:
    """VOX Reverb (bus 9) named, its insert on FX5, FX5 holding V-REV."""
    return {"/bus/9/name": "VOX Reverb", "/bus/9/preins/ins": "FX5",
            "/bus/9/preins/on": 1, "/bus/9/postins/ins": "NONE", "/bus/9/postins/on": 0,
            "/fx/5/mdl": "V-REV"}


@pytest.mark.parametrize("change, words", [
    ({"/bus/9/preins/on": 0}, ["switched off", "bypassed"]),
    ({"/bus/9/preins/ins": "FX6"}, ["names FX6, not FX5"]),
    ({"/fx/5/mdl": "HALL"}, ["FX5 holds HALL, not V-REV"]),
])
def test_an_fx_bus_not_as_planned_is_a_warning(library, change, words):
    from atoo.audit import ConsoleState, diff_against_plan

    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    assert [f for f in diff_against_plan(ConsoleState(_desk_as_applied(plan)), plan)
            if f.rule_id == "CV015"] == []
    found = [f for f in diff_against_plan(ConsoleState({**_desk_as_applied(plan), **change}), plan)
             if f.rule_id == "CV015"]
    assert [f.severity.value for f in found] == ["warning"]
    for word in words:
        assert word in found[0].message


def test_sp_e003_stands_down_on_a_planned_fx_bus_and_sp_cv015_says_it(library):
    from atoo.audit import ConsoleState, apply_plan_scope, diff_against_plan, run_audit

    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    state = ConsoleState({**_desk_as_applied(plan), "/bus/9/preins/on": 0})
    structural = run_audit(state)
    assert "E003" in {f.rule_id for f in structural}
    scoped = apply_plan_scope(state, structural, plan)
    assert "E003" not in {f.rule_id for f in scoped.findings}
    assert "CV015" in {f.rule_id for f in diff_against_plan(state, plan)}


def test_watch_adds_the_fx_rule_only_for_a_plan_that_loads_an_effect(library, tmp_path):
    from atoo.audit import plan_watch_rules

    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert "CV015" in [r.id for r in plan_watch_rules(path)]
    path.write_text(json.dumps(fx_plan()))
    # The plan-drift rules (CV016/017) come with any
    # plan; the FX rule only with one that loads an effect.
    assert "CV015" not in [r.id for r in plan_watch_rules(path)]
    path.write_text("{not json")
    assert plan_watch_rules(path) == []


def test_watch_folds_sp_e003_under_the_fx_bus_row(library):
    from atoo.audit import ConsoleState, fx_insert_rule, run_audit
    from atoo.watch import present_findings

    plan = expanded(library, **{"VOX Reverb": "Vox Verb"})
    state = ConsoleState({**_desk_as_applied(plan), "/bus/9/preins/on": 0})
    from atoo.audit import DEFAULT_RULES
    shown = present_findings(run_audit(state, list(DEFAULT_RULES) + [fx_insert_rule(plan)]))
    ids = [f.rule_id for f in shown.alerts]
    assert "CV015" in ids and "E003" not in ids
    assert [f.rule_id for fs in shown.folded.values() for f in fs] == ["E003"]
