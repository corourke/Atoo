"""A stereo pair cabled where the desk cannot pair it, built through two
USER PATCH slots.

The desk forms a stereo pair only from two consecutive sockets of one group,
odd first. An input list whose L/R rows state LCL 4 and LCL 5, A 16 and
A 17, or one socket in each of two groups, could not be one channel. Build
now patches the channel to the first free pair of USER PATCH slots (USR 25
to 56, odd first), each slot taking one row's socket, and says so at INFO.
With no pair free, the two rows are built as two mono channels, also at
INFO. Apply's phantom and head-amp gain follow each slot to its jack.

Every input list here is built in the test, from a scripted reply.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from atoo import apply, cli, console_facts as facts, generate, plan_schema
from atoo.ai_provider import FakeProvider
from atoo.input_list import parse_input_list, parse_socket_spec
from atoo.render import render_plan
from atoo.schema_check import validate
from atoo.verify_plan import verify_plan

MODELS = sorted(facts.CONSOLE_MODELS)


def _csv(left: str, right: str) -> str:
    return ("patch,name,category,type,model,phantom\n"
            "LCL 1,Vox,vocals,Mic,SM58,FALSE\n"
            f"{left},Keys L,keys,DI,,TRUE\n"
            f"{right},Keys R,keys,DI,,TRUE\n")


def _build(csv_text: str, model: str = "wing-compact", reserved=()) -> tuple[dict, list]:
    reply = {"channels": [{"input": "Vox"},
                          {"input": "Keys L", "pair": "Keys R", "name": "Keys",
                           "processing": {"gain_db": 12}}],
             "busses": [], "outputs": [], "dcas": [], "mute_groups": []}
    findings: list = []
    plan = generate.generate_plan("Conventions.\n", csv_text,
                                  provider=FakeProvider(response=json.dumps(reply)),
                                  console_model=model, findings=findings,
                                  reserved_user_slots=reserved)
    return plan, findings


def _keys(plan: dict) -> dict:
    return next(c for c in plan["channels"] if c["source"]["input"] == "Keys L")


def _codes(findings, code: str) -> list:
    return [f for f in findings if f.code == code]


def _problems(plan: dict, csv_text: str, model: str) -> list:
    result = verify_plan(plan, parse_input_list(csv_text), console_model=model)
    return [f for f in result.findings
            if f.severity != "info" and f.code != "routing.channel-reaches-nothing"]


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("left,right,why", [
    ("LCL 4", "LCL 5", "the pair starts on 4, an even socket"),
    ("AES50-A 16", "AES50-A 17", "the pair starts on 16, an even socket"),
    ("AES50-A 3", "AES50-A 7", "3 and 7 are not consecutive"),
    ("AES50-A 16", "AES50-B 1", "they are in two socket groups"),
])
def test_a_pair_the_desk_cannot_form_is_one_channel_through_a_user_patch(model, left, right,
                                                                         why):
    csv_text = _csv(left, right)
    plan, findings = _build(csv_text, model)
    keys = _keys(plan)
    assert keys["patch"] == {"group": "USR", "sockets": [25, 26], "stated": True}
    assert keys["source"]["stereo"] is True and keys["source"]["pair_input"] == "Keys R"
    jacks = [parse_socket_spec(left), parse_socket_spec(right)]
    assert plan["user_sources"] == [
        {"slot": 25, "name": "Keys", "source": {"group": jacks[0][0], "index": jacks[0][1]},
         "stated": False},
        {"slot": 26, "name": "Keys", "source": {"group": jacks[1][0], "index": jacks[1][1]},
         "stated": False},
    ]
    assert len(plan["channels"]) == 2
    (said,) = _codes(findings, "reply.pair-through-user-patch")
    assert why in said.message
    assert f"'Keys L' ({left}) and 'Keys R' ({right}) can't be one stereo pair" in said.message
    assert f"patched through user patch USR 25-26, which take {left} and {right}" in said.message
    assert validate(plan, plan_schema.PLAN_SCHEMA) == []
    assert _problems(plan, csv_text, model) == []


def test_a_pair_the_desk_can_form_stays_a_direct_patch():
    plan, findings = _build(_csv("LCL 3", "LCL 4"))
    assert _keys(plan)["patch"] == {"group": "LCL", "sockets": [3, 4], "stated": True}
    assert "user_sources" not in plan
    assert not _codes(findings, "reply.pair-through-user-patch")


def test_the_slots_step_round_the_ones_user_csv_names():
    plan, _ = _build(_csv("LCL 4", "LCL 5"), reserved={25, 28})
    assert _keys(plan)["patch"]["sockets"] == [29, 30]
    assert [e["slot"] for e in plan["user_sources"]] == [29, 30]


def test_with_no_pair_of_slots_free_the_rows_are_two_mono_channels():
    csv_text = _csv("LCL 4", "LCL 5")
    low, high = facts.USER_PATCH_SLOTS
    plan, findings = _build(csv_text, reserved=set(range(low, high + 1)))
    assert "user_sources" not in plan
    by_input = {c["source"]["input"]: c for c in plan["channels"]}
    assert by_input["Keys L"]["patch"] == {"group": "LCL", "sockets": [4], "stated": True}
    assert by_input["Keys L"]["source"]["stereo"] is False
    assert by_input["Keys R"]["patch"]["group"] == "LCL"
    assert by_input["Keys R"]["patch"]["sockets"] == [5]
    (said,) = _codes(findings, "reply.pair-split")
    assert "no pair of user patch slots (USR 25-56) is free" in said.message
    assert "built as two mono channels" in said.message
    assert _problems(plan, csv_text, "wing-compact") == []


def _writes(plan: dict) -> tuple[dict, list]:
    targets, warnings = apply._build_write_targets(plan, True)
    return {t.address: t.compute_value(None) for t in targets}, warnings


@pytest.mark.parametrize("model", MODELS)
def test_apply_writes_the_slots_and_sends_48v_and_gain_to_the_jacks(model):
    plan, _ = _build(_csv("LCL 4", "LCL 5"), model)
    writes, warnings = _writes(plan)
    assert warnings == []
    assert writes["/io/in/USR/25/user/grp"] == "LCL" and writes["/io/in/USR/25/user/in"] == 4
    assert writes["/io/in/USR/26/user/grp"] == "LCL" and writes["/io/in/USR/26/user/in"] == 5
    assert writes["/io/in/USR/25/mode"] == "ST"
    assert writes["/io/in/USR/25/name"] == writes["/io/in/USR/26/name"] == "Keys"
    ch = _keys(plan)["channel"]
    assert writes[f"/ch/{ch}/in/conn/grp"] == "USR" and writes[f"/ch/{ch}/in/conn/in"] == 25
    # Phantom and gain live on the jack, not on the slot.
    assert writes["/io/in/LCL/4/vph"] == writes["/io/in/LCL/5/vph"] == 1
    assert writes["/io/in/LCL/4/g"] == writes["/io/in/LCL/5/g"] == 12
    assert not [a for a in writes if a.startswith("/io/in/USR/") and a.endswith(("/vph", "/g"))]


def test_releasing_the_channel_switches_phantom_off_on_the_jacks():
    from atoo import inferred

    plan, _ = _build(_csv("LCL 4", "LCL 5"))
    targets = apply.release_write_targets([_keys(plan)],
                                          user_jacks=inferred.user_patch_jacks(plan))
    off = {t.address: t.compute_value(None) for t in targets if t.address.endswith("/vph")}
    assert off == {"/io/in/LCL/4/vph": 0, "/io/in/LCL/5/vph": 0}


def test_verify_reads_the_jack_through_the_slot():
    """The stated socket is checked against the jack each slot takes: a
    slot moved to another jack contradicts the list."""
    csv_text = _csv("LCL 4", "LCL 5")
    plan, _ = _build(csv_text)
    plan["user_sources"][1]["source"]["index"] = 6
    codes = [f.code for f in _problems(plan, csv_text, "wing-compact")]
    assert "patch.contradicts-input-list" in codes


def test_the_summary_names_the_jacks():
    plan, _ = _build(_csv("LCL 4", "LCL 5"))
    assert "Patch: USR 25-26 (LCL 4 + LCL 5)" in render_plan(plan, [])


def test_build_reserves_the_slots_the_shows_user_csv_names(tmp_path):
    (tmp_path / "user.csv").write_text("slot,source,tap,leg,name\nUSR 25,LCL 9,,,Spare\n"
                                       "USR 27,OFF,,,\n", encoding="utf-8")
    assert cli._user_sheet_slots(SimpleNamespace(directory=tmp_path)) == {25, 27}
    assert cli._user_sheet_slots(SimpleNamespace(directory=tmp_path / "none")) == set()
    assert cli._user_sheet_slots(None) == set()


def _build_split(csv_text: str) -> tuple[dict, list]:
    """The reply the Compact sitting's first build got: the model left the
    pair as two mono channels, citing the odd-first rule."""
    reply = {"channels": [{"input": "Vox"}, {"input": "Keys L"}, {"input": "Keys R"}],
             "busses": [], "outputs": [], "dcas": [], "mute_groups": []}
    findings: list = []
    plan = generate.generate_plan("Conventions.\n", csv_text,
                                  provider=FakeProvider(response=json.dumps(reply)),
                                  console_model="wing-compact", findings=findings)
    return plan, findings


def test_a_pair_the_reply_split_over_its_sockets_is_paired_by_code():
    """The pair is code's decision, not the model's."""
    csv_text = _csv("LCL 4", "LCL 5")
    plan, findings = _build_split(csv_text)
    keys = [c for c in plan["channels"] if c["source"]["input"] in ("Keys L", "Keys R")]
    assert len(keys) == 1
    assert keys[0]["name"] == "Keys" and keys[0]["source"]["pair_input"] == "Keys R"
    assert keys[0]["patch"] == {"group": "USR", "sockets": [25, 26], "stated": True}
    (said,) = _codes(findings, "reply.pair-by-names")
    assert said.message.startswith("'Keys L' and 'Keys R' are one L/R pair by their names")
    assert _codes(findings, "reply.pair-through-user-patch")
    assert _problems(plan, csv_text, "wing-compact") == []


def test_two_mono_channels_on_a_pair_the_desk_could_form_are_the_replys_choice():
    plan, findings = _build_split(_csv("LCL 3", "LCL 4"))
    assert len([c for c in plan["channels"] if c["source"]["input"].startswith("Keys")]) == 2
    assert not _codes(findings, "reply.pair-by-names")


def test_the_build_command_says_how_a_pair_was_built(tmp_path, monkeypatch, capsys):
    """The notes were in plan.json and not on the
    console, where the sitting looked for them."""
    from atoo.cli import main

    show = tmp_path / "show"
    show.mkdir()
    (show / "input.csv").write_text(_csv("LCL 4", "LCL 5"))
    reply = {"channels": [{"input": "Vox"}, {"input": "Keys L"}, {"input": "Keys R"}],
             "busses": [], "outputs": [], "dcas": [], "mute_groups": []}
    monkeypatch.setattr("atoo.cli.provider_from_env",
                        lambda: FakeProvider(response=json.dumps(reply)))
    conventions = tmp_path / "house.md"
    conventions.write_text("Conventions.\n")
    main(["build", "--console-model", "wing-compact", "--show", str(show),
          "--conventions", str(conventions)])
    out = capsys.readouterr()
    text = " ".join((out.out + out.err).split())  # the notes wrap
    assert "Stereo pairs -- 2 note(s)" in text, text
    assert "'Keys L' and 'Keys R' are one L/R pair by their names" in text
    assert "patched through user patch USR 25-26" in text
