"""A full apply resets the desk to its initialized state first -- an earlier change.

*"We still need to first initialize the console before
we do a full apply so that the console is in a known state."* Atoo
reads the desk, writes back every setting that differs from the model's
initialized capture (except what the plan sets itself and the skip-list),
then writes the plan.

The desks here are `tests/snap_desk.SnapDesk`, built from the frozen
captures under `tests/fixtures/`, never from `examples/`. The capture the
code resets FROM is package data (`atoo/initialized/`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atoo import cli
from atoo import initialize as init
from atoo.apply import _build_write_targets, apply_plan, full_apply_targets
from atoo.undo import load_journal, undo_from_journal
from tests.snap_desk import SnapDesk, snap_values
from tests.test_full_apply import tiny

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIXPIECE = FIXTURES / "sixpiece_2026-10-02.plan.json"
COMPACT_SNAP = FIXTURES / "console-runs" / "Initialized-Compact.snap"
CHURCH_FULL = FIXTURES / "console-runs" / "Church-Full.snap"


def compact() -> init.Capture:
    return init.load_capture("wing-compact")


def desk_with(changes: dict) -> SnapDesk:
    """A WING Compact exactly as initialized, plus `changes` ({address: value})."""
    values = {leaf.address: leaf.value for leaf in compact().leaves}
    values.update(changes)
    return SnapDesk(values)


def initialized_desk() -> SnapDesk:
    return desk_with({})


def reset_records(result):
    return [r for r in result.writes if r.description.startswith(init.DESCRIPTION)]


def note(result) -> str:
    [line] = [w for w in result.warnings if w.startswith("INFO reset to initialized")]
    return line


# ======================================================================
# The capture: package data, parsed into (address, type, value)
# ======================================================================


def test_every_capture_in_the_table_is_package_data_and_vice_versa():
    files = {p.name for p in init.CAPTURE_DIR.glob("*.snap")}
    assert files == {file for file, _source in init.CAPTURES.values()}
    assert set(init.CAPTURES) == {"wing-compact", "wing-full"}


@pytest.mark.parametrize("model", ["wing-compact", "wing-full"])
def test_the_packaged_capture_is_the_frozen_initialized_capture(model):
    """Byte for byte the same desk export the tests' frozen copies are."""
    frozen = {"wing-compact": COMPACT_SNAP,
              "wing-full": FIXTURES / "Initialized-Full.snap"}[model]
    packaged = init.CAPTURE_DIR / init.CAPTURES[model][0]
    assert packaged.read_bytes() == frozen.read_bytes()


def test_capture_leaves_are_typed_for_the_desk():
    leaves = {leaf.address: leaf for leaf in compact().leaves}
    assert len(leaves) == 21122
    assert (leaves["/ch/1/fdr"].value_type, leaves["/ch/1/fdr"].value) == ("f", -144.0)
    assert (leaves["/ch/1/mute"].value_type, leaves["/ch/1/mute"].value) == ("i", 0)
    assert (leaves["/ch/1/in/conn/grp"].value_type, leaves["/ch/1/in/conn/grp"].value) == (
        "s", "LCL")
    assert (leaves["/ch/1/in/conn/in"].value_type, leaves["/ch/1/in/conn/in"].value) == ("i", 1)
    # A list choice whose JSON is a number is written as the desk's token.
    assert (leaves["/ch/1/dyn/ratio"].value_type, leaves["/ch/1/dyn/ratio"].value) == (
        "s", "3.0")
    assert leaves["/ch/1/main/1/on"].value == 1
    assert leaves["/ch/1/send/1/lvl"].value == -144.0


def test_a_leaf_with_no_known_type_is_not_settable():
    leaves = {leaf.address: leaf for leaf in compact().leaves}
    unsettable = sorted(a for a, leaf in leaves.items() if leaf.value_type is None)
    assert unsettable == ["/cfg/mon/1/lvl", "/cfg/mon/2/lvl", "/cfg/talk/lvl", "/rec/path"]


def test_the_full_size_capture_differs_from_the_compact_only_where_the_desks_do():
    """Its channel run stops at LCL 8, and its AES50 A preamps sit at 0.5."""
    full = {leaf.address: leaf.value for leaf in init.load_capture("wing-full").leaves}
    small = {leaf.address: leaf.value for leaf in compact().leaves}
    differ = {a for a in full if full[a] != small[a]}
    assert {a for a in differ if a.startswith("/ch/")} == {
        f"/ch/{n}/in/conn/{leaf}" for n in range(9, 25) for leaf in ("grp", "in")}
    assert {a for a in differ if not a.startswith("/ch/")} == {
        f"/io/in/A/{n}/g" for n in range(1, 33)}


def test_the_rack_has_no_capture():
    assert init.load_capture("wing-rack") is None
    assert init.load_capture(None) is None


# ======================================================================
# The skip-list: one named place, each entry with its reason
# ======================================================================


@pytest.mark.parametrize("address,key", [
    ("/$syscfg/ip0", "system"),
    ("/$globals/clksrc", "system"),
    ("/cards/wmadi/rxclock", "cards"),
    ("/cards/wlive/1/cfg/playmode", "cards"),
    ("/cfg/rta/rtasrc", "display"),
    ("/cfg/mtr/mainmtr", "display"),
    ("/cfg/mon/1/src", "listening"),
    ("/cfg/solo/mode", "listening"),
])
def test_the_skip_list(address, key):
    assert init.skip_rule(address).key == key


@pytest.mark.parametrize("address", [
    "/ch/1/fdr", "/io/in/LCL/3/vph", "/cfg/talk/A/B1", "/cfg/mainlink", "/fx/1/mdl",
    "/io/out/LCL/1/grp", "/play/repeat"])
def test_a_show_setting_is_not_on_the_skip_list(address):
    assert init.skip_rule(address) is None


def test_every_skip_rule_says_why():
    for rule in init.SKIP_LIST:
        assert rule.reason and rule.label
    assert len({rule.key for rule in init.SKIP_LIST}) == len(init.SKIP_LIST)


def test_nothing_on_the_skip_list_is_ever_written():
    desk = desk_with({"/cfg/rta/rtasrc": 19, "/cfg/mon/1/src": "MTX.1",
                      "/cards/wmadi/mode": "BNC", "/ch/5/fdr": -10.0})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model="wing-compact")
    written = {a for a, _v in desk.writes}
    assert "/ch/5/fdr" in written
    assert not written & {"/cfg/rta/rtasrc", "/cfg/mon/1/src", "/cards/wmadi/mode"}
    assert desk.values["/cfg/rta/rtasrc"] == 19
    assert "on the skip-list (meter/RTA display)" in note(result)


# ======================================================================
# Diff only
# ======================================================================


def test_an_initialized_desk_gets_no_reset_writes():
    plan = tiny(("ch", 1, "Kick"))
    desk = initialized_desk()
    result = apply_plan(plan, desk, dry_run=False, full_apply=True, initialize=True,
                        init_model="wing-compact")
    assert [r for r in reset_records(result) if r.status in ("match", "mismatch")] == []
    assert "nothing written" in note(result)


def test_only_the_leaves_that_differ_are_written():
    changes = {"/ch/30/fdr": -6.0, "/ch/30/name": "Old show", "/bus/3/mute": 1,
               "/io/in/A/12/vph": 1, "/mtx/2/col": 7}
    desk = desk_with(changes)
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model="wing-compact")
    reset = reset_records(result)
    assert {r.address for r in reset} == set(changes)
    assert all(r.status == "match" for r in reset)
    initial = {leaf.address: leaf.value for leaf in compact().leaves}
    for address in changes:
        assert desk.values[address] == initial[address]
    assert "5 setting(s) written -- " in note(result)


def test_a_value_within_apply_s_tolerance_is_not_rewritten():
    """`_values_equal`, the stepped-parameter tolerance -- the same rule
    apply uses to skip a write."""
    initial = {leaf.address: leaf.value for leaf in compact().leaves}
    desk = desk_with({"/ch/30/flt/lcf": initial["/ch/30/flt/lcf"] * 1.001})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=True, full_apply=True,
                        initialize=True, init_model="wing-compact")
    assert reset_records(result) == []


def test_the_desk_is_read_by_node_dump_and_reset_baselines_are_not_asked_again():
    desk = desk_with({"/ch/30/fdr": -6.0})
    apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=True, full_apply=True,
               initialize=True, init_model="wing-compact")
    assert "/ch/30" in desk.dumps
    assert "/ch/30/fdr" not in desk.gets


# ======================================================================
# Order: reset before the plan; selectors first; mutes last
# ======================================================================


def test_the_reset_comes_before_every_plan_write():
    desk = desk_with({"/ch/30/fdr": -6.0, "/bus/5/name": "X"})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=True, full_apply=True,
                        initialize=True, init_model="wing-compact")
    kinds = ["reset" if r.description.startswith(init.DESCRIPTION) else "plan"
             for r in result.writes]
    assert kinds == sorted(kinds, key=lambda k: k != "reset")
    assert kinds[0] == "reset"


def test_selectors_first_then_values_then_switches_then_mutes():
    desk = desk_with({"/ch/30/dyn/mdl": "LA", "/ch/30/dyn/on": 1, "/ch/30/mute": 1,
                      "/ch/30/fdr": -6.0, "/ch/31/eq/mdl": "SOUL"})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=True, full_apply=True,
                        initialize=True, init_model="wing-compact")
    order = [r.address for r in reset_records(result)]
    assert order.index("/ch/30/dyn/mdl") < order.index("/ch/30/fdr")
    assert order.index("/ch/31/eq/mdl") < order.index("/ch/30/fdr")
    assert order.index("/ch/30/fdr") < order.index("/ch/30/dyn/on") < order.index("/ch/30/mute")


def test_a_selector_the_reset_changes_forces_the_values_it_governs():
    """The rule: `dyn/thr` already reads the initialized -10 under
    the old model, but the desk re-reads it when the model changes, so it
    is written after the model whatever the read said."""
    desk = desk_with({"/ch/30/dyn/mdl": "LA"})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model="wing-compact")
    by = {r.address: r for r in reset_records(result)}
    assert by["/ch/30/dyn/thr"].forced_by == "/ch/30/dyn/mdl"
    assert by["/ch/30/dyn/thr"].status == "match"
    order = [r.address for r in result.writes]
    assert order.index("/ch/30/dyn/mdl") < order.index("/ch/30/dyn/thr")
    assert "forced by a selector it changes" in note(result)


def test_a_value_not_on_the_desk_under_its_old_selector_is_written_after_it():
    """The desk's gate is PSE, which has no `ratio`; the reset puts GATE
    back, and the capture's `ratio` with it -- no GET is spent on a leaf
    the dump showed was not there."""
    desk = desk_with({"/ch/30/gate/mdl": "PSE"})
    desk.hidden.add("/ch/30/gate/ratio")
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model="wing-compact")
    by = {r.address: r for r in reset_records(result)}
    assert by["/ch/30/gate/ratio"].prior_value is None
    assert by["/ch/30/gate/ratio"].status == "match"
    assert desk.values["/ch/30/gate/ratio"] == "1:3"
    # Its only GET is the readback after the write.
    assert desk.gets.count("/ch/30/gate/ratio") == 1


def test_a_value_under_a_selector_the_plan_sets_to_another_model_is_left_alone():
    """The plan's own gate model wins; the capture's gate values are for
    the capture's model and mean something else under the plan's."""
    plan = json.loads(SIXPIECE.read_text())
    targets = {t.address: t for t in _build_write_targets(plan, True)[0]}
    selector = next(a for a in targets if a.endswith("/gate/mdl")
                    and targets[a].compute_value(None) != "GATE")
    node = selector.rpartition("/")[0]
    desk = initialized_desk()
    result = apply_plan(plan, desk, dry_run=True, full_apply=True, initialize=True,
                        init_model="wing-compact")
    reset_addresses = {r.address for r in reset_records(result)}
    assert not {a for a in reset_addresses if a.startswith(node + "/")}
    assert "under a selector the plan sets to another model" in note(result)


# ======================================================================
# A mono bus's width -- an earlier change
# ======================================================================

APPLY_EXCERPT = FIXTURES / "console-runs" / "2026-10-02-sixpiece-apply-excerpt.json"
_BUS_LEAF = re.compile(r"^(/bus/\d+)/(wid|busmono)$")


class MonoHoldingDesk(SnapDesk):
    """A SnapDesk that holds a bus's `wid` at 0 while its `busmono` is 1,
    as the Compact did on 2026-10-02."""

    def _store(self, address, value):
        super()._store(address, value)
        match = _BUS_LEAF.match(address)
        if match and self.values.get(match.group(1) + "/busmono") == 1:
            self.values[match.group(1) + "/wid"] = 0.0


def mono_desk(changes: dict) -> MonoHoldingDesk:
    values = {leaf.address: leaf.value for leaf in compact().leaves}
    values.update(changes)
    return MonoHoldingDesk(values)


def _mono(*buses: int) -> dict:
    out = {}
    for n in buses:
        out.update({f"/bus/{n}/busmono": 1, f"/bus/{n}/wid": 0.0})
    return out


def test_the_evidence_a_mono_bus_holds_its_width_at_zero():
    """What the rule rests on, frozen: every bus captured with `busmono` 1
    holds `wid` 0, and on 2026-10-02 the Compact read back 0 for every
    width written to a bus whose `busmono` was 1 -- and only for those."""
    mono_buses = 0
    for snap in sorted(FIXTURES.rglob("*.snap")):
        buses = json.loads(snap.read_text())["ae_data"].get("bus") or {}
        for node in buses.values():
            if isinstance(node, dict) and node.get("busmono") is True:
                mono_buses += 1
                assert node["wid"] == 0, snap.name
    assert mono_buses >= 4

    rows = json.loads(APPLY_EXCERPT.read_text())["writes"]
    mono = {r["address"].rpartition("/")[0] for r in rows
            if r["address"].endswith("/busmono") and r["prior_value"] == 1}
    widths = [r for r in rows if r["address"].endswith("/wid")]
    assert len(widths) == 6
    for row in widths:
        assert row["address"].rpartition("/")[0] in mono
        assert (row["intended_value"], row["readback_value"], row["status"]) == \
            (100.0, 0.0, "mismatch")


def test_the_width_of_a_bus_the_plan_leaves_mono_is_not_reset():
    plan = json.loads(SIXPIECE.read_text())
    mono = [entry["index"] for entry in plan["busses"].values() if entry.get("mono")]
    assert mono
    desk = mono_desk(_mono(*mono))
    result = apply_plan(plan, desk, dry_run=False, full_apply=True, initialize=True,
                        init_model="wing-compact")
    written = {r.address for r in result.writes}
    for n in mono:
        assert f"/bus/{n}/wid" not in written
    assert not [r for r in reset_records(result) if r.status == "mismatch"]
    assert f"{len(mono)} a mono bus's width (the desk holds it at 0)" in note(result)


def test_a_bus_the_reset_takes_back_to_stereo_gets_its_width_after_its_busmono():
    """An old show left bus 9 mono and the plan does not mention it: the
    reset puts `busmono` back to 0 first, then the width, which the desk
    now takes."""
    desk = mono_desk(_mono(9))
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model="wing-compact")
    by = {r.address: r for r in reset_records(result)}
    order = [r.address for r in result.writes]
    assert order.index("/bus/9/busmono") < order.index("/bus/9/wid")
    assert by["/bus/9/wid"].status == "match"
    assert desk.values["/bus/9/wid"] == 100.0


def test_a_bus_the_plan_makes_stereo_gets_its_width_after_the_plans_busmono():
    """The desk's bus is mono from an old show; the plan says stereo. The
    plan's `busmono` is moved into the reset's selector pass, so the
    width lands on a stereo bus."""
    plan = json.loads(SIXPIECE.read_text())
    stereo = next(entry["index"] for entry in plan["busses"].values()
                  if entry.get("mono") is False)
    desk = mono_desk(_mono(stereo))
    result = apply_plan(plan, desk, dry_run=False, full_apply=True, initialize=True,
                        init_model="wing-compact")
    order = [r.address for r in result.writes]
    assert order.index(f"/bus/{stereo}/busmono") < order.index(f"/bus/{stereo}/wid")
    width = next(r for r in reset_records(result) if r.address == f"/bus/{stereo}/wid")
    assert width.status == "match"
    assert desk.values[f"/bus/{stereo}/wid"] == 100.0


# ======================================================================
# The plan's own leaves: never written twice
# ======================================================================


def test_a_leaf_the_plan_writes_is_not_reset():
    plan = tiny(("ch", 1, "Kick"))
    desk = desk_with({"/ch/1/name": "Old", "/ch/1/fdr": -20.0, "/ch/2/in/conn/grp": "A"})
    result = apply_plan(plan, desk, dry_run=False, full_apply=True, initialize=True,
                        init_model="wing-compact")
    addresses = [r.address for r in result.writes]
    assert len(addresses) == len(set(addresses))
    reset = {r.address for r in reset_records(result)}
    assert "/ch/1/name" not in reset and "/ch/1/fdr" not in reset
    # The full apply's own unpatch is not a reset write either.
    assert "/ch/2/in/conn/grp" not in reset
    assert desk.values["/ch/1/name"] == "Kick"
    assert desk.values["/ch/2/in/conn/grp"] == "OFF"
    assert [a for a, _v in desk.writes].count("/ch/1/name") <= 1


def test_the_plans_tags_merge_into_the_initialized_value_not_the_old_show():
    """apply merges a strip's DCA tokens into what its tags hold, keeping
    any other text there; after a reset that is nothing, so an old show's
    own tag text (`OLDSHOW`) does not survive."""
    plan = tiny(("ch", 1, "Kick"))
    plan["channels"][0]["dca"] = ["Drums"]
    plan["dcas"] = {"Drums": {"index": 1}}
    desk = desk_with({"/ch/1/tags": "OLDSHOW"})
    apply_plan(plan, desk, dry_run=False, full_apply=True, initialize=True,
               init_model="wing-compact")
    assert "OLDSHOW" not in desk.values["/ch/1/tags"]
    plain = desk_with({"/ch/1/tags": "OLDSHOW"})
    apply_plan(plan, plain, dry_run=False, full_apply=True)
    assert "OLDSHOW" in plain.values["/ch/1/tags"]


# ======================================================================
# Journalled, and reversed by undo
# ======================================================================


def test_every_reset_write_is_journalled_and_undo_puts_the_desk_back(tmp_path):
    changes = {"/ch/30/fdr": -6.0, "/ch/30/dyn/mdl": "LA", "/bus/3/name": "Old",
               "/io/in/A/12/vph": 1, "/cfg/talk/A/B3": 1}
    desk = desk_with(changes)
    before = dict(desk.values)
    journal = tmp_path / "apply.json"
    apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, journal_path=str(journal),
               full_apply=True, initialize=True, init_model="wing-compact")
    rows = {w["address"]: w for w in json.loads(journal.read_text())["writes"]}
    for address, value in changes.items():
        assert rows[address]["prior_value"] == value
        assert rows[address]["description"].startswith(init.DESCRIPTION)
    undo_from_journal(load_journal(str(journal)), desk, dry_run=False)
    assert {a: desk.values[a] for a in changes} == changes
    assert desk.values == before


def test_church_full_round_trip_reset_is_idempotent_and_undone(tmp_path):
    """A heavily used full-size desk (the frozen Church-Full capture): the
    reset lands with no mismatch, a second run finds nothing to reset, and
    undo restores every value the desk had (the only leaves left over are
    ones the desk did not have before -- on a real desk they go away again
    with the selector undo restores)."""
    plan = json.loads(SIXPIECE.read_text())
    before = snap_values(CHURCH_FULL)
    desk = SnapDesk(before)
    journal = tmp_path / "apply.json"
    result = apply_plan(plan, desk, dry_run=False, journal_path=str(journal), full_apply=True,
                        initialize=True, init_model="wing-full")
    assert not result.mismatches
    again = apply_plan(plan, desk, dry_run=True, full_apply=True, initialize=True,
                       init_model="wing-full")
    assert reset_records(again) == []
    undo_from_journal(load_journal(str(journal)), desk, dry_run=False)
    rows = {w["address"]: w for w in json.loads(journal.read_text())["writes"]}

    def same(a, b):
        # The capture keeps some list-model values as text ("0.4"); the
        # desk takes them back as numbers.
        try:
            x, y = float(a), float(b)
        except (TypeError, ValueError):
            return a == b
        return abs(x - y) <= 1e-6 * max(1.0, abs(x))

    left = {a for a in desk.values if not same(desk.values[a], before.get(a))}
    # What is left is a leaf the desk did not have before, or one whose
    # prior could not be read as the kind of control the initialized
    # model has (a bus compressor's `rel` reading AUTO under another model):
    # journalled with no prior, so undo restores its selector and not it.
    assert left
    assert all(a not in before or rows[a]["prior_value"] is None for a in left), sorted(
        a for a in left if a in before and rows[a]["prior_value"] is not None)


# ======================================================================
# The boundary: only a full apply
# ======================================================================


def test_initialize_needs_a_full_apply():
    with pytest.raises(ValueError):
        apply_plan(tiny(("ch", 1, "Kick")), initialized_desk(), initialize=True,
                   init_model="wing-compact")


def test_apply_plan_does_not_reset_unless_asked():
    desk = desk_with({"/ch/30/fdr": -6.0})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=True, full_apply=True)
    assert reset_records(result) == []
    assert not any("initialized" in w for w in result.warnings)


def test_amend_patch_and_undo_never_initialize():
    """A text guard beside `test_full_apply.py`'s: the scoped commands
    never opt in to a reset."""
    root = Path(__file__).resolve().parents[1] / "atoo"
    for name in ("amend.py", "patch.py", "undo.py"):
        assert "initialize=" not in (root / name).read_text(), name


# ======================================================================
# A model with no capture: WARNING, and the plan still goes on
# ======================================================================


def test_the_rack_warns_and_the_plan_is_still_applied():
    desk = desk_with({"/ch/30/fdr": -6.0})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model="wing-rack")
    assert reset_records(result) == []
    [warning] = [w for w in result.warnings if w.startswith("WARNING not reset")]
    assert "no initialized capture for the WING Rack" in warning
    assert "save its show file (.snap)" in warning
    assert "attach it to a desk test report" in warning
    assert "freeze_initialized" not in warning
    assert desk.values["/ch/1/name"] == "Kick"
    assert desk.values["/ch/30/fdr"] == -6.0


def test_an_unresolved_desk_warns_and_the_plan_is_still_applied():
    desk = desk_with({})
    result = apply_plan(tiny(("ch", 1, "Kick")), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model=None, init_token="wing-mystery")
    [warning] = [w for w in result.warnings if w.startswith("WARNING not reset")]
    assert "'wing-mystery'" in warning
    assert desk.values["/ch/1/name"] == "Kick"


def test_no_init_is_said_at_info():
    result = apply_plan(tiny(("ch", 1, "Kick")), desk_with({}), dry_run=True,
                        full_apply=True, initialize=False)
    assert init.NO_INIT_NOTE in result.warnings


# ======================================================================
# The command: on by default, --no-init to skip
# ======================================================================


def _apply_cli(tmp_path, monkeypatch, capsys, *extra):
    desk = desk_with({"/ch/30/fdr": -6.0})
    monkeypatch.setattr("atoo.console.WingConsole", lambda *a, **k: desk)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(tiny(("ch", 1, "Kick"))))
    code = cli.main(["apply", "--plan", str(plan), "--console", "198.51.100.9", "--skip-verify",
                     *extra])
    return code, desk, capsys.readouterr()


def test_apply_resets_by_default(tmp_path, monkeypatch, capsys):
    code, desk, out = _apply_cli(tmp_path, monkeypatch, capsys, "--confirm")
    assert code == 0, out
    assert desk.values["/ch/30/fdr"] == -144.0
    assert "reset to initialized (WING Compact capture)" in out.err


def test_apply_no_init_skips_the_reset(tmp_path, monkeypatch, capsys):
    code, desk, out = _apply_cli(tmp_path, monkeypatch, capsys, "--confirm", "--no-init")
    assert code == 0, out
    assert desk.values["/ch/30/fdr"] == -6.0
    assert "--no-init" in out.err
    assert "reset to initialized (" not in out.err


def test_apply_dry_run_previews_the_reset(tmp_path, monkeypatch, capsys):
    code, desk, out = _apply_cli(tmp_path, monkeypatch, capsys)
    assert code == 0, out
    assert desk.writes == []
    assert "1 setting(s) would change -- 1 channel" in out.err
    assert "writing would take about" in out.err


# ======================================================================
# Apply's pre-flight
# ======================================================================


def test_preflight_note_for_a_model_with_a_capture():
    code, text = init.preflight_note(json.loads(SIXPIECE.read_text()), "wing-compact")
    assert code == "apply.init"
    assert text.startswith("INFO before writing the plan, a full apply resets the desk to the "
                           "WING Compact's initialized state")
    assert "--no-init" in text and "at the very most" in text


def test_preflight_note_for_the_rack_is_the_warning():
    code, text = init.preflight_note(json.loads(SIXPIECE.read_text()), "wing-rack")
    assert code == "apply.init-no-capture"
    assert text.startswith("WARNING not reset to initialized first")


def test_full_apply_targets_are_all_left_to_the_full_apply():
    """The unpatches and the talkback assign are the full apply's own
    writes, so the reset never writes them."""
    plan = json.loads(SIXPIECE.read_text())
    desk = initialized_desk()
    result = apply_plan(plan, desk, dry_run=True, full_apply=True, initialize=True,
                        init_model="wing-compact")
    reset = {r.address for r in reset_records(result)}
    assert not reset & {t.address for t in full_apply_targets(plan)}

