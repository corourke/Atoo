"""Build step 04's Remove row on the Busses, Mains and Matrix, Outputs, and
User signals and patches tables.

Removing a row is the engineer's explicit instruction, so a Save carries it
out and never refuses it: the row says OFF (a bus's Name, a socket's or a
slot's Source), the object comes out of the plan, and what pointed at it
follows, said at INFO. The OFF line stays in the sheet, so a rebuild leaves
the object out too, over the conventions.

Every bundle is captured in the test from the church desk's frozen snapshot;
nothing under `examples/` is read.
"""

from __future__ import annotations

import copy
import csv
import io
import json

import pytest

from atoo import capture, outputs_sheet, sheets, verify_plan
from atoo.snapshot import load_snapshot
from tests.test_capture import CHURCH
from tests.test_user_sources_apply import _church_with_usr

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()


def _capture(state):
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


@pytest.fixture(scope="module")
def church():
    return _capture(capture.state_from_snap(load_snapshot(CHURCH), "wing-full"))


def _client(tmp_path, cap):
    from atoo.webui import create_app

    directory = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(cap), directory, evidence_name="church.snap",
                         evidence=b"{}")
    app = create_app(initial_bundle=str(directory))
    client = fastapi_testclient.TestClient(app)
    client.directory = directory
    return client


@pytest.fixture
def show(tmp_path, church):
    with _client(tmp_path, church) as c:
        yield c


def _plan(c) -> dict:
    return json.loads((c.directory / "plan.json").read_text())


def _remove_bus(c, label):
    """What the page sends for a Remove row: the row's Name says OFF and every
    other cell is blank."""
    sheet = c.get("/api/build/bus-sheet").json()["bus_sheet"]
    rows = []
    for record in sheet["records"]:
        values = dict(record["values"])
        if values["bus"] == label:
            values = {column: "" for column in values}
            values.update(bus=label, name="OFF")
        rows.append({"line": record["line"], "values": values})
    return c.post("/api/build/bus-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(c.directory), "rows": rows})


def _notes(body) -> str:
    return " ".join(body.get("notes") or [])


def _sheet_rows(c, name):
    return list(csv.DictReader(io.StringIO((c.directory / name).read_text())))


def test_a_removed_bus_is_out_of_the_plan_with_its_sends_and_sockets(show):
    r = _remove_bus(show, "Bus 9")
    assert r.status_code == 200, r.text
    body = r.json()
    plan = _plan(show)
    assert "Presentr" not in plan["busses"]
    assert not [s for ch in plan["channels"] for s in ch.get("bus_sends") or []
                if s.get("bus") == "Presentr"]
    assert not [s for b in plan["busses"].values() for s in b.get("bus_sends") or []
                if s.get("bus") == "Presentr"]
    said = _notes(body)
    assert "Bus 9 'Presentr' is removed, as busses.csv says (OFF): it is returned to free" in said
    assert "Guide, Drums, Drums Comp, VOCALS, Tracks, Reverb, CHORUS, DrumGATEVerb no longer " \
        "send to it" in said
    assert "LCL 1, LCL 2 are no longer fed from it" in said
    # The OFF line stays, so a rebuild leaves the bus out too.
    row = next(r for r in _sheet_rows(show, "busses.csv") if r["bus"] == "Bus 9")
    assert row["name"] == "OFF" and not any(v for k, v in row.items() if k not in ("bus", "name"))
    # outputs.csv follows: its sockets are not fed now.
    assert "outputs.csv follows: LCL 1 removed; LCL 2 removed." in body["message"]
    assert {"LCL 1", "LCL 2"}.isdisjoint(r["output"] for r in _sheet_rows(show, "outputs.csv"))
    # The page reads the sheet back with the row still in it.
    sheet = show.get("/api/build/bus-sheet").json()
    assert any(rec["values"]["bus"] == "Bus 9" and rec["values"]["name"] == "OFF"
               for rec in sheet["bus_sheet"]["records"])
    assert not any(d["bus"] == "Bus 9" for d in sheet["derived"])


def test_a_removed_main_takes_its_routes_its_matrix_feeds_and_its_sockets(show):
    r = _remove_bus(show, "Main 1")
    assert r.status_code == 200, r.text
    plan = _plan(show)
    assert not [k for k, o in plan["outputs"].items() if o.get("kind") == "main"]
    assert not [ch["name"] for ch in plan["channels"] if ch.get("main_routes")]
    said = _notes(r.json())
    assert "Main 1 'Main' is removed, as busses.csv says (OFF)" in said
    assert "are no longer routed to it" in said
    assert "CRD 31, CRD 32, USB 41, USB 42 are no longer fed from it" in said
    feeds = {key: [f for f in feed if f[0] == "main"]
             for key, feed in sheets.plan_compat.matrix_feeds(plan).items()}
    assert not any(feeds.values())
    # Other rows that named it as a source no longer do, in the plan and the file.
    assert "Matrix 2's sources no longer name Main, which busses.csv takes out (OFF)." in said
    row = next(r for r in _sheet_rows(show, "busses.csv") if r["bus"] == "Matrix 2")
    assert row["sources"] == "Click;Guide"
    # The Matrices it alone fed carry nothing now: said.
    assert ("Matrix 1 'Main PA', Matrix 4 'Main PFl' carry nothing now: it was their only "
            "source") in said
    # A bus that went only to it now feeds nothing: a warning, never a block
    # on Apply.
    verdict = verify_plan.verify_plan(plan, console_model="wing-full")
    assert ("bus.no-destination", "busses[Bus 5]") in {(f.code, f.where) for f in verdict.warnings}
    assert not verdict.errors


def test_a_removed_matrix_takes_the_sends_into_it(show):
    r = _remove_bus(show, "Matrix 2")
    assert r.status_code == 200, r.text
    plan = _plan(show)
    assert "MON SPKRS" not in plan["outputs"]
    assert "MON SPKRS" not in sheets.plan_compat.matrix_feeds(plan)
    said = _notes(r.json())
    assert "Matrix 2 'MON SPKRS' is removed" in said
    assert "Click, Guide, Main no longer send to it" in said
    assert "LCL 5, LCL 6 are no longer fed from it" in said


def test_a_rebuild_leaves_a_removed_object_out_over_the_conventions(church):
    """The build lays busses.csv on after the conventions made the plan: an
    OFF row takes the object out again, as a filled cell wins over them."""
    result = sheets.overlay_busses(church.plan, [{"bus": "Bus 9", "name": "off"}])
    assert result.refusals == []
    assert "Presentr" not in result.plan["busses"]
    assert result.changes == ["Bus 9 removed"]
    # A row that is already out says nothing more.
    again = sheets.overlay_busses(result.plan, [{"bus": "Bus 9", "name": "OFF"}])
    assert again.changes == [] and again.notes == []


def test_a_removed_output_socket_is_disconnected(show):
    sheet = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]
    rows = [dict(r, source="OFF") if r["output"] in ("LCL 7", "LCL 8") else r
            for r in sheet["rows"]]
    r = show.post("/api/build/outputs-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory), "rows": rows})
    assert r.status_code == 200, r.text
    assert "LCL 7 disconnected (was Matrix 1 L)" in r.json()["message"]
    assert "LCL 8 disconnected (was Matrix 1 R)" in r.json()["message"]
    sources = outputs_sheet.output_sources(_plan(show))
    assert ("LCL", 7) not in sources and ("LCL", 8) not in sources
    kept = {row["output"]: row["source"] for row in _sheet_rows(show, "outputs.csv")}
    assert kept["LCL 7"] == kept["LCL 8"] == "OFF"


def test_a_removed_user_slot_names_what_still_reads_it(tmp_path):
    with _client(tmp_path, _capture(_church_with_usr())) as c:
        sheet = c.get("/api/build/user-sheet").json()["user_sheet"]
        rows = [dict(r, source="OFF", tap="", leg="") for r in sheet["rows"]]
        r = c.post("/api/build/user-sheet/save", json={
            "expected_sha256": sheet["sha256"], "expected_bundle": str(c.directory),
            "rows": rows})
        assert r.status_code == 200, r.text
        assert ("USR 3 taken out (was CH 10 POST L+R (Lead post)); USB 29 still reads it, so it "
                "carries nothing until patched from something else") in r.json()["message"]
        assert not [e for e in _plan(c).get("user_sources") or [] if e["slot"] == 3]
        assert "USR 3,OFF" in (c.directory / "user.csv").read_text()


def test_the_page_has_a_remove_row_button_on_each_sheet(show):
    js = show.get("/static/setup.js").text
    for wanted in ('"data-bus-remove"', '"data-out-remove"', '"data-out-remove-run"',
                   '"data-user-remove"', "function removeOutRun",
                   'title="Remove row" aria-label="Remove row"', "function removeBusRow",
                   "function removeOutRow", "function removeUserRow", 'const REMOVED = "OFF"',
                   "row-removed-tag"):
        assert wanted in js, wanted
    css = show.get("/static/styles.css").text
    assert ".ct tr.row-removed > td" in css
