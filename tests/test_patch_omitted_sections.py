"""A change set that leaves a section out says "nothing there".

The change compiler asks the model for every key of the change set. An
unconstrained model that had nothing to put in a section sometimes left
the key out, and the whole change was refused for it: "plan.add: missing
required field 'busses'" ... for a reply that added two strips and dropped
one. An absent section means what an empty one means, so it is read as
empty, said at INFO, and the change is reviewed like any other.

`fixtures/patch-aux8.change-reply.json` is that reply as the model wrote it
(a full-size WING, "Add another vocal channel, move Playback to Aux 8."),
and `fixtures/patch-aux8.plan.json` is the plan it was compiled onto, cut
down to the strips and objects the reply names. Bundles are built in
`tmp_path`; nothing here reads a bundle under `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import amend, cli, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from atoo.apply import _build_write_targets
from test_amend import _FACTORY, DeskConsole, occupancy_state

FIXTURES = Path(__file__).parent / "fixtures"
REPLY = (FIXTURES / "patch-aux8.change-reply.json").read_text(encoding="utf-8")
TEXT = "Add another vocal channel, move Playback to Aux 8."


def base_plan() -> dict:
    return json.loads((FIXTURES / "patch-aux8.plan.json").read_text(encoding="utf-8"))


def test_the_recorded_reply_is_missing_four_sections_of_add():
    """The evidence: the reply names `add.channels` alone."""
    assert sorted(json.loads(REPLY)["add"]) == ["channels"]


def test_a_reply_that_leaves_out_empty_sections_is_read_with_them_empty():
    infos: list[str] = []
    change_set = patch.parse_change_set(REPLY, infos=infos)
    assert change_set["add"]["busses"] == {} and change_set["add"]["dcas"] == {}
    assert change_set["add"]["mute_groups"] == {} and change_set["add"]["outputs"] == {}
    assert [c["name"] for c in change_set["add"]["channels"]] == ["Vox 2", "Playback"]
    assert change_set["drop"]["channels"] == ["Playback"]
    [info] = infos
    assert "add.busses, add.dcas, add.mute_groups, add.outputs" in info
    assert "read as empty" in info


def test_a_complete_reply_says_nothing_about_defaults():
    infos: list[str] = []
    patch.parse_change_set(json.dumps(patch.empty_change_set("x")), infos=infos)
    assert infos == []


def test_every_section_may_be_left_out_but_the_name_may_not():
    infos: list[str] = []
    change_set = patch.parse_change_set(json.dumps({"name": "Nothing"}), infos=infos)
    assert change_set == patch.empty_change_set("Nothing")
    assert "add, drop, modify, notes" in infos[0]
    with pytest.raises(patch.ChangeError, match="missing required field 'name'"):
        patch.parse_change_set(json.dumps({"add": {}}))


def test_a_section_of_the_wrong_shape_is_still_refused():
    reply = json.loads(REPLY)
    reply["add"]["busses"] = []
    with pytest.raises(patch.ChangeError, match="add.busses: expected object"):
        patch.parse_change_set(json.dumps(reply))
    reply = json.loads(REPLY)
    reply["add"]["colours"] = {}
    with pytest.raises(patch.ChangeError, match="colours"):
        patch.parse_change_set(json.dumps(reply))


def _review(model: str):
    base = base_plan()
    occupancy = amend.strip_occupancy(
        occupancy_state(plan=base, theirs=(), unread=()), base, channels=40, aux=8)
    return patch.plan_patch(base, patch.parse_change_set(REPLY), occupancy,
                            console_model=model, text=TEXT)


@pytest.mark.parametrize("model", ["wing-full", "wing-compact"])
def test_the_recorded_move_to_aux_8_is_a_move_not_a_renumber(model):
    """The move half of the change: Playback leaves channel 13 for aux 8,
    on the same LCL 1+2, and the new vocal takes a free A socket. AUX 1-8
    are channel strips on every WING; it is the AUX *socket group* that a
    Compact or Rack lacks, and nothing in this change patches one. The
    change drops Playback and adds it again, which the review used to take
    for a running strip renumbered by accident and refuse."""
    amendment, merge = _review(model)
    assert not merge.refused and not amendment.blocked
    kinds = {(c.kind, c.where, c.slot) for c in amendment.changes}
    assert (ChangeKind.ADDED, "'Playback'", "aux:8") in kinds
    assert (ChangeKind.RELEASED, "'Playback'", "ch:13") in kinds
    assert (ChangeKind.ADDED, "'Vox 2'", "ch:14") in kinds
    assert not any(kind is ChangeKind.RENUMBERED for kind, _, _ in kinds)
    plan = amendment.effective_plan
    by_name = {c["name"]: c for c in plan["channels"]}
    assert (by_name["Playback"]["bank"], by_name["Playback"]["channel"]) == ("aux", 8)
    assert by_name["Playback"]["patch"] == {"group": "LCL", "sockets": [1, 2], "stated": True}
    assert sum(1 for c in plan["channels"] if c["name"] == "Playback") == 1
    assert any("it is moved" in info and "ch:13" in info and "aux:8" in info
               for info in amendment.infos)
    # The channel's own cable is not a clash: nothing warns about LCL 1+2.
    assert not [w for w in amendment.warnings if "LCL" in w]


def test_dropping_a_channel_and_adding_another_source_is_not_a_move():
    base = base_plan()
    change_set = patch.parse_change_set(REPLY)
    playback = next(c for c in change_set["add"]["channels"] if c["name"] == "Playback")
    playback["name"] = "Tracks"
    playback["source"] = {**playback["source"], "input": "Tracks L", "pair_input": "Tracks R"}
    merge = patch.merge_change(base, change_set, console_model="wing-full")
    assert merge.moved == set()


@pytest.fixture
def desk(monkeypatch):
    base = base_plan()
    merged = patch.merge_change(base, patch.parse_change_set(REPLY)).plan
    state: dict = {}
    for plan, factory in ((merged, True), (base, False)):
        for t in _build_write_targets(plan, set_fader_levels=True)[0]:
            state[t.address] = ((_FACTORY[t.value_type], t.value_type) if factory
                                else (t.compute_value(None), t.value_type))
    for address, value in occupancy_state(plan=base, theirs=(), unread=()).values.items():
        state[address] = (value, "i" if isinstance(value, int) else "s")
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


def test_the_cli_reviews_the_recorded_reply_instead_of_refusing_it(
        tmp_path, desk, monkeypatch, capsys):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(base_plan(), indent=2), encoding="utf-8")
    monkeypatch.setattr(cli, "provider_from_env", lambda: FakeProvider(response=REPLY))
    review_path = tmp_path / "review.json"

    code = cli.main(["patch", "--show", str(show), TEXT, "--console", "198.51.100.9",
                     "--console-model", "wing-full", "--no-progress",
                     "--review-json", str(review_path)])

    out = capsys.readouterr()
    assert code == 0, out.err
    assert "could not be compiled" not in out.err
    assert "INFO the change set left out add.busses" in out.out
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert any("left out add.busses" in info for info in review["infos"])
    assert review["to_write"]
    assert not (show / "change.json").exists()


def test_confirmed_the_move_clears_channel_13_and_builds_aux_8(
        tmp_path, desk, monkeypatch, capsys):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(base_plan(), indent=2), encoding="utf-8")
    monkeypatch.setattr(cli, "provider_from_env", lambda: FakeProvider(response=REPLY))

    code = cli.main(["patch", "--show", str(show), TEXT, "--console", "198.51.100.9",
                     "--console-model", "wing-full", "--no-progress", "--confirm"])

    out = capsys.readouterr()
    assert code == 0, out.err
    written = [a for a, _v, _t in desk.set_param_calls] + [a for a, _p in desk.set_node_calls]
    assert any(a.startswith("/aux/8") for a in written)
    assert any(a.startswith("/ch/13") for a in written)
    assert any(a.startswith("/ch/14") for a in written)
    # The cable stays as it is: only the strips change.
    assert not [a for a in written if a.startswith("/io/in/LCL/1/") or a.startswith("/io/in/LCL/2/")]


def test_a_saved_reply_with_sections_left_out_loads_with_an_info(tmp_path, desk, capsys):
    """The reply file `atoo patch` keeps when it refuses one is the same
    text, and `--change-set` of it reviews the change with no model call."""
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(base_plan(), indent=2), encoding="utf-8")
    reply = tmp_path / "change.partial.json"
    reply.write_text(REPLY, encoding="utf-8")

    code = cli.main(["patch", "--show", str(show), "--change-set", str(reply),
                     TEXT, "--console", "198.51.100.9", "--console-model", "wing-full",
                     "--no-progress"])

    out = capsys.readouterr()
    assert code == 0, out.err
    assert "INFO the change set left out add.busses" in out.out
