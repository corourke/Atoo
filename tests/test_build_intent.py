"""`atoo build --intent` (`atoo/intent_build.py`), offline: a fake provider answers with an
intent for the whole show, code compiles it over an empty desk, and the build's usual steps
run on the plan. Frozen inputs built here; nothing reads `examples/`."""

from __future__ import annotations

import json

import pytest

from atoo import generate, intent_build
from atoo.ai_provider import FakeProvider

CSV = """patch,name,category,type,model,phantom,notes
,Kick,drums,Mic,Beta 91A,TRUE,
,Snare,drums,Mic,SM57,FALSE,
,Bass,bass,DI,J48,TRUE,
,Lead,vocals,Mic,SM58,FALSE,
"""
CONVENTIONS = "Drums go in a Drums DCA. Vocals go in a Vocals DCA.\n"


def intent_for(*names, extra=()):
    ops = [{"op": "add_channel", "name": n, "kind": "mic", "dca": ["Drums"] if n in ("Kick", "Snare") else None}
           for n in names]
    ops = [{k: v for k, v in op.items() if v is not None} for op in ops]
    return {"name": "Build the band", "ops": [*ops, *extra], "notes": [], "categories": []}


def build(intent, **kw):
    infos: list[str] = []
    plan = intent_build.generate_plan(
        CONVENTIONS, CSV, provider=FakeProvider(response=json.dumps(intent)),
        console_model="wing-compact", infos=infos, **kw)
    return plan, infos


def test_the_intent_builds_a_plan_with_a_channel_per_row_and_the_groups_it_names():
    plan, infos = build(intent_for("Kick", "Snare", "Bass", "Lead",
                                   extra=[{"op": "add_group", "object": "dca", "name": "Vocals"}]))
    assert [c["name"] for c in plan["channels"]] == ["Kick", "Snare", "Bass", "Lead"]
    assert [c["channel"] for c in plan["channels"]] == [1, 2, 3, 4]
    assert set(plan["dcas"]) == {"Drums", "Vocals"}
    assert plan["meta"]["console_model"] == "wing-compact"
    assert all(c["patch"]["sockets"] for c in plan["channels"])
    assert not any("had no channel" in line for line in infos)


def test_code_writes_the_rows_the_intent_does_not_mention():
    plan, infos = build(intent_for("Kick", "Snare"))
    assert [c["name"] for c in plan["channels"]] == ["Kick", "Snare", "Bass", "Lead"]   # the list's order
    bass = next(c for c in plan["channels"] if c["name"] == "Bass")
    assert bass["source"]["type"] == "DI" and bass["source"]["phantom"] is True
    assert bass["source"]["model"] == "J48"


def test_the_models_channel_takes_the_place_of_the_rows_own_and_a_second_row_is_not_added_twice():
    from atoo import intent_build, input_list
    rows = input_list.parse_input_list(PAIR_CSV)
    out = intent_build.with_rows(
        {"name": "n", "notes": [], "categories": [], "ops": [
            {"op": "add_channel", "name": "Overheads", "rows": ["OH L", "OH R"]},
            {"op": "add_channel", "name": "Extra Strip"},
            {"op": "add_group", "object": "dca", "name": "Kit"}]}, rows)
    names = [(op["op"], op["name"]) for op in out["ops"]]
    assert names == [("add_channel", "Cab"), ("add_channel", "Pan"), ("add_channel", "Overheads"),
                     ("add_channel", "Dub"), ("add_channel", "Cora"), ("add_channel", "Extra Strip"),
                     ("add_group", "Kit")]


def test_the_input_list_is_sent_whole_and_the_build_note_is_in_the_system_prompt():
    provider = FakeProvider(response=json.dumps(intent_for("Kick", "Snare", "Bass", "Lead")))
    intent_build.generate_plan(CONVENTIONS, CSV, provider=provider, console_model="wing-compact")
    system, user = provider.calls[0]
    assert "This request builds a whole show" in system
    assert "```csv" in user and "Beta 91A" in user and user.index("The input list") < user.index("# The request")


def test_a_socket_past_the_stage_box_costs_that_strip_not_the_show():
    """A build refuses only the op that cannot be built, names it, and builds the rest."""
    bad = intent_for("Kick", extra=[{"op": "add_channel", "name": "Tamb", "patch": {"group": "LCL", "first": 30}}])
    plan, infos = build(bad)
    assert "Tamb" not in [c["name"] for c in plan["channels"]] and "Kick" in [c["name"] for c in plan["channels"]]
    assert any(line.startswith("not built") and "Tamb" in line for line in infos)


def test_atoo_build_intent_writes_a_plan_that_verifies(tmp_path, monkeypatch, capsys):
    from atoo.cli import main
    (tmp_path / "input.csv").write_text(CSV)
    (tmp_path / "conventions.md").write_text(CONVENTIONS)
    provider = FakeProvider(response=json.dumps(intent_for("Kick", "Snare", "Bass", "Lead")))
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    rc = main(["build", "--console-model", "wing-compact", "--intent",
               "--input", str(tmp_path / "input.csv"), "--conventions", str(tmp_path / "conventions.md"),
               "--out", str(tmp_path / "plan.json")])
    err = capsys.readouterr().err
    assert rc == 0, err
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert [c["name"] for c in plan["channels"]] == ["Kick", "Snare", "Bass", "Lead"]
    assert plan["meta"]["verify_findings"]["errors"] == []
    assert provider.labels[0] == "intent"
    log = json.loads((tmp_path / plan["meta"]["build_log_file"]).read_text())
    assert [json.loads(r)["name"] for r in log["intent_replies"]] == ["Build the band"]   # what the model wrote


# -- what an intent for a whole show can say: rows, categories, members, order -----------------

from atoo import intent_compile as ic, patch  # noqa: E402

PAIR_CSV = """patch,name,category,type,model,phantom,notes
AES50-A 1,Cab,drums,Mic,Beta 91A,TRUE,
AES50-A 2,Pan,drums,Mic,SM57,FALSE,
AES50-A 5,OH L,drums,Mic,KSM137,TRUE,
AES50-A 6,OH R,drums,Mic,KSM137,TRUE,
,Dub,bass,DI,J48,FALSE,
,Cora,vocals,Mic,SM58,FALSE,
"""


GROUPS = "Groups: Kit, Everyone, Kit Bus. A Click strip.\n- Put a Talkback mic on source LCL 20.\n- A Click track plays from source USB 1.\n"


def compiled(ops, *, categories=None, csv=PAIR_CSV, conventions=GROUPS):
    merge, infos = merged(ops, categories=categories, csv=csv, conventions=conventions)
    assert not merge.refused, merge.refused
    return merge.plan, infos


def merged(ops, *, categories=None, csv=PAIR_CSV, conventions=GROUPS):
    intent = {"name": "n", "ops": ops, "notes": [], "categories": categories or []}
    return ic.apply_intent(intent, patch.empty_base("wing-compact"), "wing-compact",
                           text="Build the show.", input_list_text=csv, build=True,
                           conventions_text=conventions)


def channel(plan, name):
    return next(c for c in plan["channels"] if c["name"] == name)


def test_a_channel_built_from_two_rows_is_one_stereo_pair_with_the_lists_sockets():
    plan, _ = compiled([{"op": "add_channel", "name": "OH", "rows": ["OH L", "OH R"]}])
    oh = channel(plan, "OH")
    assert oh["source"]["stereo"] is True and oh["source"]["input"] == "OH L"
    assert oh["source"]["pair_input"] == "OH R" and oh["patch"]["sockets"] == [5, 6]
    assert oh["source"]["phantom"] is True and oh["source"]["model"] == "KSM137"


def test_a_channel_named_like_a_row_is_filled_from_it_and_a_row_that_is_not_there_is_refused():
    plan, _ = compiled([{"op": "add_channel", "name": "Cab"}])
    cab = channel(plan, "Cab")
    assert cab["source"]["model"] == "Beta 91A" and cab["source"]["phantom"] is True
    assert cab["patch"] == {"group": "A", "sockets": [1], "stated": True}
    with pytest.raises(ic.IntentRefused) as raised:
        compiled([{"op": "add_channel", "name": "Both", "rows": ["Cab", "Nope"]}])
    assert "'Nope' is not a row of the input list" in " ".join(raised.value.reasons)


def test_members_by_category_put_every_channel_of_it_in_the_group_and_the_bus():
    ops = [{"op": "add_channel", "name": n} for n in ("Cab", "Pan", "Dub", "Cora")]
    ops += [{"op": "add_group", "object": "dca", "name": "Kit", "members": {"categories": ["drums"]}},
            {"op": "add_group", "object": "mute_group", "name": "Everyone", "members": {"all": True}},
            {"op": "add_bus", "name": "Kit Bus", "mode": "post",
             "members": {"categories": ["drums"], "channels": ["Dub"]}}]
    plan, infos = compiled(ops)
    assert {c["name"] for c in plan["channels"] if "Kit" in c["dca"]} == {"Cab", "Pan"}
    assert all("Everyone" in c["mute_group"] for c in plan["channels"])
    sending = {c["name"] for c in plan["channels"] if any(s["bus"] == "Kit Bus" for s in c["bus_sends"])}
    assert sending == {"Cab", "Pan", "Dub"}
    assert any("dca 'Kit': 2 member channel(s)" in line for line in infos)


def test_order_puts_the_strips_in_the_order_of_the_categories_listed():
    ops = [{"op": "add_channel", "name": n} for n in ("Cab", "Dub", "Cora", "Pan")]
    ops.append({"op": "order", "categories": ["vocals", "drums", "bass"]})
    plan, _ = compiled(ops)
    by_strip = [c["name"] for c in sorted(plan["channels"], key=lambda c: c["channel"])]
    assert by_strip == ["Cora", "Cab", "Pan", "Dub"]


def test_categories_in_the_intent_are_the_category_table_code_applies():
    entries = [{"name": "Drums", "aliases": ["drums"], "hpf_hz": 80, "color": "Yellow"},
               {"name": "Vox", "aliases": ["vocals"], "hpf_hz": 120}]
    ops = [{"op": "add_channel", "name": n} for n in ("Cab", "Cora", "Dub")]
    plan, _ = compiled(ops, categories=entries)
    assert channel(plan, "Cab")["processing"]["hpf_hz"] == 80
    assert channel(plan, "Cora")["processing"]["hpf_hz"] == 120
    assert channel(plan, "Dub")["processing"]["hpf_hz"] is None       # no entry for bass
    with pytest.raises(ic.IntentRefused) as raised:
        compiled(ops, categories=[{"name": "A", "aliases": ["x"]}, {"name": "B", "aliases": ["x"]}])
    assert "alias of both" in " ".join(raised.value.reasons)


def test_a_row_is_left_out_only_when_the_model_quotes_words_that_say_so():
    csv = PAIR_CSV.replace("Pan,drums,Mic,SM57,FALSE,", "Pan,drums,Mic,SM57,FALSE,not patched tonight")
    ops = lambda quote: [{"op": "add_channel", "name": "Cab"}, {"op": "add_channel", "name": "Pan"},  # noqa: E731
                         {"op": "drop", "object": "channel", "name": "Pan", "quote": quote}]
    for quote, built in ((None, True), ("Pan is not needed", True), ("not patched tonight", False)):
        plan, infos = compiled(ops(quote), csv=csv)
        assert ("Pan" in [c["name"] for c in plan["channels"]]) is built, (quote, infos)
        assert any("input-list row 'Pan'" in line for line in infos)


def test_a_strip_that_is_not_a_row_can_be_added_and_dropped_without_a_quote():
    plan, infos = compiled([{"op": "add_channel", "name": "Click"}, {"op": "add_channel", "name": "Cab"},
                            {"op": "drop", "object": "channel", "name": "Click"}])
    assert [c["name"] for c in plan["channels"]] == ["Cab"]
    assert any("added by this intent and then dropped" in line for line in infos)


def test_a_strip_the_conventions_ask_for_by_name_and_socket_carries_their_words():
    """A strip that is not a row is built when a line of the conventions names it and says where
    it is plugged in; the line goes on `source.quote`, so verify reads it as asked for, not
    invented (`reconcile.invented-source`)."""
    plan, infos = compiled([{"op": "add_channel", "name": "Talkback", "patch": {"group": "LCL", "first": 20}}])
    source = channel(plan, "Talkback")["source"]
    assert source["from"] == "conventions"
    assert source["quote"] == "Put a Talkback mic on source LCL 20"
    assert any("not a row of the input list" in line and "Talkback" in line for line in infos)


def test_a_strip_that_is_neither_a_row_nor_asked_for_with_a_socket_is_refused():
    for conventions in ("Groups: Kit. A Click strip.\n", "Groups: Kit. A Click strip, Click 3 times.\n"):
        with pytest.raises(ic.IntentRefused, match="not a row of the input list"):
            merged([{"op": "add_channel", "name": "Click"}], conventions=conventions)


def test_a_build_whose_first_reply_is_valid_but_refused_is_repaired_with_a_slice_widened_by_every_op():
    """The repair round widens the slice from the ops of the first reply, `order` included; a table
    that missed that op raised KeyError and the build died with no repair. The first reply here is
    a valid intent the compile refuses (a category nobody said), which is how that path is reached."""
    bad = {"name": "n", "notes": [], "categories": [], "ops": [
        {"op": "order", "categories": ["drums"]}, {"op": "add_channel", "name": "Kick", "category": "zorkblorp"}]}
    good = {"name": "n", "notes": [], "categories": [], "ops": [
        {"op": "order", "categories": ["drums"]},
        {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "LCL", "first": 1, "count": 2}}]}

    class Scripted(FakeProvider):
        def complete(self, **kw):
            self.calls.append((kw["system"], kw["user"]))
            return json.dumps([bad, good][len(self.calls) - 1])

    provider = Scripted()
    infos: list[str] = []
    plan = intent_build.generate_plan(CONVENTIONS, CSV, provider=provider, console_model="wing-compact",
                                      infos=infos)
    assert len(provider.calls) == 2 and "the compile refused it" in provider.calls[1][1]
    assert [o["patch"]["sockets"] for o in plan["outputs"].values()] == [[1, 2]]
    assert [c["name"] for c in plan["channels"]][:2] == ["Kick", "Snare"]
    assert any("asked once more" in line for line in infos)


# -- the input list's word about a row, against the model's ------------------------------------

def test_a_socket_the_list_states_wins_over_the_one_the_model_wrote_and_is_said():
    plan, infos = compiled([{"op": "add_channel", "name": "Cab", "patch": {"group": "A", "first": 9}}])
    assert channel(plan, "Cab")["patch"]["sockets"] == [1]
    assert any("the input list states patch A 1 for 'Cab'; the model wrote A 9" in line for line in infos)


def test_a_microphone_the_list_states_wins_over_the_models():
    plan, infos = compiled([{"op": "add_channel", "name": "Pan", "model": "SM58"}])
    assert channel(plan, "Pan")["source"]["model"] == "SM57"
    assert any("the input list states model 'SM57'" in line for line in infos)


def test_a_stereo_pair_whose_other_half_the_list_gives_another_row_is_refused_naming_the_row():
    csv = PAIR_CSV.replace(",Dub,bass,DI,J48,FALSE,", "AES50-A 2,Dub,bass,DI,J48,FALSE,").replace(
        "AES50-A 2,Pan,drums,Mic,SM57,FALSE,", ",Pan,drums,Mic,SM57,FALSE,")
    with pytest.raises(ic.IntentRefused) as raised:
        compiled([{"op": "add_channel", "name": "Cab", "stereo": True}], csv=csv)
    assert "A 2, the other half of the pair, is the input list's socket for 'Dub'" in " ".join(raised.value.reasons)


def test_a_pair_of_two_rows_takes_both_rows_sockets_and_is_not_refused_for_its_own_second_row():
    plan, _ = compiled([{"op": "add_channel", "name": "OH", "rows": ["OH L", "OH R"]}])
    assert channel(plan, "OH")["patch"]["sockets"] == [5, 6]


def test_order_can_put_named_channels_first_within_their_category():
    ops = [{"op": "add_channel", "name": n} for n in ("Cab", "Pan", "Dub", "Cora")]
    ops.append({"op": "order", "categories": ["drums", "bass", "vocals"], "channels": ["Pan", "Cab"]})
    plan, infos = compiled(ops)
    by_strip = [c["name"] for c in sorted(plan["channels"], key=lambda c: c["channel"])]
    assert by_strip == ["Pan", "Cab", "Dub", "Cora"]


UNPATCHED_PAIR_CSV = """patch,name,category,type,model,phantom,notes
,Zither L,keys,DI,,FALSE,
,Zither R,keys,DI,,FALSE,
"""


def test_a_socket_only_the_model_chose_that_cannot_exist_is_chosen_by_code_instead():
    """No row states a socket, so LCL 6+7 is the model's own arithmetic, and a pair cannot start on
    an even socket: code picks the socket, at INFO, rather than refusing the whole show."""
    pair = {"op": "add_channel", "name": "Zither", "rows": ["Zither L", "Zither R"], "stereo": True,
            "patch": {"group": "LCL", "first": 6, "count": 2}}
    plan, infos = compiled([pair], csv=UNPATCHED_PAIR_CSV)
    patched = channel(plan, "Zither")["patch"]
    assert patched["group"] == "LCL" and patched["sockets"][0] % 2 == 1 and len(patched["sockets"]) == 2
    assert any("LCL 6+7" in line and "Atoo chose one" in line for line in infos)


def test_a_socket_the_conventions_name_that_cannot_exist_is_still_refused():
    pair = {"op": "add_channel", "name": "Zither", "rows": ["Zither L", "Zither R"], "stereo": True,
            "patch": {"group": "LCL", "first": 6, "count": 2}}
    with pytest.raises(ic.IntentRefused, match="even socket"):
        merged([pair], csv=UNPATCHED_PAIR_CSV, conventions="The Zither goes on LCL 6-7.\n")


# -- completeness: what the conventions' sections ask for, and Main's sockets -------------------

QUARTET_CSV = """patch,name,category,type,model,phantom,notes
,Fiddle,strings,Mic,,FALSE,
,Cello,strings,Mic,,FALSE,
,Singer,voice,Mic,,FALSE,
"""

QUARTET = """## DCAs
- Strings: all strings-category channels
- Brass: all brass-category channels
## Mute Groups
- Voices: all voice-category channels
## Busses
- Room Verb: strings channels route to bus post-fader at -10dB, bus routes to main
- Wedge A: voice channels route to bus pre-fader at unity, mono, bus routes to a dedicated output, named "Singer wedge", routed to Local outputs 5
## Output
- Main: full mix, routed to Local outputs 1-2
"""

GROUP_OPS = [
    {"op": "add_group", "object": "dca", "name": "Strings", "members": {"categories": ["strings"]}},
    {"op": "add_group", "object": "mute_group", "name": "Voices", "members": {"categories": ["voice"]}},
    {"op": "add_bus", "name": "Room Verb", "stereo": True, "mode": "post", "level_db": -10,
     "members": {"categories": ["strings"]}, "to": {"main": True}},
]
WEDGE = {"op": "add_bus", "name": "Singer wedge", "stereo": False, "mode": "pre", "level_db": 0,
         "members": {"categories": ["voice"]}, "to": {"output": {"group": "LCL", "first": 5}}}


def quartet(*ops, notes=()):
    return {"name": "Build the quartet", "notes": list(notes), "categories": [], "ops": list(ops)}


class Scripted(FakeProvider):
    def __init__(self, *replies):
        super().__init__()
        self.replies = [json.dumps(r) if isinstance(r, dict) else r for r in replies]

    def complete(self, **kw):
        self.calls.append((kw["system"], kw["user"]))
        return self.replies[min(len(self.calls), len(self.replies)) - 1]


def build_quartet(*replies):
    provider, infos = Scripted(*replies), []
    plan = intent_build.generate_plan(QUARTET, QUARTET_CSV, provider=provider, console_model="wing-compact",
                                      infos=infos)
    return plan, infos, provider


def test_the_conventions_sections_name_what_is_asked_for_and_a_category_with_no_rows_asks_nothing():
    asked = intent_build.asked_for(QUARTET)
    assert [(a.kind, a.name) for a in asked] == [
        ("DCA", "Strings"), ("DCA", "Brass"), ("mute group", "Voices"), ("bus", "Room Verb"),
        ("bus", "Wedge A"), ("output", "Main")]
    assert asked[4].aliases == ("Singer wedge",)
    missing = intent_build.left_out(quartet(*GROUP_OPS, WEDGE), asked, {"strings", "voice"})
    assert "Main" in missing and "Brass" not in missing and "Wedge" not in missing   # alias counts
    assert intent_build.left_out(quartet(*GROUP_OPS, WEDGE, notes=["No Main: the house has it."]),
                                 asked, {"strings", "voice"}) == ""


def test_a_reply_that_leaves_out_a_bus_is_asked_once_more_naming_it():
    plan, infos, provider = build_quartet(quartet(*GROUP_OPS), quartet(*GROUP_OPS, WEDGE))
    assert len(provider.calls) == 2 and "'Wedge A'" in provider.calls[1][1]
    assert "Singer wedge" in plan["busses"]
    assert any("asked once more" in line for line in infos)


def test_what_is_still_left_out_after_asking_once_more_is_said_and_not_made_by_code():
    plan, infos, provider = build_quartet(quartet(*GROUP_OPS), quartet(*GROUP_OPS))
    assert len(provider.calls) == 2 and set(plan["busses"]) == {"Room Verb"}
    assert any(line.startswith("still left out") and "Wedge A" in line for line in infos)


def test_a_repair_reply_that_cannot_be_used_keeps_the_first_show():
    plan, infos, _ = build_quartet(quartet(*GROUP_OPS), "not json at all")
    assert set(plan["busses"]) == {"Room Verb"} and [c["name"] for c in plan["channels"]] == ["Fiddle", "Cello", "Singer"]
    assert any("so the first stands" in line for line in infos)


def test_main_is_patched_by_code_where_the_conventions_state_its_sockets():
    plan, infos, provider = build_quartet(quartet(*GROUP_OPS, WEDGE))
    assert len(provider.calls) == 1                      # Main is not asked for again: code made it
    assert plan["outputs"]["Main"]["patch"]["sockets"] == [1, 2]
    assert any("Main patched to LCL 1-2, filled by code" in line for line in infos)


def test_main_patched_by_the_reply_is_left_and_main_with_no_readable_socket_is_said():
    patched = {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "USB", "first": 3, "count": 2}}
    asked = intent_build.asked_for(QUARTET)
    assert intent_build.with_main(quartet(patched), asked) == (quartet(patched), None)
    vague = intent_build.asked_for("## Output\n- Main: full mix, to the house system\n")
    intent_, info = intent_build.with_main(quartet(), vague)
    assert intent_ == quartet() and "names no socket" in info


def test_the_build_prompts_worked_example_compiles():
    """The example in `prompts/intent_build.md` is a made-up show; its ops must be ones the compile
    accepts, or it teaches a model to be refused."""
    from pathlib import Path
    text = (Path(intent_build.__file__).parent / "prompts" / "intent_build.md").read_text()
    ops = [json.loads(line.strip()) for line in text.splitlines() if line.strip().startswith('{"op"')]
    assert len(ops) == 7 and ops[0]["rows"] == ["Harp L", "Harp R"]
    plan, _ = compiled(ops, csv=QUARTET_CSV + ",Harp L,strings,DI,,FALSE,\n,Harp R,strings,DI,,FALSE,\n",
                       conventions=QUARTET + "- Any L/R pair of inputs becomes one stereo Harp channel.\n")
    assert channel(plan, "Harp")["source"]["stereo"] is True


def test_the_repair_for_what_was_left_out_asks_for_that_section_only_and_joins_it_to_the_first():
    plan, infos, provider = build_quartet(quartet(*GROUP_OPS), quartet(WEDGE))
    assert "ONLY the ops for what is missing" in provider.calls[1][1]
    assert set(plan["busses"]) == {"Room Verb", "Singer wedge"} and "Strings" in plan["dcas"]


def test_a_section_repair_naming_what_the_show_does_not_have_is_refused_and_the_first_stands():
    bad = {**WEDGE, "members": {"channels": ["Kazoo"]}}           # no such channel on this show
    plan, infos, _ = build_quartet(quartet(*GROUP_OPS), quartet(bad))
    assert set(plan["busses"]) == {"Room Verb"}
    assert any("so the first stands" in line for line in infos)


# -- a row the model names nearly as the list does ------------------------------------------------

NEAR_CSV = """patch,name,category,type,model,phantom,notes
,Bongo,perc,Mic,,FALSE,
,OH L,perc,Mic,,TRUE,
,OH R,perc,Mic,,TRUE,
,Lute Vox,voice,Mic,,FALSE,
,Gtr 1,strings,DI,,FALSE,
,Gtr 2,strings,DI,,FALSE,
,Hum,misc,Mic,,FALSE,
,Hum L,misc,Mic,,FALSE,
,Hum R,misc,Mic,,FALSE,
"""


def test_a_near_spelling_of_one_row_is_read_as_that_row_at_info():
    rows = intent_build.input_list.parse_input_list(NEAR_CSV)
    intent_, infos = intent_build.resolve_row_names(quartet(
        {"op": "add_channel", "name": "Overheads", "rows": ["Overheads L", "overhead r"], "stereo": True},
        {"op": "add_channel", "name": "Lute Vocal", "preset": "BGV"},
        {"op": "add_group", "object": "dca", "name": "Strings", "members": {"channels": ["Guitar 1", "GTR2"]}},
    ), rows)
    ops = intent_["ops"]
    assert ops[0]["rows"] == ["OH L", "OH R"] and ops[0]["name"] == "Overheads"   # its own name stays
    assert ops[1]["name"] == "Lute Vox"
    assert ops[2]["members"]["channels"] == ["Gtr 1", "Gtr 2"]
    assert len(infos) == 5 and all("read as that row" in line for line in infos)


def test_a_stereo_side_matches_only_the_same_side_and_never_the_mono_row():
    rows = intent_build.input_list.parse_input_list(NEAR_CSV)
    intent_, _ = intent_build.resolve_row_names(quartet(
        {"op": "add_channel", "name": "x", "rows": ["Hums L", "Hum Right"]},
        {"op": "add_channel", "name": "Hums"},
        {"op": "add_channel", "name": "Bongos Left"}), rows)
    ops = intent_["ops"]
    assert ops[0]["rows"] == ["Hum L", "Hum R"]
    assert ops[1]["name"] == "Hum"                         # the mono row, not a side
    assert ops[2]["name"] == "Bongos Left"                 # a side of a mono row: no match, left for the compile


def test_a_name_that_matches_no_row_or_several_is_left_for_the_compile_to_refuse():
    rows = intent_build.input_list.parse_input_list(NEAR_CSV + ",Gtr  1,strings,DI,,FALSE,\n")
    intent_, infos = intent_build.resolve_row_names(quartet(
        {"op": "drop", "object": "channel", "name": "Guitar 1", "quote": "q"},
        {"op": "add_channel", "name": "Banjo"}), rows)
    assert [op["name"] for op in intent_["ops"]] == ["Guitar 1", "Banjo"] and infos == []


def test_a_build_whose_reply_names_a_row_nearly_builds_it_once():
    infos = []
    reply = quartet({"op": "add_channel", "name": "Overheads", "rows": ["Overheads L", "Overheads R"], "stereo": True})
    plan = intent_build.generate_plan("The Overheads are one stereo pair.\n", NEAR_CSV, provider=FakeProvider(response=json.dumps(reply)),
                                      console_model="wing-compact", infos=infos)
    names = [c["name"] for c in plan["channels"]]
    assert names.count("Overheads") == 1 and "OH L" not in names and "OH R" not in names


def test_the_repair_only_adds_it_never_edits_what_the_first_reply_wrote():
    edits = quartet(WEDGE, {"op": "rename", "object": "bus", "name": "Room Verb", "new_name": "Hall"},
                    {"op": "drop", "object": "dca", "name": "Strings", "quote": "x"},
                    {**GROUP_OPS[2], "level_db": 0})                     # Room Verb again, changed
    plan, _, _ = build_quartet(quartet(*GROUP_OPS), edits)
    assert set(plan["busses"]) == {"Room Verb", "Singer wedge"} and "Strings" in plan["dcas"]


def test_an_output_socket_that_cannot_exist_takes_the_one_the_conventions_state():
    """"AES50-A outputs 41" written as AES 41 (a group with two outputs) is the model's slip; the
    conventions say where the wedge goes. A socket that exists stays the reply's choice."""
    conventions = QUARTET.replace("routed to Local outputs 5", "routed to AES50-A outputs 41")
    asked = intent_build.asked_for(conventions)
    slipped = {**WEDGE, "to": {"output": {"group": "AES", "first": 41}}}
    fixed, infos = intent_build.with_stated_outputs(quartet(slipped), asked, "wing-compact")
    assert fixed["ops"][0]["to"]["output"] == {"group": "A", "first": 41, "count": 1}
    assert "AES 41" in infos[0] and "A 41 stands" in infos[0]
    chosen = {**WEDGE, "to": {"output": {"group": "LCL", "first": 7}}}
    assert intent_build.with_stated_outputs(quartet(chosen), [], "wing-compact") == (quartet(chosen), [])
    # The conventions say where it goes: their socket stands over one the reply chose that exists.
    fixed, infos = intent_build.with_stated_outputs(quartet(chosen), asked, "wing-compact")
    assert fixed["ops"][0]["to"]["output"]["group"] == "A" and "LCL 7" in infos[0] and "A 41 stands" in infos[0]
    main = {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "LCL", "first": 30, "count": 2}}
    fixed, infos = intent_build.with_stated_outputs(quartet(main), asked, "wing-compact")
    assert fixed["ops"][0]["patch"] == {"group": "LCL", "first": 1, "count": 2} and len(infos) == 1


def test_a_group_written_as_one_name_not_a_list_is_read_as_a_list_at_info():
    """A Category-table `dca` or `mute_group` written as "Strings" means ["Strings"]; with no schema
    sent (Claude), nothing else would catch it, and the show was refused on schema."""
    reply = quartet(*GROUP_OPS[2:], WEDGE)
    reply["categories"] = [{"name": "Strings", "aliases": ["strings"], "dca": "Strings", "mute_group": "Bowed"}]
    plan, infos, _ = build_quartet(reply)
    assert "Strings" in plan["dcas"] and "Bowed" in plan["mute_groups"]
    assert any("`dca` was one name, not a list; read as ['Strings']" in line for line in infos)


def test_an_output_socket_that_cannot_exist_and_that_the_conventions_do_not_state_takes_the_nearest_free():
    """USB 49 on a desk with 48 USB outputs, for a matrix the conventions give no socket: the nearest
    free USB output stands, at INFO, rather than the show being refused."""
    asked = intent_build.asked_for("## Output\n- Matrix: fed from Main, EQ corrects the room\n")
    taken = {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "USB", "first": 47, "count": 2}}
    matrix = {"op": "add_output", "object": "matrix", "name": "Matrix", "patch": {"group": "USB", "first": 49}}
    fixed, infos = intent_build.with_stated_outputs(quartet(taken, matrix), asked, "wing-compact")
    assert fixed["ops"][1]["patch"] == {"group": "USB", "first": 46, "count": None}
    assert "USB 49" in infos[0] and "nearest free" in infos[0] and "USB 46 stands" in infos[0]


def test_a_bus_output_in_a_group_the_console_lacks_takes_the_nearest_free_local_output():
    """PLAY has no outputs on any WING (a host sent no schema, so nothing stopped the reply)."""
    wedge = {**WEDGE, "to": {"output": {"group": "PLAY", "first": 3}}}
    fixed, infos = intent_build.with_stated_outputs(quartet(wedge), [], "wing-rack")
    assert fixed["ops"][0]["to"]["output"] == {"group": "LCL", "first": 3, "count": None}
    assert "nearest free local" in infos[0]


def test_a_build_with_an_impossible_matrix_socket_still_builds_the_show():
    infos = []
    reply = quartet(*GROUP_OPS, WEDGE, {"op": "add_output", "object": "matrix", "name": "Matrix",
                                       "patch": {"group": "USB", "first": 49}})
    plan = intent_build.generate_plan(QUARTET + "- Matrix: fed from Main\n", QUARTET_CSV,
                                      provider=FakeProvider(response=json.dumps(reply)),
                                      console_model="wing-compact", infos=infos)
    assert plan["outputs"]["Matrix"]["patch"]["group"] == "USB"
    assert any("USB 49" in line for line in infos)


def test_a_malformed_op_in_the_last_reply_costs_that_op_not_the_show():
    """The first reply is held to the schema and repaired; the repair's malformed op is left out
    and named, and the rest is built."""
    loud = {**WEDGE, "mode": "loud"}
    plan, infos, provider = build_quartet(quartet(*GROUP_OPS, loud), quartet(*GROUP_OPS, loud))
    assert len(provider.calls) == 2 and set(plan["busses"]) == {"Room Verb"}
    assert any(line.startswith("not built") and "'loud'" in line for line in infos)


def test_a_refused_override_of_a_row_falls_back_to_the_row_as_the_list_states_it():
    """A preset the model gave a row that cannot be built costs the override, not the input: the
    row is built as the input list states it, said so."""
    bad = {"op": "add_channel", "name": "Fiddle", "place": {"at": 99}}       # past the desk's strips
    plan, infos, _ = build_quartet(quartet(*GROUP_OPS, WEDGE, bad), quartet(*GROUP_OPS, WEDGE, bad))
    assert [c["name"] for c in plan["channels"]] == ["Fiddle", "Cello", "Singer"]
    assert any(line.startswith("not built as the reply wrote it") and "Fiddle" in line for line in infos)


def test_a_group_the_table_and_an_op_both_name_is_made_once_with_its_members_joined():
    reply = quartet({"op": "add_group", "object": "mute_group", "name": "voices",
                     "members": {"channels": ["Cello"]}}, *GROUP_OPS[::2], WEDGE)
    reply["categories"] = [{"name": "Voice", "aliases": ["voice"], "mute_group": ["Voices"]}]
    plan, infos, _ = build_quartet(reply)
    assert [g for g in plan["mute_groups"] if g.casefold() == "voices"] == ["Voices"]
    assert set(next(c for c in plan["channels"] if c["name"] == "Cello")["mute_group"]) == {"Voices"}
    assert any("is already made by this show" in line for line in infos)


def test_more_groups_than_the_desk_has_cost_the_ones_past_its_limit_not_the_show():
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India"]
    conventions = "## Mute Groups\n" + "".join(f"- {n}: all voice-category channels\n" for n in names)
    reply = quartet(*({"op": "add_group", "object": "mute_group", "name": n,
                       "members": {"categories": ["voice"]}} for n in names))
    infos = []
    plan = intent_build.generate_plan(conventions, QUARTET_CSV, provider=FakeProvider(response=json.dumps(reply)),
                                      console_model="wing-compact", infos=infos)
    from atoo import console_facts as facts
    cap = facts.CAPACITY["mgrp"]
    assert len(plan["mute_groups"]) == cap and [c["name"] for c in plan["channels"]] == ["Fiddle", "Cello", "Singer"]
    left = [line for line in infos if line.startswith("not built: the mute group")]
    assert len(left) == len(names) - cap and "already in use" in left[0]
    singer = next(c for c in plan["channels"] if c["name"] == "Singer")
    assert all(g in plan["mute_groups"] for g in singer["mute_group"])      # no reference to a group not built


def test_a_reply_cut_off_at_a_limit_keeps_what_it_finished_and_asks_for_the_rest():
    """The reply stops mid-op at the reply cap; the ops it finished stand, the one it was writing is
    not guessed at, and the scoped repair asks for the sections it did not reach."""
    from atoo.ai_provider import AIProviderError
    whole = json.dumps(quartet(*GROUP_OPS, WEDGE))
    cut_at = whole.index('"Singer wedge"') + 5                                  # inside the wedge bus

    class CutOff(Scripted):
        def complete(self, **kw):
            self.calls.append((kw["system"], kw["user"]))
            if len(self.calls) == 1:
                raise AIProviderError("Ollama's reply was cut off (done_reason 'length') before 'm' "
                                      "finished, after 4000 tokens: it hit the reply cap",
                                      partial_text=whole[:cut_at])
            return json.dumps(quartet(WEDGE))

    provider, infos = CutOff(), []
    plan = intent_build.generate_plan(QUARTET, QUARTET_CSV, provider=provider, console_model="wing-compact",
                                      infos=infos)
    assert len(provider.calls) == 2 and "ONLY the ops for what is missing" in provider.calls[1][1]
    assert set(plan["busses"]) == {"Room Verb", "Singer wedge"}
    assert any("cut off" in line and "3 op(s) it finished are kept" in line for line in infos)


def test_the_build_reply_cap_grows_with_the_input_list_up_to_a_ceiling():
    from atoo import intent
    assert intent.build_reply_tokens(0) == intent.REPLY_TOKENS
    assert intent.build_reply_tokens(40) == intent.REPLY_TOKENS + 40 * intent.BUILD_TOKENS_PER_ROW
    assert intent.build_reply_tokens(10_000) == intent.BUILD_REPLY_TOKENS_MAX


def test_complete_part_keeps_finished_keys_and_list_items_only():
    from atoo.intent import complete_part
    raw = '{"name": "n", "notes": ["a"], "ops": [{"op": "add_group", "name": "A"}, {"op": "add_bus", "na'
    assert complete_part(raw) == {"name": "n", "notes": ["a"], "ops": [{"op": "add_group", "name": "A"}]}
    assert complete_part("no json here") is None


def test_an_output_pair_on_an_even_start_takes_the_conventions_socket_or_the_nearest_odd_pair():
    """A 42+43 cannot be a pair; where the conventions route the bus to A 42 it goes there (mono, as
    they say), and otherwise the nearest pair that starts odd."""
    asked = intent_build.asked_for("## Busses\n- Monitor 3: vocals, pre-fader, routed to AES50-A outputs 42\n")
    even = {**WEDGE, "name": "Monitor 3", "stereo": True, "to": {"output": {"group": "A", "first": 42, "count": 2}}}
    fixed, infos = intent_build.with_stated_outputs(quartet(even), asked, "wing-rack")
    assert fixed["ops"][0]["to"]["output"] == {"group": "A", "first": 42, "count": 1} and "A 42" in infos[0]
    assert fixed["ops"][0]["stereo"] is False and "the bus is mono" in infos[0]
    fixed, infos = intent_build.with_stated_outputs(quartet(even), [], "wing-rack")
    assert fixed["ops"][0]["to"]["output"] == {"group": "A", "first": 41, "count": 2} and "nearest free" in infos[0]


def test_a_channel_named_by_what_a_pair_of_rows_shares_is_that_pair_in_stereo():
    """"Hum" with no rows, where the list has "Hum L" and "Hum R" (and no plain "Hum"), is the pair;
    with a plain "Hum" row too, it is that row, never the pair."""
    pairs = """patch,name,category,type,model,phantom,notes
,Hum L,misc,DI,,FALSE,
,Hum R,misc,DI,,FALSE,
,Bongo,perc,Mic,,FALSE,
"""
    rows = intent_build.input_list.parse_input_list(pairs)
    intent_, infos = intent_build.resolve_row_names(quartet({"op": "add_channel", "name": "Hum"}), rows)
    assert intent_["ops"][0] == {"op": "add_channel", "name": "Hum", "rows": ["Hum L", "Hum R"], "stereo": True}
    assert "built as that pair, one stereo channel" in infos[0]
    rows = intent_build.input_list.parse_input_list(NEAR_CSV)              # has Hum, Hum L and Hum R
    intent_, _ = intent_build.resolve_row_names(quartet({"op": "add_channel", "name": "Hum"}), rows)
    assert "rows" not in intent_["ops"][0]


# -- L/R pairs the conventions make one stereo channel in so many words ---------------------------

PAIRS_CSV = """patch,name,category,type,model,phantom,notes
,Hum L,misc,DI,,FALSE,
,Hum R,misc,DI,,FALSE,
,Fiddle L,strings,Mic,,FALSE,
,Fiddle R,strings,Mic,,FALSE,
,Lute (stage left),strings,DI,,FALSE,
,Lute (stage right),strings,DI,,FALSE,
"""
PAIR_RULE = ("Any L/R pair of inputs becomes one stereo channel, named without the L/R. "
             "Fiddle L and Fiddle R stay two mono channels.\n")


def pairs_rows():
    return intent_build.input_list.parse_input_list(PAIRS_CSV)


def test_a_pair_the_conventions_make_stereo_is_one_channel_whatever_the_reply_wrote():
    intent_, infos = intent_build.with_stated_pairs(quartet(), pairs_rows(), PAIR_RULE)
    assert intent_["ops"] == [{"op": "add_channel", "name": "Hum", "rows": ["Hum L", "Hum R"], "stereo": True}]
    assert any("one stereo channel, 'Hum', as the conventions say" in line for line in infos)
    assert any("kept apart as the conventions say: 'Fiddle'" in line for line in infos)


def test_what_the_reply_wrote_for_one_row_stays_on_the_pair_and_references_name_the_pair():
    reply = quartet({"op": "add_channel", "name": "Hum L", "preset": "Drone"},
                    {"op": "add_group", "object": "dca", "name": "Misc", "members": {"channels": ["Hum L", "Hum R", "Fiddle L"]}})
    intent_, infos = intent_build.with_stated_pairs(reply, pairs_rows(), PAIR_RULE)
    pair = next(op for op in intent_["ops"] if op["op"] == "add_channel")
    assert pair == {"op": "add_channel", "name": "Hum", "rows": ["Hum L", "Hum R"], "stereo": True, "preset": "Drone"}
    group = next(op for op in intent_["ops"] if op["op"] == "add_group")
    assert group["members"]["channels"] == ["Hum", "Fiddle L"]
    assert any("(the reply wrote them apart)" in line for line in infos)


def test_a_pair_the_reply_wrote_mono_is_made_stereo_when_the_conventions_say_so():
    reply = quartet({"op": "add_channel", "name": "Drone", "rows": ["Hum L", "Hum R"], "stereo": False})
    intent_, _ = intent_build.with_stated_pairs(reply, pairs_rows(), PAIR_RULE)
    assert intent_["ops"] == [{"op": "add_channel", "name": "Drone", "rows": ["Hum L", "Hum R"], "stereo": True}]


def test_stage_left_and_right_are_where_players_stand_not_a_pair():
    pairs, _, _ = intent_build.stated_pairs(PAIR_RULE, pairs_rows())
    assert [p[2] for p in pairs] == ["Hum"]


def test_vague_or_negated_words_leave_the_pairing_to_the_reply_and_say_so():
    for conventions in ("Stereo-paired inputs become one stereo channel.\n",
                        "An L/R pair of inputs is never one stereo channel here.\n"):
        intent_, infos = intent_build.with_stated_pairs(quartet(), pairs_rows(), conventions)
        assert intent_["ops"] == [] and "is the reply's choice" in infos[0], conventions


def test_a_build_pairs_what_the_conventions_pair_and_builds_it():
    infos = []
    plan = intent_build.generate_plan("## Channels\n" + PAIR_RULE, PAIRS_CSV,
                                      provider=FakeProvider(response=json.dumps(quartet())),
                                      console_model="wing-compact", infos=infos)
    names = [c["name"] for c in plan["channels"]]
    assert names.count("Hum") == 1 and "Hum L" not in names and "Fiddle L" in names and "Fiddle R" in names
    assert channel(plan, "Hum")["source"]["stereo"] is True


# -- rows a build leaves out on purpose are declared, not dropped ----------------------------------

def _verify_errors(tmp_path, plan, csv):
    from atoo.cli import main
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "input.csv").write_text(csv)
    out = tmp_path / "verify.txt"
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            main(["verify", "--plan", str(tmp_path / "plan.json"), "--input", str(tmp_path / "input.csv")])
        except SystemExit:
            pass
    return buf.getvalue()


def test_rows_past_the_desk_are_declared_unassigned_so_the_plan_is_not_blocked(tmp_path):
    from atoo import console_facts as facts
    n = facts.CAPACITY["ch"] + 2
    csv = "patch,name,category,type,model,phantom,notes\n" + "".join(
        f",Mic {k},misc,Mic,,FALSE,\n" for k in range(1, n + 1))
    infos = []
    plan = intent_build.generate_plan("", csv, provider=FakeProvider(response=json.dumps(quartet())),
                                      console_model="wing-compact", infos=infos)
    built = {c["name"] for c in plan["channels"]}
    left = [e["input"] for e in plan["unassigned_inputs"]]
    assert left and left == [f"Mic {k}" for k in range(1, n + 1) if f"Mic {k}" not in built]
    assert all(any(line.startswith("not built") and name in line for line in infos) for name in left)
    text = _verify_errors(tmp_path, plan, csv)
    assert "reconcile.dropped-input" not in text and "reconcile.deliberately-unassigned" in text


def test_only_a_row_a_not_built_line_names_is_declared_a_row_dropped_silently_is_not(tmp_path):
    """A row rebuilt from the list ("not built as the reply wrote it") and a row a refusal names
    ("not built: op 5 ({... 'Bongo' ...})") do not declare every unused row: a row the reply
    dropped silently in the same build is still verify's dropped input, an ERROR."""
    csv = QUARTET_CSV + ",Bongo,perc,Mic,,FALSE,\n"
    bad = {"op": "add_channel", "name": "Fiddle", "place": {"at": 99}}       # past the desk's strips
    plan, infos, _ = build_quartet(quartet(*GROUP_OPS, WEDGE, bad), quartet(*GROUP_OPS, WEDGE, bad))
    assert any(line.startswith("not built as the reply wrote it") for line in infos)
    infos.append("not built: op 5 ({'op': 'add_channel', 'name': 'Bongo', 'mode': 'loud'}): no such mode")
    plan["channels"] = [c for c in plan["channels"] if c["name"] != "Cello"]   # dropped silently
    plan["unassigned_inputs"] = []
    intent_build.declare_left_out(plan, intent_build.input_list.parse_input_list(csv), infos)
    assert plan["unassigned_inputs"] == [{"input": "Bongo"}]
    text = _verify_errors(tmp_path, plan, csv)
    assert "reconcile.dropped-input" in text and "Cello" in text


def test_a_row_the_engineers_words_leave_out_is_declared_with_those_words():
    csv = "patch,name,category,type,model,phantom,notes\n,Bongo,perc,Mic,,FALSE,\n,Lute,strings,DI,,FALSE,\n"
    reply = quartet({"op": "drop", "object": "channel", "name": "Bongo", "quote": "The bongo is not used tonight"})
    plan = intent_build.generate_plan("The bongo is not used tonight.\n", csv,
                                      provider=FakeProvider(response=json.dumps(reply)), console_model="wing-compact")
    assert plan["unassigned_inputs"] == [{"input": "Bongo", "quote": "The bongo is not used tonight",
                                          "from": "conventions"}]


# -- aux strips: a category the conventions put on Aux, and strips they ask for by name -------------

AUX_CSV = """patch,name,category,type,model,phantom,notes
,Fiddle,strings,Mic,,FALSE,
,Loop L,loops,Line,,FALSE,
,Loop R,loops,Line,,FALSE,
,Cue,loops,Line,,FALSE,
"""


def test_every_row_of_a_category_the_conventions_put_on_aux_is_an_aux_strip():
    rows = intent_build.input_list.parse_input_list(AUX_CSV)
    conventions = "Every loops-category input goes on an Aux channel.\n"
    reply = quartet({"op": "add_channel", "name": "Loop", "rows": ["Loop L", "Loop R"], "stereo": True})
    intent_, infos = intent_build.with_stated_aux(reply, rows, conventions)
    assert intent_["ops"] == [{"op": "add_channel", "name": "Loop", "rows": ["Loop L", "Loop R"], "stereo": True, "bank": "aux"},
                              {"op": "add_channel", "name": "Cue", "bank": "aux"}]
    assert "every loops-category input" in infos[0] and "'Loop'" in infos[0] and "'Cue'" in infos[0]
    plan = intent_build.generate_plan(conventions, AUX_CSV, provider=FakeProvider(response=json.dumps(reply)),
                                      console_model="wing-compact")
    assert {c["name"]: c.get("bank", "ch") for c in plan["channels"]} == {"Fiddle": "ch", "Loop": "aux", "Cue": "aux"}


def test_a_strip_the_conventions_ask_for_on_aux_by_name_is_asked_for_when_left_out():
    conventions = "## Aux Channels\n- Setup a DRONE box on Aux 3, source LCL 20.\n- Put the Cue on aux.\n"
    asked = intent_build.asked_strips(conventions)
    assert [(a.kind, a.name) for a in asked] == [("aux strip", "DRONE")]            # the second states no socket
    assert "the aux strip 'DRONE'" in intent_build.left_out(quartet(), asked)
    drone = {"op": "add_channel", "name": "DRONE", "bank": "aux", "place": {"at": 3}, "patch": {"group": "LCL", "first": 20}}
    assert intent_build.left_out(quartet(drone), asked) == ""


def test_aes50_written_out_is_read_as_the_desks_group():
    from atoo import intent, intent_schema
    said = []
    schema = intent_schema.intent_schema("wing-compact", build=True)
    raw = json.dumps(quartet({"op": "add_output", "object": "matrix", "name": "Delay",
                              "patch": {"group": "AES50-A", "first": 1, "count": 2}}))
    parsed, problem = intent.parse_intent(raw, schema, said)
    assert problem is None and parsed["ops"][0]["patch"]["group"] == "A" and "is the desk's A" in said[0]


def test_a_builds_wire_schema_bounds_notes_and_a_long_list_still_parses():
    """The grammar a host builds from the wire schema cannot loop in `notes` (checked on Ollama
    0.32.15: maxItems and an item's maxLength are enforced); what a reply is READ against keeps no
    bound, so a host with no grammar is never refused for writing more."""
    from atoo import intent, intent_schema
    schema = intent_schema.intent_schema("wing-compact", build=True)
    wire = intent_schema.wire_schema(schema)
    notes = wire["properties"]["notes"]
    assert notes["maxItems"] == intent_schema.NOTES_MAX and notes["items"]["maxLength"] == intent_schema.NOTE_MAX_CHARS
    assert "maxItems" not in schema["properties"]["notes"]
    many = quartet(*GROUP_OPS, notes=[f"note {k}: " + "x" * 600 for k in range(30)])
    parsed, problem = intent.parse_intent(json.dumps(many), schema)
    assert problem is None and len(parsed["notes"]) == 30


def test_the_build_sends_the_bounded_wire_schema_and_a_patch_does_not():
    from atoo import intent_schema

    class Seen(FakeProvider):
        def complete(self, **kw):
            self.calls.append(kw.get("response_schema"))
            return json.dumps(quartet(*GROUP_OPS, WEDGE))

    provider = Seen()
    intent_build.generate_plan(QUARTET, QUARTET_CSV, provider=provider, console_model="wing-compact")
    assert provider.calls[0]["properties"]["notes"]["maxItems"] == intent_schema.NOTES_MAX
    patch_wire = intent_schema.without_bounds(intent_schema.intent_schema("wing-compact"))
    assert "maxItems" not in patch_wire["properties"]["notes"]


EVEN_PAIR_CSV = """patch,name,category,type,model,phantom,notes
LCL 1,Bongo,perc,Mic,,FALSE,
LCL 2,Hum,misc,DI,,FALSE,
LCL 3,Fiddle,strings,Mic,,FALSE,
LCL 4,Lute L,strings,DI,,FALSE,
LCL 5,Lute R,strings,DI,,FALSE,
LCL 7,Harp L,strings,DI,,FALSE,
LCL 8,Harp R,strings,DI,,FALSE,
"""
EVEN_PAIR_RULE = "## Channels\nAny L/R pair of inputs becomes one stereo channel, named without the L/R.\n"


def _even_pair_build(csv=EVEN_PAIR_CSV, **kw):
    infos = []
    plan = intent_build.generate_plan(EVEN_PAIR_RULE, csv, provider=FakeProvider(response=json.dumps(quartet())),
                                      console_model="wing-compact", infos=infos, **kw)
    return plan, infos, {c["name"]: c["patch"] for c in plan["channels"]}


def test_a_stated_pair_the_desk_cannot_join_is_one_stereo_channel_through_a_user_patch(tmp_path):
    """Lute L/R are on LCL 4 and 5, which the desk cannot pair (a pair starts on an odd socket):
    the channel is patched through user patch USR 25-26, which take LCL 4 and LCL 5, said at INFO,
    as the compact path does. Harp L/R on LCL 7 and 8 pair directly."""
    plan, infos, patches = _even_pair_build()
    assert (patches["Lute"]["group"], patches["Lute"]["sockets"]) == ("USR", [25, 26])
    assert (patches["Harp"]["group"], patches["Harp"]["sockets"]) == ("LCL", [7, 8])
    assert "Lute L" not in patches and channel(plan, "Lute")["source"]["stereo"] is True
    assert plan["user_sources"] == [
        {"slot": 25, "name": "Lute", "source": {"group": "LCL", "index": 4}, "stated": False},
        {"slot": 26, "name": "Lute", "source": {"group": "LCL", "index": 5}, "stated": False}]
    assert any("'Lute' is patched through user patch USR 25-26, which take LCL 4 and LCL 5" in line
               for line in infos)
    text = _verify_errors(tmp_path, plan, EVEN_PAIR_CSV)
    assert "0 error(s)" in text, text


def test_apply_sends_a_routed_pairs_48v_to_its_jacks_on_a_plan_the_intent_built():
    from atoo import apply
    plan, _, _ = _even_pair_build(EVEN_PAIR_CSV.replace("Lute L,strings,DI,,FALSE", "Lute L,strings,DI,,TRUE")
                                  .replace("Lute R,strings,DI,,FALSE", "Lute R,strings,DI,,TRUE"))
    targets, warnings = apply._build_write_targets(plan, True)
    writes = {t.address: t.compute_value(None) for t in targets}
    ch = channel(plan, "Lute")["channel"]
    assert writes[f"/ch/{ch}/in/conn/grp"] == "USR" and writes[f"/ch/{ch}/in/conn/in"] == 25
    assert writes["/io/in/USR/25/user/grp"] == "LCL" and writes["/io/in/USR/25/user/in"] == 4
    assert writes["/io/in/USR/26/user/in"] == 5
    assert writes["/io/in/LCL/4/vph"] == writes["/io/in/LCL/5/vph"] == 1
    assert not [a for a in writes if a.startswith("/io/in/USR/") and a.endswith(("/vph", "/g"))]


def test_a_routed_pair_steps_round_user_csv_slots_and_with_none_free_is_two_mono_channels():
    _, _, patches = _even_pair_build(reserved_user_slots=(25, 26))
    assert (patches["Lute"]["group"], patches["Lute"]["sockets"]) == ("USR", [27, 28])
    plan, infos, patches = _even_pair_build(reserved_user_slots=tuple(range(25, 57)))
    assert patches["Lute"]["sockets"] == [4] and patches["Lute R"]["sockets"] == [5]
    assert "user_sources" not in plan
    assert any("no pair of user patch slots (USR 25-56) is free" in line
               and "built as two mono channels" in line for line in infos)


def test_a_colour_run_into_a_category_name_is_the_desks_colour_at_info():
    """Step 1's Category tables wrote "Drum-Red", "Kit-Lime": the last word is the desk's colour."""
    reply = quartet({"op": "add_channel", "name": "Fiddle", "color": "Keyboards-Amber"})
    reply["categories"] = [{"name": "Voices", "aliases": ["voice"], "color": "Drum-Red"}]
    intent_, infos = intent_build.with_reasonable_values(reply)
    assert intent_["categories"][0]["color"] == "Red" and intent_["ops"][0]["color"] == "Amber"
    assert any("'Drum-Red' is the desk's 'Red'" in line for line in infos)
    plan, _, _ = build_quartet(reply)
    assert channel(plan, "Singer")["color"] == "Red" and channel(plan, "Fiddle")["color"] == "Amber"


def test_a_colour_with_no_word_of_the_palette_stays_refused():
    from atoo import intent_build as ib
    assert ib.desk_colour("Kit-Mauve") is None and ib.desk_colour("Red") is None
    with pytest.raises(ic.IntentRefused, match="Kit-Mauve"):
        merged([{"op": "add_channel", "name": "Talkback", "color": "Kit-Mauve", "patch": {"group": "LCL", "first": 20}}])


def test_a_pair_the_conventions_keep_apart_stays_two_mono_channels_when_the_reply_joins_it():
    """'Fiddle L and Fiddle R stay two mono channels.' The reply joined them anyway, on sockets
    the desk could pair directly (LCL 5+6) and on ones it would route through a user patch (LCL
    4+5): either way they are two mono channels, the reply's join split at INFO, and a member
    named by the joined name names both."""
    joined = {"op": "add_channel", "name": "Fiddle", "rows": ["Fiddle L", "Fiddle R"], "stereo": True, "color": "Green"}
    dca = {"op": "add_group", "object": "dca", "name": "Strings", "members": {"channels": ["Fiddle"]}}
    for first in (5, 4):
        csv = ("patch,name,category,type,model,phantom,notes\n"
               f"LCL {first},Fiddle L,strings,Mic,,FALSE,\nLCL {first + 1},Fiddle R,strings,Mic,,FALSE,\n")
        rows = intent_build.input_list.parse_input_list(csv)
        intent_, infos = intent_build.with_stated_pairs(quartet(joined, dca), rows, PAIR_RULE)
        assert [op["name"] for op in intent_["ops"] if op["op"] == "add_channel"] == ["Fiddle L", "Fiddle R"]
        assert all("rows" not in op and op.get("color") == "Green" for op in intent_["ops"] if op["op"] == "add_channel")
        assert intent_["ops"][-1]["members"]["channels"] == ["Fiddle L", "Fiddle R"]
        assert "'Fiddle' (Fiddle L and Fiddle R) is two mono channels, as the conventions say; the reply joined them" in infos
        plan = intent_build.generate_plan(PAIR_RULE, csv, provider=FakeProvider(response=json.dumps(quartet(joined, dca))),
                                          console_model="wing-compact")
        patches = {c["name"]: (c["patch"]["group"], c["patch"]["sockets"]) for c in plan["channels"]}
        assert patches == {"Fiddle L": ("LCL", [first]), "Fiddle R": ("LCL", [first + 1])}
        assert "user_sources" not in plan


# -- a high-pass the conventions or a row's notes state for one channel -----------------------------

HPF_CSV = """patch,name,category,type,model,phantom,notes
,Kick,drums,Mic,,FALSE,
,Snare,drums,Mic,,FALSE,
,Tom,drums,Mic,,FALSE,
,Keys L,keys,DI,,FALSE,
,Keys R,keys,DI,,FALSE,
,Vox,vocals,Mic,,FALSE,HPF 150
,Loop,tracks,Line,,FALSE,
"""


def _stated_hpf(conventions, ops=()):
    rows = intent_build.input_list.parse_input_list(HPF_CSV)
    intent_, infos = intent_build.with_stated_hpf({"ops": [dict(op) for op in ops]}, rows, conventions)
    return {str(op.get("name")): op.get("hpf_hz") for op in intent_["ops"]}, infos


@pytest.mark.parametrize("line, want", [
    ("- Drums: HPF 80, except the kick at 40 Hz", {"Kick": 40}),
    ("Kick HPF 40, Snare HPF 100", {"Kick": 40, "Snare": 100}),
    ("Kick, snare and tom: high-pass 100", {"Kick": 100, "Snare": 100, "Tom": 100}),
    ("High-pass the kick at 50 and the snare at 120.", {"Kick": 50, "Snare": 120}),
    ("Low cut the tom at 1.2 kHz", {"Tom": 1200}),
    ("- Drums: high-pass 80 Hz", {}),                      # a category's: the Category table's
    ("- Drums: HPF 80, but not the kick", {}),
    ("Kick on LCL 3, snare at 2", {}),                      # no high-pass named on the line
])
def test_a_high_pass_the_conventions_state_for_a_channel_is_written_on_it(line, want):
    got, infos = _stated_hpf(line)
    assert {n: hz for n, hz in got.items() if n != "Vox"} == want
    assert all(any(f"{n!r} high-pass {hz:g} Hz" in i and repr(line.strip()[:100]) in i for i in infos)
               for n, hz in want.items())


def test_a_rows_notes_give_its_high_pass_and_win_over_the_conventions():
    got, infos = _stated_hpf("Vox: HPF 90")
    assert got["Vox"] == 150 and any("as its input-list notes state it: 'HPF 150'" in i for i in infos)


def test_a_pair_takes_the_high_pass_said_of_its_name_and_the_reply_s_own_value_stands():
    got, infos = _stated_hpf("Keys: high-pass at 60. Kick: HPF 40",
                             [{"op": "add_channel", "name": "Keys", "rows": ["Keys L", "Keys R"], "stereo": True},
                              {"op": "add_channel", "name": "Kick", "hpf_hz": 70}])
    assert got["Keys"] == 60 and got["Kick"] == 70
    assert [i for i in infos if "'Keys'" in i] == ["'Keys' high-pass 60 Hz, as the conventions state it: "
                                                   "'Keys: high-pass at 60. Kick: HPF 40'"]


def test_an_aux_strip_or_a_value_past_the_desk_gets_no_high_pass_said_at_info():
    got, infos = _stated_hpf("Loop: HPF 100. Tom: HPF 5000", [{"op": "add_channel", "name": "Loop", "bank": "aux"}])
    assert got["Loop"] is None and "Tom" not in got
    assert any("'Loop' gets no high-pass" in i and "an aux strip has no high-pass" in i for i in infos)
    assert any("'Tom' gets no high-pass of 5000 Hz" in i and "20 to 2000 Hz" in i for i in infos)


def test_a_build_carries_a_channels_stated_high_pass_the_reply_left_out():
    infos = []
    conventions = QUARTET + "## Channels\n- High-pass the fiddle at 120 Hz.\n"
    plan = intent_build.generate_plan(conventions, QUARTET_CSV,
                                      provider=FakeProvider(response=json.dumps(quartet(*GROUP_OPS, WEDGE))),
                                      console_model="wing-compact", infos=infos)
    assert channel(plan, "Fiddle")["processing"]["hpf_hz"] == 120
    assert channel(plan, "Cello")["processing"].get("hpf_hz") != 120
    assert any(line.startswith("'Fiddle' high-pass 120 Hz, as the conventions state it") for line in infos)


# -- an output socket claimed twice: one keeps it, the other moves to a free one -------------------

def _out(op):
    return (op.get("to") or {}).get("output") if op["op"] == "add_bus" else op.get("patch")


def _bus(name, group, first, count=1):
    return {"op": "add_bus", "name": name, "stereo": count == 2, "mode": "pre", "members": {"all": True},
            "to": {"output": {"group": group, "first": first, "count": count}}}


MAIN_LCL_1_2 = {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "LCL", "first": 1, "count": 2}}


def test_a_socket_only_the_reply_chose_earns_no_precedence_not_even_mains():
    """Monitors written in the buses step on LCL 1 and 2, and a Main the reply put on LCL 1-2 in
    the outputs step, with nothing the engineer wrote saying where Main goes: the monitors were
    written first and keep their sockets; Main's invented patch goes, said at INFO."""
    intent_, infos = intent_build.with_free_outputs(
        {"ops": [_bus("Mon 1", "LCL", 1), _bus("Mon 2", "LCL", 2), MAIN_LCL_1_2]}, [], "wing-compact")
    assert [_out(op) for op in intent_["ops"]] == [{"group": "LCL", "first": 1, "count": 1},
                                                   {"group": "LCL", "first": 2, "count": 1}, None]
    assert infos == ["'Main': the reply wrote LCL 1-2, which 'Mon 1' also uses; nothing the engineer "
                     "wrote puts it there, so it is left unpatched"]


def test_monitors_keep_their_sockets_when_the_conventions_give_main_no_output_and_the_reply_invents_one():
    conventions = ("## Busses\n" + "".join(f"- MON{k}: vocals, pre-fader, mono, its own output\n" for k in range(1, 5))
                   + "## Output\n- Main: Main has no physical output of its own; it only feeds Matrix 1\n")
    asked = intent_build.asked_for(conventions)
    mons = [_bus(f"MON{k}", "LCL", k) for k in range(1, 5)]
    intent_, infos = intent_build.with_free_outputs({"ops": [*mons, MAIN_LCL_1_2]}, asked, "wing-compact")
    assert [_out(op)["first"] for op in intent_["ops"][:4]] == [1, 2, 3, 4]
    assert "patch" not in intent_["ops"][4] and len(infos) == 1 and infos[0].startswith("'Main'")


def test_the_socket_the_conventions_state_is_kept_and_two_stated_ones_are_left_for_verify():
    asked = intent_build.asked_for("## Busses\n- Mon 1: vocals, pre-fader, routed to Local outputs 1\n"
                                   "## Output\n- Matrix: fed from Main\n")
    intent_, infos = intent_build.with_free_outputs({"ops": [MAIN_LCL_1_2, _bus("Mon 1", "LCL", 1)]},
                                                    asked, "wing-compact")
    assert _out(intent_["ops"][1]) == {"group": "LCL", "first": 1, "count": 1}
    assert "patch" not in intent_["ops"][0]       # Main came first, but only the reply put it there
    asked = intent_build.asked_for("## Busses\n- Mon 1: routed to Local outputs 1\n"
                                   "## Output\n- Main: routed to Local outputs 1-2\n")
    intent_, infos = intent_build.with_free_outputs({"ops": [_bus("Mon 1", "LCL", 1), MAIN_LCL_1_2]},
                                                    asked, "wing-compact")
    assert infos == [] and _out(intent_["ops"][0])["first"] == 1      # the engineer's own conflict


def test_two_buses_on_the_only_aes_pair_take_a_stage_box_the_list_uses_when_the_locals_are_full():
    rows = intent_build.input_list.parse_input_list(
        "patch,name,category,type,model,phantom,notes\nAES50-A 1,Kick,drums,Mic,,FALSE,\n")
    boxes = intent_build.stage_boxes(rows)
    assert boxes == ("A",)
    locals_ = [{"op": "add_output", "object": "matrix", "name": f"Fill {k}", "patch": {"group": "LCL", "first": k}}
               for k in range(1, 9)]
    intent_, infos = intent_build.with_free_outputs(
        {"ops": [*locals_, _bus("Lead IEM", "AES", 1, 2), _bus("Bass IEM", "AES", 1, 2)]}, [], "wing-rack", boxes)
    assert _out(intent_["ops"][-1]) == {"group": "A", "first": 1, "count": 2}
    assert "Atoo chose the lowest free one on the A stage box the input list already uses" in infos[0]
    # a socket that does not exist (AES 7 on a desk with AES 1-2) goes the same way, not refused
    intent_, infos = intent_build.with_stated_outputs(
        {"ops": [*locals_, _bus("Lead IEM", "AES", 1, 2), _bus("Bass IEM", "AES", 7, 2)]}, [], "wing-rack", boxes)
    assert _out(intent_["ops"][-1]) == {"group": "A", "first": 1, "count": 2}       # the lowest, not A 7


def test_an_output_on_a_socket_already_taken_is_left_unpatched_said_so():
    locals_ = [_bus(f"Mon {k}", "LCL", k) for k in range(1, 9)]
    clash = {"op": "add_output", "object": "matrix", "name": "Balcony", "patch": {"group": "LCL", "first": 2}}
    intent_, infos = intent_build.with_free_outputs({"ops": [*locals_, clash]}, [], "wing-compact")
    assert "patch" not in intent_["ops"][-1]
    assert infos == ["'Balcony': the reply wrote LCL 2, which 'Mon 2' also uses; nothing the engineer wrote "
                     "puts it there, so it is left unpatched"]


def test_a_build_moves_a_bus_off_the_socket_main_is_patched_to():
    infos = []
    side = {"op": "add_bus", "name": "Side Fill", "stereo": False, "mode": "pre", "members": {"all": True},
            "to": {"output": {"group": "LCL", "first": 2}}}
    conventions = QUARTET.replace("## Output", "- Side Fill: all channels, pre-fader, on its own output\n## Output")
    plan = intent_build.generate_plan(conventions, QUARTET_CSV,
                                      provider=FakeProvider(response=json.dumps(quartet(*GROUP_OPS, WEDGE, side))),
                                      console_model="wing-compact", infos=infos)
    sockets = plan["busses"]["Side Fill"]["destination"]["patch"]
    assert (sockets["group"], sockets["sockets"]) == ("LCL", [3])
    assert any(line.startswith("'Side Fill': the reply wrote LCL 2, which 'Main' also uses") for line in infos)


def test_an_output_that_repeats_a_bus_on_its_own_sockets_is_one_object_and_is_dropped():
    """A model wrote a monitor bus with its output in the buses step and an output of the same
    name on the same sockets in the outputs step: one object said twice, not two claimants, so
    nothing is moved for it (a second output would be built on a free socket)."""
    asked = intent_build.asked_for('## Busses\n- Drum IEM: drums, pre-fader, named "Drummer"\n')
    wedge = {"op": "add_bus", "name": "Drum IEM", "stereo": True, "mode": "pre", "members": {"all": True},
             "to": {"output": {"group": "A", "first": 9}}}
    again = {"op": "add_output", "object": "matrix", "name": "Drum IEM", "patch": {"group": "A", "first": 9, "count": 2}}
    alias = {**again, "name": "Drummer"}
    elsewhere = {**again, "name": "Drum IEM", "patch": {"group": "A", "first": 11, "count": 2}}
    for dup in (again, alias):
        intent_, infos = intent_build.with_free_outputs({"ops": [wedge, dup]}, asked, "wing-rack")
        assert intent_["ops"] == [wedge]
        assert infos[0].startswith(f"{dup['name']!r}: the reply made it as a bus with its output on A 9")
    intent_, infos = intent_build.with_free_outputs({"ops": [wedge, elsewhere]}, asked, "wing-rack")
    assert intent_["ops"] == [wedge, elsewhere] and infos == []      # another socket: not this case


# -- a strip the conventions ask for by name on an Aux strip, with its source ----------------------

ASKED_STRIPS = ('## Aux Channels\n- Setup CUE on Aux 5, source LCL 18 if available.\n'
                '- Setup a JINGLES playback on Aux 1, source LCL 15-16.\n'
                '- Setup ANNOUNCER mic on Aux 3, Preset "Voice Plain", Source LCL 12.\n')


def test_a_strip_the_conventions_ask_for_on_an_aux_strip_is_filled_by_code_when_the_reply_leaves_it_out():
    rows = intent_build.input_list.parse_input_list(QUARTET_CSV)
    made = {"op": "add_channel", "name": "Cue", "bank": "aux", "place": {"at": 6}, "patch": {"group": "LCL", "first": 19}}
    intent_, infos = intent_build.with_asked_strips(quartet(made), ASKED_STRIPS, rows)
    assert intent_["ops"][0] == made                                   # the reply's own stands
    assert intent_["ops"][1:] == [
        {"op": "add_channel", "name": "JINGLES", "bank": "aux", "place": {"at": 1},
         "patch": {"group": "LCL", "first": 15, "count": 2}, "stereo": True},
        {"op": "add_channel", "name": "ANNOUNCER", "bank": "aux", "place": {"at": 3},
         "patch": {"group": "LCL", "first": 12, "count": None}, "preset": "Voice Plain"}]
    assert infos[0] == ("'JINGLES' on Aux 1, source LCL 15-16, filled by code: the conventions say "
                        "'Setup a JINGLES playback on Aux 1, source LCL 15-16.' and the reply did not make it")


def test_a_build_makes_the_aux_strips_the_conventions_ask_for_that_the_reply_left_out():
    infos = []
    conventions = QUARTET + ASKED_STRIPS.replace(', Preset "Voice Plain"', "")
    plan = intent_build.generate_plan(conventions, QUARTET_CSV,
                                      provider=FakeProvider(response=json.dumps(quartet(*GROUP_OPS, WEDGE))),
                                      console_model="wing-compact", infos=infos)
    aux = {c["name"]: (c["channel"], c["patch"]["group"], c["patch"]["sockets"])
           for c in plan["channels"] if c.get("bank") == "aux"}
    assert aux == {"CUE": (5, "LCL", [18]), "JINGLES": (1, "LCL", [15, 16]), "ANNOUNCER": (3, "LCL", [12])}
    assert channel(plan, "JINGLES")["source"]["stereo"] is True
    assert sum("filled by code" in line and "Aux" in line for line in infos) == 3


def test_a_stated_high_pass_the_category_table_already_gives_is_left_alone_with_nothing_said():
    """'Bass channels get a high-pass at 35Hz' names the Bass row too; when the reply's Category
    table already gives the bass category 35 Hz, nothing is corrected, so nothing is said."""
    rows = intent_build.input_list.parse_input_list(
        "patch,name,category,type,model,phantom,notes\n,Bass,bass,DI,,FALSE,\n,Keys,keys,DI,,FALSE,\n")
    table = [{"name": "Bass", "aliases": ["bass"], "hpf_hz": 35}]
    line = "Bass channels get a high-pass at 35Hz. Keys: HPF 60."
    intent_, infos = intent_build.with_stated_hpf({"ops": [], "categories": table}, rows, line)
    assert [op["name"] for op in intent_["ops"]] == ["Keys"] and len(infos) == 1
    table[0]["hpf_hz"] = 40                                   # the table says otherwise: the line wins
    intent_, infos = intent_build.with_stated_hpf({"ops": [], "categories": table}, rows, line)
    assert {op["name"]: op["hpf_hz"] for op in intent_["ops"]} == {"Bass": 35, "Keys": 60}


# -- rows with no socket, more than the local inputs hold ------------------------------------------

def _rows_csv(n):
    return "patch,name,category,type,model,phantom,notes\n" + "".join(f",Mic {k},misc,Mic,,FALSE,\n" for k in range(1, n + 1))


OVERFLOW = "If the input list gives no socket for a row, patch to local inputs 1-24, then overflow to AES50-B from 1.\n"


def test_rows_with_no_socket_overflow_to_the_stage_box_the_conventions_name_for_inputs():
    """25 rows and a WING Compact's 24 local inputs: the 25th goes to AES50-B, which the
    conventions name for inputs. An aux strip's stated socket (LCL 24) is held for it first."""
    assert ic.input_boxes(OVERFLOW + "Matrix out on AES50-C 3.\n", None) == ("B",)
    conventions = OVERFLOW + "## Aux Channels\n- Setup CUE on Aux 5, source LCL 24.\n"
    plan = intent_build.generate_plan(conventions, _rows_csv(25), provider=FakeProvider(response=json.dumps(quartet())),
                                      console_model="wing-compact")
    patches = {c["name"]: (c["patch"]["group"], c["patch"]["sockets"]) for c in plan["channels"]}
    assert patches["CUE"] == ("LCL", [24])
    assert sorted(s for g, ss in patches.values() if g == "LCL" for s in ss) == list(range(1, 25))
    assert [name for name, (g, _) in patches.items() if g == "B"] == ["Mic 24", "Mic 25"]


def test_a_group_stands_without_a_member_the_build_could_not_make():
    """No box is named, so the 25th row has no socket and is not built; the DCA that names it
    with another channel is built with the other, said at INFO, not lost with it."""
    infos = []
    dca = {"op": "add_group", "object": "dca", "name": "Mics", "members": {"channels": ["Mic 24", "Mic 25"]}}
    plan = intent_build.generate_plan("## DCAs\n- Mics: Mic 24 and Mic 25\n", _rows_csv(25),
                                      provider=FakeProvider(response=json.dumps(quartet(dca))),
                                      console_model="wing-compact", infos=infos)
    assert "Mic 25" not in {c["name"] for c in plan["channels"]}
    assert "Mics" in plan["dcas"] and channel(plan, "Mic 24")["dca"] == ["Mics"]
    assert any(line == "dca 'Mics' is built without 'Mic 25', which is not a channel of the show" for line in infos)


# -- a per-channel setting stated for one side of a pair the reply joined ---------------------------

CYMBALS_CSV = """patch,name,category,type,model,phantom,notes
,Kick,drums,Mic,,FALSE,
,Cymbals Left,drums,Mic,,TRUE,
,Cymbals Right,drums,Mic,,TRUE,
"""
JOINED = {"op": "add_channel", "name": "Cymbals", "rows": ["Cymbals Left", "Cymbals Right"], "stereo": True}
DRUMS = {"op": "add_group", "object": "dca", "name": "Drums", "members": {"channels": ["Kick", "Cymbals"]}}


def test_a_high_pass_stated_for_one_side_keeps_a_joined_pair_two_mono_channels():
    """Nothing pairs the cymbals, and the reply joined them; the conventions high-pass the left one
    only, which one stereo channel cannot carry, so they are two mono channels, said at INFO."""
    rows = intent_build.input_list.parse_input_list(CYMBALS_CSV)
    intent_, infos = intent_build.with_stated_hpf(quartet(JOINED, DRUMS), rows, "High-pass Cymbals Left at 30Hz.")
    channels = {op["name"]: op.get("hpf_hz") for op in intent_["ops"] if op["op"] == "add_channel"}
    assert channels == {"Cymbals Left": 30, "Cymbals Right": None}
    assert intent_["ops"][-1]["members"]["channels"] == ["Kick", "Cymbals Left", "Cymbals Right"]
    assert ("'Cymbals' (Cymbals Left and Cymbals Right) is two mono channels: a high-pass is stated for "
            "'Cymbals Left' only, which one stereo channel cannot carry") in infos
    # the same value for both sides is one stereo channel's to carry: the pair stands
    intent_, _ = intent_build.with_stated_hpf(quartet(JOINED), rows, "High-pass the cymbals at 30Hz.")
    assert [(op["name"], op.get("hpf_hz")) for op in intent_["ops"]] == [("Cymbals", 30)]
    plan = intent_build.generate_plan("## Channels\nHigh-pass Cymbals Left at 30Hz.\n", CYMBALS_CSV,
                                      provider=FakeProvider(response=json.dumps(quartet(JOINED))),
                                      console_model="wing-compact")
    assert {c["name"]: c["processing"].get("hpf_hz") for c in plan["channels"]
            if c["name"].startswith("Cymbals")} == {"Cymbals Left": 30, "Cymbals Right": None}


# -- an output socket stated in a line that is not an item of a bus or output section --------------

LINE_CONVENTIONS = """## Monitors
- Vocal Wdg: a mono wedge for the singer. It goes out on AES50-A outputs 1.
- Drum Wdg: the drummer's wedge, on Local outs 3.
## PA
Main goes to Local outputs 5-6. The Balcony fill feeds on Local outputs 2.
## Groups
- Kick Bus: drums channels route to bus pre-fader, bus routes to Local outputs 4.
"""


def test_a_socket_stated_in_a_line_that_names_the_object_is_carried_out():
    """Neither 'Monitors' nor 'PA' is a heading Atoo reads as a bus or output section, so no item
    states these sockets; the lines that name each object do, and each is carried out at INFO."""
    asked = intent_build.asked_for(LINE_CONVENTIONS)
    ops = [_bus("Vocal Wdg", "AES", 1), _bus("Drum Wdg", "LCL", 4),
           {"op": "add_output", "object": "main", "name": "Main", "patch": {"group": "LCL", "first": 1, "count": 2}},
           {"op": "add_output", "object": "matrix", "name": "Balcony"}]
    intent_, infos = intent_build.with_stated_outputs({"ops": ops}, asked, "wing-rack", (), LINE_CONVENTIONS)
    assert [_out(op) for op in intent_["ops"]] == [
        {"group": "A", "first": 1, "count": 1}, {"group": "LCL", "first": 3, "count": 1},
        {"group": "LCL", "first": 5, "count": 2}, {"group": "LCL", "first": 2, "count": None}]
    assert any(line.startswith("'Vocal Wdg': the reply wrote AES 1") and "A 1 stands" in line for line in infos)
    assert any(line.startswith("'Balcony' patched to LCL 2, filled by code") for line in infos)


def test_a_name_used_as_a_category_or_in_another_objects_item_is_not_that_objects_socket():
    asked = intent_build.asked_for(LINE_CONVENTIONS)
    drums = {"op": "add_bus", "name": "Drums", "stereo": True, "mode": "post", "members": {"all": True}}
    intent_, infos = intent_build.with_stated_outputs({"ops": [drums]}, asked, "wing-rack", (), LINE_CONVENTIONS)
    assert intent_["ops"] == [drums] and infos == []      # "drums channels ... Local outputs 4" is Kick Bus's


def test_main_s_socket_stated_in_a_sentence_is_filled_when_the_reply_leaves_main_unpatched():
    intent_, said = intent_build.with_main({"ops": []}, intent_build.asked_for(LINE_CONVENTIONS), LINE_CONVENTIONS)
    assert intent_["ops"] == [{"op": "add_output", "object": "main", "name": "Main",
                               "patch": {"group": "LCL", "first": 5, "count": 2}}]
    assert said.startswith("Main patched to LCL 5-6, filled by code")


@pytest.mark.parametrize("text, want", [
    ("Patch output to local XLR outputs 1 through 4", {"group": "LCL", "first": 1, "count": None}),
    ("it goes out on AES50-A outputs 1", {"group": "A", "first": 1, "count": None}),
    ("feeds on Local outs 7 and 8", {"group": "LCL", "first": 7, "count": 2}),
    ("on USB output #3", {"group": "USB", "first": 3, "count": None}),
])
def test_output_sockets_in_the_ways_an_engineer_writes_them(text, want):
    assert intent_build.stated_sockets(intent_build.AskedFor("bus", "X", (), text)) == want


# -- a strip order the conventions state by category -------------------------------------------

ORDER_CSV = """patch,name,category,type,model,phantom,notes
,Thud,Kit,Mic,Beta 91A,TRUE,
,Crack,Kit,Mic,SM57,FALSE,
,Low End,Bass,DI,J48,TRUE,
,Twang,Gtrs,Mic,SM57,FALSE,
,Ivy,Vox,Mic,SM58,FALSE,
,Rowan,Vox,Mic,SM58,FALSE,
"""


def by_strip(plan):
    return [c["name"] for c in sorted(plan["channels"], key=lambda c: c["channel"])]


def build_ordered(conventions, *ops):
    infos: list[str] = []
    reply = {"name": "Build the trio", "ops": list(ops), "notes": [], "categories": []}
    plan = intent_build.generate_plan(conventions, ORDER_CSV, provider=FakeProvider(response=json.dumps(reply)),
                                      console_model="wing-compact", infos=infos)
    return plan, infos


def test_a_stated_category_order_in_other_words_than_the_lists_lays_the_strips_out_that_way():
    plan, infos = build_ordered("## Inputs\nPatch order: voice then guitars then drums then bass.\n")
    assert by_strip(plan) == ["Ivy", "Rowan", "Twang", "Thud", "Crack", "Low End"]
    said = [i for i in infos if i.startswith("the strips are laid out by category")]
    assert said == ["the strips are laid out by category as the conventions state ('Patch order: voice then "
                    "guitars then drums then bass.'): Vox, Gtrs, Kit, Bass, filled by code; the reply wrote no order"]


def test_a_reply_order_that_misses_a_stated_category_is_replaced_and_its_order_within_one_is_kept():
    reply_order = {"op": "order", "categories": ["voice", "drums"], "channels": ["Rowan"]}
    plan, infos = build_ordered("Strip order: vocals > drums > bass > guitars.\n", reply_order)
    assert by_strip(plan) == ["Rowan", "Ivy", "Thud", "Crack", "Low End", "Twang"]
    assert any(i.endswith("the reply's order was voice, drums") for i in infos)


def test_band_then_vocals_puts_every_other_category_first_in_the_lists_order():
    plan, _ = build_ordered("Order on the desk: band, then vocals.\n")
    assert by_strip(plan) == ["Thud", "Crack", "Low End", "Twang", "Ivy", "Rowan"]


def test_an_order_written_in_a_sentence_is_read_and_an_unnamed_category_goes_last():
    plan, _ = build_ordered("We keep it simple. The channel order is vocals, then bass, then kit. Colours as usual.\n")
    assert by_strip(plan) == ["Ivy", "Rowan", "Low End", "Thud", "Crack", "Twang"]


def test_a_reply_order_that_already_matches_is_kept_and_nothing_is_said():
    reply_order = {"op": "order", "categories": ["Vox", "Kit", "Bass", "Gtrs"]}
    intent_, infos = intent_build.with_stated_order(
        {"ops": [reply_order], "categories": []}, "Patch order: vox, drums, bass, guitars.",
        intent_build.input_list.parse_input_list(ORDER_CSV))
    assert intent_["ops"] == [reply_order] and infos == []


def test_a_line_that_orders_channels_not_categories_leaves_the_replys_order():
    rows = intent_build.input_list.parse_input_list(ORDER_CSV)
    for conventions in ("Order on the desk: Thud, Crack, Ivy.", "Channel order: follow the input list.",
                        "The strip order matters to us."):
        intent_, infos = intent_build.with_stated_order({"ops": [], "categories": []}, conventions, rows)
        assert intent_["ops"] == [] and infos == [], conventions


def test_a_stated_word_is_read_through_a_category_table_entry_before_its_family():
    rows = intent_build.input_list.parse_input_list(ORDER_CSV)
    table = [{"name": "Singers", "aliases": ["Vox"]}, {"name": "Rhythm", "aliases": ["Kit", "Bass"]}]
    intent_, _ = intent_build.with_stated_order({"ops": [], "categories": table},
                                                "Patch order: singers, rhythm, guitars.", rows)
    assert intent_["ops"] == [{"op": "order", "categories": ["Vox", "Kit", "Bass", "Gtrs"]}]
