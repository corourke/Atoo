"""The Watch page shows the plan's phantom row (CV019), and clears it when the
48V is switched back on.

The Python suite cannot see the browser, and this row adds no wire field -- it
rides the finding the page already draws -- so what is pinned is that the real
page, in Chromium, draws it as an ordinary WARNING row with its rule id and the
strip as the desk names it, and drops it on the reading that no longer has it.
The desk is the Demo's, with its random faults replaced by a fixed sequence; it
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

#: Kick's condenser, on AES50-A 1, loses its 48V for a few readings.
READINGS_WITHOUT_48V = range(1, 7)


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
        if reading in READINGS_WITHOUT_48V:
            values["/io/in/A/1/vph"] = 0
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_demo_desk_as_planned_has_48v_where_the_plan_does():
    from atoo.audit import DEFAULT_RULES, run_audit, with_plan_rules

    plan = Path(webui.DEMO_SHOW_DIR) / "plan.json"
    rules = with_plan_rules(DEFAULT_RULES, plan)
    assert "CV019" not in {f.rule_id for f in run_audit(ConsoleState(webui._load_demo_base()), rules)}
    off = ConsoleState({**webui._load_demo_base(), "/io/in/A/1/vph": 0})
    assert "CV019" in {f.rule_id for f in run_audit(off, rules)}


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
                page.wait_for_selector("#alert-body tr:has-text('CV019')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="CV019").first
                assert "WARNING" in row.inner_text().upper()
                assert 'CH 1 "Kick": the plan has 48V on at AES50-A 1' in row.inner_text()
                # No C001 for it: the socket is patched.
                assert "C001" not in page.locator("#alert-body").inner_text()
                page.wait_for_function(
                    "!/CV019/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
