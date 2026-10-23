"""Watch, to the UI style guide (docs/developer/ui-style.md;
the drawing is mockups/ui-audit/sample-watch.html).

The bug first (§4: "a button that would do nothing must be locked"): on
the empty Watch page -- no show, no console -- **Start watching** was a
live brass button, and with no file the conditions' **Save** was too.
Now Start is locked with "Locked: no console. Choose one in the bar",
and Save with "Locked: no watch-conditions file. ...". On the read-only
Demo the conditions are text, the controls that would change the file
are hidden, and Save stays up, locked, with "Locked: the Demo show is
read-only" (as Build step 02 does).

The rest is the look: the header is a block header outside its box, the
box is the alert table, and a verdict bar heads it -- TROUBLE, WARNING,
ALL OK, or NOT WATCHING in grey before Start (§10).

The Python suite cannot see a browser, so the asset tests pin what the served page
carries, and the Chromium tests drive the real page against a real
server on a loopback port. They skip where Playwright or Chromium is
missing. The watch socket is mocked in the verdict test so each state is
exact; the Demo test runs the real Demo rig. Every show is built in the
test; the Demo is a scratch copy of the packaged one.
"""

from __future__ import annotations

import json
import os
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

WATCH_JSON = {
    "watch_conditions": [
        {"id": "kick-unmuted", "description": "The kick drives the room.",
         "channel": "Kick", "field": "muted", "operator": "==", "value": False,
         "severity": "error"},
    ],
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    for name in ("ATOO_CONSOLE", "ATOO_CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
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
    (show / "input.csv").write_text(
        "order,patch,name,category,type,model,phantom,notes\n1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,\n")
    (show / "watch.json").write_text(json.dumps(WATCH_JSON))
    return show


@pytest.fixture
def assets(home):
    with fastapi_testclient.TestClient(create_app()) as client:
        yield {
            "html": client.get("/").text,
            "js": client.get("/static/watch.js").text,
            "css": client.get("/static/styles.css").text,
        }


def _watch_panel(html):
    return html[html.index('id="mode-watch"'):html.index("The findings dock")]


def _fn(js, signature):
    body = js[js.index(signature):]
    return body[:body.index("\n  }\n")]


# ---- the served assets ------------------------------------------------------


def test_start_and_save_are_served_locked_and_unlocked_only_by_the_script(assets):
    """Before the script has said there is a console (or a file), neither
    is a live button."""
    panel = _watch_panel(assets["html"])
    for button in ('id="start-btn"', 'id="wc-save-btn"'):
        start = panel.index(button)
        tag = panel[panel.rindex("<", 0, start):panel.index(">", start)]
        assert " disabled" in tag, button
    assert 'class="lock-reason" id="start-lock" hidden>no console. Choose one in the bar<' in panel
    assert 'class="lock-reason" id="wc-save-lock"' in panel
    js = assets["js"]
    lock = _fn(js, "function startLockReason()")
    assert '!desk.demo && !barLabel(desk)' in lock and '"no console. Choose one in the bar"' in lock
    render = _fn(js, "function renderStartLock()")
    assert "startBtn.disabled = running || startPending || !!reason;" in render
    assert "startLock.hidden = !reason;" in render
    # A console chosen in the bar unlocks it, without a reload.
    assert "renderStartLock(); });" in js[js.index("SP.onConsoleChange("):]
    save = _fn(js, "function wcSaveLockReason()")
    assert '"the Demo show is read-only"' in save
    assert "!wcLoadedPath && !wcBundle()" in save and '"no watch-conditions file.' in save
    render = _fn(js, "function wcRenderSave()")
    assert "wcSaveBtn.disabled = !!reason || !wcDirty || wcSaving;" in render
    # Hidden with nothing to save, except on a read-only show (§4).
    assert "const shown = wcDirty || wcReadOnly();" in render


def test_the_verdict_bar_heads_the_alert_table_inside_its_box(assets):
    panel = _watch_panel(assets["html"])
    # The verdict is the box's head but a sibling of it, so it
    # can pin under the Watch header for the whole page.
    box = panel[panel.index('id="watch-verdict"'):panel.index('id="watch-suppressed"')]
    assert box.index('id="watch-verdict"') < box.index('class="panel box table-box watch-table-wrap"')
    assert box.index('class="panel box table-box watch-table-wrap"') < box.index('id="alert-table"')
    # The three counts moved into it, their filter hooks unchanged.
    verdict = box[box.index('id="watch-verdict"'):box.index('id="alert-table"')]
    for sev in ("error", "warning", "info"):
        assert f'class="count-pill count-{sev}" data-sev="{sev}"' in verdict
    assert 'id="empty-state" class="empty is-centered"' in box
    js = assets["js"]
    for word in ('"Trouble"', '"Warning"', '"All OK"', '"Not watching"'):
        assert word in js[js.index("const VERDICT = {"):]
    render = _fn(js, "function renderVerdict(worst)")
    assert 'verdictBar.className = "verdict-bar"' in render
    css = assets["css"]
    for cls, solid in (("is-trouble", "--alarm-solid"), ("is-warn", "--caution-solid"),
                       ("is-ok", "--ok-solid")):
        assert f".verdict-bar.{cls} {{ border-left-color: var({solid});" in css
    assert "border-left: 6px solid var(--text-off)" in css
    assert "font-size: 22px; font-weight: 800" in css


def test_the_connection_is_a_state_tag_not_a_blue_pill(assets):
    js = assets["js"]
    conn = _fn(js, "function setConnPill(state, label)")
    assert 'connPill.className = "state";' in conn
    assert 'connPill.classList.add("is-ok", "is-live");' in conn
    assert 'connPill.classList.add("is-err");' in conn
    assert "pill-watching" not in js and "pill-idle" not in js
    assert ".pill-watching" not in assets["css"]


def test_the_folds_take_their_headers_outside(assets):
    panel = _watch_panel(assets["html"])
    for fold, title in (("watch-suppressed", "Suppressed"), ("watch-about", "This watch"),
                        ("wc-panel", "Watch conditions")):
        part = panel[panel.index(f'<details id="{fold}"'):]
        part = part[:part.index("</summary>")]
        assert '<summary class="block-head">' in part, fold
        assert f"<h2>{title}</h2>" in part and 'class="notation' in part, fold
        assert 'class="btn btn-quiet watch-fold-hint' in part, fold
    # The count is the notation, not in brackets.
    assert '"(" + items.length + ")"' not in assets["js"]


def test_on_a_read_only_show_the_conditions_are_text(assets):
    js, css = assets["js"], assets["css"]
    row = js[js.index("function wcBuildRow(cond, index)"):js.index("function wcRenderTable()")]
    readonly = row[row.index("if (readOnly) {"):row.index('const idCell = document.createElement("td");')]
    assert "wcTextCell(tr, cond.channel" in readonly and "return tr;" in readonly
    assert 'tag.className = "sev sev-" + sev;' in readonly
    assert "input" not in readonly.replace("wcTextCell", "")
    assert 'tag.className = "state is-info wc-source-drafted";' in row
    assert 'tag.className = "prop wc-source-yours";' in row
    assert "wc-source-drafted:hover" not in css.replace("button.wc-source-drafted:hover", "")
    assert "body.is-demo-show :is(#wc-change-btn, #wc-new-btn, #wc-add-btn) { display: none; }" in css
    assert "#wc-table.is-readonly .wc-col-remove { display: none; }" in css


# ---- the real page, in Chromium -------------------------------------------


def _chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    path = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(path).exists():
        pytest.skip(f"no Chromium at {path} (set ATOO_TEST_CHROMIUM)")
    return sync_api, path


def _serve(app):
    uvicorn = pytest.importorskip("uvicorn")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
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
    return server, thread, f"http://127.0.0.1:{port}/"


@pytest.fixture
def served_empty(home, demo_copy):
    """No show and no console: the empty Watch page of the bug."""
    server, thread, url = _serve(create_app())
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def served_show(show, demo_copy):
    server, thread, url = _serve(create_app(
        initial_bundle=str(show), initial_watch_conditions_path=str(show / "watch.json")))
    yield url
    server.should_exit = True
    thread.join(timeout=5)


VISIBLE = "s => { const e = document.querySelector(s); return !!e && e.offsetParent !== null; }"


def _open_watch(page, url):
    page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1'); } catch (e) {}")
    page.goto(url + "#watch")
    page.wait_for_selector("#mode-watch:not([hidden])")


def test_with_no_console_start_is_locked_and_with_no_file_save_is_locked(served_empty):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            _open_watch(page, served_empty)
            page.wait_for_function(
                "document.getElementById('watch-notation').textContent === 'No console'")
            assert page.locator("#start-btn").is_disabled()
            assert page.evaluate(VISIBLE, "#start-lock")
            assert page.locator("#start-lock").inner_text() == "no console. Choose one in the bar"
            # The one locked look: no hue, a dashed edge (§4).
            assert page.locator("#start-btn").evaluate(
                "e => getComputedStyle(e).borderTopStyle") == "dashed"
            assert page.locator("#watch-verdict-word").inner_text() == "NOT WATCHING"
            # Nothing to save: Save is hidden. A row typed with no file and
            # no show has nowhere to go: Save shows, locked, and says why.
            assert not page.evaluate(VISIBLE, "#wc-save-btn")
            page.click("#wc-add-btn")
            assert page.evaluate(VISIBLE, "#wc-save-btn")
            assert page.locator("#wc-save-btn").is_disabled()
            assert page.locator("#wc-save-lock").inner_text().startswith("no watch-conditions file")

            # A console in the bar unlocks Start without a reload.
            # (Set in the bar's own editor. Nothing is sent to it: Watch
            # is not started.)
            page.click("#console-change-btn")
            page.fill("#console-edit-address", "192.0.2.10")
            page.click("#console-set-btn")
            page.wait_for_function("!document.getElementById('start-btn').disabled")
            assert not page.evaluate(VISIBLE, "#start-lock")
            assert "192.0.2.10" in page.locator("#watch-notation").inner_text()
        finally:
            browser.close()


def test_a_writable_show_saves_and_the_demo_is_text_with_save_locked(served_show, show):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            _open_watch(page, served_show)
            page.wait_for_selector("#wc-body tr")
            # The editor: inputs, Change file, + Add condition; Save hidden
            # until there is something to save, then a live primary.
            assert page.locator("#wc-body input").count() > 0
            assert page.evaluate(VISIBLE, "#wc-change-btn")
            assert not page.evaluate(VISIBLE, "#wc-save-btn")
            page.fill("#wc-body .wc-description", "The kick is the show.")
            page.wait_for_selector("#wc-save-btn:not([disabled])")
            assert not page.evaluate(VISIBLE, "#wc-save-lock")
            page.click("#wc-save-btn")
            page.wait_for_selector("#wc-save-btn", state="hidden")
            assert "The kick is the show." in (show / "watch.json").read_text()

            # The Demo: read-only. The cells are text, and only Save says so.
            r = page.request.post(served_show + "api/console", data={"demo": True})
            assert r.ok, r.text()
            page.reload()
            page.wait_for_function("document.body.classList.contains('is-demo-show')")
            page.wait_for_selector("#wc-body tr")
            assert page.locator("#wc-body tr").count() > 1
            assert page.locator("#wc-body input, #wc-body select, "
                                "#wc-body button:not(.wc-explain-btn)").count() == 0
            assert page.locator("#wc-body .sev").count() == page.locator("#wc-body tr").count()
            for control in ("#wc-change-btn", "#wc-new-btn", "#wc-add-btn"):
                assert not page.evaluate(VISIBLE, control), control
            assert page.evaluate(VISIBLE, "#wc-save-btn")
            assert page.locator("#wc-save-btn").is_disabled()
            assert page.locator("#wc-save-lock").inner_text() == "the Demo show is read-only"
            assert page.locator("#wc-fold-hint").inner_text() == "Show"
            # Drafted is a yellow state in the header; Yours is a property.
            assert page.evaluate(VISIBLE, "#wc-drafted-badge")
            assert "drafted, unreviewed" in page.locator("#wc-drafted-badge").text_content()
            assert page.locator("#wc-body .prop").count() > 0

            # The Demo rig, watched for real: green and live, and a verdict.
            assert not page.locator("#start-btn").is_disabled()
            assert page.locator("#watch-notation").inner_text().upper() == "DEMO RIG"
            page.fill("#interval", "0.5")
            page.click("#start-btn")
            page.wait_for_function(
                "['TROUBLE', 'WARNING', 'ALL OK'].includes("
                "document.getElementById('watch-verdict-word').innerText)", timeout=30000)
            assert page.locator("#conn-pill").get_attribute("class") == "state is-ok is-live"
            assert page.locator("#conn-pill").inner_text().upper() == "WATCHING DEMO"
            assert page.locator("#start-btn").is_disabled()
            assert not page.evaluate(VISIBLE, "#start-lock")
            page.click("#stop-btn")
            page.wait_for_function("!document.getElementById('start-btn').disabled")
            assert page.locator("#conn-pill").get_attribute("class") == "state"
        finally:
            browser.close()


def _finding(sev, rule, strip, title, detail):
    return {"rule_id": rule, "addresses": [rule], "severity": sev, "title": title,
            "detail": detail, "category": "watch", "strip": strip, "also": []}


ERROR = _finding("error", "WATCH:kick-unmuted", 'CH 1 "Kick"', "The kick drives the room.",
                 'CH 1 "Kick" is muted -- The kick drives the room.')
WARNING = _finding("warning", "CH002", 'DCA 1 "Drums"', "DCA Fader Low With Active Members",
                   "DCA 1 is at the floor.")
INFO = _finding("info", "CH001", 'CH 2 "Snare"', "Channel Not In Any DCA", "No DCA.")


@pytest.mark.parametrize("findings, word, cls, line, lit", [
    ([ERROR, WARNING, INFO], "TROUBLE", "is-trouble", 'CH 1 "Kick": is muted', {"error", "warning", "info"}),
    ([WARNING], "WARNING", "is-warn", 'DCA 1 "Drums": DCA fader low with active members', {"warning"}),
    ([INFO], "ALL OK", "is-ok", "Nothing on this desk is out of place.", {"info"}),
    ([], "ALL OK", "is-ok", "Nothing on this desk is out of place.", set()),
])
def test_the_verdict_reads_the_desk_and_lights_only_the_counts_that_are_not_zero(
        served_show, findings, word, cls, line, lit):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 900})

            def on_ws(ws):
                ws.send(json.dumps({"type": "status", "running": True, "label": "Demo"}))
                ws.send(json.dumps({"type": "event", "baseline": True, "all_findings": findings,
                                    "new_findings": [], "cleared_findings": [],
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "notes": []}))
            page.route_web_socket("**/ws/watch", on_ws)
            page.route("**/api/status", lambda r: r.fulfill(json={"running": True, "label": "Demo"}))
            _open_watch(page, served_show)
            page.wait_for_function(
                f"document.getElementById('watch-verdict-word').innerText === {json.dumps(word)}")
            assert cls in page.locator("#watch-verdict").get_attribute("class")
            assert page.locator("#watch-verdict-line").inner_text() == line
            for sev in ("error", "warning", "info"):
                pill = page.locator(f'.count-pill[data-sev="{sev}"]')
                assert ("has-count" in pill.get_attribute("class")) == (sev in lit), sev
            # The table's error and warning tags are the large solids.
            if findings:
                tag = page.locator("#alert-body tr:first-child .sev")
                assert "big" in tag.get_attribute("class")
                assert ("solid" in tag.get_attribute("class")) == (findings[0]["severity"] != "info")
            # Phone width: the verdict and counts wrap; the page never
            # scrolls sideways.
            assert page.evaluate("document.documentElement.scrollWidth") <= 390
        finally:
            browser.close()


def test_a_collapsed_folds_hint_sits_on_the_right_of_its_header(served_show):
    """Guide §3: "on the right: one state tag and the block's own actions".
    `.push` inside a fold summary once had no `margin-left: auto`, so the
    hint floated mid-row wherever the notation happened to end. A layout
    defect: the asset tests cannot see it."""
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            _open_watch(page, served_show)
            page.wait_for_selector("#wc-body tr")
            page.evaluate("document.querySelectorAll('details.watch-fold').forEach(d => d.open = false)")
            right = """s => { const r = document.querySelector(s).getBoundingClientRect(); return r.right; }"""
            for hint, summary in (("#wc-fold-hint", "#wc-panel > summary"),
                                  ("#watch-about .watch-fold-hint", "#watch-about > summary")):
                assert page.evaluate(VISIBLE, hint), hint
                edge, head = page.evaluate(right, hint), page.evaluate(right, summary)
                assert abs(head - edge) <= 2, (hint, edge, head)
            # Both hints end on the same line.
            assert abs(page.evaluate(right, "#wc-fold-hint")
                       - page.evaluate(right, "#watch-about .watch-fold-hint")) <= 2
            # With a draft badge beside it, the pair still ends on the edge.
            page.evaluate("""() => { const b = document.getElementById('wc-drafted-badge');
                                     b.hidden = false; b.textContent = '6 drafted, unreviewed'; }""")
            assert abs(page.evaluate(right, "#wc-panel > summary")
                       - page.evaluate(right, "#wc-fold-hint")) <= 2
            assert page.evaluate(right, "#wc-drafted-badge") < page.evaluate(right, "#wc-fold-hint")
            # Phone width: the hint wraps under the title, the page never scrolls sideways.
            page.set_viewport_size({"width": 390, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth") <= 390
        finally:
            browser.close()


def test_the_digest_is_meta_type_the_locked_buttons_say_why_and_unsaved_is_said_once(served_show):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            _open_watch(page, served_show)
            page.wait_for_selector("#wc-body tr")
            # The digest is a sentence in meta type, not label caps.
            style = page.locator("#watch-about-line").evaluate(
                "e => { const s = getComputedStyle(e); return [s.textTransform, s.letterSpacing, "
                "s.fontSize, s.fontWeight, s.textOverflow]; }")
            assert style[0] == "none" and style[1] in ("0px", "normal"), style
            assert style[2] == "12px" and style[3] == "400" and style[4] == "ellipsis", style
            # Idle: Stop is locked, with a title for hover and assistive technology.
            assert page.get_attribute("#stop-btn", "title") == "Locked: not watching"
            # No console chosen: Start is locked, and the title says why.
            assert page.get_attribute("#start-btn", "title") == (
                "Locked: no console. Choose one in the bar")
            # Unsaved is said by the tag in the box, not twice.
            page.fill("#wc-body .wc-description", "Edited.")
            page.wait_for_selector("#wc-dirty-badge:not([hidden])")
            assert "unsaved" not in page.locator("#wc-fold-meta").inner_text().lower()
            # Watching: Start is locked and says so; Stop is live.
            r = page.request.post(served_show + "api/console", data={"demo": True})
            assert r.ok, r.text()
            page.reload()
            page.wait_for_function("document.body.classList.contains('is-demo-show')")
            page.fill("#interval", "0.5")
            page.click("#start-btn")
            page.wait_for_function("document.getElementById('start-btn').disabled", timeout=30000)
            # (Start is disabled the moment it is pressed; the title follows
            # once the page hears the watch is running.)
            page.wait_for_function(
                "document.getElementById('start-btn').title === 'Locked: already watching'")
            assert page.get_attribute("#stop-btn", "title") is None
            page.click("#stop-btn")
            page.wait_for_function("!document.getElementById('start-btn').disabled")
            assert page.get_attribute("#stop-btn", "title") == "Locked: not watching"
        finally:
            browser.close()
