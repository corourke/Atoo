"""The Watch page's Virtual soundcheck switch, in a real browser.

The Python suite cannot see the page, so what is pinned here is what an engineer
sees: a toggle in the header that is Off at every Start, a state tag beside the
connection while it is On, the C004 rows regraded from WARNING to INFO the moment
it is pressed and back to WARNING when it is released, the note under "This
watch", and a Stop that forgets it. The desk is the Demo's, with channels 1 and
2 on their alternate input; it skips where Playwright or Chromium is missing.
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

    def provider() -> ConsoleState:
        values = dict(base)
        for n in (1, 2):
            values[f"/ch/{n}/in/set/altsrc"] = 1
            values[f"/ch/{n}/in/conn/altgrp"] = "CRD"
        return ConsoleState(values)

    return provider, None


def _alt_rows(page):
    return page.locator("#alert-body tr", has_text="C004")


def test_the_page_regrades_the_alternate_rows_with_the_switch(home, demo_copy, monkeypatch, tmp_path):
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
                toggle, tag = page.locator("#watch-virtual"), page.locator("#vs-pill")

                # Off at Start: a switch, no tag, the rows are warnings.
                assert toggle.get_attribute("role") == "switch" and toggle.locator(".word").inner_text() == "Off"
                assert toggle.get_attribute("aria-checked") == "false" and not tag.is_visible()
                page.fill("#interval", "0.5")
                page.click("#start-btn")
                page.wait_for_selector("#alert-body tr:has-text('C004')", timeout=30000)
                assert _alt_rows(page).count() == 2
                assert all("WARNING" in t.upper() for t in _alt_rows(page).all_inner_texts())

                # On: the tag appears at once, the rows become INFO and say why.
                toggle.click()
                assert toggle.locator(".word").inner_text() == "On"
                assert toggle.get_attribute("aria-checked") == "true"
                assert tag.is_visible() and tag.inner_text().lower() == "virtual soundcheck"
                page.wait_for_function(
                    "[...document.querySelectorAll('#alert-body tr')]"
                    ".filter(r => /C004/.test(r.innerText) && /INFO/i.test(r.innerText)).length === 2",
                    timeout=30000)
                # (a cleared row fades out before it leaves the table)
                page.wait_for_function(
                    "![...document.querySelectorAll('#alert-body tr')]"
                    ".some(r => /C004/.test(r.innerText) && /WARNING/i.test(r.innerText))",
                    timeout=30000)
                first = _alt_rows(page).first.inner_text()
                assert "Virtual soundcheck is on, so this is expected" in first
                # Still named, strip by strip.
                assert 'CH 1' in first and 'CH 2' in _alt_rows(page).nth(1).inner_text()
                # Recorded in "This watch".
                page.wait_for_function(
                    "/Virtual soundcheck: on, alternate inputs at INFO/"
                    ".test(document.getElementById('watch-about-line').innerText)", timeout=30000)
                page.screenshot(path=str(tmp_path / "on.png"))

                # Off: a strip still on its alternate is a warning again.
                toggle.click()
                assert toggle.locator(".word").inner_text() == "Off" and not tag.is_visible()
                page.wait_for_function(
                    "[...document.querySelectorAll('#alert-body tr')]"
                    ".filter(r => /C004/.test(r.innerText) && /WARNING/i.test(r.innerText)).length === 2",
                    timeout=30000)
                page.wait_for_function(
                    "![...document.querySelectorAll('#alert-body tr')]"
                    ".some(r => /C004/.test(r.innerText) && /INFO/i.test(r.innerText))",
                    timeout=30000)
                assert not page.locator("#watch-notes").is_visible()

                # A switch left on does not survive Stop.
                toggle.click()
                assert tag.is_visible()
                page.click("#stop-btn")
                page.wait_for_function("document.getElementById('start-btn').disabled === false")
                assert toggle.locator(".word").inner_text() == "Off" and not tag.is_visible()

                # Chosen before Start, it is on from the first reading.
                toggle.click()
                page.click("#start-btn")
                page.wait_for_function(
                    "[...document.querySelectorAll('#alert-body tr')]"
                    ".filter(r => /C004/.test(r.innerText) && /INFO/i.test(r.innerText)).length === 2",
                    timeout=30000)
                assert tag.is_visible()
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
