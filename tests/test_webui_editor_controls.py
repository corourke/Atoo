"""Save and Discard sit at the top of every Build editor.

The conventions editor and the instructions editor put their unsaved tag,
Discard and Save in the block's own header, above the text. The input
list had them in a toolbar below the table, which on a long list is off
the screen. They are now in the input list's header too, in the same
order (tag, Discard, Save), and that header stays at the top while the
rows scroll. A read-only show keeps the pair up, locked, with the reason
beside it.

Watch's conditions editor and step 04's input columns already have theirs
at the top of what they edit; this file pins that they stay there.

That is layout, which the Python suite cannot see, so:

* the asset tests always run and pin the served markup by where the
  controls are in it;
* the Chromium test drives the real page against a real server on a
  loopback port: it edits a long list, scrolls it to the end and checks
  Save is still on the screen. It skips where Playwright or a Chromium is
  not installed.

Every bundle is built in the test; nothing under `examples/` is read.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import webui  # noqa: E402
from atoo.webui import create_app  # noqa: E402

ROWS = 40
INPUT_CSV = "order,patch,name,category,type,model,phantom,notes\n" + "".join(
    f"{n},LCL {n},Input {n},drums,Mic,SM57,FALSE,\n" for n in range(1, ROWS + 1))


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def demo_copy(tmp_path, monkeypatch):
    """The server's Demo show is a scratch copy of the packaged one."""
    copy = tmp_path / "package" / "starter"
    shutil.copytree(webui.DEMO_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(webui, "DEMO_ROOT", copy)
    monkeypatch.setattr(webui, "DEMO_SHOW_DIR", copy / webui.DEMO_SHOW_DIR.name)
    monkeypatch.setattr(webui, "DEMO_CONVENTIONS", copy / "conventions.md")
    monkeypatch.setattr(webui, "DEMO_PRESETS", copy / "presets")
    return copy


@pytest.fixture
def show(home):
    show = home / "shows" / "club"
    show.mkdir(parents=True)
    (show / "input.csv").write_text(INPUT_CSV)
    (show / "instructions.md").write_text("## Channels\n- Kick first.\n")
    (home / "conventions.md").write_text("## Inputs\n- Patch in list order.\n")
    return show


@pytest.fixture
def client(show, home):
    app = create_app(initial_bundle=str(show), initial_conventions=str(home / "conventions.md"))
    with fastapi_testclient.TestClient(app) as c:
        yield c


# ---- the served markup ------------------------------------------------------


def _panel(html: str, panel_id: str) -> str:
    start = html.index(f'id="{panel_id}"')
    nxt = re.search(r'<section id="panel-[a-z-]+" class="step-panel"', html[start:])
    return html[start:start + nxt.start()] if nxt else html[start:]


def test_the_three_editors_carry_save_and_discard_in_their_header(client):
    html = client.get("/static/shell.html").text
    cases = (
        ("panel-conventions", 'id="conv-ro-badge"', "conv-cancel-btn", "conv-save-btn", 'id="conv-text"'),
        ("panel-input-list", 'id="input-dirty-badge"', "input-discard-btn", "input-save-btn", 'id="input-table-wrap"'),
        ("panel-instructions", 'id="instr-edit-badge"', "instr-cancel-btn", "instr-save-btn", 'id="instr-text"'),
    )
    for panel_id, tag_marker, discard, save, editor in cases:
        panel = _panel(html, panel_id)
        head_start = panel.rindex('<div class="section-head', 0, panel.index(f'id="{save}"'))
        head = panel[head_start:panel.index("</div>", panel.index(f'id="{save}"'))]
        # One header holds the tag, then Discard, then Save...
        assert head.index(tag_marker) < head.index(f'id="{discard}"') < head.index(f'id="{save}"'), panel_id
        # ...and it comes before what is being edited, not after it.
        assert panel.index(f'id="{discard}"') < panel.index(f'id="{save}"') < panel.index(editor), panel_id
        # Discard is the quiet one, Save the primary one, as everywhere.
        assert re.search(rf'class="btn btn-secondary btn-sm" id="{discard}"', head), panel_id
        assert re.search(rf'class="btn btn-primary btn-sm" id="{save}"', head), panel_id


def test_the_input_lists_bottom_toolbar_no_longer_holds_save_or_discard(client):
    html = client.get("/static/shell.html").text
    toolbar = html[html.index('id="input-edit-toolbar"'):]
    toolbar = toolbar[:toolbar.index("</div>")]
    assert 'id="input-add-row"' in toolbar
    for gone in ("input-save-btn", "input-discard-btn", "input-lock-reason"):
        assert gone not in toolbar
    # The read-only reason is in the header, beside the locked pair.
    head = html[html.index('id="input-head"'):]
    head = head[:head.index('id="input-save-btn"')]
    assert head.index('id="input-lock-reason"') < head.index('id="input-discard-btn"')


def test_the_input_lists_header_stays_put_while_the_rows_scroll(client):
    css = client.get("/static/styles.css").text
    rule = css[css.index(".input-head {"):]
    rule = rule[:rule.index("}")]
    assert "position: sticky" in rule and "top: 0" in rule
    js = client.get("/static/shell.js").text
    # The header is always there, so the pair follows whether a list loaded.
    assert "if (node) node.hidden = !inputListLoaded || (!dirty && !locked);" in js


def test_watch_conditions_and_step_04_keep_theirs_at_the_top_of_what_they_edit(client):
    html = client.get("/static/shell.html").text
    watch = html[html.index('id="wc-panel"'):]
    assert watch.index('id="wc-save-btn"') < watch.index('id="wc-table-wrap"')
    plan = html[html.index('id="plan-input-toolbar"'):]
    assert plan.index('id="plan-input-save-btn"') < plan.index('id="plan-input-save-note"')


# ---- the real page ----------------------------------------------------------


def _chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    path = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(path).exists():
        pytest.skip(f"no Chromium at {path} (set ATOO_TEST_CHROMIUM)")
    return sync_api, path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def served(show, home, demo_copy):
    uvicorn = pytest.importorskip("uvicorn")
    app = create_app(initial_bundle=str(show), initial_conventions=str(home / "conventions.md"))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the test server did not start")
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=5)


def _open_step(page, step):
    page.evaluate("s => document.getElementById('tab-' + s).click()", step)
    page.wait_for_selector(f"#panel-{step}:not([hidden])", state="attached")


# The control's box, and the box of the step's scrolling area.
BOX = "s => { const r = document.querySelector(s).getBoundingClientRect(); return {top: r.top, bottom: r.bottom, height: r.height}; }"
SCROLLER = "() => { const r = document.querySelector('#panel-input-list .step-scroll').getBoundingClientRect(); return {top: r.top, bottom: r.bottom}; }"


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 800}])
def test_save_is_above_a_long_list_and_stays_on_screen_when_it_is_scrolled(served, show, viewport):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport=viewport)
            page.goto(served)
            page.wait_for_selector("#input-rows tr", state="attached")
            _open_step(page, "input-list")
            assert page.locator("#input-rows tr").count() == ROWS

            # Nothing to save: the pair is hidden, not locked.
            assert not page.locator("#input-save-btn").is_visible()
            page.locator('#input-rows tr:nth-child(2) [data-col="name"]').fill("Snare Top")
            page.wait_for_selector("#input-save-btn:not([disabled])")

            # Above the table, in the block's header, tag then Discard then Save.
            save, discard = page.evaluate(BOX, "#input-save-btn"), page.evaluate(BOX, "#input-discard-btn")
            table = page.evaluate(BOX, "#input-table-wrap")
            assert save["bottom"] <= table["top"] and discard["bottom"] <= table["top"]
            # (A narrow screen wraps the header, so order is line, then left to right.)
            places = page.evaluate("""() => ['input-dirty-badge', 'input-discard-btn', 'input-save-btn']
                .map((id) => { const r = document.getElementById(id).getBoundingClientRect();
                               return [Math.round(r.top / 24), r.left]; })""")
            assert places == sorted(places)

            # Scroll to the end of the step: Save is still in view, and works.
            page.evaluate("""() => {
              document.querySelectorAll('#panel-input-list .step-scroll, .build-body')
                .forEach((e) => { e.scrollTop = e.scrollHeight; });
              const wrap = document.getElementById('input-table-wrap');
              wrap.scrollTop = wrap.scrollHeight;
            }""")
            time.sleep(0.2)
            now = page.evaluate(BOX, "#input-save-btn")
            assert 0 <= now["top"] and now["bottom"] <= viewport["height"], now
            page.click("#input-save-btn")
            page.wait_for_selector("#input-save-btn", state="hidden")
            assert "Snare Top" in (show / "input.csv").read_text()
        finally:
            browser.close()


def test_a_read_only_show_keeps_the_pair_up_locked_in_the_header(served):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            r = page.request.post(served + "api/console", data={"demo": True})
            assert r.ok, r.text()
            page.goto(served)
            page.wait_for_function("document.body.classList.contains('is-demo-show')")
            page.wait_for_selector("#input-rows tr", state="attached")
            _open_step(page, "input-list")
            table = page.evaluate(BOX, "#input-table-wrap")
            for button in ("#input-discard-btn", "#input-save-btn", "#input-lock-reason"):
                assert page.locator(button).is_visible(), button
                assert page.evaluate(BOX, button)["bottom"] <= table["top"], button
            for button in ("#input-discard-btn", "#input-save-btn"):
                assert page.locator(button).is_disabled(), button
            assert page.locator("#input-lock-reason").inner_text() == "the Demo show is read-only"
        finally:
            browser.close()
