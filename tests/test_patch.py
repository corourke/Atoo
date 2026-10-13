"""`atoo patch` -- a change typed in plain English.

The model cannot be called here, so every compile is a `FakeProvider`
answering with a canned change set -- which is also the point: what these
tests check is everything AROUND the model call. The merge (adds, drops,
references to things that do not exist), what is not written because it
would modify a running strip, which plan is the base (the desk's journal,
plan.json with an INFO, or an empty board), that plan.json is never written,
what the journal records, undo, the apply WARNING, and that `amend` still
behaves exactly as it did.

The desk is `test_amend.DeskConsole`, seeded from the frozen
`tests/fixtures/applied-show.plan.json` scenario: strips 1-19 ours, 20
somebody's "Podium" (named only on its source socket), 21-32 free, 33-40
never answering. **Bundles are built in `tmp_path`; nothing here reads a
bundle under `examples/`.**
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import amend, cli, journal_stack, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from test_amend import applied_plan, horn, occupancy, occupancy_state
from test_amend_plan_json import _seed, _writes
from test_amend import DeskConsole

HORNS_TEXT = "trumpet, trombone and tenor sax on A 21-23 for tonight, Horns DCA, Band mute"


def horns_change_set(start: int = 20) -> dict:
    change_set = patch.empty_change_set("Horns for tonight")
    change_set["add"]["channels"] = [horn(start, "Trumpet", 21), horn(start + 1, "Trombone", 22),
                                     horn(start + 2, "T.Sax", 23)]
    return change_set


def _reply(change_set: dict) -> str:
    return json.dumps(change_set)


@pytest.fixture
def desk(monkeypatch):
    console = DeskConsole(_seed(applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


@pytest.fixture
def model(monkeypatch):
    """The provider `atoo patch` builds -- swapped for a canned one.
    Set `model.response` to the change set's JSON."""
    fake = FakeProvider(response=_reply(horns_change_set()))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


def _bundle(tmp_path, *, plan: dict | None = "applied") -> Path:
    show = tmp_path / "show"
    show.mkdir()
    if plan == "applied":
        plan = applied_plan()
    if plan is not None:
        (show / "plan.json").write_text(json.dumps(plan, indent=4) + "\n\n")
    return show


def _patch(show: Path, *extra: str, text: str | None = HORNS_TEXT, confirm: bool = False) -> int:
    return cli.main(["patch", "--show", str(show), *( [text] if text else []),
                     "--console", "198.51.100.9", "--no-progress",
                     *(["--confirm"] if confirm else []), *extra])


# ======================================================================
# The merge
# ======================================================================


def test_a_change_set_adds_channels_and_the_back_half_places_them():
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(
        horns_change_set()), occupancy())
    assert [c.slot for c in amendment.additions] == ["ch:21", "ch:22", "ch:23"]
    assert not amendment.blocked and not merge.refused
    # The words are the change's, not a rebuild's.
    assert "(the change asked for ch:20)" in amendment.additions[0].line()
    assert any("the socket the change named" in i for i in amendment.infos)
    # Nothing already on the desk is modified or renumbered.
    assert {c.kind for c in amendment.changes} == {ChangeKind.ADDED, ChangeKind.UNCHANGED}


def test_a_new_bus_and_dca_get_the_lowest_free_index():
    change_set = patch.empty_change_set("Brass")
    trumpet = horn(20, "Trumpet", 21)
    trumpet.update(dca=["Brass"], bus_sends=[{"bus": "Brass Mix", "mode": "post",
                                              "level_db": 0.0}])
    change_set["add"]["channels"] = [trumpet]
    change_set["add"]["dcas"] = {"Brass": {}}
    change_set["add"]["busses"] = {"Brass Mix": {"destination": {"type": "main"}}}
    merge = patch.merge_change(applied_plan(), patch.validate_change_set(change_set),
                               occupancy=occupancy())
    assert merge.plan["dcas"]["Brass"]["index"] == 9       # 1-8 are the show's
    assert merge.plan["busses"]["Brass Mix"]["index"] == 13  # 1-12 are the show's
    # The bus's width and destination were decided and marked, as for a build.
    assert merge.plan["busses"]["Brass Mix"]["inferred"]
    amendment, _ = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                    occupancy())
    kinds = {(c.kind_of_object, c.kind) for c in amendment.changes}
    assert ("dca", ChangeKind.ADDED) in kinds and ("bus", ChangeKind.ADDED) in kinds


@pytest.mark.parametrize("field,value,named", [
    ("bus_sends", [{"bus": "MON9", "mode": "pre", "level_db": 0.0}], "bus 'MON9'"),
    ("dca", ["Strings"], "dca 'Strings'"),
    ("mute_group", ["Nobody"], "mute group 'Nobody'"),
])
def test_a_reference_to_something_that_does_not_exist_refuses_the_change(field, value, named):
    change_set = horns_change_set()
    change_set["add"]["channels"][0][field] = value
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy())
    assert amendment.blocked
    [refused] = merge.refused
    assert refused.where == "'Trumpet'" and named in refused.reason
    assert "neither on the desk nor added by this change" in refused.reason
    # The refused channel is not in the merged plan: nothing half-connected.
    assert "Trumpet" not in {c["name"] for c in merge.plan["channels"]}


def test_an_object_the_change_adds_satisfies_a_reference_from_another_it_adds():
    change_set = horns_change_set()
    for channel in change_set["add"]["channels"]:
        channel["bus_sends"] = [{"bus": "Horn Wedge", "mode": "pre", "level_db": 0.0}]
    change_set["add"]["busses"] = {"Horn Wedge": {"destination": {
        "type": "dedicated_output", "label": "Horn Wedge",
        "socket": {"group": "LCL", "sockets": [5], "stated": True}}}}
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy())
    assert not merge.refused and not amendment.blocked


def test_a_drop_returns_the_strip_to_free_and_a_drop_of_nothing_is_refused():
    change_set = patch.empty_change_set("Lose the MD vocal")
    change_set["drop"]["channels"] = ["MLD VOX"]
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy())
    assert amendment.released == ["ch:14"]
    assert "dropped by the change" in next(
        c for c in amendment.changes if c.kind is ChangeKind.RELEASED).reason
    change_set["drop"]["channels"] = ["Bagpipes"]
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy())
    assert amendment.blocked and merge.refused[0].where == "'Bagpipes'"


def test_a_channel_already_on_the_desk_is_modified_not_written():
    """A change that RESTATES a running channel whole (a changed copy of the
    Kick in `add`), or asks for a modification in words only, is reported
    as MODIFIED -- amend's "Modified, not written" -- and the merged plan
    keeps the desk's Kick. Slice 2 writes a running strip only through
    `modify` naming its fields, so nothing unnamed can move."""
    kick = copy.deepcopy(next(c for c in applied_plan()["channels"] if c["name"] == "Kick"))
    kick["bus_sends"].append({"bus": "MON2", "mode": "pre", "level_db": -10.0})
    change_set = patch.empty_change_set("Kick in MON2")
    change_set["add"]["channels"] = [kick]
    change_set["modify"] = [{"object": "channel", "name": "Lead Vox",
                             "change": "add a send to MON2"}]
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy())
    modified = [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert [c.where for c in modified] == ["'Kick'", "'Lead Vox'"]
    assert "restates" in modified[0].reason and "`modify`" in modified[0].reason
    assert "names no field to set" in modified[1].reason
    assert all("not written" in c.reason for c in modified)
    assert not amendment.blocked and amendment.strips == []
    assert merge.plan["channels"][0] == applied_plan()["channels"][0]
    assert amend.amendment_targets(amendment).to_write == []


def test_dropping_a_bus_is_not_written():
    change_set = patch.empty_change_set("No drum bus")
    change_set["drop"]["busses"] = ["Drums"]
    amendment, merge = patch.plan_patch(applied_plan(), patch.validate_change_set(change_set),
                                        occupancy())
    [change] = [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert change.kind_of_object == "bus" and "nothing returns a bus to free" in change.reason
    assert "Drums" in merge.plan["busses"]


def test_a_socket_the_change_names_is_honoured_even_when_taken():
    change_set = horns_change_set()
    change_set["add"]["channels"][0]["patch"] = {"group": "A", "sockets": [1], "stated": True}
    merge = patch.merge_change(applied_plan(), patch.validate_change_set(change_set),
                               occupancy=occupancy())
    trumpet = next(c for c in merge.plan["channels"] if c["name"] == "Trumpet")
    assert trumpet["patch"]["sockets"] == [1]
    assert any("honoured as named" in w for w in merge.warnings)


def test_an_unnamed_socket_that_is_taken_is_chosen_afresh_and_said():
    change_set = horns_change_set()
    change_set["add"]["channels"][0]["patch"] = {"group": "A", "sockets": [1], "stated": False}
    merge = patch.merge_change(applied_plan(), patch.validate_change_set(change_set),
                               occupancy=occupancy())
    trumpet = next(c for c in merge.plan["channels"] if c["name"] == "Trumpet")
    # A 1-20 are the show's and A 22/23 are claimed by the other two horns
    # further down the list only once they are merged -- A 21 is the first
    # free socket in the group at the moment the Trumpet is settled.
    assert trumpet["patch"]["sockets"] == [21]
    info = next(i for i in merge.infos if "'Trumpet'" in i and "chosen instead" in i)
    assert "A 1 was picked" in info and "A 21 was chosen instead" in info


def test_an_unnamed_free_socket_is_kept_and_announced():
    change_set = horns_change_set()
    change_set["add"]["channels"][0]["patch"]["stated"] = False
    merge = patch.merge_change(applied_plan(), patch.validate_change_set(change_set),
                               occupancy=occupancy())
    assert any("the change named no socket, so A 21 was chosen" in i for i in merge.infos)


def test_an_empty_base_builds_a_show_up_from_an_initialized_board():
    change_set = patch.empty_change_set("Kick")
    kick = horn(1, "Kick", 1)
    kick.update(dca=["Drums"], mute_group=[], bus_sends=[])
    change_set["add"]["channels"] = [kick]
    change_set["add"]["dcas"] = {"Drums": {}}
    board = amend.strip_occupancy(
        occupancy_state(plan={"channels": []}, theirs=(), unread=()), None)
    amendment, merge = patch.plan_patch(patch.empty_base("wing-compact"),
                                        patch.validate_change_set(change_set), board,
                                        console_model="wing-compact")
    assert amendment.strips == ["ch:1"] and not amendment.blocked
    assert merge.plan["dcas"] == {"Drums": {"index": 1}}
    assert amend.preflight(amendment).refusal is None


def test_placements_from_earlier_amends_are_carried_forward():
    base = applied_plan()
    base["meta"]["amend_placements"] = {"ch:12": "ch:11"}
    amendment, _ = patch.plan_patch(base, patch.validate_change_set(horns_change_set()),
                                    occupancy())
    assert amendment.effective_plan["meta"]["amend_placements"]["ch:12"] == "ch:11"


def test_a_malformed_reply_is_a_change_error_with_the_text_kept():
    with pytest.raises(patch.ChangeError) as exc:
        patch.parse_change_set("I think you want three horns.")
    assert exc.value.partial_text == "I think you want three horns."
    with pytest.raises(patch.ChangeError, match="change-set format"):
        patch.parse_change_set(json.dumps({"name": "x", "add": {}, "drop": {}}))


# ======================================================================
# The command
# ======================================================================


def test_a_preview_compiles_the_change_reads_the_desk_and_writes_nothing(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _patch(show) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "Change: Horns for tonight" in out
    assert "3 added, 19 unchanged" in out
    assert "Timing: desk read" in out and "model call" in out and "(fake)" in out
    assert _writes(desk) == []
    assert (show / "plan.json").read_bytes() == before
    assert journal_stack.entries(show) == []
    assert "--save-change-set" in out


def test_what_the_model_is_given(tmp_path, desk, model, capsys):
    """Decision 3: the plan on the desk as read-only context, the house
    conventions and the bundle's instructions (comments stripped), and the
    change -- and a change set, not a plan, is what it is asked for."""
    show = _bundle(tmp_path)
    house = tmp_path / "house.md"
    house.write_text("# House\n\nHorns get a 100 Hz high-pass.\n<!-- a note to myself -->\n")
    (show / "instructions.md").write_text("# Tonight\n\nThe horns go in the Horns DCA.\n")
    assert _patch(show, "--conventions", str(house)) == 0, capsys.readouterr()
    [(system, user)] = model.calls
    assert "CHANGE SET" in system and "{console}" not in system
    assert model.schemas == [patch.CHANGE_SET_SCHEMA]
    assert model.labels == ["change"]
    assert HORNS_TEXT in user
    assert "Horns get a 100 Hz high-pass." in user and "a note to myself" not in user
    assert "The horns go in the Horns DCA." in user
    assert '"name": "Kick"' in user and "READ-ONLY" in user


def test_a_confirmed_patch_writes_journals_the_change_and_leaves_plan_json(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert {desk.state[f"/ch/{n}/name"][0] for n in (21, 22, 23)} == {
        "Trumpet", "Trombone", "T.Sax"}
    assert (show / "plan.json").read_bytes() == before
    assert "plan.json is unchanged -- only a build writes it" in out
    assert "recorded as change 1: Horns for tonight" in out
    [entry] = journal_stack.entries(show)
    assert entry.kind == "patch"
    assert entry.change == {"number": 1, "name": "Horns for tonight", "text": HORNS_TEXT}
    payload = json.loads(entry.path.read_text())
    assert payload["change"] == entry.change
    assert {c["name"] for c in payload[journal_stack.DESK_PLAN_BLOCK]["plan"]["channels"]} >= {
        "Trumpet", "Trombone", "T.Sax"}
    # Written straight into journals/ -- no top-level copy --
    # and the index row the UI draws from.
    assert entry.path.parent == show / "journals"
    assert not (show / "patch-journal.json").exists()
    [row] = journal_stack.listing(show)
    assert row.change["name"] == "Horns for tonight" and row.is_top
    assert "change 1: Horns for tonight" in journal_stack.describe(row)


def test_changes_are_numbered_in_the_order_they_are_written(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    lose = patch.empty_change_set("Lose the MD vocal")
    lose["drop"]["channels"] = ["MLD VOX"]
    model.response = _reply(lose)
    assert _patch(show, text="the MD has gone home", confirm=True) == 0, capsys.readouterr()
    changes = [e.change for e in journal_stack.entries(show)]
    assert [(c["number"], c["name"]) for c in changes] == [
        (1, "Horns for tonight"), (2, "Lose the MD vocal")]
    assert desk.state["/ch/14/name"][0] in ("", "CH14")


def test_the_same_change_again_finds_the_horns_on_the_desk_and_writes_nothing(
        tmp_path, desk, model, capsys):
    """The base is the desk's own journal entry: the horns the first patch
    wrote are ON the desk, so the same change set now describes channels
    already there -- nothing is added a second time."""
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    first = _writes(desk)
    capsys.readouterr()
    assert _patch(show, confirm=True) == 0
    out = capsys.readouterr().out
    assert _writes(desk) == first
    assert "applied plan: the one this desk's newest write left on it" in out
    assert "22 ours" in out
    assert "Nothing to add" in out


def test_undo_takes_a_patch_off_like_an_amend(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    capsys.readouterr()
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9"]) == 0
    assert "change 1: Horns for tonight" in capsys.readouterr().out
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "only a build writes it, and that patch did not" in out
    for n in (21, 22, 23):
        assert desk.state[f"/ch/{n}/name"][0] != "Trumpet"
    assert (show / "plan.json").read_bytes() == before
    [patched, undone] = journal_stack.listing(show)[::-1]
    assert patched.undone_by == undone.id


def test_a_refused_change_writes_nothing_and_exits_2(tmp_path, desk, model, capsys):
    change_set = horns_change_set()
    change_set["add"]["channels"][0]["bus_sends"] = [{"bus": "MON9", "mode": "pre",
                                                      "level_db": 0.0}]
    model.response = _reply(change_set)
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 2
    captured = capsys.readouterr()
    assert "REFUSED" in captured.out and "bus 'MON9'" in captured.out
    assert "Refusing to patch: nothing was written." in captured.err
    assert _writes(desk) == [] and journal_stack.entries(show) == []


def test_a_change_that_only_modifies_writes_nothing_and_says_so(tmp_path, desk, model, capsys):
    change_set = patch.empty_change_set("Vox to MON2")
    change_set["modify"] = [{"object": "channel", "name": "F VOX 1",
                             "change": "send to MON2 at -10 dB"}]
    model.response = _reply(change_set)
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0
    out = capsys.readouterr().out
    assert "MODIFIED" in out and "names no field to set" in out
    assert "Nothing to add" in out and _writes(desk) == []


# ---- the base ----------------------------------------------------------


def test_a_desk_this_bundle_never_wrote_falls_back_to_plan_json_and_says_so(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    assert _patch(show) == 0
    out = capsys.readouterr().out
    assert "so the applied plan is plan.json -- the bundle's last build" in out


def test_no_journal_and_no_plan_json_is_an_empty_base(tmp_path, monkeypatch, model, capsys):
    """An initialized board: every strip free, and a bundle with nothing in
    it yet. The change starts from an empty base, said at INFO."""
    board = DeskConsole({address: (value, "i" if isinstance(value, int) else "s")
                         for address, value in occupancy_state(
                             plan={"channels": []}, theirs=(), unread=()).values.items()})
    board.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: board)
    kick = horn(1, "Kick", 1)
    kick.update(dca=["Drums"], mute_group=[], bus_sends=[])
    change_set = patch.empty_change_set("Kick drum")
    change_set["add"]["channels"] = [kick]
    change_set["add"]["dcas"] = {"Drums": {}}
    model.response = _reply(change_set)
    show = _bundle(tmp_path, plan=None)
    assert _patch(show, "--console-model", "wing-compact", text="kick on A1, Drums DCA",
                  confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "starts from an EMPTY base" in out
    assert board.state["/ch/1/name"][0] == "Kick"
    assert not (show / "plan.json").exists(), "a patch never writes plan.json"
    [entry] = journal_stack.entries(show)
    assert [c["name"] for c in json.loads(entry.path.read_text())[
        journal_stack.DESK_PLAN_BLOCK]["plan"]["channels"]] == ["Kick"]
    # And the next change builds on it: the base is now the desk's journal.
    snare = horn(2, "Snare", 2)
    snare.update(dca=["Drums"], mute_group=[], bus_sends=[])
    change_set = patch.empty_change_set("Snare")
    change_set["add"]["channels"] = [snare]
    model.response = _reply(change_set)
    assert _patch(show, "--console-model", "wing-compact", text="snare on A2, Drums DCA",
                  confirm=True) == 0, capsys.readouterr()
    assert board.state["/ch/2/name"][0] == "Snare"
    assert [e.change["number"] for e in journal_stack.entries(show)] == [1, 2]


def test_an_empty_base_with_no_model_to_be_had_asks_for_one(tmp_path, monkeypatch, model,
                                                            capsys):
    board = DeskConsole({})
    board.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: board)
    show = _bundle(tmp_path, plan=None)
    assert _patch(show) == 1
    assert "pass --console-model" in capsys.readouterr().err


# ---- the change set, saved and reused ----------------------------------


def test_save_change_set_then_write_exactly_it_with_no_model_call(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    saved = tmp_path / "horns.json"
    assert _patch(show, "--save-change-set", str(saved)) == 0, capsys.readouterr()
    assert json.loads(saved.read_text())["change"] == HORNS_TEXT
    model.response = None                          # a second call would now fail
    assert _patch(show, "--change-set", str(saved), text=None, confirm=True) == 0, \
        capsys.readouterr()
    assert len(model.calls) == 1
    [entry] = journal_stack.entries(show)
    assert entry.change["text"] == HORNS_TEXT
    out = capsys.readouterr().out
    assert "model call: none (--change-set" in out


def test_a_review_json_is_a_change_set_too(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    review = tmp_path / "review.json"
    assert _patch(show, "--review-json", str(review)) == 0, capsys.readouterr()
    payload = json.loads(review.read_text())
    assert payload["mode"] == "patch"
    assert payload["change"]["name"] == "Horns for tonight"
    assert payload["change"]["number"] == 1 and payload["change"]["compiled_by"] == "fake"
    assert payload["timing"]["model_s"] is not None and "Timing:" in payload["timing"]["line"]
    model.response = None
    assert _patch(show, "--change-set", str(review), text=None) == 0, capsys.readouterr()


def test_the_model_failing_says_why_and_keeps_what_arrived(tmp_path, desk, model, capsys):
    model.response = "Sure! Three horns coming up."
    show = _bundle(tmp_path)
    assert _patch(show) == 1
    err = capsys.readouterr().err
    assert "the change could not be compiled" in err
    assert (show / "change.partial.json").read_text() == "Sure! Three horns coming up."
    assert _writes(desk) == []


def test_a_patch_offline_from_state_needs_no_desk(tmp_path, model, capsys):
    show = _bundle(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(json.dumps(occupancy_state().values))
    assert cli.main(["patch", "--show", str(show), HORNS_TEXT, "--state", str(state),
                     "--console-model", "wing-compact"]) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "3 added" in out and "desk read: none (--state)" in out
    assert "Reviewed offline from --state" in out


def test_usage_errors(tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    assert cli.main(["patch", "--show", str(show), "--console", "198.51.100.9"]) == 1
    assert "say what the change is" in capsys.readouterr().err
    assert cli.main(["patch", "--show", str(show), "x", "--amended-plan",
                     str(show / "plan.json"), "--console", "198.51.100.9"]) == 1
    assert "give one or the other" in capsys.readouterr().err
    assert cli.main(["patch", "x", "--console", "198.51.100.9"]) == 1
    assert "patch needs --show DIR" in capsys.readouterr().err


# ======================================================================
# amend: the same operation, under its old name, unchanged
# ======================================================================


def test_patch_amended_plan_is_amend(tmp_path, desk, capsys):
    from test_amend import amended_plan

    show = _bundle(tmp_path)
    (show / "rebuilt.plan.json").write_text(json.dumps(amended_plan(), indent=2))
    assert cli.main(["patch", "--show", str(show), "--amended-plan",
                     str(show / "rebuilt.plan.json"), "--console", "198.51.100.9",
                     "--no-progress", "--confirm"]) == 0, capsys.readouterr()
    [entry] = journal_stack.entries(show)
    assert entry.kind == "amend" and entry.change is None
    assert entry.path.parent == show / "journals"
    assert not (show / "amend-journal.json").exists()
    assert not (show / "patch-journal.json").exists()


def test_amend_still_requires_its_rebuilt_plan():
    with pytest.raises(SystemExit):
        cli.main(["amend", "--show", "x", "--console", "198.51.100.9"])


def test_amend_keeps_every_flag_it_had():
    _parser, subparsers = cli.build_parser()
    amend_flags = {a.dest for a in subparsers["amend"]._actions}
    for flag in ("show", "plan", "amended_plan", "console", "state", "port", "timeout",
                 "channels", "aux", "allow_strip", "confirm", "journal", "skip_verify",
                 "skip_untouched_proof", "per_leaf", "review_json", "no_progress"):
        assert flag in amend_flags, flag
    patch_flags = {a.dest for a in subparsers["patch"]._actions}
    assert amend_flags - {"help"} <= patch_flags


# ======================================================================
# Decision 7: a full apply warns before it replaces changes
# ======================================================================


def _apply_harness(desk, monkeypatch):
    import atoo.console as console_module
    from atoo.console import OscReply

    desk.identity = lambda: OscReply(
        address="/?", typetag="s", args=["WING,198.51.100.9,DESK,wing-compact,SER,3.1"])
    monkeypatch.setattr(type(desk), "__enter__", lambda self: self, raising=False)
    monkeypatch.setattr(type(desk), "__exit__", lambda self, *exc: False, raising=False)
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: desk)


def test_a_full_apply_warns_that_it_replaces_the_changes_on_this_desk(
        tmp_path, desk, model, monkeypatch, capsys):
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    _apply_harness(desk, monkeypatch)
    capsys.readouterr()
    cli.main(["apply", "--show", str(show), "--console", "198.51.100.9"])
    err = " ".join(capsys.readouterr().err.split())
    assert "apply.replaces-changes" in err
    assert "a full apply replaces 1 change(s)" in err
    assert "change 1: Horns for tonight" in err
    assert "WARNING" in err


def test_the_warning_points_at_promote_and_names_a_promoted_change(
        tmp_path, desk, model, monkeypatch, capsys):
    """After `patch --promote` the change is in instructions.md, but still
    not in plan.json until the rebuilt show is built and applied -- so the
    warning still lists it, and now says it is promoted. Its fix names
    `atoo patch --promote` as the way to keep a change."""
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    assert cli.main(["patch", "--show", str(show), "--promote", "1", "--confirm"]) == 0, \
        capsys.readouterr()
    _apply_harness(desk, monkeypatch)
    capsys.readouterr()
    cli.main(["apply", "--show", str(show), "--console", "198.51.100.9"])
    err = " ".join(capsys.readouterr().err.split())
    assert "change 1: Horns for tonight (promoted)" in err
    assert "1 of them is already promoted into instructions.md" in err
    assert "atoo patch --promote" in err


def test_no_warning_once_an_apply_stands_above_the_changes(
        tmp_path, desk, model, monkeypatch, capsys):
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 0, capsys.readouterr()
    _apply_harness(desk, monkeypatch)
    assert cli.main(["apply", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) in (0, 2), capsys.readouterr()
    capsys.readouterr()
    cli.main(["apply", "--show", str(show), "--console", "198.51.100.9"])
    assert "apply.replaces-changes" not in capsys.readouterr().err


def test_an_amend_counts_as_a_change_the_apply_would_replace(tmp_path, desk, capsys):
    from test_amend import amended_plan

    show = _bundle(tmp_path)
    (show / "rebuilt.plan.json").write_text(json.dumps(amended_plan(), indent=2))
    assert cli.main(["amend", "--show", str(show), "--amended-plan",
                     str(show / "rebuilt.plan.json"), "--console", "198.51.100.9",
                     "--no-progress", "--confirm"]) == 0, capsys.readouterr()
    [entry] = journal_stack.changes_on_desk(show, {"address": "198.51.100.9", "port": 2223})
    diagnostic = journal_stack.replaced_changes_diagnostic(
        show, {"address": "198.51.100.9", "port": 2223})
    assert "an amend from a rebuilt plan" in diagnostic.message


def test_a_legacy_amend_whose_plan_is_plan_json_is_not_warned_about(tmp_path, desk, capsys):
    """An amend recorded between #259 and #279 replaced plan.json. While
    plan.json is still what it wrote, its content IS in plan.json."""
    from test_amend_plan_json import _bundle as amend_bundle, _legacy_amend

    show = amend_bundle(tmp_path)
    _legacy_amend(show)
    desk_block = {"address": "198.51.100.9", "port": 2223}
    assert journal_stack.changes_on_desk(show, desk_block,
                                         (show / "plan.json").read_bytes()) == []
    (show / "plan.json").write_text("{}")
    assert len(journal_stack.changes_on_desk(show, desk_block, b"{}")) == 1


def test_a_socket_the_desk_lacks_is_refused_in_a_changes_words(tmp_path, desk, model, capsys):
    """The pre-flight runs on a change as on an amend, and its
    refusal speaks of the change -- "patch" in it still means sockets."""
    change_set = horns_change_set()
    change_set["add"]["channels"][0]["patch"] = {"group": "LCL", "sockets": [30],
                                                 "stated": True}
    model.response = _reply(change_set)
    show = _bundle(tmp_path)
    assert _patch(show, confirm=True) == 2
    err = capsys.readouterr().err
    assert "This change would patch 1 socket(s) that do not exist" in err
    assert "Refusing to write this change: LCL 30" in err
    assert _writes(desk) == []


@pytest.mark.example_guard
def test_the_shipped_example_change_set_is_a_valid_change_set():
    """`examples/amend-demo/horns.change-set.json` is the worked example in
    docs/user/applying.md and examples/README.md stage 6b. Asserted valid,
    never on what is in it."""
    path = Path(__file__).parent.parent / "examples" / "amend-demo" / "horns.change-set.json"
    change_set, text = patch.load_change_set(path)
    assert text and change_set["name"]
