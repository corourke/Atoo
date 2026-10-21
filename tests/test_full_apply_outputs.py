"""A full apply disconnects the panel outputs the plan does not patch.

On a WING Compact, after a full apply of the Demo, local outputs 3-8 were
still patched to busses 5, 7, 9 and 11 and to Mains 1 and 2, and the audit
called them leftovers from an earlier apply and warned that the Drums and
Vocals busses were patched on their left side only. They were not leftovers:
the desk ships that way, so the reset to the initialized state put it back,
and the plan, which patches the Main to local outputs 1 and 2 only, never
mentioned them.

A full apply makes the desk the plan, as it already does for every strip the
plan does not build, so it now disconnects every output socket on the model's
own panel that no bus, Main or Matrix of the plan is patched to, and says so.
Patch and amend, which touch only what they own, never do. The desks are
`tests/snap_desk`'s, built from the packaged initialized capture, and the
show is the packaged Demo. Nothing here reads `examples/`.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from atoo import cli, console as console_module, firstrun
from atoo import initialize as init
from atoo.apply import (
    _build_write_targets,
    apply_plan,
    full_apply_notes,
    full_apply_targets,
    undeclared_outputs,
)
from tests.snap_desk import PairedSnapDesk

DEMO_PLAN = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME / "plan.json"
MODEL = "wing-compact"
HOST = "198.51.100.9"


def demo_plan() -> dict:
    return json.loads(DEMO_PLAN.read_text(encoding="utf-8"))


def fresh_desk() -> PairedSnapDesk:
    """An initialized Compact: local outputs 3-8 patched as the desk ships."""
    return PairedSnapDesk({leaf.address: leaf.value for leaf in init.load_capture(MODEL).leaves})


def out_grp(desk, group: str, n: int):
    return desk.values[f"/io/out/{group}/{n}/grp"]


def full_apply(plan: dict, desk, *, dry_run: bool = False, initialize: bool = True, **kwargs):
    return apply_plan(copy.deepcopy(plan), desk, dry_run=dry_run, full_apply=True,
                      initialize=initialize, init_model=MODEL, **kwargs)


def output_notes(result) -> list[str]:
    return [w for w in result.warnings if "output" in w and w.startswith("INFO")]


# ---- what the plan leaves unpatched --------------------------------------


def test_the_demo_patches_local_outputs_1_and_2_so_3_to_8_are_undeclared():
    assert undeclared_outputs(demo_plan(), MODEL) == {"LCL": [3, 4, 5, 6, 7, 8]}


def test_a_full_size_console_has_aux_outputs_on_its_panel_and_a_compact_does_not():
    plan = demo_plan()
    assert set(undeclared_outputs(plan, "wing-full")) == {"LCL", "AUX"}
    assert "AUX" not in undeclared_outputs(plan, MODEL)


def test_the_plans_own_model_is_used_when_the_desk_is_not_named():
    assert undeclared_outputs(demo_plan(), None) == {"LCL": [3, 4, 5, 6, 7, 8]}


def test_an_unknown_model_disconnects_nothing():
    plan = demo_plan()
    plan["meta"] = {**plan["meta"], "console_model": "wing-unheard-of"}
    assert undeclared_outputs(plan, None) == {}
    assert not [t for t in full_apply_targets(plan) if t.address.startswith("/io/out/")]


def test_a_plan_that_patches_no_output_leaves_every_panel_socket_undeclared():
    plan = demo_plan()
    plan["outputs"] = {}
    assert undeclared_outputs(plan, MODEL) == {"LCL": [1, 2, 3, 4, 5, 6, 7, 8]}


def test_the_writes_are_a_full_applys_and_not_the_plans_own():
    """`patch` and `amend` build the plan's writes and never add these."""
    plan = demo_plan()
    targets = {t.address: t for t in full_apply_targets(plan, MODEL)}
    for n in range(3, 9):
        target = targets[f"/io/out/LCL/{n}/grp"]
        assert target.compute_value(None) == "OFF"
    assert "/io/out/LCL/1/grp" not in targets and "/io/out/LCL/2/grp" not in targets
    own, _warnings = _build_write_targets(plan, True)
    assert not {t.address for t in own} & {f"/io/out/LCL/{n}/grp" for n in range(3, 9)}


def test_the_pre_flight_says_it_before_anyone_arms_the_apply():
    notes = dict(full_apply_notes(demo_plan(), MODEL))
    assert "output LCL 3-8" in notes["apply.undeclared-outputs"]


# ---- a full apply on the simulated desk ----------------------------------


def test_a_desk_as_it_ships_has_local_outputs_3_to_8_patched():
    """The starting point the fix is about: the capture itself, not a leftover."""
    desk = fresh_desk()
    assert all(out_grp(desk, "LCL", n) != "OFF" for n in range(3, 9))


def test_a_full_apply_disconnects_them_and_keeps_the_plans_outputs():
    desk = fresh_desk()
    result = full_apply(demo_plan(), desk)
    assert not result.mismatches
    assert [out_grp(desk, "LCL", n) for n in range(3, 9)] == ["OFF"] * 6
    assert [out_grp(desk, "LCL", n) for n in (1, 2)] == ["MAIN", "MAIN"]
    [note] = output_notes(result)
    assert note.startswith("INFO output LCL 3-8: ")


def test_it_does_so_without_the_reset_too():
    desk = fresh_desk()
    result = full_apply(demo_plan(), desk, initialize=False)
    assert [out_grp(desk, "LCL", n) for n in range(3, 9)] == ["OFF"] * 6
    assert any("output LCL 3-8" in w for w in output_notes(result))


def test_a_preview_names_the_sockets_and_writes_nothing():
    desk = fresh_desk()
    result = full_apply(demo_plan(), desk, dry_run=True)
    assert not desk.writes
    assert all(out_grp(desk, "LCL", n) != "OFF" for n in range(3, 9))
    [note] = output_notes(result)
    assert "LCL 3-8" in note


def test_a_second_apply_finds_them_already_disconnected_and_says_so():
    desk = fresh_desk()
    full_apply(demo_plan(), desk)
    writes_before = len(desk.writes)
    result = full_apply(demo_plan(), desk)
    assert len(desk.writes) == writes_before
    [note] = output_notes(result)
    assert "6 output socket(s) the plan does not patch already read disconnected" in note


def test_the_flag_does_not_write_a_socket_twice():
    desk = fresh_desk()
    result = full_apply(demo_plan(), desk, clean_output_sockets={"LCL": 8})
    written = [w.address for w in result.writes if w.address.startswith("/io/out/LCL/")]
    assert len(written) == len(set(written))
    assert [out_grp(desk, "LCL", n) for n in range(3, 9)] == ["OFF"] * 6


def test_a_scoped_run_leaves_outputs_alone():
    """A run that is not a full apply (what `patch` and `amend` are) never
    touches a socket the plan does not patch."""
    desk = fresh_desk()
    before = [out_grp(desk, "LCL", n) for n in range(3, 9)]
    apply_plan(demo_plan(), desk, dry_run=False, target_filter=lambda t: t.address.startswith("/ch/1/"))
    assert [out_grp(desk, "LCL", n) for n in range(3, 9)] == before


# ---- the command line, end to end ----------------------------------------


@pytest.fixture
def cli_desk(monkeypatch, tmp_path):
    desk = fresh_desk()
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: desk)
    plan = tmp_path / "plan.json"
    shutil.copy(DEMO_PLAN, plan)
    return desk, plan


def run(plan, *extra) -> int:
    return cli.main(["apply", "--plan", str(plan), "--console", HOST, "--skip-verify",
                     "--no-progress", *extra])


def test_apply_confirm_leaves_the_audit_with_nothing_to_say_about_the_outputs(cli_desk, capsys):
    desk, plan = cli_desk
    assert run(plan, "--confirm") == 0
    err = capsys.readouterr().err
    assert "INFO output LCL 3-8" in err
    assert [out_grp(desk, "LCL", n) for n in range(3, 9)] == ["OFF"] * 6

    code = cli.main(["audit", "--plan", str(plan), "--console", HOST, "--no-progress"])
    out = capsys.readouterr().out
    assert code in (0, 2), out
    assert "CV009" not in out and "leftover" not in out
    assert "R011" not in out and "left side only" not in out


def test_an_apply_that_is_only_previewed_changes_nothing_and_names_them(cli_desk, capsys):
    desk, plan = cli_desk
    assert run(plan) == 0
    captured = capsys.readouterr()
    assert "INFO output LCL 3-8" in captured.err
    assert not desk.writes


def test_undo_puts_the_outputs_back_as_they_were(cli_desk, tmp_path, capsys):
    desk, plan = cli_desk
    before = {n: (out_grp(desk, "LCL", n), desk.values[f"/io/out/LCL/{n}/in"]) for n in range(3, 9)}
    journal = tmp_path / "j.json"
    assert run(plan, "--confirm", "--journal", str(journal)) == 0
    capsys.readouterr()
    # Exit 0: some settings of the Demo's presets had no earlier value to
    # restore (first writes), which is said at INFO and is not a failure.
    assert cli.main(["undo", str(journal), "--console", HOST, "--confirm", "--no-progress"]) == 0
    assert {n: (out_grp(desk, "LCL", n), desk.values[f"/io/out/LCL/{n}/in"])
            for n in range(3, 9)} == before
