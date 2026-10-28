"""Apply's Preview, one tile at a time.

`preview_detail` puts every row of a preview journal in exactly one tile:
a strip, an input or output socket group, an FX slot or the
Console. These tests read a frozen preview of the Demo show
on its simulated WING Compact (`tests/fixtures/demo-preview/`): 1677
addresses read, 537 will change.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from atoo import desk_view, preview_detail
from atoo.apply import WriteRecord

FIXTURE = Path(__file__).parent / "fixtures" / "demo-preview"


def _records() -> list[dict]:
    """The journal's rows as the server hands them to the drawing, with
    `would_change` the engine's own answer (`WriteRecord.would_change`)."""
    journal = json.loads((FIXTURE / "journal.json").read_text(encoding="utf-8"))
    out = []
    for row in journal["writes"]:
        record = WriteRecord(
            address=row["address"], description=row.get("description", ""),
            value_type=row.get("value_type", "s"), method=None, ack=None,
            prior_value=row.get("prior_value"), intended_value=row.get("intended_value"),
            readback_value=None, status=row["status"], timestamp="",
            forced_by=row.get("forced_by"), mirrored_by=row.get("mirrored_by"))
        out.append({"address": record.address, "description": record.description,
                    "status": record.status, "prior_value": record.prior_value,
                    "intended_value": record.intended_value,
                    "would_change": record.would_change, "forced_by": record.forced_by,
                    "mirrored_by": record.mirrored_by})
    return out


@pytest.fixture(scope="module")
def drawing() -> dict:
    plan = json.loads((FIXTURE / "plan.json").read_text(encoding="utf-8"))
    return desk_view.full_build_desk(plan, _records())


def test_every_address_falls_in_exactly_one_tile(drawing):
    records = _records()
    rows = [r["address"] for t in drawing["tiles"].values() for r in t["rows"]]
    assert len(rows) == len(records) == 1677
    assert Counter(rows) == Counter(r["address"] for r in records)
    # And every tile a row landed in is drawn.
    drawn = {s["key"] for section in drawing["sections"] for s in section["strips"]}
    assert set(drawing["tiles"]) <= drawn


def test_the_tiles_change_counts_add_up_to_will_change(drawing):
    will_change = sum(1 for r in _records() if r["would_change"])
    assert will_change == 537
    assert sum(t["changes"] for t in drawing["tiles"].values()) == will_change
    for key, tile in drawing["tiles"].items():
        assert tile["changes"] == sum(1 for r in tile["rows"] if r["changes"]), key
        assert tile["changes"] + tile["same"] == len(tile["rows"]), key
    # A tile is outlined exactly when it changes.
    for section in drawing["sections"]:
        for strip in section["strips"]:
            assert strip["changes"] == bool(drawing["tiles"].get(strip["key"], {}).get("changes"))


def test_addresses_go_to_their_own_kind_of_tile():
    tile = preview_detail.tile_of
    assert tile("/ch/1/eq/1g") == "ch/1"
    assert tile("/mgrp/3/name") == "mgrp/3"
    assert tile("/io/in/A/1/g") == "in/A"
    assert tile("/io/out/LCL/3/grp") == "out/LCL"
    assert tile("/fx/5/mdl") == "fx/5"
    assert tile("/cfg/talk/assign") == "cfg/talk"
    # Past the desk, or nowhere the drawing has a tile: the Console's Other.
    assert tile("/ch/99/name") == "cfg/other"
    assert tile("/$stat/time") == "cfg/other"


def test_a_group_no_bank_lists_still_gets_a_tile():
    tiles = preview_detail.detail([{"address": "/io/in/AUX/1/g", "status": "dry_run",
                                    "prior_value": 0.0, "intended_value": 6.0,
                                    "would_change": True},
                                   {"address": "/xyz", "status": "dry_run",
                                    "prior_value": 1, "intended_value": 1}])
    banks = {b["kind"]: b for b in preview_detail.banks(tiles)}
    assert [s["key"] for s in banks["in"]["strips"]][-1] == "in/AUX"
    assert [s["key"] for s in banks["cfg"]["strips"]] == ["cfg/talk", "cfg/other"]


def test_the_banks_after_mute_groups(drawing):
    titles = [s["title"] for s in drawing["sections"]]
    assert titles[-4:] == ["Inputs", "Outputs", "FX", "Console"]
    inputs = drawing["sections"][-4]
    assert [s["label"] for s in inputs["strips"]] == [
        "LCL", "A", "B", "C", "SC", "USB", "CRD", "MOD", "AES"]
    fx = {s["key"]: s for s in drawing["sections"][-2]["strips"]}
    assert fx["fx/5"]["state"] == "plan" and fx["fx/5"]["name"] == "V-REV"
    assert fx["fx/1"]["state"] == "unused"


def test_a_channels_detail(drawing):
    kick = drawing["tiles"]["ch/1"]
    assert (kick["changes"], kick["same"]) == (39, 64)
    assert kick["presets"] == ["Kick In"]
    # The source socket's jump: the socket group and its count.
    assert kick["links"] == [{"key": "in/A", "text": "Source AES50-A 1 has 3 changes"}]
    rows = {r["address"]: r for r in kick["rows"]}
    assert rows["/ch/1/flt/lcf"] == {
        "section": "Filter", "label": "low cut frequency", "address": "/ch/1/flt/lcf",
        "now": "100 Hz", "after": "40.2 Hz", "changes": True, "note": ""}
    assert rows["/ch/1/flt/hcf"]["now"] == "10.02 kHz"
    assert rows["/ch/1/gate/on"]["now"] == "off" and rows["/ch/1/gate/on"]["after"] == "on"
    assert rows["/ch/1/col"]["now"] == "Red (9)"
    assert rows["/ch/1/send/5/mode"]["section"] == "Send to Drums (bus 5)"
    # Sent again because its selector changes (the journal's forced_by).
    assert rows["/ch/1/in/set/dly"]["note"] == "sent again: delay mode changes"
    # Within the desk's stepped tolerance: not changing, the plan's figure beside it.
    assert rows["/ch/1/gate/thr"]["changes"] is False
    assert rows["/ch/1/gate/thr"]["plan"] == "-40.5 dB"


def test_rows_run_in_the_desks_order(drawing):
    sections = []
    for row in drawing["tiles"]["ch/1"]["rows"]:
        if not sections or sections[-1] != row["section"]:
            sections.append(row["section"])
    assert len(sections) == len(set(sections)), "a heading appears twice"
    assert sections[:3] == ["Strip", "Patch", "Input"]
    assert sections.index("Filter") < sections.index("Gate") < sections.index("EQ") \
        < sections.index("Dynamics") < sections.index("Send to Drums (bus 5)") \
        < sections.index("Main 1")


def test_a_value_not_on_the_desk_until_its_model_changes(drawing):
    rows = {r["address"]: r for r in drawing["tiles"]["ch/10"]["rows"]}
    depth = rows["/ch/10/gate/depth"]
    assert depth["now"] is None and depth["after"] == "16 dB" and depth["changes"]
    assert depth["note"] == "not on the desk until model changes"


def test_socket_groups_list_their_sockets_with_the_strip_they_feed(drawing):
    a = drawing["tiles"]["in/A"]
    assert (a["changes"], a["same"]) == (42, 28)
    numbers = [int(r["section"].split()[-1]) for r in a["rows"]]
    assert numbers == sorted(numbers)
    first = a["rows"][0]
    assert first["section"] == "AES50-A 1" and first["owner"] == "ch 1 (Kick)"
    assert first["now"] == "(blank)" and first["after"] == "Kick"
    pair = {r["address"]: r for r in a["rows"]}["/io/in/A/6/g"]
    assert pair["note"] == "second socket of a stereo pair"
    lcl = {r["address"]: r for r in drawing["tiles"]["out/LCL"]["rows"]}
    assert lcl["/io/out/LCL/3/grp"]["note"] == "disconnected: nothing in the plan is patched here"
    assert lcl["/io/out/LCL/1/grp"]["owner"] == "main 1 (PA)"
    assert drawing["tiles"]["main/1"]["links"] == [
        {"key": "out/LCL", "text": "Outputs LCL 1, 2 have no changes"}]


def test_an_unused_strip_that_changes_keeps_its_outline(drawing):
    ch14 = {s["n"]: s for s in drawing["sections"][0]["strips"]}[14]
    assert ch14["state"] == "unused" and ch14["changes"] is True
    row = drawing["tiles"]["ch/14"]["rows"][0]
    assert row["note"] == "reset to the initialized desk"


def test_a_tile_with_no_changes(drawing):
    dca = drawing["tiles"]["dca/1"]
    assert dca["changes"] == 0 and dca["same"] == 3


@pytest.mark.parametrize("value,unit,shown", [
    (100.2374573, "Hz", "100 Hz"), (40.19342422, "Hz", "40.2 Hz"),
    (10018.26074, "Hz", "10.02 kHz"), (1002.37439, "Hz", "1 kHz"),
    (-10.10000038, "dB", "-10.1 dB"), (0.0, "dB", "0 dB"), (50.11872101, "ms", "50.1 ms"),
    (0.997970223, None, "1"), (1.486628652, None, "1.49"), (-144.0, "fader", "-∞ dB"),
    (1, "bool", "on"), (0, "bool", "off"), (9, "colour", "Red (9)"), (99, "colour", "color 99"),
    ("", None, "(blank)"), (None, "dB", None),
])
def test_values_read_as_the_desk_shows_them(value, unit, shown):
    assert preview_detail.format_value(value, unit) == shown
