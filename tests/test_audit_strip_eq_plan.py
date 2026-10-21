"""CV008 over a bus's, Main's or Matrix's own EQ and tilt, and a channel's
PreSend EQ: the plan's statement against what the desk holds.

The plan already names all of them (`busses[*].processing`, the `outputs[*]` of
kind main or matrix, `processing.presend_eq`), so nothing here needs a plan
format of its own. They are compared the way a channel's EQ is: with `apply`'s
own readback tolerance, band by band. Plans and desks are built in the test; the
live-read test uses a frozen factory capture, never a show bundle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atoo.audit import (
    ConsoleState,
    console_read_plan,
    diff_against_plan,
    plan_processing_read_addresses,
    planned_processing_leaves,
    planned_strip_processing_objects,
    read_console_state,
    socket_groups_to_read,
)
from atoo.diagnostics import Severity
from tests.snap_desk import SnapDesk, snap_values

INITIALIZED_COMPACT = (Path(__file__).parent / "fixtures" / "console-runs"
                       / "Initialized-Compact.snap")


def _band(band, freq=None, gain=None, q=None, shape=None):
    entry = {"band": band, "freq_hz": freq, "gain_db": gain, "q": q}
    if shape is not None:
        entry["shape"] = shape
    return entry


def _eq(*bands, on=None):
    return {"on": on, "model": None, "mix_pct": None, "bands": list(bands)}


def _plan(*, busses=None, outputs=None, channels=None) -> dict:
    return {"busses": busses or {}, "outputs": outputs or {}, "channels": channels or [],
            "dcas": {}, "mute_groups": {}}


def _channel(presend_eq, bank="ch"):
    return {"channel": 1, "bank": bank, "name": "Kick",
            "source": {"input": "Kick", "type": "Mic", "model": "", "stereo": False,
                       "phantom": False},
            "patch": {"group": "LCL", "sockets": [1], "stated": True},
            "processing": {"hpf_hz": None, "preset": None, "presend_eq": presend_eq},
            "fader": {"fader_db": None, "muted": None}, "dca": [], "mute_group": [],
            "bus_sends": [], "main_routes": [{"index": 1}]}


def _desk(**leaves) -> ConsoleState:
    """A desk as read, with `leaves` set by full address."""
    return ConsoleState(dict(leaves), console_model="wing-compact")


def _cv008(state, plan):
    return [f for f in diff_against_plan(state, plan) if f.rule_id == "CV008"]


# --------------------------------------------------------------------------
# A bus
# --------------------------------------------------------------------------


def _bus_plan(**processing):
    return _plan(busses={"Drums": {"index": 1, "destination": {"type": "main"},
                                   "processing": processing,
                                   "provenance": "Busses: Drums get a low cut"}})


def test_a_bus_band_that_reads_where_the_plan_puts_it_is_silent_at_the_nearest_step():
    state = _desk(**{"/bus/1/eq/2f": 1004.0, "/bus/1/eq/2g": 3.0, "/bus/1/eq/on": 1})
    assert _cv008(state, _bus_plan(eq=_eq(_band("2", freq=1000.0, gain=3.0)))) == []


def test_a_bus_band_that_differs_is_one_warning_naming_every_leaf_and_the_bus():
    state = _desk(**{"/bus/1/eq/2f": 1800.0, "/bus/1/eq/2g": -2.0, "/bus/1/eq/2q": 1.0,
                     "/bus/1/eq/on": 1})
    [finding] = _cv008(state, _bus_plan(eq=_eq(_band("2", freq=1000.0, gain=3.0, q=1.0))))
    assert (finding.rule_id, finding.severity) == ("CV008", Severity.WARNING)
    assert finding.message == (
        'BUS 1 "Drums": EQ band 2: plan says frequency 1000Hz but 1800Hz live; gain 3dB but '
        "-2dB live (tolerance 2%). (plan provenance: Busses: Drums get a low cut)")
    assert finding.addresses == ("/bus/1/eq/2f", "/bus/1/eq/2g")


def test_a_bus_eq_the_plan_states_that_reads_off_is_reported_on_its_own():
    state = _desk(**{"/bus/1/eq/2f": 1000.0, "/bus/1/eq/on": 0})
    [finding] = _cv008(state, _bus_plan(eq=_eq(_band("2", freq=1000.0))))
    assert "plan says the EQ on but it is off live" in finding.message
    assert finding.addresses == ("/bus/1/eq/on",)


def test_a_bus_tilt_is_a_leaf_of_its_eq_node_with_no_switch_of_its_own():
    [finding] = _cv008(_desk(**{"/bus/1/eq/tilt": 0.0}), _bus_plan(tilt_db=3.0))
    assert finding.message.startswith('BUS 1 "Drums": plan says the tilt is 3dB, live console '
                                      "reads 0dB (tolerance 2%).")
    assert finding.addresses == ("/bus/1/eq/tilt",)
    assert _cv008(_desk(**{"/bus/1/eq/tilt": 3.0}), _bus_plan(tilt_db=3.0)) == []


def test_a_bus_leaf_that_was_not_read_is_not_compared():
    assert _cv008(_desk(), _bus_plan(eq=_eq(_band("2", freq=1000.0)))) == []


def test_a_bus_with_no_index_names_no_console_object():
    plan = _plan(busses={"Drums": {"processing": {"eq": _eq(_band("2", freq=1000.0))}}})
    assert planned_strip_processing_objects(plan) == []
    assert _cv008(_desk(**{"/bus/1/eq/2f": 50.0}), plan) == []


def test_a_bus_the_plan_states_nothing_for_is_left_alone():
    plan = _plan(busses={"Drums": {"index": 1, "destination": {"type": "main"}}})
    assert _cv008(_desk(**{"/bus/1/eq/2f": 50.0}), plan) == []


# --------------------------------------------------------------------------
# A Main and a Matrix
# --------------------------------------------------------------------------


def _outputs_plan():
    return _plan(outputs={
        "PA": {"kind": "main", "index": 1, "processing": {"eq": _eq(_band("high", gain=-3.0,
                                                                          shape="SHV"))}},
        "Fill": {"kind": "matrix", "index": 2, "processing": {"tilt_db": 1.0,
                                                               "eq": _eq(_band("1", freq=250.0))}},
        "Spare": {"kind": "matrix", "index": 3},
    })


def test_a_main_and_a_matrix_are_compared_on_their_own_nodes_and_named_by_the_plan():
    state = _desk(**{"/main/1/eq/hg": 0.0, "/main/1/eq/heq": "SHV",
                     "/mtx/2/eq/1f": 500.0, "/mtx/2/eq/tilt": 0.0})
    findings = _cv008(state, _outputs_plan())
    assert [f.message for f in findings] == [
        'MAIN 1 "PA": EQ band high: plan says gain -3dB but 0dB live (tolerance 2%).',
        'MTX 2 "Fill": EQ band 1: plan says frequency 250Hz but 500Hz live (tolerance 2%).',
        'MTX 2 "Fill": plan says the tilt is 1dB, live console reads 0dB (tolerance 2%).',
    ]
    assert [f.addresses for f in findings] == [
        ("/main/1/eq/hg",), ("/mtx/2/eq/1f",), ("/mtx/2/eq/tilt",)]


def test_a_shelf_type_on_a_main_is_compared_exactly():
    state = _desk(**{"/main/1/eq/hg": -3.0, "/main/1/eq/heq": "PEQ"})
    [finding] = _cv008(state, _outputs_plan())
    assert "shape SHV but PEQ live" in finding.message


def test_an_output_that_is_not_a_main_or_a_matrix_is_not_an_object_with_an_eq():
    plan = _plan(outputs={"Odd": {"kind": None, "index": 1, "processing": {"tilt_db": 2.0}}})
    assert planned_strip_processing_objects(plan) == []


# --------------------------------------------------------------------------
# A channel's PreSend EQ
# --------------------------------------------------------------------------


def _peq(on=None, *bands):
    return {"on": on, "bands": list(bands)}


def test_the_presend_eq_is_compared_band_by_band_and_by_its_switch():
    plan = _plan(channels=[_channel(_peq(True, _band("1", freq=300.0, gain=3.0, q=1.0),
                                         _band("3", freq=5000.0)))])
    state = _desk(**{"/ch/1/name": "Kick", "/ch/1/peq/1f": 300.0, "/ch/1/peq/1g": 0.0,
                     "/ch/1/peq/1q": 1.0, "/ch/1/peq/3f": 5000.0, "/ch/1/peq/on": 0})
    findings = _cv008(state, plan)
    assert [f.message for f in findings] == [
        'CH 1 "Kick": PreSend EQ band 1: plan says gain 3dB but 0dB live (tolerance 2%).',
        'CH 1 "Kick": plan says the PreSend EQ on but it is off live.',
    ]
    assert [f.addresses for f in findings] == [("/ch/1/peq/1g",), ("/ch/1/peq/on",)]


def test_a_presend_eq_that_matches_is_silent():
    plan = _plan(channels=[_channel(_peq(None, _band("2", freq=1000.0)))])
    state = _desk(**{"/ch/1/name": "Kick", "/ch/1/peq/2f": 1004.0, "/ch/1/peq/on": 1})
    assert _cv008(state, plan) == []


def test_a_presend_eq_on_an_aux_is_apply_s_warning_and_no_leaf_here():
    entry = _channel(_peq(True, _band("1", freq=300.0)), bank="aux")
    assert planned_processing_leaves(entry) == []


# --------------------------------------------------------------------------
# What a plan reads
# --------------------------------------------------------------------------


def test_the_leaves_to_read_include_exactly_what_these_entries_state():
    plan = _plan(
        busses={"Drums": {"index": 1, "processing": {"tilt_db": 2.0}}},
        outputs={"PA": {"kind": "main", "index": 1,
                        "processing": {"eq": _eq(_band("2", freq=1000.0))}}},
        channels=[_channel(_peq(None, _band("1", gain=3.0)))])
    assert dict(plan_processing_read_addresses(plan)) == {
        "/ch/1/peq/1g": "f", "/ch/1/peq/on": "i",
        "/bus/1/eq/tilt": "f",
        "/main/1/eq/2f": "f", "/main/1/eq/on": "i",
    }


def test_a_live_read_takes_these_leaves_from_the_objects_own_dump_at_no_extra_request():
    """A factory Compact capture read the way `audit --plan` reads it. The leaves
    ride in the `/bus/1`, `/main/1`, `/mtx/1` and `/ch/1` dumps, so the request
    count does not move."""
    plan = _plan(
        busses={"Drums": {"index": 1, "processing": {"eq": _eq(_band("2", freq=1000.0))}}},
        outputs={"PA": {"kind": "main", "index": 1,
                        "processing": {"eq": _eq(_band("1", gain=3.0))}},
                 "Fill": {"kind": "matrix", "index": 1, "processing": {"tilt_db": 2.0}}},
        channels=[_channel(_peq(True, _band("1", freq=300.0)))])
    inputs, outputs = socket_groups_to_read("wing-compact")
    desk = SnapDesk(dict(snap_values(INITIALIZED_COMPACT)))
    plain = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True)
    plain_requests = len(desk.dumps) + len(desk.gets)
    assert plain.get("/bus/1/eq/2f") is None

    desk = SnapDesk(dict(snap_values(INITIALIZED_COMPACT)))
    state = read_console_state(desk, input_sockets=inputs, output_sockets=outputs, bulk=True,
                               extra=plan_processing_read_addresses(plan))
    assert len(desk.dumps) + len(desk.gets) == plain_requests
    for address in ("/bus/1/eq/2f", "/main/1/eq/1g", "/mtx/1/eq/tilt", "/ch/1/peq/1f",
                    "/ch/1/peq/on"):
        assert state.get(address) is not None, address
    findings = _cv008(state, plan)
    # A stated band implies the EQ is on, which a factory desk has off.
    assert {f.addresses for f in findings} == {
        ("/bus/1/eq/2f",), ("/main/1/eq/1g",), ("/mtx/1/eq/tilt",), ("/ch/1/peq/1f",),
        ("/bus/1/eq/on",), ("/main/1/eq/on",), ("/ch/1/peq/on",)}


def test_the_default_read_plan_is_not_moved():
    base = console_read_plan()
    assert console_read_plan(extra=[]) == base
