"""The critic reads a strip's starting level and mute as the desk will hold
them, so an unset mute is not reported against a convention that says
"unmuted".

A plan leaves `fader.muted` null when the conventions did not say, and
`apply` then writes the strip unmuted at unity. The critic is a model
reading the plan JSON; handed a null where the conventions said "start
every channel unmuted", it reported every regular channel's mute as "left
unset", a note about nothing. That is decided in code, not by asking the
model to remember the default: the plan the critic is shown has the
defaults filled in, from the constants `apply` writes. These tests pin the
view, and that a convention the default does not satisfy still reads as a
mismatch. No model is called: the provider is a recorder.
"""

from __future__ import annotations

import copy
import json

from atoo import apply, generate
from atoo import console_facts as facts


def _channel(name: str, fader: dict | None = None) -> dict:
    channel = {"channel": 1, "bank": "ch", "name": name,
               "fader": {"fader_db": None, "muted": None}}
    if fader is not None:
        channel["fader"] = fader
    return channel


def _plan() -> dict:
    return {
        "channels": [_channel("Kick"), _channel("Snare")],
        "busses": {"Drums": {"fader": {"fader_db": None, "muted": None}},
                   "Bare": {"mono": True}},
        "dcas": {"Band": {"fader": {"fader_db": None, "muted": None}}},
        "outputs": {"Main L": {"kind": "main", "fader": {"fader_db": None, "muted": None}}},
        "mute_groups": {"All": {"index": 1}},
    }


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, label: str = "", **kwargs) -> str:
        self.calls.append({"system": system, "user": user, "label": label})
        return json.dumps({"findings": []})


def _seen_by_the_critic(plan: dict, conventions: str) -> dict:
    """The plan JSON the critic's request carries, parsed back out."""
    provider = _Recorder()
    generate.critique_plan(conventions, "name\nKick\n", plan, provider=provider)
    user = provider.calls[0]["user"]
    block = user.split("# The plan to review\n\n```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(block)


def test_an_unset_mute_and_fader_are_shown_as_what_apply_writes():
    seen = _seen_by_the_critic(_plan(), "Start every channel fader at unity, unmuted.")
    expect = {"fader_db": facts.FADER_DEFAULT_DB, "muted": facts.MUTED_DEFAULT}
    assert [c["fader"] for c in seen["channels"]] == [expect, expect]
    assert seen["busses"]["Drums"]["fader"] == expect
    assert seen["dcas"]["Band"]["fader"] == expect
    assert seen["outputs"]["Main L"]["fader"] == expect
    # The reviewer is no longer handed a null to read as "never said".
    assert '"muted": null' not in json.dumps(seen)


def test_the_view_is_what_apply_writes_for_a_strip_with_nothing_stated():
    unset = {"fader_db": None, "muted": None}
    written = {t.address.rsplit("/", 1)[1]: t for t in apply._fader_targets("/ch/1", "Kick", unset)}
    shown = generate._with_starting_levels({"fader": unset})["fader"]
    assert written["fdr"].compute_value(None) == shown["fader_db"]
    assert written["mute"].compute_value(None) == (1 if shown["muted"] else 0)


def test_a_stated_value_is_shown_as_stated():
    plan = _plan()
    plan["channels"][0]["fader"] = {"fader_db": -144.0, "muted": True}
    plan["channels"][1]["fader"] = {"fader_db": -6.0, "muted": False}
    seen = _seen_by_the_critic(plan, "Start every channel muted, faders all the way down.")
    assert seen["channels"][0]["fader"] == {"fader_db": -144.0, "muted": True}
    assert seen["channels"][1]["fader"] == {"fader_db": -6.0, "muted": False}


def test_a_convention_the_default_does_not_meet_is_still_a_mismatch_the_critic_can_see():
    # "start muted" with the mute unset: the critic is shown `muted: false`,
    # which disagrees with the convention in its own words, not a gap that
    # was hidden from it.
    plan = _plan()
    provider = _Recorder()
    generate.critique_plan("Start every channel muted.", "name\nKick\n", plan, provider=provider)
    user = provider.calls[0]["user"]
    assert "Start every channel muted." in user
    assert '"muted": false' in user
    assert '"muted": null' not in user


def test_an_entry_with_no_fader_block_and_the_callers_plan_are_left_alone():
    plan = _plan()
    before = copy.deepcopy(plan)
    seen = generate._plan_for_critic(plan)
    assert plan == before
    assert seen["busses"]["Bare"] == {"mono": True}
    assert seen["mute_groups"] == {"All": {"index": 1}}
    # Not a plan at all: nothing to fill in, nothing raised.
    assert generate._plan_for_critic({}) == {}
    assert generate._plan_for_critic({"channels": "x", "busses": []}) == {"channels": "x", "busses": []}


def test_the_critic_is_told_the_defaults_are_neither_an_invention_nor_unset():
    system = " ".join(generate.critic_system().split())
    assert "A strip's starting fader and mute are shown to you as the desk will hold them" in system
    assert "never an invention and never \"not set\"" in system
    assert "A convention they already satisfy" in system
    assert "is a mismatch with the value you see" in system


def test_the_other_unset_fields_stay_unset_in_the_critics_view():
    # A colour, an icon, a filter, a gain, a preset have no default that
    # satisfies a convention, so a null there is still the plan's gap to
    # report.
    plan = _plan()
    plan["channels"][0].update({"color": None, "icon": None, "processing": {"hpf_hz": None, "preset": None}})
    seen = generate._plan_for_critic(plan)["channels"][0]
    assert seen["color"] is None and seen["icon"] is None
    assert seen["processing"] == {"hpf_hz": None, "preset": None}
