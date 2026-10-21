"""CV008 over the filters and the EQ: the plan's high-pass, hi-cut, tilt and EQ
against what the desk holds.

The filter and EQ frequencies and Q are `log` controls, stepped by a fixed
ratio, so the desk holds the nearest step of what was written. CV008 compares
them the way `apply` compares a readback (2% relative, 0.02 absolute), not
with the fader's half a dB. Plans and desks are built here; the real-desk
evidence is the frozen apply journals, which say what the desk read back for
each write.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atoo.apply import _values_equal
from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    _differs,
    console_read_plan,
    diff_against_plan,
    plan_processing_read_addresses,
    plan_scope,
    plan_watch_rules,
    planned_processing_leaves,
    read_console_state,
    socket_groups_to_read,
)
from atoo.diagnostics import Severity
from tests.snap_desk import SnapDesk, snap_values

FIXTURES = Path(__file__).parent / "fixtures"
INITIALIZED_COMPACT = FIXTURES / "console-runs" / "Initialized-Compact.snap"


def _entry(n=1, name="Kick", bank="ch", **processing):
    return {
        "channel": n, "bank": bank, "name": name,
        "source": {"input": name, "type": "Mic", "model": "", "stereo": False, "phantom": False},
        "patch": {"group": "LCL", "sockets": [n], "stated": True},
        "processing": {"hpf_hz": None, "preset": None, **processing},
        "fader": {"fader_db": None, "muted": None}, "dca": [], "mute_group": [],
        "bus_sends": [], "main_routes": [{"index": 1}],
    }


def _plan(*entries) -> dict:
    return {"busses": {}, "dcas": {}, "mute_groups": {}, "outputs": {}, "channels": list(entries)}


def _desk(*, base="/ch/1", name="Kick", **leaves) -> ConsoleState:
    """A strip as the desk reads it, with `leaves` set (`"flt/lcf": 100.2`)."""
    values: dict[str, object] = {f"{base}/name": name}
    values.update({f"{base}/{suffix}": v for suffix, v in leaves.items()})
    return ConsoleState(values, console_model="wing-compact")


def _cv008(state, plan):
    return [f for f in diff_against_plan(state, plan) if f.rule_id == "CV008"]


# --------------------------------------------------------------------------
# The filters
# --------------------------------------------------------------------------


def test_a_high_pass_where_the_plan_puts_it_is_silent_at_the_desks_nearest_step():
    """100Hz written, 100.2374573 read back: what the 2026-09-21 raw log shows."""
    state = _desk(**{"flt/lc": 1, "flt/lcf": 100.2374573})
    assert _cv008(state, _plan(_entry(hpf_hz=100))) == []


def test_a_high_pass_at_another_frequency_is_a_warning_naming_both():
    [f] = _cv008(_desk(**{"flt/lc": 1, "flt/lcf": 80.19641876}), _plan(_entry(hpf_hz=120)))
    assert (f.rule_id, f.severity) == ("CV008", Severity.WARNING)
    assert f.message == ('CH 1 "Kick": plan says the high-pass is 120Hz, live console reads '
                         "80.2Hz (tolerance 2%).")
    assert f.addresses == ("/ch/1/flt/lcf",)


def test_a_high_pass_the_plan_states_that_reads_off_is_its_own_finding():
    [f] = _cv008(_desk(**{"flt/lc": 0, "flt/lcf": 40.0}), _plan(_entry(hpf_hz=100)))
    assert f.message == 'CH 1 "Kick": plan says the high-pass is on at 100Hz; live console has it off.'
    assert f.addresses == ("/ch/1/flt/lc",)


def test_a_filter_that_is_off_is_not_also_compared_for_its_frequency():
    findings = _cv008(_desk(**{"flt/lc": 0, "flt/lcf": 5000.0}), _plan(_entry(hpf_hz=100)))
    assert len(findings) == 1 and "has it off" in findings[0].message


def test_hi_cut_and_tilt_are_filters_with_their_own_switch_and_value():
    plan = _plan(_entry(hi_cut_hz=12000, tilt_db=3.0))
    state = _desk(**{"flt/hc": 1, "flt/hcf": 8000.0, "flt/tf": 0, "flt/tilt": 3.0})
    findings = _cv008(state, plan)
    assert [f.message for f in findings] == [
        'CH 1 "Kick": plan says the hi-cut is 12000Hz, live console reads 8000Hz (tolerance 2%).',
        'CH 1 "Kick": plan says the tilt is on at 3dB; live console has it off.',
    ]
    assert [f.addresses for f in findings] == [("/ch/1/flt/hcf",), ("/ch/1/flt/tf",)]


@pytest.mark.parametrize("live,flagged", [
    (100.0, False), (100.72, False), (101.9, False), (98.1, False),
    (102.5, True), (97.0, True),
])
def test_the_tolerance_is_two_percent_of_the_value(live, flagged):
    """About three steps of the desk's 0.72% a step either way."""
    state = _desk(**{"flt/lc": 1, "flt/lcf": live})
    assert bool(_cv008(state, _plan(_entry(hpf_hz=100)))) is flagged


@pytest.mark.parametrize("live,flagged", [(0.0, False), (0.015, False), (0.1, True), (-0.1, True)])
def test_a_value_at_zero_has_an_absolute_floor(live, flagged):
    """A relative tolerance degenerates at zero; tilt can be stated 0dB."""
    state = _desk(**{"flt/tf": 1, "flt/tilt": live})
    assert bool(_cv008(state, _plan(_entry(tilt_db=0.0)))) is flagged


def test_a_half_decibel_is_not_the_filters_tolerance():
    """A 4000Hz hi-cut read back 12Hz away is the next step, not a fault:
    CV008's ±0.5 for a trim would have called it wrong."""
    state = _desk(**{"flt/hc": 1, "flt/hcf": 4012.0})
    assert _cv008(state, _plan(_entry(hi_cut_hz=4000))) == []


def test_the_comparison_is_applys_own_readback_helper():
    """One function decides whether a value is where it was asked to be, on
    the write path and here: 2.0% and a bit either way agrees with it."""
    for planned, live in ((100.0, 101.9), (100.0, 102.1), (0.0, 0.015), (0.0, 0.03), (4000.0, 4012.0)):
        state = _desk(**{"flt/lc": 1, "flt/lcf": live})
        assert bool(_cv008(state, _plan(_entry(hpf_hz=planned)))) is (
            not _values_equal("f", planned, live, "/ch/1/flt/lcf"))


def test_an_empty_plan_field_states_nothing():
    assert _cv008(_desk(**{"flt/lc": 0, "flt/lcf": 40.0}), _plan(_entry())) == []


def test_silent_when_the_leaves_were_not_read():
    state = _desk()
    assert _cv008(state, _plan(_entry(hpf_hz=100, hi_cut_hz=8000, tilt_db=2.0))) == []


def test_a_switch_that_was_not_read_leaves_the_frequency_compared():
    [f] = _cv008(_desk(**{"flt/lcf": 40.0}), _plan(_entry(hpf_hz=100)))
    assert "reads 40Hz" in f.message


def test_an_aux_strip_has_no_filter_node_so_nothing_is_compared():
    """`apply` refuses a filter on an aux (it has no `flt` node), and says so;
    there is nothing for the audit to read there."""
    plan = _plan(_entry(3, "Cue", bank="aux", hpf_hz=100))
    state = _desk(base="/aux/3", name="Cue", **{"flt/lc": 0, "flt/lcf": 40.0})
    assert planned_processing_leaves(plan["channels"][0]) == []
    assert _cv008(state, plan) == []


def test_the_plans_provenance_is_cited():
    entry = _entry(hpf_hz=120)
    entry["provenance"] = {"processing": "Processing: 'Drums get a high-pass at 120Hz'"}
    [f] = _cv008(_desk(**{"flt/lc": 1, "flt/lcf": 80.0}), _plan(entry))
    assert f.message.endswith(
        "(tolerance 2%). (plan provenance: Processing: 'Drums get a high-pass at 120Hz')")


def test_a_strip_whose_live_state_was_never_read_is_skipped():
    assert _cv008(ConsoleState({"/ch/1/flt/lcf": 40.0}), _plan(_entry(hpf_hz=100))) == []


# --------------------------------------------------------------------------
# The EQ
# --------------------------------------------------------------------------

BANDS = [{"band": "2", "freq_hz": 2500.0, "gain_db": -3.0, "q": 2.0},
         {"band": "high", "freq_hz": 10000.0, "gain_db": 2.0, "shape": "SHV"}]


def _eq_entry(**eq):
    return _entry(eq={"on": None, "model": None, "mix_pct": None, "bands": BANDS, **eq})


def _eq_desk(**changes) -> ConsoleState:
    leaves = {"eq/on": 1, "eq/mdl": "STD", "eq/mix": 100.0,
              "eq/2f": 2503.1, "eq/2g": -3.0, "eq/2q": 2.0,
              "eq/hf": 10018.26, "eq/hg": 2.0, "eq/heq": "SHV"}
    leaves.update(changes)
    return _desk(**leaves)


def test_an_eq_as_planned_is_silent():
    assert _cv008(_eq_desk(), _plan(_eq_entry())) == []


def test_a_band_is_one_finding_naming_every_leaf_that_differs():
    state = _eq_desk(**{"eq/2f": 1800.0, "eq/2g": 0.0})
    [f] = _cv008(state, _plan(_eq_entry()))
    assert f.message == ('CH 1 "Kick": EQ band 2: plan says frequency 2500Hz but 1800Hz live; '
                         "gain -3dB but 0dB live (tolerance 2%).")
    assert f.addresses == ("/ch/1/eq/2f", "/ch/1/eq/2g")


def test_a_q_ten_steps_out_is_caught():
    """Q is 0.44..10 in 181 steps, so 1.4 against 0.998 is not a rounding."""
    [f] = _cv008(_eq_desk(**{"eq/2q": 0.998}), _plan(_eq_entry(
        bands=[{"band": "2", "freq_hz": None, "gain_db": None, "q": 1.4}])))
    assert "Q 1.4 but 0.998 live" in f.message


def test_a_shelf_type_and_a_shelf_band_use_their_own_leaves():
    [f] = _cv008(_eq_desk(**{"eq/heq": "PEQ", "eq/hf": 5000.0}), _plan(_eq_entry()))
    assert f.message == ('CH 1 "Kick": EQ band high: plan says frequency 10000Hz but 5000Hz live; '
                         "shape SHV but PEQ live (tolerance 2%).")
    assert f.addresses == ("/ch/1/eq/hf", "/ch/1/eq/heq")


def test_the_eq_switch_model_and_mix_are_one_finding():
    state = _eq_desk(**{"eq/on": 0, "eq/mdl": "SOUL", "eq/mix": 50.0})
    [f] = _cv008(state, _plan(_eq_entry(model="STD", mix_pct=100.0)))
    assert f.message == ('CH 1 "Kick": plan says the EQ on but it is off live; '
                         "model STD but SOUL live; mix 100% but 50% live.")
    assert f.addresses == ("/ch/1/eq/on", "/ch/1/eq/mdl", "/ch/1/eq/mix")


def test_stating_a_band_implies_the_eq_is_on_and_an_explicit_off_is_respected():
    off = _eq_desk(**{"eq/on": 0})
    assert [f.addresses for f in _cv008(off, _plan(_eq_entry()))] == [("/ch/1/eq/on",)]
    assert _cv008(off, _plan(_eq_entry(on=False))) == []


def test_silent_for_eq_leaves_that_were_not_read():
    assert _cv008(_desk(), _plan(_eq_entry(model="STD", mix_pct=100.0))) == []


def test_an_aux_strips_eq_is_compared_and_its_filters_are_not():
    entry = _entry(3, "Cue", bank="aux", hpf_hz=100,
                   eq={"on": None, "model": None, "mix_pct": None,
                       "bands": [{"band": "1", "freq_hz": 300.0, "gain_db": None, "q": None}]})
    state = _desk(base="/aux/3", name="Cue", **{"flt/lcf": 40.0, "flt/lc": 0, "eq/on": 1, "eq/1f": 150.0})
    [f] = _cv008(state, _plan(entry))
    assert f.message == 'AUX 3 "Cue": EQ band 1: plan says frequency 300Hz but 150Hz live (tolerance 2%).'


def test_the_presend_eq_is_compared_and_an_auxs_is_not():
    peq = {"on": True, "bands": [{"band": "1", "freq_hz": 300.0, "gain_db": 3.0, "q": 1.0}]}
    assert {t.address for t in planned_processing_leaves(_entry(presend_eq=peq))} == {
        "/ch/1/peq/1f", "/ch/1/peq/1g", "/ch/1/peq/1q", "/ch/1/peq/on"}
    assert planned_processing_leaves(_entry(3, "Cue", bank="aux", presend_eq=peq)) == []


# --------------------------------------------------------------------------
# What a plan reads, and who reads it
# --------------------------------------------------------------------------


def test_the_leaves_to_read_are_exactly_the_ones_the_plan_states():
    plan = _plan(_entry(hpf_hz=100, tilt_db=1.0), _eq_entry(), _entry(2, "Snare"))
    plan["channels"][1]["channel"] = 7
    got = dict(plan_processing_read_addresses(plan))
    assert got == {
        "/ch/1/flt/lc": "i", "/ch/1/flt/lcf": "f", "/ch/1/flt/tf": "i", "/ch/1/flt/tilt": "f",
        "/ch/7/eq/2f": "f", "/ch/7/eq/2g": "f", "/ch/7/eq/2q": "f",
        "/ch/7/eq/hf": "f", "/ch/7/eq/hg": "f", "/ch/7/eq/heq": "s", "/ch/7/eq/on": "i",
    }
    assert plan_processing_read_addresses(None) == [] == plan_processing_read_addresses({})


def test_the_default_read_plan_is_not_moved_and_extra_leaves_are_appended_once():
    base = console_read_plan()
    extra = plan_processing_read_addresses(_plan(_entry(hpf_hz=100)))
    plan = console_read_plan(extra=extra + extra + [base[0]])
    assert plan == base + extra


def test_a_live_read_takes_the_filter_leaves_from_the_strips_own_dump_at_no_extra_request():
    """A factory Compact read the way `audit --plan` reads it: node dumps. The
    leaves ride in `/ch/1`'s dump, so the request count does not move."""
    desk = SnapDesk(dict(snap_values(INITIALIZED_COMPACT)))
    inputs, outputs = socket_groups_to_read("wing-compact")
    plain = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    plain_requests = len(desk.dumps) + len(desk.gets)
    assert plain.get("/ch/1/flt/lcf") is None

    desk = SnapDesk(dict(snap_values(INITIALIZED_COMPACT)))
    extra = plan_processing_read_addresses(_plan(_entry(hpf_hz=120), _entry(2, "Snare", hi_cut_hz=9000)))
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True, extra=extra)
    assert len(desk.dumps) + len(desk.gets) == plain_requests
    assert state.get("/ch/1/flt/lcf") == pytest.approx(100.2374573)
    assert state.get("/ch/2/flt/hcf") == pytest.approx(10018.26074)
    assert state.get("/ch/1/flt/lc") == 0
    [f] = _cv008(state, _plan(_entry(hpf_hz=120)))
    assert f.message == ('CH 1: plan says the high-pass is on at 120Hz; live console has it off.')


def test_a_per_leaf_read_asks_for_exactly_the_extra_leaves():
    desk = SnapDesk(dict(snap_values(INITIALIZED_COMPACT)))
    inputs, outputs = socket_groups_to_read("wing-compact")
    extra = plan_processing_read_addresses(_plan(_entry(hpf_hz=120)))
    read_console_state(desk, input_sockets=inputs, output_sockets=outputs, extra=extra)
    asked = {a for a in desk.gets if "/flt/" in a}
    assert asked == {"/ch/1/flt/lc", "/ch/1/flt/lcf"}


def test_the_plan_scope_states_the_leaves_cv008_compares():
    scope = plan_scope(_desk(), _plan(_entry(hpf_hz=100), _eq_entry()))
    assert scope.states("/ch/1", "flt/lcf") and scope.states("/ch/1", "flt/lc")
    assert not scope.states("/ch/1", "flt/hcf")


def test_watch_does_not_run_it():
    """A filter is a set-up value. CV008 is not in the rules Watch runs, and
    no plan-bound Watch rule reads a filter or an EQ leaf."""
    assert "CV008" not in {r.id for r in DEFAULT_RULES}
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plan.json"
        path.write_text(json.dumps(_plan(_entry(hpf_hz=100), _eq_entry())))
        assert "CV008" not in {r.id for r in plan_watch_rules(path)}


# --------------------------------------------------------------------------
# Real desks
# --------------------------------------------------------------------------


def _journal_pairs(path):
    writes = json.loads(path.read_text())["writes"]
    for write in writes:
        address = write.get("address", "")
        if (re.search(r"/(flt|eq)/", address)
                and isinstance(write.get("intended_value"), (int, float))
                and isinstance(write.get("readback_value"), (int, float))):
            yield address, write["intended_value"], write["readback_value"]


JOURNALS = [FIXTURES / "touringband-2026-09-18.apply-journal.json",
            FIXTURES / "console-runs" / "2026-09-21-2100" / "A1-apply-journal.json",
            FIXTURES / "console-runs" / "2026-09-22-2136" / "A1-apply-journal.json",
            FIXTURES / "console-runs" / "2026-09-28-1904" / "A22-apply-journal.json"]


@pytest.mark.parametrize("journal", JOURNALS, ids=lambda p: p.parent.name + "/" + p.name)
def test_no_value_a_real_desk_read_back_for_a_filter_or_eq_write_is_called_wrong(journal):
    """The false-positive rate on real hardware: every filter and EQ write in
    the four frozen apply journals (36, 36, 36 and 60 values), the desk's
    readback against what was written, through the same leaf comparison
    CV008 makes. 0 flagged of 168."""
    pairs = list(_journal_pairs(journal))
    assert pairs
    flagged = []
    for address, intended, readback in pairs:
        state = ConsoleState({address: readback})
        leaf_type = "i" if address.endswith(("/lc", "/hc", "/tf", "/on")) else "f"
        if _differs(state, address, leaf_type, intended) is not None:
            flagged.append((address, intended, readback))
    assert flagged == []


@pytest.mark.parametrize("capture", sorted(FIXTURES.rglob("*.snap")), ids=lambda p: p.name)
def test_a_plan_that_states_what_a_capture_holds_has_no_cv008_on_it(capture):
    """Every channel of every frozen capture that has a filter, planned with
    the values an engineer would type for what the desk holds (the high-pass to
    a tenth of a hertz, the hi-cut to the hertz, the tilt to its 0.25dB step),
    gives 0 CV008 findings: the tolerance holds on real quantisation."""
    values = snap_values(capture)
    channels, entries = 0, []
    for n in range(1, 41):
        base = f"/ch/{n}"
        lcf, hcf, tilt = (values.get(f"{base}/flt/{leaf}") for leaf in ("lcf", "hcf", "tilt"))
        if lcf is None:
            continue
        channels += 1
        entries.append(_entry(n, f"CH{n}", hpf_hz=round(lcf, 1),
                              hi_cut_hz=None if hcf is None else round(hcf),
                              tilt_db=None if tilt is None else round(tilt, 2)))
        values[f"{base}/name"] = f"CH{n}"
        values[f"{base}/flt/lc"] = values[f"{base}/flt/hc"] = values[f"{base}/flt/tf"] = 1
    if not entries:
        pytest.skip("this capture holds no filter leaves")
    state = ConsoleState(values)
    assert _cv008(state, _plan(*entries)) == []
    assert channels >= 1


def test_the_same_capture_with_one_filter_moved_does_report_it():
    """The captures' silence is the rule's reading of them, not its blindness."""
    values = snap_values(INITIALIZED_COMPACT)
    values.update({"/ch/1/name": "Kick", "/ch/1/flt/lc": 1, "/ch/1/flt/lcf": 240.0})
    plan = _plan(_entry(hpf_hz=round(values["/ch/1/flt/lcf"] / 2, 1)))
    [f] = _cv008(ConsoleState(values), plan)
    assert "plan says the high-pass is 120Hz, live console reads 240Hz" in f.message


# --------------------------------------------------------------------------
# The command line reads what the plan states, and only `audit` does
# --------------------------------------------------------------------------


def test_audit_console_with_a_plan_asks_the_read_for_the_leaves_the_plan_states(
        monkeypatch, tmp_path, capsys):
    from atoo import audit, cli

    class Desk:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    asked = []

    def read(console, **kwargs):
        asked.append(kwargs)
        return ConsoleState({"/ch/1/name": "Kick", "/ch/1/flt/lc": 1, "/ch/1/flt/lcf": 240.0},
                            console_model="wing-compact")

    monkeypatch.setattr(cli, "_open_console", lambda args, raw_log=None: Desk())
    monkeypatch.setattr(audit, "read_console_state", read)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(_plan(_entry(hpf_hz=120))))

    code = cli.main(["audit", "--console", "192.0.2.1", "--no-progress", "--plan", str(plan_file)])
    out = capsys.readouterr().out
    assert code == 0
    assert asked[0]["extra"] == [("/ch/1/flt/lc", "i"), ("/ch/1/flt/lcf", "f")]
    assert 'CH 1 "Kick": plan says the high-pass is 120Hz, live console reads 240Hz' in out

    asked.clear()
    cli.main(["audit", "--console", "192.0.2.1", "--no-progress"])
    capsys.readouterr()
    assert asked[0]["extra"] == []
