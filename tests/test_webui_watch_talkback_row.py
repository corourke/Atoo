"""The Watch page shows the plan's monitor-mix talkback row (CV021) and its
INFO note (CV022), and clears the warning when talkback is put back.

The Python suite cannot see the browser, and these rows add no wire field -- they
ride the findings the page already draws -- so what is pinned is that the real
page, in Chromium, draws CV021 as an ordinary WARNING row naming the bus as the
desk shows it, draws CV022 as an info row, and drops CV021 on the reading that
no longer has it. The desk is the Demo's, with talkback assigned and a fixed
sequence of destination switches; it skips where Playwright or Chromium is
missing.
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

from atoo import console_facts, webui  # noqa: E402
from atoo.audit import ConsoleState  # noqa: E402
from atoo.webui import create_app  # noqa: E402

#: Talkback reaches the Demo's four monitor mixes, then misses bus 4 (the Drum
#: IEM) for a few readings, then reaches it again.
READINGS_MISSING = range(1, 7)


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
        values["/cfg/talk/assign"] = "CH40"
        for button in console_facts.TALK_BUTTONS:
            for dest in console_facts.TALK_DESTINATIONS:
                values[console_facts.talk_destination(button, dest)] = 0
        for n in (1, 2, 3, 4):
            values[console_facts.talk_destination("A", f"B{n}")] = 1
        if reading in READINGS_MISSING:
            values[console_facts.talk_destination("A", "B4")] = 0
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_demo_plan_builds_four_monitor_mixes_and_a_desk_routed_to_them_is_quiet():
    from atoo.audit import DEFAULT_RULES, run_audit, with_plan_rules

    plan = Path(webui.DEMO_SHOW_DIR) / "plan.json"
    rules = with_plan_rules(DEFAULT_RULES, plan)
    values = webui._load_demo_base()
    values["/cfg/talk/assign"] = "CH40"
    for button in console_facts.TALK_BUTTONS:
        for dest in console_facts.TALK_DESTINATIONS:
            values[console_facts.talk_destination(button, dest)] = 0
    for n in (1, 2, 3, 4):
        values[console_facts.talk_destination("A", f"B{n}")] = 1
    ids = {f.rule_id for f in run_audit(ConsoleState(values), rules)}
    assert "CV021" not in ids and "CV022" in ids
    values[console_facts.talk_destination("A", "B2")] = 0
    ids = {f.rule_id for f in run_audit(ConsoleState(values), rules)}
    assert "CV021" in ids


def test_the_demo_as_it_stands_says_nothing_about_talkback():
    """The Demo's desk has no talkback set up: neither rule speaks."""
    from atoo.audit import DEFAULT_RULES, run_audit, with_plan_rules

    rules = with_plan_rules(DEFAULT_RULES, Path(webui.DEMO_SHOW_DIR) / "plan.json")
    ids = {f.rule_id for f in run_audit(ConsoleState(webui._load_demo_base()), rules)}
    assert not ids & {"CV021", "CV022", "T001"}


def test_the_page_draws_the_rows_and_drops_the_warning(home, demo_copy, monkeypatch):
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
                page.wait_for_selector("#alert-body tr:has-text('CV021')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="CV021").first
                assert "WARNING" in row.inner_text().upper()
                assert 'not BUS 4 "Drum IEM"' in row.inner_text()
                # The other three mixes are reached: one warning, and the note
                # that says which busses were taken.
                assert page.locator("#alert-body tr", has_text="CV021").count() == 1
                body = page.locator("body").inner_text()
                assert "CV022" in body and "Talkback reaches 3 of the 4 monitor mixes" in body
                page.wait_for_function(
                    "!/CV021/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
