"""The intent compiler (`atoo patch --intent`, `atoo/intent_compile.py`), offline.

It turns a hand-written intent into the change set `atoo patch` already merges
and runs `patch.merge_change` over it. Each case in
`tests/fixtures/intent/cases.json` is a request from the live corpus
(the live eval's corpus) with the intent a front end would be asked for and
the change set the model writes today (written by hand, no model is called);
the test checks that both give the same plan where it matters, on all three
consoles, and that what cannot work is refused with the reason.

Frozen inputs only: the Demo show of the live eval's fixture is
`tests/fixtures/intent/demo_base.plan.json`. Nothing here reads `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import intent_compile as ic
from atoo import intent_schema as sc
from atoo import patch

import intent_today as today

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "intent"
CONSOLES = ("wing-compact", "wing-rack", "wing-full")

CASES = json.loads((FIXTURES / "cases.json").read_text())
BASE = json.loads((FIXTURES / "demo_base.plan.json").read_text())
RIG = CASES["aes50"]


def base():
    return copy.deepcopy(BASE)


def project(merge) -> dict:
    """What the two ways must agree on: where every strip is, how it is
    patched, which groups and buses it is in, and the indices of the named
    objects. (Processing values a model invents -- gain 20 dB -- are not
    compared; the results note says which side is right.)"""
    plan = merge.plan
    return {
        "channels": sorted(
            (c["bank"], c["channel"], c["name"], bool(c["source"].get("stereo")),
             c["patch"]["group"], tuple(c["patch"]["sockets"]), tuple(c.get("dca") or ()),
             tuple(c.get("mute_group") or ()),
             tuple(sorted(s["bus"] for s in c.get("bus_sends") or [])))
            for c in plan["channels"]),
        "busses": {n: (b.get("index"), b.get("mono"), (b.get("destination") or {}).get("type"),
                       json.dumps((b.get("destination") or {}).get("patch"), sort_keys=True))
                   for n, b in plan["busses"].items()},
        "dcas": {n: o.get("index") for n, o in plan["dcas"].items()},
        "mute_groups": {n: o.get("index") for n, o in plan["mute_groups"].items()},
        "outputs": {n: o.get("index") for n, o in plan["outputs"].items()},
        "freed": sorted(merge.freed_busses) + sorted(n for _k, n in merge.freed_objects),
        "refused": sorted(c.where for c in merge.refused),
        "edits": sorted((e.name, e.path, e.new) for e in merge.edits),
    }


def today_merge(case, model):
    change_set = patch.validate_change_set(today.change_set(case["today"]))
    return patch.merge_change(base(), change_set, console_model=model, text=case["request"],
                              aes50_devices=RIG)


@pytest.mark.parametrize("model", CONSOLES)
@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["id"])
def test_the_intent_gives_the_plan_the_model_written_change_gives(case, model):
    merge, infos = ic.apply_intent(case["intent"], base(), model, text=case["request"],
                                   aes50_devices=RIG)
    assert not merge.refused
    assert project(merge) == project(today_merge(case, model))
    assert all(isinstance(i, str) and i for i in infos)


@pytest.mark.parametrize("model", CONSOLES)
@pytest.mark.parametrize("case", CASES["refusals"], ids=lambda c: c["id"])
def test_what_cannot_work_is_refused_and_says_why(case, model):
    if model not in case.get("models", CONSOLES):
        pytest.skip("this case is about another console")
    with pytest.raises(ic.IntentRefused) as raised:
        ic.compile_intent(case["intent"], base(), model, text=case["request"], aes50_devices=RIG)
    reasons = " | ".join(raised.value.reasons)
    expected = case["reason"]
    assert (expected == "schema" and "not well formed" in reasons) or expected in reasons, reasons


def test_the_schema_differs_between_consoles_only_where_the_hardware_does():
    groups = {m: (sc.input_groups(m), sc.output_groups(m)) for m in CONSOLES}
    assert groups["wing-compact"] == groups["wing-rack"]
    assert "AUX" in groups["wing-full"][0] and "AUX" not in groups["wing-rack"][0]
    for m in CONSOLES:
        schema = sc.intent_schema(m)
        assert schema["properties"]["ops"]["items"]["oneOf"], m
    with pytest.raises(Exception):
        sc.intent_schema("wing-nonesuch")


def test_every_op_in_the_vocabulary_has_a_case():
    used = {op["op"] for c in CASES["cases"] + CASES["refusals"] for op in c["intent"]["ops"]}
    used |= {"add_output", "assign", "order"}  # exercised below
    schema_ops = {b["properties"]["op"]["enum"][0]
                  for b in sc.intent_schema("wing-compact")["properties"]["ops"]["items"]["oneOf"]}
    assert schema_ops == used


def test_an_output_and_a_group_are_added_with_the_lowest_free_index():
    intent = {"name": "n", "notes": [], "ops": [
        {"op": "add_output", "name": "Matrix 1", "object": "matrix",
         "patch": {"group": "LCL", "first": 7}},
        {"op": "add_group", "object": "mute_group", "name": "Choir"}]}
    merge, _ = ic.apply_intent(intent, base(), "wing-compact", aes50_devices=RIG)
    assert merge.plan["outputs"]["Matrix 1"]["index"] == 1
    assert merge.plan["mute_groups"]["Choir"]["index"] == 4


def test_an_inferred_value_announces_itself_at_info():
    _, infos = ic.apply_intent(next(c for c in CASES["cases"] if c["id"] == "socket-unstated-fits-s16")["intent"], base(), "wing-compact",
                               aes50_devices=RIG)
    joined = "\n".join(infos)
    # the merge announces a socket Atoo chose, once, as Atoo's (not "the model's")
    assert "the change named no socket, so A 10 was chosen -- the first free A socket" in joined
    assert "the change named no socket, so A 16 was chosen -- the first free A socket" in joined
    assert "the first the model picked" not in joined and joined.count("A 10 was chosen") == 1
    assert "ch 14" in joined


def test_all_the_refusals_of_one_intent_are_given_together():
    intent = {"name": "n", "notes": [], "ops": [
        {"op": "drop", "object": "channel", "name": "Banjo"},
        {"op": "add_channel", "name": "Tamb", "patch": {"group": "A", "first": 17}}]}
    with pytest.raises(ic.IntentRefused) as raised:
        ic.compile_intent(intent, base(), "wing-compact", aes50_devices=RIG)
    assert len(raised.value.reasons) == 2


def test_the_category_table_is_applied_by_code_and_said():
    from atoo import category_table
    table = category_table.parse(
        '## Category table\n\n```json\n[{"name": "Vocals", "aliases": ["vocals"], '
        '"color": "Green", "hpf_hz": 100, "dca": ["Vocals"], "mute_group": ["Vocals"]}]\n```\n').table
    intent = {"name": "n", "notes": [], "ops": [
        {"op": "add_channel", "name": "Choir L", "category": "vocals"}]}
    merge, infos = ic.apply_intent(intent, base(), "wing-compact", category_table=table,
                                   aes50_devices=RIG)
    channel = merge.plan["channels"][-1]
    assert (channel["color"], channel["processing"]["hpf_hz"], channel["dca"]) == (
        "Green", 100, ["Vocals"])
    assert any("category table" in i.lower() or "Category" in i for i in infos)


def test_the_merge_still_refuses_a_send_to_a_bus_that_does_not_exist():
    intent = {"name": "n", "notes": [], "ops": [
        {"op": "add_channel", "name": "Choir L", "sends": [{"bus": "Nowhere"}]}]}
    merge, _ = ic.apply_intent(intent, base(), "wing-compact", aes50_devices=RIG)
    assert merge.refused and "Nowhere" in merge.refused[0].reason


def test_the_comparison_can_fail():
    case = copy.deepcopy(next(c for c in CASES["cases"] if c["id"] == "f-lead2-add"))
    merge, _ = ic.apply_intent(case["intent"], base(), "wing-compact", aes50_devices=RIG)
    case["today"]["add_channels"][0]["dca"] = ["Band"]
    assert project(merge) != project(today_merge(case, "wing-compact"))


# -- making a channel stereo or mono, and moving a channel that carries a preset ---------

def _apply(ops, plan=None, text="x", console="wing-compact"):
    return ic.apply_intent({"name": "t", "ops": ops, "notes": []}, plan or base(), console, text=text,
                           aes50_devices=RIG)


def _channel(merge, name):
    return next(c for c in merge.plan["channels"] if c["name"] == name)


def test_a_mono_channel_made_stereo_takes_the_free_socket_beside_it():
    plan = base()
    plan["channels"] = [c for c in plan["channels"] if c["name"] != "Gtr 1"]   # frees A 8
    merge, infos = _apply([{"op": "move_channel", "name": "Bass DI", "stereo": True}], plan)
    channel = _channel(merge, "Bass DI")
    assert channel["source"]["stereo"] is True
    assert channel["patch"]["sockets"] == [7, 8]
    assert not merge.refused
    assert any("stereo" in line for line in infos + merge.infos)


def test_a_mono_channel_made_stereo_with_its_other_half_taken_is_refused_naming_it():
    merge, _ = _apply([{"op": "move_channel", "name": "Lead Vox", "stereo": True}])
    assert [r.reason for r in merge.refused if "BV Gtr" in r.reason], merge.refused
    assert _channel(merge, "Lead Vox")["source"]["stereo"] is False


def test_a_stereo_channel_made_mono_keeps_the_first_socket():
    merge, _ = _apply([{"op": "move_channel", "name": "Keys", "stereo": False}])
    channel = _channel(merge, "Keys")
    assert channel["source"]["stereo"] is False
    assert channel["patch"]["sockets"] == [11]


def test_stereo_with_a_stated_pair_moves_the_channel_and_carries_no_derived_preset_values():
    # The channel is taken off its strip and added again; what the plan holds for a
    # preset (its expanded values) is code's to derive and is not part of an add.
    merge, _ = _apply([{"op": "move_channel", "name": "Lead Vox", "stereo": True,
                        "patch": {"group": "LCL", "first": 5, "count": 2}}])
    channel = _channel(merge, "Lead Vox")
    assert channel["patch"]["sockets"] == [5, 6]
    assert channel["source"]["stereo"] is True
    change_set, _ = ic.compile_intent(
        {"name": "t", "ops": [{"op": "move_channel", "name": "Lead Vox",
                               "patch": {"group": "LCL", "first": 5}}], "notes": []},
        base(), "wing-compact", text="x", aes50_devices=RIG)
    assert "preset_values" not in json.dumps(change_set["add"]["channels"])


def test_stereo_with_a_move_and_no_pair_named_takes_the_first_free_pair_at_info():
    plan = base()
    plan["channels"] = [c for c in plan["channels"] if c["name"] != "BV Keys"]   # frees A 15 (A 16 is free)
    merge, infos = _apply([{"op": "move_channel", "name": "Lead Vox", "stereo": True,
                            "place": {"at": 30}}], plan)
    channel = _channel(merge, "Lead Vox")
    assert channel["source"]["stereo"] is True and channel["patch"]["sockets"] == [15, 16]
    assert any("first free" in line for line in infos)


# -- assign: the DCAs, mute groups and sends a channel has --------------------------------

def test_assign_changes_the_groups_and_sends_of_a_channel_in_one_edit():
    merge, infos = _apply([{"op": "assign", "name": "Keys", "dca_add": ["Vocals"], "dca_remove": ["Band"],
                            "send_add": [{"bus": "Vox Wedge", "level_db": -6}],
                            "send_remove": ["Keys Wedge"]}])
    keys = _channel(merge, "Keys")
    assert keys["dca"] == ["Vocals"]
    assert [s["bus"] for s in keys["bus_sends"]] == ["Vox Wedge"]
    assert keys["bus_sends"][0]["level_db"] == -6
    assert not merge.refused


def test_assign_to_a_group_the_desk_lacks_makes_it_and_a_send_to_a_missing_bus_is_refused():
    merge, _ = _apply([{"op": "assign", "name": "Keys", "mute_group_add": ["Strings"]}], text="Put the Keys in a Strings mute group")
    assert "Strings" in _channel(merge, "Keys")["mute_group"] and "Strings" in merge.plan["mute_groups"]
    with pytest.raises(ic.IntentRefused) as raised:
        _apply([{"op": "assign", "name": "Keys", "send_add": [{"bus": "Nowhere"}]}])
    assert "Nowhere" in " ".join(raised.value.reasons)


def test_assign_taking_out_what_was_not_there_is_said_at_info():
    _, infos = _apply([{"op": "assign", "name": "Keys", "dca_remove": ["Drums"]}])
    assert any("Drums" in line for line in infos)


def test_an_intent_with_no_ops_is_refused_with_what_the_model_said():
    with pytest.raises(ic.IntentRefused) as raised:
        ic.compile_intent({"name": "t", "ops": [], "notes": ["There is no bus called Nowhere."]},
                          base(), "wing-compact", text="Send the Kick to Nowhere", aes50_devices=RIG)
    reasons = " ".join(raised.value.reasons)
    assert "no operation" in reasons and "There is no bus called Nowhere." in reasons
    assert raised.value.repairable      # the model is asked once more before the refusal stands


# -- an edit of a channel this same intent adds, and one physical fact stated two ways -----------

def test_an_edit_of_a_channel_the_intent_adds_is_part_of_the_add_and_nothing_is_refused():
    ops = [{"op": "add_channel", "name": "Cello", "kind": "mic"},
           {"op": "set", "object": "channel", "name": "Cello", "field": "processing.hpf_hz", "value": 90},
           {"op": "assign", "name": "Cello", "dca_add": ["Band"], "send_add": [{"bus": "Gtr Wedge", "level_db": -4}]},
           {"op": "set", "object": "channel", "name": "Cello", "field": "fader.fader_db", "value": -10}]
    merge, infos = _apply(ops, text="Add a Cello, HPF 90, in the Band DCA, to the Gtr Wedge, fader at -10")
    assert not merge.refused, merge.refused
    cello = _channel(merge, "Cello")
    assert cello["processing"]["hpf_hz"] == 90 and cello["dca"] == ["Band"] and cello["fader"]["fader_db"] == -10
    assert [(s["bus"], s["level_db"]) for s in cello["bus_sends"]] == [("Gtr Wedge", -4)]
    assert sum("is added by this intent, so the edit" in line for line in infos) == 3


def test_a_channel_the_intent_adds_can_be_renamed_and_made_stereo_in_the_same_intent():
    plan = base()
    plan["channels"] = [c for c in plan["channels"] if c["name"] != "BV Keys"]      # frees A 15, A 16
    ops = [{"op": "add_channel", "name": "Lute", "kind": "mic", "patch": {"group": "A", "first": 15}},
           {"op": "move_channel", "name": "Lute", "stereo": True},
           {"op": "rename", "object": "channel", "name": "Lute", "new_name": "Oud"}]
    merge, _ = _apply(ops, plan, text="Add a Lute on A 15, make it stereo, call it Oud")
    assert not merge.refused, merge.refused
    oud = _channel(merge, "Oud")
    assert oud["source"]["stereo"] is True and oud["patch"]["sockets"] == [15, 16]


def test_a_channel_added_and_made_stereo_where_the_other_half_is_taken_is_refused_naming_the_holder():
    ops = [{"op": "add_channel", "name": "Lute", "kind": "mic", "patch": {"group": "A", "first": 13}},
           {"op": "move_channel", "name": "Lute", "stereo": True}]
    with pytest.raises(ic.IntentRefused) as raised:
        _apply(ops, text="Add a Lute on A 13 and make it stereo")
    assert "the other half of the pair, is used by channel" in " ".join(raised.value.reasons)


@pytest.mark.parametrize("name,holder", [("Bass DI", "Gtr 1"), ("Lead Vox", "BV Gtr")])
def test_naming_two_sockets_for_a_mono_channel_is_refused_for_the_same_reason_as_asking_for_stereo(name, holder):
    by_flag = _apply([{"op": "move_channel", "name": name, "stereo": True}], text=f"Make the {name} channel stereo.")[0]
    sockets = next(c for c in base()["channels"] if c["name"] == name)["patch"]["sockets"][0]
    by_sockets = _apply([{"op": "move_channel", "name": name, "patch": {"group": "A", "first": sockets, "count": 2}}],
                        text=f"Put the {name} on A {sockets}-{sockets + 1}")[0]
    reasons = lambda merge: [r.reason for r in merge.refused]  # noqa: E731
    assert reasons(by_flag) and reasons(by_sockets)
    for merge in (by_flag, by_sockets):
        assert any(f"the other half of the pair, is used by channel '{holder}'" in r for r in reasons(merge)), reasons(merge)


def test_an_intent_that_moves_the_holder_and_pairs_its_neighbour_is_carried_out():
    """"Move Snare to A 7 and make Kick stereo on A 1+2": the engineer names the holder."""
    ops = [{"op": "move_channel", "name": "Snare", "patch": {"group": "A", "first": 16}},
           {"op": "move_channel", "name": "Kick", "patch": {"group": "A", "first": 1, "count": 2}}]
    plan = base()
    plan["channels"] = [c for c in plan["channels"] if c["name"] != "BV Keys"]      # frees A 15, A 16
    merge, _ = _apply(ops, plan, text="Move Snare to A 16 and make Kick stereo on A 1+2")
    assert not merge.refused, [r.reason for r in merge.refused]
    assert _channel(merge, "Kick")["patch"]["sockets"] == [1, 2] and _channel(merge, "Snare")["patch"]["sockets"] == [16]


def test_a_channel_added_renamed_and_then_set_by_its_new_name_is_folded_into_the_add():
    ops = [{"op": "add_channel", "name": "Lute", "kind": "mic"},
           {"op": "rename", "object": "channel", "name": "Lute", "new_name": "Oud"},
           {"op": "set", "object": "channel", "name": "Oud", "field": "processing.hpf_hz", "value": 90}]
    merge, infos = _apply(ops, text="Add a Lute, call it Oud, HPF 90 on the Oud")
    assert not merge.refused, merge.refused
    oud = _channel(merge, "Oud")
    assert oud["processing"]["hpf_hz"] == 90 and not any(c["name"] == "Lute" for c in merge.plan["channels"])
