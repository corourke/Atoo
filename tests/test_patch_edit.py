"""`atoo patch`, slice 2: a change may edit the fields it
NAMES on something already running, and nothing else.

Every compile here is a canned change set (`FakeProvider`, or a change set
built in the test). The desk is `test_amend.DeskConsole` seeded from the
frozen `tests/fixtures/applied-show.plan.json` scenario; bundles are built in
`tmp_path`. Nothing reads a bundle under `examples/`.
"""

from __future__ import annotations

import copy
import json

import pytest

from atoo import amend, cli, journal_stack, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from test_amend import applied_plan, occupancy
from test_amend_plan_json import _seed, _writes
from test_amend import DeskConsole


def _channel(plan: dict, number: int) -> dict:
    return next(c for c in plan["channels"] if c["channel"] == number)


def _modify(name: str, fields: dict, change: str = "as typed", obj: str = "channel") -> dict:
    return {"object": obj, "name": name, "change": change, "fields": fields}


def _change_set(*modify: dict, name: str = "Edits") -> dict:
    change_set = patch.empty_change_set(name)
    change_set["modify"] = list(modify)
    return patch.validate_change_set(change_set)


def _sax_to_mon3(level: float = -10.0) -> list:
    sends = copy.deepcopy(_channel(applied_plan(), 10)["bus_sends"])
    for send in sends:
        if send["bus"] == "MON3":
            send["level_db"] = level
    return sends


def _review(change_set: dict, text: str = ""):
    amendment, merge = patch.plan_patch(applied_plan(), change_set, occupancy(), text=text)
    return amendment, merge, amend.amendment_targets(amendment)


# ======================================================================
# The merge: only the named fields move
# ======================================================================


def _without(channel: dict, *paths: str) -> dict:
    out = copy.deepcopy(channel)
    for path in paths:
        parts = path.split(".")
        node = out
        for part in parts[:-1]:
            node = node.get(part) or {}
        node.pop(parts[-1], None)
    return out


def test_the_merged_plan_differs_from_the_desk_only_in_the_named_fields():
    change_set = _change_set(
        _modify("F VOX 1", {"processing.hpf_hz": 100}, "HPF 100 on the vocal"),
        _modify("T.Sax SM57", {"bus_sends": _sax_to_mon3()}, "sax in MON3 at -10"))
    merge = patch.merge_change(applied_plan(), change_set, occupancy=occupancy())
    base = applied_plan()
    for before, after in zip(base["channels"], merge.plan["channels"]):
        if before["channel"] == 13:
            assert after["processing"]["hpf_hz"] == 100
            assert _without(after, "processing.hpf_hz") == _without(before, "processing.hpf_hz")
        elif before["channel"] == 10:
            assert _without(after, "bus_sends") == _without(before, "bus_sends")
        else:
            assert after == before
    assert [(e.slot, e.path, e.old, e.new) for e in merge.edits] == [
        ("ch:13", "processing.hpf_hz", 120, 100),
        ("ch:10", "bus_sends", _channel(base, 10)["bus_sends"], _sax_to_mon3())]


def test_an_edit_writes_exactly_the_addresses_its_fields_change():
    amendment, _merge, targets = _review(_change_set(
        _modify("F VOX 1", {"processing.hpf_hz": 100}),
        _modify("T.Sax SM57", {"bus_sends": _sax_to_mon3()})))
    assert not amendment.blocked and not targets.collisions
    assert sorted(t.address for t in targets.to_write) == ["/ch/10/send/3/lvl", "/ch/13/flt/lcf"]
    assert [t.address for t in targets.edits] == [t.address for t in targets.to_write]
    # Every other address of both strips -- the name, the fader, the other
    # sends, the high-pass switch -- is withheld, and so read before and
    # after the write by FR-2.2's proof.
    withheld = {t.address for t in targets.withheld}
    for address in ("/ch/13/name", "/ch/13/fdr", "/ch/13/flt/lc", "/ch/10/send/3/on",
                    "/ch/10/send/1/lvl", "/ch/10/fdr", "/ch/10/name"):
        assert address in withheld, address
    assert amendment.edited == ["ch:13", "ch:10"]
    edited = [c for c in amendment.changes if c.kind is ChangeKind.EDITED]
    assert [c.slot for c in edited] == ["ch:13", "ch:10"]


def test_every_edited_field_is_announced_old_to_new_at_info():
    amendment, _m, _t = _review(_change_set(
        _modify("ch 1", {"name": "Kick In"}),
        _modify("T.Sax SM57", {"bus_sends": _sax_to_mon3()})))
    assert "ch:1: the change edits name \"Kick\" -> \"Kick In\"" in amendment.infos
    assert "ch:10: the change edits bus_sends: MON3 level -144 -> -10.0" in amendment.infos
    assert "channel 'Kick' on ch:1: name \"Kick\" -> \"Kick In\"" in amendment.summary()


def test_a_renamed_strip_is_still_the_same_strip_not_a_drop_and_an_add():
    """A channel is matched by its strip, so a rename is an edit of the
    same strip -- never the old name dropped and a new one added."""
    plan = applied_plan()
    _channel(plan, 19)["source"]["input"] = "TRAX"
    amendment, _merge = patch.plan_patch(plan, _change_set(_modify("TRAX", {"name": "Tracks"})),
                                         occupancy())
    kinds = {c.kind for c in amendment.changes}
    assert ChangeKind.RELEASED not in kinds and ChangeKind.ADDED not in kinds
    assert amendment.released == [] and amendment.strips == []
    assert amendment.edited == ["ch:19"]


def test_taking_things_away_writes_them_off():
    """A send removed is turned off, a high-pass removed is switched off,
    and leaving every DCA and mute group clears the strip's tags -- the
    plan no longer states those addresses, and a desk left alone would keep
    them on."""
    sends = [s for s in _channel(applied_plan(), 10)["bus_sends"] if s["bus"] != "Horns"]
    amendment, _m, targets = _review(_change_set(_modify(
        "T.Sax SM57", {"bus_sends": sends, "dca": [], "mute_group": [],
                       "processing.hpf_hz": None})))
    written = {t.address: t for t in targets.to_write}
    horns = applied_plan()["busses"]["Horns"]["index"]
    assert written[f"/ch/10/send/{horns}/on"].compute_value(1) == 0
    assert written["/ch/10/flt/lc"].compute_value(1) == 0
    assert written["/ch/10/tags"].compute_value("#D6,#M1,cue") == "cue"
    assert set(written) == {f"/ch/10/send/{horns}/on", "/ch/10/flt/lc", "/ch/10/tags"}
    assert any("left exactly as the desk has it" in i for i in amendment.infos)


def test_joining_a_dca_and_a_mute_group_rewrites_only_the_tags():
    amendment, _m, targets = _review(_change_set(_modify(
        "EG 1", {"dca": ["Guitars", "Band"], "mute_group": ["Band", "Vocals"]},
        "EG in the Band DCA, mute group Vocals")), text="mute group Vocals on the EG")
    [target] = targets.to_write
    assert target.address == "/ch/8/tags"
    dcas, groups = applied_plan()["dcas"], applied_plan()["mute_groups"]
    value = target.compute_value("cue")
    assert f"#D{dcas['Band']['index']}" in value and f"#M{groups['Vocals']['index']}" in value
    assert value.startswith("cue")


# ---- the fader --------------------------------------------------------------


def test_a_fader_the_change_does_not_name_is_never_moved():
    amendment, merge, targets = _review(
        _change_set(_modify("Kick", {"name": "Kick In", "fader": {"fader_db": 0, "muted": None}})),
        text="rename ch 1 Kick In")
    [held] = [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert "fader.fader_db" in held.reason and "does not name the fader" in held.reason
    assert _channel(merge.plan, 1)["fader"] == _channel(applied_plan(), 1)["fader"]
    assert [t.address for t in targets.to_write] == ["/ch/1/name", "/io/in/A/1/name"]


def test_a_fader_the_change_names_is_moved():
    _amendment, _merge, targets = _review(
        _change_set(_modify("Kick", {"fader.fader_db": -5})), text="kick fader to -5")
    assert [t.address for t in targets.to_write] == ["/ch/1/fdr"]


def test_mute_group_is_not_the_mute():
    amendment, _m, targets = _review(
        _change_set(_modify("Kick", {"fader.muted": True})), text="kick in mute group Band")
    assert targets.to_write == []
    assert any("does not name the mute" in c.reason for c in amendment.changes)


# ---- the patch --------------------------------------------------------------


def test_a_repatch_is_written_and_marked_as_moving_audio_live():
    amendment, _m, targets = _review(_change_set(_modify(
        "BassDI", {"patch": {"group": "A", "sockets": [30], "stated": True}},
        "move the bass to A 30")))
    [edit] = amendment.edits
    assert edit.moves_audio and edit.line().startswith("MOVES AUDIO LIVE")
    assert "MOVES AUDIO LIVE" in next(c for c in amendment.changes
                                      if c.kind is ChangeKind.EDITED).reason
    assert any("PHYSICAL patch change" in w for w in amendment.warnings)
    written = {t.address for t in targets.to_write}
    assert "/ch/7/in/conn/in" in written and "/io/in/A/30/name" in written
    # The old socket's own settings are left alone and said.
    assert not any(a.startswith("/io/in/A/6/") for a in written)
    assert any("/io/in/A/6/name" in i for i in amendment.infos)


def test_a_repatch_onto_a_socket_somebody_on_the_desk_uses_leaves_that_socket_alone():
    """Ch 20 on the desk is somebody's (Podium, on LCL 20): the repatch is
    honoured as named, and the socket's own settings are not written."""
    amendment, _m, targets = _review(_change_set(_modify(
        "BassDI", {"patch": {"group": "LCL", "sockets": [20], "stated": True}})))
    written = {t.address for t in targets.to_write}
    assert written == {"/ch/7/in/conn/grp", "/ch/7/in/conn/in"}
    assert any("honoured as named" in w for w in amendment.warnings)
    [held] = [w for w in amendment.warnings if "/io/in/LCL/20" in w]
    assert "ch:20 on the desk also uses" in held and "NOT written" in held


def test_sharing_a_running_strips_socket_is_refused_because_it_rewrites_that_strip():
    """Two strips on one socket turn `clink` off on both -- and the Kick is
    not named by the change, so the edit is refused, not written."""
    amendment, _m, targets = _review(_change_set(_modify(
        "BassDI", {"patch": {"group": "A", "sockets": [1], "stated": True}})))
    [refused] = amendment.blocked
    assert "/ch/1/clink" in refused.reason and "does not name" in refused.reason


def test_a_repatch_to_a_socket_the_desk_lacks_is_refused_by_the_preflight():
    amendment, _m, _t = _review(_change_set(_modify(
        "BassDI", {"patch": {"group": "LCL", "sockets": [30], "stated": True}})))
    result = amend.preflight(amendment, skip_verify=True, what="change")
    assert result.refuses and "LCL 30" in result.refusal
    assert "repatched by the change" in result.refusal


# ---- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("fields,words", [
    ({"channel": 40}, "renumber"),
    ({"source.input": "Bagpipes"}, "how a running strip is recognised"),
    ({"colour": "Red"}, "carries no field 'colour'"),
    ({"processing.foo": 1}, "not a field this format has"),
    ({"processing.hpf_hz": 5}, "hpf_hz"),
    ({"dca": ["Strings"]}, "dca 'Strings'"),
])
def test_a_field_the_object_cannot_carry_refuses_the_change(fields, words):
    amendment, merge, _t = _review(_change_set(_modify("Snare", fields)))
    assert amendment.blocked
    [refused] = [c for c in amendment.changes if c.kind is ChangeKind.REFUSED]
    assert words in refused.reason
    assert _channel(merge.plan, 2) == _channel(applied_plan(), 2)


def test_an_edit_of_nothing_on_the_desk_is_refused():
    amendment, _m, _t = _review(_change_set(_modify("Bagpipes", {"name": "Pipes"})))
    assert amendment.blocked and "no channel of that name is on the desk" in \
        amendment.blocked[0].reason


def test_a_modification_in_words_only_is_still_reported_not_written():
    change_set = patch.empty_change_set("Old shape")
    change_set["modify"] = [{"object": "channel", "name": "Kick", "change": "more sub"}]
    amendment, _m, targets = _review(patch.validate_change_set(change_set))
    [held] = [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert "names no field to set" in held.reason and targets.to_write == []


def test_a_named_object_edit_writes_only_its_own_addresses():
    amendment, _m, targets = _review(
        _change_set(_modify("MON2", {"fader.fader_db": -5}, obj="bus")), text="MON2 fader -5")
    index = applied_plan()["busses"]["MON2"]["index"]
    assert [t.address for t in targets.to_write] == [f"/bus/{index}/fdr"]
    assert amendment.edited == ["bus 'MON2'"]


def test_an_edit_that_would_rewrite_another_object_is_refused(monkeypatch):
    """Named fields only: an edit whose value moves an address of something
    it does not name (here, simulated: a bus field that rewrote a strip's
    send) is refused rather than written."""
    real = amend._target_map

    def spill(plan):
        out = real(plan)
        if plan["busses"]["MON2"]["fader"]["fader_db"] == -5:
            send = out["/ch/1/send/2/lvl"]
            out["/ch/1/send/2/lvl"] = amend.apply_module.WriteTarget(
                send.address, send.value_type, send.description,
                amend.apply_module._const(-7.0), send.stage)
        return out

    monkeypatch.setattr(amend, "_target_map", spill)
    amendment, _m, _t = _review(
        _change_set(_modify("MON2", {"fader.fader_db": -5}, obj="bus")), text="MON2 fader -5")
    [refused] = amendment.blocked
    assert "/ch/1/send/2/lvl" in refused.reason and "does not name" in refused.reason


# ======================================================================
# End to end: write, journal, prove, undo
# ======================================================================


@pytest.fixture
def desk(monkeypatch):
    console = DeskConsole(_seed(applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


@pytest.fixture
def model(monkeypatch):
    fake = FakeProvider(response=json.dumps(_change_set(
        _modify("F VOX 1", {"processing.hpf_hz": 100}, "HPF 100 on the vocal"),
        _modify("T.Sax SM57", {"bus_sends": _sax_to_mon3()}, "sax in MON3 at -10"),
        name="Vocal HPF, sax wedge")))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


TEXT = "HPF 100 on the lead vocal, and the sax in MON3 at -10"


def _patch(show, *extra, confirm=False):
    return cli.main(["patch", "--show", str(show), TEXT, "--console", "198.51.100.9",
                     "--no-progress", *(["--confirm"] if confirm else []), *extra])


def _bundle(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(applied_plan(), indent=4) + "\n")
    return show


def test_a_confirmed_edit_writes_proves_journals_and_undoes(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert desk.state["/ch/13/flt/lcf"][0] == 120
    review = tmp_path / "review.json"
    assert _patch(show, "--review-json", str(review), confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "EDITED" in out and "processing.hpf_hz 120 -> 100" in out
    assert "0 changed" in out  # FR-2.2: nothing unnamed moved
    assert desk.state["/ch/13/flt/lcf"][0] == 100
    assert desk.state["/ch/10/send/3/lvl"][0] == -10.0
    leaves = {a for a, _v, _t in desk.set_param_calls} | {
        f"{a}/{command.partition('=')[0]}" for a, command in desk.set_node_calls}
    assert leaves == {"/ch/10/send/3/lvl", "/ch/13/flt/lcf"}
    assert (show / "plan.json").read_bytes() == before

    payload = json.loads(review.read_text())
    assert payload["edited"] == ["ch:13", "ch:10"]
    assert [e["path"] for e in payload["edits"]] == ["processing.hpf_hz", "bus_sends"]
    assert payload["proof"]["moved"] == []

    [entry] = journal_stack.entries(show)
    journal = json.loads(entry.path.read_text())
    assert journal["scope"]["edited"] == ["ch:13", "ch:10"]
    assert {f["path"] for f in journal["scope"]["fields"]} == {"processing.hpf_hz", "bus_sends"}
    prior = {r["address"]: r["prior_value"] for r in journal["writes"]}
    assert prior["/ch/13/flt/lcf"] == 120
    # The plan left on the desk carries the edit, so the next change reads it.
    left = journal[journal_stack.DESK_PLAN_BLOCK]["plan"]
    assert _channel(left, 13)["processing"]["hpf_hz"] == 100

    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9", "--confirm"]) == 0, \
        capsys.readouterr()
    assert desk.state["/ch/13/flt/lcf"][0] == 120
    assert desk.state["/ch/10/send/3/lvl"][0] == -144


def test_the_same_edit_again_finds_it_already_so(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    capsys.readouterr()
    assert _patch(show) == 0
    out = capsys.readouterr().out
    assert "already so on the desk" in out and "Nothing to add" in out


def test_a_repatch_is_announced_before_anything_else(tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify(
        "BassDI", {"patch": {"group": "A", "sockets": [30], "stated": True}},
        "move the bass to A 30")))
    show = _bundle(tmp_path)
    assert _patch(show) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "!! 1 PATCH CHANGE(S) ON SOMETHING ALREADY RUNNING" in out
    assert "!!   MOVES AUDIO LIVE -- channel 'BassDI' on ch:7" in out
