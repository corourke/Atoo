"""`user.csv`: the USR slots a show uses, one row each, in the desk's own words
(built).

A capture writes it from the slots a channel or an output reads; a build lays
it on, a filled row winning for its slot; Build 04's table saves it whole. The
desk is the church's full-size WING, from its frozen snapshot, with USR 3 set
to CH 10 at POST and read by USB 29, and USR 25 assigned but read by nothing
(`tests/test_user_sources_apply.py`).
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from atoo import capture, plan_freshness, user_sheet
from tests.test_user_sources_apply import _church_with_usr

from conftest import require_fastapi_testclient  # noqa: E402


@pytest.fixture(scope="module")
def church() -> capture.Capture:
    return capture.capture_desk(_church_with_usr(), console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _rows(**cells) -> list[dict]:
    return [dict({"slot": "", "source": "", "tap": "", "leg": "", "name": ""}, **cells)]


# -- capture --------------------------------------------------------------------------


def test_a_capture_writes_one_row_per_slot_something_reads(church, tmp_path):
    assert church.user_csv() == "slot,source,tap,leg,name\nUSR 3,CH 10,POST,L+R,Lead post\n"
    assert "user.csv     1 USR slot: 1 user signal" in capture.summary_lines(church)
    show = tmp_path / "church"
    capture.write_bundle(church, show, evidence_name="church.snap", evidence=b"{}")
    assert (show / "user.csv").read_text() == church.user_csv()
    plan = json.loads((show / "plan.json").read_text())
    assert plan["meta"]["user_sheet"]["sha256"]
    assert user_sheet.readers(plan) == {3: ["USB 29"]}


def test_a_desk_with_no_slot_in_use_gets_no_user_csv(tmp_path):
    from atoo.snapshot import load_snapshot
    from tests.test_capture import CHURCH

    plain = capture.capture_desk(capture.state_from_snap(load_snapshot(CHURCH), "wing-full"),
                                 console_model="wing-full", made_from="snap", captured="x",
                                 snapshot="x")
    capture.write_bundle(plain, tmp_path / "plain", evidence_name="c.snap", evidence=b"{}")
    assert not (tmp_path / "plain" / "user.csv").exists()
    assert not [line for line in capture.summary_lines(plain) if line.startswith("user.csv")]


def test_the_sheet_laid_back_on_its_own_plan_changes_nothing(church):
    rows = user_sheet.read_rows(church.user_csv())
    result = user_sheet.overlay(church.plan, rows, complete=True, console_model="wing-full")
    assert result.refusals == [] and result.changes == []
    assert result.plan == church.plan


# -- a build, and a Save ---------------------------------------------------------------


def test_a_build_takes_only_the_rows_it_is_given(church):
    """A filled row wins for its slot; a blank tap keeps the plan's; a slot the
    sheet does not name is left to the plan; OFF takes a slot out."""
    plan = copy.deepcopy(church.plan)
    plan["user_sources"].append({"slot": 25, "source": {"group": "LCL", "index": 5}})
    result = user_sheet.overlay(
        plan, _rows(slot="USR 3", source="ch 11", tap="pre")
        + _rows(slot="4", source="Bus 8", leg="L", name="Stream L"),
        complete=False, console_model="wing-full")
    assert result.refusals == []
    assert result.changes == [
        "USR 3 takes CH 11 PRE L+R (Lead post) (was CH 10 POST L+R (Lead post))",
        "USR 4 takes BUS 8 POST L (Stream L)"]
    assert [u["slot"] for u in result.plan["user_sources"]] == [3, 4, 25]
    off = user_sheet.overlay(plan, _rows(slot="USR 25", source="OFF"), complete=False)
    assert off.changes == ["USR 25 taken out (was LCL 5)"]
    assert [u["slot"] for u in off.plan["user_sources"]] == [3]


def test_a_save_is_the_whole_list(church):
    result = user_sheet.overlay(church.plan, _rows(slot="USR 25", source="LCL 5", name="Mic 3"),
                                complete=True, console_model="wing-full")
    assert result.changes == ["USR 3 taken out (was CH 10 POST L+R (Lead post))",
                              "USR 25 takes LCL 5 (Mic 3)"]
    assert result.plan["user_sources"] == [
        {"slot": 25, "source": {"group": "LCL", "index": 5}, "name": "Mic 3"}]


@pytest.mark.parametrize("cells, reason", [
    ({"slot": "USR 25", "source": "LCL 5", "tap": "POST"},
     "USR 25 is a user patch, which takes an input socket as it is -- only a user signal "
     "(USR 1-24) has a tap"),
    ({"slot": "USR 25", "source": "CH 3"},
     "USR 25 is a user patch, which takes an input socket"),
    ({"slot": "USR 4", "source": "LCL 2"},
     "USR 4 is a user signal, which takes a strip"),
    ({"slot": "USR 57", "source": "LCL 2"},
     "is not a USR slot: the desk has USR 1-24 (user signals) and USR 25-56 (user patches)"),
    ({"slot": "USR 4", "source": "Dante 3"},
     "is not a source a USR slot takes"),
    ({"slot": "USR 4", "source": "CH 3", "tap": "MID"}, "a user signal's tap is PRE or POST"),
    ({"slot": "USR 4", "source": "CH 99"},
     "CH 99 does not exist -- the console has 40 of them (user-source.index-out-of-range)"),
])
def test_what_cannot_work_is_refused_naming_the_row(church, cells, reason):
    result = user_sheet.overlay(church.plan, _rows(**cells), complete=False,
                                console_model="wing-full")
    assert any(reason in r.text() for r in result.refusals), [r.text() for r in result.refusals]


def test_a_slot_listed_twice_is_refused(church):
    result = user_sheet.overlay(church.plan, _rows(slot="USR 4", source="CH 1")
                                + _rows(slot="usr 4", source="CH 2"), complete=True)
    assert [r.text() for r in result.refusals] == [
        "user.csv, USR 4, slot 'usr 4': is listed twice (lines 2 and 3): one slot holds one "
        "source"]


def test_a_build_lays_it_on_and_records_it(church, tmp_path):
    from atoo import cli

    show = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(church), show, evidence_name="church.snap", evidence=b"{}")
    (show / "user.csv").write_text("slot,source,tap,leg,name\nUSR 3,CH 11,PRE,,\n")
    plan = copy.deepcopy(church.plan)
    findings = cli._lay_on_sheets(plan, SimpleNamespace(directory=show),
                                  (show / "input.csv").read_text(), "wing-full")
    assert [f.message for f in findings if f.code == "build.user-sheet"] == [
        "user.csv wins over the conventions: USR 3 takes CH 11 PRE L+R (Lead post) "
        "(was CH 10 POST L+R (Lead post))."]
    assert plan["user_sources"][0]["source"] == {"group": "CH", "index": 11}
    # The capture's plan recorded the sheet as written; the edit reads Stale.
    recorded = json.loads((show / "plan.json").read_text())
    fresh = plan_freshness.assess(recorded, conventions=None, instructions=None,
                                  input_list=None, user_sheet=show / "user.csv")
    assert "plan.user-sheet-edited" in {r["code"] for r in fresh["reasons"]}


def test_a_refused_row_stops_the_build(church, tmp_path):
    from atoo import cli

    show = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(church), show, evidence_name="church.snap", evidence=b"{}")
    (show / "user.csv").write_text("slot,source,tap,leg,name\nUSR 30,LCL 5,POST,,\n")
    with pytest.raises(cli.SheetRefused) as refused:
        cli._lay_on_sheets(copy.deepcopy(church.plan), SimpleNamespace(directory=show),
                           (show / "input.csv").read_text(), "wing-full")
    assert "user.csv, USR 30, tap 'POST': USR 30 is a user patch" in str(refused.value)


# -- Build 04's table: read, check, Save -----------------------------------------------

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


def test_the_table_reads_the_sheet_and_what_reads_each_slot(show):
    body = show.get("/api/build/user-sheet").json()
    assert body["user_sheet"]["rows"] == [
        {"slot": "USR 3", "source": "CH 10", "tap": "POST", "leg": "L+R", "name": "Lead post"}]
    assert body["readers"] == {"3": ["USB 29"]} and body["plan_behind"] is False


def test_check_says_what_a_save_would_refuse(show):
    body = show.post("/api/build/user-sheet/check", json={"rows": _rows(
        slot="USR 25", source="LCL 5", tap="POST")}).json()
    assert [r["column"] for r in body["refusals"]] == ["tap"]


def test_save_writes_the_sheet_and_updates_the_plan(show):
    sheet = show.get("/api/build/user-sheet").json()["user_sheet"]
    rows = sheet["rows"] + _rows(slot="usr 25", source="lcl 5", name="Mic 3 split")
    r = show.post("/api/build/user-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory), "rows": rows})
    assert r.status_code == 200, r.text
    assert "Saved church/user.csv" in r.json()["message"]
    assert "USR 25 takes LCL 5 (Mic 3 split)" in r.json()["message"]
    # Written in the desk's words, whatever was typed.
    assert (show.directory / "user.csv").read_text() == (
        "slot,source,tap,leg,name\nUSR 3,CH 10,POST,L+R,Lead post\nUSR 25,LCL 5,,,Mic 3 split\n")
    plan = json.loads((show.directory / "plan.json").read_text())
    assert plan["user_sources"][-1] == {"slot": 25, "source": {"group": "LCL", "index": 5},
                                        "name": "Mic 3 split"}
    freshness = show.get("/api/build/sources").json()["plan_freshness"]
    assert not any(r["slot"] == "user_sheet" for r in freshness["reasons"])


def test_a_refused_save_writes_nothing(show):
    sheet = show.get("/api/build/user-sheet").json()["user_sheet"]
    before = (show.directory / "user.csv").read_text()
    r = show.post("/api/build/user-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory),
        "rows": _rows(slot="USR 25", source="LCL 5", tap="POST")})
    assert r.status_code == 400 and "user.csv" in r.json()["error"]
    assert (show.directory / "user.csv").read_text() == before


def test_a_sheet_changed_on_disk_is_not_overwritten(show):
    sheet = show.get("/api/build/user-sheet").json()["user_sheet"]
    (show.directory / "user.csv").write_text("slot,source,tap,leg,name\n")
    r = show.post("/api/build/user-sheet/save", json={
        "expected_sha256": sheet["sha256"], "expected_bundle": str(show.directory),
        "rows": sheet["rows"]})
    assert r.status_code == 409 and r.json()["stale"] == "file"


def test_build_04_serves_the_table(show):
    """The Python suite cannot see the browser code; this is the check that the
    page still asks for the sheet and draws its table."""
    js = show.get("/static/setup.js").text
    for wanted in ('fetch("/api/build/user-sheet")', '"/api/build/user-sheet/check"',
                   '"/api/build/user-sheet/save"', 'id="plan-user-table"', "Save user.csv",
                   "Add a slot"):
        assert wanted in js, wanted
    assert "#plan-user-table" in show.get("/static/styles.css").text
