"""The browser's Patch on a show built with presets: an edit to a running
channel is reviewed and written, and a refusal is headed for what it is.

`atoo patch` runs for real in the server's worker thread against the
simulated desk of `test_webui_amend`, with a canned model reply. The plan is
the frozen applied show with presets expanded into it
(`test_patch_preset_values.preset_plan`); nothing reads `examples/`.
"""

from __future__ import annotations

import json

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import console as console_module  # noqa: E402
from atoo.ai_provider import FakeProvider  # noqa: E402
from atoo import cli  # noqa: E402
from test_amend import amended_plan  # noqa: E402
from test_patch_preset_values import _change_set, _modify, preset_plan  # noqa: E402
from test_webui_amend import _Desk, _app, _desk_state, _preview, _wait, _write, _writes  # noqa: E402

RENAME = "rename channel 2 to Test Vox"


@pytest.fixture
def desk(monkeypatch):
    _Desk.made = []
    _Desk.next_state = _desk_state(preset_plan(), amended_plan())
    monkeypatch.setattr(console_module, "WingConsole", _Desk)
    return _Desk


def _model(monkeypatch, change_set: dict) -> FakeProvider:
    fake = FakeProvider(response=json.dumps(change_set))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


@pytest.fixture
def client(tmp_path, desk):
    directory = tmp_path / "show"
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(preset_plan(), indent=2))
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.bundle_directory = directory
        yield c


def test_a_rename_of_a_preset_channel_is_reviewed_not_refused(client, desk, monkeypatch):
    _model(monkeypatch, _change_set(_modify("Snare", {"name": "Test Vox"})))
    status = _preview(client, text=RENAME)
    assert status["exit_code"] == 0, status["log"]
    review = status["review"]
    assert not review["blocked"] and review["review_id"]
    assert [c["kind"] for c in review["changes"] if c["kind"] != "unchanged"] == ["edited"]
    assert [f["code"] for f in status["findings"] if f["severity"] == "error"] == []
    assert "not a field this format has" not in status["log"]
    assert _writes(desk) == []


def test_that_rename_is_written_and_only_the_name_moves(client, desk, monkeypatch):
    _model(monkeypatch, _change_set(_modify("Snare", {"name": "Test Vox"})))
    _preview(client, text=RENAME)
    r = _write(client, text=RENAME)
    assert r.status_code == 200, r.json()
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert desk.made[-1].state["/ch/2/name"][0] == "Test Vox"
    assert not any(a.startswith(("/ch/2/gate", "/ch/2/eq", "/ch/2/dyn", "/ch/2/peq"))
                   for a in _writes(desk))


def test_the_fader_of_a_preset_channel_is_set(client, desk, monkeypatch):
    _model(monkeypatch, _change_set(_modify("Snare", {"fader.fader_db": -10.0})))
    text = "set the Snare fader to -10dB"
    status = _preview(client, text=text)
    assert status["exit_code"] == 0, status["log"]
    assert _write(client, text=text).status_code == 200
    assert _wait(client)["exit_code"] == 0
    assert desk.made[-1].state["/ch/2/fdr"][0] == pytest.approx(-10.0)


def test_a_field_the_format_lacks_is_still_refused_and_arms_nothing(client, desk, monkeypatch):
    _model(monkeypatch, _change_set(_modify("Snare", {"processing.foo": 1})))
    status = _preview(client, text="foo the snare")
    assert status["exit_code"] == 2
    assert status["review"]["blocked"] and "review_id" not in status["review"]
    [refused] = [c for c in status["review"]["changes"] if c["kind"] == "refused"]
    assert "processing.foo: not a field this format has" in refused["line"]
    [finding] = [f for f in status["findings"] if f["code"] == "patch.blocked"]
    assert "processing.foo" in finding["message"]
    r = _write(client, text="foo the snare")
    _wait(client)
    assert r.status_code == 409 and _writes(desk) == []


def test_the_refusal_is_not_headed_as_if_it_named_something_missing(client):
    js = client.get("/static/amend.js").text
    assert 'refused: "Refused: cannot be written as asked"' in js
    assert "names something that is not there" not in js


# ======================================================================
# The real page, in Chromium (dark first)
# ======================================================================


def _drive(tmp_path, monkeypatch, change_set, text, theme="dark"):
    """Preview `text` on the Patch screen against the simulated desk and
    return (the review rows as (kind label, row text), the page's text)."""
    from playwright.sync_api import sync_playwright
    from atoo import webui
    from test_webui_choosers import _chromium, _serve

    chromium = _chromium()
    _model(monkeypatch, change_set)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(webui, "_patch_model_state", lambda: (True, None))
    directory = tmp_path / "show"
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(preset_plan(), indent=2))
    server, thread, url = _serve(_app(directory))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chromium)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 1000})
                page.add_init_script(
                    "try { localStorage.setItem('atoo.demoPopupSeen', '1');"
                    f" localStorage.setItem('atoo.theme', '{theme}'); }} catch (e) {{}}")
                page.goto(url)
                page.click("#nav-apply")
                page.click("#apply-mode-amend")
                page.fill("#patch-change-text", text)
                page.click("#apply-preview-btn")
                page.wait_for_function(
                    "document.getElementById('patch-timing').innerText.includes('Timing')"
                    " || document.querySelector('.amend-change-kind') !== null",
                    timeout=60000)
                assert page.evaluate("document.documentElement.dataset.theme") == theme
                kinds = page.locator(".amend-change-kind").all_text_contents()
                return kinds, page.text_content("body")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_the_patch_page_shows_a_rename_of_a_preset_channel_as_an_edit(
        tmp_path, monkeypatch, desk):
    kinds, body = _drive(tmp_path, monkeypatch,
                         _change_set(_modify("Snare", {"name": "Test Vox"})), RENAME)
    assert "Edited: named fields only" in kinds
    assert not any(k.startswith("Refused") for k in kinds)
    assert "not a field this format has" not in body


def test_the_patch_page_heads_a_refusal_for_what_it_is(tmp_path, monkeypatch, desk):
    kinds, body = _drive(tmp_path, monkeypatch,
                         _change_set(_modify("Snare", {"processing.foo": 1})), "foo the snare")
    assert "Refused: cannot be written as asked" in kinds
    assert "names something that is not there" not in body
    assert "processing.foo: not a field this format has" in body
