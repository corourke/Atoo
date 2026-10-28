"""A change that names a bus, DCA, mute group, Main or Matrix the plan does not know
(and an earlier change for outputs).

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


@pytest.mark.parametrize("model", MODELS)
def test_a_send_on_a_strip_the_plan_has_no_record_of_is_switched_off_too(model):
    """"clear bus Drums" takes the bus's sends off every
    strip that has one, the plan's or not -- from what the desk read."""
    plan = _unrecorded(applied_plan())
    desk = _desk(plan)
    desk["/ch/33/send/5/on"] = 1          # nothing in the plan stands on ch 33
    change_set = patch.validate_change_set(_drop("busses", "Drums"))
    amendment, _m = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                     desk_objects=desk)
    assert not amendment.blocked
    assert ("bus 'Drums': a send into it on ch 33, a strip the plan has no record of, is "
            "switched off there too, from what the desk read; Undo puts it back") in amendment.infos
    writes = {t.address: t.compute_value("") for t in amend.amendment_targets(amendment).to_write}
    assert writes["/ch/33/send/5/on"] == 0


@pytest.mark.parametrize("key, name, token", [("dcas", "Drums", "#D1"),
                                              ("mute_groups", "Band", "#M1")])
def test_a_tag_on_a_strip_the_plan_has_no_record_of_is_taken_off_too(key, name, token):
    plan = _unrecorded(applied_plan())
    desk = _desk(plan)
    desk["/ch/33/tags"] = f"{token},#D9,cue"     # its other tokens stay where they are
    change_set = patch.validate_change_set(_drop(key, name))
    amendment, _m = patch.plan_patch(plan, change_set, occupancy(), console_model="wing-compact",
                                     desk_objects=desk)
    assert not amendment.blocked
    [target] = [t for t in amend.amendment_targets(amendment).to_write
                if t.address == "/ch/33/tags"]
    assert target.compute_value(f"{token},#D9,cue") == "#D9,cue"


def test_a_name_the_desk_does_not_hold_either_is_still_refused():
    amendment, merge, _t = _review(_drop("busses", "Nowhere"))
    assert merge.refused and "is on the desk" in merge.refused[0].reason


# ----------------------------------------------------------------------
# On the command line, against a console that holds the bus
# ----------------------------------------------------------------------


@pytest.mark.parametrize("model", MODELS)
def test_the_command_reads_the_bus_off_the_desk_and_clears_it_and_undo_restores(
        model, tmp_path, monkeypatch, capsys):
    import copy as _copy

    from atoo import cli, initialize
    from atoo.ai_provider import FakeProvider
    from test_amend import DeskConsole
    from test_amend_plan_json import _seed
    from test_patch import _bundle, _patch, _reply

    plan = applied_plan()
    plan["meta"]["console_model"] = model
    state = _seed(plan)                  # the desk holds the whole applied show, bus 5 included
    for leaf in initialize.freed_leaves(model, "/bus/5/"):
        state.setdefault(leaf.address, (leaf.value, leaf.value_type))
    # ... and a strip somebody set up by hand, which the plan has no record of,
    # sending into it.
    state["/ch/33/send/5/on"] = (1, "i")
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(_drop("busses", "Drums"))))
    unrecorded = _unrecorded(applied_plan())
    unrecorded["meta"]["console_model"] = model
    show = _bundle(tmp_path, plan=unrecorded)
    before = _copy.deepcopy(console.state)
    assert _patch(show, text="Clear the Drums bus.", confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "the desk holds it as bus 5" in out and "Refus" not in out
    assert console.state["/bus/5/name"][0] == ""
    assert console.state["/ch/1/send/5/on"][0] == 0
    assert console.state["/ch/33/send/5/on"][0] == 0
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert console.state == before


# ----------------------------------------------------------------------
# A Main or Matrix the plan does not know
# ----------------------------------------------------------------------


def _without_outputs(*names: str) -> dict:
    """The plan with those outputs left out, and the routes into a Main it
    leaves out."""
    plan = copy.deepcopy(applied_plan())
    for name in names:
        plan["outputs"].pop(name)
    if "Main 1" in names:
        for channel in plan["channels"]:
            channel.pop("main_routes", None)
    return plan


#: The desk: Matrix 1 named "Room EQ", fed from Main 1 (which the plan may
#: know) and from ch 33, a strip the plan has no record of.
_OUTPUT_DESK = {"/mtx/1/name": "Room EQ", "/main/1/name": "PA",
                "/main/1/send/MX1/on": 1, "/ch/33/send/MX1/on": 1, "/ch/1/send/MX1/on": 0}


def _review_outputs(change_set: dict, plan: dict, model: str = "wing-compact"):
    plan["meta"]["console_model"] = model
    amendment, merge = patch.plan_patch(plan, patch.validate_change_set(change_set), occupancy(),
                                        console_model=model, desk_objects=dict(_OUTPUT_DESK))
    return amendment, merge, amend.amendment_targets(amendment)


def test_the_reads_for_an_output_are_the_names_then_the_sends_into_a_dropped_matrix():
    plan = _without_outputs("Matrix 1")
    change_set = patch.validate_change_set(_drop("outputs", "Room EQ"))
    first = patch.name_reads(plan, change_set, {})
    assert {a for a, _t in first} == ({f"/main/{n}/name" for n in range(1, 5)}
                                      | {f"/mtx/{n}/name" for n in range(1, 9)})
    second = {a for a, _t in patch.member_reads(plan, change_set, {"/mtx/1/name": "Room EQ"})}
    assert "/ch/40/send/MX1/on" in second and "/aux/8/send/MX1/on" in second
    assert "/bus/16/send/MX1/on" in second and "/main/4/send/MX1/on" in second
    assert {a.split("/send/")[1] for a in second} == {"MX1/on"}
    # A Main's drop reads nothing more: its routes are the strips' own.
    main = patch.validate_change_set(_drop("outputs", "PA"))
    assert patch.member_reads(_without_outputs("Matrix 1", "Main 1"), main,
                              {"/main/1/name": "PA"}) == []


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("name", ["Room EQ", "Matrix 1", "room eq"])
def test_a_matrix_the_plan_does_not_know_is_dropped_from_what_the_desk_holds(model, name):
    amendment, merge, targets = _review_outputs(_drop("outputs", name),
                                                _without_outputs("Matrix 1"), model)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    [released] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert released.slot == "mtx:1"
    assert "stay patched as the desk has them" in released.reason
    assert any(f"output {name!r} is not in the plan on the desk, but the desk holds it as "
               "Matrix 1 ('Room EQ'), so the change is carried out against that" in i
               for i in amendment.infos)
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/mtx/1/name"] == ""
    # Every send the desk read as on is switched off: Main 1's (a Main the
    # plan holds) and ch 33's (a strip it has no record of); none other.
    assert writes["/main/1/send/MX1/on"] == 0 and writes["/ch/33/send/MX1/on"] == 0
    assert "/ch/1/send/MX1/on" not in writes
    assert any("on main 1, which the desk reads as on, is switched off" in i
               for i in amendment.infos)
    assert any("on ch 33, a strip the plan has no record of, is switched off there too" in i
               for i in amendment.infos)
    # Its sockets were not read: they are left as the desk has them.
    assert not [a for a in writes if a.startswith("/io/out/")]


@pytest.mark.parametrize("model", MODELS)
def test_a_main_the_plan_does_not_know_is_dropped_and_its_routes_left(model):
    amendment, merge, targets = _review_outputs(_drop("outputs", "PA"),
                                                _without_outputs("Matrix 1", "Main 1"), model)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    [released] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert released.slot == "main:1"
    assert any("routed to Main 1 keep their routes as the desk has them" in i
               for i in amendment.infos)
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/main/1/name"] == "" and writes["/main/1/send/MX1/on"] == 0
    assert not [a for a in writes if a.startswith(("/io/out/", "/ch/"))]


def test_an_output_the_desk_does_not_hold_is_still_refused():
    amendment, merge, _t = _review_outputs(_drop("outputs", "Matrix 9"),
                                           _without_outputs("Matrix 1"))
    assert merge.refused and "no output of that name is on the desk" in merge.refused[0].reason


@pytest.mark.parametrize("model", MODELS)
def test_the_command_reads_the_matrix_off_the_desk_and_drops_it_and_undo_restores(
        model, tmp_path, monkeypatch, capsys):
    import copy as _copy

    from atoo import cli, initialize
    from atoo.ai_provider import FakeProvider
    from test_amend import DeskConsole
    from test_amend_plan_json import _seed
    from test_patch import _bundle, _patch, _reply

    plan = applied_plan()
    plan["meta"]["console_model"] = model
    state = _seed(plan)              # the desk holds the whole applied show, Matrix 1 included
    for leaf in initialize.freed_leaves(model, "/mtx/1/"):
        state.setdefault(leaf.address, (leaf.value, leaf.value_type))
    state["/mtx/1/name"] = ("Room EQ", "s")
    state["/ch/33/send/MX1/on"] = (1, "i")       # a strip the plan has no record of
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(_drop("outputs", "Room EQ"))))
    unrecorded = _without_outputs("Matrix 1")
    unrecorded["meta"]["console_model"] = model
    show = _bundle(tmp_path, plan=unrecorded)
    before = _copy.deepcopy(console.state)
    assert before["/main/1/send/MX1/on"][0] == 1
    assert _patch(show, text="Drop the Room EQ matrix.", confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "the desk holds it as Matrix 1" in out and "Refus" not in out
    assert console.state["/mtx/1/name"][0] == ""
    assert console.state["/main/1/send/MX1/on"][0] == 0
    assert console.state["/ch/33/send/MX1/on"][0] == 0
    assert console.state["/io/out/LCL/7/grp"] == before["/io/out/LCL/7/grp"]
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert console.state == before


# ----------------------------------------------------------------------
# Editing what the desk holds and the plan does not know
# ----------------------------------------------------------------------


def _modify(obj: str, name: str, fields: dict) -> dict:
    change_set = patch.empty_change_set("edit")
    change_set["modify"] = [{"object": obj, "name": name, "change": "as typed",
                             "fields": fields}]
    return change_set


@pytest.mark.parametrize("model", MODELS)
def test_an_edit_of_a_bus_the_plan_does_not_know_writes_only_what_it_names(model):
    amendment, merge, targets = _review(_modify("bus", "Drums", {"processing.tilt_db": 2}),
                                        model)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    assert {t.address: t.compute_value("") for t in targets.to_write} == {"/bus/5/eq/tilt": 2.0}
    assert any("nothing else of it was read, so only what the change names is written" in i
               for i in amendment.infos)


@pytest.mark.parametrize("model", MODELS)
def test_a_bus_the_plan_does_not_know_is_sent_to_a_socket_and_leaves_its_main(model):
    """'Bus 5 to LCL 5-6': its routes to the Mains are read off the desk, so
    the one it leaves is switched off, as for a bus the plan built."""
    change_set = patch.validate_change_set(_modify("bus", "Drums", {"destination": {
        "type": "dedicated_output", "patch": {"group": "LCL", "sockets": [5, 6]}}}))
    plan = _unrecorded(applied_plan())
    plan["meta"]["console_model"] = model
    desk = _desk(plan)
    assert {a for a, _t in patch.member_reads(plan, change_set, desk)} \
        == {f"/bus/5/main/{m}/on" for m in range(1, 5)}
    desk.update({"/bus/5/main/1/on": 1, "/bus/5/main/2/on": 0, "/bus/5/main/3/on": 0,
                 "/bus/5/main/4/on": 0})
    amendment, _merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                         desk_objects=desk)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    writes = {t.address: t.compute_value("") for t in amend.amendment_targets(amendment).to_write}
    assert writes == {"/io/out/LCL/5/grp": "BUS", "/io/out/LCL/5/in": 9,
                      "/io/out/LCL/6/grp": "BUS", "/io/out/LCL/6/in": 10,
                      "/bus/5/main/1/on": 0}
    assert any("the desk routes it to Main 1" in i for i in amendment.infos)


def _seeded_desk(model: str, plan: dict, *prefixes: str):
    """A fake desk holding the whole applied show, and every leaf under
    `prefixes` at the initialized reading where the show set none."""
    from atoo import initialize
    from test_amend import DeskConsole
    from test_amend_plan_json import _seed
    state = _seed(plan)
    for prefix in prefixes:
        for leaf in initialize.freed_leaves(model, prefix):
            state.setdefault(leaf.address, (leaf.value, leaf.value_type))
    console = DeskConsole(state)
    console.close = lambda: None
    return console


def _run_and_undo(model, tmp_path, monkeypatch, capsys, console, unrecorded, change_set, text):
    import copy as _copy

    from atoo import cli
    from atoo.ai_provider import FakeProvider
    from test_patch import _bundle, _patch, _reply

    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(change_set)))
    unrecorded["meta"]["console_model"] = model
    show = _bundle(tmp_path, plan=unrecorded)
    before = _copy.deepcopy(console.state)
    assert _patch(show, text=text, confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    after = _copy.deepcopy(console.state)
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert console.state == before
    return out, before, after


@pytest.mark.parametrize("model", MODELS)
def test_the_command_edits_a_bus_the_plan_does_not_know_and_undo_restores(
        model, tmp_path, monkeypatch, capsys):
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    console = _seeded_desk(model, plan, "/bus/5/", "/io/out/LCL/5/", "/io/out/LCL/6/")
    change_set = _modify("bus", "Drums", {"destination": {
        "type": "dedicated_output", "patch": {"group": "LCL", "sockets": [5, 6]}}})
    out, before, after = _run_and_undo(model, tmp_path, monkeypatch, capsys, console,
                                       _unrecorded(applied_plan()), change_set,
                                       "Send the Drums bus to LCL 5 and 6.")
    assert "the desk holds it as bus 5" in out and "Refus" not in out
    assert before["/bus/5/main/1/on"][0] == 1 and after["/bus/5/main/1/on"][0] == 0
    assert after["/io/out/LCL/5/grp"][0] == "BUS" and after["/io/out/LCL/5/in"][0] == 9


@pytest.mark.parametrize("model", MODELS)
def test_a_matrix_the_plan_does_not_know_is_renumbered_from_what_the_desk_read(model):
    from atoo import initialize
    plan = _without_outputs("Matrix 1")
    plan["meta"]["console_model"] = model
    change_set = patch.validate_change_set(_modify("output", "Room EQ", {"index": 3}))
    desk = {f"/mtx/{n}/name": "" for n in range(1, 9)}
    desk.update({f"/main/{n}/name": "" for n in range(1, 5)})
    desk["/mtx/1/name"] = "Room EQ"
    reads = patch.member_reads(plan, change_set, desk)
    assert ("/mtx/1/fdr", "f") in reads and ("/ch/40/send/MX1/on", "i") in reads
    assert not [a for a, _t in reads if "/mtx/3/" in a or "MX3" in a]    # only Matrix 1's
    for address, _t in reads:
        desk[address] = next(x.value for x in initialize.freed_leaves(model, address)
                             if x.address == address)
    desk.update({"/mtx/1/fdr": -6.0, "/mtx/1/eq/1g": 3.0, "/main/1/send/MX1/on": 1,
                 "/main/1/send/MX1/lvl": -3.0, "/ch/33/send/MX1/on": 1})
    amendment, _merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                         desk_objects=desk)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    [edited] = [c for c in amendment.changes if c.kind is ChangeKind.EDITED]
    assert edited.reason.startswith("renumbered (Matrix 1 -> 3) from what the desk read")
    assert "the feed into it from ch 33, main 1" in edited.reason
    targets = amend.amendment_targets(amendment)
    addresses = [t.address for t in targets.to_write]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    writes = {t.address: t.compute_value("") for t in targets.to_write}
    assert writes["/mtx/3/name"] == "Room EQ" and writes["/mtx/1/name"] == ""
    assert writes["/mtx/3/fdr"] == -6.0 and writes["/mtx/3/eq/1g"] == 3.0
    assert writes["/main/1/send/MX3/on"] == 1 and writes["/main/1/send/MX3/lvl"] == -3.0
    assert writes["/main/1/send/MX1/on"] == 0 and writes["/ch/33/send/MX1/on"] == 0
    assert writes["/ch/33/send/MX3/on"] == 1
    assert not [a for a in writes if a.startswith("/io/out/")]
    assert any("the output sockets it feeds were not read, so they still take Matrix 1" in i
               for i in amendment.infos)
    assert amendment.effective_plan["outputs"]["Room EQ"]["index"] == 3


def test_a_main_the_plan_does_not_know_is_renumbered_with_every_route_into_it():
    from atoo import initialize
    model = "wing-full"
    plan = _without_outputs("Main 1")
    plan["meta"]["console_model"] = model
    change_set = patch.validate_change_set(_modify("output", "PA", {"index": 2}))
    desk = {f"/mtx/{n}/name": "" for n in range(1, 9)}
    desk.update({f"/main/{n}/name": "" for n in range(1, 5)})
    desk["/main/1/name"] = "PA"
    for address, _t in patch.member_reads(plan, change_set, desk):
        desk[address] = next(x.value for x in initialize.freed_leaves(model, address)
                             if x.address == address)
    desk.update({"/ch/1/main/1/on": 1, "/ch/2/main/1/on": 0, "/bus/5/main/1/on": 1})
    amendment, _merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                         desk_objects=desk)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    writes = {t.address: t.compute_value("")
              for t in amend.amendment_targets(amendment).to_write}
    assert writes["/main/2/name"] == "PA" and writes["/main/1/name"] == ""
    assert writes["/ch/1/main/2/on"] == 1 and writes["/ch/1/main/1/on"] == 0
    assert writes["/bus/5/main/2/on"] == 1 and writes["/bus/5/main/1/on"] == 0
    assert "/ch/2/main/2/on" not in writes and "/ch/2/main/1/on" not in writes
    # The plan's own record of the Matrix it feeds follows it.
    assert amendment.effective_plan["outputs"]["Matrix 1"]["fed_by"] == {"type": "main",
                                                                          "index": 2}


@pytest.mark.parametrize("number, reason", [
    (5, "which the desk holds as 'Podium Feed' -- not this plan's"),
    (9, "there is no Matrix 9")])
def test_a_renumber_onto_a_number_that_cannot_be_had_is_refused(number, reason):
    plan = _without_outputs("Matrix 1")
    desk = {**{f"/mtx/{n}/name": "" for n in range(1, 9)}, "/mtx/1/name": "Room EQ",
            "/mtx/5/name": "Podium Feed"}
    amendment, _merge = patch.plan_patch(
        plan, patch.validate_change_set(_modify("output", "Room EQ", {"index": number})),
        occupancy(), console_model="wing-compact", desk_objects=desk)
    assert [c.reason for c in amendment.blocked if reason in c.reason]


@pytest.mark.parametrize("model", MODELS)
def test_the_command_renumbers_a_matrix_the_plan_does_not_know_and_undo_restores(
        model, tmp_path, monkeypatch, capsys):
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    console = _seeded_desk(model, plan, "/mtx/1/", "/mtx/3/",
                           *patch._output_senders("matrix", 1),
                           *patch._output_senders("matrix", 3))
    console.state["/mtx/1/name"] = ("Room EQ", "s")
    console.state["/mtx/1/fdr"] = (-6.0, "f")
    console.state["/ch/33/send/MX1/on"] = (1, "i")
    out, before, after = _run_and_undo(
        model, tmp_path, monkeypatch, capsys, console, _without_outputs("Matrix 1"),
        _modify("output", "Room EQ", {"index": 3}), "Make the Room EQ matrix Matrix 3.")
    assert "renumbered (Matrix 1 -> 3) from what the desk read" in out and "Refus" not in out
    assert after["/mtx/3/name"][0] == "Room EQ" and after["/mtx/3/fdr"][0] == -6.0
    assert after["/mtx/1/name"][0] == "" and after["/mtx/1/fdr"][0] == -144.0
    assert before["/main/1/send/MX1/on"][0] == 1
    assert after["/main/1/send/MX3/on"][0] == 1 and after["/main/1/send/MX1/on"][0] == 0
    assert after["/ch/33/send/MX3/on"][0] == 1 and after["/ch/33/send/MX1/on"][0] == 0


@pytest.mark.parametrize("model", MODELS)
def test_two_matrices_the_plan_does_not_know_swap_numbers(model):
    """Each lands on the other's number from what the desk read, and the
    landing is the write: a clear of the old number is not written where the
    other lands. A feed only one of them had is switched off on its old
    number."""
    from atoo import initialize
    plan = _without_outputs("Matrix 1")
    plan["meta"]["console_model"] = model
    change_set = patch.empty_change_set("swap")
    change_set["modify"] = [
        {"object": "output", "name": "Room EQ", "change": "x", "fields": {"index": 2}},
        {"object": "output", "name": "Delay Fill", "change": "x", "fields": {"index": 1}}]
    change_set = patch.validate_change_set(change_set)
    desk = {f"/mtx/{n}/name": "" for n in range(1, 9)}
    desk.update({f"/main/{n}/name": "" for n in range(1, 5)})
    desk.update({"/mtx/1/name": "Room EQ", "/mtx/2/name": "Delay Fill"})
    for address, _t in patch.member_reads(plan, change_set, desk):
        desk[address] = next(x.value for x in initialize.freed_leaves(model, address)
                             if x.address == address)
    desk.update({"/mtx/1/name": "Room EQ", "/mtx/2/name": "Delay Fill",
                 "/mtx/1/fdr": -6.0, "/mtx/2/fdr": -12.0,
                 "/main/1/send/MX1/on": 1, "/main/1/send/MX1/lvl": -3.0,
                 "/ch/33/send/MX1/on": 1, "/ch/33/send/MX2/on": 1,
                 "/ch/33/send/MX2/lvl": -10.0})
    amendment, _merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model,
                                         desk_objects=desk)
    assert not amendment.blocked, [c.reason for c in amendment.blocked]
    to_write = amend.amendment_targets(amendment).to_write
    addresses = [t.address for t in to_write]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    writes = {t.address: t.compute_value("") for t in to_write}
    assert (writes["/mtx/2/name"], writes["/mtx/1/name"]) == ("Room EQ", "Delay Fill")
    assert (writes["/mtx/2/fdr"], writes["/mtx/1/fdr"]) == (-6.0, -12.0)
    # Main 1 fed Room EQ only: its feed lands on Matrix 2, and goes off on 1.
    assert (writes["/main/1/send/MX2/on"], writes["/main/1/send/MX2/lvl"]) == (1, -3.0)
    assert writes["/main/1/send/MX1/on"] == 0
    # ch 33 fed both: each feed lands on its Matrix's new number, at its level.
    assert (writes["/ch/33/send/MX2/on"], writes["/ch/33/send/MX1/on"]) == (1, 1)
    assert writes["/ch/33/send/MX1/lvl"] == -10.0
    outputs = amendment.effective_plan["outputs"]
    assert (outputs["Room EQ"]["index"], outputs["Delay Fill"]["index"]) == (2, 1)
