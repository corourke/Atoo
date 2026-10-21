"""A name that is only a label never sinks a paid change reply.

A real reply was refused for a 61-character short name ("limit is 48")
though everything else in it was whole. The change's name is a journal
row and a strip's name is cut by the console at 16 characters, so both are
cut and said at INFO, and the reply is applied. `fixtures/` holds the
reply it is built from; nothing here reads a bundle under `examples/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import patch

FIXTURES = Path(__file__).parent / "fixtures"
REPLY = json.loads((FIXTURES / "patch-aux8.change-reply.json").read_text(encoding="utf-8"))
LONG_NAME = "Add HiHat and F Lead2, move Playback to ch 16 on A 16 as mono"


def _reply(**changes) -> str:
    return json.dumps({**REPLY, **changes})


def test_the_61_character_name_is_cut_not_refused():
    assert len(LONG_NAME) == 61
    infos: list[str] = []
    change_set = patch.parse_change_set(_reply(name=LONG_NAME), infos=infos)
    assert change_set["name"] == LONG_NAME[:patch.CHANGE_NAME_MAX]
    assert any(LONG_NAME in i and "cut to" in i for i in infos)


def test_an_overlong_new_channel_name_is_cut_and_named():
    channels = [dict(c) for c in REPLY["add"]["channels"]]
    channels[0]["name"] = "Lead Vocal Wireless Handheld"
    infos: list[str] = []
    change_set = patch.parse_change_set(
        _reply(add={**REPLY["add"], "channels": channels}), infos=infos)
    assert change_set["add"]["channels"][0]["name"] == "Lead Vocal Wirel"
    assert any("Lead Vocal Wireless Handheld" in i for i in infos)


def test_both_overlong_at_once_still_compile_with_two_infos():
    channels = [dict(c) for c in REPLY["add"]["channels"]]
    channels[0]["name"] = "x" * 40
    infos: list[str] = []
    patch.parse_change_set(_reply(name=LONG_NAME, add={**REPLY["add"], "channels": channels}),
                           infos=infos)
    assert sum("cut to" in i for i in infos) == 2


def test_a_name_within_the_limits_is_untouched_and_silent():
    infos: list[str] = []
    change_set = patch.parse_change_set(json.dumps(REPLY), infos=infos)
    assert change_set["name"] == REPLY["name"]
    assert not any("cut to" in i for i in infos)


def test_a_physical_violation_is_still_refused():
    channels = [dict(c) for c in REPLY["add"]["channels"]]
    channels[0]["channel"] = 9999
    with pytest.raises(patch.ChangeError):
        patch.parse_change_set(_reply(add={**REPLY["add"], "channels": channels}))


def test_the_prompt_states_the_limit():
    assert str(patch.CHANGE_NAME_MAX) in (Path(patch.__file__).parent / "prompts"
                                          / "change_compile.md").read_text(encoding="utf-8")


def test_the_recorded_real_reply_compiles_with_a_name_cut_info():
    """The reply a real model returned (refused for its 61-character name)."""
    raw = (FIXTURES / "patch-change-name-61.change-reply.json").read_text(encoding="utf-8")
    assert json.loads(raw)["name"] == LONG_NAME
    infos: list[str] = []
    change_set = patch.parse_change_set(raw, infos=infos)
    assert len(change_set["name"]) <= patch.CHANGE_NAME_MAX
    assert [c["name"] for c in change_set["add"]["channels"]] == ["HiHat", "F Lead2", "Playback"]
    assert any(LONG_NAME in i and "cut to" in i for i in infos)


def _rename(name: str, new: str, *, obj: str = "channel") -> dict:
    return {"object": obj, "name": name, "change": "as typed", "fields": {"name": new}}


def test_an_overlong_rename_of_a_running_strip_is_cut_and_named():
    modify = [_rename("Snare", "Snare Top Close Mic Number Two")]
    infos: list[str] = []
    change_set = patch.parse_change_set(_reply(modify=modify), infos=infos)
    assert change_set["modify"][0]["fields"]["name"] == "Snare Top Close"
    assert any("Snare Top Close Mic Number Two" in i and "cut to 'Snare Top Close'" in i
               and "'Snare'" in i for i in infos)
    # the reply's own entry is not edited in place
    assert modify[0]["fields"]["name"] == "Snare Top Close Mic Number Two"


def test_the_rename_wording_matches_the_added_channels():
    channels = [dict(c) for c in REPLY["add"]["channels"]]
    channels[0]["name"] = "x" * 20
    infos: list[str] = []
    patch.parse_change_set(
        _reply(add={**REPLY["add"], "channels": channels}, modify=[_rename("Snare", "y" * 20)]),
        infos=infos)
    cut = [i for i in infos if "cut to" in i]
    assert len(cut) == 2
    assert all("characters, longer than the 16 it is shown at; it is cut to" in i for i in cut)


def test_a_rename_within_the_limit_is_untouched_and_silent():
    infos: list[str] = []
    change_set = patch.parse_change_set(
        _reply(modify=[_rename("Snare", "Snare Top")]), infos=infos)
    assert change_set["modify"][0]["fields"]["name"] == "Snare Top"
    assert not any("cut to" in i for i in infos)


def test_only_a_channels_name_is_cut_by_length():
    """A bus or DCA name is how everything refers to it, and is never renamed
    by a change -- so it is not this cut's to shorten."""
    infos: list[str] = []
    change_set = patch.parse_change_set(
        _reply(modify=[_rename("Drums", "z" * 30, obj="dca")]), infos=infos)
    assert change_set["modify"][0]["fields"]["name"] == "z" * 30
    assert not any("cut to" in i for i in infos)


def test_the_overlong_rename_reaches_the_review_as_an_edit_not_a_refusal():
    from test_amend import applied_plan
    from test_patch_preset_values import _modify, occupancy

    plan = applied_plan()
    target = plan["channels"][1]["name"]
    change_set = patch.empty_change_set("Rename")
    change_set["modify"] = [_modify(target, {"name": "A name far past the sixteen"})]
    infos: list[str] = []
    change_set = patch.validate_change_set(change_set, infos=infos)
    amendment, merge = patch.plan_patch(plan, change_set, occupancy(), text="rename it")
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    assert [e.new for e in merge.edits if e.path == "name"] == ["A name far past the"[:16].rstrip()]
