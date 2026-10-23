"""`atoo patch` on a running strip's source: 48V and the mic model are a
change's to set, the input and stereo-ness are not.

A running strip's `source` is part phantom power and a mic model -- things
an engineer reasonably changes in the setup window, and which move no audio
between strips -- and part the identity of the strip (which input it is,
mono or stereo), which a change never rewrites. The refusal used to cover the
whole of `source` while its own text said to set `source.phantom` and
`source.model`. These tests hold:

* `source.phantom`, `source.pair_phantom`, `source.model` and `source.type`
  are set when named, and nothing else of the strip moves;
* switching 48V is written to the socket's phantom address and the review
  says SWITCHES 48V LIVE, as a repatch says MOVES AUDIO LIVE; a model, which
  no console address carries, is recorded in the plan and nothing is written;
* the input, the second row of a pair, stereo-ness and the build's own
  record of the strip are still refused, also when the change restates the
  whole `source`;
* a passive ribbon microphone left with 48V on is refused: that setting
  destroys the microphone;
* it holds on the command line, on the simulated desk, and in the browser's
  Patch API.

The plan is the frozen applied show; nothing reads a bundle under
`examples/`.
"""

from __future__ import annotations

import copy
import json

import pytest

from atoo import amend, cli, journal_stack, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from test_amend import DeskConsole, applied_plan, occupancy
from test_amend_plan_json import _seed


def _channel(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


def _modify(name: str, fields: dict) -> dict:
    return {"object": "channel", "name": name, "change": "as typed", "fields": fields}


def _change_set(*modify: dict) -> dict:
    change_set = patch.empty_change_set("Source")
    change_set["modify"] = list(modify)
    return patch.validate_change_set(change_set)


def _review(plan: dict, name: str, fields: dict):
    amendment, merge = patch.plan_patch(plan, _change_set(_modify(name, fields)), occupancy())
    return amendment, merge, amend.amendment_targets(amendment)


def _refusals(amendment) -> list:
    return [c for c in amendment.changes if c.kind is ChangeKind.REFUSED]


def _plan_with(name: str, **source) -> dict:
    plan = applied_plan()
    _channel(plan, name)["source"].update(source)
    return plan


def _stereo_plan() -> dict:
    plan = applied_plan()
    snare = _channel(plan, "Snare")
    snare["source"]["stereo"] = True
    snare["patch"] = {"group": "A", "sockets": [40, 41], "stated": True}
    return plan


# ======================================================================
# What a change may set
# ======================================================================


@pytest.mark.parametrize("fields,path", [
    ({"source.phantom": True}, "source.phantom"),
    ({"source.model": "SM57"}, "source.model"),
    ({"source.type": "Line"}, "source.type"),
])
def test_phantom_model_and_type_of_a_running_strip_are_set_and_nothing_else_moves(fields, path):
    plan = applied_plan()
    amendment, merge, _targets = _review(plan, "Snare", fields)
    assert _refusals(amendment) == [] and not amendment.blocked
    assert [e.path for e in merge.edits] == [path]
    expected = copy.deepcopy(plan)
    _channel(expected, "Snare")["source"][path.split(".")[1]] = next(iter(fields.values()))
    assert merge.plan["channels"] == expected["channels"]


def test_48v_is_written_to_the_sockets_phantom_address_and_the_review_says_it_is_live():
    amendment, merge, targets = _review(applied_plan(), "Snare", {"source.phantom": True})
    [edit] = merge.edits
    assert edit.switches_phantom and not edit.moves_audio
    assert edit.line().startswith("SWITCHES 48V LIVE -- channel 'Snare' on ch:2")
    assert [(t.address, t.compute_value(None)) for t in targets.to_write] == \
        [("/io/in/A/2/vph", 1)]
    [edited] = [c for c in amendment.changes if c.kind is ChangeKind.EDITED]
    assert edited.reason.startswith("SWITCHES 48V LIVE -- ")
    [warning] = [w for w in amendment.warnings if "phantom" in w]
    assert "the moment it is written" in warning and "passive ribbon" in warning
    assert edit.to_json()["switches_phantom"] is True
    assert edit.to_json()["moves_audio"] is False


def test_48v_off_is_live_too():
    plan = _plan_with("Snare", phantom=True)
    _amendment, merge, targets = _review(plan, "Snare", {"source.phantom": False})
    assert merge.edits[0].line().startswith("SWITCHES 48V LIVE -- ")
    assert [(t.address, t.compute_value(None)) for t in targets.to_write] == \
        [("/io/in/A/2/vph", 0)]


def test_a_model_is_set_in_the_plan_and_nothing_is_written_to_the_desk_for_it():
    amendment, merge, targets = _review(applied_plan(), "Snare", {"source.model": "SM57"})
    assert targets.to_write == []
    assert not merge.edits[0].switches_phantom and merge.edits[0].live_marker == ""
    [info] = [i for i in amendment.infos if "no console address carries it" in i]
    assert "source.model" in info and "only when the same change writes something else" in info
    assert not any("phantom" in w for w in amendment.warnings)


def test_48v_on_a_group_with_no_phantom_address_is_not_called_live():
    plan = applied_plan()
    _channel(plan, "Snare")["patch"] = {"group": "USB", "sockets": [2], "stated": True}
    amendment, _merge, targets = _review(plan, "Snare", {"source.phantom": True})
    assert targets.to_write == []
    [edit] = amendment.edits
    assert not edit.switches_phantom and "SWITCHES" not in edit.line()
    assert any("no confirmed phantom-power address" in w for w in targets.warnings)


def test_48v_on_a_stereo_channel_switches_both_sockets_and_the_review_marks_both():
    plan = _stereo_plan()
    amendment, merge, targets = _review(plan, "Snare", {"source.phantom": True})
    assert _refusals(amendment) == []
    assert sorted((t.address, t.compute_value(None)) for t in targets.to_write) == \
        [("/io/in/A/40/vph", 1), ("/io/in/A/41/vph", 1)]
    assert [e.path for e in merge.edits] == ["source.phantom"]
    assert merge.edits[0].switches_phantom and merge.edits[0].line().startswith("SWITCHES 48V LIVE")


def test_48v_set_on_a_pair_the_plan_states_two_values_for_is_carried_to_both_sockets():
    """A plan from an older build can state two values for a pair. The desk
    holds one for both sockets, so the plan is read as on (on if either is)
    and setting `source.phantom` is the pair's 48V: the second follows, and
    the review says it did."""
    plan = _stereo_plan()
    _channel(plan, "Snare")["source"].update(phantom=False, pair_phantom=True)
    amendment, merge, targets = _review(plan, "Snare", {"source.phantom": False})
    assert _refusals(amendment) == []
    assert [e.path for e in merge.edits] == ["source.pair_phantom"]
    assert merge.edits[0].switches_phantom
    assert sorted((t.address, t.compute_value(None)) for t in targets.to_write) == \
        [("/io/in/A/40/vph", 0), ("/io/in/A/41/vph", 0)]
    [info] = [i for i in amendment.infos if "switches both sockets together" in i]
    assert "source.pair_phantom is set to false to match source.phantom" in info
    assert _channel(merge.plan, "Snare")["source"]["pair_phantom"] is False


@pytest.mark.parametrize("fields", [
    {"source.pair_phantom": True},
    {"source": {"stereo": True, "pair_phantom": True, "input": "Snare", "type": "Mic",
                "model": "", "phantom": False}},
    {"source.phantom": True, "source.pair_phantom": False},
], ids=["the second side alone", "the whole source, second side alone", "the two sides different"])
def test_one_side_of_a_stereo_channel_is_not_switched_on_its_own(fields):
    """The desk switches a stereo channel's 48V on both sockets together,
    so a change that would switch only one is a setting that cannot be made
    -- refused, naming the field that does it, nothing written."""
    plan = _stereo_plan()
    amendment, merge, targets = _review(plan, "Snare", fields)
    [refused] = _refusals(amendment)
    assert "switch 48V together" in refused.reason and "set source.phantom" in refused.reason
    assert amendment.blocked and targets.to_write == []
    assert merge.plan["channels"] == plan["channels"]


def test_both_sides_set_to_the_same_value_are_accepted():
    plan = _stereo_plan()
    amendment, merge, targets = _review(
        plan, "Snare", {"source.phantom": True, "source.pair_phantom": True})
    assert _refusals(amendment) == []
    assert sorted(t.address for t in targets.to_write) == ["/io/in/A/40/vph", "/io/in/A/41/vph"]


def test_a_stereo_pair_built_with_two_values_is_left_alone_by_a_change_that_is_not_about_48v():
    plan = _stereo_plan()
    _channel(plan, "Snare")["source"].update(phantom=True, pair_phantom=False)
    amendment, merge, targets = _review(plan, "Snare", {"source.model": "SM57"})
    assert _refusals(amendment) == []
    assert _channel(merge.plan, "Snare")["source"]["pair_phantom"] is False
    assert targets.to_write == []


def test_a_change_that_restates_the_whole_source_sets_what_changed_in_it():
    plan = applied_plan()
    source = dict(_channel(plan, "Snare")["source"], model="SM57", phantom=True)
    amendment, merge, _t = _review(plan, "Snare", {"source": source})
    assert _refusals(amendment) == []
    assert sorted(e.path for e in merge.edits) == ["source.model", "source.phantom"]


# ======================================================================
# What a change may not set, and what the refusal says
# ======================================================================


@pytest.mark.parametrize("fields,words", [
    ({"source.input": "Bagpipes"}, "how a running strip is recognised"),
    ({"source.pair_input": "Snare B"}, "second row of a stereo pair"),
    ({"source.from": "instructions"}, "the build's own record"),
    ({"source.quote": "snare on 2"}, "the build's own record"),
    ({"source.condition": "if available"}, "the build's own record"),
])
def test_what_says_which_source_a_strip_is_is_still_refused(fields, words):
    plan = applied_plan()
    amendment, merge, targets = _review(plan, "Snare", fields)
    [refused] = _refusals(amendment)
    assert words in refused.reason and amendment.blocked
    assert merge.plan["channels"] == plan["channels"] and targets.to_write == []


def test_the_refusal_names_the_parts_of_a_source_a_change_can_set():
    amendment, _m, _t = _review(applied_plan(), "Snare", {"source.input": "Bagpipes"})
    [refused] = _refusals(amendment)
    for field in ("source.phantom", "source.model", "source.type"):
        assert field in refused.reason


def test_restating_the_whole_source_with_a_different_input_is_refused():
    plan = applied_plan()
    for changed in ({"input": "Bagpipes"},):
        source = dict(_channel(plan, "Snare")["source"], phantom=True, **changed)
        amendment, merge, _t = _review(plan, "Snare", {"source": source})
        [refused] = _refusals(amendment)
        assert f"source.{next(iter(changed))}" in refused.reason
        assert merge.plan["channels"] == plan["channels"]


def test_a_field_a_source_lacks_is_still_refused_by_the_schema():
    amendment, _m, _t = _review(applied_plan(), "Snare", {"source.gain": 30})
    [refused] = _refusals(amendment)
    assert "source.gain" in refused.reason and "not a field this format has" in refused.reason


# ======================================================================
# A passive ribbon with 48V on destroys the microphone
# ======================================================================


@pytest.mark.parametrize("plan,fields", [
    (applied_plan(), {"source.model": "Royer R-121", "source.phantom": True}),
    (_plan_with("Snare", model="Royer R-121"), {"source.phantom": True}),
    (_plan_with("Snare", phantom=True), {"source.model": "Royer R-121"}),
], ids=["both in one change", "48V onto a ribbon", "a ribbon named on a strip with 48V"])
def test_a_change_that_leaves_a_passive_ribbon_with_48v_on_is_refused(plan, fields):
    amendment, merge, targets = _review(plan, "Snare", fields)
    [refused] = _refusals(amendment)
    assert "passive ribbon" in refused.reason and "destroys" in refused.reason
    assert amendment.blocked and targets.to_write == []
    assert merge.plan["channels"] == plan["channels"]


def test_a_ribbon_with_48v_switched_off_in_the_same_change_goes_through():
    plan = _plan_with("Snare", phantom=True)
    amendment, merge, targets = _review(
        plan, "Snare", {"source.model": "Royer R-121", "source.phantom": False})
    assert _refusals(amendment) == []
    assert [(t.address, t.compute_value(None)) for t in targets.to_write] == \
        [("/io/in/A/2/vph", 0)]
    assert _channel(merge.plan, "Snare")["source"]["model"] == "Royer R-121"


def test_a_ribbon_with_48v_off_is_not_refused():
    amendment, _m, _t = _review(applied_plan(), "Snare", {"source.model": "Royer R-121"})
    assert _refusals(amendment) == []


# ======================================================================
# `atoo patch`, end to end, on the simulated desk
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
        _modify("Snare", {"source.phantom": True}))))
    monkeypatch.setattr(cli, "provider_from_env", lambda: fake)
    return fake


def _bundle(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(applied_plan(), indent=4) + "\n")
    return show


def _patch(show, text, *extra, confirm=False):
    return cli.main(["patch", "--show", str(show), text, "--console", "198.51.100.9",
                     "--no-progress", *(["--confirm"] if confirm else []), *extra])


def _leaves_written(console) -> set[str]:
    return {a for a, _v, _t in console.set_param_calls} | {
        f"{a}/{command.partition('=')[0]}" for a, command in console.set_node_calls}


def test_patch_switches_48v_on_a_running_strip_says_so_and_undo_puts_it_back(
        tmp_path, desk, model, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert desk.state["/io/in/A/2/vph"][0] == 0
    assert _patch(show, "48V on the snare", confirm=True) == 0, capsys.readouterr()
    captured = capsys.readouterr()
    assert "1 PHANTOM POWER CHANGE(S) ON SOMETHING ALREADY RUNNING" in captured.out
    assert "!!   SWITCHES 48V LIVE -- channel 'Snare' on ch:2: source.phantom false -> true" \
        in captured.out
    assert "REFUSED" not in captured.out
    assert desk.state["/io/in/A/2/vph"][0] == 1
    assert _leaves_written(desk) == {"/io/in/A/2/vph"}
    assert (show / "plan.json").read_bytes() == before
    [entry] = journal_stack.entries(show)
    left = json.loads(entry.path.read_text())[journal_stack.DESK_PLAN_BLOCK]["plan"]
    assert _channel(left, "Snare")["source"]["phantom"] is True

    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) == 0, capsys.readouterr()
    assert desk.state["/io/in/A/2/vph"][0] == 0


def test_patch_switches_48v_on_both_sockets_of_a_stereo_pair_and_the_review_marks_both(
        tmp_path, desk, model, capsys):
    """Keys is the applied show's stereo pair, on A 15-16."""
    model.response = json.dumps(_change_set(_modify("Keys", {"source.phantom": True})))
    show = _bundle(tmp_path)
    assert desk.state["/io/in/A/15/vph"][0] == 0 and desk.state["/io/in/A/16/vph"][0] == 0
    assert _patch(show, "48V on the keys", confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "SWITCHES 48V LIVE -- channel 'Keys' on ch:9: source.phantom false -> true" in out
    assert desk.state["/io/in/A/15/vph"][0] == 1 and desk.state["/io/in/A/16/vph"][0] == 1
    assert _leaves_written(desk) == {"/io/in/A/15/vph", "/io/in/A/16/vph"}


def test_patch_refuses_one_side_of_a_stereo_pair_and_the_desk_is_untouched(
        tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify("Keys", {"source.pair_phantom": True})))
    show = _bundle(tmp_path)
    assert _patch(show, "48V on the right side of the keys", confirm=True) == 2
    out = capsys.readouterr().out
    assert "switch 48V together" in out and "set source.phantom" in out
    assert _leaves_written(desk) == set()
    assert desk.state["/io/in/A/16/vph"][0] == 0


def test_patch_with_only_a_mic_model_writes_nothing_and_says_it_is_not_kept(
        tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify("Snare", {"source.model": "SM57"})))
    show = _bundle(tmp_path)
    assert _patch(show, "the snare mic is an SM57", confirm=True) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "no console address carries it" in out and "PHANTOM POWER" not in out
    assert "Nothing to add and nothing to return to free" in out
    assert _leaves_written(desk) == set()
    assert journal_stack.entries(show) == []


def test_a_mic_model_beside_a_write_is_kept_in_the_journal_entrys_plan(
        tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify(
        "Snare", {"source.model": "SM57", "source.phantom": True})))
    show = _bundle(tmp_path)
    assert _patch(show, "the snare mic is an SM57, 48V on", confirm=True) == 0, capsys.readouterr()
    assert _leaves_written(desk) == {"/io/in/A/2/vph"}
    [entry] = journal_stack.entries(show)
    left = json.loads(entry.path.read_text())[journal_stack.DESK_PLAN_BLOCK]["plan"]
    assert _channel(left, "Snare")["source"]["model"] == "SM57"


def test_patch_refuses_a_ribbon_with_48v_and_the_desk_is_untouched(tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify(
        "Snare", {"source.model": "Royer R-121", "source.phantom": True})))
    show = _bundle(tmp_path)
    assert _patch(show, "Royer on the snare, 48V on", confirm=True) == 2
    assert "passive ribbon microphone" in capsys.readouterr().out
    assert _leaves_written(desk) == set()


def test_patch_still_refuses_to_change_the_input_and_says_what_can_be_set(
        tmp_path, desk, model, capsys):
    model.response = json.dumps(_change_set(_modify("Snare", {"source.input": "Bagpipes"})))
    show = _bundle(tmp_path)
    assert _patch(show, "the snare is the bagpipes", confirm=True) == 2
    out = capsys.readouterr().out
    assert "how a running strip is recognised" in out and "source.phantom" in out
    assert _leaves_written(desk) == set()


def test_the_command_help_says_which_parts_of_a_source_a_change_sets():
    text = " ".join(cli.PATCH_DESCRIPTION.split())
    assert "SWITCHES 48V LIVE" in text and "not in which input it is or whether it is stereo" in text
