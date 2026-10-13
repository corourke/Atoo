"""Opening a different show drops the last show's build and apply runs
(*"The findings panel remains populated for an old show even
when we create a new show."*).

What stayed was the last build's run -- a `build.failed`, say -- because
the server kept `GET /api/build/status`'s findings across a bundle open and
setup.js put them back in the dock at every page load. Apply's last run was
the same shape. The server now forgets both on `POST /api/bundle/open`
(unless one is still running), and the two pages drop their run findings
on the same event.

Checked in Chromium: a failed build in a copy of smallband, then New
show..., then a reload -- the dock held only the new show's step 01-03
findings each time.
"""

from __future__ import annotations

import pytest

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import BuildRun, create_app  # noqa: E402

FAILED = {"severity": "error", "code": "build.failed", "message": "the last show's build"}


def _stale_runs(app):
    for runner in (app.state.build_run, app.state.apply_run):
        runner.state = "failed"
        runner.log = ["the last show's log"]
        runner.findings = [dict(FAILED)]


@pytest.fixture
def app(tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    return create_app(initial_bundle=str(first))


def test_opening_another_show_forgets_the_last_build_and_apply(app, tmp_path):
    with fastapi_testclient.TestClient(app) as client:
        _stale_runs(app)
        r = client.post("/api/bundle/open",
                        json={"directory": str(tmp_path / "second"), "create": True})
        assert r.status_code == 200
        for endpoint in ("/api/build/status", "/api/apply/status"):
            status = client.get(endpoint).json()
            assert status["state"] == "idle", endpoint
            assert status["findings"] == [], endpoint
            assert status["log"] == [], endpoint


def test_the_page_loaded_after_a_new_show_carries_no_old_run(app, tmp_path):
    with fastapi_testclient.TestClient(app) as client:
        _stale_runs(app)
        client.post("/api/bundle/open", json={"directory": str(tmp_path / "second"), "create": True})
        page = client.get("/app").text
        assert "the last show's build" not in page


def test_a_build_still_running_is_not_forgotten():
    runner = BuildRun()
    runner.state = "running"
    runner.findings = [dict(FAILED)]
    assert runner.forget() is False
    assert runner.state == "running"
    assert runner.findings == [FAILED]


def test_both_pages_drop_their_run_findings_on_a_show_change(app):
    with fastapi_testclient.TestClient(app) as client:
        setup = client.get("/static/setup.js").text
        start = setup.index("SP.onBundleChange(() => {")
        body = setup[start:setup.index("});", start)]
        assert 'if (run.state !== "running") {' in body
        assert 'run = { state: "idle" };' in body
        assert "publishRunFindings([]);" in body

        apply = client.get("/static/apply.js").text
        start = apply.index("SP.onBundleChange(() => {")
        body = apply[start:apply.index("});", start)]
        assert "publishRunFindings([]);" in body
