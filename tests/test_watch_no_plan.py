"""Watch says, once and at INFO, when it is judging the desk without the
show's plan (W005): none was given, or the one it was given could not be read.
The bundles are built here, none from `examples/`."""

from __future__ import annotations

import json
import time

import pytest

from atoo import audit
from atoo.audit import DEFAULT_RULES, ConsoleState, Severity
from atoo.cli import main
from atoo.watch import NO_PLAN_RULE_ID, no_plan_note, plan_notes, watch

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def _desk() -> dict:
    return {"/ch/1/name": "Kick", "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1}


@pytest.fixture
def state_file(tmp_path):
    path = tmp_path / "desk.state.json"
    path.write_text(json.dumps(_desk()), encoding="utf-8")
    return path


def _show(tmp_path, plan_text: str | None):
    show = tmp_path / "show"
    show.mkdir()
    if plan_text is not None:
        (show / "plan.json").write_text(plan_text, encoding="utf-8")
    return show


# --------------------------------------------------------------------------
# What is off comes from the rules, not a list kept beside them
# --------------------------------------------------------------------------


def test_the_checks_named_are_exactly_the_rules_that_take_a_plan():
    plan = {"channels": [{"channel": 1, "name": "Kick", "bus_sends": [{"bus": 1, "level": -10}],
                          "phantom": True, "routes": [{"to": "bus", "number": 1}]}],
            "busses": {"Mon": {"index": 1, "width": "stereo"}}}
    judged, absent = audit.rules_needing_a_plan()
    bound = {rid for rid, _ in judged}
    assert bound == set(audit.PLAN_REBOUND_RULES) | set(audit.PLAN_SPLIT_PATH_RULE_IDS)
    assert bound <= {rule.id for rule in DEFAULT_RULES}
    # a rule a factory builds carries the id and title the list names
    built = []
    for rid, title, factory in audit.PLAN_ADDED_RULES:
        rule = factory(plan)
        if rule is not None:
            assert (rule.id, rule.title) == (rid, title)
            built.append(rid)
    assert {"CV006", "CV018"} <= set(built)
    assert len({rid for rid, _ in absent}) == len(absent)


def test_with_plan_rules_and_the_list_cannot_disagree(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"channels": [{"channel": 1, "name": "K"}]}), encoding="utf-8")
    after = {r.id for r in audit.with_plan_rules(DEFAULT_RULES, path)}
    before = {r.id for r in DEFAULT_RULES}
    assert before <= after
    assert after - before <= {rid for rid, _ in audit.rules_needing_a_plan()[1]}


# --------------------------------------------------------------------------
# The note
# --------------------------------------------------------------------------


def test_no_plan_counts_the_checks_that_are_off_and_says_how_to_start_with_one():
    """Two sentences, counts not lists: the Rules reference names the rules."""
    note = no_plan_note()
    assert (note.rule_id, note.severity) == (NO_PLAN_RULE_ID, Severity.INFO)
    judged, absent = audit.rules_needing_a_plan()
    assert f"the {len(absent)} checks that compare the desk with the plan are off" in note.message
    assert f"{len(judged)} others" in note.message
    assert "--show DIR" in note.message and "open the show on the Watch page" in note.message
    assert not any(rid in note.message for rid, _ in judged + absent)
    assert len(note.message) < 300


def test_an_unreadable_plan_names_the_file_and_the_reason(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{not json", encoding="utf-8")
    [note] = plan_notes(path)()[:1]
    assert note.rule_id == NO_PLAN_RULE_ID
    assert str(path) in note.message and "not valid JSON" in note.message

    path.write_text("[1, 2]", encoding="utf-8")
    assert "is not a JSON object" in plan_notes(path)()[0].message

    gone = tmp_path / "gone.json"
    [note] = plan_notes(gone)()[:1]
    assert str(gone) in note.message and "No such file" in note.message


def test_a_readable_plan_has_no_such_note(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{}", encoding="utf-8")
    assert plan_notes(path)() == []


def test_an_unreadable_plan_that_is_mended_is_said_as_a_change(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text("{oops", encoding="utf-8")
    notes = plan_notes(path)
    path.write_text("{}", encoding="utf-8")
    assert [n.rule_id for n in notes()] == [NO_PLAN_RULE_ID, "W004"]


def test_watch_carries_it_every_pass_as_part_of_the_baseline():
    events = list(watch(lambda: ConsoleState(_desk()), rules=list(DEFAULT_RULES),
                        max_iterations=3, sleep=lambda _s: None, session_notes=plan_notes(None)))
    assert all(any(f.rule_id == NO_PLAN_RULE_ID for f in e.all_findings) for e in events)
    # in the baseline and kept: never NEW, never CLEARED, as W001 is
    assert not [f for e in events for f in e.new_findings + e.cleared_findings
                if f.rule_id == NO_PLAN_RULE_ID]


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_watch_without_a_show_says_so_once_at_start(state_file, capsys):
    assert main(["watch", "--state-sequence", str(state_file), "--count", "2"]) == 0
    out = capsys.readouterr().out
    assert out.count("[INFO] W005 Watching without a plan") == 1
    assert "checks that compare the desk with the plan are off" in out


def test_watch_with_a_show_whose_plan_is_broken_says_which_file_and_why(
        tmp_path, state_file, capsys):
    show = _show(tmp_path, "{not json")
    assert main(["watch", "--show", str(show), "--state-sequence", str(state_file),
                 "--count", "1"]) == 0
    out = capsys.readouterr().out
    assert "[INFO] W005 The plan could not be read" in out
    assert str(show / "plan.json") in out and "not valid JSON" in out


def test_watch_with_a_show_that_has_no_plan_file_says_so(tmp_path, state_file, capsys):
    show = _show(tmp_path, None)
    main(["watch", "--show", str(show), "--state-sequence", str(state_file), "--count", "1"])
    out = capsys.readouterr().out
    assert "W005 The plan could not be read" in out and "No such file" in out


def test_watch_with_a_good_plan_says_nothing_of_it(tmp_path, state_file, capsys):
    show = _show(tmp_path, "{}")
    main(["watch", "--show", str(show), "--state-sequence", str(state_file), "--count", "1"])
    assert "W005" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# The Watch page
# --------------------------------------------------------------------------


def _wait(predicate, what, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _first_event(client):
    with client.websocket_connect("/ws/watch") as ws:
        while True:
            msg = ws.receive_json()
            if msg["type"] == "event":
                return msg


def _page_watch(show_dir):
    """The Watch page's server over the Demo console, with `show_dir` the open
    show (None: no show open). Demo opens the packaged demo show, which has a
    plan, so the open show is swapped after."""
    from atoo import bundle
    from atoo.webui import create_app

    client = fastapi_testclient.TestClient(create_app())
    client.__enter__()
    client.post("/api/console", json={"demo": True})
    client.app.state.bundle = bundle.load(show_dir) if show_dir else None
    return client


def _page_notes(client):
    assert client.post("/api/watch/start",
                       json={"source": "console", "interval": 0.1}).status_code == 200
    event = _first_event(client)
    client.post("/api/watch/stop")
    client.__exit__(None, None, None)
    return [n for n in event["notes"] if n["rule_id"] == NO_PLAN_RULE_ID]


def test_the_watch_page_with_no_show_open_carries_the_note():
    [note] = _page_notes(_page_watch(None))
    assert note["group"] == "Plan" and note["severity"] == "info"
    assert "open the show on the Watch page" in note["detail"]


def test_the_watch_page_with_an_unreadable_plan_names_the_file(tmp_path):
    show = _show(tmp_path, "{not json")
    [note] = _page_notes(_page_watch(show))
    assert str(show / "plan.json") in note["detail"] and "not valid JSON" in note["detail"]


def test_the_watch_page_with_a_good_plan_has_none(tmp_path):
    assert _page_notes(_page_watch(_show(tmp_path, "{}"))) == []
