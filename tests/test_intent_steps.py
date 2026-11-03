"""`atoo build --intent --intent-steps` (`atoo/intent_steps.py`), offline: a scripted provider
answers each of the three scoped calls, code compiles the joined intent after each step, and the
build's usual steps run on the plan. The show is made up here for these tests (a string band
no corpus show resembles); nothing reads `examples/` or `evals/`."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field

import pytest

from atoo import generate, intent_steps, schema_check
from atoo.ai_provider import OllamaProvider

CSV = """patch,name,category,type,model,phantom,notes
,Upright,bass,DI,J48,TRUE,
,Mando,strings,Mic,KM184,TRUE,
,Dobro,strings,Mic,KM184,TRUE,
,Fiddle L,strings,Mic,DPA 4099,TRUE,
,Fiddle R,strings,Mic,DPA 4099,TRUE,
,Hollis Vox,vocals,Mic,SM58,FALSE,
,Wren Vox,vocals,Mic,SM58,FALSE,
"""
CONVENTIONS = """# House conventions

## Categories
- Strings: green, high-pass 100 Hz.
- Vocals: red.

## Fiddle
- The two fiddle mics are one stereo Fiddle.

## Buses
- Strings Wedge: the strings and Hollis Vox, pre-fader, on LCL 5.
- Room Verb: the vocals, post-fader.

## DCAs
- Strings: the strings.
- Vox: the vocals.

## Mute groups
- Verb Mute: the vocals.

## Outputs
- Main: Local outputs 1-2.
"""

STEP1 = {"name": "Categories", "notes": [], "categories": [
    {"name": "Strings", "aliases": ["strings"], "color": "Green", "hpf_hz": 100},
    {"name": "Vocals", "aliases": ["vocals"], "color": "Red"}],
    "ops": [{"op": "add_channel", "name": "Fiddle", "rows": ["Fiddle L", "Fiddle R"], "stereo": True}]}
STEP2 = {"name": "Buses", "notes": [], "ops": [
    {"op": "add_bus", "name": "Strings Wedge", "mode": "pre", "stereo": False,
     "members": {"categories": ["strings"], "channels": ["Hollis Vox"]},
     "to": {"output": {"group": "LCL", "first": 5, "count": 1}}},
    {"op": "add_bus", "name": "Room Verb", "mode": "post", "members": {"categories": ["vocals"]}}]}
STEP3 = {"name": "Groups and outputs", "notes": [], "ops": [
    {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "LCL", "first": 1, "count": 2}},
    {"op": "add_group", "object": "dca", "name": "Strings", "members": {"categories": ["strings"]}},
    {"op": "add_group", "object": "dca", "name": "Vox", "members": {"categories": ["vocals"]}},
    {"op": "add_group", "object": "mute_group", "name": "Verb Mute", "members": {"categories": ["vocals"]}}]}


@dataclass
class Scripted:
    """Answers by the call's label (`intent-categories`, `intent-buses-repair`, ...), and records
    every call: what a test needs to see the prefix stay the same and the repairs happen."""
    replies: dict
    calls: list = field(default_factory=list)
    build_log: dict = field(default_factory=dict)

    def complete(self, *, system, user, response_schema=None, label=""):
        self.calls.append({"system": system, "user": user, "schema": response_schema, "label": label})
        reply = self.replies[label]
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def build(replies, conventions=CONVENTIONS, **kw):
    infos: list[str] = []
    trace: dict = {}
    provider = Scripted(replies)
    plan = intent_steps.generate_plan(conventions, CSV, provider=provider, console_model="wing-compact",
                                      conventions_name="conventions.md", infos=infos, trace=trace, **kw)
    return plan, provider, infos, trace


GOOD = {"intent-categories": STEP1, "intent-buses": STEP2, "intent-outputs": STEP3}


def channel(plan, name):
    return next(c for c in plan["channels"] if c["name"] == name)


def test_three_calls_build_the_whole_show():
    plan, provider, infos, trace = build(GOOD)
    assert [c["label"] for c in provider.calls] == ["intent-categories", "intent-buses", "intent-outputs"]
    assert [c["name"] for c in plan["channels"]] == ["Upright", "Mando", "Dobro", "Fiddle", "Hollis Vox", "Wren Vox"]
    assert channel(plan, "Fiddle")["source"]["stereo"] is True
    assert channel(plan, "Mando")["processing"]["hpf_hz"] == 100
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}
    assert {s["bus"] for s in channel(plan, "Hollis Vox")["bus_sends"]} == {"Strings Wedge", "Room Verb"}
    assert {s["bus"] for s in channel(plan, "Wren Vox")["bus_sends"]} == {"Room Verb"}
    assert set(plan["dcas"]) == {"Strings", "Vox"} and set(plan["mute_groups"]) == {"Verb Mute"}
    assert channel(plan, "Dobro")["dca"] == ["Strings"]
    assert plan["outputs"]["Main"]["patch"]["sockets"] == [1, 2]
    assert [c["attempt"] for c in trace["steps"]] == ["first try"] * 3
    assert all(c["accepted"] for c in trace["steps"])


def test_every_call_starts_with_the_same_prefix_and_differs_only_after_it():
    _, provider, _, _ = build(GOOD)
    systems = {c["system"] for c in provider.calls}
    groups = {c["user"].groups for c in provider.calls}
    assert len(systems) == 1 and len(groups) == 1         # byte-identical up to the step's own text
    (static, show), = groups
    assert "# Domain knowledge" in static and "Strings Wedge" not in static
    assert "Strings Wedge" in show and "Fiddle L" in show      # the whole conventions and the input list
    tails = [c["user"].tail for c in provider.calls]
    assert len(set(tails)) == 3
    assert "Step 1 of 3" in tails[0] and "Step 2 of 3" in tails[1] and "Step 3 of 3" in tails[2]
    assert all(str(c["user"]).startswith(static + show) for c in provider.calls)


def test_later_steps_are_told_the_names_the_earlier_steps_built():
    _, provider, _, _ = build(GOOD)
    buses, outputs = provider.calls[1]["user"].tail, provider.calls[2]["user"].tail
    assert "Fiddle, strings, stereo" in buses and "Hollis Vox, vocals" in buses
    assert "Categories a member may name:" in buses and "Strings" in buses
    assert "Buses (written in step 2): Strings Wedge, Room Verb" in outputs
    assert "Nothing yet" in provider.calls[0]["user"].tail


def test_each_step_is_sent_a_schema_holding_only_its_own_ops():
    _, provider, _, _ = build(GOOD)
    tags = [{b["properties"]["op"]["enum"][0] for b in c["schema"]["properties"]["ops"]["items"]["oneOf"]}
            for c in provider.calls]
    assert tags == [{"add_channel", "drop", "order"}, {"add_bus"}, {"add_output", "add_group"}]
    first = provider.calls[0]["schema"]
    assert set(first["properties"]["categories"]["items"]["properties"]) & {"dca", "mute_group"} == set()
    channel_op = next(b for b in first["properties"]["ops"]["items"]["oneOf"]
                      if b["properties"]["op"]["enum"] == ["add_channel"])
    assert not set(channel_op["properties"]) & {"dca", "mute_group", "sends"}
    assert "categories" not in provider.calls[1]["schema"]["properties"]


def test_claude_is_sent_no_step_schema_so_the_request_only_differs_after_the_cache_breakpoint(monkeypatch):
    """A changed output format misses Claude's cache, and the buses step's schema is one its
    decoder would take while the other two are not: so none is sent, and every reply is still
    checked against its step's schema here."""
    from atoo.ai_provider import ClaudeProvider
    wires = [schema_check.anthropic_format(intent_steps.intent_schema.without_bounds(
        intent_steps.step_schema("wing-compact", s))) for s in intent_steps.STEPS]
    assert any(w is not None for w in wires) and any(w is None for w in wires)   # why it matters
    sent = []
    replies = iter([STEP1, STEP2, STEP3])

    def fake_complete(self, *, system, user, response_schema=None, label=""):
        sent.append((response_schema, user))
        return json.dumps(next(replies))

    monkeypatch.setattr(ClaudeProvider, "complete", fake_complete)
    plan = intent_steps.generate_plan(CONVENTIONS, CSV, provider=ClaudeProvider(api_key="k", show_progress=False),
                                      console_model="wing-compact")
    assert [s for s, _ in sent] == [None, None, None]
    assert len({u.groups for _, u in sent}) == 1
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}


def test_an_unusable_step_reply_is_repaired_over_the_same_cached_prefix():
    plan, provider, infos, trace = build({**GOOD, "intent-buses": "not json", "intent-buses-repair": STEP2})
    assert [c["label"] for c in provider.calls] == ["intent-categories", "intent-buses", "intent-buses-repair",
                                                    "intent-outputs"]
    repair = provider.calls[2]["user"]
    assert repair.groups == provider.calls[0]["user"].groups           # the repair reads the prefix from cache too
    assert "Step 2 of 3" in repair.tail and "Step 1 of 3" not in repair.tail and "not json" in repair.tail
    assert [(c["step"], c["attempt"], c["accepted"]) for c in trace["steps"]] == [
        ("categories", "first try", True), ("buses", "first try", False), ("buses", "repair", True),
        ("outputs", "first try", True)]
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}
    assert any("intent step 2 (buses and their sends): the first reply was not accepted" in i for i in infos)


def test_a_member_category_no_channel_carries_keeps_the_bus_as_the_single_call_does():
    """A category word that matches no channel is a judgement miss, not an impossibility: in both
    arms the bus is made, the miss is said at INFO, and no repair round is spent on it."""
    from atoo import intent_build
    from atoo.ai_provider import FakeProvider
    wedge = {**STEP2["ops"][0], "members": {"categories": ["fiddles"]}}
    bad_step2 = {**STEP2, "ops": [wedge, STEP2["ops"][1]]}
    steps_plan, provider, steps_infos, trace = build({**GOOD, "intent-buses": bad_step2})
    assert [c["label"] for c in provider.calls] == ["intent-categories", "intent-buses", "intent-outputs"]
    single = {"name": "Build", "notes": [], "categories": STEP1["categories"],
              "ops": [*STEP1["ops"], wedge, STEP2["ops"][1], *STEP3["ops"]]}
    single_infos: list[str] = []
    single_plan = intent_build.generate_plan(CONVENTIONS, CSV, provider=FakeProvider(response=json.dumps(single)),
                                             console_model="wing-compact", conventions_name="conventions.md",
                                             infos=single_infos)
    for plan in (steps_plan, single_plan):
        assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}
        assert not any(s["bus"] == "Strings Wedge" for c in plan["channels"] for s in c["bus_sends"])
    sends = lambda plan: {c["name"]: sorted(s["bus"] for s in c["bus_sends"]) for c in plan["channels"]}  # noqa: E731
    assert sends(steps_plan) == sends(single_plan)
    said = "bus 'Strings Wedge' named members, and no channel matched them: it has none"
    assert any(said in i for i in steps_infos) and any(said in i for i in single_infos)


def test_a_member_channel_that_is_not_built_is_refused_naming_the_steps_own_op():
    bad = {**STEP2, "ops": [STEP2["ops"][1], {**STEP2["ops"][0], "members": {"channels": ["Hollis"]}}]}
    _, provider, _, trace = build({**GOOD, "intent-buses": bad, "intent-buses-repair": STEP2})
    problem = trace["steps"][1]["problem"]
    assert "ops[1] (bus 'Strings Wedge'): its member 'hollis' is not a channel" in problem
    assert "ops[1] (bus 'Strings Wedge')" in provider.calls[2]["user"].tail


def test_an_op_of_another_step_is_not_accepted():
    bad = {**STEP1, "ops": [*STEP1["ops"], STEP2["ops"][1]]}
    _, provider, _, trace = build({**GOOD, "intent-categories": bad, "intent-categories-repair": STEP1})
    assert trace["steps"][0]["accepted"] is False and "add_bus" in trace["steps"][0]["problem"]
    assert trace["steps"][1]["step"] == "categories" and trace["steps"][1]["accepted"] is True


def test_a_step_still_unusable_after_its_repair_adds_nothing_and_the_others_still_build():
    plan, provider, infos, trace = build({**GOOD, "intent-buses": "not json", "intent-buses-repair": "still not"})
    assert not plan.get("busses")                          # a content miss: code writes no bus for the model
    assert set(plan["dcas"]) == {"Strings", "Vox"}         # step 3 still ran, on what steps 1 built
    assert any("intent step 2 (buses and their sends) gave no usable reply after its repair round" in i
               for i in infos)
    assert [c["accepted"] for c in trace["steps"]] == [True, False, False, True]


def test_an_output_socket_only_the_model_chose_that_cannot_exist_takes_the_nearest_free_one():
    """"Delay" is not in the conventions, so LCL 40 (the desk has 8) is the model's slip: the nearest
    free local output stands, at INFO, and the show is built."""
    bad = {**STEP3, "ops": [{**STEP3["ops"][0], "patch": {"group": "LCL", "first": 1, "count": 2}},
                            {"op": "add_output", "object": "matrix", "name": "Delay",
                             "patch": {"group": "LCL", "first": 40}}]}
    plan, _, infos, _ = build({**GOOD, "intent-outputs": bad, "intent-outputs-repair": bad})
    matrix = next(o for o in plan["outputs"].values() if o["kind"] == "matrix")   # named by code: not a word of the texts
    assert matrix["patch"]["sockets"] == [8]
    assert any("LCL 40" in line and "nearest free" in line for line in infos)


def test_a_socket_the_conventions_name_that_cannot_exist_costs_that_output_not_the_show():
    """The engineer's own socket is never re-chosen: the output is refused, named, and left out;
    the rest of the show is built."""
    conventions = CONVENTIONS.replace("- Main: Local outputs 1-2.", "- Main: Local outputs 1-2.\n- Delay: Local outputs 40.")
    bad = {**STEP3, "ops": [*STEP3["ops"], {"op": "add_output", "object": "matrix", "name": "Delay",
                                            "patch": {"group": "LCL", "first": 40}}]}
    plan, _, infos, _ = build({**GOOD, "intent-outputs": bad, "intent-outputs-repair": bad}, conventions=conventions)
    assert "Delay" not in plan["outputs"] and "Main" in plan["outputs"]
    assert any(line.startswith("not built") and "LCL 40" in line for line in infos)


# -- the single call's rules, per step: completeness, Main, row names -----------------------------

def test_a_step_that_leaves_out_a_bus_its_section_asks_for_is_asked_for_that_only_and_the_answer_is_added():
    only_wedge = {**STEP2, "ops": [STEP2["ops"][0]]}
    verb_and_a_repeat = {"name": "More", "notes": [], "ops": [STEP2["ops"][1], STEP2["ops"][0]]}
    plan, provider, infos, trace = build({**GOOD, "intent-buses": only_wedge, "intent-buses-repair": verb_and_a_repeat})
    repair = provider.calls[2]
    assert repair["label"] == "intent-buses-repair" and repair["user"].groups == provider.calls[0]["user"].groups
    asked = repair["user"].tail.split("It was accepted, but")[1]
    assert asked.startswith(" the conventions ask for objects the intent does not make: the bus 'Room Verb'")
    assert "'Strings Wedge'" not in asked
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}                 # added; the repeat dropped
    assert [c["attempt"] for c in trace["steps"] if c["step"] == "buses"] == ["first try", "repair"]
    assert any("intent step 2 (buses and their sends): the model's first reply left something out" in i
               for i in infos)


def test_what_is_still_left_out_after_the_repair_is_said_and_not_made_by_code():
    only_wedge = {**STEP2, "ops": [STEP2["ops"][0]]}
    plan, _, infos, _ = build({**GOOD, "intent-buses": only_wedge,
                               "intent-buses-repair": {"name": "x", "ops": [], "notes": []}})
    assert set(plan["busses"]) == {"Strings Wedge"}
    assert any(i.startswith("still left out after asking once more, and not made by code: ") and "Room Verb" in i
               for i in infos)


def test_main_left_unpatched_by_step_3_is_patched_from_the_conventions_by_code_and_said():
    no_patch = {**STEP3, "ops": [{"op": "add_output", "object": "main", "name": "Main"}, *STEP3["ops"][1:]]}
    plan, _, infos, _ = build({**GOOD, "intent-outputs": no_patch})
    assert plan["outputs"]["Main"]["patch"]["sockets"] == [1, 2]
    assert any("Main patched to LCL 1-2, filled by code" in i for i in infos)


def test_a_near_spelling_of_a_row_in_step_1_is_read_as_the_row():
    near = {**STEP1, "ops": [{"op": "add_channel", "name": "Fiddle", "rows": ["Fiddles L", "Fiddles R"],
                              "stereo": True}]}
    plan, _, infos, _ = build({**GOOD, "intent-categories": near})
    assert channel(plan, "Fiddle")["source"]["stereo"] is True
    assert any("which is the input list's 'Fiddle L'" in i for i in infos)


# -- the provider: one context, kept loaded ------------------------------------------------------

def test_ollama_gets_one_context_size_and_keep_alive_for_every_call(monkeypatch):
    sent = []

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/api/show"):
            return io.BytesIO(json.dumps({"capabilities": ["completion"]}).encode())
        body = json.loads(req.data)
        sent.append(body)
        label_reply = [STEP1, STEP2, STEP3][len(sent) - 1]
        # As Ollama v0.33.3+ answers: the whole prompt every time, and what the cache held.
        line = {"message": {"content": json.dumps(label_reply)}, "done": True,
                "prompt_eval_count": 9000, "prompt_eval_cached_count": 0 if len(sent) == 1 else 8700,
                "prompt_eval_duration": 40_000_000_000 if len(sent) == 1 else 1_500_000_000, "eval_count": 120}
        return io.BytesIO((json.dumps(line) + "\n").encode())

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(model="m", show_progress=False)
    trace: dict = {}
    intent_steps.generate_plan(CONVENTIONS, CSV, provider=provider, console_model="wing-compact",
                               trace=trace)
    assert len(sent) == 3
    # The shared prefix is its own user turn and a fixed assistant turn, the same in every step;
    # only the last turn, the step's own text, differs.
    assert [[m["role"] for m in b["messages"]] for b in sent] == [["system", "user", "assistant", "user"]] * 3
    assert len({json.dumps(b["messages"][:3]) for b in sent}) == 1
    assert len({b["messages"][3]["content"] for b in sent}) == 3
    assert all(b["messages"][3]["content"].startswith("# Step ") for b in sent)
    assert len({b["options"]["num_ctx"] for b in sent}) == 1
    assert {b["keep_alive"] for b in sent} == {intent_steps.KEEP_ALIVE}
    assert all(b["options"]["temperature"] == 0 for b in sent)
    assert provider.num_ctx is None and provider.keep_alive is None      # the caller's is not changed
    assert trace["settings"]["num_ctx"] == sent[0]["options"]["num_ctx"]
    assert trace["settings"]["keep_alive"] == intent_steps.KEEP_ALIVE
    # What the cache held, and how long the prompt took to read, per call.
    assert [(c["input"], c["cache_read"], c["prompt_eval_ms"]) for c in trace["steps"]] == [
        (9000, None, 40000.0), (9000, 8700, 1500.0), (9000, 8700, 1500.0)]


def test_a_context_size_the_engineer_set_is_kept():
    worker = intent_steps.for_steps(OllamaProvider(model="m", num_ctx=24576), "s", ("a", "b"), CSV)
    assert worker.num_ctx == 24576 and worker.keep_alive == intent_steps.KEEP_ALIVE


def test_the_context_is_sized_for_the_longest_call():
    system = intent_steps.system_prompt("wing-compact")
    groups = intent_steps.prefix_groups(conventions=CONVENTIONS, conventions_name="c", instructions=None,
                                        instructions_name=None, input_csv=CSV, input_name="i", presets=None)
    worker = intent_steps.for_steps(OllamaProvider(model="m"), system, groups, CSV)
    longest = max(len(system) + len("".join(groups)) + len(intent_steps.step_tail(s, "x" * 2 * len(CSV)))
                  for s in intent_steps.STEPS)
    assert worker.num_ctx * 3.0 > longest + intent_steps.intent.REPLY_TOKENS * 3.0


def test_ollama_sends_keep_alive_only_when_set(monkeypatch):
    bodies = []

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/api/show"):
            return io.BytesIO(b"{}")
        bodies.append(json.loads(req.data))
        return io.BytesIO(json.dumps({"message": {"content": "ok"}, "done": True}).encode() + b"\n")

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    OllamaProvider(model="m", show_progress=False).complete(system="s", user="u")
    OllamaProvider(model="m", show_progress=False, keep_alive="30m").complete(system="s", user="u")
    assert "keep_alive" not in bodies[0] and bodies[1]["keep_alive"] == "30m"


# -- the command ---------------------------------------------------------------------------------

def test_atoo_build_intent_steps_writes_a_plan_and_logs_every_call(tmp_path, monkeypatch, capsys):
    from atoo.cli import main
    (tmp_path / "input.csv").write_text(CSV)
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    provider = Scripted(GOOD)
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    rc = main(["build", "--console-model", "wing-compact", "--intent", "--intent-steps",
               "--input", str(tmp_path / "input.csv"), "--conventions", str(tmp_path / "conventions.md"),
               "--out", str(tmp_path / "plan.json")])
    err = capsys.readouterr().err
    assert rc == 0, err
    assert "intent step 2/3 (buses), first try" in err
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["meta"]["verify_findings"]["errors"] == []
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}
    log = json.loads((tmp_path / plan["meta"]["build_log_file"]).read_text())
    assert [c["step"] for c in log["intent_steps"]["steps"]] == ["categories", "buses", "outputs"]
    assert len(log["intent_replies"]) == 3


def test_intent_steps_alone_builds_through_the_intent(tmp_path, monkeypatch, capsys):
    from atoo.cli import main
    (tmp_path / "input.csv").write_text(CSV)
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    provider = Scripted(GOOD)
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    rc = main(["build", "--console-model", "wing-compact", "--intent-steps",
               "--input", str(tmp_path / "input.csv"), "--conventions", str(tmp_path / "conventions.md"),
               "--out", str(tmp_path / "plan.json")])
    assert rc == 0, capsys.readouterr().err
    assert [c["label"] for c in provider.calls][:3] == ["intent-categories", "intent-buses", "intent-outputs"]


def test_atoo_ai_keep_alive_sets_it_for_any_ollama_call_and_the_steps_keep_it():
    from atoo.ai_provider import provider_from_env
    provider = provider_from_env({"ATOO_AI_PROVIDER": "ollama", "ATOO_AI_KEEP_ALIVE": "1h"})
    assert provider.keep_alive == "1h"
    assert intent_steps.for_steps(provider, "s", ("a", "b"), CSV).keep_alive == "1h"
    assert provider_from_env({"ATOO_AI_PROVIDER": "ollama"}).keep_alive is None


def test_a_bus_output_that_cannot_exist_takes_the_socket_the_conventions_state():
    slip = {**STEP2, "ops": [{**STEP2["ops"][0], "to": {"output": {"group": "LCL", "first": 50, "count": 1}}},
                             STEP2["ops"][1]]}
    plan, _, infos, _ = build({**GOOD, "intent-buses": slip})
    assert plan["busses"]["Strings Wedge"]["destination"]["patch"]["sockets"] == [5]
    assert any("'Strings Wedge': the reply wrote LCL 50, which does not exist" in i for i in infos)


# -- reading Ollama's prompt cache ---------------------------------------------------------------

def test_ollamas_usage_keeps_the_whole_prompt_as_input_and_says_what_the_cache_held():
    """`prompt_eval_count` is the whole prompt, cached or not; `prompt_eval_cached_count` (Ollama
    v0.33.3+) is the cache's share, kept as a cache read the way Claude's is."""
    from atoo.ai_provider import ollama_usage
    from atoo.progress import input_total
    hit = ollama_usage({"prompt_eval_count": 9000, "prompt_eval_cached_count": 8700,
                        "prompt_eval_duration": 1_500_000_000, "eval_count": 120})
    assert hit == {"input_tokens": 300, "cache_read_input_tokens": 8700, "output_tokens": 120,
                   "prompt_eval_ms": 1500.0}
    assert input_total(hit) == 9000
    older = ollama_usage({"prompt_eval_count": 9000, "eval_count": 120, "prompt_eval_duration": 40_000_000_000})
    assert older == {"input_tokens": 9000, "output_tokens": 120, "prompt_eval_ms": 40000.0}
    assert ollama_usage({"prompt_eval_count": 9000, "prompt_eval_cached_count": 0}) == {"input_tokens": 9000}


def test_the_ollama_usage_line_shows_the_cache_and_the_prompt_read_time_and_build_eval_reads_them(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/api/show"):
            return io.BytesIO(b"{}")
        line = {"message": {"content": "ok"}, "done": True, "prompt_eval_count": 9000,
                "prompt_eval_cached_count": 8700, "prompt_eval_duration": 1_500_000_000, "eval_count": 120}
        return io.BytesIO((json.dumps(line) + "\n").encode())

    monkeypatch.setattr("atoo.ai_provider.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(model="m")
    provider.complete(system="s", user="u", label="intent-buses")
    err = capsys.readouterr().err
    assert "m (intent-buses): 9,000 in (300 uncached, 0 cache write, 8,700 cache read), 120 out" in err
    assert ", prompt read in 1.5 s -- $0.00" in err
    usage = provider.build_log["intent-buses"]["usage"]
    assert (usage["input"], usage["cache_read"], usage["prompt_eval_ms"]) == (9000, 8700, 1500.0)
    live = Path(__file__).resolve().parents[1] / "evals" / "live"
    if not (live / "build_eval.py").exists():
        pytest.skip("evals/live is private; not in the public tree")
    import sys
    sys.path.insert(0, str(live))
    spec = importlib.util.spec_from_file_location("build_eval_for_steps", live / "build_eval.py")
    build_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_eval)
    step = build_eval.call_summary(err)["by_step"]["buses"]
    assert (step["input"], step["cache_read"], step["prompt_read_s"]) == (9000, 8700, 1.5)


# -- the shared prefix as its own chat turn --------------------------------------------------------

def test_a_prompt_with_a_turn_is_sent_as_two_user_turns_and_the_repair_keeps_it():
    from atoo.ai_provider import Prompt, chat_messages
    prompt = Prompt(("static ", "show "), "step text", "ack")
    assert str(prompt) == "static show step text"                  # what every other provider sends
    assert chat_messages("sys", prompt) == [
        {"role": "system", "content": "sys"}, {"role": "user", "content": "static show "},
        {"role": "assistant", "content": "ack"}, {"role": "user", "content": "step text"}]
    repair = prompt.with_tail(" and what was wrong")
    assert chat_messages("sys", repair)[:3] == chat_messages("sys", prompt)[:3]
    assert chat_messages("sys", repair)[3]["content"] == "step text and what was wrong"
    assert chat_messages("sys", Prompt(("a",), "b")) == [{"role": "system", "content": "sys"},
                                                         {"role": "user", "content": "ab"}]


# -- an empty Category table, in both arms ---------------------------------------------------------

def test_an_empty_category_table_is_asked_for_once_in_step_1_when_the_conventions_give_categories_settings():
    empty = {**STEP1, "categories": []}
    table_only = {"name": "Categories", "notes": [], "ops": [], "categories": STEP1["categories"]}
    plan, provider, infos, trace = build({**GOOD, "intent-categories": empty,
                                          "intent-categories-repair": table_only})
    repair = provider.calls[1]
    assert repair["label"] == "intent-categories-repair"
    assert "the conventions give settings to categories (strings, vocals) and the reply's `categories` is empty" \
        in repair["user"].tail and "its `categories`" in repair["user"].tail
    assert channel(plan, "Mando")["processing"]["hpf_hz"] == 100
    assert channel(plan, "Fiddle")["source"]["stereo"] is True                  # the first reply's pair stands
    assert any("intent step 1 (categories and exceptions): the model's first reply left something out" in i
               for i in infos)


def test_the_single_call_asks_for_an_empty_category_table_the_same_way():
    from atoo import intent_build
    whole = {"name": "Build", "notes": [], "categories": [],
             "ops": [*STEP1["ops"], *STEP2["ops"], *STEP3["ops"]]}
    table_only = {"name": "Categories", "notes": [], "ops": [], "categories": STEP1["categories"]}
    provider = Scripted({"intent": whole, "intent-repair": table_only})
    infos: list[str] = []
    plan = intent_build.generate_plan(CONVENTIONS, CSV, provider=provider, console_model="wing-compact",
                                      conventions_name="conventions.md", infos=infos)
    assert [c["label"] for c in provider.calls] == ["intent", "intent-repair"]
    assert "`categories` is empty" in provider.calls[1]["user"]
    assert channel(plan, "Mando")["processing"]["hpf_hz"] == 100
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}               # the first reply's ops stand


def test_a_category_table_is_not_asked_for_when_the_conventions_give_categories_no_settings():
    from atoo import intent_build, input_list
    rows = input_list.parse_input_list(CSV)
    assert intent_build.categories_given_settings("- Strings Wedge: the strings, pre-fader, on LCL 5.", rows) == []
    assert intent_build.categories_given_settings("- Vocals: red.\n- Strings: high-pass 100 Hz.", rows) == [
        "vocals", "strings"]
    assert intent_build.categories_left_out({"categories": [{"name": "X", "aliases": ["x"]}]}, CONVENTIONS, rows) == ""


# -- judgement slips the compile used to refuse: 0 Hz, "Gray" -------------------------------------

SLIPS_CATEGORIES = [{"name": "Strings", "aliases": ["strings"], "color": "Green", "hpf_hz": 0},
                    {"name": "Vocals", "aliases": ["vocals"], "color": "Red"}]
SLIPS_OPS = [{"op": "add_channel", "name": "Fiddle", "rows": ["Fiddle L", "Fiddle R"], "stereo": True,
              "color": "Gray"}]


def _slips_hold(plan, infos):
    assert channel(plan, "Mando")["processing"]["hpf_hz"] is None              # no high-pass is set
    assert channel(plan, "Mando")["color"] == "Green"                          # the rest of the entry stands
    assert channel(plan, "Fiddle")["color"] == "Grey"
    assert any("category 'Strings': a high-pass of 0 Hz is read as no high-pass" in i for i in infos)
    assert any("channel 'Fiddle': the colour 'Gray' is the desk's 'Grey'" in i for i in infos)


def test_a_zero_high_pass_and_gray_are_read_at_info_in_the_steps():
    step1 = {**STEP1, "categories": SLIPS_CATEGORIES, "ops": SLIPS_OPS}
    plan, provider, infos, trace = build({**GOOD, "intent-categories": step1})
    assert [c["label"] for c in provider.calls] == ["intent-categories", "intent-buses", "intent-outputs"]
    _slips_hold(plan, infos)


def test_a_zero_high_pass_and_gray_are_read_at_info_in_the_single_call():
    from atoo import intent_build
    whole = {"name": "Build", "notes": [], "categories": SLIPS_CATEGORIES,
             "ops": [*SLIPS_OPS, *STEP2["ops"], *STEP3["ops"]]}
    provider = Scripted({"intent": whole})
    infos: list[str] = []
    plan = intent_build.generate_plan(CONVENTIONS, CSV, provider=provider, console_model="wing-compact",
                                      conventions_name="conventions.md", infos=infos)
    assert [c["label"] for c in provider.calls] == ["intent"]                 # no repair spent on it
    _slips_hold(plan, infos)


def test_only_what_the_compile_refused_is_read_anew():
    from atoo import intent_build
    intent = {"name": "n", "notes": [], "ops": [{"op": "add_bus", "name": "Wedge", "color": "Gold"},
                                                {"op": "add_channel", "name": "Kick", "hpf_hz": 80}],
              "categories": [{"name": "Keys", "aliases": ["keys"], "color": "Gray", "hpf_hz": 100}]}
    out, infos = intent_build.with_reasonable_values(intent)
    assert out["ops"] == intent["ops"]                # not a spelling of a desk colour; a real HPF
    # A Category table's colour is read as a channel's is, since step 1 writes "Drum-Red" there.
    assert out["categories"][0]["color"] == "Grey" and len(infos) == 1


def test_a_malformed_op_in_a_steps_repair_costs_that_op_not_the_show():
    loud = {**STEP2, "ops": [STEP2["ops"][0], {**STEP2["ops"][1], "mode": "loud"}]}
    plan, _, infos, _ = build({**GOOD, "intent-buses": loud, "intent-buses-repair": loud})
    assert set(plan["busses"]) == {"Strings Wedge"}
    assert any(line.startswith("not built") and "'loud'" in line for line in infos)


def test_a_step_cut_off_at_a_limit_keeps_what_it_finished_and_asks_for_the_rest():
    from atoo.ai_provider import AIProviderError
    whole = json.dumps(STEP2)
    cut = AIProviderError("Ollama's reply was cut off (done_reason 'length') before 'm' finished, after "
                          "4000 tokens: it hit the reply cap", partial_text=whole[:whole.index('"Room Verb"') + 4])
    rest = {"name": "More", "notes": [], "ops": [STEP2["ops"][1]]}
    plan, _, infos, _ = build({**GOOD, "intent-buses": cut, "intent-buses-repair": rest})
    assert set(plan["busses"]) == {"Strings Wedge", "Room Verb"}
    assert any("cut off" in line and "1 op(s) it finished are kept" in line for line in infos)


def test_every_step_sends_notes_bounded_for_the_grammar():
    from atoo import intent_schema
    _, provider, _, _ = build(GOOD)
    sent = [c["schema"] for c in provider.calls if c["schema"]]
    assert sent and all(s["properties"]["notes"]["maxItems"] == intent_schema.NOTES_MAX for s in sent)


def test_steps_build_a_show_whose_stated_pair_the_desk_cannot_join():
    """The three-call arm built no plan at all when a pair the conventions make stereo sat on an
    even socket (refused before step 1); it now builds, with the pair through a user patch."""
    from test_build_intent import EVEN_PAIR_CSV, EVEN_PAIR_RULE
    from atoo.ai_provider import FakeProvider
    empty = {"name": "n", "notes": [], "categories": [], "ops": []}
    infos = []
    plan = intent_steps.generate_plan(EVEN_PAIR_RULE, EVEN_PAIR_CSV, provider=FakeProvider(response=json.dumps(empty)),
                                      console_model="wing-compact", infos=infos)
    names = {c["name"]: (c["patch"]["group"], c["patch"]["sockets"]) for c in plan["channels"]}
    assert names["Lute"] == ("USR", [25, 26]) and names["Harp"] == ("LCL", [7, 8])
    assert [e["source"]["index"] for e in plan["user_sources"]] == [4, 5]
    assert any("patched through user patch USR 25-26" in line for line in infos)


def test_steps_read_a_colour_run_into_a_category_name_as_the_desks():
    step1 = {**STEP1, "categories": [{**STEP1["categories"][0], "color": "Strings-Green"},
                                     {**STEP1["categories"][1], "color": "Vocal-Red"}]}
    plan, _, infos, _ = build({**GOOD, "intent-categories": step1})
    assert channel(plan, "Fiddle")["color"] == "Green"
    assert any("'Strings-Green' is the desk's 'Green'" in line for line in infos)


# -- the default: three steps for a local model --------------------------------------------------

SINGLE = {"name": "The show", "notes": [], "categories": STEP1["categories"],
          "ops": [*STEP1["ops"], *STEP2["ops"], *STEP3["ops"]]}


def test_a_local_model_asks_in_three_steps_by_default_and_any_other_provider_in_one():
    from atoo.ai_provider import OllamaProvider
    from atoo.cli import _intent_steps_default
    steps, said = _intent_steps_default(OllamaProvider(model="m", show_progress=False))
    assert steps is True and "default for a local model (Ollama)" in said and "--no-intent-steps" in said
    steps, said = _intent_steps_default(Scripted({}))
    assert steps is False and "in one call" in said and "--intent-steps" in said


def _build_cli(tmp_path, monkeypatch, provider, *flags):
    from atoo.cli import main
    (tmp_path / "input.csv").write_text(CSV)
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    return main(["build", "--console-model", "wing-compact", *flags,
                 "--input", str(tmp_path / "input.csv"), "--conventions", str(tmp_path / "conventions.md"),
                 "--out", str(tmp_path / "plan.json")])


@pytest.mark.parametrize("local, flags, labels, said", [
    (True, ["--intent"], ["intent-categories", "intent-buses", "intent-outputs"], "three steps, the default"),
    (True, ["--intent", "--no-intent-steps"], ["intent"], None),
    (False, ["--intent"], ["intent"], "one call, the default"),
    (False, ["--intent", "--intent-steps"], ["intent-categories", "intent-buses", "intent-outputs"], None),
])
def test_the_build_follows_the_default_unless_a_flag_says_otherwise(tmp_path, monkeypatch, capsys,
                                                                     local, flags, labels, said):
    import atoo.cli
    real = atoo.cli._intent_steps_default
    monkeypatch.setattr("atoo.cli._intent_steps_default",
                        lambda provider: real(provider) if not local else
                        (True, "the intent is asked for in three steps, the default for a local model (Ollama); "
                               "--no-intent-steps asks for it in one call"))
    provider = Scripted({**GOOD, "intent": SINGLE})
    rc = _build_cli(tmp_path, monkeypatch, provider, *flags)
    err = capsys.readouterr().err
    assert rc == 0, err
    assert [c["label"] for c in provider.calls][:len(labels)] == labels
    assert (said in err) if said else ("the default" not in err)


@pytest.mark.parametrize("url, local", [
    ("http://localhost:1234", True), ("http://127.0.0.1:8080/v1", True), ("http://[::1]:8000", True),
    ("http://169.254.10.20:1234", True), ("http://[fd12:3456::5]:8000", True), ("http://studio.local:1234", True),
    ("https://api.openai.com", False), ("https://api.x.ai", False), ("http://8.8.8.8", False),
])
def test_the_api_provider_on_a_host_on_this_machine_or_network_is_a_local_model(url, local):
    from atoo.ai_provider import ApiKeyProvider
    from atoo.cli import _intent_steps_default
    steps, said = _intent_steps_default(ApiKeyProvider(api_key="k", model="m", base_url=url))
    assert steps is local
    assert (url in said) if local else ("in one call" in said)


def test_steps_carry_a_channels_stated_high_pass_over_its_categorys():
    conventions = CONVENTIONS + "\n## Exceptions\n- The dobro is high-passed at 140 Hz, the fiddle at 80.\n"
    plan, _, infos, _ = build(GOOD, conventions=conventions)
    assert channel(plan, "Dobro")["processing"]["hpf_hz"] == 140
    assert channel(plan, "Fiddle")["processing"]["hpf_hz"] == 80
    assert channel(plan, "Mando")["processing"]["hpf_hz"] == 100           # its category's
    assert any(line.startswith("'Dobro' high-pass 140 Hz") for line in infos)


def test_steps_move_a_step_two_bus_off_the_socket_step_three_gives_main():
    """The buses step and the outputs step are separate calls: a bus on LCL 1 and Main on LCL 1-2
    are each fine alone, and claim one socket together."""
    step2 = {**STEP2, "ops": [STEP2["ops"][0], {**STEP2["ops"][1], "to": {"output": {"group": "LCL", "first": 1}}}]}
    plan, _, infos, _ = build({**GOOD, "intent-buses": step2})
    sockets = plan["busses"]["Room Verb"]["destination"]["patch"]
    assert (sockets["group"], sockets["sockets"]) == ("LCL", [3])
    assert any(line.startswith("'Room Verb': the reply wrote LCL 1, which 'Main' also uses") for line in infos)


def test_steps_make_the_aux_strips_the_conventions_ask_for_that_no_step_wrote():
    """The steps' own completeness check covers buses, groups and outputs, not strips asked for by
    name on an Aux strip; code builds them from the line that asks."""
    conventions = CONVENTIONS + "\n## Aux Channels\n- Setup TALKBACK on Aux 8, source LCL 22.\n"
    plan, _, infos, _ = build(GOOD, conventions=conventions)
    talkback = channel(plan, "TALKBACK")
    assert (talkback["bank"], talkback["channel"], talkback["patch"]["sockets"]) == ("aux", 8, [22])
    assert any(line.startswith("'TALKBACK' on Aux 8, source LCL 22, filled by code") for line in infos)


def test_steps_overflow_rows_with_no_socket_to_the_box_the_conventions_name():
    from test_build_intent import OVERFLOW, _rows_csv
    from atoo.ai_provider import FakeProvider
    empty = {"name": "n", "notes": [], "categories": [], "ops": []}
    plan = intent_steps.generate_plan(OVERFLOW, _rows_csv(26), provider=FakeProvider(response=json.dumps(empty)),
                                      console_model="wing-compact", infos=[])
    groups = [c["patch"]["group"] for c in plan["channels"]]
    assert groups.count("LCL") == 24 and groups.count("B") == 2


def test_steps_keep_a_pair_two_mono_channels_when_a_high_pass_is_stated_for_one_side():
    from test_build_intent import CYMBALS_CSV, JOINED
    from atoo.ai_provider import FakeProvider
    reply = {"name": "n", "notes": [], "categories": [], "ops": [JOINED]}
    plan = intent_steps.generate_plan("## Channels\nHigh-pass Cymbals Left at 30Hz.\n", CYMBALS_CSV,
                                      provider=FakeProvider(response=json.dumps(reply)),
                                      console_model="wing-compact", infos=[])
    assert {c["name"]: c["processing"].get("hpf_hz") for c in plan["channels"]
            if c["name"].startswith("Cymbals")} == {"Cymbals Left": 30, "Cymbals Right": None}


def test_steps_carry_out_a_bus_socket_stated_in_a_line_under_a_heading_atoo_does_not_read():
    """'## Monitors' names no kind, so its line is not an item of a bus section; the line that names
    the bus still says where it goes, and the steps carry it out."""
    conventions = CONVENTIONS + "\n## Monitors\n- Room Verb: the vocals' reverb return. It goes out on Local outs 7.\n"
    conventions = conventions.replace("- Room Verb: the vocals, post-fader.\n", "")
    step2 = {**STEP2, "ops": [STEP2["ops"][0], {**STEP2["ops"][1], "to": {"output": {"group": "LCL", "first": 3}}}]}
    plan, _, infos, _ = build({**GOOD, "intent-buses": step2}, conventions=conventions)
    sockets = plan["busses"]["Room Verb"]["destination"]["patch"]
    assert (sockets["group"], sockets["sockets"]) == ("LCL", [7])
    assert any(line.startswith("'Room Verb': the reply wrote LCL 3") for line in infos)


def test_the_steps_lay_the_strips_out_in_the_category_order_the_conventions_state():
    conventions = CONVENTIONS.replace("## Categories\n", "## Categories\nStrip order: voice, then bass, then strings.\n")
    plan, _, infos, _ = build(GOOD, conventions=conventions)
    strips = [c["name"] for c in sorted(plan["channels"], key=lambda c: c["channel"])]
    assert strips[:3] == ["Hollis Vox", "Wren Vox", "Upright"]
    assert set(strips[3:]) == {"Mando", "Dobro", "Fiddle"}
    assert any(i.startswith("the strips are laid out by category as the conventions state") for i in infos)
