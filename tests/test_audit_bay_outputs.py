"""

A full-size WING with a Dante module fitted (`/$syscfg/opt_mod "DANTE"`),
read with no plan, raised R006 on a Matrix patched to the module's
outputs: the read covered LCL, AUX and the AES50 ports with a device, and
never `/io/out/MOD`, where a WING stores that patch. The read now asks
what each expansion bay holds whenever it reads outputs, and follows the
outputs of every bay the desk reports fitted.

Every test here is built by hand -- no bundle under `examples/` -- and
runs with no plan, which is the case that went wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES, ConsoleState, bay_output_addresses, bay_output_index_addresses,
    console_read_plan, fitted_bays, output_sockets, read_console_state, render_coverage,
    run_audit, socket_groups_to_read, summarise_sockets,
)
from atoo.console import OscReply

# Matrix 6's L and R feeds are output slots 11 and 12 (`output_source_object`).
_MTX6_L, _MTX6_R = 11, 12
# What the church desk's read had in it: Matrix 6, fed from Main 1, out on
# the Dante module's 36 and 37.
_SMALL = dict(channels=1, aux=0, buses=0, mains=1, matrices=8, dcas=0, mute_groups=0,
              fx_slots=0)


def _desk_values(*, module: str = "DANTE", card: str = "NONE") -> dict[str, object]:
    """A full-size WING answering the read plan for its own panel, with
    Main 1 sending to Matrix 6 and Matrix 6 patched to `MOD 36-37`."""
    _in, out = socket_groups_to_read("wing-full")
    values: dict[str, object] = {}
    for address, value_type in console_read_plan(output_sockets=out, **_SMALL):
        values[address] = {"s": "OFF", "i": 0, "f": 0.0}[value_type]
    values["/$stat/A/stat"] = values["/$stat/B/stat"] = values["/$stat/C/stat"] = "-"
    values[console_facts.FITTED_MODULE_ADDRESS] = module
    values[console_facts.FITTED_CARD_ADDRESS] = card
    values["/mtx/6/fdr"] = 0.0
    values["/main/1/send/MX6/on"] = 1
    for group in ("MOD", "CRD"):
        for n in range(1, 65):
            values[f"/io/out/{group}/{n}/grp"] = "OFF"
            values[f"/io/out/{group}/{n}/in"] = 0
    values["/io/out/MOD/36/grp"], values["/io/out/MOD/36/in"] = "MTX", _MTX6_L
    values["/io/out/MOD/37/grp"], values["/io/out/MOD/37/in"] = "MTX", _MTX6_R
    return values


class _Desk:
    """Answers from a dict, as a WING does on the wire; records what was
    asked."""

    console_model = "wing-full"

    def __init__(self, values):
        self.values = values
        self.asked: list[str] = []

    def get(self, address):
        self.asked.append(address)
        if address not in self.values:
            return None
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address=address, typetag="s", args=[value])
        if isinstance(value, float):
            return OscReply(address=address, typetag="sff", args=[f"{value:g}", 0.0, value])
        wire = value - console_facts.readback_index_offset(address)
        return OscReply(address=address, typetag="sfi", args=[str(value), 0.0, wire])


def _read(values: dict) -> tuple[_Desk, ConsoleState]:
    desk = _Desk(values)
    _in, out = socket_groups_to_read("wing-full")
    return desk, read_console_state(desk, output_sockets=out, **_SMALL)


def _ids(state: ConsoleState) -> set[str]:
    return {f.rule_id for f in run_audit(state, DEFAULT_RULES)}


# -- the case that went wrong ------------------------------------------------


def test_a_matrix_on_the_dante_module_is_patched_with_no_plan():
    desk, state = _read(_desk_values())
    assert "/$syscfg/opt_mod" in desk.asked
    assert "/io/out/MOD/36/grp" in desk.asked
    assert state.output_source("MOD", 36) == ("MTX", _MTX6_L)
    ids = _ids(state)
    assert "R006" not in ids
    assert "R007" not in ids, "the module was read, so nothing is left unchecked"


def test_the_sockets_read_name_the_module():
    """R006's and R011's "output sockets read (...)" and the coverage line
    are built from what was read, so they name the module now."""
    _desk, state = _read(_desk_values())
    read = summarise_sockets(output_sockets(state))
    assert read == "AUX 1-8, LCL 1-8, MOD 1-64"
    assert "MOD 1-64" in render_coverage(state)


def test_a_matrix_really_patched_nowhere_still_names_the_module_it_looked_at():
    values = _desk_values()
    values["/io/out/MOD/36/grp"] = values["/io/out/MOD/37/grp"] = "OFF"
    _desk, state = _read(values)
    r006 = [f for f in run_audit(state, DEFAULT_RULES) if f.rule_id == "R006"]
    assert len(r006) == 1
    assert "(AUX 1-8, LCL 1-8, MOD 1-64)" in r006[0].message


def test_only_a_patched_sockets_index_is_asked():
    """64 `grp` per fitted bay, then `in` only where `grp` names
    something: two here, not 64."""
    desk, _state = _read(_desk_values())
    assert len([a for a in desk.asked if a.startswith("/io/out/MOD/") and a.endswith("/grp")]) == 64
    assert sorted(a for a in desk.asked if a.startswith("/io/out/MOD/") and a.endswith("/in")) == [
        "/io/out/MOD/36/in", "/io/out/MOD/37/in"]


def test_a_fitted_card_is_followed_too():
    values = _desk_values(module="NONE", card="WLIVE")
    values["/io/out/CRD/1/grp"], values["/io/out/CRD/1/in"] = "MTX", _MTX6_L
    values["/io/out/CRD/2/grp"], values["/io/out/CRD/2/in"] = "MTX", _MTX6_R
    desk, state = _read(values)
    assert not any(a.startswith("/io/out/MOD/") for a in desk.asked)
    assert "/io/out/CRD/1/in" in desk.asked
    assert "R006" not in _ids(state)


# -- the negative: nothing fitted, nothing more read --------------------------


def test_no_module_and_no_card_reads_nothing_more():
    values = _desk_values(module="NONE", card="NONE")
    desk, state = _read(values)
    assert not any(a.startswith(("/io/out/MOD/", "/io/out/CRD/")) for a in desk.asked)
    assert fitted_bays(state) == {}
    # The Matrix really is patched to nothing the desk has, and is said so,
    # among the sockets that were read.
    r006 = [f for f in run_audit(state, DEFAULT_RULES) if f.rule_id == "R006"]
    assert len(r006) == 1 and "(AUX 1-8, LCL 1-8)" in r006[0].message


def test_a_read_with_no_outputs_asks_for_no_bay():
    plan = console_read_plan()
    assert not any(a in (console_facts.FITTED_CARD_ADDRESS, console_facts.FITTED_MODULE_ADDRESS)
                   for a, _ in plan)
    state = ConsoleState({console_facts.FITTED_MODULE_ADDRESS: "DANTE"})
    assert bay_output_addresses(state) == []


def test_a_bay_that_did_not_answer_is_not_fitted():
    state = ConsoleState({"/io/out/LCL/1/grp": "OFF", "/io/out/LCL/1/in": 0})
    assert fitted_bays(state) == {}
    assert bay_output_addresses(state) == []
    state = ConsoleState({"/io/out/LCL/1/grp": "OFF", "/$syscfg/opt_mod": " "})
    assert fitted_bays(state) == {}


def test_index_addresses_follow_what_grp_read():
    state = ConsoleState({"/io/out/LCL/1/grp": "OFF", "/$syscfg/opt_mod": "DANTE",
                          "/io/out/MOD/3/grp": "BUS", "/io/out/MOD/4/grp": "OFF"})
    assert bay_output_index_addresses(state) == [("/io/out/MOD/3/in", "i")]


# -- a reading that holds the module's word but not its outputs ---------------


def test_a_capture_without_the_module_outputs_says_the_route_was_not_checked():
    """A capture taken before this read existed, with the module's reading
    in it (the second pass asked it for a strip patched from MOD): R006
    stands down and R007 says where nobody looked, at INFO."""
    values = {a: v for a, v in _desk_values().items() if not a.startswith("/io/out/MOD/")
              and not a.startswith("/io/out/CRD/")}
    findings = run_audit(ConsoleState(values, console_model="wing-full"), DEFAULT_RULES)
    assert "R006" not in {f.rule_id for f in findings}
    r007 = [f for f in findings if f.rule_id == "R007"]
    assert len(r007) == 1
    assert "MOD (the desk reports DANTE fitted)" in r007[0].message


# -- the desk the issue came from ---------------------------------------------
#
# `tests/fixtures/church-full-dante.state.json`: the full-size WING's own
# snapshot, flattened and cut to what the output-side rules read, with the
# console's name, serial and address removed. See tests/fixtures/README.md.

_CHURCH = Path(__file__).parent / "fixtures" / "church-full-dante.state.json"


def _church() -> dict[str, object]:
    return json.loads(_CHURCH.read_text(encoding="utf-8"))


def _routing(values: dict) -> list:
    state = ConsoleState(values, console_model="wing-full")
    return [f for f in run_audit(state, DEFAULT_RULES)
            if f.rule_id in ("R002", "R005", "R006", "R007")]


def test_the_church_desk_patches_matrix_6_to_the_dante_module():
    values = _church()
    assert values["/$syscfg/opt_mod"] == "DANTE"
    assert ConsoleState(values).output_source("MOD", 36) == ("MTX", _MTX6_L)
    assert ConsoleState(values).output_source("MOD", 37) == ("MTX", _MTX6_R)


def test_the_church_desk_as_read_before_the_fix_raised_the_reported_r006():
    """Without the module's outputs and its reading -- what a no-plan read
    held -- the message is the one on the issue."""
    values = {a: v for a, v in _church().items()
              if not a.startswith("/io/out/MOD/") and a != "/$syscfg/opt_mod"}
    messages = [f.message for f in _routing(values) if f.rule_id == "R006"]
    assert ("MTX 6 has an active send feeding it but is patched to none of the output "
            "sockets read (AES50-A 1-48, AUX 1-8, LCL 1-8), and no monitor output listens "
            "to it.") in messages


def test_the_church_desk_read_now_raises_no_routing_finding():
    """Matrix 5 and 6 (two IEM mixes) and BUS 4 all go out on the Dante
    module: none is unrouted."""
    assert _routing(_church()) == []


def test_a_live_read_of_the_church_desk_follows_the_module():
    """Down the path `audit --console` and Watch take, with no plan: the
    desk is asked for its module, then for the module's outputs."""
    values = _church()
    values.pop("_comment")
    desk = _Desk(values)
    _in, out = socket_groups_to_read("wing-full")
    state = read_console_state(desk, channels=40, aux=8, buses=16, mains=4, matrices=8,
                               dcas=0, mute_groups=0, fx_slots=0, output_sockets=out)
    assert "/io/out/MOD/36/grp" in desk.asked and "/io/out/MOD/36/in" in desk.asked
    assert "/io/out/MOD/1/in" not in desk.asked, "MOD 1 is unpatched: its index is not asked"
    assert "MOD 1-64" in summarise_sockets(output_sockets(state))
    ids = _ids(state)
    assert "R006" not in ids and "R007" not in ids
