"""A change that drops a bus clears it.

A user, 2026-10-21, after applying the demo show to an initialized desk:
*"Clear bus 5 and 6 we are not using them. Add a stereo IEM bus (reuse bus 5)
and output to LCL 3-4."* Atoo refused ("nothing returns a bus to free yet").
His rule: an instruction stated explicitly is carried out; rules only decide
what the instruction leaves open.

The model cannot be called here: every compile is a canned change set, and
what is tested is everything around the call -- the merge, the writes, Undo.
Whether the real model says "drop bus 5" for those words is the live eval's
(`evals/live/corpus.json`, case `clear-bus-reuse-iem`), not this file's.

The desk is `test_amend`'s frozen applied show (buses 1-12, Drums on 5 and
Drums Comp on 6). One code path serves every WING model; the API tests run
it for the Compact, the Full and the Rack, the end-to-end ones on the Compact
fake.
"""

from __future__ import annotations

import copy
import json

import pytest

from atoo import amend, cli, initialize, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from test_amend import DeskConsole, applied_plan, occupancy
from test_amend_plan_json import _seed
from test_patch import _bundle, _patch, _reply

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _iem(index: int | None = None, sockets=(5, 6)) -> dict:
    entry = {"destination": {"type": "dedicated_output", "label": "IEM",
                             "patch": {"group": "LCL", "sockets": list(sockets), "stated": True}},
             "mono": False}
    if index is not None:
        entry["index"] = index
    return entry


def _plan(model: str) -> dict:
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    return plan


def _feeds_lcl(plan: dict, sockets: list[int], group: str = "LCL") -> None:
    """Drums feeds an output of its own, as a plan states one: `destination`
    and the `destinations` it mirrors."""
    destination = {"type": "dedicated_output", "label": "D",
                   "patch": {"group": group, "sockets": sockets, "stated": True}}
    plan["busses"]["Drums"]["destination"] = destination
    plan["busses"]["Drums"]["destinations"] = [destination]


def _clear_and_reuse(index: int | None = 5) -> dict:
    change_set = patch.empty_change_set("Clear 5 and 6, IEM")
    change_set["drop"]["busses"] = ["Drums", "Drums Comp"]
    change_set["add"]["busses"] = {"IEM": _iem(index)}
    return patch.validate_change_set(change_set)


def _targets(plan: dict, change_set: dict, model: str):
    amendment, merge = patch.plan_patch(plan, change_set, occupancy(), console_model=model)
    return amendment, merge, amend.amendment_targets(amendment)


# ----------------------------------------------------------------------
# What a freed bus is
# ----------------------------------------------------------------------


def test_a_bus_strip_is_initialized_the_same_on_every_model():
    """The values a freed bus takes are one set: every bus of the Compact's
    capture and of the Full's reads leaf for leaf alike, and the Rack, which
    has no capture yet, is freed from the Compact's."""
    def bus(model: str, n: int):
        return [(leaf.address, leaf.value_type, leaf.value)
                for leaf in initialize.freed_leaves(model, f"/bus/{n}/")]

    for n in range(1, 17):
        assert bus("wing-compact", n) == bus("wing-full", n) == bus("wing-rack", n) != []
    names = {a: v for a, _t, v in bus("wing-compact", 5)}
    assert names["/bus/5/name"] == "" and names["/bus/5/mute"] == 0
    assert names["/bus/5/fdr"] <= -100


@pytest.mark.parametrize("model", MODELS)
def test_dropping_a_bus_frees_it_and_switches_its_sends_off(model):
    change_set = patch.empty_change_set("No drum bus")
    change_set["drop"]["busses"] = ["Drums"]
    amendment, merge, targets = _targets(_plan(model), patch.validate_change_set(change_set),
                                         model)
    assert not amendment.blocked and not merge.refused
    [freed] = [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert freed.kind_of_object == "bus" and freed.slot == "bus:5"
    assert not [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert "Drums" not in merge.plan["busses"] and "Drums Comp" in merge.plan["busses"]
    assert any("returned to free" in i and "'Drums'" in i for i in amendment.infos)
    writes = {t.address: t.compute_value(None) for t in targets.to_write}
    # The bus itself reads as an initialized one ...
    assert writes["/bus/5/name"] == "" and writes["/bus/5/mute"] == 0
    assert writes["/bus/5/fdr"] <= -100
    # ... and every channel that sent into it no longer does, and that is all.
    senders = [c for c in applied_plan()["channels"]
               if any(s["bus"] == "Drums" for s in c.get("bus_sends") or [])]
    assert senders
    for channel in senders:
        assert writes[f"/ch/{channel['channel']}/send/5/on"] == 0
        # what the plan wrote of the send (switch, level, mode) reads as an
        # initialized one, not only its switch
        initial = {leaf.address: leaf.value for leaf in initialize.freed_leaves(
            model, f"/ch/{channel['channel']}/send/5/")}
        for leaf in ("on", "lvl", "mode"):
            address = f"/ch/{channel['channel']}/send/5/{leaf}"
            assert writes[address] == initial[address]
    for address in writes:
        assert address.startswith("/bus/5/") or "/send/5/" in address, address
    assert merge.plan["channels"][0]["bus_sends"] == [
        s for s in applied_plan()["channels"][0]["bus_sends"] if s["bus"] != "Drums"]


@pytest.mark.parametrize("model", MODELS)
def test_clear_bus_5_and_6_and_reuse_5_as_a_stereo_iem_on_lcl_5_6(model):
    """The request, as one change: both buses are cleared, bus 5 takes
    the IEM and writes it once -- its own values, never a clear after them."""
    amendment, merge, targets = _targets(_plan(model), _clear_and_reuse(), model)
    assert not amendment.blocked and not merge.refused and not targets.collisions
    kinds = {(c.kind, c.where) for c in amendment.changes if c.kind is not ChangeKind.UNCHANGED}
    assert (ChangeKind.RELEASED, "'Drums'") in kinds
    assert (ChangeKind.RELEASED, "'Drums Comp'") in kinds
    [added] = [c for c in amendment.changes if c.kind is ChangeKind.ADDED]
    assert added.where == "'IEM'" and added.slot == "bus:5"
    assert merge.plan["busses"]["IEM"]["index"] == 5
    assert any("put on bus 5 as the change said" in i and "returns to free" in i
               for i in merge.infos)
    # Written once, bar a freed bus's mute: ON for the clear, OFF at the end,
    # the bracket a freed strip has too.
    addresses = [t.address for t in targets.to_write if not t.address.endswith("/mute")]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    written = {t.address: t.compute_value(None) for t in targets.to_write}
    assert written["/bus/5/name"] == "IEM"                  # the new bus, not the clear
    assert written["/bus/6/name"] == "" and written["/bus/6/mute"] == 0
    assert written["/bus/5/busmono"] == 0                   # stereo
    assert "/io/out/LCL/5/grp" in written and "/io/out/LCL/6/grp" in written
    # Nothing outside the two buses, their senders and the new output.
    for address in written:
        assert (address.startswith(("/bus/5/", "/bus/6/", "/io/out/LCL/5/", "/io/out/LCL/6/"))
                or "/send/5/" in address or "/send/6/" in address), address


def test_the_output_a_freed_bus_fed_is_unpatched():
    plan = applied_plan()
    _feeds_lcl(plan, [40], "A")   # LCL 7-8 are the Main's, in this show
    change_set = patch.empty_change_set("No drum bus")
    change_set["drop"]["busses"] = ["Drums"]
    amendment, _merge, targets = _targets(plan, patch.validate_change_set(change_set),
                                          "wing-compact")
    writes = {t.address: t.compute_value(None) for t in targets.to_write}
    assert writes["/io/out/A/40/grp"] == "OFF"


def test_reusing_a_bus_the_output_it_fed_is_the_new_buses():
    plan = applied_plan()
    _feeds_lcl(plan, [5, 6])
    amendment, merge, targets = _targets(plan, _clear_and_reuse(), "wing-compact")
    assert not amendment.blocked and not targets.collisions, amendment.blocked
    addresses = [t.address for t in targets.to_write if not t.address.endswith("/mute")]
    assert len(addresses) == len(set(addresses))
    assert not [w for w in amendment.warnings if "already uses" in w]


# ----------------------------------------------------------------------
# The words: "reuse bus 5", and what is left open
# ----------------------------------------------------------------------


def test_with_no_number_named_the_lowest_free_index_is_taken_and_said():
    amendment, merge, _targets_ = _targets(_plan("wing-compact"), _clear_and_reuse(None),
                                           "wing-compact")
    assert merge.plan["busses"]["IEM"]["index"] == 5
    assert any("IEM" in i and "given index 5" in i for i in merge.infos)


def test_a_named_index_a_running_bus_holds_is_not_taken_and_is_said():
    change_set = patch.empty_change_set("IEM")
    change_set["add"]["busses"] = {"IEM": _iem(7)}      # 7 is Vocals, kept
    amendment, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(change_set),
                                    "wing-compact")
    assert not amendment.blocked
    assert merge.plan["busses"]["IEM"]["index"] == 13
    assert any("bus 7" in i and "lowest free index instead" in i for i in merge.infos)


def test_a_bus_past_the_desks_range_is_refused_with_the_reason():
    change_set = patch.empty_change_set("IEM")
    change_set["add"]["busses"] = {"IEM": _iem(40)}
    amendment, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(change_set),
                                    "wing-compact")
    [refused] = merge.refused
    assert "there is no bus 40" in refused.reason


def test_an_accidental_restatement_is_still_held_back_and_an_explicit_drop_is_not():
    """The guard on a running object restated whole stays: a model that puts
    a changed copy of Drums in `add` is not heard as "drop it". The engineer's
    own drop passes."""
    restated = patch.empty_change_set("restated")
    restated["add"]["busses"] = {"Drums": {"destination": {"type": "main", "index": 2}}}
    amendment, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(restated),
                                    "wing-compact")
    assert [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert "Drums" in merge.plan["busses"]
    assert not [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    dropped = patch.empty_change_set("drop")
    dropped["drop"]["busses"] = ["Drums"]
    amendment, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(dropped),
                                    "wing-compact")
    assert [c for c in amendment.changes if c.kind is ChangeKind.RELEASED]
    assert not [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]


def test_dropping_a_bus_a_new_channel_sends_to_is_still_refused():
    """The reference is to something that no longer exists: a setting the
    desk cannot be left in, so the change is refused and says which."""
    from test_amend import horn
    change_set = patch.empty_change_set("clear Drums, feed it")
    trumpet = horn(20, "Trumpet", 21)
    trumpet["bus_sends"] = [{"bus": "Drums", "mode": "post", "level_db": 0.0}]
    change_set["add"]["channels"] = [trumpet]
    change_set["drop"]["busses"] = ["Drums"]
    _a, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(change_set),
                             "wing-compact")
    [refused] = merge.refused
    assert "bus 'Drums'" in refused.reason


def test_dropping_a_bus_that_is_not_on_the_desk_is_refused():
    change_set = patch.empty_change_set("nothing")
    change_set["drop"]["busses"] = ["Nope"]
    _a, merge, _t = _targets(_plan("wing-compact"), patch.validate_change_set(change_set),
                             "wing-compact")
    assert "no bus of that name is on the desk" in merge.refused[0].reason


# ----------------------------------------------------------------------
# On the wire: written, read back, and Undo puts every address back
# ----------------------------------------------------------------------


@pytest.fixture
def desk(monkeypatch):
    state = _seed(applied_plan())
    # The initialized capture's bus leaves, seeded with a show's values so a
    # clear is a change, and so there is something for Undo to put back. (A
    # float stays where the capture has it: the desk steps a float to its
    # own grid, so an arbitrary seed would not read back as written.)
    for n in (5, 6):
        for leaf in initialize.freed_leaves("wing-compact", f"/bus/{n}/"):
            if leaf.address not in state:
                shown = {"s": "Show", "i": 1}.get(leaf.value_type, leaf.value)
                state[leaf.address] = (shown, leaf.value_type)
    for socket in (5, 6):
        for leaf in initialize.freed_leaves("wing-compact", f"/io/out/LCL/{socket}/"):
            state.setdefault(leaf.address, (leaf.value, leaf.value_type))
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


def test_the_whole_request_is_written_and_undo_puts_every_address_back(
        tmp_path, desk, monkeypatch, capsys):
    fake = FakeProvider(response=_reply(_clear_and_reuse()))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    show = _bundle(tmp_path)
    before = copy.deepcopy(desk.state)
    text = "Clear bus 5 and 6 we are not using them. Add a stereo IEM bus (reuse bus 5) " \
           "and output to LCL 5-6."
    assert _patch(show, text=text, confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "returned to free" in out and "Refus" not in out
    assert desk.state["/bus/5/name"][0] == "IEM"
    assert desk.state["/bus/6/name"][0] == ""
    assert desk.state["/ch/1/send/5/on"][0] == 0
    assert desk.state != before
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert desk.state == before


def test_the_preview_counts_the_writes_the_confirm_makes(tmp_path, desk, monkeypatch, capsys):
    """Forge's check: the preview said 106 would change and the
    write made 107. A freed bus's mute used to be written ON then OFF, two
    writes to one address that a preview reading the desk once cannot count.
    The preview's number is the write's, for the clear-bus change."""
    import re
    fake = FakeProvider(response=_reply(_clear_and_reuse()))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    show = _bundle(tmp_path)
    text = "Clear bus 5 and 6, add a stereo IEM (reuse bus 5) on LCL 5-6."
    assert _patch(show, text=text) == 0
    previewed = int(re.search(r"(\d+) would change", capsys.readouterr().out).group(1))
    assert previewed > 0
    assert _patch(show, text=text, confirm=True) == 0
    written = int(re.search(r"(\d+) written", capsys.readouterr().out).group(1))
    assert written == previewed


@pytest.mark.parametrize("model", MODELS)
def test_the_iem_output_is_fed_from_the_iem_buses_own_slots(model):
    """The output patch takes a SLOT, not a bus number: bus N reserves slots
    2N-1 and 2N (`apply._output_slot`, confirmed on a desk). The
    IEM is bus 5, so LCL 5 and 6 read `BUS` slots 9 and 10 -- bus 5's left and
    right. The desk's read-out of `in` 9/10 is bus 5, not bus 9."""
    amendment, merge, targets = _targets(_plan(model), _clear_and_reuse(), model)
    written = {t.address: t.compute_value(None) for t in targets.to_write}
    assert written["/io/out/LCL/5/grp"] == written["/io/out/LCL/6/grp"] == "BUS"
    assert (written["/io/out/LCL/5/in"], written["/io/out/LCL/6/in"]) == (9, 10)
    assert merge.plan["busses"]["IEM"]["index"] == 5
