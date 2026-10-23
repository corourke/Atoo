"""The Watch page says when it is watching without the show's plan (W005), in a
real browser: the Plan group in the "This watch" line, the full sentence under
Details, and nothing at all for a show whose plan reads. The desk is the Demo's;
it skips where Playwright or Chromium is missing."""

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

from atoo import bundle, webui  # noqa: E402
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


def test_the_page_says_when_watch_has_no_plan(home, demo_copy, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    uvicorn = pytest.importorskip("uvicorn")
    chromium = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(chromium).exists():
        pytest.skip(f"no Chromium at {chromium} (set ATOO_TEST_CHROMIUM)")

    broken = tmp_path / "broken-show"
    broken.mkdir()
    (broken / "plan.json").write_text("{not json", encoding="utf-8")
    good = tmp_path / "good-show"
    good.mkdir()
    (good / "plan.json").write_text("{}", encoding="utf-8")

    app = create_app()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"
    shots = Path(os.environ.get("ATOO_SHOT_DIR") or tmp_path)

    def start_with(page, show):
        app.state.bundle = bundle.load(show) if show else None
        page.click("#start-btn")
        page.wait_for_selector("#alert-body tr, #watch-about-line:has-text('Reading')", timeout=30000)

    def open_details(page):
        # "This watch" is a fold and its Details are redrawn every reading, so
        # open both from the page rather than click a node that is replaced.
        page.evaluate("document.getElementById('watch-about').open = true;"
                      " const d = document.querySelector('#watch-notes summary');"
                      " if (d && !d.parentElement.open) d.click();")
        page.wait_for_selector("#watch-notes li")

    def stop(page):
        page.click("#stop-btn")
        page.wait_for_function("document.getElementById('start-btn').disabled === false")

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

                # A readable plan: no Plan group.
                start_with(page, good)
                page.wait_for_function("document.getElementById('watch-about-line').innerText"
                                       ".includes('Reading')", timeout=30000)
                assert "Plan:" not in page.locator("#watch-about-line").inner_text()
                assert not page.locator("#watch-notes").is_visible()
                stop(page)

                # No show open: said in short in "This watch", in full under Details.
                start_with(page, None)
                page.wait_for_function("document.getElementById('watch-about-line').innerText"
                                       ".includes('Plan: no plan, plan checks off')", timeout=30000)
                open_details(page)
                detail = page.locator("#watch-notes li", has_text="W005").text_content()
                assert "Watching without a plan" in detail
                assert "R012 Signal Splits And Recombines" in detail and "CV016" in detail
                page.locator("#watch-about").screenshot(path=str(shots / "watch-no-plan-dark.png"))
                stop(page)

                # A plan that will not read: the file and the reason.
                start_with(page, broken)
                page.wait_for_function("document.getElementById('watch-about-line').innerText"
                                       ".includes('Plan: plan unreadable, plan checks off')",
                                       timeout=30000)
                open_details(page)
                detail = page.locator("#watch-notes li", has_text="W005").text_content()
                assert str(broken / "plan.json") in detail and "not valid JSON" in detail
                page.locator("#watch-about").screenshot(path=str(shots / "watch-unreadable-plan-dark.png"))
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_the_page_renders_notes_the_same_way_for_every_rule_id():
    """The page keys a note on its group and summary, never on a rule id, so
    W005 needs no change under `web/static/`; this pins that."""
    page = (Path(webui.__file__).parent / "web" / "static" / "watch.js").read_text(encoding="utf-8")
    assert "n.summary || n.detail" in page and "W005" not in page
