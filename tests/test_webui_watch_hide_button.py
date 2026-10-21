"""Watch's Hide check box sits at the far left of every row, in the same
place whatever the row, and is a finger-sized target on a small screen.

It is a check box in the table's first column (headed "Hide"), as the
findings pane puts its own; ticked, the finding leaves the table, and in the
Suppressed list the same box is ticked and brings the finding back when
cleared. The label around the box is the 32px target; the box is drawn at the
pane's size.

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
      const row = tr.getBoundingClientRect();
      const hit = tr.querySelector('.watch-row-hide-hit').getBoundingClientRect();
      const box = tr.querySelector('input.watch-row-hide');
      const tag = tr.querySelector('.sev').getBoundingClientRect();
      return {sev: tr.querySelector('.sev').textContent, tagWidth: tag.width,
              hitFromRowLeft: hit.left - row.left, hitHeight: hit.height, hitWidth: hit.width,
              boxType: box.type, boxChecked: box.checked,
              leftOfTag: hit.right <= tag.left + 0.5};
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


def test_the_served_assets_carry_the_far_left_check_box_and_the_touch_target(url):
    import urllib.request
    css = urllib.request.urlopen(url + "static/styles.css").read().decode()
    js = urllib.request.urlopen(url + "static/watch.js").read().decode()
    html = urllib.request.urlopen(url + "static/shell.html").read().decode()
    assert '<th class="col-hide">Hide</th>' in html
    assert html.index('class="col-hide"') < html.index('class="col-sev"')
    assert re.search(r"\.watch-row-hide-hit \{[^}]*width: 32px; height: 32px", css)
    assert re.search(r"\.watch-row-hide \{[^}]*accent-color: var\(--accent\)", css)
    # The box is made as the findings pane makes its own, and added to the
    # first cell, or it floats free.
    assert 'box.type = "checkbox"' in js
    assert '<td class="col-hide"></td>' in js
    assert 'tr.querySelector(".col-hide").appendChild(makeHideCheck(f, false))' in js
    assert "makeHideButton" not in js


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_hide_box_is_at_the_far_left_in_the_same_place_on_every_row(url, theme, width):
    sync_api, path = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        try:
            m = _watch_page(browser, url, width, theme).evaluate(MEASURE)
        finally:
            browser.close()
    rows = m["rows"]
    assert [r["sev"] for r in rows] == ["Error", "Warning", "Info"], rows
    # The three tags are not the same width, or this proves nothing.
    assert len({round(r["tagWidth"]) for r in rows}) > 1, rows
    for r in rows:
        assert r["boxType"] == "checkbox" and not r["boxChecked"], r
        assert r["leftOfTag"], r
        assert r["hitFromRowLeft"] < 40, r
        assert r["hitHeight"] >= 32 and r["hitWidth"] >= 32, r
    assert max(r["hitFromRowLeft"] for r in rows) - min(r["hitFromRowLeft"] for r in rows) < 0.5, rows
    assert m["sideways"] <= 0, m


def test_ticking_a_box_hides_the_row_and_clearing_it_in_the_list_brings_it_back(url):
    sync_api, path = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        try:
            page = _watch_page(browser, url, 1280, "dark")
            first = page.locator("#alert-body tr .watch-row-hide").first
            first.focus()
            page.keyboard.press("Space")
            assert page.locator("#alert-body tr").count() == 2
            # Keyboard focus lands on the next row's box, not on <body>.
            assert page.evaluate("document.activeElement.classList.contains('watch-row-hide')")
            page.locator("#watch-suppressed > summary").click()
            hidden = page.locator("#watch-suppressed-list .watch-row-hide")
            assert hidden.count() == 1 and hidden.is_checked()
            hidden.click()
            assert page.locator("#alert-body tr").count() == 3
        finally:
            browser.close()
