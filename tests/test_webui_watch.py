"""An earlier change, UI phase 6: Watch moves into the shell, and the shell moves to `/`.

Three halves, and the third is the one `CLAUDE.md` warns about:

* **The routes.** `/` is the shell; `/app` (where it lived) redirects
  there; the old Watch page's `index.html` and `app.js` are gone.
* **The server's watch state follows the open show.** Opening another
  bundle swaps Watch's rules for that bundle's `watch.json`, and a build
  that drafts into `watch.json` is re-read -- because on one page, a
  rules editor still holding the pre-build file would Save the drafted
  conditions away.
* **The served assets.** The Python suite cannot see the browser, and a
  moved page that reads an id the new markup does not carry renders a
  silently blank element rather than throwing. So every id `watch.js`
  looks up is asserted to exist in the page as served, and the two
  vocabularies the editor duplicates from Python -- the relational fields
  and the `source` values -- are asserted against Python's own.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo import watch_conditions as wc  # noqa: E402
from atoo.webui import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

HOUSE = "# house\n\n## Inputs\nPatch input sockets according to the supplied input list.\n"

HAND = {"id": "kick-muted", "description": "Kick muted", "channel": "Kick",
        "field": "muted", "operator": "==", "value": True, "severity": "warning"}
DRAFTED_ROW = {"id": "vox-in-band", "description": "Vox stays in Band", "channel": "Vox",
               "field": "dca", "operator": "==", "value": "Band", "severity": "info",
               "source": "drafted"}


@pytest.fixture
def client():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def _bundle(tmp_path, name, conditions=None, drafted=None):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "input.csv").write_text((FIXTURES / "touringband.csv").read_text())
    if conditions is not None:
        document = {"watch_conditions": conditions}
        if drafted is not None:
            document["drafted"] = drafted
        (directory / "watch.json").write_text(json.dumps(document, indent=2) + "\n")
    return directory


# ======================================================================
# Routes
# ======================================================================


def test_the_shell_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="initial-shell"' in r.text
    for mode in ("mode-build", "mode-apply", "mode-watch"):
        assert f'id="{mode}"' in r.text


def test_app_redirects_to_the_root_and_is_not_cached_as_permanent(client):
    """Bookmarks and docs already read point at `/app`. A 307 rather than
    a 301/308: a permanent redirect is cached by the browser and would
    outlive a checkout of an older branch, where `/` is another page."""
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/"
    followed = client.get("/app")
    assert followed.status_code == 200 and 'id="initial-shell"' in followed.text


def test_the_old_watch_page_is_gone(client):
    """Retired, not left beside the shell: a second copy of the Watch
    page's markup is a second place to fix every bug."""
    assert client.get("/static/index.html").status_code == 404
    assert client.get("/static/app.js").status_code == 404
    assert client.get("/static/watch.js").status_code == 200
    page = client.get("/").text
    assert "/static/app.js" not in page
    assert 'href="/app' not in page
    assert "watch-page-link" not in page, "the Watch stub's link to the old page survived"


# ======================================================================
# The server's watch state follows the open show
# ======================================================================


def test_opening_another_bundle_loads_its_watch_json(client, tmp_path):
    first = _bundle(tmp_path, "first", [HAND])
    second = _bundle(tmp_path, "second", [DRAFTED_ROW], drafted=["vox-in-band"])
    client.post("/api/bundle/open", json={"directory": str(first)})
    assert client.get("/api/watch-conditions").json()["path"] == str(first / "watch.json")

    client.post("/api/bundle/open", json={"directory": str(second)})
    data = client.get("/api/watch-conditions").json()
    assert data["path"] == str(second / "watch.json")
    assert [c["id"] for c in data["watch_conditions"]] == ["vox-in-band"]
    assert data["watch_conditions"][0]["source"] == "drafted"


def test_opening_a_bundle_with_no_watch_json_leaves_watch_with_none(client, tmp_path):
    """The absent case: the last show's rules must not stay on screen
    under a show that has none of its own."""
    first = _bundle(tmp_path, "first", [HAND])
    bare = _bundle(tmp_path, "bare")
    client.post("/api/bundle/open", json={"directory": str(first)})
    assert client.get("/api/watch-conditions").status_code == 200

    client.post("/api/bundle/open", json={"directory": str(bare)})
    assert client.get("/api/watch-conditions").status_code == 404


def _wait_for_build(c, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = c.get("/api/build/status").json()
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("the build never finished")


@pytest.fixture
def drafting(tmp_path, stub_build, monkeypatch):
    """A stubbed build that drafts one condition into the bundle."""
    stub_build("touringband")
    drafted = {k: v for k, v in DRAFTED_ROW.items() if k != "source"}
    monkeypatch.setattr("atoo.generate.draft_watch_conditions",
                        lambda *a, **k: [dict(drafted)])
    house = tmp_path / "house.md"
    house.write_text(HOUSE)
    return house


def test_a_build_that_drafts_is_what_watch_serves_next(drafting, tmp_path):
    """The trap on one page: without the re-read, `GET /api/watch-conditions`
    kept serving the pre-build file, the editor showed it, and a Save
    wrote the drafted condition away -- with its id already in `drafted`,
    so the next build would not propose it again."""
    directory = _bundle(tmp_path, "show", [HAND])
    app = create_app(initial_bundle=str(directory), initial_conventions=str(drafting),
                     initial_watch_conditions_path=str(directory / "watch.json"))
    with fastapi_testclient.TestClient(app) as c:
        before = c.get("/api/watch-conditions").json()
        assert [x["id"] for x in before["watch_conditions"]] == ["kick-muted"]
        c.post("/api/build/run", json={"console_model": "wing-compact"})
        _wait_for_build(c)
        after = c.get("/api/watch-conditions").json()
    assert [x["id"] for x in after["watch_conditions"]] == ["kick-muted", "vox-in-band"]
    assert after["watch_conditions"][1]["source"] == "drafted"


def test_a_shows_first_drafted_watchlist_reaches_an_empty_editor(drafting, tmp_path):
    """No watch.json before the build, so nothing was loaded: the file the
    build creates is the one Watch should now have."""
    directory = _bundle(tmp_path, "show")
    app = create_app(initial_bundle=str(directory), initial_conventions=str(drafting))
    with fastapi_testclient.TestClient(app) as c:
        assert c.get("/api/watch-conditions").status_code == 404
        c.post("/api/build/run", json={"console_model": "wing-compact"})
        _wait_for_build(c)
        after = c.get("/api/watch-conditions")
    assert after.status_code == 200
    assert after.json()["path"] == str(directory / "watch.json")


def test_a_build_leaves_a_watch_file_pointed_at_by_hand_alone(drafting, tmp_path):
    """The absent case for the re-read: an operator who loaded some other
    watch-conditions file keeps it. Only the bundle's own watchlist is
    what a build drafts into."""
    directory = _bundle(tmp_path, "show", [HAND])
    elsewhere = tmp_path / "elsewhere.watch.json"
    elsewhere.write_text(json.dumps({"watch_conditions": [HAND]}))
    app = create_app(initial_bundle=str(directory), initial_conventions=str(drafting),
                     initial_watch_conditions_path=str(elsewhere))
    with fastapi_testclient.TestClient(app) as c:
        c.post("/api/build/run", json={"console_model": "wing-compact"})
        _wait_for_build(c)
        after = c.get("/api/watch-conditions").json()
    assert after["path"] == str(elsewhere)
    assert [x["id"] for x in after["watch_conditions"]] == ["kick-muted"]


def test_save_keeps_a_drafted_source_and_an_absent_one_absent(client, tmp_path):
    """What the Source column round-trips. An untouched drafted row stays
    `"source": "drafted"`; a row the engineer edited reaches the server
    with no `source` key (watch.js deletes it) and is written without one,
    because absent IS "hand" and a hand-written file stays byte-for-byte
    the engineer's. The `drafted` bookkeeping is carried forward either
    way, so deleting a drafted row sticks."""
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"watch_conditions": [DRAFTED_ROW, HAND],
                                "drafted": ["vox-in-band", "gone"]}))
    edited = dict(HAND, severity="error")
    r = client.post("/api/watch-conditions/save",
                    json={"path": str(path), "watch_conditions": [DRAFTED_ROW, edited]})
    assert r.status_code == 200
    written = json.loads(path.read_text())
    assert written["watch_conditions"][0]["source"] == "drafted"
    assert "source" not in written["watch_conditions"][1]
    assert written["drafted"] == ["vox-in-band", "gone"]


# ======================================================================
# The served assets
# ======================================================================


def test_every_id_watch_js_reads_is_on_the_served_page(client):
    """The whole risk of this phase in one test. `el("x")` on an id the
    moved markup does not carry is null, and the first `.hidden =` on it
    throws inside an IIFE -- every later line of the Watch script simply
    does not run, and the page looks fine until someone presses Start.
    The ids are pulled from the script itself, so a new lookup is covered
    the day it is written."""
    js = client.get("/static/watch.js").text
    page = client.get("/").text
    ids = set(re.findall(r'\bel\("([^"]+)"\)', js))
    # The regex found the lookups at all. 20, not 25: the connect form's
    # IP/port boxes and their two seed tags went when the console became
    # the bundle bar's alone (the maintainer, 2026-09-24), and one read-only
    # readout came in their place.
    assert len(ids) >= 20, ids
    missing = sorted(i for i in ids if f'id="{i}"' not in page)
    assert not missing, f"watch.js reads ids the served page does not have: {missing}"
    # The one lookup that is a selector, not an id: the severity pills.
    assert ".count-pill[data-sev=" in js
    for sev in ("error", "warning", "info"):
        assert f'class="count-pill count-{sev}" data-sev="{sev}"' in page


def test_the_moved_ids_are_not_claimed_twice_on_the_page(client):
    """Build, Apply and Watch now share one document. An id that two modes
    both use resolves to whichever comes first, and the other mode's
    script writes into the wrong panel without an error."""
    page = client.get("/").text
    ids = re.findall(r'\bid="([^"]+)"', page)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"ids used more than once on /: {dupes}"


def test_the_source_column_speaks_pythons_source_vocabulary(client):
    """`"drafted"` is `watch_conditions.SOURCE_DRAFTED`. The editor keeps
    its own copy; a rename on the Python side would make every drafted
    row read Yours, silently."""
    js = client.get("/static/watch.js").text
    assert f'const WC_SOURCE_DRAFTED = "{wc.SOURCE_DRAFTED}";' in js
    assert "cond.source === WC_SOURCE_DRAFTED" in js
    assert '"Drafted"' in js and '"Yours"' in js
    # An edit is a decision: the key is DELETED, which is what a
    # hand-written condition looks like in the file -- not set to "hand",
    # and not left saying drafted.
    assert "delete cond.source;" in js
    assert f'cond.source = "{wc.SOURCE_HAND}"' not in js
    # A row added in the editor carries no source key at all.
    add = js[js.index("wcAddBtn.addEventListener"):js.index("async function wcLoadPointer")]
    assert "source" not in add.replace("// No `source` key", "")

    html = client.get("/static/shell.html").text
    head = html[html.index('<table id="wc-table">'):html.index("</thead>", html.index('<table id="wc-table">'))]
    assert re.findall(r"<th[^>]*>([^<]*)</th>", head) == [
        "ID", "Description", "Channel", "Field", "Operator", "Value", "Severity", "Source", ""]


def _js_array(js: str, name: str) -> list:
    m = re.search(r"const " + re.escape(name) + r" = (\[[^\]]*\])", js)
    assert m, f"watch.js has no array literal for {name}"
    return json.loads(m.group(1))


def test_the_relational_fields_offer_only_the_two_equality_operators(client):
    """`dca`, `mute_group` and `patch` ask a yes/no question and
    take `==`/`!=` only. The editor's list of them has to BE Python's list,
    and the operators it narrows them to have to be exactly Python's two
    -- the editor must not offer an operator the loader would refuse."""
    js = client.get("/static/watch.js").text
    assert set(_js_array(js, "WC_TEXT_FIELDS")) == wc._RELATIONAL_FIELDS
    assert set(_js_array(js, "WC_BOOL_OPERATORS")) == wc._BOOL_COMPATIBLE_OPERATORS
    assert set(_js_array(js, "WC_FIELDS")) == wc._ALLOWED_FIELDS
    assert set(_js_array(js, "WC_OPERATORS")) == set(wc._OPERATORS)
    assert 'const WC_EQUALITY_ONLY_FIELDS = ["muted"].concat(WC_TEXT_FIELDS);' in js
    # The narrowing itself, at the two places it happens: when a row is
    # drawn, and when its field changes under an ordering operator.
    assert ("const opOptions = WC_EQUALITY_ONLY_FIELDS.includes(cond.field)\n"
            "      ? WC_BOOL_OPERATORS : WC_OPERATORS;") in js
    assert ("if (WC_EQUALITY_ONLY_FIELDS.includes(cond.field)\n"
            "          && !WC_BOOL_OPERATORS.includes(cond.operator)) {\n"
            "        cond.operator = \"==\";") in js


@pytest.mark.parametrize("field", sorted(wc._RELATIONAL_FIELDS))
@pytest.mark.parametrize("operator", [">", "<", ">=", "<="])
def test_the_loader_refuses_an_ordering_operator_on_a_relational_field(field, operator):
    """What the editor's narrowing protects against, checked on the Python
    side so the claim in the issue is not taken on trust."""
    value = "AES50-A 1" if field == "patch" else "Drums"
    cond = {"id": "x", "description": "x", "channel": "Kick", "field": field,
            "operator": operator, "value": value, "severity": "info"}
    with pytest.raises(wc.WatchConditionsError, match="only supports"):
        wc.parse_watch_conditions(json.dumps({"watch_conditions": [cond]}))


def test_watch_js_rereads_watch_json_on_entering_watch_but_never_over_edits(client):
    """The browser half of the drafted-watchlist trap. The re-read hangs
    off the shell's `onModeChange`/`onBundleChange` contract, and a table
    with unsaved edits is told rather than overwritten."""
    js = client.get("/static/watch.js").text
    shell = client.get("/static/shell.js").text
    assert 'SP.onModeChange((mode) => { if (mode === "watch") wcRefresh(); });' in js
    assert "SP.onBundleChange(() => wcRefresh());" in js
    assert "onModeChange: (fn) =>" in shell
    refresh = js[js.index("async function wcRefresh()"):js.index("async function wcInit()")]
    dirty = refresh.index("if (wcDirty) {")
    assert refresh.index("return;", dirty) < refresh.index("wcApplyResponse(", dirty), (
        "a dirty table must return before anything is applied over it"
    )
    # Every edit path marks the table dirty.
    assert js.count("edited();") >= 9
    assert "wcSetDirty(false);" in js[js.index("function wcApplyResponse"):js.index("wcAddBtn.addEventListener")]


def test_the_drafted_watchlist_finding_jumps_to_the_rules_editor(client):
    """OPTIONS-H point 3: the Build finding that says conditions were
    drafted opens Watch, now on the editor that marks them -- the old
    target was the stub's link to the retired page."""
    js = client.get("/static/setup.js").text
    assert '{ label: "Review on Watch", mode: "watch", target: "#wc-panel" }' in js
    assert 'id="wc-panel"' in client.get("/").text


def test_watch_js_still_renders_the_coverage_caveat_off_every_event(client):
    """Exactly as the old page did -- on every event, not only
    the baseline, and hidden (not "undefined") when the key is absent."""
    js = client.get("/static/watch.js").text
    handle = js[js.index("function handleEvent(payload)"):js.index("if (payload.baseline)")]
    assert 'const caveat = payload.coverage_caveat || "";' in handle
    assert 'coverageNote.hidden = caveat === "";' in handle
    assert "coverageNote.textContent = caveat;" in handle
    page = client.get("/").text
    note = page.index('id="coverage-note"')
    assert "hidden" in page[note:page.index(">", note)]


# ======================================================================
# position targets, and the editor's inline check
# ======================================================================


def test_the_check_endpoint_answers_per_row_with_the_loaders_reasons(client):
    rows = [dict(HAND, channel="dca1-4", field="fader_db", operator="<=", value=0),
            dict(HAND, channel="BUS -"),
            dict(HAND, channel="DCA 1", field="patch", operator="==", value="LCL 1"),
            HAND,
            dict(HAND, channel="bus Drums"),
            dict(HAND, channel="BUS"),
            dict(HAND, channel="DCA Vocals", field="patch", operator="==", value="LCL 1")]
    r = client.post("/api/watch-conditions/check", json={"watch_conditions": rows})
    assert r.status_code == 200
    answer = r.json()["rows"]
    assert answer[0] == {"canonical": "DCA 1-4", "position": True, "scoped": False}
    assert "begins like a position" in answer[1]["channel"]
    assert "has no input patch" in answer[2]["field"]
    assert answer[3] == {"canonical": "Kick", "position": False, "scoped": False}
    # A scoped name: the kind word normalised, the name as typed.
    assert answer[4] == {"canonical": "BUS Drums", "position": False, "scoped": True}
    assert "has no position or name" in answer[5]["channel"]
    assert "has no input patch" in answer[6]["field"]


def test_save_writes_a_position_canonically_and_a_name_as_typed(client, tmp_path):
    path = tmp_path / "watch.json"
    rows = [dict(HAND, id="a", channel="ch10"), dict(HAND, id="b", channel="kick ")]
    r = client.post("/api/watch-conditions/save",
                    json={"path": str(path), "watch_conditions": rows})
    assert r.status_code == 200
    written = json.loads(path.read_text())["watch_conditions"]
    assert [c["channel"] for c in written] == ["CH 10", "kick "]


def test_save_refuses_a_target_that_cannot_work(client, tmp_path):
    path = tmp_path / "watch.json"
    r = client.post("/api/watch-conditions/save",
                    json={"path": str(path), "watch_conditions": [dict(HAND, channel="CH 41")]})
    assert r.status_code == 400
    assert "CH 41 does not exist" in r.json()["error"]
    assert not path.exists()


def test_watch_js_asks_the_server_to_check_each_row(client):
    """The Python suite cannot see the browser; this is the one thing
    standing between a renamed endpoint or key and a table that quietly
    stops refusing anything."""
    js = client.get("/static/watch.js").text
    assert "/api/watch-conditions/check" in js
    for key in ('"channel"', '"field"', '"value"', "check.canonical", "check.position",
                "check.scoped"):
        assert key in js
    # The cell's hint names the scoped form too.
    assert "BUS Drums" in js
    # `Main` alone: the server's `note` is shown under the cell, not red.
    assert "check.note" in js and '"is-note"' in js
    assert ".wc-cell-error.is-note" in client.get("/static/styles.css").text


def test_start_clears_the_table_before_asking_not_after(client):
    """Found checking an earlier change in Chromium: the baseline event can reach
    the socket before `POST /api/watch/start` answers, and a table cleared
    after the answer threw it away -- every finding already present at
    Start (a per-strip watch finding among them) never showed."""
    js = client.get("/static/watch.js").text
    start = js[js.index('startBtn.addEventListener("click"'):js.index('stopBtn.addEventListener("click"')]
    assert start.index("alertBody.innerHTML = \"\";") < start.index('fetch("/api/watch/start"')
    assert start.count("alertBody.innerHTML") == 1


def test_a_stopped_session_replays_nothing_to_a_new_page(client):
    """Found checking an earlier change in Chromium: the last event of a stopped
    session was replayed to every page opened afterwards, and the page
    read it as a running session -- Start disabled, the pill on Watching
    -- while `/api/status` said `running: false`. Stop now forgets that
    event and says so to every open tab; Start says so before its first
    event.

    Every wait below ends on a frame that arrives with or without the
    fix (a status on connect, or the next session's baseline), so a
    regression fails here rather than hanging the suite."""
    running = {"type": "status", "running": True, "label": "Demo", "error": None}
    stopped = {"type": "status", "running": False, "label": "Demo", "error": None}

    def until_baseline(ws):
        frames = []
        while not (frames and frames[-1].get("baseline") is True):
            frames.append(ws.receive_json())
        return frames

    client.post("/api/console", json={"demo": True})
    assert client.post("/api/watch/start", json={"source": "console", "interval": 0.1}).status_code == 200
    with client.websocket_connect("/ws/watch") as open_tab:
        assert open_tab.receive_json() == running
        assert open_tab.receive_json()["type"] == "event"
        assert client.post("/api/watch/stop").json()["running"] is False
        assert client.get("/api/status").json()["running"] is False

        with client.websocket_connect("/ws/watch") as new_tab:
            # Nothing is replayed: after the connect status, the next
            # frame is the next session's "running", ahead of its own
            # first event -- not the stopped session's last one.
            assert new_tab.receive_json() == stopped
            client.post("/api/console", json={"demo": True})
            assert client.post("/api/watch/start",
                               json={"source": "console", "interval": 5.0}).status_code == 200
            assert [f["type"] for f in until_baseline(new_tab)] == ["status", "event"]

        # The tab that was already open heard the stop and the start, not
        # only the one that pressed them (one event may have been in
        # flight when Stop landed).
        statuses = [f for f in until_baseline(open_tab) if f["type"] == "status"]
        assert statuses == [stopped, running]
    client.post("/api/watch/stop")


def test_watch_js_does_not_take_an_event_as_proof_of_running(client):
    """The page half of the same fix, which the Python suite cannot run:
    an event while the server last said "not running" is dropped before
    it can set the page running."""
    js = client.get("/static/watch.js").text
    on_event = js[js.index('payload.type === "event"'):js.index('payload.type === "error"')]
    assert on_event.index("if (serverRunning === false) return;") < on_event.index("setRunningUI(true)")
    assert "serverRunning = !!payload.running;" in js
    assert "serverRunning = !!status.running;" in js


# ======================================================================
# Scoped names (`BUS Drums`), resolved once at Start (the maintainer, 2026-10-01)
# ======================================================================


def test_demo_start_resolves_scoped_names_and_says_so(client, tmp_path, monkeypatch):
    """The Demo rig has a bus named Drums and a Main named PA; each scoped
    name resolves at Start, the INFO is in the baseline's notes (not a row in the table), and a finding arrives against the
    resolved position. The rig is the frozen copy of the 7-channel Demo
    rig (`tests/fixtures/old-demo-rig/`), not the shipped one, whose
    contents change with the Demo show."""
    from atoo import webui
    monkeypatch.setattr(webui, "_DEMO_DIR", FIXTURES / "old-demo-rig")
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"watch_conditions": [
        dict(HAND, id="drums-bus-muted", channel="BUS Drums", field="muted", value=True),
        dict(HAND, id="pa-muted", channel="MAIN PA", field="muted", value=True),
        dict(HAND, id="horns", channel="BUS Horns", field="muted", value=True),
    ]}))
    client.post("/api/console", json={"demo": True})
    r = client.post("/api/watch/start", json={
        "source": "console", "interval": 0.1, "watch_conditions_path": str(path)})
    assert r.status_code == 200
    with client.websocket_connect("/ws/watch") as ws:
        ws.receive_json()  # status
        baseline = ws.receive_json()
    client.post("/api/watch/stop")
    assert baseline["baseline"] is True
    rows = {f["rule_id"]: f for f in baseline["all_findings"]}
    notes: dict = {}
    for n in baseline["notes"]:
        notes.setdefault(n["rule_id"], []).append(n)
    assert rows["WATCH:drums-bus-muted"]["addresses"] == ["/bus/1/mute"]
    [drums] = notes["WATCH:drums-bus-muted"]
    assert drums["detail"].startswith("BUS Drums resolved to BUS 1 at Start")
    assert (drums["group"], drums["summary"]) == ("Resolved at Start", "BUS Drums → BUS 1")
    assert rows["WATCH:pa-muted"]["addresses"] == ["/main/1/mute"]
    [pa] = notes["WATCH:pa-muted"]
    assert pa["detail"].startswith("MAIN PA resolved to MAIN 1 at Start")
    # Not watched: a warning note, and no row.
    assert "WATCH:horns" not in rows
    [horns] = notes["WATCH:horns"]
    assert horns["severity"] == "warning" and horns["group"] == "Not watched"
    assert "matches no BUS" in horns["detail"]


@pytest.mark.parametrize("channel, expected", [
    ("MAIN PA", [f"/main/{n}/name" for n in range(1, 5)]),
    ("BUS Drums", None),
])
def test_console_start_reads_main_names_only_when_a_scoped_main_needs_them(
        monkeypatch, tmp_path, channel, expected):
    from atoo import webui

    seen: list[dict] = []

    def factory(ip, *, port=2223, timeout=1.0, read_kwargs=None, **extra):
        seen.append(extra)
        raise webui.ConsoleUnreachable("test: stop here")

    monkeypatch.setattr(webui, "console_provider_factory", factory)
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"watch_conditions": [dict(HAND, channel=channel)]}))
    with fastapi_testclient.TestClient(create_app()) as c:
        r = c.post("/api/watch/start", json={
            "source": "console", "console": "192.0.2.1", "interval": 0.1,
            "watch_conditions_path": str(path)})
        assert r.status_code == 200
        deadline = time.monotonic() + 5
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
        c.post("/api/watch/stop")
    assert seen
    assert seen[0].get("start_name_addresses") == expected


# ======================================================================
# The maintainer, 2026-10-01: a saved list reaches a running watch; Start and
# Stop leave nothing of the last session behind; the Watch page has no
# findings dock; findings sort by severity, newest first.
# ======================================================================


def _events_until(ws, predicate, limit=60):
    for _ in range(limit):
        payload = ws.receive_json()
        if predicate(payload):
            return payload
    raise AssertionError("the expected watch event never arrived")


def _rig_on_an_address(client, monkeypatch):
    """A regular show's watch, with the Demo rig standing in for the desk
    at the bar's address. Demo is the read-only demo show,
    whose watch.json cannot be saved -- these tests save a watched list."""
    from atoo import webui

    monkeypatch.setattr(webui, "console_provider_factory",
                        lambda *a, **k: webui.demo_provider_factory())
    assert client.post("/api/console", json={"address": "192.0.2.10"}).status_code == 200


def test_saving_the_watched_list_swaps_it_into_the_running_session(client, tmp_path, monkeypatch):
    path = tmp_path / "watch.json"
    old = dict(HAND, id="old-drums", channel="BUS 1", field="muted", value=True)
    path.write_text(json.dumps({"watch_conditions": [old]}))
    client.post("/api/watch-conditions/load", json={"path": str(path)})
    _rig_on_an_address(client, monkeypatch)
    r = client.post("/api/watch/start", json={
        "source": "console", "interval": 0.05, "watch_conditions_path": str(path)})
    assert r.status_code == 200
    try:
        with client.websocket_connect("/ws/watch") as ws:
            baseline = _events_until(ws, lambda p: p.get("baseline"))
            assert any(f["rule_id"] == "WATCH:old-drums" for f in baseline["all_findings"])
            new = dict(old, id="new-drums")
            saved = client.post("/api/watch-conditions/save", json={
                "path": str(path), "watch_conditions": [new]})
            assert saved.status_code == 200 and saved.json()["watch_reloaded"] is True
            change = _events_until(ws, lambda p: any(
                f["rule_id"] == "WATCH:new-drums" for f in p.get("new_findings", [])))
            assert any(f["rule_id"] == "WATCH:old-drums" for f in change["cleared_findings"])
    finally:
        client.post("/api/watch/stop")


def test_saving_some_other_file_leaves_the_running_watch_alone(client, tmp_path, monkeypatch):
    watched = tmp_path / "watch.json"
    watched.write_text(json.dumps({"watch_conditions": [HAND]}))
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"watch_conditions": []}))
    client.post("/api/watch-conditions/load", json={"path": str(watched)})
    _rig_on_an_address(client, monkeypatch)
    client.post("/api/watch/start", json={
        "source": "console", "interval": 0.05, "watch_conditions_path": str(watched)})
    try:
        client.post("/api/watch-conditions/load", json={"path": str(other)})
        saved = client.post("/api/watch-conditions/save", json={
            "path": str(other), "watch_conditions": [HAND]})
        assert saved.json()["watch_reloaded"] is False
    finally:
        client.post("/api/watch/stop")


def test_saving_while_not_watching_reloads_nothing(client, tmp_path):
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"watch_conditions": []}))
    client.post("/api/watch-conditions/load", json={"path": str(path)})
    saved = client.post("/api/watch-conditions/save", json={
        "path": str(path), "watch_conditions": [HAND]})
    assert saved.json()["watch_reloaded"] is False


def test_a_stopped_session_hands_nobody_its_last_event():
    """The page opened after Stop used to receive the stopped session's
    last update, showing old findings and greying Start."""
    import asyncio

    from atoo.webui import WatchSession, demo_provider_factory

    session = WatchSession()
    loop = asyncio.new_event_loop()
    try:
        session.start(loop, demo_provider_factory, 0.05, "Demo")
        deadline = time.time() + 5
        while session._last_payload is None and time.time() < deadline:
            time.sleep(0.02)
        assert session._last_payload is not None
        session.stop()
        assert session._last_payload is None
    finally:
        session.stop()
        loop.close()


def test_the_watch_page_has_no_findings_dock_and_start_resets_everything(client):
    shell = client.get("/static/shell.js").text
    assert 'dockCol.hidden = name === "watch"' in shell
    js = client.get("/static/watch.js").text
    start = js[js.index('startBtn.addEventListener("click"'):js.index('stopBtn.addEventListener("click"')]
    reset = start[:start.index('fetch("/api/watch/start"')]
    for step in ("shown = new Map();", 'lastUpdated.textContent = "";', "updateCounts();"):
        assert step in reset, step


def test_findings_sort_by_severity_then_newest_first_and_every_row_is_placed(client):
    js = client.get("/static/watch.js").text
    render = js[js.index("function renderTable()"):js.index("function clearRow(")]
    assert render.index("sa - sb") < render.index("tb - ta") < render.index("localeCompare")
    # Each row is (re)appended in sorted order, existing rows included --
    # not only a newly created one.
    loop_body = render[render.index("for (const f of rows)"):]
    assert loop_body.index("rowEls.set(key, tr);") < loop_body.index("alertBody.appendChild(tr);")
    assert render.count("alertBody.appendChild(tr);") == 1


def test_last_updated_ages_and_turns_stale_when_readings_stop(client):
    """The label was written once per reading, so it read
    "Updated just now" for ever after readings stopped. It is redrawn
    every second from the reading's time, and a running watch with no
    reading for several intervals says so."""
    js = client.get("/static/watch.js").text
    handle = js[js.index("function handleEvent("):js.index("function connectWs(")]
    assert '"Updated " + relativeTime(payload.at)' not in handle
    assert "noteReading(payload.at);" in handle and "renderLastUpdated();" in handle
    assert "setInterval(renderLastUpdated, 1000);" in js
    render = js[js.index("function renderLastUpdated()"):js.index("setInterval(renderLastUpdated")]
    assert "serverRunning === true" in render          # only while watching
    assert '"No reading for "' in render
    assert 'classList.toggle("is-stale", stale)' in render
    # The reading's own time, so a replay on reconnect does not look fresh.
    note = js[js.index("function noteReading("):js.index("function staleAfterMs(")]
    assert "Date.parse(at)" in note and "clockOffset" in note
    # Start forgets the last session's reading and starts the silence clock.
    start = js[js.index('startBtn.addEventListener("click"'):js.index('stopBtn.addEventListener("click"')]
    reset = start[:start.index('fetch("/api/watch/start"')]
    assert "lastReadingAt = null;" in reset and "waitingSince = Date.now();" in reset
    css = client.get("/static/styles.css").text
    assert "#last-updated.is-stale" in css


def test_a_clearing_row_collapses_rather_than_leaving_a_blank_gap(client):
    """`transform: scaleY(0)` does not give a table row's
    height back, so a clearing row went blank and kept its space."""
    css = client.get("/static/styles.css").text
    clearing = css[css.index("tr.row-clearing"):]
    clearing = clearing[:clearing.index("@media")]
    assert "scaleY" not in clearing
    assert "padding-top: 0" in clearing and "padding-bottom: 0" in clearing
    assert ".cell-collapse" in css and "max-height" in css[css.index(".cell-collapse"):]
    js = client.get("/static/watch.js").text
    clear = js[js.index("function clearRow("):js.index("function tick(")]
    assert '"cell-collapse"' in clear
    assert 'wrap.style.maxHeight = "0px"' in clear
    assert "tr.remove();" in clear and "renderTable();" in clear
