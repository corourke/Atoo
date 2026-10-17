"""Watch speaks in one voice, hides a finding with a labelled button, and
keeps its empty sentence true (the UI style guide).

1. **Voice.** The verdict line reads `<where>: <claim>`. A built-in finding's
   claim is its catalogue title, which is Title Case ("Main Not Patched"); it
   is sentence-cased in Watch only ("Main not patched"), so it reads like an
   engineer's own condition ("has its fader at -144 dB"). Acronyms stay.
2. **Hide.** Each alert row has a quiet **Hide** button, not a bare check box,
   with the finding named in its accessible label. The Suppressed fold lists
   it with **Show**.
3. **The empty sentence.** With no show, "Choose a console in the bar" is
   true; once a console (or the Demo) is chosen it is not, and the header tag
   no longer reads "Not connected" beside a chosen Demo.

The Python suite cannot see a browser, so the first half asserts over the
served script and stylesheet and the second drives the real page in Chromium
with the watch socket mocked, so each state is exact. The Chromium tests skip
where Playwright or a Chromium is not installed (`ATOO_TEST_CHROMIUM`).
Every show is built in the test; nothing under `examples/` is read.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_watch_guide import (  # noqa: E402,F401
    VISIBLE, _chromium, _finding, _fn, _open_watch, _serve, assets, demo_copy,
    home, served_empty, served_show, show,
)

MAIN = _finding("error", "R005", 'MAIN 1 "PA"', "Main Not Patched", "MAIN 1 has no output socket.")
CLIP = _finding("warning", "L003", 'CH 10 "Lead Vox"', "Clipped", "Lead Vox peaked at 0 dBFS.")
ACRONYMS = _finding("info", "CH001", 'CH 2 "Snare"', "Channel Not In Any DCA", "No DCA.")
CONDITION = _finding("warning", "WATCH:vox-fader", 'BUS 5 "Drums"', "No mix or FX bus fader is below -40 dB.",
                     'BUS 5 "Drums" has its fader at -144 dB -- No mix or FX bus fader is below -40 dB.')


# ---- the served assets ------------------------------------------------------


def test_a_built_in_claim_is_sentence_cased_in_watch_only(assets):
    js = assets["js"]
    assert "claim: sentenceCase(f.title)" in js
    assert "escapeHtml(sentenceCase(g.title))" in js
    case = _fn(js, "function sentenceCase(title)")
    # The first word keeps its capital; an acronym or a word with a digit stays.
    assert "at === 0 || word === word.toUpperCase()" in case
    # The verdict line and the table agree: strip, a colon, the claim.
    assert "line = joinWhere(parts.where, parts.claim);" in _fn(js, "function renderVerdict(worst)")
    assert 'where + ": " + claim' in _fn(js, "function joinWhere(where, claim)")
    # The catalogue's own titles are unchanged: Watch's copy is not theirs.
    from atoo import audit
    assert any(r.title == "Main Not Patched" for r in audit.DEFAULT_RULES)


def test_a_row_is_hidden_by_a_labelled_quiet_button_not_a_check_box(assets):
    js, css, html = assets["js"], assets["css"], assets["html"]
    assert "watch-row-check" not in js + css + html
    hide = _fn(js, "function makeHideButton(f, hidden)")
    assert 'btn.className = "btn btn-quiet watch-row-hide"' in hide
    assert 'btn.textContent = hidden ? "Show" : "Hide";' in hide
    assert 'btn.setAttribute("aria-label"' in hide
    assert 'appendChild(makeHideButton(f, false))' in js
    assert "untick" not in js.lower()
    assert re.search(r"\.watch-row-hide \{[^}]*margin-left", css)


def test_the_empty_sentence_is_redrawn_when_start_unlocks(assets):
    js = assets["js"]
    assert "renderEmptyState();" in _fn(js, "function renderStartLock()")
    assert "renderEmptyState();" in _fn(js, "function renderTable()")
    assert 'barConsole().demo ? "Demo ready" : "Not connected"' in js


# ---- the real page, in Chromium --------------------------------------------


def _watching(page, findings):
    def on_ws(ws):
        ws.send(json.dumps({"type": "status", "running": True, "label": "Demo"}))
        ws.send(json.dumps({"type": "event", "baseline": True, "all_findings": findings,
                            "new_findings": [], "cleared_findings": [],
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "notes": []}))
    page.route_web_socket("**/ws/watch", on_ws)
    page.route("**/api/status", lambda r: r.fulfill(json={"running": True, "label": "Demo"}))


class _Page:
    def __init__(self, width, theme="dark"):
        self.width, self.theme = width, theme
        self.sync_api, self.path = _chromium()

    def __enter__(self):
        self._p = self.sync_api.sync_playwright().start()
        self.browser = self._p.chromium.launch(executable_path=self.path)
        self.page = self.browser.new_page(viewport={"width": self.width, "height": 900})
        self.page.add_init_script(
            "try { localStorage.setItem('atoo.demoPopupSeen', '1');"
            f" localStorage.setItem('atoo.theme', '{self.theme}'); }} catch (e) {{}}")
        return self.page

    def __exit__(self, *exc):
        self.browser.close()
        self._p.stop()


@pytest.mark.parametrize("width, theme", [(1280, "dark"), (1280, "light"), (390, "dark")])
def test_the_table_and_the_verdict_speak_one_voice(served_show, width, theme):
    with _Page(width, theme) as page:
        _watching(page, [MAIN, CLIP, ACRONYMS, CONDITION])
        page.goto(served_show + "#watch")
        page.wait_for_selector("#alert-body tr")
        # The first open finding is the error.
        assert page.locator("#watch-verdict-line").inner_text() == 'MAIN 1 "PA": Main not patched'
        claims = page.locator("#alert-body .row-claim").all_inner_texts()
        assert claims == ["Main not patched", "Clipped", "has its fader at -144 dB",
                          "Channel not in any DCA"]
        assert page.evaluate("document.documentElement.scrollWidth") <= width


@pytest.mark.parametrize("width, theme", [(1280, "dark"), (1280, "light"), (390, "dark")])
def test_hide_is_a_labelled_button_that_moves_the_row_to_suppressed_and_back(served_show, width, theme):
    with _Page(width, theme) as page:
        _watching(page, [MAIN, CLIP])
        page.goto(served_show + "#watch")
        page.wait_for_selector("#alert-body tr")
        buttons = page.locator("#alert-body .watch-row-hide")
        assert buttons.count() == 2
        assert page.locator("#alert-body input").count() == 0
        first = buttons.first
        assert first.inner_text() == "Hide"
        assert first.get_attribute("aria-label") == 'Hide: MAIN 1 "PA": Main not patched'
        # Quiet: brass words, no box (the UI style guide).
        assert first.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        assert first.evaluate("e => getComputedStyle(e).color") == page.evaluate(
            "() => { const p = document.createElement('span'); p.style.color = 'var(--accent)';"
            " document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; }")
        # The button sits inside its row, and the page does not scroll sideways.
        inside = first.evaluate(
            "e => { const b = e.getBoundingClientRect(), r = e.closest('tr').getBoundingClientRect();"
            " return b.left >= r.left && b.right <= r.right && b.top >= r.top && b.bottom <= r.bottom; }")
        assert inside
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        first.click()
        assert page.locator("#alert-body tr").count() == 1
        # Focus moved to the next row's button, not to the page.
        assert page.evaluate("document.activeElement.classList.contains('watch-row-hide')")
        page.locator("#watch-suppressed > summary").click()
        item = page.locator("#watch-suppressed-list li")
        assert item.count() == 1
        assert "MAIN 1 \"PA\": Main not patched" in item.inner_text().replace("\n", " ")
        show = item.locator(".watch-row-hide")
        assert show.inner_text() == "Show"
        assert show.get_attribute("aria-label") == 'Show again: MAIN 1 "PA": Main not patched'
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        show.click()
        assert page.locator("#alert-body tr").count() == 2


def test_the_empty_sentence_and_the_tag_follow_the_console_in_the_bar(served_empty):
    with _Page(1280) as page:
        page.goto(served_empty + "#watch")
        page.wait_for_function("document.getElementById('watch-notation').textContent === 'No console'")
        assert page.locator("#empty-state").inner_text() == \
            "Not watching yet. Choose a console in the bar, then Start watching."
        assert page.locator("#conn-pill").inner_text().upper() == "NOT CONNECTED"
        # Try the Demo show, from the bar: Start is live, so the sentence says so.
        page.click("#try-demo-btn")
        page.wait_for_function("!document.getElementById('start-btn').disabled")
        assert page.locator("#empty-state").inner_text() == "Not watching yet. Press Start watching."
        assert page.locator("#conn-pill").inner_text().upper() == "DEMO READY"
        assert page.locator("#conn-pill").get_attribute("class") == "state"
