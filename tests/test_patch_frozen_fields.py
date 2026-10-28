"""Moving a running channel, and changing which input-list row it takes.

"Move the Kick to ch 30" and "swap the Kick and the Snare" are instructions:
the channel is returned to free where it was and written whole where it goes,
and Undo puts every address back. Refused only for a strip that cannot take
it -- past the desk's range, held by a running channel the change does not
move, or one the desk reads as somebody else's or could not read -- each
named. "Ch 1 is now the Kick Sub" sets the strip's input-list row; its patch
stays unless the change names a socket.

The desk is the frozen applied show (`test_amend.applied_plan`, 19 channels on
ch 1-19), with ch 20 holding somebody else's "Podium" and ch 33-40 not
answering (`test_amend.occupancy_state`).
"""

from __future__ import annotations

import pytest

from atoo import amend, cli, initialize, patch
from atoo.amend import ChangeKind
from atoo.ai_provider import FakeProvider
from test_amend import applied_plan, occupancy
from test_patch import _bundle, _patch, _reply
from test_patch_exactness import ModelDesk, _seed_free

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _modify(name: str, fields: dict) -> dict:
    return {"object": "channel", "name": name, "change": "as typed", "fields": fields}


def _review(*modify: dict, model: str = "wing-compact", plan: dict | None = None):
    change_set = patch.empty_change_set("Moves")
    change_set["modify"] = list(modify)
    amendment, merge = patch.plan_patch(plan or applied_plan(),
                                        patch.validate_change_set(change_set), occupancy(),
                                        console_model=model)
    return amendment, merge, amend.amendment_targets(amendment)


def _slots(plan: dict) -> dict:
    return {c["name"]: f"{c.get('bank', 'ch')}:{c['channel']}" for c in plan["channels"]}


def _strips(targets) -> set[str]:
    return {"/".join(t.address.split("/")[:3]) for t in targets.to_write}


@pytest.mark.parametrize("model", MODELS)
def test_moving_a_channel_frees_its_strip_and_writes_it_whole_on_the_new_one(model):
    amendment, merge, targets = _review(_modify("Kick", {"channel": 30}), model=model)
    assert not amendment.blocked
    assert _slots(amendment.effective_plan)["Kick"] == "ch:30"
    kinds = {(c.kind, c.slot) for c in amendment.changes if c.kind is not ChangeKind.UNCHANGED}
    assert kinds == {(ChangeKind.ADDED, "ch:30"), (ChangeKind.RELEASED, "ch:1")}
    assert _strips(targets) == {"/ch/1", "/ch/30"}
    assert any("drops it from ch:1 and adds it again on ch:30, so it is moved" in i
               for i in amendment.infos)


def test_a_strip_another_running_channel_holds_is_refused_naming_it():
    amendment, merge, targets = _review(_modify("Kick", {"channel": 3}))
    [refused] = merge.refused
    assert refused.reason == ("the change moves it from ch:1 to ch:3, and ch:3 holds channel "
                              "'HH', which the change does not move or drop -- say what to do "
                              "with it too, and both are carried out")
    assert not targets.to_write


@pytest.mark.parametrize("number, why", [
    (41, "this console has channel strips 1 to 40 -- there is no ch:41"),
    (20, "the desk reads ch:20 as holding something that is not this show's ('Podium')"),
    (35, "the desk did not answer for ch:35, so it counts as occupied"),
])
def test_a_strip_that_cannot_take_it_is_refused_saying_which(number, why):
    _a, merge, targets = _review(_modify("Kick", {"channel": number}))
    [refused] = merge.refused
    assert refused.reason == f"the change moves it from ch:1 to ch:{number}, and {why}"
    assert not targets.to_write


@pytest.mark.parametrize("model", MODELS)
def test_two_channels_swap_strips(model):
    amendment, _m, targets = _review(_modify("Kick", {"channel": 2}),
                                     _modify("Snare", {"channel": 1}), model=model)
    assert not amendment.blocked
    slots = _slots(amendment.effective_plan)
    assert (slots["Kick"], slots["Snare"]) == ("ch:2", "ch:1")
    assert _strips(targets) == {"/ch/1", "/ch/2"}
    # Each strip is written once, by the channel that lands on it.
    addresses = [t.address for t in targets.to_write]
    assert len(addresses) == len(set(addresses))
    names = {t.address: t.compute_value("") for t in targets.to_write
             if t.address in ("/ch/1/name", "/ch/2/name")}
    assert names == {"/ch/1/name": "Snare", "/ch/2/name": "Kick"}
    # The review says each strip is moved onto, not freed for nobody.
    said = {(c.kind, c.slot): c.reason for c in amendment.changes}
    assert said[(ChangeKind.ADDED, "ch:2")] == "moved here from ch:1, and written whole on this strip"
    assert said[(ChangeKind.RELEASED, "ch:1")].startswith(
        "moved off it by the change, and channel 'Snare' moves onto it: written whole by 'Snare'")


def test_a_move_carries_the_other_fields_it_names():
    amendment, merge, _t = _review(_modify("Kick", {"channel": 30, "name": "Kick In"}))
    assert not amendment.blocked
    assert _slots(amendment.effective_plan)["Kick In"] == "ch:30"
    assert ("channel 'Kick': moved to ch:30 with name as the change set them -- written with "
            "the rest of the strip there") in merge.infos


def test_naming_its_own_strip_moves_nothing():
    amendment, _m, targets = _review(_modify("Kick", {"channel": 1}))
    assert not amendment.blocked and not targets.to_write


def test_a_channel_moves_to_an_aux_strip():
    amendment, _m, targets = _review(_modify("TRAX", {"bank": "aux", "channel": 5}))
    assert not amendment.blocked
    assert _slots(amendment.effective_plan)["TRAX"] == "aux:5"
    assert _strips(targets) == {"/ch/19", "/aux/5"}


def test_a_new_input_list_row_keeps_the_patch_and_says_so():
    amendment, merge, targets = _review(_modify("Kick", {"source.input": "Kick Sub"}))
    assert not amendment.blocked
    kick = next(c for c in amendment.effective_plan["channels"] if c["name"] == "Kick")
    assert kick["source"]["input"] == "Kick Sub" and kick["patch"]["sockets"] == [1]
    assert ("channel 'Kick' on ch:1: its input-list row 'Kick' -> 'Kick Sub'; the change names no "
            "socket, so its patch stays A 1 -- the cable is taken to be where it was. Name the "
            "socket to move it") in merge.infos
    assert not targets.to_write


def test_a_new_input_list_row_with_a_socket_repatches_the_strip():
    amendment, merge, targets = _review(_modify("Kick", {
        "source.input": "Kick Sub", "patch": {"group": "A", "sockets": [30], "stated": True}}))
    assert not amendment.blocked
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert "/ch/1/in/conn/in" in writes and "/io/in/A/30/name" in writes
    assert not [i for i in merge.infos if "its input-list row" in i]


# -- Apply, then Undo: every address back -------------------------------------------------


def _apply_and_undo(tmp_path, monkeypatch, capsys, model, modify: list, text: str,
                    plan: dict | None = None):
    plan = plan or applied_plan()
    plan.setdefault("meta", {})["console_model"] = model
    state = _seed_free(plan)
    # Every address the change writes holds something on a real desk: the
    # ones the show never used, at an initialized desk's reading.
    preview, _merge = patch.plan_patch(plan, patch.validate_change_set(
        dict(patch.empty_change_set("Moves"), modify=modify)), occupancy(), console_model=model)
    for target in amend.amendment_targets(preview).to_write:
        if target.address not in state:
            leaf = [x for x in initialize.freed_leaves(model, target.address)
                    if x.address == target.address][:1]
            if leaf:
                state[target.address] = (leaf[0].value, leaf[0].value_type)
    console = ModelDesk(state)
    console.close = lambda: None
    change_set = patch.empty_change_set("Moves")
    change_set["modify"] = modify
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(patch.validate_change_set(change_set))))
    show = _bundle(tmp_path, plan=plan)
    before = dict(console.state)
    assert _patch(show, text=text, confirm=True) == 0, capsys.readouterr()
    capsys.readouterr()
    after = dict(console.state)
    code = cli.main(["undo", "--show", str(show), "--console", "198.51.100.9", "--confirm"])
    out = capsys.readouterr()
    assert code == 0, out
    differing = {a: (before.get(a), console.state.get(a))
                 for a in set(before) | set(console.state) if console.state.get(a) != before.get(a)}
    assert differing == {}, differing
    return before, after


@pytest.mark.parametrize("model", MODELS)
def test_apply_then_undo_of_a_move(model, tmp_path, monkeypatch, capsys):
    before, after = _apply_and_undo(tmp_path, monkeypatch, capsys, model,
                                    [_modify("Kick", {"channel": 30})], "Move the Kick to ch 30.")
    assert after["/ch/30/name"][0] == "Kick" and before["/ch/1/name"][0] == "Kick"
    assert after["/ch/1/name"][0] == ""


@pytest.mark.parametrize("model", MODELS)
def test_apply_then_undo_of_a_swap(model, tmp_path, monkeypatch, capsys):
    _before, after = _apply_and_undo(
        tmp_path, monkeypatch, capsys, model,
        [_modify("Kick", {"channel": 2}), _modify("Snare", {"channel": 1})],
        "Swap the Kick and the Snare.")
    assert (after["/ch/1/name"][0], after["/ch/2/name"][0]) == ("Snare", "Kick")


# -- A bus, DCA, mute group or output given a new number ---------------------------------


def _renumber(word: str, name: str, fields: dict, model: str = "wing-compact"):
    change_set = patch.empty_change_set("Renumber")
    change_set["modify"] = [{"object": word, "name": name, "change": "as typed", "fields": fields}]
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy(), console_model=model)
    return amendment, merge, {t.address: t.compute_value("")
                              for t in amend.amendment_targets(amendment).to_write}


def _swap(word: str, a: str, b: str, ia: int, ib: int, model: str, plan: dict | None = None):
    """Two objects of a kind swapping numbers: the amendment and its writes,
    each address written once (tags computed over `#D1,#M1`, a strip's tags
    as the desk holds them)."""
    change_set = patch.empty_change_set("Swap")
    change_set["modify"] = [{"object": word, "name": a, "change": "x", "fields": {"index": ia}},
                            {"object": word, "name": b, "change": "x", "fields": {"index": ib}}]
    amendment, _merge = patch.plan_patch(plan or applied_plan(),
                                         patch.validate_change_set(change_set), occupancy(),
                                         console_model=model)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    to_write = amend.amendment_targets(amendment).to_write
    addresses = [t.address for t in to_write]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    return amendment, {t.address: t.compute_value("#D1,#M1") for t in to_write}


def _two_of_each_output() -> dict:
    plan = applied_plan()
    plan["outputs"]["Matrix 2"] = {"kind": "matrix", "index": 2,
                                   "fed_by": {"type": "main", "index": 1},
                                   "socket": {"group": "LCL", "sockets": [5, 6], "stated": True}}
    plan["outputs"]["Main 2"] = {"kind": "main", "index": 2, "socket": None}
    return plan


@pytest.mark.parametrize("model", MODELS)
def test_a_bus_renumbered_takes_its_sends_with_it(model):
    amendment, merge, writes = _renumber("bus", "Drums", {"index": 14}, model)
    assert not amendment.blocked
    assert amendment.effective_plan["busses"]["Drums"]["index"] == 14
    assert writes["/bus/14/name"] == "Drums" and writes["/bus/5/name"] == ""
    # Kick's send into it moves: on at 14, cleared at 5.
    assert writes["/ch/1/send/14/on"] == 1 and writes["/ch/1/send/5/on"] == 0
    assert {a.split("/")[1] for a in writes} == {"bus", "ch"}
    assert not [a for a in writes if a.startswith("/bus/") and a.split("/")[2] not in ("5", "14")]
    [said] = [i for i in amendment.infos if "the new number moves" in i]
    assert said.startswith("bus 'Drums': the new number moves") and "channel 'Kick' (ch:1)" in said
    assert any(c.kind is ChangeKind.EDITED and c.reason.startswith("renumbered (index 5 -> 14)")
               for c in amendment.changes)


@pytest.mark.parametrize("word, name, number, why", [
    ("bus", "Drums", 9, "bus 9 is 'VOX Reverb''s, which the change does not renumber or drop"),
    ("bus", "Drums", 17, "this console has busses 1 to 16 -- there is no bus 17"),
    ("dca", "Drums", 17, "this console has DCAs 1 to 16 -- there is no dca 17"),
    ("mute group", "Band", 2, "mute group 2 is 'Vocals''s"),
    ("output", "Matrix 1", 9, "this console has Matrices 1 to 8 -- there is no Matrix 9"),
])
def test_a_number_that_cannot_be_had_is_refused_saying_why(word, name, number, why):
    amendment, merge, writes = _renumber(word, name, {"index": number})
    [refused] = merge.refused
    assert why in refused.reason
    assert not writes


@pytest.mark.parametrize("model", MODELS)
def test_two_busses_swap_numbers(model):
    """Each lands on the other's number, and the landing is the write: the
    old-number clears are not written over it."""
    amendment, writes = _swap("bus", "Drums", "Drums Comp", 6, 5, model)
    busses = amendment.effective_plan["busses"]
    assert (busses["Drums"]["index"], busses["Drums Comp"]["index"]) == (6, 5)
    assert (writes["/bus/6/name"], writes["/bus/5/name"]) == ("Drums", "Drums Comp")
    assert (writes["/bus/6/fdr"], writes["/bus/5/fdr"]) == (0.0, -6.0)
    # ch 1 (Kick) sends to both: each send lands on its bus's new number.
    assert (writes["/ch/1/send/6/on"], writes["/ch/1/send/5/on"]) == (1, 1)


@pytest.mark.parametrize("model", MODELS)
def test_two_dcas_swap_numbers(model):
    _a, writes = _swap("dca", "Drums", "Guitars", 2, 1, model)
    assert (writes["/dca/2/name"], writes["/dca/1/name"]) == ("Drums", "Guitars")
    assert writes["/ch/1/tags"] == "#D2,#M1"          # Kick, in Drums
    assert writes["/ch/8/tags"] == "#D1,#M1"          # EG 1, in Guitars


@pytest.mark.parametrize("model", MODELS)
def test_two_mute_groups_swap_numbers(model):
    _a, writes = _swap("mute group", "Band", "Vocals", 2, 1, model)
    assert (writes["/mgrp/2/name"], writes["/mgrp/1/name"]) == ("Band", "Vocals")
    assert writes["/ch/1/tags"] == "#D1,#M2"          # Kick, in Band
    assert writes["/ch/13/tags"] == "#D4,#M1"         # F VOX 1, in Vocals (and DCA 4)


@pytest.mark.parametrize("model", MODELS)
def test_two_matrices_swap_numbers(model):
    _a, writes = _swap("output", "Matrix 1", "Matrix 2", 2, 1, model, plan=_two_of_each_output())
    assert (writes["/mtx/2/name"], writes["/mtx/1/name"]) == ("Matrix 1", "Matrix 2")
    assert (writes["/io/out/LCL/7/in"], writes["/io/out/LCL/5/in"]) == (3, 1)
    assert (writes["/main/1/send/MX1/on"], writes["/main/1/send/MX2/on"]) == (1, 1)


@pytest.mark.parametrize("model", MODELS)
def test_two_mains_swap_numbers_and_each_takes_its_own_routes(model):
    """The routes follow each Main once: Main 1's busses and the Matrix it
    feeds go to Main 2, and are not moved back by the other's renumber."""
    amendment, writes = _swap("output", "Main 1", "Main 2", 2, 1, model,
                              plan=_two_of_each_output())
    assert (writes["/main/2/name"], writes["/main/1/name"]) == ("Main 1", "Main 2")
    assert (writes["/bus/5/main/2/on"], writes["/bus/5/main/1/on"]) == (1, 0)
    assert (writes["/main/2/send/MX1/on"], writes["/main/1/send/MX1/on"]) == (1, 0)
    assert amendment.effective_plan["outputs"]["Matrix 1"]["fed_by"] == {"type": "main",
                                                                          "index": 2}


@pytest.mark.parametrize("model", MODELS)
def test_apply_then_undo_of_a_bus_swap(model, tmp_path, monkeypatch, capsys):
    before, after = _apply_and_undo(
        tmp_path, monkeypatch, capsys, model,
        [{"object": "bus", "name": "Drums", "change": "x", "fields": {"index": 6}},
         {"object": "bus", "name": "Drums Comp", "change": "x", "fields": {"index": 5}}],
        "Swap the numbers of the Drums and Drums Comp busses.")
    assert (after["/bus/6/name"][0], after["/bus/5/name"][0]) == ("Drums", "Drums Comp")
    assert (after["/bus/6/fdr"][0], after["/bus/5/fdr"][0]) == (0.0, -6.0)
    assert (before["/bus/5/fdr"][0], before["/bus/6/fdr"][0]) == (0.0, -6.0)


def test_a_dca_renumbered_retags_its_members():
    amendment, _m, writes = _renumber("dca", "Drums", {"index": 9})
    assert not amendment.blocked
    assert writes["/dca/9/name"] == "Drums" and writes["/dca/1/name"] == ""
    assert "#D9" in writes["/ch/1/tags"] and "#D1" not in writes["/ch/1/tags"]


def test_a_mute_group_renumbered_retags_its_members():
    amendment, _m, writes = _renumber("mute group", "Band", {"index": 5})
    assert not amendment.blocked
    assert writes["/mgrp/5/name"] == "Band"
    assert "#M5" in writes["/ch/1/tags"]


def test_a_main_renumbered_takes_the_routes_into_it():
    amendment, merge, writes = _renumber("output", "Main 1", {"index": 2})
    assert not amendment.blocked
    plan = amendment.effective_plan
    assert plan["outputs"]["Main 1"]["index"] == 2
    assert plan["busses"]["Drums"]["destination"] == {"type": "main", "index": 2}
    assert plan["outputs"]["Matrix 1"]["fed_by"] == {"type": "main", "index": 2}
    assert writes["/main/2/name"] == "Main 1" and writes["/main/1/name"] == ""
    assert any("routed to Main 1 by number, and follow it to Main 2" in i for i in merge.infos)


def test_a_matrix_renumbered_takes_its_feed():
    amendment, _m, writes = _renumber("output", "Matrix 1", {"index": 3})
    assert not amendment.blocked
    assert writes["/mtx/3/name"] == "Matrix 1" and writes["/mtx/1/name"] == ""
    assert writes["/main/1/send/MX3/on"] == 1 and writes["/main/1/send/MX1/on"] == 0
    # Its sockets now take Matrix 3.
    assert "/io/out/LCL/7/in" in writes


def test_a_matrix_made_a_main_takes_the_lowest_free_main():
    amendment, merge, writes = _renumber("output", "Matrix 1", {"kind": "main"})
    assert not amendment.blocked
    out = amendment.effective_plan["outputs"]["Matrix 1"]
    assert (out["kind"], out["index"]) == ("main", 2)
    assert ("output 'Matrix 1' becomes Main 2, the lowest Main the plan on the desk leaves free -- "
            "name the number to choose it") in merge.infos
    assert writes["/main/2/name"] == "Matrix 1" and writes["/mtx/1/name"] == ""
    assert writes["/io/out/LCL/7/grp"] == "MAIN"


@pytest.mark.parametrize("model", MODELS)
def test_apply_then_undo_of_a_bus_renumber(model, tmp_path, monkeypatch, capsys):
    before, after = _apply_and_undo(
        tmp_path, monkeypatch, capsys, model,
        [{"object": "bus", "name": "Drums", "change": "x", "fields": {"index": 14}}],
        "Make the Drums bus bus 14.")
    assert after["/bus/14/name"][0] == "Drums" and after["/bus/5/name"][0] == ""


@pytest.mark.parametrize("model", MODELS)
def test_apply_then_undo_of_a_main_renumber(model, tmp_path, monkeypatch, capsys):
    _before, after = _apply_and_undo(
        tmp_path, monkeypatch, capsys, model,
        [{"object": "output", "name": "Main 1", "change": "x", "fields": {"index": 2}}],
        "Make the main mix Main 2.")
    assert after["/main/2/name"][0] == "Main 1"
    assert after["/bus/5/main/2/on"][0] == 1 and after["/bus/5/main/1/on"][0] == 0
