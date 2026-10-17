"""Apply announces the fixed defaults it writes on every plan, once each,
at INFO.

* Every strip a plan builds goes back to its main input
  (`altsrc = 0`). Kept -- a show apply means stage inputs live -- and now
  counted in apply's report, with how many were on their alternate.
* Direct Main routes and Matrix feeds are written at unity, post-fader.
  Announced once per plan in apply's report (not verify's findings).

Plans come from `tests/fixtures/`.
"""

from __future__ import annotations

from atoo.apply import apply_plan
from tests.test_apply import FakeConsole, compiled


def _plan() -> dict:
    plan = compiled("smallband")
    plan["meta"] = {"console_model": "wing-compact"}
    return plan


def _notes(result) -> list[str]:
    return [w for w in result.warnings if w.startswith("INFO ")]


def test_apply_counts_the_strips_it_returns_to_their_main_input():
    plan = _plan()
    strips = len(plan["channels"])
    result = apply_plan(plan, FakeConsole(), dry_run=True)
    alt = [n for n in _notes(result) if "set to their main input" in n]
    assert alt == [f"INFO {strips} strip(s) set to their main input (not their alternate) "
                   "-- a show apply means stage inputs live"]


def test_apply_says_how_many_strips_were_on_their_alternate():
    plan = _plan()
    first = plan["channels"][0]
    base = f"/{first.get('bank', 'ch')}/{first['channel']}"
    desk = FakeConsole({f"{base}/in/set/altsrc": (1, "i")})
    result = apply_plan(plan, desk, dry_run=True)
    alt = next(n for n in _notes(result) if "set to their main input" in n)
    assert "; 1 of them read as on their alternate before this run --" in alt


def test_apply_announces_unity_post_fader_routes_once():
    plan = _plan()
    plan["channels"][0]["main_routes"] = [{"index": 1}]
    plan["channels"][1]["main_routes"] = [{"index": 1}]
    result = apply_plan(plan, FakeConsole(), dry_run=True)
    unity = [n for n in _notes(result) if "unity" in n]
    assert len(unity) == 1
    assert unity[0].startswith("INFO 2 direct Main route(s)")
    assert "set to unity (0 dB), post-fader" in unity[0]


def test_no_route_no_unity_note_and_notes_are_not_counted_as_warnings():
    plan = _plan()
    for ch in plan["channels"]:
        ch["main_routes"] = []
    for out in plan.get("outputs", {}).values():
        out.pop("fed_by", None)
    result = apply_plan(plan, FakeConsole(), dry_run=True)
    assert not [n for n in _notes(result) if "unity" in n]
    real = [w for w in result.warnings if not w.startswith("INFO ")]
    summary = result.summary()
    if not real:
        assert "warning(s)" not in summary
