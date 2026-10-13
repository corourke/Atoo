"""The generator's shorter reply, expanded into today's plan
(`atoo/reply_expand.py`; docs/developer/plan-output-compaction.md,
slices 2-4).

Every plan here is frozen under `tests/fixtures/` or built in the test.
Nothing reads `examples/` (CLAUDE.md: a bundle there is a living example,
not a fixture). `_compact()` is the test's own inverse of the expander --
what a model writing the reply format would have written for a plan --
so the round trip `expand(compact(plan)) == plan` can be checked on the
four real plans in `real_plans.json` and on `touringband.plan.json`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import console_facts as facts
from atoo import generate, inferred, plan_compat, plan_schema, reply_expand, schema_check
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_PLANS = json.loads((FIXTURES / "real_plans.json").read_text())
CSV_FOR = {"smallband": "smallband", "fullband": "fullband",
           "touringband": "touringband", "festival": "festival"}


def _plans():
    """The frozen plans, read as a plan built today is: old `socket` keys
    under their new names and every rule-4b width decided -- the
    compiler-era fixtures left `mono` null, which the reply may not."""
    plans = dict(REAL_PLANS)
    plans["touringband.plan"] = json.loads((FIXTURES / "touringband.plan.json").read_text())
    return {stem: inferred.with_decisions(plan_compat.normalise_plan(plan))
            for stem, plan in plans.items()}


def _csv(stem: str) -> str:
    return (FIXTURES / f"{CSV_FOR.get(stem.split('.')[0], stem)}.csv").read_text()


# --------------------------------------------------------------------------
# the inverse: a plan as the model would have written it
# --------------------------------------------------------------------------

def _strip_nulls(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if v is None and k not in ("destination", "patch"):   # written even when null
                continue
            v = _strip_nulls(v)
            if v == {} and k in ("processing", "fader"):
                continue
            out[k] = v
        return out
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


def _compact(plan: dict) -> dict:
    """The reply a model would have written for `plan`: no nulls, arrays
    for the name-keyed maps, no index (allocation writes it), each bus's
    senders once, and each channel as its input-list row plus what was
    decided -- no number, no source facts, no stated socket, and for an
    unstated one only the group (code counts the number)."""
    reply = {"channels": [], "dcas": [], "mute_groups": [], "busses": [], "outputs": [],
             "unassigned_inputs": list(plan.get("unassigned_inputs") or []),
             "notes": list(plan.get("notes") or [])}
    # Slice 3: each bus's senders once, grouped by (mode, level, marker),
    # in the order the busses are declared; nothing on the channel.
    groups: dict[str, dict] = {name: {} for name in plan.get("busses") or {}}
    for ch in plan["channels"]:
        c = _strip_nulls(copy.deepcopy(ch))
        source = c.pop("source")
        c = {"input": source["input"], **c}
        if source.get("stereo"):
            c["stereo"] = True          # the fixtures' pairs are one stated row each
        if c["name"] == source["input"]:
            del c["name"]
        del c["channel"]
        if c["bank"] == "ch":
            del c["bank"]
        if c["patch"].get("stated"):
            del c["patch"]
        elif c["patch"]["sockets"][0] > facts.input_socket_limit(c["patch"]["group"], "wing-compact"):
            # The compiler-era festival fixture counted LCL up to 30 on a
            # console with 24: a socket the count would never reach is
            # one the reply states, as it states any the conventions name.
            c["patch"] = {"group": c["patch"]["group"], "sockets": c["patch"]["sockets"]}
        else:
            c["patch"] = {"group": c["patch"]["group"]}
        c.get("provenance", {}).pop("patch", None)
        for send in c.pop("bus_sends", []):
            key = json.dumps({k: v for k, v in send.items() if k != "bus"}, sort_keys=True)
            groups.setdefault(send["bus"], {}).setdefault(key, {**{k: v for k, v in send.items() if k != "bus"}, "from": []})
            groups[send["bus"]][key]["from"].append(c.get("name") or c["input"])
        c.get("provenance", {}).pop("bus_sends", None)
        reply["channels"].append(c)
    for section in plan_schema.REPLY_ARRAY_SECTIONS:
        for name, entry in (plan.get(section) or {}).items():
            item = {"name": name, **_strip_nulls(copy.deepcopy(entry))}
            if section != "outputs":
                # A bus's or DCA's index is allocation's, never written; an
                # output's says which Main/Matrix it IS and may be stated.
                item.pop("index", None)
            if section == "busses" and groups.get(name):
                item["sends"] = list(groups[name].values())
            reply[section].append(item)
    return reply


# Since 2026-09-29 code builds every input-list row the reply leaves out,
# unless a quote from the conventions, the instructions or the row's notes
# says to leave it out. A test that builds only some of a list's rows says
# so with `_leave_out(...)`, quoting this line of its conventions.
LEAVE_OUT = "This test leaves the rest of the list off the desk."


def _leave_out(*names: str) -> list[dict]:
    return [{"input": n, "quote": LEAVE_OUT} for n in names]


def _build(reply: dict, csv: str = "name,category,type,phantom\nKick,drums,Mic,FALSE\n",
           findings: list | None = None) -> dict:
    return generate.generate_plan(
        f"conventions\n{LEAVE_OUT}\n", csv, provider=FakeProvider(response=json.dumps(reply)),
        console_model="wing-compact", findings=findings)


def _comparable(plan: dict) -> dict:
    """A plan with only what the model decides, in a form that compares:
    no meta, no allocation/repair notes, no indices, bus_sends by bus,
    `""` and null the same for an input list's blank model/type."""
    out = {k: copy.deepcopy(v) for k, v in plan.items()
           if k in ("channels", "dcas", "mute_groups", "busses", "outputs")}
    out["unassigned_inputs"] = list(plan.get("unassigned_inputs") or [])
    for ch in out["channels"]:
        ch.setdefault("color", None)   # optional in the format; the compiler never wrote it
        ch["bus_sends"] = sorted(ch["bus_sends"], key=lambda s: s["bus"])
        for send in ch["bus_sends"]:
            for marker in send.get("inferred") or []:
                marker.pop("by", None)
        # The intended round-trip differences: code writes the channel's
        # `provenance.bus_sends` from the busses' own citations (slice 3)
        # and `provenance.patch` from the rule it applied (slice 4).
        for key in ("bus_sends", "patch"):
            (ch.get("provenance") or {}).pop(key, None)
        for key in ("type", "model"):
            if ch["source"].get(key) == "":
                ch["source"][key] = None
    for section in plan_schema.REPLY_ARRAY_SECTIONS:
        for entry in out.get(section, {}).values():
            entry.pop("index", None)
            # An all-null bus/output fader is optional in the plan format:
            # the reply leaves it out, the compiler-era fixtures wrote it.
            if entry.get("fader") == {"fader_db": None, "muted": None}:
                del entry["fader"]
            for marker in entry.get("inferred") or []:
                marker.pop("by", None)
    return out


# --------------------------------------------------------------------------
# slice 2: the reply schema, no nulls, arrays
# --------------------------------------------------------------------------

def test_the_reply_schema_can_be_sent_to_anthropics_decoder():
    """An earlier change, and the point of the array shape: the plan's name-keyed
    maps could never be sent as `output_config.format`, so every hosted
    generator reply was decoded unconstrained (Haiku's `inferred` on an
    output, 2026-09-28). The reply can be."""
    assert schema_check.anthropic_schema(plan_schema.GENERATION_SCHEMA) is None
    projected = schema_check.anthropic_schema(plan_schema.REPLY_SCHEMA)
    assert projected is not None
    assert schema_check.unsupported_keywords(plan_schema.REPLY_SCHEMA) == set()
    # Closed everywhere: an open object cannot be sent, and provenance's
    # keys are named so it can be.
    text = json.dumps(projected)
    assert '"additionalProperties": true' not in text
    keys = projected["properties"]["channels"]["items"]["properties"]["provenance"]["properties"]
    assert set(keys) == set(plan_schema.PROVENANCE_KEYS)


def test_the_generator_is_constrained_to_the_reply_schema():
    provider = FakeProvider(response=json.dumps(_compact(_plans()["smallband"])))
    generate.generate_plan("c", _csv("smallband"), provider=provider, console_model="wing-compact")
    assert provider.schemas == [plan_schema.REPLY_SCHEMA]


@pytest.mark.parametrize("stem", sorted(_plans()))
def test_a_compact_reply_expands_to_the_plan_it_came_from(stem):
    plan = _plans()[stem]
    reply = _compact(plan)
    assert schema_check.validate(reply, plan_schema.REPLY_SCHEMA, path="reply") == []
    built = _build(reply, _csv(stem))
    assert _comparable(built) == _comparable(plan)


def test_the_reply_is_shorter_than_the_plan_it_expands_to():
    plan = _plans()["festival"]
    reply = json.dumps(_compact(plan), indent=None)
    today = json.dumps({k: plan[k] for k in ("channels", "dcas", "mute_groups", "busses", "outputs")},
                       indent=None)
    assert len(reply) < len(today)


def test_an_omitted_field_expands_exactly_as_null_does():
    """Rule 4: an omitted field makes the claim null makes. Two replies,
    one writing every null and one writing none, give one plan."""
    plan = _plans()["smallband"]
    nulls = {"hpf_hz": None, "preset": None, "hi_cut_hz": None, "tilt_db": None,
             "trim_db": None, "balance_db": None, "invert": None, "gain_db": None}
    explicit = _compact(plan)
    for ch in explicit["channels"]:
        ch["color"] = None
        ch["processing"] = {**nulls, **ch.get("processing", {})}
        ch["fader"] = {"fader_db": None, "muted": None, **ch.get("fader", {})}
    silent = _compact(plan)
    assert _comparable(_build(explicit, _csv("smallband"))) == \
        _comparable(_build(silent, _csv("smallband")))
    # ...and the plan on disk carries every leaf today's format has.
    built = _build(silent, _csv("smallband"))
    for ch in built["channels"]:
        assert set(ch["processing"]) >= set(nulls)
        assert set(ch["fader"]) == {"fader_db", "muted"}
        assert "color" in ch and "main_routes" in ch and "mute_group" in ch


# A smaller hosted model writes null for what it has nothing to say about
# (the maintainer's two Haiku 4.5 smallband builds, 2026-09-28, frozen here from
# `plan.json.partial`'s outputs section -- never read from examples/):
# `fader: null` on an output whose fader is an optional OBJECT, and a
# null under a key the format does not have at all (`destination` on an
# output; a top-level `aux`). Neither says anything, so neither is an
# error: a null optional reads as absent, a null unknown key is dropped.
# An unknown key with a VALUE still fails, as it always has.
NULLS_REPLY = FIXTURES / "haiku45_smallband_nulls.reply.json"


def test_a_null_optional_or_unknown_field_reads_as_absent():
    outputs = json.loads(NULLS_REPLY.read_text())["outputs"]
    assert outputs["Main 1"]["fader"] is None and "destination" in outputs["Main 1"]
    # As it arrived: three violations, on nothing but nulls.
    before = schema_check.validate(outputs, {"type": "object",
                                             "additionalProperties": plan_schema.OUTPUT_SCHEMA})
    assert len(before) == 3 and all("fader" in v or "destination" in v for v in before)

    reply = _compact(_plans()["smallband"])
    reply["outputs"] = [{"name": n, **o} for n, o in outputs.items()]
    reply["aux"] = None
    built = _build(reply, _csv("smallband"))
    assert set(built["outputs"]) == {"Main 1", "Matrix 1"}
    assert "fader" not in built["outputs"]["Main 1"]
    assert "destination" not in built["outputs"]["Main 1"]
    assert "aux" not in built
    # The same courtesy in the plan's own (older) format.
    full = {k: copy.deepcopy(_plans()["smallband"][k])
            for k in ("channels", "dcas", "mute_groups", "busses")}
    full.update(outputs=copy.deepcopy(outputs), unassigned_inputs=[], notes=[], aux=None)
    built = _build(full, _csv("smallband"))
    assert "fader" not in built["outputs"]["Main 1"] and "aux" not in built


def test_an_unknown_field_with_a_value_still_fails():
    reply = _compact(_plans()["smallband"])
    reply["outputs"][0]["destination"] = {"type": "main", "index": 1}
    with pytest.raises(generate.GenerationError, match="destination: not a field"):
        _build(reply, _csv("smallband"))
    reply = _compact(_plans()["smallband"])
    reply["aux"] = [{"name": "Aux 1"}]     # an empty [] says nothing, and is dropped
    with pytest.raises(generate.GenerationError, match="aux: not a field"):
        _build(reply, _csv("smallband"))


def test_a_rule_4b_field_left_out_is_refused_not_defaulted():
    """The four decided fields are never "not stated": a bus without a
    width, a send without a mode, a bus without a destination."""
    reply = _compact(_plans()["smallband"])
    del reply["busses"][0]["mono"]
    with pytest.raises(generate.GenerationError, match="mono"):
        _build(reply, _csv("smallband"))

    reply = _compact(_plans()["smallband"])
    del reply["busses"][0]["destination"]
    with pytest.raises(generate.GenerationError, match="destination"):
        _build(reply, _csv("smallband"))

    reply = _compact(_plans()["smallband"])
    del reply["busses"][0]["sends"][0]["mode"]
    with pytest.raises(generate.GenerationError, match="mode"):
        _build(reply, _csv("smallband"))


def test_a_send_level_left_out_is_unity_written_and_marked():
    """Not null: apply writes no level for null, and a fresh desk's -144
    would leave the send silent (the maintainer's festival build, 2026-09-29;
    `test_send_levels_and_reply_repair.py`)."""
    reply = _compact(_plans()["smallband"])
    group = reply["busses"][0]["sends"][0]
    group.pop("level_db", None)
    group.pop("inferred", None)
    built = _build(reply, _csv("smallband"))
    bus = reply["busses"][0]["name"]
    sends = [s for c in built["channels"] for s in c["bus_sends"] if s["bus"] == bus]
    assert sends and all(s["level_db"] == 0.0 for s in sends)
    assert all(any(m["field"] == "level_db" and m["by"] == "fallback" for m in s["inferred"])
               for s in sends)


# --------------------------------------------------------------------------
# slice 3: sends per bus
# --------------------------------------------------------------------------

def _two_channel_reply() -> dict:
    kick = {"input": "Kick", "patch": {"group": "LCL"}}
    vox = {"input": "Vox 1", "name": "Lead Vox", "patch": {"group": "LCL"}}
    return {"channels": [kick, vox], "dcas": [], "mute_groups": [],
            "busses": [{"name": "MON1", "destination": {"type": "dedicated_output", "label": "MON1",
                                                        "patch": {"group": "LCL", "sockets": [1]}},
                        "mono": True, "sends": []},
                       {"name": "Verb", "destination": {"type": "main", "index": 1},
                        "mono": False, "sends": []}],
            "outputs": [{"name": "Main", "kind": "main", "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": [], "notes": []}

TWO = "name,category,type,phantom\nKick,drums,Mic,FALSE\nVox 1,vocals,Mic,FALSE\n"


def _sends(plan: dict, name: str) -> list[dict]:
    return next(c for c in plan["channels"] if c["name"] == name)["bus_sends"]


def test_a_bus_lists_its_senders_once_and_every_channel_gets_the_send():
    reply = _two_channel_reply()
    reply["busses"][0]["sends"] = [{"from": ["*"], "mode": "pre", "level_db": -144.0,
                                    "provenance": "Busses: 'MON1 takes everything, pre'"}]
    reply["busses"][1]["sends"] = [{"from": ["Vox 1"], "mode": "post",
                                    "inferred": [{"field": "mode", "basis": "an FX send"}]}]
    findings: list = []
    plan = _build(reply, TWO, findings=findings)

    assert _sends(plan, "Kick") == [{"bus": "MON1", "mode": "pre", "level_db": -144.0}]
    assert _sends(plan, "Lead Vox") == [
        {"bus": "MON1", "mode": "pre", "level_db": -144.0},
        {"bus": "Verb", "mode": "post", "level_db": 0.0,
         "inferred": [{"field": "mode", "basis": "an FX send", "by": "model"},
                      {"field": "level_db", "by": "fallback",
                       "basis": inferred.send_level_fallback("Verb", "post")[1]}]}]
    # The bus keeps no `sends` in the plan, and the channel cites the
    # bus's own line.
    assert "sends" not in plan["busses"]["MON1"]
    vox = next(c for c in plan["channels"] if c["name"] == "Lead Vox")
    assert vox["provenance"]["bus_sends"] == "MON1: Busses: 'MON1 takes everything, pre'; Verb (post)"
    # ...and says so at INFO.
    info = [f for f in findings if f.code == "reply.sends-expanded"]
    assert len(info) == 1 and "MON1 <- 2 of 2 (every channel)" in info[0].message \
        and "Verb <- 1 of 2" in info[0].message


def test_a_from_naming_no_channel_is_refused():
    reply = _two_channel_reply()
    reply["busses"][1]["sends"] = [{"from": ["Snare"], "mode": "post"}]
    with pytest.raises(generate.GenerationError, match="'Snare', which is no channel"):
        _build(reply, TWO)


def test_a_later_group_replaces_an_earlier_send_into_the_same_bus():
    reply = _two_channel_reply()
    reply["busses"][0]["sends"] = [{"from": ["*"], "mode": "pre", "level_db": -144.0},
                                   {"from": ["Kick"], "mode": "pre", "level_db": -10.0}]
    plan = _build(reply, TWO)
    assert _sends(plan, "Kick") == [{"bus": "MON1", "mode": "pre", "level_db": -10.0}]
    assert _sends(plan, "Lead Vox") == [{"bus": "MON1", "mode": "pre", "level_db": -144.0}]


def test_a_channel_is_named_by_its_strip_name_or_its_input():
    reply = _two_channel_reply()
    reply["busses"][1]["sends"] = [{"from": ["Lead Vox"], "mode": "post"}]
    assert len(_sends(_build(reply, TWO), "Lead Vox")) == 1
    reply["busses"][1]["sends"] = [{"from": ["Vox 1"], "mode": "post"}]
    assert len(_sends(_build(reply, TWO), "Lead Vox")) == 1


def test_a_channel_no_bus_names_sends_nowhere():
    plan = _build(_two_channel_reply(), TWO)
    assert all(c["bus_sends"] == [] for c in plan["channels"])


def test_the_prompt_moves_sends_onto_the_bus():
    section = plan_schema.schema_section()
    assert "NOT on a channel" in section
    assert '"from": [names]' in section
    assert "bus_sends" not in plan_schema.EXAMPLE_REPLY_CHANNEL
    assert plan_schema.EXAMPLE_REPLY_BUS["sends"][0]["from"] == ["*"]
    assert "bus_sends" not in plan_schema.REPLY_CHANNEL_SCHEMA["properties"]


def test_a_name_written_twice_is_refused():
    reply = _compact(_plans()["smallband"])
    reply["busses"].append(dict(reply["busses"][0]))
    with pytest.raises(generate.GenerationError, match="written twice"):
        _build(reply, _csv("smallband"))


def test_the_full_format_still_builds_unchanged():
    """A reply in the plan's own shape -- a replay fixture, an
    unconstrained provider that ignored the prompt -- is not the compact
    form and is not touched beyond the nulls it may have left out."""
    plan = _plans()["smallband"]
    reply = {k: copy.deepcopy(plan[k])
             for k in ("channels", "dcas", "mute_groups", "busses", "outputs")}
    reply["unassigned_inputs"], reply["notes"] = [], []
    assert not reply_expand.is_array_form(reply)
    built = _build(reply, _csv("smallband"))
    assert _comparable(built) == _comparable(plan)


def test_the_change_compiler_still_asks_for_the_plan_format():
    """`patch`'s change sets keep the full format (change_compile.md)."""
    from atoo import patch
    assert "Every field below is REQUIRED on every channel" in patch.change_system("wing-compact")
    assert "Every field below is REQUIRED on every channel" not in \
        generate.generator_system("wing-compact")
    assert "leave out means what" in generate.generator_system("wing-compact")


def test_the_prompt_examples_are_unindented():
    section = plan_schema.schema_section()
    assert plan_schema.EXAMPLE_REPLY_CHANNEL_JSON in section
    assert "\n" not in plan_schema.EXAMPLE_REPLY_CHANNEL_JSON
    assert "NO indentation" in section


# --------------------------------------------------------------------------
# slice 4: code does the mechanical parts
# --------------------------------------------------------------------------

ROWS = ("patch,name,category,type,model,phantom,notes\n"
        ",Kick,drums,Mic,Beta 52,FALSE,\n"
        ",Snare,drums,Mic,SM57,FALSE,\n"
        "LCL 9,Bass,bass,DI,,FALSE,\n"
        ",Keys L,keys,Instrument,,FALSE,\n"
        ",Keys R,keys,Instrument,,FALSE,\n"
        "AES50-A 21,Playback,misc,Line,Stereo DI,FALSE,one row for the pair\n"
        ",A Very Long Vocalist Name,vocals,Mic,SM58,TRUE,\n")


def _reply(*channels, **top) -> dict:
    return {"channels": list(channels), "dcas": [], "mute_groups": [],
            "busses": [], "outputs": [{"name": "Main", "kind": "main",
                                       "patch": {"group": "LCL", "sockets": [7, 8]}}],
            "unassigned_inputs": [], "notes": [], **top}


def _ch(plan: dict, name: str) -> dict:
    return next(c for c in plan["channels"] if c["name"] == name)


def test_code_numbers_each_bank_in_the_order_written_and_says_so():
    findings: list = []
    rest = _leave_out("Keys L", "Keys R", "Playback", "A Very Long Vocalist Name")
    plan = _build(_reply({"input": "Snare", "patch": {"group": "LCL"}},
                         {"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Bass", "bank": "aux"}, unassigned_inputs=rest), ROWS, findings)
    assert [(c["bank"], c["channel"], c["name"]) for c in plan["channels"]] == \
        [("ch", 1, "Snare"), ("ch", 2, "Kick"), ("aux", 1, "Bass")]
    assert _ch(plan, "Kick")["provenance"]["channel"] == \
        "numbered ch 2 in the order the reply listed it"
    info = next(f for f in findings if f.code == "reply.channels-numbered")
    assert "ch 1-2; aux 1" in info.message
    # A number written starts a run there; the next channel follows it.
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Snare", "channel": 17, "patch": {"group": "LCL"}},
                         {"input": "Bass"}, unassigned_inputs=rest), ROWS)
    assert [c["channel"] for c in plan["channels"]] == [1, 17, 18]


def test_the_input_list_supplies_the_source_facts_and_the_stated_patch():
    findings: list = []
    plan = _build(_reply({"input": "Bass"}, {"input": "Kick", "patch": {"group": "LCL"}}),
                  ROWS, findings)
    bass = _ch(plan, "Bass")
    assert bass["source"] == {"input": "Bass", "type": "DI", "model": None,
                              "stereo": False, "phantom": False}
    assert bass["patch"] == {"group": "LCL", "sockets": [9], "stated": True}
    assert bass["provenance"]["patch"] == "Input list patch column: 'LCL 9'"
    assert _ch(plan, "Kick")["source"]["model"] == "Beta 52"
    # A stated socket is never counted out to another row (FR-1.10).
    assert _ch(plan, "Kick")["patch"] == {"group": "LCL", "sockets": [1], "stated": False}


def test_a_stated_socket_the_reply_moved_is_put_back_with_a_note():
    plan = _build(_reply({"input": "Bass", "patch": {"group": "LCL", "sockets": [3]}}), ROWS)
    assert _ch(plan, "Bass")["patch"]["sockets"] == [9]
    assert any("the list wins (rule 3)" in n["text"] for n in plan["notes"] if n["source"] == "repair")


def test_the_next_free_socket_is_counted_out_in_channel_order_and_announced():
    findings: list = []
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Snare", "patch": {"group": "LCL"}},
                         {"input": "Bass"},
                         {"input": "A Very Long Vocalist Name", "patch": {"group": "A"}}),
                  ROWS, findings)
    assert _ch(plan, "Kick")["patch"] == {"group": "LCL", "sockets": [1], "stated": False}
    assert _ch(plan, "Snare")["patch"] == {"group": "LCL", "sockets": [2], "stated": False}
    vox = _ch(plan, "A Very Long Voca")
    assert vox["patch"] == {"group": "A", "sockets": [1], "stated": False}
    assert vox["provenance"]["patch"] == \
        "next free A socket in channel order (AES50-A 1): the reply chose the group, code the number"
    chosen = {f.message.split(":")[0]: f.message for f in findings if f.code == "reply.sockets-chosen"}
    assert set(chosen) == {"LCL", "A"}
    assert "Kick LCL 1, Snare LCL 2" in chosen["LCL"]
    assert "A Very Long Voca AES50-A 1" in chosen["A"]
    # The long name was cut to what the console shows, and said.
    assert any(f.code == "reply.name-cut" for f in findings)


def test_a_reply_that_names_no_group_gets_lcl_and_says_so():
    findings: list = []
    plan = _build(_reply({"input": "Kick"}), ROWS, findings)
    assert _ch(plan, "Kick")["patch"] == {"group": "LCL", "sockets": [1], "stated": False}
    assert any(f.code == "reply.socket-group-assumed" for f in findings)


def test_a_stereo_pair_takes_two_rows_and_an_odd_socket_skipping_one_to_align():
    findings: list = []
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Keys L", "pair": "Keys R", "name": "Keys",
                          "patch": {"group": "LCL"},
                          "inferred": [{"field": "stereo", "basis": "named L and R"}]}),
                  ROWS, findings)
    keys = _ch(plan, "Keys")
    assert keys["source"]["stereo"] is True and keys["source"]["input"] == "Keys L"
    # LCL 1 is Kick's; LCL 2 cannot start a pair, so 3-4.
    assert keys["patch"] == {"group": "LCL", "sockets": [3, 4], "stated": False}
    skipped = [f for f in findings if f.code == "reply.socket-skipped"]
    assert len(skipped) == 1 and "LCL 2 left empty" in skipped[0].message \
        and "LCL 3-4" in skipped[0].message
    assert keys["inferred"] == [{"field": "stereo", "basis": "named L and R", "by": "model"}]
    # verify still reads an UNSTATED pair's second row as dropped -- it
    # matches a stereo channel's second row by the input list's own
    # stated socket only -- exactly as it did for a full-format reply.
    # The plan on disk has no field for the second row's name, and
    # this change does not add one.


def test_one_stated_row_standing_for_a_pair_takes_n_and_n_plus_one():
    plan = _build(_reply({"input": "Playback", "stereo": True}), ROWS)
    pb = _ch(plan, "Playback")
    assert pb["source"]["stereo"] is True
    assert pb["patch"] == {"group": "A", "sockets": [21, 22], "stated": True}


def test_a_one_row_channel_is_mono_by_construction():
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}}), ROWS)
    assert _ch(plan, "Kick")["source"]["stereo"] is False
    assert "inferred" not in _ch(plan, "Kick")


def test_a_group_that_runs_out_is_a_hard_error_naming_the_choice():
    """The reply chose the group, so it must choose where the overflow
    goes (CLAUDE.md: a socket that does not exist is an error of
    patching, not of judgement)."""
    rows = "name,category,type,phantom\n" + "".join(f"In {i},misc,Line,FALSE\n" for i in range(1, 4))
    reply = _reply(*({"input": f"In {i}", "patch": {"group": "AES"}} for i in range(1, 4)))
    with pytest.raises(generate.GenerationError) as caught:
        _build(reply, rows)
    text = str(caught.value)
    assert "channels[In 3]: no room in AES" in text and "AES 1-2" in text
    assert "must choose where the overflow goes" in text


def test_the_category_map_colours_each_channel_by_its_row_and_says_so():
    findings: list = []
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}},
                         {"input": "Snare", "patch": {"group": "LCL"}, "color": "White"},
                         {"input": "Bass", "color": None},
                         {"input": "Keys L", "patch": {"group": "LCL"}},
                         category_colors=[{"category": "Drums", "color": "Red"},
                                          {"category": "bass", "color": "Blue"}]),
                  ROWS, findings)
    assert _ch(plan, "Kick")["color"] == "Red"
    assert _ch(plan, "Kick")["provenance"]["color"] == "category map: drums -> Red"
    assert _ch(plan, "Snare")["color"] == "White"          # the channel's own wins
    # C3 (review 2026-09-28, R7): `color: null` means "not stated", so the
    # category map applies, and the INFO says the null was read that way.
    assert _ch(plan, "Bass")["color"] == "Blue"
    assert _ch(plan, "Bass")["provenance"]["color"] == "category map: bass -> Blue"
    assert _ch(plan, "Keys L")["color"] is None            # no entry for keys
    assert "category_colors" not in plan                   # not a plan field
    info = next(f for f in findings if f.code == "reply.colours-applied")
    assert "drums -> Red (1: Kick)" in info.message
    assert "stated for the channel alone: Snare White" in info.message
    assert "bass -> Blue (1: Bass)" in info.message
    assert ("color: null read as not stated, so the category map applies: Bass"
            in info.message)


def test_an_input_that_is_not_on_the_list_is_refused():
    with pytest.raises(generate.GenerationError, match="'Tambourine' is not a row"):
        _build(_reply({"input": "Tambourine"}), ROWS)
    with pytest.raises(generate.GenerationError, match="pair 'Keys X' is not a row"):
        _build(_reply({"input": "Keys L", "pair": "Keys X"}), ROWS)


def test_a_compact_reply_needs_a_readable_input_list():
    with pytest.raises(generate.GenerationError, match="input list could not be read"):
        _build(_reply({"input": "Kick"}), "not,a,list\n")


def test_the_expanded_plan_is_todays_plan_shape():
    """Every key today's channel has, in today's order, so a plan built
    from the reply reads like one built from a full reply."""
    plan = _build(_reply({"input": "Kick", "patch": {"group": "LCL"}}), ROWS)
    assert list(_ch(plan, "Kick")) == ["channel", "bank", "name", "color", "source", "patch",
                                        "processing", "fader", "dca", "mute_group", "bus_sends",
                                        "main_routes", "provenance"]
    assert schema_check.validate(plan, plan_schema.PLAN_SCHEMA) == []


def test_the_live_outline_names_a_reply_channel_by_its_input():
    """Step 04's live view: `Channels · 14 · Horns` still reads when the
    reply writes no `name` (stream_outline)."""
    from atoo.stream_outline import outline_of
    text = json.dumps({"channels": [
        {"input": "Kick", "dca": ["Drums"]},
        {"input": "Vox 1", "name": "Lead Vox", "dca": ["Vocals"]},
    ]})
    outline = outline_of(text)
    part = outline["sections"][0]
    assert part["names"] == ["Kick", "Lead Vox"]
    cut = text.index('"dca"', text.index("Vox 1"))
    item = outline_of(text[:cut + 6])["item"]
    assert item["name"] == "Lead Vox" and item["field"] == "dca"
    # A partial with only the input so far is named by it.
    item = outline_of(text[:text.index('"name"')])["item"]
    assert item["name"] == "Vox 1"
