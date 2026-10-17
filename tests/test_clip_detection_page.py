"""The Watch page shows a clip as one ERROR row, and nothing else: no meters, no level display, no peak bars.

The Python suite cannot see the browser, and this change adds no wire field -- a clip
rides the existing finding -- so what is pinned is what the page already
does that the feature leans on: a row already showing takes each reading's
new sentence (that is how the timer's restart is seen), and an ERROR row
is Trouble. The Chromium test drives the real Demo, which simulates the
clip, with its chance turned up so the test is quick; it skips where
Playwright or Chromium is missing.
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


def test_the_page_takes_each_readings_sentence_into_a_row_it_already_shows():
    """The restart of the minute is seen in the finding's sentence ("clipped
    2 times; the last was 4 s ago"), which only works if the page redraws a
    known row's detail on every reading."""
    with fastapi_testclient.TestClient(create_app()) as client:
        js = client.get("/static/watch.js").text
    assert "known.detail = f.detail;" in js
    # Keyed by rule and strip, so a second clip is the same row.
    assert 'return f.rule_id + "|" + f.addresses.join(",") + "|" + f.severity;' in js
    # No level display: nothing in the page asks for a meter.
    for word in ("peak", "meter-bar", "level-meter"):
        assert word not in js.lower().replace("keypeak", "")


def test_the_demo_clips_in_the_real_page(home, demo_copy, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")
    monkeypatch.setattr(webui, "DEMO_CLIP_CHANCE", 1.0)
    monkeypatch.setenv("ATOO_DEMO_SEED", "703")

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
                # A clip arrives: one ERROR row, titled Clipped, rule L003.
                page.wait_for_selector("#alert-body tr:has-text('Clipped')", timeout=30000)
                row = page.locator("#alert-body tr", has_text="Clipped").first
                assert "ERROR" in row.inner_text().upper()
                assert "L003" in row.inner_text()
                assert "clipped" in row.inner_text()
                assert "clears in" in row.inner_text()
                assert page.locator("#watch-verdict-word").inner_text() == "TROUBLE"
                # The restart: a strip that clips again says how often, in the
                # same row.
                page.wait_for_function(
                    "[...document.querySelectorAll('#alert-body tr')].some("
                    "r => /clipped \\d+ times/.test(r.innerText))", timeout=60000)
                # Where it is said: the strip as the desk names it.
                text = page.locator("#alert-body").inner_text()
                assert any(label in text for label in
                           ('CH 10 "Lead Vox"', 'CH 1 "Kick"', 'BUS 5 "Drums"',
                            'BUS 6 "Vocals"', 'MAIN 1 "PA"'))
                # "This watch" carries the INFO note, not the table.
                assert "Clip detection" in page.locator("#watch-about-line").inner_text()
                assert "W002" not in page.locator("#alert-body").inner_text()
                # No level display on the page.
                assert page.locator("meter, .meter, .peak, canvas").count() == 0
                page.click("#stop-btn")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
