"""A change that drops a DCA, a mute group or an output carries it out.

The same approach as the freed bus (`test_freed_bus.py`): the
object reads as an initialized one on every WING model, from the model's
initialized capture; its members are taken off it; a new object in the same
change may take the index it held; Undo puts every address back. A user,
2026-10-21: *"if I explicitly state an instruction, it should be carried out."*

The model is not called: every compile is a canned change set. One code path
serves every WING model; the API tests run it for the Compact, the Full and
the Rack, the end-to-end ones on the Compact fake. The desk is `test_amend`'s
frozen applied show (DCAs Drums 1 and Guitars 2, mute groups Band 1 and
Vocals 2, Main 1 and Matrix 1 on LCL 7-8).
"""

from __future__ import annotations

import copy

import pytest

from atoo import amend, cli, initialize, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from test_amend import DeskConsole, applied_plan, occupancy
from test_amend_plan_json import _seed
from test_patch import _bundle, _patch, _reply

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _plan(model: str) -> dict:
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    return plan


def _drop(key: str, *names: str, add: dict | None = None) -> dict:
    change_set = patch.empty_change_set("drop")
    change_set["drop"][key] = list(names)
    for add_key, objects in (add or {}).items():
        change_set["add"][add_key] = objects
    return patch.validate_change_set(change_set)


def _targets(plan: dict, change_set: dict, model: str):
    amendment, merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model)
    return amendment, merge, amend.amendment_targets(amendment)


def _writes(targets) -> dict:
    return {t.address: t.compute_value("") for t in targets.to_write}


def _members(plan: dict, field: str, name: str) -> list[int]:
    return [c["channel"] for c in plan["channels"] if name in (c.get(field) or [])]


@pytest.mark.parametrize("model", MODELS)
def test_dropping_a_dca_frees_it_and_takes_its_members_off(model):
    plan = _plan(model)
    members = _members(plan, "dca", "Drums")
    assert members
    amendment, merge, targets = _targets(plan, _drop("dcas", "Drums"), model)
    assert not amendment.blocked and not merge.refused
    [freed] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert freed.kind_of_object == "dca" and freed.slot == "dca:1"
    assert not [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert "Drums" not in merge.plan["dcas"] and "Guitars" in merge.plan["dcas"]
    assert any("returned to free" in i and "'Drums'" in i for i in amendment.infos)
    writes = _writes(targets)
    capture = {leaf.address: leaf.value for leaf in initialize.freed_leaves(model, "/dca/1/")}
    assert capture and {a: writes[a] for a in capture} == capture
    assert writes["/dca/1/fdr"] <= -100
    # The members' tags are rebuilt without #D1, and that is all of theirs.
    for number in members:
        tags = writes[f"/ch/{number}/tags"]
        assert "#D1" not in tags.split(",")
    for address in writes:
        assert address.startswith("/dca/1/") or address.endswith("/tags"), address
    assert all("Drums" not in c.get("dca", []) for c in merge.plan["channels"])


@pytest.mark.parametrize("model", MODELS)
def test_dropping_a_mute_group_frees_it_and_takes_its_members_off(model):
    plan = _plan(model)
    members = _members(plan, "mute_group", "Vocals")
    assert members
    amendment, merge, targets = _targets(plan, _drop("mute_groups", "Vocals"), model)
    assert not amendment.blocked and not merge.refused
    [freed] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert freed.kind_of_object == "mute group" and freed.slot == "mgrp:2"
    writes = _writes(targets)
    assert writes["/mgrp/2/name"] == "MGRP.2" and writes["/mgrp/2/mute"] == 0
    for number in members:
        assert "#M2" not in writes[f"/ch/{number}/tags"].split(",")
    for address in writes:
        assert address.startswith("/mgrp/2/") or address.endswith("/tags"), address


def test_a_member_of_two_groups_keeps_the_other():
    plan = _plan("wing-compact")
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    assert kick["dca"] == ["Drums"] and kick["mute_group"] == ["Band"]
    _a, merge, targets = _targets(plan, _drop("dcas", "Drums"), "wing-compact")
    assert _writes(targets)["/ch/1/tags"] == "#M1"
    assert next(c for c in merge.plan["channels"] if c["name"] == "Kick")["mute_group"] == ["Band"]


def test_a_dca_and_a_mute_group_dropped_together_are_one_edit_per_strip():
    change_set = _drop("dcas", "Drums")
    change_set["drop"]["mute_groups"] = ["Band"]
    amendment, _merge, targets = _targets(_plan("wing-compact"), change_set, "wing-compact")
    writes = _writes(targets)
    assert writes["/ch/1/tags"] == ""
    assert not [a for a in writes if a.startswith("/ch/") and not a.endswith("/tags")]


@pytest.mark.parametrize("model", MODELS)
def test_a_dca_may_take_the_index_a_dropped_one_held(model):
    amendment, merge, targets = _targets(
        _plan(model), _drop("dcas", "Drums", add={"dcas": {"Band DCA": {"index": 1}}}), model)
    assert not amendment.blocked and not merge.refused
    assert merge.plan["dcas"]["Band DCA"]["index"] == 1
    assert any("put on dca 1 as the change said" in i and "returns to free" in i
               for i in merge.infos)
    assert not [c for c in amendment.changes if c.kind is ChangeKind.UNPLACEABLE]
    writes = _writes(targets)
    assert writes["/dca/1/name"] == "Band DCA"          # the new one, not the clear
    addresses = [t.address for t in targets.to_write]
    assert len(addresses) == len(set(addresses)), "an address is written twice"


def test_a_mute_group_may_take_the_index_a_dropped_one_held():
    amendment, merge, targets = _targets(
        _plan("wing-compact"),
        _drop("mute_groups", "Band", add={"mute_groups": {"Stage": {"index": 1}}}),
        "wing-compact")
    assert not amendment.blocked and not merge.refused
    assert merge.plan["mute_groups"]["Stage"]["index"] == 1
    assert _writes(targets)["/mgrp/1/name"] == "Stage"


def test_with_no_index_named_a_new_dca_takes_the_lowest_free_one_and_says_so():
    amendment, merge, _t = _targets(
        _plan("wing-compact"),
        _drop("dcas", "Drums", add={"dcas": {"Band DCA": {}}}), "wing-compact")
    assert merge.plan["dcas"]["Band DCA"]["index"] == 1
    assert any("Band DCA" in i and "given index 1" in i for i in merge.infos)


def test_a_dca_past_the_desks_range_is_refused_with_the_reason():
    _a, merge, _t = _targets(_plan("wing-compact"),
                             _drop("dcas", add={"dcas": {"X": {"index": 40}}}), "wing-compact")
    [refused] = merge.refused
    assert "there is no dca 40" in refused.reason


@pytest.mark.parametrize("model", MODELS)
def test_dropping_an_output_frees_the_matrix_its_socket_and_its_feed(model):
    amendment, merge, targets = _targets(_plan(model), _drop("outputs", "Matrix 1"), model)
    assert not amendment.blocked and not merge.refused
    [freed] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert freed.kind_of_object == "output" and freed.slot == "mtx:1"
    assert "Matrix 1" not in merge.plan["outputs"] and "Main 1" in merge.plan["outputs"]
    writes = _writes(targets)
    capture = {leaf.address: leaf.value for leaf in initialize.freed_leaves(model, "/mtx/1/")}
    assert {a: writes[a] for a in capture} == capture
    for socket in (7, 8):
        initial = {leaf.address: leaf.value
                   for leaf in initialize.freed_leaves(model, f"/io/out/LCL/{socket}/")}
        assert {a: writes[a] for a in initial} == initial
    assert "/main/1/send/MX1/lvl" in writes          # taken off the Main that fed it
    for address in writes:
        assert address.startswith(("/mtx/1/", "/io/out/LCL/7/", "/io/out/LCL/8/",
                                   "/main/1/send/MX1/")), address


def test_dropping_a_main_frees_it_and_says_what_still_feeds_from_it():
    amendment, merge, targets = _targets(_plan("wing-compact"), _drop("outputs", "Main 1"),
                                         "wing-compact")
    assert not amendment.blocked and not merge.refused
    assert any("'Matrix 1' is fed from that Main" in i for i in merge.infos)
    assert _writes(targets)["/main/1/mute"] == 0


def test_a_new_output_may_take_the_socket_and_matrix_a_dropped_one_held():
    new = {"kind": "matrix", "fed_by": {"type": "main", "index": 1},
           "socket": {"group": "LCL", "sockets": [7, 8], "stated": True}}
    amendment, merge, targets = _targets(
        _plan("wing-compact"), _drop("outputs", "Matrix 1", add={"outputs": {"Delays": new}}),
        "wing-compact")
    assert not amendment.blocked and not merge.refused and not targets.collisions
    assert merge.plan["outputs"]["Delays"]["index"] == 1
    assert not [w for w in amendment.warnings if "already routes" in w or "already uses" in w]
    addresses = [t.address for t in targets.to_write]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    assert "/io/out/LCL/7/grp" in _writes(targets)


@pytest.mark.parametrize("key", ["dcas", "mute_groups", "outputs"])
def test_dropping_one_that_is_not_on_the_desk_is_refused(key):
    _a, merge, _t = _targets(_plan("wing-compact"), _drop(key, "Nope"), "wing-compact")
    assert "is on the desk" in merge.refused[0].reason


def test_an_accidental_restatement_of_a_dca_is_still_held_back():
    restated = patch.empty_change_set("restated")
    restated["add"]["dcas"] = {"Drums": {"fader": {"fader_db": -6}}}
    amendment, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(restated),
                                    "wing-compact")
    assert [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert "Drums" in merge.plan["dcas"]
    assert not [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]


# ----------------------------------------------------------------------
# On the wire: written, read back, and Undo puts every address back
# ----------------------------------------------------------------------


@pytest.fixture
def desk(monkeypatch):
    state = _seed(applied_plan())
    for root in ("/dca/1/", "/mgrp/2/", "/mtx/1/", "/main/1/send/MX1/",
                 "/io/out/LCL/7/", "/io/out/LCL/8/"):
        for leaf in initialize.freed_leaves("wing-compact", root):
            if leaf.address not in state:
                shown = {"s": "Show", "i": 1}.get(leaf.value_type, leaf.value)
                state[leaf.address] = (shown, leaf.value_type)
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


@pytest.mark.parametrize("drop", [("dcas", "Drums"), ("mute_groups", "Vocals"),
                                  ("outputs", "Matrix 1")])
def test_a_drop_is_written_and_undo_puts_every_address_back(
        tmp_path, desk, monkeypatch, capsys, drop):
    fake = FakeProvider(response=_reply(_drop(*drop)))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    show = _bundle(tmp_path)
    before = copy.deepcopy(desk.state)
    assert _patch(show, text=f"Drop {drop[1]}.", confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "returned to free" in out and "Refus" not in out
    assert desk.state != before
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert desk.state == before
