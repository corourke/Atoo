"""The desk sheets edited in Build's step 04 (piece 3).

A Save writes the sheet and lays it onto the show's plan.json with no model
(`atoo/sheets.py`): a filled cell wins, a blank one is left to the plan, a
cell that cannot physically work is refused before anything is written, and
every choice made on the way is said at INFO.

Every bundle here is captured in the test from the church desk's frozen
snapshot (`tests/fixtures/church-full-2026-10-24.snap`); nothing under
`examples/` is read.
"""

from __future__ import annotations

import copy
import csv
import io
import json

import pytest

from atoo import capture, plan_compat, sheets, source_edit
from atoo.snapshot import load_snapshot
from tests.test_capture import CHURCH

from conftest import require_fastapi_testclient  # noqa: E402


@pytest.fixture(scope="module")
def church():
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _bus_rows(cap) -> list[dict]:
    return list(csv.DictReader(io.StringIO(cap.busses_csv())))


def _row(rows, label):
    return next(r for r in rows if r["bus"] == label)


# -- the bus sheet, read from the plan ------------------------------------------------


def test_a_captured_sheet_says_what_its_plan_says(church):
    """The overlay of a capture's own sheet onto its own plan changes nothing,
    and verify finds nothing new: the two are one record of the desk."""
    result = sheets.overlay_busses(church.plan, _bus_rows(church), before=_bus_rows(church))
    sheets.refuse_new_errors(church.plan, result, console_model="wing-full")
    assert result.refusals == [] and result.changes == []
    assert result.plan == church.plan


def test_the_plan_is_read_back_as_the_sheet(church):
    derived = {r["bus"]: r for r in sheets.bus_rows_from_plan(church.plan)}
    for row in _bus_rows(church):
        mine = derived[row["bus"]]
        assert sorted(sheets.parse_sources(row["sources"])) == \
            sorted(sheets.parse_sources(mine["sources"])) or row["bus"].startswith("Main"), row["bus"]
        assert sheets._socket_set(row["outputs"]) == sheets._socket_set(mine["outputs"]), row["bus"]
        assert row["width"] == mine["width"], row["bus"]


# -- carrying out a bus row ------------------------------------------------------------


def test_a_role_and_a_label_go_into_the_plan(church):
    rows = _bus_rows(church)
    _row(rows, "Bus 2").update(role="parallel", label="parallel compression on the drums")
    result = sheets.overlay_busses(church.plan, rows, before=_bus_rows(church))
    bus = result.plan["busses"]["Drums Comp"]
    assert bus["role"] == "parallel"
    assert bus["description"] == "parallel compression on the drums"
    assert result.refusals == []


def test_a_source_taken_out_is_a_send_taken_out(church):
    rows = _bus_rows(church)
    row = _row(rows, "Bus 1")
    row["sources"] = ";".join(n for n in row["sources"].split(";") if n != "Kick")
    result = sheets.overlay_busses(church.plan, rows)
    kick = next(c for c in result.plan["channels"] if c["name"] == "Kick")
    assert not any(s["bus"] == "Drums" for s in kick["bus_sends"])
    assert any(s["bus"] == "Drums Comp" for s in kick["bus_sends"])
    assert "Bus 1 fed no longer from Kick" in result.changes


def test_a_channel_added_to_a_matrix_is_a_send_on_the_channel_with_its_tap(church):
    rows = _bus_rows(church)
    # With no tap on the row, the sends it has keep theirs and a new one
    # with none of its own is decided, and said.
    _row(rows, "Matrix 2").update(sources=_row(rows, "Matrix 2")["sources"] + ";Snare (pre);Tom",
                                  tap="")
    result = sheets.overlay_busses(church.plan, rows)
    feeds = plan_compat.matrix_feeds(result.plan)["MON SPKRS"]
    assert ("channel", "Snare", "pre") in feeds
    assert ("channel", "Tom", "post") in feeds
    assert any("no tap is stated for the new send(s) from Tom, so they are post-fader" in n
               for n in result.notes)


def test_new_outputs_patch_the_bus_and_keep_its_main_route(church):
    rows = _bus_rows(church)
    _row(rows, "Bus 9")["outputs"] = "LCL 1-2; AUX 1-2"
    result = sheets.overlay_busses(church.plan, rows)
    dest = result.plan["busses"]["Presentr"]["destinations"]
    patches = [p for d in dest if d["type"] == "dedicated_output" for p in d["patches"]]
    assert {(p["group"], tuple(p["sockets"])) for p in patches} == {("LCL", (1, 2)),
                                                                    ("AUX", (1, 2))}


def test_a_rename_reaches_every_send_that_names_it(church):
    rows = _bus_rows(church)
    _row(rows, "Matrix 6")["name"] = "DRUM IEM"
    result = sheets.overlay_busses(church.plan, rows)
    assert "DRUM IEM" in result.plan["outputs"] and "DRUMS IEM" not in result.plan["outputs"]
    kick = next(c for c in result.plan["channels"] if c["name"] == "Kick")
    assert any(s["matrix"] == "DRUM IEM" for s in kick["matrix_sends"])
    assert result.renamed == {"DRUMS IEM": "DRUM IEM"}


def test_a_new_dca_takes_the_first_free_one_and_says_so(church):
    rows = _bus_rows(church)
    _row(rows, "Bus 6")["dca"] = "AllBand;Playback Bus"
    result = sheets.overlay_busses(church.plan, rows)
    assert result.plan["busses"]["Tracks"]["dca"] == ["AllBand", "Playback Bus"]
    taken = {e["index"] for k, e in church.plan["dcas"].items()}
    assert result.plan["dcas"]["Playback Bus"]["index"] == min(set(range(1, 17)) - taken)
    assert any("'Playback Bus' is new to this plan" in n for n in result.notes)


# -- what cannot physically work is refused, naming the cell ----------------------------


@pytest.mark.parametrize("label,column,value,reason", [
    ("Bus 3", "sources", "MIC2;Main", "a Main feeds only a Matrix"),
    ("Bus 3", "sources", "MIC2;Nobody", "no channel, bus, Main or input-list category"),
    ("Bus 1", "sources", "Drums;Kick", "a bus cannot feed itself"),
    ("Main 1", "sources", "Main PA", "a Matrix feeds only its outputs"),
    ("Bus 9", "outputs", "LCL 1-two", "is not an output socket"),
    ("Bus 9", "width", "wide", "width is mono or stereo"),
])
def test_a_cell_that_cannot_work_is_refused(church, label, column, value, reason):
    rows = _bus_rows(church)
    _row(rows, label)[column] = value
    result = sheets.overlay_busses(church.plan, rows)
    [refusal] = [r for r in result.refusals if r.row == label]
    assert refusal.column == column and reason in refusal.reason


def test_a_socket_the_desk_does_not_have_is_refused_by_verify(church):
    rows = _bus_rows(church)
    _row(rows, "Bus 8")["outputs"] = "LCL 9-10"
    result = sheets.overlay_busses(church.plan, rows)
    sheets.refuse_new_errors(church.plan, result, console_model="wing-full")
    assert {r.row for r in result.refusals} == {"Bus 8"}
    assert any("LCL output 9 does not exist" in r.reason for r in result.refusals)


def test_a_bus_past_the_desk_is_refused(church):
    rows = _bus_rows(church) + [{"bus": "Bus 17", "name": "Spare"}]
    result = sheets.overlay_busses(church.plan, rows)
    [refusal] = result.refusals
    assert refusal.column == "bus" and "no Bus 17" in refusal.reason


def test_a_name_both_a_channel_and_a_bus_reads_as_the_channel_and_says_so(church):
    rows = _bus_rows(church)
    _row(rows, "Bus 4")["name"] = "Keys"
    result = sheets.overlay_busses(church.plan, rows)
    assert result.refusals == []
    assert result.sources_spelling() == {"Keys Bus": "Bus 4"}
    assert sheets.rename_in_sources("Piano1;Keys Bus (pre)", result.sources_spelling()) == \
        "Piano1;Bus 4 (pre)"


# -- the input list -------------------------------------------------------------------


def _input_edit(cap, edits: dict, *, drop=(), add=()):
    text = cap.input_csv()
    _header, records, _end = source_edit.read_records(text)
    rows = []
    for i, record in enumerate(records):
        name = record.values["name"]
        if name in drop:
            continue
        rows.append({"line": i, "values": edits.get(name, {})})
    rows += [{"line": None, "values": values} for values in add]
    new, _summary = source_edit.splice_input_list(text, rows)
    return text, new, [r["line"] for r in rows]


def test_an_input_edit_reaches_its_channel(church):
    before, after, lines = _input_edit(church, {
        "Kick": {"name": "Kick In"}, "Snare": {"patch": "AES50-A 30"},
        "Click": {"channel": "39"}, "Bass": {"dca": "Bass/Keys/AG;Low End", "phantom": "TRUE"}})
    result = sheets.overlay_inputs(church.plan, before, after, lines)
    channels = {c["name"]: c for c in result.plan["channels"]}
    assert "Kick In" in channels and channels["Kick In"]["source"]["input"] == "Kick In"
    assert channels["Snare"]["patch"]["sockets"] == [30]
    assert channels["Click"]["channel"] == 39
    assert channels["Bass"]["dca"] == ["Bass/Keys/AG", "Low End"]
    assert channels["Bass"]["source"]["phantom"] is True
    assert result.renamed == {"Kick": "Kick In"}


def test_an_input_save_names_a_group_as_the_list_spells_it(church):
    """A Save takes the list's spelling as a build does: `BASS/KEYS/AG` for
    the plan's `Bass/Keys/AG` renames the DCA, on every channel in it."""
    members = [c["name"] for c in church.plan["channels"] if "Bass/Keys/AG" in (c.get("dca") or [])]
    assert len(members) > 1
    before, after, lines = _input_edit(church, {"Bass": {"dca": "BASS/KEYS/AG"}})
    result = sheets.overlay_inputs(church.plan, before, after, lines)
    assert "BASS/KEYS/AG" in result.plan["dcas"] and "Bass/Keys/AG" not in result.plan["dcas"]
    channels = {c["name"]: c for c in result.plan["channels"]}
    assert all(channels[name]["dca"].count("BASS/KEYS/AG") == 1 for name in members)
    assert "DCA 'Bass/Keys/AG' is named 'BASS/KEYS/AG', as the input list spells it." in result.notes
    assert result.refusals == []


def test_a_removed_row_takes_its_channel_out_and_a_pair_goes_mono(church):
    before, after, lines = _input_edit(church, {}, drop=("Floor", "Acoustic R"))
    result = sheets.overlay_inputs(church.plan, before, after, lines)
    names = [c["name"] for c in result.plan["channels"]]
    assert "Floor" not in names
    acoustic = next(c for c in result.plan["channels"] if c["name"] == "Acoustic")
    assert acoustic["source"]["stereo"] is False and acoustic["patch"]["sockets"] == [11]


def test_an_added_row_with_a_channel_is_placed_and_one_without_is_said(church):
    before, after, lines = _input_edit(church, {}, add=(
        {"channel": "27", "patch": "AES50-A 40", "name": "Sax", "category": "Horns",
         "type": "Mic", "phantom": "FALSE"},
        {"patch": "AES50-A 41", "name": "Flute", "category": "Horns", "type": "Mic",
         "phantom": "FALSE"}))
    result = sheets.overlay_inputs(church.plan, before, after, lines)
    sax = next(c for c in result.plan["channels"] if c["name"] == "Sax")
    assert (sax["bank"], sax["channel"], sax["patch"]["sockets"]) == ("ch", 27, [40])
    assert result.unplaced == ["Flute"]


def test_a_second_input_on_a_taken_channel_is_refused_unless_it_makes_a_pair(church):
    before, after, lines = _input_edit(church, {}, add=(
        {"channel": "9", "patch": "AES50-A 41", "name": "Kick 2", "category": "Drums",
         "type": "Mic", "phantom": "FALSE"},))
    result = sheets.overlay_inputs(church.plan, before, after, lines)
    [refusal] = result.refusals
    assert refusal.column == "channel" and "CH 9 already holds 'Kick'" in refusal.reason
    assert "AES50-A 20" in refusal.reason


def test_a_stereo_pair_the_desk_cannot_form_is_refused(church):
    before, after, lines = _input_edit(church, {"Acoustic R": {"patch": "AES50-A 15"}})
    result = sheets.overlay_inputs(church.plan, before, after, lines)
    sheets.refuse_new_errors(church.plan, result, console_model="wing-full")
    assert any("cannot be a stereo pair" in r.reason for r in result.refusals)


# -- the Save, end to end ----------------------------------------------------------------

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


def _sheet(c):
    return c.get("/api/build/bus-sheet").json()


def _bus_save(c, edit):
    sheet = _sheet(c)
    rows = []
    for record in sheet["bus_sheet"]["records"]:
        values = dict(record["values"])
        values.update(edit.get(values["bus"], {}))
        rows.append({"line": record["line"], "values": values})
    return c.post("/api/build/bus-sheet/save", json={
        "expected_sha256": sheet["bus_sheet"]["sha256"], "expected_bundle": str(c.directory),
        "rows": rows})


def test_save_writes_the_sheet_and_updates_the_plan(show):
    r = _bus_save(show, {"Bus 2": {"role": "parallel"}, "Bus 9": {"outputs": "LCL 1-2; AUX 1-2"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Saved church/busses.csv" in body["message"] and "The plan is updated" in body["message"]
    plan = json.loads((show.directory / "plan.json").read_text())
    assert plan["busses"]["Drums Comp"]["role"] == "parallel"
    assert "AUX 1-2" in (show.directory / "busses.csv").read_text()
    # The plan records the sheet it now agrees with: not Stale.
    freshness = show.get("/api/build/sources").json()["plan_freshness"]
    assert not any(r["slot"] == "bus_sheet" for r in freshness["reasons"])


def _dedicated(plan, bus):
    return [d["patches"] for d in plan["busses"][bus]["destinations"]
            if d["type"] == "dedicated_output"]


def _outputs_rows(directory):
    from atoo import outputs_sheet

    return {r["output"]: r["source"]
            for r in outputs_sheet.read_rows((directory / "outputs.csv").read_text())}


def test_a_bus_save_that_moves_a_bus_brings_outputs_csv_along(show):
    """Bus 9 (Presentr) moves from LCL 1-2 to AUX 1-2 in the
    Busses table. outputs.csv follows, so the next build lays nothing old back
    on: LCL 1-2 lose their rows, AUX 1-2 gain theirs (a captured sheet is the
    whole list), and the plan stays current with it."""
    r = _bus_save(show, {"Bus 9": {"outputs": "AUX 1-2"}})
    assert r.status_code == 200, r.text
    assert ("outputs.csv follows: LCL 1 removed; LCL 2 removed; AUX 1 from Bus 9 L; "
            "AUX 2 from Bus 9 R.") in r.json()["message"]
    rows = _outputs_rows(show.directory)
    assert "LCL 1" not in rows and "LCL 2" not in rows
    assert (rows["AUX 1"], rows["AUX 2"]) == ("Bus 9 L", "Bus 9 R")
    plan = json.loads((show.directory / "plan.json").read_text())
    assert _dedicated(plan, "Presentr") == [[{"group": "AUX", "sockets": [1, 2], "stated": True}]]
    freshness = show.get("/api/build/sources").json()["plan_freshness"]
    assert not any(r["code"] == "plan.outputs-sheet-edited" for r in freshness["reasons"])


def _bus_sheet_moved_by_hand(directory):
    """busses.csv edited in another program (Bus 9 to AUX 1-2); outputs.csv
    still says LCL 1-2 carry Bus 9."""
    path = directory / "busses.csv"
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    for row in rows:
        if row["bus"] == "Bus 9":
            row["outputs"] = "AUX 1-2"
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(out.getvalue())


def _outputs_sheet_moved_by_hand(directory):
    """outputs.csv edited in a spreadsheet: LCL 1-2's rows become AUX 1-2, so
    Bus 9 (Presentr) moves; busses.csv still says LCL 1-2."""
    path = directory / "outputs.csv"
    text = path.read_text()
    assert "LCL 1,Bus 9 L," in text and "LCL 2,Bus 9 R," in text
    path.write_text(text.replace("LCL 1,Bus 9 L,", "AUX 1,Bus 9 L,")
                    .replace("LCL 2,Bus 9 R,", "AUX 2,Bus 9 R,"))


def _lay_on(directory, plan):
    from types import SimpleNamespace

    from atoo import cli

    return cli._lay_on_sheets(plan, SimpleNamespace(directory=directory),
                              (directory / "input.csv").read_text(), "wing-full")


@pytest.fixture
def church_show(tmp_path, church):
    directory = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(church), directory, evidence_name="church.snap",
                         evidence=b"{}")
    return directory


def test_an_edit_to_outputs_csv_moves_the_bus_and_does_not_copy_it(church_show, church):
    """Bus 9 moved from LCL 1-2 to AUX 1-2 in outputs.csv;
    busses.csv still says LCL 1-2, and so does the plan the build starts from.
    outputs.csv is where the sockets are kept, so Bus 9 ends on AUX 1-2 only:
    its old sockets come off, and busses.csv's stale cell is said at INFO."""
    from atoo import outputs_sheet

    _outputs_sheet_moved_by_hand(church_show)
    plan = copy.deepcopy(church.plan)
    findings = _lay_on(church_show, plan)
    assert _dedicated(plan, "Presentr") == [[{"group": "AUX", "sockets": [1, 2], "stated": True}]]
    sources = outputs_sheet.output_sources(plan)
    assert ("LCL", 1) not in sources and ("LCL", 2) not in sources
    said = [f.message for f in findings]
    assert "outputs.csv wins over the conventions: LCL 1 disconnected (was Bus 9 L)." in said
    assert ("busses.csv says Bus 9 goes to LCL 1-2, outputs.csv says AUX 1-2: outputs.csv is "
            "where each socket's source is kept, so it wins, and busses.csv's Outputs column "
            "follows it. Edit outputs.csv, or its rows in Build 04's Outputs table, to move a bus."
            ) in said


def test_a_hand_edit_to_the_bus_sheets_outputs_column_is_said_not_laid_on(church_show, church):
    """The other way round: busses.csv's Outputs cell edited in another
    program, outputs.csv as captured. The column follows outputs.csv, so the
    build keeps Bus 9 where outputs.csv has it, and says which file to edit."""
    from atoo import outputs_sheet

    _bus_sheet_moved_by_hand(church_show)
    plan = copy.deepcopy(church.plan)
    findings = _lay_on(church_show, plan)
    assert _dedicated(plan, "Presentr") == [[{"group": "LCL", "sockets": [1, 2], "stated": True}]]
    assert ("AUX", 1) not in outputs_sheet.output_sources(plan)
    assert [f.message for f in findings if f.where == "busses.csv" and "Bus 9" in f.message] == [
        "busses.csv says Bus 9 goes to AUX 1-2, outputs.csv says LCL 1-2: outputs.csv is where "
        "each socket's source is kept, so it wins, and busses.csv's Outputs column follows it. "
        "Edit outputs.csv, or its rows in Build 04's Outputs table, to move a bus."]


def test_a_captured_show_laid_on_itself_says_nothing_and_changes_nothing(church_show, church):
    plan = copy.deepcopy(church.plan)
    findings = _lay_on(church_show, plan)
    assert plan == church.plan
    assert not [f for f in findings if f.code == "build.outputs-sheet"]


def test_a_save_that_replaces_an_effect_leaves_its_writes_for_apply(show):
    """The fx cell is carried out. TAP-DL off Bus 13, ST-DL on in
    the engine it frees; what Apply would write waits in the plan, so Watch
    says it (CV023) until the desk has it."""
    r = _bus_save(show, {"Bus 13": {"fx": "ST-DL"}})
    assert r.status_code == 200, r.text
    plan = json.loads((show.directory / "plan.json").read_text())
    (insert,) = plan["busses"]["Delay Long"]["inserts"]
    assert (insert["point"], insert["model"], insert["engine"]) == ("preins", "ST-DL", 2)
    [group] = plan["meta"]["sheet_pending"]
    assert group["cells"] == ['busses.csv, Bus 13 "Delay Long", fx: ST-DL']
    assert "/fx/2/mdl" in {w["address"] for w in group["writes"]}


def test_a_refused_save_writes_nothing(show):
    before_sheet = (show.directory / "busses.csv").read_bytes()
    before_plan = (show.directory / "plan.json").read_bytes()
    r = _bus_save(show, {"Bus 8": {"outputs": "LCL 9-10"}})
    assert r.status_code == 400
    assert r.json()["refusals"][0]["row"] == "Bus 8"
    assert "Nothing was saved" in r.json()["error"]
    assert (show.directory / "busses.csv").read_bytes() == before_sheet
    assert (show.directory / "plan.json").read_bytes() == before_plan


def test_the_check_says_what_save_would_refuse(show):
    sheet = _sheet(show)
    rows = [{"line": r["line"], "values": dict(r["values"], outputs="LCL 9-10")
             if r["values"]["bus"] == "Bus 8" else r["values"]}
            for r in sheet["bus_sheet"]["records"]]
    r = show.post("/api/build/sheets/check", json={"sheet": "bus_sheet", "rows": rows})
    assert [x["row"] for x in r.json()["refusals"]] == ["Bus 8", "Bus 8"]


def test_an_input_rename_is_carried_into_the_bus_sheet(show):
    source = show.get("/api/build/sources").json()["input_list"]
    rows = []
    for record in source["records"]:
        values = {"name": "Kick In"} if record["values"]["name"] == "Kick" else {}
        rows.append({"line": record["line"], "values": values})
    r = show.post("/api/build/input-list/save", json={
        "expected_path": source["path"], "expected_sha256": source["sha256"],
        "expected_bundle": str(show.directory), "rows": rows})
    assert r.status_code == 200, r.text
    plan = json.loads((show.directory / "plan.json").read_text())
    assert any(c["name"] == "Kick In" for c in plan["channels"])
    sheet = (show.directory / "busses.csv").read_text()
    assert "Kick In" in sheet and ";Kick;" not in sheet
    freshness = show.get("/api/build/sources").json()["plan_freshness"]
    assert freshness["reasons"] == []


def test_a_sheet_edited_elsewhere_makes_the_plan_stale(show):
    path = show.directory / "busses.csv"
    path.write_text(path.read_text().replace("Presentr", "Presenter"))
    freshness = show.get("/api/build/sources").json()["plan_freshness"]
    assert [r["code"] for r in freshness["reasons"]] == ["plan.bus-sheet-edited"]


def test_save_lays_on_a_sheet_edited_elsewhere_with_nothing_typed(show):
    path = show.directory / "busses.csv"
    path.write_text(path.read_text().replace("Bus 2,Drums Comp,,", "Bus 2,Drums Comp,parallel,"))
    sheet = _sheet(show)
    assert sheet["plan_behind"] is True
    r = _bus_save(show, {})
    assert r.status_code == 200, r.text
    assert r.json()["plan_behind"] is False
    plan = json.loads((show.directory / "plan.json").read_text())
    assert plan["busses"]["Drums Comp"]["role"] == "parallel"


# -- New show > From a desk -------------------------------------------------------------


def test_new_show_from_a_snap_writes_a_captured_show(tmp_path):
    from atoo.webui import create_app

    with fastapi_testclient.TestClient(create_app()) as c:
        r = c.post("/api/capture", json={"source": "snap", "snap_path": str(CHURCH),
                                          "console_model": "wing-full",
                                          "folder": str(tmp_path / "church")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["directory"] == str(tmp_path / "church") and body["renamed"] is False
        for name in ("input.csv", "busses.csv", "plan.json", "watch.json"):
            assert (tmp_path / "church" / name).is_file(), name
        assert (tmp_path / "church" / "captures" / CHURCH.name).is_file()
        assert body["notes"] and body["summary"][0].startswith("input.csv")
        # A second capture to the same name takes the next one.
        again = c.post("/api/capture", json={"source": "snap", "snap_path": str(CHURCH),
                                              "console_model": "wing-full",
                                              "folder": str(tmp_path / "church")}).json()
        assert again["directory"] == str(tmp_path / "church-2") and again["renamed"] is True


@pytest.mark.parametrize("body,said", [
    ({"source": "snap", "console_model": "wing-full"}, "choose the .snap file"),
    ({"source": "snap", "snap_path": str(CHURCH)}, "choose the console model"),
    ({"source": "console"}, "no console is set"),
])
def test_new_show_from_a_desk_says_what_it_still_needs(tmp_path, body, said):
    from atoo.webui import create_app

    with fastapi_testclient.TestClient(create_app()) as c:
        r = c.post("/api/capture", json=dict(body, folder=str(tmp_path / "x")))
    assert r.status_code == 400 and said in r.json()["error"]
    assert not (tmp_path / "x").exists()


# -- Apply, and a build, on a show with sheets -----------------------------------------


def test_a_send_taken_out_of_the_sheet_is_switched_off_by_a_full_apply(church):
    from atoo.apply import _build_write_targets

    rows = _bus_rows(church)
    row = _row(rows, "Bus 1")
    row["sources"] = ";".join(n for n in row["sources"].split(";") if n != "Kick")
    plan = sheets.overlay_busses(church.plan, rows).plan
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    drums = plan["busses"]["Drums"]["index"]
    targets = {t.address: t for t in _build_write_targets(plan, True)[0]}
    off = targets[f"/ch/{kick['channel']}/send/{drums}/on"]
    assert off.compute_value(None) == 0 and "NOT sent to Drums" in off.description
    # Its level and tap are the desk's: only the switch is written.
    assert f"/ch/{kick['channel']}/send/{drums}/lvl" not in targets


def test_a_captured_plan_writes_empty_membership_and_its_widths(church):
    from atoo.apply import _build_write_targets

    plan = copy.deepcopy(church.plan)
    plan["channels"][0]["dca"] = []
    plan["channels"][0]["mute_group"] = []
    targets = {t.address: t for t in _build_write_targets(plan, True)[0]}
    first = plan["channels"][0]
    tags = targets[f"/{first['bank']}/{first['channel']}/tags"]
    assert tags.compute_value("#D3,#M8,keep") == "keep"
    main = next(o for o in plan["outputs"].values() if o["kind"] == "main")
    assert f"/main/{main['index']}/busmono" in targets


def _build_with_sheet(tmp_path, stub_build, monkeypatch, sheet):
    """A Build-page run of the touringband show with `sheet` as its
    busses.csv (None: no busses.csv): `(status, plan or None, directory)`."""
    import test_webui as webui_tests
    from atoo.webui import create_app

    stub_build("touringband")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    directory = webui_tests._touringband_bundle(tmp_path)
    if sheet is not None:
        (directory / "busses.csv").write_text(sheet)
    (directory / "plan.json").unlink(missing_ok=True)
    app = create_app(initial_bundle=str(directory),
                     initial_conventions=str(webui_tests._house(tmp_path)))
    with fastapi_testclient.TestClient(app) as c:
        r = c.post("/api/build/run", json={"console_model": "wing-compact",
                                           "expected_bundle": str(directory)})
        assert r.status_code == 200, r.json()
        status = webui_tests._wait_for_build(c)
        findings = c.get("/api/build/status").json()
    path = directory / "plan.json"
    plan = json.loads(path.read_text()) if path.is_file() else None
    return status, plan, directory, findings


def test_a_build_lays_the_bus_sheet_on_and_says_each_change(tmp_path, stub_build, monkeypatch):
    """A filled cell of busses.csv wins over the conventions in a
    build, as a Save in step 04 does, and each change is an INFO."""
    from atoo import plan_freshness

    status, plan, directory, _ = _build_with_sheet(
        tmp_path, stub_build, monkeypatch, "bus,name,role\nBus 1,Kit,parallel\n")
    assert status["state"] == "done", status
    assert plan["busses"]["Kit"]["index"] == 1 and plan["busses"]["Kit"]["role"] == "parallel"
    assert "Drums" not in plan["busses"]
    said = [f["message"] for f in plan["meta"]["build_findings"] if f["code"] == "build.bus-sheet"]
    assert any(m.startswith("busses.csv wins over the conventions: ") and "Kit" in m
               for m in said), said
    assert all(f["severity"] == "info" for f in plan["meta"]["build_findings"]
               if f["code"] == "build.bus-sheet")
    # The old note is gone, and the plan records the sheet it was made from.
    assert not [n for n in plan.get("notes") or [] if n.get("source") == "sheets"
                and "does not read" in n.get("text", "")]
    assert plan["meta"]["bus_sheet"]["sha256"]
    fresh = plan_freshness.assess(plan, conventions=None, instructions=None, input_list=None,
                                  bus_sheet=directory / "busses.csv")
    assert "plan.bus-sheet-edited" not in {r["code"] for r in fresh["reasons"]}


def test_a_bus_sheet_cell_that_cannot_work_stops_the_build_naming_it(tmp_path, stub_build,
                                                                    monkeypatch):
    status, plan, _, _ = _build_with_sheet(
        tmp_path, stub_build, monkeypatch, "bus,name,outputs\nBus 4,,LCL 99\n")
    assert status["state"] != "done", status
    assert plan is None
    text = json.dumps(status)
    assert "busses.csv cannot be laid onto this plan, so nothing was written" in text
    assert "busses.csv, Bus 4, outputs: LCL output 99 does not exist" in text


def test_a_build_with_no_bus_sheet_is_as_before(tmp_path, stub_build, monkeypatch):
    status, plan, _, _ = _build_with_sheet(tmp_path, stub_build, monkeypatch, None)
    assert status["state"] == "done", status
    assert "Drums" in plan["busses"]
    assert "bus_sheet" not in plan["meta"]
    assert not [f for f in plan["meta"]["build_findings"] if f["code"] == "build.bus-sheet"]


def test_the_plan_schema_holds_a_role_and_a_main_s_width(church):
    from atoo.plan_schema import PLAN_SCHEMA
    from atoo.schema_check import validate as validate_schema

    plan = copy.deepcopy(church.plan)
    plan["busses"]["Drums Comp"]["role"] = "parallel"
    next(iter(plan["outputs"].values()))["role"] = "pa"
    assert validate_schema(plan, PLAN_SCHEMA) == []
    plan["busses"]["Drums Comp"]["role"] = "pa"
    assert validate_schema(plan, PLAN_SCHEMA)
    assert church.plan["busses"]["Reverb"]["role"] == "fx"


# -- a desk with unused buses routed to a Main ----------------------------


INITIALIZED = CHURCH.parent / "Initialized-Full.snap"


@pytest.fixture(scope="module")
def factory_desk():
    state = capture.state_from_snap(load_snapshot(INITIALIZED), "wing-full")
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-25", snapshot="captures/init.snap")


def test_no_sources_cell_names_a_bus_without_a_row(factory_desk):
    rows = _bus_rows(factory_desk)
    labels = {r["bus"] for r in rows} | {r["name"] for r in rows if r["name"]}
    labels |= set(factory_desk.plan["busses"])
    named = [n for r in rows for n, _tap in sheets.parse_sources(r["sources"])]
    buses_named = [n for n in named if str(n).startswith("Bus ")]
    assert all(n in labels for n in buses_named), buses_named
    assert "Bus 9" not in labels
    [note] = [n for n in factory_desk.notes if "Bus 9" in n]
    assert note.startswith("Left out of the sheets: Bus 9, Bus 10,")
    assert "Bus 16, which nothing feeds and which reach only a Main" in note


def test_the_factory_desk_s_sheet_with_one_cell_changed_passes_the_check(tmp_path,
                                                                         factory_desk):
    from atoo.webui import create_app

    directory = tmp_path / "init"
    capture.write_bundle(copy.deepcopy(factory_desk), directory, evidence_name="init.snap",
                         evidence=b"{}")
    with fastapi_testclient.TestClient(create_app(initial_bundle=str(directory))) as c:
        sheet = _sheet(c)
        rows = [{"line": r["line"], "values": dict(r["values"], name="Mon 1")
                 if r["values"]["bus"] == "Bus 1" else r["values"]}
                for r in sheet["bus_sheet"]["records"]]
        r = c.post("/api/build/sheets/check", json={"sheet": "bus_sheet", "rows": rows})
    assert r.status_code == 200, r.text
    assert r.json()["refusals"] == []


def test_a_refusal_names_the_rows_as_the_sheet_does(church):
    """verify's text names plan paths (`busses[Speakers].destinations[1]`);
    a refusal shown under a sheet's row names them as the sheet does."""
    before = _bus_rows(church)
    after = [dict(r, outputs="LCL 3-4") if r["bus"] == "Bus 10" else r for r in before]
    result = sheets.overlay_busses(church.plan, after, before=before)
    sheets.refuse_new_errors(church.plan, result, console_model="wing-full")
    [refusal] = [r for r in result.refusals if "claimed by 2 sources" in r.reason]
    assert 'Bus 8 "Broadcast Mix" and Bus 10 "Speakers", outputs' in refusal.reason
    assert "busses[" not in refusal.reason


def test_a_captured_show_rebuilt_from_conventions_keeps_every_filled_cell(tmp_path, church,
                                                                         monkeypatch):
    """A captured show rebuilt from conventions. The conventions
    named a bus otherwise, gave no role and patched no outputs on Bus 9; the
    show's bus sheet wins wherever it has a filled cell, each change said at
    INFO, and what the plan cannot hold is said too (nothing dropped)."""
    from atoo.cli import main

    directory = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(church), directory, evidence_name="church.snap",
                         evidence=b"{}")
    conventions_built = copy.deepcopy(church.plan)
    conventions_built.pop("meta", None)
    drums_comp = conventions_built["busses"].pop("Drums Comp")
    drums_comp["role"] = None
    conventions_built["busses"]["Comp Bus"] = drums_comp
    presentr = conventions_built["busses"]["Presentr"]
    presentr["destinations"] = [d for d in presentr.get("destinations") or []
                                if d.get("type") != "dedicated_output"]
    presentr["destination"] = presentr["destinations"][0] if presentr["destinations"] else None
    for bus in conventions_built["busses"].values():
        bus["role"] = None

    def fake_generate_plan(*args, **kwargs):
        built = copy.deepcopy(conventions_built)
        built.setdefault("meta", {})["console_model"] = kwargs.get("console_model")
        return built

    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: object())
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    monkeypatch.setattr("atoo.generate.generate_plan", fake_generate_plan)
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    conventions = tmp_path / "house.md"
    conventions.write_text("# House\n\nBuses as the band asks.\n")
    (directory / "plan.json").unlink()
    assert main(["build", "--show", str(directory), "--conventions", str(conventions),
                 "--console-model", "wing-full"]) in (0, 1)
    plan = json.loads((directory / "plan.json").read_text())
    sheet = {r["bus"]: r for r in _bus_rows(church)}
    # The sheet's name for Bus 2 wins, and its roles (fx on 11-16).
    assert "Drums Comp" in plan["busses"] and "Comp Bus" not in plan["busses"]
    for label, row in sheet.items():
        if row["role"] and label.startswith("Bus "):
            entry = next(b for b in plan["busses"].values()
                         if b["index"] == int(label.split()[1]))
            assert entry["role"] == row["role"], label
    # Bus 9's outputs, from the sheet.
    derived = {r["bus"]: r for r in sheets.bus_rows_from_plan(plan)}
    assert derived["Bus 9"]["outputs"] == sheet["Bus 9"]["outputs"]
    said = [f["message"] for f in plan["meta"]["build_findings"] if f["code"] == "build.bus-sheet"]
    assert any("Drums Comp" in m for m in said), said
    # What the plan cannot hold (fx) is said, not dropped.
    assert any("fx" in m for m in said), said


# -- a Main's and a Matrix's own DCAs and mute groups --------------------


def test_a_main_s_dcas_and_mute_groups_are_captured_into_the_plan_and_sheet(church):
    """Capture reads `/main/{n}/tags` and `/mtx/{n}/tags` as it reads a bus's."""
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    dca = next(iter(church.plan["dcas"]))
    index = church.plan["dcas"][dca]["index"]
    state.values["/main/1/tags"] = f"#D{index},#M1"
    cap = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                               captured="2026-10-25")
    main = next(o for o in cap.plan["outputs"].values() if o["kind"] == "main" and o["index"] == 1)
    assert main["dca"] == [dca] and len(main["mute_group"]) == 1
    row = next(r for r in _bus_rows(cap) if r["bus"] == "Main 1")
    assert row["dca"] == dca
    # A Matrix with nothing tagged states an empty membership.
    mtx = next(o for o in cap.plan["outputs"].values() if o["kind"] == "matrix")
    assert mtx["dca"] == [] and mtx["mute_group"] == []


def test_the_sheet_carries_a_main_s_dcas_into_the_plan(church):
    dca = next(iter(church.plan["dcas"]))
    before = _bus_rows(church)
    after = [dict(r, dca=dca) if r["bus"] == "Main 1" else r for r in before]
    result = sheets.overlay_busses(church.plan, after, before=before)
    assert result.refusals == []
    main = next(o for o in result.plan["outputs"].values()
                if o["kind"] == "main" and o["index"] == 1)
    assert main["dca"] == [dca]
    assert f"Main 1 dca {dca}" in result.changes
    assert not [n for n in result.notes if "does not hold" in n]
    assert {r["bus"]: r for r in sheets.bus_rows_from_plan(result.plan)}["Main 1"]["dca"] == dca


def test_apply_writes_a_main_s_tags_by_merging(church):
    from atoo import apply

    plan = copy.deepcopy(church.plan)
    dca = next(iter(plan["dcas"]))
    index = plan["dcas"][dca]["index"]
    main = next(o for o in plan["outputs"].values() if o["kind"] == "main" and o["index"] == 1)
    main["dca"] = [dca]
    targets, _ = apply._build_write_targets(plan, True)
    [tags] = [t for t in targets if t.address == "/main/1/tags"]
    # The captured plan states the Main's mute groups too (none), so the
    # desk's #M3 goes and the DCA is set.
    assert main["mute_group"] == []
    assert tags.compute_value("#M3") == f"#D{index}"
    # A built plan that states none leaves the desk's tags alone.
    main.pop("dca"); main.pop("mute_group", None)
    plan.setdefault("meta", {})["made_from"] = None
    assert not [t for t in apply._build_write_targets(plan, True)[0]
                if t.address == "/main/1/tags"]
