"""



    The `watch.json` file always needs to go with the current bundle. Make
    its file handling consistent with the way we handle other files: file
    change / new / save and if we change to a new file or create a new
    one, it goes into the bundle.

    Set where we choose a demo console on the same dialog as where we
    choose the IP address. Just call it 'Demo' and be sure the IP address
    area in the status header reflects this. (no need to repeat the IP
    address)

    Be sure the watch.json box has a section title consistent with the
    rest of the UI.

So, tested here:

* **Watch's file is a bundle file.** `POST /api/bundle/adopt` takes slot
  `watch` and copies a file from outside into the bundle as `watch.json`
  -- the same copy, `.bak` and INFO as `input.csv` and `instructions.md`,
  and a file Watch could not load is refused before anything is copied.
  `POST /api/watch-conditions/new` makes an empty one there, never over
  one. Save with no path writes the bundle's. With no bundle open, a file
  is used where it is, and New/Save-with-no-path say why they cannot.
* **Demo is a console.** `POST /api/console {"demo": true}`: no address,
  so Ping and every write refuse it; Watch started on the bar's console
  runs the demo rig under the label "Demo". It opens the
  demo show too -- `tests/test_demo_show.py` covers that.
* **The page**, as served assets: the Demo choice in the bar's editor, the
  section title on the watch-conditions box, and watch.js reaching the
  shell's own copy-in flow rather than a second one.

Every bundle here is built in `tmp_path`; nothing under `examples/` is read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402

LOCAL = dict(client=("127.0.0.1", 50123), base_url="http://127.0.0.1:8420")

COND = {"id": "kick-muted", "description": "Kick muted", "channel": "Kick",
        "field": "muted", "operator": "==", "value": True, "severity": "warning"}
OTHER = dict(COND, id="vox-muted", channel="Lead Vox")


def _doc(*conds) -> str:
    return json.dumps({"watch_conditions": list(conds)}, indent=2) + "\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    (home / "rules").mkdir()
    (home / "rules" / "kick.json").write_text(_doc(COND))
    (home / "rules" / "vox.json").write_text(_doc(OTHER))
    (home / "rules" / "broken.json").write_text('{"watch_conditions": [{"id": "x"}]}')
    return home


@pytest.fixture
def show(home):
    show = home / "shows" / "festival"
    show.mkdir(parents=True)
    return show


@pytest.fixture
def client(show):
    app = create_app(initial_bundle=str(show),
                     initial_console={"address": "203.0.113.50", "port": 2223,
                                      "address_source": "~/.atoo.config [console]"})
    with fastapi_testclient.TestClient(app, **LOCAL) as c:
        c.app_state = app.state
        yield c


def _adopt(c, show, path, **extra):
    return c.post("/api/bundle/adopt", json={"slot": "watch", "path": str(path),
                                             "expected_bundle": str(show), **extra})


# ---- Change file: copied into the bundle ------------------------------------

def test_a_watch_file_from_elsewhere_is_copied_into_the_bundle(client, show, home):
    r = _adopt(client, show, home / "rules" / "kick.json")
    assert r.status_code == 200, r.text
    data = r.json()
    assert (show / "watch.json").read_text() == _doc(COND)
    assert data["copied"] is True
    assert data["message"] == ("Copied ~/rules/kick.json into festival/watch.json -- the "
                               "bundle now owns its copy; edits to the original won't "
                               "reach it.")
    # Watch now uses the bundle's copy, and says so in GET's own shape.
    assert data["path"] == str(show / "watch.json")
    assert [c["id"] for c in data["watch_conditions"]] == ["kick-muted"]
    assert data["bundle_file"] == {"path": str(show / "watch.json"),
                                   "display_path": "festival/watch.json", "present": True}
    assert client.get("/api/watch-conditions").json()["path"] == str(show / "watch.json")
    # The same provenance INFO as Build's copies.
    assert data["finding"]["severity"] == "info"
    assert data["finding"]["code"] == "bundle.copied-in"
    assert data["finding"]["where"] == "festival/watch.json"


def test_a_bundle_with_a_watch_file_is_asked_and_replace_keeps_a_bak(client, show, home):
    (show / "watch.json").write_text(_doc(OTHER))
    r = _adopt(client, show, home / "rules" / "kick.json")
    assert r.status_code == 409
    body = r.json()
    assert body["error"].startswith("festival already has a watch.json -- replace it with ")
    assert body["exists"]["display_path"] == "festival/watch.json"
    assert (show / "watch.json").read_text() == _doc(OTHER), "a 409 wrote something"

    r = _adopt(client, show, home / "rules" / "kick.json", replace=True)
    assert r.status_code == 200, r.text
    assert (show / "watch.json").read_text() == _doc(COND)
    assert (show / "backups" / "watch.json.bak").read_text() == _doc(OTHER)
    assert r.json()["message"].endswith(
        "The watch.json it replaced was kept as festival/backups/watch.json.bak.")


def test_a_file_watch_could_not_load_is_never_copied_in(client, show, home):
    (show / "watch.json").write_text(_doc(OTHER))
    r = _adopt(client, show, home / "rules" / "broken.json", replace=True)
    assert r.status_code == 400
    assert "nothing was copied into festival/watch.json" in r.json()["error"]
    assert (show / "watch.json").read_text() == _doc(OTHER)
    assert not (show / "backups" / "watch.json.bak").exists()


def test_the_build_slots_keep_their_article(client, show, home):
    """`_a_or_an` replaced a hard-coded "an": input.csv and instructions.md
    still read "an"."""
    (home / "band.csv").write_text("socket,name\nLCL 1,Kick\n")
    (show / "input.csv").write_text("socket,name\nLCL 1,Snare\n")
    r = client.post("/api/bundle/adopt", json={"slot": "input_list",
                                               "path": str(home / "band.csv"),
                                               "expected_bundle": str(show)})
    assert r.status_code == 409
    assert r.json()["error"].startswith("festival already has an input.csv")


# ---- New file and Save -------------------------------------------------------

def test_new_file_makes_an_empty_watch_json_in_the_bundle(client, show):
    r = client.post("/api/watch-conditions/new", json={"expected_bundle": str(show)})
    assert r.status_code == 200, r.text
    data = r.json()
    assert json.loads((show / "watch.json").read_text()) == {"watch_conditions": []}
    assert data["path"] == str(show / "watch.json")
    assert data["watch_conditions"] == []
    assert data["bundle_file"]["present"] is True
    assert data["message"].startswith("Created festival/watch.json, empty")
    # Never over one.
    r = client.post("/api/watch-conditions/new", json={"expected_bundle": str(show)})
    assert r.status_code == 409
    assert "nothing was written" in r.json()["error"]


def test_new_file_from_a_stale_page_writes_nothing(client, show, home):
    r = client.post("/api/watch-conditions/new",
                    json={"expected_bundle": str(home / "shows" / "other")})
    assert r.status_code == 409 and r.json().get("stale") == "bundle"
    assert not (show / "watch.json").exists()


def test_save_with_no_path_writes_the_bundles_watch_json(client, show):
    r = client.post("/api/watch-conditions/save", json={"watch_conditions": [COND]})
    assert r.status_code == 200, r.text
    assert json.loads((show / "watch.json").read_text()) == {"watch_conditions": [COND]}
    assert r.json()["path"] == str(show / "watch.json")


def test_with_no_bundle_a_file_is_used_where_it_is(home):
    """As for Build's input list and instructions: with no bundle there is
    nothing to copy into. Change file loads in place; New file and a
    path-less Save say why they cannot."""
    app = create_app()
    with fastapi_testclient.TestClient(app, **LOCAL) as c:
        assert c.get("/api/watch-conditions").json() == {
            "error": "no watch-conditions file loaded", "bundle_file": None}
        r = c.post("/api/watch-conditions/load", json={"path": str(home / "rules" / "kick.json")})
        assert r.status_code == 200
        assert r.json()["path"] == str(home / "rules" / "kick.json")
        assert r.json()["bundle_file"] is None
        r = c.post("/api/watch-conditions/new", json={})
        assert r.status_code == 400 and "no show bundle open" in r.json()["error"]
        r = c.post("/api/watch-conditions/save", json={"watch_conditions": [COND]})
        assert r.status_code == 400 and "no show bundle open" in r.json()["error"]
        r = c.post("/api/bundle/adopt", json={"slot": "watch",
                                              "path": str(home / "rules" / "kick.json")})
        assert r.status_code == 400 and "no show bundle open" in r.json()["error"]


def test_the_watch_conditions_startup_flag_still_loads(home, show):
    """`atoo ui --watch-conditions FILE` is unchanged: the file is used
    where it is, and Watch's answer still names the bundle's own file so
    the page can offer to bring one in."""
    app = create_app(initial_bundle=str(show),
                     initial_watch_conditions_path=str(home / "rules" / "kick.json"))
    with fastapi_testclient.TestClient(app, **LOCAL) as c:
        data = c.get("/api/watch-conditions").json()
        assert data["path"] == str(home / "rules" / "kick.json")
        assert data["bundle_file"] == {"path": str(show / "watch.json"),
                                       "display_path": "festival/watch.json",
                                       "present": False}


# ---- Demo, in the bar's console editor ---------------------------------------

def test_demo_is_a_console_with_no_address(client):
    r = client.post("/api/console", json={"demo": True})
    assert r.status_code == 200, r.text
    desk = r.json()
    # Choosing Demo opens the demo show too, in the same reply.
    assert desk.pop("bundle_changed") is True and desk.pop("bundle")["demo"] is True
    assert desk["demo"] is True and desk["address"] is None
    assert desk["address_source"] == "set here"
    assert client.get("/api/console").json() == desk
    # The page's first paint carries it too.
    assert '"demo": true' in client.get("/").text

    # Back to an address: Demo is gone.
    r = client.post("/api/console", json={"address": "198.51.100.7"})
    assert r.status_code == 200
    assert "demo" not in r.json() and r.json()["address"] == "198.51.100.7"


def test_ping_refuses_demo_without_pretending(client):
    client.post("/api/console", json={"demo": True})
    r = client.post("/api/ping", json={})
    assert r.status_code == 400
    assert r.json() == {"error": "the console is Demo -- there is no desk to ping",
                        "demo": True}


def test_apply_writes_and_undo_refuse_demo(client, show):
    """The Demo previews (tests/test_demo_show.py), and a write
    or an undo, previewed or armed, is refused before anything starts."""
    (show / "plan.json").write_text("{}")
    client.post("/api/console", json={"demo": True})
    for url, body, code, words in (
            ("/api/apply/run", {"confirm": True, "arm": True}, 403,
             "Writing is switched off in the Demo show"),
            ("/api/patch/run", {"change": "horns", "confirm": True, "arm": True}, 403,
             "Writing is switched off in the Demo show"),
            ("/api/undo/run", {}, 400, "writing and Undo are switched off"),
            ("/api/undo/run", {"confirm": True, "arm": True}, 400,
             "writing and Undo are switched off")):
        r = client.post(url, json=body)
        assert r.status_code == code, (url, r.text)
        assert r.json()["demo"] is True
        assert words in r.json()["error"], (url, r.text)
    assert client.get("/api/apply/status").json()["state"] == "idle"


def test_watch_on_the_bars_console_runs_the_demo_when_the_bar_says_demo(client):
    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={"source": "console", "interval": 5.0})
    assert r.status_code == 200, r.text
    assert r.json()["running"] is True and r.json()["label"] == "Demo"
    client.post("/api/watch/stop")


def test_demo_cannot_be_chosen_while_a_write_runs(client, monkeypatch):
    """The same lock and refusal as an address change: a write never
    switches desks part way through, and Demo is a desk change."""
    runner = client.app_state.apply_run
    monkeypatch.setattr(type(runner), "running", property(lambda self: True))
    monkeypatch.setattr(runner, "kind", "apply", raising=False)
    r = client.post("/api/console", json={"demo": True})
    assert r.status_code == 409
    assert "cannot change until it finishes" in r.json()["error"]
    assert client.get("/api/console").json()["address"] == "203.0.113.50"


# ---- The page, as served -----------------------------------------------------

def test_the_bars_editor_offers_demo_beside_the_address(client):
    page = client.get("/").text
    edit = page[page.index('id="console-bar-edit"'):page.index('id="bundle-message"')]
    assert 'id="console-kind-desk"' in edit and 'id="console-kind-demo"' in edit
    assert ">Demo</button>" in edit and 'role="radiogroup" aria-label="Which console"' in edit
    shell = client.get("/static/shell.js").text
    for marker in ('el("console-kind-demo")', "body = { demo: true };",
                   'const DEMO_LABEL = "Demo";', "consoleDefaults.demo"):
        assert marker in shell, marker
    # The Watch page has no Source picker and no copy of the address.
    watch_panel = page[page.index('id="mode-watch"'):page.index("The findings dock")]
    assert "source-select" not in watch_panel and "watch-console" not in watch_panel
    assert "Demo fixtures" not in page
    apply_js = client.get("/static/apply.js").text
    assert "desk.demo" in apply_js


def test_the_watch_conditions_box_has_a_section_title_like_the_others(client):
    page = client.get("/").text
    panel = page[page.index('id="wc-panel"'):page.index('id="wc-table-wrap"')]
    # An earlier change (ui-style.md §3): the fold's summary is the block header,
    # outside the box.
    assert '<summary class="block-head">' in panel
    assert "<h2>Watch conditions</h2>" in panel
    for element_id in ("wc-file", "wc-change-btn", "wc-new-btn", "wc-save-btn",
                       "wc-dirty-badge"):
        assert f'id="{element_id}"' in panel, element_id
    for gone in ("wc-path", "wc-load-btn", "wc-browse-btn"):
        assert f'id="{gone}"' not in page, gone


def test_watch_js_uses_the_shells_copy_in_flow_and_reads_what_the_server_sends(client, show):
    js = client.get("/static/watch.js").text
    shell = client.get("/static/shell.js").text
    assert 'SP.adoptIntoBundle("watch", result, dialog' in js
    assert "adoptIntoBundle: adoptAsking," in shell
    assert 'watch: "watch.json"' in shell
    for element_id in ("wc-file", "wc-change-btn", "wc-new-btn", "wc-dirty-badge"):
        assert f'el("{element_id}")' in js, element_id
    assert '"/api/watch-conditions/new"' in js
    # Every key watch.js reads off the answer is one the server sends --
    # the silently-blank trap.
    data = client.post("/api/watch-conditions/new", json={"expected_bundle": str(show)}).json()
    for key in ("path", "watch_conditions", "bundle_file", "message"):
        assert key in data and f"data.{key}" in js, key
    for key in ("path", "display_path", "present"):
        assert key in data["bundle_file"] and f"wcBundleFile.{key}" in js, key
