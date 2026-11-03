"""Build 04's Outputs table takes a run typed as one row.

`USB 1-16` from `AES50-A 1-16` is sixteen sockets, each from its own
source: a plain instruction, so it is carried out, and outputs.csv is written
one row per socket. A row that feeds a socket wins over a row that took it
OFF (the table's Remove row), so a run typed over removed rows is not
refused as a socket listed twice. A run's header is labelled from its rows
as they are now.

The desk is the church's full-size WING, from its frozen snapshot
(`tests/fixtures/church-full-2026-10-24.snap`): USB 1-8 are fed from
AES50-A 1-8 and USB 9-16 from AES50-A 19-26.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from atoo import capture, outputs_sheet
from atoo.snapshot import load_snapshot

from conftest import require_fastapi_testclient  # noqa: E402

CHURCH = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"


@pytest.fixture(scope="module")
def church() -> capture.Capture:
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _expand(output: str, source: str):
    rows, notes, refusals = outputs_sheet.expand_rows([{"output": output, "source": source,
                                                        "notes": "rec"}])
    return [(r["output"], r["source"]) for _n, r in rows], notes, [r.text() for r in refusals]


# -- a run read as one row per socket ----------------------------------------------


def test_a_run_from_a_run_of_the_same_length_is_a_row_per_socket():
    rows, notes, refused = _expand("USB 1-16", "AES50-A 1-16")
    assert rows == [(f"USB {n}", f"AES50-A {n}") for n in range(1, 17)]
    assert notes == [] and refused == []


def test_a_run_from_one_source_counts_up_from_it_and_says_so():
    rows, notes, refused = _expand("aes50-b 3-5", "LCL 6")
    assert rows == [("AES50-B 3", "LCL 6"), ("AES50-B 4", "LCL 7"), ("AES50-B 5", "LCL 8")]
    assert notes == ["outputs.csv, aes50-b 3-5: from LCL 6, counting up: AES50-B 3 from LCL 6 "
                     "to AES50-B 5 from LCL 8"]
    assert refused == []


def test_a_bus_main_or_matrix_run_is_its_two_sides():
    assert _expand("AES50-A 7-8", "Bus 4 L-R")[0] == [("AES50-A 7", "Bus 4 L"),
                                                     ("AES50-A 8", "Bus 4 R")]
    assert _expand("USB 41-42", "Main 1 L-R")[0] == [("USB 41", "Main 1 L"),
                                                    ("USB 42", "Main 1 R")]


def test_a_run_taken_off_or_left_blank_is_every_socket_of_it():
    assert _expand("USB 2-4", "OFF")[0] == [("USB 2", "OFF"), ("USB 3", "OFF"), ("USB 4", "OFF")]
    assert _expand("USB 2-3", "")[0] == [("USB 2", ""), ("USB 3", "")]


def test_each_socket_keeps_the_rows_notes_and_a_plain_row_passes_as_it_is():
    rows, _notes, _refused = outputs_sheet.expand_rows([
        {"output": "USB 1-2", "source": "AES50-A 1-2", "notes": "rec"},
        {"output": "Stage left", "source": "LCL 1", "notes": ""}])
    assert [(n, r["output"], r["notes"]) for n, r in rows] == [
        (2, "USB 1", "rec"), (2, "USB 2", "rec"), (3, "Stage left", "")]


@pytest.mark.parametrize("output, source, said", [
    ("USB 1-16", "AES50-A 1-8",
     "outputs.csv, USB 1-16, source 'AES50-A 1-8': is 8 source(s) for 16 socket(s): a run feeds "
     "one socket from each source, so the two must be the same length"),
    ("USB 1-2", "Bus 4 L-R", None),
    ("LCL 1-3", "Bus 4 L-R",
     "outputs.csv, LCL 1-3, source 'Bus 4 L-R': is 2 source(s) for 3 socket(s)"),
    ("USB 45-50", "AES50-A 1-6",
     "outputs.csv, USB 45-50, output 'USB 45-50': goes past USB 48, the last output socket of "
     "its group"),
    ("USB 1-10", "AES50-A 40",
     "outputs.csv, USB 1-10, source 'AES50-A 40': counts past AES50-A 48, the last of its group, "
     "for 10 socket(s)"),
    ("USB 9-2", "AES50-A 1-8",
     "outputs.csv, USB 9-2, output 'USB 9-2': runs backwards: write it USB 2-9"),
    ("USB 1-4", "Dante 1-4", "outputs.csv, USB 1-4, source 'Dante 1-4': 'Dante 1-4' is not a source"),
])
def test_only_what_cannot_work_is_refused_naming_the_row(output, source, said):
    rows, _notes, refused = _expand(output, source)
    if said is None:
        assert refused == [] and len(rows) == 2
    else:
        assert rows == [] and len(refused) == 1 and refused[0].startswith(said), refused


# -- laid on the plan ---------------------------------------------------------------


def _rows(church) -> list[dict]:
    return outputs_sheet.read_rows(church.outputs_csv())


def _removed(rows: list[dict], *outputs: str) -> list[dict]:
    """`rows` with each named socket taken OFF, as the table's Remove row does."""
    return [dict(r, source="OFF") if r["output"] in outputs else r for r in rows]


def test_a_run_typed_over_removed_rows_replaces_them(church):
    """The sitting: USB 1-16 were two runs (AES50-A 1-8, AES50-A 19-26); he
    removed them and typed one row."""
    usb = [f"USB {n}" for n in range(1, 17)]
    rows = _removed(_rows(church), *usb)
    rows.append({"output": "USB 1-16", "source": "AES50-A 1-16", "notes": ""})
    result = outputs_sheet.overlay(church.plan, rows, complete=True, console_model="wing-full")
    assert result.refusals == []
    sources = outputs_sheet.output_sources(result.plan)
    assert [sources[("USB", n)] for n in range(1, 17)] == [("A", n) for n in range(1, 17)]
    assert result.changes == [f"USB {n} from AES50-A {n} (was AES50-A {n + 10})"
                              for n in range(9, 17)]


def test_a_removed_row_gives_way_whichever_comes_first(church):
    rows = [r for r in _rows(church) if r["output"] != "USB 5"]
    rows = [{"output": "USB 5", "source": "LCL 8", "notes": ""}] + rows + [
        {"output": "USB 5", "source": "OFF", "notes": ""}]
    result = outputs_sheet.overlay(church.plan, rows, complete=True, console_model="wing-full")
    assert result.refusals == []
    assert outputs_sheet.output_sources(result.plan)[("USB", 5)] == ("LCL", 8)


def test_two_rows_that_both_feed_a_socket_are_still_refused(church):
    rows = _rows(church) + [{"output": "USB 1-16", "source": "AES50-A 1-16", "notes": ""}]
    said = [r.text() for r in outputs_sheet.overlay(church.plan, rows, complete=True,
                                                    console_model="wing-full").refusals]
    assert len(said) == 16
    assert said[0].startswith("outputs.csv, USB 1, output 'USB 1': is listed twice (lines 31 "
                              "and 149)")


def test_a_build_lays_on_a_run_too(church):
    plan = copy.deepcopy(church.plan)
    result = outputs_sheet.overlay(plan, [{"output": "USB 33-40", "source": "AES50-B 1"}],
                                   complete=False, console_model="wing-full")
    assert result.refusals == []
    sources = outputs_sheet.output_sources(result.plan)
    assert [sources[("USB", n)] for n in range(33, 41)] == [("B", n) for n in range(1, 9)]
    assert result.notes == ["outputs.csv, USB 33-40: from AES50-B 1, counting up: USB 33 from "
                            "AES50-B 1 to USB 40 from AES50-B 8"]


def test_the_build_precheck_reads_a_run(church, tmp_path):
    from atoo import bundle
    from atoo.cli import _precheck_show

    class Show:
        directory = tmp_path

    (tmp_path / bundle.OUTPUTS).write_text(
        "output,source,notes\nUSB 1-16,AES50-A 1-16,\nUSB 17-20,AES50-A 1-2,\n"
        "USB 21-22,Bus 4 L-R,\nUSB 21,OFF,\n")
    assert _precheck_show([], Show, "wing-full") == [
        "outputs.csv, USB 17-20, source 'AES50-A 1-2': is 2 source(s) for 4 socket(s): a run "
        "feeds one socket from each source, so the two must be the same length"]


# -- the page --------------------------------------------------------------------------

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


def test_check_and_save_take_a_run_and_write_a_row_per_socket(show):
    sheet = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]
    rows = _removed(sheet["rows"], *[f"USB {n}" for n in range(2, 10)])
    rows.append({"output": "USB 2-9", "source": "MOD 1-8", "notes": "playback"})
    body = show.post("/api/build/outputs-sheet/check", json={"rows": rows}).json()
    assert body["refusals"] == []
    r = show.post("/api/build/outputs-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory), "rows": rows})
    assert r.status_code == 200, r.text
    text = (show.directory / "outputs.csv").read_text()
    assert "USB 2-9" not in text
    for n in range(2, 10):
        assert f"\nUSB {n},MOD {n - 1},playback\n" in text
    assert "\nUSB 1,AES50-A 1,\n" in text and "\nUSB 10,AES50-A 20,\n" in text
    rows = show.get("/api/build/outputs-sheet").json()["outputs_sheet"]["rows"]
    assert [r["output"] for r in rows].count("USB 5") == 1


def test_the_page_labels_a_runs_header_from_its_rows_as_they_are(show):
    """The Python suite cannot see the browser code: the run's header is
    worked out from the rows as they are now, and only falls back to the
    rows as read while a cell reads as no socket."""
    js = show.get("/static/setup.js").text
    start = js.index("function outRunWords(run)")
    body = js[start:js.index("\n  }\n", start)]
    assert "return words(outSheet.rows) || words(outSheet.original);" in body
    assert "A row \" +\n    \"may be typed as a run too (USB 1-16 from AES50-A 1-16)" in js
