"""What a change ASKS FOR is a fact the merge can be told, not only a sentence
it reads (`patch.Asked`).

Five decisions of `merge_change` -- an insert that renumbers, the strip a new
channel goes on, whether its socket was named, whether a fader or a mute may
be moved, whether a gain was stated -- were read from the typed words. A front
end that has them as facts (`atoo patch --intent`) states them outright, with
the same results and no sentence to be mis-read. A typed change is unchanged:
`tests/test_patch_insert.py` and the rest of the patch suite are its proof.

Plans and desks are `test_amend`'s frozen applied show; nothing reads `examples/`.
"""

from __future__ import annotations

from atoo import patch
from atoo.amend import ChangeKind, strip_occupancy
from test_amend import applied_plan, horn, occupancy_state


def _desk(plan):
    return strip_occupancy(occupancy_state(theirs=(), plan=plan), plan)


def _hihat(number=3, socket=21) -> dict:
    channel = horn(number, "HiHat", socket)
    channel["dca"], channel["mute_group"], channel["bus_sends"] = [], [], []
    return channel


def _change(*channels, **extra) -> dict:
    change_set = patch.empty_change_set("Add HiHat")
    change_set["add"]["channels"] = list(channels or (_hihat(),))
    change_set.update(extra)
    return change_set


def _review(change_set, *, text=None):
    plan = applied_plan()
    return patch.plan_patch(plan, change_set, _desk(plan), console_model="wing-compact", text=text)


def test_stated_as_a_fact_an_insert_renumbers_with_no_word_asking_for_it():
    asked = patch.Asked(insert=True, positions={"HiHat": 3})
    amendment, merge = _review(_change(**{patch.ASKED_KEY: asked.to_dict()}), text="HiHat after Snare")
    assert len([c for c in amendment.changes if c.kind is ChangeKind.SHIFTED]) == 17
    assert merge.inserted == {"hihat": "ch:3"}


def test_stated_as_a_fact_that_it_is_not_an_insert_it_is_not_even_if_the_words_say_insert():
    asked = patch.Asked(insert=False, positions={"HiHat": 3})
    amendment, merge = _review(_change(**{patch.ASKED_KEY: asked.to_dict()}),
                               text="insert HiHat after Snare and renumber")
    assert not [c for c in amendment.changes if c.kind is ChangeKind.SHIFTED]
    assert merge.not_renumbered and merge.not_renumbered[0][0] == "HiHat"


def test_the_same_facts_are_read_back_from_a_saved_change_set():
    asked = patch.Asked(insert=True, positions={"HiHat": 3}, sockets={"HiHat"}, fader=False,
                        mute=True, gain={"HiHat"}, picked_by="Atoo")
    saved = patch.validate_change_set(_change(**{patch.ASKED_KEY: asked.to_dict()}))
    back = patch.Asked.for_change_set(saved, "words")
    assert (back.insert, back.positions, back.sockets, back.fader, back.mute, back.gain,
            back.picked_by) == (True, {"hihat": 3}, {"hihat"}, False, True, {"hihat"}, "Atoo")
    assert patch.Asked.for_change_set(_change(), "words").words == "words"   # no facts: the words


def test_a_fader_or_mute_is_moved_only_when_the_facts_name_it_not_the_words():
    plan = applied_plan()
    name = plan["channels"][0]["name"]
    edit = {"object": "channel", "name": name, "change": "x", "fields": {"fader.fader_db": -6}}
    for named, moved in ((True, True), (False, False)):
        change_set = patch.empty_change_set("fader")
        change_set["modify"] = [edit]
        asked = patch.Asked(fader=named, mute=False)
        change_set[patch.ASKED_KEY] = asked.to_dict()
        amendment, merge = _review(change_set, text="set the fader" if not named else "set it")
        assert bool(merge.edits) is moved, (named, [c.line() for c in amendment.changes])


def test_a_socket_the_facts_say_was_chosen_by_atoo_is_announced_as_atoos():
    channel = _hihat(socket=3)           # A 3 is Tom1's: taken
    channel["patch"]["stated"] = False
    asked = patch.Asked(sockets=set(), picked_by="Atoo")
    _amendment, merge = _review(_change(channel, **{patch.ASKED_KEY: asked.to_dict()}))
    said = [i for i in merge.infos if "HiHat" in i and "no socket" in i]
    assert said and "the first the model picked" not in said[0]
    # an untouched socket the model proposed keeps the model's attribution
    free = _hihat(socket=30)
    free["patch"]["stated"] = False
    _amendment, merge = _review(_change(free), text="add HiHat")
    assert any("the first the model picked" in i for i in merge.infos)
    asked = patch.Asked(sockets=set(), picked_by="Atoo")
    _amendment, merge = _review(_change(free, **{patch.ASKED_KEY: asked.to_dict()}))
    assert any("the first free" in i and "model picked" not in i for i in merge.infos)


def test_a_gain_the_facts_name_counts_as_stated_for_that_channel_only():
    asked = patch.Asked.from_dict({"gain": ["HiHat"]})
    assert asked.gain_stated({"name": "HiHat"}) and not asked.gain_stated({"name": "Snare"})
