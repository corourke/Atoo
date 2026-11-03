"""Making a running channel stereo, or mono again.

"Make ch 5 stereo" is an instruction, not a rule to refuse with "drop it and
add it again". A mono channel on an odd socket takes the next socket if nothing
uses it; what physically cannot be done (an even socket, a second socket
another channel uses) is refused with the reason. Nothing reads a bundle under
`examples/`: the frozen applied show, plus an extra mono channel on A 21 with A 22 free,
Snare is on A 2 and Kick on A 1 next to it.
"""

from __future__ import annotations

import pytest

from atoo import amend, patch
from atoo.amend import ChangeKind
from atoo.amend import strip_occupancy
from test_amend import applied_plan, horn, occupancy_state

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _stereo(name: str, model: str = "wing-compact", *, stereo: bool = True, extra=None):
    fields = {"source.stereo": stereo, **(extra or {})}
    change_set = patch.empty_change_set("stereo")
    change_set["modify"] = [{"object": "channel", "name": name, "change": "x", "fields": fields}]
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    plan["channels"].append(horn(30, "Extra", 21))      # mono on A 21; A 22 is free
    desk = strip_occupancy(occupancy_state(plan=plan), plan)
    amendment, merge = patch.plan_patch(plan, patch.validate_change_set(change_set), desk,
                                        console_model=model)
    return amendment, merge


@pytest.mark.parametrize("model", MODELS)
def test_a_mono_channel_on_an_odd_socket_takes_the_next_one(model):
    amendment, merge = _stereo("Extra", model)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    eg = next(c for c in merge.plan["channels"] if c["name"] == "Extra")
    assert eg["source"]["stereo"] is True and eg["patch"]["sockets"] == [21, 22]
    assert any("made stereo on A 21+22" in i for i in merge.infos)
    written = {t.address: t.compute_value("") for t in amend.amendment_targets(amendment).to_write}
    assert written["/io/in/A/21/mode"] == written["/io/in/A/22/mode"] == "ST"
    assert [e.path for e in merge.edits] == ["source.stereo", "patch"]


def test_a_second_socket_another_channel_uses_is_refused_with_the_reason():
    _a, merge = _stereo("Kick")
    [refused] = merge.refused
    assert "A 2, the other half of the pair, is used by channel 'Snare'" in refused.reason


def test_a_channel_on_an_even_socket_cannot_be_half_of_a_pair_and_says_why():
    _a, merge = _stereo("Snare")
    [refused] = merge.refused
    assert "starts on an odd socket" in refused.reason


def test_the_change_may_name_the_pair_itself():
    # A 23+24: free. (A 21 is the extra channel's: moving the Kick onto it
    # would turn that strip's link off too, which the change would have to name.)
    amendment, merge = _stereo("Kick", extra={"patch": {"group": "A", "sockets": [23, 24],
                                                        "stated": True}})
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    kick = next(c for c in merge.plan["channels"] if c["name"] == "Kick")
    assert kick["patch"]["sockets"] == [23, 24] and kick["source"]["stereo"] is True


def test_a_pair_that_cannot_be_formed_is_refused():
    _a, merge = _stereo("Kick", extra={"patch": {"group": "A", "sockets": [21, 23],
                                                 "stated": True}})
    assert merge.refused


@pytest.mark.parametrize("model", MODELS)
def test_a_stereo_channel_made_mono_keeps_its_first_socket(model):
    amendment, merge = _stereo("Keys", model, stereo=False)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    keys = next(c for c in merge.plan["channels"] if c["name"] == "Keys")
    assert keys["source"]["stereo"] is False and keys["patch"]["sockets"] == [15]
    assert any("A 16, its other half, is left exactly as the desk has it" in i
               for i in merge.infos)
    written = {t.address: t.compute_value("") for t in amend.amendment_targets(amendment).to_write}
    assert written["/io/in/A/15/mode"] == "M"


def test_a_stereo_channel_made_mono_lets_go_of_the_second_input_list_row(tmp_path):
    """The second row of the pair (Keys R) stays on the list, unused; a change is
    not called to account for it, and the review's pre-flight does not stop the change."""
    import json
    from pathlib import Path

    from atoo import input_list
    from atoo.verify_plan import rows_for_a_change, verify_plan

    live = Path(__file__).resolve().parent / "fixtures" / "live-show"
    plan = json.loads((live / "plan.json").read_text())
    rows = input_list.parse_input_list((live / "input.csv").read_text())
    stereo = next(c for c in plan["channels"] if (c["source"].get("pair_input")))
    change_set = patch.empty_change_set("mono")
    change_set["modify"] = [{"object": "channel", "name": stereo["name"], "change": "x",
                             "fields": {"source.stereo": False}}]
    merge = patch.merge_change(plan, patch.validate_change_set(change_set),
                               console_model="wing-compact")
    mono = next(c for c in merge.plan["channels"] if c["name"] == stereo["name"])
    assert "pair_input" not in mono["source"] and len(mono["patch"]["sockets"]) == 1
    assert any("second input-list row" in i for i in merge.infos)
    cut, _stand_ins, _set_aside = rows_for_a_change(merge.plan, rows, changed={stereo["name"]})
    result = verify_plan(merge.plan, rows=cut, console_model="wing-compact")
    assert not [f for f in result.findings if f.code == "reconcile.dropped-input"]


def test_a_named_pair_with_a_socket_another_channel_uses_is_refused_like_a_pair_left_to_be_chosen():
    """One physical fact, one answer: the other half is Snare's whether the change says "make it
    stereo" or names A 1-2 itself."""
    _a, left_to_code = _stereo("Kick")
    _a, named = _stereo("Kick", extra={"patch": {"group": "A", "sockets": [1, 2], "stated": True}})
    [by_code], [by_name] = left_to_code.refused, named.refused
    assert "A 2, the other half of the pair, is used by channel 'Snare'" in by_code.reason
    assert "A 2, the other half of the pair, is used by channel 'Snare'" in by_name.reason


def _two_edits(model: str = "wing-compact"):
    """Snare moved to A 7 and Kick made stereo on A 1+2, in ONE change: the holder is named."""
    change_set = patch.empty_change_set("snare moves, kick pairs")
    change_set["modify"] = [
        {"object": "channel", "name": "Snare", "change": "x", "fields": {"patch": {"group": "A", "sockets": [7], "stated": True}}},
        {"object": "channel", "name": "Kick", "change": "x", "fields": {
            "source.stereo": True, "patch": {"group": "A", "sockets": [1, 2], "stated": True}}}]
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    plan["channels"] = [c for c in plan["channels"] if c["name"] != "Bass DI"] if any(
        c["name"] == "Bass DI" for c in plan["channels"]) else plan["channels"]
    desk = strip_occupancy(occupancy_state(plan=plan), plan)
    return patch.plan_patch(plan, patch.validate_change_set(change_set), desk, console_model=model)


def test_a_change_that_moves_the_holder_and_pairs_the_neighbour_is_carried_out():
    """An explicit instruction that names the holder goes through: the desk still shows Snare on A 2,
    but this change moves it."""
    _amendment, merge = _two_edits()
    assert not merge.refused, [r.reason for r in merge.refused]
    kick = next(c for c in merge.plan["channels"] if c["name"] == "Kick")
    snare = next(c for c in merge.plan["channels"] if c["name"] == "Snare")
    assert kick["source"]["stereo"] is True and kick["patch"]["sockets"] == [1, 2]
    assert snare["patch"]["sockets"] == [7]


def test_the_refusal_for_a_named_pair_says_which_socket_of_it_is_held():
    _a, held_second = _stereo("Kick", extra={"patch": {"group": "A", "sockets": [1, 2], "stated": True}})
    [by_second] = held_second.refused
    assert "A 2, the other half of the pair, is used by channel 'Snare'" in by_second.reason
    # a pair whose FIRST socket another channel holds is not "the other half"
    _a, held_first = _stereo("Extra", extra={"patch": {"group": "A", "sockets": [1, 2], "stated": True}})
    [by_first] = held_first.refused
    assert "A 1, one socket of the pair, is used by channel 'Kick'" in by_first.reason


def test_it_makes_no_difference_which_of_the_two_edits_is_written_first():
    change_set = patch.empty_change_set("kick pairs, snare moves")
    change_set["modify"] = [
        {"object": "channel", "name": "Kick", "change": "x", "fields": {
            "source.stereo": True, "patch": {"group": "A", "sockets": [1, 2], "stated": True}}},
        {"object": "channel", "name": "Snare", "change": "x", "fields": {"patch": {"group": "A", "sockets": [7], "stated": True}}}]
    plan = applied_plan()
    desk = strip_occupancy(occupancy_state(plan=plan), plan)
    _amendment, merge = patch.plan_patch(plan, patch.validate_change_set(change_set), desk,
                                         console_model="wing-compact")
    assert not merge.refused, [r.reason for r in merge.refused]


def _entries(entries, model="wing-compact"):
    change_set = patch.empty_change_set("several edits of one channel")
    change_set["modify"] = [{"object": "channel", "name": n, "change": "x", "fields": f} for n, f in entries]
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    plan["channels"].append(horn(30, "Extra", 21))      # mono on A 21; A 22 is free
    desk = strip_occupancy(occupancy_state(plan=plan), plan)
    _a, merge = patch.plan_patch(plan, patch.validate_change_set(change_set), desk, console_model=model)
    return merge


@pytest.mark.parametrize("entries", [
    [("Extra", {"source.stereo": True}), ("Extra", {"name": "Extra ST"})],
    [("Extra", {"name": "Extra ST"}), ("Extra", {"source.stereo": True})],
    [("Extra", {"name": "Extra ST"}), ("Extra ST", {"source.stereo": True})],
    [("Extra", {"processing.hpf_hz": 90}), ("Extra", {"source.stereo": True}), ("Extra", {"name": "Extra ST"})],
], ids=["stereo-then-rename", "rename-then-stereo-by-old-name", "rename-then-stereo-by-new-name", "three-entries"])
def test_several_entries_on_one_channel_are_one_edit_found_by_its_old_or_its_new_name(entries):
    """"Make Extra stereo and call it Extra ST": however the change is written, one object is edited."""
    merge = _entries(entries)
    assert not merge.refused, [r.reason for r in merge.refused]
    extras = [c for c in merge.plan["channels"] if c["name"].startswith("Extra")]
    assert [c["name"] for c in extras] == ["Extra ST"]
    assert extras[0]["source"]["stereo"] is True and extras[0]["patch"]["sockets"] == [21, 22]


def test_an_entry_naming_a_channel_that_was_never_on_the_desk_is_still_refused_after_a_rename():
    merge = _entries([("Extra", {"name": "Extra ST"}), ("Nothing", {"processing.hpf_hz": 90})])
    assert [r.reason for r in merge.refused] == ["the change edits it (x), and no channel of that name is on the desk"]
