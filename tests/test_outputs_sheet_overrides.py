"""An outputs.csv that takes a socket off a bus, Main or Matrix the
instructions or conventions asked for is a WARNING quoting the line.

The sheet takes priority over the conventions and the instructions in a
build -- an object it names feeds only its rows' sockets -- so
"Video Feed: Send the main mix to USB 18-19", built as the Main's second
patch, comes off when the sheet lists the Main on LCL 1-2 only. That was an
INFO blaming "the conventions"; the engineer asked for it in words, so it
is said as a WARNING, naming the line and how to carry it out.

The show is `tests/fixtures/video-feed/`: the Demo's input list and plan
(the Main "PA" on LCL 1-2) with a desk test's Outputs instructions.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from atoo import cli, outputs_sheet

FIXTURE = Path(__file__).parent / "fixtures" / "video-feed"
LINE = "Video Feed: Send the main mix to USB 18-19"


@pytest.fixture
def show(tmp_path):
    for name in ("input.csv", "plan.json", "instructions.md"):
        (tmp_path / name).write_bytes((FIXTURE / name).read_bytes())
    return tmp_path


def _built(show) -> dict:
    """The plan as a model that carried the line out writes it: the Main on
    LCL 1-2 and, as its second patch, USB 18-19."""
    plan = json.loads((show / "plan.json").read_text())
    main = plan["outputs"]["PA"]
    main["patches"] = [main["patch"], {"group": "USB", "sockets": [18, 19], "stated": True}]
    return plan


def _lay_on(show, plan, layers):
    return cli._lay_on_sheets(plan, SimpleNamespace(directory=show),
                              (show / "input.csv").read_text(), "wing-full", layers)


def _layers(show, conventions: str = "") -> list:
    return [("instructions", (show / "instructions.md").read_text()), ("conventions", conventions)]


def test_with_no_outputs_csv_the_instruction_is_carried_out(show):
    plan = _built(show)
    findings = _lay_on(show, plan, _layers(show))
    assert {"group": "USB", "sockets": [18, 19], "stated": True} in plan["outputs"]["PA"]["patches"]
    assert not [f for f in findings if f.code == "build.outputs-sheet-overrides"]


def test_a_sheet_that_takes_the_instructions_sockets_off_says_so_quoting_the_line(show):
    # outputs.csv saved from Build 04 before the line was added: the Main on LCL 1-2.
    before = json.loads((show / "plan.json").read_text())
    (show / "outputs.csv").write_text(outputs_sheet.csv_text(outputs_sheet.rows_from_plan(before)))
    plan = _built(show)
    findings = _lay_on(show, plan, _layers(show))
    assert plan["outputs"]["PA"]["patches"] == [{"group": "LCL", "sockets": [1, 2], "stated": True}]
    (warning,) = [f for f in findings if f.code == "build.outputs-sheet-overrides"]
    assert warning.severity.value == "warning"
    assert warning.message == (
        f"outputs.csv decides Main 1's sockets (LCL 1-2), so the instructions' '{LINE}' is not "
        "carried out: USB 18-19 are not patched from Main 1. Add USB 18-19 to outputs.csv, or "
        "edit them in Build 04's Outputs table, to carry it out.")


def test_a_conventions_line_is_named_as_the_conventions(show):
    before = json.loads((show / "plan.json").read_text())
    (show / "outputs.csv").write_text(outputs_sheet.csv_text(outputs_sheet.rows_from_plan(before)))
    plan = _built(show)
    layers = [("instructions", ""), ("conventions", "## Outputs\n- The PA also feeds USB 18-19.\n")]
    (warning,) = [f for f in _lay_on(show, plan, layers) if f.code == "build.outputs-sheet-overrides"]
    assert "so the conventions' 'The PA also feeds USB 18-19.' is not carried out" in warning.message


def test_a_socket_no_line_names_stays_an_info(show):
    """A socket the build patched that no line asked for in words -- the
    model's own choice, or a convention by category -- comes off at INFO,
    as before."""
    before = json.loads((show / "plan.json").read_text())
    (show / "outputs.csv").write_text(outputs_sheet.csv_text(outputs_sheet.rows_from_plan(before)))
    plan = _built(show)
    findings = _lay_on(show, plan, [("instructions", "nothing about sockets"), ("conventions", "")])
    assert not [f for f in findings if f.code == "build.outputs-sheet-overrides"]
    assert "outputs.csv wins over the conventions: USB 18 disconnected (was Main 1 L)." in [
        f.message for f in findings]


@pytest.mark.parametrize("line, sockets", [
    ("Send the main mix to USB 18-19", {("USB", 18), ("USB", 19)}),
    ("record to AES50-B 3", {("B", 3)}),
    ("Bus 3 and Main 1 and CH 2 are not sockets", set()),
    ("LCL 7", {("LCL", 7)}),
])
def test_the_sockets_a_line_names(line, sockets):
    assert cli._sockets_named(line) == sockets
