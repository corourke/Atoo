"""The intent front end's model call (`atoo/intent.py`): the prompt, the one
repair round, and the cap on a runaway reply. A `FakeProvider` answers; no model
is called. Frozen inputs only.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import intent, intent_compile, intent_schema, patch, strict_schema
from atoo.ai_provider import FakeProvider, OllamaProvider
from atoo.schema_check import anthropic_schema
from atoo.schema_check import validate as validate_schema

BASE = json.loads((Path(__file__).parent / "fixtures" / "intent" / "demo_base.plan.json").read_text())
RIG = {"A": "S16"}
HEAD = {"name": "Add F Lead2", "notes": []}
GOOD = {**HEAD, "ops": [{"op": "add_channel", "name": "F Lead2", "kind": "mic", "dca": ["Vocals"]}]}
REQUEST = 'Add another vocal mic "F Lead2"'


class Scripted(FakeProvider):
    """Answers each call from a list, and keeps every call."""

    def __init__(self, *replies):
        super().__init__()
        self.replies = list(replies)

    def complete(self, **kw):
        self.calls.append((kw["system"], kw["user"]))
        self.schemas.append(kw.get("response_schema"))
        self.labels.append(kw.get("label", ""))
        reply = self.replies.pop(0)
        return reply if isinstance(reply, str) else json.dumps(reply)


def run(*replies, request=REQUEST, **kw):
    provider = Scripted(*replies)
    infos: list[str] = []
    cs = intent.compile_change(request, copy.deepcopy(BASE), provider=provider,
                               console_model="wing-compact", aes50_devices=RIG, infos=infos, **kw)
    return cs, infos, provider


def test_one_call_gives_the_change_set_and_the_prompt_carries_the_slice_not_the_desk():
    cs, infos, provider = run(GOOD)
    assert [c["name"] for c in cs["add"]["channels"]] == ["F Lead2"] and len(provider.calls) == 1
    system, user = provider.calls[0]
    assert provider.schemas[0]["properties"]["ops"] and provider.labels == ["intent"]
    assert "preset_values" not in user and len(user) < 30000       # the Demo plan is 68,000
    assert '"index":{"ch":{"Kick":"1"' in user and REQUEST in user
    assert user.index("# Domain knowledge") < user.index("# The desk") < user.index("# The request")
    assert "LCL 1-24" in system and "processing.hpf_hz" in system
    assert cs[patch.ASKED_KEY]["picked_by"] == "Atoo"


def test_the_system_prompt_is_the_consoles_own():
    assert "LCL 1-8" in intent.system_prompt("wing-full")
    assert "AUX 1-8" in intent.system_prompt("wing-full")
    assert "AUX 1-" not in intent.system_prompt("wing-rack")


def test_a_reply_that_is_not_an_intent_is_asked_for_again_once():
    cs, infos, provider = run("I would add a vocal mic.", GOOD)
    assert len(provider.calls) == 2 and provider.labels == ["intent", "intent-repair"]
    second = provider.calls[1][1]
    assert "I would add a vocal mic." in second and "not accepted" in second
    assert any("asked once more" in i for i in infos)


def test_something_the_model_made_up_is_fed_back_with_the_reason_and_a_wider_slice():
    wrong = {**HEAD, "ops": [{"op": "set", "object": "channel", "name": "Lead Vocal",
                              "field": "processing.hpf_hz", "value": 100}]}
    right = {**HEAD, "ops": [{"op": "set", "object": "channel", "name": "Lead Vox",
                              "field": "processing.hpf_hz", "value": 100}]}
    cs, _infos, provider = run(wrong, right, request="HPF 100 on the lead vocal")
    assert [m["name"] for m in cs["modify"]] == ["Lead Vox"]
    assert "no channel of that name is on the desk" in provider.calls[1][1]


def test_an_instruction_the_engineer_typed_is_never_sent_back_to_be_fixed():
    """A 17 on the S16 is the engineer's own socket: asking the model to fix it would be
    carrying the instruction out on another socket."""
    tamb = {**HEAD, "ops": [{"op": "add_channel", "name": "Tamb",
                             "patch": {"group": "A", "first": 17}}]}
    with pytest.raises(intent.IntentRefused) as raised:
        run(tamb, GOOD, request='Add a tambourine mic "Tamb" on A 17')
    assert "A 17 does not exist on the S16" in raised.value.reasons[0]
    assert not raised.value.repairable


def test_the_same_socket_the_model_invented_is_sent_back():
    tamb = {**HEAD, "ops": [{"op": "add_channel", "name": "Tamb",
                             "patch": {"group": "A", "first": 17}}]}
    ok = {**HEAD, "ops": [{"op": "add_channel", "name": "Tamb"}]}
    cs, _infos, provider = run(tamb, ok, request='Add a tambourine mic "Tamb"')
    assert len(provider.calls) == 2 and "A 17 does not exist" in provider.calls[1][1]
    assert cs["add"]["channels"][0]["patch"]["sockets"] == [10]


def test_two_replies_that_are_not_intents_are_an_error_with_what_arrived():
    with pytest.raises(patch.ChangeError) as raised:
        run("nope", '{"name": "x", "ops": [{"op": "explode"}], "notes": []}')
    assert "twice" in str(raised.value) and "explode" in raised.value.partial_text


def test_a_second_refusal_is_the_answer():
    bad = {**HEAD, "ops": [{"op": "drop", "object": "channel", "name": "Banjo"}]}
    with pytest.raises(intent.IntentRefused) as raised:
        run(bad, bad, request="Remove the Banjo")
    assert "no channel of that name" in raised.value.reasons[0]


def test_a_runaway_reply_is_capped_where_the_provider_can_be_capped():
    local = OllamaProvider(model="m")
    assert local.num_predict == -1
    capped = intent._capped(local)
    assert capped.num_predict == intent.REPLY_TOKENS and local.num_predict == -1
    limited = OllamaProvider(model="m", num_predict=500)
    assert intent._capped(limited).num_predict == 500          # the engineer's own limit stands
    fake = FakeProvider()
    assert intent._capped(fake) is fake


def _every_key(intent_: dict, schema: dict) -> dict:
    """The intent as a strict-mode host makes a model write it: every property of an
    op present, `null` for what is unstated."""
    shapes = {b["properties"]["op"]["enum"][0]: b["properties"]
              for b in schema["properties"]["ops"]["items"]["oneOf"]}
    return {**intent_, "ops": [{k: op.get(k) for k in shapes[op["op"]]} for op in intent_["ops"]]}


@pytest.mark.parametrize("model", ("wing-compact", "wing-rack", "wing-full"))
def test_the_reply_schema_goes_both_ways_a_provider_sends_it(model):
    schema = intent_schema.intent_schema(model)
    assert anthropic_schema(schema) is not None
    wire = strict_schema.strict_wire(schema)
    assert wire is not None and len(wire["properties"]["ops"]["items"]["anyOf"]) == 10
    cases = json.loads((Path(__file__).parent / "fixtures" / "intent" / "cases.json").read_text())
    for case in cases["cases"]:
        # what a strict host makes a model write comes back as a valid intent that
        # compiles to the same change set as the one written without the nulls
        back = strict_schema.from_wire(_every_key(case["intent"], schema), schema)
        assert validate_schema(back, schema, path="intent") == []
        kw = dict(text=case["request"], aes50_devices=RIG)
        assert (intent_compile.compile_intent(back, copy.deepcopy(BASE), model, **kw)
                == intent_compile.compile_intent(case["intent"], copy.deepcopy(BASE), model, **kw))


def test_a_reply_that_declines_in_notes_alone_is_asked_once_more_and_then_refused():
    declined = {**HEAD, "ops": [], "notes": ["No bus called Nowhere is on the desk."]}
    with pytest.raises(intent_compile.IntentRefused) as raised:
        run(declined, declined, request="Send the Kick to Nowhere")
    assert "no operation" in " ".join(raised.value.reasons)
    assert "No bus called Nowhere" in " ".join(raised.value.reasons)


def test_the_second_reply_writes_the_op_and_code_refuses_it_naming_the_bus():
    declined = {**HEAD, "ops": [], "notes": ["No bus called Nowhere is on the desk."]}
    send = {**HEAD, "ops": [{"op": "assign", "name": "Kick", "send_add": [{"bus": "Nowhere"}]}]}
    with pytest.raises(intent_compile.IntentRefused) as raised:
        run(declined, send, request="Send the Kick to Nowhere")
    assert "Nowhere" in " ".join(raised.value.reasons) and "no operation" not in " ".join(raised.value.reasons)


def test_every_op_that_names_what_kind_of_thing_it_works_on_does_so_with_object():
    """`object` is the one word for "which kind of thing": a model that learns it on `drop` must not
    meet `kind` for the same idea on `add_output`. (`add_channel`'s `kind` is a source type, a
    different idea.)"""
    ops = {b["properties"]["op"]["enum"][0]: b["properties"]
           for b in intent_schema.intent_schema("wing-compact")["properties"]["ops"]["items"]["oneOf"]}
    for tag in ("drop", "rename", "set", "add_group", "add_output"):
        assert "object" in ops[tag] and "kind" not in ops[tag], tag
    assert ops["add_output"]["object"]["enum"] == ["main", "matrix"]


def test_a_wrong_field_is_named_in_the_message_the_model_is_sent_back_and_one_repair_fixes_it():
    schema = intent_schema.intent_schema("wing-compact")
    wrong = {**HEAD, "ops": [{"op": "add_output", "kind": "main", "name": "Front"}]}
    parsed, problem = intent.parse_intent(json.dumps(wrong), schema)
    assert parsed is None
    assert "ops[0] (add_output): missing required field 'object'" in problem
    assert "kind: not a field this format has" in problem and "object" in problem.split("known:")[1]
    assert "allowed shapes" not in problem
    right = {**HEAD, "ops": [{"op": "add_output", "object": "main", "name": "Front"}]}
    cs, infos, provider = run(wrong, right, request="Add a main output called Front")
    assert "ops[0] (add_output): missing required field 'object'" in provider.calls[1][1]
    assert "Front" in cs["add"]["outputs"]
    assert any("asked once more" in line for line in infos)


def test_an_op_that_is_not_in_the_vocabulary_is_named_with_the_ones_that_are():
    schema = intent_schema.intent_schema("wing-compact")
    _parsed, problem = intent.parse_intent(json.dumps({**HEAD, "ops": [{"op": "mute_everything"}]}), schema)
    assert "ops[0]: 'op' must be one of add_channel" in problem and "'mute_everything'" in problem


def test_every_op_in_the_schema_has_an_entry_in_every_per_op_table():
    """A table keyed by op that misses a new op fails far from where the op was added (a KeyError in
    the repair round of one build). Every such table is listed here and held to the schema."""
    from atoo import intent_desk
    ops = {b["properties"]["op"]["enum"][0]
           for b in intent_schema.intent_schema("wing-compact")["properties"]["ops"]["items"]["oneOf"]}
    assert ops == set(intent_desk.OP_HINT)
    assert ops == set(intent_compile.OP_HANDLERS)
    assert all(callable(getattr(intent_compile._Compile, method)) for method in intent_compile.OP_HANDLERS.values())
    # the schema for a build has the same ops
    build = {b["properties"]["op"]["enum"][0]
             for b in intent_schema.intent_schema("wing-compact", build=True)["properties"]["ops"]["items"]["oneOf"]}
    assert build == ops


def test_the_wider_slice_of_a_repair_round_is_built_for_every_op_the_model_may_have_written():
    """The crash this guards: `order` had no entry in the table `hints_from_intent` reads, so the
    repair prompt of a Build raised KeyError instead of being sent."""
    from atoo import intent_desk
    graph = intent_desk.index_desk(copy.deepcopy(BASE), console_model="wing-compact")
    samples = [{"op": "add_channel", "name": "X"}, {"op": "drop", "object": "bus", "index": 1},
               {"op": "move_channel", "name": "Kick"}, {"op": "rename", "object": "channel", "name": "Kick",
                                                       "new_name": "K"},
               {"op": "set", "object": "channel", "name": "Kick", "field": "fader.fader_db", "value": 0},
               {"op": "assign", "name": "Kick"}, {"op": "add_bus", "name": "B"},
               {"op": "add_group", "object": "dca", "name": "G"}, {"op": "add_output", "object": "main"},
               {"op": "order", "categories": ["drums"]}]
    assert {s["op"] for s in samples} == set(intent_desk.OP_HINT)
    hints = intent_desk.hints_from_intent({"name": "n", "notes": [], "ops": samples}, graph)
    assert {"add", "bus", "output", "move", "drop", "rename", "set"} <= hints["ops"]


def test_the_schema_a_host_decodes_against_has_no_numeric_bounds_so_a_request_past_the_range_can_be_written():
    """"Add a stereo bus as bus 40": a grammar capped at 16 produced bus 4 on every local model, and
    nothing was left for the compile to refuse. The bounds are the compile's to check and name."""
    def bounds(value):
        if isinstance(value, dict):
            return {k for k in value if k in ("minimum", "maximum")} | set().union(*[bounds(v) for v in value.values()])
        if isinstance(value, list):
            return set().union(*[bounds(v) for v in value]) if value else set()
        return set()
    _cs, _infos, provider = run(GOOD)
    assert bounds(provider.schemas[0]) == set()
    assert bounds(intent_schema.intent_schema("wing-compact")) == {"minimum", "maximum"}   # the full one keeps them
    over = {**HEAD, "ops": [{"op": "add_bus", "name": "Subs", "stereo": True, "index": 40}]}
    with pytest.raises(intent_compile.IntentRefused) as raised:
        run(over, request="Add a stereo bus called Subs as bus 40")
    assert "40 is above the console's maximum" in " ".join(raised.value.reasons) and raised.value.final
