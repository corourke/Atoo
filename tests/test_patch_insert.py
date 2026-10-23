"""`atoo patch`: an explicit insert renumbers the strips after it; "add X
after Snare" does not, and says what to type to make it.

The rule is the maintainer's: *if the patch instruction says specifically to
insert it, then yes the channels must be renumbered; if not specifically
asked for, then no -- note the ambiguous case and give the user specific
language to enable renumbering.* The usual reason is something missed on the
input list, so the desk has to be lined up with the real one on site.

Every plan and desk here is built from `test_amend`'s frozen copy of the
applied show (19 channels on ch 1-19); nothing reads `examples/`.
"""

from __future__ import annotations

import copy
import json

import pytest

from atoo import amend, patch, undo
from atoo.amend import ChangeKind, strip_occupancy
from test_amend import (DeskConsole, applied_plan, full_console_state, horn,  # noqa: E402
                        occupancy_state)

INSERT = "insert HiHat after Snare and renumber the channels after it"
ADD = "add HiHat after Snare"


def _kinds(amendment, kind) -> list:
    return [c for c in amendment.changes if c.kind is kind]


def _desk(plan=None, *, theirs=()):
    plan = plan if plan is not None else applied_plan()
    return strip_occupancy(occupancy_state(theirs=theirs, plan=plan), plan)


def _change(*channels: dict, name: str = "Add HiHat") -> dict:
    change_set = patch.empty_change_set(name)
    change_set["add"]["channels"] = list(channels)
    return change_set


def _hihat(number: int = 3, socket: int = 21) -> dict:
    channel = horn(number, "HiHat", socket)
    channel["dca"], channel["mute_group"] = [], []
    channel["bus_sends"] = []
    return channel


def _review(text: str, *channels: dict, plan=None, theirs=()):
    plan = plan if plan is not None else applied_plan()
    return patch.plan_patch(plan, _change(*channels or (_hihat(),)), _desk(plan, theirs=theirs),
                            console_model="wing-compact", text=text)


# ---------------------------------------------------------------- the words


@pytest.mark.parametrize("text", [
    "insert HiHat after Snare", "Insert a hi-hat as channel 3 and move the rest down",
    "put HiHat after Snare and renumber the channels after it", "make room for HiHat after Snare",
    "shift the rest down and add HiHat on ch 3", "inserting HiHat after the snare",
])
def test_these_words_ask_for_an_insert(text):
    assert patch._INSERT_WORDS.search(text)


@pytest.mark.parametrize("text", [
    "add HiHat after Snare", "HiHat as channel 3", "move Playback to ch 16 on A 16",
    "add a hi-hat channel", "put the sax in the Horns DCA",
])
def test_these_words_do_not(text):
    assert not patch._INSERT_WORDS.search(text)


# ------------------------------------------------------ an explicit insert


def test_an_explicit_insert_moves_every_strip_after_it_and_lists_each():
    amendment, merge = _review(INSERT)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    moved = _kinds(amendment, ChangeKind.SHIFTED)
    # ch 3..19 each move down one, and each is its own line of the review
    assert [(c.where, c.slot) for c in moved][:2] == [("'HH'", "ch:4"), ("'Tom1'", "ch:5")]
    assert len(moved) == 17
    assert [t[1:] for t in amendment.shifted][0] == ("ch:3", "ch:4")
    assert amendment.shifted[-1][1:] == ("ch:19", "ch:20")
    for change in moved:
        assert change.line() in amendment.summary()
    [added] = _kinds(amendment, ChangeKind.ADDED)
    assert added.slot == "ch:3" and "inserted" in added.reason
    effective = {c["name"]: c["channel"] for c in amendment.effective_plan["channels"]}
    assert effective["Snare"] == 2 and effective["HiHat"] == 3 and effective["HH"] == 4
    assert effective["Tom1"] == 5 and sorted(effective.values()) == list(range(1, 21))
    assert any("inserts 'HiHat' at ch 3" in i and "17 channel(s)" in i for i in amendment.infos)
    assert merge.renumbered["ch:3"] == "ch:4" and merge.inserted == {"hihat": "ch:3"}


def test_the_merge_does_not_edit_the_base():
    plan = applied_plan()
    before = copy.deepcopy(plan)
    patch.merge_change(plan, _change(_hihat()), occupancy=_desk(plan), text=INSERT)
    assert plan == before


def test_what_refers_to_a_channel_moves_with_it():
    """Sends, DCA and mute-group membership are the channel's own fields, so
    they go with it -- the moved entry is the same channel on a new number."""
    plan = applied_plan()
    amendment, _ = _review(INSERT, plan=plan)
    by_name = {c["name"]: c for c in amendment.effective_plan["channels"]}
    for old in plan["channels"]:
        if old["channel"] < 3:
            continue
        new = by_name[old["name"]]
        assert new["channel"] == old["channel"] + 1
        for field in ("bus_sends", "dca", "mute_group", "patch", "processing", "fader"):
            assert new[field] == old[field]
        assert f"ch:{old['channel']} -> ch:{new['channel']}" in new["provenance"]["channel"]


def test_the_shifted_strips_are_written_and_every_other_address_is_withheld():
    amendment, _ = _review(INSERT)
    targets = amend.amendment_targets(amendment)
    assert not targets.collisions
    written = {t.address for t in targets.to_write}
    assert "/ch/4/name" in written and "/ch/20/in/conn/in" in written
    assert not any(a.startswith(("/ch/1/", "/ch/2/")) for a in written)
    # a socket is the source's, and the source moved with its channel
    assert not any(a.startswith("/io/in/") and "/A/2" not in a for a in written
                   if a.startswith("/io/in/A/1") or a.startswith("/io/in/A/3"))
    assert targets.shift_clears, "what the old occupant left must be cleared"
    assert all(t.description.startswith("left by the channel the insert moved off it")
               for t in targets.shift_clears)
    assert {t.address for t in targets.shift_clears} <= written


def test_a_write_and_its_undo_put_every_address_back(tmp_path):
    """The property the maintainer asked for: Undo must put it back."""
    amendment, _ = _review(INSERT)
    state = full_console_state()
    console = DeskConsole(state)
    before = dict(console.state)
    journal = tmp_path / "insert.journal.json"
    result = amend.apply_amendment(amendment, console, dry_run=False, journal_path=str(journal))
    assert not result.aborted
    after = dict(console.state)
    # HH, which stood on ch 3, now stands on ch 4 with everything it had
    assert after["/ch/3/name"][0] == "HiHat" and after["/ch/4/name"][0] == "HH"
    assert after["/ch/4/in/conn/in"][0] == before["/ch/3/in/conn/in"][0]
    assert after["/ch/20/name"][0] == "TRAX"
    # a send the old occupant of ch 3 had, which HiHat does not, is gone from the strip
    assert before["/ch/3/send/1/on"][0] == 1 and after["/ch/3/send/1/on"][0] == 0
    assert after["/ch/4/send/1/on"][0] == before["/ch/3/send/1/on"][0]

    payload = json.loads(journal.read_text())
    scope = payload["scope"]
    assert scope["renumbered"][0] == "HH: ch:3 -> ch:4" and len(scope["renumbered"]) == 17
    assert "/ch/3" in scope["grants"] and "/ch/20" in scope["grants"]
    assert "ch:3" in scope["strips"]

    undone = undo.undo_from_journal(payload, console, dry_run=False)
    assert not undone.aborted
    differing = {a for a in set(before) | set(console.state)
                 if console.state.get(a) != before.get(a)}
    assert differing == set()


def test_the_untouched_strips_are_proved_untouched_by_the_witness_set():
    amendment, _ = _review(INSERT)
    targets = amend.amendment_targets(amendment)
    witness = {a for a, _ in amend.witness_addresses(targets)}
    assert "/ch/1/name" in witness and "/ch/2/name" in witness
    assert "/ch/4/name" not in witness and "/ch/3/name" not in witness


def test_the_review_json_lists_every_strip_that_moves():
    amendment, _ = _review(INSERT)
    review = amend.review_payload(_desk(), amendment, amend.amendment_targets(amendment))
    assert len(review["shifted"]) == 17
    assert review["shifted"][0] == {"name": "HH", "from": "ch:3", "to": "ch:4"}
    assert review["shift_clears"]
    assert sum(c["kind"] == "shifted" for c in review["changes"]) == 17
    assert not review["blocked"]


# ---------------------------------------- the model puts it somewhere else


def test_the_words_decide_when_the_model_ignored_the_position():
    """The model proposed the end of the list; the change says insert after
    Snare, which is what happens."""
    amendment, merge = _review(INSERT, _hihat(number=20))
    assert not amendment.blocked
    assert amendment.effective_plan["channels"][-1]["channel"] in range(1, 21)
    by_name = {c["name"]: c["channel"] for c in amendment.effective_plan["channels"]}
    assert by_name["HiHat"] == 3 and by_name["HH"] == 4
    assert merge.inserted == {"hihat": "ch:3"}


def test_several_channels_inserted_together_take_consecutive_strips():
    one, two = _hihat(3, 21), horn(4, "Ride", 22)
    two["dca"], two["mute_group"], two["bus_sends"] = [], [], []
    amendment, _ = _review("insert HiHat and Ride after Snare", one, two, theirs=())
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    by_name = {c["name"]: c["channel"] for c in amendment.effective_plan["channels"]}
    assert (by_name["HiHat"], by_name["Ride"], by_name["HH"]) == (3, 4, 5)
    assert len(_kinds(amendment, ChangeKind.SHIFTED)) == 17
    assert amendment.shifted[-1][1:] == ("ch:19", "ch:21")


def test_the_move_stops_at_the_first_free_strip():
    plan = applied_plan()
    plan["channels"] = [c for c in plan["channels"] if c["channel"] != 6]
    amendment, merge = _review(INSERT, plan=plan)
    assert not amendment.blocked
    # ch 3, 4, 5 move to 4, 5, 6; ch 7 onward are where they were
    assert [t[1:] for t in amendment.shifted] == [("ch:3", "ch:4"), ("ch:4", "ch:5"),
                                                  ("ch:5", "ch:6")]
    assert any("after ch 6 are left where they are" in i for i in amendment.infos)


# ----------------------------------------------- "add X after Snare" alone


def test_add_after_snare_does_not_renumber_and_says_what_would():
    amendment, merge = _review(ADD)
    assert not amendment.blocked
    assert _kinds(amendment, ChangeKind.SHIFTED) == []
    assert amendment.shifted == [] and merge.renumbered == {}
    [added] = _kinds(amendment, ChangeKind.ADDED)
    assert added.slot == "ch:20", "the next free strip, nothing on the desk moved"
    [info] = [i for i in amendment.infos if "did not" in i or "does not ask" in i]
    assert "'HiHat'" in info and "ch 3" in info and "ch:20" in info
    assert 'say: "insert HiHat after Snare and renumber the channels after it".' in info
    effective = {c["name"]: c["channel"] for c in amendment.effective_plan["channels"]}
    assert effective["HH"] == 3 and effective["Snare"] == 2


def test_the_wording_is_the_one_that_does_it():
    """The INFO's sentence, typed back, is an explicit insert."""
    amendment, _ = _review(ADD)
    [info] = [i for i in amendment.infos if "does not ask" in i]
    wording = info.split('say: "', 1)[1].rsplit('".', 1)[0]
    assert patch._INSERT_WORDS.search(wording)
    again, _ = _review(wording)
    assert len(_kinds(again, ChangeKind.SHIFTED)) == 17


def test_a_change_that_names_no_position_says_nothing_about_renumbering():
    amendment, _ = _review("add a hi-hat", _hihat(number=20))
    assert not any("renumber" in i for i in amendment.infos)
    assert _kinds(amendment, ChangeKind.SHIFTED) == []


def test_the_ambiguous_case_is_noted_even_when_the_model_chose_the_end():
    """The scenario that started this: 'add HiHat after Snare' came back on
    ch 14 with a note nobody saw. The words say where, so the INFO does."""
    amendment, _ = _review(ADD, _hihat(number=20))
    assert any('say: "insert HiHat after Snare and renumber the channels after it"' in i
               for i in amendment.infos)


# ----------------------------------------------------------- what is refused


def test_no_room_below_is_unplaceable_and_nothing_is_written():
    """ch 20 is somebody else's: the last strip cannot move onto it."""
    amendment, _ = _review(INSERT, theirs=(20,))
    assert amendment.blocked
    [bad] = _kinds(amendment, ChangeKind.UNPLACEABLE)
    assert "'MLD VOX'" in bad.where or "ch:20" in bad.reason
    assert "not free on the desk" in bad.reason


def test_an_insert_past_the_last_strip_is_refused():
    plan = applied_plan()
    plan["channels"] += [horn(n, f"Extra {n}", n + 30) for n in range(20, 41)]
    amendment, _ = _review("insert HiHat after Snare", plan=plan)
    refused = _kinds(amendment, ChangeKind.REFUSED)
    assert refused and "ch 40" in refused[0].reason


@pytest.mark.parametrize("dropped", ["Keys", "Tom1", "Kick"])
def test_an_insert_and_a_drop_in_one_change_are_both_carried_out(dropped):
    """A strip a dropped channel leaves, which a moved channel
    then lands on, is written once -- by the channel that lands."""
    change_set = _change(_hihat())
    change_set["drop"]["channels"] = [dropped]
    amendment, merge = patch.plan_patch(applied_plan(), change_set, _desk(), text=INSERT,
                                        console_model="wing-compact")
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    assert [c for c in amendment.changes if c.kind is ChangeKind.RELEASED
            and c.where == repr(dropped)]
    assert merge.inserted == {"hihat": "ch:3"}
    targets = amend.amendment_targets(amendment)
    assert not targets.collisions
    addresses = [t.address for t in targets.to_write if not t.address.endswith("/mute")]
    assert len(addresses) == len(set(addresses)), "an address is written twice"


def test_an_insert_beside_a_drop_is_written_and_undo_puts_every_address_back(tmp_path):
    change_set = _change(_hihat())
    change_set["drop"]["channels"] = ["Keys"]
    amendment, _ = patch.plan_patch(applied_plan(), change_set, _desk(), text=INSERT,
                                    console_model="wing-compact")
    console = DeskConsole(full_console_state())
    before = dict(console.state)
    journal = tmp_path / "insert-drop.journal.json"
    result = amend.apply_amendment(amendment, console, dry_run=False, journal_path=str(journal))
    assert not result.aborted
    assert console.state["/ch/3/name"][0] == "HiHat"
    assert console.state["/ch/9/name"][0] == "EG 1"      # moved onto the strip Keys left
    undone = undo.undo_from_journal(json.loads(journal.read_text()), console, dry_run=False)
    assert not undone.aborted
    assert {a for a in set(before) | set(console.state)
            if console.state.get(a) != before.get(a)} == set()


def test_an_edit_of_a_strip_the_insert_moves_rides_with_the_move(tmp_path):
    """The moved strip is rewritten whole on its new number, so
    the edit is in that write -- not refused, not written twice."""
    change_set = _change(_hihat())
    change_set["modify"] = [{"object": "channel", "name": "Tom1", "change": "HPF 90",
                             "fields": {"processing.hpf_hz": 90}}]
    amendment, merge = patch.plan_patch(applied_plan(), change_set, _desk(), text=INSERT,
                                        console_model="wing-compact")
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    assert next(c for c in merge.plan["channels"]
                if c["name"] == "Tom1")["processing"]["hpf_hz"] == 90
    assert any("Tom1" in i and "moves with the insert" in i for i in amendment.infos)
    targets = amend.amendment_targets(amendment)
    written = {t.address: t.compute_value("") for t in targets.to_write}
    assert written["/ch/5/flt/lcf"] == 90.0
    addresses = [t.address for t in targets.to_write if not t.address.endswith("/mute")]
    assert len(addresses) == len(set(addresses))


def test_an_edit_of_a_strip_it_leaves_alone_is_fine_beside_an_insert():
    change_set = _change(_hihat())
    change_set["modify"] = [{"object": "channel", "name": "Kick", "change": "HPF 90",
                             "fields": {"processing.hpf_hz": 90}}]
    amendment, _ = patch.plan_patch(applied_plan(), change_set, _desk(), text=INSERT + ", HPF 90 on Kick",
                                    console_model="wing-compact")
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    assert len(_kinds(amendment, ChangeKind.EDITED)) == 1


# ------------------------------------------------------------ the web page


def test_the_page_names_the_new_kind_and_draws_the_moved_strips():
    from pathlib import Path

    static = Path(patch.__file__).parent / "web" / "static"
    amend_js = (static / "amend.js").read_text(encoding="utf-8")
    apply_js = (static / "apply.js").read_text(encoding="utf-8")
    assert 'shifted: "Moved down by the insert"' in amend_js
    assert 'strip.mark === "moved"' in apply_js and '"l-moved"' in apply_js
    assert ".desk-strip.is-moved" in (static / "styles.css").read_text(encoding="utf-8")


def test_the_desk_drawing_marks_moved_strips_and_the_new_one():
    from atoo import desk_view

    amendment, _ = _review(INSERT)
    drawing = desk_view.patch_desk(_desk(), {}, amendment)
    marks = {s["n"]: s.get("mark") for sec in drawing["sections"] if sec["kind"] == "ch"
             for s in sec["strips"]}
    assert marks[3] == "new" and marks[4] == "moved" and marks[20] == "moved"
    assert marks[2] is None
    assert drawing["counts"]["moved"] == 17 and drawing["counts"]["new"] == 1


# ------------------------------------------------- the worked example in the docs


def _docs_run(capsys, text, change_set="hihat.change-set.json", state=None):
    from pathlib import Path

    from atoo.cli import main

    root = Path(__file__).parent.parent
    code = main(["patch", "--show", str(root / "starter" / "demo-show"), "--change-set",
                 str(root / "docs" / "user" / "demo" / "demo-show" / change_set),
                 "--state", str(state or root / "atoo" / "web" / "demo_states" / "before.json"),
                 text])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_docs_insert_example_runs_as_the_page_shows(capsys):
    code, out, _ = _docs_run(
        capsys, "insert HiHat after Snare and renumber the channels after it")
    assert code == 0
    assert "1 added, 3 unchanged, 11 shifted" in out
    assert "  SHIFTED          channel 'Rack Tom' -> ch:4: moves from ch:3 to ch:4 to make room for the insert" in out
    assert "  ADDED            channel 'HiHat' -> ch:3: new channel, inserted here" in out
    assert "!! 11 RUNNING STRIP(S) RENUMBERED" in out and "!!   'Playback': ch:13 -> ch:14" in out


def test_the_docs_add_example_runs_as_the_page_shows(capsys):
    code, out, _ = _docs_run(capsys, "add HiHat after Snare")
    assert code == 0
    assert "1 added, 14 unchanged" in out
    assert ("  ADDED            channel 'HiHat' -> ch:14 (the change asked for ch:3): new channel, "
            "placed on a free strip") in out
    assert ('say: "insert HiHat after Snare and renumber the channels after it".') in out
