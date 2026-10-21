"""The Patch screen's review and its guards -- server and assets.

Patch is a MODE of the Apply screen, not a screen of its own, because
exactly one screen in Atoo writes to a console and it carries exactly
one arming control. So these tests are weighted, like `test_webui_apply.py`'s,
towards the guards:

* a write without the arming checkbox reaches nothing;
* a write that is not the change the last preview reviewed reaches
  nothing -- same text, same plan on the desk, same `--allow-strip`;
* one preview arms one write;
* a value the page sends that lands in an argv is known to be a strip
  label first (`--allow-strip --confirm` must not become a flag);
* patch, apply and undo share ONE runner, so two writes cannot overlap.

This module also holds what the other Patch and Undo test modules share:
the simulated desk (`_Desk`), the bundle (`_bundle`), and the model
(`model`, a `FakeProvider` answering with the horn section).

**No test here touches a real console, a real model, or a bundle under
`examples/`.** `atoo patch` runs for real, in the server's worker thread,
against `test_amend.DeskConsole` substituted for `WingConsole`, seeded from
the frozen `tests/fixtures/applied-show.plan.json` scenario `test_amend.py`
is built on: strips 1-19 ours, 20 somebody's "Podium" (named only on its
source socket), 21-32 free, 33-40 never answering.

The second half asserts over the served assets, because the Python suite
cannot see the browser.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

import atoo.console as console_module  # noqa: E402
from atoo import cli, patch  # noqa: E402
from atoo.ai_provider import FakeProvider  # noqa: E402
from atoo.apply import _build_write_targets  # noqa: E402
from atoo.console import OscReply  # noqa: E402
from atoo.webui import _object_base, _withheld_groups, create_app  # noqa: E402
from webui_page import armed  # noqa: E402
from test_amend import (_FACTORY, DeskConsole, amended_plan, applied_plan,  # noqa: E402
                        horn, occupancy_state)

CONSOLE = {"address": "198.51.100.9", "port": 2223, "timeout": 1.0,
           "address_source": "ATOO_CONSOLE"}
IDENTITY = OscReply(address="/?", typetag="s",
                    args=["WING,198.51.100.9,DESK,wing-compact,SER,3.1"])

TEXT = "trumpet, trombone and tenor sax on A 21-23 for tonight, Horns DCA"

#: The only objects the horn change may write: three new strips, the three
#: sockets they are patched to, and the new groups/bus the horns bring.
#: Written out rather than taken from the engine -- this is the independent
#: check.
HORN_BASES = ("/ch/21", "/ch/22", "/ch/23", "/io/in/A/21", "/io/in/A/22",
              "/io/in/A/23", "/dca/", "/mgrp/", "/bus/")


def _desk_state(applied: dict, rebuilt: dict) -> dict:
    """What `DeskConsole` answers: every address the applied plan wrote at
    its planned value, every other address a build of `rebuilt` (the applied
    plan with the horns in it) would touch at a factory value, and the
    scoped occupancy read's leaves as `occupancy_state` describes the room."""
    state: dict = {}
    for plan, factory in ((rebuilt, True), (applied, False)):
        built, _ = _build_write_targets(plan, set_fader_levels=True)
        for t in built:
            state[t.address] = ((_FACTORY[t.value_type], t.value_type) if factory
                                else (t.compute_value(None), t.value_type))
    for address, value in occupancy_state(plan=applied).values.items():
        state[address] = (value, "i" if isinstance(value, int) else "s")
    return state


class _Desk(DeskConsole):
    next_state: dict = {}
    made: list = []

    def __init__(self, address, port=2223, timeout=1.0, raw_log=None):
        # The SAME dict every connection, not a copy: this is one desk, and
        # an undo has to find on it what the write before it wrote.
        super().__init__()
        self.state = type(self).next_state
        type(self).made.append(self)

    def identity(self):
        return IDENTITY

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def desk(monkeypatch):
    _Desk.made = []
    _Desk.next_state = _desk_state(applied_plan(), amended_plan())
    monkeypatch.setattr(console_module, "WingConsole", _Desk)
    return _Desk


def _writes(desk) -> list[str]:
    return ([a for d in desk.made for a, _v, _t in d.set_param_calls]
            + [a for d in desk.made for a, _p in d.set_node_calls])


def _bundle(tmp_path, name="show"):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(applied_plan(), indent=2))
    return directory


def _app(directory, console=CONSOLE):
    return create_app(initial_bundle=str(directory),
                      initial_console=dict(console) if console else None)


def horns() -> dict:
    change_set = patch.empty_change_set("Horns for tonight")
    change_set["add"]["channels"] = [horn(20, "Trumpet", 21), horn(21, "Trombone", 22),
                                     horn(22, "T.Sax", 23)]
    return change_set


def fake_model(monkeypatch, change_set=None):
    """A model that answers every compile with `change_set` (the horns by
    default). Streamed, so the runner's `progress` has something to carry."""
    fake = FakeProvider(response=json.dumps(change_set or horns()), stream_chunks=2,
                        thinking_chars=40)
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


@pytest.fixture
def model(monkeypatch):
    return fake_model(monkeypatch)


@pytest.fixture
def client(tmp_path, desk, model):
    directory = _bundle(tmp_path)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        c.bundle_directory = directory
        yield c


def _wait(c, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = c.get("/api/apply/status").json()
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("the run never finished")


PATCH = "/api/patch/run"


def _preview(c, text=TEXT, **body):
    r = c.post(PATCH, json={"confirm": False, "arm": False, "change": text, **body})
    assert r.status_code == 200, r.json()
    status = _wait(c)
    assert status["kind"] == "patch"
    return status


def _write(c, text=TEXT, **body):
    return c.post(PATCH, json=armed(c, PATCH, change=text, **body))


# ======================================================================
# The preview is the review
# ======================================================================


def test_the_one_runners_status_says_which_command_it_is(client):
    status = client.get("/api/apply/status").json()
    assert status["kind"] == "apply" and status["review"] is None


def test_the_review_keeps_unknown_apart_from_free(client):
    """A strip that never answered is not a free one. Strips 33-40 never
    answered; the review the page draws must carry them as `unknown`, and
    placement must not have used one."""
    review = _preview(client)["review"]
    states = {s["label"]: s["state"] for s in review["occupancy"]}
    assert {states[f"ch:{n}"] for n in range(33, 41)} == {"unknown"}
    assert {states[f"ch:{n}"] for n in range(1, 20)} == {"ours"}
    assert states["ch:25"] == "free"
    unknown = [s for s in review["occupancy"] if s["state"] == "unknown"]
    assert all(s["unread"] for s in unknown), "an unknown strip must say what did not answer"
    assert not set(review["strips"]) & {f"ch:{n}" for n in range(33, 41)}


def test_a_strip_named_on_its_source_is_theirs_and_says_where(client):
    """"Podium": blank at /ch/20/name, named on LCL 20. The review carries
    BOTH names, so the page can say the source is named even though the
    strip is not -- and the horns skip it."""
    review = _preview(client)["review"]
    podium = next(s for s in review["occupancy"] if s["label"] == "ch:20")
    assert podium["state"] == "theirs"
    assert podium["name"] == "" and podium["source_name"] == "Podium"
    assert podium["patch"] == ["LCL", 20]
    assert review["strips"] == ["ch:21", "ch:22", "ch:23"]


def test_the_withheld_set_is_sent_and_grouped_by_object(client):
    review = _preview(client)["review"]
    assert len(review["withheld"]) > 300
    groups = {g["base"]: g["count"] for g in review["withheld_groups"]}
    assert sum(groups.values()) == len(review["withheld"])
    assert "/ch/1" in groups and "/ch/21" not in groups
    assert review["targets_summary"].startswith(f"{len(review['to_write'])} address(es) will")


def test_object_base_groups_sockets_by_socket():
    assert _object_base("/ch/21/eq/1/g") == "/ch/21"
    assert _object_base("/io/in/A/5/name") == "/io/in/A/5"
    assert _withheld_groups(["/ch/1/name", "/ch/1/fdr", "/bus/2/name"]) == [
        {"base": "/ch/1", "count": 2}, {"base": "/bus/2", "count": 1}]


def test_a_dropped_channel_is_a_release_not_an_addition(tmp_path, desk, monkeypatch):
    """A removal renders distinctly and shows in the preview -- its own
    `kind`, its own address list, its own strip list."""
    dropped = applied_plan()["channels"][-1]
    change_set = patch.empty_change_set("Drop " + dropped["name"])
    change_set["drop"]["channels"] = [dropped["name"]]
    fake_model(monkeypatch, change_set)
    with fastapi_testclient.TestClient(_app(_bundle(tmp_path))) as c:
        review = _preview(c, f"drop {dropped['name']}")["review"]
    released = [ch for ch in review["changes"] if ch["kind"] == "released"]
    assert len(released) == 1, review["changes"]
    assert review["released"] == [f"ch:{dropped['channel']}"]
    assert f"ch:{dropped['channel']}" not in review["strips"]
    assert review["releases"] and all(r["address"] for r in review["releases"])
    assert _writes(desk) == []


# ======================================================================
# The write, and every guard in front of it
# ======================================================================


def test_an_absent_arm_key_is_not_armed(client, desk):
    _preview(client)
    r = client.post(PATCH, json={"confirm": True, "change": TEXT})
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 400


def test_a_write_for_a_plan_that_has_since_changed_does_not_arm(client, desk):
    """The preview key hashes plan.json as well as reading its mtime. A
    build elsewhere (the CLI, another page) rewrites plan.json, and mtime is
    only as fine as the filesystem keeps it -- so this changes the CONTENT and
    puts the mtime back exactly as it was, and the review must still refuse to
    arm.

    Mutation-checked: drop the plan.json hash from `_patch_key` and this
    reaches the desk."""
    _preview(client)
    plan = client.bundle_directory / "plan.json"
    stat = plan.stat()
    plan.write_text(plan.read_text().replace('"Kick"', '"Kick drum"', 1))
    os.utime(plan, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    r = _write(client)
    _wait(client)
    assert r.status_code == 409
    assert _writes(desk) == []


def test_a_write_recorded_on_the_stack_by_a_terminal_voids_the_review(client, desk):
    """Per-desk journals: `patch --show` compares against the plan the
    desk's own newest write left on it, so a write (or an undo) recorded
    after the review -- from a terminal, with plan.json untouched -- is a
    different applied plan, and the review must not arm.

    Mutation-checked: drop the stack from `_patch_key` and this writes."""
    from atoo import journal_stack

    _preview(client)
    outside = client.bundle_directory.parent / "terminal-apply-journal.json"
    outside.write_text(json.dumps({"generated_at": "2026-09-24T00:00:00+00:00",
                                   "dry_run": False, "writes": []}))
    journal_stack.record(client.bundle_directory, "apply", outside,
                         desk=journal_stack.desk_from_identity(IDENTITY.args, "198.51.100.9", 2223))
    r = _write(client)
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 409


def test_armed_after_a_clean_preview_writes_only_the_new_strips(client, desk):
    from atoo import journal_stack

    _preview(client)
    r = _write(client)
    assert r.status_code == 200, r.json()
    status = _wait(client)
    assert status["state"] == "done" and status["exit_code"] == 0, status["log"]
    assert "--confirm" in status["command"]

    touched = _writes(desk)
    assert touched
    assert not [a for a in touched if not any(
        a == b.rstrip("/") or a.startswith(b if b.endswith("/") else b + "/")
        for b in HORN_BASES)], "a change wrote outside the objects it owns"

    # The page draws this run's own stack entry -- journals/ is the only
    # record, and nothing lands at the top level.
    [entry] = journal_stack.entries(client.bundle_directory)
    assert entry.kind == "patch"
    assert status["result"]["journal_path"] == str(entry.path)
    assert json.loads(entry.path.read_text())["scope"]["strips"] == ["ch:21", "ch:22", "ch:23"]
    proof = status["review"]["proof"]
    assert proof["read"] is True and proof["moved"] == [] and proof["addresses"] > 300


def test_a_full_build_apply_voids_the_patch_review(client, desk):
    """An apply rewrites the desk; a review taken before it no longer
    describes it."""
    _preview(client)
    r = client.post("/api/apply/run", json=armed(client, "/api/apply/run"))
    assert r.status_code == 200
    _wait(client)
    before = len(_writes(desk))
    r = _write(client)
    _wait(client)
    assert r.status_code == 409 and len(_writes(desk)) == before


@pytest.mark.parametrize("label", ["--confirm", "ch:20 --confirm", "channel 20", "ch:0",
                                   "bus:1", "ch:20,ch:21"])
def test_an_allow_strip_that_is_not_a_strip_label_never_reaches_an_argv(
        client, desk, model, label):
    """The value is spliced into a command line. It has to be known to be
    a strip label before that happens -- `--confirm` smuggled in as an
    allow-strip is the case that matters."""
    r = client.post(PATCH, json={"change": TEXT, "allow_strips": [label]})
    status = _wait(client)
    assert status["state"] == "idle", status["command"]
    assert _writes(desk) == [] and model.calls == []
    assert r.status_code == 400 and "expected a strip label" in r.json()["error"]


def test_an_allow_strip_reaches_the_command_as_one_argument(client):
    status = _preview(client, allow_strips=["ch:20"])
    assert "--allow-strip=ch:20" in status["command"]


def test_a_change_needs_a_bundle_and_a_console(tmp_path, desk, model):
    with fastapi_testclient.TestClient(create_app(initial_console=CONSOLE)) as c:
        assert c.post(PATCH, json={"change": TEXT}).status_code == 400
    directory = _bundle(tmp_path, name="other")
    with fastapi_testclient.TestClient(_app(directory, console=None)) as c:
        r = c.post(PATCH, json={"change": TEXT})
        assert r.status_code == 400 and "no console address" in r.json()["error"]


# ======================================================================
# The journal stack, and Undo -- armed by the same one checkbox
# ======================================================================


def test_the_journal_stack_lists_the_patch_on_top(client):
    assert client.get("/api/journals").json()["entries"] == []
    _preview(client)
    assert client.get("/api/journals").json()["entries"] == [], "a preview is not a write"
    _write(client)
    _wait(client)
    entries = client.get("/api/journals").json()["entries"]
    assert [(e["kind"], e["is_top"]) for e in entries] == [("patch", True)]
    assert entries[0]["writes"] > 0 and entries[0]["mismatches"] == 0


def test_the_journal_stack_with_no_bundle_is_empty_not_an_error(desk):
    with fastapi_testclient.TestClient(create_app()) as c:
        assert c.get("/api/journals").json() == {"bundle": None, "entries": []}


def test_an_undo_without_the_arming_checkbox_is_refused(client, desk):
    _preview(client)
    _write(client)
    _wait(client)
    written = len(_writes(desk))
    r = client.post("/api/undo/run", json={"confirm": True, "arm": False})
    _wait(client)
    assert len(_writes(desk)) == written
    assert r.status_code == 400 and "not armed" in r.json()["error"]


def test_an_undo_request_that_omits_the_arm_key_is_refused(client, desk):
    """Every undo test used to spell `arm` out, so flipping
    `UndoRunRequest.arm`'s default to True left the whole suite green while
    a bare `{"confirm": true}` reversed the change on the desk. A default no
    test omits is a default no test covers."""
    _preview(client)
    _write(client)
    _wait(client)
    written = len(_writes(desk))
    r = client.post("/api/undo/run", json={"confirm": True})
    _wait(client)
    assert len(_writes(desk)) == written, "an absent arm key must not reverse anything"
    assert r.status_code == 400


def test_an_undo_preview_writes_nothing_and_an_armed_undo_pops_the_stack(client, desk):
    _preview(client)
    _write(client)
    _wait(client)
    written = len(_writes(desk))

    assert client.post("/api/undo/run", json={}).status_code == 200
    status = _wait(client)
    assert status["kind"] == "undo" and "--confirm" not in status["command"]
    assert status["command"][:4] == ["atoo", "undo", "--show",
                                     str(client.bundle_directory)]
    assert len(_writes(desk)) == written

    assert client.post("/api/undo/run", json=armed(client, "/api/undo/run")).status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert len(_writes(desk)) > written
    entries = client.get("/api/journals").json()["entries"]
    assert [e["kind"] for e in entries] == ["undo", "patch"]
    assert entries[1]["undone_by"] and not any(e["is_top"] for e in entries)


def test_the_undo_button_takes_the_change_off_and_leaves_plan_json_alone(client, desk):
    plan = client.bundle_directory / "plan.json"
    before = plan.read_bytes()
    _preview(client)
    _write(client)
    _wait(client)
    assert plan.read_bytes() == before
    assert client.post("/api/undo/run", json=armed(client, "/api/undo/run")).status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert plan.read_bytes() == before


# ======================================================================
# The served assets
# ======================================================================


@pytest.fixture
def assets():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def test_amend_js_is_served_and_loads_before_apply_js(assets):
    html = assets.get("/static/shell.html").text
    assert assets.get("/static/amend.js").status_code == 200
    assert html.index('src="/static/amend.js"') < html.index('src="/static/apply.js"')


def test_the_amend_switch_is_enabled_now_that_the_flow_exists(assets):
    html = assets.get("/static/shell.html").text
    amend = html[html.index('id="apply-mode-amend"'):]
    assert "disabled" not in amend[:amend.index(">")]
    # No private issue or PR reference on the page (a release strips them
    # from comments only; page text is the reader's).
    switch = html[html.index('id="apply-mode-switch"'):html.index('id="apply-mode-switch"') + 1200]
    assert not re.search(r"(?i)\b(?:issue|pr) #\d", switch)


def test_shell_html_carries_every_element_amend_js_and_apply_js_fill(assets):
    html = assets.get("/static/shell.html").text
    for script in ("amend.js", "apply.js"):
        js = assets.get(f"/static/{script}").text
        for element_id in sorted(set(re.findall(r'el\("([a-z0-9-]+)"\)', js))):
            if element_id == "initial-shell":
                continue
            assert f'id="{element_id}"' in html, f"{script}: shell.html has no #{element_id}"


def test_amend_js_writes_nothing_and_arms_nothing(assets):
    """The renderer half. Every request that can reach a console is
    apply.js's, behind its one checkbox."""
    js = assets.get("/static/amend.js").text
    for marker in ("method:", '"POST"', "/api/patch/run", "/api/undo/run", "/api/apply/run",
                   "apply-arm-checkbox", ".checked"):
        assert marker not in js, marker


def test_the_rebuilt_plan_route_is_gone_from_the_browser(assets):
    """The Patch screen is one thing: type a change. The rebuilt-plan route
    stays on the command line (`atoo amend`), and nothing on the page, in the
    scripts or on the server still names it."""
    html = assets.get("/static/shell.html").text
    served = assets.get("/").text
    scripts = {name: assets.get(f"/static/{name}").text
               for name in ("apply.js", "amend.js", "setup.js", "shell.js", "styles.css")}
    for gone in ("patch-source-change", "patch-source-rebuilt", "patch-source-switch",
                 "data-patch-only", "amend-rebuilt", "amend-build-hint",
                 "From a rebuilt plan", "Where the change comes from",
                 "rebuilt.plan.json", "/api/amend/run", "setPatchSource", "patchSource"):
        assert gone not in html and gone not in served, f"shell.html still has {gone}"
        for name, text in scripts.items():
            assert gone not in text, f"{name} still has {gone}"
    # What stays: the typed change, its Options, and the one Patch block.
    for kept in ('id="patch-change-text"', 'id="amend-allow-toggle"', 'id="amend-panel"'):
        assert kept in html
    assert assets.post("/api/amend/run", json={}).status_code in (404, 405)


def test_there_is_still_exactly_one_arming_control(assets):
    html = assets.get("/static/shell.html").text
    served = assets.get("/").text
    assert re.findall(r'id="[^"]*arm[^"]*"', html) == ['id="apply-arm-checkbox"']
    assert re.findall(r'id="[^"]*arm[^"]*"', served) == ['id="apply-arm-checkbox"']
    # Patch's Options hold one checkbox, which opens the box for
    # the strip to reuse -- an input to the preview, never an arming
    # control. It is the only checkbox in the Patch block.
    amend_panel = html[html.index('id="amend-panel"'):html.index('id="apply-preview-btn"')]
    assert re.findall(r'<input type="checkbox" id="([^"]+)"', amend_panel) == ["amend-allow-toggle"]


def test_apply_js_sends_the_arming_checkbox_with_every_write(assets):
    js = assets.get("/static/apply.js").text
    for url in ("/api/apply/run", "/api/patch/run", "/api/undo/run"):
        assert url in js
    # One body-builder per kind, and each carries the checkbox itself.
    assert js.count("arm: !!armCheckbox.checked") == 3
    # The amend write button stays disabled until a clean preview of these
    # exact inputs -- the page's half of the server's 409. Mutation-checked
    # in Chromium: without this term an armed page offers the write
    # before anything was reviewed.
    run_btn = js[js.index("runBtn.disabled = "):]
    assert "!previewed" in run_btn[:run_btn.index(";")]
    assert "!armCheckbox.checked" in run_btn[:run_btn.index(";")]
    # Undo's write button is gated by the same checkbox.
    undo = js[js.index("undoRunBtn.disabled ="):]
    assert "!armCheckbox.checked" in undo[:undo.index(";")]


def test_unknown_is_drawn_apart_from_free(assets):
    css = assets.get("/static/styles.css").text
    js = assets.get("/static/amend.js").text
    # The desk is drawn as scribble strips (apply.js, from
    # desk_view's `desk`); an unread strip keeps a state of its own there.
    apply_js = assets.get("/static/apply.js").text
    for cls in (".desk-strip.is-free", ".desk-strip.is-unknown", ".desk-strip.is-new",
                ".desk-strip.is-edit", ".desk-strip.is-released"):
        assert cls in css, cls
    assert 'if (strip.state === "unknown") cls += " is-unknown";' in apply_js
    assert "never answered — treated as in use" in apply_js
    assert "treated as OCCUPIED" in js


def test_amend_js_shows_the_source_name_not_only_the_strips(assets):
    js = assets.get("/static/amend.js").text
    for key in ("strip.source_name", "strip.name", "strip.patch", "strip.unread",
                "strip.state", "strip.label"):
        assert key in js, key


def test_amend_js_reads_every_review_key_the_command_writes(assets):
    js = assets.get("/static/amend.js").text
    for key in ("review.occupancy", "review.occupancy_summary", "review.changes",
                "review.amendment_summary",
                "review.infos", "review.warnings", "review.releases",
                "review.targets_summary", "review.targets_warnings", "review.withheld",
                "review.withheld_groups", "review.proof", "review.blocked",
                "review.collisions", "review.preflight", "change.kind", "change.line"):
        assert key in js, f"amend.js never reads {key}"
    # The strips a write lands on are named in step 3's result (apply.js).
    apply_js = assets.get("/static/apply.js").text
    assert "review.strips" in apply_js and "review.released" in apply_js


def test_amend_js_draws_the_preflight_refusal_verbatim(assets):
    """The refusal is the command's text, drawn whole, with
    The INFO/WARNING and the verify's findings beside it."""
    js = assets.get("/static/amend.js").text
    for key in ("pre.refusal", "pre.where", "pre.skip_verify", "pre.model_check",
                "pre.verify", "renderPreflight(review);"):
        assert key in js, f"amend.js never reads {key}"


def test_amend_js_says_the_applied_plan_is_the_desks_own(assets):
    """Per-desk journals: the subject line no longer says the applied plan
    IS plan.json -- it is the bar's desk's own newest write's, with
    plan.json as the fallback -- and the review's INFO says which. That is said in the Patch head's '?', not the subject line."""
    html = assets.get("/static/shell.html").text
    start = html.index('id="help-patch"')
    help_text = html[start:html.index("</span>", start)]
    assert "this desk's newest write left on it" in help_text
    assert "if this bundle has not written to it" in help_text


def test_removals_render_distinctly_from_additions(assets):
    js = assets.get("/static/amend.js").text
    css = assets.get("/static/styles.css").text
    assert '"amend-change kind-" + change.kind' in js
    assert ".amend-change.kind-added" in css and ".amend-change.kind-released" in css


def test_the_screen_says_amend_is_a_setup_window_operation(assets):
    html = assets.get("/static/shell.html").text
    assert "after the build, before doors" in html
    assert "not\n              mid-show" in html or "not mid-show" in html


def test_there_is_no_click_to_open_a_strip(assets):
    """`--allow-strip` is typed. A click on a grid cell is too routine a
    gesture to open an unread strip with."""
    js = assets.get("/static/amend.js").text
    assert "addEventListener" not in js


def test_a_preview_with_nothing_to_write_cannot_arm_a_write(client, desk, monkeypatch):
    """A change that adds nothing and drops nothing: exit 0, nothing to
    write. That is not a review of anything, and a write armed on it is
    refused."""
    fake_model(monkeypatch, patch.empty_change_set("Nothing"))
    status = _preview(client, "leave everything as it is")
    assert status["exit_code"] == 0 and status["review"]["to_write"] == []
    r = _write(client, "leave everything as it is")
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 409


# ======================================================================
# Apply's pre-flight, asked of the change -- in the review
# ======================================================================


def _identity(model_token: str) -> OscReply:
    return OscReply(address="/?", typetag="s",
                    args=[f"WING,198.51.100.9,DESK,{model_token},SER,3.1"])


def test_a_socket_the_desk_lacks_is_refused_in_the_review_and_never_arms(
        client, desk, monkeypatch):
    """A full-size WING (LCL 1..8) and a change that patches the new
    Trumpet to LCL 20. The preview is the command's refusal: `blocked` in
    the review, the whole refusal in its pre-flight block, the line that
    names the socket and the channel in the dock -- and the write never
    arms, on the page or at the server."""
    monkeypatch.setattr(_Desk, "identity", lambda self: _identity("wing-fullsize"))
    change_set = horns()
    trumpet = next(c for c in change_set["add"]["channels"] if c["name"] == "Trumpet")
    trumpet["patch"] = {"group": "LCL", "sockets": [20], "stated": True}
    fake_model(monkeypatch, change_set)
    status = _preview(client)
    assert status["exit_code"] == 2 and status["state"] == "done"
    review = status["review"]
    assert review["blocked"] is True
    assert review["preflight"]["refusal_code"] == "amend.socket-missing-on-desk"
    assert "LCL 20 (input) -- channel 'Trumpet'" in review["preflight"]["refusal"]
    assert [f["code"] for f in status["findings"]] == ["amend.socket-missing-on-desk"]
    assert status["findings"][0]["message"].startswith(
        "Refusing to write this change: LCL 20 (channel 'Trumpet', new on ch:21) does not "
        "exist on the WING (full-size console) at 198.51.100.9.")

    r = _write(client)
    _wait(client)
    assert r.status_code == 409
    assert _writes(desk) == []


def test_a_cross_model_preview_carries_apply_s_info_to_the_dock_and_arms(
        client, desk, monkeypatch):
    """A Compact-built show on a Rack: every socket the change writes
    exists, so the preview is clean and arms -- and the INFO reaches the dock
    the way an apply's does, from the preview journal's `model_check`."""
    monkeypatch.setattr(_Desk, "identity", lambda self: _identity("wing-rack"))
    status = _preview(client)
    assert status["exit_code"] == 0, status["log"]
    review = status["review"]
    assert review["blocked"] is False
    assert review["preflight"]["refusal"] is None
    assert review["preflight"]["model_check"]["outcome"] == "cross-model"
    infos = [f for f in status["findings"] if f["code"] == "apply.cross-model"]
    assert len(infos) == 1 and infos[0]["severity"] == "info"
    assert "is a WING Rack" in infos[0]["message"]

    r = _write(client)
    assert r.status_code == 200, r.json()
    _wait(client)
    assert any(a.startswith("/ch/21") for a in _writes(desk))


# ======================================================================
# The command's own review file
# ======================================================================


def test_review_json_is_written_even_when_the_amend_is_refused(tmp_path, capsys):
    """`atoo amend` (a rebuilt plan, the command line's route) writes the
    review the page draws even when it refuses; the page reads the same
    shape from `atoo patch`."""
    rebuilt = amended_plan()
    rebuilt["channels"][0] = dict(rebuilt["channels"][0], channel=30)
    applied_path = tmp_path / "plan.json"
    applied_path.write_text(json.dumps(applied_plan()))
    rebuilt_path = tmp_path / "rebuilt.json"
    rebuilt_path.write_text(json.dumps(rebuilt))
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(occupancy_state().values))
    review_path = tmp_path / "review.json"

    code = cli.main(["amend", "--plan", str(applied_path), "--amended-plan",
                     str(rebuilt_path), "--state", str(state_path),
                     "--review-json", str(review_path)])
    out = capsys.readouterr().out
    assert code == 2
    review = json.loads(review_path.read_text())
    assert review["blocked"] is True
    # The command's own words, verbatim -- the page never re-words them.
    assert review["amendment_summary"] in out
    assert review["occupancy_summary"] in out
    assert review["proof"] is None


def test_a_compile_that_fails_says_which_atoo_ran(tmp_path, desk, monkeypatch):
    """The Patch page's failure is the command's own, and it carries the
    line saying which copy of Atoo ran -- in the finding, where a reader
    forwarding the failure finds it, as well as in the run log."""
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response="this is not json at all"))
    with fastapi_testclient.TestClient(_app(_bundle(tmp_path))) as c:
        c.post(PATCH, json={"confirm": False, "arm": False, "change": "add a thing"})
        status = _wait(c)
    assert status["exit_code"] == 1
    [finding] = [f for f in status["findings"] if f["code"] == "preview.failed"]
    assert "usable change set" in finding["message"]
    assert re.search(r" Ran as atoo \d[^ ]* \(", finding["message"]), finding["message"]
    assert any(line.strip().startswith("atoo ") for line in status["log"])


def test_a_socket_past_the_end_of_the_stage_box_is_refused_in_the_preview(
        tmp_path, desk, monkeypatch):
    """The desk names an S16 on AES50-A, and the horns are on A 21-23: not
    sockets that box has. The Patch page's preview says so and arms nothing."""
    desk.next_state["/$stat/A/dev"] = ("S16", "s")
    fake_model(monkeypatch)
    with fastapi_testclient.TestClient(_app(_bundle(tmp_path))) as c:
        r = c.post(PATCH, json={"confirm": False, "arm": False, "change": TEXT})
        assert r.status_code == 200, r.json()
        status = _wait(c)
        review = status["review"]
        pre = review["preflight"]
        assert review["blocked"] and "review_id" not in review
        assert pre["refusal_code"] == "amend.socket-missing-on-box"
        assert "the S16 on AES50-A" in pre["refusal"] and "has 16 inputs" in pre["refusal"]
        assert {"A 21", "A 22", "A 23"} <= {m.split(" (")[0] for m in pre["missing"]}
        [finding] = [f for f in status["findings"]
                     if f["code"] == "amend.socket-missing-on-box"]
        assert finding["severity"] == "error"
        refused = _write(c)
        _wait(c)
    assert refused.status_code == 409 and _writes(desk) == []
