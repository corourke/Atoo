"""Two failures of the maintainer's real builds on 2026-09-29, and their fixes.

1. **Unity send levels were lost.** The slice-C reply prompt said "Omit
   level_db for unity", on the belief that apply reads a null level as
   unity. It does not: apply writes no `/send/{b}/lvl` for null, so a send
   keeps the desk's own level, and a fresh desk's is -144 -- switched on
   and silent. The festival build came back with every unity send to a
   mix or FX bus null. Now the reply writes a level on every send group,
   and a level still left out (or a null already on disk) is decided --
   unity -- and announced at INFO (`inferred.send-level`) by build,
   verify and apply alike.

2. **Haiku's smallband reply failed the reply format** on fields whose
   meaning is not in doubt: no `unassigned_inputs`, no `patch` on a Main
   that only feeds a Matrix, `"muted": false` on every send group,
   `"mono": false` on a Matrix. `reply_expand.repair_reply` reads those,
   one `[repair]` note per kind; a value that means something is still
   refused.

Every plan and reply here is frozen under `tests/fixtures/` or built in
the test; nothing reads `examples/` (CLAUDE.md).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import generate, inferred, plan_schema, reply_expand
from atoo.ai_provider import FakeProvider
from atoo.apply import _build_write_targets
from atoo.input_list import parse_input_list
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# The maintainer's festival build, 2026-09-29 (Sonnet 5), as it was written: every
# unity send null, with no marker.
FESTIVAL_NULLS = FIXTURES / "festival_2026-09-29.plan.json"
# The maintainer's smallband build on Haiku 4.5, 2026-09-29: the reply as the
# failed build saved it (`plan.partial.json`), and its input list.
HAIKU_SMALLBAND = FIXTURES / "haiku45_smallband_2026-09-29.reply.json"
HAIKU_SMALLBAND_CSV = FIXTURES / "haiku45_smallband.csv"

TWO = "name,category,type,phantom\nKick,drums,Mic,FALSE\nVox,vocals,Mic,FALSE\n"


def _reply(**send_groups) -> dict:
    """Two channels, a monitor bus, a mix bus and an FX bus; `send_groups`
    replaces a bus's `sends` by name."""
    busses = [
        {"name": "MON1", "mono": True,
         "destination": {"type": "dedicated_output", "label": "MON1",
                         "patch": {"group": "LCL", "sockets": [1]}},
         "sends": [{"from": ["*"], "mode": "pre", "level_db": -144.0}]},
        {"name": "Drums", "mono": False, "destination": {"type": "main", "index": 1},
         "sends": [{"from": ["Kick"], "mode": "post"}]},
        {"name": "Snare Verb", "mono": False, "destination": {"type": "main", "index": 1},
         "sends": [{"from": ["Kick"], "mode": "pre", "level_db": -10.0}]},
        {"name": "VOX Reverb", "mono": False, "destination": {"type": "main", "index": 1},
         "sends": [{"from": ["Vox"], "mode": "post"}]},
    ]
    for bus in busses:
        if bus["name"] in send_groups:
            bus["sends"] = send_groups[bus["name"]]
    return {"channels": [{"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Vox", "patch": {"group": "LCL"}}],
            "busses": busses,
            "outputs": [{"name": "Main", "kind": "main", "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": [], "notes": []}


def _build(reply: dict, csv: str = TWO, findings: list | None = None) -> dict:
    return generate.generate_plan(
        "conventions", csv, provider=FakeProvider(response=json.dumps(reply)),
        console_model="wing-compact", findings=findings)


def _levels(plan: dict) -> dict[tuple[str, str], float | None]:
    return {(c["name"], s["bus"]): s["level_db"]
            for c in plan["channels"] for s in c["bus_sends"]}


def _codes(plan: dict, csv: str | None = None) -> list:
    rows = parse_input_list(csv) if csv else None
    return verify_plan(plan, rows, console_model="wing-compact").findings


# --------------------------------------------------------------------------
# 1. send levels
# --------------------------------------------------------------------------

def test_a_reply_whose_sends_omit_level_db_gets_unity_on_every_send_and_says_so():
    plan = _build(_reply())
    levels = _levels(plan)
    assert all(isinstance(v, (int, float)) for v in levels.values()), levels
    assert levels[("Kick", "Drums")] == 0.0
    assert levels[("Vox", "VOX Reverb")] == 0.0
    # Stated levels come through untouched: a monitor send all the way
    # down, and a send at -10.
    assert levels[("Kick", "MON1")] == -144.0 and levels[("Vox", "MON1")] == -144.0
    assert levels[("Kick", "Snare Verb")] == -10.0

    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    drums = next(s for s in kick["bus_sends"] if s["bus"] == "Drums")
    assert drums["inferred"] == [{"field": "level_db", "by": "fallback",
                                  "basis": drums["inferred"][0]["basis"]}]
    mon = next(s for s in kick["bus_sends"] if s["bus"] == "MON1")
    assert "inferred" not in mon    # a stated level is not announced

    info = [d for d in _codes(plan) if d.code == inferred.CODE_SEND_LEVEL]
    assert {d.where for d in info} == {"busses[Drums]", "busses[VOX Reverb]"}
    assert all(d.severity.name == "INFO" for d in info)
    assert "0 dB" in info[0].message and "-144" in info[0].message


def test_a_send_level_left_out_is_one_repair_note_not_a_refusal():
    """The reply schema requires `level_db` (so a constrained model writes
    it); a reply that still leaves it out is read as not stated, once."""
    plan = _build(_reply())
    repairs = [n["text"] for n in plan["notes"] if n["source"] == "repair"]
    assert [r for r in repairs if "'level_db' left out" in r] == [
        next(r for r in repairs if "'level_db' left out" in r)]
    assert "2 times" in next(r for r in repairs if "'level_db' left out" in r)


def test_the_reply_format_asks_for_a_level_on_every_send_group():
    group = plan_schema.REPLY_SEND_GROUP_SCHEMA
    assert "level_db" in group["required"]
    prompt = " ".join(generate.generator_system("wing-compact").split())
    assert "Omit level_db for unity" not in prompt
    assert "level_db always: 0 is unity" in prompt
    for send in plan_schema.EXAMPLE_REPLY_BUS["sends"]:
        assert "level_db" in send


def test_a_plan_on_disk_with_null_send_levels_is_decided_at_verify_and_apply():
    """The maintainer's festival plan of 2026-09-29, as it was written."""
    plan = json.loads(FESTIVAL_NULLS.read_text())
    nulls = [(c["name"], s["bus"]) for c in plan["channels"] for s in c["bus_sends"]
             if s["level_db"] is None]
    assert nulls, "the frozen plan is the evidence: it must still carry its nulls"
    null_busses = {bus for _name, bus in nulls}

    info = [d for d in _codes(plan) if d.code == inferred.CODE_SEND_LEVEL]
    assert {d.where for d in info} == {f"busses[{b}]" for b in null_busses}
    assert sum(int(d.message.split(" on ")[1].split(" ")[0]) for d in info) == len(nulls)

    # apply writes the level verify said it would, and nothing else moves.
    targets, _warnings = _build_write_targets(plan, set_fader_levels=False)
    levels = {t.description: t.compute_value(None) for t in targets
              if t.address.endswith("/lvl") and "/send/" in t.address}
    for name, bus in nulls:
        hits = [v for d, v in levels.items() if f"({name}): send to {bus} level" in d]
        assert hits == [0.0], (name, bus, hits)
    stated = {(c["name"], s["bus"]): s["level_db"] for c in plan["channels"]
              for s in c["bus_sends"] if s["level_db"] is not None}
    for (name, bus), level in stated.items():
        hits = [v for d, v in levels.items() if f"({name}): send to {bus} level" in d]
        assert hits == [float(level)], (name, bus, hits)
    assert -144 in stated.values() and -10 in stated.values()

    # And the plan itself was not modified by being read.
    assert json.loads(FESTIVAL_NULLS.read_text()) == plan


def test_the_decision_is_idempotent_and_leaves_a_stated_level_alone():
    plan = {"busses": {"FX": {"mono": False, "destination": {"type": "main", "index": 1}}},
            "channels": [{"name": "Vox", "bus_sends": [
                {"bus": "FX", "mode": "post", "level_db": None},
                {"bus": "FX", "mode": "post", "level_db": -144.0}]}]}
    assert inferred.decide_unstated(plan) == 1
    sends = plan["channels"][0]["bus_sends"]
    assert sends[0]["level_db"] == 0.0 and sends[0]["inferred"][0]["field"] == "level_db"
    assert sends[1] == {"bus": "FX", "mode": "post", "level_db": -144.0}
    before = copy.deepcopy(plan)
    assert inferred.decide_unstated(plan) == 0 and plan == before


# --------------------------------------------------------------------------
# 2. Haiku's reply: repaired where the meaning is not in doubt
# --------------------------------------------------------------------------

def test_haikus_smallband_reply_now_expands_and_validates():
    """The 2026-09-29 reply failed with six violations. Now it builds, with
    one repair note per kind. Playback, which the reply dropped with no
    `unassigned_inputs` entry, is built by code (every row is, unless the
    engineer's words say to leave it out -- the maintainer, 2026-09-29), stereo
    on its stated A 21-22 because its notes say so. What verify still
    reports is the model's own mistake: a one-row Keyboard on two
    sockets."""
    reply = json.loads(HAIKU_SMALLBAND.read_text())
    csv = HAIKU_SMALLBAND_CSV.read_text()
    plan = _build(reply, csv)
    repairs = [n["text"] for n in plan["notes"] if n["source"] == "repair"]
    assert len(repairs) == 4, repairs
    assert any("'unassigned_inputs' left out once" in r for r in repairs)
    assert any("outputs[*]: 'patch' left out once" in r for r in repairs)
    assert any("sends[*]: dropped 'muted': false 4 times" in r for r in repairs)
    assert any("outputs[*]: dropped 'mono': false once" in r for r in repairs)
    assert plan["unassigned_inputs"] == []
    assert plan["outputs"]["Main 1"]["patch"] is None
    assert all(isinstance(s["level_db"], (int, float))
               for c in plan["channels"] for s in c["bus_sends"])

    playback = next(c for c in plan["channels"] if c["name"] == "Playback")
    assert playback["patch"] == {"group": "A", "sockets": [21, 22], "stated": True}
    assert playback["source"]["stereo"] is True
    assert "left it out without a word" in playback["provenance"]["input"]

    errors = sorted((d.code, d.where) for d in _codes(plan, csv) if d.severity.name == "ERROR")
    assert errors == [("patch.mono-socket-count", "channels[Keyboard].patch")]


@pytest.mark.parametrize("where, key, value", [
    ("send", "muted", True),
    ("send", "on", False),
    ("output", "mono", True),
])
def test_an_unknown_field_that_means_something_is_still_refused(where, key, value):
    reply = _reply(Drums=[{"from": ["Kick"], "mode": "post", "level_db": 0.0}])
    if where == "send":
        reply["busses"][1]["sends"][0][key] = value
    else:
        reply["outputs"][0][key] = value
    with pytest.raises(generate.GenerationError, match=f"{key}: not a field"):
        _build(reply)


def test_a_missing_field_with_no_safe_default_is_still_refused():
    reply = _reply()
    del reply["busses"][1]["mono"]          # rule 4b: decided, never defaulted
    with pytest.raises(generate.GenerationError, match="mono"):
        _build(reply)
    reply = _reply()
    del reply["busses"][1]["sends"][0]["mode"]
    with pytest.raises(generate.GenerationError, match="mode"):
        _build(reply)


def test_the_repair_says_nothing_when_nothing_was_repaired():
    reply = _reply(Drums=[{"from": ["Kick"], "mode": "post", "level_db": 0.0}],
                   **{"VOX Reverb": [{"from": ["Vox"], "mode": "post", "level_db": 0.0}]})
    assert reply_expand.repair_reply(copy.deepcopy(reply)) == []


# --- sixpiece on Haiku, 2026-09-29: two more slips with one meaning ---

SIXPIECE = Path(__file__).parent / "fixtures" / "haiku45_sixpiece_2026-09-29.reply.json"


def test_a_category_given_no_colour_is_dropped_from_the_map_and_said():
    reply = json.loads(SIXPIECE.read_text())
    notes = reply_expand.repair_reply(reply)
    assert all(e.get("color") for e in reply["category_colors"])
    assert any("'misc' given no colour" in n for n in notes)


def test_a_marker_for_a_field_the_object_cannot_carry_is_dropped_and_said():
    reply = json.loads(SIXPIECE.read_text())
    notes = reply_expand.repair_reply(reply)
    matrix = [o for o in reply["outputs"] if o.get("kind") == "matrix"][0]
    assert all(m.get("field") != "mono" for m in matrix.get("inferred", []))
    assert any("dropped a marker for 'mono'" in n for n in notes)


def test_a_marker_for_a_field_the_object_carries_is_kept():
    reply = {"outputs": [{"name": "Matrix 1", "kind": "matrix",
                          "inferred": [{"field": "index", "basis": "named Matrix 1"}]}]}
    reply_expand.repair_reply(reply)
    assert reply["outputs"][0]["inferred"] == [{"field": "index", "basis": "named Matrix 1"}]


def test_a_dated_model_id_prices_as_its_model():
    from atoo.ai_provider import _undated
    assert _undated("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
    assert _undated("claude-sonnet-5") == "claude-sonnet-5"
