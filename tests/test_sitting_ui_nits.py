"""The browser sitting's small findings (items 9 and 10).

The page code has no Python to call, so the served assets are checked for
the change, since the Python suite cannot see the browser code; the one
Python piece -- how outputs.csv writes a mono bus -- is called.
"""

from __future__ import annotations

from atoo import outputs_sheet

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()


def _assets():
    from atoo.webui import create_app

    return fastapi_testclient.TestClient(create_app())


def test_a_mono_bus_is_written_with_no_side_and_read_as_its_one_output():
    plan = {"channels": [], "outputs": {},
            "busses": {"Wedge 1": {"index": 1, "mono": True, "destination": {
                "type": "dedicated_output", "label": "Wedge 1",
                "patch": {"group": "LCL", "sockets": [3], "stated": True}}},
                       "Drums": {"index": 2, "mono": False, "destination": {
                "type": "dedicated_output", "label": "Drums",
                "patch": {"group": "LCL", "sockets": [5, 6], "stated": True}}}}}
    rows = {r["output"]: r["source"] for r in outputs_sheet.rows_from_plan(plan)}
    assert rows == {"LCL 3": "Bus 1", "LCL 5": "Bus 2 L", "LCL 6": "Bus 2 R"}
    assert outputs_sheet.parse_source("Bus 1") == (("BUS", 1), None)
    assert outputs_sheet.parse_source("Bus 2 R") == (("BUS", 4), None)


def test_the_pages_carry_the_sittings_fixes():
    with _assets() as c:
        apply_js = c.get("/static/apply.js").text
        setup_js = c.get("/static/setup.js").text
        shell_js = c.get("/static/shell.js").text
        html = c.get("/").text
    # 9: a Detail link, and ‹ ›, bring the tile they select into view.
    assert "selectTile(l.key, true)" in apply_js
    assert 't.cell.scrollIntoView({ block: "center", behavior: "smooth" })' in apply_js
    # 10: a new bus goes in its place among the busses, not at the end.
    assert "items.sort((a, b) => deskOrder(a[0]) - deskOrder(b[0]))" in setup_js
    assert "kept.splice(at < 0 ? kept.length : at, 0, row)" in setup_js
    # 10: "5 strips reach", not "reaches".
    assert 'reaches: "reach"' in shell_js and "plural([...claims][0])" in shell_js
    # 10: capture writes outputs.csv too, and says so.
    assert "into input.csv, busses.csv and outputs.csv." in html
    # 10: the pre-flight's notes are placed in Findings, not counted beside it.
    assert "\"This pre-flight's \"" in apply_js and '" under Choices"' in apply_js
