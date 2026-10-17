"""verify's `routing.channel-reaches-nothing` (Haiku round 2, 2026-09-29).

Haiku's smallband plan built the Playback aux with no Main route and no
send; nothing but the critic noticed. A channel with no route to a Main,
no send into a monitor bus and no send above -144 dB into any other bus is
now a WARNING -- not an ERROR: the desk works, and a silent strip may be
deliberate. A monitor send counts at any level, since the conventions
start monitor sends all the way down and raise them at soundcheck (the
festival plan's click, sent only to the monitors at -144, is routed).

Built from the frozen `tests/fixtures/smallband.plan.json` (never
from a bundle under `examples/`).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo.verify_plan import verify_plan

PLAN = json.loads((Path(__file__).resolve().parent / "fixtures" / "smallband.plan.json")
                  .read_text())
CODE = "routing.channel-reaches-nothing"


def _with_aux(**fields) -> dict:
    plan = copy.deepcopy(PLAN)
    strip = copy.deepcopy(next(c for c in plan["channels"] if c["name"] == "Kick"))
    strip.update({"bank": "aux", "channel": 1, "name": "Playback", "main_routes": [],
                  "bus_sends": [], "dca": [], "mute_group": []})
    strip["source"] = dict(strip["source"], input="Playback")
    strip.update(fields)
    plan["channels"].append(strip)
    return plan


def _hits(plan: dict) -> list:
    return [f for f in verify_plan(plan, None).findings if f.code == CODE]


def test_a_plan_whose_channels_all_reach_an_output_says_nothing():
    assert _hits(copy.deepcopy(PLAN)) == []


def test_a_channel_with_no_route_and_no_send_is_a_warning():
    [hit] = _hits(_with_aux())
    assert hit.severity == "warning" and hit.where == "channels[Playback]"
    assert "aux 1 'Playback' reaches no output" in hit.message
    assert "it sends to no bus" in hit.message


def test_sends_all_the_way_down_into_mix_busses_reach_nothing():
    [hit] = _hits(_with_aux(bus_sends=[{"bus": "Vocals", "mode": "post", "level_db": -144},
                                       {"bus": "VOX Reverb", "mode": "post", "level_db": -144}]))
    assert "(Vocals, VOX Reverb) are all the way down" in hit.message


@pytest.mark.parametrize("sends,routes", [
    ([], [{"index": 1}]),                                                   # a Main route
    ([{"bus": "Vocals", "mode": "post", "level_db": -20}], []),             # an audible mix send
    ([{"bus": "Vocals", "mode": "post", "level_db": None}], []),            # null: decided unity
    ([{"bus": "MON1", "mode": "pre", "level_db": -144}], []),               # a click to the wedges
])
def test_a_channel_that_reaches_an_output_is_not_flagged(sends, routes):
    assert _hits(_with_aux(bus_sends=sends, main_routes=routes)) == []


def test_a_send_to_a_bus_the_plan_never_declares_does_not_count():
    # reference.dangling is the error for that; this says the strip is unheard.
    plan = _with_aux(bus_sends=[{"bus": "Nowhere", "mode": "post", "level_db": 0}])
    assert len(_hits(plan)) == 1
