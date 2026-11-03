"""A captured show rebuilds.

`atoo capture` writes the desk's busses into `busses.csv`; a rebuild lays
that sheet onto the plan the model built from the conventions, and the
sheet's names are the engineer's. The model's own names must not get in
the way: a channel it names "Vocals" is not the sheet's "VOCALS" bus, a bus
it puts on another number moves to the sheet's, and a bus the sheet renames
does not take over a channel's name in a `sources` cell.

The bundle is captured in the test from the church desk's frozen snapshot;
nothing under `examples/` is read.
"""

from __future__ import annotations

import copy
import json

from atoo import capture
from atoo.ai_provider import FakeProvider
from atoo.cli import main
from atoo.snapshot import load_snapshot
from tests.test_capture import CHURCH


def _model_reply(captured: dict) -> dict:
    """What a model might build for the church list from house conventions:
    every channel, a "Vocals" channel name for the vocal track, and six
    busses of its own, three of whose names the sheet gives other numbers
    or other meanings."""
    channels = []
    for ch in captured["channels"]:
        c = {"input": ch["source"]["input"], "name": ch["name"], "main_routes": [{"index": 1}]}
        if ch["source"].get("pair_input"):
            c["pair"] = ch["source"]["pair_input"]
        if c["input"] == "T Vocals":
            c["name"] = "Vocals"
        channels.append(c)
    busses = [{"name": n, "mono": False, "destination": {"type": "main", "index": 1},
               "sends": [{"from": [channels[0]["name"]], "mode": "post"}]}
              for n in ("Drums", "Drums Comp", "Vox Bus", "Keys", "Reverb", "Tracks")]
    return {"channels": channels, "busses": busses, "dcas": [], "mute_groups": [],
            "outputs": [{"name": "Main", "kind": "main", "index": 1,
                         "patch": {"group": "LCL", "sockets": [1, 2]}}],
            "unassigned_inputs": [], "notes": []}


def test_a_captured_show_rebuilds_with_its_sheets(tmp_path, monkeypatch, capsys):
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    captured = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                    captured="2026-10-24", snapshot="captures/church.snap")
    show = tmp_path / "church"
    capture.write_bundle(copy.deepcopy(captured), show, evidence_name="church.snap",
                         evidence=b"{}")
    reply = _model_reply(captured.plan)
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: FakeProvider(response=json.dumps(reply)))
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    conventions = tmp_path / "house.md"
    conventions.write_text("House conventions.\n")
    code = main(["build", "--console-model", "wing-full", "--show", str(show),
                 "--conventions", str(conventions), "--no-resolve"])
    err = capsys.readouterr().err
    assert code == 0, err
    plan = json.loads((show / "plan.json").read_text())

    # Bus 3 is the desk's VOCALS again: to Main 1, to USB 43-44, and on to
    # Broadcast Mix and Presentr, as the sheet's rows say.
    vocals = plan["busses"]["VOCALS"]
    assert vocals["index"] == 3
    assert {"type": "main", "index": 1} in vocals["destinations"]
    assert any(d.get("patch", {}).get("sockets") == [43, 44] for d in vocals["destinations"])
    assert {s["bus"] for s in vocals["bus_sends"]} == {"Broadcast Mix", "Presentr"}
    # The model's "Vocals" channel is still the channel, and sends to no bus
    # it was not given.
    assert any(ch["name"] == "Vocals" for ch in plan["channels"])

    # The model's Reverb moved to the sheet's Bus 11, said at INFO.
    assert plan["busses"]["Reverb"]["index"] == 11
    notes = [f["message"] for f in plan["meta"]["build_findings"]]
    assert any("busses.csv puts 'Reverb' on Bus 11, where the build had it on Bus 5: the sheet "
               "wins" in n for n in notes)
    # "Keys" in Keys Bus's sources is the Keys channel, not the bus the
    # sheet renamed from the model's "Keys".
    keys = next(ch for ch in plan["channels"] if ch["name"] == "Keys")
    assert any(s["bus"] == "Keys Bus" for s in keys.get("bus_sends") or [])


def test_a_bus_moved_off_a_number_the_sheet_names_otherwise_leaves_its_effects_behind():
    """Forge's real-model run of this fix: the model built Vocals on Bus 2 and
    its Vox Verb, with a reverb preset, on Bus 3. The sheet says Bus 3 is
    VOCALS, so Vocals moved there and Vox Verb took Bus 2 -- which the sheet
    calls Drums Comp, with no fx or preset of its own. The reverb was the
    model's choice for Vox Verb, so it does not stay on the desk's drum
    bus: an empty cell is the desk's, not the model's old number's."""
    from atoo import sheets

    plan = {"channels": [], "outputs": {}, "busses": {
        "Vocals": {"index": 2, "mono": False, "destination": {"type": "main", "index": 1}},
        "Vox Verb": {"index": 3, "mono": False, "role": "fx", "preset": "Vox Verb",
                     "destination": {"type": "main", "index": 1},
                     "inserts": [{"point": "pre", "model": "V-REV", "engine": 8,
                                  "parameters": {}}]}}}
    rows = [{"bus": "Bus 2", "name": "Drums Comp"}, {"bus": "Bus 3", "name": "VOCALS"}]
    result = sheets.overlay_busses(plan, rows, build=True)
    assert result.refusals == []
    busses = result.plan["busses"]
    assert busses["VOCALS"]["index"] == 3
    drums_comp = busses["Drums Comp"]
    assert drums_comp["index"] == 2
    assert not {"preset", "inserts", "role"} & set(drums_comp)
    assert ("Bus 2 is 'Drums Comp' on busses.csv, not the build's 'Vox Verb', which was moved "
            "onto it: the preset 'Vox Verb', effect V-REV, role 'fx' the build chose for "
            "'Vox Verb' are taken off, and what the sheet leaves empty is the desk's.") \
        in result.notes


def test_a_bus_the_sheet_only_renames_in_place_keeps_what_the_build_gave_it():
    from atoo import sheets

    plan = {"channels": [], "outputs": {}, "busses": {
        "Verb": {"index": 11, "mono": False, "role": "fx", "preset": "Vox Verb",
                 "destination": {"type": "main", "index": 1}}}}
    result = sheets.overlay_busses(plan, [{"bus": "Bus 11", "name": "Reverb"}], build=True)
    assert result.plan["busses"]["Reverb"]["preset"] == "Vox Verb"
