"""A preview does not ask for a plan value its selector's model does not have.

Not only FX: on a Rack the plan's Vocal preset sets a gate to PSE while the desk
holds GATE, and the PSE-only leaves (`gate/depth`, `fast`, `peak`) do not exist on
the desk until the model is set, so each cost its full timeout. The same holds for
every family a selector governs (`preset_expand.governs`, the table the real apply
forces governed writes by): dynamics, EQ, the filters, the side-chain types, the
delay mode, an FX slot. A node dump says which leaves the desk holds under the model
it holds now; the preview does not ask for the others, shows them as changes with no
prior, says so at INFO, and the apply still writes the model and then each leaf.

Every family the two frozen plans carry is tried, on the Compact, Full and Rack fakes.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from atoo.apply import _build_write_targets, _governing_selectors, apply_plan
from tests.test_combined_preview_read import _desk_for, _wired
from tests.test_preview_read_stats import assert_line_equals_what_the_desk_received

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLANS = {name: json.loads((FIXTURES / name).read_text())
         for name in ("sixpiece_2026-10-02.plan.json", "watch-build.plan.json")}
MODELS = ["wing-compact", "wing-full", "wing-rack"]
OTHER = "ANOTHER-MODEL"


def _family(selector: str) -> str:
    return re.sub(r"/\d+", "/{n}", selector)


def _cases():
    cases = []
    for name, plan in PLANS.items():
        targets, _ = _build_write_targets(plan, True)
        for family in sorted({_family(s) for s in _governing_selectors(targets).values()}):
            cases.append(pytest.param(name, family, id=f"{name.split('.')[0]}:{family}"))
    return cases


def _scenario(model, name, family):
    """A desk whose selector of this family holds another model and lacks the plan's
    leaves it governs; the selector, and the leaves removed."""
    plan = PLANS[name]
    targets, _ = _build_write_targets(plan, True)
    governed = _governing_selectors(targets)
    selector = sorted(s for s in set(governed.values()) if _family(s) == family)[0]
    removed = {a for a, s in governed.items() if s == selector}
    desk = _desk_for(model)
    for address in removed:
        desk.values.pop(address, None)
    desk.values[selector] = OTHER
    return plan, desk, selector, removed


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("name,family", _cases())
def test_a_family_that_holds_another_model_is_not_asked_for_what_it_lacks(model, name, family):
    plan, desk, selector, removed = _scenario(model, name, family)
    assert removed
    with _wired(desk, window=8, timeout=0.2, silent=removed) as (console, udp):
        result = apply_plan(plan, console, dry_run=True, full_apply=True, initialize=True,
                            init_model=model)
    asked = {address for address, _ in udp.requests}
    assert not asked & removed
    notes = [w for w in result.warnings if "were not read: the desk holds" in w
             and f"{OTHER} in {selector}" in w]
    assert len(notes) == 1
    rows = {r.address: r for r in result.writes if r.address in removed}
    assert set(rows) == removed
    for row in rows.values():
        assert row.prior_value is None and row.would_change and row.forced_by == selector
    [line] = [w for w in result.warnings if w.startswith("INFO the preview read the desk")]
    assert_line_equals_what_the_desk_received(line, udp)
    assert "did not answer" not in line


@pytest.mark.parametrize("name,family", _cases())
def test_the_apply_writes_the_selector_and_then_each_leaf_of_the_family(name, family):
    """A skipped read must never become a skipped write."""
    plan, desk, selector, removed = _scenario("wing-compact", name, family)
    with _wired(desk, window=8, timeout=0.2) as (console, udp):
        result = apply_plan(plan, console, dry_run=False, full_apply=True, initialize=True,
                            init_model="wing-compact")
    assert not result.aborted
    written = [address for address, _ in desk.writes]
    assert selector in written
    for address in removed:
        assert address in written and written.index(address) > written.index(selector), address


@pytest.mark.parametrize("model", MODELS)
def test_a_real_run_on_each_model_writes_the_gate_model_and_then_its_leaves(model):
    name = "sixpiece_2026-10-02.plan.json"
    plan, desk, selector, removed = _scenario(model, name, "/ch/{n}/gate/mdl")
    with _wired(desk, window=8, timeout=0.2) as (console, udp):
        apply_plan(plan, console, dry_run=False, full_apply=True, initialize=True,
                   init_model=model)
    written = [address for address, _ in desk.writes]
    assert all(written.index(a) > written.index(selector) for a in removed)


@pytest.mark.parametrize("model", MODELS)
def test_a_rack_like_desk_with_gates_and_an_fx_slot_on_other_models_is_not_slow(model):
    """The Rack's Preview: the Vocal gate holds GATE, the plan sets PSE, and FX slot 5 holds NONE;
    none of the leaves they lack may cost a timeout (at 2 s and 3 tries, one would cost 6 s)."""
    plan = PLANS["watch-build.plan.json"]
    targets, _ = _build_write_targets(plan, True)
    governed = _governing_selectors(targets)
    desk = _desk_for(model)
    removed = set()
    for selector in {s for s in governed.values()
                     if _family(s) in ("/ch/{n}/gate/mdl", "/fx/{n}/mdl")}:
        desk.values[selector] = "NONE" if selector.startswith("/fx/") else OTHER
        for address in [a for a, s in governed.items() if s == selector]:
            desk.values.pop(address, None)
            removed.add(address)
    assert removed
    with _wired(desk, window=8, timeout=2.0, silent=removed) as (console, udp):
        began = time.monotonic()
        result = apply_plan(plan, console, dry_run=True, full_apply=True, initialize=True,
                            init_model=model)
        took = time.monotonic() - began
    assert took < 5.0
    assert not {a for a, _ in udp.requests} & removed
    [line] = [w for w in result.warnings if w.startswith("INFO the preview read the desk")]
    assert "did not answer" not in line
