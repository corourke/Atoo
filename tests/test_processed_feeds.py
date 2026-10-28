"""A processed feed stated in the conventions.

"The lead vocal post-fader to USB 13" names a strip, a tap and a socket. The
desk carries such a feed through a user signal (USR 1-24); the model names
only the strip, and code takes the next free slot, shares one already
carrying the same strip at the same tap, and patches the socket from it. A
stereo strip takes two slots, its L and its R, on two sockets. More than 24,
or a strip the plan does not have, is a WARNING and that feed is not built.
The plans are built here; the end-to-end build goes through a scripted
stand-in model.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from atoo.apply import _build_write_targets
from atoo.cli import main
from atoo.reply_expand import expand_processed_feeds
from tests.test_outputs_sheet import _Scripted

QUOTE = "Record the lead vocal post-fader to USB 13."


def _plan(**extra) -> dict:
    plan = {
        "channels": [
            {"name": "Lead Vox", "bank": "ch", "channel": 5, "source": {"stereo": False}},
            {"name": "Keys", "bank": "ch", "channel": 6, "source": {"stereo": True}},
            {"name": "Playback", "bank": "aux", "channel": 3, "source": {"stereo": False}},
        ],
        "busses": {"Mon 1": {"index": 3, "mono": True}},
        "outputs": {"Main": {"kind": "main", "index": 1, "mono": False}},
    }
    plan.update(extra)
    return plan


def _feed(strip="Lead Vox", to="USB 13", tap="post", quote=QUOTE) -> dict:
    return {"to": to, "strip": strip, "tap": tap, "quote": quote}


def _expand(plan, *feeds):
    plan["processed_feeds"] = list(feeds)
    findings: list = []
    written = expand_processed_feeds(plan, findings)
    return written, findings


def test_a_mono_channel_post_fader_takes_the_first_free_user_signal():
    plan = _plan()
    written, findings = _expand(plan, _feed())
    assert written == 1 and "processed_feeds" not in plan
    assert plan["user_sources"] == [{"slot": 1, "source": {"group": "CH", "index": 5},
                                     "tap": "POST", "leg": "L+R", "name": "Lead Vox post"}]
    assert plan["direct_outputs"] == [{"group": "USB", "socket": 13,
                                       "source": {"group": "USR", "index": 1}}]
    [info] = findings
    assert (info.code, info.message) == (
        "inferred.processed-feed",
        f"USB 13 carries Lead Vox after its fader (post), through USR 1, the next free user "
        f"signal, as {QUOTE!r} asks")


def test_a_stereo_strip_takes_two_slots_on_two_sockets():
    plan = _plan()
    _expand(plan, _feed("Keys", "USB 20", "pre", "Keys pre-fader to USB 20."))
    assert [(u["slot"], u["source"], u["tap"], u["leg"]) for u in plan["user_sources"]] == [
        (1, {"group": "CH", "index": 6}, "PRE", "L"), (2, {"group": "CH", "index": 6}, "PRE", "R")]
    assert [(e["socket"], e["source"]["index"]) for e in plan["direct_outputs"]] == [(20, 1), (21, 2)]


def test_a_bus_a_main_and_an_aux_are_strips_too():
    plan = _plan()
    _expand(plan, _feed("Mon 1", "USB 1"), _feed("Playback", "USB 2"), _feed("main", "USB 3"))
    assert [(u["source"]["group"], u["source"]["index"], u["leg"]) for u in plan["user_sources"]] == [
        ("BUS", 3, "L+R"), ("AUX", 3, "L+R"), ("MAIN", 1, "L"), ("MAIN", 1, "R")]


def test_the_same_feed_twice_shares_its_slot():
    plan = _plan()
    _expand(plan, _feed(to="USB 13"), _feed(to="AES50-B 1"))
    assert [u["slot"] for u in plan["user_sources"]] == [1]
    assert {e["source"]["index"] for e in plan["direct_outputs"]} == {1}


def test_a_slot_the_plan_already_uses_is_skipped():
    """USR 1 is defined, and a channel reads USR 2 (undefined, verify says so):
    neither is taken."""
    plan = _plan(user_sources=[{"slot": 1, "source": {"group": "CH", "index": 1}}])
    plan["channels"].append({"name": "Spare", "bank": "ch", "channel": 7,
                             "patch": {"group": "USR", "sockets": [2]}, "source": {}})
    _expand(plan, _feed())
    assert plan["user_sources"][-1]["slot"] == 3


def test_more_than_twenty_four_is_refused_and_nothing_is_half_built():
    taken = [{"slot": n, "source": {"group": "CH", "index": 1}, "tap": "PRE", "leg": "L+R"}
             for n in range(1, 24)]
    plan = _plan(user_sources=copy.deepcopy(taken))
    written, findings = _expand(plan, _feed("Keys", "USB 20"))
    assert written == 0
    assert plan["user_sources"] == taken and "direct_outputs" not in plan
    [warning] = findings
    assert warning.code == "processed-feed.no-free-user-signal"
    assert warning.message.startswith(
        "USB 20 was not fed Keys post-fader: all 24 user signals (USR 1-24) are in use")
    # The one left still carries a mono feed.
    written, _ = _expand(plan, _feed())
    assert written == 1 and plan["user_sources"][-1]["slot"] == 24


def test_a_strip_the_plan_does_not_have_is_said_and_not_built():
    plan = _plan()
    written, findings = _expand(plan, _feed("Lead Vocal"))
    assert written == 0 and "user_sources" not in plan
    [warning] = findings
    assert warning.code == "processed-feed.no-such-strip"
    assert "the plan has no channel, bus, Main or Matrix named 'Lead Vocal'" in warning.message


# -- the processed-feed case, end to end -------------------------------------------
#
# `evals/processed-feed/`, frozen under `tests/fixtures/processed-feed/`: the
# split case's twelve inputs, the lead vocal post-fader to USB 13 and the
# stereo keys pre-fader to USB 14-15. The reply is what a model writes for
# those conventions: the strips by name and their taps, no slot.

CASE = Path(__file__).parent / "fixtures" / "processed-feed"
LEAD = "- Stream recorder: the lead vocal, post-fader, on USB 13"
KEYS = "- Keys to the video desk: the keys pre-fader, on USB 14-15"


def _case_reply() -> dict:
    from tests.test_outputs_sheet import _forge_reply

    reply = _forge_reply()
    reply["busses"] = []
    reply.pop("output_runs")
    reply["processed_feeds"] = [
        {"to": "USB 13", "strip": "Lead Vox", "tap": "post", "quote": LEAD},
        {"to": "USB 14", "strip": KEYS_STRIP, "tap": "pre", "quote": KEYS}]
    return reply


KEYS_STRIP = "Keys"   # the model's word; the stereo channel is named "Keys L"


def test_the_processed_feed_case_builds_both_feeds_and_nothing_else(tmp_path, monkeypatch):
    show = tmp_path / "feeds"
    show.mkdir()
    (show / "input.csv").write_text((CASE / "feeds.csv").read_text())
    provider = _Scripted(script=[json.dumps(_case_reply())])
    monkeypatch.setattr("atoo.cli.provider_from_env", lambda: provider)
    monkeypatch.setenv("ATOO_AI_FIXUP_ROUNDS", "0")
    monkeypatch.setattr("atoo.generate.draft_watch_conditions", lambda *a, **k: [])
    assert main(["build", "--show", str(show), "--console-model", "wing-compact",
                 "--conventions", str(CASE / "feeds.md")]) == 0
    system, _user = provider.calls[0]
    assert "processed_feeds" in system and "never name a USR slot" in system
    plan = json.loads((show / "plan.json").read_text())
    number = {ch["name"]: ch["channel"] for ch in plan["channels"]}
    assert [(u["slot"], u["source"], u["tap"], u["leg"]) for u in plan["user_sources"]] == [
        (1, {"group": "CH", "index": number["Lead Vox"]}, "POST", "L+R"),
        (2, {"group": "CH", "index": number["Keys L"]}, "PRE", "L"),
        (3, {"group": "CH", "index": number["Keys L"]}, "PRE", "R")]
    feeds = sorted(((e["group"], e["socket"]), (e["source"]["group"], e["source"]["index"]))
                   for e in plan["direct_outputs"])
    assert feeds == [(("USB", 13), ("USR", 1)), (("USB", 14), ("USR", 2)),
                     (("USB", 15), ("USR", 3))]
    stereo = [c for c in plan["channels"] if len(c["patch"]["sockets"]) == 2]
    assert len(plan["channels"]) == 10 and len(stereo) == 2
    assert sorted(plan["dcas"]) == ["Band", "Drums", "Vocals"]
    assert plan["meta"]["verify_findings"]["errors"] == []
    said = [f["message"] for f in plan["meta"]["build_findings"]
            if f["code"] == "inferred.processed-feed"]
    # The two lines docs/user/conventions.md shows.
    assert said == [
        f"USB 13 carries Lead Vox after its fader (post), through USR 1, the next free user "
        f"signal, as {LEAD!r} asks",
        f"USB 14-15 carries Keys before its fader (pre), through USR 2, USR 3, the next free "
        f"user signals, as {KEYS!r} asks"]
    # Apply writes each slot before the socket that reads it.
    order = [t.address for t in _build_write_targets(plan, True)[0]]
    assert order.index("/io/in/USR/3/user/grp") < order.index("/io/out/USB/15/grp")
