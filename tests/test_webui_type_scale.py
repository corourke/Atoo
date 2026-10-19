"""Every size of text on the page is one of the style guide's scale.

The guide (`docs/developer/ui-style.md`, section 2) allows five sizes of
type, 11, 12, 13, 14 and 16 (nothing under 11), and three exceptions: the
brand name and the Watch table's where and claim at 17, and the verdict word
at 22. The stylesheet had drifted to 7, 9.5, 10, 10.5, 11.5, 12.5, 13.5 and
15, and a form control that sets no size takes the browser's 13.33.

The Python suite cannot see a browser, so there are two halves. The served
stylesheet is read for every size it declares, which covers the screens that
are hard to drive (Patch, the undo preview); and the real page is measured in
Chromium, in the dark theme: the computed size of every element that holds
text, or is a form control, on Build (all four steps, folds open), Apply
(Full build and Patch, folds open) and Watch (a baseline with one finding of
each severity, which are the table's three row styles), plus Patch's review
against a simulated desk. They skip where Playwright or a Chromium is not
installed (`ATOO_TEST_CHROMIUM`). Every show is built in the test; nothing
under `examples/` is read.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import webui  # noqa: E402
from atoo.webui import create_app  # noqa: E402
from test_webui_amend import (TEXT, _app, _bundle, desk, model)  # noqa: E402,F401
from test_webui_choosers import _chromium as _chromium_path, _serve as _serve_patch  # noqa: E402
from test_webui_ui_followups import _chromium, _serve, demo_copy, home  # noqa: E402,F401

SCALE = {11, 12, 13, 14, 16, 17, 22}

#: One finding of each severity: the table's three row styles.
FINDINGS = [
    {"rule_id": "R001", "severity": "error", "category": "routing", "title": "Channel not patched",
     "detail": "Nothing is patched to the channel.", "addresses": ["/ch/1/in/conn/in"], "strip": "CH 1"},
    {"rule_id": "R002", "severity": "warning", "category": "routing", "title": "Output patch missing",
     "detail": "The output is not patched.", "addresses": ["/ch/2/in/conn/in"], "strip": "CH 2"},
    {"rule_id": "R003", "severity": "info", "category": "naming", "title": "Name was shortened",
     "detail": "The name was shortened to fit.", "addresses": ["/ch/3/name"], "strip": "CH 3"},
]

#: Every element that holds text of its own, or is a form control, by its
#: computed size. Elements that are hidden count too: a fold that is closed
#: still has a size, and is drawn the moment it opens.
SIZES = """() => {
  const found = {};
  const skip = new Set(['SCRIPT', 'STYLE', 'TITLE']);
  for (const el of document.querySelectorAll('body *')) {
    if (skip.has(el.tagName) || el instanceof SVGElement) continue;
    const text = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
    if (!text && !/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) continue;
    const px = parseFloat(getComputedStyle(el).fontSize);
    const klass = typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
    (found[px] = found[px] || new Set()).add(el.tagName.toLowerCase() + klass);
  }
  return Object.fromEntries(Object.entries(found).map(([k, v]) => [k, Array.from(v).sort()]));
}"""

OPEN_FOLDS = "() => document.querySelectorAll('details').forEach(d => { d.open = true; })"


def _off_scale(sizes: dict) -> dict:
    return {px: names for px, names in sizes.items() if float(px) not in SCALE}


def test_the_stylesheet_declares_only_sizes_on_the_scale():
    with fastapi_testclient.TestClient(create_app()) as c:
        css = c.get("/static/styles.css").text
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    declared = [float(m) for m in re.findall(r"font-size:\s*([0-9.]+)px", css)]
    # The `font` shorthand: [style] [weight] SIZE[/line-height] family.
    declared += [float(m) for m in re.findall(
        r"(?<![-\w])font:\s*(?:(?:italic|normal|\d{3})\s+)*([0-9.]+)px", css)]
    assert declared, "no sizes found: the pattern no longer reads the stylesheet"
    assert {px for px in declared if px not in SCALE} == set()


def test_no_script_sets_a_size_of_its_own():
    with fastapi_testclient.TestClient(create_app()) as c:
        for name in ("apply.js", "amend.js", "setup.js", "watch.js", "shell.js", "filebrowser.js"):
            js = c.get(f"/static/{name}").text
            assert not re.search(r"fontSize|font-size", js), name


def _demo_page(browser, url, *, width=1280, theme="dark"):
    """The Demo show, with a stand-in for the watch's socket: a baseline of
    one finding of each severity."""
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen','1');"
                         f" localStorage.setItem('atoo.theme','{theme}'); }} catch (e) {{}}")
    page.goto(url)
    assert page.request.post(url + "api/console", data={"demo": True}).ok
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
    page.goto("about:blank")
    page.goto(url)
    page.wait_for_function("document.body.classList.contains('is-demo-show')")
    page.wait_for_selector("#build-steps .pipe-stop", state="attached")
    page.wait_for_selector("#input-rows tr", state="attached")
    return page


@pytest.fixture
def served(home, demo_copy):
    app = create_app()
    url, server, thread = _serve(app)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def _merge(into: dict, sizes: dict):
    for px, names in sizes.items():
        into.setdefault(px, set()).update(names)


def test_build_apply_and_watch_use_only_the_scale(served):
    sync_api, path = _chromium()
    seen: dict = {}
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=path)
        try:
            page = _demo_page(browser, served)
            for step in ("conventions", "input-list", "instructions", "plan"):
                page.evaluate("s => document.getElementById('tab-' + s).click()", step)
                page.wait_for_selector(f"#panel-{step}:not([hidden])", state="attached")
                page.evaluate(OPEN_FOLDS)
                # A plan table's rows open: the expand arrow is the thing.
                page.evaluate("() => document.querySelectorAll('.row-expand-btn').forEach(b => b.click())")
                _merge(seen, page.evaluate(SIZES))
            page.evaluate("document.getElementById('nav-apply').click()")
            page.wait_for_selector("#mode-apply:not([hidden])", state="attached")
            for mode in ("full", "amend"):
                page.evaluate("m => document.getElementById('apply-mode-' + m).click()", mode)
                page.evaluate(OPEN_FOLDS)
                _merge(seen, page.evaluate(SIZES))
            page.evaluate("document.getElementById('nav-watch').click()")
            page.wait_for_selector("#alert-body tr .watch-row-hide", state="attached")
            page.evaluate(OPEN_FOLDS)
            _merge(seen, page.evaluate(SIZES))
            assert page.locator("#alert-body tr").count() == len(FINDINGS)
        finally:
            browser.close()
    assert seen, "nothing was measured"
    assert _off_scale({px: sorted(v) for px, v in seen.items()}) == {}


@pytest.mark.parametrize("theme", ["dark"])
def test_patch_review_uses_only_the_scale(tmp_path, monkeypatch, desk, model, theme):
    path = _chromium_path()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(webui, "_patch_model_state", lambda: (True, None))
    server, thread, url = _serve_patch(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=path)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
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
                page.evaluate(OPEN_FOLDS)
                sizes = page.evaluate(SIZES)
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert sizes
    assert _off_scale(sizes) == {}
