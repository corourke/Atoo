"""Watch and the desk sheets.

A Save in Build's step 04 records what Apply would now write that it did not
before (`meta.sheet_pending`); Watch says each object the desk does not have
yet as a WARNING, "Sheet differs from desk" (CV023), quoting the cells. A
running Watch reads the saved plan on its next pass, without a restart, and
says when it did. R013 reads a bus the sheet gives a role by that role.

Every bundle here is captured in the test from the church desk's frozen
snapshot; nothing under `examples/` is read.
"""

from __future__ import annotations

import copy
import json
import time

import pytest

from atoo import audit, capture, sheets
from atoo.audit import ConsoleState, Severity
from atoo.snapshot import load_snapshot
from tests.test_capture import CHURCH
from tests.test_sheets import _bus_rows, _bus_save, church, show  # noqa: F401 -- fixtures

BUS_9_OUTPUTS = "LCL 1-2; AUX 1-2"


@pytest.fixture(scope="module")
def desk():
    return capture.state_from_snap(load_snapshot(CHURCH), "wing-full")


def _edited(church):  # noqa: F811 -- the fixture
    """The church plan after a Save that sends Bus 9 to AUX 1-2 too, with
    what that Save leaves for Apply."""
    before_rows = _bus_rows(church)
    after_rows = copy.deepcopy(before_rows)
    for row in after_rows:
        if row["bus"] == "Bus 9":
            row["outputs"] = BUS_9_OUTPUTS
    result = sheets.overlay_busses(church.plan, after_rows, before=before_rows)
    assert result.refusals == []
    cells = sheets.bus_cells(before_rows, after_rows, result.plan)
    plan = copy.deepcopy(result.plan)
    plan.setdefault("meta", {})["sheet_pending"] = sheets.pending_writes(
        church.plan, plan, cells)
    return plan


# -- what a Save leaves for Apply -----------------------------------------------------


def test_a_save_records_the_writes_it_leaves_and_the_cells_that_asked(church):  # noqa: F811
    [group] = _edited(church)["meta"]["sheet_pending"]
    assert group["object"] == "bus 9 (Presentr)"
    assert group["cells"] == [f'busses.csv, Bus 9 "Presentr", outputs: {BUS_9_OUTPUTS}']
    addresses = {w["address"] for w in group["writes"]}
    assert any(a.startswith("/io/out/AUX/1/") for a in addresses)
    assert any(a.startswith("/io/out/AUX/2/") for a in addresses)


def test_a_later_save_keeps_what_an_earlier_one_left(church):  # noqa: F811
    plan = _edited(church)
    earlier = plan["meta"]["sheet_pending"]
    again = sheets.pending_writes(plan, copy.deepcopy(plan), {}, earlier)
    assert again == earlier


def test_a_renamed_input_is_named_by_its_cell(church):  # noqa: F811
    text = church.input_csv()
    lines = text.splitlines()
    header, first = lines[0], lines[1]
    columns = header.split(",")
    values = first.split(",")
    name = values[columns.index("name")]
    values[columns.index("name")] = name + " 2"
    after = "\n".join([header, ",".join(values)] + lines[2:]) + "\n"
    lines = list(range(len(sheets.parse_input_list(after, include_skipped=True))))
    result = sheets.overlay_inputs(copy.deepcopy(church.plan), text, after, lines)
    cells = sheets.input_cells(text, after, lines, result.plan)
    [(label, quoted)] = cells.items()
    assert label.startswith("ch ") and f"name: {name} 2" in quoted[0]


# -- CV023, Sheet differs from desk ---------------------------------------------------


def test_a_desk_without_the_edit_is_said_once_per_object_quoting_the_cell(church, desk):  # noqa: F811
    [finding] = audit.sheet_differs_findings(desk, _edited(church))
    assert finding.rule_id == "CV023" and finding.severity == Severity.WARNING
    assert finding.title == "Sheet Differs From Desk" and finding.category == "sheets"
    assert finding.detail.startswith(
        f'BUS 9 "Presentr": "busses.csv, Bus 9 "Presentr", outputs: {BUS_9_OUTPUTS}."')
    assert "Nothing is written until you apply it, or undo the edit." in finding.detail
    # The bus first, so the page's Where is the bus, then what differs.
    assert finding.addresses[0] == "/bus/9"
    assert all(a.startswith("/io/out/AUX/") for a in finding.addresses[1:])


def test_a_desk_that_has_the_edit_says_nothing(church, desk):  # noqa: F811
    plan = _edited(church)
    values = dict(desk.values)
    for group in plan["meta"]["sheet_pending"]:
        for write in group["writes"]:
            values[write["address"]] = write["value"]
    assert audit.sheet_differs_findings(ConsoleState(values=values, console_model="wing-full"),
                                        plan) == []


def test_what_was_not_read_is_not_said(church):  # noqa: F811
    assert audit.sheet_differs_findings(ConsoleState(values={"/bus/9/name": "Presentr"}),
                                        _edited(church)) == []


def test_the_rule_is_bound_only_when_a_save_left_something(church, tmp_path):  # noqa: F811
    assert audit.sheet_differs_rule(church.plan) is None
    rule = audit.sheet_differs_rule(_edited(church))
    assert (rule.id, rule.severity) == ("CV023", Severity.WARNING)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_edited(church)), encoding="utf-8")
    assert "CV023" in {r.id for r in audit.with_plan_rules(audit.DEFAULT_RULES, path)}


# -- R013 reads the bus's role ---------------------------------------------------------


def _r013(plan, desk):
    [rule] = [r for r in audit.split_path_rules(audit.DEFAULT_RULES, plan) if r.id == "R013"]
    return rule.check(desk)


def test_a_parallel_bus_is_said_as_asked_for_and_quotes_its_cell(church, desk):  # noqa: F811
    plan = copy.deepcopy(church.plan)
    plan["busses"]["Drums Comp"]["role"] = "parallel"
    titles = [f.title for f in _r013(plan, desk)]
    assert "Parallel Bus Asked For" in titles
    [finding] = [f for f in _r013(plan, desk) if f.title == "Parallel Bus Asked For"]
    assert finding.detail.startswith('"busses.csv, Bus 2 "Drums Comp", role: parallel."')
    assert "parallel processing" in finding.detail


def test_an_fx_bus_reads_as_effect_sends(church, desk):  # noqa: F811
    plan = copy.deepcopy(church.plan)
    fx = [name for name, b in plan["busses"].items() if b.get("role") == "fx"]
    if not fx:
        pytest.skip("the church capture gives no bus the fx role")
    assert "Read As Effect Sends" in {f.title for f in _r013(plan, desk)}


def test_without_a_role_the_split_is_said_as_before(church, desk):  # noqa: F811
    plan = copy.deepcopy(church.plan)
    for entry in plan["busses"].values():
        entry.pop("role", None)
    assert {f.title for f in _r013(plan, desk)} <= {"Signal Split Asked For"}


# -- a Save while Watch runs ------------------------------------------------------------


def _small_desk(desk):
    """Only what Bus 9 and its sockets read as, so a pass is quick."""
    keep = ("/bus/9/", "/io/out/AUX/1/", "/io/out/AUX/2/")
    return ConsoleState(values={a: v for a, v in desk.values.items() if a.startswith(keep)},
                        console_model="wing-full")


def _wait_for(predicate, what, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        found = predicate()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def test_a_running_watch_reads_the_saved_sheet_without_a_restart(show, desk, monkeypatch):  # noqa: F811
    from atoo import webui

    state = _small_desk(desk)
    monkeypatch.setattr(webui, "console_provider_factory",
                        lambda address, **kw: ((lambda names=None: copy.deepcopy(state)), None))
    r = show.post("/api/watch/start", json={"source": "console", "console": "192.0.2.1",
                                            "interval": 0.1})
    assert r.status_code == 200, r.text
    session = show.app.state.session
    try:
        _wait_for(lambda: session._last_payload, "a first pass")
        r = _bus_save(show, {"Bus 9": {"outputs": BUS_9_OUTPUTS}})
        assert r.status_code == 200, r.text
        payload = _wait_for(lambda: (session._last_payload or {}).get("sheet_read")
                            and session._last_payload, "the pass after the Save")
    finally:
        show.post("/api/watch/stop")
    read = payload["sheet_read"]
    assert read["sheet"] == "busses.csv" and read["saved_at"] and read["read_at"]
    assert read["waiting"] == 1
    [finding] = [f for f in payload["all_findings"] if f["rule_id"] == "CV023"]
    assert finding["severity"] == "warning" and BUS_9_OUTPUTS in finding["detail"]
    # The Save's own change to plan.json is not a rebuild: no W004.
    assert "W004" not in {n["rule_id"] for n in payload.get("notes") or []}


def test_a_pass_whose_reading_came_before_the_save_has_not_read_it():
    from atoo.webui import WatchSession

    session = WatchSession()
    session._readings = 3
    session._sheet_read = {"sheet": "busses.csv", "saved_at": "t", "read_at": None, "after": 3}
    payload = {"at": "now", "all_findings": []}
    session._with_sheet_read(payload)
    assert "sheet_read" not in payload
    session._readings = 4
    session._with_sheet_read(payload)
    assert payload["sheet_read"] == {"sheet": "busses.csv", "saved_at": "t", "read_at": "now",
                                     "waiting": 0}


def test_a_save_to_another_show_leaves_the_watch_alone(tmp_path):
    from atoo.webui import WatchSession

    session = WatchSession()
    session.running, session.rules, session.unbound_rules = True, [], []
    session.plan_path = str(tmp_path / "watched" / "plan.json")
    assert not session.follow_sheet_save(tmp_path / "other" / "plan.json", lambda rules: rules,
                                         sheet="busses.csv", saved_at="t")
    assert session._sheet_read is None


# -- Make a show from this desk, while Watch runs with no show --------------------------


def test_a_watch_with_no_show_takes_the_plan_of_the_show_opened_since(tmp_path, church, desk,  # noqa: F811
                                                                     monkeypatch):
    """The church desk's splits are R012 WARNINGs with no plan; once a show
    captured from it is open, the next pass reads them by the plan (R013,
    INFO) and W005 goes, with no restart."""
    from atoo import webui
    from atoo.webui import create_app
    from tests.test_sheets import fastapi_testclient

    directory = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(church), directory, evidence_name="church.snap",
                         evidence=b"{}")
    monkeypatch.setattr(webui, "console_provider_factory",
                        lambda address, **kw: ((lambda names=None: copy.deepcopy(desk)), None))
    with fastapi_testclient.TestClient(create_app()) as c:
        session = c.app.state.session
        assert c.post("/api/watch/start", json={"source": "console", "console": "192.0.2.1",
                                                "interval": 0.1}).status_code == 200
        try:
            first = _wait_for(lambda: session._last_payload, "a first pass", timeout=60)
            assert "W005" in {n["rule_id"] for n in first["notes"]}
            assert c.post("/api/bundle/open", json={"directory": str(directory)}).status_code == 200
            assert session.plan_path == str(directory / "plan.json")
            after = _wait_for(lambda: session._last_payload is not first
                              and "W005" not in {n["rule_id"] for n in session._last_payload["notes"]}
                              and session._last_payload, "a pass with the plan", timeout=60)
        finally:
            c.post("/api/watch/stop")
    warned = {f["rule_id"] for f in first["all_findings"] if f["severity"] == "warning"}
    assert "R012" in warned
    assert "R012" not in {f["rule_id"] for f in after["all_findings"]
                          if f["severity"] == "warning"}
    assert "R013" in {f["rule_id"] for f in after["all_findings"]}


def test_a_watch_bound_to_a_plan_keeps_it_when_another_show_opens(tmp_path):
    from atoo.webui import WatchSession

    session = WatchSession()
    session.running, session.rules, session.unbound_rules = True, [], []
    session.plan_path = str(tmp_path / "watched" / "plan.json")
    assert not session.take_plan(tmp_path / "other" / "plan.json", lambda rules: rules)
    assert session.plan_path == str(tmp_path / "watched" / "plan.json")


def test_an_edit_undone_and_saved_waits_for_nothing(church, desk):  # noqa: F811
    """Undo in the sheet, Save: the desk already has what the plan now says,
    so Sheet differs from desk clears without an Apply."""
    edited = _edited(church)
    undone = copy.deepcopy(church.plan)
    pending = sheets.pending_writes(edited, undone, {}, edited["meta"]["sheet_pending"])
    undone.setdefault("meta", {})["sheet_pending"] = pending
    assert audit.sheet_differs_findings(desk, undone) == []
