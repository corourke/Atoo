"""Per-desk journal history -- one bundle, applied to more than one console.

*"you might generate a plan, and want to apply it to
more than one console, ex: primary console wing compact, backup console
wing rack (both have similar I/O.)"* The journal stack is one
per BUNDLE, and until this change it assumed one desk. The hazard that
made per-desk history a requirement rather than a nicety:

1. apply the plan to the primary, then to the backup;
2. press Undo while connected to the primary;
3. the top of the stack is the backup's apply. Undo's per-address guard
   passes -- the primary holds exactly the values the backup's journal
   says were written -- and the PRIMARY is reversed.

`test_undo_on_the_primary_pops_the_primarys_apply_not_the_backups` is that
scenario, end to end through `atoo apply` and `atoo undo`.

No test here touches a real console (`test_apply.FakeConsole` via
`test_undo.console_holding`), and none reads a bundle under `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import journal_stack
from atoo.journal_stack import desk_from_identity, same_desk
from tests.test_undo import console_holding, journal, row

PRIMARY_ID = "WING,198.51.100.5,PRIMARY,wing-compact,SER-P,3.1.0"
BACKUP_ID = "WING,198.51.100.6,BACKUP,wing-rack,SER-B,3.1.0"
PRIMARY = desk_from_identity([PRIMARY_ID], "198.51.100.5", 2223)
BACKUP = desk_from_identity([BACKUP_ID], "198.51.100.6", 2223)
IDENTITIES = {"198.51.100.5": PRIMARY_ID, "198.51.100.6": BACKUP_ID}


def write_journal(path: Path, *rows, **kwargs) -> Path:
    path.write_text(json.dumps(journal(*rows, **kwargs)))
    return path


def holding_the_show():
    """A desk the plan has been applied to: ch 1 and ch 2 named."""
    return console_holding(__ch__1__name=("Kick", "s"), __ch__2__name=("Snare", "s"))


# ---------------------------------------------------------------------------
# What a desk is
# ---------------------------------------------------------------------------

def test_the_desk_is_read_off_the_identity_reply():
    assert PRIMARY == {"serial": "SER-P", "name": "PRIMARY", "model": "wing-compact",
                       "model_token": "wing-compact",
                       "address": "198.51.100.5", "port": 2223, "firmware": "3.1.0"}


def test_the_desk_keeps_the_model_exactly_as_it_spelled_it():
    """`model_token` is the raw `<model>` field: translated for a measured
    alias, left alone for a token nobody has measured -- which is the
    string a first run against a WING Rack hands back for
    `IDENTITY_MODEL_ALIASES`."""
    full = desk_from_identity(["WING,198.51.100.5,FOH,wing-fullsize,SER,3.1"], "198.51.100.5")
    assert full["model"] == "wing-full" and full["model_token"] == "wing-fullsize"
    rack = desk_from_identity(["WING,198.51.100.6,MON,wing-racksize,SER2,3.1"], "198.51.100.6")
    assert rack["model"] == "wing-racksize" and rack["model_token"] == "wing-racksize"


def test_a_desk_that_states_no_serial_is_known_by_its_address():
    desk = desk_from_identity(["WING,198.51.100.5,PRIMARY,wing-compact"], "198.51.100.5", 2223)
    assert desk["serial"] is None and desk["address"] == "198.51.100.5"
    blank = desk_from_identity(["WING,198.51.100.5,PRIMARY,wing-compact,,3.1"], "198.51.100.5")
    assert blank["serial"] is None


def test_with_no_identity_the_address_is_all_there_is():
    assert desk_from_identity(None, "198.51.100.5", 2223)["address"] == "198.51.100.5"
    assert desk_from_identity(None, None) is None


def test_the_serial_decides_even_at_the_same_address():
    """The backup brought up on the primary's IP is still the backup."""
    swapped = desk_from_identity([BACKUP_ID], "198.51.100.5", 2223)
    assert not same_desk(PRIMARY, swapped)
    # ...and the same desk at a new address is still the same desk.
    moved = desk_from_identity([PRIMARY_ID], "198.51.100.99", 2223)
    assert same_desk(PRIMARY, moved)


def test_without_a_serial_on_one_side_the_address_decides():
    by_address = desk_from_identity(None, "198.51.100.5")
    assert same_desk(PRIMARY, by_address)
    assert not same_desk(BACKUP, by_address)
    assert not same_desk(PRIMARY, {}) and not same_desk(None, PRIMARY)


# ---------------------------------------------------------------------------
# The stack, per desk
# ---------------------------------------------------------------------------

def two_desk_stack(tmp_path):
    """Apply to the primary, then the same plan to the backup."""
    a = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=PRIMARY)
    b = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=BACKUP)
    return a, b


def test_every_entry_records_its_desk_in_the_journal_and_the_index(tmp_path):
    a, b = two_desk_stack(tmp_path)
    assert json.loads(a.path.read_text())["stack_entry"]["desk"]["serial"] == "SER-P"
    index = json.loads((journal_stack.stack_dir(tmp_path) / "index.json").read_text())
    assert [r["desk"]["serial"] for r in index["entries"]] == ["SER-P", "SER-B"]
    # ...and survives the index being rebuilt from the files alone.
    (journal_stack.stack_dir(tmp_path) / "index.json").unlink()
    assert [e.desk["serial"] for e in journal_stack.entries(tmp_path)] == ["SER-P", "SER-B"]


def test_the_top_is_asked_of_one_desk(tmp_path):
    a, b = two_desk_stack(tmp_path)
    assert journal_stack.top(tmp_path, PRIMARY).id == a.id
    assert journal_stack.top(tmp_path, BACKUP).id == b.id
    # No desk: the whole stack's newest, which is what it always was.
    assert journal_stack.top(tmp_path).id == b.id


def test_another_desks_entry_is_not_above_this_one(tmp_path):
    a, b = two_desk_stack(tmp_path)
    assert journal_stack.above(tmp_path, a, PRIMARY) == []
    assert [e.id for e in journal_stack.above(tmp_path, a)] == [b.id]
    assert [e.id for e in journal_stack.positions(tmp_path, PRIMARY)] == [a.id]


def test_the_listing_carries_the_desk_and_marks_that_desks_top(tmp_path):
    a, b = two_desk_stack(tmp_path)
    rows = {e.id: e for e in journal_stack.listing(tmp_path, PRIMARY)}
    assert rows[a.id].is_top and not rows[b.id].is_top
    assert rows[a.id].on_this_desk is True and rows[b.id].on_this_desk is False
    assert rows[b.id].desk["serial"] == "SER-B"
    # Asked for no desk: the global top, and no opinion about which desk.
    rows = {e.id: e for e in journal_stack.listing(tmp_path)}
    assert rows[b.id].is_top and rows[a.id].on_this_desk is None


def test_an_entry_recorded_before_desks_counts_as_any_desks(tmp_path):
    """The single-desk assumption was true when it was written."""
    legacy = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    assert legacy.desk is None
    assert journal_stack.top(tmp_path, PRIMARY).id == legacy.id
    assert journal_stack.top(tmp_path, BACKUP).id == legacy.id


def test_desks_without_serials_are_told_apart_by_address(tmp_path):
    left = desk_from_identity(None, "198.51.100.5", 2223)
    right = desk_from_identity(None, "198.51.100.6", 2223)
    a = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=left)
    journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=right)
    assert journal_stack.top(tmp_path, left).id == a.id


# ---------------------------------------------------------------------------
# Through the commands
# ---------------------------------------------------------------------------

@pytest.fixture
def bundle_dir(tmp_path):
    show = tmp_path / "show"
    show.mkdir()
    (show / "plan.json").write_text(json.dumps({"meta": {}, "channels": []}))
    return show


def apply_to(monkeypatch, show: Path, address: str) -> int:
    """`atoo apply --show DIR --confirm` against a fake desk at
    `address` that names itself with that desk's `/?` reply. The engine is
    stubbed to write a one-row journal; what is under test is what the
    command RECORDS about where it wrote."""
    import atoo.apply as apply_module
    from atoo import cli
    from atoo.apply import ApplyResult, WriteRecord, _write_journal
    from atoo.console import OscReply

    def fake_apply_plan(plan, console, *, dry_run=True, journal_path=None, **kwargs):
        result = ApplyResult(dry_run=dry_run, writes=[WriteRecord(
            address="/ch/1/name", description="ch 1: name", value_type="s", method="node",
            ack="OK", prior_value="", intended_value="Kick", readback_value="Kick",
            status="match", timestamp="2026-09-24T00:00:00+00:00")],
            journal_path=journal_path)
        if journal_path:
            _write_journal(journal_path, result)
        return result

    class _Desk:
        def __init__(self, ip, *a, **k):
            self.ip = ip

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def identity(self):
            return OscReply(address="/?", typetag="s", args=[IDENTITIES[self.ip]])

    monkeypatch.setattr(apply_module, "apply_plan", fake_apply_plan)
    monkeypatch.setattr("atoo.console.WingConsole", _Desk)
    return cli.main(["apply", "--show", str(show), "--console", address,
                     "--confirm", "--skip-verify"])


def undo_on(monkeypatch, desk_console, address, argv):
    """`atoo undo ...` with `--console address`, the desk at that
    address answering `/?` with its own identity -- `_open_console` is
    replaced by one that stashes the reply as the real one does."""
    from atoo import cli

    desk_console.close = lambda: None
    opened = []

    def opener(args, raw_log=None):
        opened.append(args.console)
        args.console_identity = [IDENTITIES[args.console]] if args.console in IDENTITIES else None
        return desk_console

    monkeypatch.setattr(cli, "_open_console", opener)
    code = cli.main(argv + ["--console", address])
    return code, opened


def test_apply_records_the_desk_it_wrote_to(bundle_dir, monkeypatch, capsys):
    assert apply_to(monkeypatch, bundle_dir, "198.51.100.5") == 0, capsys.readouterr().err
    assert apply_to(monkeypatch, bundle_dir, "198.51.100.6") == 0, capsys.readouterr().err
    desks = [e.desk for e in journal_stack.entries(bundle_dir)]
    assert [d["serial"] for d in desks] == ["SER-P", "SER-B"]
    assert [d["address"] for d in desks] == ["198.51.100.5", "198.51.100.6"]
    assert desks[1]["model"] == "wing-rack"


def test_undo_on_the_primary_pops_the_primarys_apply_not_the_backups(
        bundle_dir, monkeypatch, capsys):
    """**The hazard, closed.** Apply to the primary, then to the backup;
    undo while connected to the primary. It must reverse the PRIMARY'S
    apply -- the backup's is the top of the stack, and before per-desk
    history undo popped it and reversed the primary with it.

    Mutation-checked: drop the desk filter from `journal_stack.top` (or
    stop `_undo_run` passing `link.desk` to it) and `undo_of` names the
    backup's entry."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    apply_to(monkeypatch, bundle_dir, "198.51.100.6")
    primary_apply, backup_apply = journal_stack.entries(bundle_dir)
    capsys.readouterr()

    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", "--show", str(bundle_dir), "--confirm"])
    out = capsys.readouterr().out
    assert code == 0, out
    undos = [e for e in journal_stack.entries(bundle_dir) if e.kind == "undo"]
    assert len(undos) == 1 and undos[0].undo_of == primary_apply.id
    assert undos[0].desk["serial"] == "SER-P"
    # The backup's history is untouched: its apply is still its top.
    assert journal_stack.top(bundle_dir, BACKUP).id == backup_apply.id
    assert journal_stack.top(bundle_dir, PRIMARY) is None
    # And it said what it walked past.
    assert "on a different desk, and are left alone" in out
    assert "BACKUP" in out


def test_with_nothing_left_on_this_desk_it_says_so_and_names_the_other(
        bundle_dir, monkeypatch, capsys):
    journal_stack.record(bundle_dir, "apply", write_journal(
        bundle_dir / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=BACKUP)
    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", "--show", str(bundle_dir), "--confirm"])
    err = capsys.readouterr().err
    assert code == 1
    assert "nothing to undo on this desk" in err and "BACKUP" in err
    assert primary.state["/ch/1/name"] == ("Kick", "s")


def test_a_legacy_entry_is_popped_on_whatever_desk_and_says_so(
        bundle_dir, monkeypatch, capsys):
    """An entry recorded before entries named their desk. An
    inferred value is fine, an inferred value that does not announce
    itself is not."""
    legacy = journal_stack.record(bundle_dir, "apply", write_journal(
        bundle_dir / "apply-journal.json", row("/ch/1/name", "", "Kick")))
    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", "--show", str(bundle_dir), "--confirm"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert primary.state["/ch/1/name"] == ("", "s")
    assert "INFO" in out and "predates per-desk journals" in out
    undo = [e for e in journal_stack.entries(bundle_dir) if e.kind == "undo"][0]
    assert undo.undo_of == legacy.id


def test_a_journal_written_to_another_desk_is_refused_naming_both(
        bundle_dir, monkeypatch, capsys):
    """Named explicitly -- the newest apply entry, which after
    apply-primary-then-backup is the backup's. Refused while the primary is
    on the line.

    Mutation-checked: make `journal_stack.same_desk` return True and this
    reverses the primary. There is no override (
    *"undo can only apply against correct desk / correct journal"*), and the
    refusal no longer offers one."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    apply_to(monkeypatch, bundle_dir, "198.51.100.6")
    capsys.readouterr()
    primary = holding_the_show()
    newest = journal_stack.entries(bundle_dir)[-1]
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", str(newest.path), "--confirm"])
    err = capsys.readouterr().err
    assert code == 1
    assert primary.state["/ch/1/name"] == ("Kick", "s")
    assert "BACKUP" in err and "PRIMARY" in err
    assert "--other-desk" not in err


def test_there_is_no_override_for_another_desks_journal(bundle_dir, monkeypatch, capsys):
    """The `--other-desk` is gone: "can only" rules out an escape hatch.
    Passing it is a usage error, and nothing is written.

    Mutation-checked: put the flag back (argparse accepts it, `_undo_run`
    ignores it) and the refusal still holds -- but `argparse` exiting 2 is
    what this pins, so a reintroduced override has to delete this test."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    apply_to(monkeypatch, bundle_dir, "198.51.100.6")
    capsys.readouterr()
    primary = holding_the_show()
    with pytest.raises(SystemExit) as exc:
        undo_on(monkeypatch, primary, "198.51.100.5",
                ["undo", str(journal_stack.entries(bundle_dir)[-1].path), "--confirm",
                 "--other-desk"])
    assert exc.value.code == 2
    assert "unrecognized arguments: --other-desk" in capsys.readouterr().err
    assert primary.state["/ch/1/name"] == ("Kick", "s")
    from atoo import cli
    assert "--other-desk" not in cli.build_parser()[1]["undo"].format_help()


def test_a_later_write_on_another_desk_does_not_make_a_journal_stale(
        bundle_dir, monkeypatch, capsys):
    """The explicit-journal staleness question is "is there a later live
    entry on THIS desk". The backup's apply is later, but not on this desk.

    Mutation-checked: drop the desk from `_undo_staleness`'s `above` call
    and this is refused as out of order."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    primary_apply = journal_stack.entries(bundle_dir)[0]
    apply_to(monkeypatch, bundle_dir, "198.51.100.6")
    capsys.readouterr()
    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", str(primary_apply.path), "--confirm"])
    assert code == 0, capsys.readouterr().err
    assert primary.state["/ch/1/name"] == ("", "s")


def test_a_later_write_on_the_same_desk_still_refuses_and_names_only_it(
        bundle_dir, monkeypatch, capsys):
    """Apply A, amend A, apply B: reversing A's apply reaches under A's
    amend, and the refusal names the amend -- not the backup's apply --
    before the console is opened (phase 1, from files alone)."""
    a = journal_stack.record(bundle_dir, "apply", write_journal(
        bundle_dir / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=PRIMARY)
    journal_stack.record(bundle_dir, "amend", write_journal(
        bundle_dir / "amend-journal.json", row("/ch/21/name", "", "Trumpet")), desk=PRIMARY)
    journal_stack.record(bundle_dir, "apply", write_journal(
        bundle_dir / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=BACKUP)
    primary = holding_the_show()
    code, opened = undo_on(monkeypatch, primary, "198.51.100.5",
                           ["undo", str(a.path), "--confirm"])
    err = capsys.readouterr().err
    assert code == 1 and opened == [], "refused from files, before the desk was contacted"
    assert "1 later write(s) are still on the desk" in err
    assert "amend" in err and "BACKUP" not in err


def test_no_serial_on_the_desk_matches_its_entries_by_address(
        bundle_dir, monkeypatch, capsys):
    """Absent case: a desk whose `/?` states no serial. Its entries are
    recorded by address and undo finds them by address."""
    no_serial = {"198.51.100.5": "WING,198.51.100.5,PRIMARY,wing-compact",
                 "198.51.100.6": "WING,198.51.100.6,BACKUP,wing-rack"}
    monkeypatch.setitem(IDENTITIES, "198.51.100.5", no_serial["198.51.100.5"])
    monkeypatch.setitem(IDENTITIES, "198.51.100.6", no_serial["198.51.100.6"])
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    primary_apply = journal_stack.entries(bundle_dir)[0]
    apply_to(monkeypatch, bundle_dir, "198.51.100.6")
    assert primary_apply.desk["serial"] is None
    capsys.readouterr()
    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", "--show", str(bundle_dir), "--confirm"])
    assert code == 0, capsys.readouterr().out
    undo = [e for e in journal_stack.entries(bundle_dir) if e.kind == "undo"][0]
    assert undo.undo_of == primary_apply.id


def test_undo_show_with_no_console_anywhere_asks_for_one(bundle_dir, monkeypatch, capsys):
    """Absent case: entries exist, so which one to pop depends on the desk
    -- and there is no desk. The same message every console command gives,
    exit 2, and nothing popped."""
    from atoo import cli

    two_desk_stack(bundle_dir)
    monkeypatch.setattr(cli, "_open_console", lambda args, raw_log=None: pytest.fail(
        "no console address, so nothing may be opened"))
    code = cli.main(["undo", "--show", str(bundle_dir), "--confirm"])
    assert code == 2
    assert "no console address" in capsys.readouterr().err
    assert not [e for e in journal_stack.entries(bundle_dir) if e.kind == "undo"]


def test_an_offline_preview_has_no_desk_and_says_whose_top_it_shows(
        bundle_dir, monkeypatch, capsys, tmp_path):
    """`--state` contacts no desk, so there is no desk to ask the stack
    about: it previews the whole stack's newest, and says the confirmed
    run may pick a different entry."""
    from atoo import cli

    two_desk_stack(bundle_dir)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"/ch/1/name": "Kick"}))
    code = cli.main(["undo", "--show", str(bundle_dir), "--state", str(state)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "no desk was contacted" in out


# ---------------------------------------------------------------------------
# File names carry the desk -- its serial, or its address when it has none
#
# ---------------------------------------------------------------------------

def _stamp(monkeypatch, *when):
    moments = iter(journal_stack.datetime(*w, tzinfo=journal_stack.timezone.utc)
                   for w in when)
    current = {}

    def now():
        # `record` asks the clock twice per entry (the name and
        # `recorded_at`); both see the same moment.
        if "value" not in current or current.get("used", 0) >= 2:
            current["value"] = next(moments)
            current["used"] = 0
        current["used"] += 1
        return current["value"]

    monkeypatch.setattr(journal_stack, "_now", now)


def test_an_entry_is_named_for_its_desks_serial(tmp_path, monkeypatch):
    _stamp(monkeypatch, (2026, 9, 24, 19, 1, 4, 102728))
    entry = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/21/name", "", "Trumpet")), desk=PRIMARY)
    assert entry.id == "20260924T190104.102728Z-amend-SER-P.json".replace("SER-P", "SER_P")
    assert journal_stack.parse_entry_name(entry.id) == {
        "stamp": "20260924T190104.102728Z", "n": None, "kind": "amend", "desk": "SER_P"}


def test_a_desk_with_no_serial_is_named_for_its_address(tmp_path):
    desk = desk_from_identity(["WING,192.0.2.16,BACKUP,wing-rack"], "192.0.2.16", 2223)
    entry = journal_stack.record(tmp_path, "apply", write_journal(
        tmp_path / "apply-journal.json", row("/ch/1/name", "", "Kick")), desk=desk)
    assert entry.id.endswith("-apply-192.0.2.16.json")
    assert journal_stack.parse_entry_name(entry.id)["desk"] == "192.0.2.16"


def test_the_desk_token_is_made_safe_for_a_file_name():
    token = journal_stack.desk_token
    assert token({"serial": "S123/45:6", "address": "198.51.100.5"}) == "S123_45_6"
    assert token({"serial": None, "address": "fe80::1"}) == "fe80__1"
    assert token({"serial": None, "address": "wing-primary.local"}) == "wing_primary.local"
    assert token({"serial": None, "address": "198.51.100.5", "port": 2224}) == "198.51.100.5_port2224"
    assert token({"serial": None, "address": "198.51.100.5", "port": 2223}) == "198.51.100.5"
    assert token({"serial": None, "address": ".."}) == "__"
    assert len(token({"serial": "X" * 500})) <= 64
    assert token(None) is None and token({"serial": None, "address": None}) is None
    # A sanitised token never contains the name's own separator.
    assert "-" not in token({"serial": "a-b-c"})


def test_legacy_names_still_parse_sort_and_list_beside_new_ones(tmp_path, monkeypatch):
    """An entry recorded before names carried a desk -- `<stamp>-<kind>.json`
    -- sorts by its stamp among the new ones and lists with its kind, with
    or without the index. The kind is read off the NAME here: the files
    carry no `stack_entry`, so `_kind_from_name` is all there is."""
    directory = journal_stack.stack_dir(tmp_path)
    directory.mkdir()
    write_journal(directory / "20260924T050000.000000Z-apply.json", row("/ch/1/name", "", "K"))
    write_journal(directory / "20260924T040000.000000Z-2-amend.json",
                  row("/ch/21/name", "", "T"))
    _stamp(monkeypatch, (2026, 9, 24, 6, 0, 0, 0), (2026, 9, 24, 7, 0, 0, 0))
    new = journal_stack.record(tmp_path, "amend", write_journal(
        tmp_path / "amend-journal.json", row("/ch/22/name", "", "Tb")), desk=PRIMARY)
    write_journal(directory / "20260924T063000.000000Z-undo.json", row("/ch/22/name", "Tb", ""))
    # A new-style name on a file with no `stack_entry` (copied in by hand):
    # the kind still comes off the name, past the desk token.
    write_journal(directory / "20260924T080000.000000Z-undo-S9.json",
                  row("/ch/22/name", "Tb", ""))

    for _ in range(2):
        listed = journal_stack.entries(tmp_path)
        assert [e.id for e in listed] == [
            "20260924T040000.000000Z-2-amend.json", "20260924T050000.000000Z-apply.json",
            new.id, "20260924T063000.000000Z-undo.json", "20260924T080000.000000Z-undo-S9.json"]
        assert [e.kind for e in listed] == ["amend", "apply", "amend", "undo", "undo"]
        (directory / journal_stack.INDEX).unlink(missing_ok=True)
    assert journal_stack.parse_entry_name("20260924T050000.000000Z-apply.json")["desk"] is None
    assert journal_stack.parse_entry_name("notes.json") is None


def test_a_legacy_named_entry_with_no_desk_still_undoes(bundle_dir, monkeypatch, capsys):
    """A stack laid out before this change: `<stamp>-apply.json`, no desk.
    Undo pops it on whichever desk is connected and says so at INFO; its
    own undo entry is named for the desk it DID reach."""
    directory = journal_stack.stack_dir(bundle_dir)
    directory.mkdir()
    write_journal(directory / "20260924T050000.000000Z-apply.json",
                  row("/ch/1/name", "", "Kick"))
    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.5",
                      ["undo", "--show", str(bundle_dir), "--confirm"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert primary.state["/ch/1/name"] == ("", "s")
    assert "predates per-desk journals" in out
    undo = journal_stack.entries(bundle_dir)[-1]
    assert undo.kind == "undo" and undo.undo_of == "20260924T050000.000000Z-apply.json"
    assert undo.id.endswith("-undo-SER_P.json")


def test_the_index_row_carries_the_serial_and_the_address(tmp_path):
    a, b = two_desk_stack(tmp_path)
    index = json.loads((journal_stack.stack_dir(tmp_path) / "index.json").read_text())
    assert [(r["serial"], r["address"]) for r in index["entries"]] == [
        ("SER-P", "198.51.100.5"), ("SER-B", "198.51.100.6")]


# ---------------------------------------------------------------------------
# The serial is the desk: a new address is the same desk, a new serial is not
# ---------------------------------------------------------------------------

def test_the_same_serial_at_a_new_address_is_the_same_desk_and_says_so(
        bundle_dir, monkeypatch, capsys):
    """Home network to gig network. Applied at 198.51.100.5; the primary comes
    up at 198.51.100.99 with the same serial. Undo pops its apply, with an INFO
    naming both addresses.

    Mutation-checked: make `same_desk` compare addresses even when both
    serials are known and this says "nothing to undo on this desk"."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    applied = journal_stack.entries(bundle_dir)[0]
    monkeypatch.setitem(IDENTITIES, "198.51.100.99", PRIMARY_ID)
    capsys.readouterr()
    primary = holding_the_show()
    code, _ = undo_on(monkeypatch, primary, "198.51.100.99",
                      ["undo", "--show", str(bundle_dir), "--confirm"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert primary.state["/ch/1/name"] == ("", "s")
    assert "INFO this journal was written to serial SER-P at 198.51.100.5" in out
    assert "198.51.100.99" in out
    assert journal_stack.entries(bundle_dir)[-1].undo_of == applied.id


def test_a_different_serial_at_the_same_address_is_refused_naming_both(
        bundle_dir, monkeypatch, capsys):
    """The backup brought up on the primary's IP: the primary's apply is
    not its to reverse, even though every address would pass the guard."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    applied = journal_stack.entries(bundle_dir)[0]
    monkeypatch.setitem(IDENTITIES, "198.51.100.5", BACKUP_ID)
    capsys.readouterr()
    backup = holding_the_show()
    code, _ = undo_on(monkeypatch, backup, "198.51.100.5",
                      ["undo", str(applied.path), "--confirm"])
    err = capsys.readouterr().err
    assert code == 1
    assert backup.state["/ch/1/name"] == ("Kick", "s")
    assert "SER-P" in err and "SER-B" in err
    assert "Undo only reverses a journal on the desk it was written to" in err


def test_a_copied_journal_outside_any_bundle_is_still_held_to_its_desk(
        bundle_dir, monkeypatch, capsys, tmp_path):
    """A stack entry copied out of the bundle carries its own
    `stack_entry.desk`; the stack cannot place it, but the desk rule still
    holds.

    Mutation-checked: drop the off-stack check in `_undo_run` and this
    reverses the backup."""
    apply_to(monkeypatch, bundle_dir, "198.51.100.5")
    copy = tmp_path / "elsewhere" / "apply-journal.json"
    copy.parent.mkdir()
    copy.write_text(journal_stack.entries(bundle_dir)[-1].path.read_text())
    capsys.readouterr()
    backup = holding_the_show()
    code, _ = undo_on(monkeypatch, backup, "198.51.100.6", ["undo", str(copy), "--confirm"])
    err = capsys.readouterr().err
    assert code == 1
    assert backup.state["/ch/1/name"] == ("Kick", "s")
    assert "SER-P" in err and "SER-B" in err
