"""Apply writes the USR slots a plan defines.

A USR slot is the desk's own indirection: a user signal (USR 1-24) takes a
strip at a tap, a user patch (USR 25-56) takes a physical socket, and a
channel or an output is then patched to the slot. Apply writes what each slot
takes before anything that reads it; Undo puts it back; a capture records the
slots a channel or an output reads, so a captured show applied back to its own
desk changes nothing. The desks are `tests/snap_desk`'s, built from the
packaged initialized capture, and the church's frozen snapshot; the show is
the packaged Demo.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from atoo import capture, firstrun
from atoo import initialize as init
from atoo.amend import ChangeKind, plan_amendment
from atoo.apply import _build_write_targets, apply_plan, user_source_targets
from atoo.audit import ConsoleState
from atoo.snapshot import load_snapshot
from atoo.undo import load_journal, undo_from_journal
from atoo.verify_plan import verify_plan
from tests.snap_desk import PairedSnapDesk

DEMO_PLAN = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME / "plan.json"
CHURCH = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"
MODEL = "wing-compact"

# A post-fader feed of channel 1 to USB 13 through USR 3, and a user patch.
LEAD_POST = {"slot": 3, "name": "Lead post", "source": {"group": "CH", "index": 1},
             "tap": "POST", "leg": None}
PATCH_25 = {"slot": 25, "source": {"group": "LCL", "index": 5}}


def demo_with(*sources, feeds=True) -> dict:
    plan = json.loads(DEMO_PLAN.read_text(encoding="utf-8"))
    plan["user_sources"] = [copy.deepcopy(s) for s in sources]
    if feeds:
        plan["direct_outputs"] = [
            {"group": "USB", "socket": 13 + i, "source": {"group": "USR", "index": s["slot"]}}
            for i, s in enumerate(sources)]
    return plan


def test_each_slot_is_written_and_a_null_leaves_the_desks_value():
    written = {t.address: t.compute_value(None) for t in user_source_targets(
        demo_with(LEAD_POST, PATCH_25))}
    assert written == {"/io/in/USR/3/user/grp": "CH", "/io/in/USR/3/user/in": 1,
                       "/io/in/USR/3/user/tap": "POST", "/io/in/USR/3/name": "Lead post",
                       "/io/in/USR/25/user/grp": "LCL", "/io/in/USR/25/user/in": 5}


def test_a_slot_is_written_before_anything_that_reads_it():
    targets, _warnings = _build_write_targets(demo_with(LEAD_POST), True)
    order = [t.address for t in targets]
    slot = order.index("/io/in/USR/3/user/grp")
    first_patch = next(i for i, a in enumerate(order) if a.endswith("/in/conn/grp"))
    assert slot < first_patch < order.index("/io/out/USB/13/grp")


def test_a_full_apply_writes_the_slots_and_undo_puts_them_back(tmp_path):
    desk = PairedSnapDesk({leaf.address: leaf.value for leaf in init.load_capture(MODEL).leaves})
    before = {a: desk.values.get(a) for a in ("/io/in/USR/3/user/grp", "/io/in/USR/3/user/in",
                                              "/io/in/USR/3/user/tap", "/io/in/USR/3/name",
                                              "/io/in/USR/25/user/grp", "/io/in/USR/25/user/in")}
    journal = tmp_path / "apply.json"
    result = apply_plan(demo_with(LEAD_POST, PATCH_25), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model=MODEL, journal_path=str(journal))
    assert not result.mismatches
    assert (desk.values["/io/in/USR/3/user/grp"], desk.values["/io/in/USR/3/user/tap"],
            desk.values["/io/in/USR/3/name"]) == ("CH", "POST", "Lead post")
    assert desk.values["/io/in/USR/25/user/grp"] == "LCL"
    assert (desk.values["/io/out/USB/13/grp"], desk.values["/io/out/USB/14/grp"]) == ("USR", "USR")

    undo_from_journal(load_journal(str(journal)), desk, dry_run=False)
    assert {a: desk.values.get(a) for a in before} == before


def test_a_stereo_channel_on_a_usr_pair_sets_both_slots_stereo():
    plan = demo_with({"slot": 25, "source": {"group": "CRD", "index": 1}},
                     {"slot": 26, "source": {"group": "CRD", "index": 33}}, feeds=False)
    channel = plan["channels"][0]
    channel["patch"] = {"group": "USR", "sockets": [25, 26]}
    channel["source"]["stereo"] = True
    targets = {t.address: t.compute_value(None) for t in _build_write_targets(plan, True)[0]}
    assert targets["/io/in/USR/25/mode"] == targets["/io/in/USR/26/mode"] == "ST"


def test_verify_counts_an_output_as_reading_a_slot_and_warns_on_an_undefined_one():
    codes = {f.code for f in verify_plan(demo_with(LEAD_POST), console_model=MODEL).findings}
    assert "user-source.unused" not in codes and "user-source.not-written-by-apply" not in codes
    plan = demo_with(LEAD_POST)
    plan["user_sources"] = []
    [warning] = [f for f in verify_plan(plan, console_model=MODEL).warnings
                 if f.code == "patch.user-source-undefined"]
    assert warning.where == "direct_outputs[USB 13]"
    assert "USB 13 is fed from USR 3, a user signal" in warning.message


def test_a_patch_writes_a_new_slot_and_reports_a_changed_one():
    applied = demo_with(LEAD_POST, feeds=False)
    amended = copy.deepcopy(applied)
    amended["user_sources"].append(copy.deepcopy(PATCH_25))
    amended["user_sources"][0]["tap"] = "PRE"
    amendment = plan_amendment(applied, amended, [], console_model=MODEL)
    by_slot = {c.where: c for c in amendment.changes if c.kind_of_object == "USR slot"}
    assert by_slot["USR 25"].kind == ChangeKind.ADDED
    assert by_slot["USR 3"].kind == ChangeKind.MODIFIED
    assert amendment.allows("/io/in/USR/25/user/grp")
    assert not amendment.allows("/io/in/USR/3/user/tap")


# -- capture, and applying it back --------------------------------------------------


def _church_with_usr() -> ConsoleState:
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    values = dict(state.values)
    values.update({"/io/in/USR/3/user/grp": "CH", "/io/in/USR/3/user/in": 10,
                   "/io/in/USR/3/user/tap": "POST", "/io/in/USR/3/name": "Lead post",
                   "/io/out/USB/29/grp": "USR", "/io/out/USB/29/in": 3,
                   # Assigned, read by nothing: left as the desk has it.
                   "/io/in/USR/25/user/grp": "LCL", "/io/in/USR/25/user/in": 5})
    return ConsoleState(values)


def test_a_capture_records_the_slots_something_reads():
    state = _church_with_usr()
    result = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                  captured="2026-10-24", snapshot="captures/church.snap")
    assert result.plan["user_sources"] == [
        {"slot": 3, "source": {"group": "CH", "index": 10}, "tap": "POST", "leg": "L+R",
         "name": "Lead post"}]
    assert ("1 USR slot(s) a channel or an output reads, each recorded as the desk has it, "
            "so Apply puts it back: USR 3 from CH 10.") in result.notes
    assert ("USR 25 (from LCL 5) is assigned on the desk, but no channel or output reads it, "
            "so the plan leaves it as the desk has it.") in result.notes
    assert not [f for f in verify_plan(result.plan, console_model="wing-full").findings
                if "user" in f.code]


def test_a_captured_plan_with_usr_slots_applied_to_its_own_desk_changes_nothing():
    from tests.test_capture import _church_desk

    state = _church_with_usr()
    result = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                  captured="2026-10-24", snapshot="captures/church.snap")
    preview = apply_plan(result.plan, _church_desk(state), dry_run=True, full_apply=True,
                         initialize=True, init_model="wing-full")
    changing = [(w.address, w.prior_value, w.intended_value) for w in preview.writes
                if w.status == "dry_run" and w.would_change]
    assert changing == []
    compared = {w.address for w in preview.writes}
    assert {"/io/in/USR/3/user/grp", "/io/in/USR/3/user/in", "/io/in/USR/3/user/tap",
            "/io/in/USR/3/user/lr", "/io/in/USR/3/name", "/io/out/USB/29/grp"} <= compared
