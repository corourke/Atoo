"""The maintainer's desk test of 2026-10-12, reproduced offline.

He watched his WING Compact with the sixpiece show's plan and reported
four things, each an issue and each a test here:

* R002 on all six monitor busses, which are patched to
  AES50-A outputs: Watch read only LCL 1-8.
* R006 on MTX 4, which is the phones' monitor source.
* Kick taken out of its two busses raised nothing.
* The Vocals bus muted raised nothing.

The plan is a frozen copy (`tests/fixtures/sixpiece_2026-10-11.plan.json`,
never `examples/`), and the desk is built from it here, the way the rig
stood on the maintainer's Compact: what apply writes, plus the two things he did
by hand -- the monitor busses patched to AES50-A 1-6, and Main 1 feeding a
Matrix 4 the phones listen to.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES, ConsoleState, Severity, aes50_output_addresses, console_read_plan,
    diff_against_plan, mute_drift_findings, plan_watch_rules, read_console_state,
    route_drift_findings, run_audit, socket_groups_to_read, split_path_rules,
)
from atoo.console import OscReply
from atoo.watch import watch

PLAN_PATH = Path(__file__).parent / "fixtures" / "sixpiece_2026-10-11.plan.json"
PLAN = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
FLOOR = -144.0


def _desk() -> dict[str, object]:
    """The rig on the maintainer's Compact, as an address -> value dict."""
    v: dict[str, object] = {}
    busses = PLAN["busses"]
    for entry in PLAN["channels"]:
        base = f"/{entry['bank']}/{entry['channel']}"
        v[f"{base}/name"] = entry["name"]
        v[f"{base}/mute"] = 1 if entry["fader"].get("muted") else 0
        v[f"{base}/fdr"] = float(entry["fader"]["fader_db"])
        patch = entry.get("patch") or {}
        v[f"{base}/in/conn/grp"] = patch.get("group", "OFF")
        v[f"{base}/in/conn/in"] = (patch.get("sockets") or [0])[0]
        for n in range(1, 17):
            v[f"{base}/send/{n}/on"], v[f"{base}/send/{n}/lvl"] = 0, FLOOR
        for send in entry.get("bus_sends") or []:
            n = busses[send["bus"]]["index"]
            v[f"{base}/send/{n}/on"] = 1
            v[f"{base}/send/{n}/lvl"] = float(send["level_db"])
        routed = {r["index"] for r in entry.get("main_routes") or []}
        for m in range(1, 5):
            v[f"{base}/main/{m}/on"] = 1 if m in routed else 0
    for name, entry in busses.items():
        base = f"/bus/{entry['index']}"
        v[f"{base}/name"], v[f"{base}/mute"] = name, 0
        v[f"{base}/fdr"] = float(entry["fader"]["fader_db"])
        dest = entry["destination"]
        for m in range(1, 5):
            v[f"{base}/main/{m}/on"] = 1 if dest.get("type") == "main" and dest.get("index") == m else 0
    for name, entry in PLAN["dcas"].items():
        base = f"/dca/{entry['index']}"
        v[f"{base}/name"], v[f"{base}/mute"], v[f"{base}/fdr"] = name, 0, 0.0
    for m in range(1, 5):
        v[f"/main/{m}/mute"], v[f"/main/{m}/fdr"] = 0, 0.0
    for x in range(1, 9):
        v[f"/mtx/{x}/mute"], v[f"/mtx/{x}/fdr"] = 0, 0.0
    # Main 1 feeds Matrix 1 (the plan's house feed) and Matrix 4 (the
    # phones, set up on the desk).
    v["/main/1/send/MX1/on"], v["/main/1/send/MX1/lvl"] = 1, 0.0
    v["/main/1/send/MX4/on"], v["/main/1/send/MX4/lvl"] = 1, 0.0
    # Output patch: Matrix 1 on LCL 7/8 (slots 1, 2); the six monitor
    # busses on AES50-A 1-6, each on its L slot; everything else off.
    for n in range(1, 9):
        v[f"/io/out/LCL/{n}/grp"], v[f"/io/out/LCL/{n}/in"] = "OFF", 0
    v["/io/out/LCL/7/grp"], v["/io/out/LCL/7/in"] = "MTX", 1
    v["/io/out/LCL/8/grp"], v["/io/out/LCL/8/in"] = "MTX", 2
    for n in range(1, 49):
        v[f"/io/out/A/{n}/grp"], v[f"/io/out/A/{n}/in"] = "OFF", 0
    for n in range(1, 7):
        v[f"/io/out/A/{n}/grp"], v[f"/io/out/A/{n}/in"] = "BUS", 2 * n - 1
    v["/$stat/A/stat"], v["/$stat/B/stat"], v["/$stat/C/stat"] = "OK", "-", "-"
    v["/cfg/mon/1/src"], v["/cfg/mon/2/src"] = "MTX.4", "OFF"
    return v


def _state(**changes) -> ConsoleState:
    values = _desk()
    values.update(changes)
    return ConsoleState(values, console_model="wing-compact")


def _without_aes50_outputs(values: dict) -> dict:
    return {a: x for a, x in values.items() if not a.startswith("/io/out/A/")}


def _rules():
    # R012 told which splits the plan states, as Watch runs it on a show with a plan.
    return split_path_rules(DEFAULT_RULES, PLAN) + plan_watch_rules(PLAN_PATH)


def _ids(findings, *, at_least=Severity.WARNING):
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    return sorted(f.rule_id for f in findings if order[f.severity] <= order[at_least])


# --------------------------------------------------------------------------
# The clean rig raises nothing above INFO
# --------------------------------------------------------------------------


def test_the_rig_as_the_maintainer_had_it_raises_no_warning():
    assert _ids(run_audit(_state(), _rules())) == []


def test_watch_adds_the_two_drift_rules_from_the_plan():
    assert {r.id for r in plan_watch_rules(PLAN_PATH)} >= {"CV016", "CV017"}


# --------------------------------------------------------------------------
# monitor busses patched to AES50 outputs
# --------------------------------------------------------------------------


def test_busses_on_aes50_outputs_reach_an_output():
    findings = run_audit(_state(), _rules())
    assert "R002" not in {f.rule_id for f in findings}


def test_a_read_that_skipped_aes50_says_the_route_could_not_be_checked():
    """The reading the maintainer's Watch made: LCL 1-8 only, with a stage box on
    AES50-A. Not six R002s -- six INFOs saying where nobody looked."""
    state = ConsoleState(_without_aes50_outputs(_desk()), console_model="wing-compact")
    findings = run_audit(state, _rules())
    assert "R002" not in {f.rule_id for f in findings}
    unchecked = [f for f in findings if f.rule_id == "R007"]
    assert len(unchecked) == 6
    assert all(f.severity is Severity.INFO for f in unchecked)
    assert unchecked[0].message == (
        'BUS 1 "MON1" reaches none of the output sockets read (LCL 1-8), but the outputs of '
        "AES50-A (the desk reports a device on it) were not read, so whether it reaches an "
        "output there could not be checked.")


def test_a_bus_that_really_goes_nowhere_is_still_reported():
    """The real fault R002 exists for survives: AES50-A read, MON1
    patched nowhere."""
    state = _state(**{"/io/out/A/1/grp": "OFF", "/io/out/A/1/in": 0})
    findings = [f for f in run_audit(state, _rules()) if f.rule_id == "R002"]
    assert [f.message.split(" is in use")[0] for f in findings] == ['BUS 1 "MON1"']


def test_a_strip_patched_from_aes50_makes_the_read_follow_the_port():
    """With no status leaf (a desk that did not answer it), a strip taking
    its input from AES50-A is enough for the second pass to read A."""
    values = _desk()
    values.pop("/$stat/A/stat")
    state = ConsoleState(_without_aes50_outputs(values))
    assert ("/io/out/A/1/grp", "s") in aes50_output_addresses(state)


def test_a_capture_without_the_status_keeps_its_verdict():
    """A capture from before an earlier change holds no port status; standing R002
    down on every stage box it took inputs from would hide the fault
    R002 exists for. It keeps the verdict it had."""
    values = _without_aes50_outputs(_desk())
    values.pop("/$stat/A/stat")
    ids = {f.rule_id for f in run_audit(ConsoleState(values))}
    assert "R002" in ids and "R007" not in ids


class _Desk:
    """Answers from a dict, as a WING does on the wire; records what was
    asked."""

    console_model = "wing-compact"

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


def test_a_live_read_reads_the_outputs_of_an_aes50_port_with_a_device():
    """What Watch asked for on the Compact -- the panel, LCL 1-8 -- and
    the second pass that now follows the stage box onto AES50-A."""
    desk = _Desk(_desk())
    _in, out = socket_groups_to_read("wing-compact")
    assert "A" not in out
    state = read_console_state(desk, output_sockets=out)
    assert "/io/out/A/48/in" in desk.asked
    assert not any(a.startswith("/io/out/B/") for a in desk.asked)
    assert state.output_source("A", 3) == ("BUS", 5)
    assert "R002" not in {f.rule_id for f in run_audit(state)}
    assert "R007" not in {f.rule_id for f in run_audit(state)}


def test_a_desk_with_nothing_on_aes50_reads_nothing_more():
    values = {"/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
              "/$stat/A/stat": "-", "/$stat/B/stat": "-", "/$stat/C/stat": "-"}
    desk = _Desk(values)
    read_console_state(desk, channels=1, aux=0, buses=0, mains=0, matrices=0, dcas=0,
                       mute_groups=0, output_sockets={"LCL": 8})
    assert not any(a.startswith("/io/out/A/") for a in desk.asked)


def test_no_output_read_asks_for_no_aes50_or_monitor_leaves():
    plan = console_read_plan()
    assert not any(a.startswith(("/$stat/", "/cfg/mon/")) for a, _ in plan)
    state = ConsoleState({"/$stat/A/stat": "OK"})
    assert aes50_output_addresses(state) == []


def test_the_plans_output_groups_are_read_by_watch_too():
    _in, out = socket_groups_to_read("wing-compact", PLAN)
    assert out["LCL"] == 8


# --------------------------------------------------------------------------
# a Matrix the phones listen to
# --------------------------------------------------------------------------


def test_a_matrix_used_as_the_monitor_source_is_not_unpatched():
    assert "R006" not in {f.rule_id for f in run_audit(_state(), _rules())}


def test_the_same_matrix_with_no_monitor_listening_is_reported():
    findings = [f for f in run_audit(_state(**{"/cfg/mon/1/src": "MAIN.1"}), _rules())
                if f.rule_id == "R006"]
    assert [f.message for f in findings] == [
        "MTX 4 has an active send feeding it but is patched to none of the output sockets "
        "read (AES50-A 1-48, LCL 1-8), and no monitor output listens to it."]


# --------------------------------------------------------------------------
# Kick out of its two busses
# --------------------------------------------------------------------------


def test_kick_out_of_both_busses_is_a_warning_naming_them():
    state = _state(**{"/ch/1/send/7/on": 0, "/ch/1/send/8/on": 0})
    findings = route_drift_findings(state, PLAN)
    assert [(f.rule_id, f.severity) for f in findings] == [("CV016", Severity.WARNING)]
    assert findings[0].message == (
        'CH 1 "Kick": the plan sends it to Drums and Drums Comp; neither send is on. '
        "Its signal reaches nothing the plan routes it to.")


def test_kick_out_of_one_bus_is_not_this_rule():
    state = _state(**{"/ch/1/send/7/on": 0})
    assert route_drift_findings(state, PLAN) == []


def test_a_send_pulled_to_the_floor_counts_as_cut():
    state = _state(**{"/ch/1/send/7/on": 0, "/ch/1/send/8/lvl": FLOOR})
    [finding] = route_drift_findings(state, PLAN)
    assert "Drums is off; Drums Comp is at the floor." in finding.message


def test_a_channel_still_reaching_a_wedge_says_so():
    state = _state(**{"/ch/1/send/7/on": 0, "/ch/1/send/8/on": 0,
                      "/ch/1/send/1/lvl": -10.0})
    [finding] = route_drift_findings(state, PLAN)
    assert finding.message.endswith("It still reaches MON1, which the plan does not route it to.")


def test_a_main_route_switched_off_is_cut_too():
    """Bass goes straight to Main 1 (and its INST Reverb send is planned at
    the floor, so it is not a planned path)."""
    [finding] = route_drift_findings(_state(**{"/ch/11/main/1/on": 0}), PLAN)
    assert finding.message.startswith('CH 11 "Bass": the plan routes it to MAIN 1; '
                                      "that route is off.")


def test_monitor_only_channels_are_not_planned_paths():
    """Crowd sends only to the wedges, at the floor: the plan expects it to
    carry nothing yet, so it can never be "cut"."""
    assert not any("Crowd" in f.message for f in route_drift_findings(_state(), PLAN))


def test_an_unread_route_is_not_judged():
    values = _desk()
    del values["/ch/1/send/7/on"]
    values["/ch/1/send/8/on"] = 0
    assert route_drift_findings(ConsoleState(values), PLAN) == []


# --------------------------------------------------------------------------
# the Vocals bus muted
# --------------------------------------------------------------------------


def test_the_vocals_bus_muted_is_a_warning():
    [finding] = mute_drift_findings(_state(**{"/bus/9/mute": 1}), PLAN)
    assert (finding.rule_id, finding.severity) == ("CV017", Severity.WARNING)
    assert finding.message == 'BUS 9 "Vocals" is muted on the desk; the plan leaves it unmuted.'


def test_main_matrix_dca_and_channel_mutes_are_each_reported():
    state = _state(**{"/main/1/mute": 1, "/mtx/1/mute": 1, "/dca/5/mute": 1,
                      "/ch/17/mute": 1})
    messages = [f.message for f in mute_drift_findings(state, PLAN)]
    assert messages == [
        'CH 17 "DSC Lead Vox" is muted on the desk; the plan leaves it unmuted.',
        'DCA 5 "Vocals" is muted on the desk; the plan leaves it unmuted.',
        'MAIN 1 is muted on the desk; the plan leaves it unmuted.',
        'MTX 1 is muted on the desk; the plan leaves it unmuted.',
    ]


def test_the_talk_mic_muted_is_not_drift():
    """TALKBACK is muted between talks by design, which the show's own
    watch.json asks for; the plan has no way to say so."""
    assert mute_drift_findings(_state(**{"/aux/8/mute": 1}), PLAN) == []


def test_a_matrix_the_plan_does_not_use_is_not_judged():
    assert mute_drift_findings(_state(**{"/mtx/4/mute": 1}), PLAN) == []


def test_audit_with_a_plan_reports_the_mute_once():
    """CV010 compares a bus's stated mute too; since an earlier change it reports
    only a planned mute found off, so the two do not say it twice."""
    ids = [f.rule_id for f in diff_against_plan(_state(**{"/bus/9/mute": 1}), PLAN)]
    assert ids.count("CV017") == 1
    assert "CV010" not in ids


def test_watch_raises_the_mute_and_clears_it_when_unmuted():
    states = iter([_state(), _state(**{"/bus/9/mute": 1}), _state()])
    events = list(watch(lambda: next(states), rules=_rules(), interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    assert [f.rule_id for f in events[1].new_findings] == ["CV017"]
    assert [f.rule_id for f in events[2].cleared_findings] == ["CV017"]


def test_watch_raises_the_kick_and_clears_it_when_sent_again():
    cut = {"/ch/1/send/7/on": 0, "/ch/1/send/8/on": 0}
    states = iter([_state(), _state(**cut), _state()])
    events = list(watch(lambda: next(states), rules=_rules(), interval=0, max_iterations=3,
                        sleep=lambda _s: None))
    # R013 is the INFO that lists the planned splits; it changes its members when a strip
    # stops being split, which is not what this test is about.
    def warnings(findings):
        return [f.rule_id for f in findings if f.rule_id != "R013"]

    assert warnings(events[1].new_findings) == ["CV016"]
    assert warnings(events[2].cleared_findings) == ["CV016"]


# --------------------------------------------------------------------------
# Both Watch paths read what the plan patches
# --------------------------------------------------------------------------


class _WireDesk(_Desk):
    """`_Desk` with the rest of what a live read uses."""

    def __init__(self, values, ip=None, port=2223, timeout=1.0):
        super().__init__(values)

    def identity(self):
        return OscReply(address="/?", typetag="s",
                        args=["WING,198.51.100.1,DESK,wing-compact,SER,3.1"])

    def node_dump(self, node):
        return None  # every leaf falls back to `get`

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_watch_page_reads_the_plans_output_groups(monkeypatch):
    import atoo.console as console_module
    from atoo import webui

    desks = []

    def make(ip, port=2223, timeout=1.0):
        desks.append(_WireDesk({}))
        return desks[-1]

    monkeypatch.setattr(console_module, "WingConsole", make)
    plan = {"busses": {"Wedge": {"index": 1, "destination": {
        "type": "dedicated_output", "patch": {"group": "B", "sockets": [5]}}}}}
    provider, close = webui.console_provider_factory("198.51.100.1", plan=plan)
    provider()
    close()
    assert "/io/out/B/5/grp" in desks[0].asked
    assert "/io/out/LCL/8/grp" in desks[0].asked


def test_atoo_watch_reads_the_sixpiece_plan_and_the_stage_box(tmp_path, monkeypatch, capsys):
    from atoo import cli

    show = tmp_path / "sixpiece"
    show.mkdir()
    (show / "plan.json").write_text(PLAN_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    desk = _WireDesk(_desk())
    monkeypatch.setattr(cli, "_open_console", lambda args, **kw: desk)
    exit_code = cli.main(["watch", "--show", str(show), "--console", "198.51.100.1",
                          "--count", "1", "--interval", "0"])
    out = capsys.readouterr().out
    assert "/io/out/A/6/grp" in desk.asked
    assert "R002" not in out and "R006" not in out
    assert exit_code == 0
