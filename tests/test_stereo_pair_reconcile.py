"""A stereo channel's second input-list row, named on the plan.

A compact reply writes a stereo channel as the row it comes from plus a
`pair` naming the second row (Keys L + Keys R). When the input list states
no socket for either, the expander counts the sockets itself -- and until
2026-09-29 the plan recorded the second row nowhere, so verify, which
found a pair's second row only by its stated socket, reported it as
`reconcile.dropped-input`. The expander now writes it as
`source.pair_input`, and verify counts a row named there as built.

Replayed from Haiku's sixpiece build (`tests/fixtures/`), and from plans
built here.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import generate, instructed_channels, plan_schema, reply_expand
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list
from atoo.schema_check import validate
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).parent / "fixtures"
REPLY = FIXTURES / "haiku45_sixpiece_2026-09-29_fixup.reply.json"
CSV = FIXTURES / "sixpiece_2026-09-29.csv"
INSTRUCTIONS = FIXTURES / "sixpiece_instructions_2026-09-29.md"
CONVENTIONS = FIXTURES / "sixpiece_conventions_2026-09-29.md"


def _build(reply: dict, csv_text: str | None = None) -> dict:
    return generate.generate_plan(
        CONVENTIONS.read_text(), csv_text or CSV.read_text(),
        provider=FakeProvider(response=json.dumps(reply)), console_model="wing-compact",
        instructions=INSTRUCTIONS.read_text(), instructions_name="instructions.md",
        conventions_name="conventions.md")


def _verify(plan: dict, csv_text: str | None = None):
    layers = instructed_channels.layers_from_texts(
        CONVENTIONS.read_text(), "conventions.md", INSTRUCTIONS.read_text(), "instructions.md")
    return verify_plan(plan, parse_input_list(csv_text or CSV.read_text()),
                       console_model="wing-compact", layers=layers)


@pytest.fixture(scope="module")
def replay_plan() -> dict:
    return _build(json.loads(REPLY.read_text()))


def _keys(plan: dict) -> dict:
    return next(c for c in plan["channels"] if c["source"]["input"] == "Keys L")


def test_the_expander_names_the_pairs_second_row(replay_plan):
    keys = _keys(replay_plan)
    assert keys["source"]["stereo"] is True
    assert keys["source"]["pair_input"] == "Keys R"
    assert keys["patch"]["stated"] is False and len(keys["patch"]["sockets"]) == 2
    assert validate(replay_plan, plan_schema.PLAN_SCHEMA) == []


def test_the_sixpiece_replay_verifies_with_keys_r_built(replay_plan):
    result = _verify(replay_plan)
    assert not [f for f in result.findings if f.code == "reconcile.dropped-input"]
    assert not [f for f in result.findings if f.where == "input list[Keys R]"]
    assert result.errors == []


def test_a_plan_without_the_field_loads_and_reconciles_as_before(replay_plan):
    """A plan built before 2026-09-29 carries no `pair_input`: it is still
    valid, and its unstated pair's second row reads as it always did."""
    plan = copy.deepcopy(replay_plan)
    del _keys(plan)["source"]["pair_input"]
    assert validate(plan, plan_schema.PLAN_SCHEMA) == []
    assert [(f.code, f.where) for f in _verify(plan).errors] == [
        ("reconcile.dropped-input", "input list[Keys R]")]


def test_a_pair_naming_a_row_not_on_the_list_is_an_error(replay_plan):
    plan = copy.deepcopy(replay_plan)
    _keys(plan)["source"]["pair_input"] = "Keys Right"
    errors = [(f.code, f.where) for f in _verify(plan).errors]
    assert ("reconcile.invented-source", f"channels[{_keys(plan)['name']}]") in errors
    # ...and the real second row is, again, built by nothing.
    assert ("reconcile.dropped-input", "input list[Keys R]") in errors


def test_a_reply_pairing_a_row_not_on_the_list_is_refused():
    reply = json.loads(REPLY.read_text())
    keys = next(c for c in reply["channels"] if c.get("pair"))
    keys["pair"] = "Keys Right"
    with pytest.raises(reply_expand.ReplyError, match="is not a row of the input list"):
        reply_expand.expand_mechanical(reply, parse_input_list(CSV.read_text()),
                                       console_model="wing-compact")


def _stated_csv() -> str:
    """The sixpiece list with Keys L/R on stated sockets, AES50-A 21-22."""
    return (CSV.read_text()
            .replace(",Keys L,keys,", "AES50-A 21,Keys L,keys,")
            .replace(",Keys R,keys,", "AES50-A 22,Keys R,keys,"))


def test_a_stated_socket_pair_reconciles_with_or_without_the_field(replay_plan):
    plan = copy.deepcopy(replay_plan)
    keys = _keys(plan)
    # Clear A 21-22 of whatever the counted build put there.
    for c in plan["channels"]:
        if c is not keys and c["patch"]["group"] == "A" and \
                set(c["patch"]["sockets"]) & {21, 22}:
            c["patch"]["sockets"] = [45 + i for i in range(len(c["patch"]["sockets"]))]
    keys["patch"] = {"group": "A", "sockets": [21, 22], "stated": True}
    assert not [f for f in _verify(plan, _stated_csv()).findings
                if f.code == "reconcile.dropped-input"]
    del keys["source"]["pair_input"]
    assert validate(plan, plan_schema.PLAN_SCHEMA) == []
    assert not [f for f in _verify(plan, _stated_csv()).findings
                if f.code == "reconcile.dropped-input"]


def test_a_stated_socket_pair_from_the_reply_names_its_second_row():
    plan = _build(json.loads(REPLY.read_text()), _stated_csv())
    keys = _keys(plan)
    assert keys["patch"] == {"group": "A", "sockets": [21, 22], "stated": True}
    assert keys["source"]["pair_input"] == "Keys R"
