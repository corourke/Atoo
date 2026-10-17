"""The Watch page shows a muted DCA over active members (CH004), and clears it
when the DCA is unmuted.

The Python suite cannot see the browser, and this row adds no wire field -- it
rides the finding the page already draws -- so what is pinned is that the real
page, in Chromium, draws it as an ordinary INFO row with its rule id and the DCA
as the desk names it, and drops it on the reading that no longer has it. The
desk is the Demo's with a sixth DCA the Demo's plan does not declare, and its
random faults replaced by a fixed sequence; the plan's own Band DCA is muted in
the same readings and is CV017's, so the page shows each mute once. It skips
where Playwright or Chromium is missing.
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

#: The readings in which the Stage DCA (not in the plan) and the plan's Band
#: DCA are muted.
READINGS_MUTED = range(1, 7)


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
        values.update({"/dca/6/name": "Stage", "/dca/6/mute": 0, "/dca/6/fdr": 0.0,
                       "/ch/13/tags": "#D4,#D6"})
        if reading in READINGS_MUTED:
            values["/dca/6/mute"] = 1
            values["/dca/2/mute"] = 1
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_demo_plan_declares_the_band_dca_and_not_the_stage_dca():
    from atoo.audit import DEFAULT_RULES, run_audit, with_plan_rules

    plan = Path(webui.DEMO_SHOW_DIR) / "plan.json"
    rules = with_plan_rules(DEFAULT_RULES, plan)
    base = {**webui._load_demo_base(), "/dca/6/name": "Stage", "/dca/6/mute": 1,
            "/dca/6/fdr": 0.0, "/ch/13/tags": "#D4,#D6", "/dca/2/mute": 1}
    found = {(f.rule_id, f.addresses) for f in run_audit(ConsoleState(base), rules)
             if f.rule_id in {"CH004", "CV017"}}
    assert found == {("CH004", ("/dca/6/mute",)), ("CV017", ("/dca/2/mute",))}


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
                page.wait_for_selector("#alert-body tr:has-text('CH004')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="CH004").first
                text = row.inner_text()
                assert "INFO" in text.upper()
                assert 'DCA 6 "Stage" is muted and is silencing' in text
                # The plan's Band DCA is muted too, and is CV017's alone.
                body = page.locator("#alert-body").inner_text()
                assert "CV017" in body and 'DCA 2 "Band"' in body
                assert page.locator("#alert-body tr", has_text="CH004").count() == 1
                page.wait_for_function(
                    "!/CH004/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
