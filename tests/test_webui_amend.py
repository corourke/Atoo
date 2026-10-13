"""Amend inside Apply (version H phase 5) -- server and assets.

Amend is a MODE of the Apply screen, not a screen of its own, because
exactly one screen in Atoo writes to a console and it carries exactly
one arming control (`OPTIONS-H.md`). So these tests are weighted, like
`test_webui_apply.py`'s, towards the guards:

* a write without the arming checkbox reaches nothing;
* a write that is not the amendment the last preview reviewed reaches
  nothing -- same rebuild, same applied plan, same `--allow-strip`;
* one preview arms one write;
* a value the page sends that lands in an argv is known to be a strip
  label first (`--allow-strip --confirm` must not become a flag);
* amend, apply and undo share ONE runner, so two writes cannot overlap.

**No test here touches a real console, or a bundle under `examples/`.**
`atoo amend` runs for real, in the server's worker thread, against
`test_amend.DeskConsole` substituted for `WingConsole`, seeded from the
frozen `tests/fixtures/applied-show.plan.json` scenario `test_amend.py`
is built on: strips 1-19 ours, 20 somebody's "Podium" (named only on its
source socket), 21-32 free, 33-40 never answering.

The second half asserts over the served assets, because the Python suite
cannot see the browser (`CLAUDE.md`).
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
from atoo import cli  # noqa: E402
from atoo.apply import _build_write_targets  # noqa: E402
from atoo.console import OscReply  # noqa: E402
from atoo.webui import _object_base, _withheld_groups, create_app  # noqa: E402
from webui_page import armed  # noqa: E402
from test_amend import (_FACTORY, DeskConsole, amended_plan, applied_plan,  # noqa: E402
                        occupancy_state, plan_without)

CONSOLE = {"address": "198.51.100.9", "port": 2223, "timeout": 1.0,
           "address_source": "ATOO_CONSOLE"}
IDENTITY = OscReply(address="/?", typetag="s",
                    args=["WING,198.51.100.9,DESK,wing-compact,SER,3.1"])

#: The only objects the horn amendment may write: three new strips, the
#: three sockets they are patched to, and the new groups/bus the horns
#: bring. Written out rather than taken from the engine -- this is the
#: independent check.
HORN_BASES = ("/ch/21", "/ch/22", "/ch/23", "/io/in/A/21", "/io/in/A/22",
              "/io/in/A/23", "/dca/", "/mgrp/", "/bus/")


def _desk_state(applied: dict, rebuilt: dict) -> dict:
    """What `DeskConsole` answers: every address the applied plan wrote at
    its planned value, every other address a build of the rebuild would
    touch at a factory value, and the scoped occupancy read's leaves as
    `occupancy_state` describes the room."""
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
        # an undo has to find on it what the amend before it wrote.
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


def _bundle(tmp_path, rebuilt=None, name="show"):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(applied_plan(), indent=2))
    (directory / "rebuilt.plan.json").write_text(
        json.dumps(rebuilt if rebuilt is not None else amended_plan(), indent=2))
    return directory


def _app(directory, console=CONSOLE):
    return create_app(initial_bundle=str(directory),
                      initial_console=dict(console) if console else None)


@pytest.fixture
def client(tmp_path, desk):
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


def _preview(c, **body):
    r = c.post("/api/amend/run", json={"confirm": False, "arm": False, **body})
    assert r.status_code == 200, r.json()
    status = _wait(c)
    assert status["kind"] == "amend"
    return status


# ======================================================================
# Stages 1-3: the preview is the review
# ======================================================================


def test_the_one_runners_status_says_which_command_it_is(client):
    status = client.get("/api/apply/status").json()
    assert status["kind"] == "apply" and status["review"] is None


def test_a_preview_is_the_command_and_writes_nothing(client, desk):
    status = _preview(client)
    assert status["state"] == "done" and status["exit_code"] == 0, status["log"]
    command = status["command"]
    assert command[:4] == ["atoo", "amend", "--show", str(client.bundle_directory)]
    assert f"--amended-plan={client.bundle_directory / 'rebuilt.plan.json'}" in command
    assert "--review-json" in command and "--confirm" not in command
    assert command[command.index("--console") + 1] == "198.51.100.9"

    assert _writes(desk) == []
    assert not (client.bundle_directory / "amend-journal.json").exists()
    assert not (client.bundle_directory / "journals").exists()
    assert status["result"]["dry_run"] is True and status["result"]["journal_path"] is None


def test_the_review_keeps_unknown_apart_from_free(client):
    """UNKNOWN is not FREE (OPTIONS-H). Strips 33-40 never answered; the
    review the page draws must carry them as `unknown`, and placement
    must not have used one."""
    review = _preview(client)["review"]
    states = {s["label"]: s["state"] for s in review["occupancy"]}
    assert {states[f"ch:{n}"] for n in range(33, 41)} == {"unknown"}
    assert {states[f"ch:{n}"] for n in range(1, 20)} == {"ours"}
    assert states["ch:25"] == "free"
    unknown = [s for s in review["occupancy"] if s["state"] == "unknown"]
    assert all(s["unread"] for s in unknown), "an unknown strip must say what did not answer"
    assert not set(review["strips"]) & {f"ch:{n}" for n in range(33, 41)}


def test_a_strip_named_on_its_source_is_theirs_and_says_where(client):
    """#204's "Podium": blank at /ch/20/name, named on LCL 20. The review
    carries BOTH names, so the page can say the source is named even
    though the strip is not -- and the horns skip it."""
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


def test_a_dropped_channel_is_a_release_not_an_addition(tmp_path, desk):
    """#207: a removal renders distinctly and shows in the preview -- its
    own `kind`, its own address list, its own strip list."""
    applied = applied_plan()
    dropped = applied["channels"][-1]
    rebuilt = plan_without(dropped["name"])
    desk.next_state = _desk_state(applied, rebuilt)
    directory = _bundle(tmp_path, rebuilt)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        review = _preview(c)["review"]
    released = [ch for ch in review["changes"] if ch["kind"] == "released"]
    assert len(released) == 1, review["changes"]
    assert review["released"] == [f"ch:{dropped['channel']}"]
    assert f"ch:{dropped['channel']}" not in review["strips"]
    assert review["releases"] and all(r["address"] for r in review["releases"])
    assert _writes(desk) == []


def test_a_blocked_preview_says_why_and_can_never_arm_a_write(tmp_path, desk):
    """The rebuild moved Kick's source to another strip: `amend` refuses
    renumbering (FR-2.3). The review is still written -- the reason is
    the thing to read -- and the dock carries the refusal."""
    rebuilt = amended_plan()
    rebuilt["channels"][0] = dict(rebuilt["channels"][0], channel=30)
    directory = _bundle(tmp_path, rebuilt)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        status = _preview(c)
        assert status["exit_code"] == 2 and status["state"] == "done"
        assert status["review"]["blocked"] is True
        assert any(ch["kind"] == "renumbered" for ch in status["review"]["changes"])
        assert [f["code"] for f in status["findings"]] == ["amend.blocked"]

        r = c.post("/api/amend/run", json=armed(c, "/api/amend/run"))
        _wait(c)
        assert _writes(desk) == []
        assert r.status_code == 409


# ======================================================================
# Stage 4: the write, and every guard in front of it
# ======================================================================


def test_a_confirm_without_the_arming_checkbox_is_refused(client, desk):
    _preview(client)
    r = client.post("/api/amend/run", json={"confirm": True, "arm": False})
    _wait(client)
    assert _writes(desk) == [], "no arming, no write"
    assert not (client.bundle_directory / "amend-journal.json").exists()
    assert r.status_code == 400 and "not armed" in r.json()["error"]


def test_an_absent_arm_key_is_not_armed(client, desk):
    _preview(client)
    r = client.post("/api/amend/run", json={"confirm": True})
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 400


def test_a_write_with_no_preview_is_refused(client, desk):
    """Stage 3 is not optional: the write is armed only for an amendment
    a preview on this server has just shown."""
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 409 and "preview this amendment first" in r.json()["error"]


def test_a_write_for_different_allow_strips_than_were_previewed_is_refused(client, desk):
    _preview(client)
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run", allow_strips=["ch:20"]))
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 409


def test_a_rebuild_edited_after_the_preview_is_refused(client, desk):
    _preview(client)
    rebuilt = client.bundle_directory / "rebuilt.plan.json"
    stat = rebuilt.stat()
    os.utime(rebuilt, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 409


def test_a_write_recorded_on_the_stack_after_the_preview_voids_it(client, desk):
    """Per-desk journals: `amend --show` compares against the plan the
    desk's own newest write left on it, so a write (or an undo) recorded
    after the review -- from a terminal, with plan.json untouched -- is a
    different applied plan, and the review must not arm.

    Mutation-checked: drop the stack from `_amend_key` and this writes."""
    from atoo import journal_stack

    _preview(client)
    outside = client.bundle_directory.parent / "terminal-apply-journal.json"
    outside.write_text(json.dumps({"generated_at": "2026-09-24T00:00:00+00:00",
                                   "dry_run": False, "writes": []}))
    journal_stack.record(client.bundle_directory, "apply", outside,
                         desk=journal_stack.desk_from_identity(IDENTITY.args, "198.51.100.9", 2223))
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert _writes(desk) == []
    assert r.status_code == 409


def test_armed_after_a_clean_preview_writes_only_the_new_strips(client, desk):
    from atoo import journal_stack

    _preview(client)
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    assert r.status_code == 200, r.json()
    status = _wait(client)
    assert status["state"] == "done" and status["exit_code"] == 0, status["log"]
    assert "--confirm" in status["command"]

    touched = _writes(desk)
    assert touched
    assert not [a for a in touched if not any(
        a == b.rstrip("/") or a.startswith(b if b.endswith("/") else b + "/")
        for b in HORN_BASES)], "an amend wrote outside the objects it owns"

    # The page draws this run's own stack entry -- journals/ is the only
    # record, and nothing lands at the top level.
    [entry] = journal_stack.entries(client.bundle_directory)
    assert entry.kind == "amend"
    assert status["result"]["journal_path"] == str(entry.path)
    assert json.loads(entry.path.read_text())["scope"]["strips"] == ["ch:21", "ch:22", "ch:23"]
    assert not (client.bundle_directory / "amend-journal.json").exists()
    proof = status["review"]["proof"]
    assert proof["read"] is True and proof["moved"] == [] and proof["addresses"] > 300


def test_one_preview_arms_one_write(client, desk):
    _preview(client)
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    assert _wait(client)["exit_code"] == 0
    first = len(_writes(desk))
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert len(_writes(desk)) == first, "a second write needs a second review"
    assert r.status_code == 409


def test_a_full_build_apply_voids_the_amend_review(client, desk):
    """An apply rewrites the desk; a review taken before it no longer
    describes it."""
    _preview(client)
    r = client.post("/api/apply/run", json=armed(client, "/api/apply/run"))
    assert r.status_code == 200
    _wait(client)
    before = len(_writes(desk))
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert r.status_code == 409 and len(_writes(desk)) == before


@pytest.mark.parametrize("label", ["--confirm", "ch:20 --confirm", "channel 20", "ch:0",
                                   "bus:1", "ch:20,ch:21"])
def test_an_allow_strip_that_is_not_a_strip_label_never_reaches_an_argv(client, desk, label):
    """The value is spliced into a command line. It has to be known to be
    a strip label before that happens -- `--confirm` smuggled in as an
    allow-strip is the case that matters."""
    r = client.post("/api/amend/run", json={"allow_strips": [label]})
    status = _wait(client)
    assert status["state"] == "idle", status["command"]
    assert _writes(desk) == []
    assert r.status_code == 400 and "expected a strip label" in r.json()["error"]


def test_an_allow_strip_reaches_the_command_as_one_argument(client):
    status = _preview(client, allow_strips=["ch:20"])
    assert "--allow-strip=ch:20" in status["command"]
    assert status["review"]["strips"][0] == "ch:20"


def test_the_rebuild_must_exist_and_must_not_be_the_applied_plan(client, desk):
    r = client.post("/api/amend/run", json={"amended_plan": "nope.json"})
    assert r.status_code == 400 and "no rebuild at" in r.json()["error"]
    r = client.post("/api/amend/run", json={"amended_plan": "plan.json"})
    assert r.status_code == 400 and "APPLIED plan" in r.json()["error"]
    assert client.get("/api/apply/status").json()["state"] == "idle"


def test_an_amend_needs_a_bundle_a_plan_and_a_console(tmp_path, desk):
    with fastapi_testclient.TestClient(create_app(initial_console=CONSOLE)) as c:
        assert c.post("/api/amend/run", json={}).status_code == 400
    directory = _bundle(tmp_path)
    (directory / "plan.json").unlink()
    with fastapi_testclient.TestClient(_app(directory)) as c:
        r = c.post("/api/amend/run", json={})
        assert r.status_code == 400 and "no applied plan" in r.json()["error"]
    directory = _bundle(tmp_path, name="other")
    with fastapi_testclient.TestClient(_app(directory, console=None)) as c:
        r = c.post("/api/amend/run", json={})
        assert r.status_code == 400 and "no console address" in r.json()["error"]


def test_amend_and_apply_share_one_runner(client, monkeypatch):
    """One writer. An apply cannot start while an amend is in flight."""
    import threading

    from atoo import amend as amend_module

    release = threading.Event()
    real = amend_module.read_occupancy

    def slow(*a, **k):
        release.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(amend_module, "read_occupancy", slow)
    assert client.post("/api/amend/run", json={}).status_code == 200
    for _ in range(200):
        if client.get("/api/apply/status").json()["state"] == "running":
            break
        time.sleep(0.01)
    assert client.post("/api/apply/run", json={}).status_code == 409
    assert client.post("/api/undo/run", json={}).status_code == 409
    second = client.post("/api/amend/run", json={})
    assert second.status_code == 409 and "one write at a time" in second.json()["error"]
    release.set()
    _wait(client)


# ======================================================================
# The CLI flag the page reads
# ======================================================================


def test_review_json_is_written_even_when_the_amend_is_refused(tmp_path, capsys):
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


# ======================================================================
# The journal stack, and Undo -- armed by the same one checkbox
# ======================================================================


def test_the_journal_stack_lists_the_amend_on_top(client):
    assert client.get("/api/journals").json()["entries"] == []
    _preview(client)
    assert client.get("/api/journals").json()["entries"] == [], "a preview is not a write"
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    entries = client.get("/api/journals").json()["entries"]
    assert [(e["kind"], e["is_top"]) for e in entries] == [("amend", True)]
    assert entries[0]["writes"] > 0 and entries[0]["mismatches"] == 0


def test_the_journal_stack_with_no_bundle_is_empty_not_an_error(desk):
    with fastapi_testclient.TestClient(create_app()) as c:
        assert c.get("/api/journals").json() == {"bundle": None, "entries": []}


def test_an_undo_without_the_arming_checkbox_is_refused(client, desk):
    _preview(client)
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    written = len(_writes(desk))
    r = client.post("/api/undo/run", json={"confirm": True, "arm": False})
    _wait(client)
    assert len(_writes(desk)) == written
    assert r.status_code == 400 and "not armed" in r.json()["error"]


def test_an_undo_request_that_omits_the_arm_key_is_refused(client, desk):
    """Found in review: every undo test spelled `arm` out, so flipping
    `UndoRunRequest.arm`'s default to True left the whole suite green while
    a bare `{"confirm": true}` reversed the amend on the desk. The amend
    endpoint had this test; undo did not. Same lesson as #251's review --
    a default no test omits is a default no test covers."""
    _preview(client)
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    written = len(_writes(desk))
    r = client.post("/api/undo/run", json={"confirm": True})
    _wait(client)
    assert len(_writes(desk)) == written, "an absent arm key must not reverse anything"
    assert r.status_code == 400


def test_an_undo_preview_writes_nothing_and_an_armed_undo_pops_the_stack(client, desk):
    _preview(client)
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
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
    assert [e["kind"] for e in entries] == ["undo", "amend"]
    assert entries[1]["undone_by"] and not any(e["is_top"] for e in entries)


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
    for marker in ("method:", '"POST"', "/api/amend/run", "/api/undo/run", "/api/apply/run",
                   "apply-arm-checkbox", ".checked"):
        assert marker not in js, marker


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
    for url in ("/api/apply/run", "/api/amend/run", "/api/undo/run"):
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
    the INFO/WARNING and the verify's findings beside it."""
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


def test_a_preview_with_nothing_to_write_cannot_arm_a_write(tmp_path, desk):
    """A rebuild identical to the applied plan: exit 0, nothing to add and
    nothing to free. That is not a review of anything, and a write
    armed on it is refused."""
    directory = _bundle(tmp_path, applied_plan())
    with fastapi_testclient.TestClient(_app(directory)) as c:
        status = _preview(c)
        assert status["exit_code"] == 0 and status["review"]["to_write"] == []
        r = c.post("/api/amend/run", json=armed(c, "/api/amend/run"))
        _wait(c)
        assert _writes(desk) == []
        assert r.status_code == 409


# ======================================================================
# apply's pre-flight, asked of the amend -- in the review
# ======================================================================


def _identity(model_token: str) -> OscReply:
    return OscReply(address="/?", typetag="s",
                    args=[f"WING,198.51.100.9,DESK,{model_token},SER,3.1"])


def test_a_socket_the_desk_lacks_is_refused_in_the_review_and_never_arms(
        tmp_path, desk, monkeypatch):
    """A full-size WING (LCL 1..8) and a rebuild that patches the new
    Trumpet to LCL 20. The preview is the command's refusal: `blocked` in
    the review, the whole refusal in its pre-flight block, the line that
    names the socket and the channel in the dock -- and the write never
    arms, on the page or at the server."""
    monkeypatch.setattr(_Desk, "identity", lambda self: _identity("wing-fullsize"))
    rebuilt = amended_plan()
    trumpet = next(c for c in rebuilt["channels"] if c["name"] == "Trumpet")
    trumpet["patch"] = {"group": "LCL", "sockets": [20], "stated": True}
    directory = _bundle(tmp_path, rebuilt)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        status = _preview(c)
        assert status["exit_code"] == 2 and status["state"] == "done"
        review = status["review"]
        assert review["blocked"] is True
        assert review["preflight"]["refusal_code"] == "amend.socket-missing-on-desk"
        assert "LCL 20 (input) -- channel 'Trumpet'" in review["preflight"]["refusal"]
        assert [f["code"] for f in status["findings"]] == ["amend.socket-missing-on-desk"]
        assert status["findings"][0]["message"].startswith(
            "Refusing to amend: LCL 20 (channel 'Trumpet', new on ch:21) does not exist on "
            "the WING (full-size console) at 198.51.100.9.")

        r = c.post("/api/amend/run", json=armed(c, "/api/amend/run"))
        _wait(c)
        assert r.status_code == 409
        assert _writes(desk) == []


def test_a_cross_model_preview_carries_apply_s_info_to_the_dock_and_arms(
        tmp_path, desk, monkeypatch):
    """A Compact-built rebuild on a Rack: every socket it writes exists, so
    the preview is clean and arms -- and #273's INFO reaches the dock the
    way an apply's does, from the preview journal's `model_check`."""
    monkeypatch.setattr(_Desk, "identity", lambda self: _identity("wing-rack"))
    directory = _bundle(tmp_path)
    with fastapi_testclient.TestClient(_app(directory)) as c:
        status = _preview(c)
        assert status["exit_code"] == 0, status["log"]
        review = status["review"]
        assert review["blocked"] is False
        assert review["preflight"]["refusal"] is None
        assert review["preflight"]["model_check"]["outcome"] == "cross-model"
        infos = [f for f in status["findings"] if f["code"] == "apply.cross-model"]
        assert len(infos) == 1 and infos[0]["severity"] == "info"
        assert "is a WING Rack" in infos[0]["message"]

        r = c.post("/api/amend/run", json=armed(c, "/api/amend/run"))
        assert r.status_code == 200, r.json()
        _wait(c)
        assert any(a.startswith("/ch/21") for a in _writes(desk))


# ======================================================================
# plan.json is written only by a build, and the preview key
# ======================================================================


def test_after_an_armed_amend_the_next_preview_finds_nothing_and_cannot_arm(client, desk):
    """The desk's own journal entry records the amended show, so previewing
    the SAME rebuild again finds nothing to add -- before #259 it offered the
    horn section a second time, on ch:24-26 -- and a preview that found
    nothing arms nothing. plan.json is never touched."""
    plan = client.bundle_directory / "plan.json"
    before = plan.read_bytes()
    _preview(client)
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    assert _wait(client)["exit_code"] == 0
    assert plan.read_bytes() == before
    written = len(_writes(desk))

    status = _preview(client)
    assert status["exit_code"] == 0, status["log"]
    assert status["review"]["to_write"] == []
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert r.status_code == 409 and len(_writes(desk)) == written


def test_a_review_of_a_plan_that_has_since_changed_does_not_arm(client, desk):
    """The preview key hashes plan.json as well as reading its mtime. A
    confirmed amend or an undo elsewhere (the CLI, another page) rewrites
    plan.json, and mtime is only as fine as the filesystem keeps it -- so
    this changes the CONTENT and puts the mtime back exactly as it was, and
    the review must still refuse to arm.

    Mutation-checked: drop the plan.json hash from `_amend_key` and this
    reaches the desk."""
    _preview(client)
    plan = client.bundle_directory / "plan.json"
    stat = plan.stat()
    plan.write_text(plan.read_text().replace('"Kick"', '"Kick drum"', 1))
    os.utime(plan, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    r = client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert r.status_code == 409
    assert _writes(desk) == []


def test_the_undo_button_takes_the_amend_off_and_leaves_plan_json_alone(client, desk):
    plan = client.bundle_directory / "plan.json"
    before = plan.read_bytes()
    _preview(client)
    client.post("/api/amend/run", json=armed(client, "/api/amend/run"))
    _wait(client)
    assert plan.read_bytes() == before
    assert client.post("/api/undo/run", json=armed(client, "/api/undo/run")).status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert plan.read_bytes() == before
    assert any("only a build writes it" in line for line in status["log"])
