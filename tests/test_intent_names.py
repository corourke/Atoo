"""A new bus, DCA, mute group or output the request gave no name is named from
the request's own words, at INFO; a name the engineer gave that clashes is refused,
naming the clash. `atoo/intent_names.py`; frozen inputs only.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import intent_compile as ic
from atoo import intent_names as names

BASE = json.loads((Path(__file__).parent / "fixtures" / "intent" / "demo_base.plan.json").read_text())


def compile_(op, request):
    cs, infos = ic.compile_intent({"name": "n", "notes": [], "ops": [op]}, copy.deepcopy(BASE),
                                  "wing-compact", text=request, aes50_devices={"A": "S16"})
    return cs, infos


@pytest.mark.parametrize("kind,request_text,taken,expected", [
    ("bus", "Add a stereo IEM bus", [], "IEM"),
    ("bus", "Add a bus called FOH Verb", [], "FOH Verb"),
    ("bus", 'Make a bus named "Pad Verb"', [], "Pad Verb"),
    ("bus", "we need a vocal reverb bus", [], "Vocal Reverb"),
    ("bus", "Add a new mono wedge bus for the singer", [], "Wedge"),
    ("dca", "add a DCA for the horns", [], "Horns"),
    ("mute_group", "put a mute group on the strings", [], "Strings"),
    ("output", "Add an output for the lobby", [], "Lobby"),
    ("bus", "add a bus", [], "Bus"),
    ("bus", "Add a stereo IEM bus", ["IEM"], "IEM 2"),
    ("bus", "Add a stereo IEM bus", ["iem", "IEM 2"], "IEM 3"),
])
def test_the_name_comes_from_the_requests_own_words(kind, request_text, taken, expected):
    assert names.derive(kind, request_text, taken)[0] == expected


def test_a_bus_reference_by_number_is_not_its_name():
    assert names.derive("bus", "Clear bus 5 and 6. Add a stereo IEM bus (reuse bus 5)", [])[0] == "IEM"


@pytest.mark.parametrize("request_text,model_wrote", [
    ("Add a stereo IEM bus", None),
    ("Add a stereo IEM bus", "Drum IEM"),          # an existing bus, made up by the model
    ("Add a stereo IEM bus", "Singer Monitor"),    # not in the request
])
def test_a_bus_the_request_did_not_name_takes_its_name_from_the_request(request_text, model_wrote):
    cs, infos = compile_({"op": "add_bus", "name": model_wrote, "stereo": True}, request_text)
    assert list(cs["add"]["busses"]) == ["IEM"]
    said = [i for i in infos if "named the new bus 'IEM'" in i]
    assert said and "no name was given" in said[0]
    if model_wrote:
        assert repr(model_wrote) in said[0]       # what the model wrote, and that it was not used


def test_when_the_derived_name_is_taken_the_first_free_variant_is_used_and_said():
    base_with_iem = copy.deepcopy(BASE)
    base_with_iem["busses"]["IEM"] = copy.deepcopy(base_with_iem["busses"]["Drums"])
    base_with_iem["busses"]["IEM"]["index"] = 8
    cs, infos = ic.compile_intent(
        {"name": "n", "notes": [], "ops": [{"op": "add_bus", "name": None}]}, base_with_iem,
        "wing-compact", text="Add a stereo IEM bus")
    assert list(cs["add"]["busses"]) == ["IEM 2"]
    assert any("'IEM' was taken, so the first free variant" in i for i in infos)


def test_a_name_the_engineer_gave_that_clashes_is_refused_naming_the_clash():
    with pytest.raises(ic.IntentRefused) as raised:
        compile_({"op": "add_bus", "name": "Drums"}, "Add a bus called Drums")
    assert "the name 'Drums' is already a bus on the desk" in raised.value.reasons[0]
    with pytest.raises(ic.IntentRefused) as raised:
        compile_({"op": "add_group", "object": "dca", "name": "Vocals"}, "Add a Vocals DCA")
    assert "already a dca on the desk" in raised.value.reasons[0]


def test_a_dca_mute_group_and_output_are_named_the_same_way():
    cs, infos = compile_({"op": "add_group", "object": "dca", "name": None}, "add a DCA for the horns")
    assert list(cs["add"]["dcas"]) == ["Horns"]
    cs, _ = compile_({"op": "add_group", "object": "mute_group", "name": "Made Up"},
                     "put a mute group on the strings")
    assert list(cs["add"]["mute_groups"]) == ["Strings"]
    cs, _ = compile_({"op": "add_output", "object": "matrix", "name": None}, "Add an output for the lobby")
    assert list(cs["add"]["outputs"]) == ["Lobby"]


def test_a_name_in_the_request_is_kept_even_when_the_conventions_would_call_it_something_else():
    cs, infos = compile_({"op": "add_bus", "name": "Pad Verb"}, "Add a bus called Pad Verb")
    assert list(cs["add"]["busses"]) == ["Pad Verb"] and not any("no name was given" in i for i in infos)
