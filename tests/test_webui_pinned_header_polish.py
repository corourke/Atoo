"""Three small things from the maintainer's church-desk screenshots (Test 27):

* the pinned header is one opaque piece: no strip of the page shows between
  the app header and the bundle bar, or under the bundle bar's message line;
* the bundle bar's message reads as a note, and only an error is red; a ×
  dismisses it, and changing step still clears it;
* New show's Start is two bordered option cards, Empty and From a desk, so
  both read as choices.

The Python suite cannot see a browser, so the first test holds the served
assets to the rule and the others measure the real page in Chromium, dark
first and then light. They skip where Playwright or a Chromium is not
installed (`ATOO_TEST_CHROMIUM`). Nothing under `examples/` is read.
"""

from __future__ import annotations

import re
import urllib.request

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_ui_followups import _chromium, _serve  # noqa: E402

NOTE = "Captured the desk at 192.0.2.148 -- nothing was written to the desk. 13 note(s)."


@pytest.fixture
def url():
    app = create_app()
    address, server, thread = _serve(app)
    yield address
    server.should_exit = True
    thread.join(timeout=5)


def _page(browser, address, width, theme, height=900):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.add_init_script(
        "try { localStorage.setItem('atoo.demoPopupSeen','1');"
        f" localStorage.setItem('atoo.theme','{theme}'); }} catch (e) {{}}")
    page.goto(address)
    page.wait_for_selector("#bundle-chrome")
    return page


def _with_browser(fn):
    sync_api, path = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        try:
            return fn(browser)
        finally:
            browser.close()


def test_the_served_assets_carry_the_three_fixes(url):
    css = urllib.request.urlopen(url + "static/styles.css").read().decode()
    js = urllib.request.urlopen(url + "static/shell.js").read().decode()
    html = urllib.request.urlopen(url + "static/shell.html").read().decode()
    # The pieces are pinned by their exact heights, rounded down.
    assert "node.style.top = Math.floor(top) + \"px\";" in js
    assert "top += node.getBoundingClientRect().height;" in js
    assert "top += node.offsetHeight;" not in js
    # The message: a note in dim text, red only for an error, and a ×.
    assert re.search(r"\.bundle-message \{[^}]*color: var\(--text-dim\)", css)
    assert ".bundle-message.panel-message-error { color: var(--danger-fg); }" in css
    assert re.search(r"\.bundle-message-close \{[^}]*width: 32px; height: 32px", css)
    assert 'id="bundle-message-close" aria-label="Dismiss this message"' in html
    # Start: two option cards with a line each.
    start = html[html.index('id="ns-start"'):html.index('id="ns-read-label"')]
    assert start.count('class="ns-card" role="radio"') == 2
    assert "A new folder with no files yet." in start
    assert "Capture a console or a .snap file into input.csv and busses.csv." in start
    assert "Captures the desk to input.csv and busses.csv which you can edit." in html
    assert re.search(r"\.ns-card \{[^}]*border: 1px solid var\(--border-strong\)[^}]*cursor: pointer", css)


SEAMS = """() => {
  document.body.insertAdjacentHTML('beforeend', '<div id="tall" style="height:3000px"></div>');
  window.scrollTo(0, 800);
  const box = (n) => n ? n.getBoundingClientRect() : null;
  const top = box(document.querySelector('body.shell > .topbar'));
  const chrome = document.getElementById('bundle-chrome');
  const pipe = document.getElementById('pipeline-wrap');
  return {
    top: [top.top, top.bottom],
    chrome: [box(chrome).top, box(chrome).bottom, getComputedStyle(chrome).position],
    pipe: pipe && pipe.offsetParent ? [box(pipe).top, getComputedStyle(pipe).position] : null,
  };
}"""


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width", [1440, 1920])
@pytest.mark.parametrize("message", [False, True])
def test_nothing_of_the_page_shows_between_the_pinned_pieces(url, theme, width, message):
    def run(browser):
        page = _page(browser, url, width, theme)
        if message:
            page.evaluate(f"window.Atoo.showBundleMessage({NOTE!r}, false)")
        page.wait_for_timeout(200)
        return page.evaluate(SEAMS)

    m = _with_browser(run)
    assert m["top"][0] == 0 and m["chrome"][2] == "sticky", m
    # Each piece starts at or above the bottom of the one over it.
    assert m["chrome"][0] <= m["top"][1], m
    if m["pipe"] is not None and m["pipe"][1] == "sticky":
        assert m["pipe"][0] <= m["chrome"][1], m


def test_on_a_phone_only_the_app_header_stays(url):
    def run(browser):
        page = _page(browser, url, 390, "dark", height=800)
        page.evaluate(f"window.Atoo.showBundleMessage({NOTE!r}, false)")
        return page.evaluate(SEAMS)

    m = _with_browser(run)
    assert m["top"][0] == 0 and m["chrome"][2] == "static", m


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_note_is_not_red_an_error_is_and_the_cross_dismisses_it(url, theme):
    def run(browser):
        page = _page(browser, url, 1440, theme)
        colour = "getComputedStyle(document.getElementById('bundle-message')).color"
        page.evaluate(f"window.Atoo.showBundleMessage({NOTE!r}, false)")
        note = page.evaluate(colour)
        page.evaluate("window.Atoo.showBundleMessage(\"couldn't create the folder\", true)")
        error = page.evaluate(colour)
        danger = page.evaluate(
            "(() => { const p = document.createElement('p'); p.style.color = 'var(--danger-fg)';"
            " document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove();"
            " return c; })()")
        close = page.locator("#bundle-message-close")
        size = close.bounding_box()
        label = close.get_attribute("aria-label")
        close.click()
        dismissed = page.evaluate("document.getElementById('bundle-message').hidden")
        # Changing step clears it too.
        page.evaluate(f"window.Atoo.showBundleMessage({NOTE!r}, false)")
        page.locator(".pipe-stop").nth(1).click()
        stepped = page.evaluate("document.getElementById('bundle-message').hidden")
        return note, error, danger, size, label, dismissed, stepped

    note, error, danger, size, label, dismissed, stepped = _with_browser(run)
    assert error == danger and note != danger, (note, error, danger)
    assert size["width"] >= 32 and size["height"] >= 32, size
    assert label == "Dismiss this message"
    assert dismissed and stepped


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_new_shows_start_is_two_cards_that_both_read_as_choices(url, theme):
    def run(browser):
        page = _page(browser, url, 1440, theme)
        page.click("#bundle-new-btn")
        page.wait_for_selector("#new-show-dialog[open]")
        cards = page.locator("#ns-start [role=radio]").evaluate_all("""(ns) => ns.map((n) => {
          const r = n.getBoundingClientRect(), s = getComputedStyle(n);
          return {value: n.dataset.value, checked: n.getAttribute('aria-checked'),
                  width: r.width, height: r.height, top: r.top, border: s.borderTopWidth,
                  borderColour: s.borderTopColor, cursor: s.cursor};
        })""")
        hint = page.locator(".note-dialog-hint.ns-desk")
        before = hint.is_visible()
        page.focus("#ns-start [aria-checked=true]")
        page.keyboard.press("ArrowRight")
        chosen = page.locator("#ns-start [aria-checked=true]").get_attribute("data-value")
        return cards, before, chosen, hint.is_visible()

    cards, hint_before, chosen, hint_after = _with_browser(run)
    empty, desk = cards
    assert (empty["value"], empty["checked"], desk["value"], desk["checked"]) == \
        ("empty", "true", "desk", "false"), cards
    # Side by side, equal, each bordered; the one not chosen looks clickable.
    assert abs(empty["top"] - desk["top"]) < 1 and abs(empty["width"] - desk["width"]) < 1, cards
    assert all(c["border"] == "1px" and c["height"] >= 32 for c in cards), cards
    assert desk["cursor"] == "pointer" and desk["borderColour"] != empty["borderColour"], cards
    # Arrow keys move between them, as a radio group's do, and the capture
    # line shows once From a desk is chosen.
    assert chosen == "desk" and not hint_before and hint_after


# -- Build plan on a captured show asks first ------------------------------------

CHURCH = __import__("pathlib").Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"
REPLACES = ("This plan was read from the desk. Build plan replaces it with a new plan from your "
            "conventions, using a model; your sheet edits still win.")


def test_the_served_page_carries_the_captured_build_question(url):
    html = urllib.request.urlopen(url + "static/shell.html").read().decode()
    js = urllib.request.urlopen(url + "static/setup.js").read().decode()
    assert REPLACES in html
    assert 'id="captured-build-cancel">Cancel</button>' in html
    assert 'id="captured-build-continue">Continue</button>' in html
    assert 'runBtn.addEventListener("click", buildAsking);' in js
    assert 'meta.made_from === "desk" || meta.made_from === "snap"' in js


def _show_url(tmp_path, captured: bool):
    import json

    from atoo import capture

    source = capture.from_snap(CHURCH, "wing-full", captured="2026-10-24")
    directory = tmp_path / "church"
    capture.write_bundle(source.capture, directory, evidence_name="church.snap", evidence=b"{}")
    plan_path = directory / "plan.json"
    plan = json.loads(plan_path.read_text())
    if not captured:
        plan["meta"].pop("made_from")
        plan_path.write_text(json.dumps(plan))
    app = create_app(initial_bundle=str(directory), initial_plan=plan,
                     initial_plan_path=str(plan_path))
    return _serve(app)


@pytest.fixture
def model_set_up(monkeypatch):
    """Build plan is locked with no model set up; these press it."""
    monkeypatch.setattr("atoo.webui._build_model_state", lambda: (True, None))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_build_plan_on_a_captured_show_asks_and_cancel_does_nothing(tmp_path, theme, model_set_up):
    address, server, thread = _show_url(tmp_path, captured=True)

    def run(browser):
        page = _page(browser, address, 1440, theme)
        page.evaluate("document.getElementById('run-build-btn').click()")
        page.wait_for_selector("#captured-build-dialog[open]")
        text = page.locator("#captured-build-text").inner_text()
        focused = page.evaluate("document.activeElement.id")
        page.keyboard.press("Escape")
        closed_by_esc = page.evaluate("!document.getElementById('captured-build-dialog').open")
        page.evaluate("document.getElementById('run-build-btn').click()")
        page.click("#captured-build-cancel")
        cancelled = page.evaluate("!document.getElementById('captured-build-dialog').open")
        said = page.evaluate("document.getElementById('run-message').textContent")
        # Continue goes on to the build: with no console model chosen, the
        # build's own first check speaks.
        page.evaluate("document.getElementById('run-build-btn').click()")
        page.click("#captured-build-continue")
        page.wait_for_timeout(200)
        went_on = page.evaluate("document.getElementById('run-message').textContent")
        return text, focused, closed_by_esc, cancelled, said, went_on

    try:
        text, focused, closed_by_esc, cancelled, said, went_on = _with_browser(run)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert text == REPLACES
    assert focused == "captured-build-cancel"
    assert closed_by_esc and cancelled and not said
    assert went_on


def test_build_plan_on_a_built_plan_builds_with_no_question(tmp_path, model_set_up):
    address, server, thread = _show_url(tmp_path, captured=False)

    def run(browser):
        page = _page(browser, address, 1440, "dark")
        page.evaluate("document.getElementById('run-build-btn').click()")
        # The build's first message, however long it takes to come: a built
        # plan goes straight to the build, with no question in between.
        page.wait_for_function("document.getElementById('run-message').textContent.trim() !== ''")
        return (page.evaluate("document.getElementById('captured-build-dialog').open"),
                page.evaluate("document.getElementById('run-message').textContent"))

    try:
        opened, said = _with_browser(run)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert not opened and said
