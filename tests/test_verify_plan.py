"""Negative tests for the verifier.

A verifier that never fires is worse than no verifier, so every check gets
a mutation that must trip it. Each case starts from the real touringband
oracle plan and breaks exactly one thing.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo.input_list import InputRow, load_input_list
from atoo.verify_plan import SEVERITY_WARNING, verify_plan
from atoo.diagnostics import Severity

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CSV = FIXTURES / "touringband.csv"


@pytest.fixture(scope="module")
def rows():
    return load_input_list(str(CSV))


@pytest.fixture(scope="module")
def oracle():
    """The plan these tests verify.

    It used to be built by shelling out to `build --no-ai`, i.e. by the
    deterministic compiler. An earlier change retired that path, so the plan it produced
    for this fixture pair is checked in -- generated from the compiler at
    `origin/main` immediately before deletion, so every finding asserted
    below is still asserted against the same bytes.

    That the oracle is a *file* rather than a fresh build is if anything
    truer to this module's own docstring: the verifier "knows nothing
    about conventions files" and is handed a plan.
    """
    return json.loads((FIXTURES / "touringband.plan.json").read_text())


# The oracle's strips that reach only the monitors (see
# test_oracle_has_only_the_known_matrix_gap).
OFF_MAIN = "routing.channel-misses-main"


def codes(result):
    return {f.code for f in result.findings}


def blocking_or_warning_codes(result):
    """Everything but the notes. Since 2026-09-25 a plan that leaves a bus
    width or send mode unstated gets an INFO saying what was decided
    (`atoo/inferred.py`) -- the oracle predates that and leaves
    several unstated, so a test about something else compares these."""
    return {f.code for f in result.errors + result.warnings}


def test_oracle_has_only_the_known_matrix_gap(oracle, rows):
    # The deterministic compiler emits this as a *warning*, and since
    # 2026-10-09 so does the verifier: an unpatched Matrix is set up and
    # routed to no socket, a working desk (the maintainer: a Matrix used as the
    # phones source has none). It was an ERROR until then.
    result = verify_plan(oracle, rows)
    assert result.ok
    assert [f.where for f in result.warnings if f.code == "output.no-patch"] == ["outputs[Matrix]"]
    # And, since 2026-09-29, four strips the old compiler sent only to the
    # monitors -- BassDI, EG 1, Keys, TRAX -- reach no Main
    # (`routing.channel-misses-main`), which is true of this oracle.
    assert blocking_or_warning_codes(result) == {"output.no-patch", OFF_MAIN}
    assert [f.where for f in result.warnings if f.code == OFF_MAIN] == [
        "channels[BassDI]", "channels[EG 1]", "channels[Keys]", "channels[TRAX]"]
    # ...and the rest is notes about values the oracle never stated.
    assert {f.code for f in result.infos} <= {"inferred.bus-width", "inferred.send-mode"}


def mutate(plan, fn):
    p = copy.deepcopy(plan)
    fn(p)
    return p


def _set_bus_socket(p, bus_name, group, sockets):
    # Destinations (plural) is authoritative once populated,
    # same as destination (singular) always was -- a test that only
    # touched the old singular field would silently stop exercising
    # anything on a compiled oracle plan, since the compiler always
    # populates both. Keep every mirror of the same socket in sync.
    bus = p["busses"][bus_name]
    bus["destination"]["socket"].update(group=group, sockets=sockets)
    for dest in bus.get("destinations") or []:
        if dest.get("type") == "dedicated_output":
            dest["socket"].update(group=group, sockets=sockets)
            for s in dest.get("sockets") or []:
                s.update(group=group, sockets=sockets)


def _set_bus_destination(p, bus_name, destination):
    p["busses"][bus_name]["destination"] = destination
    p["busses"][bus_name]["destinations"] = [destination]


def _set_bus_destination_list(p, bus_name, destinations):
    p["busses"][bus_name]["destinations"] = destinations
    p["busses"][bus_name]["destination"] = destinations[0]


@pytest.mark.parametrize("code,break_it", [
    ("strip.index-out-of-range",
     lambda p: p["channels"][0].__setitem__("channel", 41)),
    ("strip.double-booked",
     lambda p: p["channels"][1].__setitem__("channel", p["channels"][0]["channel"])),
    ("strip.name-too-long",
     lambda p: p["channels"][0].__setitem__("name", "A name far longer than sixteen")),
    ("strip.unknown-bank",
     lambda p: p["channels"][0].__setitem__("bank", "bus")),
    ("patch.unknown-group",
     lambda p: p["channels"][0]["patch"].__setitem__("group", "AES50-A")),
    ("patch.socket-out-of-range",
     lambda p: p["channels"][0]["patch"].__setitem__("sockets", [49])),
    ("patch.socket-shared",
     lambda p: p["channels"][1]["patch"].update(
         group=p["channels"][0]["patch"]["group"],
         sockets=list(p["channels"][0]["patch"]["sockets"]))),
    ("patch.contradicts-input-list",
     lambda p: p["channels"][0]["patch"].__setitem__("sockets", [30])),
    ("value.hpf-out-of-range",
     lambda p: p["channels"][0]["processing"].__setitem__("hpf_hz", 5)),
    ("value.fader-out-of-range",
     lambda p: p["channels"][0]["fader"].__setitem__("fader_db", 12.0)),
    ("value.send-level-out-of-range",
     lambda p: p["channels"][0]["bus_sends"][0].__setitem__("level_db", -200.0)),
    ("value.send-mode-unrepresented",
     lambda p: p["channels"][0]["bus_sends"][0].__setitem__("mode", "GRP")),
    # A mode that is STATED and is nonsense. A null one is decided, not
    # refused, since 2026-09-25 -- see test_a_null_send_mode_is_decided_*.
    ("value.send-mode-unknown",
     lambda p: p["channels"][0]["bus_sends"][0].__setitem__("mode", "sideways")),
    ("value.main-index-out-of-range",
     lambda p: p["channels"][0].__setitem__("main_routes", [{"index": 5}])),
    ("reference.dangling",
     lambda p: p["channels"][0].__setitem__("dca", ["Nonexistent"])),
    ("reference.dangling",
     lambda p: p["busses"]["Monitor 1"].__setitem__("dca", ["Nonexistent"])),
    ("capacity.exceeded",
     lambda p: p["mute_groups"].update({f"Extra {i}": {} for i in range(9)})),
    ("reconcile.invented-source",
     lambda p: p["channels"][0]["source"].__setitem__("input", "Theremin")),
    ("reconcile.dropped-input",
     lambda p: p["channels"].pop()),
    ("output.socket-out-of-range",
     lambda p: _set_bus_socket(p, "Monitor 1", "LCL", [41])),
    # One physical output socket carries one source. Two
    # busses on one XLR...
    ("output.socket-collision",
     lambda p: _set_bus_socket(p, "Monitor 3", "A", [41])),
    # ...and a bus on top of an `outputs` entry's socket, which is the
    # shape the issue was reported in (a stereo IEM bus landing on the
    # Matrix's own XLRs). A check that only walked `busses` would miss
    # this one.
    ("output.socket-collision",
     lambda p: _set_bus_socket(p, "Monitor 1", "USB", [47])),
    ("reference.dangling",
     lambda p: p["outputs"]["Matrix"].__setitem__("fed_by", {"type": "bus", "name": "Nonexistent"})),
    # Every one of these is a write to a leaf the
    # console does not have: it would be accepted by nothing, reported by
    # nothing, and simply absent at soundcheck.
    ("value.eq-band-unavailable",
     lambda p: p["channels"][0]["processing"].__setitem__("eq", {"bands": [{"band": "6", "gain_db": 1.0}]})),
    ("value.eq-shape-unavailable",
     lambda p: p["channels"][0]["processing"].__setitem__("eq", {"bands": [{"band": "low", "shape": "BW12"}]})),
    ("value.eq-shape-on-parametric-band",
     lambda p: p["channels"][0]["processing"].__setitem__("eq", {"bands": [{"band": "2", "shape": "SHV"}]})),
    ("value.eq-model-unavailable",
     lambda p: p["channels"][0]["processing"].__setitem__("eq", {"model": "PIA", "bands": []})),
    ("value.eq-band-duplicate",
     lambda p: p["channels"][0]["processing"].__setitem__(
         "eq", {"bands": [{"band": "1", "gain_db": 1.0}, {"band": "1", "gain_db": -1.0}]})),
    ("value.eq-band-empty",
     lambda p: p["channels"][0]["processing"].__setitem__("eq", {"bands": [{"band": "1"}]})),
    ("value.eq-band-unavailable",
     lambda p: p["busses"]["Monitor 1"].__setitem__("processing", {"eq": {"bands": [{"band": "7", "gain_db": 1.0}]}})),
    ("value.eq-model-unavailable",
     lambda p: p["outputs"]["Main"].__setitem__("processing", {"eq": {"model": "MACH4", "bands": []}})),
    ("value.presend-eq-band-unavailable",
     lambda p: p["channels"][0]["processing"].__setitem__("presend_eq", {"bands": [{"band": "4", "gain_db": 1.0}]})),
    ("value.presend-eq-band-duplicate",
     lambda p: p["channels"][0]["processing"].__setitem__(
         "presend_eq", {"bands": [{"band": "1", "gain_db": 1.0}, {"band": "1", "gain_db": 2.0}]})),
    ("value.presend-eq-band-empty",
     lambda p: p["channels"][0]["processing"].__setitem__("presend_eq", {"bands": [{"band": "1"}]})),
])
def test_mutation_is_caught(oracle, rows, code, break_it):
    result = verify_plan(mutate(oracle, break_it), rows)
    assert code in codes(result), f"{code} not raised; got {sorted(codes(result))}"


def test_output_no_socket_is_not_raised_when_reached_via_a_matrix(oracle, rows):
    """A Main has no routing table of its own on real hardware
    -- its only way to a physical socket besides its own `socket` field is
    a SEND into a Matrix, stated on the MATRIX's own `fed_by`. Two real
    hosted claude-sonnet-5 runs hit exactly this shape: the conventions
    state Matrix 1's physical patch and never mention Main's own, so Main
    correctly has no socket -- and output.no-patch wrongly blocked apply
    anyway, without checking whether some other output's fed_by already
    proves the signal reaches hardware one hop further along. Swaps the
    oracle's own sockets (Main has one, Matrix doesn't -- the reverse
    shape, still correctly a finding below) to that exact case."""
    def swap(p):
        main_socket = p["outputs"]["Main"]["socket"]
        p["outputs"]["Matrix"]["socket"] = main_socket
        p["outputs"]["Matrix"]["sockets"] = [main_socket]
        p["outputs"]["Main"]["socket"] = None
        p["outputs"]["Main"]["sockets"] = []

    result = verify_plan(mutate(oracle, swap), rows)
    assert "output.no-patch" not in codes(result)


def test_output_no_socket_still_fires_when_the_matrix_doesnt_reach_this_main(oracle, rows):
    """The suppression above is specific to THIS Main being the one the
    Matrix is actually fed_by -- a Matrix reachable from a different Main
    index (or not a Matrix at all) must not paper over a real gap."""
    def swap_and_misdirect(p):
        main_socket = p["outputs"]["Main"]["socket"]
        p["outputs"]["Matrix"]["socket"] = main_socket
        p["outputs"]["Matrix"]["sockets"] = [main_socket]
        p["outputs"]["Matrix"]["fed_by"] = {"type": "main", "index": 99}
        p["outputs"]["Main"]["socket"] = None
        p["outputs"]["Main"]["sockets"] = []

    result = verify_plan(mutate(oracle, swap_and_misdirect), rows)
    assert "output.no-patch" in codes(result)
    # A WARNING, not a refusal: the Main is still set up (2026-10-09).
    assert [f.where for f in result.warnings if f.code == "output.no-patch"] == ["outputs[Main]"]


def test_a_stereo_channels_second_socket_is_not_a_dropped_input():
    """A real hosted claude-sonnet-5 run merged 'Keys L'/'Keys R' into one
    stereo channel per the conventions' own stereo-pairing rule, named
    'source.input': 'Keys L' (WING convention: a stereo channel's patch
    and source both reference the first socket only) -- and reconciliation
    then flagged 'Keys R' as reconcile.dropped-input, even though it is
    physically patched as that channel's second socket. Standalone plan
    (not the shared oracle, which has no stereo channel) so this doesn't
    depend on `_check_reconciliation`'s neighbors in verify_plan()."""
    from atoo.verify_plan import VerifyResult, _check_reconciliation

    rows = [
        InputRow(name="Keys L", category="keys", type="Instrument", phantom=False, patch="AES50-A 15"),
        InputRow(name="Keys R", category="keys", type="Instrument", phantom=False, patch="AES50-A 16"),
    ]
    plan = {
        "channels": [{
            "name": "Keys",
            "source": {"input": "Keys L", "stereo": True, "phantom": False},
            "patch": {"group": "A", "sockets": [15, 16], "stated": True},
        }],
        "unassigned_inputs": [],
    }

    result = VerifyResult()
    _check_reconciliation(plan, rows, result)
    assert codes(result) == set()


def test_bus_to_matrix_destination_is_a_warning_not_an_error(oracle, rows):
    """"matrix" is a legal destination type (a bus CAN feed a Matrix), but
    apply.py has no confirmed write path for it. A resolved
    socket here would otherwise pass the generic destination check and
    look appliable when it silently isn't -- so it gets its own code and
    stays a warning, not a block."""
    plan = mutate(oracle, lambda p: _set_bus_destination(p, "Monitor 1", {"type": "matrix", "index": 1}))
    result = verify_plan(plan, rows)
    assert "bus.matrix-destination-unsupported" in codes(result)
    assert not any(f.code == "bus.matrix-destination-unsupported" and f.severity == "error"
                   for f in result.findings)


def test_a_group_with_no_members_at_all_is_flagged(oracle, rows):
    """A DCA or mute group can be declared and joined by nothing -- neither
    a channel nor a bus -- and still be schema-valid. That is exactly the
    shape the critic pass caught by hand on the first real hosted run
    (touringband's 'FX' DCA and 'FX Busses' mute group, both declared,
    both empty, because nothing could join a bus to either yet)."""
    plan = mutate(oracle, lambda p: p["dcas"].update({"Empty DCA": {"index": 16}}))
    result = verify_plan(plan, rows)
    empty = [f for f in result.findings if f.code == "group.empty"]
    assert any("Empty DCA" in f.message for f in empty)
    # INFO since 2026-09-25 (FR-6.2, the judgement-vs-patching rule): an empty
    # group is a working desk with one object too many, never a stop.
    assert all(f.severity == "info" for f in empty)


def test_a_bus_nothing_sends_to_is_an_info(oracle, rows):
    """FR-6.2's deterministic half, for busses: declared, fed by nothing."""
    plan = mutate(oracle, lambda p: p["busses"].update({
        "Spare": {"destination": {"type": "main", "index": 1}, "index": 15, "mono": False}}))
    result = verify_plan(plan, rows)
    empty = [f for f in result.findings if f.code == "bus.empty"]
    assert [f.where for f in empty] == ["busses[Spare]"]
    assert empty[0].severity == "info"
    assert result.ok


def test_a_bus_joining_a_group_counts_as_a_member(oracle, rows):
    """The other half of the empty-group check: a bus-only membership
    must count, or every DCA/mute-group that only a bus joins
    would misreport as empty."""
    plan = mutate(oracle, lambda p: p["busses"]["Monitor 1"].__setitem__("dca", ["Drums"]))
    result = verify_plan(plan, rows)
    assert not any(f.code == "group.empty" and "Drums" in f.message for f in result.findings)


# --- Multiple simultaneous destinations/sockets ---


def test_a_bus_routing_to_main_and_a_dedicated_output_is_not_flagged(oracle, rows):
    """Festival_STANDALONE.snap's real finding: a bus can route to Main
    AND a dedicated output at the same time -- both fully resolved should
    pass clean, not trip bus.no-destination or bus.unresolved-destination."""
    plan = mutate(oracle, lambda p: _set_bus_destination_list(p, "Monitor 1", [
        {"type": "main", "index": 1},
        {"type": "dedicated_output", "label": "IEM tap",
         "socket": {"group": "LCL", "sockets": [21]}, "sockets": [{"group": "LCL", "sockets": [21]}]},
    ]))
    result = verify_plan(plan, rows)
    assert not any(f.code in ("bus.no-destination", "bus.unresolved-destination") for f in result.findings)


def test_one_bad_destination_among_several_is_still_caught(oracle, rows):
    plan = mutate(oracle, lambda p: _set_bus_destination_list(p, "Monitor 1", [
        {"type": "main", "index": 1},
        {"type": "dedicated_output", "label": "Bad tap",
         "socket": {"group": "LCL", "sockets": [41]}, "sockets": [{"group": "LCL", "sockets": [41]}]},
    ]))
    result = verify_plan(plan, rows)
    assert "output.socket-out-of-range" in codes(result)


def test_an_output_fanning_out_to_several_sockets_all_get_checked(oracle, rows):
    plan = mutate(oracle, lambda p: p["outputs"]["Matrix"].update(
        socket={"group": "USB", "sockets": [45]},
        sockets=[{"group": "USB", "sockets": [45]}, {"group": "LCL", "sockets": [41]}],
    ))
    result = verify_plan(plan, rows)
    assert "output.socket-out-of-range" in codes(result)


# --- A dedicated output's physical socket(s) depend on the
# bus's own width. Until 2026-09-25 an unstated one BLOCKED the plan
# (`bus.unstated-width-for-dedicated-output`); under the
# judgement-vs-patching rule it is now decided and announced instead ---


def _width_notes(result, bus):
    return [f for f in result.findings
            if f.code == "inferred.bus-width" and f.where == f"busses[{bus}]"]


def test_a_dedicated_output_with_unstated_bus_width_is_decided_not_blocked(oracle, rows):
    """Monitor 1 feeds one wedge socket: the fallback makes it mono and
    says so, at INFO, naming what it decided from. Nothing blocks."""
    plan = mutate(oracle, lambda p: p["busses"]["Monitor 1"].__setitem__("mono", None))
    result = verify_plan(plan, rows)
    assert "bus.unstated-width-for-dedicated-output" not in codes(result)
    [note] = _width_notes(result, "Monitor 1")
    assert note.severity == "info"
    assert "width set to mono" in note.message
    assert "fallback" in note.message and "single socket" in note.message
    # verify decides on a copy; the plan it was handed is not rewritten.
    assert plan["busses"]["Monitor 1"]["mono"] is None


def test_a_bus_on_a_socket_pair_is_decided_stereo(oracle, rows):
    plan = mutate(oracle, lambda p: (p["busses"]["Monitor 1"].__setitem__("mono", None),
                                     _set_bus_socket(p, "Monitor 1", "LCL", [1, 2])))
    [note] = _width_notes(verify_plan(plan, rows), "Monitor 1")
    assert "width set to stereo" in note.message and "socket pair" in note.message


@pytest.mark.parametrize("width", [True, False])
def test_a_stated_bus_width_draws_no_note(oracle, rows, width):
    plan = mutate(oracle, lambda p: p["busses"]["Monitor 1"].__setitem__("mono", width))
    result = verify_plan(plan, rows)
    assert not _width_notes(result, "Monitor 1")


def test_an_unstated_width_on_a_main_only_bus_takes_the_factory_stereo(oracle, rows):
    """Drums routes to Main only -- no jack depends on its width, so the
    fallback leaves it at the WING's own factory width, and says so."""
    plan = mutate(oracle, lambda p: p["busses"]["Drums"].__setitem__("mono", None))
    [note] = _width_notes(verify_plan(plan, rows), "Drums")
    assert "width set to stereo" in note.message and "factory" in note.message


def test_a_generator_marked_width_is_reported_as_the_generators(oracle, rows):
    plan = mutate(oracle, lambda p: p["busses"]["Monitor 1"].update(
        mono=True, inferred=[{"field": "mono", "by": "model",
                              "basis": "a wedge send on one socket"}]))
    [note] = _width_notes(verify_plan(plan, rows), "Monitor 1")
    assert "decided by the generator: a wedge send on one socket" in note.message


def test_a_third_socket_on_one_source_is_rejected(oracle, rows):
    """apply.py's _output_slot only has an L (position 0) and an R
    (position 1) slot to give out per bus/Main/Matrix -- a third socket in
    the same clause would silently collide with the NEXT object's own L
    slot, exactly the wrong-jack bug an earlier change was filed for."""
    plan = mutate(oracle, lambda p: _set_bus_socket(p, "Monitor 1", "LCL", [1, 2, 3]))
    result = verify_plan(plan, rows)
    assert "output.too-many-sockets-for-one-source" in codes(result)


def test_a_null_send_mode_is_decided_with_a_note_not_refused(oracle, rows):
    """compiler.py deliberately left a bus_send's mode null when the
    conventions never stated pre/post -- a real conventions file hit this.
    It used to be the ERROR value.send-mode-unknown (after, before that, a
    confusing generic "schema" finding as well). Pre vs post is a
    judgement call, not a patching fact, so since 2026-09-25
    it is decided -- post into a bus that reaches a Main -- and noted."""
    plan = mutate(oracle, lambda p: p["channels"][0]["bus_sends"][0].__setitem__("mode", None))
    bus = plan["channels"][0]["bus_sends"][0]["bus"]
    result = verify_plan(plan, rows)
    assert "value.send-mode-unknown" not in codes(result)
    assert "schema" not in codes(result)
    notes = [f for f in result.findings
             if f.code == "inferred.send-mode" and f.where == f"busses[{bus}]"]
    assert notes and notes[0].severity == "info"
    assert plan["channels"][0]["name"] in notes[0].message


def test_dropped_input_is_an_error_but_declaring_it_is_a_warning(oracle, rows):
    dropped = mutate(oracle, lambda p: p["channels"].pop())
    assert any(f.code == "reconcile.dropped-input" and f.severity == "error"
               for f in verify_plan(dropped, rows).findings)

    name = oracle["channels"][-1]["source"]["input"]
    declared = copy.deepcopy(dropped)
    declared["unassigned_inputs"] = [name]
    result = verify_plan(declared, rows)
    assert not any(f.code == "reconcile.dropped-input" for f in result.findings)
    assert any(f.code == "reconcile.deliberately-unassigned" and f.severity == "warning"
               for f in result.findings)


def test_phantom_on_passive_ribbon_is_an_error(oracle, rows):
    plan = mutate(oracle, lambda p: p["channels"][0]["source"].update(model="Royer R-121", phantom=True))
    result = verify_plan(plan, rows)
    assert "safety.phantom-on-passive-ribbon" in codes(result)
    assert not result.ok


def test_lcl_output_asymmetry_is_explained(oracle, rows):
    # LCL has 24 inputs but only 8 outputs on a Compact -- the message has
    # to say so, or the finding reads like a typo.
    plan = mutate(oracle, lambda p: _set_bus_socket(p, "Monitor 1", "LCL", [20]))
    msg = next(f.message for f in verify_plan(plan, rows).findings
               if f.code == "output.socket-out-of-range")
    assert "24 INPUTS but only 8 outputs" in msg


def test_malformed_plan_reports_rather_than_raises(rows):
    assert not verify_plan({"channels": "not a list"}, rows).ok
    assert not verify_plan([], rows).ok


def test_warnings_alone_do_not_block(oracle, rows):
    """A plan with findings but no errors must still be applicable --
    otherwise every warning becomes a stop and operators learn to ignore
    the whole report."""
    plan = mutate(oracle, lambda p: p["outputs"]["Matrix"].__setitem__(
        "socket", {"group": "USB", "sockets": [45]}))          # clears the one real error
    orphan = plan["channels"].pop()["source"]["input"]          # leaves a warning-only finding
    plan["unassigned_inputs"] = [orphan]

    result = verify_plan(plan, rows)
    assert result.errors == [], [str(f) for f in result.errors]
    # TRAX (the popped channel) was the sole member of the "Tracks" DCA
    # and mute group, so removing it also -- correctly -- empties both:
    # two notes (INFO since 2026-09-25), still no error, still applicable.
    assert {f.code for f in result.warnings} == {"reconcile.deliberately-unassigned", OFF_MAIN}
    assert "group.empty" in {f.code for f in result.infos}
    assert result.ok is True
    assert "APPLICABLE" in result.report()


# --------------------------------------------------------------------------
# socket bounds are per-model, and an unknown model is a hard stop
# --------------------------------------------------------------------------

def _patch_first_channel(plan, group, sockets):
    p = copy.deepcopy(plan)
    p["channels"][0]["patch"] = {"group": group, "sockets": sockets}
    return p


def test_aux_sockets_are_refused_on_a_compact_though_the_address_tree_has_them():
    """The bug this issue was really about.

    `/io/in/AUX/1..8` is present in the 2026-09-08 walk of the maintainer's
    Compact, so the address-space table says AUX 1..8 are fine. The
    protocol reference (pp. 11-12) says the Compact has no local aux jacks
    at all -- local Aux I/O is a full-size-WING feature. Before an earlier change this
    plan verified clean and could not be patched.
    """
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = _patch_first_channel(oracle, "AUX", [1])
    result = verify_plan(plan, console_model="wing-compact")
    assert "patch.socket-out-of-range" in codes(result)
    assert any("no AUX inputs at all" in f.message for f in result.errors)


def test_the_same_aux_patch_is_fine_on_a_full_size_wing():
    """The other half: it is a real socket there, so the same plan passes.
    A bound that rejected AUX everywhere would be wrong in the other
    direction."""
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = _patch_first_channel(oracle, "AUX", [1])
    result = verify_plan(plan, console_model="wing-full")
    assert "patch.socket-out-of-range" not in codes(result)


def test_local_input_9_is_fine_on_a_compact_and_impossible_on_a_full():
    """The Full has 8 local inputs, the Rack and Compact have 24 (pp. 11-12,
    cross-checked against p.4's preamp count). Same plan, two verdicts --
    which is the whole reason the model has to be stated."""
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = _patch_first_channel(oracle, "LCL", [9])
    assert "patch.socket-out-of-range" not in codes(verify_plan(plan, console_model="wing-compact"))
    assert "patch.socket-out-of-range" not in codes(verify_plan(plan, console_model="wing-rack"))

    full = verify_plan(plan, console_model="wing-full")
    assert "patch.socket-out-of-range" in codes(full)
    assert any("1..8" in f.message for f in full.errors)


@pytest.mark.parametrize("model", [None, "", "not-a-real-console"])
def test_an_unstated_or_unknown_console_model_is_an_error(model):
    """"an unknown console-model is a hard stop -- we
    have no way of knowing what its capabilities are and any plan would be
    meaningless.\""""
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = copy.deepcopy(oracle)
    plan.get("meta", {}).pop("console_model", None)
    result = verify_plan(plan, console_model=model)
    assert "console.unknown-model" in codes(result)
    assert not result.ok


def test_skipped_socket_checks_are_said_to_be_skipped_not_silently_passed():
    """This module's standing rule: a check that did not run must never
    read as one that passed. Without a model the socket bound is
    unknowable, so it is reported as not-checked alongside the hard stop.
    """
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = copy.deepcopy(oracle)
    plan.get("meta", {}).pop("console_model", None)
    # AUX 1 does not exist on a Compact, but with no model we cannot know
    # that -- so the finding we must NOT produce is a clean bill of health.
    plan = _patch_first_channel(plan, "AUX", [1])
    result = verify_plan(plan, console_model=None)
    assert "patch.not-checked" in codes(result)


def test_a_plan_states_its_own_console_model_and_that_is_enough():
    """A plan built by Atoo records `meta.console_model`, so verifying
    it later -- from a file, by someone who wasn't there -- checks it
    against the console it was actually built for."""
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = _patch_first_channel(oracle, "AUX", [1])
    plan.setdefault("meta", {})["console_model"] = "wing-full"
    assert "patch.socket-out-of-range" not in codes(verify_plan(plan))

    plan["meta"]["console_model"] = "wing-compact"
    assert "patch.socket-out-of-range" in codes(verify_plan(plan))


def test_an_explicit_model_overrides_the_plans_own():
    """The flag wins -- you are holding the console, the file is not."""
    oracle = json.loads((FIXTURES / "touringband.plan.json").read_text())
    plan = _patch_first_channel(oracle, "AUX", [1])
    plan.setdefault("meta", {})["console_model"] = "wing-full"
    assert "patch.socket-out-of-range" in codes(
        verify_plan(plan, console_model="wing-compact"))


# patch.stereo-pair-not-odd-even
# --------------------------------------------------------------------------
#
# Two sockets is necessary but not sufficient. The protocol PDF p.225 says
# the desk's routing hardware forms a stereo pair only as [odd, even]
# consecutive SOURCE numbers, and gives both failure shapes by example --
# LOCAL IN 2 + 3 (wrong parity) and WLIVE PLAY 1 + 33 (not adjacent).
#
# These build a one-channel plan and call `_check_patch` directly rather
# than mutating the shared oracle, which has no stereo channel: a stereo
# channel bolted onto it would also move reconciliation, and a test that
# has to be read twice to see which check it is pinning is not pinning it.

def _patch_result(sockets, *, stereo=True, group="A"):
    from atoo.verify_plan import VerifyResult, _check_patch

    plan = {"channels": [{
        "name": "Keys",
        "source": {"input": "Keys L", "stereo": stereo, "phantom": False},
        "patch": {"group": group, "sockets": sockets, "stated": True},
    }]}
    result = VerifyResult()
    # An earlier change made socket bounds per-model, so _check_patch takes the model.
    # The pairing rule this helper exercises is model-independent (it is a
    # property of the desk's routing hardware, protocol PDF p.225), so any
    # real model serves -- the Compact is what the rest of this module uses.
    _check_patch(plan, result, "wing-compact")
    return result


PAIR_CODE = "patch.stereo-pair-not-odd-even"


@pytest.mark.parametrize("sockets", [[1, 2], [15, 16], [23, 24]])
def test_a_legal_odd_even_stereo_pair_passes(sockets):
    assert PAIR_CODE not in codes(_patch_result(sockets))


def test_a_stereo_pair_starting_on_an_even_socket_is_refused():
    """The PDF's own first example: LOCAL IN 2 and LOCAL IN 3 cannot be a
    pair. Nothing downstream would catch it -- apply writes ST mode to both
    sockets and neither write fails -- so a wrong patch would report as a
    clean apply."""
    result = _patch_result([2, 3])
    assert PAIR_CODE in codes(result)
    finding = next(f for f in result.findings if f.code == PAIR_CODE)
    assert finding.severity == "error"
    assert "even socket" in finding.message


def test_a_non_adjacent_stereo_pair_is_refused():
    """The PDF's second example, in miniature: two sources of the right
    parity but not neighbours (WLIVE PLAY 1 and 33) are still not a pair.
    Both halves of the rule, not just the odd/even half."""
    result = _patch_result([1, 5])
    assert PAIR_CODE in codes(result)
    assert "not consecutive" in next(f for f in result.findings if f.code == PAIR_CODE).message


def test_a_descending_stereo_pair_is_refused():
    assert PAIR_CODE in codes(_patch_result([16, 15]))


def test_a_mono_channel_is_not_subject_to_the_pairing_rule():
    """An even socket is perfectly legal for a mono source -- the rule is
    about forming a pair, not about the socket."""
    assert PAIR_CODE not in codes(_patch_result([2], stereo=False))


def test_the_wrong_socket_count_is_not_also_reported_as_a_pairing_error():
    """One fact, one finding: three sockets is already
    patch.stereo-socket-count, and a second finding on the same mistake
    only makes the report harder to read."""
    result = _patch_result([1, 2, 3])
    assert "patch.stereo-socket-count" in codes(result)
    assert PAIR_CODE not in codes(result)


# ---------------------------------------------------------------------------
# what the verifier must NOT say, which is the half a
# mutation table cannot show.
# ---------------------------------------------------------------------------


def test_an_aux_low_band_may_be_a_cut_where_a_channels_may_not(oracle, rows):
    """`ch.eq.leq` is list [PEQ, SHV]; `aux.eq.leq` is list [PEQ, SHV,
    CUT]. One CHANNEL_SCHEMA serves both banks, so the schema holds their
    union and this is the only place the bank actually decides."""
    def cut_on_an_aux(p):
        p["channels"][0]["bank"] = "aux"
        p["channels"][0]["processing"]["eq"] = {"bands": [{"band": "low", "shape": "CUT", "freq_hz": 100.0}]}

    def cut_on_a_channel(p):
        p["channels"][0]["processing"]["eq"] = {"bands": [{"band": "low", "shape": "CUT", "freq_hz": 100.0}]}

    assert "value.eq-shape-unavailable" not in codes(verify_plan(mutate(oracle, cut_on_an_aux), rows))
    assert "value.eq-shape-unavailable" in codes(verify_plan(mutate(oracle, cut_on_a_channel), rows))


def test_a_bus_may_use_the_numbered_bands_a_channel_cannot(oracle, rows):
    def six_bands_on_a_bus(p):
        p["busses"]["Monitor 1"]["processing"] = {
            "eq": {"bands": [{"band": "5", "gain_db": 1.0}, {"band": "6", "gain_db": -1.0}]},
            "tilt_db": -2.0,
        }

    assert "value.eq-band-unavailable" not in codes(verify_plan(mutate(oracle, six_bands_on_a_bus), rows))


def test_processing_on_an_output_with_no_kind_is_flagged_as_unwritable(oracle, rows):
    """An output that never says whether it is a Main or a Matrix has no
    internal strip to put an EQ on -- apply.py refuses to guess one from
    the name, so a plan that states one is stating something that cannot
    land."""
    def eq_without_a_kind(p):
        p["outputs"]["Main"]["kind"] = None
        p["outputs"]["Main"]["processing"] = {"eq": {"bands": [{"band": "1", "gain_db": 1.0}]}}

    assert "value.eq-strip-unidentified" in codes(verify_plan(mutate(oracle, eq_without_a_kind), rows))


def test_the_oracle_plan_raises_no_eq_findings_at_all(oracle, rows):
    """The plan predates this field entirely. Adding an optional field
    must not make an existing plan newly non-compliant."""
    assert not any(c.startswith("value.eq-") for c in codes(verify_plan(copy.deepcopy(oracle), rows)))


def test_an_eq_on_an_unknown_bank_is_reported_not_raised(oracle, rows):
    """The verifier's job is to survive a malformed plan and describe it.
    A bank this project has no EQ facts for used to reach a bare dict
    lookup -- which would have failed the whole verify run rather than
    reporting the bank, in the one module that must never do that."""
    def nonsense_bank(p):
        p["channels"][0]["bank"] = "nonsense"
        p["channels"][0]["processing"]["eq"] = {"model": "PIA", "bands": [{"band": "1", "gain_db": 1.0}]}

    found = codes(verify_plan(mutate(oracle, nonsense_bank), rows))
    assert "value.eq-strip-unknown" in found
    assert "strip.unknown-bank" in found     # the underlying cause still reported by its own check


def test_a_presend_eq_on_an_aux_strip_is_refused(oracle, rows):
    """An aux strip has no `peq` node, the same confirmed absence as
    `flt`. The main EQ, by contrast, an aux strip does have -- so this
    must not read as "aux strips have no EQ"."""
    def peq_on_an_aux(p):
        p["channels"][0]["bank"] = "aux"
        p["channels"][0]["processing"]["presend_eq"] = {"bands": [{"band": "1", "gain_db": 2.0}]}
        p["channels"][0]["processing"]["eq"] = {"bands": [{"band": "1", "gain_db": 2.0}]}

    found = codes(verify_plan(mutate(oracle, peq_on_an_aux), rows))
    assert "value.presend-eq-unavailable" in found
    assert not any(c.startswith("value.eq-") for c in found)


# ---------------------------------------------------------------------------
# Colour: the plan promising something apply does not do. 
# ---------------------------------------------------------------------------

COLOUR_CODE = "strip.colour-not-writable"


def test_a_colour_the_desk_does_not_have_is_reported(oracle):
    """Narrowed on 2026-09-22, when the palette was measured on hardware.

    It used to fire for EVERY stated colour, because no name-to-index
    mapping existed and none of them could be written. Now most of them
    can, and what is left is the case it should always have been about: a
    colour word the console has no equivalent for. touringband's "Pink" was
    the real example until the desk named its index 11 Pink (A24,
    2026-09-28); "Gold" is one it still lacks."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = "Gold"
    result = verify_plan(plan)
    hit = next(f for f in result.findings if f.code == COLOUR_CODE)
    assert hit.severity == SEVERITY_WARNING, "a colour must not block an apply"
    assert "Gold" in hit.message
    assert ("The desk's eighteen are Navy, Blue, Violet, Turquoise, Green, Lime, Yellow, Rust, "
            "Red, Salmon, Pink, Purple, Amber, Cyan, Orange, Mint, Grey, White.") in hit.message, \
        "the finding should list what IS available, in the desk's own names"


@pytest.mark.parametrize("word", ["Red", "Pink", "Amber", "Orange"])
def test_the_desks_own_names_draw_no_finding(oracle, word):
    """A24 (2026-09-28): the desk's words for 9, 11, 13 and 15. "Pink"
    used to be the standing example of a colour the desk lacked."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = word
    found = codes(verify_plan(plan))
    assert COLOUR_CODE not in found and "strip.colour-alias" not in found


@pytest.mark.parametrize("word, desk, index", [("Crimson", "Red", 9), ("Magenta", "Pink", 11)])
def test_a_retired_colour_name_resolves_and_says_which_desk_colour_it_became(oracle, word, desk, index):
    """Atoo called 9 Crimson and 11 Magenta until the desk was asked
    (A24). A conventions file written with them keeps working, and an INFO
    says what the desk will call it -- an inferred value that announces
    itself."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = word
    plan["channels"][1]["color"] = word
    result = verify_plan(plan)
    assert COLOUR_CODE not in codes(result)
    hits = [f for f in result.findings if f.code == "strip.colour-alias"]
    assert len(hits) == 1, "one INFO per retired name, not one per strip"
    hit = hits[0]
    assert hit.severity == Severity.INFO
    assert f"'{word}' is the desk's {desk} ({index})" in hit.message
    assert plan["channels"][0]["name"] in hit.message and plan["channels"][1]["name"] in hit.message


def test_a_colour_the_desk_does_have_draws_no_finding(oracle):
    """`apply` resolves these through the measured palette now, so there
    is nothing to warn about. Before the measurement every one of these
    was silently dropped at write time."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch.pop("col", None)
        ch["color"] = "Red"
    assert COLOUR_CODE not in codes(verify_plan(plan))


def test_it_is_one_finding_for_the_plan_not_one_per_strip(oracle):
    """Several identical warnings is how a real finding gets scrolled
    past. Same call `preset.no-library` already makes."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch.pop("col", None)
        ch["color"] = "Chartreuse"
    hits = [f for f in verify_plan(plan).findings if f.code == COLOUR_CODE]
    assert len(hits) == 1
    assert hits[0].where == "plan"
    assert f"{len(plan['channels'])} strip(s)" in hits[0].message


def test_a_writable_colour_draws_no_finding(oracle):
    """`col` is the integer the console actually takes. A plan that sets
    it is not making a promise it cannot keep, whatever `color` says."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch["col"] = 3
    assert COLOUR_CODE not in codes(verify_plan(plan))


def test_no_colour_stated_draws_no_finding(oracle):
    """Not stating a colour is a perfectly good plan -- the finding is
    about the gap between stating one and writing one, not about colour."""
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"]:
        ch.pop("color", None)
        ch.pop("col", None)
    assert COLOUR_CODE not in codes(verify_plan(plan))


# ---------------------------------------------------------------------------
# One input feeding two strips. Legitimate, and until 2026-09-22 refused.
# ---------------------------------------------------------------------------

DUPLICATED = "reconcile.duplicated-input"


def _two_strips_on_one_input(oracle):
    """A monitor split: a second strip off the same mic, processed for the
    wedges. The case `atoo/domain/knowledge.md` describes."""
    plan = copy.deepcopy(oracle)
    first = plan["channels"][0]
    mon = copy.deepcopy(first)
    mon["channel"] = 30
    mon["name"] = f"{first['name']} IEM"
    mon["patch"] = dict(first["patch"])
    plan["channels"].append(mon)
    return plan


def test_two_strips_on_one_input_does_not_block_the_apply(oracle, rows):
    """It used to, with the message "one physical source cannot be two
    channels" -- which is not true. A second strip
    for monitors, or one socket reused between acts at a festival.

    Refusing it meant a monitor-split plan could never be applied, which
    is the one outcome that is definitely wrong."""
    result = verify_plan(_two_strips_on_one_input(oracle), rows)
    assert DUPLICATED not in [f.code for f in result.errors], (
        "a legitimate monitor split is being refused:\n" + result.report())


def test_two_strips_on_one_input_is_still_reported(oracle, rows):
    """Downgraded, not deleted. Nothing in the plan says whether the share
    was asked for -- his rule is that a deliberate one is called out in
    the input list or the instructions -- so it still has to be looked
    at."""
    result = verify_plan(_two_strips_on_one_input(oracle), rows)
    hit = next(f for f in result.findings if f.code == DUPLICATED)
    assert hit.severity == SEVERITY_WARNING
    assert "instructions" in hit.message, \
        "the finding should say what to check, not just that it happened"


def test_the_shared_head_amp_is_spelled_out(oracle, rows):
    """The constraint that actually bites: one preamp, so gain and phantom
    are common to both strips whatever the plan says."""
    result = verify_plan(_two_strips_on_one_input(oracle), rows)
    hit = next(f for f in result.findings if f.code == DUPLICATED)
    assert "head amp" in hit.message and "phantom" in hit.message


# --- expansion bays: the check this module deliberately cannot make -------
#
# `CRD`/`MOD` are bays, not sockets: the desk answers all 64
# addresses with an empty slot and accepts the patch. Offline verification
# has no way to know what is fitted, so what is tested here is that it
# SAYS SO -- the same contract `patch.not-checked` and
# `reconcile.not-checked` have.

BAY_NOT_CHECKED = "patch.expansion-bay-not-checked"


def _patched_from(plan, group, sockets=(1,)):
    def mutate_it(p):
        p["channels"][0]["patch"] = {"group": group, "sockets": list(sockets), "stated": True}
        p["channels"][0]["source"]["stereo"] = len(sockets) == 2
    return mutate(plan, mutate_it)


def test_a_plan_with_no_expansion_bay_patch_says_nothing_about_bays(oracle, rows):
    """The oracle patches AES50-A throughout. A warning on every plan
    would be noise, and noise is what an earlier change is already about."""
    assert BAY_NOT_CHECKED not in codes(verify_plan(oracle, rows))


@pytest.mark.parametrize("group", ["CRD", "MOD"])
def test_a_patch_from_an_expansion_bay_is_reported_as_unchecked(oracle, rows, group):
    result = verify_plan(_patched_from(oracle, group), rows)
    hit = next(f for f in result.findings if f.code == BAY_NOT_CHECKED)
    assert hit.severity == SEVERITY_WARNING, "an offline warning, never a refusal"
    assert group in hit.message
    assert hit.issue == 115


def test_the_bay_warning_says_where_the_check_actually_happens(oracle, rows):
    """A "not checked" finding that does not say who checks it instead is
    just an apology. The fix text has to name the two addresses and the
    command that reads them."""
    result = verify_plan(_patched_from(oracle, "MOD"), rows)
    hit = next(f for f in result.findings if f.code == BAY_NOT_CHECKED)
    assert "apply" in hit.fix
    assert "/$syscfg/opt_mod" in hit.fix and "/cards/$type" in hit.fix


def test_the_bay_warning_is_raised_once_per_plan_not_once_per_channel(oracle, rows):
    """Nineteen channels off a Dante module is one fact about the plan,
    not nineteen findings."""
    def all_on_mod(p):
        for i, ch in enumerate(p["channels"], start=1):
            ch["patch"] = {"group": "MOD", "sockets": [i], "stated": True}
            ch["source"]["stereo"] = False
    result = verify_plan(mutate(oracle, all_on_mod), rows)
    assert [f.code for f in result.findings].count(BAY_NOT_CHECKED) == 1
    hit = next(f for f in result.findings if f.code == BAY_NOT_CHECKED)
    assert "19 time(s)" in hit.message


def test_an_output_routed_into_an_expansion_bay_counts_too(oracle, rows):
    """The other direction is the same fault: a Matrix patched to a card
    bay with no card in it is a mix going nowhere, and the desk accepts
    that write just as happily as it accepts the input patch."""
    def main_to_crd(p):
        p["outputs"]["Main"]["socket"] = {"group": "CRD", "sockets": [1]}
        p["outputs"]["Main"]["sockets"] = [{"group": "CRD", "sockets": [1]}]
    result = verify_plan(mutate(oracle, main_to_crd), rows)
    assert BAY_NOT_CHECKED in codes(result)


def test_the_bay_warning_never_blocks_an_apply(oracle, rows):
    """It is a warning by design: on a desk that HAS the card this plan is
    perfectly correct, and the only place the difference is knowable is at
    the console. Making it an error would refuse every legitimate Dante
    rig offline."""
    result = verify_plan(_patched_from(oracle, "MOD"), rows)
    assert BAY_NOT_CHECKED not in {f.code for f in result.errors}


# user_sources: a stereo pair from two disjoint sources
# --------------------------------------------------------------------------
#
# An earlier change taught the verifier that a stereo pair is [odd, even] and consecutive,
# and the desk confirmed the rule by refusing an even-first pair by hand on
# 2026-09-21. An earlier change is the case that rule left with nowhere to go: two halves
# that are neither adjacent nor in the same group, which the protocol PDF's
# own example (WLIVE PLAY 1 and WLIVE PLAY 33) is.
#
# The desk's answer is its USR group -- 56 virtual slots, USR 1..24 user
# signals (source is a strip) and USR 25..56 user patches (source is a jack),
# each slot holding exactly one source. A stereo one is two CONSECUTIVE slots,
# odd first. So the pairing rule is not bypassed at all: it applies to the
# slot numbers, and the disjointness moves down one level into each slot's
# own assignment. These tests pin both halves of that -- that the pair still
# has to be legal, and that the slots behind it are checked.

from atoo import console_facts as _facts  # noqa: E402
from atoo.verify_plan import SEVERITY_ERROR  # noqa: E402


def _usr_plan(sockets, user_sources, *, stereo=True):
    """A one-channel plan patched into the USR group, plus the slot
    definitions behind it. Built here rather than mutated out of the oracle
    for the same reason the pairing tests above are: the oracle has no
    stereo channel, and bolting one on would move reconciliation too."""
    return {
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Trax",
            "source": {"input": "Trax L", "stereo": stereo, "phantom": False},
            "patch": {"group": "USR", "sockets": sockets, "stated": True},
            "processing": {"hpf_hz": None, "preset": None},
            "fader": {"fader_db": None, "muted": None},
            "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
        }],
        "dcas": {}, "mute_groups": {}, "busses": {},
        "outputs": {"Main": {"kind": "main", "index": 1,
                             "socket": {"group": "LCL", "sockets": [1, 2]}}},
        "user_sources": user_sources,
        # An unstated console model is a hard error, and the socket
        # bounds these tests are about cannot be checked without one.
        "meta": {"console_model": "wing-compact"},
    }


# The PDF's own worked example, as a plan: WLIVE PLAY 1 and 33 -- two sources
# 32 apart on one card -- reaching a single stereo strip through two
# consecutive user patches.
DISJOINT_PAIR = _usr_plan([25, 26], [
    {"slot": 25, "name": "Trax L", "source": {"group": "CRD", "index": 1},
     "stated": True},
    {"slot": 26, "name": "Trax R", "source": {"group": "CRD", "index": 33},
     "stated": True},
])


def test_the_pdfs_own_disjoint_pair_is_now_representable():
    """The headline: a stereo pair whose halves are CRD 1 and CRD 33
    could not be written down at all before this. It is one plan now, and
    the only finding it raises says what offline cannot know: whether the
    card bay has a card in it."""
    result = verify_plan(DISJOINT_PAIR)
    assert not result.errors, result.report()
    assert "patch.user-source-undefined" not in codes(result)
    assert PAIR_CODE not in codes(result)


def test_the_odd_even_rule_still_applies_to_the_usr_slots_themselves():
    """The escape hatch does not repeal the hardware rule -- it satisfies it
    one layer down. Two user patches at 26 and 27 are as unpairable as two
    XLRs at 2 and 3, and the same finding says so."""
    plan = _usr_plan([26, 27], [
        {"slot": 26, "source": {"group": "CRD", "index": 1}},
        {"slot": 27, "source": {"group": "CRD", "index": 33}},
    ])
    assert PAIR_CODE in codes(verify_plan(plan))


def test_a_usr_patch_with_nothing_defining_the_slot_is_warned_about():
    """The hidden-desk-state case an earlier change was filed about: `USR` was already a
    patchable group, so a plan could point at a slot whose meaning lived only
    in someone's manual setup, and verify said nothing."""
    plan = _usr_plan([25, 26], [])
    result = verify_plan(plan)
    hits = [f for f in result.findings if f.code == "patch.user-source-undefined"]
    assert len(hits) == 2
    assert all(f.severity == SEVERITY_WARNING for f in hits)
    assert "user patch" in hits[0].message
    # No `issue=`: that renders as "not something you can fix", and this one
    # the engineer fixes by stating the slot.
    assert hits[0].issue is None


def test_an_undefined_usr_slot_is_a_warning_and_never_blocks_apply():
    """A desk-side USER SIGNAL set up by hand is a legitimate thing to plan
    against -- it just cannot be checked from here. Refusing it offline would
    refuse a working rig, the same call `patch.expansion-bay-not-checked`
    makes."""
    result = verify_plan(_usr_plan([25, 26], []))
    assert "patch.user-source-undefined" not in {f.code for f in result.errors}


def test_apply_writes_the_usr_slots_so_verify_no_longer_warns_it_does_not():
    """`apply` writes `user_sources` (`apply.user_source_targets`),
    so the warning that it did not is gone, and the disjoint pair's two slots
    are written: what each takes and its name."""
    from atoo.apply import user_source_targets

    assert "user-source.not-written-by-apply" not in codes(verify_plan(DISJOINT_PAIR))
    written = {t.address: t.compute_value(None) for t in user_source_targets(DISJOINT_PAIR)}
    assert written == {"/io/in/USR/25/user/grp": "CRD", "/io/in/USR/25/user/in": 1,
                       "/io/in/USR/25/name": "Trax L", "/io/in/USR/26/user/grp": "CRD",
                       "/io/in/USR/26/user/in": 33, "/io/in/USR/26/name": "Trax R"}


@pytest.mark.parametrize("slot", [0, 57, 100, "25", None])
def test_a_slot_outside_the_usr_range_is_refused(slot):
    plan = _usr_plan([25], [{"slot": slot, "source": {"group": "CRD", "index": 1}}],
                     stereo=False)
    assert "user-source.slot-out-of-range" in codes(verify_plan(plan))


def test_one_slot_cannot_be_defined_twice():
    """One slot holds one source, so the second definition would quietly
    overwrite the first -- and a copy-pasted entry with the slot number not
    updated looks exactly like this."""
    plan = _usr_plan([25, 26], [
        {"slot": 25, "source": {"group": "CRD", "index": 1}},
        {"slot": 25, "source": {"group": "CRD", "index": 33}},
    ])
    assert "user-source.duplicate-slot" in codes(verify_plan(plan))


def test_a_user_patch_cannot_take_a_strip_as_its_source():
    """USR 25..56 connect a physical jack straight through -- that is the
    whole difference from a user signal. `BUS` is a source the other kind
    takes, and the message says so rather than just listing the enum."""
    plan = _usr_plan([25], [{"slot": 25, "source": {"group": "BUS", "index": 3}}],
                     stereo=False)
    result = verify_plan(plan)
    hit = next(f for f in result.findings if f.code == "user-source.group-not-allowed")
    assert hit.severity == SEVERITY_ERROR
    assert "user patch" in hit.message and "user signal" in hit.message


def test_a_user_signal_cannot_take_a_physical_socket_as_its_source():
    """And the other way round: USR 1..24 tap a strip, never a jack. The two
    enums are genuinely different, which is why the JSON schema's union of
    them cannot be the last word."""
    plan = _usr_plan([1], [{"slot": 1, "source": {"group": "LCL", "index": 3}}],
                     stereo=False)
    assert "user-source.group-not-allowed" in codes(verify_plan(plan))


def test_aux_means_the_strips_on_a_user_signal_and_the_jacks_on_a_user_patch():
    """`AUX` is the one spelling in both enums, and it means two different
    things: 8 aux STRIPS on a user signal, 1/4" aux JACKS on a user patch.
    Both are legal, and the index bound is what separates them -- 8 strips
    either way here, so the case that bites is a Compact's zero aux jacks."""
    signal = _usr_plan([1], [{"slot": 1, "source": {"group": "AUX", "index": 8}}],
                       stereo=False)
    assert "user-source.group-not-allowed" not in codes(verify_plan(signal))
    assert "user-source.index-out-of-range" not in codes(
        verify_plan(signal, console_model="wing-compact"))

    patch = _usr_plan([25], [{"slot": 25, "source": {"group": "AUX", "index": 1}}],
                      stereo=False)
    result = verify_plan(patch, console_model="wing-compact")
    hit = next(f for f in result.findings if f.code == "user-source.index-out-of-range")
    assert "no" in hit.message or "1..0" in hit.message


def test_a_user_signal_index_is_bounded_by_the_strip_count_not_the_leaf():
    """`/io/in/USR/{n}/user.in` accepts 1..40 because channels are the widest
    of the five banks it can name. There are 16 busses, so BUS 20 is a source
    that does not exist -- and the leaf's own range would have waved it
    through."""
    plan = _usr_plan([1], [{"slot": 1, "source": {"group": "BUS", "index": 20}}],
                     stereo=False)
    result = verify_plan(plan)
    hit = next(f for f in result.findings if f.code == "user-source.index-out-of-range")
    assert hit.severity == SEVERITY_ERROR
    assert "16" in hit.message


def test_a_user_patch_index_is_bounded_by_the_panel_like_any_other_patch():
    """It is addressing the very same jacks a channel patch addresses, so it
    gets the same per-model bound -- a Full WING has 8 local inputs, not 24."""
    plan = _usr_plan([25], [{"slot": 25, "source": {"group": "LCL", "index": 20}}],
                     stereo=False)
    assert "user-source.index-out-of-range" not in codes(
        verify_plan(plan, console_model="wing-compact"))
    assert "user-source.index-out-of-range" in codes(
        verify_plan(plan, console_model="wing-full"))


@pytest.mark.parametrize("field,value", [("tap", "POST"), ("leg", "L")])
def test_tap_and_leg_are_refused_on_a_user_patch(field, value):
    """`/io/in/USR/25..56/user` carries no `tap` and no `lr` leaf at all --
    there is no strip to tap and no stereo source to take one leg of. Stating
    either would be asking apply to write an address that is not there."""
    entry = {"slot": 25, "source": {"group": "CRD", "index": 1}, field: value}
    result = verify_plan(_usr_plan([25], [entry], stereo=False))
    hit = next(f for f in result.findings
               if f.code == "user-source.field-not-on-user-patch")
    assert hit.severity == SEVERITY_ERROR
    assert field in hit.message


@pytest.mark.parametrize("field,value", [("tap", "PRE"), ("leg", "R")])
def test_tap_and_leg_are_fine_on_a_user_signal(field, value):
    entry = {"slot": 1, "source": {"group": "CH", "index": 5}, field: value}
    assert "user-source.field-not-on-user-patch" not in codes(
        verify_plan(_usr_plan([1], [entry], stereo=False)))


def test_a_defined_slot_no_channel_patches_is_said_at_info():
    """A slot nothing reads is kept, so a feed can be defined before it is
    patched -- and said, since a mistyped slot number looks exactly like this."""
    plan = _usr_plan([25], [
        {"slot": 25, "source": {"group": "CRD", "index": 1}},
        {"slot": 40, "source": {"group": "CRD", "index": 33}},
    ], stereo=False)
    result = verify_plan(plan)
    hit = next(f for f in result.findings if f.code == "user-source.unused")
    assert "USR 40" in hit.message
    assert hit.severity == Severity.INFO


def test_both_halves_of_a_stereo_pair_count_as_used():
    """The channel states both slots, the way every stereo patch states both
    sockets, so neither half is 'unused'."""
    assert "user-source.unused" not in codes(verify_plan(DISJOINT_PAIR))


def test_no_stereo_pair_can_straddle_the_two_kinds_and_no_check_was_needed():
    """One `USR` group holding two kinds of virtual source invites a pair
    with one of each in it. There is exactly one candidate -- USR 24+25, the
    slots either side of the boundary -- and the pairing rule already refuses
    it, because 24 is even. Every other consecutive pair sits wholly inside
    1..24 or wholly inside 25..56.

    So the boundary falls exactly where the hardware rule already forbids a
    pair, and the verifier needs nothing extra. This pins that, because the
    absence of a check is a decision: move the boundary to an even slot and
    it stops being true."""
    plan = _usr_plan([24, 25], [
        {"slot": 24, "source": {"group": "CH", "index": 1}},
        {"slot": 25, "source": {"group": "CRD", "index": 33}},
    ])
    result = verify_plan(plan)
    assert PAIR_CODE in codes(result)
    assert _facts.USER_KIND_BOUNDARY_IS_PROTECTED_BY_PARITY
    kinds = {_facts.user_slot_kind(n) for pair in
             [[n, n + 1] for n in range(1, _facts.INPUT_SOCKETS["USR"], 2)]
             for n in pair}
    assert kinds == {_facts.USER_SIGNAL, _facts.USER_PATCH}
    for first in range(1, _facts.INPUT_SOCKETS["USR"], 2):
        assert _facts.user_slot_kind(first) == _facts.user_slot_kind(first + 1), first


def test_a_user_patch_from_an_empty_card_bay_raises_the_bay_warning():
    """The silence is the same one an earlier change is about, one hop further back: the
    channel patches USR 25, which exists on every console, so nothing notices
    that USR 25 is fed from a slot that may have no card in it."""
    assert BAY_NOT_CHECKED in codes(verify_plan(DISJOINT_PAIR))


def test_the_stereo_pair_error_now_names_the_way_forward():
    """The actual complaint: the refusal was correct and
    offered nothing. A finding that closes off the only route a show has
    should at least say what the desk itself does about it."""
    result = _patch_result([1, 5])
    hit = next(f for f in result.findings if f.code == PAIR_CODE)
    assert "USER SIGNAL" in hit.fix and "user_sources" in hit.fix
    assert "does not write them yet" in hit.fix
    # Not tagged with `issue=`: re-cabling, or setting the USR slots up on
    # the desk, is squarely something the engineer can do -- and that tag
    # prints "not something you can fix in your conventions file".
    assert hit.issue is None


def test_a_plan_with_no_user_sources_section_is_untouched(oracle, rows):
    """Purely additive: every plan.json written before this -- the examples,
    every fixture, everything on anyone's disk -- omits the section and must
    verify exactly as it did."""
    assert "user_sources" not in oracle
    assert blocking_or_warning_codes(verify_plan(oracle, rows)) == {"output.no-patch", OFF_MAIN}


# The facts behind all of the above, pinned against the walk rather than
# against this module's reading of it.

def test_the_two_usr_kinds_tile_the_group_exactly():
    """24 user signals + 32 user patches = the 56 slots `INPUT_SOCKETS` has,
    with no gap and no overlap. Three independent sources agree on that
    split -- the PDF's counts, the walk's two descriptor variants, and the
    group's own size -- which is why it is recorded as a fact."""
    assert _facts.USER_SIGNAL_SLOTS == (1, 24)
    assert _facts.USER_PATCH_SLOTS == (25, 56)
    assert _facts.USER_PATCH_SLOTS[0] == _facts.USER_SIGNAL_SLOTS[1] + 1
    assert _facts.USER_PATCH_SLOTS[1] == _facts.INPUT_SOCKETS["USR"] == 56
    assert all(_facts.user_slot_kind(n) is not None
               for n in range(1, _facts.INPUT_SOCKETS["USR"] + 1))


def test_every_user_patch_source_group_is_a_real_input_group():
    """A user patch names the same jacks a channel patch does, so each of its
    source groups has to be a key of INPUT_SOCKETS or the index bound above
    would be checking nothing."""
    assert set(_facts.USER_PATCH_SOURCE_GROUPS) <= set(_facts.INPUT_SOCKETS)
    assert "OSC" not in _facts.USER_PATCH_SOURCE_GROUPS
    assert "USR" not in _facts.USER_PATCH_SOURCE_GROUPS


def test_every_user_signal_source_group_is_a_real_strip_bank():
    assert set(_facts.USER_SIGNAL_SOURCE_BANKS) == set(_facts.USER_SIGNAL_SOURCE_GROUPS)
    assert set(_facts.USER_SIGNAL_SOURCE_BANKS.values()) <= set(_facts.CAPACITY)


def test_the_schemas_group_enum_is_the_union_of_the_two_kinds():
    """The schema cannot see which slot an entry is for, so it takes the
    union and `verify_plan` makes the exact call -- the same split
    `_eq_schema` makes across strip classes."""
    from atoo.plan_schema import USER_SOURCE_SCHEMA
    allowed = set(USER_SOURCE_SCHEMA["properties"]["source"]["properties"]["group"]["enum"])
    assert allowed == (set(_facts.USER_SIGNAL_SOURCE_GROUPS)
                       | set(_facts.USER_PATCH_SOURCE_GROUPS))
    assert _facts.USER_SLOT_UNASSIGNED not in allowed




# ---------------------------------------------------------------------------
# What a shared source actually costs depends on whether it has a preamp.
# ---------------------------------------------------------------------------

SHARED = "patch.socket-shared"


def _both_channels_on(oracle, group, socket=1):
    plan = copy.deepcopy(oracle)
    for ch in plan["channels"][:2]:
        ch["patch"] = {"group": group, "sockets": [socket], "stated": True}
    return plan


def test_a_shared_mic_input_says_they_share_a_preamp(oracle):
    """Two strips off one XLR do share one head amp, and that is the thing
    an engineer needs to know: they cannot have different gain."""
    hit = next(f for f in verify_plan(_both_channels_on(oracle, "A")).findings
               if f.code == SHARED)
    assert "One preamp between them" in hit.message
    assert "phantom" in hit.message


def test_a_shared_source_with_no_preamp_does_not_claim_one(oracle):
    """Written 2026-09-22 and wrong within hours. The message asserted
    "one preamp between them" for ANY shared source, which is untrue of a
    USER slot, PLAY, OSC, USB, CRD and MOD — none of them has a head amp
    to share.

    Telling someone their two playback strips share a gain knob that does
    not exist is the confident wrongness this project keeps trying not to
    emit, and it is worse than saying nothing."""
    hit = next(f for f in verify_plan(_both_channels_on(oracle, "USR")).findings
               if f.code == SHARED)
    assert "preamp between them" not in hit.message
    assert "no head amp" in hit.message


def test_both_messages_still_say_it_is_a_normal_request(oracle):
    """The finding exists to prompt a check, not to scold. Whichever group
    it is, sharing a source is something engineers deliberately do."""
    for group in ("A", "USR"):
        hit = next(f for f in verify_plan(_both_channels_on(oracle, group)).findings
                   if f.code == SHARED)
        assert "normal request" in hit.message
        assert hit.severity == SEVERITY_WARNING


def test_apply_and_console_facts_agree_on_which_groups_have_a_preamp():
    """Two copies of a hardware fact is how they drift. `apply` writes
    phantom to exactly the groups `verify` says have a head amp."""
    from atoo.apply import _VPH_CAPABLE_GROUPS
    from atoo.console_facts import PHANTOM_CAPABLE_GROUPS
    assert set(_VPH_CAPABLE_GROUPS) == set(PHANTOM_CAPABLE_GROUPS)


# --------------------------------------------------------------------------
# two objects patched to the same physical output
# --------------------------------------------------------------------------

COLLISION = "output.socket-collision"


def _mono_wedge(name: str, index: int, socket: int) -> dict:
    """A mono wedge send on one dedicated LCL output."""
    return {"destination": {"type": "dedicated_output", "label": name,
                            "socket": {"group": "LCL", "sockets": [socket], "stated": True}},
            "fader": {"fader_db": -144, "muted": None},
            "dca": [], "mute_group": [],
            "description": f"Wedge send {name}.", "provenance": "",
            "index": index, "mono": True}


def _stereo_iem(name: str, index: int, sockets: list[int]) -> dict:
    """A stereo IEM bus on a dedicated output, shaped exactly as the
    compiler emits one (the own reproduction)."""
    return {"destination": {"type": "dedicated_output", "label": name,
                            "socket": {"group": "LCL", "sockets": sockets, "stated": True}},
            "fader": {"fader_db": -144, "muted": None},
            "dca": [], "mute_group": [],
            "description": f"Stereo IEM send {name}.",
            "provenance": "Busses: 'Add two stereo IEM busses, MON5 and MON6'",
            "index": index, "mono": False}


@pytest.fixture(scope="module")
def collided():
    """**A plan whose LCL outputs are all eight claimed**, with two of them
    claimed twice.

    Four mono wedges on LCL 1-4, a matrix on LCL 7-8, and then the issue's
    own reproduction on top: two stereo IEM busses needing four sockets
    where only LCL 5 and 6 are free, so MON6 lands on the matrix's own
    XLRs.

    Built here rather than read out of `examples/touringband/plan.json`,
    which is where this fixture started. That bundle is a living example
    the maintainer rebuilds between shows, and the rebuild of 2026-09-23 moved
    its monitors off LCL onto AES50-A -- which left LCL half empty, so the
    verifier correctly stopped saying "the group is full" and the test
    below that asks for that sentence failed with nothing wrong in the
    code. What this fixture needs is stated in its first line now, instead
    of being a property of a 48KB file somebody else owns.
    """
    return {
        "meta": {"console_model": "wing-compact"},
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Kick", "color": "Red",
            "source": {"input": "Kick", "type": "Mic", "model": "",
                       "stereo": False, "phantom": False},
            "patch": {"group": "LCL", "sockets": [1], "stated": True},
            "processing": {"hpf_hz": None, "preset": None},
            "fader": {"fader_db": -144, "muted": None},
            "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
            "provenance": {},
        }],
        "busses": {
            **{f"MON{n}": _mono_wedge(f"MON{n}", n, n) for n in (1, 2, 3, 4)},
            "MON5": _stereo_iem("MON5", 5, [5, 6]),
            "MON6": _stereo_iem("MON6", 6, [7, 8]),
        },
        "outputs": {"Matrix 1": {
            "kind": "matrix", "index": 1,
            "sockets": [{"group": "LCL", "sockets": [7, 8], "stated": True}],
            "description": "", "provenance": "",
        }},
        "dcas": {}, "mute_groups": {},
    }


def test_two_objects_on_one_output_socket_is_an_error(collided):
    """A physical setting that cannot work is an error, not a
    preference. One XLR carries one signal; the loser is silently dead."""
    hits = [f for f in verify_plan(collided).findings if f.code == COLLISION]
    assert len(hits) == 1, [f.message for f in hits]
    assert hits[0].severity == SEVERITY_ERROR


def test_the_collision_message_names_both_claimants_and_the_sockets(collided):
    """"LCL 7 is taken" without saying by what sends someone hunting."""
    hit = next(f for f in verify_plan(collided).findings if f.code == COLLISION)
    assert "busses[MON6]" in hit.message
    assert "outputs[Matrix 1]" in hit.message
    assert "LCL outputs 7 and 8" in hit.message


def test_the_collision_message_says_the_group_is_full(collided):
    """The sentence that tells an engineer to move the IEM sends to AES50
    rather than shuffle within a group that has nothing free left."""
    hit = next(f for f in verify_plan(collided).findings if f.code == COLLISION)
    assert "LCL has 8 outputs on a WING Compact and all 8 are claimed" in hit.message
    assert "AES50" in hit.message


def test_the_collision_message_offers_a_free_socket_when_there_is_one(collided):
    """Same check, the other branch: with room left in the group, say
    where -- an engineer fixes this by moving one claimant, and the free
    list is the answer to "to where?"."""
    plan = copy.deepcopy(collided)
    del plan["busses"]["MON5"]          # frees LCL 5 and 6
    hit = next(f for f in verify_plan(plan).findings if f.code == COLLISION)
    assert "LCL 5, LCL 6" in hit.message
    assert "all 8 are claimed" not in hit.message


def test_verify_exits_non_zero_on_a_collision(collided, tmp_path, capsys):
    """The issue's actual complaint: `verify` said APPLICABLE and exited
    0 on a plan that sends two signals out of one XLR."""
    from atoo.cli import main
    path = tmp_path / "collide.json"
    path.write_text(json.dumps(collided))
    code = main(["verify", "--plan", str(path)])
    assert code != 0
    out = capsys.readouterr()
    assert COLLISION in out.out + out.err


def test_an_outputs_entry_colliding_with_another_outputs_entry(oracle, rows):
    """Both claimants on the `outputs` side, with no bus involved -- the
    case a busses-only check would pass."""
    plan = copy.deepcopy(oracle)
    plan["outputs"]["Matrix"]["socket"] = {"group": "USB", "sockets": [47, 48]}
    plan["outputs"]["Matrix"]["sockets"] = [{"group": "USB", "sockets": [47, 48]}]
    hit = next(f for f in verify_plan(plan, rows).findings if f.code == COLLISION)
    assert "outputs[Main]" in hit.message and "outputs[Matrix]" in hit.message
    assert hit.severity == SEVERITY_ERROR


def test_a_shared_physical_input_is_still_not_an_error(oracle):
    """The rule is outputs only. Two channels on one physical INPUT is a
    monitor split or a festival patch -- legitimate, and reported as
    advice (an earlier change says so in as many words)."""
    result = verify_plan(_both_channels_on(oracle, "A"))
    assert COLLISION not in codes(result)
    hit = next(f for f in result.findings if f.code == SHARED)
    assert hit.severity == SEVERITY_WARNING
