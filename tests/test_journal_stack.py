"""The bundle's journal stack -- one time-ordered stack, not one file per kind.

The file starts with the **hazard**, because the fix only makes sense next
to it: `undo`'s guard is per address, it reverses an address wherever the
desk still holds what the journal says we wrote, and it cannot see a
*later* journal. Apply writes ch 1-2; a later amend adds ch 21 and touches
neither of them; every address in the apply journal still reads exactly
what apply put there, so the guard passes on all of them and the whole
show comes off the desk under the amend.

`test_the_per_address_guard_cannot_see_a_later_amend` reproduces that at
the engine level and still passes after the fix -- the guard was never
wrong, it was answering a different question. The refusal that stops it
is the stack's, and is tested under "The stale-pointer refusal" below.

No test here touches a real console (`test_apply.FakeConsole` is the
established fake) and none reads a bundle under `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import journal_stack
from atoo.undo import REVERSED, undo_from_journal
from tests.test_undo import console_holding, journal, row


def write_journal(path: Path, *rows, **kwargs) -> Path:
    path.write_text(json.dumps(journal(*rows, **kwargs)))
    return path


# ---------------------------------------------------------------------------
# The hazard
# ---------------------------------------------------------------------------

def test_the_per_address_guard_cannot_see_a_later_amend():
    """Reproduction of the hazard 1, at the engine level.

    The apply wrote ch 1 and ch 2. An amend then added ch 21 and touched
    nothing else. Every address the apply journal names still holds what
    the apply put there -- so the per-address guard, correctly, reverses
    all of them, and the amend is left sitting on a desk with no show
    under it. Nothing at this level can stop that, which is the whole
    argument for a stack: only something that can see the LATER journal
    can refuse.
    """
    desk = console_holding(
        __ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"),
        __ch__21__name=("Trumpet", "s"))
    result = undo_from_journal(
        journal(row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare")),
        desk, dry_run=False)

    assert [s.verdict for s in result.steps] == [REVERSED, REVERSED]
    assert desk.state["/ch/1/name"] == ("", "s")
    # ...and the amend is still there, on a desk with nothing under it.
    assert desk.state["/ch/21/name"] == ("Trumpet", "s")


# ---------------------------------------------------------------------------
# The stack: ordering, kinds, and what the top is
# ---------------------------------------------------------------------------

def test_entries_are_time_ordered_across_kinds(tmp_path):
    """One stack, not one file per kind: an apply and two amends land in
    the order they happened, and the second amend does not overwrite the
    first."""
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))
    journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/22/name", "", "Trombone")))

    got = journal_stack.entries(tmp_path)
    assert [e.kind for e in got] == ["apply", "amend", "amend"]
    assert journal_stack.top(tmp_path).id == got[-1].id
    # The first amend's journal is still on disk in full, which is the
    # thing one-file-per-kind could not do.
    first_amend = json.loads(got[1].path.read_text())
    assert [w["address"] for w in first_amend["writes"]] == ["/ch/21/name"]


def test_an_aborted_runs_journal_goes_on_the_stack_too(tmp_path):
    """`undo.py`'s docstring: a partial journal "is the most important one
    to be able to reverse -- it is the one nobody planned for"."""
    partial = write_journal(tmp_path / "apply-journal.json",
                            row("/ch/1/name", "", "Kick"))
    payload = json.loads(partial.read_text())
    payload["aborted"] = True
    partial.write_text(json.dumps(payload))

    entry = journal_stack.record(tmp_path, "apply", partial)
    assert journal_stack.top(tmp_path).id == entry.id
    assert json.loads(entry.path.read_text())["aborted"] is True


def test_an_undo_pops_the_stack_rather_than_pushing_a_position(tmp_path):
    """The maintainer's call: a second press of undo "steps back two". The undo's
    own journal is kept -- it carries the refusals and exists nowhere else
    -- but it is never the pop target, so after undoing the amend the top
    is the apply."""
    apply_entry = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    amend_entry = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))
    assert journal_stack.top(tmp_path).id == amend_entry.id

    journal_stack.record(tmp_path, "undo", write_journal(
        tmp_path / "amend-journal.undo.json", row("/ch/21/name", "Trumpet", "")),
        undo_of=amend_entry.id)

    assert journal_stack.top(tmp_path).id == apply_entry.id
    # Kept, and readable, but not a position.
    assert [e.kind for e in journal_stack.entries(tmp_path)] == ["apply", "amend", "undo"]
    listed = {e.id: e for e in journal_stack.listing(tmp_path)}
    assert listed[amend_entry.id].undone_by is not None
    assert listed[amend_entry.id].is_top is False


def test_undoing_the_undo_puts_the_entry_back_on_the_stack(tmp_path):
    """The redo is `atoo undo <the .undo.json>`, and it leaves the
    stack where it was before the undo -- the amend is on the desk again,
    so it is a position again."""
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    amend_entry = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))
    undo_entry = journal_stack.record(tmp_path, "undo", write_journal(
        tmp_path / "amend-journal.undo.json", row("/ch/21/name", "Trumpet", "")),
        undo_of=amend_entry.id)
    journal_stack.record(tmp_path, "undo", write_journal(
        tmp_path / "redo.undo.json", row("/ch/21/name", "", "Trumpet")),
        undo_of=undo_entry.id)

    assert journal_stack.top(tmp_path).id == amend_entry.id


def test_an_empty_bundle_has_no_top(tmp_path):
    assert journal_stack.entries(tmp_path) == []
    assert journal_stack.top(tmp_path) is None


# ---------------------------------------------------------------------------
# Finding an entry from a path somebody typed
# ---------------------------------------------------------------------------

def test_the_legacy_pointer_still_names_its_entry(tmp_path):
    """A journal recorded from outside the stack -- a `--journal PATH` --
    resolves to the stack entry it copies, so the staleness check can be
    made about it."""
    pointer = write_journal(tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick"))
    entry = journal_stack.record(tmp_path, "apply", pointer)

    assert pointer.is_file()
    found = journal_stack.find(tmp_path, pointer)
    assert found is not None and found.id == entry.id
    # Same run, byte for byte -- the mirror is not a summary of the entry.
    assert json.loads(pointer.read_text()) == json.loads(entry.path.read_text())


def test_a_journal_from_outside_the_stack_resolves_to_nothing(tmp_path):
    """A journal that was never recorded here is not silently matched to
    an entry it merely resembles -- there is nothing to be stale about."""
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    stray = write_journal(tmp_path / "somewhere-else.json", row("/ch/1/name", "", "Kick"))
    assert journal_stack.find(tmp_path, stray) is None


def test_above_names_what_is_newer_than_an_entry(tmp_path):
    apply_entry = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    amend_entry = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))

    assert [e.id for e in journal_stack.above(tmp_path, apply_entry)] == [amend_entry.id]
    assert journal_stack.above(tmp_path, amend_entry) == []


# ---------------------------------------------------------------------------
# The listing the Apply screen will draw
# ---------------------------------------------------------------------------

def test_the_listing_gives_timestamp_kind_summary_and_mismatch_count(tmp_path):
    """Four things per row, newest first, and no caller has to parse a
    journal to get them."""
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json",
        row("/ch/1/name", "", "Kick"),
        row("/ch/2/name", "", "Snare", status="mismatch", readback="Snar")))

    (only,) = journal_stack.listing(tmp_path)
    assert only.kind == "apply"
    assert only.timestamp.startswith("2026-")
    assert only.summary == "APPLIED: 2 address(es) evaluated, 2 written, 1 mismatch(es)."
    assert only.mismatches == 1
    assert only.is_top is True


def test_an_undo_row_is_summarised_as_an_undo(tmp_path):
    """"APPLIED: ..." would be a lie on a row whose whole content is
    reversals and refusals."""
    entry = journal_stack.record(tmp_path, "undo", write_journal(
        tmp_path / "apply-journal.undo.json",
        row("/ch/1/name", "Kick", ""),
        row("/ch/2/name", None, None, status="refused_changed_since")))
    assert entry.summary == "UNDONE: 1 reversed, 1 refused (changed since)."
    assert entry.kind == "undo"


def test_the_listing_reads_the_index_not_every_journal(tmp_path, monkeypatch):
    """The Apply screen draws one row per entry and must not pay for
    parsing every record of every journal to do it. Mutation-checked: make
    `listing` parse each entry file and this fails.

    The journals are made unreadable after recording, which is exactly
    what a listing that re-parses them would trip over."""
    for _ in range(3):
        journal_stack.record(tmp_path, "apply", write_journal(
            tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    for entry in journal_stack.entries(tmp_path):
        entry.path.write_text("this is not JSON")

    rows = journal_stack.listing(tmp_path)
    assert len(rows) == 3
    assert all(r.summary.startswith("APPLIED: ") for r in rows)


def test_a_journal_the_index_never_saw_is_still_listed(tmp_path):
    """Self-healing: a stack directory copied without its index, or an
    entry written by a future version, is read rather than ignored. A
    journal on disk is evidence of a desk write and must not vanish from
    the listing because a cache is stale."""
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    (journal_stack.stack_dir(tmp_path) / journal_stack.INDEX).unlink()

    rows = journal_stack.listing(tmp_path)
    assert len(rows) == 1 and rows[0].kind == "apply"
    assert rows[0].summary.startswith("APPLIED: ")


def test_an_index_row_whose_file_is_gone_is_dropped(tmp_path):
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    keep = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))
    journal_stack.entries(tmp_path)[0].path.unlink()

    assert [e.id for e in journal_stack.entries(tmp_path)] == [keep.id]


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

def test_the_stack_keeps_the_newest_five_and_prunes_the_oldest(tmp_path):
    """The maintainer, 2026-10-02: journals/ is pruned to five entries. Seven
    applies with no desk: the newest five are kept, and the two oldest
    files are gone (the deeper cases are in tests/test_journal_prune.py)."""
    ids = [journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", f"Take {n}"))).id
        for n in range(7)]

    assert [e.id for e in journal_stack.entries(tmp_path)] == ids[2:]
    assert not (journal_stack.stack_dir(tmp_path) / ids[0]).exists()


def test_the_limit_is_five_and_shared_with_builds_and_logs():
    """One named constant, `prune.KEEP`, for all three folders."""
    from atoo import prune
    assert prune.KEEP == 5
    assert journal_stack.keep_limit() == prune.KEEP


def test_the_index_is_pruned_with_the_files(tmp_path, monkeypatch):
    from atoo import prune
    monkeypatch.setattr(prune, "KEEP", 2)
    for n in range(4):
        journal_stack.record(tmp_path, "apply", write_journal(
            tmp_path / "apply-journal.json", row("/ch/1/name", "", f"Take {n}")))
    index = json.loads((journal_stack.stack_dir(tmp_path) / journal_stack.INDEX).read_text())
    assert len(index["entries"]) == 2


def test_two_journals_recorded_in_the_same_microsecond_do_not_collide(tmp_path, monkeypatch):
    """Two entries, two files, whatever the clock says. A stack that
    silently overwrote one would be the bug it exists to fix."""
    monkeypatch.setattr(journal_stack, "_now", lambda: journal_stack.datetime(
        2026, 9, 24, 5, 40, 16, tzinfo=journal_stack.timezone.utc))
    first = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    second = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/2/name", "", "Snare")))

    assert first.id != second.id
    assert len(journal_stack.entries(tmp_path)) == 2


# ---------------------------------------------------------------------------
# The stale-pointer refusal -- the fix for the hazard at the top of this file
# ---------------------------------------------------------------------------

def bundle_with_apply_then_amend(tmp_path):
    """A bundle whose stack holds an apply (ch 1, ch 2) and, above it, an
    amend that added ch 21 and touched nothing else. Built here rather
    than taken from `examples/`, which is a show file, not a fixture."""
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json",
        row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare")))
    journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))
    return tmp_path


def desk_after_both():
    return console_holding(
        __ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"),
        __ch__21__name=("Trumpet", "s"))


def run_cli(monkeypatch, desk, argv):
    from atoo import cli

    if desk is not None:
        desk.close = lambda: None
        monkeypatch.setattr(cli, "_open_console", lambda args: desk)
    return cli.main(argv)


def test_undoing_an_apply_out_from_under_a_later_amend_is_refused(
        tmp_path, monkeypatch, capsys):
    """**The fix.** The same command that, before #252, reversed the whole
    show out from under the amend (exit 0, no warning, no refusal) now
    refuses and names what is above it.

    Mutation-checked twice: drop the `top_entry.id != source_entry.id`
    comparison in `cli.undo_cmd` and this fails, and so does
    `test_the_refusal_names_what_is_above_it`; make `journal_stack.find`
    return None and this fails too."""
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()

    code = run_cli(monkeypatch, desk, [
        "undo", str(directory / "apply-journal.json"), "--console", "198.51.100.1", "--confirm"])

    assert code == 1
    # The desk first: nothing was written, which is the assertion that
    # must fail if the guard is removed.
    assert desk.state["/ch/1/name"] == ("Kick", "s")
    assert desk.state["/ch/2/name"] == ("Snare", "s")
    err = capsys.readouterr().err
    assert "not the newest entry" in err


def test_the_refusal_names_what_is_above_it(tmp_path, monkeypatch, capsys):
    """A refusal that does not say what is in the way leaves the operator
    exactly where they were."""
    directory = bundle_with_apply_then_amend(tmp_path)
    run_cli(monkeypatch, desk_after_both(), [
        "undo", str(directory / "apply-journal.json"), "--console", "198.51.100.1", "--confirm"])

    err = capsys.readouterr().err
    assert "1 later write(s) are still on the desk" in err
    assert "amend" in err
    assert "--out-of-order" in err


def test_a_refusal_happens_before_the_console_is_opened(tmp_path, monkeypatch, capsys):
    """The guard is made from files alone. An operator who is told no
    should be told before the command starts waiting on a desk."""
    from atoo import cli

    directory = bundle_with_apply_then_amend(tmp_path)
    opened = []
    monkeypatch.setattr(cli, "_open_console",
                        lambda args: opened.append(args) or desk_after_both())
    code = cli.main(["undo", str(directory / "apply-journal.json"),
                     "--console", "198.51.100.1", "--confirm"])
    assert code == 1 and opened == []


def test_out_of_order_proceeds_and_says_so(tmp_path, monkeypatch, capsys):
    """The override exists because "never" is not a thing this tool gets
    to say about somebody's own desk -- but it is loud, and it names what
    is still on the console."""
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()
    code = run_cli(monkeypatch, desk, [
        "undo", str(directory / "apply-journal.json"), "--console", "198.51.100.1",
        "--confirm", "--out-of-order"])

    assert code == 0
    assert desk.state["/ch/1/name"] == ("", "s")
    assert "still on the desk" in capsys.readouterr().err


def test_the_newest_entry_is_not_refused(tmp_path, monkeypatch, capsys):
    """The guard fires on staleness, not on the mere existence of a
    stack: naming the top explicitly works exactly as it always did.

    Mutation-checked: make the comparison in `cli.undo_cmd` refuse
    whenever an entry is found and this fails."""
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()
    code = run_cli(monkeypatch, desk, [
        "undo", str(directory / "amend-journal.json"), "--console", "198.51.100.1", "--confirm"])

    assert code == 0, capsys.readouterr().err
    assert desk.state["/ch/21/name"] == ("", "s")


def bundle_with_legacy_apply_then_stacked_amend(tmp_path):
    """A journal that is not on the stack -- no `stack_entry` block: one
    copied in from elsewhere, or written before the bundle had a stack --
    sitting beside a stack whose only entry is an amend."""
    write_journal(tmp_path / "apply-journal.json",
                  row("/ch/1/name", "", "Kick"), row("/ch/2/name", "", "Snare"))
    journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")))
    return tmp_path


def test_a_journal_from_before_the_stack_is_refused_under_a_stacked_amend(
        tmp_path, monkeypatch, capsys):
    """Found in review. `find` cannot place a journal with no
    `stack_entry`, so the staleness check never ran on one, and this
    exited 0 having reversed the apply out from under the amend -- #252's
    hazard, intact. A journal that is
    not on the stack predates it (or came from elsewhere), so everything
    standing on the stack is above it.

    Mutation-checked: make `stale` False for an unplaced journal in
    `cli.undo_cmd` and the desk assertion below fails."""
    directory = bundle_with_legacy_apply_then_stacked_amend(tmp_path)
    desk = desk_after_both()
    code = run_cli(monkeypatch, desk, [
        "undo", str(directory / "apply-journal.json"), "--console", "198.51.100.1", "--confirm"])

    assert desk.state["/ch/1/name"] == ("Kick", "s"), "the apply came off under the amend"
    assert code == 1
    err = capsys.readouterr().err
    assert "not on the journal stack" in err
    assert "1 later write(s) are still on the desk" in err
    assert "amend" in err


def test_a_journal_from_before_the_stack_still_undoes_when_nothing_stands_on_it(
        tmp_path, monkeypatch, capsys):
    """The absent case: a stack whose only entry has been reversed leaves
    nothing above the old journal, and the old invocation must keep
    working exactly as it always did."""
    directory = bundle_with_legacy_apply_then_stacked_amend(tmp_path)
    desk = desk_after_both()
    assert run_cli(monkeypatch, desk, [
        "undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"]) == 0
    assert desk.state["/ch/21/name"] == ("", "s")      # the amend popped
    capsys.readouterr()

    code = run_cli(monkeypatch, desk, [
        "undo", str(directory / "apply-journal.json"), "--console", "198.51.100.1", "--confirm"])
    assert code == 0, capsys.readouterr().err
    assert desk.state["/ch/1/name"] == ("", "s")


def test_out_of_order_reaches_under_the_stack_for_an_old_journal_too(
        tmp_path, monkeypatch, capsys):
    directory = bundle_with_legacy_apply_then_stacked_amend(tmp_path)
    desk = desk_after_both()
    code = run_cli(monkeypatch, desk, [
        "undo", str(directory / "apply-journal.json"), "--console", "198.51.100.1",
        "--confirm", "--out-of-order"])
    assert code == 0
    assert desk.state["/ch/1/name"] == ("", "s")
    assert "still on the desk" in capsys.readouterr().err


def test_a_bundle_from_before_the_stack_behaves_exactly_as_it_did(
        tmp_path, monkeypatch, capsys):
    """A journal named by path in a directory with no `journals/` (a
    `<plan>.apply-journal.json`, or `docs/user/demo/undo-demo/`): nothing to be
    stale about, no refusal, and the undo journal lands beside it. A
    guard keyed on "is there a bundle here" would have broken it."""
    write_journal(tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick"))
    desk = console_holding(__ch__1__name=("Kick", "s"))
    code = run_cli(monkeypatch, desk, [
        "undo", str(tmp_path / "apply-journal.json"), "--console", "198.51.100.1", "--confirm"])

    assert code == 0
    assert desk.state["/ch/1/name"] == ("", "s")
    assert (tmp_path / "apply-journal.undo.json").is_file()
    # And no stack was conjured up around a journal that is not in one.
    assert not journal_stack.stack_dir(tmp_path).exists()


# ---------------------------------------------------------------------------
# `undo --show DIR`: popping the stack
# ---------------------------------------------------------------------------

def test_undo_with_no_journal_pops_the_top_of_the_stack(tmp_path, monkeypatch, capsys):
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()
    code = run_cli(monkeypatch, desk, [
        "undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"])

    assert code == 0, capsys.readouterr().err
    # The amend came off; the apply is untouched.
    assert desk.state["/ch/21/name"] == ("", "s")
    assert desk.state["/ch/1/name"] == ("Kick", "s")


def test_a_second_undo_steps_back_two_rather_than_redoing(tmp_path, monkeypatch, capsys):
    """The maintainer's call, in his words: "steps back two". The second press
    reverses the apply, not the undo.

    Mutation-checked: make `journal_stack._live` push undo entries like
    any other kind and this fails -- the second undo reverses the undo
    (a redo) and ch 21 comes back."""
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()
    argv = ["undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"]
    assert run_cli(monkeypatch, desk, argv) == 0, capsys.readouterr().err
    assert run_cli(monkeypatch, desk, argv) == 0, capsys.readouterr().err

    assert desk.state["/ch/21/name"] == ("", "s")
    assert desk.state["/ch/1/name"] == ("", "s")
    assert desk.state["/ch/2/name"] == ("", "s")


def test_the_undos_own_journal_goes_on_the_stack_and_pops_its_source(
        tmp_path, monkeypatch, capsys):
    """FR-X.3 gets no exception -- an undo is a set of writes and is
    journalled. The file is kept because it carries the refusals, which
    exist in no other file, and it pops rather than pushes."""
    directory = bundle_with_apply_then_amend(tmp_path)
    run_cli(monkeypatch, desk_after_both(), [
        "undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"])

    kinds = [e.kind for e in journal_stack.entries(directory)]
    assert kinds == ["apply", "amend", "undo"]
    assert journal_stack.top(directory).kind == "apply"
    # And it went into the stack directory, not beside the entry it
    # reversed under a name the ordering scheme cannot read.
    undo_entry = journal_stack.entries(directory)[-1]
    assert undo_entry.path.parent == journal_stack.stack_dir(directory)
    assert undo_entry.undo_of == journal_stack.entries(directory)[1].id
    # And it is named by the stack's own scheme, not after the entry it
    # reversed: the filename IS the ordering, so an entry called
    # `<the amend's id>.undo.json` would sort in the middle of the stack
    # rather than at the end of it.
    assert journal_stack.parse_entry_name(undo_entry.id)["kind"] == "undo"
    assert undo_entry.id > journal_stack.entries(directory)[1].id


def test_undoing_the_undo_journal_is_still_the_redo(tmp_path, monkeypatch, capsys):
    """The CLI-only redo the maintainer kept: `atoo undo <the .undo.json>`.
    There is no redo command and no second button."""
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()
    run_cli(monkeypatch, desk, [
        "undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"])
    assert desk.state["/ch/21/name"] == ("", "s")

    undo_entry = journal_stack.entries(directory)[-1]
    assert run_cli(monkeypatch, desk, [
        "undo", str(undo_entry.path), "--console", "198.51.100.1", "--confirm"]) == 0

    assert desk.state["/ch/21/name"] == ("Trumpet", "s")
    assert journal_stack.top(directory).kind == "amend"


def test_undo_show_does_not_read_a_top_level_journal(
        tmp_path, monkeypatch, capsys):
    """A bundle with no `journals/` has recorded nothing, whatever else is
    in it. Until 2026-10-02 `undo --show` fell back to a top-level
    `apply-journal.json` an earlier version wrote; that fallback is
    retired (the maintainer: *"you can delete them."*). Nothing is written, and
    the file is still undone by naming it."""
    write_journal(tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick"))
    desk = console_holding(__ch__1__name=("Kick", "s"))
    code = run_cli(monkeypatch, desk, [
        "undo", "--show", str(tmp_path), "--console", "198.51.100.1", "--confirm"])

    err = capsys.readouterr().err
    assert code == 1
    assert "nothing to undo" in err
    assert desk.state["/ch/1/name"] == ("Kick", "s")

    assert run_cli(monkeypatch, desk, [
        "undo", str(tmp_path / "apply-journal.json"), "--console", "198.51.100.1",
        "--confirm"]) == 0
    assert desk.state["/ch/1/name"] == ("", "s")


def test_undo_show_reads_the_stack_and_ignores_a_stale_top_level_copy(
        tmp_path, monkeypatch, capsys):
    """The stack is the record. A top-level journal file (a
    bundle made between #252 and #356 has one, and a `--journal PATH`
    can put one there) is neither read nor reported -- here it is a copy
    of an OLDER apply, and undo must pop the newer one on the stack."""
    old = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    newer_path = journal_stack.new_entry_path(tmp_path, "apply")
    write_journal(newer_path, row("/ch/2/name", "", "Snare"))
    newer = journal_stack.record(tmp_path, "apply", newer_path)
    assert (tmp_path / "apply-journal.json").is_file()
    assert journal_stack.find(tmp_path, tmp_path / "apply-journal.json").id == old.id

    desk = console_holding(__ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"))
    code = run_cli(monkeypatch, desk, [
        "undo", "--show", str(tmp_path), "--console", "198.51.100.1", "--confirm"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert desk.state["/ch/2/name"] == ("", "s")
    assert desk.state["/ch/1/name"] == ("Kick", "s")
    assert "apply-journal.json" not in captured.out + captured.err
    assert newer.id in captured.out


def test_undo_show_on_a_bundle_that_was_never_written_to_says_so(
        tmp_path, monkeypatch, capsys):
    code = run_cli(monkeypatch, None, ["undo", "--show", str(tmp_path)])
    assert code == 1
    assert "recorded no writes" in capsys.readouterr().err


def test_undo_with_neither_a_journal_nor_a_show_says_which_to_give(
        tmp_path, monkeypatch, capsys):
    """The positional became optional, so the absent case is a real one
    and gets a real message rather than an argparse usage line."""
    code = run_cli(monkeypatch, None, ["undo", "--console", "198.51.100.1"])
    assert code == 1
    assert "--show DIR" in capsys.readouterr().err


def test_a_stack_whose_writes_have_all_been_reversed_has_nothing_to_pop(
        tmp_path, monkeypatch, capsys):
    directory = bundle_with_apply_then_amend(tmp_path)
    desk = desk_after_both()
    argv = ["undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"]
    run_cli(monkeypatch, desk, argv)
    run_cli(monkeypatch, desk, argv)

    assert journal_stack.top(directory) is None
    assert run_cli(monkeypatch, desk, argv) == 1
    err = capsys.readouterr().err
    assert "has already been reversed" in err
    # And it says how to get back -- the journals are still there.
    assert "redo" in err


# ---------------------------------------------------------------------------
# A run that died partway
# ---------------------------------------------------------------------------

def test_an_aborted_apply_is_recorded_before_the_command_gives_up(
        tmp_path, monkeypatch, capsys):
    """`undo.py`: a partial journal "is the most important one to be able
    to reverse -- it is the one nobody planned for". `apply_cmd` exits 1
    on a connection lost mid-run, and the recording has to happen on the
    way out, not after it.

    Mutation-checked: move the `_record_on_stack` call in `cli.apply_cmd`
    back below the `if result.aborted: return 1` branch and this fails,
    while every other apply test stays green -- which is exactly how the
    ordering was wrong to begin with.
    """
    import atoo.apply as apply_module
    from atoo import cli
    from atoo.apply import ApplyResult, WriteRecord, _write_journal

    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps({"meta": {}, "channels": []}))

    def fake_apply_plan(plan, console, *, dry_run=True, journal_path=None, **kwargs):
        result = ApplyResult(
            dry_run=dry_run,
            writes=[WriteRecord(
                address="/ch/1/name", description="ch 1: name", value_type="s",
                method="node", ack="OK", prior_value="", intended_value="Kick",
                readback_value="Kick", status="match",
                timestamp="2026-09-24T00:00:00+00:00")],
            journal_path=journal_path, aborted=True,
            abort_reason="OSError: [Errno 65] No route to host")
        if journal_path:
            _write_journal(journal_path, result)
        return result

    monkeypatch.setattr(apply_module, "apply_plan", fake_apply_plan)

    class _Reachable:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def identity(self):
            from atoo.console import OscReply
            return OscReply(address="/?", typetag="s",
                            args=["WING,198.51.100.1,DESK,wing-compact,SER,1"])

    monkeypatch.setattr("atoo.console.WingConsole", _Reachable)

    code = cli.main(["apply", "--show", str(show), "--console", "198.51.100.1",
                     "--confirm", "--skip-verify"])
    assert code == 1, capsys.readouterr().out

    entries = journal_stack.entries(show)
    assert [e.kind for e in entries] == ["apply"]
    assert json.loads(entries[0].path.read_text())["writes"][0]["address"] == "/ch/1/name"


def test_an_amend_row_carries_the_scope_the_run_was_held_to(tmp_path):
    """An address count cannot tell two amends apart on a listing;
    "ch:21" can. The journal already records the scope."""
    entry = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet"),
        scope={"strips": ["ch:21"], "grants": {"/ch/21": "added"},
               "released": ["ch:9"]}))
    assert "scope: ch:21; returned to free: ch:9" in entry.summary


# ---------------------------------------------------------------------------
# An undo that aborted partway (found reviewing #259's PR, 2026-09-24)
# ---------------------------------------------------------------------------

def _partial_undo_journal(path: Path) -> Path:
    """What `undo` leaves when the connection goes partway through
    reversing the amend: one address reached, and `aborted` set."""
    payload = journal(row("/ch/21/name", "Trumpet", ""))
    payload["aborted"] = True
    payload["abort_reason"] = "OSError: [Errno 65] No route to host"
    path.write_text(json.dumps(payload))
    return path


def test_an_aborted_undo_is_recorded_but_does_not_pop_what_it_was_reversing(tmp_path):
    """A partial reversal is evidence -- the only file saying which
    addresses it reached -- so it goes on the stack, linked to the run it
    was reversing. But that run's writes partly still stand, so it must
    stay the top: the next `undo --show` lands on it again and finishes
    it (undo's per-address guard counts what is already back as
    `already_restored`).

    Mutation-checked: drop the `entry.aborted` skip in `_live` and the
    amend is popped by a reversal that never finished."""
    directory = bundle_with_apply_then_amend(tmp_path)
    amend = journal_stack.top(directory)
    assert amend.kind == "amend"

    partial = journal_stack.record(
        directory, "undo",
        _partial_undo_journal(journal_stack.new_entry_path(directory, "undo")),
        undo_of=amend.id)

    assert partial.aborted and partial.undo_of == amend.id
    assert journal_stack.top(directory).id == amend.id, "a partial undo must not pop"
    assert journal_stack.reversed_by(directory, amend) is None
    listed = {e.id: e for e in journal_stack.listing(directory)}
    assert listed[partial.id].aborted and listed[amend.id].is_top
    # ...and survives the index being rebuilt from the files alone.
    (journal_stack.stack_dir(directory) / "index.json").unlink()
    assert journal_stack.top(directory).id == amend.id

    # The finishing undo is an ordinary, complete one: it pops.
    done = journal_stack.record(
        directory, "undo",
        write_journal(journal_stack.new_entry_path(directory, "undo"),
                      row("/ch/21/name", "Trumpet", "")),
        undo_of=amend.id)
    assert not done.aborted
    assert journal_stack.top(directory).kind == "apply"
    assert journal_stack.reversed_by(directory, amend) == done.id


def test_undo_cmd_records_an_aborted_undo_on_the_way_out(tmp_path, monkeypatch, capsys):
    """Before this, `undo_cmd` returned 1 on an abort BEFORE recording,
    so the partial journal sat in `journals/` unlinked -- listed by the
    stack's self-heal as an undo of nothing. Mirrors
    `test_an_aborted_apply_is_recorded_before_the_command_gives_up`.

    Mutation-checked: remove the `_record_on_stack` call from the
    `result.aborted` branch and the linkage assertion fails."""
    from atoo import undo as undo_engine
    from atoo.undo import UndoResult

    directory = bundle_with_apply_then_amend(tmp_path)
    amend = journal_stack.top(directory)

    def fake_undo(journal_, console, *, journal_path=None, dry_run=True, **kwargs):
        if journal_path:
            _partial_undo_journal(Path(journal_path))
        result = UndoResult(dry_run=dry_run, source_journal=str(amend.path))
        result.aborted, result.abort_reason = True, "OSError: [Errno 65] No route to host"
        return result

    monkeypatch.setattr(undo_engine, "undo_from_journal", fake_undo)
    code = run_cli(monkeypatch, desk_after_both(), [
        "undo", "--show", str(directory), "--console", "198.51.100.1", "--confirm"])

    assert code == 1
    undos = [e for e in journal_stack.entries(directory) if e.kind == "undo"]
    assert len(undos) == 1 and undos[0].aborted and undos[0].undo_of == amend.id
    assert journal_stack.top(directory).id == amend.id
    assert "still the top" in capsys.readouterr().err
