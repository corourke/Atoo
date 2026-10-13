"""A smaller hosted model's plan, and what it takes to accept one.

The maintainer, 2026-09-28: *"I'm looking to see if we can get acceptable plans
on smaller hosted models."* His smallband build on claude-haiku-4-5 failed
outright on `plan.outputs.Main.inferred: not a field this format has`.
The plan is not constrained-decoded (its name-keyed maps are outside the
Anthropic structured-output subset), so local validation is the only
guard, and a smaller model drifts further from the format than Sonnet.

The reply itself is frozen in `tests/fixtures/haiku45_smallband.reply.json`
(a copy, never read from `examples/smallband/`, which is the maintainer's living
bundle -- CLAUDE.md). What it needed:

  * `inferred` on an output (fix 1) -- the marker a bus and a channel
    already carry, for the one field an output can have decided: its
    `index`. A marker naming a field the object cannot carry (Haiku wrote
    `destination` on the Main) is dropped with a repair note, not refused.
  * a missing output `index` (fix 2) -- Haiku left it off both Main and
    Matrix 1. `build`'s allocation already filled it; it now says so, at
    INFO `inferred.output-index`. `verify` on a plan that never went
    through `build` still errors, and now names the missing index.
  * aux numbering (fix 3) -- Haiku numbered its aux strip 11, carrying on
    from the ch strips. That stays an ERROR (a Compact has aux 1..8); the
    prompt now says aux strips count from 1 on their own.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from atoo import generate, inferred, plan_schema
from atoo.ai_provider import FakeProvider
from atoo.allocate import allocate_console_indices
from atoo.input_list import load_input_list
from atoo.schema_check import validate as validate_schema
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPLY = FIXTURES / "haiku45_smallband.reply.json"
CSV = FIXTURES / "haiku45_smallband.csv"


def _build(reply: str) -> dict:
    """The build's own post-reply path: parse, normalise, validate,
    allocate, decide -- with the model replaced by the saved reply."""
    return generate.generate_plan("conventions", CSV.read_text(),
                                  provider=FakeProvider(response=reply),
                                  console_model="wing-compact")


# --------------------------------------------------------------------------
# the saved reply, end to end
# --------------------------------------------------------------------------

def test_haikus_saved_reply_builds_and_verifies_down_to_its_one_real_error():
    plan = _build(REPLY.read_text())

    # The stray marker went, and said so -- its basis kept, nothing lost.
    repairs = [n["text"] for n in plan["notes"] if n["source"] == "repair"]
    assert any("outputs[Main]: dropped an 'inferred' marker for 'destination'" in r
               for r in repairs), repairs

    result = verify_plan(plan, load_input_list(str(CSV)))
    # Aux 11 is Haiku's own mistake and stays one: a Compact has aux 1..8.
    assert {f.code for f in result.errors} == {"strip.index-out-of-range"}
    assert "aux 11" in result.errors[0].message
    # Both output indices were filled, and both announce themselves.
    index_notes = {f.where: f.message for f in result.infos
                   if f.code == inferred.CODE_OUTPUT_INDEX}
    assert set(index_notes) == {"outputs[Main]", "outputs[Matrix 1]"}
    assert "Main index set to 1" in index_notes["outputs[Main]"]
    assert "the plan has one Main" in index_notes["outputs[Main]"]
    assert "its name, 'Matrix 1', states slot 1" in index_notes["outputs[Matrix 1]"]
    # ...so the Main reaches a socket through its Matrix, as Sonnet's does.
    assert "output.no-patch" not in {f.code for f in result.findings}


# --------------------------------------------------------------------------
# fix 1 -- `inferred` on outputs (and busses, which already had it)
# --------------------------------------------------------------------------

def test_an_output_and_a_bus_may_carry_an_inferred_marker():
    output = {"kind": "main", "index": 1, "patch": {"group": "LCL", "sockets": [7, 8]},
              "inferred": [{"field": "index", "basis": "one Main", "by": "fallback"}]}
    assert validate_schema(output, plan_schema.OUTPUT_SCHEMA) == []
    bus = {"destination": {"type": "main", "index": 1}, "mono": False,
           "inferred": [{"field": "mono", "basis": "a mix bus", "by": "model"}]}
    assert validate_schema(bus, plan_schema.BUS_SCHEMA) == []


def test_an_output_marker_for_a_field_it_cannot_carry_is_still_a_schema_error():
    """The schema stays strict -- a hand-edited plan.json is told. It is
    the BUILD that drops such a marker, before validating (below)."""
    output = {"kind": "main", "patch": None,
              "inferred": [{"field": "destination", "basis": "x"}]}
    assert validate_schema(output, plan_schema.OUTPUT_SCHEMA)


def test_the_rule_4b_list_is_unchanged_by_the_output_index():
    """An output's index is ALLOCATED, not a rule-4b decision the model
    is asked to make, so the prompt's "four fields" stay four."""
    assert "output" not in plan_schema.INFERABLE_FIELDS
    assert plan_schema.markable_fields("output") == ("index",)


def test_drop_unmarkable_removes_only_the_markers_with_nothing_to_announce():
    plan = {
        "channels": [{"name": "Kick", "inferred": [
            {"field": "stereo", "basis": "mono mic"},
            {"field": "hpf_hz", "basis": "drums"}],
            "bus_sends": [{"bus": "Drums", "inferred": [{"field": "bus", "basis": "u"}]}]}],
        "busses": {"Drums": {"inferred": [{"field": "mono", "basis": "mix bus"}]}},
        "outputs": {"Main": {"inferred": [{"field": "destination", "basis": "to Matrix 1"}]}},
    }
    dropped = inferred.drop_unmarkable(plan)

    assert len(dropped) == 3
    assert plan["channels"][0]["inferred"] == [{"field": "stereo", "basis": "mono mic"}]
    assert "inferred" not in plan["channels"][0]["bus_sends"][0]
    assert "inferred" not in plan["outputs"]["Main"]
    assert plan["busses"]["Drums"]["inferred"] == [{"field": "mono", "basis": "mix bus"}]
    assert any("to Matrix 1" in d for d in dropped), "the basis is kept in the note"


# --------------------------------------------------------------------------
# fix 2 -- a missing output index
# --------------------------------------------------------------------------

def _outputs_plan(outputs: dict) -> dict:
    return {"channels": [], "dcas": {}, "mute_groups": {}, "busses": {},
            "outputs": copy.deepcopy(outputs)}


def test_allocation_fills_a_missing_output_index_and_marks_it():
    plan = _outputs_plan({"Main": {"kind": "main", "patch": None}})
    allocate_console_indices(plan, console_model="wing-compact")

    main = plan["outputs"]["Main"]
    assert main["index"] == 1
    assert main["inferred"] == [{"field": "index", "by": "fallback",
                                 "basis": "the plan has one Main, so it is Main 1"}]


def test_a_stated_output_index_is_left_alone_and_unmarked():
    plan = _outputs_plan({"Main": {"kind": "main", "index": 2, "patch": None}})
    allocate_console_indices(plan, console_model="wing-compact")
    assert plan["outputs"]["Main"]["index"] == 2
    assert "inferred" not in plan["outputs"]["Main"]


def test_several_unnumbered_mains_are_numbered_in_order_and_say_so():
    plan = _outputs_plan({"FOH": {"kind": "main"}, "Broadcast": {"kind": "main"}})
    allocate_console_indices(plan, console_model="wing-compact")
    assert [plan["outputs"][n]["index"] for n in ("FOH", "Broadcast")] == [1, 2]
    basis = plan["outputs"]["Broadcast"]["inferred"][0]["basis"]
    assert "2 Mains" in basis and "order the plan declares them" in basis


def test_verify_names_a_missing_main_index_as_the_cause_of_no_patch():
    """A plan that never went through `build` (hand-edited, or a saved
    reply checked directly) has no allocation to fill the index. The
    finding stays -- which Main the Matrix is fed from cannot be matched --
    but it now names the missing field instead of only "no patch". It is
    a WARNING since 2026-10-09: the Main is still set up, routed to no
    socket, and the desk works."""
    plan = json.loads((FIXTURES / "touringband.plan.json").read_text())
    outs = plan["outputs"]
    outs["Matrix"]["socket"] = outs["Main"]["socket"]
    outs["Matrix"]["sockets"] = outs["Main"]["sockets"]
    outs["Main"]["socket"], outs["Main"]["sockets"] = None, []

    with_index = verify_plan(copy.deepcopy(plan))
    assert "output.no-patch" not in {f.code for f in with_index.findings}

    del outs["Main"]["index"]
    result = verify_plan(plan)
    assert "output.no-patch" not in {f.code for f in result.errors}
    [finding] = [f for f in result.warnings if f.code == "output.no-patch"]
    assert finding.where == "outputs[Main]"
    assert 'states no "index"' in finding.message
    assert "Matrix fed from Main 1" in finding.message
    assert '"index"' in finding.fix


# --------------------------------------------------------------------------
# fix 3 -- the prompt
# --------------------------------------------------------------------------

def test_the_prompt_says_aux_strips_count_from_one_on_their_own():
    gen = " ".join(generate.generator_system("wing-compact").split())
    assert "Aux strips count from 1 on their own" in gen
    assert "never on from the ch numbers" in gen


def test_the_prompt_no_longer_says_a_channel_colour_is_never_written():
    """It is written now (the measured palette); the old prose said
    otherwise, and freeing it paid for the aux line above."""
    gen = generate.generator_system("wing-compact")
    assert "never written to the desk" not in gen
    assert "Written to the strip" in gen
