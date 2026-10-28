"""Apply writes a plan's `direct_outputs`.

A capture records every output socket fed straight from a source rather
than from a bus, Main or Matrix -- a Dante split, a card's or USB's
recording feed -- as `{group, socket, source: {group, index}}`. Apply writes
each one's `/io/out/{group}/{socket}/grp` and `/in`, as it does a bus's or a
Main's output patch, so a captured show restores its splits on any desk. A
socket that something else also patches, and a source the desk cannot have,
are verify ERRORs. The church capture applied back to its own desk is
`tests/test_capture.py`'s. The desks here are `tests/snap_desk`'s, built
from the packaged initialized capture, and the show is the packaged Demo.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from atoo import firstrun
from atoo import initialize as init
from atoo.apply import (
    _build_write_targets,
    _clean_write_targets,
    apply_plan,
    full_apply_targets,
    plan_expansion_bay_use,
)
from atoo.preview_detail import tile_of
from atoo.verify_plan import verify_plan
from tests.snap_desk import PairedSnapDesk

DEMO_PLAN = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME / "plan.json"
MODEL = "wing-compact"


def demo_with(*entries: dict) -> dict:
    plan = json.loads(DEMO_PLAN.read_text(encoding="utf-8"))
    plan["direct_outputs"] = list(entries)
    return plan


def split(group: str, socket: int, source_group: str, index: int) -> dict:
    return {"group": group, "socket": socket, "source": {"group": source_group, "index": index}}


def test_each_entry_is_written_as_an_output_patch():
    targets, _warnings = _build_write_targets(
        demo_with(split("USB", 1, "A", 1), split("USB", 2, "MON", 2)), True)
    by_address = {t.address: t for t in targets}
    assert by_address["/io/out/USB/1/grp"].compute_value(None) == "A"
    assert by_address["/io/out/USB/1/in"].compute_value(None) == 1
    assert by_address["/io/out/USB/2/grp"].compute_value(None) == "MON"
    assert by_address["/io/out/USB/2/in"].compute_value(None) == 2
    assert by_address["/io/out/USB/1/in"].stage == by_address["/io/out/LCL/1/in"].stage
    assert by_address["/io/out/USB/1/grp"].description == "direct output USB 1: source A"
    # The Preview shows them on their output group's tile.
    assert tile_of("/io/out/USB/1/grp") == tile_of("/io/out/USB/1/in") == "out/USB"


def test_a_full_apply_writes_them_and_disconnects_nothing_they_claim():
    plan = demo_with(split("LCL", 5, "LCL", 1), split("A", 40, "LCL", 2))
    assert not any(t.address.startswith("/io/out/LCL/5/") for t in full_apply_targets(plan, MODEL))
    assert not any(t.address.startswith("/io/out/A/40/")
                   for t in _clean_write_targets(plan, {"LCL": 8, "A": 48}))
    desk = PairedSnapDesk({leaf.address: leaf.value for leaf in init.load_capture(MODEL).leaves})
    result = apply_plan(copy.deepcopy(plan), desk, dry_run=False, full_apply=True, initialize=True,
                        init_model=MODEL)
    assert not result.mismatches
    assert (desk.values["/io/out/LCL/5/grp"], desk.values["/io/out/LCL/5/in"]) == ("LCL", 1)
    assert (desk.values["/io/out/A/40/grp"], desk.values["/io/out/A/40/in"]) == ("LCL", 2)
    # Its neighbour, which nothing in the plan claims, is disconnected.
    assert desk.values["/io/out/LCL/6/grp"] == "OFF"


def test_a_socket_also_patched_from_a_main_is_refused_naming_both():
    plan = demo_with(split("LCL", 1, "A", 7))
    result = verify_plan(plan, console_model=MODEL)
    [collision] = [f for f in result.errors if f.code == "output.socket-collision"]
    assert "LCL output 1 is claimed by 2 sources" in collision.message
    assert "direct_outputs[LCL 1]" in collision.message


def test_two_entries_on_one_socket_are_refused():
    result = verify_plan(demo_with(split("USB", 9, "A", 1), split("USB", 9, "A", 2)),
                         console_model=MODEL)
    assert "output.socket-collision" in {f.code for f in result.errors}


def test_a_source_the_desk_cannot_have_is_refused():
    result = verify_plan(demo_with(split("USB", 1, "XLR", 1), split("USB", 2, "LCL", 30),
                                   split("USB", 3, "MON", 65), split("USB", 4, "OFF", 1),
                                   split("REC", 9, "A", 1)),
                         console_model=MODEL)
    errors = {(f.code, f.where): f.message for f in result.errors}
    assert "'XLR', which the desk's output routing does not offer" in errors[
        ("direct-output.unknown-source", "direct_outputs[USB 1]")]
    assert errors[("direct-output.source-out-of-range", "direct_outputs[USB 2]")].endswith(
        "LCL inputs are 1..24")
    assert errors[("direct-output.source-out-of-range", "direct_outputs[USB 3]")].endswith(
        "the routing numbers MON 1..64")
    assert ("direct-output.unknown-source", "direct_outputs[USB 4]") in errors
    assert ("output.socket-out-of-range", "direct_outputs[REC 9]") in errors


def test_a_well_formed_split_verifies_clean():
    result = verify_plan(demo_with(split("USB", 1, "A", 1), split("USB", 2, "MON", 2)),
                         console_model=MODEL)
    assert not [f for f in result.findings
                if f.code.startswith("direct-output.") or "direct_outputs" in f.where]


def test_a_feed_from_a_card_needs_the_card():
    use = plan_expansion_bay_use(demo_with(split("USB", 1, "MOD", 4)))
    assert "USB 1 fed from MOD 4" in use["MOD"]
