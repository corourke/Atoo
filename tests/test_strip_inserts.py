"""The effects a strip inserts, held by the plan.

A capture records every insert switched on -- on a channel, a bus, a Main or
a Matrix -- as the strip's own `inserts`: the model, the engine it is in and
the engine's parameters. Apply loads them back, CV015 watches them, and the
bus sheet's `fx` cell edits a bus's, a Main's or a Matrix's by model.

The church desk is `tests/fixtures/church-full-2026-10-24.snap`; the small
cases are built in the test.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from atoo import apply, bus_presets, capture, fx_engines, sheets
from atoo.audit import ConsoleState, fx_insert_findings, planned_fx_inserts
from atoo.snapshot import load_snapshot

CHURCH = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"


@pytest.fixture(scope="module")
def church_state() -> ConsoleState:
    return capture.state_from_snap(load_snapshot(CHURCH), "wing-full")


@pytest.fixture()
def church(church_state) -> capture.Capture:
    return capture.capture_desk(church_state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


def _inserts(entry: dict) -> list[tuple]:
    return [(i["point"], i["model"], i.get("engine")) for i in entry.get("inserts") or []]


def _writes(plan: dict, prefix: str) -> dict:
    targets, _warnings = apply._build_write_targets(plan, True)
    return {t.address: t.compute_value(None) for t in targets if t.address.startswith(prefix)}


# -- capture --------------------------------------------------------------------


def test_a_capture_holds_every_strips_inserts_with_the_engines_parameters(church):
    plan = church.plan
    reverb = plan["busses"]["Reverb"]
    assert _inserts(reverb) == [("preins", "BPLATE", 4), ("postins", "VSS3", 1)]
    plate = reverb["inserts"][0]["parameters"]
    assert plate["dcy"] == pytest.approx(1.784963012) and plate["size"] == 66
    assert "mdl" not in plate
    ch4 = next(c for c in plan["channels"] if (c["bank"], c["channel"]) == ("ch", 4))
    assert _inserts(ch4) == [("preins", "BODY", 15), ("postins", "C5-CMB", 8)]
    # A strip with nothing inserted states nothing, and Apply leaves it.
    assert "inserts" not in plan["busses"]["Broadcast Mix"]


def test_apply_loads_the_captured_effects_back(church):
    writes = _writes(church.plan, "/fx/4/")
    assert writes["/fx/4/mdl"] == "BPLATE" and writes["/fx/4/size"] == 66
    inserts = _writes(church.plan, "/bus/11/")
    assert inserts["/bus/11/preins/ins"] == "FX4" and inserts["/bus/11/preins/on"] == 1
    assert _writes(church.plan, "/ch/17/")["/ch/17/preins/ins"] == "FX9"


def test_a_choice_the_desk_gave_is_written_though_the_map_lists_another_models(church):
    """`mode` is typed by the map with one model's choices; TAP-DL's MOVE is
    the desk's own, so it is written and read back."""
    targets, warnings = apply._build_write_targets(church.plan, True)
    assert not any("is not a choice" in w for w in warnings)
    assert {t.address: t.compute_value(None) for t in targets}["/fx/2/mode"] == "MOVE"
    # A bus preset's value is still checked (verify's fx.value-not-offered).
    value, why, _ = fx_engines.coerce_param("hq", "MEDIUM")
    assert value is None and "LOW, HIGH" in why


class _DumpingDesk:
    """Answers `/fx/{n}` node dumps from a reading; `refuse` engines answer nothing."""

    def __init__(self, values, refuse=()):
        self.values, self.refuse, self.dumped = values, set(refuse), []

    def node_dump(self, node):
        self.dumped.append(node)
        if int(node.rsplit("/", 1)[1]) in self.refuse:
            return None
        prefix = node + "/"
        return "".join(f"{a[len(prefix):]}={v}," for a, v in self.values.items()
                       if a.startswith(prefix) and "/" not in a[len(prefix):])


def _live_state(church_state) -> ConsoleState:
    """The church reading as a live read leaves it: each engine's model and
    wet/dry only."""
    values = {a: v for a, v in church_state.values.items()
              if not a.startswith("/fx/") or a.endswith(("/mdl", "/fxmix"))}
    return ConsoleState(values, console_model="wing-full")


def test_a_live_capture_reads_each_inserted_engine_once_more(church_state):
    state = _live_state(church_state)
    desk = _DumpingDesk(church_state.values)
    unread, requests = capture.read_effect_parameters(desk, state)
    assert unread == set() and requests == 16 == len(desk.dumped)
    assert state.values["/fx/4/size"] == 66
    assert state.values["/fx/4/dcy"] == pytest.approx(1.784963012)
    assert state.values["/fx/2/mode"] == "MOVE"


def test_a_live_capture_counts_the_follow_up_in_its_progress_and_summary(church_state):
    class Progress:
        total = done = 0

        def add_total(self, n=1):
            self.total += n

        def start_address(self, _address):
            pass

        def finish_address(self, *, answered):
            self.done += 1

    progress = Progress()
    state = _live_state(church_state)
    unread, requests = capture.read_effect_parameters(_DumpingDesk(church_state.values), state,
                                                      progress)
    assert (progress.total, progress.done) == (16, 16)
    result = capture.capture_desk(state, console_model="wing-full", made_from="desk",
                                  captured="2026-10-24", unread_effects=unread)
    result.effect_reads = (16, requests)
    plan_line = next(line for line in capture.summary_lines(result) if line.startswith("plan.json"))
    assert plan_line.endswith("16 effect(s), their parameters read in 16 more request(s) after "
                              "the desk's read")


def test_an_engine_that_does_not_answer_keeps_its_model_only_and_is_said(church_state):
    state = _live_state(church_state)
    unread, _requests = capture.read_effect_parameters(
        _DumpingDesk(church_state.values, refuse={4}), state)
    assert unread == {4}
    result = capture.capture_desk(state, console_model="wing-full", made_from="desk",
                                  captured="2026-10-24", unread_effects=unread)
    plate, vss3 = result.plan["busses"]["Reverb"]["inserts"]
    assert (plate["model"], plate["engine"], plate["parameters"]) == ("BPLATE", 4, {})
    assert vss3["parameters"]
    assert any(note.startswith("The parameters of FX4 could not be read, so the plan keeps its "
                               "model only") for note in result.notes)
    assert _writes(result.plan, "/fx/4/") == {"/fx/4/mdl": "BPLATE"}


def test_a_desk_with_no_node_dumps_keeps_every_model_only(church_state):
    unread, requests = capture.read_effect_parameters(object(), _live_state(church_state))
    assert len(unread) == 16 and requests == 0


# -- apply ------------------------------------------------------------------------


def _plan(**objects) -> dict:
    vox = {"channel": 1, "bank": "ch", "name": "Vox",
           "source": {"input": "Vox", "type": "Mic", "model": None, "stereo": False,
                      "phantom": False},
           "patch": {"group": "LCL", "sockets": [1], "stated": True},
           "processing": {"hpf_hz": None, "preset": None},
           "fader": {"fader_db": None, "muted": None}, "dca": [], "mute_group": [],
           "bus_sends": [], "main_routes": []}
    plan = {"channels": [vox], "busses": {}, "outputs": {}, "dcas": {}, "mute_groups": {}}
    for key, value in objects.items():
        plan[key] = value
    return plan


def test_a_main_a_matrix_and_a_channel_write_their_own_inserts():
    plan = _plan(outputs={
        "PA": {"kind": "main", "index": 1,
               "inserts": [{"point": "postins", "model": "GEQ", "engine": 9, "parameters": {}}]},
        "Fill": {"kind": "matrix", "index": 2,
                 "inserts": [{"point": "preins", "model": None}]}})
    plan["channels"][0]["inserts"] = [{"point": "preins", "model": "DE-S2", "engine": 16,
                                       "parameters": {}}]
    assert _writes(plan, "/main/1/postins/") == {"/main/1/postins/ins": "FX9", "/main/1/postins/on": 1}
    assert _writes(plan, "/fx/9/") == {"/fx/9/mdl": "GEQ"}
    # Taken off: the insert names nothing, and the engine is left.
    assert _writes(plan, "/mtx/2/preins/") == {"/mtx/2/preins/ins": "NONE"}
    assert _writes(plan, "/ch/1/")["/ch/1/preins/ins"] == "FX16"


def test_a_strips_own_insert_wins_over_its_bus_presets_at_that_point():
    preset = {"point": "preins", "model": "V-REV", "parameters": {}, "saved_engine": 5,
              "saved_on": True, "engine": 5}
    entry = {"index": 7, "preset": "Vox Verb",
             "preset_values": {"preset": "Vox Verb", "leaves": {}, "inserts": [preset]},
             "inserts": [{"point": "preins", "model": "HALL", "engine": 2, "parameters": {}}]}
    assert [(i["model"], i["engine"]) for i in bus_presets.strip_inserts(entry)] == [("HALL", 2)]
    writes = _writes(_plan(busses={"Vox Verb": entry}), "/bus/7/")
    assert writes["/bus/7/preins/ins"] == "FX2"


# -- CV015 ------------------------------------------------------------------------


def test_cv015_watches_a_captured_channels_insert(church, church_state):
    assert fx_insert_findings(church_state, church.plan) == []
    state = ConsoleState(dict(church_state.values, **{"/ch/17/preins/on": 0}),
                         console_model="wing-full")
    (finding,) = fx_insert_findings(state, church.plan)
    assert finding.title == "Effect Insert Contradicts Plan"
    assert "the plan loads GEQ into FX9" in finding.message
    assert "its pre-insert is switched off, so the GEQ is bypassed." in finding.message


def test_cv015_says_an_insert_the_plan_took_off_that_names_an_engine_again():
    plan = _plan(busses={"Delay": {"index": 13, "inserts": [{"point": "preins", "model": None}]}})
    assert planned_fx_inserts(plan) == [("/bus/13", "preins", None, None)]
    quiet = ConsoleState({"/bus/13/preins/ins": "NONE"})
    assert fx_insert_findings(quiet, plan) == []
    (finding,) = fx_insert_findings(ConsoleState({"/bus/13/preins/ins": "FX2"}), plan)
    assert "the plan takes its pre-insert off; it names FX2" in finding.message


# -- the bus sheet's fx cell ------------------------------------------------------


def _edit(church, **cells):
    """The church sheet with `cells` ({"Bus 11": "BPLATE; V-REV"}) changed,
    laid on its plan as a Save in step 04 lays it."""
    before = copy.deepcopy(church.bus_rows)
    rows = copy.deepcopy(church.bus_rows)
    for row in rows:
        if row["bus"] in cells:
            row["fx"] = cells[row["bus"]]
    return sheets.overlay_busses(church.plan, rows, before=before)


def test_an_unchanged_cell_keeps_the_effects_and_their_parameters(church):
    result = _edit(church, **{"Bus 11": "vss3; bplate"})
    assert not result.changes and not result.refusals
    assert result.plan["busses"]["Reverb"] == church.plan["busses"]["Reverb"]


def test_a_model_the_cell_drops_comes_off_its_insert(church):
    result = _edit(church, **{"Bus 11": "BPLATE"})
    assert _inserts(result.plan["busses"]["Reverb"]) == [
        ("preins", "BPLATE", 4), ("postins", None, None)]
    assert "Bus 11: VSS3 comes off its post-insert; FX1 keeps the model, inserted nowhere." \
        in result.notes
    assert _writes(result.plan, "/bus/11/postins/") == {"/bus/11/postins/ins": "NONE"}


def test_an_emptied_cell_takes_every_effect_off(church):
    result = _edit(church, **{"Bus 12": ""})
    assert _inserts(result.plan["busses"]["CHORUS"]) == [("preins", None, None)]


def test_no_engine_left_for_an_added_model_is_refused(church):
    """The church desk uses every engine that can hold a reverb (1-8)."""
    result = _edit(church, **{"Main 1": "V-PLATE"})
    (refusal,) = result.refusals
    assert "every engine that can hold V-PLATE (FX1-8) is already in use" in refusal.text()
    assert "inserts" not in result.plan["outputs"]["Main"]


def test_an_added_model_goes_round_every_engine_the_plan_uses(church):
    # Free FX5 first (CHORUS's), then add a reverb to Main 1: it can go
    # only on 1-8, all taken but the one just released.
    result = _edit(church, **{"Bus 12": "", "Main 1": "V-PLATE"})
    assert not result.refusals
    assert _inserts(result.plan["outputs"]["Main"]) == [("preins", "V-PLATE", 5)]
    assert ("Main 1: V-PLATE goes on its pre-insert, in FX5, a free engine that can hold it; "
            "its parameters are left as the desk has them.") in result.notes
    assert _writes(result.plan, "/main/1/preins/") == {"/main/1/preins/ins": "FX5",
                                                "/main/1/preins/on": 1}


def test_a_replaced_model_takes_the_point_it_frees(church):
    result = _edit(church, **{"Bus 13": "ST-DL"})
    assert not result.refusals
    (insert,) = result.plan["busses"]["Delay Long"]["inserts"]
    assert (insert["point"], insert["model"]) == ("preins", "ST-DL")
    assert insert["engine"] == 2      # TAP-DL's, released by the same edit


@pytest.mark.parametrize("cell, why", [
    ("NOPE", "no FX engine on the desk offers this effect"),
    ("HALL; ROOM; PLATE", "a Bus has 2 insert points (pre and post), so it inserts 2 effects at "
                          "most"),
])
def test_a_cell_that_cannot_work_is_refused_and_changes_nothing(church, cell, why):
    result = _edit(church, **{"Bus 11": cell})
    (refusal,) = result.refusals
    assert (refusal.column, why in refusal.text()) == ("fx", True)
    assert result.plan["busses"]["Reverb"] == church.plan["busses"]["Reverb"]


def test_a_bus_presets_engine_is_given_round_a_strips_own():
    plan = _plan(busses={"Vox Verb": {"index": 7, "preset_values": {
        "preset": "Vox Verb", "leaves": {},
        "inserts": [{"point": "preins", "model": "V-REV", "parameters": {}, "saved_engine": 5,
                     "saved_on": True, "engine": None}]}}})
    plan["channels"][0]["inserts"] = [{"point": "preins", "model": "HALL", "engine": 5,
                                       "parameters": {}}]
    bus_presets.allocate_engines(plan, taken=bus_presets.own_claimed_engines(plan))
    assert plan["busses"]["Vox Verb"]["preset_values"]["inserts"][0]["engine"] != 5
