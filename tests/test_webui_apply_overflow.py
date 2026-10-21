"""No screen scrolls sideways at 390px: Apply's History, and four small
oddities from a real-desk browser run.

1. **History.** The History table was wider than its card at phone width
   (a desk's name is one unbreakable line) and the page scrolled sideways.
   The rows are stacked lines there now and wrap; at any width the table
   scrolls inside its own box rather than the page. The browser half draws
   a populated History -- the journal listing answered with realistic rows,
   the way a real desk's would be -- and measures the page.
2. **A stale "Updated 1m ago"** is forgotten when the show or the console
   changes while the watch is stopped.
3. **No 404s in the console on load** with no show open: Apply does not ask
   for a pre-flight (it writes a show's plan.json, and there is no show),
   and Watch does not ask for a watch-conditions file nothing holds.
4. **Two "Show" buttons in a row**: the Suppressed fold opens with
   "Open the hidden list"; the row keeps "Show".
5. **After an Undo** the Arm tick is cleared and nothing can be written until
   the write is previewed again.

The page is checked in the dark theme first, then light. Every show is built
in the test; nothing under `examples/` is read. The browser halves skip where
Playwright or Chromium is missing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_amend import (TEXT, _app, _bundle, desk, model)  # noqa: E402,F401
from test_webui_choosers import _chromium, _serve  # noqa: E402
from test_webui_watch_guide import (  # noqa: E402,F401
    _chromium as _watch_chromium, demo_copy, home, served_empty, show,
)
from test_webui_watch_voice import MAIN, CLIP, _Page, _watching  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _rule(css: str, selector: str) -> str:
    match = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert match, f"styles.css has no rule {selector}"
    return match.group(1)


@pytest.fixture(scope="module")
def assets():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield {"html": c.get("/").text, "css": c.get("/static/styles.css").text,
               "apply": c.get("/static/apply.js").text, "watch": c.get("/static/watch.js").text}


# ---- the served assets ------------------------------------------------------


def test_the_history_table_scrolls_in_its_own_box_and_stacks_without_a_nowrap_cell(assets):
    html, css = assets["html"], assets["css"]
    box = html[html.index('id="apply-step-4-box"'):]
    box = box[:box.index('id="journal-stack-empty"')]
    assert '<div class="journal-stack-scroll" id="journal-stack-scroll">' in box
    assert box.index("journal-stack-scroll") < box.index('<table class="journal-stack-table">')
    assert "overflow-x: auto" in _rule(css, ".journal-stack-scroll")
    stacked = css[css.index("@container (max-width: 760px)"):]
    stacked = stacked[:stacked.index("\n}\n")]
    # Block all the way down, so no cell's width can widen the table.
    assert re.search(r"\.journal-stack-table, \.journal-stack-table tbody,\s*"
                     r"\.journal-stack-table tr, \.journal-stack-table td \{ display: block; \}",
                     stacked)
    assert "td.journal-desk-cell { white-space: normal; }" in stacked
    assert "overflow-wrap: anywhere" in stacked


def test_the_history_table_gives_summary_the_width_and_sizes_the_rest_to_their_content(assets):
    css = assets["css"]
    wide = css[css.index("@container (min-width: 761px)"):]
    wide = wide[:wide.index("\n}\n")]
    # When, Kind, Mismatches and the buttons' cell shrink to their content ...
    assert "width: 1%; white-space: nowrap;" in wide
    for n in (1, 2, 5, 6):
        assert f".journal-stack-table td:nth-child({n})" in wide
    # ... the Desk's long name wraps within a bounded width ...
    assert re.search(r"td\.journal-desk-cell \{[^}]*max-width: 22ch", wide)
    # ... and Summary is the one column left to take the slack.
    assert re.search(r"td:nth-child\(4\) \{ width: auto; min-width: 24ch;", wide)


def test_the_suppressed_fold_is_opened_by_its_own_words_and_the_row_keeps_a_ticked_box(assets):
    html, js = assets["html"], assets["watch"]
    fold = html[html.index('<details id="watch-suppressed"'):]
    head = fold[:fold.index("</summary>")]
    assert ">Open the hidden list</span>" in head
    assert ">Show</span>" not in head
    assert "box.checked = hidden" in js


def test_apply_and_watch_do_not_ask_for_what_a_page_with_no_show_cannot_have(assets):
    apply_js, watch_js, html = assets["apply"], assets["watch"], assets["html"]
    preflight = apply_js[apply_js.index("async function loadPreflight(mine)"):]
    preflight = preflight[:preflight.index("if (mine !== preflightSeq) return;")]
    assert "if (SP.bundle()) {" in preflight
    assert preflight.index("SP.bundle()") < preflight.index('fetch("/api/apply/preflight"')
    refresh = watch_js[watch_js.index("async function wcRefresh()"):]
    refresh = refresh[:refresh.index('fetch("/api/watch-conditions")')]
    assert "if (!wcBundle() && !wcLoadedPath && !wcStartedWith) {" in refresh
    assert "watch_conditions_path" in watch_js
    # The server says, in the embedded start-up data, whether it holds one.
    assert '"watch_conditions_path"' in (ROOT / "atoo" / "webui.py").read_text()
    # The page has its own icon, so the browser does not ask for /favicon.ico.
    assert '<link rel="icon" href="data:image/svg+xml,' in html


def test_a_stopped_reading_is_forgotten_when_the_show_or_the_console_changes(assets):
    js = assets["watch"]
    body = js[js.index("function forgetStoppedReading()"):]
    body = body[:body.index("SP.onConsoleChange(forgetStoppedReading);")]
    assert "if (serverRunning === true) return;" in body
    assert "lastReadingAt = null;" in body and 'lastUpdated.textContent = "";' in body
    assert "SP.onBundleChange(forgetStoppedReading)" in body
    assert "SP.onConsoleChange(forgetStoppedReading)" in js


def test_the_page_says_what_follows_an_undo():
    text = (ROOT / "docs" / "user" / "apply-to-desk.md").read_text()
    text = " ".join(text.split())
    assert "its button reads plain **Preview** again" in text
    assert "nothing can be written until you preview the write again" in text


# ---- the real page, in Chromium ---------------------------------------------


def _entry(id_, kind, stamp, summary, *, top=False, here=True, desk=None, change=None, mismatches=0):
    desk = desk or {"name": "wing-rack", "model": "wing-rack", "serial": "S100231",
                    "address": "198.51.100.250"}
    return {"id": id_, "kind": kind, "timestamp": stamp, "summary": summary,
            "mismatches": mismatches, "writes": 12, "undo_of": None, "undone_by": None,
            "is_top": top, "path": f"/show/journals/{id_}.json", "desk": desk,
            "serial": desk["serial"], "address": desk["address"], "desk_label": "x",
            "on_this_desk": here, "change": change,
            "change_label": f"change {change['number']}: {change['name']}" if change else None}


HISTORY = [
    _entry("c", "patch", "2026-10-16T12:00:00.123456Z",
           "APPLIED: 12 of 12 writes confirmed on the desk, 0 mismatches, 3 channels added",
           top=True, change={"number": 2, "name": "Horns for tonight",
                             "text": "add three horns on channels 21 to 23 with the usual "
                                     "horn mics and a group bus for them"}),
    _entry("b", "apply", "2026-10-16T11:00:00.123456Z",
           "APPLIED: 707 of 707 writes confirmed on the desk, 0 mismatches"),
    # A desk that names itself at length, and a summary with no space in it.
    _entry("a", "undo", "2026-10-16T10:00:00.123456Z", "UNDONE: 12 put back " + "x" * 90,
           here=False, mismatches=1,
           desk={"name": "Desk in the other room", "model": "wing-rack", "serial": "S9999",
                 "address": "203.0.113.100"}),
]


@pytest.mark.parametrize("width, theme", [(390, "dark"), (390, "light"), (1280, "dark")])
def test_a_populated_history_does_not_make_the_page_scroll_sideways(tmp_path, monkeypatch, width, theme):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    server, thread, url = _serve(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                     f" localStorage.setItem('atoo.theme', '{theme}'); }} catch (e) {{}}")

                def journals(route):
                    body = route.fetch().json()
                    body["entries"] = HISTORY
                    route.fulfill(json=body)

                page.route("**/api/journals", journals)
                page.goto(url)
                page.click("#nav-apply")
                page.wait_for_selector("#journal-stack-rows tr")
                assert page.evaluate("document.documentElement.dataset.theme") == theme
                assert page.locator("#journal-stack-rows tr").count() == len(HISTORY)
                assert page.evaluate("document.documentElement.scrollWidth") == width
                box = page.locator("#apply-step-4-box")
                assert box.evaluate("e => e.scrollWidth <= e.clientWidth")
                # Nothing on Apply reaches past the screen's right edge, except
                # what scrolls inside a box of its own.
                past = page.evaluate(
                    "[...document.querySelectorAll('#mode-apply *')].filter(e => e.offsetParent"
                    " && !e.closest('.journal-stack-scroll') && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.tagName)")
                assert past == [], past
                if width == 390:
                    # The rows are stacked lines; the desk's name wraps in the box.
                    desk_cell = page.locator("#journal-stack-rows tr").last.locator("td.journal-desk-cell")
                    assert desk_cell.evaluate("e => getComputedStyle(e).whiteSpace") == "normal"
                    assert page.locator(".journal-stack-scroll").evaluate(
                        "e => e.scrollWidth <= e.clientWidth")
                else:
                    # Wide: a row too long for the card scrolls inside its own box.
                    assert page.locator(".journal-stack-scroll").evaluate(
                        "e => getComputedStyle(e).overflowX") == "auto"
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_a_page_with_no_show_open_logs_no_404_on_load_or_when_visiting_apply_and_watch(served_empty):
    sync_api, chromium = _watch_chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1'); } catch (e) {}")
            refused, logged = [], []
            page.on("response", lambda r: refused.append((r.status, r.url)) if r.status >= 400 else None)
            page.on("console", lambda m: logged.append(m.text) if m.type == "error" else None)
            page.goto(served_empty)
            page.wait_for_load_state("networkidle")
            for mode in ("apply", "watch", "build"):
                page.click(f"#nav-{mode}")
                page.wait_for_load_state("networkidle")
            assert refused == [] and logged == []
        finally:
            browser.close()


@pytest.mark.parametrize("width, theme", [(1280, "dark"), (1280, "light"), (390, "dark")])
def test_the_suppressed_fold_keeps_the_rows_ticked_box_and_nothing_scrolls(tmp_path, monkeypatch, show,
                                                              demo_copy, width, theme):
    from test_webui_watch_guide import _serve as serve_watch

    server, thread, url = serve_watch(create_app(
        initial_bundle=str(show), initial_watch_conditions_path=str(show / "watch.json")))
    try:
        with _Page(width, theme) as page:
            _watching(page, [MAIN, CLIP])
            page.goto(url + "#watch")
            page.wait_for_selector("#alert-body tr")
            page.locator("#alert-body .watch-row-hide").first.click()
            fold = page.locator("#watch-suppressed")
            hint = fold.locator("summary .watch-fold-hint")
            assert hint.inner_text() == "Open the hidden list"
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            page.locator("#watch-suppressed > summary").click()
            assert fold.locator("#watch-suppressed-list .watch-row-hide").is_checked()
            assert hint.is_hidden()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_a_stopped_watchs_updated_label_goes_when_the_console_changes(served_empty):
    sync_api, chromium = _watch_chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                 " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
            page.goto(served_empty + "#watch")
            page.click("#try-demo-btn")
            page.wait_for_function("!document.getElementById('start-btn').disabled")
            page.click("#start-btn")
            page.wait_for_function(
                "/^Updated/.test(document.getElementById('last-updated').textContent)", timeout=30000)
            # Running: the label belongs to the watch, and a console edit leaves it be.
            page.click("#stop-btn")
            page.wait_for_function("!document.getElementById('start-btn').disabled")
            # Stopped, it ages ("Updated 3m ago") until something it was about changes.
            assert page.locator("#last-updated").inner_text().startswith("Updated")
            page.click("#console-change-btn")
            page.click("#console-kind-desk")
            page.fill("#console-edit-address", "203.0.113.9")
            page.click("#console-set-btn")
            page.wait_for_function("document.getElementById('last-updated').textContent === ''")
        finally:
            browser.close()


def test_after_an_undo_the_arm_tick_is_cleared_and_nothing_can_be_written_until_a_new_preview(
        tmp_path, monkeypatch, desk, model):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ATOO_AI_API_KEY", "not-a-real-key")
    server, thread, url = _serve(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                     " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
                page.goto(url)
                page.click("#nav-apply")
                page.click("#apply-mode-amend")
                page.fill("#patch-change-text", TEXT)
                page.click("#apply-preview-btn")
                page.wait_for_selector("#amend-review:not([hidden])", timeout=60000)
                page.check("#apply-arm-checkbox")
                page.click("#apply-run-btn")
                page.wait_for_function(
                    "document.querySelector('#journal-stack-rows').children.length > 0", timeout=60000)
                page.click("#undo-preview-btn")
                page.wait_for_function(
                    "document.querySelector('#undo-result-state').textContent"
                    " && !/Reading/i.test(document.querySelector('#undo-result-state').textContent)",
                    timeout=30000)
                assert page.locator("#apply-preview-btn").text_content() == "Preview write"
                page.check("#apply-arm-checkbox")
                page.click("#undo-run-btn")
                page.wait_for_function(
                    "!document.querySelector('#undo-banner').hidden"
                    " && /put back/.test(document.querySelector('#undo-banner-head').textContent)",
                    timeout=30000)
                # Step 2 is the write's box again, with the plain button.
                assert page.locator("#apply-preview-btn").text_content() == "Preview"
                assert page.locator("#undo-result").is_hidden()
                assert not page.locator("#apply-arm-checkbox").is_checked()
                # No write control is on offer, and Undo is locked: nothing is left to undo.
                assert page.locator("#apply-run-btn").is_hidden()
                assert page.locator("#undo-run-btn").is_disabled()
                # A new preview brings the write back, locked until Arm is ticked.
                page.click("#apply-preview-btn")
                page.wait_for_selector("#amend-review:not([hidden])", timeout=60000)
                assert page.locator("#apply-step-3-title").inner_text() == "Arm and write"
                assert not page.locator("#apply-arm-checkbox").is_checked()
                assert page.locator("#apply-run-btn").is_disabled()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
