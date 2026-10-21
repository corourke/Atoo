"""The Watch page shows a strip that reaches one Main by two routes (R012), as an
ordinary WARNING row naming the routes, and drops it on the reading that no
longer has the split.

The Python suite cannot see the browser, and the row adds no wire field -- it rides
the findings the page already draws -- so what is pinned is that the real page, in
Chromium, draws R012 with its rule id and the strip and bus as the desk names them,
draws the Demo's own planned split as the INFO R013, and clears R012. The desk is the Demo's, with a fixed sequence of readings; the test
skips where Playwright or Chromium is missing.
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

#: Channel 1 reaches Main 1 directly and through bus 1 for these readings, and
#: not on the others.
READINGS_SPLIT = range(1, 7)


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
        if reading in READINGS_SPLIT:
            values["/ch/1/name"] = "Kick"
            values["/ch/1/main/1/on"] = 1
            values["/ch/1/send/1/on"], values["/ch/1/send/1/lvl"] = 1, 0.0
            values["/bus/1/main/1/on"] = 1
        else:
            values["/ch/1/main/1/on"] = 0
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_page_draws_the_split_and_drops_it(home, demo_copy, monkeypatch):
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
                # The Demo's own planned split (parallel vocals) is announced at
                # INFO and is not trouble; the strip the plan never mentions is
                # the WARNING.
                page.wait_for_selector("#alert-body tr:has-text('reaches MAIN 1 three times')",
                                       timeout=30000)
                row = page.locator("#alert-body tr", has_text="reaches MAIN 1 three times").first
                assert "WARNING" in row.inner_text().upper()
                assert "R012" in row.inner_text()
                assert 'CH 1 "Kick" reaches MAIN 1 three times: directly; through BUS 1' in row.inner_text()
                asked = page.locator("#alert-body tr", has_text="Signal split asked for").first
                assert "INFO" in asked.inner_text().upper()
                page.wait_for_function(
                    "!/reaches MAIN 1 three times/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
