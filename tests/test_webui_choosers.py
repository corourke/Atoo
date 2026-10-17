"""Choosers are not buttons: the segmented control and the switch.

Apply mode (Full build / Patch), Which console (Address / Demo) and the
Theme (Auto / Light / Dark) are segmented controls -- `role="radiogroup"`
holding `role="radio"` options with `aria-checked`, one tab stop on the
selected option, arrows that move and select, Home and End. Flash on new
and Virtual soundcheck are switches -- `role="switch"` with `aria-checked`
and the word On or Off beside them. Watch's severity chips are filters,
several of which may be on, so they keep `aria-pressed`.

The Python suite cannot see the browser, so the first half asserts over the
served assets and the second drives the real page in Chromium.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from test_webui_amend import _app, _bundle  # noqa: E402


@pytest.fixture
def assets():
    from atoo.webui import create_app

    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def _tag(html: str, element_id: str) -> str:
    start = html.rindex("<", 0, html.index(f'id="{element_id}"'))
    return html[start:html.index(">", start) + 1]


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r" \{([^}]*)\}", css)
    assert match, f"styles.css has no rule {selector}"
    return match.group(1)


# ======================================================================
# The served assets
# ======================================================================


def test_apply_mode_is_a_radiogroup_not_a_pair_of_pressed_buttons(assets):
    html = assets.get("/static/shell.html").text
    group = html[html.index('id="apply-mode-seg"') - 40:html.index('id="apply-mode-hint"')]
    assert 'class="seg is-fill" id="apply-mode-seg" role="radiogroup" aria-label="Apply mode"' in group
    full, amend = _tag(html, "apply-mode-full"), _tag(html, "apply-mode-amend")
    assert 'role="radio"' in full and 'aria-checked="true"' in full and 'tabindex="0"' in full
    assert 'role="radio"' in amend and 'aria-checked="false"' in amend and 'tabindex="-1"' in amend
    assert "aria-pressed" not in full + amend
    # The hint stays beside the control.
    assert html.index('id="apply-mode-hint"') > html.index('id="apply-mode-amend"')


def test_no_chooser_is_left_as_a_pressed_segment_button(assets):
    html = assets.get("/static/shell.html").text
    css = assets.get("/static/styles.css").text
    for name in ("shell.js", "apply.js", "watch.js", "setup.js", "amend.js"):
        assert "seg-btn" not in assets.get(f"/static/{name}").text, name
    assert "seg-btn" not in html and "seg-btn" not in css
    assert "THEME_NEXT" not in assets.get("/static/shell.js").text
    # aria-pressed is for a toggle among several: Watch's severity chips keep it.
    assert re.findall(r'<[^>]*aria-pressed[^>]*>', html), "the filter chips lost aria-pressed"
    for tag in re.findall(r'<[^>]*aria-pressed[^>]*>', html):
        assert 'count-pill' in tag, tag


def test_console_kind_and_theme_are_segmented_controls(assets):
    html = assets.get("/static/shell.html").text
    assert 'id="console-kind-seg" role="radiogroup" aria-label="Which console"' in html
    for element_id, value in (("console-kind-desk", "desk"), ("console-kind-demo", "demo")):
        tag = _tag(html, element_id)
        assert 'role="radio"' in tag and f'data-value="{value}"' in tag and "<input" not in tag
    assert 'name="console-kind"' not in html
    theme = html[html.index('id="theme-seg"'):html.index('id="theme-seg"') + 900]
    assert 'role="radiogroup" aria-label="Theme"' in theme
    assert [m for m in re.findall(r'data-value="(\w+)"', theme)][:3] == ["auto", "light", "dark"]
    assert 'class="seg is-sm"' in html


def test_the_two_watch_settings_are_switches(assets):
    html = assets.get("/static/shell.html").text
    for element_id, label in (("watch-flash-on", "Flash on new"), ("watch-virtual", "Virtual soundcheck")):
        tag = _tag(html, element_id)
        assert 'role="switch"' in tag and 'aria-checked="false"' in tag, element_id
        assert f'aria-label="{label}"' in tag and "aria-pressed" not in tag
        body = html[html.index(f'id="{element_id}"'):]
        body = body[:body.index("</button>")]
        assert f"<span>{label}</span>" in body and 'class="word"' in body and 'class="track"' in body
    js = assets.get("/static/watch.js").text
    assert 'flashToggle.setAttribute("aria-checked"' in js
    assert 'vsToggle.setAttribute("aria-checked"' in js
    assert "aria-pressed" not in js.replace('pill.setAttribute("aria-pressed"', "")


def test_the_segmented_control_is_neutral_and_never_an_action_colour(assets):
    css = assets.get("/static/styles.css").text
    selected = _rule(css, '.seg-opt[aria-checked="true"]')
    assert "var(--border-strong)" in selected and "var(--text)" in selected
    assert "--accent" not in selected and "--err" not in selected and "--alarm" not in selected
    assert 'content: "\\2713"' in _rule(css, '.seg-opt[aria-checked="true"]::before')
    # The track and knob of a switch are neutral too.
    for selector in (".switch .track", '.switch[aria-checked="true"] .track'):
        assert "--accent" not in _rule(css, selector)
    assert "--accent" in _rule(css, ".seg-opt:focus-visible")


def test_the_helper_that_every_chooser_shares_is_served(assets):
    js = assets.get("/static/shell.js").text
    for marker in ('"ArrowRight"', '"ArrowLeft"', '"Home"', '"End"', "% opts.length",
                   'aria-disabled', "o.tabIndex = on ? 0 : -1"):
        assert marker in js, marker
    assert "wireSeg: wireSeg" in js
    assert 'SP.wireSeg(el("apply-mode-seg")' in assets.get("/static/apply.js").text


# ======================================================================
# The real page
# ======================================================================


def _chromium() -> str:
    pytest.importorskip("playwright.sync_api")
    pytest.importorskip("uvicorn")
    path = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(path).exists():
        pytest.skip(f"no Chromium at {path} (set ATOO_TEST_CHROMIUM)")
    return path


def _serve(app):
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{port}/"


def _checked(page, selector: str) -> str:
    return page.evaluate(
        "(s) => [...document.querySelectorAll(s + ' [role=radio]')]"
        ".find(o => o.getAttribute('aria-checked') === 'true').dataset.value", selector)


def test_the_choosers_work_by_mouse_and_keyboard_in_a_real_browser(tmp_path, monkeypatch):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    server, thread, url = _serve(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                     " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
                page.goto(url)

                # -- Theme: three options, chosen directly ------------------
                assert _checked(page, "#theme-seg") == "dark"
                page.click("#theme-seg [data-value=light]")
                assert page.evaluate("document.documentElement.dataset.theme") == "light"
                assert page.evaluate("localStorage.getItem('atoo.theme')") == "light"
                page.click("#theme-seg [data-value=auto]")
                assert page.evaluate("document.documentElement.dataset.theme") is None
                assert page.evaluate("localStorage.getItem('atoo.theme')") == "auto"
                page.click("#theme-seg [data-value=dark]")
                assert page.evaluate("document.documentElement.dataset.theme") == "dark"
                # One tab stop: the selected option; the others are -1.
                assert page.evaluate(
                    "[...document.querySelectorAll('#theme-seg [role=radio]')].map(o => o.tabIndex)"
                ) == [-1, -1, 0]

                # -- Apply mode: arrows move AND select, with wrap -----------
                page.click("#nav-apply")
                full = page.locator("#apply-mode-full")
                assert full.get_attribute("aria-checked") == "true"
                full.focus()
                page.keyboard.press("ArrowRight")
                assert _checked(page, "#apply-mode-seg") == "amend"
                assert page.evaluate("document.activeElement.id") == "apply-mode-amend"
                assert page.locator("#patch-change-text").is_visible()
                page.keyboard.press("ArrowRight")           # wraps
                assert _checked(page, "#apply-mode-seg") == "full"
                page.keyboard.press("ArrowLeft")            # wraps back
                assert _checked(page, "#apply-mode-seg") == "amend"
                page.keyboard.press("Home")
                assert _checked(page, "#apply-mode-seg") == "full"
                page.keyboard.press("End")
                assert _checked(page, "#apply-mode-seg") == "amend"
                page.keyboard.press("Enter")                # on the selected: nothing
                assert _checked(page, "#apply-mode-seg") == "amend"
                assert "Patch" in page.locator("#apply-mode-hint").inner_text()
                page.click("#apply-mode-full")
                assert _checked(page, "#apply-mode-seg") == "full"
                assert page.evaluate(
                    "[...document.querySelectorAll('#apply-mode-seg [role=radio]')]"
                    ".map(o => o.tabIndex)") == [0, -1]

                # The selected option is a neutral fill, an action is not.
                colours = page.evaluate("""() => {
                    const bg = s => getComputedStyle(document.querySelector(s)).backgroundColor;
                    const root = getComputedStyle(document.documentElement);
                    const tok = n => { const d = document.createElement('i');
                        d.style.color = root.getPropertyValue(n); document.body.appendChild(d);
                        const c = getComputedStyle(d).color; d.remove(); return c; };
                    return { selected: bg('#apply-mode-full'), other: bg('#apply-mode-amend'),
                             accent: tok('--accent'), strong: tok('--border-strong'),
                             err: tok('--err-solid'), preview: bg('#apply-preview-btn') };
                }""")
                assert colours["selected"] == colours["strong"]
                assert colours["selected"] not in (colours["accent"], colours["err"])
                assert colours["preview"] == colours["accent"]
                assert colours["other"] != colours["selected"]

                # -- A locked group: aria-disabled, dashed, no fill ----------
                page.evaluate("""() => {
                    const g = document.getElementById('apply-mode-seg');
                    g.classList.add('is-locked'); g.setAttribute('aria-disabled', 'true');
                    g.querySelectorAll('[role=radio]').forEach(o => { o.disabled = true; });
                }""")
                assert page.evaluate(
                    "getComputedStyle(document.getElementById('apply-mode-seg')).borderStyle") == "dashed"
                page.evaluate("document.getElementById('apply-mode-amend').click()")
                assert _checked(page, "#apply-mode-seg") == "full"
                page.evaluate("""() => {
                    const g = document.getElementById('apply-mode-seg');
                    g.classList.remove('is-locked'); g.removeAttribute('aria-disabled');
                    g.querySelectorAll('[role=radio]').forEach(o => { o.disabled = false; });
                }""")

                # -- Which console: Demo locks the address and port ----------
                page.click("#console-change-btn")
                assert _checked(page, "#console-kind-seg") == "desk"
                assert page.locator("#console-edit-address").is_enabled()
                page.focus("#console-kind-desk")
                page.keyboard.press("ArrowRight")
                assert _checked(page, "#console-kind-seg") == "demo"
                assert page.locator("#console-edit-address").is_disabled()
                assert page.locator("#console-edit-port").is_disabled()
                page.keyboard.press("ArrowLeft")
                assert _checked(page, "#console-kind-seg") == "desk"
                assert page.locator("#console-edit-address").is_enabled()
                page.click("#console-cancel-btn")

                # -- Watch: two switches -------------------------------------
                page.click("#nav-watch")
                flash = page.locator("#watch-flash-on")
                assert flash.get_attribute("role") == "switch"
                assert flash.get_attribute("aria-checked") == "false"
                assert flash.locator(".word").inner_text() == "Off"
                flash.focus()
                page.keyboard.press("Space")
                assert flash.get_attribute("aria-checked") == "true"
                assert flash.locator(".word").inner_text() == "On"
                assert page.evaluate("localStorage.getItem('atoo.watchFlash')") == "1"
                page.keyboard.press("Enter")
                assert flash.get_attribute("aria-checked") == "false"
                assert page.evaluate("localStorage.getItem('atoo.watchFlash')") == "0"
                virtual = page.locator("#watch-virtual")
                virtual.click()
                assert virtual.get_attribute("aria-checked") == "true"
                assert page.locator("#vs-pill").is_visible()
                virtual.click()
                assert virtual.get_attribute("aria-checked") == "false"
                assert page.locator("#vs-pill").is_hidden()
                # The filter chips are not switches.
                assert page.locator(".count-pill[aria-pressed]").count() >= 1

                # -- 390 px: the fill makes the controls one row each --------
                page.set_viewport_size({"width": 390, "height": 900})
                page.click("#nav-apply")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                box = page.locator("#apply-mode-seg").bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= 390
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
