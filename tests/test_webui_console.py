"""The bundle bar's editable console (the maintainer, 2026-09-24).

Asked whether the Apply screen should get the mockup's IP/port/timeout
fields, the maintainer chose: *"Editable in the bundle bar only -- and the reason
is that you might generate a plan, and want to apply it to more than one
console, ex: primary console wing compact, backup console wing rack (both
have similar I/O.)"*

So there is ONE address, changed with `POST /api/console`, and every
desk-facing endpoint uses it: Ping, Apply, Amend, Undo and Watch. The
guards are what these tests are weighted towards:

* an edit while a write is running is refused -- one runner carries apply,
  amend and undo, and a write never switches desks part way through;
* a page naming one desk cannot confirm a write once the bar names another
  (`expected_console`);
* an amend preview against desk A never arms a write to desk B -- the
  review key carries the console (the model is the key).

**No test here touches a real console**: `WingConsole` is replaced by the
fakes `test_webui_apply.py` and `test_webui_amend.py` already use, and no
test reads a bundle under `examples/`.
"""

from __future__ import annotations

import json
import threading

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

import atoo.console as console_module  # noqa: E402
from atoo import journal_stack  # noqa: E402
from atoo import webui  # noqa: E402
from atoo.console import OscReply  # noqa: E402
from atoo.webui import CONSOLE_SET_HERE, create_app  # noqa: E402
import test_webui_amend as amend_tests  # noqa: E402
import test_webui_apply as apply_tests  # noqa: E402
from webui_page import armed  # noqa: E402

PRIMARY = "198.51.100.9"
BACKUP = "198.51.100.7"
CONSOLE = {"address": PRIMARY, "address_source": "ATOO_CONSOLE",
           "port": 2223, "port_source": None, "timeout": 1.0, "timeout_source": None}
IDENTITIES = {PRIMARY: "WING,198.51.100.9,PRIMARY,wing-compact,SER-P,3.1",
              BACKUP: "WING,198.51.100.7,BACKUP,wing-compact,SER-B,3.1"}


class _ApplyDesk(apply_tests._Desk):
    """Apply's fake desk, answering `/?` as whichever desk is at the
    address it was opened on -- two desks, two serials."""

    def identity(self):
        return OscReply(address="/?", typetag="s", args=[IDENTITIES[self.address]])


@pytest.fixture
def apply_desk(monkeypatch):
    _ApplyDesk.next_state = apply_tests._seeded_state(apply_tests.CLEAN_PLAN)
    _ApplyDesk.reject = set()
    _ApplyDesk.made = []
    monkeypatch.setattr(console_module, "WingConsole", _ApplyDesk)
    return _ApplyDesk


@pytest.fixture
def apply_client(tmp_path, apply_desk):
    directory = apply_tests._bundle(tmp_path, apply_tests.CLEAN_PLAN)
    with fastapi_testclient.TestClient(apply_tests._app(directory, console=CONSOLE)) as c:
        c.bundle_directory = directory
        yield c


def _set(c, address, **extra):
    return c.post("/api/console", json={"address": address, **extra})


# ======================================================================
# GET / POST /api/console
# ======================================================================


def test_the_console_endpoint_answers_what_the_bar_shows():
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        assert c.get("/api/console").json() == CONSOLE


def test_an_edit_replaces_the_address_and_says_set_here():
    """#137's rule turned round: an address typed into the bar says so."""
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        r = _set(c, BACKUP)
        assert r.status_code == 200
        body = r.json()
        assert body["address"] == BACKUP and body["address_source"] == CONSOLE_SET_HERE
        # Port omitted: the one in force stays, with its own provenance.
        assert body["port"] == 2223 and body["port_source"] is None
        # The answer is the console plus the bundle it left open.
        assert body.pop("bundle") is None and body.pop("bundle_changed") is False
        assert c.get("/api/console").json() == body
        # ...and the page served from now on is seeded with it.
        html = c.get("/").text
        blob = html.index('id="initial-shell"')
        startup = json.loads(html[html.index(">", blob) + 1:html.index("</script>", blob)])
        assert startup["console"]["address"] == BACKUP


def test_an_edit_can_set_the_port_too():
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        body = _set(c, BACKUP, port=9000).json()
    assert body["port"] == 9000 and body["port_source"] == CONSOLE_SET_HERE


def test_an_edit_with_no_console_configured_at_all_fills_the_rest_in():
    """Absent case: `atoo ui` started with no ATOO_CONSOLE and no
    config file. The bar is where one gets set, without a restart."""
    with fastapi_testclient.TestClient(create_app()) as c:
        assert c.get("/api/console").json() == {}
        body = _set(c, BACKUP).json()
    assert body.pop("bundle") is None and body.pop("bundle_changed") is False
    assert body == {"address": BACKUP, "address_source": CONSOLE_SET_HERE,
                    "port": 2223, "port_source": None, "timeout": 1.0, "timeout_source": None}


@pytest.mark.parametrize("address", ["", "   ", "198.51.100.7 --confirm", "a/b", "x" * 300])
def test_an_address_that_is_not_one_is_refused(address):
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        r = _set(c, address)
        assert r.status_code == 400
        assert c.get("/api/console").json()["address"] == PRIMARY


def test_a_port_out_of_range_is_refused():
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        assert _set(c, BACKUP, port=70000).status_code == 400
        assert c.get("/api/console").json()["address"] == PRIMARY


# ======================================================================
# Every desk-facing endpoint uses the bar's address
# ======================================================================


def test_ping_uses_the_edited_address_and_remembers_what_answered(apply_desk):
    """The bar's Ping sends `{}`: "the console in the bar"."""
    with fastapi_testclient.TestClient(create_app(initial_console=dict(CONSOLE))) as c:
        _set(c, BACKUP)
        body = c.post("/api/ping", json={}).json()
        assert body["ok"] and body["address"] == BACKUP
        assert body["address_source"] == CONSOLE_SET_HERE
        assert c.app.state.console_identity["identity"] == [IDENTITIES[BACKUP]]
        # An edit forgets it: what answered at the old address says
        # nothing about the new one.
        _set(c, PRIMARY)
        assert c.app.state.console_identity is None
    assert [d.address for d in apply_desk.made] == [BACKUP]


def test_apply_writes_to_the_edited_address(apply_client, apply_desk):
    _set(apply_client, BACKUP)
    r = apply_client.post("/api/apply/run", json=armed(
        apply_client, "/api/apply/run", expected_console=f"{BACKUP}:2223"))
    assert r.status_code == 200, r.json()
    status = apply_tests._wait(apply_client)
    assert status["exit_code"] == 0, status["log"]
    assert status["command"][status["command"].index("--console") + 1] == BACKUP
    assert {d.address for d in apply_desk.made} == {BACKUP}
    entry = journal_stack.entries(apply_client.bundle_directory)[-1]
    assert entry.desk["serial"] == "SER-B" and entry.desk["address"] == BACKUP


RACK = "198.51.100.8"
FULL = "198.51.100.10"


def _confirm_on(c, address):
    _set(c, address)
    r = c.post("/api/apply/run", json=armed(
        c, "/api/apply/run", expected_console=f"{address}:2223"))
    assert r.status_code == 200, r.json()
    return apply_tests._wait(c)


def test_a_compact_plan_applies_to_a_rack_from_the_apply_screen(
        apply_client, apply_desk, monkeypatch):
    """The maintainer's own example, end to end through the screen: the primary is
    a Compact, the backup a Rack. Before 2026-09-24 the Apply screen had no
    way past the model check at all. Now it writes, and the INFO naming
    both models reaches the findings dock, not only the run log."""
    monkeypatch.setitem(IDENTITIES, RACK, "WING,198.51.100.8,RACK,wing-rack,SER-R,3.1")
    status = _confirm_on(apply_client, RACK)
    assert status["exit_code"] == 0, status["log"]
    assert {d.address for d in apply_desk.made} == {RACK}
    assert apply_tests._writes(apply_desk) > 0
    [info] = [f for f in status["findings"] if f["code"] == "apply.cross-model"]
    assert info["severity"] == "info"
    assert "WING Compact" in info["message"] and "WING Rack" in info["message"]
    assert "Every socket the plan patches exists on this desk" in info["message"]
    assert status["result"]["model_check"]["desk_model"] == "wing-rack"


def test_the_apply_screen_no_longer_says_a_different_model_is_refused(apply_client):
    """The served asset, because the Python suite cannot see the page
    (`CLAUDE.md`): the console line used to promise a refusal the command
    no longer makes. The rule is in the Apply head's '?'."""
    js = apply_client.get("/static/apply.js").text
    assert "refuses a plan built for a different model" not in js
    html = apply_client.get("/static/shell.html").text
    assert "applied if this desk has every socket it patches" in html


def test_an_unmeasured_desk_model_reaches_the_dock_as_a_warning(
        apply_client, apply_desk, monkeypatch):
    monkeypatch.setitem(IDENTITIES, RACK, "WING,198.51.100.8,RACK,wing-racksize,SER-R,3.1")
    status = _confirm_on(apply_client, RACK)
    assert status["exit_code"] == 0, status["log"]
    [warning] = [f for f in status["findings"] if f["code"] == "apply.desk-model-unmeasured"]
    assert warning["severity"] == "warning" and "'wing-racksize'" in warning["message"]
    entry = journal_stack.entries(apply_client.bundle_directory)[-1]
    assert entry.desk["model_token"] == "wing-racksize"


def test_a_socket_the_desk_lacks_is_refused_from_the_apply_screen(
        apply_client, apply_desk, monkeypatch):
    monkeypatch.setitem(IDENTITIES, FULL, "WING,198.51.100.10,FOH,wing-fullsize,SER-F,3.1")
    plan_path = apply_client.bundle_directory / "plan.json"
    plan = json.loads(plan_path.read_text())
    plan["channels"][0]["patch"] = {"group": "LCL", "sockets": [20], "stated": True}
    plan_path.write_text(json.dumps(plan))
    status = _confirm_on(apply_client, FULL)
    assert status["exit_code"] == 2, status["log"]
    assert apply_tests._writes(apply_desk) == 0
    # Exit 2 with no journal: the screen shows the command's own words in
    # the run log, as it does for the verify gate's refusal.
    log = "\n".join(status["log"])
    assert "LCL 20 does not exist on the WING (full-size console)" in log
    assert status["result"] is None


def test_undo_uses_the_edited_address(apply_client, apply_desk):
    _set(apply_client, BACKUP)
    apply_client.post("/api/undo/run", json={})
    status = apply_tests._wait(apply_client)
    assert status["command"][status["command"].index("--console") + 1] == BACKUP


def test_watch_follows_the_bar_when_the_page_sends_no_console(monkeypatch):
    """The Watch form has no address boxes any more; Start sends none, and
    the server watches the bar's desk -- port and timeout included."""
    seen = []

    def factory(address, port=2223, timeout=1.0, read_kwargs=None, name_refresh=1):
        seen.append((address, port, timeout))
        return (lambda: (_ for _ in ()).throw(webui.ConsoleUnreachable("fake"))), None

    monkeypatch.setattr(webui, "console_provider_factory", factory)
    console = dict(CONSOLE, timeout=2.5, timeout_source="ATOO_CONSOLE_TIMEOUT")
    with fastapi_testclient.TestClient(create_app(initial_console=console)) as c:
        _set(c, BACKUP, port=9000)
        r = c.post("/api/watch/start", json={"source": "console"})
        assert r.status_code == 200, r.json()
        assert r.json()["label"] == f"{BACKUP}:9000"
        c.post("/api/watch/stop")
    assert seen and seen[0] == (BACKUP, 9000, 2.5)


def test_watch_with_no_console_anywhere_says_where_to_set_one():
    with fastapi_testclient.TestClient(create_app()) as c:
        r = c.post("/api/watch/start", json={"source": "console"})
    assert r.status_code == 400 and "bundle bar" in r.json()["error"]


def test_a_write_with_no_console_anywhere_says_the_bar_is_where(tmp_path, apply_desk):
    directory = apply_tests._bundle(tmp_path, apply_tests.CLEAN_PLAN)
    with fastapi_testclient.TestClient(apply_tests._app(directory, console=None)) as c:
        for url in ("/api/apply/run", "/api/undo/run"):
            r = c.post(url, json={})
            assert r.status_code == 400 and "bundle bar" in r.json()["error"], url
    assert apply_desk.made == []


# ======================================================================
# An edit while a write is running is refused
# ======================================================================


class _SlowDesk(_ApplyDesk):
    """Holds the run at its first `/?` until the test lets it go, so the
    runner is provably `running` while the edit is attempted."""

    gate = threading.Event()
    reached = threading.Event()

    def identity(self):
        type(self).reached.set()
        type(self).gate.wait(20)
        return super().identity()


def test_changing_the_console_while_a_write_runs_is_refused(tmp_path, monkeypatch):
    """One runner, `apply_run`, carries apply, amend and undo. A write must
    never switch desks part way through, so the bar cannot move while one
    is running -- checked under the same lock the write started under.

    Mutation-checked: delete the `apply_run.running` refusal in
    `api_console_set` and this changes the bar under a running apply."""
    _SlowDesk.next_state = apply_tests._seeded_state(apply_tests.CLEAN_PLAN)
    _SlowDesk.reject, _SlowDesk.made = set(), []
    _SlowDesk.gate, _SlowDesk.reached = threading.Event(), threading.Event()
    monkeypatch.setattr(console_module, "WingConsole", _SlowDesk)
    directory = apply_tests._bundle(tmp_path, apply_tests.CLEAN_PLAN)
    with fastapi_testclient.TestClient(apply_tests._app(directory, console=CONSOLE)) as c:
        try:
            r = c.post("/api/apply/run", json=armed(c, "/api/apply/run"))
            assert r.status_code == 200, r.json()
            assert _SlowDesk.reached.wait(20), "the apply never reached the desk"
            refused = _set(c, BACKUP)
            assert refused.status_code == 409
            assert "running" in refused.json()["error"] and PRIMARY in refused.json()["error"]
            assert c.get("/api/console").json()["address"] == PRIMARY
        finally:
            _SlowDesk.gate.set()
        status = apply_tests._wait(c)
        assert status["exit_code"] == 0, status["log"]
        assert {d.address for d in _SlowDesk.made} == {PRIMARY}
        # Once it has finished, the bar is free again.
        assert _set(c, BACKUP).status_code == 200


# ======================================================================
# A page naming one desk cannot confirm a write to another
# ======================================================================


def test_a_stale_page_cannot_confirm_an_apply_to_a_desk_it_does_not_name(
        apply_client, apply_desk):
    """A tab left open on the primary while the bar was moved to the
    backup in another. Its Apply button still says "Writing to
    198.51.100.9:2223"; the write is refused rather than landing on the backup.

    Mutation-checked: make `_stale_page` return None and this writes."""
    _set(apply_client, BACKUP)
    r = apply_client.post("/api/apply/run", json=armed(
        apply_client, "/api/apply/run", expected_console=f"{PRIMARY}:2223"))
    assert r.status_code == 409
    assert BACKUP in r.json()["error"] and PRIMARY in r.json()["error"]
    assert apply_client.get("/api/apply/status").json()["state"] == "idle"
    assert apply_tests._writes(apply_desk) == 0


def test_a_stale_page_cannot_confirm_an_undo_either(apply_client, apply_desk):
    _set(apply_client, BACKUP)
    r = apply_client.post("/api/undo/run", json=armed(
        apply_client, "/api/undo/run", expected_console=f"{PRIMARY}:2223"))
    assert r.status_code == 409
    assert apply_client.get("/api/apply/status").json()["state"] == "idle"


def test_a_stale_page_may_still_preview(apply_client, apply_desk):
    """A preview writes nothing, and its log names the desk it read."""
    _set(apply_client, BACKUP)
    r = apply_client.post("/api/apply/run", json={"expected_console": f"{PRIMARY}:2223"})
    assert r.status_code == 200
    apply_tests._wait(apply_client)
    assert apply_tests._writes(apply_desk) == 0


# ======================================================================
# An amend preview on desk A never arms a write to desk B
# ======================================================================


@pytest.fixture
def amend_client(tmp_path, monkeypatch):
    amend_tests._Desk.made = []
    amend_tests._Desk.next_state = amend_tests._desk_state(
        amend_tests.applied_plan(), amend_tests.amended_plan())
    monkeypatch.setattr(console_module, "WingConsole", amend_tests._Desk)
    directory = amend_tests._bundle(tmp_path)
    with fastapi_testclient.TestClient(amend_tests._app(directory, console=CONSOLE)) as c:
        c.bundle_directory = directory
        yield c


def test_a_preview_on_one_desk_never_arms_a_write_to_another(amend_client):
    """The review key, with the console in it. The preview read the
    PRIMARY's strips; the bar then moves to the backup, whose strips nobody
    has read. The write is refused -- sent WITHOUT `expected_console`, so
    it is the key and nothing else that refuses it.

    Mutation-checked: drop the console from `_amend_key` and this writes
    the amendment to the backup."""
    status = amend_tests._preview(amend_client)
    assert status["exit_code"] == 0, status["log"]
    _set(amend_client, BACKUP)
    written = len(amend_tests._writes(amend_tests._Desk))
    r = amend_client.post("/api/amend/run", json=armed(amend_client, "/api/amend/run"))
    assert r.status_code == 409 and "same console" in r.json()["error"]
    assert len(amend_tests._writes(amend_tests._Desk)) == written
    assert not (amend_client.bundle_directory / "amend-journal.json").exists()


def test_back_on_the_desk_it_previewed_the_write_is_armed_again(amend_client):
    """The key is the desk, not the history of the bar: back on the
    primary, the review of the primary still stands."""
    amend_tests._preview(amend_client)
    _set(amend_client, BACKUP)
    _set(amend_client, PRIMARY)
    r = amend_client.post("/api/amend/run", json=armed(
        amend_client, "/api/amend/run", expected_console=f"{PRIMARY}:2223"))
    assert r.status_code == 200, r.json()
    status = amend_tests._wait(amend_client)
    assert status["exit_code"] == 0, status["log"]


# ======================================================================
# The journal listing, per desk
# ======================================================================


def _two_desk_bundle(directory):
    desks = {a: journal_stack.desk_from_identity([IDENTITIES[a]], a, 2223)
             for a in (PRIMARY, BACKUP)}
    ids = {}
    for address in (PRIMARY, BACKUP):
        path = directory / "apply-journal.json"
        path.write_text(json.dumps({"generated_at": "2026-09-24T00:00:00+00:00",
                                    "dry_run": False, "writes": []}))
        ids[address] = journal_stack.record(directory, "apply", path,
                                            desk=desks[address]).id
    return ids


def test_the_journal_listing_names_each_rows_desk_and_the_bars_top(apply_client):
    ids = _two_desk_bundle(apply_client.bundle_directory)
    body = apply_client.get("/api/journals").json()
    assert body["desk"]["address"] == PRIMARY and body["desk_label"]
    rows = {e["id"]: e for e in body["entries"]}
    assert rows[ids[PRIMARY]]["is_top"] and rows[ids[PRIMARY]]["on_this_desk"] is True
    assert not rows[ids[BACKUP]]["is_top"] and rows[ids[BACKUP]]["on_this_desk"] is False
    assert rows[ids[BACKUP]]["desk"]["serial"] == "SER-B"
    assert "BACKUP" in rows[ids[BACKUP]]["desk_label"]
    # The fields that were there before are all still there (the
    # console-run scripts read them).
    for key in ("id", "kind", "timestamp", "summary", "mismatches", "writes",
                "undo_of", "undone_by", "is_top", "path"):
        assert key in rows[ids[BACKUP]], key

    # Move the bar: the top moves with it.
    _set(apply_client, BACKUP)
    rows = {e["id"]: e for e in apply_client.get("/api/journals").json()["entries"]}
    assert rows[ids[BACKUP]]["is_top"] and not rows[ids[PRIMARY]]["is_top"]


def test_a_ping_lets_the_listing_match_by_serial(apply_client, apply_desk):
    """Unpinged, the bar's desk is known by its address; pinged, by the
    serial it stated -- so a row written to the primary at another address
    is still recognised as the primary's."""
    moved = journal_stack.desk_from_identity([IDENTITIES[PRIMARY]], "198.51.100.99", 2223)
    path = apply_client.bundle_directory / "apply-journal.json"
    path.write_text('{"generated_at": "2026-09-24T00:00:00+00:00", "dry_run": false, '
                    '"writes": []}')
    entry = journal_stack.record(apply_client.bundle_directory, "apply", path, desk=moved)
    rows = {e["id"]: e for e in apply_client.get("/api/journals").json()["entries"]}
    assert rows[entry.id]["on_this_desk"] is False, "by address alone it is another desk"
    apply_client.post("/api/ping", json={})
    rows = {e["id"]: e for e in apply_client.get("/api/journals").json()["entries"]}
    assert rows[entry.id]["on_this_desk"] is True and rows[entry.id]["is_top"]


def test_with_no_console_the_listing_has_no_desk(tmp_path, apply_desk):
    directory = apply_tests._bundle(tmp_path, apply_tests.CLEAN_PLAN)
    ids = _two_desk_bundle(directory)
    with fastapi_testclient.TestClient(apply_tests._app(directory, console=None)) as c:
        body = c.get("/api/journals").json()
    assert body["desk"] is None
    rows = {e["id"]: e for e in body["entries"]}
    assert rows[ids[BACKUP]]["is_top"] and rows[ids[PRIMARY]]["on_this_desk"] is None


# ======================================================================
# The served assets -- the Python suite cannot see the browser
# ======================================================================


@pytest.fixture
def assets():
    with fastapi_testclient.TestClient(create_app()) as c:
        yield c


def test_shell_js_edits_the_console_through_the_endpoint_and_tells_every_mode(assets):
    js = assets.get("/static/shell.js").text
    assert '"/api/console"' in js
    assert 'const CONSOLE_SET_HERE = "set here";' in js, (
        "shell.js's copy of webui.CONSOLE_SET_HERE has drifted")
    assert CONSOLE_SET_HERE == "set here"
    for contract in ("onConsoleChange:", "onPing:", "setConsoleLock:", "consoleLabel:",
                     "consoleProvenance:"):
        assert contract in js, f"window.Atoo has no {contract}"
    # The Change button is disabled while a write runs.
    assert "consoleChangeBtn.disabled = !!consoleLock;" in js


def test_apply_js_names_the_bars_desk_and_sends_it_with_every_write(assets):
    js = assets.get("/static/apply.js").text
    assert js.count("expected_console: deskLabel()") == 3, (
        "every write body -- apply, amend, undo -- must carry the desk the page names")
    assert "SP.consoleProvenance(desk)" in js
    assert "SP.onConsoleChange(" in js
    # A tick given for one desk is not consent to write to another.
    change = js[js.index("SP.onConsoleChange("):]
    assert "armCheckbox.checked = false;" in change[:change.index("});")]
    # The amend review the page arms for carries the desk too.
    assert "console: deskLabel()" in js
    # And the bar is locked while a run is in flight.
    assert "SP.setConsoleLock(" in js
    assert "restart atoo ui" not in js, "the old 'restart to change it' advice is untrue now"


def test_amend_js_draws_each_rows_desk(assets):
    js = assets.get("/static/amend.js").text
    for key in ("entry.desk", "entry.on_this_desk", "entry.desk_label", "stack.desk_label"):
        assert key in js, f"amend.js never reads {key}"
    html = assets.get("/static/shell.html").text
    head = html[html.index('class="journal-stack-table"'):]
    assert "<th>Desk</th>" in head[:head.index("</thead>")]
    assert 'id="journal-stack-desk"' in html
