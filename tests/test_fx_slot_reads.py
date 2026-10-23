"""A preview does not ask for the plan's parameters under an FX slot that holds another model.

On a WING Rack whose FX slot 5 held NONE, a Preview of a show with a Vox Verb in
that slot asked for the plan's V-REV parameters one by one (`/fx/5/pdel`, `dcy`,
`lmult`, ...). They do not exist on the desk until the model is set, so none
answered, each cost its full timeout and retries, and the Preview took 23 s
against the Compact's 4.7. The apply never read them that way: before it
changes a selector it asks the desk which leaves are there now. The preview does
the same, so it does not ask for what the desk does not hold, says so at INFO,
and the apply still writes the model first and then every parameter.

Every assertion runs on the Compact, Full and Rack fakes, and with the reset off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import initialize as init
from atoo.apply import apply_plan
from tests.snap_desk import SnapDesk
from tests.test_combined_preview_read import _desk_for, _wired

PLAN = json.loads((Path(__file__).resolve().parent / "fixtures" / "watch-build.plan.json").read_text())
MODELS = ["wing-compact", "wing-full", "wing-rack"]
SLOT = "/fx/5"


def _slot_desk(model, *, holds: str, keep: tuple[str, ...] = ()) -> SnapDesk:
    """A desk whose FX slot 5 holds `holds` and has only the parameters in `keep`."""
    desk = _desk_for(model)
    for address in [a for a in desk.values if a.startswith(SLOT + "/")]:
        if address != SLOT + "/mdl" and address.rsplit("/", 1)[-1] not in keep:
            desk.values.pop(address)
    desk.values[SLOT + "/mdl"] = holds
    return desk


def _plan_slot_params() -> set[str]:
    return {a for a in _plan_targets() if a.startswith(SLOT + "/") and not a.endswith("/mdl")}


def _plan_targets() -> set[str]:
    from atoo.apply import _build_write_targets

    targets, _ = _build_write_targets(PLAN, True)
    return {t.address for t in targets}


def _preview(model, desk, *, initialize=True):
    silent = _plan_slot_params() - set(desk.values)
    with _wired(desk, window=8, timeout=0.2, silent=silent) as (console, udp):
        result = apply_plan(PLAN, console, dry_run=True, full_apply=True,
                            initialize=initialize, init_model=model)
    return result, udp


@pytest.mark.parametrize("initialize", [True, False])
@pytest.mark.parametrize("model", MODELS)
def test_a_slot_that_holds_none_is_not_asked_for_the_plans_parameters(model, initialize):
    params = _plan_slot_params()
    assert len(params) >= 5
    result, udp = _preview(model, _slot_desk(model, holds="NONE"), initialize=initialize)
    asked = {address for address, _ in udp.requests}
    assert not asked & params
    [line] = [w for w in result.warnings if w.startswith("INFO the preview read the desk")]
    assert "did not answer" not in line


@pytest.mark.parametrize("model", MODELS)
def test_it_says_what_it_did_not_read_and_why(model):
    result, _ = _preview(model, _slot_desk(model, holds="NONE"))
    [note] = [w for w in result.warnings if "were not read: the desk holds" in w and "/fx/5" in w]
    assert note.startswith("INFO ") and "/fx/5" in note
    assert "holds NONE in /fx/5/mdl and the plan sets V-REV" in note
    assert "writes it first and then each of them" in note
    count = int(note.split()[1].replace(",", ""))
    assert count == len(_plan_slot_params())


@pytest.mark.parametrize("model", MODELS)
def test_the_preview_still_shows_each_of_them_as_a_change(model):
    result, _ = _preview(model, _slot_desk(model, holds="NONE"))
    rows = {r.address: r for r in result.writes if r.address in _plan_slot_params()}
    assert set(rows) == _plan_slot_params()
    for row in rows.values():
        assert row.prior_value is None and row.would_change
        assert row.forced_by == SLOT + "/mdl"


@pytest.mark.parametrize("model", MODELS)
def test_a_request_count_in_the_line_still_equals_what_the_desk_received(model):
    from tests.test_preview_read_stats import assert_line_equals_what_the_desk_received

    result, udp = _preview(model, _slot_desk(model, holds="NONE"))
    [line] = [w for w in result.warnings if w.startswith("INFO the preview read the desk")]
    assert_line_equals_what_the_desk_received(line, udp)


@pytest.mark.parametrize("model", MODELS)
def test_a_slot_that_holds_another_model_is_read_only_where_the_desk_has_the_leaf(model):
    params = sorted(_plan_slot_params())
    desk = _slot_desk(model, holds="PLATE", keep=tuple(p.rsplit("/", 1)[-1] for p in params))
    present = {p for p in params if p in desk.values}
    assert present and len(present) < len(params)
    result, udp = _preview(model, desk)
    asked = {address for address, _ in udp.requests}
    assert present <= asked
    assert not asked & (set(params) - present)
    [note] = [w for w in result.warnings if "were not read: the desk holds PLATE" in w and "/fx/5" in w]
    assert int(note.split()[1]) == len(params) - len(present)


@pytest.mark.parametrize("model", MODELS)
def test_a_slot_that_already_holds_the_plans_model_is_read_in_full(model):
    desk = _desk_for(model)
    params = sorted(_plan_slot_params())
    for address in params:
        desk.values.setdefault(address, 0.0 if not address.endswith(("out", "trans")) else "FRONT")
    desk.values[SLOT + "/mdl"] = "V-REV"
    result, udp = _preview(model, desk)
    assert not [w for w in result.warnings if "were not read" in w and "/fx/5" in w]


@pytest.mark.parametrize("model", MODELS)
def test_the_apply_writes_the_model_first_and_then_every_parameter(model):
    """A skipped read must never become a skipped write."""
    desk = _slot_desk(model, holds="NONE")
    with _wired(desk, window=8, timeout=0.2) as (console, udp):
        result = apply_plan(PLAN, console, dry_run=False, full_apply=True, initialize=True,
                            init_model=model)
    assert not result.aborted
    written = [address for address, _ in desk.writes]
    assert desk.values[SLOT + "/mdl"] == "V-REV"
    at = written.index(SLOT + "/mdl")
    for address in _plan_slot_params():
        assert address in written and written.index(address) > at, address


@pytest.mark.parametrize("model", ["wing-compact", "wing-full"])
def test_the_reset_does_not_read_leaves_it_will_skip_as_under_another_model(model, monkeypatch):
    """A leaf the reset skips whatever the desk holds (under a selector the plan sets to
    another model, or held by one the plan leaves on) is never read: its value is never used."""
    seen = {}
    real = init.read_desk

    def recording(console, wanted, **kw):
        seen["wanted"] = list(wanted)
        return real(console, wanted, **kw)

    monkeypatch.setattr(init, "read_desk", recording)
    result, _ = _preview(model, _slot_desk(model, holds="NONE"))
    capture = init.load_capture(model)
    [line] = [w for w in result.warnings if w.startswith("INFO reset to initialized")]
    assert "under a selector the plan sets to another model" in line
    import re

    other = int(re.search(r"([\d,]+) under a selector the plan sets to another model", line)
                .group(1).replace(",", ""))
    mono = re.search(r"([\d,]+) a mono bus's width", line)
    skipped = other + (int(mono.group(1).replace(",", "")) if mono else 0)
    assert skipped > 0
    # The reset's own read holds neither: what it asked for is what it considers, less what
    # the plan writes itself and less what it skips without a value.
    run_free = sum(1 for leaf in capture.leaves if init.skip_rule(leaf.address) is None
                   and leaf.value_type is not None)
    assert len(seen["wanted"]) <= run_free - skipped
