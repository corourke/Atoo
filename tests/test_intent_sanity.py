"""The intent compiler refuses nonsense that is valid against the schema
(`atoo/intent_sanity.py`). Frozen inputs only
(`tests/fixtures/intent/`); nothing here reads `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "intent"


from atoo import intent_compile as ic  # noqa: E402

BASE = json.loads((FIXTURES / "demo_base.plan.json").read_text())
RIG = {"A": "S16"}
TAMB = 'Add a tambourine mic "Tamb" on A 17'
INPUT_LIST = (FIXTURES / "input.csv").read_text()


def compile_(ops, request, **kw):
    intent = {"name": "n", "notes": [], "ops": ops}
    return ic.compile_intent(intent, copy.deepcopy(BASE), "wing-compact", text=request,
                             aes50_devices=RIG, **kw)


def add(name, **kw):
    return {"op": "add_channel", "name": name, **kw}


def refusal(ops, request, **kw):
    with pytest.raises(ic.IntentRefused) as raised:
        compile_(ops, request, **kw)
    return " | ".join(raised.value.reasons)


def test_the_degenerate_reply_from_the_7b_model_is_refused_with_every_reason():
    reply = json.loads((FIXTURES / "qwen7b_socket_past_s16.reply.json").read_text())
    with pytest.raises(ic.IntentRefused) as raised:
        ic.compile_intent(reply, copy.deepcopy(BASE), "wing-compact", text=TAMB, aes50_devices=RIG)
    said = " | ".join(raised.value.reasons)
    assert "'few', 'words'" in said                       # the strip's name
    assert "vocals寒冬" in said and "not one this show knows" in said   # the category
    assert "SM500" in said                                # the microphone
    # nothing was planned: it is a refusal, not a change set with a channel on ch 14
    assert len(raised.value.reasons) == 3


@pytest.mark.parametrize("name,request_text", [
    ("F Lead2", 'Add another vocal mic "F Lead2"'),
    ("Choir L", 'Add two choir mics, "Choir L" and "Choir R"'),
    ("Choir", "Add a choir mic"),
    ("Choir 2", "Add a choir mic"),
    ("Tamb", "Add a tambourine mic"),                    # an abbreviation of a word said
    ("Drum IEM 2", "Add a second Drum IEM mic"),           # words from the desk
    ("DrumsComp", 'Add a mic called "DrumsComp"'),         # verbatim
    ("DrumsComp", "Add a drums compressor channel"),       # its parts: Drums + Comp(ressor)
    ("Café", "Add a Café ambience mic"),                   # a letter the request itself uses
    ("Vox Verb 2", "Add a second vocal reverb return"),
])
def test_legitimate_names_are_not_refused(name, request_text):
    compile_([add(name)], request_text)


@pytest.mark.parametrize("name,said", [
    ("Kazoo寒冬", "contains"), ("Zork Blorp", "'Zork', 'Blorp'"), ("Add a few words", "'few', 'words'"),
    ("Café", "'é'")])
def test_a_name_nobody_said_is_refused_and_says_which_word(name, said):
    assert said in refusal([add(name)], TAMB)


def test_a_label_with_a_stray_script_is_replaced_not_refused():
    from atoo import patch
    intent = {"name": "Add a mic寒冬", "notes": ["fine", "also寒冬"], "ops": [add("Tamb")]}
    cs, infos = ic.compile_intent(intent, copy.deepcopy(BASE), "wing-compact", text=TAMB,
                                  aes50_devices=RIG)
    assert cs["name"] == patch.default_name(TAMB) and cs["notes"] == ["fine"]
    assert any("name had characters" in i for i in infos) and any("note" in i for i in infos)


def test_a_new_bus_group_or_output_the_model_made_up_is_named_from_the_request_instead():
    """The name of a new bus, DCA, mute group or output is the engineer's only when
    its words are in the request; otherwise code names it from the request, at INFO."""
    for op, word in (({"op": "add_bus", "name": "Zork Blorp"}, "bus"),
                     ({"op": "add_group", "object": "dca", "name": "Zork Blorp"}, "DCA"),
                     ({"op": "add_output", "name": "Zork Blorp", "object": "matrix"}, "output")):
        cs, infos = compile_([op], "Add a thing")
        added = {**cs["add"]["busses"], **cs["add"]["dcas"], **cs["add"]["outputs"]}
        assert "Zork Blorp" not in added
        assert any("Zork Blorp" in i and "no name was given" in i for i in infos), infos
    # a rename, and a channel's new group, are still held to the words
    assert "'Zork', 'Blorp'" in refusal(
        [{"op": "rename", "object": "channel", "name": "Keys", "new_name": "Zork Blorp"}], TAMB)
    assert "'Zork', 'Blorp'" in refusal([add("Tamb", dca=["Zork Blorp"])], TAMB)
    # an existing DCA, and a new one the request names, are fine
    compile_([add("Tamb", dca=["Vocals"])], TAMB)
    compile_([add("Tamb", dca=["Percussion"])], "Add a tambourine mic Tamb in a Percussion DCA")


def test_a_category_must_be_one_the_show_knows():
    from atoo import category_table
    table = category_table.parse(
        '## Category table\n\n```json\n[{"name": "Percussion", "aliases": ["percussion", "perc"], '
        '"color": "Green"}]\n```\n').table
    compile_([add("Tamb", category="percussion")], TAMB, category_table=table)
    assert "'zither'" in refusal([add("Tamb", category="zither")], TAMB, category_table=table)
    compile_([add("Tamb", category="drums")], TAMB, input_list_text=INPUT_LIST)  # the input list's
    compile_([add("Tamb", category="Horns")], TAMB)                              # a domain word
    assert "not one this show knows" in refusal([add("Tamb", category="zither")], TAMB)


def test_a_microphone_model_must_have_been_said():
    compile_([add("Tamb", model="SM57")], TAMB + ", an SM57")              # in the request
    compile_([add("Tamb", model="Beta 91A")], TAMB)                        # on the desk
    compile_([add("Tamb", model="e604")], TAMB, input_list_text=INPUT_LIST)  # in the input list
    assert "SM500" in refusal([add("Tamb", model="SM500")], TAMB)


def test_a_colour_must_be_one_of_the_consoles_and_a_preset_one_in_the_library():
    compile_([add("Tamb", color="Green")], TAMB)
    compile_([add("Tamb", color="crimson")], TAMB)                          # a retired alias
    said = refusal([add("Tamb", color="Gold")], TAMB)
    assert "'Gold' is not a colour this console has" in said and "Turquoise" in said
    assert "not a preset in the library" in refusal([add("Tamb", preset="Zither")], TAMB,
                                                    known_presets=["A Sax"])
    compile_([add("Tamb", preset="A Sax")], TAMB, known_presets=["A Sax"])
    compile_([add("Tamb", preset="Anything")], TAMB)                        # no library given
    assert "not a colour" in refusal(
        [{"op": "set", "object": "channel", "name": "Keys", "field": "color", "value": "寒冬"}], TAMB)


def test_without_the_request_the_words_are_not_traced_but_the_characters_are():
    intent = {"name": "n", "notes": [], "ops": [add("Zork Blorp")]}
    ic.compile_intent(intent, copy.deepcopy(BASE), "wing-compact", aes50_devices=RIG)
    intent["ops"] = [add("Zork寒冬")]
    with pytest.raises(ic.IntentRefused):
        ic.compile_intent(intent, copy.deepcopy(BASE), "wing-compact", aes50_devices=RIG)


def test_every_corpus_intent_still_compiles_with_the_input_list_and_presets():
    cases = json.loads((FIXTURES / "cases.json").read_text())
    for case in cases["cases"]:
        ic.compile_intent(case["intent"], copy.deepcopy(BASE), "wing-compact", text=case["request"],
                          aes50_devices=RIG, input_list_text=INPUT_LIST, known_presets=["A Sax"])


@pytest.mark.parametrize("op", [
    {"op": "add_group", "name": "Choir"},                      # no object
    {"op": "add_channel"}, {"op": "rename", "object": "channel", "name": "Keys"},
    {"op": "set", "object": "channel", "name": "Keys", "field": "fader.fader_db"},
    {"op": "add_output", "name": "Out"}, {"op": "drop"}])
def test_an_op_missing_what_it_cannot_do_without_is_refused_not_a_crash(op):
    """A 7B model wrote an `add_group` with no `object` and the compile died on a
    KeyError, taking the whole eval run with it."""
    said = refusal([op], TAMB)
    assert "not well formed" in said


def test_a_set_on_a_group_name_is_carried_out_on_its_members_and_said():
    """Three local models wrote `set channel "Vocals"` for "HPF 100 on the vocals":
    the Vocals DCA, not a channel. The engineer plainly meant its members."""
    cs, infos = compile_([{"op": "set", "object": "channel", "name": "Vocals", "field": "processing.hpf_hz",
                           "value": 100}], "HPF 100 on the vocals")
    assert [m["name"] for m in cs["modify"]] == ["Lead Vox", "BV Gtr", "BV Keys"]
    assert all(m["fields"] == {"processing.hpf_hz": 100} for m in cs["modify"])
    assert any("is the 'Vocals' DCA" in i and "3 channels" in i for i in infos)
    # a name that is neither a channel nor a group is still refused
    assert "no channel of that name" in refusal(
        [{"op": "set", "object": "channel", "name": "Choirs", "field": "processing.hpf_hz", "value": 100}], "x")


def test_a_new_bus_may_take_the_conventions_own_name_for_it():
    conventions = "## Busses\n- Monitor 1 to 5, and a Reverb Send.\n"
    cs, infos = compile_([{"op": "add_bus", "name": "Reverb Send"}], "Add the mix busses",
                         conventions_text=conventions)
    assert "Reverb Send" in cs["add"]["busses"] and not any("no name was given" in i for i in infos)
    # but a strip's name still has to come from the request, the input list or the desk
    assert "'Monitor'" in refusal([add("Monitor 1")], "Add a mic", conventions_text=conventions)


