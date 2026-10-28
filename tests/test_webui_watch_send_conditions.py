"""The Watch conditions editor offers the send and phantom fields, and the Bus
box that goes with the send ones.

The Python suite cannot see the browser: `watch.js` keeps its own copy of the
field list (`WC_FIELDS`), so a field added to `watch_conditions` and not there
is an editor that cannot author it, silently. What is pinned here is the served
asset (the lists match Python's) and the real page, in Chromium and in the dark
theme: choosing a send field shows the Bus box under the Field select and a
phantom field hides it, a bus written loosely is rewritten once the cell is
left, a bus the loader would refuse is outlined with the loader's reason, and
Save writes the `bus` key. They skip where Playwright or Chromium is missing.
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

from atoo import watch_conditions as wc  # noqa: E402
from atoo.webui import create_app  # noqa: E402

WATCH_JSON = {
    "version": 2, "watch_conditions": [
        {"id": "kick-unmuted", "description": "The kick drives the room.",
         "channel": "Kick", "field": "muted", "operator": "!=", "value": False,
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
def show(home):
    show = home / "shows" / "club"
    show.mkdir(parents=True)
    (show / "input.csv").write_text(
        "order,patch,name,category,type,model,phantom,notes\n1,LCL 1,Kick,drums,Mic,Beta 91A,TRUE,\n")
    (show / "watch.json").write_text(json.dumps(WATCH_JSON))
    return show


@pytest.fixture
def served_show(show):
    uvicorn = pytest.importorskip("uvicorn")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        create_app(initial_bundle=str(show), initial_watch_conditions_path=str(show / "watch.json")),
        host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=5)


def _js_array(js: str, name: str) -> list:
    import re
    m = re.search(r"const " + re.escape(name) + r" = (\[[^\]]*\])", js)
    assert m, f"watch.js has no array literal for {name}"
    return json.loads(m.group(1).replace("\n", " "))


def test_the_served_editor_offers_the_fields_python_has():
    with fastapi_testclient.TestClient(create_app()) as client:
        js = client.get("/static/watch.js").text
    assert set(_js_array(js, "WC_FIELDS")) == wc._ALLOWED_FIELDS
    assert set(_js_array(js, "WC_SEND_FIELDS")) == wc._SEND_FIELDS
    assert set(_js_array(js, "WC_BOOL_FIELDS")) == wc._BOOLEAN_FIELDS
    assert _js_array(js, "WC_SEND_MODES") == list(wc._SEND_MODES)
    # The Bus box is drawn for the send fields only, and the key is dropped
    # when the field changes to one that has none.
    assert 'if (WC_SEND_FIELDS.includes(cond.field)) {\n      const busInput' in js
    assert "delete cond.bus;" in js
    # The cell is checked by the server like Channel, Field and Value.
    assert 'for (const cell of ["channel", "field", "bus", "value"])' in js


def test_the_page_authors_a_send_condition_and_saves_its_bus(served_show, show):
    sync_api = pytest.importorskip("playwright.sync_api")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                 " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
            page.goto(served_show + "#watch")
            page.wait_for_selector("#mode-watch:not([hidden])")
            page.wait_for_selector("#wc-body tr")
            page.click("#wc-add-btn")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-field option").all_inner_texts() == [
                "muted", "fader_db", "dca", "mute_group", "patch",
                "send_on", "send_db", "send_mode", "phantom"]
            assert row.locator(".wc-bus").count() == 0

            # A send field: the Bus box appears under the select, and the
            # value is a checkbox with the equality operators only.
            row.locator(".wc-field").select_option("send_on")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-bus").count() == 1
            assert row.locator(".wc-value-checkbox").count() == 1
            assert row.locator(".wc-operator option").all_inner_texts() == ["==", "!="]
            row.locator(".wc-id").fill("click-off-in-iem")
            row.locator(".wc-description").fill("The click is off in an IEM")
            row.locator(".wc-channel").fill("Click")
            # It alerts when the send is off.
            row.locator(".wc-value-checkbox").uncheck()

            # A bus the loader would refuse is outlined, with its reason.
            row.locator(".wc-bus").fill("BUS 17")
            row.locator(".wc-bus").blur()
            # The empty cell is already invalid ("needs a 'bus' key"), so wait
            # for this value's own reason, not for the outline.
            page.wait_for_function(
                "(document.querySelector('#wc-body tr:nth-child(2) .wc-bus + .wc-cell-error')"
                " || {}).innerText?.includes('BUS 17 does not exist')")
            assert row.locator(".wc-bus").get_attribute("class").split().count("is-invalid") == 1
            # ... and a loose spelling of a good one is written back once left.
            row.locator(".wc-bus").fill("bus5-8")
            row.locator(".wc-bus").blur()
            page.wait_for_function(
                "document.querySelector('#wc-body tr:nth-child(2) .wc-bus').value === 'BUS 5-8'")
            if os.environ.get("ATOO_SHOT"):
                page.screenshot(path=os.environ["ATOO_SHOT"])

            # The other send fields: a level, and a mode with three words.
            row.locator(".wc-field").select_option("send_db")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-value-number").count() == 1
            assert row.locator(".wc-operator option").all_inner_texts() == [
                "==", "!=", ">", "<", ">=", "<="]
            assert row.locator(".wc-bus").input_value() == "BUS 5-8"
            row.locator(".wc-field").select_option("send_mode")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-value-select option").all_inner_texts() == ["pre", "post", "group"]
            # Membership in words: not in / in, and patch == / !=.
            row.locator(".wc-field").select_option("dca")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-operator option").all_inner_texts() == ["not in", "in"]
            assert row.locator(".wc-operator").input_value() == "not in"
            row.locator(".wc-field").select_option("patch")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-operator option").all_inner_texts() == ["==", "!="]
            assert page.locator("#wc-table thead th").nth(3).inner_text().lower() == "alert when"
            row.locator(".wc-field").select_option("send_on")

            # 48V has no bus: the box goes, and so does the key.
            row.locator(".wc-field").select_option("phantom")
            row = page.locator("#wc-body tr").nth(1)
            assert row.locator(".wc-bus").count() == 0
            assert row.locator(".wc-value-checkbox").count() == 1
            row.locator(".wc-field").select_option("send_on")
            row = page.locator("#wc-body tr").nth(1)
            row.locator(".wc-bus").fill("BUS 5-8")
            row.locator(".wc-bus").blur()
            page.wait_for_function(
                "!document.querySelector('#wc-body tr:nth-child(2) .wc-bus.is-invalid')")
            row.locator(".wc-value-checkbox").uncheck()

            page.wait_for_selector("#wc-save-btn:not([disabled])")
            page.click("#wc-save-btn")
            page.wait_for_selector("#wc-save-btn", state="hidden")
        finally:
            browser.close()
    saved = json.loads((show / "watch.json").read_text())["watch_conditions"]
    assert saved[1] == {"id": "click-off-in-iem", "description": "The click is off in an IEM",
                        "channel": "Click", "field": "send_on", "operator": "==", "value": False,
                        "severity": "warning", "bus": "BUS 5-8"}
    wc.load_watch_conditions(show / "watch.json")
