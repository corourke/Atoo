"""A full apply unpatches every strip the plan does not build, and sets
talkback's assign to the plan's talkback strip (2026-10-02).

The maintainer's sixpiece build (89f2baa) showed a channel 24 named MUSIC: the
plan built ch 1-23, so ch 24 kept its factory patch (LCL 24), apply named
LCL 23/24 "MUSIC" for aux 1's stereo pair, and an unnamed strip shows its
source's name. *"We should unpatch any channels that are not in the plan.
Simply unpatch from the source."* And: *"when there is a talkback channel,
there is a setting in Setup -> Audio to enable the talkback on either CH 40
or AUX 8."*

The sixpiece plan here is the frozen copy under `tests/fixtures/`, never
`examples/sixpiece/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import cli, console_facts as facts
from atoo.apply import (apply_plan, full_apply_notes, full_apply_targets,
                             talkback_assign, unbuilt_strips)
from atoo.undo import undo_from_journal, load_journal
from atoo.verify_plan import verify_plan
from tests.test_apply import FakeConsole

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIXPIECE = FIXTURES / "sixpiece_2026-10-02.plan.json"


def sixpiece() -> dict:
    return json.loads(SIXPIECE.read_text())


def tiny(*strips) -> dict:
    """A plan of the given strips, (bank, n, name), each a copy of the
    frozen sixpiece plan's Kick with its place and name changed, and
    nothing else in it."""
    base = sixpiece()
    kick = base["channels"][0]
    kick.update(bus_sends=[], dca=[], mute_group=[], main_routes=[])
    channels = []
    for bank, n, name in strips:
        ch = copy.deepcopy(kick)
        ch.update(bank=bank, channel=n, name=name)
        ch["source"]["input"] = name
        ch["patch"] = {"group": "A", "sockets": [n], "stated": True}
        channels.append(ch)
    return {"meta": base["meta"], "dcas": {}, "mute_groups": {}, "busses": {},
            "outputs": {}, "channels": channels}


def factory_desk(plan: dict, **overrides) -> FakeConsole:
    """Every unbuilt strip on its factory patch (ch N <- LCL N; aux on
    AUX), talkback OFF -- plus `overrides` ({address: value})."""
    state = {}
    for t in full_apply_targets(plan):
        if t.address == facts.TALK_ASSIGN:
            state[t.address] = (facts.TALK_OFF, "s")
        else:
            state[t.address] = ("LCL" if t.address.startswith("/ch/") else "AUX", "s")
    for address, value in overrides.items():
        state[address] = (value, "s")
    return FakeConsole(state)


# ======================================================================
# The sixpiece plan: what a full apply writes beyond its own strips
# ======================================================================


def test_sixpiece_unbuilt_strips_are_ch_24_to_40_and_aux_3_to_7():
    assert unbuilt_strips(sixpiece()) == {"ch": list(range(24, 41)), "aux": [3, 4, 5, 6, 7]}


def test_sixpiece_full_apply_targets_unpatch_them_and_assign_talkback_to_aux8():
    targets = full_apply_targets(sixpiece())
    off = {t.address: t.compute_value(None) for t in targets if t.address != facts.TALK_ASSIGN}
    assert off == {**{f"/ch/{n}/in/conn/grp": "OFF" for n in range(24, 41)},
                   **{f"/aux/{n}/in/conn/grp": "OFF" for n in range(3, 8)}}
    [talk] = [t for t in targets if t.address == facts.TALK_ASSIGN]
    assert talk.address == "/cfg/talk/assign"
    assert talk.value_type == "s" and talk.compute_value("OFF") == "AUX8"
    assert "TALKBACK" in talk.description


def test_sixpiece_full_apply_writes_only_the_source_of_an_unbuilt_strip():
    """Only `in/conn/grp`: no name, fader, mute or anything else."""
    for t in full_apply_targets(sixpiece()):
        if t.address != facts.TALK_ASSIGN:
            assert t.address.endswith("/in/conn/grp")


def test_sixpiece_preflight_notes_say_both_at_info():
    notes = full_apply_notes(sixpiece())
    assert notes == [
        ("apply.unbuilt-strips",
         "INFO ch 24-40, aux 3-7: not in this plan, unpatched from their sources so none "
         "listens to a socket the plan uses (a strip already unpatched is left as it is)"),
        ("apply.talkback-assign",
         "INFO talkback assign (Setup -> Audio) set to AUX8: aux 8 'TALKBACK' is the plan's "
         "talkback strip"),
    ]


def test_sixpiece_verify_has_no_talkback_warning():
    """Its TALKBACK is on aux 8, a strip the assign can name."""
    result = verify_plan(sixpiece())
    assert "talkback.unassignable" not in {f.code for f in result.findings}


def test_sixpiece_full_apply_dry_run_previews_the_unpatch_and_the_assign():
    plan = sixpiece()
    desk = factory_desk(plan)
    result = apply_plan(plan, desk, dry_run=True, full_apply=True)
    by_address = {r.address: r for r in result.writes}
    assert by_address["/ch/24/in/conn/grp"].prior_value == "LCL"
    assert by_address["/ch/24/in/conn/grp"].intended_value == "OFF"
    assert by_address["/ch/24/in/conn/grp"].would_change
    assert by_address["/cfg/talk/assign"].intended_value == "AUX8"
    notes = [w for w in result.warnings if "not in this plan" in w or "talkback assign" in w]
    assert notes == [
        "INFO ch 24-40, aux 3-7: not in this plan, unpatched from their sources so none "
        "listens to a socket the plan uses",
        "INFO talkback assign (Setup -> Audio) set to AUX8 (was 'OFF'): aux 8 'TALKBACK' "
        "is the plan's talkback strip",
    ]
    assert desk.set_node_calls == [] and desk.set_param_calls == []


# ======================================================================
# The unpatch: skipped when already OFF, journalled, reversed by undo
# ======================================================================


def test_a_strip_the_desk_already_reads_as_off_is_skipped_and_counted():
    plan = tiny(("ch", 1, "Kick"))
    desk = factory_desk(plan, **{"/ch/2/in/conn/grp": "OFF", "/aux/3/in/conn/grp": "OFF"})
    result = apply_plan(plan, desk, dry_run=False, full_apply=True)
    by_address = {r.address: r for r in result.writes}
    assert by_address["/ch/2/in/conn/grp"].status == "skipped_no_change"
    assert by_address["/aux/3/in/conn/grp"].status == "skipped_no_change"
    assert by_address["/ch/3/in/conn/grp"].status == "match"
    assert not any(cmd == "grp=OFF" and address == "/ch/2/in/conn"
                   for address, cmd in desk.set_node_calls)
    [note] = [w for w in result.warnings if "not in this plan" in w]
    assert note == ("INFO ch 3-40, aux 1-2, 4-8: not in this plan, unpatched from their "
                    "sources so none listens to a socket the plan uses; 2 more already "
                    "read unpatched")


def test_every_unpatch_is_journalled_and_undo_restores_the_prior_patch(tmp_path):
    """The point of the journal: `undo` puts each unbuilt strip back on the
    socket it had, and talkback's assign back to OFF."""
    plan = tiny(("ch", 1, "Kick"), ("ch", 40, "Talkback"))
    desk = factory_desk(plan, **{"/ch/7/in/conn/grp": "A"})
    journal = tmp_path / "apply.json"
    result = apply_plan(plan, desk, dry_run=False, journal_path=str(journal), full_apply=True)
    assert desk.state["/ch/7/in/conn/grp"][0] == "OFF"
    assert desk.state["/ch/24/in/conn/grp"][0] == "OFF"
    assert desk.state["/aux/5/in/conn/grp"][0] == "OFF"
    assert desk.state["/cfg/talk/assign"][0] == "CH40"
    records = {w["address"]: w for w in json.loads(journal.read_text())["writes"]}
    assert records["/ch/7/in/conn/grp"]["prior_value"] == "A"
    assert records["/ch/24/in/conn/grp"]["prior_value"] == "LCL"
    assert records["/cfg/talk/assign"]["prior_value"] == "OFF"
    assert not result.mismatches

    undo = undo_from_journal(load_journal(str(journal)), desk, dry_run=False)
    assert desk.state["/ch/7/in/conn/grp"][0] == "A"
    assert desk.state["/ch/24/in/conn/grp"][0] == "LCL"
    assert desk.state["/aux/5/in/conn/grp"][0] == "AUX"
    assert desk.state["/cfg/talk/assign"][0] == "OFF"
    assert {s.address for s in undo.reversed_steps} >= {
        "/ch/7/in/conn/grp", "/ch/24/in/conn/grp", "/aux/5/in/conn/grp", "/cfg/talk/assign"}


def test_respects_the_console_models_strip_counts():
    counts = unbuilt_strips({"channels": []})
    assert len(counts["ch"]) == facts.CAPACITY["ch"]
    assert len(counts["aux"]) == facts.CAPACITY["aux"]
    assert "/ch/41/in/conn/grp" not in {t.address for t in full_apply_targets({"channels": []})}


def test_a_built_strip_is_never_unpatched_by_the_full_apply():
    plan = tiny(("ch", 24, "Crowd"), ("aux", 1, "Music"))
    addresses = {t.address for t in full_apply_targets(plan)}
    assert "/ch/24/in/conn/grp" not in addresses
    assert "/aux/1/in/conn/grp" not in addresses


# ======================================================================
# The boundary: only a full apply. Never amend, patch or undo (D14).
# ======================================================================


def test_apply_plan_does_not_unpatch_unless_asked():
    """The default -- what `amend` and `patch` call -- writes nothing for a
    strip the plan does not build."""
    plan = tiny(("ch", 1, "Kick"), ("aux", 8, "TB"))
    result = apply_plan(plan, factory_desk(plan), dry_run=True)
    addresses = {r.address for r in result.writes}
    assert "/ch/2/in/conn/grp" not in addresses
    assert "/cfg/talk/assign" not in addresses
    assert not any("not in this plan" in w for w in result.warnings)


@pytest.mark.parametrize("scope", [{"target_filter": lambda t: True},
                                   {"extra_targets": [object()]}],
                         ids=["target_filter", "extra_targets"])
def test_a_scoped_run_cannot_be_a_full_apply(scope):
    with pytest.raises(ValueError):
        apply_plan(tiny(("ch", 1, "Kick")), FakeConsole(), full_apply=True, **scope)


def test_amend_after_a_full_apply_unpatches_nothing_outside_its_strips(tmp_path, monkeypatch,
                                                                      capsys):
    """The real `atoo apply` then `amend`, through `cli.main`, against
    the fake desk `test_amend_two_desks.py` is built on: the apply's journal
    carries the unpatches, the amend's carries none -- and no talkback
    assign either."""
    from test_amend import amended_plan, applied_plan
    from test_amend_two_desks import PRIMARY_ID, Desk, fresh_state, podium_patched_by_hand

    desk = Desk(fresh_state(), PRIMARY_ID)

    def connect(address, port=None, timeout=None, raw_log=None):
        desk.ip = address
        return desk

    monkeypatch.setattr("atoo.console.WingConsole", connect)
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps(applied_plan(), indent=2) + "\n")
    (show / "rebuilt.plan.json").write_text(json.dumps(amended_plan(), indent=2))
    # The applied show's strips on their factory patch, and talkback OFF,
    # so the apply has something to unpatch.
    for n in range(20, 33):
        desk.state[f"/ch/{n}/in/conn/grp"] = ("LCL", "s")
    desk.state["/cfg/talk/assign"] = ("OFF", "s")

    assert cli.main(["apply", "--show", str(show), "--console", "198.51.100.5", "--confirm",
                     "--skip-verify"]) == 0, capsys.readouterr()
    podium_patched_by_hand(desk)
    assert cli.main(["amend", "--show", str(show),
                     "--amended-plan", str(show / "rebuilt.plan.json"),
                     "--console", "198.51.100.5", "--no-progress", "--confirm"]) == 0, \
        capsys.readouterr()

    from atoo import journal_stack
    entries = journal_stack.entries(show)
    apply_entry = next(e for e in entries if e.kind == "apply")
    amend_entry = next(e for e in entries if e.kind == "amend")
    applied = json.loads(apply_entry.path.read_text())["writes"]
    amended = json.loads(amend_entry.path.read_text())["writes"]
    assert any(w["description"].endswith("not in this plan, unpatched (OFF)")
               and w["status"] == "match" for w in applied)
    assert not any("not in this plan" in w["description"] for w in amended)
    assert not any(w["address"] == "/cfg/talk/assign" for w in amended)


def test_amend_and_patch_never_pass_full_apply():
    """A text guard over the two call sites, beside the behaviour test
    above: the scoped back half (`amend.py`, which `patch` runs) never
    opts in."""
    source = (Path(__file__).resolve().parents[1] / "atoo" / "amend.py").read_text()
    assert "full_apply" not in source
    source = (Path(__file__).resolve().parents[1] / "atoo" / "patch.py").read_text()
    assert "full_apply" not in source


# ======================================================================
# Talkback
# ======================================================================


@pytest.mark.parametrize("name", ["Talkback", "TALKBACK", "Talk Back", "TB", "T/B", "Talk",
                                  "Talk Mic", "FOH Talk"])
def test_talkback_names(name):
    assert facts.is_talkback_name(name)


@pytest.mark.parametrize("name", ["Tom", "Stab", "Talk box", "Talking drum", "TBone", "Kick"])
def test_not_talkback_names(name):
    assert not facts.is_talkback_name(name)


def test_a_talkback_strip_on_ch_40_assigns_ch40():
    plan = tiny(("ch", 1, "Kick"), ("ch", 40, "Talk Mic"))
    value, entry = talkback_assign(plan)
    assert value == "CH40" and entry["name"] == "Talk Mic"


def test_a_talkback_strip_recognised_by_its_input_name():
    plan = tiny(("aux", 8, "Producer"))
    plan["channels"][0]["source"]["input"] = "TB mic"
    assert talkback_assign(plan)[0] == "AUX8"


def test_no_talkback_strip_sets_the_assign_off():
    """A full apply makes the desk the plan, and this
    plan has no talkback."""
    plan = tiny(("ch", 1, "Kick"), ("ch", 40, "Crowd"))
    assert talkback_assign(plan) is None
    [talk] = [t for t in full_apply_targets(plan) if t.address == facts.TALK_ASSIGN]
    assert talk.compute_value(None) == "OFF"
    notes = dict(full_apply_notes(plan))
    assert notes["apply.talkback-assign"] == ("INFO talkback assign (Setup -> Audio) set to "
                                              "OFF: no talkback strip on ch 40 or aux 8 in "
                                              "this plan")


def test_a_talkback_strip_elsewhere_is_a_verify_warning_and_is_not_assigned():
    plan = tiny(("ch", 1, "Kick"), ("ch", 12, "Talkback"))
    assert talkback_assign(plan) is None
    # The desk's talkback cannot reach ch 12, so it is set OFF, not to it.
    assert "OFF: no talkback strip on ch 40 or aux 8" in dict(full_apply_notes(plan))[
        "apply.talkback-assign"]
    [warning] = [f for f in verify_plan(plan).findings if f.code == "talkback.unassignable"]
    assert warning.severity.value == "warning"
    assert "CH 40 or AUX 8" in warning.message and "ch 12 'Talkback'" in warning.message
    # Not moved.
    assert plan["channels"][1]["channel"] == 12


def test_a_second_talk_mic_elsewhere_is_quiet_when_one_is_on_aux_8():
    plan = tiny(("aux", 8, "Talkback"), ("ch", 12, "TB 2"))
    assert talkback_assign(plan)[0] == "AUX8"
    assert "talkback.unassignable" not in {f.code for f in verify_plan(plan).findings}


def test_audit_sp_cv014_reads_the_same_talkback_names():
    """CV014 exempts the strip apply assigns: one vocabulary."""
    from atoo import audit

    assert audit._TALKBACK_STRIPS == {"CH40": ("ch", 40), "AUX8": ("aux", 8)}
    plan = copy.deepcopy(tiny(("aux", 8, "TALKBACK")))
    state = audit.ConsoleState(values={"/cfg/talk/assign": "AUX8"})
    assert audit._diff_talkback_strip(state, plan) == []
