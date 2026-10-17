"""The browser's Patch API on a running strip's source: 48V is switched and
the review says so; the input is still refused, with what can be set.

`atoo patch` runs for real in the server's worker thread against
`test_webui_amend._Desk` (the frozen applied show), with a canned model
reply. No test here touches a real console, a real model, or a bundle under
`examples/`.
"""

from __future__ import annotations

import json

import pytest

from conftest import require_fastapi_testclient

fastapi_testclient = require_fastapi_testclient()

from atoo import patch  # noqa: E402
from webui_page import armed  # noqa: E402
from test_webui_amend import (_Desk, _app, _bundle, _preview, _wait, _write,  # noqa: E402,F401
                              _writes, client, desk, model)


def _change(fields: dict) -> str:
    change_set = patch.empty_change_set("Snare source")
    change_set["modify"] = [{"object": "channel", "name": "Snare", "change": "as typed",
                             "fields": fields}]
    return json.dumps(patch.validate_change_set(change_set))


def test_a_preview_marks_48v_live_and_writes_nothing(client, desk, model):
    model.response = _change({"source.phantom": True})
    plan = client.bundle_directory / "plan.json"
    before = plan.read_bytes()
    status = _preview(client, text="48V on the snare")
    assert status["exit_code"] == 0, status["log"]
    review = status["review"]
    assert not review["blocked"]
    [edit] = review["edits"]
    assert edit["switches_phantom"] is True and edit["moves_audio"] is False
    assert edit["line"].startswith("SWITCHES 48V LIVE -- channel 'Snare' on ch:2")
    assert [t["address"] for t in review["to_write"]] == ["/io/in/A/2/vph"]
    assert any("the moment it is written" in w for w in review["warnings"])
    assert _writes(desk) == [] and plan.read_bytes() == before


def test_an_armed_write_switches_48v_and_nothing_else_and_undo_takes_it_off(client, desk, model):
    model.response = _change({"source.phantom": True})
    _preview(client, text="48V on the snare")
    assert _write(client, text="48V on the snare").status_code == 200
    status = _wait(client)
    assert status["exit_code"] == 0, status["log"]
    assert [(a, p) for d in desk.made for a, p in d.set_node_calls] == [("/io/in/A/2", "vph=1")]
    assert [a for d in desk.made for a, _v, _t in d.set_param_calls] == []
    assert desk.made[-1].state["/io/in/A/2/vph"][0] == 1
    [row] = client.get("/api/journals").json()["entries"]
    assert row["kind"] == "patch"
    assert client.post("/api/undo/run", json=armed(client, "/api/undo/run")).status_code == 200
    assert _wait(client)["exit_code"] == 0
    assert desk.made[-1].state["/io/in/A/2/vph"][0] == 0


def test_a_model_is_recorded_and_the_review_has_nothing_to_write(client, desk, model):
    model.response = _change({"source.model": "SM57"})
    status = _preview(client, text="the snare mic is an SM57")
    review = status["review"]
    assert not review["blocked"] and review["to_write"] == []
    [edit] = review["edits"]
    assert edit["switches_phantom"] is False and "SWITCHES" not in edit["line"]


def test_a_ribbon_with_48v_is_a_blocked_review_that_cannot_arm(client, desk, model):
    model.response = _change({"source.model": "Royer R-121", "source.phantom": True})
    status = _preview(client, text="Royer on the snare, 48V on")
    assert status["exit_code"] == 2
    review = status["review"]
    assert review["blocked"]
    assert any("passive ribbon" in c["reason"] for c in review["changes"]
               if c["kind"] == "refused")
    assert _writes(desk) == []


def test_the_input_is_refused_and_the_refusal_names_what_can_be_set(client, desk, model):
    model.response = _change({"source.input": "Bagpipes"})
    status = _preview(client, text="the snare is the bagpipes")
    assert status["exit_code"] == 2
    [refused] = [c for c in status["review"]["changes"] if c["kind"] == "refused"]
    assert "how a running strip is recognised" in refused["reason"]
    for field in ("source.phantom", "source.model"):
        assert field in refused["reason"]


@pytest.fixture
def assets(client):
    return client


def test_the_edits_list_draws_a_phantom_switch_in_the_danger_colour(assets):
    js = assets.get("/static/amend.js").text
    assert "e.switches_phantom" in js and "isLive(e) ? \"is-live\"" in js
    assert "ed.appendChild(text(\"li\", e.moves_audio ?" not in js
