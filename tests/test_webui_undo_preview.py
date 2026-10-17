"""What Preview undo shows -- server, and the page in Chromium.

An undo preview reads the desk and says, address by address, what Undo
would put back and what it would leave alone because it has changed since.
The server sends that as `result.undo` on the one runner's status. The newest
standing History row asks for it (Preview undo, in its last cell), the page
draws it in step 2's Preview box -- the one box for both previews -- and step 3
becomes Arm and undo, with Write gone until the write is previewed again.

The simulated desk and the model are `test_webui_amend`'s (strips 1-19 ours,
20 "Podium", 21-32 free): a change is written to it, and then undone, or
previewed. **No test here touches a real console, a real model, or a bundle
under `examples/`.** The browser half skips where Playwright or Chromium is
missing.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import journal_stack  # noqa: E402
from webui_page import armed  # noqa: E402
from test_amend import horn  # noqa: E402
from test_webui_amend import (TEXT, _Desk, _app, _bundle, _preview, _wait, _write,  # noqa: E402,F401
                              _writes, client, desk, horns, model)

UNDO = "/api/undo/run"


def _written(c) -> None:
    """Preview and write the horn change, so there is something to undo."""
    _preview(c)
    assert _write(c).status_code == 200
    assert _wait(c)["exit_code"] == 0


def _undo_preview(c) -> dict:
    r = c.post(UNDO, json={})
    assert r.status_code == 200, r.json()
    status = _wait(c)
    assert status["kind"] == "undo" and status["preview"] is True
    return status


def _journal_rows(c) -> int:
    [top] = journal_stack.entries(c.bundle_directory)
    journal = json.loads(top.path.read_text())
    return len([w for w in journal["writes"] if w["status"] == "match"])


# ======================================================================
# The payload
# ======================================================================


def test_a_preview_names_the_row_it_reverses_and_lists_every_address_it_would_put_back(
        client, desk):
    _written(client)
    written = len(_writes(desk))
    status = _undo_preview(client)
    assert status["state"] == "done" and status["exit_code"] == 0, status["log"]
    assert "--confirm" not in status["command"] and "--result-json" in status["command"]
    assert len(_writes(desk)) == written, "a preview writes nothing"

    undo = status["result"]["undo"]
    [top] = journal_stack.entries(client.bundle_directory)
    assert undo["dry_run"] is True and undo["outcome"] == "safe"
    assert undo["journal_id"] == top.id and undo["kind"] == "patch"
    assert undo["change_label"] == "change 1: Horns for tonight"
    assert undo["timestamp"]
    rows = undo["rows"]
    assert len(rows) == _journal_rows(client) and rows
    assert undo["counts"]["goes-back"] == len(rows) and undo["counts"]["total"] == len(rows)
    assert {r["verdict"] for r in rows} == {"goes-back"}
    name = next(r for r in rows if r["address"] == "/ch/21/name")
    assert name["strip"] == "ch:21" and name["strip_name"] == "Trumpet"
    # What the change wrote, what the desk holds now, what an undo restores.
    assert (name["written"], name["now"], name["goes_back_to"]) == ("Trumpet", "Trumpet", "CH21")
    # A socket row is labelled by the socket, whichever strip it was written for.
    assert any(r["strip"] == "A 21" for r in rows)
    # The journal does not record a control's name or unit apart from the
    # words of the write's own description, which is what `control` carries.
    assert all(r["control"] for r in rows)


def test_a_value_moved_since_the_write_is_said_before_undo_is_pressed(client, desk):
    _written(client)
    desk.next_state["/ch/21/name"] = ("Kick", "s")
    written = len(_writes(desk))
    undo = _undo_preview(client)["result"]["undo"]
    assert undo["outcome"] == "differs"
    held = [r for r in undo["rows"] if r["verdict"] == "changed-since"]
    assert [(r["address"], r["written"], r["now"], r["goes_back_to"]) for r in held] == [
        ("/ch/21/name", "Trumpet", "Kick", "CH21")]
    assert undo["counts"]["changed-since"] == 1
    assert undo["counts"]["goes-back"] == len(undo["rows"]) - 1
    assert len(_writes(desk)) == written
    assert desk.next_state["/ch/21/name"] == ("Kick", "s")


def test_an_address_already_back_is_counted_apart(client, desk):
    _written(client)
    desk.next_state["/ch/21/name"] = ("CH21", "s")
    undo = _undo_preview(client)["result"]["undo"]
    assert undo["outcome"] == "safe"
    assert undo["counts"]["already-back"] == 1


def test_a_confirmed_undo_that_leaves_something_is_a_warning_not_a_clean_finish(client, desk):
    _written(client)
    desk.next_state["/ch/21/name"] = ("Kick", "s")
    r = client.post(UNDO, json=armed(client, UNDO))
    assert r.status_code == 200, r.json()
    status = _wait(client)
    assert status["kind"] == "undo" and status["preview"] is False
    assert status["exit_code"] == 2
    undo = status["result"]["undo"]
    assert undo["outcome"] == "partly-undone" and undo["dry_run"] is False
    assert undo["counts"]["changed-since"] == 1 and undo["counts"]["went-back"] > 0
    assert [(f["code"], f["severity"]) for f in status["findings"]] == [
        ("undo.partial", "warning")]
    assert desk.next_state["/ch/21/name"] == ("Kick", "s"), "their value is left alone"


def test_a_clean_undo_says_undone_and_raises_no_finding(client, desk):
    _written(client)
    assert client.post(UNDO, json=armed(client, UNDO)).status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0 and status["findings"] == []
    assert status["result"]["undo"]["outcome"] == "undone"
    assert {r["verdict"] for r in status["result"]["undo"]["rows"]} == {"went-back"}


def test_a_refusal_before_the_desk_is_asked_has_no_payload_and_says_why(tmp_path, desk, model):
    """An empty stack: the command refuses, writes no result file, and the
    status carries its words in the log rather than a half-made payload."""
    import test_webui_amend as base

    with fastapi_testclient.TestClient(base._app(_bundle(tmp_path))) as c:
        r = c.post(UNDO, json={})
        assert r.status_code == 200
        status = _wait(c)
        assert status["result"] is None
        assert any("nothing to undo" in line for line in status["log"])


# ======================================================================
# The preview leaves the rest of the screen alone
# ======================================================================


def test_a_preview_of_an_undo_does_not_disarm_a_write_previewed_before_it(client, desk, model):
    """The runner is shared, and its status shows the last run. A patch
    previewed, an undo previewed, and the patch written: the server still
    holds the patch's review (only a confirmed run spends it), and the page
    keeps the review id it drew."""
    _written(client)
    second = horns()
    second["name"] = "More horns"
    second["add"]["channels"] = [horn(23, "Flugel", 24)]
    model.response = json.dumps(second)
    previewed = _preview(client, "a flugelhorn on A 24")
    review_id = previewed["review"]["review_id"]
    _undo_preview(client)
    r = client.post("/api/patch/run", json=armed(
        client, "/api/patch/run", change="a flugelhorn on A 24", expected_review_id=review_id))
    assert r.status_code == 200, r.json()
    assert _wait(client)["exit_code"] == 0


# ======================================================================
# The served page
# ======================================================================


@pytest.fixture
def assets():
    with fastapi_testclient.TestClient(_app_without_bundle()) as c:
        yield c


def _app_without_bundle():
    from atoo.webui import create_app

    return create_app()


def test_the_undo_preview_is_in_step_two_and_undo_is_in_step_three(assets):
    html = assets.get("/static/shell.html").text
    step2 = html[html.index('id="apply-step-2-box"'):html.index('id="apply-step-3"')]
    step3 = html[html.index('id="apply-step-3-box"'):html.index('id="journal-stack-panel"')]
    history = html[html.index('id="journal-stack-panel"'):html.index('id="mode-watch"')]
    for element in ("undo-result", "undo-result-state", "undo-result-which", "undo-result-facts",
                    "undo-result-stays", "undo-result-info", "undo-result-back", "undo-result-line",
                    "undo-result-log"):
        assert f'id="{element}"' in step2, element
    assert 'id="undo-result" role="region" aria-label="Undo preview"' in step2
    assert 'aria-live="polite" tabindex="-1"' in step2
    # Step 3: Arm, then Write or Undo; the red Undo is directly under its header.
    assert step3.index("<h3>Arm</h3>") < step3.index("<h3>Write</h3>") < step3.index("<h3>Undo</h3>")
    assert step3.index("<h3>Undo</h3>") < step3.index('id="undo-run-btn"') < step3.index('id="undo-sum"')
    assert 'id="apply-undo-section" hidden' in step3
    # History holds no undo buttons, no panel and no log of its own.
    for gone in ("undo-preview-btn", "undo-run-btn", "undo-result", "undo-explain",
                 "apply-log-slot-4", "undo-locked"):
        assert f'id="{gone}"' not in history, gone
    assert 'id="undo-preview-btn"' not in html
    # The button is drawn with the row, before Keep this in the show.
    amend = assets.get("/static/amend.js").text
    row = amend[amend.index("if (entry.is_top) undoPreviewControls(stack_);"):]
    assert row.index("undoPreviewControls(stack_)") < row.index('"btn btn-secondary btn-sm promote-btn"')
    assert 'btn.id = "undo-preview-btn";' in amend
    assert '"btn btn-primary btn-sm"' in amend and '"Preview undo again"' in amend
    # No Next undo or Undo reverses this badge, and no note on another desk's row.
    assert "Next undo" not in amend and "Undo reverses this" not in amend
    assert 'text("span", "prop", "Other desk")' in amend and "journal-flag-note" not in amend


def test_the_page_reads_what_the_server_sends_for_an_undo(assets):
    js = assets.get("/static/apply.js").text
    for key in ("result.undo", "payload.rows", "payload.counts", "payload.journal_id",
                "payload.change_label", "payload.kind", "row.strip", "row.strip_name",
                "row.written", "row.now", "row.goes_back_to", "row.verdict", "row.control",
                "changed-since", "no-earlier-value", "already-back", "goes-back", "went-back"):
        assert key in js, key
    # A preview of an undo replaces neither step's account of the write; a
    # write that was sent -- or a fresh write preview -- ends the undo preview.
    take = js[js.index("function take(status) {"):js.index("function isDemo()")]
    assert "if (status.preview) {\n        undoView = status;\n        lastPreview = \"undo\";" in take
    assert "run = status;\n      undoView = null;\n      lastPreview = \"write\";" in take
    # One Preview box, one verdict vocabulary, scrolled to and focused.
    for words in ('"Ready to undo"', '" will stay"', '"Can\'t undo"',
                  "block: \"start\"", "prefers-reduced-motion", "panel.focus({ preventScroll: true })",
                  '"Arm and undo"', '"Arm and write"'):
        assert words in js or words.replace("\\'", "'") in js, words
    css = assets.get("/static/styles.css").text
    for cls in (".undo-preview", ".undo-preview.is-warn", ".undo-row", ".act-stack", ".shown-in"):
        assert cls in css, cls
    assert ".undo-result {" not in css and ".undo-rows-held" not in css
    # At phone width a History row is a stack of labelled lines, not a scrolled table.
    assert "td[data-l]" in css and "@container (max-width: 760px)" in css
    assert ".journal-stack-table { display: block; overflow-x: auto; }" not in css


# ======================================================================
# The page in Chromium
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
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{port}/"


def _visible_actions(page) -> list[str]:
    """Which of the two red buttons is on the page. Exactly one at every step."""
    return [i for i in ("apply-run-btn", "undo-run-btn") if page.locator(f"#{i}").is_visible()]


def test_preview_undo_is_on_the_row_its_preview_is_in_step_two_and_undo_is_in_step_three(
        tmp_path, desk, model, monkeypatch):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # The page offers Preview only when a model is set up; the stand-in
    # answers, and this makes the page believe there is one.
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
                # Nothing written yet: the empty History line holds a locked
                # Preview undo with its reason in words.
                empty = page.locator("#journal-stack-empty")
                assert empty.is_visible()
                assert empty.locator("#undo-preview-btn").is_disabled()
                assert "nothing has been written" in empty.locator(".act-note").inner_text()

                page.click("#apply-mode-amend")
                page.fill("#patch-change-text", TEXT)
                page.click("#apply-preview-btn")
                page.wait_for_selector("#amend-review:not([hidden])", timeout=60000)
                assert page.locator("#apply-step-3-title").inner_text() == "Arm and write"
                assert _visible_actions(page) == ["apply-run-btn"]
                page.check("#apply-arm-checkbox")
                page.click("#apply-run-btn")
                page.wait_for_function(
                    "document.querySelector('#journal-stack-rows').children.length > 0",
                    timeout=60000)
                written = page.locator("#apply-write-line").inner_text()
                assert "written" in written
                assert _visible_actions(page) == ["apply-run-btn"]

                # The newest row: Preview undo (brass), then Keep this in the
                # show; no Next undo or Undo reverses this anywhere.
                cell = page.locator("#journal-stack-rows tr").first.locator("td.journal-act-cell")
                button = cell.locator("#undo-preview-btn")
                assert button.text_content() == "Preview undo"
                assert "btn-primary" in button.get_attribute("class")
                kinds = cell.locator(".act-stack > *").evaluate_all("els => els.map(e => e.id || e.className)")
                assert kinds.index("undo-preview-btn") < next(
                    i for i, k in enumerate(kinds) if "promote-btn" in k)
                history = page.locator("#journal-stack-panel").inner_text()
                assert "Next undo" not in history and "Undo reverses this" not in history
                assert page.locator("#journal-stack-panel .btn-primary:visible").count() == 1

                # Preview undo: step 2's box shows it, in view and focused;
                # step 3 is Arm and undo, Write is gone.
                desk.next_state["/ch/21/name"] = ("Kick", "s")
                button.click()
                page.wait_for_function(
                    "document.querySelector('#undo-result-state').textContent"
                    " && !/Reading/i.test(document.querySelector('#undo-result-state').textContent)",
                    timeout=30000)
                assert page.locator("#apply-step-2-box #undo-result").is_visible()
                assert page.locator("#apply-step-3-box #undo-result").count() == 0
                assert page.evaluate("document.activeElement.id") == "undo-result"
                top = page.locator("#undo-result").bounding_box()["y"]
                assert 0 <= top < 900
                assert page.locator("#apply-step-3-title").inner_text() == "Arm and undo"
                assert page.locator("#apply-step-2-state").inner_text().lower().startswith("undo preview")
                assert _visible_actions(page) == ["undo-run-btn"]
                assert page.locator("#apply-run-btn").is_hidden()
                # The verdict is words, in the warning colour; what stays is
                # named with the value the desk holds now, above the red button.
                tag = page.locator("#undo-result-state")
                assert tag.inner_text().lower() == "1 will stay"
                assert "sev-warning" in tag.get_attribute("class")
                stays = page.locator("#undo-result-stays")
                assert "ch:21" in stays.inner_text() and '"Kick"' in stays.inner_text()
                assert stays.bounding_box()["y"] < page.locator("#undo-run-btn").bounding_box()["y"]
                assert "1 stay" in page.locator("#undo-sum-line").inner_text()
                # The red Undo is the first control after its header, locked
                # until Arm is ticked; the write's account is not in step 3.
                first = page.evaluate(
                    "document.querySelector('#apply-undo-section .section-head')"
                    ".nextElementSibling.querySelector('button').id")
                assert first == "undo-run-btn"
                assert page.locator("#undo-run-btn").is_disabled()
                assert "tick Arm" in page.locator("#undo-locked").inner_text()
                # History: the button is outline now, and points at step 2.
                again = page.locator("#undo-preview-btn")
                assert again.text_content() == "Preview undo again"
                assert "btn-primary" not in again.get_attribute("class")
                assert "step 2" in page.locator("[data-shown-in]").inner_text()

                # The flip: Preview write brings the write's box back, clears
                # the tick, and the History button is brass again.
                page.check("#apply-arm-checkbox")
                assert page.locator("#undo-run-btn").is_enabled()
                page.click("#apply-preview-btn")
                page.wait_for_selector("#undo-result", state="hidden")
                assert page.locator("#apply-step-3-title").inner_text() == "Arm and write"
                assert _visible_actions(page) == ["apply-run-btn"]
                assert not page.locator("#apply-arm-checkbox").is_checked()
                page.wait_for_function(
                    "document.querySelector('#undo-preview-btn').textContent === 'Preview undo'")
                assert "btn-primary" in page.locator("#undo-preview-btn").get_attribute("class")

                # Preview undo again, arm, Undo: the moved value is left where
                # it is, the result is under the locked Undo button in step 3
                # (yellow, Partly), and step 2 is the write's again.
                page.click("#undo-preview-btn")
                page.wait_for_function(
                    "/will stay/i.test(document.querySelector('#undo-result-state').textContent)",
                    timeout=30000)
                page.check("#apply-arm-checkbox")
                page.click("#undo-run-btn")
                page.wait_for_function(
                    "!document.querySelector('#undo-banner').hidden"
                    " && /put back/.test(document.querySelector('#undo-banner-head').textContent)",
                    timeout=30000)
                banner = page.locator("#undo-banner")
                assert "is-warn" in banner.get_attribute("class")
                assert "left as it is" in banner.inner_text()
                assert page.locator("#undo-result").is_hidden()
                assert page.locator("#undo-run-btn").is_disabled()
                assert not page.locator("#apply-arm-checkbox").is_checked()
                assert banner.bounding_box()["y"] > page.locator("#undo-run-btn").bounding_box()["y"]
                assert page.locator("#apply-run-panel").is_hidden()
                assert desk.next_state["/ch/21/name"] == ("Kick", "s")
                assert _visible_actions(page) == ["undo-run-btn"]

                # At phone width the History row is a stack of labelled lines and
                # the button is on screen without scrolling sideways.
                page.set_viewport_size({"width": 390, "height": 900})
                box = page.locator("#apply-step-4-box")
                assert box.evaluate("e => e.scrollWidth <= e.clientWidth")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                row = page.locator("#journal-stack-rows tr").nth(1)
                assert row.locator("td").first.evaluate("e => getComputedStyle(e).display") == "block"
                assert "When" in row.locator("td").first.evaluate(
                    "e => getComputedStyle(e, '::before').content")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_only_the_newest_standing_row_has_a_button_and_another_desks_row_has_only_a_badge(
        tmp_path, monkeypatch):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def row(n, **extra):
        return {"id": f"j{n}", "path": f"/x/j{n}.json", "timestamp": f"2026-10-15T18:0{n}:00+00:00",
                "kind": "apply", "summary": f"APPLIED {n}", "mismatches": 0, "aborted": False,
                "desk": {"name": "Desk", "serial": "S1", "address": "192.0.2.1"},
                "on_this_desk": True, "is_top": False, "undone_by": None, "change": None, **extra}

    stack = {"bundle": "show", "desk_label": "Desk #S1", "desk": {"serial": "S1"},
             "entries": [row(4, is_top=True), row(3), row(2, on_this_desk=False),
                         row(1, undone_by="j9")]}
    server, thread, url = _serve(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1'); } catch (e) {}")
                page.route("**/api/journals", lambda route: route.fulfill(json=stack))
                page.goto(url + "#apply")
                page.wait_for_selector("#journal-stack-rows tr")
                cells = page.locator("#journal-stack-rows td.journal-act-cell")
                assert cells.count() == 4
                assert cells.nth(0).locator("#undo-preview-btn").count() == 1
                texts = [cells.nth(i).inner_text().strip().lower() for i in range(4)]
                assert texts[0] == "preview undo"
                assert texts[1] == ""                       # older, standing: nothing
                assert texts[2] == "other desk"             # a badge, no note, no button
                assert texts[3] == "undone"
                assert page.locator("#undo-preview-btn").count() == 1
                assert page.locator("#journal-stack-rows .act-note").count() == 0
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_the_demo_has_a_locked_preview_undo_on_its_empty_line(tmp_path, monkeypatch):
    chromium = _chromium()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    server, thread, url = _serve(_app(_bundle(tmp_path)))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1'); } catch (e) {}")
                page.goto(url + "#apply")
                assert page.request.post(url + "api/console", data={"demo": True}).ok
                page.reload()
                page.wait_for_function("document.body.classList.contains('is-demo-show')")
                empty = page.locator("#journal-stack-empty")
                empty.wait_for(state="visible")
                assert empty.locator("#undo-preview-btn").is_disabled()
                assert "the Demo show is read-only" in empty.locator(".act-note").inner_text()
                assert page.locator("#apply-step-3-title").inner_text() == "Arm and write"
                assert page.locator("#apply-run-btn").is_disabled()
                assert page.locator("#undo-run-btn").is_hidden()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
