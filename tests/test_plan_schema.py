"""One definition of the plan format, three consumers.

The prompt states the rules, Anthropic's `output_config.format` and
Ollama's `format` enforce them during decoding, and everything downstream
reads the result. These pin that they cannot drift apart, and that what is
shipped in the prompt is itself valid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import console_facts as facts
from atoo import schema_check
from atoo import generate
from atoo.plan_compat import normalise_plan
from atoo.ai_provider import FakeProvider
from atoo.plan_schema import (
    BUS_SCHEMA,
    CHANNEL_SCHEMA,
    EXAMPLE_BUS,
    EXAMPLE_CHANNEL,
    EXAMPLE_OUTPUT,
    GENERATION_SCHEMA,
    OUTPUT_SCHEMA,
    TOP_LEVEL_KEYS,
    schema_section,
)

ROOT = Path(__file__).parents[1]


def validate(instance, schema):
    """Assert with the validator Atoo actually ships.

    These tests used to call `jsonschema.validate`, which made an optional
    test-only dependency a hard import: on a machine without it the whole
    module failed at collection and nothing here ran. jsonschema is now
    used in exactly one place -- the cross-check below that proves our
    stdlib validator says the same thing as the real library -- and it
    skips when absent.
    """
    errors = schema_check.validate(instance, schema)
    assert not errors, errors


def rejects(instance, schema):
    return schema_check.validate(instance, schema)
FIXTURES = Path(__file__).parent / "fixtures"
GENERATED = ROOT / "tests" / "fixtures" / "touringband.generated.plan.json"


def _generated():
    """The recorded generation, read the way every reader reads a plan: a
    model run from, so its outputs say `socket` where the
    format now says `patch` (`plan_compat`)."""
    return normalise_plan(json.loads(GENERATED.read_text()))


def test_the_schema_is_itself_a_valid_json_schema():
    assert schema_check.unsupported_keywords(GENERATION_SCHEMA) == set()
    assert GENERATION_SCHEMA["type"] == "object"


def _example_after(section: str, marker: str) -> dict:
    """Parse the first JSON object in `section` after `marker`.

    `json.JSONDecoder.raw_decode` stops at the end of one valid object
    rather than demanding the rest of the string be empty, so this finds
    each of the three worked examples regardless of what prose follows it.
    """
    start = section.index("{", section.index(marker))
    return json.JSONDecoder().raw_decode(section, start)[0]


def test_the_examples_in_the_prompt_are_valid():
    """The previous channel exemplar had `//` comments -- it was not JSON
    at all. We were showing a model an unparseable document as the
    template for its parseable output. The bus/output examples exist
    because a hosted run, decoding unconstrained, invented a
    `{"number": N}` shape for a bus/output socket instead of the real
    group/sockets/stated object -- these pin that the worked examples in
    the prompt are themselves valid and unambiguous."""
    validate(EXAMPLE_CHANNEL, CHANNEL_SCHEMA)
    validate(EXAMPLE_BUS, BUS_SCHEMA)
    validate(EXAMPLE_OUTPUT, OUTPUT_SCHEMA)

    # The plan's own format, as `patch`'s change compiler asks for it.
    section = schema_section(compact=False)
    assert _example_after(section, "one channel:") == EXAMPLE_CHANNEL
    assert _example_after(section, "one bus") == EXAMPLE_BUS
    assert _example_after(section, "one output") == EXAMPLE_OUTPUT

    # The reply format the generator reads by default: the same examples
    # with nothing it did not decide, each valid against the reply schema
    # (docs/developer/plan-output-compaction.md, slice 2).
    from atoo import plan_schema
    section = schema_section()
    for marker, example, schema in (
            ("one channel", plan_schema.EXAMPLE_REPLY_CHANNEL, plan_schema.REPLY_CHANNEL_SCHEMA),
            ("one bus", plan_schema.EXAMPLE_REPLY_BUS, plan_schema.REPLY_BUS_SCHEMA),
            ("one output", plan_schema.EXAMPLE_REPLY_OUTPUT, plan_schema.REPLY_OUTPUT_SCHEMA)):
        assert _example_after(section, marker) == example
        validate(example, schema)
        assert "\n" not in json.dumps(example, indent=None)
        assert json.dumps(example, indent=None) in section   # written unindented


def test_a_real_generated_plan_validates():
    validate(_generated(), GENERATION_SCHEMA)


def test_the_prompt_quotes_the_schema_not_a_copy_of_it():
    """Every bound in the prompt is rendered from the schema, so editing
    one cannot leave the other behind."""
    section = schema_section()
    assert f"1..{facts.CAPACITY['ch']}" in section
    assert f"at most {facts.NAME_MAX_CHARS} characters" in section
    assert f"{facts.HPF_HZ_RANGE[0]:g}..{facts.HPF_HZ_RANGE[1]:g}" in section
    assert "'pre' | 'post'" in section


@pytest.mark.parametrize("mutate,why", [
    (lambda c: c.update(channel=41), "strip beyond the console's 40"),
    (lambda c: c.update(channel="one"), "a string where an integer belongs"),
    (lambda c: c.update(name="a name far longer than sixteen characters"), "over the name limit"),
    (lambda c: c.update(bank="bus"), "a bank that is not an input bank"),
    (lambda c: c["patch"].update(group="AES50-A"), "a group spelled as an input list spells it"),
    (lambda c: c["processing"].update(hpf_hz=5), "a high-pass below the console's range"),
    (lambda c: c["bus_sends"][0].update(mode="GRP"), "a send mode the plan cannot express"),
    (lambda c: c["fader"].update(fader_db=20.0), "a fader above +10dB"),
    (lambda c: c.update(colour="red"), "a field the schema does not name"),
    (lambda c: c.pop("main_routes"), "a required field omitted"),
])
def test_the_schema_rejects_what_it_should(mutate, why):
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    mutate(channel)
    assert rejects(channel, CHANNEL_SCHEMA), why


def test_a_bus_sends_mode_may_be_null():
    """compiler.py deliberately leaves a bus_send's mode unset when the
    conventions never state pre/post/group for that bus ("bus X has
    resolved membership but no send mode ... was stated -- left
    unspecified in the plan") -- there's no safe default for mode the way
    unity is for level. A real conventions file hit this (a bus with
    membership but no stated send mode), and the schema wrongly required
    a string here, producing a confusing generic "expected string, got
    NoneType" on top of verify_plan.py's own clear, specific
    value.send-mode-unknown finding for the exact same gap."""
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["bus_sends"][0]["mode"] = None
    assert not rejects(channel, CHANNEL_SCHEMA)


def test_an_output_patch_may_be_null():
    """"Matrix: fed from Main" with no stated destination is a real thing
    an engineer writes. The honest answer is null plus a note, not an
    invented socket -- verify_plan then refuses to apply it, which is
    where that gap belongs."""
    plan = _generated()
    assert plan["outputs"]["Matrix"]["patch"] is None
    validate(plan, GENERATION_SCHEMA)


def test_unassigned_inputs_is_required_of_a_generator():
    """Stricter than the compiler's own output, on purpose: a generator
    that may omit this can drop an input silently, which is the worst
    failure available to it."""
    assert "unassigned_inputs" in GENERATION_SCHEMA["required"]
    plan = _generated()
    del plan["unassigned_inputs"]
    assert rejects(plan, GENERATION_SCHEMA)


def test_top_level_keys_cover_every_optional_section_too():
    """json_repair uses these to tell a safe end-of-document repair from one
    that would re-nest a section. A reply whose `notes` ended up inside
    `busses` is exactly that case, so the set has to include optional keys
    -- not just what a generator is required to produce."""
    from atoo.plan_schema import PLAN_SCHEMA
    assert TOP_LEVEL_KEYS == frozenset(PLAN_SCHEMA["properties"])
    assert frozenset(GENERATION_SCHEMA["required"]) < TOP_LEVEL_KEYS


def test_meta_is_optional_and_namespaced(tmp_path):
    """`meta` is a plan-valid top-level key -- present or
    absent, either is fine, on both the compiler's schema and a
    generator's stricter one -- since it is build provenance, not part of
    the console spec a compiler must always produce."""
    from atoo.plan_schema import PLAN_SCHEMA
    assert "meta" in PLAN_SCHEMA["properties"]
    assert "meta" not in PLAN_SCHEMA["required"]
    assert "meta" not in GENERATION_SCHEMA["required"]

    plan = _generated()
    assert "meta" not in plan
    validate(plan, GENERATION_SCHEMA)          # absent: still valid

    plan["meta"] = {
        "generated_at": "2026-09-16T00:00:00+00:00",
        # Retired 2026-09-28 (C5); a plan built before carries it and must
        # still validate.
        "strategy": "generate",
        "verify_at_generation": {
            "skipped": False, "ok": True, "error_count": 0,
            "warning_count": 0, "summary": "OK",
        },
    }
    validate(plan, GENERATION_SCHEMA)          # present: still valid


def test_the_schema_is_sent_to_the_provider_by_default():
    provider = FakeProvider(response=GENERATED.read_text())
    generate.generate_plan("c", "i", provider=provider, console_model="wing-compact")
    # The REPLY schema, not the plan's: it is the shape the model is asked
    # to write, and the one a hosted decoder can take.
    from atoo.plan_schema import REPLY_SCHEMA
    assert provider.schemas == [REPLY_SCHEMA]
    assert schema_check.anthropic_schema(REPLY_SCHEMA) is not None


def test_no_constrain_omits_it():
    """A grammar can degrade the content it shapes, and slows local
    generation. The trade-off has to be measurable, not arguable."""
    provider = FakeProvider(response=GENERATED.read_text())
    generate.generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    assert provider.schemas == [None]


def test_claude_sends_it_as_structured_output(monkeypatch):
    import io

    from atoo.ai_provider import ClaudeProvider

    seen = {}

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *e): return False

    def fake(req, timeout=None):
        seen["body"] = json.loads(req.data)
        # The provider streams; a reply is Server-Sent Events, not a body.
        events = [
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "{}"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        ]
        return _R("".join(f"data: {json.dumps(e)}\n\n" for e in events).encode())

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)

    # A schema their decoder can take: projected onto the subset, sent.
    small = {"type": "object", "required": ["channel"],
             "properties": {"channel": {"type": "integer", "minimum": 1},
                            "name": {"type": ["string", "null"]}}}
    ClaudeProvider(api_key="k").complete(system="s", user="u", response_schema=small)
    fmt = seen["body"]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] == schema_check.anthropic_schema(small)
    assert "minimum" not in json.dumps(fmt["schema"])   # a 400 if sent

    # Over the API's limit of 24 optional properties: refused with a 400
    # ("too many optional parameters (103) ... (limit: 24)") on every
    # 2026-09-30 Sonnet build, so not sent -- no wasted round trip.
    from atoo.plan_schema import REPLY_SCHEMA
    for too_big in (CHANNEL_SCHEMA, REPLY_SCHEMA):
        assert schema_check.optional_count(schema_check.anthropic_schema(too_big)) > 24
        ClaudeProvider(api_key="k").complete(system="s", user="u",
                                             response_schema=too_big)
        assert "format" not in seen["body"]["output_config"]

    # The whole plan schema is not expressible there (name-keyed maps).
    # No format at all beats a wrong one -- and the local validator still
    # enforces the full schema either way.
    ClaudeProvider(api_key="k").complete(system="s", user="u",
                                         response_schema=GENERATION_SCHEMA)
    assert "format" not in seen["body"]["output_config"]
    assert seen["body"]["output_config"]["effort"] == "medium"


def test_the_anthropic_subset_drops_only_what_it_must():
    """The projection is not allowed to quietly weaken the shape -- it may
    drop value constraints (which the local validator re-applies) and may
    rewrite oneOf to anyOf, and nothing else."""
    projected = schema_check.anthropic_schema(CHANNEL_SCHEMA)
    assert projected is not None

    for gone in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        assert gone not in json.dumps(projected), gone
    assert "oneOf" not in json.dumps(projected)

    # Structure survives: every property, every enum, every required list.
    assert projected["properties"].keys() == CHANNEL_SCHEMA["properties"].keys()
    assert projected["required"] == CHANNEL_SCHEMA["required"]
    assert (projected["properties"]["bank"]["enum"]
            == CHANNEL_SCHEMA["properties"]["bank"]["enum"])

    # Their one hard requirement: every object closed.
    def closed(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False, node
            for v in node.values():
                closed(v)
        elif isinstance(node, list):
            for v in node:
                closed(v)
    closed(projected)


def test_a_nullable_enum_is_split_into_branches_the_api_accepts():
    """The 2026-09-29 Sonnet rebuilds: every generator call had its schema
    refused -- "Enum value 'E84' does not match declared type
    '['string', 'null']'" -- and was asked again without one, so the reply
    came back unconstrained and two of three shows spent a fix-up round on
    a format slip. An enum under a list of types is split into one branch
    per type, and none is left behind."""
    from atoo.plan_schema import REPLY_SCHEMA
    projected = schema_check.anthropic_schema(REPLY_SCHEMA)

    def walk(node):
        if isinstance(node, dict):
            assert not (isinstance(node.get("type"), list) and "enum" in node), node
            for value in node.values():
                yield from walk(value)
            if "anyOf" in node:
                yield node
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    list(walk(projected))
    kind = projected["properties"]["outputs"]["items"]["properties"]["kind"]
    assert kind == {"anyOf": [{"type": "string", "enum": ["main", "matrix"]},
                              {"type": "null"}]}


def test_a_name_keyed_map_is_reported_as_inexpressible():
    """`busses` is keyed by the engineer's own bus names. Their subset
    allows additionalProperties to be `false` and nothing else, and `false`
    would forbid every bus -- so there is no projection, and saying so is
    the only honest answer."""
    open_map = {
        "type": "object",
        "properties": {"busses": {"type": "object",
                                  "additionalProperties": {"type": "object"}}},
    }
    assert schema_check.anthropic_schema(open_map) is None


def test_ollama_sends_it_as_a_grammar(monkeypatch):
    import io

    from atoo.ai_provider import OllamaProvider

    seen = {}

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *e): return False

    def fake(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _R(json.dumps({"message": {"content": "{}"}, "done": True}).encode())

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake)
    OllamaProvider(model="m").complete(system="s", user="u",
                                       response_schema=GENERATION_SCHEMA)
    assert seen["body"]["format"] == GENERATION_SCHEMA


# ---------------------------------------------------------------------------
# The schema is enforced in code, on every path -- not only where a
# provider happens to support constrained decoding.
# ---------------------------------------------------------------------------

def test_the_stdlib_validator_agrees_with_jsonschema():
    """schema_check.py exists so Atoo has no runtime dependency. It is
    only worth having if it says the same thing as the real library -- so
    this is the one test that needs jsonschema, and it names itself as
    skipped rather than taking the module down when it is missing."""
    jsonschema = pytest.importorskip(
        "jsonschema",
        reason="optional test-only oracle -- pip install -e '.[test]'",
    )

    plan = _generated()
    cases = [plan]
    for mutate in (lambda p: p["channels"][0].update(channel=99),
                   lambda p: p["channels"][0].update(colour="red"),
                   lambda p: p.pop("notes"),
                   lambda p: p["channels"][0]["patch"].update(group="AES50-A")):
        broken = _generated()
        mutate(broken)
        cases.append(broken)

    for case in cases:
        ours = schema_check.validate(case, GENERATION_SCHEMA)
        try:
            jsonschema.validate(case, GENERATION_SCHEMA)
            theirs = False
        except jsonschema.ValidationError:
            theirs = True
        assert bool(ours) == theirs, (ours, theirs)


def test_the_validator_enforces_every_keyword_the_schema_uses():
    """A schema promising something nothing checks reads as a guarantee and
    is not one. If you add a keyword to plan_schema.py, add it to
    schema_check.SUPPORTED_KEYWORDS or this fails."""
    from atoo.plan_schema import PLAN_SCHEMA
    from atoo.schema_check import unsupported_keywords

    assert unsupported_keywords(PLAN_SCHEMA) == set()
    assert unsupported_keywords(GENERATION_SCHEMA) == set()


def test_generation_validates_even_with_constraining_off():
    """The path that most needs checking is the one where the decoder did
    not do it."""
    from atoo.generate import GenerationError, generate_plan

    bad = _generated()
    bad["channels"][0]["channel"] = 99          # beyond the console
    provider = FakeProvider(response=json.dumps(bad))

    with pytest.raises(GenerationError, match="does not match the plan format"):
        generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")


def test_a_schema_invalid_plan_is_preserved_as_partial_text():
    """Two hosted runs in a row hit exactly this path and lost
    the model's actual reply, leaving only validate_schema's own truncated
    error list to diagnose from. cli.py already writes ANY exception's
    `partial_text` to a `.partial` file next to the output (its generic
    `getattr(exc, "partial_text", "")` branch) -- this pins that
    GenerationError now carries one here, so that existing mechanism picks
    it up without cli.py itself changing."""
    from atoo.generate import GenerationError, generate_plan

    bad = _generated()
    bad["channels"][0]["channel"] = 99          # beyond the console
    provider = FakeProvider(response=json.dumps(bad))

    with pytest.raises(GenerationError) as exc_info:
        generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")

    # The preserved text is the parsed (if invalid) plan, not raw model
    # text -- re-parseable, and reflects any repairs already applied.
    preserved = json.loads(exc_info.value.partial_text)
    assert preserved["channels"][0]["channel"] == 99


def test_an_unusable_reply_preserves_the_raw_text_as_partial():
    """The other GenerationError site: a reply that never became JSON at
    all (no braces to even attempt a repair on) has no `plan` dict to
    fall back to, so the raw reply itself is what's preserved."""
    from atoo.generate import GenerationError, generate_plan

    provider = FakeProvider(response="I cannot produce a plan for this show.")

    with pytest.raises(GenerationError) as exc_info:
        generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")

    assert exc_info.value.partial_text == "I cannot produce a plan for this show."


def test_a_dedicated_output_socket_may_say_stated_too():
    """A channel's `patch` has group/sockets/stated; a bus or output
    destination's socket has the same group/sockets shape but, before
    this, no `stated` -- one worked example in the prompt (a channel's
    patch) is what an unconstrained model generalizes from, so it adds
    `stated` to every socket it writes. A real llama3.1 touringband run
    did exactly that on every dedicated-output destination and every
    output socket, and schema validation rejected all of them."""
    from atoo.generate import generate_plan

    plan = _generated()
    plan["busses"]["Monitor 1"]["destination"]["patch"]["stated"] = True
    provider = FakeProvider(response=json.dumps(plan))

    result = generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    assert result["busses"]["Monitor 1"]["destination"]["patch"]["stated"] is True


def test_an_output_destination_may_name_a_recorder_tap_group():
    """OUTPUT_SOCKETS has "REC" (a recorder tap) that INPUT_SOCKETS does
    not -- a bus/output destination's socket used to validate its `group`
    against INPUT_SOCKETS regardless, so a plan correctly naming "REC" for
    a real output was wrongly rejected."""
    from atoo.generate import generate_plan

    plan = _generated()
    plan["busses"]["Monitor 1"]["destination"]["patch"]["group"] = "REC"
    provider = FakeProvider(response=json.dumps(plan))

    result = generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    assert result["busses"]["Monitor 1"]["destination"]["patch"]["group"] == "REC"


def test_an_output_destination_may_not_name_an_input_only_group():
    """The flip side: "PLAY"/"OSC"/"USR" exist in INPUT_SOCKETS but not
    OUTPUT_SOCKETS -- naming one of them for an output destination should
    still be rejected, not silently accepted because it happens to be a
    real group name somewhere on the console."""
    from atoo.generate import GenerationError, generate_plan

    plan = _generated()
    plan["busses"]["Monitor 1"]["destination"]["patch"]["group"] = "PLAY"
    provider = FakeProvider(response=json.dumps(plan))

    with pytest.raises(GenerationError, match="does not match the plan format"):
        generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")


def test_a_channel_patch_still_only_accepts_input_groups():
    """The other direction of the same distinction: a channel's `patch` is
    an INPUT socket and must keep rejecting an output-only group like
    "REC", even though the output-side schema now accepts it."""
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["patch"]["group"] = "REC"
    assert rejects(channel, CHANNEL_SCHEMA)


def test_a_string_notes_field_is_coerced_to_a_list():
    """An unconstrained local model wrote `"notes": ""` for "nothing to
    add" rather than `[]` on a real touringband run -- the meaning
    is unambiguous, so this is repaired rather than rejected, and the
    repair is recorded in the plan's own notes rather than done silently."""
    from atoo.generate import generate_plan

    plan = _generated()
    plan["notes"] = ""
    provider = FakeProvider(response=json.dumps(plan))

    result = generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    assert isinstance(result["notes"], list)
    # The repair message itself is tagged "repair": it
    # describes what generate.py did to the model's reply, not something
    # the model said.
    assert any(n["source"] == "repair" and "was a string, not an array" in n["text"]
               for n in result["notes"])


def test_a_non_empty_string_notes_field_is_wrapped_not_dropped():
    from atoo.generate import generate_plan

    plan = _generated()
    plan["notes"] = "one thing worth flagging"
    provider = FakeProvider(response=json.dumps(plan))

    result = generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    # Content the model wrote is tagged "model", even though it
    # only reached the right shape via _coerce_string_array_fields's
    # array-wrapping followed by generate_plan()'s own object-tagging --
    # the repair message describing THAT fixup is a separate, "repair"
    # tagged entry (checked above).
    assert {"text": "one thing worth flagging", "source": "model"} in result["notes"]


def test_generate_and_critique_label_their_calls_by_role():
    """Two calls against the same model, indistinguishable in progress or
    usage output without this -- a real generate-then-critique run does
    exactly that. Checked at the provider boundary: this is
    what the label a human would actually see is built from."""
    provider = FakeProvider(response=GENERATED.read_text())
    generate.generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    assert provider.labels == ["generator"]

    provider = FakeProvider(response=json.dumps({"findings": []}))
    generate.critique_plan("c", "i", _generated(), provider=provider)
    assert provider.labels == ["critic"]


# ---------------------------------------------------------------------------
# `notes` provenance -- every entry is {"text", "source"}, and
# the four sources ("model", "extraction", "repair", "allocation") each get
# tagged at the point they're actually written, not guessed at afterward.
# ---------------------------------------------------------------------------

def test_generated_notes_validate_against_the_note_schema():
    """GENERATED is what a schema-compliant model reply looks like: every
    entry already the {"text", "source": "model"} shape the prompt and
    GENERATION_SCHEMA ask for, not something generate_plan() had to fix up."""
    from atoo.plan_schema import NOTE_SCHEMA

    plan = _generated()
    assert plan["notes"], "fixture should carry at least one note to make this test meaningful"
    for note in plan["notes"]:
        validate(note, NOTE_SCHEMA)
        assert note["source"] == "model"


def test_model_notes_are_tagged_model():
    """The ordinary path: a compliant model's own notes come back tagged
    "model", unchanged in content, when nothing needed repair or overflowed
    the console."""
    from atoo.generate import generate_plan

    original = _generated()
    result = generate_plan("c", "i", provider=FakeProvider(response=GENERATED.read_text()), console_model="wing-compact")

    assert result["notes"] == original["notes"]
    assert all(n["source"] == "model" for n in result["notes"])


def test_an_unconstrained_models_bare_string_notes_are_tagged_model_too():
    """The tolerance (an unconstrained model writes plain strings
    instead of the {"text", "source"} shape the prompt asks for) still
    applies here -- generate_plan() upgrades each one to "source": "model"
    rather than rejecting a plan whose only fault is this shape."""
    from atoo.generate import generate_plan

    plan = _generated()
    plan["notes"] = ["a plain string note, as an unconstrained model might still write"]
    provider = FakeProvider(response=json.dumps(plan))

    result = generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    assert result["notes"] == [
        {"text": "a plain string note, as an unconstrained model might still write",
         "source": "model"},
    ]


def test_allocation_notes_are_tagged_allocation():
    """An index-overflow warning from allocate.py is Atoo's own
    bookkeeping, not something the model said -- tagged "allocation",
    distinctly from the model's own "model"-tagged notes already in the
    plan.

    An earlier change note: this used to use an unknown console model to provoke
    the warning. That is a hard stop now (see
    `test_an_unknown_console_model_is_a_hard_stop`), so the overflow case
    -- the other thing allocate.py warns about -- carries the test.
    """
    from atoo.generate import generate_plan

    plan = _generated()
    plan["dcas"] = {f"DCA {n}": {"members": []} for n in range(1, 19)}
    result = generate_plan(
        "c", "i", provider=FakeProvider(response=json.dumps(plan)),
        console_model="wing-compact",
    )
    allocation_notes = [n for n in result["notes"] if n["source"] == "allocation"]
    assert len(allocation_notes) == 1
    assert "DCA" in allocation_notes[0]["text"]
    # The model's own notes are still there, still tagged "model".
    assert any(n["source"] == "model" for n in result["notes"])


@pytest.mark.parametrize("model", [None, "", "not-a-real-console"])
def test_an_unknown_console_model_is_a_hard_stop(model):
    """"an unknown console-model is a hard
    stop -- we have no way of knowing what its capabilities are and any
    plan would be meaningless."

    It used to be a warning that skipped the index-overflow checks, which
    reads as a pass in every output that renders notes.
    """
    from atoo.allocate import allocate_console_indices
    from atoo.console_facts import UnknownConsoleModel

    plan = _generated()
    with pytest.raises(UnknownConsoleModel):
        allocate_console_indices(plan, console_model=model)


def test_repair_notes_are_tagged_repair():
    """A json_repair.py fixup describes what generate.py did to a truncated
    reply, not something the model said -- tagged "repair"."""
    from atoo.generate import generate_plan

    original = _generated()
    truncated = json.dumps(original)[:-2]   # drop the closing `}\n` -- the repair path
    provider = FakeProvider(response=truncated)

    result = generate_plan("c", "i", provider=provider, constrain=False, console_model="wing-compact")
    repair_notes = [n for n in result["notes"] if n["source"] == "repair"]
    assert repair_notes
    assert all(n["text"] for n in repair_notes)
    # The model's own notes survive the repair, still tagged "model".
    assert any(n["source"] == "model" and n["text"] == original["notes"][0]["text"]
               for n in result["notes"])


def test_note_line_prefixes_the_source_for_human_facing_output():
    """render.py, report.py and cli.py all print `note_line()` rather than
    the bare note -- this is the one place that formatting is decided, so
    a reader can tell "the model flagged this" apart from "Atoo's own
    repair/allocation step did," which a flat string could not.
    A bare string (a compile-path warning, which is not a `notes` entry at
    all) prints unprefixed, unchanged from before this issue."""
    from atoo.plan_schema import note_line

    assert note_line({"text": "the matrix has no socket", "source": "model"}) == \
        "[model] the matrix has no socket"
    assert note_line({"text": "'notes' was a string -- wrapped it", "source": "repair"}) == \
        "[repair] 'notes' was a string -- wrapped it"
    assert note_line("a plain compiler warning") == "a plain compiler warning"


def test_render_plan_surfaces_the_note_source():
    """A generated plan's `render_plan()` output shows which process wrote
    each warning line -- not just the ambiguous bare text an earlier change exists
    to fix."""
    from atoo.generate import generate_plan
    from atoo.render import render_plan

    # An overflow provokes the "allocation"-tagged line; an unknown
    # console model used to, and is a hard stop.
    source = _generated()
    source["dcas"] = {f"DCA {n}": {"members": []} for n in range(1, 19)}
    plan = generate_plan(
        "c", "i", provider=FakeProvider(response=json.dumps(source)),
        console_model="wing-compact",
    )
    plan.setdefault("conventions_file", "c")
    plan.setdefault("input_list", "i")
    text = render_plan(plan, list(plan["notes"]))
    assert "[model] Matrix has no physical output socket" in text
    assert "[allocation]" in text
    assert "DCA" in text


def test_generation_allocates_console_indices():
    """Without this a generated plan passes verification, satisfies
    expectations, and then dies in apply with KeyError: 'index'."""
    from atoo.generate import generate_plan

    plan = generate_plan("c", "i", provider=FakeProvider(response=GENERATED.read_text()), console_model="wing-compact")
    assert [e["index"] for e in plan["dcas"].values()] == [1, 2, 3, 4, 5, 6]
    assert plan["outputs"]["Main"]["kind"] == "main"
    assert plan["busses"]["Drums"]["destination"]["index"] == 1


def test_a_generated_output_gets_its_index_from_a_stated_kind_not_just_its_name():
    """An earlier change, the generate-path half: a model can name an output "FOH"
    and still say what it is (the generator prompt documents `kind` as
    exactly this). Before this fix allocate.py, like the compiler, only
    ever looked at the NAME -- a stated `kind` was accepted by the
    schema and then silently ignored."""
    from atoo.allocate import allocate_console_indices

    plan = _generated()
    plan["outputs"]["FOH"] = {"kind": "main", "patch": None, "description": None}
    allocate_console_indices(plan, console_model="wing-compact")
    assert plan["outputs"]["FOH"]["kind"] == "main"
    assert isinstance(plan["outputs"]["FOH"]["index"], int)


def test_a_matrix_may_state_what_feeds_it():
    """A model can state fed_by directly (it already knows which
    bus/Main it means, the same way it already knows bus_sends' bus
    names) -- schema-valid for both a Main source and a bus source."""
    plan = _generated()
    plan["outputs"]["Matrix"]["fed_by"] = {"type": "main", "index": 1}
    validate(plan, GENERATION_SCHEMA)

    plan["outputs"]["Matrix"]["fed_by"] = {"type": "bus", "name": "Drums"}
    validate(plan, GENERATION_SCHEMA)


def test_fed_by_may_be_null_or_omitted():
    plan = _generated()
    plan["outputs"]["Matrix"]["fed_by"] = None
    validate(plan, GENERATION_SCHEMA)


@pytest.mark.parametrize("mutate,why", [
    (lambda fb: fb.update(type="matrix"), "a type outside main/bus"),
    (lambda fb: fb.update(index="1"), "a string where an integer belongs"),
    (lambda fb: fb.update(extra="x"), "a field the schema does not name"),
])
def test_the_schema_rejects_a_malformed_fed_by(mutate, why):
    plan = _generated()
    fed_by = {"type": "main", "index": 1}
    mutate(fed_by)
    plan["outputs"]["Matrix"]["fed_by"] = fed_by
    assert rejects(plan, GENERATION_SCHEMA), why


def test_a_bus_may_state_multiple_destinations():
    """An earlier change, Festival_STANDALONE.snap's real finding: a bus can route
    to Main AND a dedicated output at once -- a model already knows both
    (the same way it already knows a single destination), so it states
    them as a list."""
    plan = _generated()
    plan["busses"]["Drums"]["destinations"] = [
        {"type": "main", "index": 1},
        {"type": "dedicated_output", "label": "IEM tap",
         "patch": {"group": "LCL", "sockets": [21]}},
    ]
    validate(plan, GENERATION_SCHEMA)


def test_destinations_may_be_omitted():
    plan = _generated()
    assert "destinations" not in plan["busses"]["Drums"]
    validate(plan, GENERATION_SCHEMA)


def test_an_output_may_state_multiple_patches():
    """An earlier change, TOURING_260821_MIX.snap's real finding: a single Main
    fanning out to several physical sockets at once."""
    plan = _generated()
    plan["outputs"]["Matrix"]["patches"] = [
        {"group": "USB", "sockets": [47, 48]},
        {"group": "SC", "sockets": [31, 32]},
    ]
    validate(plan, GENERATION_SCHEMA)


def test_a_generated_plan_can_actually_be_applied():
    """The end-to-end claim, checked rather than assumed."""
    from atoo.apply import apply_plan
    from atoo.generate import generate_plan

    class _Console:
        def get(self, *a, **k): return None
        def set_param(self, *a, **k): return None
        def set_node(self, *a, **k): return None

    plan = generate_plan("c", "i", provider=FakeProvider(response=GENERATED.read_text()), console_model="wing-compact")
    apply_plan(plan, _Console(), dry_run=True)       # must not raise


def test_verify_reports_schema_violations_as_findings():
    from atoo.input_list import load_input_list
    from atoo.verify_plan import verify_plan

    plan = _generated()
    plan["channels"][0]["colour"] = "red"
    rows = load_input_list(str(FIXTURES / "touringband.csv"))
    result = verify_plan(plan, rows)
    assert any(f.code == "schema" and "colour" in f.message for f in result.findings)


# ---------------------------------------------------------------------------
# hi_cut_hz/tilt_db/trim_db/balance_db/invert/gain_db --
# optional additions to `processing`, never required (see plan_schema.py's
# own comment on this block for why: making them required would break
# every existing plan.json in this repo, and every test fixture that
# builds a minimal channel dict, for omitting a field it predates).
# ---------------------------------------------------------------------------

def test_processing_still_validates_with_only_hpf_and_preset():
    """The exact shape a plan predating this issue has -- no new keys at
    all, not even null ones."""
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    assert "hi_cut_hz" not in channel["processing"]
    validate(channel, CHANNEL_SCHEMA)


def test_processing_accepts_every_new_field_populated():
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"].update(
        hi_cut_hz=8000.0, tilt_db=2.0, trim_db=6.0, balance_db=-3.0,
        invert=True, gain_db=30.0,
    )
    validate(channel, CHANNEL_SCHEMA)


def test_processing_new_fields_may_be_null():
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"].update(
        hi_cut_hz=None, tilt_db=None, trim_db=None,
        balance_db=None, invert=None, gain_db=None,
    )
    validate(channel, CHANNEL_SCHEMA)


@pytest.mark.parametrize("field,bad_value", [
    ("hi_cut_hz", facts.HI_CUT_HZ_RANGE[1] + 1),
    ("hi_cut_hz", facts.HI_CUT_HZ_RANGE[0] - 1),
    ("tilt_db", facts.TILT_DB_RANGE[1] + 1),
    ("tilt_db", facts.TILT_DB_RANGE[0] - 1),
    ("trim_db", facts.TRIM_DB_RANGE[1] + 1),
    ("trim_db", facts.TRIM_DB_RANGE[0] - 1),
    ("balance_db", facts.BALANCE_DB_RANGE[1] + 1),
    ("balance_db", facts.BALANCE_DB_RANGE[0] - 1),
    ("gain_db", facts.HEAD_AMP_GAIN_DB_RANGE[1] + 1),
    ("gain_db", facts.HEAD_AMP_GAIN_DB_RANGE[0] - 1),
])
def test_processing_rejects_a_new_field_out_of_range(field, bad_value):
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"][field] = bad_value
    assert rejects(channel, CHANNEL_SCHEMA), (field, bad_value)


def test_processing_new_fields_are_optional_not_required():
    """The critical design decision this issue turns on."""
    proc = CHANNEL_SCHEMA["properties"]["processing"]
    assert proc["required"] == ["hpf_hz", "preset"]
    for field in ("hi_cut_hz", "tilt_db", "trim_db", "balance_db", "invert", "gain_db"):
        assert field in proc["properties"]
        assert field not in proc["required"]


def test_every_compiled_fixture_satisfies_the_format_schema():
    """The schema describes the format, not one path's view of it -- proved
    by running it over four real plans for four real shows.

    These used to be built by shelling out to the deterministic compiler.
    An earlier change retired it, so the plans are checked in (generated from the
    compiler at `origin/main` immediately before deletion). The point of
    the test is unchanged: the schema has to accept plans for shows of
    very different shapes, from 9 channels to 38.
    """
    from atoo.plan_schema import PLAN_SCHEMA
    from atoo.schema_check import validate

    plans = json.loads((FIXTURES / "real_plans.json").read_text())
    assert set(plans) == {"smallband", "fullband", "touringband", "festival"}
    for stem, plan in plans.items():
        assert validate(normalise_plan(plan), PLAN_SCHEMA) == [], stem


# ---------------------------------------------------------------------------
# `processing.eq` on a channel, and a whole `processing`
# block on a bus and an output -- which had none at all before, the gap this
# issue was filed for. Additive on exactly the same terms as phase 1 above.
# ---------------------------------------------------------------------------

def test_a_channel_without_an_eq_block_is_still_valid():
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    assert "eq" not in channel["processing"]
    validate(channel, CHANNEL_SCHEMA)


def test_channel_eq_accepts_a_fully_stated_band():
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"]["eq"] = {
        "on": True, "model": "SOUL",
        "bands": [{"band": "low", "freq_hz": 120.0, "gain_db": -3.0, "q": 0.7, "shape": "SHV"}],
    }
    validate(channel, CHANNEL_SCHEMA)


def test_channel_eq_rejects_a_band_number_a_channel_does_not_have():
    """The asymmetry this slice exists to hold: `ch.eq` stops at band 4,
    `bus.eq` runs to 6. A schema modelling "six bands" everywhere would
    let a plan ask for `/ch/{n}/eq.5f`, a leaf the firmware never answers."""
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"]["eq"] = {"bands": [{"band": "5", "gain_db": 1.0}]}
    assert rejects(channel, CHANNEL_SCHEMA)


def test_bus_eq_accepts_band_five_and_six():
    bus = json.loads(json.dumps(EXAMPLE_BUS))
    bus["processing"] = {"eq": {"bands": [{"band": "5", "gain_db": 1.0}, {"band": "6", "gain_db": -1.0}]},
                         "tilt_db": -2.0}
    validate(bus, BUS_SCHEMA)


@pytest.mark.parametrize("field,bad_value", [
    ("freq_hz", facts.EQ_FREQ_HZ_RANGE[1] + 1),
    ("freq_hz", facts.EQ_FREQ_HZ_RANGE[0] - 1),
    ("gain_db", facts.EQ_GAIN_DB_RANGE[1] + 1),
    ("gain_db", facts.EQ_GAIN_DB_RANGE[0] - 1),
    ("q", facts.EQ_Q_RANGE[1] + 1),
    ("q", facts.EQ_Q_RANGE[0] - 0.1),
])
def test_channel_eq_rejects_a_band_value_out_of_range(field, bad_value):
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"]["eq"] = {"bands": [{"band": "1", field: bad_value}]}
    assert rejects(channel, CHANNEL_SCHEMA), (field, bad_value)


def test_channel_eq_holds_the_union_of_both_banks_shelf_types():
    """One CHANNEL_SCHEMA serves `ch` and `aux`, whose shelf enums differ
    (aux also takes CUT), so the schema can only hold their union -- and
    verify_plan.py makes the exact per-bank call. Pinning the union here
    keeps "the schema is deliberately loose about this" from reading as
    an oversight later."""
    shapes = CHANNEL_SCHEMA["properties"]["processing"]["properties"]["eq"] \
        ["properties"]["bands"]["items"]["properties"]["shape"]["enum"]
    assert set(facts.EQ_SHELF_TYPES["ch"]) | set(facts.EQ_SHELF_TYPES["aux"]) == set(shapes) - {None}
    assert "BW12" not in shapes          # a bus-only filter type, on neither bank


def test_eq_mix_is_representable_and_bounded():
    """The maintainer's scope for this issue (2026-09-21): EQ is
    modelled in FULL for channels and busses. `eq.mix` is the one
    remaining leaf on the node an engineer sets and a show depends on --
    the solo state is transient surface, not a setting."""
    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"]["eq"] = {"mix_pct": 60.0, "bands": []}
    validate(channel, CHANNEL_SCHEMA)
    channel["processing"]["eq"] = {"mix_pct": facts.EQ_MIX_PCT_RANGE[1] + 1, "bands": []}
    assert rejects(channel, CHANNEL_SCHEMA)

    bus = json.loads(json.dumps(EXAMPLE_BUS))
    bus["processing"] = {"eq": {"mix_pct": 125.0}}
    validate(bus, BUS_SCHEMA)


def test_an_outputs_eq_is_the_six_band_one():
    output = json.loads(json.dumps(EXAMPLE_OUTPUT))
    output["processing"] = {"eq": {"bands": [{"band": "6", "gain_db": 2.0, "shape": None}]}}
    validate(output, OUTPUT_SCHEMA)


def test_eq_is_optional_on_every_strip_that_has_one():
    proc = CHANNEL_SCHEMA["properties"]["processing"]
    assert "eq" in proc["properties"] and "eq" not in proc["required"]
    assert "processing" not in (BUS_SCHEMA.get("required") or [])
    assert "processing" not in (OUTPUT_SCHEMA.get("required") or [])


def test_a_bus_has_a_tilt_field_and_a_channels_eq_block_does_not():
    """Tilt crosses nodes: a channel's is `ch.{n}.flt.tilt` (already
    `processing.tilt_db`), a bus's is `bus.{n}.eq.tilt`, and an aux has
    neither -- it has no `flt` node at all."""
    assert "tilt_db" in BUS_SCHEMA["properties"]["processing"]["properties"]
    assert "tilt_db" in OUTPUT_SCHEMA["properties"]["processing"]["properties"]
    assert "tilt_db" in CHANNEL_SCHEMA["properties"]["processing"]["properties"]
    assert "tilt_db" not in CHANNEL_SCHEMA["properties"]["processing"]["properties"]["eq"]["properties"]


def test_the_prompt_tells_the_model_the_band_counts_it_must_respect():
    """A schema that enforces a fact the prompt never states produces a
    model that keeps generating rejected plans -- the lesson, one
    field over: when a fact moves, grep for every RENDERER of it, not
    just every consumer."""
    section = schema_section()
    assert '"low", "1", "2", "3", "4", "high"' in section
    assert '"low", "1".."6", "high"' in section
    for shape in facts.EQ_SHELF_TYPES["ch"]:
        assert shape in section
    assert "MACH4" in section
    # The two paragraphs that used to say a bus's/Main's EQ has no field
    # at all must not still say it.
    assert "A bus's compressor/EQ/insert settings have no field" not in section
    assert "Main/Matrix EQ or processing has no field either" not in section


def test_presend_eq_is_three_bells_with_no_shelf_and_no_model():
    """`ch.{n}.peq` is a different node, not the main EQ with fewer bands
    -- modelling it as a variant would invite the "surely it has a low
    band too" assumption this issue's band-count lesson is against."""
    peq = CHANNEL_SCHEMA["properties"]["processing"]["properties"]["presend_eq"]
    assert peq["properties"]["bands"]["items"]["properties"]["band"]["enum"] == ["1", "2", "3"]
    assert set(peq["properties"]) == {"on", "bands"}          # no model, no mix, no tilt
    assert "shape" not in peq["properties"]["bands"]["items"]["properties"]

    channel = json.loads(json.dumps(EXAMPLE_CHANNEL))
    channel["processing"]["presend_eq"] = {"on": True, "bands": [{"band": "3", "freq_hz": 5000.0, "q": 1.0}]}
    validate(channel, CHANNEL_SCHEMA)
    channel["processing"]["presend_eq"] = {"bands": [{"band": "low", "gain_db": 1.0}]}
    assert rejects(channel, CHANNEL_SCHEMA)


def test_a_source_with_no_model_or_type_is_a_valid_plan():
    """2026-09-25, the maintainer's festival build: the input list left 23 model
    cells blank, the generator wrote `"model": null` as rule 4 tells it
    to, and the strict string schema threw the whole $0.61 generation
    away. A missing mic model breaks nothing -- it is allowed now."""
    import copy
    from atoo import schema_check, plan_schema
    from atoo.render import _source_desc
    channel = copy.deepcopy(plan_schema.EXAMPLE_CHANNEL)
    channel["source"]["model"] = None
    channel["source"]["type"] = None
    assert schema_check.validate(channel, plan_schema.CHANNEL_SCHEMA) == []
    assert _source_desc(channel["source"]) == ""
    channel["source"]["model"] = 7
    assert schema_check.validate(channel, plan_schema.CHANNEL_SCHEMA)
