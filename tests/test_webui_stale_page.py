"""A stale page cannot write (the maintainer's desk session, 2026-09-24).

A19's script started `atoo ui` on port 8420 against one bundle copy;
A20's stopped it and started another on the same port against a DIFFERENT
copy. The browser tab A19 had opened kept showing A19's journal stack
against A20's server. As a display that is harmless -- but until this
guard, a confirmed `POST /api/apply/run` from that tab was checked only for
the desk it named, so it would have written a plan.json nobody on that page
had reviewed.

Two halves, both tested here:

* **The server refuses** a confirmed apply, amend or undo whose page shows
  a different bundle, verified a different plan.json, drew a different
  amend review, or shows a different journal-stack top than the server
  would act on -- and one that does not say (a page from before this
  guard). 409, `stale` naming what was wrong, nothing written. A preview
  is never refused: it writes nothing.
* **The page knows**: every server process has its own `instance` id,
  embedded at first paint and answered by `GET /api/status` beside the
  bundle it has open, which shell.js polls (asserted over the served
  assets in tests/test_webui.py).

The "restart" is two `create_app()` calls, which is what a restart is to
the page: a different process on the same port.
"""

from __future__ import annotations

import json

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
import test_webui_amend as amend_tests  # noqa: E402
import test_webui_apply as apply_tests  # noqa: E402
from webui_page import armed, page_fields  # noqa: E402

APPLY = "/api/apply/run"
AMEND = "/api/amend/run"
UNDO = "/api/undo/run"


def _first_paint(c) -> dict:
    page = c.get("/").text
    start = page.index('id="initial-shell"')
    return json.loads(page[page.index(">", start) + 1:page.index("</script>", start)])


@pytest.fixture
def desk(monkeypatch):
    apply_tests._Desk.next_state = apply_tests._seeded_state(apply_tests.CLEAN_PLAN)
    apply_tests._Desk.reject = set()
    apply_tests._Desk.made = []
    monkeypatch.setattr(apply_tests.console_module, "WingConsole", apply_tests._Desk)
    return apply_tests._Desk


@pytest.fixture
def two_copies(tmp_path):
    """Two copies of one show, as A19 and A20 each made their own."""
    return (apply_tests._bundle(tmp_path, apply_tests.CLEAN_PLAN, name="a19-copy"),
            apply_tests._bundle(tmp_path, apply_tests.CLEAN_PLAN, name="a20-copy"))


def _refused(r, what):
    assert r.status_code == 409, r.json()
    body = r.json()
    assert body["stale"] == what, body
    assert "Nothing was written" in body["error"]
    return body["error"]


# ======================================================================
# The instance id, and what the page polls
# ======================================================================


def test_every_server_process_has_its_own_instance_id(tmp_path):
    with fastapi_testclient.TestClient(create_app()) as first:
        a = first.get("/api/status").json()["instance"]
        assert _first_paint(first)["instance"] == a
        assert first.get("/api/status").json()["instance"] == a, "stable for the process"
    with fastapi_testclient.TestClient(create_app()) as second:
        b = second.get("/api/status").json()["instance"]
    assert a and b and a != b


def test_status_names_the_bundle_the_server_has_open(two_copies):
    first, second = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        assert c.get("/api/status").json()["bundle"] == str(first)
        assert c.post("/api/bundle/open", json={"directory": str(second)}).status_code == 200
        assert c.get("/api/status").json()["bundle"] == str(second)
    with fastapi_testclient.TestClient(create_app()) as c:
        assert c.get("/api/status").json()["bundle"] is None


def test_the_preflight_reports_the_sha256_of_the_bytes_on_disk(two_copies):
    import hashlib

    first, _ = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        sha = c.get("/api/apply/preflight").json()["plan_sha256"]
    assert sha == hashlib.sha256((first / "plan.json").read_bytes()).hexdigest()


# ======================================================================
# Apply
# ======================================================================


def test_the_desk_session_a_tab_kept_across_a_restart_onto_another_copy(two_copies, desk):
    """The 2026-09-24 case exactly. The page was drawn by the A19 server,
    over the A19 copy; the server behind it is now A20's, over another.
    Everything the page sends is what it honestly showed -- and none of it
    is what this server would write.

    Mutation-checked: make `_stale_bundle` return None and this writes."""
    a19, a20 = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(a19)) as old_server:
        page = armed(old_server, APPLY)
        old_instance = old_server.get("/api/status").json()["instance"]
    with fastapi_testclient.TestClient(apply_tests._app(a20)) as new_server:
        assert new_server.get("/api/status").json()["instance"] != old_instance
        error = _refused(new_server.post(APPLY, json=page), "bundle")
        assert str(a19) in error and str(a20) in error
        assert new_server.get("/api/apply/status").json()["state"] == "idle"
    assert apply_tests._writes(desk) == 0
    assert not (a20 / "apply-journal.json").exists()
    assert not (a20 / "journals").exists()


def test_a_second_tab_opening_another_bundle_refuses_the_first_tabs_write(two_copies, desk):
    first, second = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        tab_one = armed(c, APPLY)
        assert c.post("/api/bundle/open", json={"directory": str(second)}).status_code == 200
        _refused(c.post(APPLY, json=tab_one), "bundle")
        assert apply_tests._writes(desk) == 0
        # The same press from a page that shows the bundle now open writes.
        r = c.post(APPLY, json=armed(c, APPLY))
        assert r.status_code == 200, r.json()
        assert apply_tests._wait(c)["exit_code"] == 0
    assert apply_tests._writes(desk) > 0


def test_a_confirmed_write_that_does_not_name_its_bundle_is_refused(two_copies, desk):
    """A page served before this guard sends no `expected_bundle` -- which
    is exactly the tab it is for. Absent is refused, not waved through."""
    first, _ = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        body = armed(c, APPLY)
        del body["expected_bundle"]
        error = _refused(c.post(APPLY, json=body), "bundle")
        assert "expected_bundle" in error
    assert apply_tests._writes(desk) == 0


def test_a_confirmed_apply_that_does_not_name_its_plan_is_refused(two_copies, desk):
    first, _ = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        body = armed(c, APPLY)
        del body["expected_plan_sha256"]
        assert "expected_plan_sha256" in _refused(c.post(APPLY, json=body), "plan")
    assert apply_tests._writes(desk) == 0


def test_a_plan_rebuilt_after_the_preflight_is_refused_not_written_unread(two_copies, desk):
    """Same bundle, same server -- but plan.json was replaced (a build in
    another tab, an editor) after this page's pre-flight read it."""
    first, _ = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        page = armed(c, APPLY)
        plan = json.loads((first / "plan.json").read_text())
        plan.setdefault("meta", {})["edited_after_the_preflight"] = True
        (first / "plan.json").write_text(json.dumps(plan, indent=2))
        error = _refused(c.post(APPLY, json=page), "plan")
        assert page["expected_plan_sha256"][:12] in error
        assert apply_tests._writes(desk) == 0
        # Re-run the pre-flight (what the page does on this 409) and it arms.
        r = c.post(APPLY, json=armed(c, APPLY))
        assert r.status_code == 200, r.json()


def test_a_preview_from_a_stale_page_is_not_refused(two_copies, desk):
    """A preview writes nothing -- the same posture `_stale_page` has."""
    first, second = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        r = c.post(APPLY, json={"confirm": False, "arm": False,
                                "expected_bundle": str(second),
                                "expected_plan_sha256": "0" * 64})
        assert r.status_code == 200, r.json()
        apply_tests._wait(c)
    assert apply_tests._writes(desk) == 0


def test_a_confirmed_apply_while_a_build_runs_is_refused(two_copies, desk):
    """The build ends by replacing plan.json, so no hash taken now says
    what the command would read a moment later."""
    first, _ = two_copies
    app = apply_tests._app(first)
    with fastapi_testclient.TestClient(app) as c:
        page = armed(c, APPLY)
        app.state.build_run.state = "running"
        try:
            r = c.post(APPLY, json=page)
        finally:
            app.state.build_run.state = "idle"
        assert r.status_code == 409 and "a build is running" in r.json()["error"]
    assert apply_tests._writes(desk) == 0


# ======================================================================
# Amend
# ======================================================================


@pytest.fixture
def amend_client(tmp_path, monkeypatch):
    amend_tests._Desk.made = []
    amend_tests._Desk.next_state = amend_tests._desk_state(
        amend_tests.applied_plan(), amend_tests.amended_plan())
    monkeypatch.setattr(amend_tests.console_module, "WingConsole", amend_tests._Desk)
    directory = amend_tests._bundle(tmp_path)
    with fastapi_testclient.TestClient(amend_tests._app(directory)) as c:
        c.bundle_directory = directory
        yield c


def test_a_writable_amend_preview_names_its_review(amend_client):
    status = amend_tests._preview(amend_client)
    assert status["exit_code"] == 0, status["log"]
    assert status["review"]["review_id"]


def test_a_later_preview_from_another_tab_voids_the_review_this_page_drew(amend_client):
    """The server arms ONE review for the whole process. Tab one previewed;
    the rebuild was then rewritten and tab two previewed it. Tab one's
    inputs now describe exactly what the server is armed for -- but the
    review on tab one's screen is the older one, so its write is refused.

    Mutation-checked: drop the `expected_review_id` comparison and this
    writes the amendment tab one never saw."""
    amend_tests._preview(amend_client)
    tab_one = armed(amend_client, AMEND)
    rebuilt = amend_client.bundle_directory / "rebuilt.plan.json"
    rebuilt.write_text(json.dumps(json.loads(rebuilt.read_text()), indent=4))
    amend_tests._preview(amend_client)            # tab two
    written = len(amend_tests._writes(amend_tests._Desk))
    _refused(amend_client.post(AMEND, json=tab_one), "review")
    assert len(amend_tests._writes(amend_tests._Desk)) == written
    assert not (amend_client.bundle_directory / "amend-journal.json").exists()
    # Tab two drew the review the server is armed for, and it writes.
    r = amend_client.post(AMEND, json=armed(amend_client, AMEND))
    assert r.status_code == 200, r.json()
    assert amend_tests._wait(amend_client)["exit_code"] == 0


def test_an_amend_write_that_does_not_name_its_review_is_refused(amend_client):
    amend_tests._preview(amend_client)
    body = armed(amend_client, AMEND)
    del body["expected_review_id"]
    assert "expected_review_id" in _refused(amend_client.post(AMEND, json=body), "review")


def test_an_amend_from_a_page_showing_another_bundle_is_refused(amend_client, tmp_path):
    amend_tests._preview(amend_client)
    body = armed(amend_client, AMEND, expected_bundle=str(tmp_path / "somewhere-else"))
    _refused(amend_client.post(AMEND, json=body), "bundle")


# ======================================================================
# Undo
# ======================================================================


def _amended(c):
    amend_tests._preview(c)
    r = c.post(AMEND, json=armed(c, AMEND))
    assert r.status_code == 200, r.json()
    assert amend_tests._wait(c)["exit_code"] == 0


def test_an_undo_that_does_not_name_the_write_it_reverses_is_refused(amend_client):
    _amended(amend_client)
    body = armed(amend_client, UNDO)
    del body["expected_undo_id"]
    written = len(amend_tests._writes(amend_tests._Desk))
    assert "expected_undo_id" in _refused(amend_client.post(UNDO, json=body), "undo")
    assert len(amend_tests._writes(amend_tests._Desk)) == written


def test_two_tabs_one_undo_the_second_press_is_refused_not_reaching_further(amend_client):
    """Both tabs show the amend as the top. Tab one undoes it. Tab two's
    press must not go on to reverse whatever is underneath -- the row it
    showed is gone."""
    _amended(amend_client)
    tab_two = armed(amend_client, UNDO)
    r = amend_client.post(UNDO, json=armed(amend_client, UNDO))      # tab one
    assert r.status_code == 200, r.json()
    assert amend_tests._wait(amend_client)["exit_code"] == 0
    written = len(amend_tests._writes(amend_tests._Desk))
    error = _refused(amend_client.post(UNDO, json=tab_two), "undo")
    assert tab_two["expected_undo_id"] in error
    assert len(amend_tests._writes(amend_tests._Desk)) == written


def test_an_undo_preview_is_not_refused_for_a_stale_id(amend_client):
    _amended(amend_client)
    r = amend_client.post(UNDO, json={"expected_undo_id": "not-the-top",
                                      "expected_bundle": "/nowhere"})
    assert r.status_code == 200, r.json()
    amend_tests._wait(amend_client)


def test_page_fields_reads_what_the_page_reads(two_copies):
    """The helper every other write test leans on reads the three values
    from the endpoints the page reads them from -- if it silently sent
    nothing, every test using it would be testing the refusal instead."""
    first, _ = two_copies
    with fastapi_testclient.TestClient(apply_tests._app(first)) as c:
        fields = page_fields(c, APPLY)
    assert fields["expected_bundle"] == str(first)
    assert len(fields["expected_plan_sha256"]) == 64
