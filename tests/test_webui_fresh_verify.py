"""The dock's verify findings are asked again, not read from the plan.

The maintainer, 2026-10-09: *"Still getting this for matrix 4 'outputs[Phones]
-- output has no patch -- no physical socket is stated for it, so apply
has nothing to write'"* -- after `output.no-patch` had become a WARNING
with other words. The dock read the `meta.verify_findings` the build
recorded; verify's rules had changed since. Asked whether the dock
should re-check fresh, he chose it. Verify costs no model call; the
critic's and the build's own findings stay as recorded.
"""
from __future__ import annotations

import copy
import json

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()

from atoo.webui import create_app  # noqa: E402
from test_webui_apply import CLEAN_PLAN, _bundle  # noqa: E402

OLD = "output has no patch -- no physical socket is stated for it, so apply has nothing to write"


def _stale_plan():
    """A plan whose Phones matrix has no socket, carrying the ERROR an
    older verify recorded about it, and a critic note."""
    plan = copy.deepcopy(CLEAN_PLAN)
    plan["outputs"]["Phones"] = {"kind": "matrix", "index": 4, "patch": None,
                                 "fed_by": {"type": "main", "index": 1}}
    meta = plan.setdefault("meta", {})
    meta["verify_findings"] = {"errors": [{"severity": "error", "code": "output.no-patch",
                                           "where": "outputs[Phones]", "message": OLD}],
                               "warnings": [], "info": []}
    meta["critic_findings"] = [{"severity": "warning", "code": "critic.intent",
                                "where": "plan", "message": "a recorded critic note"}]
    return plan


def _findings(client):
    return client.get("/api/plan").json()["findings"]


def test_the_open_bundles_plan_is_verified_now(tmp_path):
    plan = _stale_plan()
    directory = _bundle(tmp_path, plan)
    app = create_app(initial_bundle=str(directory), initial_plan=plan,
                     initial_plan_path=str(directory / "plan.json"))
    with fastapi_testclient.TestClient(app) as client:
        findings = _findings(client)
    phones = [f for f in findings if f.get("code") == "output.no-patch"]
    assert phones and all(f["severity"] == "warning" for f in phones)
    assert not any(OLD in json.dumps(f) for f in findings)
    # The critic's note is still the recorded one.
    assert any(f.get("message") == "a recorded critic note" for f in findings)


def test_a_plan_with_no_bundle_shows_what_it_recorded(tmp_path):
    plan = _stale_plan()
    path = tmp_path / "loose.plan.json"
    path.write_text(json.dumps(plan))
    app = create_app(initial_plan=plan, initial_plan_path=str(path))
    with fastapi_testclient.TestClient(app) as client:
        findings = _findings(client)
    assert any(f.get("code") == "output.no-patch" and f["severity"] == "error" for f in findings)


def test_step_04s_verdict_is_todays_too(tmp_path):
    """The maintainer's screenshot, 2026-10-09: "BLOCKED -- DO NOT APPLY, 1
    error(s)" beside a dock with no error -- the badge read the verdict the
    build recorded (`meta.verify_at_generation`)."""
    plan = _stale_plan()
    plan["meta"]["verify_at_generation"] = {"skipped": False, "ok": False, "error_count": 1,
                                            "warning_count": 0, "summary": "BLOCKED -- do not apply"}
    directory = _bundle(tmp_path, plan)
    app = create_app(initial_bundle=str(directory), initial_plan=plan,
                     initial_plan_path=str(directory / "plan.json"))
    with fastapi_testclient.TestClient(app) as client:
        body = client.get("/api/plan").json()
        js = client.get("/static/setup.js").text
    assert body["verify_now"]["ok"] is True and body["verify_now"]["error_count"] == 0
    assert "const v = (current && current.verify_now) || meta.verify_at_generation;" in js


def test_a_build_note_on_an_out_of_date_plan_says_so(tmp_path):
    """The maintainer, 2026-10-09: a `reply.socket-skipped` note about OH L+R
    stayed after he moved channels on the input list. It was true of the
    plan as built; the dock now says so when the plan is older than its
    inputs -- once, in the verdict: each note is marked
    `stale` and its own words are left as they were."""
    plan = _stale_plan()
    plan["meta"]["build_findings"] = [{"severity": "info", "code": "reply.socket-skipped",
                                       "where": "channels[OH L+R]", "message": "A 6 left empty"}]
    from atoo import conventions_ref

    directory = _bundle(tmp_path, plan, with_input_list=True)
    # The plan records the input list it was built from, as a build does.
    plan["meta"]["input_list"] = {"path": str(directory / "input.csv"),
                                  "bundle_relative_path": "input.csv",
                                  "sha256": conventions_ref.file_sha256(directory / "input.csv")}
    (directory / "plan.json").write_text(json.dumps(plan))
    app = create_app(initial_bundle=str(directory), initial_plan=plan,
                     initial_plan_path=str(directory / "plan.json"))
    with fastapi_testclient.TestClient(app) as client:
        before = client.get("/api/plan").json()["findings"]
        [note] = [f for f in before if f.get("code") == "reply.socket-skipped"]
        assert "stale" not in note, "a plan its input list still matches is not marked"
        # Edit the input list after the build: the plan is now older than it.
        (directory / "input.csv").write_text((directory / "input.csv").read_text() + "\n")
        after = client.get("/api/plan").json()["findings"]
    [edited] = [f for f in after if f.get("code") == "reply.socket-skipped"]
    assert edited["stale"] is True and edited["message"] == "A 6 left empty"
    # Verify's own findings are fresh and are not marked.
    assert not any(f.get("stale") for f in after if f.get("source") == "verify")
