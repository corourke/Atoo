"""Apply and Patch at 390px wide: no screen scrolls sideways after a patch
preview.

The Patch review's timing line (`#patch-timing`, a `.readout`) is one long
line of figures. `.readout` is `white-space: nowrap`, so at phone width the
line ran past the screen and the whole page scrolled sideways. The line
wraps now, as the undo preview's readouts do.

Two halves, as elsewhere: the served stylesheet (the Python suite cannot see
the browser) and the real page in Chromium, a patch previewed against a
simulated desk with a fake model, in the dark theme first and then light.
Every show is built in the test; nothing under `examples/` is read.
"""

from __future__ import annotations

import re
import socket
import threading
import time

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import webui  # noqa: E402
from atoo.webui import create_app  # noqa: E402
from test_webui_amend import (TEXT, _app, _bundle, desk, model)  # noqa: E402,F401
from test_webui_choosers import _chromium, _serve  # noqa: E402


def _rule(css: str, selector: str) -> str:
    match = re.search(r"(?:^|\n)" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert match, f"styles.css has no rule {selector}"
    return match.group(1)


def test_the_patch_timing_line_wraps_in_the_served_stylesheet():
    with fastapi_testclient.TestClient(create_app()) as c:
        css = c.get("/static/styles.css").text
        html = c.get("/static/shell.html").text
    assert 'class="panel-note readout" id="patch-timing"' in html
    rule = _rule(css, "#patch-timing")
    assert "white-space: normal" in rule and "overflow-wrap: anywhere" in rule
    # `.panel-note`'s dim grey must not sit on the readout's chip.
    assert "color: var(--readout-fg)" in rule


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_a_patch_preview_does_not_scroll_the_page_sideways_at_390px(
        tmp_path, monkeypatch, desk, model, theme):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # A model is "set up" for the page's pre-flight; the fake one answers.
    monkeypatch.setattr(webui, "_patch_model_state", lambda: (True, None))
    server, thread, url = _serve(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 900})
                page.add_init_script(
                    "try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                    f" localStorage.setItem('atoo.theme', '{theme}'); }} catch (e) {{}}")
                page.goto(url)
                page.click("#nav-apply")
                page.click("#apply-mode-amend")
                page.fill("#patch-change-text", TEXT)
                page.click("#apply-preview-btn")
                page.wait_for_function(
                    "document.getElementById('patch-timing').innerText.includes('Timing')",
                    timeout=60000)
                assert page.evaluate("document.documentElement.dataset.theme") == theme
                line = page.locator("#patch-timing")
                assert line.is_visible()
                # The line is wide enough that, unwrapped, it overflowed.
                assert page.evaluate("document.documentElement.scrollWidth") == 390
                assert line.evaluate("e => e.scrollWidth <= e.clientWidth")
                box = line.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= 390
                # Every readout on the screen fits as well.
                assert page.evaluate("""() => [...document.querySelectorAll('.readout')]
                    .filter(e => e.offsetParent !== null)
                    .map(e => e.getBoundingClientRect().right)
                    .every(r => r <= 390.5)""")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
