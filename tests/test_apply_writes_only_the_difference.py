"""A full build writes only the addresses its preview said would change.

On a WING Compact, after a Hi Hat was added to the Demo's input list and
the plan rebuilt, the preview read the desk and said "12 will change, 1755
already match", and the write then seemed to go through the whole board.
The write already decides each address for itself: it reads the address just
before sending it and sends nothing the desk already holds. What looked like
a rewrite was the stretch's count, which counted every setting it looked at
as though it were a write, and a stereo pair's second gain, which the plan
did not name and the reset to initialized wrote and the plan then wrote
again (`tests/test_apply_stereo_pair_gain.py`).

What is pinned here, on a simulated desk with the packaged Demo (a desk
that links a stereo pair's gains, as a WING does): the number written
is the number the preview said would change; exactly those addresses are
written and each is read back; the journal holds them as written and the
rest as already right; Undo reverses exactly them; a second preview finds
nothing; and a desk that moved between the preview and the write still ends
as the plan says, because the write decides on a fresh read. Nothing here
reads `examples/`.
"""

from __future__ import annotations

import json

import pytest

from atoo import initialize as init
from atoo.apply import _values_equal, apply_plan
from atoo.undo import REVERSED, load_journal, undo_from_journal
from tests.snap_desk import PairedSnapDesk
from tests.test_apply_stereo_pair_gain import (demo_plan, fresh_desk, full_apply,
                                               with_hi_hat, would_change, written)


class LoggedDesk(PairedSnapDesk):
    """Every request the desk receives, in order: ("get"|"set", address)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ops: list[tuple[str, str]] = []

    def get(self, address):
        self.ops.append(("get", address))
        return super().get(address)

    def set_node(self, node, command):
        self.ops.append(("set", f"{node}/{command.partition('=')[0]}"))
        return super().set_node(node, command)

    def set_param(self, address, value, value_type="f"):
        self.ops.append(("set", address))
        return super().set_param(address, value, value_type)


def applied_demo():
    """The Demo applied to a fresh desk, and the plan rebuilt with a Hi Hat."""
    desk = fresh_desk(LoggedDesk)
    assert not full_apply(demo_plan(), desk, dry_run=False).mismatches
    return desk, with_hi_hat(demo_plan())


def test_the_write_sends_exactly_the_addresses_the_preview_said_would_change(tmp_path):
    desk, rebuilt = applied_demo()
    preview = full_apply(rebuilt, desk, dry_run=True)
    expected = would_change(preview)
    assert 0 < len(expected) < len(preview.writes) // 10

    desk.ops.clear()
    result = full_apply(rebuilt, desk, dry_run=False, journal_path=str(tmp_path / "j.json"))
    assert not result.mismatches
    assert written(result) == expected
    assert len(result.changed) == len(expected)

    sent = [address for kind, address in desk.ops if kind == "set"]
    assert sorted(sent) == sorted(expected), "nothing is sent that the preview did not list"
    assert len(sent) == len(set(sent)), "and none twice"
    # Every write is read back, straight after it.
    for index, (kind, address) in enumerate(desk.ops):
        if kind == "set":
            assert desk.ops[index + 1] == ("get", address), address
    assert f"{len(expected)} written" in result.summary()


def test_the_journal_holds_the_writes_as_written_and_the_rest_as_already_right(tmp_path):
    desk, rebuilt = applied_demo()
    expected = would_change(full_apply(rebuilt, desk, dry_run=True))
    journal = tmp_path / "j.json"
    full_apply(rebuilt, desk, dry_run=False, journal_path=str(journal))

    rows = json.loads(journal.read_text())["writes"]
    by_status = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row)
    assert {r["address"] for r in by_status["match"]} == expected
    # What was not written holds what the plan says: proof, not a gap.
    for row in by_status["skipped_no_change"]:
        assert _values_equal(row["value_type"], row["prior_value"], row["intended_value"],
                             row["address"]), row["address"]
    assert len(by_status["skipped_no_change"]) > 10 * len(expected)
    # And every row that was sent changed something, or was forced to be sent
    # by the selector it sits under, which the desk re-reads when it changes.
    for row in by_status["match"]:
        assert "forced_by" in row or not _values_equal(
            row["value_type"], row["prior_value"], row["intended_value"], row["address"]), row


def test_undo_reverses_exactly_the_addresses_that_were_written(tmp_path):
    desk, rebuilt = applied_demo()
    expected = would_change(full_apply(rebuilt, desk, dry_run=True))
    before = dict(desk.values)
    journal = tmp_path / "j.json"
    full_apply(rebuilt, desk, dry_run=False, journal_path=str(journal))

    preview = undo_from_journal(load_journal(str(journal)), desk, dry_run=True)
    assert {s.address for s in preview.steps} == expected
    desk.ops.clear()
    undone = undo_from_journal(load_journal(str(journal)), desk, dry_run=False,
                               journal_path=str(tmp_path / "undo.json"))
    assert {s.address for s in undone.of(REVERSED)} == expected
    assert sorted(a for kind, a in desk.ops if kind == "set") == sorted(expected)
    assert undone.never_written > 0, "the rows that were not written are left out"
    assert {a: v for a, v in desk.values.items() if a in before} == before


def test_a_second_preview_after_the_write_finds_nothing_and_a_second_write_sends_nothing():
    desk, rebuilt = applied_demo()
    full_apply(rebuilt, desk, dry_run=False)
    assert would_change(full_apply(rebuilt, desk, dry_run=True)) == set()
    desk.ops.clear()
    again = full_apply(rebuilt, desk, dry_run=False)
    assert again.changed == []
    assert not [op for op in desk.ops if op[0] == "set"]


def test_a_desk_that_moved_after_the_preview_still_ends_as_the_plan_says():
    """The write decides on a fresh read of each address, not on the
    preview's: a value moved since is written back, one set right since is
    left alone, and the desk ends as the plan says either way."""
    desk, rebuilt = applied_demo()
    preview = full_apply(rebuilt, desk, dry_run=True)
    expected = would_change(preview)
    intended = {w.address: w.intended_value for w in preview.writes}

    moved = "/ch/1/fdr"
    assert moved not in expected
    desk.values[moved] = -33.0
    set_right = sorted(expected)[0]
    desk.values[set_right] = intended[set_right]

    result = full_apply(rebuilt, desk, dry_run=False)
    assert not result.mismatches
    assert written(result) == (expected - {set_right}) | {moved}
    assert desk.values[moved] == pytest.approx(intended[moved])
    assert would_change(full_apply(rebuilt, desk, dry_run=True)) == set()


def test_the_reset_to_initialized_still_comes_first_and_writes_only_what_differs():
    desk = fresh_desk(LoggedDesk)
    old = {"/ch/30/name": "OLD SHOW", "/ch/31/name": "Old"}
    desk.values.update(old)
    preview = full_apply(demo_plan(), desk, dry_run=True)
    reset = [w for w in preview.writes if w.description.startswith(init.DESCRIPTION)]
    assert {w.address for w in reset if w.would_change} == set(old)

    result = full_apply(demo_plan(), desk, dry_run=False)
    wrote_reset = {w.address for w in result.writes
                   if w.description.startswith(init.DESCRIPTION) and w.status == "match"}
    assert wrote_reset == set(old)
    first_plan_write = next(i for i, w in enumerate(result.writes)
                            if not w.description.startswith(init.DESCRIPTION))
    assert all(w.description.startswith(init.DESCRIPTION)
               for w in result.writes[:first_plan_write])
