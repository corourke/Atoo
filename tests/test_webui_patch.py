"""The Patch screen: a typed change, inside Apply -- server and
assets.

*"Also the UI needs to support this workflow."* The
Amend screen became the Patch screen: type a change, Preview change (one
model call, with its progress), read the review, tick the one arming
checkbox, Write the change, see it in the journal stack by its short name,
Undo newest write. These tests are weighted, like `test_webui_amend.py`'s,
towards the guards:

* a write without the arming checkbox reaches nothing;
* a write that is not the change the last preview reviewed reaches nothing
  -- same text, same plan on the desk, same `--allow-strip`, same console;
* **the write is the change set the preview compiled**, never a second
  model call's -- a model asked twice may answer differently;
* a stale page cannot write (FR-6.11);
* patch, apply and undo share ONE runner.

`atoo patch` runs for real, in the server's worker thread, against
`test_webui_amend._Desk` (the frozen applied-show scenario: strips 1-19
ours, 20 "Podium", 21-32 free, 33-40 unread), with a `FakeProvider` in
place of `cli.provider_from_env`. **No test here touches a real console, a
real model, or a bundle under `examples/`.**
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import cli, patch, webui  # noqa: E402
from atoo.webui import create_app  # noqa: E402
from webui_page import armed  # noqa: E402
from test_amend import horn  # noqa: E402
from test_webui_amend import (TEXT, _Desk, _app, _bundle, _preview, _wait, _write,  # noqa: E402,F401
                              _writes, client, desk, horns, model)

# ======================================================================
# Preview change
# ======================================================================


def test_a_preview_compiles_the_change_and_writes_nothing(client, desk, model):
    plan = client.bundle_directory / "plan.json"
    before = plan.read_bytes()
    status = _preview(client)
    assert status["exit_code"] == 0, status["log"]
    review = status["review"]
    assert review["mode"] == "patch"
    assert review["change"]["name"] == "Horns for tonight"
    assert review["change"]["text"] == TEXT
    assert review["change"]["number"] == 1
    assert review["strips"] == ["ch:21", "ch:22", "ch:23"]
    assert review["review_id"]
    assert "Timing:" in review["timing"]["line"] and review["timing"]["model_s"] is not None
    assert _writes(desk) == [] and plan.read_bytes() == before
    assert status["result"]["dry_run"] is True
    assert len(model.calls) == 1


def test_the_model_calls_progress_rides_on_the_runners_status(client, model):
    status = _preview(client)
    progress = status["progress"]
    assert progress is not None and progress["phase"] == "change"
    assert progress["stage"] == "done"


def test_the_change_text_reaches_the_model_whole(client, model):
    """Sent as a file, not an argv: a change that starts with a dash, or
    runs over several lines, is the change -- never a flag."""
    text = "--confirm\ntrumpet on A 21\n  and a sax on A 22"
    _preview(client, text=text)
    assert text in model.calls[0][1]


def test_a_refused_change_can_never_arm_a_write(client, desk, model):
    bad = horns()
    bad["add"]["channels"][0]["bus_sends"] = [{"bus": "MON9", "mode": "pre", "level_db": 0.0}]
    model.response = json.dumps(bad)
    status = _preview(client)
    assert status["exit_code"] == 2 and status["review"]["blocked"]
    assert "review_id" not in status["review"]
    assert [f["code"] for f in status["findings"]] == ["patch.blocked"]
    assert "bus 'MON9'" in status["findings"][0]["message"]
    r = _write(client)
    _wait(client)
    assert r.status_code == 409 and _writes(desk) == []


def test_empty_text_and_no_bundle_are_refused_before_anything_runs(tmp_path, desk, model):
    directory = _bundle(tmp_path)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        r = c.post("/api/patch/run", json={"change": "   "})
        assert r.status_code == 400 and "type the change first" in r.json()["error"]
    with fastapi_testclient.TestClient(create_app(initial_console={"address": "198.51.100.9"})) as c:
        r = c.post("/api/patch/run", json={"change": TEXT})
        assert r.status_code == 400 and "no show bundle open" in r.json()["error"]
    assert model.calls == []


# ======================================================================
# Write the change
# ======================================================================


def test_armed_after_a_clean_preview_writes_the_change_and_journals_it(client, desk, model):
    plan = client.bundle_directory / "plan.json"
    before = plan.read_bytes()
    _preview(client)
    r = _write(client)
    assert r.status_code == 200, r.json()
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert status["result"]["dry_run"] is False
    assert {d.state[f"/ch/{n}/name"][0] for d in desk.made[-1:] for n in (21, 22, 23)} == {
        "Trumpet", "Trombone", "T.Sax"}
    assert plan.read_bytes() == before, "plan.json is written only by a build"
    journals = client.get("/api/journals").json()
    [row] = journals["entries"]
    assert row["kind"] == "patch" and row["is_top"]
    assert row["change"] == {"number": 1, "name": "Horns for tonight", "text": TEXT}
    assert row["change_label"] == "change 1: Horns for tonight"
    # journals/ is the only record.
    assert not (client.bundle_directory / "patch-journal.json").exists()
    assert status["result"]["journal_path"] == str(
        client.bundle_directory / "journals" / row["id"])


def test_the_write_is_the_change_set_the_preview_compiled(client, desk, model):
    """A second model call could answer differently -- so the write never
    makes one. The preview's change set is handed to the command."""
    _preview(client)
    other = horns()
    other["add"]["channels"] = [horn(24, "Bagpipes", 24)]
    model.response = json.dumps(other)
    assert _write(client).status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert len(model.calls) == 1, "the write called the model again"
    assert "--change-set" in status["command"]
    written = _writes(desk)
    assert any(a.startswith("/ch/21") for a in written)
    assert not any(a.startswith("/ch/24") for a in written)


def test_a_confirm_without_the_arming_checkbox_is_refused(client, desk):
    _preview(client)
    r = client.post("/api/patch/run", json={**armed(client, "/api/patch/run", change=TEXT),
                                            "arm": False})
    assert r.status_code == 400 and "not armed" in r.json()["error"]
    assert _writes(desk) == []


def test_a_write_with_no_preview_is_refused(client, desk, model):
    r = _write(client)
    assert r.status_code == 409 and "preview this change first" in r.json()["error"]
    assert _writes(desk) == [] and model.calls == []


def test_a_write_of_different_text_than_was_previewed_is_refused(client, desk):
    _preview(client)
    r = _write(client, text=TEXT + ", and a flugelhorn")
    assert r.status_code == 409
    assert _writes(desk) == []


def test_a_write_for_different_allow_strips_is_refused(client, desk):
    _preview(client)
    r = _write(client, allow_strips=["ch:20"])
    assert r.status_code == 409 and _writes(desk) == []


def test_one_preview_arms_one_write(client, desk):
    _preview(client)
    assert _write(client).status_code == 200
    _wait(client)
    written = len(_writes(desk))
    r = _write(client)
    assert r.status_code == 409 and len(_writes(desk)) == written


def test_a_stale_page_cannot_write(client, desk):
    """FR-6.11: a confirmed write names the bundle it showed and the review
    it drew, or it is refused."""
    _preview(client)
    body = armed(client, "/api/patch/run", change=TEXT)
    no_bundle = {k: v for k, v in body.items() if k != "expected_bundle"}
    r = client.post("/api/patch/run", json=no_bundle)
    assert r.status_code == 409 and r.json()["stale"] == "bundle"
    r = client.post("/api/patch/run", json={**body, "expected_review_id": "0" * 16})
    assert r.status_code == 409 and r.json()["stale"] == "review"
    r = client.post("/api/patch/run", json={**body, "expected_review_id": None})
    assert r.status_code == 409 and r.json()["stale"] == "review"
    assert _writes(desk) == []


def test_a_write_recorded_on_the_stack_after_the_preview_voids_it(client, desk):
    """Another write (here, a patch from the same page's other review, via
    the CLI) changes the plan on the desk: the review no longer arms."""
    _preview(client)
    cli.main(["patch", "--show", str(client.bundle_directory), TEXT, "--console", "198.51.100.9",
              "--no-progress", "--confirm"])
    r = _write(client)
    assert r.status_code == 409


def test_patch_and_apply_and_undo_share_one_runner(client, model, monkeypatch):
    import threading

    gate = threading.Event()
    real = model.complete

    def slow(**kwargs):
        gate.wait(10)
        return real(**kwargs)

    monkeypatch.setattr(model, "complete", slow)
    r = client.post("/api/patch/run", json={"change": TEXT})
    assert r.status_code == 200
    for url, body in (("/api/apply/run", {}),
                      ("/api/undo/run", {}), ("/api/patch/run", {"change": TEXT})):
        r2 = client.post(url, json=body)
        assert r2.status_code == 409, (url, r2.json())
    gate.set()
    _wait(client)


def test_undo_newest_write_takes_the_change_off(client, desk):
    _preview(client)
    _write(client)
    _wait(client)
    assert client.post("/api/undo/run", json=armed(client, "/api/undo/run")).status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    rows = client.get("/api/journals").json()["entries"]
    assert [r["kind"] for r in rows] == ["undo", "patch"]
    assert rows[1]["undone_by"] == rows[0]["id"]


def test_the_apply_preflight_warns_it_would_replace_the_change(client, desk):
    """Decision 7, on the Apply screen: after a change is written, the full
    build's pre-flight says a full apply replaces it."""
    assert not any(f["code"] == "apply.replaces-changes"
                   for f in client.get("/api/apply/preflight").json()["findings"])
    _preview(client)
    _write(client)
    _wait(client)
    preflight = client.get("/api/apply/preflight").json()
    [finding] = [f for f in preflight["findings"] if f["code"] == "apply.replaces-changes"]
    assert finding["severity"] == "warning"
    assert "change 1: Horns for tonight" in finding["message"]
    assert preflight["errors"] == 0


# ======================================================================
# The assets -- the Python suite cannot see the browser
# ======================================================================


@pytest.fixture
def assets():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def test_the_page_says_patch_and_change(assets):
    html = assets.get("/static/shell.html").text
    switch = html[html.index('id="apply-mode-amend"'):]
    assert switch[switch.index(">") + 1:].startswith("Patch<")
    # The old title went; the four steps say it.
    assert "Patch a show that is already on the desk" not in html
    assert "What will be written" in html
    for element_id in ("patch-change-text", "patch-progress", "patch-change-head",
                       "patch-timing"):
        assert f'id="{element_id}"' in html, element_id


def test_the_change_box_is_not_an_arming_control(assets):
    html = assets.get("/static/shell.html").text
    assert re.findall(r'id="[^"]*arm[^"]*"', html) == ['id="apply-arm-checkbox"']
    panel = html[html.index('id="amend-panel"'):html.index('id="apply-preview-btn"')]
    # Only the Options toggle that opens the strip-to-reuse box.
    assert re.findall(r'type="checkbox" id="([^"]+)"', panel) == ["amend-allow-toggle"]


def test_apply_js_sends_a_typed_change_to_the_patch_endpoint(assets):
    js = assets.get("/static/apply.js").text
    assert '"/api/patch/run"' in js and "patchText" in js
    assert 'change: (patchText.value || "").trim()' in js
    # One Preview button, and the write says what it writes.
    assert '"Write changes to console" : "Write to console"' in js
    # The review this page drew is what a confirmed write names.
    assert "expected_review_id: (run.kind === kind && run.review && run.review.review_id)" in js
    assert "AV.renderProgress(run)" in js


def test_amend_js_draws_the_change_its_progress_and_the_journal_by_change(assets):
    js = assets.get("/static/amend.js").text
    for key in ("review.change", "change.name", "change.text", "review.timing",
                "run.progress", "entry.change", "entry.change_label", "refused:"):
        assert key in js, key
    for marker in ("method:", '"POST"', "/api/patch/run", "apply-arm-checkbox", ".checked"):
        assert marker not in js, marker


# ---- Slice 2: edits on the review; slice 3: "Keep this in the show" --------


def test_the_page_draws_edits_and_offers_to_keep_a_change(assets):
    html = assets.get("/static/shell.html").text
    for element_id in ("amend-edits", "amend-edits-list", "promote-panel", "promote-preview",
                       "promote-confirm-btn", "promote-cancel-btn"):
        assert f'id="{element_id}"' in html, element_id
    js = assets.get("/static/amend.js").text
    for key in ("review.edits", "e.moves_audio", "e.line", 'edited: "Edited', "promote-btn",
                "Keep this in the show", "entry.undone_by", "dataset.promote"):
        assert key in js, key
    # amend.js draws the button; apply.js handles it and makes the one
    # request -- to the show's files, never the console, and never armed.
    apply_js = assets.get("/static/apply.js").text
    start = apply_js.index("async function promoteCall")
    assert '"/api/patch/promote"' in apply_js[start:apply_js.index("function promoteMessage")]
    handler = apply_js[apply_js.index("// ---- Keep a change in the show"):
                       apply_js.index('el("promote-cancel-btn")')]
    assert "armCheckbox" not in handler and "arm:" not in handler


def test_keep_this_in_the_show_previews_then_writes_the_bundle_files(client, desk, model):
    directory = client.bundle_directory
    (directory / "input.csv").write_text(
        "socket,name,category,type,model,phantom,notes\nA 18,T.Sax SM57,horns,Mic,,FALSE,\n")
    (directory / "instructions.md").write_text("# Show\n")
    plan_before = (directory / "plan.json").read_bytes()
    _preview(client)
    assert _write(client).status_code == 200
    assert _wait(client)["exit_code"] == 0
    [row] = client.get("/api/journals").json()["entries"]

    r = client.post("/api/patch/promote", json={"ref": row["id"]})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["rows"] == 3 and body["written"] == [] and TEXT in body["summary"]
    assert (directory / "instructions.md").read_text() == "# Show\n"

    r = client.post("/api/patch/promote", json={"ref": row["id"], "confirm": True})
    assert r.json()["written"] == ["instructions.md", "input.csv"]
    assert TEXT in (directory / "instructions.md").read_text()
    assert "Trumpet" in (directory / "input.csv").read_text()
    assert (directory / "plan.json").read_bytes() == plan_before
    assert client.post("/api/patch/promote", json={"ref": row["id"]}).json()["already"]


def test_keep_this_in_the_show_refuses_an_unknown_change(client):
    r = client.post("/api/patch/promote", json={"ref": "bagpipes"})
    assert r.status_code == 400 and "no change 'bagpipes'" in r.json()["error"]


# ======================================================================
# a status poll racing the run's own finish
# ======================================================================


def test_a_status_poll_never_races_the_preview_finishing(client, monkeypatch):
    """An earlier change (webui: intermittent "dictionary changed size during
    iteration" in the patch pre-flight). The run's `finish` published its
    review dict and THEN added `review_id` to it, in the run's thread,
    while a `GET /api/apply/status` in flight was serializing that same
    dict. Seen once in a full-suite run.

    The window is widened here rather than waited for: the review is made
    big (a long `withheld_groups`, which `finish` adds before anything
    else), so serializing it takes a few tenths of a second, and
    `_apply_payload` -- which ran between publishing the review and
    finishing it -- is made slower than one poll, so a poll is always
    mid-serialization when the review changed. A second thread polls status the whole time. A review must be
    complete before anything can read it, and what a status poll returns
    must be its own copy."""
    import threading
    import time

    big = [{"base": f"/ch/{n}", "count": 1} for n in range(60000)]
    monkeypatch.setattr(webui, "_withheld_groups", lambda addresses: list(big))
    apply_payload = webui._apply_payload

    def slow_apply_payload(*args, **kwargs):
        time.sleep(0.6)
        return apply_payload(*args, **kwargs)

    monkeypatch.setattr(webui, "_apply_payload", slow_apply_payload)
    errors: list[BaseException] = []

    for _ in range(2):
        done = threading.Event()

        def poll():
            while not done.is_set():
                try:
                    client.get("/api/apply/status")
                except BaseException as exc:  # noqa: BLE001 -- what the test is about
                    errors.append(exc)
                    return

        poller = threading.Thread(target=poll, daemon=True)
        poller.start()
        try:
            status = _preview(client)
        finally:
            done.set()
            poller.join(timeout=60)
        assert status["review"]["review_id"], "the preview must arm a review"
    assert not errors, f"a status poll failed while the run finished: {errors[0]!r}"


def test_a_preview_takes_presets_from_the_library_the_ui_was_given(tmp_path, desk, model):
    """`ui --presets DIR` reaches a patch as it reaches a build: a horn
    whose change names the Trumpet preset carries that preset's values
    into the review."""
    from pathlib import Path

    from test_webui_amend import CONSOLE

    change_set = horns()
    change_set["add"]["channels"][0]["processing"]["preset"] = "Trumpet"
    model.response = json.dumps(change_set)
    library = Path(__file__).parent / "fixtures" / "channel_presets"
    directory = _bundle(tmp_path)
    with fastapi_testclient.TestClient(create_app(
            initial_bundle=str(directory), initial_console=dict(CONSOLE),
            initial_presets=str(library))) as c:
        status = _preview(c)
    assert status["exit_code"] == 0, status["log"]
    assert any("the preset 'Trumpet' (Trumpet.chn) puts" in i
               for i in status["review"]["infos"]), status["review"]["infos"]


# ======================================================================
# A change states the change, never when or why it is wanted
# ======================================================================


def test_nothing_a_change_says_or_is_told_to_say_assumes_an_occasion(assets):
    """The change compiler's prompt names a change by what it does, and
    tells the model not to state or imply when or why it is wanted; the
    Patch screen's copy and the commands' help carry no occasion either. The
    browser half reads the served assets, which the Python suite otherwise
    cannot see."""
    from pathlib import Path

    prompt = (Path(webui.__file__).parent / "prompts" / "change_compile.md").read_text()
    assert "tonight" not in prompt.lower()
    assert "Do not state or imply when or why the change is wanted" in " ".join(prompt.split())
    for name in ("shell.html", "apply.js", "amend.js", "setup.js", "shell.js"):
        text = assets.get(f"/static/{name}").text
        assert "tonight" not in text.lower(), name
    assert "tonight" not in assets.get("/").text.lower()
    _parser, commands = cli.build_parser()
    for command in ("patch", "amend"):
        assert "tonight" not in commands[command].format_help().lower(), command
