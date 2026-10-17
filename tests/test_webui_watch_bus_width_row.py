"""The Watch page shows the plan's bus width row (CV020) and a stereo bus heard
on one side (R011), and clears the width row when the bus is put back.

The Python suite cannot see the browser, and these rows add no wire field -- they
ride the findings the page already draws -- so what is pinned is that the real
page, in Chromium, draws CV020 as an ordinary WARNING row with its rule id and
the bus as the desk names it, draws R011 as a WARNING row for a bus the plan does not declare,
says nothing for the wedge the plan does declare, and drops CV020 on the reading
that no longer has it. The desk is the Demo's, with its random faults replaced by
a fixed sequence; it skips where Playwright or Chromium is missing.
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

#: The Vox Wedge, which the plan makes mono, reads stereo for a few readings,
#: and the Vocals bus (stereo, in use, not declared on any output socket by
#: the plan) is patched on its left slot only from the second reading on.
READINGS_STEREO = range(1, 7)


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
        if reading in READINGS_STEREO:
            values["/bus/1/busmono"] = 0
            values["/io/out/LCL/3/grp"], values["/io/out/LCL/3/in"] = "BUS", 11
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_demo_desk_as_planned_has_the_widths_the_plan_states():
    from atoo.audit import DEFAULT_RULES, run_audit, with_plan_rules

    plan = Path(webui.DEMO_SHOW_DIR) / "plan.json"
    rules = with_plan_rules(DEFAULT_RULES, plan)
    assert {"CV020", "R011"}.isdisjoint(
        f.rule_id for f in run_audit(ConsoleState(webui._load_demo_base()), rules))
    flipped = ConsoleState({**webui._load_demo_base(), "/bus/1/busmono": 0})
    ids = {f.rule_id for f in run_audit(flipped, rules)}
    assert "CV020" in ids and "R011" not in ids  # the plan declares the wedge's socket


def test_the_page_draws_the_rows_and_drops_the_width_row(home, demo_copy, monkeypatch):
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
                page.wait_for_selector("#alert-body tr:has-text('CV020')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="CV020").first
                assert "WARNING" in row.inner_text().upper()
                assert 'BUS 1 "Vox Wedge": the plan has this bus mono' in row.inner_text()
                # The Vocals bus is a stereo bus on one side, and the plan
                # does not declare the socket; the wedge it does declare is quiet.
                page.wait_for_selector("#alert-body tr:has-text('R011')", timeout=30000)
                r011 = page.locator("#alert-body tr", has_text="R011").first
                assert "WARNING" in r011.inner_text().upper()
                assert 'BUS 6 "Vocals" is stereo but is patched on its left side' in r011.inner_text()
                body = page.locator("body").inner_text()
                assert 'BUS 1 "Vox Wedge" is stereo' not in body
                page.wait_for_function(
                    "!/CV020/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
