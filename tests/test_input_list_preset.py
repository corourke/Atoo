"""The input list's optional `preset` column: *"a
preset column to the input list which would override anything in
conventions and instructions (as is currently done with patches) and in
the input step in the UI have a chooser for the preset name drawing from
the available presets."*

Every input list and plan here is built in the test; the preset library
is `tests/fixtures/presets/`. Nothing reads `examples/` (a bundle
there is a living example, not a fixture).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import generate, preset_expand
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list, rows_feeding, stated_preset
from atoo.presets import PresetLibrary
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIBRARY = PresetLibrary(FIXTURES / "presets")

ROWS = ("patch,name,category,type,model,phantom,preset,notes\n"
        "LCL 1,Kick,drums,Mic,Beta 91A,FALSE,kick-in,\n"
        "LCL 2,Snare,drums,Mic,i5,FALSE,,\n"
        "LCL 3,Keys L,keys,Instrument,,FALSE,Piano,\n"
        "LCL 4,Keys R,keys,Instrument,,FALSE,,\n"
        "LCL 5,Pad L,keys,Instrument,,FALSE,Snare,\n"
        "LCL 6,Pad R,keys,Instrument,,FALSE,H Tom,\n")


def _reply(*channels) -> dict:
    return {"channels": list(channels), "dcas": [], "mute_groups": [], "busses": [],
            "outputs": [{"name": "Main", "kind": "main",
                         "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": [], "notes": []}


def _build(reply: dict, csv: str = ROWS, findings: list | None = None) -> dict:
    return generate.generate_plan(
        "conventions", csv, provider=FakeProvider(response=json.dumps(reply)),
        console_model="wing-compact", findings=findings)


def _ch(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


def _full_reply() -> dict:
    return _reply({"input": "Kick", "processing": {"preset": "Snare"}},
                  {"input": "Snare", "processing": {"preset": "Snare"}},
                  {"input": "Keys L", "pair": "Keys R"},
                  {"input": "Pad L", "pair": "Pad R"})


# ---- the column ---------------------------------------------------------


def test_the_column_is_optional_and_read_as_written():
    rows = parse_input_list(ROWS)
    assert [r.preset for r in rows] == ["kick-in", "", "Piano", "", "Snare",
                                        "H Tom"]
    without = parse_input_list("name,category,type,phantom\nKick,drums,Mic,FALSE\n")
    assert without[0].preset == ""


def test_a_pair_takes_one_rows_preset_and_the_first_row_wins_a_disagreement():
    rows = parse_input_list(ROWS)
    by = {r.name: r for r in rows}
    channel = {"source": {"input": "Keys L", "stereo": True},
               "patch": {"group": "LCL", "sockets": [3, 4]}}
    assert [r.name for r in rows_feeding(channel, rows)] == ["Keys L", "Keys R"]
    assert stated_preset(rows_feeding(channel, rows))[0] == "Piano"
    # Only the SECOND row (the reply's `pair`) states it: still the channel's.
    channel_r = {"source": {"input": "Keys R", "stereo": True}}
    name, row, others = stated_preset(rows_feeding(channel_r, rows, by["Keys L"]))
    assert (name, row.name, others) == ("Piano", "Keys L", [])
    # Disagreeing: the first row's wins, and the other is returned.
    pad = {"source": {"input": "Pad L", "stereo": True},
           "patch": {"group": "LCL", "sockets": [5, 6]}}
    name, row, others = stated_preset(rows_feeding(pad, rows))
    assert name == "Snare" and [o.name for o in others] == ["Pad R"]


# ---- build: the list wins ----------------------------------------------


def test_the_lists_preset_replaces_the_models_and_says_so_at_info():
    findings: list = []
    plan = _build(_full_reply(), findings=findings)
    kick = _ch(plan, "Kick")
    assert kick["processing"]["preset"] == "kick-in"
    assert kick["provenance"]["preset"] == "Input list preset column: 'kick-in' (Kick)"
    info = [f for f in findings if f.code == "reply.preset-from-input-list"]
    assert len(info) == 1 and info[0].severity.value == "info"
    assert "'Snare'" in info[0].message and "'kick-in'" in info[0].message
    # A row stating none leaves the model's choice alone.
    assert _ch(plan, "Snare")["processing"]["preset"] == "Snare"
    assert "preset" not in _ch(plan, "Snare")["provenance"]


def test_a_stereo_pair_gets_its_rows_preset_and_a_disagreement_is_cited():
    findings: list = []
    plan = _build(_full_reply(), findings=findings)
    assert _ch(plan, "Keys L")["processing"]["preset"] == "Piano"
    pad = _ch(plan, "Pad L")
    assert pad["processing"]["preset"] == "Snare"
    assert "Pad R says 'H Tom'" in pad["provenance"]["preset"]
    # Setting a preset the model left empty is not a replacement: no INFO.
    assert not any("Keys" in f.where for f in findings if f.code == "reply.preset-from-input-list")


def test_the_same_name_spelled_differently_is_not_announced_as_a_replacement():
    findings: list = []
    plan = _build(_reply({"input": "Kick", "processing": {"preset": "Kick In"}},
                         {"input": "Snare"}, {"input": "Keys L", "pair": "Keys R"},
                         {"input": "Pad L", "pair": "Pad R"}), findings=findings)
    assert _ch(plan, "Kick")["processing"]["preset"] == "kick-in"
    assert not [f for f in findings if f.code == "reply.preset-from-input-list"]


def test_the_stated_name_is_expanded_from_the_library_forgivingly():
    plan = _build(_full_reply())
    findings = preset_expand.expand_plan(plan, LIBRARY)
    values = _ch(plan, "Kick")["processing"]["preset_values"]
    assert values["preset"] == "Kick In" and values["leaves"]
    assert any(f.code == "preset.expanded" for f in findings)


def test_a_list_without_the_column_builds_as_before():
    csv = "name,category,type,phantom\nKick,drums,Mic,FALSE\n"
    plan = _build(_reply({"input": "Kick", "processing": {"preset": "Snare"}}), csv=csv)
    assert _ch(plan, "Kick")["processing"]["preset"] == "Snare"


# ---- verify ---------------------------------------------------------------


def _codes(result, code):
    return [f for f in result.findings if f.code == code]


def test_verify_warns_when_the_plan_disagrees_with_the_list():
    plan = _build(_full_reply())
    rows = parse_input_list(ROWS)
    assert not _codes(verify_plan(plan, rows, presets=LIBRARY), "preset.contradicts-input-list")
    _ch(plan, "Kick")["processing"]["preset"] = "Snare"
    _ch(plan, "Keys L")["processing"]["preset"] = None
    found = _codes(verify_plan(plan, rows, presets=LIBRARY), "preset.contradicts-input-list")
    assert {f.where for f in found} == {"channels[Kick].processing.preset",
                                         "channels[Keys L].processing.preset"}
    assert all(f.severity.value == "warning" for f in found)


def test_verify_warns_about_a_pair_whose_rows_disagree():
    plan = _build(_full_reply())
    found = _codes(verify_plan(plan, parse_input_list(ROWS), presets=LIBRARY),
                   "preset.input-list-pair-disagrees")
    assert len(found) == 1 and found[0].severity.value == "warning"
    assert "'Pad R' says 'H Tom'" in found[0].message


def test_a_stated_name_the_library_has_not_got_is_preset_unknown():
    csv = ROWS.replace("kick-in", "Kick D6")
    plan = _build(_full_reply(), csv=csv)
    preset_expand.expand_plan(plan, LIBRARY)
    found = _codes(verify_plan(plan, parse_input_list(csv), presets=LIBRARY), "preset.unknown")
    assert [f.where for f in found] == ["channels[Kick]"] and "'Kick D6'" in found[0].message


# ---- the Setup UI -------------------------------------------------------

from conftest import require_fastapi_testclient  # noqa: E402

fastapi_testclient = require_fastapi_testclient()
from atoo.webui import create_app  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home with no ~/.atoo.config, so the real one never leaks in."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def _bundle(tmp_path, csv):
    directory = tmp_path / "show"
    directory.mkdir()
    (directory / "input.csv").write_text(csv)
    return directory


def test_the_presets_endpoint_lists_the_library_names(tmp_path, home):
    app = create_app(initial_presets=str(FIXTURES / "presets"))
    with fastapi_testclient.TestClient(app) as c:
        body = c.get("/api/build/presets").json()
    assert body["configured"] is True and body["source"] == "--presets"
    assert body["names"] == sorted(LIBRARY.names(), key=str.casefold)
    assert body["error"] is None


def test_the_presets_endpoint_falls_back_to_the_config_default(tmp_path, home):
    (home / ".atoo.config").write_text(f'[presets]\ndefault = "{FIXTURES / "presets"}"\n')
    with fastapi_testclient.TestClient(create_app()) as c:
        body = c.get("/api/build/presets").json()
    assert body["configured"] is True and "Kick In" in body["names"]
    assert body["source"].startswith("[presets] default")


def test_the_presets_endpoint_with_no_library_is_a_state_not_an_error(tmp_path, home):
    with fastapi_testclient.TestClient(create_app()) as c:
        r = c.get("/api/build/presets")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "library": None, "source": None, "names": [],
                        "error": None}
    with fastapi_testclient.TestClient(create_app(initial_presets=str(tmp_path / "nope"))) as c:
        body = c.get("/api/build/presets").json()
    assert body["configured"] is True and body["names"] == [] and "does not exist" in body["error"]


def _save(c, directory, rows):
    source = c.get("/api/build/sources").json()["input_list"]
    return c.post("/api/build/input-list/save", json={
        "expected_path": source["path"], "expected_sha256": source["sha256"],
        "expected_bundle": str(directory), "rows": rows})


def test_saving_a_preset_adds_the_column_only_when_one_is_set(tmp_path, home):
    csv = "patch,name,category,type,model,phantom,notes\nLCL 1,Kick,drums,Mic,,FALSE,\n"
    directory = _bundle(tmp_path, csv)
    with fastapi_testclient.TestClient(create_app(initial_bundle=str(directory))) as c:
        assert c.get("/api/build/sources").json()["input_list"]["columns"][-2:] == \
            ["preset", "notes"]
        # An edit that sets no preset leaves the header as it was.
        assert _save(c, directory, [{"line": 0, "values": {"model": "D6", "preset": ""}}]) \
            .status_code == 200
        assert (directory / "input.csv").read_text().splitlines()[0] == \
            "patch,name,category,type,model,phantom,notes"
        r = _save(c, directory, [{"line": 0, "values": {"preset": "Kick In"}}])
        assert r.status_code == 200, r.json()
        assert r.json()["input_list"]["rows"][0]["preset"] == "Kick In"
    assert (directory / "input.csv").read_text().splitlines() == [
        "patch,name,category,type,model,phantom,notes,preset",
        "LCL 1,Kick,drums,Mic,D6,FALSE,,Kick In"]


def test_the_page_draws_the_preset_chooser(tmp_path, home):
    with fastapi_testclient.TestClient(create_app()) as c:
        js = c.get("/static/shell.js").text
        html = c.get("/").text
    assert '"/api/build/presets"' in js
    assert '"input-preset-options"' in js and '"input-preset-note"' in js
    assert '"phantom", "preset", "notes"' in js
    assert 'id="input-preset-options"' in html and ">Preset</th>" in html
