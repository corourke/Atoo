"""A change that names a bus, DCA or mute group the plan does not know.

On a desk Atoo did not set up (or one set up by hand since), the plan on the
desk is no record of its busses, DCAs and mute groups. An explicit "clear bus
Drums" used to be refused for want of a plan record. The change now reads the
objects it names off the desk -- their names, then for a drop which strips
send into the bus or belong to the group -- and is carried out against what
the desk holds. The desk here is a dict of the addresses the reads return;
the plan is the frozen applied show with those objects taken out of it.
"""

from __future__ import annotations

import copy

import pytest

from atoo import amend, patch
from atoo.amend import ChangeKind
from test_amend import applied_plan, horn, occupancy

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _unrecorded(plan: dict) -> dict:
    """The plan with Drums (bus 5), the Drums DCA (1) and the Band mute group (1)
    left out, and everything that referred to them."""
    plan = copy.deepcopy(plan)
    plan["busses"].pop("Drums")
    plan["dcas"].pop("Drums")
    plan["mute_groups"].pop("Band")
    for channel in plan["channels"]:
        channel["bus_sends"] = [s for s in channel.get("bus_sends") or [] if s["bus"] != "Drums"]
        channel["dca"] = [d for d in channel.get("dca") or [] if d != "Drums"]
        channel["mute_group"] = [m for m in channel.get("mute_group") or [] if m != "Band"]
    return plan


def _desk(plan: dict) -> dict:
    """What the desk holds of them: the names, a send into bus 5 from the first
    drum channels, the DCA and mute-group tags of the strips that had them."""
    known = {"/bus/5/name": "Drums", "/dca/1/name": "drums", "/mgrp/1/name": "Band"}
    for channel in applied_plan()["channels"]:
        n = channel["channel"]
        known[f"/ch/{n}/send/5/on"] = int(any(s["bus"] == "Drums"
                                              for s in channel.get("bus_sends") or []))
        tags = [f"#D{1}" for d in channel.get("dca") or [] if d == "Drums"]
        tags += [f"#M{1}" for m in channel.get("mute_group") or [] if m == "Band"]
        known[f"/ch/{n}/tags"] = ",".join(tags)
    return known


def _review(change_set: dict, model: str = "wing-compact"):
    plan = _unrecorded(applied_plan())
    plan["meta"]["console_model"] = model
    desk = _desk(plan)
    amendment, merge = patch.plan_patch(plan, patch.validate_change_set(change_set), occupancy(),
                                        console_model=model, desk_objects=desk)
    return amendment, merge, amend.amendment_targets(amendment)


def _drop(key: str, name: str) -> dict:
    change_set = patch.empty_change_set("drop")
    change_set["drop"][key] = [name]
    return change_set


def test_the_reads_ask_for_the_names_first_and_then_only_what_the_drop_needs():
    plan = _unrecorded(applied_plan())
    change_set = patch.validate_change_set(_drop("busses", "Drums"))
    first = patch.name_reads(plan, change_set, {})
    assert {a for a, _t in first} == {f"/bus/{n}/name" for n in range(1, 17)}
    known = {"/bus/5/name": "Drums"}
    second = patch.member_reads(plan, change_set, known)
    assert {a for a, _t in second} == {f"/{b}/{n}/send/5/on" for b, c in (("ch", 40), ("aux", 8))
                                       for n in range(1, c + 1)}
    assert patch.name_reads(applied_plan(), change_set, {}) == []      # known: no reads
    assert patch.member_reads(applied_plan(), change_set, known) == []


@pytest.mark.parametrize("model", MODELS)
def test_a_bus_the_plan_does_not_know_is_cleared_from_what_the_desk_holds(model):
    amendment, merge, targets = _review(_drop("busses", "Drums"), model)
    assert not amendment.blocked and not merge.refused
    [freed] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED
               and c.kind_of_object == "bus"]
    assert freed.slot == "bus:5"
    assert any("not in the plan on the desk, but the desk holds it as bus 5" in i
               for i in amendment.infos)
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/bus/5/name"] == "" and writes["/ch/1/send/5/on"] == 0
    assert all(a.startswith("/bus/5/") or "/send/5/" in a for a in writes), writes.keys()


@pytest.mark.parametrize("model", MODELS)
def test_a_dca_the_plan_does_not_know_is_cleared_and_its_members_taken_off(model):
    amendment, merge, targets = _review(_drop("dcas", "Drums"), model)
    assert not amendment.blocked and not merge.refused
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/dca/1/name"] == ""            # the desk's "drums" matched case-blind
    assert "#D1" not in writes["/ch/1/tags"].split(",")


def test_a_mute_group_the_plan_does_not_know_is_cleared_too():
    amendment, merge, targets = _review(_drop("mute_groups", "Band"))
    assert not amendment.blocked
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/mgrp/1/name"] == "MGRP.1"
    assert "#M1" not in writes["/ch/1/tags"].split(",")


def test_a_new_channel_may_join_a_dca_the_plan_does_not_know():
    change_set = patch.empty_change_set("trumpet")
    trumpet = horn(20, "Trumpet", 41)
    trumpet["dca"] = ["Drums"]
    change_set["add"]["channels"] = [trumpet]
    amendment, merge, targets = _review(change_set)
    assert not [c for c in amendment.changes if c.kind is ChangeKind.REFUSED]
    assert merge.plan["dcas"]["Drums"]["index"] == 1


def test_strips_the_plan_has_no_record_of_are_named_not_edited():
    plan = _unrecorded(applied_plan())
    desk = _desk(plan)
    desk["/ch/33/send/5/on"] = 1          # nothing in the plan stands on ch 33
    change_set = patch.validate_change_set(_drop("busses", "Drums"))
    amendment, _m = patch.plan_patch(plan, change_set, occupancy(), console_model="wing-compact",
                                     desk_objects=desk)
    assert any("ch 33" in w and "left as the desk has it" in w for w in amendment.warnings)


def test_a_name_the_desk_does_not_hold_either_is_still_refused():
    amendment, merge, _t = _review(_drop("busses", "Nowhere"))
    assert merge.refused and "is on the desk" in merge.refused[0].reason


# ----------------------------------------------------------------------
# On the command line, against a console that holds the bus
# ----------------------------------------------------------------------


def test_the_command_reads_the_bus_off_the_desk_and_clears_it_and_undo_restores(
        tmp_path, monkeypatch, capsys):
    import copy as _copy

    from atoo import cli, initialize
    from atoo.ai_provider import FakeProvider
    from test_amend import DeskConsole
    from test_amend_plan_json import _seed
    from test_patch import _bundle, _patch, _reply

    state = _seed(applied_plan())        # the desk holds the whole applied show, bus 5 included
    for leaf in initialize.freed_leaves("wing-compact", "/bus/5/"):
        state.setdefault(leaf.address, (leaf.value, leaf.value_type))
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(_drop("busses", "Drums"))))
    show = _bundle(tmp_path, plan=_unrecorded(applied_plan()))
    before = _copy.deepcopy(console.state)
    assert _patch(show, text="Clear the Drums bus.", confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "the desk holds it as bus 5" in out and "Refus" not in out
    assert console.state["/bus/5/name"][0] == ""
    assert console.state["/ch/1/send/5/on"][0] == 0
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert console.state == before
