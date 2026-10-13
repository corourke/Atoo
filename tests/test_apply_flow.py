"""Apply as one four-step flow, the desk drawn as scribble
strips, and the Demo show that previews but never writes.

The mockup it builds is `mockups/apply-flow/` (approved 2026-10-13).
Tested here:

* **`desk_view`** -- what the drawing holds: every strip kind, sized from
  `console_facts.CAPACITY` (never a 40 written down), names and colours
  from the plan's own writes (Full build) or from the desk read (Patch),
  and an unread strip that stays unread.
* **`demo_desk.DemoDesk`** -- the simulated WING the Demo previews
  against: it answers the protocol, and drops a write.
* **The Demo's Patch preview** -- refused, saying why, when no model is
  set up; with one (here a stand-in that answers the frozen horns change
  set), it runs on the simulated WING and draws the four new strips.
* **The page, as served** (CLAUDE.md: the suite cannot see the browser
  code): the four headings, the button labels, the popups, and no
  "that is off here".

Nothing under `examples/` is read. The Demo show is the packaged one under
`starter/`, copied for every test that runs a command on it.
"""

from __future__ import annotations

import json
import shutil
import socket
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import console_facts, desk_view, firstrun, webui  # noqa: E402
from atoo.amend import StripState, StripStatus  # noqa: E402
from atoo.console import decode_message, encode_message  # noqa: E402
from atoo.demo_desk import DEMO_IDENTITY, DemoDesk  # noqa: E402
from atoo.webui import create_app  # noqa: E402

PACKAGED_ROOT = Path(firstrun.STARTER_DIR)
PACKAGED_SHOW = PACKAGED_ROOT / firstrun.DEMO_SHOW_NAME
FIXTURES = Path(__file__).parent / "fixtures"
LOCAL = dict(client=("127.0.0.1", 50123), base_url="http://127.0.0.1:8420")


# ---- desk_view --------------------------------------------------------------


def _plan() -> dict:
    return json.loads((PACKAGED_SHOW / "plan.json").read_text(encoding="utf-8"))


def test_the_drawing_has_every_strip_kind_sized_from_the_console_facts(monkeypatch):
    drawing = desk_view.full_build_desk(_plan())
    assert [(s["kind"], s["count"]) for s in drawing["sections"]] == [
        (kind, console_facts.CAPACITY[kind]) for kind, _ in desk_view.SECTIONS]
    assert [s["title"] for s in drawing["sections"]] == [
        "Channels", "Aux", "Buses", "Mains", "Matrices", "DCAs", "Mute groups"]
    # A desk of another size draws its own size: nothing counts to 40 itself.
    monkeypatch.setitem(console_facts.CAPACITY, "ch", 24)
    smaller = desk_view.full_build_desk(_plan())
    assert len(smaller["sections"][0]["strips"]) == 24


def test_a_full_build_draws_the_plans_own_names_and_colours():
    plan = _plan()
    drawing = desk_view.full_build_desk(plan)
    channels = {s["n"]: s for s in drawing["sections"][0]["strips"]}
    for entry in plan["channels"]:
        if entry.get("bank", "ch") != "ch":
            continue
        strip = channels[entry["channel"]]
        assert strip["state"] == "plan" and strip["name"] == entry["name"]
        assert strip["colour"] == console_facts.COLOUR_NAMES[
            console_facts.colour_index(entry["color"])]
    used = {c["channel"] for c in plan["channels"] if c.get("bank", "ch") == "ch"}
    assert all(s["state"] == "unused" for n, s in channels.items() if n not in used)
    busses = {s["n"]: s for s in drawing["sections"][2]["strips"]}
    for name, bus in plan["busses"].items():
        assert busses[bus["index"]]["name"] == name


def test_a_preview_marks_the_strips_its_write_changes():
    records = [{"address": "/ch/2/fdr", "status": "dry_run", "would_change": True},
               {"address": "/ch/3/fdr", "status": "dry_run", "would_change": False},
               {"address": "/io/in/A/1/name", "status": "dry_run", "would_change": True},
               {"address": "/bus/1/name", "status": "dry_run", "would_change": True}]
    drawing = desk_view.full_build_desk(_plan(), records)
    changes = {(s["kind"], x["n"]) for s in drawing["sections"] for x in s["strips"]
               if x["changes"]}
    assert changes == {("ch", 2), ("bus", 1)}
    assert drawing["counts"]["changing"] == 2


def test_the_patch_read_asks_a_colour_per_strip_and_a_name_per_group():
    plan = desk_view.face_read_plan()
    assert len(plan) == 144
    assert ("/ch/1/col", "i") in plan and ("/ch/1/name", "s") not in plan
    assert ("/dca/16/name", "s") in plan and ("/mgrp/8/name", "s") in plan
    assert ("/mgrp/1/col", "i") not in plan


def _status(n, state, name=None, unread=()):
    return StripStatus(base=f"/ch/{n}", bank="ch", number=n, state=state, name=name,
                       patch=None, unread=tuple(unread))


def test_a_patch_drawing_keeps_unread_apart_from_free_and_marks_the_change():
    occupancy = [_status(1, StripState.OURS, "Kick"), _status(2, StripState.FREE, ""),
                 _status(3, StripState.UNKNOWN, None, ["/ch/3/name"]),
                 _status(4, StripState.THEIRS, "Podium")]
    faces = {"/ch/1/col": 9, "/bus/1/name": "Vox Wedge", "/bus/1/col": 18,
             "/bus/2/name": "BUS 2", "/mgrp/1/name": "MGRP.1", "/dca/1/name": "Drums"}

    class Scope:
        def __init__(self, grants):
            self.grants = grants

    class Amendment:
        scope = Scope({"/ch/2": "new channel 'Horn'", "/io/in/A/21": "its socket"})
        edit_scope = Scope({"/bus/1/send/3/lvl": "a send level"})
        released: list = []
        horn = dict(_plan()["channels"][0], channel=2, name="Horn", color="Amber",
                    patch={"group": "A", "sockets": [21], "stated": True})
        effective_plan = dict(_plan(), channels=[horn])

    drawing = desk_view.patch_desk(occupancy, faces, Amendment())
    ch = {s["n"]: s for s in drawing["sections"][0]["strips"]}
    assert (ch[1]["state"], ch[1]["name"], ch[1]["colour"]) == ("used", "Kick", "Red")
    assert ch[2]["mark"] == "new" and ch[2]["name"] == "Horn" and ch[2]["colour"] == "Amber"
    assert ch[3]["state"] == "unknown"          # never "free"
    assert ch[4]["state"] == "used"
    bus = {s["n"]: s for s in drawing["sections"][2]["strips"]}
    assert bus[1]["state"] == "used" and bus[1]["mark"] == "edit"
    assert bus[2]["state"] == "free"            # the desk's own label is no name
    assert bus[3]["state"] == "unknown"         # its name was never read
    mgrp = {s["n"]: s for s in drawing["sections"][6]["strips"]}
    assert mgrp[1]["state"] == "free"
    assert drawing["counts"]["new"] == 1 and drawing["counts"]["edit"] == 1


# ---- the simulated WING --------------------------------------------------------


def _ask(port, address, typetag="", *args):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1.0)
        s.sendto(encode_message(address, typetag, *args), ("127.0.0.1", port))
        try:
            return decode_message(s.recvfrom(65535)[0])
        except socket.timeout:
            return None


def test_the_demo_desk_answers_as_a_wing_and_drops_a_write():
    with DemoDesk() as desk:
        assert _ask(desk.port, "/?").args == [DEMO_IDENTITY]
        assert _ask(desk.port, "/ch/1/name").args == ["Kick"]
        # A connector's INT is one lower on the wire than the number shown.
        assert _ask(desk.port, "/ch/1/in/conn/in").args[2] == 0
        assert _ask(desk.port, "/ch/1/col").args[2] == 8       # Red, 9, one lower
        assert _ask(desk.port, "/nope/1").args == ["NODE NOT FOUND"]
        assert _ask(desk.port, "/ch/1/name", "s", "Hijacked") is None
        assert desk.refused_writes == 1
        assert _ask(desk.port, "/ch/1/name").args == ["Kick"]


# ---- the Demo's Patch preview ------------------------------------------------------


@pytest.fixture
def demo(tmp_path, monkeypatch):
    copy = tmp_path / "package" / "starter"
    shutil.copytree(PACKAGED_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(webui, "DEMO_ROOT", copy)
    monkeypatch.setattr(webui, "DEMO_SHOW_DIR", copy / PACKAGED_SHOW.name)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    for name in ("ANTHROPIC_API_KEY", "ATOO_AI_API_KEY", "ATOO_AI_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    app = create_app()
    with fastapi_testclient.TestClient(app, **LOCAL) as c:
        assert c.post("/api/console", json={"demo": True}).status_code == 200
        yield c


def _wait(c):
    for _ in range(240):
        status = c.get("/api/apply/status").json()
        if status["state"] != "running":
            return status
        time.sleep(0.25)
    raise AssertionError("the run did not finish")


def test_with_no_model_the_demo_says_so_and_previews_a_full_build_only(demo):
    pre = demo.get("/api/apply/preflight").json()
    assert pre["patch_model"]["ready"] is False and "API key" in pre["patch_model"]["why"]
    assert pre["plan_counts"]["channels"] == len(
        [c for c in _plan()["channels"] if c.get("bank", "ch") == "ch"])
    r = demo.post("/api/patch/run", json={"change": "trumpet on LCL 21"})
    assert r.status_code == 400 and r.json()["demo"] is True
    assert "compiled by a model, and none is set up here" in r.json()["error"]
    assert "The Demo can still preview a Full build." in r.json()["error"]
    assert demo.get("/api/apply/status").json()["state"] == "idle"
    # A rebuilt plan: the Demo show has none, and cannot be given one.
    r = demo.post("/api/amend/run", json={})
    assert r.status_code == 400 and "no rebuilt plan" in r.json()["error"]


def test_with_a_model_the_demo_previews_a_typed_change_on_the_simulated_wing(demo, monkeypatch):
    from atoo import cli
    from atoo import patch as patch_engine

    change_set, _text = patch_engine.load_change_set(FIXTURES / "demo-horns.change-set.json")
    monkeypatch.setattr(patch_engine, "compile_change", lambda *a, **k: change_set)

    class Stand:
        model = "stand-in"

    monkeypatch.setattr(cli, "provider_from_env", lambda *a, **k: Stand())
    monkeypatch.setattr(webui, "_patch_model_state", lambda: (True, None))
    r = demo.post("/api/patch/run", json={"change": "trumpet, sax and trombone, Band DCA"})
    assert r.status_code == 200, r.text
    assert r.json()["on"] == "the Demo's simulated WING"
    status = _wait(demo)
    assert status["state"] == "done" and status["exit_code"] == 0, status["log"][-8:]
    desk = status["review"]["desk"]
    new = sorted((s["kind"], x["n"], x["name"]) for s in desk["sections"]
                 for x in s["strips"] if x.get("mark") == "new")
    assert new == [("bus", 8, "Horns"), ("ch", 14, "Trumpet"), ("ch", 15, "Sax"),
                   ("ch", 16, "Trombone")]
    channels = {x["n"]: x for x in desk["sections"][0]["strips"]}
    assert channels[1]["name"] == "Kick" and channels[1]["colour"] == "Red"
    assert desk["counts"]["unknown"] == 0
    # The read named its size: the occupancy read plus the drawing's 144.
    assert status["review"]["timing"]["desk_addresses"] >= 144
    # A Demo preview arms nothing -- no review is recorded
    # against the packaged show, and the page is given no review id.
    assert demo.app.state.amend_reviewed is None
    assert demo.app.state.patch_change_set is None
    assert "review_id" not in status["review"]
    # And still nothing can be written from it.
    r = demo.post("/api/patch/run", json={"change": "trumpet, sax and trombone, Band DCA",
                                          "confirm": True, "arm": True})
    assert r.status_code == 403 and "Writing is switched off" in r.json()["error"]


# ---- the page, as served -----------------------------------------------------------


@pytest.fixture
def assets():
    with fastapi_testclient.TestClient(create_app(), **LOCAL) as c:
        yield c


def test_the_page_draws_four_steps_with_one_heading_style(assets):
    html = assets.get("/static/shell.html").text
    apply_panel = html[html.index('id="mode-apply"'):html.index('id="mode-watch"')]
    titles = [part.split(">", 1)[1].split("<", 1)[0]
              for part in apply_panel.split('class="apply-step-title"')[1:]]
    assert titles == ["What will be written", "Preview", "Arm and write", "History"]
    assert apply_panel.count('class="apply-step-num"') == 4
    # One Options fold in each mode; no flag names on the screen.
    assert 'id="apply-advanced"' in apply_panel and 'id="amend-advanced"' in apply_panel
    visible = _strip_comments(apply_panel)
    for flag in ("--allow-strip", "--skip-verify", "(<code>--clean-output-sockets</code>"):
        assert flag not in visible, flag
    assert "Allow the change to reuse one occupied strip" in visible
    assert "Disconnect output sockets the plan doesn't use" in visible
    assert 'placeholder="LCL=8,A=48"' in visible


def _strip_comments(text: str) -> str:
    out, rest = [], text
    while "<!--" in rest:
        before, _, after = rest.partition("<!--")
        out.append(before)
        rest = after.partition("-->")[2]
    out.append(rest)
    return "".join(out)


def test_the_buttons_say_what_they_do(assets):
    html = assets.get("/static/shell.html").text
    js = assets.get("/static/apply.js").text
    assert '>Preview</button>' in html and "Preview (dry run)" not in html + js
    assert '"Write changes to console" : "Write to console"' in js
    assert 'id="undo-preview-btn">Preview undo<' in html
    assert 'id="undo-run-btn" disabled>Undo newest write<' in html
    # The write's result shows in step 3, in the mockup's words.
    for words in (' written · ', ' read back and confirmed', "Nothing failed to land.",
                  "The desk now matches the plan.", "didn't land: "):
        assert words in js, words


def test_the_demo_banner_is_a_popup_and_locked_controls_explain_themselves(assets):
    html = assets.get("/").text
    shell = assets.get("/static/shell.js").text
    js = assets.get("/static/apply.js").text
    assert 'id="demo-notice"' not in html
    assert 'id="demo-popup"' in html and "This is the Demo show" in html
    assert 'data-popup="demo-popup"' in html and "Demo &middot; what's this?" in html
    assert 'id="popup-preflight"' in html and 'id="popup-clean-sockets"' in html
    assert "that is off here" not in shell + js
    assert 'const DEMO_POPUP_KEY = "atoo.demoPopupSeen";' in shell
    assert '"Writing is switched off in the Demo show."' in js
    assert '"Undo is switched off in the Demo show."' in js
    assert '"Choose a console address in the bar to write to a real desk."' in js
    # Preview is not among the controls the Demo locks.
    locked = shell[shell.index("const DEMO_LOCKED = ["):]
    locked = locked[:locked.index("].join")]
    assert "#apply-preview-btn" not in locked and "#apply-run-btn" in locked


def test_the_desk_is_drawn_from_the_servers_drawing(assets):
    js = assets.get("/static/apply.js").text
    css = assets.get("/static/styles.css").text
    for key in ("run.result.drawing", "run.review.desk", "drawing.sections",
                "section.strips", "strip.colour", "strip.mark", "strip.state"):
        assert key in js, key
    assert 'name.dataset.colour = String(strip.colour).toLowerCase();' in js
    for cls in (".desk-strip", ".desk-strip-name", ".desk-strip-no", ".desk-strip.is-new",
                ".desk-strip.is-edit", ".desk-strip.is-unused", ".desk-strip.is-unknown"):
        assert cls in css, cls
    # Light theme under the three rules the page's tokens use.
    assert ':root[data-theme="light"] .desk-view' in css
    assert ':root:not([data-theme="dark"]) .desk-view' in css


def test_a_preview_is_stale_once_step_one_changes(assets):
    js = assets.get("/static/apply.js").text
    html = assets.get("/static/shell.html").text
    assert "Step 1 changed since this preview. Preview again before writing." in html
    assert "staleNote.hidden = !(reviewedFor && reviewedFor !== stepOneKey()" in js
    assert "return previewIsWritable(run) && reviewedFor === stepOneKey();" in js
    run_btn = js[js.index("runBtn.disabled = "):]
    assert "!previewed" in run_btn[:run_btn.index(";")]


def test_a_channel_the_occupancy_read_has_no_verdict_for_is_unread_not_free():
    """The occupancy read can cover fewer strips than the desk has; a
    channel or aux it says nothing about was never read, so it is drawn
    unknown -- never free -- even when its colour answered."""
    occupancy = [_status(1, StripState.FREE, "")]
    drawing = desk_view.patch_desk(occupancy, {"/ch/2/col": 1, "/aux/1/col": 1}, None)
    ch = {s["n"]: s for s in drawing["sections"][0]["strips"]}
    aux = {s["n"]: s for s in drawing["sections"][1]["strips"]}
    assert ch[1]["state"] == "free"
    assert ch[2]["state"] == "unknown" and aux[1]["state"] == "unknown"
    assert drawing["counts"]["free"] == 1 + sum(
        1 for s in drawing["sections"][2:] for x in s["strips"] if x["state"] == "free")


def test_a_demo_preview_that_cannot_open_its_copy_leaves_nothing_behind(demo, monkeypatch):
    """`_demo_preview` closes the simulated desk and removes the scratch
    copy when the copy will not load, rather than leaking both."""
    import tempfile

    from atoo import bundle, demo_desk

    opened = []
    real = demo_desk.DemoDesk

    class Tracked(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)

    monkeypatch.setattr(demo_desk, "DemoDesk", Tracked)
    before = set(Path(tempfile.gettempdir()).glob("atoo-demo-apply-*"))

    def broken(path):
        raise bundle.BundleError("no such bundle")

    monkeypatch.setattr(bundle, "load", broken)
    with pytest.raises(Exception):
        demo.post("/api/apply/run", json={"confirm": False, "arm": False})
    assert len(opened) == 1 and opened[0].sock.fileno() == -1
    assert set(Path(tempfile.gettempdir()).glob("atoo-demo-apply-*")) == before


# ---- The Demo's refusal comes first --------------------------------------


@pytest.mark.parametrize("url, body", [
    ("/api/apply/run", {}),
    ("/api/patch/run", {"change": "trumpet on LCL 21"}),
    ("/api/amend/run", {}),
])
def test_a_demo_write_is_refused_before_it_is_told_to_tick_arm(demo, url, body):
    """A `confirm` without `arm` in the Demo is the Demo's 403, not "tick
    Arm" -- ticking it would only lead here. Armed, the same 403."""
    for arm in (False, True):
        r = demo.post(url, json={**body, "confirm": True, "arm": arm})
        assert r.status_code == 403, (url, arm, r.text)
        assert r.json()["demo"] is True
        assert "Writing is switched off in the Demo show" in r.json()["error"]
        assert "not armed" not in r.json()["error"]
    assert demo.get("/api/apply/status").json()["state"] == "idle"


def test_off_the_demo_confirm_without_arm_is_still_told_to_tick_arm(tmp_path):
    """The order changed only for the Demo: anywhere else, FR-X.2's 400."""
    app = create_app(initial_console={"address": "192.0.2.9", "port": 2223})
    with fastapi_testclient.TestClient(app, **LOCAL) as c:
        for url, body in (("/api/apply/run", {}), ("/api/patch/run", {"change": "x"}),
                          ("/api/amend/run", {})):
            r = c.post(url, json={**body, "confirm": True})
            assert r.status_code == 400 and "not armed" in r.json()["error"], (url, r.text)


# ---- A UI run says what ATOO_CONSOLE_WINDOW did -------------------


@pytest.mark.parametrize("value, line", [
    ("4", "Using console window 4 from ATOO_CONSOLE_WINDOW"),
    ("lots", "ATOO_CONSOLE_WINDOW='lots' is not a whole number of at least 1"),
])
def test_a_ui_run_logs_the_console_window_as_the_cli_does(demo, monkeypatch, value, line):
    """Apply, Patch, Amend and Undo from the page are the command, so the
    run's log -- `/api/apply/status` `log`, which the Apply screen shows --
    carries the line `atoo apply` prints on a terminal."""
    monkeypatch.setenv("ATOO_CONSOLE_WINDOW", value)
    r = demo.post("/api/apply/run", json={})
    assert r.status_code == 200, r.text
    status = _wait(demo)
    assert any(entry.startswith(line) for entry in status["log"]), status["log"][:5]


def test_a_ui_run_says_nothing_of_the_default_window(demo, monkeypatch):
    monkeypatch.delenv("ATOO_CONSOLE_WINDOW", raising=False)
    assert demo.post("/api/apply/run", json={}).status_code == 200
    status = _wait(demo)
    assert not [e for e in status["log"] if "console window" in e or "CONSOLE_WINDOW" in e]
