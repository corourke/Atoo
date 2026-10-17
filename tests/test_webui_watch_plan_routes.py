"""The Watch page shows the plan's send and route rows (CV006, CV007, CV018),
and clears them when the desk is put back.

The Python suite cannot see the browser, and these rows add no wire field --
they ride the findings the page already draws -- so what is pinned is that the
real page, in Chromium, draws each as an ordinary row with its rule id and the
strip as the desk names it, and drops it again on the reading that no longer
has it. The desk is the Demo's, with its random faults replaced by a fixed
sequence; it skips where Playwright or Chromium is missing.
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

#: What the Demo show's plan has, and the desk then shows: Kick sends to
#: Drum IEM (bus 4) and Drums (bus 5); Snare's Drum IEM send is pre; no strip
#: is routed straight to Main but the ones it lists.
SET_UP_AS_PLANNED = {"/ch/2/send/4/mode": "PRE"}
#: Three things done at the desk the plan does not have or says otherwise.
TOUCHED = {
    "/ch/1/send/1/on": 1, "/ch/1/send/1/lvl": -6.0,   # Kick opened to the Vox Wedge
    "/ch/2/send/4/mode": "POST",                      # Snare's IEM send post-fader
    "/ch/3/main/1/on": 1,                             # Rack Tom straight to Main 1
}
READINGS_TOUCHED = range(1, 7)


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
        values.update(SET_UP_AS_PLANNED)
        if reading in READINGS_TOUCHED:
            values.update(TOUCHED)
        reading += 1
        return ConsoleState(values)

    return provider, None


def test_the_demo_desk_set_up_as_planned_raises_none_of_them():
    from atoo.audit import run_audit, with_plan_rules, DEFAULT_RULES

    plan = Path(webui.DEMO_SHOW_DIR) / "plan.json"
    state = ConsoleState({**webui._load_demo_base(), **SET_UP_AS_PLANNED})
    ids = {f.rule_id for f in run_audit(state, with_plan_rules(DEFAULT_RULES, plan))}
    assert not ids & {"CV006", "CV007", "CV018"}
    touched = ConsoleState({**webui._load_demo_base(), **SET_UP_AS_PLANNED, **TOUCHED})
    ids = {f.rule_id for f in run_audit(touched, with_plan_rules(DEFAULT_RULES, plan))}
    assert {"CV006", "CV007", "CV018"} <= ids


def test_the_page_draws_the_rows_and_drops_them(home, demo_copy, monkeypatch):
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
                for rule_id, words in (
                        ("CV018", 'CH 1 "Kick": a send to BUS 1 "Vox Wedge" is on at -6dB'),
                        ("CV006", 'CH 2 "Snare": plan says send to Drum IEM mode is'),
                        ("CV007", 'CH 3 "Rack Tom": plan lists no direct route')):
                    page.wait_for_selector(f"#alert-body tr:has-text('{rule_id}')", timeout=30000)
                    row = page.locator("#alert-body tr", has_text=rule_id).first
                    assert "WARNING" in row.inner_text().upper()
                    assert words in row.inner_text()
                # The desk is put back: the rows go.
                page.wait_for_function(
                    "!/CV006|CV007|CV018/.test(document.getElementById('alert-body').innerText)",
                    timeout=30000)
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
