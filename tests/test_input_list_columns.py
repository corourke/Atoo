"""Build places channels by the input list's `channel`, `dca` and
`mute_group` columns.

A filled cell wins over the conventions and the reply, as the `preset`
column does, and each change it makes is said at INFO. A channel already on
the strip a cell names takes the strip the moved one left. Two channels
naming one strip are refused, since a strip holds one input. The lists are
built in the test.
"""

from __future__ import annotations

import json

import pytest

from atoo import generate
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list
from atoo.generate import GenerationError
from atoo.verify_plan import verify_plan

HEADER = "patch,name,category,type,model,phantom,channel,dca,mute_group\n"


def _rows(*lines: str) -> str:
    return HEADER + "".join(line + "\n" for line in lines)


PLAIN = _rows("LCL 1,Kick,drums,Mic,,FALSE,,,",
              "LCL 2,Snare,drums,Mic,,FALSE,,,",
              "LCL 3,Keys L,keys,Instrument,,FALSE,,,",
              "LCL 4,Keys R,keys,Instrument,,FALSE,,,",
              "LCL 5,Vox,vocals,Mic,,FALSE,,,")


def _reply(**dcas) -> dict:
    return {"channels": [{"input": "Kick", "dca": ["Drums"]},
                         {"input": "Snare", "dca": ["Drums"]},
                         {"input": "Keys L", "pair": "Keys R"},
                         {"input": "Vox", "dca": ["Vocals"], "mute_group": ["Band"]}],
            "dcas": [{"name": "Drums"}, {"name": "Vocals"}],
            "mute_groups": [{"name": "Band"}], "busses": [],
            "outputs": [{"name": "Main", "kind": "main",
                         "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": [], "notes": []}


def _build(csv: str, findings: list | None = None) -> dict:
    return generate.generate_plan(
        "conventions", csv, provider=FakeProvider(response=json.dumps(_reply())),
        console_model="wing-compact", findings=findings)


def _ch(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


def _spot(channel: dict) -> tuple:
    return (channel.get("bank") or "ch", channel["channel"])


def _infos(findings, code):
    return [f for f in findings if f.code == code]


def test_a_list_without_the_cells_builds_as_before():
    findings: list = []
    plan = _build(PLAIN, findings)
    assert [(_ch(plan, n)["channel"]) for n in ("Kick", "Snare", "Keys L", "Vox")] == [1, 2, 3, 4]
    assert not [f for f in findings if f.code.endswith("-from-input-list")]


def test_a_channel_cell_places_the_strip_and_the_one_there_takes_the_strip_it_left():
    findings: list = []
    csv = PLAIN.replace("LCL 5,Vox,vocals,Mic,,FALSE,,,", "LCL 5,Vox,vocals,Mic,,FALSE,1,,")
    plan = _build(csv, findings)
    assert _spot(_ch(plan, "Vox")) == ("ch", 1)
    assert _spot(_ch(plan, "Kick")) == ("ch", 4)
    assert _ch(plan, "Vox")["provenance"]["channel"] == "Input list channel column: CH 1 (Vox)"
    [info] = _infos(findings, "reply.channel-from-input-list")
    assert info.severity.value == "info"
    assert info.message == ("the input list's channel column puts 'Vox' on CH 1, where the build "
                            "had placed it on CH 4; the list wins, and 'Kick', which was there, "
                            "takes CH 4")
    # Every strip still holds one channel.
    spots = [_spot(c) for c in plan["channels"]]
    assert len(spots) == len(set(spots))


def test_a_channel_cell_on_a_free_strip_moves_nothing_else():
    findings: list = []
    csv = PLAIN.replace("LCL 2,Snare,drums,Mic,,FALSE,,,", "LCL 2,Snare,drums,Mic,,FALSE,12,,")
    plan = _build(csv, findings)
    assert _spot(_ch(plan, "Snare")) == ("ch", 12)
    assert _spot(_ch(plan, "Kick")) == ("ch", 1) and _spot(_ch(plan, "Vox")) == ("ch", 4)
    [info] = _infos(findings, "reply.channel-from-input-list")
    assert "takes" not in info.message


def test_an_aux_cell_puts_the_channel_on_an_aux_strip_with_no_high_pass():
    csv = PLAIN.replace("LCL 5,Vox,vocals,Mic,,FALSE,,,", "LCL 5,Vox,vocals,Mic,,FALSE,Aux 2,,")
    plan = _build(csv)
    vox = _ch(plan, "Vox")
    assert _spot(vox) == ("aux", 2)
    assert (vox.get("processing") or {}).get("hpf_hz") is None


def test_a_cell_that_agrees_moves_nothing_and_is_cited():
    findings: list = []
    csv = PLAIN.replace("LCL 1,Kick,drums,Mic,,FALSE,,,", "LCL 1,Kick,drums,Mic,,FALSE,1,,")
    plan = _build(csv, findings)
    assert _ch(plan, "Kick")["provenance"]["channel"] == "Input list channel column: CH 1 (Kick)"
    assert not _infos(findings, "reply.channel-from-input-list")


def test_two_rows_naming_one_strip_are_refused_naming_them():
    csv = (PLAIN.replace("LCL 1,Kick,drums,Mic,,FALSE,,,", "LCL 1,Kick,drums,Mic,,FALSE,9,,")
           .replace("LCL 2,Snare,drums,Mic,,FALSE,,,", "LCL 2,Snare,drums,Mic,,FALSE,9,,"))
    with pytest.raises(GenerationError) as raised:
        _build(csv)
    assert ("'Kick' and 'Snare' both name CH 9 in the channel column, and a strip holds one "
            "input") in str(raised.value)


def test_a_stereo_pair_s_two_rows_may_name_its_one_strip():
    csv = (PLAIN.replace("LCL 3,Keys L,keys,Instrument,,FALSE,,,",
                         "LCL 3,Keys L,keys,Instrument,,FALSE,7,,")
           .replace("LCL 4,Keys R,keys,Instrument,,FALSE,,,",
                    "LCL 4,Keys R,keys,Instrument,,FALSE,7,,"))
    plan = _build(csv)
    assert _spot(_ch(plan, "Keys L")) == ("ch", 7)


def test_a_pair_whose_rows_name_two_strips_takes_the_first_rows_and_says_so():
    findings: list = []
    csv = (PLAIN.replace("LCL 3,Keys L,keys,Instrument,,FALSE,,,",
                         "LCL 3,Keys L,keys,Instrument,,FALSE,7,,")
           .replace("LCL 4,Keys R,keys,Instrument,,FALSE,,,",
                    "LCL 4,Keys R,keys,Instrument,,FALSE,8,,"))
    plan = _build(csv, findings)
    assert _spot(_ch(plan, "Keys L")) == ("ch", 7)
    assert any("are one stereo channel, and their channel cells say CH 7 and CH 8; the first "
               "row wins" in f.message for f in _infos(findings, "reply.channel-from-input-list"))


def test_dca_and_mute_group_cells_are_the_whole_membership_and_say_so():
    findings: list = []
    csv = PLAIN.replace("LCL 5,Vox,vocals,Mic,,FALSE,,,", "LCL 5,Vox,vocals,Mic,,FALSE,,Lead;Vocals,Mains")
    plan = _build(csv, findings)
    vox = _ch(plan, "Vox")
    assert vox["dca"] == ["Lead", "Vocals"] and vox["mute_group"] == ["Mains"]
    assert vox["provenance"]["dca"] == "Input list dca column: Lead; Vocals (Vox)"
    # The new names are declared, and allocation numbers them.
    assert {"Lead", "Vocals", "Drums"} <= set(plan["dcas"])
    assert all(isinstance(e.get("index"), int) for e in plan["dcas"].values())
    assert "Mains" in plan["mute_groups"]
    messages = [f.message for f in _infos(findings, "reply.dca-from-input-list")]
    assert ("the input list's dca column puts 'Vox' in Lead; Vocals, where the reply had "
            "Vocals; the list wins") in messages
    assert ("DCA 'Lead' declared: the input list's dca column puts 'Vox' in it, and nothing "
            "else declared it") in messages
    assert any("puts 'Vox' in Mains, where the reply had Band" in f.message
               for f in _infos(findings, "reply.mute-group-from-input-list"))


def test_a_cell_naming_a_declared_group_in_another_case_renames_it_as_the_list_spells_it():
    """The conventions say Drums, the list says DRUMS: the DCA is DRUMS, on
    every channel in it, said at INFO, and verify finds the cell followed."""
    findings: list = []
    csv = PLAIN.replace("LCL 2,Snare,drums,Mic,,FALSE,,,", "LCL 2,Snare,drums,Mic,,FALSE,,DRUMS,")
    plan = _build(csv, findings)
    assert "DRUMS" in plan["dcas"] and "Drums" not in plan["dcas"]
    assert _ch(plan, "Snare")["dca"] == ["DRUMS"]
    assert _ch(plan, "Kick")["dca"] == ["DRUMS"]
    assert ("DCA 'Drums' is named 'DRUMS', as the input list spells it"
            in [f.message for f in _infos(findings, "reply.dca-from-input-list")])
    result = verify_plan(plan, parse_input_list(csv))
    assert "input-list.column-not-followed" not in {f.code for f in result.warnings}


def test_rows_spelling_a_group_two_ways_take_the_first_rows_spelling_and_say_so():
    findings: list = []
    csv = (PLAIN.replace("LCL 1,Kick,drums,Mic,,FALSE,,,", "LCL 1,Kick,drums,Mic,,FALSE,,DRUMS,")
           .replace("LCL 2,Snare,drums,Mic,,FALSE,,,", "LCL 2,Snare,drums,Mic,,FALSE,,drums ,"))
    plan = _build(csv, findings)
    assert [k for k in plan["dcas"] if k.casefold() == "drums"] == ["DRUMS"]
    assert _ch(plan, "Snare")["dca"] == ["DRUMS"]
    assert ("DCA 'DRUMS' is spelled differently on other rows of the input list: 'drums' "
            "(Snare). The first row's spelling, 'DRUMS', is the DCA's name"
            in [f.message for f in _infos(findings, "reply.dca-from-input-list")])
    result = verify_plan(plan, parse_input_list(csv))
    assert "input-list.column-not-followed" not in {f.code for f in result.warnings}


def test_a_renamed_group_is_renamed_on_every_strip_that_names_it():
    from atoo.reply_expand import rename_group

    plan = {"dcas": {"Band": {"index": 1}, "Drums": {"index": 2}},
            "mute_groups": {"Drums": {}},
            "channels": [{"name": "Kick", "dca": ["Band", "Drums"], "mute_group": ["Drums"]}],
            "busses": {"Drum Bus": {"dca": ["Drums"]}},
            "outputs": {"Main": {"dca": ["Drums", "Band"]}}}
    rename_group(plan, "dcas", "Drums", "DRUMS")
    assert list(plan["dcas"]) == ["Band", "DRUMS"]
    assert plan["channels"][0] == {"name": "Kick", "dca": ["Band", "DRUMS"],
                                   "mute_group": ["Drums"]}
    assert plan["busses"]["Drum Bus"]["dca"] == ["DRUMS"]
    assert plan["outputs"]["Main"]["dca"] == ["DRUMS", "Band"]
    assert list(plan["mute_groups"]) == ["Drums"]


def test_a_built_plan_follows_its_cells_so_verify_says_nothing_of_them():
    csv = (PLAIN.replace("LCL 5,Vox,vocals,Mic,,FALSE,,,", "LCL 5,Vox,vocals,Mic,,FALSE,1,Lead,")
           .replace("LCL 2,Snare,drums,Mic,,FALSE,,,", "LCL 2,Snare,drums,Mic,,FALSE,,,Band"))
    plan = _build(csv)
    result = verify_plan(plan, parse_input_list(csv))
    assert "input-list.column-not-followed" not in {f.code for f in result.warnings}


def test_verify_still_says_when_a_plan_edited_after_it_was_built_does_not_follow_a_cell():
    csv = PLAIN.replace("LCL 5,Vox,vocals,Mic,,FALSE,,,", "LCL 5,Vox,vocals,Mic,,FALSE,1,,")
    plan = _build(csv)
    _ch(plan, "Vox")["channel"] = 20
    result = verify_plan(plan, parse_input_list(csv))
    [warning] = [f for f in result.warnings if f.code == "input-list.column-not-followed"]
    assert warning.message == (
        "The input list puts Vox on channel 1, but the plan has it on 20: the plan was changed "
        "after it was built, or the list after the plan. Rebuild, or Save the input list in "
        "Build 04, to apply the cell; or clear the cell if the plan is right")


def test_verify_still_says_when_a_plan_does_not_follow_a_dca_cell():
    csv = PLAIN.replace("LCL 2,Snare,drums,Mic,,FALSE,,,", "LCL 2,Snare,drums,Mic,,FALSE,,DRUMS,")
    plan = _build(csv)
    _ch(plan, "Snare")["dca"] = ["Vocals"]
    _ch(plan, "Kick")["mute_group"] = []
    result = verify_plan(plan, parse_input_list(csv.replace(
        "LCL 1,Kick,drums,Mic,,FALSE,,,", "LCL 1,Kick,drums,Mic,,FALSE,,,Band")))
    messages = [f.message for f in result.warnings if f.code == "input-list.column-not-followed"]
    assert any(m.startswith("The input list puts Snare in DCA DRUMS, but the plan has it in "
                            "Vocals: the plan was changed after it was built") for m in messages)
    assert any(m.startswith("The input list puts Kick in mute group Band, but the plan has it "
                            "in no mute group:") for m in messages)
