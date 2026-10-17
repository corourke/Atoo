"""One bundle, two desks, applied and then amended -- per-desk journals.

*"Per-desk journal for both apply and amend ... undo
can only apply against correct desk / correct journal"*, revised the same
day: *"serial number is a fine idea. In general, I want to strictly track
journals and undo to the specific desk, but allow apply and subsequent
amends to be relatively permissive to allow for multiple desks or the IP
number changing on the desk (say, going from home network to gig
network)."*

**The defect this closes.** Amend the primary: `plan.json` becomes the
amended show. Amend the backup from the same rebuild, and it
reported "Nothing to add" -- amend decided which strips were "ours" from
`plan.json`, which now claimed the horns, so the backup's empty strips
21-23 were ours-and-running and it never got the channels. Every apply and
amend entry now carries the plan it left on its desk (`desk_plan`), and
`amend --show` reads the connected desk's own.

Everything here runs the real `atoo apply`, `amend` and `undo`
through `cli.main`, against fake desks (`test_amend.DeskConsole`) that
answer `/?` with their own identity -- `atoo.console.WingConsole` is
replaced, so `_open_console`'s identity handling is the real one. The plans
are the frozen `tests/fixtures/applied-show.plan.json` scenario
`test_amend.py` is built on; bundles are built in `tmp_path`, and nothing
here reads a bundle under `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import cli, journal_stack
from atoo.apply import _build_write_targets
from atoo.console import OscReply
from test_amend import _FACTORY, DeskConsole, amended_plan, applied_plan, occupancy_state

PRIMARY_IP, BACKUP_IP = "198.51.100.5", "198.51.100.6"
PRIMARY_ID = "WING,{ip},PRIMARY,wing-compact,S100231,3.1.0"
BACKUP_ID = "WING,{ip},BACKUP,wing-compact,S100587,3.1.0"
HORNS = ("Trumpet", "Trombone", "T.Sax")


class Desk(DeskConsole):
    """A fake WING that states its own identity on `/?` and can be opened
    the way every command opens one (`with WingConsole(...)` for apply,
    `_open_console` for amend and undo)."""

    def __init__(self, state: dict, identity: str):
        super().__init__(state)
        self.identity_template = identity
        self.ip = None
        self.raw_log = None

    def identity(self):
        return OscReply(address="/?", typetag="s",
                        args=[self.identity_template.format(ip=self.ip)])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fresh_state() -> dict:
    """A desk that has never had the show: every address a build of the
    show or the rebuild would touch at a factory value, and the occupancy
    read's leaves as an untouched desk answers them -- strip 20 somebody's
    "Podium" (on its socket, as a WING really puts it), 33-40 never
    answering, the rest factory. `apply` is what puts the show on it."""
    state: dict = {}
    for plan in (applied_plan(), amended_plan(), amended_plan(start=21),
                 amended_plan(start=24)):
        for t in _build_write_targets(plan, set_fader_levels=True)[0]:
            state[t.address] = (_FACTORY[t.value_type], t.value_type)
    empty = {"meta": {}, "channels": []}
    for address, value in occupancy_state(plan=empty).values.items():
        state[address] = (value, "i" if isinstance(value, int) else "s")
    return state


@pytest.fixture
def desks(monkeypatch):
    """Two desks on the network, reachable at their addresses. `desks[ip]`
    is whichever desk answers there -- a test moves a desk by re-keying."""
    primary = Desk(fresh_state(), PRIMARY_ID)
    backup = Desk(fresh_state(), BACKUP_ID)
    network = {PRIMARY_IP: primary, BACKUP_IP: backup}

    def connect(address, port=None, timeout=None, raw_log=None):
        desk = network[address]
        desk.ip = address
        return desk

    monkeypatch.setattr("atoo.console.WingConsole", connect)
    NETWORK.clear()
    NETWORK.update(network)
    return network


#: The desks the current test's `desks` fixture put on the network, so
#: `apply_to` can reach the one it just applied to.
NETWORK: dict = {}


def podium_patched_by_hand(desk) -> None:
    """Somebody patches the Podium mic back onto ch 20 once the show is on.

    A full apply unpatches every strip its plan does not build
    (2026-10-02), so `fresh_state`'s Podium-shaped strip 20 -- LCL 20,
    named only on its socket -- reads free straight after `apply`. The
    scenario these tests are built on is a strip somebody ELSE is using
    when the amend runs, so it is put back the way a person at the desk
    would: the patch, nothing else."""
    desk.state["/ch/20/in/conn/grp"] = ("LCL", "s")


@pytest.fixture
def show(tmp_path):
    directory = tmp_path / "show"
    directory.mkdir()
    (directory / "plan.json").write_text(json.dumps(applied_plan(), indent=2) + "\n")
    (directory / "rebuilt.plan.json").write_text(json.dumps(amended_plan(), indent=2))
    return directory


def apply_to(show: Path, ip: str) -> int:
    # `--no-init`: `fresh_state` is stand-in factory values (0, ''), not a
    # real WING's initialized capture, so a reset to initialized would rewrite the occupancy these tests are about.
    code = cli.main(["apply", "--show", str(show), "--console", ip, "--confirm",
                     "--skip-verify", "--no-init"])
    if ip in NETWORK:
        podium_patched_by_hand(NETWORK[ip])
    return code


def amend(show: Path, ip: str, *extra: str) -> int:
    return cli.main(["amend", "--show", str(show),
                     "--amended-plan", str(show / "rebuilt.plan.json"),
                     "--console", ip, "--no-progress", "--confirm", *extra])


def undo(show: Path, ip: str, *extra: str) -> int:
    return cli.main(["undo", "--show", str(show), "--console", ip, "--confirm", *extra])


def horns_on(desk) -> tuple:
    return tuple(desk.state[f"/ch/{n}/name"][0] for n in (21, 22, 23))


def writes(desk) -> int:
    return len(desk.set_param_calls) + len(desk.set_node_calls)


def applied_to_both(show, desks, capsys):
    assert apply_to(show, PRIMARY_IP) == 0, capsys.readouterr()
    assert apply_to(show, BACKUP_IP) == 0, capsys.readouterr()
    capsys.readouterr()


# ======================================================================
# THE test: amend the primary, then the backup from the same rebuild
# ======================================================================


def test_amending_the_backup_after_the_primary_gives_it_the_channels(
        show, desks, capsys):
    """**The test that matters most.** Apply to both desks; amend the
    primary from a rebuild that adds three horns; amend the backup from the
    SAME rebuild. The backup must get the horns -- asserted on the backup.

    Before per-desk plans it reported "Nothing to add": plan.json was the
    primary's amended show, so ch:21-23 were "ours" on the backup too, and
    their empty strips were taken to be running channels.

    Mutation-checked: make `_desk_applied_plan` return `(None, ...)` (read
    plan.json again) and the backup says "Nothing to add" with its strips
    21-23 empty."""
    primary, backup = desks[PRIMARY_IP], desks[BACKUP_IP]
    applied_to_both(show, desks, capsys)

    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    assert horns_on(primary) == HORNS
    assert horns_on(backup) == ("CH21", "CH22", "CH23"), "the primary's amend reached the backup"
    capsys.readouterr()

    before = writes(backup)
    assert amend(show, BACKUP_IP) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert horns_on(backup) == HORNS, out
    assert writes(backup) > before
    assert "Nothing to add" not in out
    # It said where the applied plan came from, and that plan.json differs.
    assert "applied plan: the one this desk's newest write left on it" in out
    assert "-apply-S100587.json" in out
    # ...and the backup's own amend is on the stack, on the backup.
    top = journal_stack.top(show, journal_stack.desk_from_identity(
        [BACKUP_ID.format(ip=BACKUP_IP)], BACKUP_IP))
    assert top.kind == "amend" and top.serial == "S100587"


def test_a_second_amend_of_the_same_desk_still_places_nothing(show, desks, capsys):
    """The guarantee survives per desk: amending the primary twice from
    the same rebuild writes nothing the second time -- the primary's own
    plan now claims the horns."""
    primary = desks[PRIMARY_IP]
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    capsys.readouterr()
    before = writes(primary)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert writes(primary) == before
    assert "Nothing to add" in out


def test_every_apply_and_amend_entry_embeds_the_plan_it_left_on_its_desk(
        show, desks, capsys):
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    apply_a, apply_b, amend_a = journal_stack.entries(show)
    for entry, expect in ((apply_a, applied_plan()), (apply_b, applied_plan())):
        block = json.loads(entry.path.read_text())[journal_stack.DESK_PLAN_BLOCK]
        assert block["plan"] == expect and block["left_by"] == "the applied plan"
    block = json.loads(amend_a.path.read_text())[journal_stack.DESK_PLAN_BLOCK]
    assert block["left_by"] == "the effective plan"
    # The amended show lives in the desk's entry, and ONLY there: plan.json
    # is written by a build alone.
    assert {c["name"] for c in block["plan"]["channels"]} >= {"Trumpet", "Trombone", "T.Sax"}
    assert json.loads((show / "plan.json").read_text()) == applied_plan()
    # Embedded: still one file per entry.
    assert sorted(p.name for p in journal_stack.stack_dir(show).iterdir()) == sorted(
        [e.id for e in (apply_a, apply_b, amend_a)] + [journal_stack.INDEX])


# ======================================================================
# Undo, per desk
# ======================================================================


def test_undo_on_the_backup_pops_its_amend_and_restores_its_applied_plan(
        show, desks, capsys):
    """Undo on the backup reverses the backup's amend -- the horns come off
    the backup and stay on the primary -- and the backup's applied plan is
    the one beneath it again, so amending it once more places them again.
    The primary's is untouched: amending it again still finds nothing."""
    primary, backup = desks[PRIMARY_IP], desks[BACKUP_IP]
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    assert amend(show, BACKUP_IP) == 0, capsys.readouterr()
    capsys.readouterr()

    assert undo(show, BACKUP_IP) == 0, capsys.readouterr()
    assert horns_on(backup) != HORNS, "the backup's amend was not reversed"
    assert horns_on(primary) == HORNS, "undo on the backup reached the primary"
    backup_desk = journal_stack.desk_from_identity([BACKUP_ID.format(ip=BACKUP_IP)], BACKUP_IP)
    primary_desk = journal_stack.desk_from_identity(
        [PRIMARY_ID.format(ip=PRIMARY_IP)], PRIMARY_IP)
    entry, plan = journal_stack.desk_plan(show, backup_desk)
    assert entry.kind == "apply" and plan == applied_plan()
    entry, plan = journal_stack.desk_plan(show, primary_desk)
    assert entry.kind == "amend" and [c["name"] for c in plan["channels"]][-3:] == list(HORNS)
    capsys.readouterr()

    assert amend(show, BACKUP_IP) == 0, capsys.readouterr()
    assert horns_on(backup) == HORNS
    capsys.readouterr()
    before = writes(primary)
    assert amend(show, PRIMARY_IP) == 0
    assert writes(primary) == before and "Nothing to add" in capsys.readouterr().out


def test_the_primarys_journal_is_refused_on_the_backup_with_no_override(
        show, desks, capsys):
    """Named explicitly while connected to the backup: refused, naming both
    desks, nothing written -- and there is no flag that overrides it.

    Mutation-checked: make `journal_stack.same_desk` return True and the
    backup's horns come off."""
    primary, backup = desks[PRIMARY_IP], desks[BACKUP_IP]
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    assert amend(show, BACKUP_IP) == 0, capsys.readouterr()
    amend_a = [e for e in journal_stack.entries(show)
               if e.kind == "amend" and e.serial == "S100231"][0]
    capsys.readouterr()

    before = writes(backup)
    code = cli.main(["undo", str(amend_a.path), "--console", BACKUP_IP, "--confirm"])
    err = capsys.readouterr().err
    assert code == 1
    assert writes(backup) == before and horns_on(backup) == HORNS
    assert "PRIMARY" in err and "BACKUP" in err
    assert "S100231" in err and "S100587" in err
    assert "--other-desk" not in err

    with pytest.raises(SystemExit) as exc:
        cli.main(["undo", str(amend_a.path), "--console", BACKUP_IP, "--confirm",
                  "--other-desk"])
    assert exc.value.code == 2
    assert writes(backup) == before


def test_a_desk_that_moved_networks_is_the_same_desk_for_undo_and_amend(
        show, desks, capsys):
    """The maintainer's home-network-to-gig-network case. The primary is applied
    and amended at 198.51.100.5, then comes up at 203.0.113.20 with the same
    serial. Amend finds its plan by serial (nothing to add), and undo pops
    its amend -- both saying, at INFO, that the address changed."""
    primary = desks[PRIMARY_IP]
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    desks["203.0.113.20"] = desks.pop(PRIMARY_IP)
    capsys.readouterr()

    before = writes(primary)
    assert amend(show, "203.0.113.20") == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert writes(primary) == before and "Nothing to add" in out
    assert "INFO that write reached serial S100231 at 198.51.100.5" in out
    assert "203.0.113.20" in out

    assert undo(show, "203.0.113.20") == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert horns_on(primary) != HORNS
    assert "INFO this journal was written to serial S100231 at 198.51.100.5" in out
    undo_entry = journal_stack.entries(show)[-1]
    assert undo_entry.kind == "undo" and undo_entry.address == "203.0.113.20"
    assert undo_entry.id.endswith("-undo-S100231.json")


def test_a_different_desk_at_the_same_address_is_refused(show, desks, capsys):
    """The backup brought up on the primary's IP is still the backup: the
    primary's amend is not its to reverse, and nothing on it is its own."""
    backup = desks[BACKUP_IP]
    assert apply_to(show, PRIMARY_IP) == 0, capsys.readouterr()
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    desks[PRIMARY_IP] = backup                  # the backup, at the primary's address
    capsys.readouterr()

    before = writes(backup)
    code = undo(show, PRIMARY_IP)
    err = capsys.readouterr().err
    assert code == 1 and writes(backup) == before
    assert "nothing to undo on this desk" in err and "PRIMARY" in err

    amend_a = journal_stack.entries(show)[-1]
    code = cli.main(["undo", str(amend_a.path), "--console", PRIMARY_IP, "--confirm"])
    err = capsys.readouterr().err
    assert code == 1 and writes(backup) == before
    assert "S100231" in err and "S100587" in err


# ======================================================================
# Amend's fallback, and the different-desk warning
# ======================================================================


def test_a_desk_with_no_entry_falls_back_to_plan_json_and_says_so(show, desks, capsys):
    """A new backup that has never been written from this bundle -- but
    has had the show put on it by hand, or from another bundle -- amends
    against plan.json, with an INFO. Not refused."""
    backup = desks[BACKUP_IP]
    for t in _build_write_targets(applied_plan(), set_fader_levels=True)[0]:
        backup.state[t.address] = (t.compute_value(None), t.value_type)
    for address, value in occupancy_state(plan=applied_plan()).values.items():
        backup.state[address] = (value, "i" if isinstance(value, int) else "s")
    assert apply_to(show, PRIMARY_IP) == 0, capsys.readouterr()
    capsys.readouterr()

    assert amend(show, BACKUP_IP) == 0, capsys.readouterr()
    captured = capsys.readouterr()
    assert horns_on(backup) == HORNS
    info = next(line for line in captured.out.splitlines() if "INFO no write" in line)
    assert "S100587" in info and "so the applied plan is plan.json" in info
    assert "may describe a different desk" not in captured.err


def test_amending_a_desk_the_plan_was_never_applied_to_warns(show, desks, capsys):
    """The safety net. The backup has nothing on it and no entry, so amend
    falls back to plan.json -- which claims ch:1-19 as running, and every
    one of them reads empty here. Warned, clearly; never refused.

    Mutation-checked: drop the `_claimed_but_empty_warning` print and this
    fails."""
    assert apply_to(show, PRIMARY_IP) == 0, capsys.readouterr()
    capsys.readouterr()
    review = show.parent / "review.json"
    code = cli.main(["amend", "--show", str(show),
                     "--amended-plan", str(show / "rebuilt.plan.json"),
                     "--console", BACKUP_IP, "--no-progress", "--review-json", str(review)])
    captured = capsys.readouterr()
    assert code == 0, captured
    assert "WARNING: the applied plan claims 19 strip(s)" in captured.err
    assert "may describe a different desk" in captured.err
    assert "ch:1, ch:2" in captured.err
    # The Amend screen gets it too, with where the plan came from.
    payload = json.loads(review.read_text())
    assert any("may describe a different desk" in w for w in payload["warnings"])
    assert any("so the applied plan is plan.json" in i for i in payload["infos"])


def test_an_offline_review_says_it_read_plan_json(show, desks, capsys, tmp_path):
    """`--state` contacts no desk, so there is no desk's plan to read."""
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    state = tmp_path / "state.json"
    state.write_text(json.dumps(occupancy_state(plan=applied_plan()).values))
    capsys.readouterr()
    code = cli.main(["amend", "--show", str(show), "--amended-plan",
                     str(show / "rebuilt.plan.json"), "--state", str(state)])
    out = capsys.readouterr().out
    assert code in (0, 2), out
    assert "no desk was contacted (--state), so the applied plan is plan.json" in out


def test_a_stated_plan_is_used_as_given(show, desks, capsys):
    """`amend --show DIR --plan FILE` reads the plan named, whatever the
    desk's entry says: somebody stated it."""
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    capsys.readouterr()
    stated = show.parent / "stated.plan.json"
    stated.write_text(json.dumps(applied_plan()))
    code = cli.main(["amend", "--show", str(show), "--plan", str(stated),
                     "--amended-plan", str(show / "rebuilt.plan.json"),
                     "--console", PRIMARY_IP, "--no-progress"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "applied plan: the one this desk's newest write left on it" not in out
    assert "so the applied plan is plan.json" not in out


# ======================================================================
# File names
# ======================================================================


def test_file_names_carry_the_desks_serial(show, desks, capsys):
    applied_to_both(show, desks, capsys)
    assert amend(show, PRIMARY_IP) == 0, capsys.readouterr()
    assert undo(show, PRIMARY_IP) == 0, capsys.readouterr()
    names = [e.id for e in journal_stack.entries(show)]
    assert [journal_stack.parse_entry_name(n)["kind"] for n in names] == [
        "apply", "apply", "amend", "undo"]
    assert [journal_stack.parse_entry_name(n)["desk"] for n in names] == [
        "S100231", "S100587", "S100231", "S100231"]
    # ...and both are recorded in the journal and the index row.
    index = json.loads((journal_stack.stack_dir(show) / "index.json").read_text())
    assert [(r["serial"], r["address"]) for r in index["entries"]] == [
        ("S100231", PRIMARY_IP), ("S100587", BACKUP_IP), ("S100231", PRIMARY_IP),
        ("S100231", PRIMARY_IP)]
    for entry in journal_stack.entries(show):
        desk = json.loads(entry.path.read_text())["stack_entry"]["desk"]
        assert desk["address"] and desk["serial"]
