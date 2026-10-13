"""Haiku's second sixpiece build of 2026-09-29 (`examples/rebuild-on-
haiku.sh`, commit 4492816), replayed.

Its first reply was refused for two format slips, and its fix-up reply for
a quote the check could not find:

  * `reply.channels[22].patch.stated` -- a compact channel's patch is
    `{group, sockets}`; code reads `stated` from the input list. Dropped,
    either value, with one `[repair]` note.
  * `reply.busses[5].processing.notes` -- free text (the Drums Comp
    compressor settings). Moved to the plan's notes, never lost.
  * `'Instructions: Talkback on Channel 40, source A 40'` for the
    instructions' *"Setup Talkback on Channel 40, source A 40."* -- a
    label and a dropped word; the rest is verbatim, so it is found
    (`instructed_channels.find`).

Only the fix-up reply reached disk (`examples/sixpiece/plan.partial.json`,
already part-expanded: its name-keyed maps are turned back into the arrays
the model wrote in the frozen copy). The first reply is that one with its
two slips put back, as the fix-up round's own thinking in the build log
(`builds/2026-09-29T19-07-03Z.json`) quotes them:
`"patch":{"group":"A","sockets":[40],"stated":true}` on Talkback and
`"processing":{"notes":"Compressor: No Stressor, ..."}` on Drums Comp.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import generate, instructed_channels, reply_expand
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXUP_REPLY = FIXTURES / "haiku45_sixpiece_2026-09-29_fixup.reply.json"
CSV = FIXTURES / "sixpiece_2026-09-29.csv"
INSTRUCTIONS = FIXTURES / "sixpiece_instructions_2026-09-29.md"
CONVENTIONS = FIXTURES / "sixpiece_conventions_2026-09-29.md"
COMPRESSOR = "Compressor: No Stressor, threshold -20dB, attack 20ms, release 50ms per conventions"


def _fixup_reply() -> dict:
    return json.loads(FIXUP_REPLY.read_text())


def _first_reply() -> dict:
    reply = _fixup_reply()
    talkback = next(c for c in reply["channels"] if c["input"] == "Talkback")
    talkback["patch"]["stated"] = True
    comp = next(b for b in reply["busses"] if b["name"] == "Drums Comp")
    comp["processing"] = {"notes": COMPRESSOR}
    return reply


def _build(reply: dict, findings: list | None = None) -> dict:
    return generate.generate_plan(
        CONVENTIONS.read_text(), CSV.read_text(),
        provider=FakeProvider(response=json.dumps(reply)), console_model="wing-compact",
        instructions=INSTRUCTIONS.read_text(), instructions_name="instructions.md",
        conventions_name="conventions.md", findings=findings)


def _verify(plan: dict):
    layers = instructed_channels.layers_from_texts(
        CONVENTIONS.read_text(), "conventions.md", INSTRUCTIONS.read_text(), "instructions.md")
    return verify_plan(plan, parse_input_list(CSV.read_text()), console_model="wing-compact",
                       layers=layers)


# --------------------------------------------------------------------------
# the two repairs
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [True, False])
def test_a_channel_patch_stated_is_dropped_with_one_note(value):
    reply = {"channels": [{"input": "Kick", "patch": {"group": "A", "stated": value}},
                          {"input": "Snare", "patch": {"group": "A", "sockets": [2],
                                                       "stated": value}}]}
    notes = reply_expand.repair_reply(reply)
    assert [c["patch"] for c in reply["channels"]] == [{"group": "A"},
                                                      {"group": "A", "sockets": [2]}]
    [note] = [n for n in notes if "'stated'" in n]
    assert "Kick, Snare" in note and "input list" in note


def test_a_bus_processing_notes_moves_to_the_plans_notes():
    reply = {"busses": [{"name": "Drums Comp", "processing": {"notes": COMPRESSOR,
                                                            "tilt_db": 1}}],
             "notes": []}
    notes = reply_expand.repair_reply(reply)
    assert reply["busses"][0]["processing"] == {"tilt_db": 1}
    assert reply["notes"] == [{"text": f"Drums Comp: {COMPRESSOR}", "source": "model"}]
    assert [n for n in notes if "moved 'notes'" in n and "'Drums Comp'" in n]


def test_a_processing_notes_that_is_not_text_is_left_for_the_schema_to_refuse():
    reply = {"busses": [{"name": "B", "processing": {"notes": {"ratio": 4}}}]}
    assert not [n for n in reply_expand.repair_reply(reply) if "moved 'notes'" in n]
    assert reply["busses"][0]["processing"] == {"notes": {"ratio": 4}}


def test_the_repairs_say_nothing_when_there_is_nothing_to_repair():
    reply = _fixup_reply()
    notes = reply_expand.repair_reply(copy.deepcopy(reply))
    assert not [n for n in notes if "'stated'" in n or "moved 'notes'" in n]


# --------------------------------------------------------------------------
# the replay
# --------------------------------------------------------------------------

def test_the_first_reply_now_builds_and_says_what_was_repaired():
    findings: list = []
    plan = _build(_first_reply(), findings)
    repairs = [n["text"] for n in plan["notes"] if n["source"] == "repair"]
    assert any("dropped 'stated' on Talkback" in t for t in repairs)
    assert any("moved 'notes' on busses 'Drums Comp'" in t for t in repairs)
    assert {"text": f"Drums Comp: {COMPRESSOR}", "source": "model"} in plan["notes"]
    assert "processing" not in plan["busses"]["Drums Comp"] or \
        "notes" not in plan["busses"]["Drums Comp"]["processing"]


@pytest.mark.parametrize("reply", [_first_reply, _fixup_reply], ids=["first", "fixup"])
def test_talkback_is_built_on_ch_40_from_a_40_with_the_quote_cleaned(reply):
    plan = _build(reply())
    talkback = next(c for c in plan["channels"] if c["name"] == "Talkback")
    assert (talkback["bank"], talkback["channel"]) == ("ch", 40)
    assert talkback["patch"] == {"group": "A", "sockets": [40], "stated": True}
    assert talkback["source"]["from"] == "instructions"
    assert talkback["source"]["quote"] == "Talkback on Channel 40, source A 40"


def test_verify_of_the_replay_warns_on_talkback_and_invents_nothing():
    result = _verify(_build(_first_reply()))
    codes = {f.code for f in result.findings}
    assert "reconcile.from-instructions" in codes
    assert "reconcile.invented-source" not in codes
    # Talkback is routed to Main. The one strip that reaches no output is
    # Ambient/EKIT: the reply left it out quoting words that are not in
    # the texts, so code built it -- with no route and no send.
    assert [f.where for f in result.findings if f.code == "routing.channel-reaches-nothing"] \
        == ["channels[Ambient/EKIT]"]
    # The Keys pair's second row, on an unstated socket, is named on the
    # channel (`source.pair_input`), so verify counts it built: no errors.
    assert result.errors == []
    assert "reconcile.dropped-input" not in codes
