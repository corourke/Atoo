"""Every input-list row is built as a channel, unless the engineer's own
words say to leave it out (the maintainer, 2026-09-29).

The evidence: Haiku's festival reply of 2026-09-29 declared 14 rows
"deliberately unassigned", and its smallband reply dropped Playback
without a word. Whether a row is on the desk is not the model's to
decide silently. So the reply names a row it leaves out AND quotes the
conventions, the instructions or that row's own input-list notes saying
so (`{"input", "quote"}`); code checks the quote, and builds every row
that is not validly left out -- with an INFO saying which and why, and a
WARNING when the quote is not there. A bare name (every reply and plan
before this) still reads: in a reply it is a row with no quote, so it is
built; in a plan it keeps its old warning.

Frozen: `haiku45_festival_2026-09-29.csv`, `examples/festival/input.csv`
as that build read it (commit 2897232). The replies are built here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import generate, plan_schema
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list
from atoo.schema_check import anthropic_schema, validate
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FESTIVAL_CSV = FIXTURES / "haiku45_festival_2026-09-29.csv"
# What Haiku's festival reply left out, from the plan it wrote
# (`examples/festival/plan.json` at commit 2897232).
HAIKU_LEFT_OUT = ["HiHat", "Tom4", "OH R", "Pads", "PERC 1", "PERC2", "BassMic", "AC GUIT 2",
                  "Keys 2", "Horns 1", "Horns 2", "Strings 1", "Strings 2", "VOX 5"]
NOT_PATCHED = "not patched for this event"


def _festival_reply(unassigned: list) -> dict:
    rows = parse_input_list(FESTIVAL_CSV.read_text())
    return {"channels": [{"input": r.name, "patch": {"group": "A"}}
                         for r in rows if r.name not in HAIKU_LEFT_OUT],
            "busses": [{"name": "MON1", "mono": True,
                        "destination": {"type": "dedicated_output", "label": "MON1",
                                        "patch": {"group": "LCL", "sockets": [1]}},
                        "sends": [{"from": ["*"], "mode": "pre", "level_db": -144.0}]}],
            "outputs": [{"name": "Main", "kind": "main", "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": unassigned, "notes": []}


def _build(reply: dict, csv: str, *, conventions: str = "conventions\n",
           instructions: str | None = None, findings: list | None = None) -> dict:
    return generate.generate_plan(
        conventions, csv, provider=FakeProvider(response=json.dumps(reply)),
        console_model="wing-compact", instructions=instructions,
        instructions_name="instructions.md" if instructions else None, findings=findings)


def _names(plan: dict) -> set[str]:
    return {c["source"]["input"] for c in plan["channels"]}


def test_the_festival_rows_haiku_left_out_by_bare_name_are_built():
    """Haiku's reply as it wrote it: 14 bare names, no quote. Each is
    built, and said so."""
    findings: list = []
    plan = _build(_festival_reply(HAIKU_LEFT_OUT), FESTIVAL_CSV.read_text(), findings=findings)
    assert set(HAIKU_LEFT_OUT) <= _names(plan)
    assert plan["unassigned_inputs"] == []
    built = [f for f in findings if f.code == "reply.row-built"]
    assert len(built) == 14 and all(f.severity.name == "INFO" for f in built)
    assert "left it out without a quote saying so" in built[0].message
    assert any("14 row(s) named with no quote" in n["text"] for n in plan["notes"])
    # The added rows take the group the reply used, after its own rows,
    # and the lowest free strips.
    added = [c for c in plan["channels"] if c["source"]["input"] in HAIKU_LEFT_OUT]
    assert {c["patch"]["group"] for c in added} == {"A"}
    assert sorted(c["channel"] for c in added) == list(range(25, 39))
    # A bus every channel sends to includes them.
    assert all(any(s["bus"] == "MON1" for s in c["bus_sends"]) for c in added)
    result = verify_plan(plan, parse_input_list(FESTIVAL_CSV.read_text()),
                         console_model="wing-compact")
    assert not [f for f in result.errors if f.code.startswith("reconcile.")]


def test_the_festival_rows_are_left_out_when_their_notes_say_so():
    """Every one of the 14 is marked "not patched for this event" in its
    own notes -- so quoting that leaves it out, validly."""
    reply = _festival_reply([{"input": n, "quote": NOT_PATCHED} for n in HAIKU_LEFT_OUT])
    findings: list = []
    plan = _build(reply, FESTIVAL_CSV.read_text(), findings=findings)
    assert not set(HAIKU_LEFT_OUT) & _names(plan)
    assert plan["unassigned_inputs"][0] == {"input": "HiHat", "quote": NOT_PATCHED,
                                            "from": "input list"}
    assert not [f for f in findings if f.code == "reply.row-built"]
    result = verify_plan(plan, parse_input_list(FESTIVAL_CSV.read_text()),
                         console_model="wing-compact")
    hihat = next(f for f in result.findings if f.where == "input list[HiHat]")
    assert hihat.code == "reconcile.deliberately-unassigned" and hihat.severity == "warning"
    assert f"because its notes say '{NOT_PATCHED}'" in hihat.message


def test_a_quote_that_is_not_there_is_a_warning_and_the_row_is_built():
    reply = _festival_reply([{"input": "HiHat", "quote": "the drummer brings no hi-hat"}]
                            + [{"input": n, "quote": NOT_PATCHED} for n in HAIKU_LEFT_OUT[1:]])
    findings: list = []
    plan = _build(reply, FESTIVAL_CSV.read_text(), findings=findings)
    assert "HiHat" in _names(plan)
    [warning] = [f for f in findings if f.code == "reply.unassigned-quote-not-found"]
    assert warning.severity.name == "WARNING"
    assert "'the drummer brings no hi-hat'" in warning.message
    assert "HiHat" not in [e["input"] for e in plan["unassigned_inputs"]]


def test_a_rows_notes_do_not_leave_out_another_row():
    csv = ("name,category,type,phantom,notes\nKick,drums,Mic,FALSE,\n"
           "Spare,misc,Mic,FALSE,not patched for this event\nVox,vocals,Mic,FALSE,\n")
    reply = {"channels": [{"input": "Kick"}], "busses": [], "outputs": [],
             "unassigned_inputs": [{"input": "Spare", "quote": NOT_PATCHED},
                                   {"input": "Vox", "quote": NOT_PATCHED}],
             "notes": []}
    plan = _build(reply, csv)
    assert "Vox" in _names(plan) and "Spare" not in _names(plan)


def test_the_instructions_can_leave_a_row_out():
    csv = "name,category,type,phantom\nKick,drums,Mic,FALSE\nSpare,misc,Mic,FALSE\n"
    reply = {"channels": [{"input": "Kick"}], "busses": [], "outputs": [],
             "unassigned_inputs": [{"input": "Spare", "quote": "Leave the spare mic off."}],
             "notes": []}
    plan = _build(reply, csv, instructions="## Inputs\nLeave the spare mic off.\n")
    assert plan["unassigned_inputs"] == [{"input": "Spare", "quote": "Leave the spare mic off.",
                                          "from": "instructions"}]


def test_a_row_built_by_code_carries_its_own_facts():
    csv = ("patch,name,category,type,model,phantom,notes\n,Kick,drums,Mic,,FALSE,\n"
           "LCL 5,OH,drums,Mic,SM81,TRUE,\n")
    reply = {"channels": [{"input": "Kick", "patch": {"group": "LCL"}}],
             "category_colors": [{"category": "drums", "color": "Red"}],
             "busses": [], "outputs": [], "unassigned_inputs": [], "notes": []}
    plan = _build(reply, csv)
    oh = next(c for c in plan["channels"] if c["name"] == "OH")
    assert oh["channel"] == 2 and oh["color"] == "Red"
    assert oh["patch"] == {"group": "LCL", "sockets": [5], "stated": True}
    assert oh["source"] == {"input": "OH", "type": "Mic", "model": "SM81",
                            "stereo": False, "phantom": True}
    assert oh["dca"] == [] and oh["processing"]["hpf_hz"] is None


def test_no_free_strip_for_a_left_out_row_is_refused():
    names = [f"In {n}" for n in range(1, 42)]
    csv = "name,category,type,phantom\n" + "".join(f"{n},misc,Mic,FALSE\n" for n in names)
    reply = {"channels": [{"input": n, "patch": {"group": "A"}} for n in names[:40]],
             "busses": [], "outputs": [], "unassigned_inputs": [], "notes": []}
    with pytest.raises(generate.GenerationError, match="all 40 channel strips are taken"):
        _build(reply, csv)


# --- verify on plans: old and new shapes --------------------------------

CSV = "name,category,type,phantom,notes\nKick,drums,Mic,FALSE,\nSpare,misc,Mic,FALSE,spare\n"
PLAN = {"channels": [{"channel": 1, "bank": "ch", "name": "Kick",
                      "source": {"input": "Kick", "stereo": False, "phantom": False},
                      "patch": {"group": "LCL", "sockets": [1], "stated": False},
                      "processing": {}, "fader": {}, "dca": [], "mute_group": [],
                      "bus_sends": [], "main_routes": []}],
        "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {},
        "meta": {"console_model": "wing-compact"}}


def _spare_warning(entry) -> str:
    plan = json.loads(json.dumps(PLAN))
    plan["unassigned_inputs"] = [entry]
    assert validate(plan["unassigned_inputs"],
                    plan_schema.PLAN_SCHEMA["properties"]["unassigned_inputs"]) == []
    result = verify_plan(plan, parse_input_list(CSV))
    [f] = [f for f in result.findings if f.where == "input list[Spare]"]
    assert (f.code, f.severity) == ("reconcile.deliberately-unassigned", "warning")
    return f.message


def test_an_old_plans_bare_name_keeps_its_warning():
    assert _spare_warning("Spare") == (
        "is on the input list and the plan declares it deliberately unassigned -- confirm that "
        "is intended before the show")


def test_a_quoted_entry_shows_its_quote():
    message = _spare_warning({"input": "Spare", "quote": "spare", "from": "input list"})
    assert "because its notes say 'spare'" in message


def test_a_quoted_entry_whose_quote_is_nowhere_says_so():
    message = _spare_warning({"input": "Spare", "quote": "not today", "from": "input list"})
    assert "quoting 'not today' -- which is not in" in message


# --- the representation and the prompt ----------------------------------

def test_the_reply_asks_for_input_and_quote_and_can_still_be_sent():
    item = plan_schema.REPLY_SCHEMA["properties"]["unassigned_inputs"]["items"]
    assert item["required"] == ["input", "quote"]
    assert anthropic_schema(plan_schema.REPLY_SCHEMA) is not None


def test_the_prompt_says_it_in_one_line():
    prose = " ".join(plan_schema.schema_section().split())
    assert ('unassigned_inputs [{"input", "quote"}]: a row left out ONLY where words quoted '
            "from the conventions, instructions or its notes say so; code builds the rest") in prose
