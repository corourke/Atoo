"""A captured show previews as 0 changes on the desk it came from (Compact sitting bugs: capture and apply round trip).

Every desk here is built in the test, from the church desk's frozen
snapshot (`tests/fixtures/`) or by hand; nothing under `examples/` is read.
"""

from __future__ import annotations

from atoo import capture, verify_plan
from atoo.snapshot import load_snapshot
from tests.test_capture import CHURCH


def _capture(model: str):
    state = capture.state_from_snap(load_snapshot(CHURCH), model)
    return capture.capture_desk(state, console_model=model, made_from="snap",
                                captured="2026-10-24")


def _sockets(cap) -> set:
    plan = cap.plan
    found = {(e["group"], e["socket"]) for e in plan["direct_outputs"]}
    from atoo import outputs_sheet
    found |= set(outputs_sheet.output_sources(plan))
    return found


def test_a_capture_leaves_out_output_sockets_the_console_does_not_have():
    """Item C: the church desk patches AUX outputs, which a Compact does not
    have. Captured as a Compact, those sockets are left out and said, so the
    captured show verifies (it was BLOCKED: "no AUX outputs at all")."""
    compact = _capture("wing-compact")
    assert not {s for s in _sockets(compact) if s[0] == "AUX"}
    assert any(n["text"].startswith("Left out of the sheets and the plan: AUX ")
               and "the WING Compact does not have as output sockets" in n["text"]
               for n in compact.plan["notes"])
    assert "\nAUX " not in compact.outputs_csv()
    verdict = verify_plan.verify_plan(compact.plan, console_model="wing-compact")
    assert not [f for f in verdict.errors if f.code == "output.socket-out-of-range"]


def test_a_console_that_has_the_sockets_keeps_them():
    full = _capture("wing-full")
    assert {s for s in _sockets(full) if s[0] == "AUX"}
    assert not any("does not have as output sockets" in n["text"] for n in full.plan["notes"])


def _church_state():
    return capture.state_from_snap(load_snapshot(CHURCH), "wing-full")


def _preview_changes(state, plan) -> list:
    from atoo.apply import apply_plan
    from tests.test_capture import _church_desk

    result = apply_plan(plan, _church_desk(state), dry_run=True, full_apply=True,
                        initialize=True, init_model="wing-full")
    return [(w.address, w.prior_value, w.intended_value) for w in result.writes
            if w.status == "dry_run" and w.would_change]


def test_two_busses_the_desk_names_alike_round_trip_with_no_change():
    """Item D: the plan keys two busses named Drums apart ("Drums (Bus 1)",
    "Drums (Bus 5)"), and Apply wrote that key to the desk as the name, so a
    capture's own preview changed both. The desk's name is kept beside the
    key and is what Apply writes and the sheets show."""
    from atoo import sheets

    state = _church_state()
    state.values["/bus/5/name"] = "Drums"
    cap = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                               captured="2026-10-24")
    assert {cap.plan["busses"][k].get("desk_name") for k in ("Drums (Bus 1)", "Drums (Bus 5)")} \
        == {"Drums"}
    assert _preview_changes(state, cap.plan) == []
    rows = {r["bus"]: r["name"] for r in sheets.bus_rows_from_plan(cap.plan)}
    assert rows["Bus 1"] == rows["Bus 5"] == "Drums"
    # A Save of the sheet as it is renames nothing.
    result = sheets.overlay_busses(cap.plan, [{"bus": "Bus 1", "name": "Drums"},
                                              {"bus": "Bus 5", "name": "Drums"}])
    assert result.refusals == [] and not [c for c in result.changes if "renamed" in c]


def test_a_user_signal_is_read_captured_and_previews_as_no_change():
    """Item E: Forge set USR 3 to CH 19 at POST, named "Lead post", and patched
    USB 29 from it. A live capture never asked a user signal (USR 1-24) what
    it takes, so there was no user.csv and Apply could not put it back. The
    capture's read now asks every slot, and the round trip is clean."""
    state = _church_state()
    state.values.update({"/io/in/USR/3/user/grp": "CH", "/io/in/USR/3/user/in": 19,
                         "/io/in/USR/3/user/tap": "POST", "/io/in/USR/3/name": "Lead post",
                         "/io/out/USB/29/grp": "USR", "/io/out/USB/29/in": 3})
    cap = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                               captured="2026-10-24")
    [usr3] = [u for u in cap.plan["user_sources"] if u["slot"] == 3]
    assert usr3 == {"slot": 3, "source": {"group": "CH", "index": 19}, "tap": "POST",
                    "leg": "L+R", "name": "Lead post"}
    assert "USR 3,CH 19" in cap.user_csv()
    assert _preview_changes(state, cap.plan) == []


def test_a_live_capture_asks_every_user_slot_what_it_takes():
    """What a live capture reads beyond the audit's plan: every USR slot's
    source and name, and a user signal's tap and leg."""
    wanted = dict(capture.capture_extra_addresses())
    for slot in (1, 3, 24, 25, 56):
        assert {f"/io/in/USR/{slot}/user/grp", f"/io/in/USR/{slot}/user/in",
                f"/io/in/USR/{slot}/name"} <= set(wanted)
    assert {"/io/in/USR/3/user/tap", "/io/in/USR/3/user/lr"} <= set(wanted)
    assert "/io/in/USR/30/user/tap" not in wanted
