"""Channels the conventions or instructions ask for that are not on the
input list (the maintainer, 2026-09-29; `atoo/instructed_channels.py`).

The case is sixpiece: its instructions say *"Setup Talkback on Channel
40, source A 40"*, Haiku's reply built a Talkback channel on 40, and the
build refused it (rule 2: invent nothing). Now such a channel is built
when its source socket is stated and its quote is really in the texts;
verify reports it as a WARNING. One with no stated socket, or a quote the
engineer never wrote, is still refused.

Every file read here is frozen under `tests/fixtures/` (CLAUDE.md): the
reply, the sixpiece input list, its instructions and the conventions it
was built with, as they were on 2026-09-29.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import generate, instructed_channels, plan_schema, reply_expand
from atoo.ai_provider import FakeProvider
from atoo.allocate import allocate_console_indices
from atoo.apply import _build_write_targets
from atoo.input_list import parse_input_list
from atoo.schema_check import anthropic_schema, validate
from atoo.verify_plan import verify_plan

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIXPIECE_REPLY = FIXTURES / "haiku45_sixpiece_2026-09-29.reply.json"
SIXPIECE_CSV = FIXTURES / "sixpiece_2026-09-29.csv"
SIXPIECE_INSTRUCTIONS = FIXTURES / "sixpiece_instructions_2026-09-29.md"
SIXPIECE_CONVENTIONS = FIXTURES / "sixpiece_conventions_2026-09-29.md"
TALKBACK_QUOTE = "Setup Talkback on Channel 40, source A 40"


def _sixpiece_layers():
    return instructed_channels.layers_from_texts(
        SIXPIECE_CONVENTIONS.read_text(), "conventions.md",
        SIXPIECE_INSTRUCTIONS.read_text(), "instructions.md")


def _sixpiece_reply(*, without_second_pair_row_sends: bool = False) -> dict:
    reply = json.loads(SIXPIECE_REPLY.read_text())
    if without_second_pair_row_sends:
        # A stand-in for a slip this change does not repair: Haiku names
        # the pair's second row ('Keys R') in the busses' sender lists,
        # and the build refuses a send from a strip that does not exist.
        for bus in reply["busses"]:
            for group in bus.get("sends") or []:
                group["from"] = [n for n in group["from"] if n != "Keys R"]
    return reply


def _expand_sixpiece(reply: dict, findings: list | None = None) -> dict:
    reply_expand.expand(reply, input_csv=SIXPIECE_CSV.read_text(), findings=findings,
                        console_model="wing-compact", layers=_sixpiece_layers())
    reply.setdefault("meta", {})["console_model"] = "wing-compact"
    # The rest of what `generate_plan` does after expanding: number the
    # busses, DCAs and mute groups.
    allocate_console_indices(reply, console_model="wing-compact")
    return reply


def _channel(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


# --------------------------------------------------------------------------
# sixpiece on Haiku, 2026-09-29, replayed
# --------------------------------------------------------------------------

def test_sixpiece_talkback_is_no_longer_what_stops_the_build():
    """The reply now gets past Talkback. What stops it next is Haiku's own
    slip: the monitor busses' sender lists name 'Keys R', the second row
    of the Keys pair, which is no strip of the plan."""
    with pytest.raises(reply_expand.ReplyError) as exc:
        _expand_sixpiece(_sixpiece_reply())
    assert "'Keys R'" in str(exc.value)
    assert "Talkback" not in str(exc.value).split("Channels:")[0]


def test_sixpiece_talkback_is_built_on_ch_40_from_a_40_and_said_at_info():
    findings: list = []
    plan = _expand_sixpiece(_sixpiece_reply(without_second_pair_row_sends=True), findings)
    tb = _channel(plan, "Talkback")
    assert (tb["bank"], tb["channel"]) == ("ch", 40)
    assert tb["patch"] == {"group": "A", "sockets": [40], "stated": True}
    assert tb["source"] == {"input": "Talkback", "type": "Mic", "model": None,
                            "stereo": False, "phantom": False,
                            "from": "instructions", "quote": TALKBACK_QUOTE}
    assert TALKBACK_QUOTE in tb["provenance"]["input"]
    assert "AES50-A 40" in tb["provenance"]["patch"]
    [info] = [d for d in findings if d.code == "reply.from-instructions"]
    assert info.severity.name == "INFO"
    assert "instructions.md says 'Setup Talkback on Channel 40, source A 40'" in info.message
    assert "phantom off" in info.message and "type Mic" in info.message
    # Nothing else was pushed off A 40 to make room.
    others = [c for c in plan["channels"] if c is not tb
              and c["patch"]["group"] == "A" and 40 in c["patch"]["sockets"]]
    assert others == []


def test_sixpiece_verify_notes_talkback_and_nothing_stops_the_plan():
    """The instructions ask for Talkback in so many words, socket and all,
    so it is an INFO, not something to check."""
    plan = _expand_sixpiece(_sixpiece_reply(without_second_pair_row_sends=True))
    assert validate(plan, plan_schema.PLAN_SCHEMA) == []
    result = verify_plan(plan, parse_input_list(SIXPIECE_CSV.read_text()),
                         console_model="wing-compact", layers=_sixpiece_layers())
    [warning] = [f for f in result.findings if f.code == "reconcile.from-instructions"]
    assert warning.severity == "info"
    assert warning.message.endswith(", on AES50-A 40 as it states"), warning.message
    assert warning.message.startswith(
        "ch 40 'Talkback' is not on the input list; built because instructions.md says "
        "'Setup Talkback on Channel 40, source A 40'")
    assert "not checked" not in warning.message
    assert not [f for f in result.findings if f.code == "reconcile.invented-source"]
    # The counted Keys pair's second row is named on the channel
    # (`source.pair_input`), so nothing stops the plan.
    assert result.errors == []


def test_sixpiece_apply_patches_ch_40_from_a_40():
    plan = _expand_sixpiece(_sixpiece_reply(without_second_pair_row_sends=True))
    targets, _ = _build_write_targets(plan, False)
    by_address = {t.address: t for t in targets}
    assert by_address["/ch/40/in/conn/grp"].compute_value(None) == "A"
    assert by_address["/ch/40/in/conn/in"].compute_value(None) == 40


def test_a_talkback_channel_built_this_way_is_the_talk_mic_to_sp_cv014():
    """CV014 fires when talkback is assigned to CH40 and the plan puts a
    band input there. The Talkback strip is the talk mic: silent."""
    from atoo import console_facts
    from atoo.audit import ConsoleState, diff_against_plan

    plan = _expand_sixpiece(_sixpiece_reply(without_second_pair_row_sends=True))
    state = ConsoleState({console_facts.TALK_ASSIGN: "CH40", "/ch/40/name": "Talkback"})
    assert [f for f in diff_against_plan(state, plan) if f.rule_id == "CV014"] == []


# --------------------------------------------------------------------------
# the rule, on a two-row show built in the test
# --------------------------------------------------------------------------

CSV = "name,category,type,phantom\nKick,drums,Mic,FALSE\nVox,vocals,Mic,FALSE\n"
CONVENTIONS = "## Colours\nDrums red, vocals blue, misc white.\n"


def _reply(extra: dict) -> dict:
    return {"channels": [{"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Vox", "patch": {"group": "LCL"}},
                         extra],
            "category_colors": [{"category": "drums", "color": "Red"},
                                {"category": "misc", "color": "White"}],
            "busses": [],
            "outputs": [{"name": "Main", "kind": "main",
                         "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": [], "notes": []}


def _build(extra: dict, instructions: str | None, findings: list | None = None,
           conventions: str = CONVENTIONS) -> dict:
    return generate.generate_plan(
        conventions, CSV, provider=FakeProvider(response=json.dumps(_reply(extra))),
        console_model="wing-compact", instructions=instructions,
        instructions_name="instructions.md", conventions_name="conventions.md",
        findings=findings)


def _layers(instructions: str):
    return instructed_channels.layers_from_texts(CONVENTIONS, "conventions.md",
                                                 instructions, "instructions.md")


def test_a_channel_with_its_quote_and_stated_socket_is_built():
    instructions = "## Inputs\nPut the talk mic on LCL 12.\n"
    findings: list = []
    plan = _build({"input": "Talk mic", "quote": "Put the talk mic on LCL 12."},
                  instructions, findings)
    tb = _channel(plan, "Talk mic")
    assert tb["patch"] == {"group": "LCL", "sockets": [12], "stated": True}
    assert tb["channel"] == 3
    assert tb["color"] == "White"          # misc, the category it falls back to
    assert tb["source"]["from"] == "instructions"
    # The counted rows never land on the stated socket.
    assert [c["patch"]["sockets"] for c in plan["channels"][:2]] == [[1], [2]]
    result = verify_plan(plan, parse_input_list(CSV), layers=_layers(instructions))
    assert result.errors == []
    # This bare reply routes nothing anywhere, so every strip also reaches
    # no output -- a separate check (`test_channel_reaches_nothing.py`).
    # And a talk mic on ch 3 is one the desk's talkback cannot use
    # (`talkback.unassignable`, `test_full_apply.py`).
    assert [f.code for f in result.warnings
            if f.code not in ("routing.channel-reaches-nothing", "talkback.unassignable")
            ] == []
    # Asked for verbatim, with its socket: noted, not to check.
    assert [f.severity for f in result.findings
            if f.code == "reconcile.from-instructions"] == ["info"]
    assert "talkback.unassignable" in {f.code for f in result.warnings}


def test_the_conventions_can_ask_for_one_too():
    conventions = CONVENTIONS + "## Inputs\nAlways add an ambient mic on AUX 1.\n"
    plan = _build({"input": "Ambient", "quote": "Always add an ambient mic on AUX 1."},
                  None, conventions=conventions)
    amb = _channel(plan, "Ambient")
    assert amb["source"]["from"] == "conventions"
    assert amb["patch"]["group"] == "AUX" and amb["patch"]["sockets"] == [1]


def test_a_channel_whose_quote_is_not_in_the_instructions_is_refused():
    instructions = "## Inputs\nPut the talk mic on LCL 12.\n"
    with pytest.raises(generate.GenerationError, match="not in the conventions or instructions"):
        _build({"input": "Click", "quote": "Add a click track on LCL 13."}, instructions)


def test_a_channel_with_no_stated_socket_is_refused():
    instructions = "## Inputs\nAdd a talkback mic for the engineer.\n"
    with pytest.raises(generate.GenerationError, match="states no source socket"):
        _build({"input": "Talkback", "quote": "Add a talkback mic for the engineer."},
               instructions)


def test_a_channel_that_quotes_nothing_is_refused_as_before():
    with pytest.raises(generate.GenerationError, match="rule 2: invent nothing"):
        _build({"input": "Talkback"}, "## Inputs\nTalkback on LCL 12.\n")


def test_the_stated_socket_wins_over_the_replys_patch():
    instructions = "## Inputs\nTalkback on LCL 12.\n"
    plan = _build({"input": "Talkback", "quote": "Talkback on LCL 12.",
                   "patch": {"group": "LCL", "sockets": [5]}}, instructions)
    assert _channel(plan, "Talkback")["patch"]["sockets"] == [12]
    assert any("the stated socket wins" in n["text"] for n in plan["notes"])


# The third sixpiece run on Haiku (2026-09-29) wrote no `channel` for
# Talkback, and the strip was counted onto ch 24 although the line it
# quoted says "Channel 40". A channel number the text states is the
# number, as its socket is.

def test_a_channel_number_the_text_states_is_used_when_the_reply_gives_none():
    instructions = "## Inputs\nSetup Talkback on Channel 40, source A 40.\n"
    findings: list = []
    plan = _build({"input": "Talkback", "quote": "Setup Talkback on Channel 40, source A 40."},
                  instructions, findings)
    tb = _channel(plan, "Talkback")
    assert (tb["bank"], tb["channel"]) == ("ch", 40)
    assert "states channel 40" in tb["provenance"]["channel"]
    [info] = [d for d in findings if d.code == "reply.from-instructions"]
    assert "On that channel and patched from AES50-A 40" in info.message


def test_the_stated_channel_wins_over_the_replys_and_says_so():
    instructions = "## Inputs\nTalkback on ch 40, source LCL 12.\n"
    plan = _build({"input": "Talkback", "quote": "Talkback on ch 40, source LCL 12.",
                   "channel": 3}, instructions)
    assert _channel(plan, "Talkback")["channel"] == 40
    assert any("the stated channel wins" in n["text"] for n in plan["notes"])


def test_counting_steps_round_a_stated_channel_and_is_not_moved_by_it():
    # Listed FIRST, on a stated ch 2: the rows after it are counted 1 and 3,
    # not 3 and 4, and not onto 2.
    reply = _reply({})
    reply["channels"] = [{"input": "Talkback", "quote": "Talkback on Channel 2, source LCL 12."},
                         {"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Vox", "patch": {"group": "LCL"}}]
    plan = generate.generate_plan(
        CONVENTIONS, CSV, provider=FakeProvider(response=json.dumps(reply)),
        console_model="wing-compact", instructions="## Inputs\nTalkback on Channel 2, source LCL 12.\n",
        instructions_name="instructions.md", conventions_name="conventions.md")
    assert {c["name"]: c["channel"] for c in plan["channels"]} == {
        "Talkback": 2, "Kick": 1, "Vox": 3}


def test_a_line_naming_two_channels_states_none():
    assert instructed_channels.stated_channel("Talkback on ch 40 or ch 39, A 40", None) is None
    assert instructed_channels.stated_channel("Setup Talkback on Channel 40, source A 40",
                                              None) == 40
    assert instructed_channels.stated_channel("Talkback on A 40", None) is None


def test_phantom_is_on_only_when_the_text_asks():
    instructions = "## Inputs\nAmbient condenser on LCL 12 with phantom.\n"
    plan = _build({"input": "Ambient",
                   "quote": "Ambient condenser on LCL 12 with phantom."}, instructions)
    assert _channel(plan, "Ambient")["source"]["phantom"] is True


# --------------------------------------------------------------------------
# verify, on a plan edited by hand
# --------------------------------------------------------------------------

def _plan_with(source_extra: dict, patch: dict | None = None) -> dict:
    instructions = "## Inputs\nTalkback on LCL 12.\n"
    plan = _build({"input": "Talkback", "quote": "Talkback on LCL 12."}, instructions)
    tb = _channel(plan, "Talkback")
    tb["source"].update(source_extra)
    if patch is not None:
        tb["patch"] = patch
    return plan


def _codes(plan: dict, layers) -> list[tuple[str, str]]:
    result = verify_plan(plan, parse_input_list(CSV), layers=layers)
    return [(f.severity, f.code) for f in result.findings if f.severity != "info"]


def test_verify_refuses_a_quote_that_is_not_in_the_texts():
    plan = _plan_with({"quote": "Talkback on LCL 12, the engineer said so."})
    assert ("error", "reconcile.invented-source") in _codes(
        plan, _layers("## Inputs\nTalkback on LCL 12.\n"))


def test_verify_refuses_a_quote_that_states_no_socket():
    instructions = "## Inputs\nTalkback for the engineer.\n"
    plan = _plan_with({"quote": "Talkback for the engineer."})
    assert ("error", "reconcile.invented-source") in _codes(plan, _layers(instructions))


def test_verify_refuses_a_patch_the_quote_does_not_state():
    plan = _plan_with({}, patch={"group": "LCL", "sockets": [11], "stated": True})
    codes = _codes(plan, _layers("## Inputs\nTalkback on LCL 12.\n"))
    assert ("error", "patch.contradicts-instructions") in codes


def test_verify_without_the_texts_warns_that_the_quote_was_not_checked():
    plan = _plan_with({})
    result = verify_plan(plan, parse_input_list(CSV), layers=None)
    [warning] = [f for f in result.findings if f.code == "reconcile.from-instructions"]
    assert "The quote was not checked" in warning.message
    assert result.errors == []


def test_a_channel_off_the_list_without_from_is_still_invented():
    plan = _plan_with({})
    tb = _channel(plan, "Talkback")
    del tb["source"]["from"], tb["source"]["quote"]
    assert ("error", "reconcile.invented-source") in _codes(
        plan, _layers("## Inputs\nTalkback on LCL 12.\n"))


def test_verify_show_finds_the_bundles_instructions(tmp_path, capsys):
    from atoo.cli import main

    instructions = "## Inputs\nTalkback on LCL 12.\n"
    plan = _plan_with({})
    (tmp_path / "instructions.md").write_text(instructions)
    (tmp_path / "input.csv").write_text(CSV)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    assert main(["verify", "--show", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "reconcile.from-instructions" in out
    # The quote is recorded as the engineer's words, label and full stop stripped.
    assert "instructions.md says 'Talkback on LCL 12'" in out
    assert "not checked" not in out


# --------------------------------------------------------------------------
# the representation
# --------------------------------------------------------------------------

def test_the_reply_and_the_plan_can_both_say_it_and_old_plans_are_unaffected():
    reply_channel = plan_schema.REPLY_CHANNEL_SCHEMA["properties"]
    assert reply_channel["quote"] == {"type": "string", "minLength": 1}
    source = plan_schema.CHANNEL_SCHEMA["properties"]["source"]
    assert source["properties"]["from"]["enum"] == ["conventions", "instructions"]
    assert "from" not in source["required"] and "quote" not in source["required"]
    assert anthropic_schema(plan_schema.REPLY_SCHEMA) is not None


def test_the_prompt_says_it_in_one_line():
    gen = " ".join(generate.generator_system("wing-compact").split())
    assert ("Except one the conventions or instructions ask for with its socket stated: "
            'write its "patch" and "quote" (their sentence).') in gen


def test_stated_sockets_reads_the_ways_an_engineer_writes_one():
    read = instructed_channels.stated_sockets
    assert read(TALKBACK_QUOTE) == [("A", 40)]
    assert read("talk mic in LCL3") == [("LCL", 3)]
    assert read("AES50-B 12") == [("B", 12)]
    assert read("on channel 40, ch 7") == []
    # A lower-case "a" is an article, not the AES50-A network.
    assert read("add a 4 way split") == []


def test_expansion_does_not_touch_a_reply_it_does_not_need_to():
    reply = _reply({"input": "Kick"})
    reply["channels"] = reply["channels"][:2]
    before = copy.deepcopy(reply)
    reply_expand.expand(reply, input_csv=CSV, console_model="wing-compact")
    assert [c["source"].get("from") for c in reply["channels"]] == [None, None]
    assert len(before["channels"]) == 2


# --------------------------------------------------------------------------
# a labelled or partial quote (Haiku's second sixpiece build, 2026-09-29)
# --------------------------------------------------------------------------
# The reply quoted 'Instructions: Talkback on Channel 40, source A 40'; the
# instructions say 'Setup Talkback on Channel 40, source A 40.' The label
# is the model's and "Setup" was dropped, but what remains is the
# engineer's own words, verbatim -- so it vouches for the channel.

SIXPIECE_ROUND2_QUOTE = "Instructions: Talkback on Channel 40, source A 40"


def test_a_labelled_quote_missing_its_first_word_is_found():
    layer = instructed_channels.find(SIXPIECE_ROUND2_QUOTE, _sixpiece_layers())
    assert layer is not None and layer.role == "instructions"
    assert instructed_channels.sockets_for(SIXPIECE_ROUND2_QUOTE, layer) == [("A", 40)]


@pytest.mark.parametrize("quote", [
    "instructions.md: 'Talkback on Channel 40, source A 40.'",
    'Conventions: "Setup Talkback on Channel 40, source A 40."',   # found in the other layer
    "Input list: “Setup Talkback on Channel 40”",
    "Instructions § Inputs: Setup Talkback on Channel 40, source A 40.",
])
def test_every_kind_of_source_label_is_stripped(quote):
    assert instructed_channels.find(quote, _sixpiece_layers()) is not None


def test_a_quote_whose_socket_is_only_in_its_line_takes_it_from_the_line():
    quote = "Instructions: Setup Talkback on Channel 40"
    layer = instructed_channels.find(quote, _sixpiece_layers())
    assert instructed_channels.stated_sockets(instructed_channels.clean_quote(quote)) == []
    assert instructed_channels.sockets_for(quote, layer) == [("A", 40)]


def test_an_invented_quote_is_still_refused():
    for quote in ("Instructions: Talkback on Channel 40, source A 41",
                  "Instructions: Add a talkback mic on A 40 for the engineer"):
        assert instructed_channels.find(quote, _sixpiece_layers()) is None


def test_a_fragment_shorter_than_four_words_vouches_for_nothing():
    # Both are in the instructions verbatim; neither says which sentence.
    for quote in ("source A 40", "Instructions: 'on Channel 40'", "Channel 40"):
        assert instructed_channels.find(quote, _sixpiece_layers()) is None


def test_the_round_2_talkback_is_built_and_verifies():
    reply = _sixpiece_reply(without_second_pair_row_sends=True)
    tb_reply = next(c for c in reply["channels"] if c.get("input") == "Talkback")
    tb_reply["provenance"]["input"] = SIXPIECE_ROUND2_QUOTE
    plan = _expand_sixpiece(reply)
    tb = _channel(plan, "Talkback")
    assert tb["patch"] == {"group": "A", "sockets": [40], "stated": True}
    assert tb["source"]["quote"] == "Talkback on Channel 40, source A 40"
    result = verify_plan(plan, parse_input_list(SIXPIECE_CSV.read_text()),
                         console_model="wing-compact", layers=_sixpiece_layers())
    assert not [f for f in result.findings if f.code == "reconcile.invented-source"]
    assert [f.code for f in result.findings if f.code == "reconcile.from-instructions"]


def test_the_build_refuses_a_two_word_fragment():
    instructions = "## Inputs\nPut the talk mic on LCL 12.\n"
    with pytest.raises(generate.GenerationError, match="is only 2 words .* too short"):
        _build({"input": "Talk mic", "quote": "LCL 12"}, instructions)


def test_the_unassigned_quote_check_strips_a_label_too():
    from atoo.input_list import InputRow  # noqa: F401 -- the row type the check reads
    row = parse_input_list("name,category,type,phantom,notes\n"
                           "Spare,misc,Mic,FALSE,Not patched for this event\n")[0]
    layers = reply_expand._unassigned_quote_layers(row, _layers("## Inputs\n"))
    assert instructed_channels.find("Input list notes: 'not patched for this event.'",
                                    layers) is not None
    assert instructed_channels.find("Input list: 'not patched'", layers) is None


# ---- Asked for in so many words is an INFO --------------------
#
# The maintainer, 2026-10-11: "Downgrade reconcile.from-instructions to INFO when
# the instructions quote the strip verbatim and state its socket. Keep it a
# WARNING when the strip was inferred, paraphrased or has no stated socket."

def _from_instructions(result):
    return [(f.severity.value, f.message) for f in result.findings
            if f.code == "reconcile.from-instructions"]


def test_a_verbatim_request_with_its_socket_is_an_info():
    instructions = "## Inputs\nPut the talk mic on LCL 12.\n"
    plan = _build({"input": "Talk mic", "quote": "Put the talk mic on LCL 12."}, instructions)
    [(severity, message)] = _from_instructions(
        verify_plan(plan, parse_input_list(CSV), layers=_layers(instructions)))
    assert severity == "info"
    assert message == ("ch 3 'Talk mic' is not on the input list; built because "
                       "instructions.md says 'Put the talk mic on LCL 12', on LCL 12 as it states")


def test_an_unchecked_quote_stays_a_warning():
    """No conventions or instructions to find the quote in: nobody can say
    it was verbatim."""
    instructions = "## Inputs\nPut the talk mic on LCL 12.\n"
    plan = _build({"input": "Talk mic", "quote": "Put the talk mic on LCL 12."}, instructions)
    [(severity, message)] = _from_instructions(verify_plan(plan, parse_input_list(CSV)))
    assert severity == "warning" and "not checked" in message


@pytest.mark.parametrize("quote, line, resolved, explicit", [
    # Verbatim, socket in the quote, in the engineer's own file.
    ("Put the talk mic on LCL 12", "Put the talk mic on LCL 12.", False, True),
    # The socket is only in the rest of the line, not in what was quoted.
    ("Put the talk mic on channel 3", "Put the talk mic on channel 3, source LCL 12.",
     False, False),
    # Found only in the resolved conventions: the model's restatement.
    ("Put the talk mic on LCL 12", "Put the talk mic on LCL 12.", True, False),
    # A fragment shorter than MIN_QUOTE_WORDS vouches for nothing.
    ("TB: LCL 12", "TB: LCL 12", False, False),
])
def test_what_counts_as_explicitly_requested(quote, line, resolved, explicit):
    from atoo.verify_plan import _explicitly_requested
    layer = instructed_channels.Layer("instructions", "instructions.md", line, resolved=resolved)
    assert _explicitly_requested(quote, layer) is explicit


def test_no_layer_is_never_explicit():
    from atoo.verify_plan import _explicitly_requested
    assert _explicitly_requested("Put the talk mic on LCL 12", None) is False
