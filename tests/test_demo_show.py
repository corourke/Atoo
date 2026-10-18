"""The demo show: a packaged, read-only show bundle that
matches the Demo console's rig.

Choosing **Demo** in the bundle bar's console dialog
opens the demo show and points the console at the Demo rig, as one
action; choosing an address, or opening or creating another show, leaves
it; and the demo show is immutable -- Save, Build, New file and Change
file are refused, and Apply never arms against the rig.

The subject here IS the packaged demo show (`starter/demo-show/`, in
the starter set), not
anything under `examples/`, so these tests read it directly. They assert
on what the demo promises -- it opens, it is read-only, its plan
verifies, its watch.json fires against the rig -- and on the few names
the rig and the show share by design.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import webui  # noqa: E402
from atoo.audit import ConsoleState, DEFAULT_RULES, run_audit  # noqa: E402
from atoo.input_list import load_input_list  # noqa: E402
from atoo.presets import PresetLibrary  # noqa: E402
from atoo.verify_plan import verify_plan  # noqa: E402
from atoo.watch_conditions import build_watch_rules, parse_watch_conditions  # noqa: E402
from atoo.webui import create_app  # noqa: E402

#: The packaged demo show itself -- read, never written, by these tests.
PACKAGED_ROOT = webui.DEMO_ROOT
PACKAGED_SHOW = webui.DEMO_SHOW_DIR
PACKAGED_CONVENTIONS = webui.DEMO_CONVENTIONS
PACKAGED_PRESETS = webui.DEMO_PRESETS

LOCAL = {}


@pytest.fixture(autouse=True)
def demo_copy(tmp_path, monkeypatch):
    """The server's demo show is a COPY of the packaged one, so a guard
    that fails here writes into a scratch folder, never into the package
    (it did once, while these tests were being mutation-checked)."""
    copy = tmp_path / "package" / "starter"
    shutil.copytree(PACKAGED_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(webui, "DEMO_ROOT", copy)
    monkeypatch.setattr(webui, "DEMO_SHOW_DIR", copy / PACKAGED_SHOW.name)
    monkeypatch.setattr(webui, "DEMO_CONVENTIONS", copy / "conventions.md")
    monkeypatch.setattr(webui, "DEMO_PRESETS", copy / "presets")
    return copy


def _fingerprint() -> dict:
    """Every demo file the server has and its sha256 -- what "nothing was
    written" means here."""
    root = webui.DEMO_ROOT
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()
            and "__pycache__" not in p.parts}


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def show(home):
    show = home / "shows" / "festival"
    show.mkdir(parents=True)
    (show / "input.csv").write_text("socket,name,category,type\nLCL 1,Kick,drums,Mic\n")
    (show / "instructions.md").write_text("## Channels\n- Kick first.\n")
    return show


DESK = {"address": "203.0.113.50", "port": 2223,
        "address_source": "~/.atoo.config [console]"}


@pytest.fixture
def client(show):
    app = create_app(initial_bundle=str(show), initial_console=dict(DESK))
    with fastapi_testclient.TestClient(app, **LOCAL) as c:
        c.app_state = app.state
        yield c


def _demo(c):
    r = c.post("/api/console", json={"demo": True})
    assert r.status_code == 200, r.text
    return r.json()


# ---- Choosing Demo -----------------------------------------------------------

def test_demo_opens_the_demo_show_and_sets_the_demo_console(client):
    answer = _demo(client)
    assert answer["demo"] is True and answer["address"] is None
    assert answer["bundle_changed"] is True
    shown = answer["bundle"]
    assert shown["directory"] == str(webui.DEMO_SHOW_DIR)
    assert shown["name"] == "Demo show"
    assert shown["demo"] is True and shown["read_only"] is True
    assert client.get("/api/bundle").json()["demo"] is True

    # Build: the demo's own house conventions, never the user's, and the
    # plan is the demo's -- fresh against its three inputs.
    sources = client.get("/api/build/sources").json()
    assert sources["read_only"] is True
    assert sources["conventions"]["path"] == str(webui.DEMO_CONVENTIONS)
    assert "demo show" in sources["conventions"]["origin"]
    assert sources["input_list"]["path"] == str(webui.DEMO_SHOW_DIR / "input.csv")
    assert sources["plan_freshness"]["state"] == "current"
    assert client.get("/api/plan").json()["path"] == str(webui.DEMO_SHOW_DIR / "plan.json")

    # Watch: the demo's watch.json.
    assert client.get("/api/watch-conditions").json()["path"] == str(webui.DEMO_SHOW_DIR / "watch.json")

    # Apply: the pre-flight is the dry view, and it is clean.
    pre = client.get("/api/apply/preflight").json()
    assert pre["errors"] == 0 and pre["checked_input_list"] is True
    assert pre["plan_freshness"]["state"] == "current"


def test_the_first_paint_carries_the_demo_show(client):
    _demo(client)
    html = client.get("/").text
    blob = html.index('id="initial-shell"')
    startup = json.loads(html[html.index(">", blob) + 1:html.index("</script>", blob)])
    assert startup["bundle"]["demo"] is True and startup["console"]["demo"] is True
    assert startup["build"]["read_only"] is True


def test_ui_started_on_the_demo_show_is_demo(home):
    app = create_app(initial_bundle=str(webui.DEMO_SHOW_DIR), initial_console=dict(DESK))
    with fastapi_testclient.TestClient(app) as c:
        assert c.get("/api/console").json()["demo"] is True
        # ...and an address leaves it, to no show at all.
        out = c.post("/api/console", json={"address": "198.51.100.7"}).json()
        assert out["bundle"] is None and out["bundle_changed"] is True


# ---- Leaving Demo ------------------------------------------------------------

def test_an_address_leaves_demo_and_reopens_the_show_before_it(client, show):
    _demo(client)
    out = client.post("/api/console", json={"address": "198.51.100.7"}).json()
    assert "demo" not in out and out["address"] == "198.51.100.7"
    assert out["bundle_changed"] is True
    assert out["bundle"]["directory"] == str(show) and out["bundle"]["demo"] is False
    assert client.get("/api/build/sources").json()["read_only"] is False


def test_an_address_with_no_show_before_demo_leaves_none_open(home):
    with fastapi_testclient.TestClient(create_app()) as c:
        _demo(c)
        out = c.post("/api/console", json={"address": "198.51.100.7"}).json()
        assert out["bundle"] is None
        assert c.get("/api/bundle").status_code == 404


@pytest.mark.parametrize("create", [False, True])
def test_opening_or_creating_another_show_leaves_demo(client, home, create):
    _demo(client)
    target = home / "shows" / ("new-show" if create else "other")
    if not create:
        target.mkdir(parents=True)
    r = client.post("/api/bundle/open", json={"directory": str(target), "create": create})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["demo"] is False
    # The console Demo replaced comes back, provenance and all.
    assert body["console"]["address"] == DESK["address"]
    assert "demo" not in body["console"]
    assert client.get("/api/console").json() == body["console"]


def test_leaving_demo_stops_a_demo_watch(client):
    _demo(client)
    assert client.post("/api/watch/start", json={"interval": 5.0}).json()["running"] is True
    client.post("/api/console", json={"address": "198.51.100.7"})
    assert client.get("/api/status").json()["running"] is False


def test_the_demo_folder_is_not_opened_as_an_ordinary_show(client):
    r = client.post("/api/bundle/open", json={"directory": str(webui.DEMO_SHOW_DIR)})
    assert r.status_code == 400 and r.json()["demo"] is True
    assert "choose Demo" in r.json()["error"]


def test_there_is_no_demo_watch_on_a_regular_show(client):
    """An earlier change removed `source: "demo"`: Demo is the demo show."""
    r = client.post("/api/watch/start", json={"source": "demo"})
    assert r.status_code == 400
    assert client.get("/api/status").json()["running"] is False


# ---- Immutable ---------------------------------------------------------------

def _writes(home):
    demo_show = str(webui.DEMO_SHOW_DIR)
    return [
        ("/api/build/sections/save", {"slot": "instructions", "text": "x",
                                      "expected_bundle": demo_show}),
        ("/api/build/sections/save", {"slot": "conventions", "text": "x",
                                      "house_confirmed": True, "expected_bundle": demo_show}),
        ("/api/build/input-list/save", {"rows": [], "expected_bundle": demo_show}),
        ("/api/build/sources/load", {"slot": "input_list", "path": str(home / "x.csv")}),
        ("/api/build/conventions/new", {"path": str(home / "house.md")}),
        ("/api/build/instructions/new", {"expected_bundle": demo_show}),
        ("/api/bundle/adopt", {"slot": "input_list", "path": str(home / "x.csv"),
                               "expected_bundle": demo_show}),
        ("/api/bundle/adopt", {"slot": "watch", "path": str(home / "w.json"),
                               "expected_bundle": demo_show}),
        ("/api/build/run", {"console_model": "wing-compact", "expected_bundle": demo_show}),
        ("/api/watch-conditions/save", {"watch_conditions": []}),
        ("/api/watch-conditions/new", {"expected_bundle": demo_show}),
        ("/api/watch-conditions/load", {"path": str(home / "w.json")}),
        ("/api/plan/load", {"path": str(home / "p.json")}),
        ("/api/patch/promote", {"ref": "x", "confirm": True}),
    ]


def test_every_write_endpoint_refuses_the_demo_show(client, home):
    (home / "x.csv").write_text("socket,name\nLCL 1,Kick\n")
    (home / "w.json").write_text('{"watch_conditions": []}')
    before = _fingerprint()
    _demo(client)
    for url, body in _writes(home):
        r = client.post(url, json=body)
        assert r.status_code == 403, (url, r.status_code, r.text)
        assert r.json()["demo"] is True, url
        assert "the demo show is read-only" in r.json()["error"], url
    assert _fingerprint() == before
    assert not (home / "house.md").exists()


def test_apply_previews_against_the_rig_and_never_writes(client):
    """The Demo previews a Full build against its simulated
    WING -- the real command, on a copy of the show -- and a write, armed
    or not, is refused before anything starts. The package is untouched."""
    import time

    before = _fingerprint()
    _demo(client)
    r = client.post("/api/apply/run", json={"confirm": True, "arm": True,
                                            "expected_bundle": str(webui.DEMO_SHOW_DIR)})
    assert r.status_code == 403 and r.json()["demo"] is True, r.text
    assert "Writing is switched off in the Demo show" in r.json()["error"]
    assert client.get("/api/apply/status").json()["state"] == "idle"
    r = client.post("/api/apply/run", json={"confirm": False, "arm": False})
    assert r.status_code == 200, r.text
    assert r.json()["on"] == "the Demo's simulated WING" and r.json()["preview"] is True
    assert "--confirm" not in r.json()["command"]
    for _ in range(240):
        status = client.get("/api/apply/status").json()
        if status["state"] != "running":
            break
        time.sleep(0.25)
    assert status["state"] == "done" and status["exit_code"] == 0, status["log"][-5:]
    result = status["result"]
    assert result["dry_run"] is True and result["counts"]["total"] > 1000
    assert result["counts"]["unreadable"] == 0
    kinds = [s["kind"] for s in result["drawing"]["sections"]]
    assert kinds == ["ch", "aux", "bus", "main", "mtx", "dca", "mgrp"]
    assert _fingerprint() == before


@pytest.mark.parametrize("url, body", [
    ("/api/watch-conditions/save", {"path": "demo-show/watch.json", "watch_conditions": []}),
    ("/api/build/sources/load", {"slot": "conventions", "path": "conventions.md"}),
    ("/api/config/conventions-default", {"path": "conventions.md"}),
    ("/api/fs/mkdir", {"path": "demo-show/journals"}),
])
def test_a_demo_file_is_refused_from_a_regular_show_too(client, home, url, body):
    """The guard is the path, not only which show is open: no other show
    can point a tile, a Save or a config default at a packaged file."""
    body = dict(body, path=str(webui.DEMO_ROOT / body["path"]))
    before = _fingerprint()
    r = client.post(url, json=body)
    assert r.status_code == 403, r.text
    assert _fingerprint() == before
    assert not (home / ".atoo.config").exists()


def test_new_folder_elsewhere_still_works_from_the_demo(client, home):
    _demo(client)
    r = client.post("/api/fs/mkdir", json={"path": str(home / "next-show")})
    assert r.status_code == 200, r.text


# ---- The plan and the watch list ---------------------------------------------

#: What verify may still say about the packaged plan: nothing above a note.
#: The starter presets ship in `starter/presets/`, so the plan
#: carries every named preset's values and `preset.no-library` is gone.
def _allowed_warnings() -> set:
    return set()


def _verify_packaged(**kwargs):
    from atoo import instructed_channels
    plan = json.loads((PACKAGED_SHOW / "plan.json").read_text())
    rows = load_input_list(str(PACKAGED_SHOW / "input.csv"))
    layers = instructed_channels.layers_from_plan(plan, PACKAGED_SHOW,
                                                  PACKAGED_SHOW / "instructions.md")
    return plan, verify_plan(plan, rows, console_model="wing-compact", layers=layers, **kwargs)


def test_the_demo_plan_verifies_against_its_own_input_list():
    plan, result = _verify_packaged()
    assert result.errors == [], result.report()
    assert {f.code for f in result.warnings} <= _allowed_warnings(), result.report()
    assert plan["meta"]["console_model"] == "wing-compact"
    # A packaged plan names no scratch folder it was built in.
    assert "/tmp" not in (PACKAGED_SHOW / "plan.json").read_text()


def test_the_demo_plan_expands_its_presets_once_they_are_packaged():
    """The conventions name one preset per source,
    and the maintainer's own set is packaged, so the Demo is built against
    it and every named preset carries its values."""
    assert any((PACKAGED_ROOT / "presets").glob("*.chn"))
    plan = json.loads((PACKAGED_SHOW / "plan.json").read_text())
    named = [c for c in plan["channels"] if (c.get("processing") or {}).get("preset")]
    assert len(named) >= 10
    expanded = [c for c in named if c["processing"].get("preset_values")]
    assert expanded == named
    # Every name the plan uses is one the packaged library answers to.
    library = PresetLibrary(PACKAGED_ROOT / "presets")
    for channel in named:
        assert library.matches(channel["processing"]["preset"]), channel["name"]


def test_the_starter_and_demo_conventions_are_one_file():
    """The Demo show is built from the starter
    conventions a newcomer gets, and reads the very same file -- there is
    one copy, in the starter set."""
    from atoo import firstrun
    assert PACKAGED_ROOT == firstrun.STARTER_DIR
    assert PACKAGED_SHOW == firstrun.STARTER_DIR / firstrun.DEMO_SHOW_NAME
    assert PACKAGED_CONVENTIONS == firstrun.STARTER_DIR / "conventions.md"
    assert PACKAGED_PRESETS == firstrun.STARTER_DIR / firstrun.PRESETS_NAME


def test_the_page_checks_the_demo_against_its_own_presets_not_yours(client, home, tmp_path):
    """A user's library that lacks the Demo's preset names would call
    every one of them unknown. While the Demo is open, the page checks it
    against the Demo's own library instead."""
    library = tmp_path / "mine"
    library.mkdir()
    doc = json.loads((Path(__file__).parent / "fixtures" / "presets" / "Kick.chn").read_text())
    doc["info_text"] = "Not A Demo Preset"
    (library / "mine.chn").write_text(json.dumps(doc))
    (home / ".atoo.config").write_text(f'[presets]\ndefault = "{library}"\n')
    _demo(client)
    plan = client.get("/api/plan").json()
    codes = {f.get("code") for f in plan["findings"]}
    assert "preset.unknown" not in codes and "preset.no-library" not in codes
    assert "preset.expanded" in codes


def test_the_demo_plan_and_the_rig_line_up():
    """The names the show and the Demo rig share by design: a channel per
    input-list row on the same socket, and the busses, Main, DCA and mute
    group the watch.json names."""
    plan = json.loads((PACKAGED_SHOW / "plan.json").read_text())
    rig = webui._load_demo_base()
    for channel in plan["channels"]:
        strip = f"/{channel.get('bank', 'ch')}/{channel['channel']}"
        assert rig[f"{strip}/name"] == channel["name"]
        patch = channel["patch"]
        group = {"AES50-A": "A"}.get(patch["group"], patch["group"])
        assert (rig[f"{strip}/in/conn/grp"], rig[f"{strip}/in/conn/in"]) == \
            (group, patch["sockets"][0])
        assert rig[f"{strip}/fdr"] == channel["fader"]["fader_db"]
    for name, bus in plan["busses"].items():
        assert rig[f"/bus/{bus['index']}/name"] == name
    for name, dca in plan["dcas"].items():
        assert rig[f"/dca/{dca['index']}/name"] == name
    for name, group in plan["mute_groups"].items():
        assert rig[f"/mgrp/{group['index']}/name"] == name
    [(main_name, main)] = [(k, v) for k, v in plan["outputs"].items() if v["kind"] == "main"]
    assert rig[f"/main/{main['index']}/name"] == main_name


def _demo_rules():
    """What Watch runs on the Demo: the built-in rules, the show's
    watch.json, bound to its plan (`audit.with_plan_rules`: L002 quiet
    on a fader the plan puts at the floor; the rule its plan
    adds for its FX bus)."""
    from atoo.audit import with_plan_rules

    text = (PACKAGED_SHOW / "watch.json").read_text()
    return with_plan_rules(
        DEFAULT_RULES + build_watch_rules(parse_watch_conditions(text, source="watch.json")),
        PACKAGED_SHOW / "plan.json")


def _watch_ids(values: dict) -> set:
    return {f.rule_id for f in run_audit(ConsoleState(values), _demo_rules())
            if f.rule_id.startswith("WATCH:") and f.severity.value != "info"}


def test_the_clean_rig_trips_no_watch_condition():
    assert _watch_ids(webui._load_demo_base()) == set()


def test_the_clean_rig_is_quiet_and_each_fault_is_heard():
    """The rig as applied trips no built-in warning or error, so every row
    Watch shows on the Demo is one of `_DEMO_ISSUES`; and each issue, armed
    alone, adds at least one finding above info, or a watch condition."""
    def loud(values):
        return [f.rule_id for f in run_audit(ConsoleState(values), _demo_rules())
                if f.severity.value != "info"]
    base = webui._load_demo_base()
    assert loud(base) == []
    for name, overrides in webui._DEMO_ISSUES.items():
        # By rule and severity: a watch condition named by kind and name
        # (`BUS Drums`) announces itself at INFO on every reading, so its
        # rule id is in the clean rig's set too.
        found = {(f.rule_id, f.severity.value)
                 for f in run_audit(ConsoleState({**base, **overrides}), _demo_rules())}
        assert found - {(f.rule_id, f.severity.value)
                        for f in run_audit(ConsoleState(base), _demo_rules())}, name


def test_the_6pm_change_applies_cleanly_to_the_demo_rig(tmp_path, capsys):
    """The change the Demo leads with, "trumpet, sax and trombone on LCL
    21-23, Band DCA", reviewed with `patch` against the Demo rig: its
    change set (frozen in tests/fixtures, as `--save-change-set` writes
    one) places three new channels on free strips, each with its starter
    preset, adds the Horns mix bus with the "Mix Bus" preset (the maintainer,
    test 13, 2026-10-12), and the pre-flight passes. No model and no
    desk: `--change-set` and `--state`."""
    from atoo import cli
    show = tmp_path / "show"
    shutil.copytree(PACKAGED_SHOW, show)
    rig = {k: v for k, v in webui._load_demo_base().items() if not k.startswith("_")}
    state = tmp_path / "rig.json"
    state.write_text(json.dumps(rig))
    review = tmp_path / "review.json"
    change_set = Path(__file__).parent / "fixtures" / "demo-horns.change-set.json"
    code = cli.main(["patch", "--show", str(show), "--state", str(state),
                     "--change-set", str(change_set), "--review-json", str(review),
                     "--presets", str(PACKAGED_ROOT / "presets"),
                     "--conventions", str(PACKAGED_ROOT / "conventions.md")])
    out = capsys.readouterr()
    text = out.out + out.err
    assert code == 0, text
    for name, strip, preset in (("Trumpet", 14, "Trumpet"), ("Sax", 15, "A Sax"),
                                ("Trombone", 16, "T Bone")):
        assert f"ADDED            channel '{name}' -> ch:{strip}" in text
        assert f"channel '{name}': the preset '{preset}' ({preset}.chn) puts" in text
    assert "ADDED            bus 'Horns'" in text
    assert "Horns: 'Mix Bus'" in text
    # The pre-flight reads the Demo's input list, so it has nothing to
    # warn about either.
    assert "of the changed plan against the WING Compact" in text
    assert "no findings." in text and "UNPLACEABLE" not in text
    assert "reconcile.not-checked" not in text
    assert "carries none of its values" not in text
    # The Horns bus's compressor is among the writes, and nothing loads an effect.
    written = [w["description"] for w in json.loads(review.read_text())["to_write"]]
    assert any("(Horns): preset Mix Bus dyn/on" in w for w in written)
    assert not [w for w in written if "FX" in w and "Horns" in w]


def _patch_the_demo_copy(tmp_path, monkeypatch, *, strip_presets: bool = False):
    """The 6pm change on a copy of the Demo show, as the maintainer ran it
    at the desk: no `--presets`, no `[presets] default`, and
    run from somewhere `starter/presets` -- the path the plan records --
    does not resolve. Returns `(exit code, stdout, stderr, review)`."""
    from atoo import cli
    show = tmp_path / "demo-show"
    shutil.copytree(PACKAGED_SHOW, show)
    if strip_presets:
        plan = json.loads((show / "plan.json").read_text())
        for channel in plan["channels"]:
            channel["processing"].pop("preset_values", None)
        for bus in plan["busses"].values():
            bus.pop("preset_values", None)
        (show / "plan.json").write_text(json.dumps(plan))
    rig = {k: v for k, v in webui._load_demo_base().items() if not k.startswith("_")}
    state = tmp_path / "rig.json"
    state.write_text(json.dumps(rig))
    review = tmp_path / "review.json"
    monkeypatch.setattr(cli, "load_default_presets", lambda: None)
    monkeypatch.chdir(tmp_path)
    code = cli.main(["patch", "--show", str(show), "--state", str(state),
                     "--change-set", str(Path(__file__).parent / "fixtures"
                                         / "demo-horns.change-set.json"),
                     "--review-json", str(review),
                     "--conventions", str(PACKAGED_ROOT / "conventions.md")])
    return code, review


def test_patch_with_no_flag_finds_the_demos_starter_presets(tmp_path, monkeypatch, capsys):
    """The library the show was built with, found
    without `--presets`, and said at INFO."""
    code, review = _patch_the_demo_copy(tmp_path, monkeypatch)
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    assert "every preset file it records is in the packaged starter presets" in out.out
    for name, preset in (("Trumpet", "Trumpet"), ("Sax", "A Sax"), ("Trombone", "T Bone")):
        assert f"channel '{name}': the preset '{preset}' ({preset}.chn) puts" in out.out
    assert "Horns: 'Mix Bus'" in out.out
    assert "carries none of its values" not in out.out + out.err
    payload = json.loads(review.read_text())
    assert payload["preset_warning"] is None
    assert any(i.startswith("preset library: ") for i in payload["infos"])
    written = [w["description"] for w in payload["to_write"]]
    assert any("(Horns): preset Mix Bus dyn/on" in w for w in written)


def test_patch_with_no_library_at_all_warns_up_top(tmp_path, monkeypatch, capsys):
    """A change naming presets, with no library to take
    their values from, says so before the review -- a WARNING (the strips
    still pass audio), not only the trailing `preset.no-library`."""
    code, review = _patch_the_demo_copy(tmp_path, monkeypatch, strip_presets=True)
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    warning = [line for line in out.err.splitlines() if line.startswith("WARNING: no preset library")]
    assert warning and "(Trumpet, A Sax, T Bone, Mix Bus)" in warning[0]
    assert json.loads(review.read_text())["preset_warning"].startswith("no preset library")


def test_the_patch_page_runs_the_6pm_change_set_the_tests_run():
    """`docs/user/patch.md`'s transcript runs the copy under docs/user/demo/;
    it is the frozen fixture, so the page and the test above say the same."""
    docs = Path(__file__).parent.parent / "docs" / "user" / "demo" / "demo-show"
    fixture = Path(__file__).parent / "fixtures" / "demo-horns.change-set.json"
    assert (docs / "horns.change-set.json").read_text() == fixture.read_text()


def test_the_demo_plan_adds_its_fx_bus_rule_and_the_rig_satisfies_it():
    """The Vox Verb bus's V-REV on FX5, inserted and on. Clean,
    the rig is quiet; bypassed, CV015 warns."""
    from atoo.audit import plan_watch_rules

    (rule,) = [r for r in plan_watch_rules(PACKAGED_SHOW / "plan.json") if r.id == "CV015"]
    base = webui._load_demo_base()
    assert rule.check(ConsoleState(base)) == []
    found = rule.check(ConsoleState({**base, **webui._DEMO_ISSUES["vox_verb_bypassed"]}))
    assert [f.severity.value for f in found] == ["warning"]
    assert "switched off" in found[0].message


def test_the_clean_demo_rig_lists_no_fader_the_plan_put_at_the_floor():
    """The Demo's conventions start every channel fader at the
    floor, and Watch opened with one L002 row per channel. Bound to the
    plan it lists none; the Drums bus pulled down (the plan puts it at
    unity) is still said."""
    def l002(values):
        return sorted(f.addresses[0] for f in run_audit(ConsoleState(values), _demo_rules())
                      if f.rule_id == "L002")

    base = dict(webui._load_demo_base())
    assert l002(base) == []
    assert l002({**base, **webui._DEMO_ISSUES["fader_at_floor"]}) == ["/bus/5/fdr"]


def test_the_demo_watch_opens_with_no_sp_l002_row(home):
    """The same, through `/api/watch/start` on the Demo show: the page's
    own Watch binds the rules to the open show's plan."""
    app = create_app(initial_bundle=str(webui.DEMO_SHOW_DIR), initial_console=dict(DESK))
    with fastapi_testclient.TestClient(app) as c:
        assert c.post("/api/watch/start", json={"source": "console", "interval": 0.1}
                      ).status_code == 200
        with c.websocket_connect("/ws/watch") as ws:
            event = ws.receive_json()
            while event.get("type") != "event":
                event = ws.receive_json()
        c.post("/api/watch/stop")
    assert event["baseline"] is True
    assert [f for f in event["all_findings"] if f["rule_id"] == "L002"] == []


@pytest.mark.parametrize("issue, condition", [
    ("dca_closed", "WATCH:band-dca-open"),
    ("fader_at_floor", "WATCH:mix-bus-fader-low"),
    ("lead_vox_muted", "WATCH:lead-vox-unmuted"),
])
def test_a_seeded_fault_trips_a_demo_watch_condition(issue, condition):
    values = dict(webui._load_demo_base())
    values.update(webui._DEMO_ISSUES[issue])
    assert condition in _watch_ids(values)


def test_the_demos_range_conditions_name_each_strip_that_breaks_them():
    """The Demo watches every DCA and every mix and FX bus with one
    condition on a range apiece. Each strip that breaks one is its own
    finding, citing the strip by number and by its name on the desk."""
    values = dict(webui._load_demo_base())
    values.update(webui._DEMO_ISSUES["dca_closed"])
    values.update({"/bus/6/mute": 1, "/bus/7/mute": 1})
    findings = {f.rule_id: [] for f in run_audit(ConsoleState(values), _demo_rules())}
    for f in run_audit(ConsoleState(values), _demo_rules()):
        findings[f.rule_id].append(f.message)
    assert any('DCA 2 "Band"' in m for m in findings["WATCH:dca-fader-low"])
    muted = findings["WATCH:mix-bus-muted"]
    assert any('BUS 6 "Vocals"' in m for m in muted)
    assert any('BUS 7 "Vox Verb"' in m for m in muted)
    # One condition, so one rule id: not a condition per bus.
    text = (PACKAGED_SHOW / "watch.json").read_text()
    channels = [c["channel"] for c in json.loads(text)["watch_conditions"]]
    assert {"DCA 1-5", "BUS 5-7"} <= set(channels)


def test_watch_on_the_demo_show_fires_its_conditions(client, monkeypatch):
    """End to end: Demo, then Watch with the bundle's watch.json, as the
    page starts it. The rig's faults are random, so the factory here arms
    `dca_closed` on the second reading."""
    from atoo.audit import ConsoleState as State

    def factory(rng=None):
        base = webui._load_demo_base()
        readings = iter([base, {**base, **webui._DEMO_ISSUES["dca_closed"]}])
        last = {"v": base}

        def provider():
            last["v"] = next(readings, last["v"])
            return State(dict(last["v"]))
        return provider, None

    monkeypatch.setattr(webui, "demo_provider_factory", factory)
    _demo(client)
    path = client.get("/api/watch-conditions").json()["path"]
    r = client.post("/api/watch/start", json={"source": "console", "interval": 0.05,
                                              "watch_conditions_path": path})
    assert r.status_code == 200 and r.json()["label"] == "Demo"
    try:
        with client.websocket_connect("/ws/watch") as ws:
            fired = None
            for _ in range(60):
                payload = ws.receive_json()
                new = [f["rule_id"] for f in payload.get("new_findings", [])]
                if "WATCH:band-dca-open" in new:
                    fired = payload
                    break
            assert fired is not None
    finally:
        client.post("/api/watch/stop")


def test_watch_on_the_demo_show_warns_when_its_fx_bus_is_bypassed(client, monkeypatch):
    """An earlier change, end to end: Watch on the Demo adds CV015 from the
    show's plan, and the Vox Verb bus switched off is a new WARNING."""
    from atoo.audit import ConsoleState as State

    def factory(rng=None):
        base = webui._load_demo_base()
        readings = iter([base, {**base, **webui._DEMO_ISSUES["vox_verb_bypassed"]}])
        last = {"v": base}

        def provider():
            last["v"] = next(readings, last["v"])
            return State(dict(last["v"]))
        return provider, None

    monkeypatch.setattr(webui, "demo_provider_factory", factory)
    _demo(client)
    r = client.post("/api/watch/start", json={"source": "console", "interval": 0.05})
    assert r.status_code == 200
    try:
        with client.websocket_connect("/ws/watch") as ws:
            fired = None
            for _ in range(60):
                payload = ws.receive_json()
                new = {f["rule_id"]: f for f in payload.get("new_findings", [])}
                if "CV015" in new:
                    fired = new["CV015"]
                    break
            assert fired is not None and fired["severity"] == "warning"
    finally:
        client.post("/api/watch/stop")


# ---- The page, as served assets (the suite cannot see the JS) ----

def test_the_page_draws_the_demo_show_read_only(client):
    html = client.get("/").text
    # The notice under the bar became a popup, shown once, and
    # a chip in the bar that opens it again.
    assert 'id="bundle-readonly"' in html and 'id="demo-notice"' not in html
    assert 'id="demo-chip" data-popup="demo-popup"' in html and 'id="demo-popup"' in html
    shell = client.get("/static/shell.js").text
    # The console reply carries the bundle, and the page redraws from it.
    for needle in ("data.bundle_changed", "delete data.bundle;", "is-demo-show",
                   "function isDemoShow()", "bundle.demo", "DEMO_LOCKED",
                   "const desk = data.console;"):
        assert needle in shell, needle
    # Nothing on the demo show is editable.
    assert "!stale && !isDemoShow()" in shell
    css = client.get("/static/styles.css").text
    assert "body.is-demo-show" in css and ".demo-notice" not in css
    # "Demo · what's this?" is a quiet button beside a neutral
    # Read-only state, not a yellow chip.
    assert 'class="btn btn-quiet" id="demo-chip"' in html
    assert '<span class="state" id="bundle-readonly" hidden>Read-only</span>' in html
    # The DEMO_LOCKED list and the stylesheet name the same write controls.
    for control in ("#run-build-btn", "#wc-save-btn",
                    "#apply-arm-checkbox", "#input-save-btn", "#change-input-list"):
        assert f'"{control}"' in shell and control in css, control
    # Preview is not locked in the Demo -- it reads the rig.
    assert '"#apply-preview-btn"' not in shell and "#apply-preview-btn" not in css
    assert "that is off here" not in shell and "sayDemoReadOnly" not in shell
    watch = client.get("/static/watch.js").text
    assert 'source: "console"' in watch and 'desk.demo ? "demo"' not in watch


def test_the_demo_plan_records_no_absolute_path():
    """The packaged plan names its inputs repository-relative: a model
    rebuild on a maintainer's machine recorded his home folder (2026-10-13)."""
    text = (PACKAGED_SHOW / "plan.json").read_text()
    plan = json.loads(text)

    def strings(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
        elif isinstance(node, str):
            yield node

    # A value that IS a path, not a quoted conventions line that happens
    # to hold `"OH L"/"OH R"` (meta.change_basis).
    assert not [s for s in strings(plan) if s.startswith("/")]
    assert "build_log_file" not in plan["meta"]
