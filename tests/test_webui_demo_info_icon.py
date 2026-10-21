"""The Demo show's lock stops edits, never reading: Watch's info icon beside
each condition's ID works in the Demo's read-only table (hover, click, Enter,
Escape), the icons sit in one column, and each is a 32px target.

The first test holds the served script and stylesheet to the rule that the
lock lists the table's editing buttons by name, not "every button in it".
The others drive the real page in Chromium, dark first and then light, and at
390px. They skip where Playwright or a Chromium is not installed
(`ATOO_TEST_CHROMIUM`). The Demo is the packaged one; nothing under
`examples/` is read.
"""

from __future__ import annotations

import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from test_webui_watch_guide import (  # noqa: E402,F401
    _chromium, demo_copy, home, served_empty, show,
)

ICON = "#wc-table .wc-explain-btn"


def test_the_demos_lock_names_its_editing_buttons_and_leaves_the_info_icon(served_empty):
    import urllib.request
    shell = urllib.request.urlopen(served_empty + "static/shell.js").read().decode()
    css = urllib.request.urlopen(served_empty + "static/styles.css").read().decode()
    locked = shell[shell.index("const DEMO_LOCKED = ["):shell.index("].join")]
    assert '"#wc-table .wc-remove"' in locked
    assert '"#wc-table button.wc-source-drafted"' in locked
    assert '"#wc-table button"' not in locked
    assert "#wc-table button)" not in css and "#wc-table button," not in css
    assert "#wc-table .wc-remove, #wc-table button.wc-source-drafted)" in css


def _demo_watch(browser, address, width, theme):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                         f" localStorage.setItem('atoo.theme', '{theme}'); }} catch (e) {{}}")
    page.goto(address + "#watch")
    page.click("#try-demo-btn")
    page.wait_for_selector(ICON, state="attached")
    return page


def _open(page):
    return page.evaluate("document.querySelector('.wc-explain-text:not([hidden])') !== null")


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_info_icon_opens_and_closes_in_the_demos_read_only_table(served_empty, theme):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = _demo_watch(browser, served_empty, 1280, theme)
            icon = page.locator(ICON).first
            assert page.evaluate("document.body.classList.contains('is-demo-show')")
            # Hover opens, moving away closes.
            icon.hover()
            assert _open(page)
            page.mouse.move(0, 0)
            assert not _open(page)
            # Click opens, Escape closes and hands the focus back to the icon.
            icon.click()
            assert _open(page)
            page.keyboard.press("Escape")
            assert not _open(page)
            assert page.evaluate("document.activeElement.classList.contains('wc-explain-btn')")
            # Tab to it and Enter: the sentence, not the Demo popup.
            icon.focus()
            page.keyboard.press("Enter")
            assert _open(page)
            assert page.evaluate("document.getElementById('demo-popup').hidden !== false"
                                 " || !document.getElementById('demo-popup').open")
            page.keyboard.press("Escape")
        finally:
            browser.close()


def test_the_editing_buttons_stay_locked_in_the_demos_table(served_empty):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = _demo_watch(browser, served_empty, 1280, "dark")
            # The read-only table has no editing button to press; the lock's
            # list still names them, so a press on one is swallowed.
            assert page.locator("#wc-table .wc-remove, #wc-table button.wc-source-drafted").count() == 0
            assert page.evaluate(
                "(() => { const b = document.createElement('button'); b.className = 'wc-remove';"
                " document.querySelector('#wc-table tbody td').appendChild(b);"
                " b.click(); return !document.getElementById('demo-popup').hidden; })()")
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_the_icons_line_up_in_one_column_and_each_is_a_32px_target(served_empty, width):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = _demo_watch(browser, served_empty, width, "dark")
            m = page.evaluate("""() => Array.from(document.querySelectorAll('#wc-table .wc-explain-btn')).map(b => {
              b.scrollIntoView({block: 'center', inline: 'center'});
              const r = b.getBoundingClientRect();
              const h = document.elementFromPoint(r.left - 6, r.top + r.height / 2);
              const cell = b.closest('td').getBoundingClientRect();
              return {right: r.right - cell.right, w: r.width,
                      hitOk: !!h && h.closest('.wc-explain-btn') === b};
            })""")
            assert len(m) >= 2, m
            assert max(x["right"] for x in m) - min(x["right"] for x in m) < 0.5, m
            for x in m:
                assert x["hitOk"], x  # a press 6px outside the drawn icon still lands on it
        finally:
            browser.close()
    assert re.search(r"#wc-table \.wc-explain-btn::after \{[^}]*inset: -7px", open(
        "atoo/web/static/styles.css").read())
