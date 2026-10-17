"""The Watch page shows a feedback loop held closed (R010, a warning), then open
(R009, an error), and drops it when the send is taken away.

The Python suite cannot see the browser, and these rows add no wire field --
they ride the findings the page already draws -- so what is pinned is that the
real page, in Chromium, draws each as an ordinary row with its rule id and the
loop named hop by hop, replaces the warning with the error when the last leg
is opened, and drops the row on the reading that no longer has it. The desk is
the Demo's with an aux patched from a bus, and its random faults replaced by a
fixed sequence; it skips where Playwright or Chromium is missing.
"""

from __future__ import annotations

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
from atoo.audit import ConsoleState  # noqa: E402
from atoo.webui import create_app  # noqa: E402

#: The aux's send to the bus it takes: switched off for the first readings
#: (a loop held closed), on for the next (an open loop), gone after that.
READINGS_CLOSED = range(0, 6)
READINGS_OPEN = range(6, 22)


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
    copy = tmp_path / "package" / "starter"
    shutil.copytree(webui.DEMO_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(webui, "DEMO_ROOT", copy)
    monkeypatch.setattr(webui, "DEMO_SHOW_DIR", copy / webui.DEMO_SHOW_DIR.name)
    monkeypatch.setattr(webui, "DEMO_CONVENTIONS", copy / "conventions.md")
    monkeypatch.setattr(webui, "DEMO_PRESETS", copy / "presets")
    return copy


def _provider_factory():
    base = webui._load_demo_base()
    reading = 0

    def provider() -> ConsoleState:
        nonlocal reading
        values = dict(base)
        values.update({"/aux/6/name": "Return", "/aux/6/in/conn/grp": "BUS",
                       "/aux/6/in/conn/in": 13, "/aux/6/in/set/altsrc": 0,
                       "/aux/6/in/conn/altgrp": "OFF",
                       "/aux/6/send/7/on": 0, "/aux/6/send/7/lvl": 0.0})
        if reading in READINGS_CLOSED:
            values["/aux/6/send/7/on"] = 0
        elif reading in READINGS_OPEN:
            values["/aux/6/send/7/on"] = 1
        else:
            values["/aux/6/send/7/lvl"] = -144.0
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_demo_desk_with_the_aux_patched_from_a_bus_has_the_loop_in_each_state():
    from atoo.audit import DEFAULT_RULES, run_audit, with_plan_rules

    plan = Path(webui.DEMO_SHOW_DIR) / "plan.json"
    rules = with_plan_rules(DEFAULT_RULES, plan)
    built = run_audit(ConsoleState(webui._load_demo_base()), rules)
    assert not {f.rule_id for f in built} & {"R009", "R010"}     # the Demo as built has no loop
    ids = []
    provider, _ = _provider_factory()
    for _ in range(24):
        state = provider()
        ids.append(sorted(f.rule_id for f in run_audit(state, rules)
                          if f.rule_id in {"R009", "R010"}))
    assert ids == [["R010"]] * 6 + [["R009"]] * 16 + [[]] * 2


def test_the_page_draws_the_row_and_drops_it(home, demo_copy, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    monkeypatch.setattr(webui, "demo_provider_factory", _provider_factory)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                                     " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
                page.goto(url + "#watch")
                page.wait_for_selector("#mode-watch:not([hidden])")
                assert page.request.post(url + "api/console", data={"demo": True}).ok
                page.reload()
                page.wait_for_function("document.body.classList.contains('is-demo-show')")
                page.fill("#interval", "0.5")
                page.click("#start-btn")
                page.wait_for_selector("#alert-body tr:has-text('R010')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="R010").first
                assert "WARNING" in row.inner_text().upper()
                assert 'AUX 6 "Return" takes BUS 7' in row.inner_text()
                assert "(switched off)" in row.inner_text()
                page.wait_for_selector("#alert-body tr:has-text('R009')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="R009").first
                assert "ERROR" in row.inner_text().upper()
                assert "AUX 6 sends to BUS 7" in row.inner_text()
                # The warning leaves the table when the error replaces it.
                page.wait_for_function(
                    "!/R010/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                assert "R009" in page.locator("#alert-body").inner_text()
                page.wait_for_function(
                    "!/R009|R010/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
