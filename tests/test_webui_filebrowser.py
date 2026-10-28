"""The Setup UI's file browser and copy-into-bundle.

"we need a real modal file browser for
selecting existing files, or creating a new show directory or a new
file." A page cannot see the disk, so the modal asks the server for one
folder at a time: `GET /api/fs/list` and, for New folder,
`POST /api/fs/mkdir` (`atoo/fsbrowse.py`).

"If I create a new show in the UI, and then open an input list from
somewhere, the program should copy the input list into the bundle and
notify the user that it has done so." -- `POST /api/bundle/adopt`, which
does the same for instructions.md (the only instructions file `build`
reads) and refuses the house conventions file, which stays outside the
bundle on purpose.

Three guards are tested beside them:

* **Only this machine's own browser** may list the disk, make a folder,
  copy a chosen file, or have any other endpoint open a path it names
  -- `--host` can put the page on the LAN: a non-loopback
  client, or a Host header that is not a loopback name (DNS rebinding),
  is a 403. The one exception is the watch-conditions file the server
  already holds, which a phone's Watch page sends back on Start and Save.
* **No other web page** may write here: a POST whose Origin is not the
  page's own, or whose Sec-Fetch-Site says cross-site, is a 403 -- on
  every write endpoint, not only the new ones.
* **A stale page** (FR-6.11) may not copy into, or create instructions in,
  a bundle it is not showing.

Every bundle here is built in `tmp_path`; nothing under `examples/` is read.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import fsbrowse  # noqa: E402
from atoo.webui import create_app  # noqa: E402

LOCAL = dict(client=("127.0.0.1", 50123), base_url="http://127.0.0.1:8420")

INPUT_CSV = ("socket,name,category,type,model,phantom,notes\n"
             "LCL 1,Kick,drums,Mic,,FALSE,\nLCL 2,Lead Vox,vocals,Mic,,TRUE,lead\n")
OTHER_CSV = INPUT_CSV + "LCL 3,Bass,bass,DI,,FALSE,\n"
INSTRUCTIONS = "## Channels\nKeys are the one stereo pair.\n"
HOUSE = "# House\n\n## Channels\nDrums first.\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    return home


def _local(app):
    return fastapi_testclient.TestClient(app, **LOCAL)


@pytest.fixture
def tree(home):
    """A small home folder: two folders, a hidden one, files of three kinds,
    a link to a folder and a link to nothing."""
    (home / "shows").mkdir()
    (home / "shows" / "festival").mkdir()
    (home / "shows" / "festival" / "input.csv").write_text(INPUT_CSV)
    (home / "lists").mkdir()
    (home / ".config").mkdir()
    (home / "Zeta.csv").write_text(INPUT_CSV)
    (home / "alpha.csv").write_text(INPUT_CSV)
    (home / "notes.md").write_text(INSTRUCTIONS)
    (home / "plan.json").write_text("{}")
    (home / ".hidden.csv").write_text(INPUT_CSV)
    os.symlink(home / "shows", home / "shows-link")
    os.symlink(home / "gone", home / "dangling")
    return home


@pytest.fixture
def client(home):
    with _local(create_app()) as c:
        yield c


def _names(data):
    return [e["name"] for e in data["entries"]]


# ---- GET /api/fs/list ---------------------------------------------------

def test_a_listing_is_folders_first_then_the_files_the_dialog_opens(client, tree):
    r = client.get("/api/fs/list", params={"path": str(tree), "kind": "csv"})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == str(tree)
    assert data["display_path"] == "~"
    # Folders (the link to one included) before the broken link, before
    # files; names case-insensitively.
    assert _names(data) == ["lists", "shows", "shows-link", "dangling", "alpha.csv", "Zeta.csv"]
    # The .md and .json files are counted, not listed.
    assert data["other_files"] == 2
    assert data["hidden_count"] == 2
    assert data["parent"] == str(tree.parent)
    assert data["sep"] == os.sep


def test_each_kind_offers_its_own_files(client, tree):
    def files(kind):
        data = client.get("/api/fs/list", params={"path": str(tree), "kind": kind}).json()
        return [e["name"] for e in data["entries"] if e["type"] == "file"]

    assert files("md") == ["notes.md"]
    assert files("json") == ["plan.json"]
    assert files("folders") == []
    assert files("any") == ["alpha.csv", "notes.md", "plan.json", "Zeta.csv"]


def test_a_listing_names_but_never_reads(client, tree):
    data = client.get("/api/fs/list", params={"path": str(tree), "kind": "any"}).json()
    alpha = next(e for e in data["entries"] if e["name"] == "alpha.csv")
    assert alpha["size"] == len(INPUT_CSV)
    assert isinstance(alpha["mtime"], float)
    assert set(alpha) <= {"name", "path", "hidden", "symlink", "type", "size", "mtime",
                          "matches", "target", "bundle"}
    assert "Kick" not in str(data)


def test_hidden_entries_are_hidden_until_asked_for(client, tree):
    shown = client.get("/api/fs/list", params={"path": str(tree), "kind": "csv",
                                               "hidden": "true"}).json()
    assert ".config" in _names(shown) and ".hidden.csv" in _names(shown)
    assert shown["hidden_count"] == 0
    hidden = client.get("/api/fs/list", params={"path": str(tree), "kind": "csv"}).json()
    assert ".config" not in _names(hidden)


def test_symlinks_are_shown_resolved_and_a_broken_one_is_not_an_error(client, tree):
    data = client.get("/api/fs/list", params={"path": str(tree), "kind": "csv"}).json()
    link = next(e for e in data["entries"] if e["name"] == "shows-link")
    assert link["symlink"] is True and link["type"] == "dir"
    assert link["target"] == str((tree / "shows").resolve())
    broken = next(e for e in data["entries"] if e["name"] == "dangling")
    assert broken["symlink"] is True and broken["type"] == "broken"
    # And a folder reached through the link keeps the name it was opened by.
    inside = client.get("/api/fs/list", params={"path": str(tree / "shows-link")}).json()
    assert inside["path"] == str(tree / "shows-link")
    assert _names(inside) == ["festival"]


def test_a_folder_that_holds_a_bundle_is_marked_when_choosing_one(client, tree):
    data = client.get("/api/fs/list", params={"path": str(tree / "shows"),
                                              "kind": "folders"}).json()
    assert data["entries"][0]["bundle"] is True
    empty = client.get("/api/fs/list", params={"path": str(tree), "kind": "folders"}).json()
    assert next(e for e in empty["entries"] if e["name"] == "lists")["bundle"] is False


def test_a_file_path_lists_its_folder_with_the_file_selected(client, tree):
    data = client.get("/api/fs/list", params={"path": str(tree / "alpha.csv"),
                                              "kind": "csv"}).json()
    assert data["path"] == str(tree)
    assert data["selected"] == "alpha.csv"


def test_home_relative_and_base_relative_paths(client, tree):
    assert client.get("/api/fs/list", params={"path": "~/shows"}).json()["path"] == str(
        tree / "shows")
    assert client.get("/api/fs/list").json()["path"] == str(tree)
    rel = client.get("/api/fs/list", params={"path": "festival", "base": str(tree / "shows")})
    assert rel.json()["path"] == str(tree / "shows" / "festival")


def test_a_folder_that_is_not_there_is_a_400_with_a_way_back_up(client, tree):
    r = client.get("/api/fs/list", params={"path": str(tree / "nope" / "deeper")})
    assert r.status_code == 400
    assert "there is nothing at" in r.json()["error"]
    assert r.json()["parent"] == str(tree / "nope")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_an_unreadable_folder_is_a_400_never_a_500(client, tree):
    locked = tree / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        r = client.get("/api/fs/list", params={"path": str(locked)})
    finally:
        locked.chmod(0o755)
    assert r.status_code == 400
    assert "permission" in r.json()["error"]


def test_an_unreadable_folder_is_reported_not_raised(monkeypatch, tree):
    """The same refusal, forced -- so it is proved when the suite runs as
    root too."""
    def refuse(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(fsbrowse.os, "listdir", refuse)
    with pytest.raises(fsbrowse.ListingError, match="permission to read ~"):
        fsbrowse.list_directory(str(tree))


def test_an_unknown_kind_is_a_400(client, tree):
    r = client.get("/api/fs/list", params={"path": str(tree), "kind": "exe"})
    assert r.status_code == 400
    assert "unknown kind" in r.json()["error"]


def test_a_huge_folder_is_cut_short_and_says_so(monkeypatch, client, tree):
    monkeypatch.setattr(fsbrowse, "MAX_ENTRIES", 3)
    data = client.get("/api/fs/list", params={"path": str(tree), "kind": "any"}).json()
    assert len(data["entries"]) == 3 and data["truncated"] is True


# ---- only this machine's own browser --------------------------------------

@pytest.mark.parametrize("client_host, host, allowed", [
    ("127.0.0.1", "127.0.0.1:8420", True),
    ("::1", "[::1]:8420", True),
    ("127.0.0.1", "localhost:8420", True),
    ("::ffff:127.0.0.1", "localhost", True),
    ("203.0.113.20", "203.0.113.5:8420", False),      # another machine on the LAN
    ("127.0.0.1", "evil.example:8420", False),         # DNS rebinding
    ("testclient", "testserver", False),
])
def test_the_file_browser_answers_this_machine_only(home, client_host, host, allowed):
    app = create_app()
    with fastapi_testclient.TestClient(app, client=(client_host, 5000),
                                       headers={"host": host}) as c:
        listing = c.get("/api/fs/list", params={"path": str(home)})
        made = c.post("/api/fs/mkdir", json={"path": str(home / "made")})
        adopted = c.post("/api/bundle/adopt", json={"slot": "input_list", "path": "x"})
    if allowed:
        assert listing.status_code == 200
        assert made.status_code == 200
    else:
        assert listing.status_code == 403
        assert made.status_code == 403
        assert adopted.status_code == 403
        assert "answers only" in listing.json()["error"]
        assert not (home / "made").exists()


# Every endpoint that opens a path the request names. Each
# entry is (method path, body) aimed at a real file or folder under `home`,
# so a request that got through would read it, write it or make it.
def _path_requests(home):
    secret = home / "secret.json"
    return [
        ("/api/plan/load", {"path": str(secret)}),
        ("/api/watch-conditions/load", {"path": str(secret)}),
        ("/api/watch-conditions/save", {"path": str(home / "written.json"),
                                        "watch_conditions": []}),
        ("/api/build/sources/load", {"slot": "input_list", "path": str(secret)}),
        ("/api/bundle/open", {"directory": str(home / "made-show"), "create": True}),
        ("/api/build/conventions/new", {"path": str(home / "house.md")}),
        ("/api/config/conventions-default", {"path": str(secret)}),
        ("/api/watch/start", {"source": "console", "watch_conditions_path": str(secret)}),
    ]


@pytest.mark.parametrize("client_host, host", [
    ("203.0.113.20", "203.0.113.5:8420"),      # another machine on the LAN
    ("127.0.0.1", "evil.example:8420"),        # DNS rebinding
])
def test_no_endpoint_opens_a_path_for_another_machine(home, client_host, host):
    (home / "secret.json").write_text('{"version": 2, "watch_conditions": [], "channels": []}')
    app = create_app()
    with fastapi_testclient.TestClient(app, client=(client_host, 5000),
                                       headers={"host": host}) as c:
        for url, body in _path_requests(home):
            r = c.post(url, json=body)
            assert r.status_code == 403, (url, r.status_code, r.text)
            assert "answers only" in r.json()["error"]
            assert "secret" not in r.text
        assert c.get("/api/watch-conditions").status_code == 404
        assert c.get("/api/plan").status_code == 404
    assert not (home / "written.json").exists()
    assert not (home / "made-show").exists()
    assert not (home / "house.md").exists()
    assert not (home / ".atoo.config").exists()


def test_every_path_endpoint_still_answers_this_machine(home):
    (home / "secret.json").write_text('{"version": 2, "watch_conditions": []}')
    with _local(create_app()) as c:
        for url, body in _path_requests(home):
            assert c.post(url, json=body).status_code != 403, url
        c.post("/api/watch/stop")


def test_a_phone_watching_may_send_back_the_watch_file_the_server_holds(home):
    held = home / "watch.json"
    held.write_text('{"version": 2, "watch_conditions": []}')
    other = home / "other.json"
    app = create_app(initial_watch_conditions_path=str(held))
    with fastapi_testclient.TestClient(app, client=("203.0.113.20", 5000),
                                       headers={"host": "203.0.113.5:8420"}) as phone:
        saved = phone.post("/api/watch-conditions/save",
                           json={"path": str(held), "watch_conditions": []})
        assert saved.status_code == 200, saved.text
        elsewhere = phone.post("/api/watch-conditions/save",
                               json={"path": str(other), "watch_conditions": []})
        assert elsewhere.status_code == 403
        # Demo opens the demo show, whose watch.json is then
        # the file the server holds -- and a phone may Start on that one.
        phone.post("/api/console", json={"demo": True})
        held_now = phone.get("/api/watch-conditions").json()["path"]
        started = phone.post("/api/watch/start",
                             json={"source": "console", "watch_conditions_path": held_now})
        assert started.status_code == 200, started.text
        phone.post("/api/watch/stop")
    assert not other.exists()


# Every Setup write -- to the console, or to the show's files --
# answers this machine only. From the LAN, Watch only.
# Each body is armed where arming exists, so one that got through would write.
_ARMED = {"confirm": True, "arm": True}
_SETUP_WRITES = [
    ("/api/apply/run", _ARMED),
    ("/api/patch/run", {**_ARMED, "change": "add a vocal on A 21"}),
    ("/api/undo/run", _ARMED),
    ("/api/build/run", {}),
    ("/api/build/stop", {}),
    ("/api/build/sections/save", {"slot": "conventions", "sections": []}),
    ("/api/build/input-list/save", {"rows": []}),
    ("/api/build/instructions/new", {}),
]


@pytest.mark.parametrize("client_host, host", [
    ("203.0.113.20", "203.0.113.5:8420"),      # another machine on the LAN
    ("127.0.0.1", "evil.example:8420"),        # DNS rebinding
])
def test_no_setup_write_answers_another_machine(home, client_host, host):
    app = create_app()
    with fastapi_testclient.TestClient(app, client=(client_host, 5000),
                                       headers={"host": host}) as c:
        for url, body in _SETUP_WRITES:
            r = c.post(url, json=body)
            assert r.status_code == 403, (url, r.status_code, r.text)
            assert "writing to the console or the show's files answers only" \
                in r.json()["error"], url


def test_every_setup_write_still_answers_this_machine(home):
    with _local(create_app()) as c:
        for url, body in _SETUP_WRITES:
            assert c.post(url, json=body).status_code != 403, url


def test_a_phone_on_the_lan_can_still_watch(home):
    app = create_app()
    with fastapi_testclient.TestClient(app, client=("203.0.113.20", 5000),
                                       headers={"host": "203.0.113.5:8420"}) as phone:
        phone.post("/api/console", json={"demo": True})
        started = phone.post("/api/watch/start", json={"source": "console"})
        assert started.status_code == 200, started.text
        assert phone.get("/api/status").status_code == 200
        assert phone.post("/api/console", json={"address": "198.51.100.50"}).status_code != 403
        phone.post("/api/watch/stop")


def test_the_loopback_checks_directly():
    assert fsbrowse.client_is_local("127.0.0.1")
    assert fsbrowse.client_is_local("127.8.9.10")
    assert fsbrowse.client_is_local("::1")
    assert not fsbrowse.client_is_local("198.51.100.2")
    assert not fsbrowse.client_is_local(None)
    assert fsbrowse.host_is_local("LOCALHOST:8420")
    assert fsbrowse.host_is_local("127.0.0.1")
    assert not fsbrowse.host_is_local("127.0.0.1.evil.example")
    assert not fsbrowse.host_is_local("")


# ---- no other web page may write ------------------------------------------

@pytest.mark.parametrize("headers", [
    {"Origin": "http://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://127.0.0.1:9999"},               # another local app
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_a_write_from_another_web_page_is_refused(client, home, headers):
    r = client.post("/api/fs/mkdir", json={"path": str(home / "made")}, headers=headers)
    assert r.status_code == 403
    assert "refused a write from another web page" in r.json()["error"]
    assert not (home / "made").exists()


def test_the_cross_site_guard_covers_the_existing_write_endpoints_too(client, home):
    """Nothing but FastAPI's JSON content-type parsing
    stood between another site and these -- and step 03's New file had no
    body at all."""
    target = home / "new-show"
    r = client.post("/api/bundle/open", json={"directory": str(target), "create": True},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert not target.exists()
    r = client.post("/api/build/instructions/new", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_the_pages_own_writes_pass(client, home):
    r = client.post("/api/fs/mkdir", json={"path": str(home / "made")},
                    headers={"Origin": "http://127.0.0.1:8420", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    # Reads are never refused for where they came from; only writes are.
    assert client.get("/api/status", headers={"Origin": "http://evil.example"}).status_code == 200


# ---- POST /api/fs/mkdir -----------------------------------------------------

def test_new_folder_makes_one_folder_and_answers_its_listing(client, home):
    r = client.post("/api/fs/mkdir", json={"path": "2026", "base": str(home)})
    assert r.status_code == 200
    data = r.json()
    assert (home / "2026").is_dir()
    assert data["created"] == str(home / "2026")
    assert data["path"] == str(home / "2026") and data["entries"] == []
    assert data["message"] == "Created the folder ~/2026."


def test_new_folder_never_over_anything(client, home):
    (home / "taken").mkdir()
    (home / "file").write_text("x")
    for name in ("taken", "file"):
        r = client.post("/api/fs/mkdir", json={"path": name, "base": str(home)})
        assert r.status_code == 409
        assert "nothing was created" in r.json()["error"]
    assert (home / "file").read_text() == "x"


def test_new_folder_one_level_at_a_time(client, home):
    r = client.post("/api/fs/mkdir", json={"path": str(home / "a" / "b")})
    assert r.status_code == 400
    assert "there is no folder ~/a" in r.json()["error"]
    assert not (home / "a").exists()


@pytest.mark.parametrize("name", ["", "   ", ".", ".."])
def test_new_folder_needs_a_name(client, home, name):
    r = client.post("/api/fs/mkdir", json={"path": name, "base": str(home)})
    assert r.status_code == 400


# ---- POST /api/bundle/adopt --------------------------------------

@pytest.fixture
def new_show(home):
    """A New show...: an empty bundle folder, and an input list and an
    instructions file somewhere else."""
    show = home / "shows" / "festival"
    show.mkdir(parents=True)
    (home / "lists").mkdir()
    (home / "lists" / "band.csv").write_text(INPUT_CSV)
    (home / "lists" / "band-v2.csv").write_text(OTHER_CSV)
    (home / "notes").mkdir()
    (home / "notes" / "festival.md").write_text(INSTRUCTIONS)
    (home / "house.md").write_text(HOUSE)
    app = create_app(initial_bundle=str(show), initial_conventions=str(home / "house.md"))
    with _local(app) as c:
        c.app_state = app.state
        yield c, show


def _adopt(c, show, slot, path, **extra):
    return c.post("/api/bundle/adopt", json={"slot": slot, "path": str(path),
                                             "expected_bundle": str(show), **extra})


def test_an_input_list_from_elsewhere_is_copied_into_a_new_show(new_show, home):
    c, show = new_show
    r = _adopt(c, show, "input_list", home / "lists" / "band.csv")
    assert r.status_code == 200
    data = r.json()
    assert (show / "input.csv").read_text() == INPUT_CSV
    assert data["copied"] is True
    assert data["message"] == ("Copied ~/lists/band.csv into festival/input.csv -- the bundle "
                               "now owns its copy; edits to the original won't reach it.")
    # The tile now shows the bundle's own file, not a pointer elsewhere.
    assert data["input_list"]["path"] == str(show / "input.csv")
    assert data["input_list"]["state"] == "loaded"
    assert c.app_state.build_overrides["input_list"] is None
    # Provenance, as an INFO the page puts in the dock.
    assert data["finding"]["severity"] == "info"
    assert data["finding"]["code"] == "bundle.copied-in"
    assert data["finding"]["line"] == str(home / "lists" / "band.csv")
    # The original is untouched, and later edits to it do not reach the copy.
    (home / "lists" / "band.csv").write_text("changed\n")
    assert (show / "input.csv").read_text() == INPUT_CSV


def test_a_bundle_that_has_one_is_asked_not_overwritten(new_show, home):
    c, show = new_show
    (show / "input.csv").write_text(INPUT_CSV)
    r = _adopt(c, show, "input_list", home / "lists" / "band-v2.csv")
    assert r.status_code == 409
    data = r.json()
    assert "festival already has an input.csv" in data["error"]
    assert "Nothing was copied" in data["error"]
    assert data["exists"]["path"] == str(show / "input.csv")
    assert data["exists"]["size"] == len(INPUT_CSV)
    assert data["chosen"]["display_path"] == "~/lists/band-v2.csv"
    assert (show / "input.csv").read_text() == INPUT_CSV


def test_replace_keeps_the_one_it_replaced(new_show, home):
    c, show = new_show
    (show / "input.csv").write_text(INPUT_CSV)
    r = _adopt(c, show, "input_list", home / "lists" / "band-v2.csv", replace=True)
    assert r.status_code == 200
    assert (show / "input.csv").read_text() == OTHER_CSV
    assert (show / "backups" / "input.csv.bak").read_text() == INPUT_CSV
    assert r.json()["replaced"] is True
    assert "kept as festival/backups/input.csv.bak" in r.json()["message"]


def test_the_same_content_is_not_a_question(new_show, home):
    c, show = new_show
    (show / "input.csv").write_text(INPUT_CSV)
    r = _adopt(c, show, "input_list", home / "lists" / "band.csv")
    assert r.status_code == 200
    assert r.json()["copied"] is False
    assert "already holds exactly what" in r.json()["message"]
    assert "finding" not in r.json()
    assert not (show / "backups" / "input.csv.bak").exists()


def test_the_bundles_own_file_is_not_copied_onto_itself(new_show):
    c, show = new_show
    (show / "input.csv").write_text(INPUT_CSV)
    r = _adopt(c, show, "input_list", show / "input.csv")
    assert r.status_code == 200 and r.json()["copied"] is False
    assert (show / "input.csv").read_text() == INPUT_CSV


def test_instructions_are_copied_in_too_and_so_can_be_built(new_show, home):
    """`build` reads instructions only from the bundle, and refused a step
    03 pointed elsewhere; copying it in is what makes it buildable."""
    c, show = new_show
    elsewhere = home / "notes" / "festival.md"
    c.post("/api/build/sources/load", json={"slot": "instructions", "path": str(elsewhere)})
    refused = c.post("/api/build/run", json={"console_model": "wing-compact"})
    assert refused.status_code == 400
    assert "Change file, which copies it into the bundle" in refused.json()["error"]

    r = _adopt(c, show, "instructions", elsewhere)
    assert r.status_code == 200
    assert (show / "instructions.md").read_text() == INSTRUCTIONS
    assert "into festival/instructions.md" in r.json()["message"]
    assert r.json()["instructions"]["path"] == str(show / "instructions.md")
    assert c.app_state.build_overrides["instructions"] is None


def test_the_house_conventions_file_is_never_copied_in(new_show, home):
    c, show = new_show
    r = _adopt(c, show, "conventions", home / "house.md")
    assert r.status_code == 400
    assert "stays outside the bundle on purpose" in r.json()["error"]
    assert list(show.iterdir()) == []


def test_copy_into_bundle_needs_a_bundle(home):
    (home / "band.csv").write_text(INPUT_CSV)
    with _local(create_app()) as c:
        r = c.post("/api/bundle/adopt", json={"slot": "input_list",
                                              "path": str(home / "band.csv")})
    assert r.status_code == 400
    assert "no show bundle open" in r.json()["error"]


@pytest.mark.parametrize("expected", [None, "/somewhere/else"])
def test_a_stale_page_cannot_copy_into_the_bundle(new_show, home, expected):
    c, show = new_show
    body = {"slot": "input_list", "path": str(home / "lists" / "band.csv")}
    if expected is not None:
        body["expected_bundle"] = expected
    r = c.post("/api/bundle/adopt", json=body)
    assert r.status_code == 409
    assert r.json()["stale"] == "bundle"
    assert not (show / "input.csv").exists()


def test_copy_refuses_what_is_not_a_readable_text_file(new_show, home):
    c, show = new_show
    (home / "blob.csv").write_bytes(b"\xff\xfe\x00binary")
    for path, words in ((home / "nope.csv", "no file at"), (home / "lists", "that is a folder"),
                        (home / "blob.csv", "not a text file")):
        r = _adopt(c, show, "input_list", path)
        assert r.status_code == 400, path
        assert words in r.json()["error"]
    assert not (show / "input.csv").exists()


def test_choosing_the_bundles_own_file_by_path_drops_the_override(new_show, home):
    """The modal's "Keep the bundle's" loads the bundle's own file by path;
    that must not count as pointing step 03 elsewhere."""
    c, show = new_show
    (show / "instructions.md").write_text(INSTRUCTIONS)
    c.post("/api/build/sources/load", json={"slot": "instructions",
                                            "path": str(home / "notes" / "festival.md")})
    assert c.app_state.build_overrides["instructions"] == str(home / "notes" / "festival.md")
    c.post("/api/build/sources/load", json={"slot": "instructions",
                                            "path": str(show / "instructions.md")})
    assert c.app_state.build_overrides["instructions"] is None


# ---- a copy into the bundle makes its plan Stale (the tracking) -------

def _built_bundle(home):
    """A bundle whose plan.json records the input list and house file it
    was built from, as `atoo build` writes them -- so its
    `plan_freshness` reads current until one of them changes."""
    import json

    from atoo import conventions_ref, plan_freshness

    show = home / "shows" / "built"
    show.mkdir(parents=True)
    (show / "input.csv").write_text(INPUT_CSV)
    house = home / "house.md"
    house.write_text(HOUSE)
    meta = {"generated_at": "2026-09-25T12:00:00+00:00",
            "conventions_stack": [{"path": str(house), "role": "conventions", "source": "test",
                                   **conventions_ref.layer_record(house, show)}],
            "input_list": plan_freshness.input_list_record(show / "input.csv", show)}
    (show / "plan.json").write_text(json.dumps(
        {"channels": [], "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {},
         "meta": meta}))
    (home / "lists").mkdir()
    (home / "lists" / "band-v2.csv").write_text(OTHER_CSV)
    (home / "lists" / "same.csv").write_text(INPUT_CSV)
    (home / "notes").mkdir()
    (home / "notes" / "festival.md").write_text(INSTRUCTIONS)
    return show, house


def test_replacing_the_input_list_makes_the_plan_stale(home):
    show, house = _built_bundle(home)
    with _local(create_app(initial_bundle=str(show), initial_conventions=str(house))) as c:
        before = c.get("/api/build/sources").json()["plan_freshness"]
        assert before["state"] == "current"
        # An identical file copies nothing, and changes nothing.
        same = _adopt(c, show, "input_list", home / "lists" / "same.csv")
        assert same.json()["plan_freshness"]["state"] == "current"
        r = _adopt(c, show, "input_list", home / "lists" / "band-v2.csv", replace=True)
    fresh = r.json()["plan_freshness"]
    assert fresh["state"] == "stale"
    assert [reason["code"] for reason in fresh["reasons"]] == ["plan.input-list-edited"]


def test_copying_instructions_into_a_built_bundle_makes_the_plan_stale(home):
    show, house = _built_bundle(home)
    with _local(create_app(initial_bundle=str(show), initial_conventions=str(house))) as c:
        r = _adopt(c, show, "instructions", home / "notes" / "festival.md")
    fresh = r.json()["plan_freshness"]
    assert fresh["state"] == "stale"
    assert [reason["code"] for reason in fresh["reasons"]] == ["plan.instructions-added"]


# ---- step 03's New file names the bundle it writes into (FR-6.11) --------------

@pytest.mark.parametrize("body", [None, {}, {"expected_bundle": "/another/show"}])
def test_a_stale_page_cannot_create_instructions(new_show, body):
    c, show = new_show
    r = (c.post("/api/build/instructions/new") if body is None
         else c.post("/api/build/instructions/new", json=body))
    assert r.status_code == 409
    assert r.json()["stale"] == "bundle"
    assert not (show / "instructions.md").exists()


def test_a_current_page_creates_instructions(new_show):
    c, show = new_show
    r = c.post("/api/build/instructions/new", json={"expected_bundle": str(show)})
    assert r.status_code == 200
    assert (show / "instructions.md").is_file()


# ---- the served page (the Python suite cannot otherwise see the browser) --------

FB_IDS = (
    "fb-modal", "fb-title", "fb-note", "fb-path", "fb-crumbs", "fb-list", "fb-empty",
    "fb-counts", "fb-hidden", "fb-all", "fb-all-row", "fb-newfolder-btn", "fb-newfolder",
    "fb-newfolder-name", "fb-newfolder-create", "fb-newfolder-cancel", "fb-name-row",
    "fb-name-label", "fb-name", "fb-check-row", "fb-check", "fb-check-label", "fb-check-note",
    "fb-ask", "fb-ask-text", "fb-ask-buttons", "fb-error", "fb-selection", "fb-confirm",
    "fb-cancel", "fb-close", "fb-up", "fb-home", "fb-go",
)


def test_the_modal_is_in_the_page_and_filebrowser_js_reaches_every_part(client):
    html = client.get("/static/shell.html").text
    js = client.get("/static/filebrowser.js").text
    for element_id in FB_IDS:
        assert f'id="{element_id}"' in html, f"shell.html has no #{element_id}"
        assert f'"{element_id}"' in js, f"filebrowser.js never reaches #{element_id}"
    # Loaded after shell.js, whose `window.Atoo` it codes against.
    assert html.index('src="/static/shell.js"') < html.index('src="/static/filebrowser.js"')
    assert 'id="plan-browse-btn"' in html and '"plan-browse-btn"' in js
    # Watch's file opens the modal from watch.js since an earlier change (and
    # copies the choice into the bundle), not through a path box.
    assert 'id="wc-browse-btn"' not in html and '"wc-browse-btn"' not in js
    assert 'id="wc-change-btn"' in html
    assert '"wc-change-btn"' in client.get("/static/watch.js").text


def test_filebrowser_js_reads_every_key_the_listing_sends(client, tree):
    js = client.get("/static/filebrowser.js").text
    assert '"/api/fs/list?"' in js and '"/api/fs/mkdir"' in js
    data = client.get("/api/fs/list", params={"path": str(tree)}).json()
    for key in ("path", "display_path", "parent", "sep", "selected", "entries",
                "other_files", "hidden_count", "truncated"):
        assert key in data
        assert f"data.{key}" in js or f"listing.{key}" in js, f"filebrowser.js never reads {key}"
    for key in ("name", "path", "type", "size", "mtime", "symlink", "target"):
        assert f"entry.{key}" in js, f"filebrowser.js never reads entry.{key}"
    assert "entry.bundle" in js
    # New folder's answer, and a refusal's way back up.
    assert "data.created" in js and "data.message" in js and "data.parent" in js
    # The stale-page banner closes the dialog, and every write checks first.
    assert "SP.onStale(" in js and "SP.checkServer()" in js


def test_shell_js_copies_into_the_bundle_and_asks_before_replacing(client):
    js = client.get("/static/shell.js").text
    assert '"/api/bundle/adopt"' in js
    assert "expected_bundle: bundle ? bundle.directory : null" in js
    for key in ("answer.data.exists", "answer.data.chosen", "answer.data.stale",
                "data.finding", "there.path", "there.display_path", "chosen.display_path"):
        assert key in js, f"shell.js never reads {key}"
    for answer in ('id: "replace"', 'id: "keep"', 'id: "cancel"'):
        assert answer in js
    # A step with unsaved edits (the editors) is asked about
    # before a chosen file replaces what it shows.
    assert "if (editingStep[slot]) {" in js and 'id: "discard"' in js
    # The old path boxes are gone; each affordance opens the modal.
    for gone in ("bundle-edit-input", "tile-edit-", "new-path-conventions"):
        assert gone not in js
    for mode in ('mode: "open-folder"', 'mode: "create-folder"', 'mode: "open-file"',
                 'mode: "save-file"'):
        assert mode in js


def test_styles_css_draws_the_modal(client):
    css = client.get("/static/styles.css").text
    for selector in (".fb-backdrop", ".fb-dialog", ".fb-row", ".fb-row.is-highlighted",
                     ".fb-ask", ".fb-backdrop[hidden]"):
        assert selector in css, f"styles.css has no {selector} rule"
