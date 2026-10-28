"""`atoo capture` (desk sheets piece 1): a desk you didn't
build, as a show bundle, with no model and nothing written to the desk.

The church desk is `tests/fixtures/church-full-2026-10-24.snap`: a full-size
WING's own snapshot (WING Edit 3.3.1), with the console's name and the one
person's name in it replaced. The small cases are built in the test.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import jsonschema
import pytest

from atoo import capture, cli, console_facts
from atoo.audit import ConsoleState, planned_unmuted, read_console_state
from atoo.input_list import parse_input_list
from atoo.plan_schema import PLAN_SCHEMA
from atoo.snapshot import load_snapshot
from atoo.verify_plan import verify_plan
from atoo.console import OscReply

CHURCH = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"


@pytest.fixture(scope="module")
def church_state() -> ConsoleState:
    return capture.state_from_snap(load_snapshot(CHURCH), "wing-full")


@pytest.fixture(scope="module")
def church(church_state) -> capture.Capture:
    return capture.capture_desk(church_state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def _bus_row(cap, which):
    return next(r for r in _rows(cap.busses_csv()) if r["bus"] == which)


# -- input.csv ------------------------------------------------------------------


def test_the_input_list_is_one_the_build_reads(church):
    rows = parse_input_list(church.input_csv())
    assert len(rows) == len(church.input_rows) == 46
    assert all(row.name for row in rows)
    kick = next(r for r in rows if r.name == "Kick")
    assert (kick.patch, kick.channel, kick.category, kick.type, kick.phantom) == (
        "AES50-A 19", ("ch", 9), "Drum LEVELS", "Mic", False)
    assert (kick.dca, kick.mute_group) == (("Drum LEVELS",), ("ALL",))


def test_a_channel_with_no_name_takes_its_sources(church):
    """Channel 20 has no name of its own; its source LCL 4 is 'MIC2'."""
    row = next(r for r in church.input_rows if r["channel"] == "20")
    assert (row["name"], row["patch"]) == ("MIC2", "LCL 4")
    assert any("CH 20 takes 'MIC2' from LCL 4" in note for note in church.notes)


def test_a_stereo_source_is_two_rows_on_one_channel(church):
    rows = [r for r in church.input_rows if r["channel"] == "Aux 4"]
    assert [(r["patch"], r["name"]) for r in rows] == [("AUX 3", "Media L"), ("AUX 4", "Media R")]


def test_type_comes_from_the_source_and_is_said(church):
    by_patch = {r["patch"]: r for r in church.input_rows}
    assert by_patch["MOD 1"]["type"] == "Line"
    assert by_patch["LCL 1"]["type"] == "Mic"
    assert any(note.startswith("type 'Line'") for note in church.notes)


def test_category_comes_from_the_first_dca_and_is_said_once(church):
    [line] = [note for note in church.notes if note.startswith("category from")]
    assert "'Drum LEVELS' for CH 9, CH 10, CH 11, CH 12, CH 13, CH 14 and CH 15" in line
    assert "'other' for CH 1, CH 2" in line


def test_a_channel_insert_goes_in_the_row_notes_and_the_plan(church):
    """The input list has no fx column, so the row's notes say
    it; the plan holds it on the channel, which Apply writes back."""
    row = next(r for r in church.input_rows if r["channel"] == "17")
    assert row["notes"] == "Inserts: GEQ (FX9, preins)"
    ch17 = next(c for c in church.plan["channels"] if (c["bank"], c["channel"]) == ("ch", 17))
    assert [(i["point"], i["model"], i["engine"]) for i in ch17["inserts"]] == [
        ("preins", "GEQ", 9)]
    assert not any("Effects inserted on channels" in note for note in church.notes)


def test_the_oscillator_is_left_out_and_said(church):
    assert not any(r["channel"] == "27" for r in church.input_rows)
    assert any("CH 27 takes OSC 1" in note for note in church.notes)


# -- busses.csv -----------------------------------------------------------------


def test_the_effect_buses_take_the_fx_role_at_info(church):
    roles = {r["bus"]: r["role"] for r in _rows(church.busses_csv())}
    assert [b for b, role in roles.items() if role == "fx"] == [
        "Bus 11", "Bus 12", "Bus 13", "Bus 14", "Bus 15", "Bus 16"]
    assert any(note.startswith("role 'fx' for BUS 11 'Reverb': BPLATE and VSS3 inserted, "
                               "100% wet") for note in church.notes)


def test_the_vocal_bus_with_a_doubler_has_no_role(church):
    """Its doubler is 36% wet: a mix with effects, not an effect return."""
    row = _bus_row(church, "Bus 3")
    assert (row["name"], row["role"], row["fx"]) == ("VOCALS", "", "DOUBLE; C5-CMB")


def test_a_matrix_row_says_what_feeds_it_and_where_it_goes(church):
    row = _bus_row(church, "Matrix 6")
    assert row["name"] == "DRUMS IEM"
    assert row["sources"].split(";") == ["DR PAD", "Kick", "Snare", "Snare Btm", "Tom",
                                         "Floor", "OH A", "OH B", "High Hat"]
    assert (row["tap"], row["outputs"], row["width"]) == ("pre", "MOD 36-37", "stereo")


def test_a_source_that_differs_from_the_tap_says_so(church):
    row = _bus_row(church, "Bus 8")
    assert row["tap"] == "post"
    assert "Crowd (pre)" in row["sources"].split(";")
    assert "Drums" in row["sources"].split(";")


def test_bus_membership_is_on_the_bus_sheet(church):
    row = _bus_row(church, "Bus 1")
    assert (row["dca"], row["mute_group"]) == ("Drum Busses;AllBand", "BAND;ALL")


def test_what_the_plan_cannot_hold_yet_is_said(church):
    """Since piece 2 the sends are in the plan; what is left is said."""
    assert not any("channel-to-Matrix" in note or "bus-to-bus" in note for note in church.notes)
    assert any("output socket(s) carry an input" in note for note in church.notes)
    assert any("GRP mode" in note for note in church.notes)


def test_the_sends_are_in_the_plan_on_their_source(church):
    """An earlier change piece 2: a channel's send to a Matrix, a bus's to a bus, and
    every Matrix feed, with its tap, on the source."""
    from atoo import plan_compat

    by_channel = {c["channel"]: c for c in church.plan["channels"] if c["bank"] == "ch"}
    assert by_channel[9]["matrix_sends"] == [
        {"matrix": "DRUMS IEM", "mode": "pre", "level_db": None}]
    assert {"bus": "Broadcast Mix", "mode": "post", "level_db": None} in \
        church.plan["busses"]["VOCALS"]["bus_sends"]
    assert church.plan["busses"]["Keys Bus"]["matrix_sends"] == [
        {"matrix": "KEYS IEM", "mode": "pre", "level_db": None}]
    assert {"matrix": "Main PA", "mode": "post", "level_db": None} in \
        church.plan["outputs"]["Main"]["matrix_sends"]
    feeds = plan_compat.matrix_feeds(church.plan)
    assert [key for _kind, key, _mode in feeds["DRUMS IEM"]] == [
        "DR PAD", "Kick", "Snare", "Snare Btm", "Tom", "Floor", "OH A", "OH B", "High Hat"]
    assert sorted(kind for kind, _key, _mode in feeds["MON SPKRS"]) == ["channel", "channel", "main"]
    assert all(out.get("fed_by") is None for out in church.plan["outputs"].values()
               if out["kind"] == "matrix")


# -- plan.json --------------------------------------------------------------------


def test_the_plan_is_a_valid_plan_of_the_desk(church):
    jsonschema.validate(church.plan, PLAN_SCHEMA)
    meta = dict(church.plan["meta"])
    assert meta.pop("socket_colours")
    assert meta == {"made_from": "snap", "captured": "2026-10-24",
                    "console_model": "wing-full", "snapshot": "captures/church.snap"}
    assert all(note["source"] == "capture" for note in church.plan["notes"])


def test_the_plan_leaves_the_mix_out(church):
    for channel in church.plan["channels"]:
        assert channel["fader"] == {"fader_db": None, "muted": None}
        assert all(send["level_db"] is None for send in channel["bus_sends"])


def test_the_plan_verifies_with_no_error(church):
    result = verify_plan(church.plan, parse_input_list(church.input_csv()))
    assert result.errors == []
    assert "input-list.column-not-followed" not in {f.code for f in result.warnings}
    assert not any(f.code.startswith("direct-output.") for f in result.findings)


def test_watching_the_captured_show_raises_nothing_above_info(church, church_state, tmp_path):
    """The point of capturing: Watch and audit with the show read the
    captured routing as asked for (R013), the splits to USB and the Dante
    module as declared, and leave the mix alone."""
    show = tmp_path / "church"
    capture.write_bundle(church, show, evidence_name="church.snap", evidence=b"{}")
    state_file = tmp_path / "church.state.json"
    state_file.write_text(json.dumps(church_state.values), encoding="utf-8")
    out = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(out):
        status = cli.main(["audit", "--state", str(state_file), "--show", str(show)])
    report = out.getvalue()
    assert status == 0, report
    assert "warning" not in report.split("\n")[1], report
    assert "[INFO] R013 Signal Split Asked For" in report


def test_a_captured_plan_leaves_mutes_to_the_desk(church, church_state):
    assert planned_unmuted(church_state, church.plan) == []
    built = dict(church.plan, meta={"console_model": "wing-full"})
    assert planned_unmuted(church_state, built)


# -- the bundle and the command ---------------------------------------------------------


def test_capture_from_a_snap_writes_the_bundle(tmp_path, capsys):
    status = cli.main(["capture", "--snap", str(CHURCH), "--console-model", "wing-full",
                       "--dir", str(tmp_path)])
    assert status == 0
    show = tmp_path / "church-full-2026-10-24"
    assert sorted(p.relative_to(show).as_posix() for p in show.rglob("*") if p.is_file()) == [
        "busses.csv", "captures/church-full-2026-10-24.snap", "input.csv", "outputs.csv",
        "plan.json", "watch.json"]
    assert (show / "captures" / CHURCH.name).read_bytes() == CHURCH.read_bytes()
    assert json.loads((show / "watch.json").read_text()) == {"version": 2, "watch_conditions": []}
    printed = capsys.readouterr().out
    assert "46 inputs on 40 channels" in printed
    assert "15 buses, 1 Mains, 5 Matrices" in printed
    assert ("147 output sockets: 123 fed straight from a source, 24 by a bus, a Main or a "
            "Matrix") in printed
    assert "Nothing was written to the desk." in printed


def test_a_taken_name_gets_a_number(tmp_path):
    args = ["capture", "--snap", str(CHURCH), "--console-model", "wing-full",
            "--dir", str(tmp_path), "--name", "church"]
    assert cli.main(args) == 0 and cli.main(args) == 0
    assert (tmp_path / "church").is_dir() and (tmp_path / "church-2").is_dir()


def test_a_snap_needs_its_model(tmp_path, capsys):
    assert cli.main(["capture", "--snap", str(CHURCH), "--dir", str(tmp_path)]) == 1
    assert "pass --console-model" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_one_source_at_a_time(tmp_path, capsys):
    assert cli.main(["capture", "--snap", str(CHURCH), "--console", "192.0.2.148",
                     "--console-model", "wing-full", "--dir", str(tmp_path)]) == 1
    assert "not both" in capsys.readouterr().err


# -- a live desk ------------------------------------------------------------------------


class _Desk:
    """Answers per-leaf GETs from a reading, as a WING does on the wire."""

    console_model = "wing-full"

    def __init__(self, values):
        self.values = values

    def get(self, address):
        if address not in self.values:
            return None
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address=address, typetag="s", args=[value])
        if isinstance(value, float):
            return OscReply(address=address, typetag="sff", args=[f"{value:g}", 0.0, value])
        wire = value - console_facts.readback_index_offset(address)
        return OscReply(address=address, typetag="sfi", args=[str(value), 0.0, wire])


def test_a_live_read_captures_the_same_bus_sheet(church, church_state):
    """The live read asks for what the sheets need: the same desk read live
    gives the same bus sheet as its snapshot."""
    desk = _Desk(church_state.values)
    state = read_console_state(desk, console_model="wing-full",
                               **capture.live_read_kwargs("wing-full"))
    for follow_up in (capture.source_mode_addresses, capture.pair_name_addresses):
        for address, _type in follow_up(state):
            state.values[address] = church_state.values[address]
    live = capture.capture_desk(state, console_model="wing-full", made_from="desk",
                                captured="2026-10-24")
    assert live.busses_csv() == church.busses_csv()
    assert live.input_csv() == church.input_csv()


# -- small desks ---------------------------------------------------------------------


def _small(**values) -> ConsoleState:
    base = {"/dca/1/name": "Drums", "/mgrp/1/name": "ALL"}
    base.update(values)
    return ConsoleState(base, console_model="wing-compact")


def test_a_name_the_desk_repeats_is_made_unique_in_the_input_list():
    state = _small(**{
        "/ch/1/name": "Acoustic", "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/name": "Acoustic", "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 2,
    })
    cap = capture.capture_desk(state, console_model="wing-compact", made_from="snap",
                               captured="2026-10-25")
    assert [r["name"] for r in cap.input_rows] == ["Acoustic", "Acoustic (CH 2)"]
    assert [c["name"] for c in cap.plan["channels"]] == ["Acoustic", "Acoustic"]
    assert any("CH 2 ('Acoustic')" in note for note in cap.notes)
    parse_input_list(cap.input_csv())


def test_a_stereo_source_with_unnamed_sockets_gets_l_and_r():
    state = _small(**{
        "/ch/3/name": "Keys", "/ch/3/in/conn/grp": "A", "/ch/3/in/conn/in": 5,
        "/io/in/A/5/mode": "ST",
    })
    cap = capture.capture_desk(state, console_model="wing-compact", made_from="snap",
                               captured="2026-10-25")
    assert [(r["patch"], r["name"]) for r in cap.input_rows] == [
        ("AES50-A 5", "Keys L"), ("AES50-A 6", "Keys R")]
    [channel] = cap.plan["channels"]
    assert channel["patch"]["sockets"] == [5, 6]
    assert channel["source"]["pair_input"] == "Keys R"


def test_an_unnamed_channel_with_an_unnamed_source_is_called_by_its_position():
    state = _small(**{"/ch/4/in/conn/grp": "A", "/ch/4/in/conn/in": 7})
    cap = capture.capture_desk(state, console_model="wing-compact", made_from="snap",
                               captured="2026-10-25")
    assert [r["name"] for r in cap.input_rows] == ["CH 4"]


def test_a_bus_with_an_effect_not_set_fully_wet_is_not_an_fx_return():
    state = _small(**{
        "/ch/1/name": "Vox", "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/1/send/2/on": 1, "/bus/2/name": "Verb", "/bus/2/main/1/on": 1,
        "/bus/2/preins/on": 1, "/bus/2/preins/ins": "FX1", "/fx/1/mdl": "HALL",
        "/fx/1/fxmix": 60.0,
    })
    cap = capture.capture_desk(state, console_model="wing-compact", made_from="snap",
                               captured="2026-10-25")
    assert _bus_row(cap, "Bus 2")["role"] == ""


# -- the input list's sheet columns, against a plan ----------------------------------------


def test_verify_says_when_a_sheet_column_had_no_effect(church):
    text = church.input_csv().replace("\n9,AES50-A 19,Kick,", "\n3,AES50-A 19,Kick,")
    result = verify_plan(church.plan, parse_input_list(text))
    [warning] = [f for f in result.warnings if f.code == "input-list.column-not-followed"]
    assert "puts Kick on channel 3, but the plan has it on 9" in warning.message


# -- applying a captured plan back to its own desk ------------------------------------
#
# An earlier change, folded into piece 1: a captured plan states no mix, so `apply`
# writes no fader, mute or send level it does not state, does no reset to
# initialized and unpatches nothing it does not hold. Applied back to the desk
# it came from, it changes nothing.


def _church_desk(church_state):
    from tests.test_apply import FakeConsole

    class Desk(FakeConsole):
        """The church desk answering in wire shapes, from its own reading."""

        console_model = "wing-full"

        def _reply_to(self, address):
            return _Desk(church_state.values).get(address) or OscReply(
                address=address, typetag="s", args=["NODE NOT FOUND"])

    return Desk()


def test_a_captured_plan_previewed_against_its_own_desk_changes_nothing(church, church_state):
    from atoo.apply import apply_plan

    result = apply_plan(church.plan, _church_desk(church_state), dry_run=True,
                        full_apply=True, initialize=True, init_model="wing-full")
    changing = [(w.address, w.prior_value, w.intended_value) for w in result.writes
                if w.status == "dry_run" and w.would_change]
    assert changing == []
    assert result.writes, "the plan's own patch, routing and names were compared"
    # The splits and recording feeds are written too, and are already so.
    direct = {(e["group"], e["socket"]) for e in church.plan["direct_outputs"]}
    compared = {w.address for w in result.writes}
    assert len(direct) == 123
    assert all({f"/io/out/{g}/{s}/grp", f"/io/out/{g}/{s}/in"} <= compared for g, s in direct)
    assert any("captured from a desk" in warning for warning in result.warnings)


def test_a_captured_plan_writes_no_reset_and_no_mix(church):
    from atoo.apply import _build_write_targets

    targets, _warnings = _build_write_targets(church.plan, True)
    addresses = {t.address for t in targets}
    assert not any(a.endswith(("/fdr", "/mute")) for a in addresses)
    assert not any("/send/" in a and a.endswith("/lvl") for a in addresses)
    assert not any(a.endswith("/main/1/lvl") or a.endswith("/main/1/pre") for a in addresses)
    assert "/ch/9/send/1/on" in addresses


def test_a_mute_a_captured_plan_states_is_still_written(church):
    from atoo.apply import _build_write_targets

    plan = json.loads(json.dumps(church.plan))
    plan["channels"][0]["fader"] = {"fader_db": -10.0, "muted": True}
    targets, _warnings = _build_write_targets(plan, True)
    base = f"/{plan['channels'][0]['bank']}/{plan['channels'][0]['channel']}"
    assert {f"{base}/fdr", f"{base}/mute"} <= {t.address for t in targets}


def test_where_the_desk_held_each_name_is_recorded(church):
    by_channel = {c["channel"]: c for c in church.plan["channels"] if c["bank"] == "ch"}
    assert by_channel[9]["name_on"] == "strip"      # 'Kick', its own name, link off
    assert by_channel[20]["name_on"] == "socket"    # 'MIC2', from LCL 4
    assert church.plan["busses"]["Bus 5"]["name_on"] == "none"
    assert church.plan["busses"]["Drums"]["name_on"] == "strip"


def test_verify_says_the_mix_is_left_to_the_desk(church):
    result = verify_plan(church.plan, parse_input_list(church.input_csv()))
    assert "capture.mix-left-to-desk" in {f.code for f in result.infos}
    assert not {"inferred.send-level", "inferred.send-mode"} & {f.code for f in result.infos}
