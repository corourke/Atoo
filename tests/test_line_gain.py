"""A Line source on a head amp does not keep a mic's gain.

A change moved a playback feed (type Line) onto a stage box's mic preamp and
the model kept "gain 20 dB, as on the other channels" -- a mic's gain on a
line-level source, which clips the preamp. The type drives the gain: a Line
source takes a line gain unless the gain was stated for it, and the choice
is said at INFO, in Build and in Patch alike (`inferred.settle_line_gain`).

Every plan and input list here is built in the test (nothing reads
`examples/`).
"""

from __future__ import annotations

import json

import pytest

from atoo import generate, inferred, patch
from atoo.ai_provider import FakeProvider
from atoo.amend import ChangeKind
from test_amend import applied_plan, horn, occupancy_state  # noqa: E402
from atoo.amend import strip_occupancy


def _channel(kind="Line", group="A", gain=20, name="Playback", provenance=None) -> dict:
    return {"channel": 5, "bank": "ch", "name": name,
            "source": {"input": name, "type": kind, "model": None, "stereo": False,
                       "phantom": False},
            "patch": {"group": group, "sockets": [16], "stated": True},
            "processing": {"gain_db": gain}, "fader": {}, "dca": [], "mute_group": [],
            "bus_sends": [], "main_routes": [], "provenance": provenance or {}}


# ------------------------------------------------------------ the rule itself


def test_a_line_source_on_a_head_amp_takes_a_line_gain_and_says_so():
    channel = _channel()
    said = inferred.settle_line_gain(channel)
    assert channel["processing"]["gain_db"] == inferred.LINE_GAIN_DB == 0.0
    assert "'Playback'" in said and "A 16" in said and "20 dB" in said and "0 dB" in said
    assert "line-level" in said and "gain 6 dB" in said
    assert "chosen because the source is line level" in channel["provenance"]["processing"]


@pytest.mark.parametrize("channel,why", [
    (_channel(kind="Mic"), "a mic keeps its gain"),
    (_channel(kind="DI"), "a DI is not read as line level"),
    (_channel(gain=6), "within the line ceiling"),
    (_channel(gain=10), "the ceiling itself is kept"),
    (_channel(gain=None), "an unset gain leaves the head amp as the desk had it"),
    (_channel(group="USB"), "a digital source has no head amp"),
    (_channel(group="LCL", gain=20, kind="line level"), None),
])
def test_what_the_rule_leaves_alone(channel, why):
    before = json.loads(json.dumps(channel))
    said = inferred.settle_line_gain(channel)
    if why is None:                       # a spelling of Line it does read
        assert said and channel["processing"]["gain_db"] == 0.0
    else:
        assert said is None, why
        assert channel == before


def test_a_gain_stated_for_the_channel_is_kept():
    channel = _channel()
    assert inferred.settle_line_gain(channel, stated=True) is None
    assert channel["processing"]["gain_db"] == 20


BLANKET = ("Unless overridden by the show instructions, set the input (head-amp) gain on each "
           "channel to 20dB, and the Trim to 0dB.")


@pytest.mark.parametrize("cited,texts,stated", [
    ("category table: Playback: gain 20 dB", (), True),
    (f"Processing: {BLANKET!r} (Playback)", (), False),   # the model's say-so is not a statement
    ("", (BLANKET,), True),                                 # the engineer's blanket line is
    ("", ("Playback gain 15 dB",), True),
    ("", ("Kick: gain 12 dB",), True),                      # a gain stated anywhere stands
    ("", ("Kick gets a high-pass at 80Hz",), False),
    ("", (), False),
])
def test_a_gain_is_stated_when_the_conventions_say_gain_anywhere(cited, texts, stated):
    channel = _channel(provenance={"processing": cited} if cited else {})
    assert inferred.gain_stated_for(channel, texts) is stated


# ------------------------------------------------------------------- Build

ROWS = ("patch,name,category,type,model,phantom,notes\n"
        "AES50-A 1,Kick,drums,Mic,Beta91,FALSE,\n"
        "AES50-A 16,Playback,tracks,Line,,FALSE,\n")


def _build(reply_channels, csv=ROWS, conventions="conventions"):
    reply = {"channels": reply_channels, "dcas": [], "mute_groups": [], "busses": [],
             "outputs": [{"name": "Main", "kind": "main",
                          "patch": {"group": "LCL", "sockets": [7, 8]}}],
             "unassigned_inputs": [], "notes": []}
    findings: list = []
    plan = generate.generate_plan(conventions, csv,
                                  provider=FakeProvider(response=json.dumps(reply)),
                                  console_model="wing-compact", findings=findings)
    return ({c["name"]: c for c in plan["channels"]},
            [f for f in findings if f.code == "reply.line-gain"])


def test_build_does_not_copy_a_mic_gain_onto_a_line_source():
    channels, infos = _build([
        {"input": "Kick", "name": "Kick", "processing": {"gain_db": 20}},
        {"input": "Playback", "name": "Playback", "processing": {"gain_db": 20}}])
    assert channels["Kick"]["processing"]["gain_db"] == 20
    assert channels["Playback"]["processing"]["gain_db"] == 0.0
    [info] = infos
    assert info.severity.value == "info" and "'Playback'" in info.message
    assert "20 dB" in info.message and info.where == "channels[Playback]"


def test_build_says_nothing_when_nothing_was_copied():
    channels, infos = _build([
        {"input": "Kick", "name": "Kick", "processing": {"gain_db": 20}},
        {"input": "Playback", "name": "Playback", "processing": {"gain_db": 0}}])
    assert infos == [] and channels["Playback"]["processing"]["gain_db"] == 0


# ------------------------------------------------------------------- Patch


def _review(text, channel):
    plan = applied_plan()
    change_set = patch.empty_change_set("Playback")
    change_set["add"]["channels"] = [channel]
    occupancy = strip_occupancy(occupancy_state(theirs=()), plan)
    return patch.plan_patch(plan, change_set, occupancy, console_model="wing-compact", text=text)


def _playback(gain, group="A", socket=30):
    channel = horn(30, "Playback", socket)
    channel["source"].update({"type": "Line", "input": "Playback"})
    channel["patch"] = {"group": group, "sockets": [socket], "stated": True}
    channel["processing"]["gain_db"] = gain
    channel["dca"], channel["mute_group"], channel["bus_sends"] = [], [], []
    return channel


def test_patch_does_not_copy_a_mic_gain_onto_a_line_source_moved_to_a_head_amp():
    amendment, _ = _review("Move Playback to channel 30 and input A 30 (make it mono)",
                           _playback(20))
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "Playback"]
    assert added["processing"]["gain_db"] == 0.0
    [info] = [i for i in amendment.infos if "a Line source" in i]
    assert "A 30" in info and "20 dB" in info and "clip" in info
    assert not amendment.blocked


def test_patch_keeps_a_gain_the_change_names_for_the_channel():
    amendment, _ = _review("Add Playback on A 30 with Playback gain 15 dB", _playback(15))
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "Playback"]
    assert added["processing"]["gain_db"] == 15
    assert not any("a Line source" in i for i in amendment.infos)


def test_patch_a_gain_the_change_states_anywhere_stands():
    amendment, _ = _review("Add Playback on A 30, and Kick gain 20 dB", _playback(20))
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "Playback"]
    assert added["processing"]["gain_db"] == 20


def test_patch_leaves_a_mic_channel_alone():
    channel = _playback(20)
    channel["source"]["type"] = "Mic"
    amendment, _ = _review("Add Playback mic on A 30", channel)
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "Playback"]
    assert added["processing"]["gain_db"] == 20


def test_the_blanket_conventions_line_stands_for_a_line_source_in_build():
    """The maintainer's decision: a line about every channel's gain applies to
    a Line source too. Playback keeps 20 dB and nothing is announced."""
    channels, infos = _build([
        {"input": "Kick", "name": "Kick", "processing": {"gain_db": 20}},
        {"input": "Playback", "name": "Playback", "processing": {"gain_db": 20}}],
        conventions=BLANKET)
    assert channels["Playback"]["processing"]["gain_db"] == 20
    assert infos == []


def test_the_type_decides_when_the_conventions_state_no_gain_in_build():
    channels, infos = _build([
        {"input": "Kick", "name": "Kick", "processing": {"gain_db": 20}},
        {"input": "Playback", "name": "Playback", "processing": {"gain_db": 20}}],
        conventions="Drums get a high-pass at 80Hz.")
    assert channels["Playback"]["processing"]["gain_db"] == 0.0
    [info] = infos
    assert "no gain is stated in your conventions or instructions" in info.message


def test_patch_a_model_quoting_the_blanket_line_alone_is_not_a_statement():
    """No conventions text reached the change (none says gain), only the
    model's own provenance: the type decides, and it is said."""
    channel = _playback(20)
    channel["provenance"] = {"processing": f"{BLANKET!r} applies to Playback"}
    amendment, _ = _review("Move Playback to channel 30 and input A 30 (make it mono)", channel)
    [added] = [c for c in amendment.effective_plan["channels"] if c["name"] == "Playback"]
    assert added["processing"]["gain_db"] == 0.0
    assert any("a Line source" in i for i in amendment.infos)


def test_patch_the_blanket_conventions_line_stands_for_the_moved_line_source():
    """The product owner's exact line in the conventions: Playback moved to A 30 keeps
    20 dB and gets no line-gain INFO. With conventions that state no gain, the
    type decides (0 dB, INFO)."""
    plan = applied_plan()
    change_set = patch.empty_change_set("Playback")
    change_set["add"]["channels"] = [_playback(20)]
    occupancy = strip_occupancy(occupancy_state(theirs=()), plan)
    text = "Move Playback to channel 30 on A 30 (make it mono)"
    stated, _ = patch.plan_patch(plan, change_set, occupancy, console_model="wing-compact",
                                 text=text, gain_texts=(BLANKET,))
    [kept] = [c for c in stated.effective_plan["channels"] if c["name"] == "Playback"]
    assert kept["processing"]["gain_db"] == 20
    assert not any("a Line source" in i for i in stated.infos)
    silent, _ = patch.plan_patch(plan, change_set, occupancy, console_model="wing-compact",
                                 text=text, gain_texts=("Drums get a high-pass at 80Hz.",))
    [moved] = [c for c in silent.effective_plan["channels"] if c["name"] == "Playback"]
    assert moved["processing"]["gain_db"] == 0.0
    assert any("a Line source" in i for i in silent.infos)


def test_the_patch_command_reads_the_instructions_for_the_gain(tmp_path):
    """The CLI hands the change the show's instructions and conventions,
    comments stripped (a commented-out line states nothing)."""
    from atoo import cli

    show_dir = tmp_path / "show"
    show_dir.mkdir()
    (show_dir / "plan.json").write_text("{}")
    (show_dir / "instructions.md").write_text(
        "Playback: gain 15dB.\n<!-- Kick: gain 12dB. -->\n")
    args = type("A", (), {"conventions": None, "show": str(show_dir)})()
    show = cli._open_bundle(args)
    texts = cli._gain_texts(args, show, {})
    joined = "\n".join(texts)
    assert "Playback: gain 15dB." in joined and "Kick: gain 12dB" not in joined
