"""A bundle's history folders keep the newest five -- 
*"continually prune the builds, journals, and logs directories to a max of
5 entries each"*; the build-log folder is now `builds/`.

`builds/` and `logs/` are plain: the newest five entries by name.
`journals/` is the delicate one, because the stack is not a list of
independent files -- an undo means something only beside what it reversed,
and what is on a desk now is that desk's newest standing write, however
old. So most of this file is about the stack: pruning keeps it saying the
same thing, undo walks back inside the kept window and refuses cleanly
beyond it, and amend/patch still find a desk's applied plan.

Every bundle here is built in `tmp_path`; nothing reads `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import build_log, bundle, journal_stack, prune
from tests.test_undo import console_holding, journal, row

REPO = Path(__file__).resolve().parent.parent

PRIMARY = journal_stack.desk_from_identity(["WING,198.51.100.1,FOH,wing-compact,S-PRIMARY,3.1"],
                                           "198.51.100.1")
BACKUP = journal_stack.desk_from_identity(["WING,198.51.100.2,MON,wing-rack,S-BACKUP,3.1"],
                                          "198.51.100.2")


def _plan(tag: str) -> dict:
    return {"meta": {"tag": tag}, "channels": [{"channel": 1, "name": tag}]}


def _record(show: Path, kind: str, tag: str, *, desk=PRIMARY, undo_of=None, change=None,
            prior: str = "", address: str = "/ch/1/name") -> journal_stack.Entry:
    """One confirmed run on the stack: a journal writing `tag` at `address`,
    with the plan it left on its desk (what amend and patch read back)."""
    path = journal_stack.new_entry_path(show, kind, desk)
    payload = journal(row(address, prior, tag))
    if change is not None:
        payload[journal_stack.CHANGE_BLOCK] = change
    path.write_text(json.dumps(payload))
    extra = None
    if kind != "undo":
        extra = {journal_stack.DESK_PLAN_BLOCK: journal_stack.desk_plan_block(
            _plan(tag), "the applied plan")}
    return journal_stack.record(show, kind, path, undo_of=undo_of, extra=extra, desk=desk)


def _undo_top(show: Path, desk=PRIMARY) -> journal_stack.Entry:
    """What a confirmed `undo --show` records: an undo of the desk's top."""
    top = journal_stack.top(show, desk)
    assert top is not None
    return _record(show, "undo", f"undo {top.id}", desk=desk, undo_of=top.id)


def _desk_tag(show: Path, desk=PRIMARY) -> str | None:
    _entry, plan = journal_stack.desk_plan(show, desk)
    return plan["meta"]["tag"] if plan else None


def _files(show: Path) -> list[str]:
    return sorted(p.name for p in journal_stack.stack_dir(show).iterdir()
                  if p.name != journal_stack.INDEX)


# ---------------------------------------------------------------------------
# The one helper and its constant
# ---------------------------------------------------------------------------

def test_one_named_limit_of_five():
    assert prune.KEEP == 5
    assert journal_stack.keep_limit() == 5


def test_select_keeps_the_newest_and_lets_a_protected_entry_take_a_place():
    keys = [f"k{n}" for n in range(8)]
    assert prune.select(keys, 5) == (keys[3:], keys[:3])
    kept, dropped = prune.select(keys, 5, protect={"k0"})
    assert kept == ["k0", "k4", "k5", "k6", "k7"]
    assert len(kept) == 5 and "k0" not in dropped


# ---------------------------------------------------------------------------
# builds/
# ---------------------------------------------------------------------------

def test_builds_is_the_folder_and_the_old_name_is_gone():
    assert build_log.DIRNAME == bundle.BUILDS == "builds"
    old = "build" + "-logs"          # spelled apart, so this file is not a hit
    hits = []
    for top in ("atoo", "docs", "tests", "README.md", "CLAUDE.md"):
        base = REPO / top
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for path in files:
            if path.suffix not in (".py", ".js", ".html", ".md", ".json", ".sh", ".css"):
                continue
            if old in path.read_text(errors="replace") or old in str(path.relative_to(REPO)):
                hits.append(str(path.relative_to(REPO)))
    assert hits == []


def test_a_build_writes_into_builds(tmp_path):
    directory = build_log.directory_for(bundle_dir=tmp_path, out_path=None)
    assert directory == tmp_path / "builds"
    written = build_log.write(directory, {"build_log": {}})
    assert written.parent == tmp_path / "builds"
    assert build_log.pointer(directory, written) == f"builds/{written.name}"


def test_builds_keeps_the_newest_five(tmp_path):
    directory = tmp_path / "builds"
    directory.mkdir()
    for n in range(7):
        (directory / f"2026-10-01T00-00-0{n}Z.json").write_text("{}")
    written = build_log.write(directory, {"build_log": {}})
    names = sorted(p.name for p in directory.iterdir())
    assert len(names) == 5
    assert names[-1] == written.name
    assert "2026-10-01T00-00-00Z.json" not in names


def test_builds_never_prunes_the_log_plan_json_points_to(tmp_path):
    """A run of failed builds must not take the log of the plan the bundle
    still holds. It keeps its place inside the five."""
    directory = tmp_path / "builds"
    directory.mkdir()
    (directory / "2026-09-01T00-00-00Z.json").write_text("{}")
    (tmp_path / "plan.json").write_text(json.dumps(
        {"meta": {"build_log_file": "builds/2026-09-01T00-00-00Z.json"}}))
    for n in range(6):
        (directory / f"2026-10-01T00-00-0{n}Z.json").write_text("{}")
    build_log.write(directory, {"build_log": {}})
    names = sorted(p.name for p in directory.iterdir())
    assert len(names) == 5
    assert "2026-09-01T00-00-00Z.json" in names


# ---------------------------------------------------------------------------
# logs/
# ---------------------------------------------------------------------------

def test_logs_counts_a_build_and_verify_pair_as_one_run(tmp_path):
    for n in range(7):
        for what in ("build", "verify"):
            (tmp_path / f"2026-10-02T10-00-0{n}Z-{what}.txt").write_text(what)
    (tmp_path / "notes.md").write_text("not ours")
    removed = prune.prune_logs(tmp_path)
    assert len(removed) == 4
    left = sorted(p.name for p in tmp_path.iterdir())
    assert "notes.md" in left
    runs = {prune.run_key(n) for n in left if n.endswith(".txt")}
    assert runs == {f"2026-10-02T10-00-0{n}Z" for n in range(2, 7)}
    assert all(f"{r}-build.txt" in left and f"{r}-verify.txt" in left for r in runs)


def test_the_script_entry_point(tmp_path, capsys):
    for n in range(6):
        (tmp_path / f"2026-10-02T10-00-0{n}Z-build.txt").write_text("x")
    assert prune.main(["logs", str(tmp_path)]) == 0
    assert "removed 1 older" in capsys.readouterr().out
    assert prune.main(["nonsense"]) == 2


# ---------------------------------------------------------------------------
# journals/: the index, and what is kept
# ---------------------------------------------------------------------------

def test_the_index_always_names_exactly_the_files_on_disk(tmp_path):
    for n in range(4):
        _record(tmp_path, "apply", f"A{n}")
    for n in range(3):
        _record(tmp_path, "patch", f"P{n}")
    _undo_top(tmp_path)
    _undo_top(tmp_path)
    for n in range(3):
        _record(tmp_path, "amend", f"M{n}", desk=BACKUP)

    files = _files(tmp_path)
    index = json.loads((journal_stack.stack_dir(tmp_path) / journal_stack.INDEX).read_text())
    assert len(files) <= 5
    assert sorted(r["id"] for r in index["entries"]) == files
    assert not set(files) & {r["id"] for r in index.get("pruned", [])}


def test_a_popped_write_and_its_undo_go_before_a_standing_write(tmp_path):
    """Five places are few, so a write that no longer stands goes first:
    the stack after the prune is the same stack."""
    a = _record(tmp_path, "apply", "A")
    p1 = _record(tmp_path, "patch", "P1")
    p2 = _record(tmp_path, "patch", "P2")
    p3 = _record(tmp_path, "patch", "P3")
    _record(tmp_path, "patch", "P4")
    _undo_top(tmp_path)                                   # pops P4: six entries
    kept = _files(tmp_path)
    assert len(kept) == 5
    assert {a.id, p1.id, p2.id, p3.id} <= set(kept)       # every standing write kept
    assert journal_stack.top(tmp_path, PRIMARY).id == p3.id
    assert journal_stack.pruned_rows(tmp_path) == []      # nothing standing was lost


def test_a_prune_never_reorders_the_stack_a_redo_made(tmp_path):
    """A, B, undo B, C, redo B (undo the undo), D. The redo put B back
    AFTER C, so undo pops D, then B, leaving C. Deleting the reversed undo
    first -- the obvious "it no longer stands" candidate -- would make the
    redo a no-op and put B back under C. Each deletion is checked against
    the whole stack, so that one is refused and the apply goes instead."""
    a = _record(tmp_path, "apply", "A")
    b = _record(tmp_path, "patch", "B")
    u1 = _record(tmp_path, "undo", "undo B", undo_of=b.id)
    c = _record(tmp_path, "patch", "C")
    _record(tmp_path, "undo", "redo B", undo_of=u1.id)
    d = _record(tmp_path, "patch", "D")

    assert len(_files(tmp_path)) == 5
    assert u1.id in _files(tmp_path) and a.id not in _files(tmp_path)
    order = []
    while journal_stack.undo_floor(tmp_path, PRIMARY) is None and journal_stack.top(
            tmp_path, PRIMARY) is not None:
        order.append(journal_stack.top(tmp_path, PRIMARY).id)
        _undo_top(tmp_path)
    assert order == [d.id, b.id]
    assert journal_stack.top(tmp_path, PRIMARY).id == c.id     # then the floor: A was pruned


def test_each_desks_newest_write_survives_however_old(tmp_path):
    """The backup was applied once, long ago; the primary then took six
    writes. The backup's apply is what amend and patch read as the plan on
    the backup, so it is never pruned -- it takes one of the five."""
    _record(tmp_path, "apply", "BACKUP-SHOW", desk=BACKUP)
    for n in range(6):
        _record(tmp_path, "patch", f"P{n}")
    assert len(_files(tmp_path)) == 5
    assert _desk_tag(tmp_path, BACKUP) == "BACKUP-SHOW"
    assert _desk_tag(tmp_path, PRIMARY) == "P5"
    assert journal_stack.top(tmp_path, BACKUP).kind == "apply"


def test_amend_and_patch_still_read_the_desks_plan_after_pruning(tmp_path, capsys):
    """`cli._desk_applied_plan` -- what amend --show and patch --show
    compare against -- after the stack has pruned past the desk's apply."""
    from atoo import cli

    show = bundle.Bundle(directory=tmp_path)
    _record(tmp_path, "apply", "SHOW")
    for n in range(7):
        _record(tmp_path, "patch", f"CHANGE {n}")
    plan, infos = cli._desk_applied_plan(show, PRIMARY, _plan("plan.json"))
    assert plan["meta"]["tag"] == "CHANGE 6"
    assert "this desk's newest write left on it" in infos[0]


# ---------------------------------------------------------------------------
# journals/: undo walks back inside the window and stops at its edge
# ---------------------------------------------------------------------------

def test_undo_steps_back_inside_the_window_and_the_floor_is_where_it_stops(tmp_path):
    _record(tmp_path, "apply", "SHOW")
    for n in range(1, 7):
        _record(tmp_path, "patch", f"P{n}")
    # Kept: P2..P6; the apply and P1 are pruned but still on the desk.
    assert [r["kind"] for r in journal_stack.pruned_rows(tmp_path)] == ["apply", "patch"]

    walked = []
    while journal_stack.undo_floor(tmp_path, PRIMARY) is None:
        walked.append(journal_stack.top(tmp_path, PRIMARY))
        _undo_top(tmp_path)
        # After each step the desk's plan is the write beneath, read from disk.
        assert _desk_tag(tmp_path) == f"P{6 - len(walked)}"
        assert len(_files(tmp_path)) <= 5
    assert [e.change is None for e in walked] == [True] * len(walked)
    assert len(walked) == 4                               # P6, P5, P4, P3
    floor = journal_stack.undo_floor(tmp_path, PRIMARY)
    assert floor.pruned and floor.id == journal_stack.pruned_rows(tmp_path)[-1]["id"]
    assert journal_stack.top(tmp_path, PRIMARY) is not None   # P2: still on the desk


def test_the_floor_is_per_desk(tmp_path):
    _record(tmp_path, "apply", "MON", desk=BACKUP)
    _record(tmp_path, "apply", "FOH")
    for n in range(5):
        _record(tmp_path, "patch", f"P{n}")
    # The FOH apply was pruned under the primary's patches; the backup's
    # only write was never pruned, so undoing it is allowed.
    assert journal_stack.undo_floor(tmp_path, BACKUP) is None


def _cli_bundle(tmp_path, takes: int):
    """A bundle whose stack holds `takes` applies, each renaming ch 1 from
    the take before ("Take 0" -> "Take 1" ...), recorded on the desk the
    fake console answers as (no serial, so matched by address)."""
    desk = journal_stack.desk_from_identity(None, "198.51.100.1")
    for n in range(1, takes + 1):
        _record(tmp_path, "apply", f"Take {n}", desk=desk, prior=f"Take {n - 1}")
    return desk


def _undo_cli(monkeypatch, console, show) -> int:
    from atoo import cli

    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return cli.main(["undo", "--show", str(show), "--console", "198.51.100.1", "--confirm"])


def test_undo_reaches_back_through_the_kept_window_then_refuses(tmp_path, monkeypatch, capsys):
    """The real command, against a fake desk: seven applies, so Take 1
    and Take 2 are pruned while still standing. Four undos walk ch 1 back
    from Take 7 to Take 3. Take 3 is then the desk's last kept write, with
    the pruned Take 2 beneath it, so the fifth undo is refused with nothing
    written -- undoing it would leave the desk holding a write no journal
    records."""
    _cli_bundle(tmp_path, 7)
    console = console_holding(__ch__1__name=("Take 7", "s"))

    for expect in ("Take 6", "Take 5", "Take 4", "Take 3"):
        assert _undo_cli(monkeypatch, console, tmp_path) == 0, capsys.readouterr()
        assert console.state["/ch/1/name"] == (expect, "s")
        assert len(_files(tmp_path)) <= 5
    capsys.readouterr()

    assert _undo_cli(monkeypatch, console, tmp_path) == 1
    err = capsys.readouterr().err
    assert console.state["/ch/1/name"] == ("Take 3", "s"), "the refusal wrote to the desk"
    assert "nothing more to undo on this desk" in err
    assert "keeps only the newest 5 entries" in err


def test_a_prune_that_limits_undo_says_so_at_info(tmp_path, capsys):
    """`record` hands back what it pruned while it still stood, and the
    commands' `_record_on_stack` says so (`cli._say_pruned`). A prune that
    takes only popped writes says nothing: undo has lost no reach."""
    from atoo import cli

    show = bundle.Bundle(directory=tmp_path)
    for n in range(5):
        _record(tmp_path, "apply", f"A{n}")
    _undo_top(tmp_path)
    quiet = _record(tmp_path, "patch", "P")              # prunes only popped A4 / its undo
    assert quiet.pruned_now == ()
    loud = _record(tmp_path, "patch", "Q")               # prunes A0, still standing
    assert [r["kind"] for r in loud.pruned_now] == ["apply"]
    cli._say_pruned(show, quiet)
    assert capsys.readouterr().out == ""
    cli._say_pruned(show, loud)
    out = capsys.readouterr().out
    assert "INFO" in out and "were pruned" in out and "Undo now reaches back" in out


def test_a_redo_of_an_undo_whose_target_was_pruned_is_refused(tmp_path, monkeypatch, capsys):
    from atoo import cli

    desk = journal_stack.desk_from_identity(None, "198.51.100.1")
    first = _record(tmp_path, "apply", "Take 1", desk=desk, prior="Take 0")
    undo = _record(tmp_path, "undo", "Take 0", desk=desk, undo_of=first.id, prior="Take 1")
    for n in range(2, 6):
        _record(tmp_path, "apply", f"Take {n}", desk=desk, prior=f"Take {n - 1}")
    assert not (journal_stack.stack_dir(tmp_path) / first.id).exists()
    assert (journal_stack.stack_dir(tmp_path) / undo.id).exists()
    assert journal_stack.pruned_target(tmp_path, undo) == first.id

    console = console_holding(__ch__1__name=("Take 5", "s"))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    code = cli.main(["undo", str(undo.path), "--console", "198.51.100.1", "--confirm",
                     "--out-of-order"])
    assert code == 1
    assert console.state["/ch/1/name"] == ("Take 5", "s")
    assert "whose journal has been pruned" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# journals/: what a pruned write still counts for
# ---------------------------------------------------------------------------

def test_a_full_apply_warning_still_counts_pruned_changes(tmp_path):
    _record(tmp_path, "apply", "SHOW")
    for n in range(1, 7):
        _record(tmp_path, "patch", f"P{n}", change={"number": n, "name": f"c{n}", "text": "t"})
    changes = journal_stack.changes_on_desk(tmp_path, PRIMARY)
    assert [c.change["number"] for c in changes] == [1, 2, 3, 4, 5, 6]
    assert [c.pruned for c in changes] == [True, False, False, False, False, False]
    warning = journal_stack.replaced_changes_diagnostic(tmp_path, PRIMARY)
    assert "6 change(s)" in warning.message and "(journal pruned)" in warning.message


def test_change_numbers_are_never_handed_out_twice(tmp_path):
    for n in range(1, 4):
        _record(tmp_path, "patch", f"P{n}", change={
            "number": journal_stack.next_change_number(tmp_path), "name": f"c{n}", "text": "t"})
    for n in range(6):
        _record(tmp_path, "apply", f"A{n}")           # every change pruned
    assert not [e for e in journal_stack.entries(tmp_path) if e.change]
    assert journal_stack.next_change_number(tmp_path) == 4


def test_promoting_a_pruned_change_says_why_it_cannot(tmp_path):
    from atoo import promote

    _record(tmp_path, "patch", "P1", change={"number": 1, "name": "horns", "text": "add horns"})
    for n in range(5):
        _record(tmp_path, "patch", f"P{n + 2}", change={"number": n + 2, "name": f"c{n}",
                                                        "text": "t"})
    with pytest.raises(promote.PromoteError, match="journal was pruned"):
        promote.find_change(tmp_path, "1")


# ---------------------------------------------------------------------------
# The top level holds plan files and inputs only
# ---------------------------------------------------------------------------

def test_the_file_picker_keeps_a_replaced_file_in_backups_not_the_top_level():
    """The served page says where the replaced file went (a rename that
    crosses into web/static is invisible to the Python suite otherwise)."""
    shell = (REPO / "atoo" / "web" / "static" / "shell.js").read_text()
    assert "kept as backups/" in shell
    assert bundle.BACKUPS == "backups"
