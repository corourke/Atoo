"""`outputs.csv`: one row per output socket the plan patches, in the desk's own
words (every patched socket, a bus's, Main's and Matrix's too).

A capture writes it from the desk; a build lays it on the plan, a filled row
winning; a Save lays it on whole; and a model states splits and recording
feeds as runs, which code expands into the plan's `direct_outputs`. The desk
is the church's full-size WING, from its frozen snapshot under
`tests/fixtures/`; the split show is built in the test, and no model is called.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from atoo import capture, firstrun, outputs_sheet, plan_freshness
from atoo.ai_provider import FakeProvider
from atoo.cli import main
from atoo.reply_expand import expand_output_runs
from atoo.snapshot import load_snapshot
from atoo.verify_plan import verify_plan

CHURCH = Path(__file__).parent / "fixtures" / "church-full-2026-10-24.snap"
DEMO_PLAN = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME / "plan.json"


@pytest.fixture(scope="module")
def church() -> capture.Capture:
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    return capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                captured="2026-10-24", snapshot="captures/church.snap")


# -- the desk's words ------------------------------------------------------------


@pytest.mark.parametrize("text, pair", [
    ("AES50-A 1", ("A", 1)), ("LCL 8", ("LCL", 8)), ("MOD 12", ("MOD", 12)),
    ("USR 3", ("USR", 3)), ("OSC 1", ("OSC", 1)), ("MON 2", ("MON", 2)),
    ("SEND 19", ("SEND", 19)), ("Bus 9 L", ("BUS", 17)), ("Bus 9 R", ("BUS", 18)),
    ("Main 1 R", ("MAIN", 2)), ("Matrix 6 L", ("MTX", 11)),
])
def test_a_source_reads_and_writes_as_the_desk_lists_it(text, pair):
    assert outputs_sheet.parse_source(text) == (pair, None)
    assert outputs_sheet.source_words(*pair) == text


def test_off_blank_and_a_word_the_desk_does_not_have():
    assert outputs_sheet.parse_source("off") == (outputs_sheet.OFF, None)
    assert outputs_sheet.parse_source("  ") == (None, None)
    source, problem = outputs_sheet.parse_source("Dante 3")
    assert source is None and "not a source the desk's output routing offers" in problem
    assert outputs_sheet.parse_source("Bus 17 L")[1] == "'Bus 17 L': the desk has Bus 1-16"


def test_an_output_is_a_socket_of_an_output_group():
    assert outputs_sheet.parse_output("AES50-B 3") == ("B", 3)
    assert outputs_sheet.parse_output("REC 2") == ("REC", 2)
    assert outputs_sheet.parse_output("OSC 1") is None
    assert outputs_sheet.parse_output("USR 3") is None


# -- capture ------------------------------------------------------------------------


def test_a_capture_writes_one_row_per_patched_socket(church, tmp_path):
    rows = outputs_sheet.read_rows(church.outputs_csv())
    assert len(church.plan["direct_outputs"]) == 123 and len(rows) == 147
    assert church.outputs_csv().splitlines()[0] == "output,source,notes"
    assert {"output": "AUX 3", "source": "SEND 19", "notes": ""} in rows
    assert {"output": "AES50-A 33", "source": "LCL 1", "notes": ""} in rows
    # A bus's, a Main's and a Matrix's sockets too, each side on its own row.
    assert [r["source"] for r in rows if r["output"] in ("LCL 1", "LCL 2", "USB 41", "MOD 36")] \
        == ["Bus 9 L", "Bus 9 R", "Main 1 L", "Matrix 6 L"]
    show = tmp_path / "church"
    capture.write_bundle(church, show, evidence_name="church.snap", evidence=b"{}")
    assert (show / "outputs.csv").read_text() == church.outputs_csv()
    plan = json.loads((show / "plan.json").read_text())
    assert plan["meta"]["outputs_sheet"]["sha256"]
    assert ("outputs.csv  147 output sockets: 123 fed straight from a source, 24 by a bus, "
            "a Main or a Matrix" in capture.summary_lines(church))


def test_the_sheet_laid_back_on_its_own_plan_changes_nothing(church):
    rows = outputs_sheet.read_rows(church.outputs_csv())
    result = outputs_sheet.overlay(church.plan, rows, complete=True, console_model="wing-full")
    assert result.refusals == [] and result.changes == []
    assert result.plan == church.plan


# -- a Save, and a build ----------------------------------------------------------------


def _edited(church, **cells) -> list[dict]:
    rows = outputs_sheet.read_rows(church.outputs_csv())
    for row in rows:
        if row["output"] in cells:
            row["source"] = cells[row["output"]]
    return rows


def test_a_save_carries_each_row_into_the_plan(church):
    rows = _edited(church, **{"USB 5": "LCL 8", "AUX 3": "OFF"})
    rows = [r for r in rows if r["output"] != "AUX 7"]
    rows.append({"output": "USB 29", "source": "USR 3", "notes": "to the recorder"})
    result = outputs_sheet.overlay(church.plan, rows, complete=True, console_model="wing-full")
    assert result.refusals == []
    assert result.changes == ["AUX 3 disconnected (was SEND 19)",
                              "AUX 7 disconnected (was MON 1)",
                              "USB 5 from LCL 8 (was AES50-A 5)",
                              "USB 29 from USR 3"]
    by_socket = {(e["group"], e["socket"]): e["source"] for e in result.plan["direct_outputs"]}
    assert by_socket[("USB", 5)] == {"group": "LCL", "index": 8}
    assert by_socket[("USB", 29)] == {"group": "USR", "index": 3}
    assert ("AUX", 3) not in by_socket and ("AUX", 7) not in by_socket


def test_a_build_takes_only_the_rows_it_is_given(church):
    """A build's sheet wins where it says something, and leaves the rest to the
    conventions: a socket it does not name stays, a blank source stays."""
    rows = [{"output": "USB 5", "source": "LCL 8"}, {"output": "USB 6", "source": ""},
            {"output": "AUX 3", "source": "off"}]
    result = outputs_sheet.overlay(church.plan, rows, complete=False, console_model="wing-full")
    assert result.changes == ["AUX 3 disconnected (was SEND 19)", "USB 5 from LCL 8 (was AES50-A 5)"]
    assert len(result.plan["direct_outputs"]) == 122


def _dedicated(plan, bus):
    return [d["patches"] for d in plan["busses"][bus]["destinations"]
            if d["type"] == "dedicated_output"]


def test_a_row_moves_a_buses_sockets_onto_another_bus(church):
    """LCL 1-2 carry Bus 9 (Presentr) on the church desk. Two rows give them to
    Bus 10 (Speakers): the plan says so on the buses' own patches, and Apply
    writes Bus 10's L and R slots."""
    from atoo.apply import _build_write_targets

    rows = [{"output": "LCL 1", "source": "Bus 10 L"}, {"output": "LCL 2", "source": "Bus 10 R"}]
    result = outputs_sheet.overlay(church.plan, rows, complete=False, console_model="wing-full")
    assert result.refusals == []
    assert result.changes == ["LCL 1 from Bus 10 L (was Bus 9 L)",
                              "LCL 2 from Bus 10 R (was Bus 9 R)"]
    assert _dedicated(result.plan, "Presentr") == []
    assert _dedicated(result.plan, "Speakers") == [[{"group": "LCL", "sockets": [1, 2],
                                                     "stated": True}]]
    assert result.plan["direct_outputs"] == church.plan["direct_outputs"]
    written = {t.address: t.compute_value(None) for t in _build_write_targets(result.plan, True)[0]}
    assert (written["/io/out/LCL/1/in"], written["/io/out/LCL/2/in"]) == (19, 20)
    assert outputs_sheet.output_sources(result.plan)[("LCL", 1)] == ("BUS", 19)


def test_what_a_patch_cannot_say_is_the_sockets_own_source(church):
    """A patch says an object's L, or its L then its R. Main 1's R alone on USB
    42, once USB 41 is switched off, and Bus 3's R alone on a socket of its
    own, are each written with the object's slot, as the row says."""
    from atoo.apply import _build_write_targets

    rows = [{"output": "USB 41", "source": "OFF"}, {"output": "USB 30", "source": "Bus 3 R"}]
    result = outputs_sheet.overlay(church.plan, rows, complete=False, console_model="wing-full")
    assert result.refusals == []
    assert result.plan["outputs"]["Main"]["patches"] == [
        {"group": "CRD", "sockets": [31, 32], "stated": True}]
    by_socket = {(e["group"], e["socket"]): e["source"] for e in result.plan["direct_outputs"]}
    assert by_socket[("USB", 42)] == {"group": "MAIN", "index": 2}
    assert by_socket[("USB", 30)] == {"group": "BUS", "index": 6}
    written = {t.address: t.compute_value(None) for t in _build_write_targets(result.plan, True)[0]}
    assert (written["/io/out/USB/42/grp"], written["/io/out/USB/42/in"]) == ("MAIN", 2)
    assert (written["/io/out/USB/30/grp"], written["/io/out/USB/30/in"]) == ("BUS", 6)
    assert "/io/out/USB/41/grp" not in written
    # And it reads back as the rows said.
    sheet = {r["output"]: r["source"] for r in outputs_sheet.rows_from_plan(result.plan)}
    assert (sheet["USB 42"], sheet["USB 30"]) == ("Main 1 R", "Bus 3 R") and "USB 41" not in sheet


def test_a_capture_records_an_objects_r_alone_as_the_sockets_own_source():
    """A desk with Bus 3's R alone on USB 30: a patch would write it as Bus 3's
    L, so the capture records it with the slot, and says so."""
    state = capture.state_from_snap(load_snapshot(CHURCH), "wing-full")
    state.values.update({"/io/out/USB/30/grp": "BUS", "/io/out/USB/30/in": 6})
    result = capture.capture_desk(state, console_model="wing-full", made_from="snap",
                                  captured="2026-10-24", snapshot="captures/church.snap")
    by_socket = {(e["group"], e["socket"]): e["source"] for e in result.plan["direct_outputs"]}
    assert by_socket[("USB", 30)] == {"group": "BUS", "index": 6}
    assert {"output": "USB 30", "source": "Bus 3 R", "notes": ""} in outputs_sheet.read_rows(
        result.outputs_csv())
    assert any("USB 30 from Bus 3 R" in note and "outputs.csv" in note for note in result.notes)


def test_what_cannot_work_is_refused_naming_the_row(church):
    rows = _edited(church, **{"USB 17": "AES50-A 49", "USB 18": "Dante 3"})
    rows += [{"output": "USB 99", "source": "LCL 1"}, {"output": "USB 1", "source": "LCL 2"},
             {"output": "Stage left", "source": "LCL 1"}, {"output": "LCL 1", "source": "LCL 3"}]
    said = {r.text() for r in outputs_sheet.overlay(church.plan, rows, complete=True,
                                                    console_model="wing-full").refusals}
    assert ("outputs.csv, USB 18, source 'Dante 3': 'Dante 3' is not a source the desk's "
            "output routing offers") in "\n".join(said)
    assert any(t.startswith("outputs.csv, USB 1, output 'USB 1': is listed twice") for t in said)
    assert any(t.startswith("outputs.csv, Stage left, output 'Stage left': is not an output "
                            "socket") for t in said)
    # Two rows for one socket are the collision: LCL 1 carries Bus 9 L already.
    assert any(t.startswith("outputs.csv, LCL 1, output 'LCL 1': is listed twice") for t in said)
    # Nothing is changed while a row is refused, so verify's own refusals come
    # once the cells that are no socket or source are put right.
    rows = _edited(church, **{"USB 17": "AES50-A 49"})
    rows += [{"output": "USB 99", "source": "LCL 1"}, {"output": "LCL 9", "source": "Bus 3 L"}]
    said = [r.text() for r in outputs_sheet.overlay(church.plan, rows, complete=True,
                                                    console_model="wing-full").refusals]
    assert ("outputs.csv, USB 17, source: USB 17 is fed from AES50-A 49, which does not exist "
            "-- AES50-A inputs are 1..48 (direct-output.source-out-of-range)") in said
    assert any(t.startswith("outputs.csv, USB 99, output: USB output 99 does not exist")
               for t in said)
    assert any(t.startswith("outputs.csv, LCL 9, output: LCL output 9 does not exist")
               for t in said)


# -- a model's output runs ------------------------------------------------------------


def _channels(*patches) -> list[dict]:
    return [{"name": f"In {i}", "bank": bank, "channel": n, "patch": {"group": g, "sockets": s}}
            for i, (bank, n, g, s) in enumerate(patches, start=1)]


def test_every_input_in_channel_order_one_socket_each():
    plan = {"channels": _channels(("ch", 2, "A", [3]), ("ch", 1, "LCL", [5, 6]),
                                  ("aux", 1, "USB", [1]), ("ch", 3, "A", [3])),
            "output_runs": [{"to": "AES50-B 1", "from": "inputs",
                             "quote": "Every input to AES50-B in order, for the monitor desk."}]}
    findings: list = []
    assert expand_output_runs(plan, findings) == 4
    assert "output_runs" not in plan
    assert [(e["socket"], e["source"]["group"], e["source"]["index"])
            for e in plan["direct_outputs"]] == [(1, "LCL", 5), (2, "LCL", 6), (3, "A", 3),
                                                 (4, "USB", 1)]
    [said] = findings
    assert said.code == "inferred.output-run" and said.severity.value == "info"
    assert said.message.startswith(
        "AES50-B 1-4 (4 socket(s)) fed every input socket the channels are patched from, in "
        "channel order, as 'Every input to AES50-B in order, for the monitor desk.' asks: "
        "AES50-B 1 from LCL 5, AES50-B 2 from LCL 6, AES50-B 3 from AES50-A 3, AES50-B 4 from "
        "USB 1")


def test_a_run_from_a_source_counts_up_and_one_past_the_end_is_refused_by_verify():
    plan = json.loads(DEMO_PLAN.read_text())
    plan["output_runs"] = [
        {"to": "USB 47", "from": "AES50-A 1", "count": 3, "quote": "A 1-3 to USB 47 on"},
        {"to": "Stage left", "from": "inputs", "quote": "x"},
        {"to": "USB 1", "from": "the drums", "quote": "y"}]
    findings: list = []
    assert expand_output_runs(plan, findings) == 3
    assert [(e["socket"], e["source"]["index"]) for e in plan["direct_outputs"]] == [
        (47, 1), (48, 2), (49, 3)]
    assert [f.code for f in findings] == ["inferred.output-run", "output-runs.not-a-socket",
                                          "output-runs.not-a-source"]
    errors = [f for f in verify_plan(plan, console_model="wing-compact").errors
              if "direct_outputs" in f.where]
    assert [(f.code, f.where) for f in errors] == [("output.socket-out-of-range",
                                                    "direct_outputs[USB 49]")]


# -- end to end: a split show through a stand-in model -------------------------------
#
# Twelve inputs on AES50-A 1-12, a monitor split to AES50-B and a recording
# feed to USB, as the conventions state them; the reply is what a model writes
# for it, scripted, and goes through the build's own expansion and verify.

SPLIT_INPUTS = "patch,name,category,type,phantom\n" + "".join(
    f"AES50-A {n},In {n},band,Mic,FALSE\n" for n in range(1, 13))
SPLIT_CONVENTIONS = """# House conventions

- Main is on LCL 1/2.
- Split every stage input to AES50-B in channel order, for the monitor desk.
- Record every input one to one to USB.
"""
SPLIT_REPLY = {
    "channels": [{"input": f"In {n}", "main_routes": [{"index": 1}]} for n in range(1, 13)],
    "busses": [],
    "outputs": [{"name": "Main", "kind": "main", "index": 1,
                 "patch": {"group": "LCL", "sockets": [1, 2]}}],
    "unassigned_inputs": [],
    "output_runs": [
        {"to": "AES50-B 1", "from": "inputs",
         "quote": "Split every stage input to AES50-B in channel order, for the monitor desk."},
        {"to": "USB 1", "from": "inputs", "quote": "Record every input one to one to USB."}],
    "notes": [],
}


@dataclass
class _Scripted(FakeProvider):
    script: list[str] = field(default_factory=list)
    model: str = "stand-in"

    def complete(self, *, system, user, response_schema=None, label=""):
        self.response = self.script[len(self.calls)]
        return super().complete(system=system, user=user, response_schema=response_schema,
                                label=label)


def _build_split(tmp_path, monkeypatch, sheet=None) -> tuple[int, Path, _Scripted]:
    show = tmp_path / "split"
    show.mkdir()
    (show / "input.csv").write_text(SPLIT_INPUTS)
    conventions = tmp_path / "conventions.md"
    conventions.write_text(SPLIT_CONVENTIONS)
    if sheet is not None:
        (show / "outputs.csv").write_text(sheet)
    provider = _Scripted(script=[json.dumps(SPLIT_REPLY)])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    status = main(["build", "--show", str(show), "--console-model", "wing-compact",
                   "--conventions", str(conventions)])
    return status, show, provider


def test_a_split_show_builds_its_splits_from_the_conventions(tmp_path, monkeypatch):
    status, show, provider = _build_split(tmp_path, monkeypatch)
    assert status == 0
    system, user = provider.calls[0]
    assert "output_runs" in system and "## Splits and recording feeds" in user
    plan = json.loads((show / "plan.json").read_text())
    by_socket = {(e["group"], e["socket"]): (e["source"]["group"], e["source"]["index"])
                 for e in plan["direct_outputs"]}
    assert len(by_socket) == 24
    assert all(by_socket[("B", n)] == ("A", n) == by_socket[("USB", n)] for n in range(1, 13))
    assert plan["meta"]["verify_findings"]["errors"] == []
    said = [f["message"] for f in plan["meta"]["build_findings"]
            if f["code"] == "inferred.output-run"]
    assert len(said) == 2 and "Record every input one to one to USB." in said[1]


def test_the_outputs_sheet_wins_over_the_conventions_in_a_build(tmp_path, monkeypatch):
    status, show, _ = _build_split(tmp_path, monkeypatch,
                                   "output,source,notes\nUSB 12,OFF,\nUSB 13,USR 3,talkback\n")
    assert status == 0
    plan = json.loads((show / "plan.json").read_text())
    sockets = {(e["group"], e["socket"]) for e in plan["direct_outputs"]}
    assert ("USB", 12) not in sockets and ("USB", 13) in sockets
    said = [f["message"] for f in plan["meta"]["build_findings"]
            if f["code"] == "build.outputs-sheet"]
    assert said == ["outputs.csv wins over the conventions: USB 12 disconnected (was AES50-A 12).",
                    "outputs.csv wins over the conventions: USB 13 from USR 3."]
    assert plan["meta"]["outputs_sheet"]["sha256"]
    (show / "outputs.csv").write_text("output,source,notes\n")
    fresh = plan_freshness.assess(plan, conventions=None, instructions=None, input_list=None,
                                  outputs_sheet=show / "outputs.csv")
    assert "plan.outputs-sheet-edited" in {r["code"] for r in fresh["reasons"]}


def test_a_sheet_row_that_cannot_work_stops_the_build_naming_it(tmp_path, monkeypatch, capsys):
    status, show, _ = _build_split(tmp_path, monkeypatch,
                                   "output,source,notes\nLCL 9,AES50-A 1,\n")
    assert status == 1
    assert not (show / "plan.json").exists()
    err = capsys.readouterr().err
    assert "outputs.csv cannot be laid onto this plan, so nothing was written" in err
    assert "outputs.csv, LCL 9, output: LCL output 9 does not exist" in err
    assert "(Build's step 04 shows it)" not in err


def test_a_sheet_row_takes_a_socket_from_the_main_the_conventions_patched(tmp_path, monkeypatch):
    """The conventions put the Main on LCL 1-2; the sheet gives LCL 1 to a split
    and LCL 3-4 to the Main. The sheet wins, and since it names the Main, the
    Main feeds the sockets the sheet gives it and no others:
    LCL 2 comes off it."""
    status, show, _ = _build_split(
        tmp_path, monkeypatch,
        "output,source,notes\nLCL 1,AES50-A 1,\nLCL 3,Main 1 L,\nLCL 4,Main 1 R,\n")
    assert status == 0
    plan = json.loads((show / "plan.json").read_text())
    sheet = {r["output"]: r["source"] for r in outputs_sheet.rows_from_plan(plan)}
    assert (sheet["LCL 1"], sheet["LCL 3"], sheet["LCL 4"]) == (
        "AES50-A 1", "Main 1 L", "Main 1 R")
    assert "LCL 2" not in sheet
    said = [f["message"] for f in plan["meta"]["build_findings"]
            if f["code"] == "build.outputs-sheet"]
    assert said == [
        "outputs.csv wins over the conventions: LCL 1 from AES50-A 1 (was Main 1 L).",
        "outputs.csv wins over the conventions: LCL 2 disconnected (was Main 1 R).",
        "outputs.csv wins over the conventions: LCL 3 from Main 1 L.",
        "outputs.csv wins over the conventions: LCL 4 from Main 1 R."]
    assert plan["meta"]["verify_findings"]["errors"] == []


def test_the_overlay_does_not_touch_the_plan_it_is_given(church):
    before = copy.deepcopy(church.plan)
    outputs_sheet.overlay(church.plan, [{"output": "USB 5", "source": "LCL 8"}], complete=False)
    assert church.plan == before


# -- Forge's split case, end to end ---------------------------------------------------
#
# `evals/split/`, frozen under `tests/fixtures/splits/`: twelve inputs on
# AES50-A, two stereo pairs, a monitor split to AES50-B and a recording split
# to USB. The reply is what a model writes for those conventions.

SPLITS = Path(__file__).parent / "fixtures" / "splits"


def _forge_reply() -> dict:
    names = ["Kick", "Snare", "Hi-Hat", "Tom", "OH L", "Bass DI", "Gtr", "Keys L", "Lead Vox",
             "BV 1"]
    category = {"Kick": "Drums", "Snare": "Drums", "Hi-Hat": "Drums", "Tom": "Drums",
                "OH L": "Drums", "Bass DI": "Band", "Gtr": "Band", "Keys L": "Band",
                "Lead Vox": "Vocals", "BV 1": "Vocals"}
    hpf = {"Drums": 80, "Band": 40, "Vocals": 100}
    channels = []
    for name in names:
        channel = {"input": name, "dca": [category[name]],
                   "processing": {"hpf_hz": hpf[category[name]]},
                   "main_routes": [{"index": 1}]}
        if name in ("OH L", "Keys L"):
            channel["pair"] = name[:-1] + "R"
        channels.append(channel)
    return {
        "channels": channels,
        "dcas": [{"name": "Drums"}, {"name": "Band"}, {"name": "Vocals"}],
        "busses": [{"name": "Wedge 1", "mono": True,
                    "inferred": [{"field": "mono", "basis": "one wedge on one socket"}],
                    "destination": {"type": "dedicated_output",
                                    "patch": {"group": "LCL", "sockets": [3], "stated": True}},
                    "sends": [{"from": ["Lead Vox", "BV 1"], "mode": "pre"}]}],
        "outputs": [{"name": "Main", "kind": "main", "index": 1,
                     "patch": {"group": "LCL", "sockets": [1, 2], "stated": True}}],
        "unassigned_inputs": [],
        "output_runs": [
            {"to": "AES50-B 1", "from": "inputs",
             "quote": "- Monitor split: every input socket goes out, unprocessed, on AES50-B in "
                      "the same order"},
            {"to": "USB 1", "from": "AES50-A 1", "count": 12,
             "quote": "- Recording split: every input socket also goes out on sequential USB "
                      "channels in input order"}],
        "notes": [],
    }


def test_forges_split_case_builds_both_splits_and_nothing_else(tmp_path, monkeypatch, capsys):
    show = tmp_path / "splits"
    show.mkdir()
    (show / "input.csv").write_text((SPLITS / "splits.csv").read_text())
    provider = _Scripted(script=[json.dumps(_forge_reply())])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    assert main(["build", "--show", str(show), "--console-model", "wing-compact",
                 "--conventions", str(SPLITS / "splits.md")]) == 0
    plan = json.loads((show / "plan.json").read_text())
    # The build says them, which the channel count does not.
    assert ("Direct outputs: 24 socket(s) fed straight from a source (AES50-B 1-12, USB 1-12)"
            in capsys.readouterr().out)

    feeds = [((e["group"], e["socket"]), (e["source"]["group"], e["source"]["index"]))
             for e in plan["direct_outputs"]]
    assert sorted(feeds) == sorted([(("B", n), ("A", n)) for n in range(1, 13)]
                                   + [(("USB", n), ("A", n)) for n in range(1, 13)])
    # The stereo pairs are one channel each and two split feeds each.
    stereo = [c for c in plan["channels"] if len(c["patch"]["sockets"]) == 2]
    assert len(plan["channels"]) == 10 and len(stereo) == 2
    assert sorted(plan["dcas"]) == ["Band", "Drums", "Vocals"]
    # Nothing else on AES50-B 1-12 or USB 1-12; verify and the build's own
    # findings (the conventions audit among them) hold no error.
    assert plan["meta"]["verify_findings"]["errors"] == []
    assert not [f for f in plan["meta"]["build_findings"] if f["severity"] == "error"]
    from atoo.apply import _declared_output_patches
    declared = _declared_output_patches(plan)
    assert declared[("LCL", 3)][0] == "BUS" and declared[("LCL", 1)][0] == "MAIN"
    assert all(declared[("B", n)] == ("A", n) == declared[("USB", n)] for n in range(1, 13))


def test_the_plan_summary_lists_the_direct_outputs_in_runs(church):
    from atoo.render import render_plan

    text = render_plan(church.plan, [])
    section = text[text.index("DIRECT OUTPUTS"):].split("\n\n")[0].splitlines()
    assert section[0] == "DIRECT OUTPUTS -- 123 socket(s) fed straight from a source"
    assert "  AUX 7-8        from MON 1-2" in section
    assert "  USB 1-8        from AES50-A 1-8" in section
    assert "  USB 17         from AES50-A 14" in section
    assert outputs_sheet.runs({"direct_outputs": [
        {"group": "LCL", "socket": 3, "source": {"group": "BUS", "index": 17}},
        {"group": "LCL", "socket": 4, "source": {"group": "BUS", "index": 18}},
        {"group": "LCL", "socket": 5, "source": {"group": "BUS", "index": 19}}]}) == [
        ("LCL 3-4", "Bus 9 L-R", 2), ("LCL 5", "Bus 10 L", 1)]
