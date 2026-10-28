"""An insert and an edit or a drop in one change.

"Insert HiHat after Snare and put HPF 100 on Rack Tom" is one instruction:
the insert renumbers the strips after Snare, an edit of a strip it moves rides
with the move, an edit of the channel it adds is set on that channel, and a
drop, a move or a renumber beside it is carried out too. Every strip is
written once, and Undo puts every address back, on the Compact, the Full and
the Rack.

The desk is the frozen applied show (`test_amend.applied_plan`, 19 channels on
ch 1-19); HiHat is inserted after Snare, on ch 3 (`test_patch_insert`).
"""

from __future__ import annotations

import json

import pytest

from atoo import amend, patch, undo
from atoo.amend import ChangeKind
from test_amend import DeskConsole, applied_plan, full_console_state
from test_patch_insert import INSERT, _change, _desk, _hihat

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _modify(obj: str, name: str, fields: dict, said: str = "as typed") -> dict:
    return {"object": obj, "name": name, "change": said, "fields": fields}


def _review(model: str, *, modify=(), drop=()):
    change_set = _change(_hihat())
    change_set["modify"] = list(modify)
    change_set["drop"]["channels"] = list(drop)
    amendment, merge = patch.plan_patch(applied_plan(), change_set, _desk(), text=INSERT,
                                        console_model=model)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    return amendment, merge, amend.amendment_targets(amendment)


def _written_once(targets) -> dict:
    addresses = [t.address for t in targets.to_write if not t.address.endswith("/mute")]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    return {t.address: t.compute_value("") for t in targets.to_write}


def _apply_and_undo(amendment, tmp_path) -> tuple[dict, dict]:
    console = DeskConsole(full_console_state())
    before = dict(console.state)
    journal = tmp_path / "change.journal.json"
    result = amend.apply_amendment(amendment, console, dry_run=False, journal_path=str(journal))
    assert not result.aborted
    after = dict(console.state)
    undone = undo.undo_from_journal(json.loads(journal.read_text()), console, dry_run=False)
    assert not undone.aborted
    assert {a for a in set(before) | set(console.state)
            if console.state.get(a) != before.get(a)} == set()
    return before, after


@pytest.mark.parametrize("model", MODELS)
def test_an_edit_of_a_strip_the_insert_moves_rides_with_it(model, tmp_path):
    amendment, _m, targets = _review(model, modify=[_modify(
        "channel", "Tom1", {"processing.hpf_hz": 100}, "HPF 100 on Rack Tom")])
    writes = _written_once(targets)
    assert writes["/ch/5/flt/lcf"] == 100.0         # Tom1, moved from ch 4 to ch 5
    _before, after = _apply_and_undo(amendment, tmp_path)
    assert after["/ch/5/name"][0] == "Tom1" and after["/ch/5/flt/lcf"][0] == 100.0


@pytest.mark.parametrize("model", MODELS)
def test_an_edit_of_the_channel_the_change_inserts_is_set_on_it(model, tmp_path):
    amendment, merge, targets = _review(model, modify=[_modify(
        "channel", "HiHat", {"processing.hpf_hz": 200}, "HPF 200 on it")])
    assert ("channel 'HiHat' is added by this change; HPF 200 on it (processing.hpf_hz) is set "
            "on it and written with it") in merge.infos
    writes = _written_once(targets)
    assert writes["/ch/3/flt/lcf"] == 200.0
    _before, after = _apply_and_undo(amendment, tmp_path)
    assert after["/ch/3/name"][0] == "HiHat"


@pytest.mark.parametrize("model", MODELS)
def test_a_drop_beside_the_insert(model, tmp_path):
    amendment, _m, targets = _review(model, drop=["Keys"])
    assert [c for c in amendment.changes if c.kind is ChangeKind.RELEASED and c.where == "'Keys'"]
    _written_once(targets)
    _before, after = _apply_and_undo(amendment, tmp_path)
    assert after["/ch/3/name"][0] == "HiHat" and after["/ch/9/name"][0] == "EG 1"


@pytest.mark.parametrize("model", MODELS)
def test_a_move_beside_the_insert(model, tmp_path):
    amendment, _m, targets = _review(model, modify=[_modify("channel", "Kick", {"channel": 22})])
    _written_once(targets)
    assert _strip_of(amendment, "Kick") == "ch:22"
    _before, after = _apply_and_undo(amendment, tmp_path)
    assert after["/ch/22/name"][0] == "Kick" and after["/ch/1/name"][0] == ""


@pytest.mark.parametrize("model", MODELS)
def test_a_bus_renumbered_beside_the_insert_is_written_once(model, tmp_path):
    """The strips the insert moves lose their send into bus 5 twice over --
    once as the strip's old occupant's, once as the renumbered bus's: one
    write each."""
    amendment, _m, targets = _review(model, modify=[_modify("bus", "Drums", {"index": 14})])
    writes = _written_once(targets)
    assert writes["/ch/4/send/5/on"] == 0 and writes["/bus/14/name"] == "Drums"
    _apply_and_undo(amendment, tmp_path)


@pytest.mark.parametrize("model", MODELS)
def test_a_rename_of_a_strip_the_insert_moves(model, tmp_path):
    amendment, _m, targets = _review(model, modify=[_modify("channel", "Tom1",
                                                            {"name": "Rack Tom"})])
    writes = _written_once(targets)
    assert writes["/ch/5/name"] == "Rack Tom"
    _apply_and_undo(amendment, tmp_path)


def test_an_edit_the_added_channel_cannot_carry_is_refused_saying_why():
    change_set = _change(_hihat())
    change_set["modify"] = [_modify("channel", "HiHat", {"colour": "Red"})]
    amendment, merge = patch.plan_patch(applied_plan(), change_set, _desk(), text=INSERT,
                                        console_model="wing-compact")
    [refused] = merge.refused
    assert refused.reason.startswith("the change adds it and edits it (as typed), and")
    assert "colour" in refused.reason


def _strip_of(amendment, name: str) -> str:
    channel = next(c for c in amendment.effective_plan["channels"] if c["name"] == name)
    return f"{channel.get('bank', 'ch')}:{channel['channel']}"
