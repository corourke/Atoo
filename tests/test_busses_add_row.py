"""Build step 04's Add a bus, on the Busses table, as Outputs and User signals
have theirs.

A new row takes the next bus number no row and no plan bus has. Save adds the
bus to `busses.csv` and the plan with no model; what code chooses for it is
said at INFO (its width, when the row states none; its color is left to the
desk), and a bus that feeds nothing yet is said, not refused: adding it was
asked for.

The bundle is captured in the test from the church desk's frozen snapshot;
nothing under `examples/` is read.
"""

from __future__ import annotations

import csv
import io
import json

from atoo import verify_plan
from tests.test_sheet_remove_row import _client, church, show  # noqa: F401


def _add_bus(c, values: dict):
    """What the page sends for a row Add a bus made: every row the file has,
    then the new one with no line."""
    sheet = c.get("/api/build/bus-sheet").json()["bus_sheet"]
    rows = [{"line": r["line"], "values": r["values"]} for r in sheet["records"]]
    rows.append({"line": None, "values": values})
    return c.post("/api/build/bus-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(c.directory), "rows": rows})


def _plan(c) -> dict:
    return json.loads((c.directory / "plan.json").read_text())


def _sheet_rows(c):
    return list(csv.DictReader(io.StringIO((c.directory / "busses.csv").read_text())))


def test_an_added_bus_is_in_the_sheet_and_the_plan_with_what_code_chose_said(show):
    r = _add_bus(show, {"bus": "Bus 7", "name": "Click"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "1 added" in body["message"] and "Bus 7 added" in body["message"]
    bus = _plan(show)["busses"]["Click"]
    assert bus["index"] == 7 and bus["mono"] is False and bus.get("color") is None
    notes = " ".join(body["notes"])
    assert ("Bus 7 Click is a row of busses.csv the plan did not have, so it is added to the "
            "plan; no width is stated, so it is stereo, the WING's factory width (set Width to "
            "mono to change it); no color is stated, so Apply leaves the desk's.") in notes
    # Nothing goes from it yet: a warning in Findings, never a block on Apply. An empty bus the engineer added is a working desk.
    verdict = verify_plan.verify_plan(_plan(show), console_model="wing-full")
    assert ("bus.no-destination", "busses[Click]") in {(f.code, f.where) for f in verdict.warnings}
    assert not verdict.errors
    assert any(row["bus"] == "Bus 7" and row["name"] == "Click" for row in _sheet_rows(show))


def test_a_stated_width_is_kept(show):
    r = _add_bus(show, {"bus": "Bus 7", "name": "Click", "width": "mono"})
    assert r.status_code == 200, r.text
    assert _plan(show)["busses"]["Click"]["mono"] is True
    assert "no width is stated" not in " ".join(r.json()["notes"])


def test_an_added_bus_with_nothing_typed_is_added_by_its_number(show):
    r = _add_bus(show, {"bus": "Bus 7"})
    assert r.status_code == 200, r.text
    assert _plan(show)["busses"]["Bus 7"]["index"] == 7
    assert any(row["bus"] == "Bus 7" for row in _sheet_rows(show))


def test_the_page_has_add_a_bus_on_the_busses_block(show):
    js = show.get("/static/setup.js").text
    for wanted in ('data-bus-add>Add a bus</button>', "function addBusRow",
                   '${busControls(true)}', "r.added ||", "const BUS_CAPACITY = 16",
                   "No bus yet. Add a bus to start one."):
        assert wanted in js, wanted
