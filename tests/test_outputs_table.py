"""Build 04's Outputs table (revision 3 of the outputs-sheet
mockup, approved): `outputs.csv` read, checked and saved from
the page; the desk's colours a capture records and the table draws; and
`busses.csv`'s Outputs cells following a Save.

The desk is the church's full-size WING, from its frozen snapshot
(`tests/fixtures/church-full-2026-10-24.snap`): Bus 9 'Presentr' on LCL 1-2,
CH 9 'Kick' red on its own strip, CH 17 'Pastor' linked to LCL 1, which is
Rust.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import capture, outputs_sheet
from atoo.apply import apply_plan
from atoo.snapshot import load_snapshot

from conftest import require_fastapi_testclient  # noqa: E402

CHURCH = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"


@pytest.fixture(scope="module")
def state():
    return capture.state_from_snap(load_snapshot(CHURCH), "wing-full")


@pytest.fixture(scope="module")
def church(state) -> capture.Capture:
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _channel(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


# -- the desk's colours ------------------------------------------------------------------


def test_a_capture_records_the_colours_the_desk_shows(church):
    plan = church.plan
    # A strip showing its own colour keeps it; one linked to its source shows
    # the socket's, so it states none and the socket's is recorded.
    assert _channel(plan, "Kick")["col"] == 9
    assert _channel(plan, "Pastor")["col"] is None
    assert plan["meta"]["socket_colours"]["LCL 1"] == 8
    assert plan["busses"]["Presentr"]["col"] == 11
    assert plan["outputs"]["Main"]["col"] == 1
    assert plan["outputs"]["DRUMS IEM"]["col"] == 9


def test_the_colours_applied_back_to_their_own_desk_change_nothing(church, state):
    from tests.test_capture import _church_desk

    preview = apply_plan(church.plan, _church_desk(state), dry_run=True, full_apply=True,
                         initialize=True, init_model="wing-full")
    assert [w.address for w in preview.writes if w.status == "dry_run" and w.would_change] == []
    compared = {w.address for w in preview.writes}
    assert {"/ch/9/col", "/bus/9/col", "/main/1/col", "/mtx/6/col"} <= compared
    # A linked strip's colour is the socket's: Apply writes neither.
    assert not {"/ch/17/col", "/io/in/LCL/1/col"} & compared


def test_apply_writes_a_main_or_matrix_colour_the_plan_states(church, state):
    from tests.test_capture import _church_desk

    plan = copy.deepcopy(church.plan)
    plan["outputs"]["DRUMS IEM"]["col"] = 5
    preview = apply_plan(plan, _church_desk(state), dry_run=True, full_apply=True,
                         initialize=True, init_model="wing-full")
    assert [(w.address, w.prior_value, w.intended_value) for w in preview.writes
            if w.status == "dry_run" and w.would_change] == [("/mtx/6/col", 9, 5)]


def test_the_table_draws_each_source_in_the_desks_colour(church):
    display = outputs_sheet.display(church.plan)
    assert display["objects"]["Bus 9"] == {"colour": "pink", "name": "Presentr"}
    assert display["sockets"]["LCL 1"] == "rust"
    # Every input socket an output takes has its colour.
    sources = {row["source"] for row in outputs_sheet.rows_from_plan(church.plan)}
    assert not [s for s in sources if outputs_sheet.parse_source(s)[0][0] in ("A", "LCL", "MOD")
                and s not in display["sockets"]]


def test_a_built_plan_draws_a_socket_in_its_channels_colour():
    plan = {"channels": [{"name": "Kick", "color": "Red",
                          "patch": {"group": "A", "sockets": [1]}}]}
    assert outputs_sheet.display(plan)["sockets"] == {"AES50-A 1": "red"}


def test_a_linked_strips_chip_takes_its_sockets_colour(church):
    from atoo.webui import _channel_display, _output_display

    display = _channel_display(church.plan)
    pastor = display[church.plan["channels"].index(_channel(church.plan, "Pastor"))]
    assert pastor["colour"] == {"stated": None, "index": 8, "name": "Rust", "from_socket": True}
    kick = display[church.plan["channels"].index(_channel(church.plan, "Kick"))]
    assert kick["colour"]["name"] == "Red"
    assert _output_display(church.plan)["DRUMS IEM"]["colour"]["name"] == "Red"


# -- the table's API ------------------------------------------------------------------------

fastapi_testclient = require_fastapi_testclient()


@pytest.fixture
def show(tmp_path, church):
    from atoo.webui import create_app

    directory = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(church), directory, evidence_name="church.snap",
                         evidence=b"{}")
    app = create_app(initial_bundle=str(directory))
    with fastapi_testclient.TestClient(app) as c:
        c.directory = directory
        yield c


def _moved(rows: list[dict], **moves) -> list[dict]:
    """`rows` with each `output` renamed as `moves` says (`LCL_1="AUX 1"`)."""
    out = []
    for row in rows:
        row = dict(row)
        row["output"] = moves.get(row["output"].replace(" ", "_"), row["output"])
        out.append(row)
    return out


def test_the_table_reads_the_sheet_and_the_desks_colours(show):
    body = show.get("/api/build/outputs-sheet").json()
    sheet = body["outputs_sheet"]
    assert sheet["present"] and len(sheet["rows"]) == 147
    assert sheet["rows"][0] == {"output": "LCL 1", "source": "Bus 9 L", "notes": ""}
    assert body["display"]["objects"]["Bus 9"]["colour"] == "pink"
    assert body["plan_behind"] is False


def test_check_says_what_a_save_would_refuse(show):
    rows = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]["rows"]
    rows = [dict(r, source="AES50-A 49") if r["output"] == "USB 5" else r for r in rows]
    body = show.post("/api/build/outputs-sheet/check", json={"rows": rows}).json()
    assert [(r["row"], r["column"]) for r in body["refusals"]] == [("USB 5", "source")]


def test_a_save_moves_a_bus_and_busses_csv_follows(show):
    sheet = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]
    rows = _moved(sheet["rows"], LCL_1="AUX 1", LCL_2="AUX 2")
    rows = [dict(r, source="lcl 8", notes="talkback to the recorder") if r["output"] == "USB 5"
            else r for r in rows]
    r = show.post("/api/build/outputs-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory), "rows": rows})
    assert r.status_code == 200, r.text
    message = r.json()["message"]
    assert message.startswith("Saved church/outputs.csv. The plan is updated: LCL 1 disconnected "
                              "(was Bus 9 L); LCL 2 disconnected (was Bus 9 R); AUX 1 from Bus 9 L")
    assert message.endswith("busses.csv's Outputs column follows: Bus 9 AUX 1-2.")
    text = (show.directory / "outputs.csv").read_text()
    assert "\nAUX 1,Bus 9 L,\n" in text and "\nLCL 1," not in text
    # Written in the desk's words, with the row's notes.
    assert "\nUSB 5,LCL 8,talkback to the recorder\n" in text
    busses = (show.directory / "busses.csv").read_text()
    bus_9 = next(line for line in busses.splitlines() if line.startswith("Bus 9,"))
    assert ",AUX 1-2," in bus_9
    plan = json.loads((show.directory / "plan.json").read_text())
    assert plan["busses"]["Presentr"]["destinations"][-1]["patches"] == [
        {"group": "AUX", "sockets": [1, 2], "stated": True}]
    # Both files moved with the plan: it reads current.
    freshness = show.get("/api/build/sources").json()["plan_freshness"]
    assert not [r for r in freshness["reasons"] if r["slot"] in ("outputs_sheet", "bus_sheet")]


def test_a_refused_save_writes_nothing(show):
    sheet = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]
    before = (show.directory / "outputs.csv").read_text()
    rows = sheet["rows"] + [{"output": "LCL 99", "source": "Bus 9 L", "notes": ""}]
    r = show.post("/api/build/outputs-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory), "rows": rows})
    assert r.status_code == 400 and "outputs.csv" in r.json()["error"]
    assert (show.directory / "outputs.csv").read_text() == before


def test_a_sheet_changed_on_disk_is_not_overwritten(show):
    sheet = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]
    (show.directory / "outputs.csv").write_text("output,source,notes\n")
    r = show.post("/api/build/outputs-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory),
        "rows": sheet["rows"]})
    assert r.status_code == 409 and r.json()["stale"] == "file"


def test_a_show_with_no_outputs_csv_shows_the_plans_and_its_save_writes_one(show):
    """A built plan has no outputs.csv: the table shows the plan's outputs,
    and the first Save writes the file, which decides from then on."""
    (show.directory / "outputs.csv").unlink()
    plan = json.loads((show.directory / "plan.json").read_text())
    del plan["meta"]["outputs_sheet"]
    (show.directory / "plan.json").write_text(json.dumps(plan))
    body = show.get("/api/build/outputs-sheet").json()
    assert body["outputs_sheet"]["present"] is False
    assert body["outputs_sheet"]["rows"] == body["derived"] and len(body["derived"]) == 147
    r = show.post("/api/build/outputs-sheet/save", json={
        "expected_sha256": "", "expected_bundle": str(show.directory),
        "rows": body["outputs_sheet"]["rows"]})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Saved church/outputs.csv."
    assert (show.directory / "outputs.csv").read_text() == outputs_sheet.csv_text(body["derived"])
    plan = json.loads((show.directory / "plan.json").read_text())
    assert plan["meta"]["outputs_sheet"]["sha256"]


def test_build_04_serves_the_table(show):
    """The Python suite cannot see the browser code; this is the check that
    the page still asks for the sheet and draws its table, and that the
    bus tables no longer edit a socket."""
    js = show.get("/static/setup.js").text
    for wanted in ('fetch("/api/build/outputs-sheet")', '"/api/build/outputs-sheet/check"',
                   '"/api/build/outputs-sheet/save"', 'id="plan-sockets-table"',
                   "Save outputs.csv", "Add a socket", "data-out-toggle",
                   "This show has no outputs.csv yet -- these are ",
                   "the plan's outputs. Save writes outputs.csv, which will then take priority over ",
                   'const BUS_ROW_COLS = ["name", "role", "width", "outputs"];'):
        assert wanted in js, wanted
    assert "#plan-sockets-table" in show.get("/static/styles.css").text
