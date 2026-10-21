"""What a full apply's reset to initialized does to the output patches.

The initialized capture holds every output group, so a full apply with the
reset on disconnects the stage boxes', cards', USB's and the other groups'
unused outputs without being told how many sockets each has, and `undo`
puts all of it back from the journal, however many addresses that is.
"""

from __future__ import annotations

from atoo import initialize as init
from atoo.apply import apply_plan
from atoo.undo import load_journal, undo_from_journal
from tests.test_full_apply import tiny
from tests.test_initialize import desk_with, reset_records

# Every group an apply can patch an output to, but the desk's own panel.
STAGE_AND_CARD_GROUPS = ("A", "B", "C", "SC", "USB", "CRD", "MOD", "AES", "REC", "AUX")


def _old_show() -> dict:
    changes = {}
    for group in STAGE_AND_CARD_GROUPS:
        for n in range(1, 9):
            changes[f"/io/out/{group}/{n}/grp"] = "BUS"
            changes[f"/io/out/{group}/{n}/in"] = 5
    for n in range(1, 41):
        changes[f"/ch/{n}/fdr"] = -7.0
        changes[f"/ch/{n}/name"] = f"Old {n}"
    for n in range(1, 17):
        changes[f"/io/in/A/{n}/g"] = 22.5
        changes[f"/io/in/A/{n}/vph"] = 1
    return changes


def test_the_reset_disconnects_every_output_group_without_a_count():
    desk = desk_with(_old_show())
    apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
               initialize=True, init_model="wing-compact")
    for group in STAGE_AND_CARD_GROUPS:
        for n in (1, 2):
            assert desk.values[f"/io/out/{group}/{n}/grp"] == "OFF"


def test_with_the_reset_off_those_outputs_are_left_alone():
    desk = desk_with(_old_show())
    apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
               initialize=False, init_model="wing-compact")
    assert desk.values["/io/out/A/1/grp"] == "BUS"


def test_a_reset_of_hundreds_of_addresses_is_undone_whole(tmp_path):
    changes = _old_show()
    desk = desk_with(changes)
    before = dict(desk.values)
    journal = tmp_path / "apply.json"
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, journal_path=str(journal),
                        full_apply=True, initialize=True, init_model="wing-compact")
    reset = reset_records(result)
    assert len(reset) > 200
    assert all(r.status == "match" for r in reset)
    undo_from_journal(load_journal(str(journal)), desk, dry_run=False)
    assert {a: desk.values[a] for a in changes} == {a: before[a] for a in changes}
    assert desk.values == before


def test_the_preview_of_the_reset_writes_nothing_and_counts_what_it_would():
    desk = desk_with(_old_show())
    before = dict(desk.values)
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=True, full_apply=True,
                        initialize=True, init_model="wing-compact")
    assert desk.values == before
    assert [w for w in result.warnings if w.startswith("INFO reset to initialized")]
    assert init.DESCRIPTION in " ".join(r.description for r in result.writes)
