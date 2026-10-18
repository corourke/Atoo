"""`atoo build --show DIR` and which WING it is for.

A show that has been built already has a plan that states its console
model. Asking for the flag again is a question with a known answer, so a
build of that show starts from it and says so at INFO; the flag still
overrides; a show with no plan to read it from is refused, and the refusal
names the flag. Everything is built in `tmp_path`; the plan is a stub.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import bundle
from atoo.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def show(tmp_path, stub_build):
    """A show folder holding an input list, no plan yet, and a conventions
    file beside it (the house file lives outside the show)."""
    stub_build("touringband")
    folder = tmp_path / "show"
    folder.mkdir()
    (folder / bundle.INPUT_LIST).write_text((FIXTURES / "touringband.csv").read_text())
    (tmp_path / "house.md").write_text((FIXTURES / "touringband.md").read_text())
    return folder


def _build(show: Path, *extra: str) -> int:
    return main(["build", "--show", str(show),
                 "--conventions", str(show.parent / "house.md"), *extra])


def _state(show: Path, model: str, name: str = bundle.PLAN) -> None:
    (show / name).write_text(json.dumps({"meta": {"console_model": model}, "channels": []}))


def test_a_show_whose_plan_names_a_model_builds_without_the_flag_and_says_so(show, capsys):
    _state(show, "wing-rack")
    code = _build(show)
    err = capsys.readouterr().err
    assert code in (0, 2), err
    assert "INFO console model: wing-rack, from plan.json" in err
    assert "pass --console-model to build for a different WING" in err
    built = json.loads((show / bundle.PLAN).read_text())
    assert built["meta"]["console_model"] == "wing-rack"


def test_the_plan_a_failed_rebuild_moved_aside_is_read_too(show, capsys):
    _state(show, "wing-full", bundle.PLAN_PREVIOUS)
    code = _build(show)
    err = capsys.readouterr().err
    assert code in (0, 2), err
    assert "INFO console model: wing-full, from plan.previous.json" in err


def test_the_flag_wins_over_the_plan(show, capsys):
    _state(show, "wing-rack")
    code = _build(show, "--console-model", "wing-compact")
    err = capsys.readouterr().err
    assert code in (0, 2), err
    assert "INFO console model" not in err
    built = json.loads((show / bundle.PLAN).read_text())
    assert built["meta"]["console_model"] == "wing-compact"


@pytest.mark.parametrize("plan_text", [None, "not json", json.dumps({"meta": {}})])
def test_a_show_with_no_model_to_take_is_refused_and_the_flag_is_named(show, capsys, plan_text):
    if plan_text is not None:
        (show / bundle.PLAN).write_text(plan_text)
    code = _build(show)
    err = capsys.readouterr().err
    assert code == 1
    assert "no console model stated" in err
    assert "--console-model wing-compact" in err
    assert "INFO console model" not in err


def test_a_stated_model_atoo_does_not_know_is_refused_by_name(show, capsys):
    _state(show, "wing-imaginary")
    code = _build(show)
    err = capsys.readouterr().err
    assert code == 1
    assert "unknown console model 'wing-imaginary'" in err
