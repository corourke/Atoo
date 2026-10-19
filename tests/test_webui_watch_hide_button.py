"""Watch's Hide button sits in the same place on every row, and is a
finger-sized target on a small screen.

The button used to follow the severity tag, so its position moved with the
tag's word (ERROR, WARNING and INFO measure differently); it now sits at the
severity cell's right edge. At phone width it stacks under the tag and takes
the 32px a button takes everywhere else.

The Python suite cannot see a browser, so the first test holds the served
assets to the rule and the others measure the real page in Chromium, dark
first and then light, at laptop width and at 390px. The watch is a stand-in:
the page's status and its socket are answered by the test with a baseline of
one finding of each severity. They skip where Playwright or a Chromium is not
installed (`ATOO_TEST_CHROMIUM`). Nothing under `examples/` is read.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_ui_followups import _chromium, _serve  # noqa: E402

FINDINGS = [
    {"rule_id": "R001", "severity": "error", "category": "routing", "title": "Channel not patched",
     "detail": "Nothing is patched to the channel.", "addresses": ["/ch/1/in/conn/in"], "strip": "CH 1"},
    {"rule_id": "R002", "severity": "warning", "category": "routing", "title": "Output patch missing",
     "detail": "The output is not patched.", "addresses": ["/ch/2/in/conn/in"], "strip": "CH 2"},
    {"rule_id": "R003", "severity": "info", "category": "naming", "title": "Name was shortened",
     "detail": "The name was shortened to fit.", "addresses": ["/ch/3/name"], "strip": "CH 3"},
]

MEASURE = """() => {
  const rows = Array.from(document.querySelectorAll('#alert-body tr'));
  return {
    sideways: document.documentElement.scrollWidth - window.innerWidth,
    rows: rows.map(tr => {
      const cell = tr.querySelector('.col-sev').getBoundingClientRect();
      const tag = tr.querySelector('.sev').getBoundingClientRect();
      const btn = tr.querySelector('.watch-row-hide').getBoundingClientRect();
      return {sev: tr.querySelector('.sev').textContent, tagWidth: tag.width,
              fromCellLeft: btn.left - cell.left, fromCellRight: cell.right - btn.right,
              height: btn.height, below: btn.top >= tag.bottom - 0.5};
    }),
  };
}"""


@pytest.fixture
def url():
    app = create_app()
    address, server, thread = _serve(app)
    yield address
    server.should_exit = True
    thread.join(timeout=5)


def _watch_page(browser, address, width, theme):
    """The Watch page, showing a baseline of FINDINGS as a running watch."""
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.add_init_script(
        "try { localStorage.setItem('atoo.demoPopupSeen','1');"
        f" localStorage.setItem('atoo.theme','{theme}'); }} catch (e) {{}}")
    status = {"type": "status", "running": True, "label": "Demo rig", "virtual_soundcheck": False}
    event = {"type": "event", "iteration": 0, "baseline": True, "at": "2026-10-18T12:00:00+00:00",
             "coverage_caveat": None, "all_findings": FINDINGS, "new_findings": [],
             "cleared_findings": [], "notes": []}

    def socket(ws):
        ws.send(json.dumps(status))
        ws.send(json.dumps(event))

    page.route_web_socket("**/ws/watch", socket)
    page.route("**/api/status", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(status)))
    page.goto(address)
    page.evaluate("document.getElementById('nav-watch').click()")
    page.wait_for_selector("#alert-body tr .watch-row-hide", state="attached")
    assert page.locator("#alert-body tr").count() == len(FINDINGS)
    return page


def test_the_served_assets_carry_the_fixed_button_and_the_touch_target(url):
    import urllib.request
    css = urllib.request.urlopen(url + "static/styles.css").read().decode()
    js = urllib.request.urlopen(url + "static/watch.js").read().decode()
    assert re.search(r"#alert-table \.watch-row-hide \{ margin-left: auto; \}", css)
    assert re.search(r"#alert-table \.sev-cell \{ display: flex;", css)
    assert re.search(r"@media \(max-width: 900px\) \{\s*#alert-table \.watch-row-hide[^{]*\{ min-height: 32px; \}",
                     css)
    # The button is added to the cell the CSS lays out, or it floats free.
    assert 'class="sev-cell"' in js
    assert 'tr.querySelector(".sev-cell").appendChild(makeHideButton(f, false))' in js


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_hide_button_is_in_the_same_place_whatever_the_tags_width(url, theme):
    sync_api, path = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        try:
            m = _watch_page(browser, url, 1280, theme).evaluate(MEASURE)
        finally:
            browser.close()
    rows = m["rows"]
    assert [r["sev"] for r in rows] == ["Error", "Warning", "Info"], rows
    # The three tags are not the same width, or this proves nothing.
    assert len({round(r["tagWidth"]) for r in rows}) > 1, rows
    assert max(r["fromCellRight"] for r in rows) - min(r["fromCellRight"] for r in rows) < 0.5, rows
    assert max(r["fromCellLeft"] for r in rows) - min(r["fromCellLeft"] for r in rows) < 0.5, rows
    assert m["sideways"] <= 0, m


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_at_phone_width_the_hide_button_is_a_32px_target_and_nothing_scrolls_sideways(url, theme):
    sync_api, path = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        try:
            m = _watch_page(browser, url, 390, theme).evaluate(MEASURE)
        finally:
            browser.close()
    rows = m["rows"]
    assert len(rows) == 3
    for r in rows:
        assert r["height"] >= 32, r
        assert r["below"], r
    assert max(r["fromCellLeft"] for r in rows) - min(r["fromCellLeft"] for r in rows) < 0.5, rows
    assert m["sideways"] <= 0, m
