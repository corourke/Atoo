"""The Findings dock's verdict agrees with the Plan tile about a stale plan.

A plan built before the input list (or the conventions, or the
instructions) was edited does not include the edit. The Plan tile has
always said Stale; the dock's verdict kept saying "Ready to apply" for
it, which invites applying a plan that is not what the engineer now
means. The verdict now reads the same freshness the tile reads
(`plan_freshness`): Stale, in the warning colour, naming what changed,
with Rebuild beside it -- and the Apply screen says it beside the plan.
It stays an announced warning, never a refusal (`plan_freshness`'s own
rule): applying a plan as built is a choice an engineer may make.

That is browser behaviour, which the Python suite cannot see, so:

* the asset tests always run and pin what the served page carries;
* the Chromium test drives the real page against a real server on a
  loopback port, edits and saves a row, and reads the dock and the
  Apply screen without a reload. It skips where Playwright or a
  Chromium is not installed.

The bundle is a scratch copy of the packaged Demo; nothing under `examples/`
is read, and nothing about what is in the Demo is asserted.
"""

from __future__ import annotations

import json
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
    return home


@pytest.fixture
def show(home):
    """A writable copy of the packaged Demo bundle: a plan that verifies
    clean and records the three files it was built from. Its contents are
    never asserted on."""
    directory = home / "shows" / "club"
    shutil.copytree(webui.DEMO_SHOW_DIR, directory, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(webui.DEMO_CONVENTIONS, home / "conventions.md")
    return directory


@pytest.fixture
def client(show, home):
    app = create_app(initial_bundle=str(show), initial_conventions=str(home / "conventions.md"))
    with fastapi_testclient.TestClient(app) as c:
        yield c


# ---- the served assets ------------------------------------------------------


def test_the_verdict_follows_the_plans_freshness(client):
    js = client.get("/static/shell.js").text
    verdict = js[js.index("function renderVerdict(counts)"):]
    verdict = verdict[:verdict.index("  function fill(list, rows, advice)")]
    # The same state the Plan tile reads, not a second opinion.
    assert 'const stale = hasPlan && (state === "stale" || !!counts.stale);' in verdict
    assert 'const verdict = blocked ? "blocked" : (stale ? "stale" : (hasPlan ? "ok" : "none"));' in verdict
    assert 'stale: "sev-warning"' in verdict and 'stale: "Stale"' in verdict
    # Errors still come first; the Stale tag is the badge, not a second tag.
    assert 'if (verdict !== "stale") {' in verdict
    assert " changed since the last build: rebuild before applying. " in verdict
    # What changed is named from the files `plan_freshness` reports.
    assert 'input_list: "the input list"' in js
    assert "stalePlanWhat: stalePlanWhat," in js
    css = client.get("/static/styles.css").text
    assert '.dock-verdict[data-state="stale"] { border-left-color: var(--warning-fg); }' in css


def test_the_apply_screen_says_a_stale_plan_is_stale(client):
    html = client.get("/static/shell.html").text
    assert 'id="apply-plan-stale"' in html and 'id="apply-plan-stale-text"' in html
    js = client.get("/static/apply.js").text
    assert "function renderPlanStale()" in js
    assert "SP.onBuildChange(renderPlanStale);" in js
    assert 'fresh.state === "stale"' in js
    # Said beside the plan, never a refusal: nothing here gates Preview on it.
    assert "plan_freshness" not in js[js.index("function updateArmState"):js.index("function updateArmState") + 4000]


# ---- the real page ----------------------------------------------------------


def _chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    path = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(path).exists():
        pytest.skip(f"no Chromium at {path} (set ATOO_TEST_CHROMIUM)")
    return sync_api, path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def served(show, home):
    uvicorn = pytest.importorskip("uvicorn")
    # As `atoo ui --show` opens it: the bundle and its own plan.
    plan = json.loads((show / "plan.json").read_text())
    app = create_app(initial_plan=plan, initial_plan_path=str(show / "plan.json"),
                     initial_bundle=str(show), initial_conventions=str(home / "conventions.md"))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the test server did not start")
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=5)


def _verdict(page) -> dict:
    return page.evaluate("""() => {
      const v = document.getElementById('dock-verdict');
      const badge = v.querySelector('.sev.big');
      return {state: v.dataset.state, badge: badge ? badge.textContent : null,
              cls: badge ? badge.className : '', text: v.innerText};
    }""")


@pytest.mark.parametrize("scheme", ["dark", "light"])
def test_saving_an_edit_turns_ready_to_apply_into_stale_without_a_reload(served, scheme):
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme=scheme)
            page.goto(served)
            page.wait_for_selector("#input-rows tr", state="attached")
            page.wait_for_selector("#dock-verdict:not([hidden])")
            before = _verdict(page)
            assert before["badge"] == "Ready to apply" and before["state"] == "ok"
            assert "sev-ok" in before["cls"]

            # An edit not yet saved changes nothing: the file is still the one built from.
            page.evaluate("document.getElementById('tab-input-list').click()")
            page.wait_for_selector("#panel-input-list:not([hidden])", state="attached")
            page.locator('#input-rows tr:nth-child(2) [data-col="name"]').fill("Snare Top")
            page.wait_for_selector("#input-save-btn:not([disabled])")
            assert _verdict(page)["badge"] == "Ready to apply"

            page.click("#input-save-btn")
            page.wait_for_function(
                "document.getElementById('dock-verdict').dataset.state === 'stale'")
            stale = _verdict(page)
            assert stale["badge"] == "Stale" and "sev-warning" in stale["cls"]
            assert "Ready to apply" not in stale["text"]
            assert "The input list changed since the last build: rebuild before applying." in stale["text"]
            assert page.locator("#dock-verdict .dock-jump").inner_text() == "Rebuild"
            # The tile and the verdict say the same thing.
            page.wait_for_function(
                "document.getElementById('badge-plan').textContent.trim().toLowerCase() === 'stale'")

            # Apply: the plan is not previewed as ready without saying so.
            page.click("#nav-apply")
            page.wait_for_selector("#apply-plan-stale:not([hidden])")
            note = page.locator("#apply-plan-stale-text").inner_text()
            assert note.startswith("The input list changed after this plan was built.")
            assert "or apply it as it is" in note
            assert _verdict(page)["badge"] in ("Stale", "Blocked")
        finally:
            browser.close()
