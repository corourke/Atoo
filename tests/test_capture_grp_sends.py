"""A send in the desk's GRP mode, captured.

GRP feeds the bus as a subgroup, after the channel's fader. A capture used to
leave such a send's tap undecided. It now keeps it: the plan holds it as
"group", the bus sheet's tap says `group`, the INFO says so once per bus, and
a full Apply of the captured show writes GRP back, so the mix is not changed.

The church desk's frozen snapshot has four: CH 17, 18, 24 and 28 into Bus 10
'Speakers'. Nothing under `examples/` is read.
"""

from __future__ import annotations

import csv
import io

import pytest

from atoo import apply, capture, plan_schema, sheets, verify_plan
from atoo.schema_check import validate
from atoo.snapshot import load_snapshot
from tests.test_capture import CHURCH

GRP_STRIPS = ("Pastor", "Host", "HOST 2", "PASTOR2")


@pytest.fixture(scope="module")
def church():
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _sends(plan, bus):
    return {c["name"]: s for c in plan["channels"] for s in c.get("bus_sends") or []
            if s.get("bus") == bus}


def test_a_grp_send_is_kept_as_group_in_the_plan(church):
    sends = _sends(church.plan, "Speakers")
    assert {n: sends[n]["mode"] for n in GRP_STRIPS} == {n: "group" for n in GRP_STRIPS}
    assert validate(church.plan, plan_schema.PLAN_SCHEMA) == []
    assert verify_plan.verify_plan(church.plan).errors == []


def test_the_bus_sheet_says_group_as_its_tap(church):
    row = next(r for r in csv.DictReader(io.StringIO(church.busses_csv())) if r["bus"] == "Bus 10")
    assert (row["sources"], row["tap"]) == ("Pastor;Host;HOST 2;PASTOR2", "group")
    # Laid back on the plan it came from, it changes nothing.
    result = sheets.overlay_busses(church.plan, [row])
    assert result.refusals == [] and result.changes == []


def test_it_is_said_once_never_left_undecided(church):
    said = [n for n in church.notes if "GRP" in n]
    assert said == [
        "CH 17, CH 18, CH 24 and CH 28 to BUS 10 'Speakers': sent in the desk's GRP mode (the "
        "bus fed as a subgroup, after the channel's fader), which is kept: written 'group' in the "
        "plan and the sheets, so Apply writes GRP back, and read as post-fader wherever a check "
        "asks pre or post."]
    assert not any("undecided" in n for n in church.notes)


def test_a_full_apply_of_the_capture_writes_grp_back_and_no_level(church):
    targets, _warnings = apply._build_write_targets(church.plan, True)
    targets += apply.full_apply_targets(church.plan)
    for n in (17, 18, 24, 28):
        writes = {t.address: t.compute_value(None) for t in targets
                  if t.address.startswith(f"/ch/{n}/send/10/")}
        # On, in GRP; the level the desk has is left alone (a capture states no mix).
        assert writes == {f"/ch/{n}/send/10/on": 1, f"/ch/{n}/send/10/mode": "GRP"}, n


def test_a_sources_cell_may_say_group(church):
    assert sheets.parse_sources("Pastor (group); Host") == [("Pastor", "group"), ("Host", None)]
    row = {"bus": "Bus 10", "sources": "Pastor;Host", "tap": "GRP"}
    refused = sheets.overlay_busses(church.plan, [row]).refusals
    assert [(r.column, r.reason) for r in refused] == [
        ("tap", "tap is pre, post or group (the desk's GRP)")]
