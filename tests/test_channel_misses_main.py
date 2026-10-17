"""verify's `routing.channel-misses-main` (routing is
checked by code, not by the critic).

The Haiku critic kept reporting channels that reach Main through a mix bus
as having no route to Main. A channel with no `main_routes` entry and no
audible send (above -144 dB, or `null`: decided unity) into a bus whose
destination is a Main is now a WARNING -- except a click, guide or
talkback strip, which the conventions keep off Main.

Built from frozen plans under `tests/fixtures/` (never from a
bundle under `examples/`).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SMALLBAND = json.loads((FIXTURES / "smallband.plan.json").read_text())
FESTIVAL = json.loads((FIXTURES / "festival_2026-09-29.plan.json").read_text())
CODE = "routing.channel-misses-main"


def _with_strip(name="Keys", **fields) -> dict:
    plan = copy.deepcopy(SMALLBAND)
    strip = copy.deepcopy(next(c for c in plan["channels"] if c["name"] == "Kick"))
    strip.update({"bank": "aux", "channel": 1, "name": name, "main_routes": [],
                  "bus_sends": [], "dca": [], "mute_group": []})
    strip["source"] = dict(strip["source"], input=name)
    strip.update(fields)
    plan["channels"].append(strip)
    return plan


def _hits(plan: dict) -> list:
    return [f for f in verify_plan(plan, None).findings if f.code == CODE]


def test_channels_reaching_main_only_through_a_bus_say_nothing():
    # The critic's false positives: Snare and Lead Vox have no Main route
    # and reach Main through the Drums and Vocals busses.
    by_name = {c["name"]: c for c in SMALLBAND["channels"]}
    for name, bus in (("Snare", "Drums"), ("Lead Vox", "Vocals")):
        assert not by_name[name]["main_routes"]
        assert bus in [s["bus"] for s in by_name[name]["bus_sends"]]
        assert SMALLBAND["busses"][bus]["destination"]["type"] == "main"
    assert _hits(copy.deepcopy(SMALLBAND)) == []


def test_a_channel_with_no_route_and_no_bus_send_is_a_warning_once():
    # It reaches nothing at all: channel-reaches-nothing says so, and this
    # check stays quiet rather than report the one strip twice.
    plan = _with_strip()
    assert _hits(plan) == []
    assert [f.where for f in verify_plan(plan, None).findings
            if f.code == "routing.channel-reaches-nothing"] == ["channels[Keys]"]


def test_a_channel_heard_only_in_the_monitors_is_a_warning():
    [hit] = _hits(_with_strip(bus_sends=[{"bus": "MON1", "mode": "pre", "level_db": 0}]))
    assert hit.severity == "warning" and hit.where == "channels[Keys]"
    assert "aux 1 'Keys' reaches no Main" in hit.message
    assert "busses that feed no Main (MON1)" in hit.message


def test_a_send_all_the_way_down_into_a_main_bus_does_not_count():
    [hit] = _hits(_with_strip(bus_sends=[{"bus": "Vocals", "mode": "post", "level_db": -144},
                                         {"bus": "MON1", "mode": "pre", "level_db": 0}]))
    assert "(Vocals) are all the way down" in hit.message


@pytest.mark.parametrize("sends,routes", [
    ([], [{"index": 1}]),                                            # a direct Main route
    ([{"bus": "Vocals", "mode": "post", "level_db": -20}], []),      # an audible send to a Main bus
    ([{"bus": "Vocals", "mode": "post", "level_db": None}], []),     # null: decided unity
])
def test_a_channel_that_reaches_main_is_not_flagged(sends, routes):
    assert _hits(_with_strip(bus_sends=sends, main_routes=routes)) == []


@pytest.mark.parametrize("name", ["Click", "T Click/Gd", "Guide", "Talkback", "TB Mic"])
def test_click_guide_and_talkback_stay_off_main_quietly(name):
    plan = _with_strip(name=name, bus_sends=[{"bus": "MON1", "mode": "pre", "level_db": 0}])
    assert _hits(plan) == []


def test_a_main_bus_nobody_sends_to_is_not_a_finding():
    plan = copy.deepcopy(SMALLBAND)
    for ch in plan["channels"]:
        ch["bus_sends"] = [s for s in ch.get("bus_sends") or [] if s.get("bus") != "Snare Verb"]
    assert _hits(plan) == []


def test_festivals_click_is_the_only_channel_off_main_and_it_is_quiet():
    off_main = [c["name"] for c in FESTIVAL["channels"]
                if not c.get("main_routes")
                and not any(FESTIVAL["busses"][s["bus"]].get("destination", {}).get("type") == "main"
                            and (s.get("level_db") is None or s["level_db"] > -144)
                            for s in c.get("bus_sends") or [])]
    assert off_main == ["T Click/Guide"]
    assert _hits(copy.deepcopy(FESTIVAL)) == []
