"""Build steps 01-03 and the pipeline tiles, to the UI style guide
(docs/developer/ui-style.md).

The rule this file is mostly about is §4/§7's: *a cell is an input only
when it can be edited and saved.* On a read-only show (the Demo) step
02's input table is text -- no inputs, no drag handle, no move, insert or
remove buttons, no + Add row -- and Save and Discard are locked with the
reason in words. On a writable show the table still edits and saves.

That is browser behaviour, and the Python suite cannot see a browser. So:

* the asset tests always run, and pin what the served page carries;
* `test_a_read_only_show_draws_text_and_a_writable_one_still_saves`
  drives the real page in Chromium through Playwright, against a real
  server on a loopback port. It skips where Playwright or a Chromium
  is not installed.

Every bundle here is built in the test; the Demo is a scratch copy of
the packaged one (as `test_demo_show.py` does), so nothing under
`examples/` or the package is read for its contents or written.
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

INPUT_CSV = (
    "order,patch,name,category,type,model,phantom,notes\n"
    "1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,inside the kick\n"
    "2,LCL 2,Snare,drums,Mic,SM57,FALSE,\n"
    "-,LCL 3,Guest Vox,vocals,Mic,SM58,FALSE,\n"
)


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
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(home / "conventions.md"))
    with fastapi_testclient.TestClient(app) as c:
        yield c


# ---- the served assets ------------------------------------------------------


def _tiles(html: str) -> str:
    start = html.index('id="build-steps"')
    return html[start:html.index('class="build-body"', start)]


def _steps_01_03(html: str) -> str:
    start = html.index('id="panel-conventions"')
    return html[start:html.index('id="panel-plan"', start)]


def test_the_tiles_use_the_guides_tags_and_quiet_buttons(client):
    html = client.get("/").text
    tiles = _tiles(html)
    # §6: one tag family each. The tile states are `.state`, House is a
    # property, and the layer count is meta text, not a state.
    assert "state-badge" not in tiles
    assert "house-tag" not in tiles
    assert '<span class="prop" title="Not part of the show bundle">House</span>' in tiles
    assert 'class="pipe-stat pipe-stat-counts" id="status-layers"' in tiles
    # §4: Change file and New file are quiet buttons, not brass-on-tint.
    for button_id in ("change-conventions", "new-conventions", "change-input-list",
                      "change-instructions", "new-instructions", "plan-browse-btn"):
        assert re.search(r'class="btn btn-quiet" id="%s"' % button_id, tiles), button_id
    assert "pipe-change-btn" not in tiles


def test_steps_01_03_use_the_guides_states_folds_and_empty_states(client):
    steps = _steps_01_03(client.get("/").text)
    # §6 and §5: Unsaved changes and Editing house style are yellow
    # states; brass never means a state.
    for badge_id in ("conv-ro-badge", "input-dirty-badge", "instr-edit-badge"):
        assert f'<span class="state is-warn" id="{badge_id}"' in steps, badge_id
    assert "state-drafted" not in steps
    # §3: the Example is a fold, with the word as a property tag.
    assert steps.count('<details class="fold source-example"') == 2
    assert steps.count('<span class="prop">Example</span>') == 2
    assert "conv-card" not in steps
    # §8: the one empty state, then its way out, a secondary button.
    for empty_id in ("conv-empty", "input-empty", "instr-empty"):
        assert f'<p class="empty" id="{empty_id}"' in steps, empty_id
    assert "step-empty\"" not in steps
    assert ('<button type="button" class="btn btn-secondary btn-sm" '
            'id="instr-create-btn">Create instructions.md</button>') in steps
    # §4: one primary per block. View source, View house file and Patch
    # this show are quiet; + Add row is secondary, not the dashed ghost
    # that now reads as locked.
    assert 'class="btn btn-quiet" id="input-source-toggle-btn"' in steps
    assert 'class="btn btn-quiet" id="house-conv-toggle-btn"' in steps
    assert 'class="btn btn-quiet" data-goto-amend' in steps
    assert 'class="btn btn-secondary btn-sm" id="input-add-row"' in steps
    # Step 01 has one header: the file's path is inside its File section.
    file_section = steps[steps.index("<h3>File</h3>"):steps.index('id="conv-text"')]
    assert 'id="conv-house-file"' in file_section
    # §4: a read-only show's Save and Discard are locked, with the reason.
    assert ('<span class="lock-reason" id="input-lock-reason" hidden>'
            'the Demo show is read-only</span>') in steps


def test_the_js_draws_tile_states_and_read_only_rows_by_the_guide(client):
    shell = client.get("/static/shell.js").text
    setup = client.get("/static/setup.js").text
    # The tile states map to `.state` meanings: green, yellow, red, grey.
    assert 'loaded: { text: "Loaded", cls: "is-ok" }' in shell
    assert 'missing: { text: "Missing", cls: "is-err" }' in shell
    assert 'stale: { text: "Stale", cls: "is-warn" }' in shell
    assert 'badge.className = "state-badge' not in shell
    assert '["Plan current", "is-ok"]' in setup
    assert '["Loaded", "is-ok"] : ["Not built", ""]' in setup
    # A read-only show's rows are drawn as text.
    assert "function readOnlyInputRow(" in shell
    assert "if (!isNew && inputReadOnly()) return readOnlyInputRow(line, values);" in shell
    assert 'table.classList.toggle("is-readonly", inputReadOnly())' in shell
    # §5: instructions.md is optional, so a missing one is a neutral
    # Not set on its tile, never a red Missing (Nora).
    assert 'if (slot === "instructions" && key === "missing") key = "notset";' in shell


def test_the_css_hides_row_controls_on_a_read_only_table_and_keeps_the_floor(client):
    css = client.get("/static/styles.css").text
    assert "#input-table.is-readonly :is(.col-move, .col-remove) { display: none; }" in css
    assert ".build-body .source-editor[readonly]" in css
    # The table scrolls inside its box, never the page (§7).
    assert "#input-table-wrap { position: relative; }" in css
    # §2: nothing in this change's block is under 11px, and the move
    # arrows (7px before) are at the floor.
    block = css[css.index("Build 01-03 and the tiles, to the guide"):]
    block = block[:block.index("The one locked look")]
    sizes = [float(s) for s in re.findall(r"font-size:\s*([\d.]+)px", block)]
    assert sizes and min(sizes) >= 11, sizes
    assert ".move-btn { font-size: 11px;" in block
    # A read-only show hides what would change its files (§4), and its
    # read-only file text still shows the focus ring.
    assert ("body.is-demo-show #build-steps :is(#change-conventions, #new-conventions, "
            "#change-input-list,") in block
    assert "body.is-demo-show .build-body .source-example-actions," in block
    assert (".build-body .source-editor[readonly]:focus-visible "
            "{ outline: 2px solid var(--accent); outline-offset: 4px; }") in block
    # At phone width a tile's name wraps rather than being cut off.
    assert "@media (max-width: 600px)" in block
    assert "#build-steps .pipe-stop-top { flex-wrap: wrap; row-gap: 4px; }" in block


# ---- the real page, in Chromium -------------------------------------------


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
    """The app on a real loopback port, for a real browser."""
    uvicorn = pytest.importorskip("uvicorn")
    app = create_app(initial_bundle=str(show),
                     initial_conventions=str(home / "conventions.md"))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
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
    # The tile's own click (a click at its centre could land on Change file).
    page.evaluate("s => document.getElementById('tab-' + s).click()", step)
    page.wait_for_selector(f"#panel-{step}:not([hidden])", state="attached")


VISIBLE_INPUTS = ("() => Array.from(document.querySelectorAll('#input-table input, "
                  "#input-table select, #input-table textarea')).filter(i => i.type !== 'hidden').length")
VISIBLE = "s => { const e = document.querySelector(s); return !!e && e.offsetParent !== null; }"


def test_a_read_only_show_draws_text_and_a_writable_one_still_saves(served, show):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            # A writable show: the table is the editor, and Save writes.
            page.goto(served)
            page.wait_for_selector("#input-rows tr", state="attached")
            _open_step(page, "input-list")
            assert page.evaluate(VISIBLE_INPUTS) > 0
            assert page.evaluate(VISIBLE, ".move-btn")
            assert page.evaluate(VISIBLE, "#input-add-row")
            assert not page.evaluate(VISIBLE, "#input-save-btn")
            assert not page.evaluate(VISIBLE, "#input-lock-reason")
            name = page.locator('#input-rows tr:nth-child(2) [data-col="name"]')
            name.fill("Snare Top")
            page.wait_for_selector("#input-save-btn:not([disabled])")
            assert page.evaluate(VISIBLE, "#input-dirty-badge")
            page.click("#input-save-btn")
            page.wait_for_selector("#input-save-btn", state="hidden")
            assert "Snare Top" in (show / "input.csv").read_text()
            assert "Kick" in (show / "input.csv").read_text()
            # Step 01's file is an editor here.
            _open_step(page, "conventions")
            assert not page.locator("#conv-text").evaluate("e => e.readOnly")
            assert page.evaluate(VISIBLE, "#change-conventions")

            # No instructions.md: optional, so the tile is a neutral Not set.
            instructions = show / "instructions.md"
            kept = instructions.read_text()
            instructions.unlink()
            page.goto(served)
            page.wait_for_function(
                "document.getElementById('badge-instructions').textContent === 'Not set'")
            assert page.locator("#badge-instructions").get_attribute("class") == "state"
            instructions.write_text(kept)

            # The Demo: read-only. The cells are text.
            r = page.request.post(served + "api/console", data={"demo": True})
            assert r.ok, r.text()
            page.goto(served)
            page.wait_for_function("document.body.classList.contains('is-demo-show')")
            page.wait_for_selector("#input-rows tr", state="attached")
            _open_step(page, "input-list")
            assert page.locator("#input-rows tr").count() > 0
            assert page.evaluate(VISIBLE_INPUTS) == 0
            assert page.locator("#input-table .move-btn, #input-table .drag-handle, "
                                "#input-table .insert-row-btn, #input-table .col-remove button"
                                ).count() == 0
            assert not page.evaluate(VISIBLE, "#input-table th.col-move")
            assert not page.evaluate(VISIBLE, "#input-add-row")
            # Save and Discard stay up, locked, and say why.
            for button in ("#input-save-btn", "#input-discard-btn"):
                assert page.evaluate(VISIBLE, button), button
                assert page.locator(button).is_disabled(), button
            assert page.evaluate(VISIBLE, "#input-lock-reason")
            assert page.locator("#input-lock-reason").inner_text() == "the Demo show is read-only"
            # Steps 01 and 03: read-only text, not an editable box.
            _open_step(page, "conventions")
            assert page.locator("#conv-text").evaluate("e => e.readOnly")
            assert page.locator("#conv-text").evaluate(
                "e => getComputedStyle(e).borderTopColor === 'rgba(0, 0, 0, 0)'")
            # ...that is still a Tab stop, and shows the brass ring (§4).
            page.focus("#tab-conventions")
            for _ in range(20):
                if page.evaluate("document.activeElement.id") == "conv-text":
                    break
                page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.id") == "conv-text"
            assert page.locator("#conv-text").evaluate(
                "e => getComputedStyle(e).outlineStyle") != "none"
            # What would change the files is hidden, not locked (§4).
            for control in ("#change-conventions", "#new-conventions", "#change-input-list",
                            "#change-instructions", "#plan-browse-btn", "#conv-example-insert"):
                assert not page.evaluate(VISIBLE, control), control
        finally:
            browser.close()
