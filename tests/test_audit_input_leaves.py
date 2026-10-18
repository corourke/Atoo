"""CV008 over trim, balance, invert and head-amp gain, read from a live desk.

A plan that states `trim_db`, `balance_db`, `invert` or `gain_db` is compared
with the desk by CV008, but until `audit --plan` asked the desk for those
leaves they were in no read, so every strip the plan stated them on was
reported as "live console reads unread" -- 28 false warnings on a Compact
audited straight after a clean full apply of the Demo. These tests pin the
read (exactly the leaves the plan states, at no extra request under the
node-dump read), the comparison over a live-style read (desk differs, desk
matches), and the command line end to end on the simulated desk.

The desks are `tests/snap_desk`'s, built from the packaged initialized
capture, and the show is the packaged Demo. Nothing here reads `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import cli, console as console_module, firstrun
from atoo import initialize as init
from atoo.apply import apply_plan
from atoo.audit import (
    ConsoleState,
    console_read_plan,
    diff_against_plan,
    plan_processing_read_addresses,
    planned_input_leaves,
    read_console_state,
    socket_groups_to_read,
)
from tests.snap_desk import PairedSnapDesk, SnapDesk, snap_values

FIXTURES = Path(__file__).parent / "fixtures"
INITIALIZED_COMPACT = FIXTURES / "console-runs" / "Initialized-Compact.snap"
DEMO_PLAN = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME / "plan.json"
MODEL = "wing-compact"


def _entry(n=1, name="Kick", bank="ch", group="LCL", sockets=None, **processing):
    return {
        "channel": n, "bank": bank, "name": name,
        "source": {"input": name, "type": "Mic", "model": "", "stereo": False, "phantom": False},
        "patch": {"group": group, "sockets": sockets or [n], "stated": True},
        "processing": {"hpf_hz": None, "preset": None, **processing},
        "fader": {"fader_db": None, "muted": None}, "dca": [], "mute_group": [],
        "bus_sends": [], "main_routes": [{"index": 1}],
    }


def _plan(*entries) -> dict:
    return {"busses": {}, "dcas": {}, "mute_groups": {}, "outputs": {}, "channels": list(entries)}


def _cv008(state, plan):
    return [f for f in diff_against_plan(state, plan) if f.rule_id == "CV008"]


STATED = dict(trim_db=3.0, balance_db=-2.0, invert=True, gain_db=20.0)


def _as_planned() -> ConsoleState:
    """Channel 1 on LCL 1, every stated leaf where the plan has it."""
    return ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
        "/ch/1/in/set/trim": 3.0, "/ch/1/in/set/bal": -2.0, "/ch/1/in/set/inv": 1,
        "/io/in/LCL/1/g": 20.0,
    }, console_model=MODEL)


# --------------------------------------------------------------------------
# What a plan reads
# --------------------------------------------------------------------------


def test_the_leaves_to_read_are_exactly_the_ones_the_plan_states():
    plan = _plan(_entry(**STATED), _entry(2, "Snare", trim_db=0.0),
                 _entry(3, "Cue", bank="aux", group="A", sockets=[5, 6], gain_db=10.0, invert=False),
                 _entry(4, "Nothing"))
    assert dict(plan_processing_read_addresses(plan)) == {
        "/ch/1/in/set/trim": "f", "/ch/1/in/set/bal": "f", "/ch/1/in/set/inv": "i",
        "/io/in/LCL/1/g": "f",
        "/ch/2/in/set/trim": "f",
        "/aux/3/in/set/inv": "i", "/io/in/A/5/g": "f",
    }


def test_a_gain_is_asked_only_where_the_source_has_a_head_amp():
    """An AUX-group jack is line level with no head amp, and a strip with no
    patch has no source to ask about."""
    unpatched = _entry(2, "Open", gain_db=10.0)
    unpatched["patch"] = {"group": None, "sockets": [], "stated": False}
    plan = _plan(_entry(group="AUX", sockets=[1], gain_db=20.0), unpatched)
    assert plan_processing_read_addresses(plan) == []
    assert planned_input_leaves(_entry(group="A", sockets=[3], gain_db=1.0)) == [("/io/in/A/3/g", "f")]


def test_the_default_read_plan_is_not_moved_and_the_leaves_are_appended_once():
    base = console_read_plan()
    extra = plan_processing_read_addresses(_plan(_entry(**STATED)))
    assert console_read_plan(extra=extra + extra) == base + extra


# --------------------------------------------------------------------------
# What the comparison says over a read
# --------------------------------------------------------------------------


def test_a_desk_as_planned_has_no_cv008():
    assert _cv008(_as_planned(), _plan(_entry(**STATED))) == []


@pytest.mark.parametrize("leaf, value, word", [
    ("/ch/1/in/set/trim", 6.0, "trim is 3dB, live console reads 6dB"),
    ("/ch/1/in/set/bal", 0.0, "balance is -2dB, live console reads 0dB"),
    ("/ch/1/in/set/inv", 0, "invert=True, live console reads invert=False"),
    ("/io/in/LCL/1/g", 5.0, "head-amp gain on LCL 1 is 20dB, live console reads 5dB"),
])
def test_each_leaf_that_differs_is_one_finding_naming_both_values(leaf, value, word):
    state = _as_planned()
    state.values[leaf] = value
    [finding] = _cv008(state, _plan(_entry(**STATED)))
    assert word in finding.message
    assert finding.addresses == (leaf,)


def test_a_leaf_that_was_not_read_is_not_a_contradiction():
    """The desk did not answer: nothing was compared, so nothing is claimed."""
    state = _as_planned()
    for leaf in ("/ch/1/in/set/trim", "/ch/1/in/set/bal", "/ch/1/in/set/inv", "/io/in/LCL/1/g"):
        del state.values[leaf]
    assert _cv008(state, _plan(_entry(**STATED))) == []


# --------------------------------------------------------------------------
# A live-style read
# --------------------------------------------------------------------------


def _desk(**overrides) -> SnapDesk:
    values = dict(snap_values(INITIALIZED_COMPACT))
    values.update(overrides)
    return SnapDesk(values)


def test_a_live_read_takes_the_leaves_from_the_dumps_it_already_fetches():
    """A factory Compact read the way `audit --plan` reads it, by node dump:
    the strip's leaves ride in `/ch/1`, the head amp's in `/io/in/LCL/1`, so
    the request count does not move."""
    inputs, outputs = socket_groups_to_read(MODEL)
    desk = _desk()
    plain = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    plain_requests = len(desk.dumps) + len(desk.gets)
    assert plain.get("/ch/1/in/set/trim") is None and plain.get("/io/in/LCL/1/g") is None

    desk = _desk(**{"/ch/1/in/set/trim": 6.0, "/io/in/LCL/1/g": 5.0})
    extra = plan_processing_read_addresses(_plan(_entry(**STATED)))
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs,
                               bulk=True, extra=extra)
    assert len(desk.dumps) + len(desk.gets) == plain_requests
    assert state.get("/ch/1/in/set/trim") == 6.0 and state.get("/io/in/LCL/1/g") == 5.0

    plan = _plan(_entry(**STATED))
    messages = [f.message for f in _cv008(state, plan)]
    assert any("trim is 3dB, live console reads 6dB" in m for m in messages)
    assert any("head-amp gain on LCL 1 is 20dB, live console reads 5dB" in m for m in messages)
    assert not any("unread" in m for m in messages)


def test_a_per_leaf_read_asks_for_exactly_the_leaves_the_plan_states():
    inputs, outputs = socket_groups_to_read(MODEL)
    desk = _desk()
    extra = plan_processing_read_addresses(_plan(_entry(trim_db=3.0, gain_db=20.0)))
    read_console_state(desk, input_sockets=inputs, output_sockets=outputs, extra=extra)
    asked = {a for a in desk.gets if a.endswith(("/in/set/trim", "/in/set/bal", "/in/set/inv"))}
    assert asked == {"/ch/1/in/set/trim"}
    assert "/io/in/LCL/1/g" in desk.gets


# --------------------------------------------------------------------------
# The command line, end to end on the simulated desk
# --------------------------------------------------------------------------


def _applied_demo(monkeypatch, tmp_path):
    """The Demo, fully applied to a simulated initialized Compact; the plan
    file and the desk it left."""
    plan = json.loads(DEMO_PLAN.read_text(encoding="utf-8"))
    desk = PairedSnapDesk({leaf.address: leaf.value for leaf in init.load_capture(MODEL).leaves})
    result = apply_plan(copy.deepcopy(plan), desk, dry_run=False, full_apply=True,
                        initialize=True, init_model=MODEL)
    assert not result.mismatches
    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: desk)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return plan, path, desk


def _audit(path, capsys) -> str:
    code = cli.main(["audit", "--plan", str(path), "--console", "198.51.100.9", "--no-progress"])
    out = capsys.readouterr().out
    assert code in (0, 2), out
    return out


def test_audit_after_a_full_apply_of_the_demo_has_no_processing_findings(
        monkeypatch, tmp_path, capsys):
    """The case seen on a real desk: every strip's trim and gain reported as
    `unread` straight after a clean apply."""
    _plan_dict, path, _desk_ = _applied_demo(monkeypatch, tmp_path)
    out = _audit(path, capsys)
    assert "CV008" not in out and "unread" not in out


def test_audit_names_a_trim_and_a_gain_the_desk_has_moved(monkeypatch, tmp_path, capsys):
    plan, path, desk = _applied_demo(monkeypatch, tmp_path)
    kick = plan["channels"][0]
    group, socket = kick["patch"]["group"], kick["patch"]["sockets"][0]
    desk.values[f"/ch/{kick['channel']}/in/set/trim"] = 6.0
    desk.values[f"/io/in/{group}/{socket}/g"] = 2.5
    out = _audit(path, capsys)
    assert "[WARNING] CV008 Processing Contradicts Plan (2)" in out
    assert "trim is 0dB, live console reads 6dB" in out
    assert f"head-amp gain on {group} {socket} is 20dB, live console reads 2.5dB" in out
    assert "unread" not in out
