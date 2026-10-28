"""What the Watch page's alert table holds.

* **Notes are not alerts.** A note about the watch itself (a
  scoped name resolved at Start, a condition not watched, W001's
  name refresh) is a `watch.WatchNote`. The CLI prints it at its
  severity as before; the page shows it in a status line, from the
  frame's `notes`, and never as a row.
* **One fault, one row.** A built-in finding whose addresses are
  all cited by a firing `WATCH:` condition is folded under that
  condition's row (`also`), and comes back as its own row when the
  condition stops firing.

Every state here is built in the test; nothing reads `examples/`.
"""

from __future__ import annotations

import json

from conftest import require_fastapi_testclient

from atoo.audit import ConsoleState, DEFAULT_RULES, Severity
from atoo.diagnostics import Diagnostic
from atoo.watch import (WatchEvent, WatchNote, finding_key, name_refresh_note, present_findings,
                             watch)
from atoo.watch_conditions import build_watch_rules, parse_watch_conditions


def _cond(**kw):
    base = {"id": "band-open", "description": "The Band DCA stays open",
            "channel": "DCA Band", "field": "fader_db", "operator": "<", "value": -20,
            "severity": "warning"}
    base.update(kw)
    return base


def _rules(*conds):
    return build_watch_rules(parse_watch_conditions(json.dumps({"version": 2, "watch_conditions": list(conds)})))


def _state(dca_fdr: float, **extra) -> ConsoleState:
    values = {"/dca/1/name": "Band", "/dca/1/fdr": dca_fdr, "/dca/1/mute": 0,
              "/main/1/name": "PA", "/main/1/mute": 0}
    values.update(extra)
    return ConsoleState(values)


def _builtin(code, addresses, severity=Severity.WARNING):
    return Diagnostic.audit(code, severity, "channels", "A Built-in Rule", "detail", addresses)


# ---- Notes ----------------------------------------------------------


def test_a_scoped_name_resolution_is_a_note_with_a_short_form():
    [rule] = _rules(_cond())
    findings = rule.check(_state(0.0))
    [note] = findings
    assert isinstance(note, WatchNote)
    assert note.severity == Severity.INFO
    assert note.group == "Resolved at Start"
    assert note.summary == "DCA Band → DCA 1"
    # The CLI's sentence is unchanged.
    assert note.message.startswith("DCA Band resolved to DCA 1 at Start;")


def test_a_scoped_name_that_matches_nothing_is_a_warning_note_naming_the_condition():
    [rule] = _rules(_cond(channel="DCA Horns"))
    [note] = rule.check(_state(0.0))
    assert isinstance(note, WatchNote)
    assert note.severity == Severity.WARNING
    assert note.group == "Not watched"
    assert "band-open" in note.summary


def test_main_alone_and_the_name_refresh_note_are_notes():
    [rule] = _rules(_cond(id="pa", channel="Main", field="muted", operator="!=", value=False))
    notes = [f for f in rule.check(_state(0.0)) if isinstance(f, WatchNote)]
    assert [n.summary for n in notes] == ["Main → MAIN 1"]
    refresh = name_refresh_note(5)
    assert isinstance(refresh, WatchNote) and refresh.code == "W001"
    assert refresh.group == "Names"


def test_a_violation_is_not_a_note():
    [rule] = _rules(_cond())
    violation = [f for f in rule.check(_state(-144.0)) if not isinstance(f, WatchNote)]
    assert len(violation) == 1 and violation[0].rule_id == "WATCH:band-open"


def test_present_findings_moves_notes_out_of_the_alerts():
    [rule] = _rules(_cond())
    shown = present_findings(rule.check(_state(-144.0)))
    assert [f.rule_id for f in shown.alerts] == ["WATCH:band-open"]
    assert [n.summary for n in shown.notes] == ["DCA Band → DCA 1"]


# ---- Folding --------------------------------------------------------


def test_a_builtin_on_the_same_strip_and_field_folds_under_the_condition():
    [rule] = _rules(_cond())
    condition = [f for f in rule.check(_state(-144.0)) if not isinstance(f, WatchNote)][0]
    same = _builtin("CH002", ("/dca/1/fdr",))
    other = _builtin("L002", ("/ch/7/fdr",), Severity.INFO)
    shown = present_findings([same, condition, other])
    assert [f.rule_id for f in shown.alerts] == ["WATCH:band-open", "L002"]
    assert shown.folded == {finding_key(condition): [same]}


def test_a_builtin_citing_more_than_the_condition_keeps_its_own_row():
    [rule] = _rules(_cond())
    condition = [f for f in rule.check(_state(-144.0)) if not isinstance(f, WatchNote)][0]
    wider = _builtin("X", ("/dca/1/fdr", "/ch/3/fdr"))
    shown = present_findings([condition, wider])
    assert [f.rule_id for f in shown.alerts] == ["WATCH:band-open", "X"]
    assert shown.folded == {}


def test_the_condition_keeps_its_own_severity_when_a_builtin_folds_under_it():
    """The engineer's row is the one that matters, at the severity they
    gave it -- even when the built-in is the louder of the two."""
    [rule] = _rules(_cond(severity="info"))
    condition = [f for f in rule.check(_state(-144.0)) if not isinstance(f, WatchNote)][0]
    shown = present_findings([_builtin("CH002", ("/dca/1/fdr",), Severity.ERROR), condition])
    assert [(f.rule_id, f.severity) for f in shown.alerts] == [("WATCH:band-open", Severity.INFO)]


def test_with_no_condition_firing_a_builtin_is_its_own_row():
    shown = present_findings([_builtin("CH002", ("/dca/1/fdr",))])
    assert [f.rule_id for f in shown.alerts] == ["CH002"] and shown.folded == {}


# ---- the page's frame -----------------------------------------------------


def _frames(states, rules):
    from atoo.webui import _WatchPresenter
    presenter = _WatchPresenter()
    provider = iter(states).__next__
    return [presenter.payload(e) for e in watch(provider, rules=rules, sleep=lambda _: None)]


def _member_state(dca_fdr):
    """DCA 1 "Band" over one in-use channel: CH002 fires at the floor."""
    return _state(dca_fdr, **{"/ch/1/name": "Kick", "/ch/1/tags": "#D1", "/ch/1/mute": 0,
                              "/ch/1/fdr": 0.0, "/ch/1/main/1/on": 1,
                              "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1})


def test_the_frame_carries_notes_apart_and_folds_the_builtin():
    rules = list(DEFAULT_RULES) + _rules(_cond())
    frames = _frames([_member_state(0.0), _member_state(-144.0)], rules)
    first, second = frames
    assert not any(f["rule_id"].startswith("WATCH:") for f in first["all_findings"])
    assert [n["summary"] for n in first["notes"]] == ["DCA Band → DCA 1"]
    assert first["notes"][0]["group"] == "Resolved at Start"

    rows = {f["rule_id"]: f for f in second["all_findings"]}
    assert "CH002" not in rows, "the built-in is folded, not a second row"
    assert [g["rule_id"] for g in rows["WATCH:band-open"]["also"]] == ["CH002"]
    assert [f["rule_id"] for f in second["new_findings"]] == ["WATCH:band-open"]
    assert not any(f["rule_id"] == "CH002" for f in second["new_findings"])


def test_new_and_cleared_are_the_tables_difference_when_a_fold_comes_and_goes():
    """The built-in is in the table, the condition starts firing (the
    built-in leaves the table, folded), then the condition stops while
    the built-in still fires (it comes back as its own row)."""
    # Built-in only, then both, then built-in only again: the condition
    # is swapped in and out by rewriting the session's rule list, as the
    # page's Save does mid-watch.
    from atoo.webui import _WatchPresenter
    presenter = _WatchPresenter()
    live = list(DEFAULT_RULES)
    states = iter([_member_state(-144.0)] * 3)
    payloads = []
    for i, event in enumerate(watch(states.__next__, rules=live, sleep=lambda _: None,
                                    max_iterations=3)):
        payloads.append(presenter.payload(event))
        live[:] = list(DEFAULT_RULES) + (_rules(_cond(id=f"open-{i}", channel="DCA 1"))
                                         if i == 0 else [])
    builtin_only, both, again = payloads
    assert any(f["rule_id"] == "CH002" for f in builtin_only["all_findings"])
    assert [f["rule_id"] for f in both["cleared_findings"]] == ["CH002"]
    assert [f["rule_id"] for f in both["new_findings"]] == ["WATCH:open-0"]
    assert [f["rule_id"] for f in again["new_findings"]] == ["CH002"]
    assert [f["rule_id"] for f in again["cleared_findings"]] == ["WATCH:open-0"]


# ---- the served page (the suite cannot see the browser) ------------------


def test_the_watch_page_reads_notes_and_also():
    fastapi_testclient = require_fastapi_testclient()
    from atoo.webui import create_app
    with fastapi_testclient.TestClient(create_app()) as client:
        js = client.get("/static/watch.js").text
        html = client.get("/").text
        css = client.get("/static/styles.css").text
    assert 'el("watch-notes")' in js and 'id="watch-notes"' in html
    assert "payload.notes" in js and "renderNotes(" in js
    # The field names Python sends, read by the page.
    for key in ("n.group", "n.summary", "f.also", "g.rule_id", "g.title", "g.detail"):
        assert key in js, key
    assert ".finding-also" in css and ".watch-notes" in css
