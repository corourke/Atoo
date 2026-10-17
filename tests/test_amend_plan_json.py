"""plan.json is written only by a build, reversing the
plan.json half.

**The history.** an earlier change found that a confirmed `amend --show DIR` left
`plan.json` describing the show from before it, so the next amend read the
strips it had just filled as somebody else's and placed the same horns a
second time. The maintainer's answer then (2026-09-24) was to REPLACE plan.json with
the amended show and keep the replaced plan in the amend's journal entry, so
undo could put it back.

**The decision now:** *"I don't think we should modify
plan.json unless we've modified the input list or the conventions file or
the instructions file, the inputs to plan.json."* So a confirmed amend (and a
confirmed patch) never touches plan.json. The hazard an earlier change closed stays closed
another way: every amend entry embeds the plan it left on its desk
(`journal_stack.DESK_PLAN_BLOCK`, per-desk journals), and the next amend of
that desk compares against THAT -- so amending again from the same rebuild
still finds nothing to add.

**Old entries still undo correctly.** An amend recorded between two earlier changes did replace plan.json and carries the replaced text (`bundle_plan`).
`_legacy_amend` below makes one, and the second half of this file checks
undo still restores it under the rules -- byte-identical, only while
plan.json is still what that amend wrote, and the redo re-installs it.

Every test runs the real CLI against a fake desk (`test_amend.DeskConsole`),
seeded from the frozen `tests/fixtures/applied-show.plan.json` scenario:
strips 1-19 ours, 20 somebody's "Podium" (named only on its source socket),
21-32 free, 33-40 never answering. The rebuild numbers the horns 20-22;
placement has to skip 20, so they land on 21-23. **Bundles are built in
`tmp_path`; nothing here reads a bundle under `examples/`.**
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import cli, journal_stack
from atoo.apply import _build_write_targets
from test_amend import _FACTORY, DeskConsole, amended_plan, applied_plan, occupancy_state

HORN_STRIPS = ("/ch/21", "/ch/22", "/ch/23")


def _seed(applied: dict) -> dict:
    """The desk: everything the applied plan wrote at its value; everything
    a build of the rebuild -- at the numbers it proposes AND at the numbers
    placement will give it -- at a factory value; and the occupancy read's
    three leaves per strip as `occupancy_state` describes the room."""
    state: dict = {}
    for plan in (amended_plan(), amended_plan(start=21), amended_plan(start=24)):
        for t in _build_write_targets(plan, set_fader_levels=True)[0]:
            state[t.address] = (_FACTORY[t.value_type], t.value_type)
    for t in _build_write_targets(applied, set_fader_levels=True)[0]:
        state[t.address] = (t.compute_value(None), t.value_type)
    for address, value in occupancy_state(plan=applied).values.items():
        state[address] = (value, "i" if isinstance(value, int) else "s")
    return state


@pytest.fixture
def desk(monkeypatch):
    """ONE desk for the whole test: every command opens the same console,
    so an undo finds on it what the amend before it wrote, and a second
    amend reads what the first one left."""
    console = DeskConsole(_seed(applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    return console


def _writes(console) -> list[str]:
    return ([a for a, _v, _t in console.set_param_calls]
            + [a for a, _p in console.set_node_calls])


def _bundle(tmp_path, rebuilt: dict | None = None) -> Path:
    show = tmp_path / "show"
    show.mkdir()
    # Deliberately NOT json.dumps(indent=2) + "\n": "untouched" means
    # byte-identical to the operator's own file, formatting and all.
    (show / "plan.json").write_text(json.dumps(applied_plan(), indent=4) + "\n\n")
    (show / "rebuilt.plan.json").write_text(
        json.dumps(rebuilt if rebuilt is not None else amended_plan(), indent=2))
    return show


def _amend(show: Path, *extra: str, confirm: bool = True) -> int:
    return cli.main(["amend", "--show", str(show),
                     "--amended-plan", str(show / "rebuilt.plan.json"),
                     "--console", "198.51.100.9", "--no-progress",
                     *(["--confirm"] if confirm else []), *extra])


def _undo(*argv: str) -> int:
    return cli.main(["undo", *argv, "--console", "198.51.100.9", "--confirm"])


def _desk_plan(entry) -> dict:
    return json.loads(entry.path.read_text())[journal_stack.DESK_PLAN_BLOCK]["plan"]


def _channels(plan: dict) -> dict[int, str]:
    return {c["channel"]: c["name"] for c in plan["channels"]}


# ======================================================================
# The hazard stays closed -- through the desk's journal, not plan.json
# ======================================================================


def test_a_second_amend_from_the_same_rebuild_places_nothing(tmp_path, desk, capsys):
    """**The test that matters most.** Amend a bundle from a rebuild that
    adds three horns; amend AGAIN from the same rebuild. The second run must
    find nothing to add and write nothing -- with plan.json never changed,
    because the desk's own journal entry says the horns are on ch:21-23.
    Asserted on the desk, not on what the command printed."""
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _amend(show) == 0, capsys.readouterr()
    first = _writes(desk)
    assert first, "the first amend has to write something for this to mean anything"
    assert {desk.state[f"/ch/{n}/name"][0] for n in (21, 22, 23)} == {
        "Trumpet", "Trombone", "T.Sax"}
    assert (show / "plan.json").read_bytes() == before
    capsys.readouterr()

    assert _amend(show) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert _writes(desk) == first, "the second amend wrote to the desk"
    for n in (24, 25, 26):
        assert desk.state[f"/ch/{n}/name"][0] in ("", f"CH{n:02d}"), \
            f"ch:{n} was given a duplicate horn"
    # ch:21-23 are OURS now, because the desk's journal entry says so...
    assert "22 ours, 1 theirs" in out
    assert "applied plan: the one this desk's newest write left on it" in out
    # ...and the horns are recognised as the same channels, not refused as
    # renumbered: the rebuild still numbers them 20-22.
    assert "22 unchanged\n" in out
    assert "renumbered" not in out.lower()
    assert "Nothing to add" in out
    assert (show / "plan.json").read_bytes() == before


def test_a_confirmed_amend_leaves_plan_json_byte_identical(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _amend(show) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert (show / "plan.json").read_bytes() == before
    assert "plan.json is unchanged -- only a build writes it" in out
    assert "now describes" not in out


def test_the_desk_entry_records_the_effective_plan_and_its_placements(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    assert _amend(show) == 0, capsys.readouterr()
    [entry] = journal_stack.entries(show)
    plan = _desk_plan(entry)
    channels = _channels(plan)
    assert (channels[21], channels[22], channels[23]) == ("Trumpet", "Trombone", "T.Sax")
    assert 20 not in channels, "the rebuild's proposed number is not where the horn went"
    assert plan["meta"]["amend_placements"] == {"ch:21": "ch:20", "ch:22": "ch:21",
                                                "ch:23": "ch:22"}
    trumpet = next(c for c in plan["channels"] if c["name"] == "Trumpet")
    assert "placed on ch:21 by `atoo amend`" in trumpet["provenance"]["channel"]
    # A new entry carries no replaced plan: there was no replacement.
    assert journal_stack.saved_plan(entry) is None
    assert journal_stack.PLAN_BLOCK not in json.loads(entry.path.read_text())


def test_the_desk_entry_carries_the_rebuilds_meta_and_conventions_stack(
        tmp_path, desk, capsys):
    """The `meta.conventions_stack` rides along in the plan the
    desk's entry records -- it is what a later patch compiles against."""
    rebuilt = amended_plan()
    stack = [{"layer": "house", "bundle_relative_path": "../house.md",
              "absolute_path": "/shows/house.md", "sha256": "ab" * 32}]
    rebuilt["meta"] = {**rebuilt.get("meta", {}), "conventions_stack": stack,
                       "generated_at": "2026-09-24T20:00:00+00:00"}
    show = _bundle(tmp_path, rebuilt=rebuilt)
    assert _amend(show) == 0, capsys.readouterr()
    [entry] = journal_stack.entries(show)
    meta = _desk_plan(entry)["meta"]
    assert meta["conventions_stack"] == stack
    assert meta["generated_at"] == "2026-09-24T20:00:00+00:00"


def test_a_third_amend_places_a_new_channel_and_keeps_the_horns_where_they_are(
        tmp_path, desk, capsys):
    """The placement memory is carried forward in the desk's entry: a later
    rebuild that adds a fourth horn, still numbering the first three 20-22,
    keeps them on 21-23 and puts the new one on a free strip."""
    show = _bundle(tmp_path)
    assert _amend(show) == 0, capsys.readouterr()
    rebuilt = amended_plan()
    bari = copy.deepcopy(rebuilt["channels"][-1])
    bari.update(channel=23, name="Bari", source={**bari["source"], "input": "Bari"},
                patch={"group": "A", "sockets": [24], "stated": True})
    rebuilt["channels"].append(bari)
    (show / "rebuilt.plan.json").write_text(json.dumps(rebuilt, indent=2))
    capsys.readouterr()

    assert _amend(show) == 0, capsys.readouterr()
    newest = journal_stack.entries(show)[-1]
    plan = _desk_plan(newest)
    channels = _channels(plan)
    assert (channels[21], channels[22], channels[23], channels[24]) == (
        "Trumpet", "Trombone", "T.Sax", "Bari")
    numbers = [c["channel"] for c in plan["channels"]]
    assert len(numbers) == len(set(numbers)), "two channels on one strip"
    assert desk.state["/ch/24/name"][0] == "Bari"
    assert plan["meta"]["amend_placements"] == {
        "ch:21": "ch:20", "ch:22": "ch:21", "ch:23": "ch:22", "ch:24": "ch:23"}


# ======================================================================
# Every other way an amend can end: plan.json is still untouched
# ======================================================================


@pytest.mark.parametrize("journal", [False, True], ids=["bare", "with-journal"])
def test_a_preview_leaves_plan_json_alone(tmp_path, desk, capsys, journal):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    extra = ("--journal", str(tmp_path / "preview.amend-journal.json")) if journal else ()
    assert _amend(show, *extra, confirm=False) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before
    assert _writes(desk) == []
    assert journal_stack.entries(show) == []


def test_an_amend_with_nothing_to_write_leaves_plan_json_alone(tmp_path, desk, capsys):
    show = _bundle(tmp_path, rebuilt=applied_plan())
    before = (show / "plan.json").read_bytes()
    assert _amend(show) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before


class _DropsMidRun(DeskConsole):
    """A desk whose socket fails after a few writes -- an amend that aborts
    PARTWAY, with some of its writes on the desk and some not."""

    fail_after = 5

    def _maybe_drop(self):
        if len(self.set_param_calls) + len(self.set_node_calls) >= self.fail_after:
            raise OSError(65, "No route to host")

    def set_param(self, address, value, value_type="f"):
        self._maybe_drop()
        return super().set_param(address, value, value_type)

    def set_node(self, address, command):
        self._maybe_drop()
        return super().set_node(address, command)


def test_an_aborted_amend_leaves_plan_json_alone_and_records_the_plan_it_started_from(
        tmp_path, monkeypatch, capsys):
    console = _DropsMidRun(_seed(applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()

    assert _amend(show) == 1
    captured = capsys.readouterr()
    assert _writes(console), "the run has to have written something first"
    assert (show / "plan.json").read_bytes() == before
    assert "aborted partway" in captured.err
    [entry] = journal_stack.entries(show)
    assert journal_stack.saved_plan(entry) is None
    block = json.loads(entry.path.read_text())[journal_stack.DESK_PLAN_BLOCK]
    assert "aborted partway" in block["left_by"]
    assert block["plan"] == applied_plan()


def test_plan_mode_leaves_the_plan_file_alone(tmp_path, desk, capsys):
    plan = tmp_path / "applied.json"
    plan.write_text(json.dumps(applied_plan(), indent=2))
    rebuilt = tmp_path / "rebuilt.json"
    rebuilt.write_text(json.dumps(amended_plan(), indent=2))
    before = plan.read_bytes()

    code = cli.main(["amend", "--plan", str(plan), "--amended-plan", str(rebuilt),
                     "--console", "198.51.100.9", "--no-progress", "--confirm",
                     "--journal", str(tmp_path / "amend-journal.json")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert _writes(desk)
    assert plan.read_bytes() == before
    assert f"{plan} was not changed -- only `atoo build` writes a plan" in out


def test_a_bundle_amend_from_another_plan_file_leaves_both_alone(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    other = tmp_path / "other.json"
    other.write_bytes((show / "plan.json").read_bytes())
    before, other_before = (show / "plan.json").read_bytes(), other.read_bytes()
    assert _amend(show, "--plan", str(other)) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before
    assert other.read_bytes() == other_before
    [entry] = journal_stack.entries(show)
    assert journal_stack.saved_plan(entry) is None


def test_a_run_with_mismatches_leaves_plan_json_and_records_its_intent(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    desk.reject_writes_to = {"/ch/21/fdr"}
    assert _amend(show) == 2
    capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before
    [entry] = journal_stack.entries(show)
    assert _channels(_desk_plan(entry))[21] == "Trumpet"


def test_undo_of_a_new_amend_leaves_plan_json_alone_and_says_why(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert _amend(show) == 0, capsys.readouterr()
    capsys.readouterr()
    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert (show / "plan.json").read_bytes() == before
    assert "only a build writes it, and that amend did not" in out
    for strip in HORN_STRIPS:
        assert desk.state[f"{strip}/name"][0] != "Trumpet"
    # With the amend popped, the desk's plan is the apply-less fallback
    # again, and a fresh amend places the horns once more.
    capsys.readouterr()
    assert _amend(show, confirm=False) == 0
    assert "3 added" in capsys.readouterr().out


# ======================================================================
# An amend recorded between two earlier changes still undoes correctly
# ======================================================================


def _legacy_amend(show: Path) -> tuple[bytes, bytes]:
    """Run an amend, then put the bundle in the state an amend recorded
    between two earlier changes left it in: plan.json replaced by the effective
    plan, and the replaced bytes kept in the entry's `bundle_plan` (and in
    its mirror, which is the same bytes). Returns `(before, written)`."""
    before = (show / "plan.json").read_bytes()
    assert _amend(show) == 0
    entry = [e for e in journal_stack.entries(show) if e.kind == "amend"][-1]
    payload = json.loads(entry.path.read_text())
    written = (json.dumps(payload[journal_stack.DESK_PLAN_BLOCK]["plan"], indent=2)
               + "\n").encode()
    payload[journal_stack.PLAN_BLOCK] = journal_stack.plan_block(before, written)
    text = json.dumps(payload, indent=2)
    entry.path.write_text(text)
    (show / "amend-journal.json").write_text(text)
    (show / "plan.json").write_bytes(written)
    return before, written


def test_undo_of_a_legacy_amend_restores_the_prior_plan_byte_identical(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    before, _written = _legacy_amend(show)
    capsys.readouterr()
    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before
    assert "plan.json put back" in capsys.readouterr().out
    for strip in HORN_STRIPS:
        assert desk.state[f"{strip}/name"][0] != "Trumpet"


def test_undo_of_a_legacy_amend_journal_named_explicitly_restores_it_too(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    before, _written = _legacy_amend(show)
    assert _undo(str(show / "amend-journal.json")) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before


def test_undo_after_the_operator_rebuilt_plan_json_leaves_it_and_warns(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _legacy_amend(show)
    rebuilt = json.dumps(amended_plan(start=21), indent=2) + "\n"
    (show / "plan.json").write_text(rebuilt)
    capsys.readouterr()

    assert _undo("--show", str(show)) == 0
    err = capsys.readouterr().err
    assert (show / "plan.json").read_text() == rebuilt
    assert "plan.json was NOT put back" in err and "rebuilt or edited" in err
    assert desk.state["/ch/21/name"][0] != "Trumpet"


def test_undo_after_the_operator_deleted_plan_json_does_not_recreate_it(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _legacy_amend(show)
    (show / "plan.json").unlink()
    assert _undo("--show", str(show)) == 0
    assert not (show / "plan.json").exists()
    assert "removed" in capsys.readouterr().err


def test_the_redo_of_a_legacy_amend_reinstalls_the_amended_plan(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    before, amended_bytes = _legacy_amend(show)
    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before

    [undo_entry] = [e for e in journal_stack.entries(show) if e.kind == "undo"]
    assert _undo(str(undo_entry.path)) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == amended_bytes
    assert desk.state["/ch/21/name"][0] == "Trumpet"

    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == before


def test_the_redo_leaves_a_plan_rebuilt_since_the_undo_alone(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _legacy_amend(show)
    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    (show / "plan.json").write_text('{"rebuilt": true}\n')
    [undo_entry] = [e for e in journal_stack.entries(show) if e.kind == "undo"]
    capsys.readouterr()
    assert _undo(str(undo_entry.path)) == 0
    assert (show / "plan.json").read_text() == '{"rebuilt": true}\n'
    assert "was NOT put back" in capsys.readouterr().err


def test_an_undo_that_left_the_plan_alone_gives_the_redo_nothing_to_install(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _legacy_amend(show)
    (show / "plan.json").write_text('{"mine": 1}\n')
    assert _undo("--show", str(show)) == 0
    [undo_entry] = [e for e in journal_stack.entries(show) if e.kind == "undo"]
    assert journal_stack.saved_plan(undo_entry) is None
    assert _undo(str(undo_entry.path)) == 0
    assert (show / "plan.json").read_text() == '{"mine": 1}\n'


def test_undo_only_leaves_a_legacy_amended_plan_in_place(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _before, amended_bytes = _legacy_amend(show)
    _undo("--show", str(show), "--only", "/ch/21/name")
    assert (show / "plan.json").read_bytes() == amended_bytes
    assert "--only reverses part of that run" in capsys.readouterr().err


def test_an_undo_preview_of_a_legacy_amend_says_what_confirm_would_do(
        tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _before, amended_bytes = _legacy_amend(show)
    capsys.readouterr()
    assert cli.main(["undo", "--show", str(show), "--console", "198.51.100.9"]) == 0
    assert (show / "plan.json").read_bytes() == amended_bytes
    assert "On --confirm, plan.json goes back" in capsys.readouterr().out


def test_an_undo_that_cannot_be_recorded_does_not_put_the_plan_back(
        tmp_path, desk, monkeypatch, capsys):
    show = _bundle(tmp_path)
    _before, amended_bytes = _legacy_amend(show)
    real = journal_stack.record

    def refuse_undo(bundle_dir, kind, *a, **k):
        if kind == "undo":
            raise journal_stack.JournalStackError("disk full")
        return real(bundle_dir, kind, *a, **k)

    monkeypatch.setattr(journal_stack, "record", refuse_undo)
    capsys.readouterr()
    _undo("--show", str(show))
    assert (show / "plan.json").read_bytes() == amended_bytes
    assert "could not be recorded on the journal stack" in capsys.readouterr().err


def test_a_tampered_saved_plan_is_not_restored(tmp_path, desk, capsys):
    show = _bundle(tmp_path)
    _before, amended_bytes = _legacy_amend(show)
    [entry] = journal_stack.entries(show)
    payload = json.loads(entry.path.read_text())
    payload["bundle_plan"]["replaced"] = '{"channels": []}'
    entry.path.write_text(json.dumps(payload, indent=2))
    (show / "amend-journal.json").write_text(json.dumps(payload, indent=2))
    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    assert (show / "plan.json").read_bytes() == amended_bytes


def test_undo_of_an_apply_never_touches_plan_json(tmp_path, desk, monkeypatch, capsys):
    """An apply writes plan.json's show to the desk; it never replaces the
    file, so its undo has no plan to put back and must not invent one."""
    import atoo.console as console_module
    from atoo.console import OscReply

    desk.identity = lambda: OscReply(
        address="/?", typetag="s", args=["WING,198.51.100.9,DESK,wing-compact,SER,3.1"])
    monkeypatch.setattr(type(desk), "__enter__", lambda self: self, raising=False)
    monkeypatch.setattr(type(desk), "__exit__", lambda self, *exc: False, raising=False)
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: desk)
    show = _bundle(tmp_path)
    before = (show / "plan.json").read_bytes()
    assert cli.main(["apply", "--show", str(show), "--console", "198.51.100.9",
                     "--confirm"]) in (0, 2), capsys.readouterr()
    assert [e.kind for e in journal_stack.entries(show)] == ["apply"]
    assert _undo("--show", str(show)) in (0, 2), capsys.readouterr()
    assert [e.kind for e in journal_stack.entries(show)] == ["apply", "undo"]
    assert (show / "plan.json").read_bytes() == before


def test_pruning_takes_the_saved_plan_with_its_entry(tmp_path, desk, capsys, monkeypatch):
    """Embedded, so `keep_limit` prunes it with the entry and nothing is
    orphaned."""
    from atoo import prune
    monkeypatch.setattr(prune, "KEEP", 1)
    show = _bundle(tmp_path)
    _legacy_amend(show)
    assert _undo("--show", str(show)) == 0, capsys.readouterr()
    names = sorted(p.name for p in journal_stack.stack_dir(show).iterdir())
    assert len(names) == 2 and journal_stack.INDEX in names
