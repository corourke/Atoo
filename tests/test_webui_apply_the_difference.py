"""Build's "Apply the difference": the way from a rebuilt plan to a preview.

After an input list is edited and the plan rebuilt, Build step 04 lists
what changed since the last build. A Full build writes only the addresses
where the desk differs from the plan, so the quickest way to apply the edit
is not a second kind of write: it is Apply with Full build chosen and the
preview already run, whose "will change" count is the difference. Build's
plan box offers that as one button, and nothing in it arms a write.

Two halves, as in `test_webui_build_page.py`:

* **The served assets.** The Python suite cannot see the browser, so what
  the page relies on -- the ids, the one function Build calls and Apply
  defines, the words of the write result -- is pinned here.
* **The page in Chromium**, against a real server on a loopback port and a
  simulated WING (the packaged Demo already applied, then the plan rebuilt
  with a Hi Hat). It skips where Playwright or Chromium is missing.

Every show is built in the test from the packaged Demo; nothing under
`examples/` is read.
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

import atoo.console as console_module  # noqa: E402
from atoo import conventions_ref, firstrun, plan_diff, plan_freshness  # noqa: E402
from atoo.webui import create_app  # noqa: E402
from tests.snap_desk import PairedSnapDesk  # noqa: E402
from tests.test_apply_stereo_pair_gain import (demo_plan, fresh_desk, full_apply,  # noqa: E402
                                               with_hi_hat, would_change)

STARTER = Path(firstrun.STARTER_DIR)


# ---- the served assets ------------------------------------------------------


@pytest.fixture
def assets(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    app = create_app(initial_bundle=str(show))
    with fastapi_testclient.TestClient(app, client=("127.0.0.1", 50123),
                                       base_url="http://127.0.0.1:8420") as c:
        yield c


def test_build_has_a_line_with_the_button_and_apply_defines_what_it_calls(assets):
    html = assets.get("/static/shell.html").text
    setup = assets.get("/static/setup.js").text
    apply_js = assets.get("/static/apply.js").text
    assert 'id="plan-apply-diff"' in html
    assert 'id="plan-apply-diff-btn">Apply the difference</button>' in html
    # Drawn with the plan box, after the freshness is known, and only for a
    # current plan of the open bundle that a rebuild changed.
    assert "function renderApplyDifference()" in setup
    assert 'f.state === "current"' in setup
    assert "changesOf(current && current.plan)" in setup
    assert setup.count("renderApplyDifference();") == 2  # with the plan, and with its freshness
    assert "SP.applyTheDifference()" in setup
    # Apply: Full build, then the page's own Preview -- no arming, no write.
    body = apply_js[apply_js.index("function applyTheDifference()"):]
    body = body[:body.index("SP.applyTheDifference = applyTheDifference;")]
    assert 'SP.activateMode("apply")' in body
    assert 'setApplyMode("full")' in body
    assert "start(false)" in body
    assert "start(true" not in body and "armCheckbox" not in body
    # It waits for the pre-flight read (no timer), and says so when that
    # read did not come back.
    assert "async function applyTheDifference()" in apply_js
    assert "while (preflightLoading) await preflightLoading;" in body
    assert body.index("await preflightLoading") < body.index("start(false)")
    assert "Preview is ready when the desk has been read." in body
    assert "setTimeout" not in body


def test_the_write_result_says_how_many_addresses_were_already_right(assets):
    js = assets.get("/static/apply.js").text
    assert "already right and left alone." in js
    assert 'chip("already right", c.unchanged)' in js
    html = assets.get("/static/shell.html").text
    assert "writes only the addresses where the desk differs" in html
    assert "writes every address in the plan" not in html
    assert "writes the whole plan to a desk you own" not in js


# ---- the payload: the preview's count is the write's count ------------------


def test_the_previews_will_change_is_the_number_the_write_sends(
        tmp_path, monkeypatch):
    """Through the server, as the page does it: preview, then an armed write
    of the same plan. The count of addresses a value's selector forces to be
    written is part of the preview's, as it is of the write's."""
    from webui_page import armed

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(console_module, "WingConsole", _WebDesk)
    show, house, expected = rebuilt_bundle(tmp_path)
    app = create_app(initial_bundle=str(show), initial_conventions=str(house),
                     initial_plan=json.loads((show / "plan.json").read_text(encoding="utf-8")),
                     initial_plan_path=str(show / "plan.json"),
                     initial_console={"address": "198.51.100.9", "port": 2223, "timeout": 1.0,
                                      "address_source": "ATOO_CONSOLE"})

    def wait(c):
        deadline = time.time() + 60
        while time.time() < deadline:
            status = c.get("/api/apply/status").json()
            if status["state"] != "running":
                return status
            time.sleep(0.05)
        raise AssertionError("the run never finished")

    with fastapi_testclient.TestClient(app, client=("127.0.0.1", 50123),
                                       base_url="http://127.0.0.1:8420") as c:
        assert c.post("/api/apply/run", json={}).status_code == 200
        preview = wait(c)
        assert preview["exit_code"] == 0, preview["log"]
        counts = preview["result"]["counts"]
        assert counts["would_change"] == len(expected) > 0
        assert counts["written"] == 0

        url = "/api/apply/run"
        assert c.post(url, json=armed(c, url)).status_code == 200
        write = wait(c)
        assert write["exit_code"] == 0, write["log"]
        done = write["result"]["counts"]
        assert done["written"] == counts["would_change"]
        assert done["mismatch"] == 0 and done["unreadable"] == counts["unreadable"]
        assert done["unchanged"] == counts["total"] - counts["would_change"] - counts["unreadable"]

        # An undo preview (`atoo undo --result-json`) lists the written rows
        # and only those: the addresses found already right are not in it.
        assert c.post("/api/undo/run", json={}).status_code == 200
        undo = wait(c)
        assert undo["exit_code"] == 0, undo["log"]
        goes_back = undo["result"]["undo"]["counts"]
        assert goes_back["goes-back"] == done["written"] == len(expected)
        assert goes_back["total"] == done["written"]

        # The same plan again has nothing left to say.
        assert c.post("/api/apply/run", json={}).status_code == 200
        again = wait(c)["result"]["counts"]
        assert again["would_change"] == 0


# ---- the page in Chromium -----------------------------------------------------


def _chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    path = os.environ.get("ATOO_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    if not Path(path).exists():
        pytest.skip(f"no Chromium at {path} (set ATOO_TEST_CHROMIUM)")
    return sync_api, path


class _WebDesk(PairedSnapDesk):
    """The desk `atoo apply` opens in the server's worker: one desk, the Demo
    applied, that every command the server runs opens again and finds as the
    last one left it. Constructed the way `WingConsole` is; set `store` before
    use."""

    store: dict = {}

    def __init__(self, address, port=2223, timeout=1.0, raw_log=None, **kwargs):
        super().__init__({})
        self.values = type(self).store


def rebuilt_bundle(tmp_path) -> tuple[Path, Path, set[str]]:
    """A show bundle whose plan.json is the Demo's with a Hi Hat added and
    which reads as built from the files beside it, with the comparison a
    rebuild keeps: `(show, house conventions, the addresses the Hi Hat
    changes on a desk the Demo was applied to)`."""
    show = tmp_path / "show"
    shutil.copytree(STARTER / firstrun.DEMO_SHOW_NAME, show)
    house = tmp_path / "house.md"
    shutil.copy(STARTER / "conventions.md", house)
    plan = with_hi_hat(demo_plan())
    hat = plan["channels"][-1]
    with (show / "input.csv").open("a", encoding="utf-8", newline="") as f:
        f.write(f"17,AES50-A {hat['patch']['sockets'][0]},Hi Hat,drums,Mic,Beta 91A,TRUE,\n")
    stack = [{"path": str(house), "role": "conventions", "source": "test",
              **conventions_ref.layer_record(house, show)},
             {"path": str(show / "instructions.md"), "role": "instructions", "source": "test",
              **conventions_ref.layer_record(show / "instructions.md", show)}]
    plan["meta"]["conventions_stack"] = stack
    plan["meta"]["input_list"] = plan_freshness.input_list_record(show / "input.csv", show)
    plan["meta"][plan_diff.CHANGES_KEY] = {
        "against": "plan.previous.json",
        "counts": {"added": 1, "removed": 0, "changed": 0, "moved": 0, "unasked": 0},
        "notes": [],
        "strips": [{"collection": "channels", "kind": "added", "label": "CH 14 Hi Hat",
                    "severity": "INFO", "reason": "an input-list row was added",
                    "moved_from": None, "slot": ["ch", 14], "summary": "added",
                    "values": []}],
    }
    (show / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    applied = fresh_desk(PairedSnapDesk)
    # Two leaves of the Vox Verb's effect that the initialized capture does
    # not hold (they exist only under that effect model): present, so every
    # address the plan writes can be read and none is reported as unread.
    applied.values.update({"/fx/5/mod": 0, "/fx/5/trans": 0})
    full_apply(demo_plan(), applied, dry_run=False)
    _WebDesk.store = dict(applied.values)
    expected = would_change(full_apply(plan, applied, dry_run=True))
    return show, house, expected


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """`serve(changes=True)` -> (url, show, the addresses a write sends): the
    rebuilt bundle on a real loopback port. `changes=False` serves the same
    plan without the comparison a rebuild keeps."""
    uvicorn = pytest.importorskip("uvicorn")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(console_module, "WingConsole", _WebDesk)
    started = []

    def start(changes=True):
        show, house, expected = rebuilt_bundle(tmp_path)
        plan = json.loads((show / "plan.json").read_text(encoding="utf-8"))
        if not changes:
            del plan["meta"][plan_diff.CHANGES_KEY]
        app = create_app(initial_bundle=str(show), initial_conventions=str(house),
                         initial_plan=plan, initial_plan_path=str(show / "plan.json"),
                         initial_console={"address": "198.51.100.9", "port": 2223,
                                          "timeout": 1.0, "address_source": "ATOO_CONSOLE"})
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        started.append((server, thread))
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the test server did not start")
        return f"http://127.0.0.1:{port}/", show, expected

    yield start
    for server, thread in started:
        server.should_exit = True
        thread.join(timeout=5)


def _open_plan(page, url):
    page.add_init_script("try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                         " localStorage.setItem('atoo.theme', 'dark'); } catch (e) {}")
    page.goto(url)
    page.evaluate("() => document.getElementById('tab-plan').click()")
    page.wait_for_selector("#panel-plan:not([hidden])", state="attached")


def test_the_button_takes_the_engineer_to_a_preview_that_has_already_run(serve):
    url, show, expected = serve()
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            _open_plan(page, url)

            line = page.locator("#plan-apply-diff")
            line.wait_for(state="visible", timeout=20000)
            assert "1 strip differs from the last build" in line.inner_text()
            button = page.locator("#plan-apply-diff-btn")
            assert button.is_enabled()

            button.click()
            # Apply, with Full build chosen, and the preview running.
            page.wait_for_selector("#mode-apply.is-active", timeout=10000)
            full = page.locator("#apply-mode-full")
            assert full.get_attribute("aria-checked") == "true"
            assert full.get_attribute("role") == "radio"
            page.wait_for_function(
                "document.getElementById('apply-review-facts').innerText.includes('will change')",
                timeout=60000)
            facts = " ".join(page.locator("#apply-review-facts").inner_text().split())
            # The number the preview gives is the number a write will send:
            # the engine's own count of what differs, forced selector writes included.
            assert f"{len(expected)} will change" in facts, (facts, len(expected))
            assert "already match" in facts and "0 didn't answer" in facts
            # Nothing was armed or written: the desk was only read.
            assert not page.locator("#apply-arm-checkbox").is_checked()
            assert page.locator("#apply-run-btn").is_disabled()
            assert not page.locator("#apply-write-result").is_visible()

            # Armed, the write sends the number the preview gave -- no more --
            # reads each back, and says how many it found already right.
            page.check("#apply-arm-checkbox")
            page.click("#apply-run-btn")
            page.wait_for_function(
                "document.getElementById('apply-write-line').innerText.includes('written')",
                timeout=60000)
            n = len(expected)
            assert page.locator("#apply-write-line").inner_text() == (
                f"{n} written · {n} read back and confirmed")
            sub = page.locator("#apply-write-sub").inner_text()
            assert sub.startswith("Nothing failed to land. The desk now matches the plan.")
            assert "already right and left alone." in sub
        finally:
            browser.close()


def test_the_line_is_not_there_for_a_plan_with_nothing_changed(serve):
    url, _show, _expected = serve(changes=False)
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            _open_plan(page, url)
            page.wait_for_selector("#sec-output:not([hidden])", timeout=20000)
            assert page.locator("#plan-apply-diff").is_hidden()
        finally:
            browser.close()


def test_the_preview_waits_for_the_preflight_to_come_back(serve):
    """Apply's pre-flight read is held on the wire after the button is
    pressed: the preview must not start until it has been answered, and
    then it starts without a second press."""
    url, _show, expected = serve()
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            runs, held, hold = [], [], []
            page.on("request", lambda r: runs.append(r) if r.url.endswith("/api/apply/run") else None)

            def preflight(route):
                if hold:
                    held.append(route)
                else:
                    route.continue_()

            page.route("**/api/apply/preflight", preflight)
            _open_plan(page, url)
            line = page.locator("#plan-apply-diff")
            line.wait_for(state="visible", timeout=20000)

            hold.append(True)
            page.locator("#plan-apply-diff-btn").click()
            page.wait_for_selector("#mode-apply.is-active", timeout=10000)
            assert page.locator("#apply-mode-full").get_attribute("aria-checked") == "true"
            deadline = time.time() + 10
            while not held and time.time() < deadline:
                page.wait_for_timeout(50)
            assert held, "Apply never asked for its pre-flight"
            # The read is still out: nothing has been started, with time to have been.
            page.wait_for_timeout(1500)
            assert runs == []

            hold.clear()
            for route in held:
                route.continue_()
            page.wait_for_function(
                "document.getElementById('apply-review-facts').innerText.includes('will change')",
                timeout=60000)
            assert len(runs) == 1
            # The preview names the plan the pre-flight verified.
            assert json.loads(runs[0].post_data)["expected_plan_sha256"]
            assert f"{len(expected)} will change" in " ".join(
                page.locator("#apply-review-facts").inner_text().split())
            assert not page.locator("#apply-arm-checkbox").is_checked()
        finally:
            browser.close()


def test_a_preflight_that_does_not_answer_leaves_apply_open_with_a_word(serve):
    url, _show, _expected = serve()
    sync_api, chromium = _chromium()
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            runs, failing = [], []
            page.on("request", lambda r: runs.append(r) if r.url.endswith("/api/apply/run") else None)

            def preflight(route):
                if failing:
                    route.fulfill(status=500, body="{}")
                else:
                    route.continue_()

            page.route("**/api/apply/preflight", preflight)
            _open_plan(page, url)
            page.locator("#plan-apply-diff").wait_for(state="visible", timeout=20000)

            failing.append(True)
            page.locator("#plan-apply-diff-btn").click()
            page.wait_for_selector("#mode-apply.is-active", timeout=10000)
            message = page.locator("#apply-message")
            message.wait_for(state="visible", timeout=10000)
            assert message.inner_text() == "Preview is ready when the desk has been read."
            # As if Apply had been opened and nothing pressed: Full build
            # chosen, no run started, Preview there to press.
            assert page.locator("#apply-mode-full").get_attribute("aria-checked") == "true"
            page.wait_for_timeout(500)
            assert runs == []
            assert not page.locator("#apply-arm-checkbox").is_checked()
        finally:
            browser.close()
