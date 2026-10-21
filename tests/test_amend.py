"""Tests for atoo/amend.py -- the amend/delta engine.

The scenario every fixture here is built on is the one the project brief
and `mockups/build-page/OPTIONS-H.md` both use, because it is the one
that motivated the feature: the touring-band show is applied and running
on strips 1-19, strip 20 belongs to somebody else ("Podium"), 21-32 are
free, 33-40 never answer, and the horn section has turned up late in the
setup window.

The centrepiece is `test_untouched_strips` further down. Everything else
is scaffolding for it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import amend
from atoo.amend import (
    AmendRefused,
    AmendScope,
    ChangeKind,
    StripState,
    amendment_targets,
    apply_amendment,
    occupancy_read_plan,
    plan_amendment,
    read_occupancy,
    strip_occupancy,
    witness_addresses,
    witness_changes,
    witness_plan,
    witness_requests,
    read_witness,
)
from atoo import console_facts as _facts
from atoo.audit import ConsoleState
from atoo.console import OscReply
from tests.test_apply import FakeConsole

APPLIED_PLAN_PATH = Path(__file__).parent / "fixtures" / "applied-show.plan.json"


def applied_plan() -> dict:
    """The real applied show: 19 channels on strips 1-19, patched A1-A20,
    MON1-4 on LCL 1-4.

    **A frozen copy under `tests/fixtures/`, not `examples/touringband/`.**
    It is the same plan -- taken verbatim off the bundle on 2026-09-23,
    immediately before the maintainer rebuilt it -- but it is now this module's
    own. `examples/touringband/` is a living example he edits between
    shows; the rebuild that moved the monitors from LCL to AES50-A turned
    six tests here red without a line of `atoo` changing, because
    they were reading his working files as though they were fixtures.
    Nothing in `tests/` may do that again (`tests/conftest.py` enforces
    it), so the scenario this module is built on lives here.
    """
    return json.loads(APPLIED_PLAN_PATH.read_text())


def horn(number: int, name: str, socket: int) -> dict:
    """One channel entry of the shape `build` produces, for a horn that
    turned up late. Patched above everything the applied show uses."""
    return {
        "channel": number,
        "bank": "ch",
        "name": name,
        "color": "Orange",
        "source": {"input": name, "type": "Mic", "model": "", "stereo": False,
                   "phantom": False},
        "patch": {"group": "A", "sockets": [socket], "stated": True},
        "processing": {"hpf_hz": 100, "preset": None, "hi_cut_hz": None, "tilt_db": None,
                       "trim_db": None, "balance_db": None, "invert": None, "gain_db": None},
        "fader": {"fader_db": -144, "muted": None},
        "dca": ["Horns"],
        "mute_group": ["Band"],
        "bus_sends": [{"bus": "Horns", "mode": "post", "level_db": 0.0}],
        "main_routes": [],
        "provenance": {},
    }


def amended_plan(*, start: int = 20) -> dict:
    """The rebuild: the same show plus three horns, which `build` would
    number from the first strip its own plan does not use -- 20, 21, 22.
    Strip 20 is somebody else's, which is what placement has to notice."""
    plan = applied_plan()
    plan["channels"] = plan["channels"] + [
        horn(start, "Trumpet", 21),
        horn(start + 1, "Trombone", 22),
        horn(start + 2, "T.Sax", 23),
    ]
    return plan


# --------------------------------------------------------------------------
# A console state for the scenario above.
# --------------------------------------------------------------------------


def occupancy_state(*, theirs=(20,), unread=tuple(range(33, 41)),
                    plan: dict | None = None) -> ConsoleState:
    """The desk as the scoped read finds it: every strip the applied plan
    built answering with its own name, its patch and its source's name;
    `theirs` answering the way a WING really answers for a strip somebody
    named by hand; `unread` answering nothing at all; the rest empty.

    **`theirs` is Podium-shaped, and that is the point.** The maintainer typed
    "Podium" on channel 20 of a real desk on 2026-09-22, and the desk put
    it on `/io/in/LCL/20/name` -- `/ch/20/name` stayed empty and the strip
    stayed on `LCL 20`, the Compact's factory patch. Every signal a strip
    normally gives off says that strip is free. The only thing that says
    otherwise is the socket, so that is what this fixture makes the engine
    read. A fixture that put "Podium" on `/ch/20/name`, as this one did
    until the hazard was found, tests nothing a real desk would do.
    """
    plan = plan if plan is not None else applied_plan()
    values: dict[str, object] = {}
    by_number = {c["channel"]: c for c in plan["channels"]}
    for bank, count in (("ch", 40), ("aux", 8)):
        for n in range(1, count + 1):
            base = f"/{bank}/{n}"
            if bank == "ch" and n in unread:
                continue
            channel = by_number.get(n) if bank == "ch" else None
            values[f"{base}/clink"] = 1  # the factory setting, on every strip
            if channel is not None:
                group, socket = channel["patch"]["group"], channel["patch"]["sockets"][0]
                values[f"{base}/name"] = channel["name"]
                values[f"{base}/in/conn/grp"] = group
                values[f"{base}/in/conn/in"] = socket
                # `apply` writes the name to the socket too, which is why
                # a desk we set up ourselves hid this problem for months.
                values[f"/io/in/{group}/{socket}/name"] = channel["name"]
            elif bank == "ch" and n in theirs:
                values[f"{base}/name"] = ""
                values[f"{base}/in/conn/grp"] = "LCL"
                values[f"{base}/in/conn/in"] = n
                values[f"/io/in/LCL/{n}/name"] = "Podium"
            else:
                # An untouched strip: WING's own factory label, nothing
                # patched. Every reading answered -- that is what makes it
                # free rather than unknown.
                values[f"{base}/name"] = f"{'CH' if bank == 'ch' else 'AUX'}{n:02d}"
                values[f"{base}/in/conn/grp"] = "OFF"
                values[f"{base}/in/conn/in"] = 0
    return ConsoleState(values, console_model="wing-compact")


def occupancy() -> list:
    return strip_occupancy(occupancy_state(), applied_plan())


def scenario(**kwargs):
    """The whole situation: applied plan, rebuild, occupancy, delta."""
    return plan_amendment(applied_plan(), amended_plan(), occupancy(), **kwargs)


# --------------------------------------------------------------------------
# 1. The scoped occupancy read
# --------------------------------------------------------------------------


def test_occupancy_read_plan_is_the_scoped_budget():
    plan = occupancy_read_plan()
    # OPTIONS-H budgets "~150 addresses and about four seconds", against
    # audit's full sweep of some six thousand. Four leaves per strip, plus
    # at most one socket name per patched strip in the second pass, so the
    # worst case is 240 -- still the same order, still a few seconds.
    assert len(plan) == 192
    assert len(plan) == (40 + 8) * 4
    sources = amend.source_name_addresses(occupancy_state())
    assert len(plan) + len(sources) <= 240
    # Four leaves per strip and no more -- a send address here would be
    # 28 more per strip and a forty-second read.
    leaves = {address.split("/", 3)[3] for address, _ in plan}
    assert leaves == {"name", "clink", "in/conn/grp", "in/conn/in"}
    assert not [a for a, _ in plan if "/send/" in a or "/main/" in a]


def test_occupancy_read_plan_is_pure_and_ordered():
    assert occupancy_read_plan(channels=2, aux=1) == [
        ("/ch/1/name", "s"), ("/ch/1/clink", "i"),
        ("/ch/1/in/conn/grp", "s"), ("/ch/1/in/conn/in", "i"),
        ("/ch/2/name", "s"), ("/ch/2/clink", "i"),
        ("/ch/2/in/conn/grp", "s"), ("/ch/2/in/conn/in", "i"),
        ("/aux/1/name", "s"), ("/aux/1/clink", "i"),
        ("/aux/1/in/conn/grp", "s"), ("/aux/1/in/conn/in", "i"),
    ]


def test_the_second_pass_asks_only_about_sockets_that_are_patched():
    """It cannot be part of `occupancy_read_plan` at all: which socket to
    ask about is not knowable until the patch has been read."""
    state = ConsoleState({
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 5,
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 5,   # shared socket
        "/ch/3/in/conn/grp": "OFF", "/ch/3/in/conn/in": 0,  # unpatched
    })
    assert amend.source_name_addresses(state, channels=3, aux=0) == [
        ("/io/in/A/5/name", "s")]


def test_read_occupancy_leaves_an_unanswered_address_absent():
    """The reading this whole path stands on: a strip that did not answer
    has no value at all, rather than a default that reads as empty."""
    console = FakeConsole({
        "/ch/1/name": ("Kick", "s"),
        "/ch/1/in/conn/grp": ("A", "s"),
        "/ch/1/in/conn/in": (1, "i"),
    })
    state = read_occupancy(console, channels=2, aux=0)
    assert state.name("/ch/1") == "Kick"
    assert "/ch/2/name" not in state.values
    assert state.name("/ch/2") is None


def test_read_occupancy_corrects_the_patch_index():
    """WING's GET for a connector answers one less than its SET takes
    -- a patch read without the correction is off by one, and
    an off-by-one patch is a false reading of who owns a socket."""
    console = FakeConsole({
        "/ch/1/name": ("Kick", "s"),
        "/ch/1/in/conn/grp": ("A", "s"),
        "/ch/1/in/conn/in": (4, "i"),
    })
    state = read_occupancy(console, channels=1, aux=0)
    assert state.patch("/ch/1") == ("A", 5)


def test_strip_occupancy_four_states():
    statuses = {s.label: s for s in occupancy()}
    assert statuses["ch:1"].state is StripState.OURS
    assert statuses["ch:20"].state is StripState.THEIRS
    assert statuses["ch:21"].state is StripState.FREE
    assert statuses["ch:33"].state is StripState.UNKNOWN
    assert statuses["ch:33"].unread == (
        "/ch/33/name", "/ch/33/clink", "/ch/33/in/conn/grp", "/ch/33/in/conn/in")
    # And the one the fixture is really for: strip 20 is blank at
    # /ch/20/name and named only on the socket it shows.
    assert statuses["ch:20"].name == ""
    assert statuses["ch:20"].source_name == "Podium"


def test_an_unread_strip_is_not_a_free_strip():
    """OPTIONS-H, non-negotiable: "33-40 never answered and therefore
    occupied, not free -- an unread strip is not a safe strip.\""""
    statuses = {s.label: s for s in occupancy()}
    for n in range(33, 41):
        status = statuses[f"ch:{n}"]
        assert status.state is StripState.UNKNOWN
        assert status.available is False


def test_a_factory_named_unpatched_strip_is_free():
    """`CH21` is WING's own label, not a name -- a desk straight out of
    the box must not read as fully occupied."""
    statuses = {s.label: s for s in occupancy()}
    assert statuses["ch:21"].name == "CH21"
    assert statuses["ch:21"].available is True


A13_DIR = (Path(__file__).parent.parent / "tests" / "fixtures" / "console-runs" /
           "2026-09-22-2139")
A13_SNAP = A13_DIR / "A13-board-with-podium.snap"
A13_CAPTURE = A13_DIR / "A13-occupancy.json"


def state_from_snapshot(path: Path) -> ConsoleState:
    """An occupancy-shaped `ConsoleState` from a console-written `.snap`.

    Used instead of the run's own `A13-occupancy.json` because that read
    predates this module: it asked nine leaves per strip and **none of
    them was a socket name**, which is exactly the blind spot this test
    exists to close. The snapshot is the desk's own export and carries
    everything, already in SET-value form, so no readback correction
    applies to it.
    """
    data = json.loads(path.read_text())["ae_data"]
    values: dict[str, object] = {}
    for bank in ("ch", "aux"):
        for number, strip in data.get(bank, {}).items():
            base = f"/{bank}/{number}"
            values[f"{base}/name"] = strip.get("name", "")
            values[f"{base}/clink"] = 1 if strip.get("clink") else 0
            conn = (strip.get("in") or {}).get("conn") or {}
            values[f"{base}/in/conn/grp"] = conn.get("grp", "OFF")
            values[f"{base}/in/conn/in"] = conn.get("in", 0)
    for group, sockets in (data.get("io", {}).get("in") or {}).items():
        for number, socket in sockets.items():
            values[f"/io/in/{group}/{number}/name"] = socket.get("name", "")
    return ConsoleState(values, console_model="wing-compact")


def test_occupancy_against_a_real_desk():
    """The classification, run over a real WING Compact rather than a
    fixture: the snapshot the maintainer exported on 2026-09-22 from a desk
    carrying the touring-band show, with one strip he had named by hand.

    **This is the test the engine nearly shipped without.** Channel 20 of
    that desk is called "Podium", and the desk holds that name at
    `/io/in/LCL/20/name`: `/ch/20/name` is empty and the strip is on
    `LCL 20`, a Compact's factory patch. Under a read that asks only for
    the strip's own name and patch, it is indistinguishable from an
    untouched strip -- so the amend engine would have allocated it and
    written over somebody's live channel.

    And the other direction, which the same capture pins: `/aux/1` and
    `/aux/2` are patched to `USB 1` and `PLAY 1` and those sockets read
    `'USB 1/2'` and `'2TR'`. Those are the desk's own labels, not names,
    and counting them would refuse two strips that are genuinely free.
    """
    statuses = {s.label: s for s in strip_occupancy(
        state_from_snapshot(A13_SNAP), applied_plan())}
    assert [k for k, s in statuses.items() if s.state is StripState.OURS] == [
        f"ch:{n}" for n in range(1, 20)]

    podium = statuses["ch:20"]
    assert podium.state is StripState.THEIRS
    assert podium.name == ""              # the strip says nothing
    assert podium.patch == ("LCL", 20)    # and sits on the factory patch
    assert podium.source_name == "Podium"  # the socket is where the name is
    assert podium.available is False

    # Its four neighbours are on the same kind of factory patch with no
    # name anywhere, and must stay free.
    for n in range(21, 25):
        assert statuses[f"ch:{n}"].patch == ("LCL", n)
        assert statuses[f"ch:{n}"].state is StripState.FREE
    for label, socket_label in (("aux:1", "USB 1/2"), ("aux:2", "2TR")):
        assert statuses[label].source_name == socket_label
        assert statuses[label].state is StripState.FREE
    assert not [s for s in statuses.values() if s.state is StripState.UNKNOWN]


def test_a_strip_named_only_on_its_source_is_occupied():
    """The Podium hazard in isolation, and its mirror: the same strip with
    nothing on the socket is free. One address decides it."""
    base = {
        "/ch/1/name": "", "/ch/1/clink": 1,
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    }
    named = ConsoleState(dict(base, **{"/io/in/LCL/1/name": "Podium"}),
                         console_model="wing-compact")
    blank = ConsoleState(dict(base, **{"/io/in/LCL/1/name": ""}),
                         console_model="wing-compact")
    assert strip_occupancy(named, channels=1, aux=0)[0].state is StripState.THEIRS
    assert strip_occupancy(blank, channels=1, aux=0)[0].state is StripState.FREE

    # `clink` off means the strip shows its OWN name, so the socket's is
    # not this strip's business -- that is the shared-socket case
    # `apply.py` creates deliberately.
    unlinked = ConsoleState(dict(base, **{"/io/in/LCL/1/name": "Podium", "/ch/1/clink": 0}),
                            console_model="wing-compact")
    assert strip_occupancy(unlinked, channels=1, aux=0)[0].state is StripState.FREE


def test_a_patched_strip_whose_source_name_went_unread_is_unknown():
    """Not free. The socket name is the only signal that can distinguish a
    Podium from an untouched strip, so not having it is not knowing."""
    state = ConsoleState({
        "/ch/1/name": "", "/ch/1/clink": 1,
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 1,
    }, console_model="wing-compact")
    status = strip_occupancy(state, channels=1, aux=0)[0]
    assert status.state is StripState.UNKNOWN
    assert status.available is False
    assert "/io/in/LCL/1/name" in status.unread


def test_a_factory_socket_label_is_not_a_name():
    assert amend.is_factory_source_label("USB", "USB 1/2")
    assert amend.is_factory_source_label("PLAY", "2TR")
    assert amend.is_factory_source_label("LCL", "")
    assert amend.is_factory_source_label("LCL", "LCL 20")
    assert not amend.is_factory_source_label("LCL", "Podium")
    assert not amend.is_factory_source_label("A", "Kick")


def test_the_old_capture_shows_why_the_socket_read_was_added():
    """`A13-occupancy.json` is the read this module had before the Podium
    was found: nine leaves a strip and not one of them a socket name.
    Feeding it in leaves every patched strip UNKNOWN rather than free,
    which is the right way for a read to be incomplete."""
    capture = json.loads(A13_CAPTURE.read_text())
    values = {a: _facts.correct_readback_index(a, v)
              for a, v in capture["raw"].items()}
    statuses = {s.label: s for s in strip_occupancy(
        ConsoleState(values, console_model="wing-compact"), applied_plan())}
    assert statuses["ch:20"].state is StripState.UNKNOWN
    assert statuses["ch:20"].available is False


def test_occupancy_summary_says_what_it_did_not_ask():
    text = amend.occupancy_summary(occupancy())
    assert "19 ours" in text and "1 theirs" in text and "8 unknown" in text
    assert "never answered, therefore treated as OCCUPIED" in text
    assert "ch:33" in text
    assert "routed somewhere but neither named nor patched reads as free" in text
    # A refusal has to say where it read the name, because the engineer's
    # next move is to go and look at the same thing -- and on strip 20 the
    # place to look is the socket, not the strip.
    assert "ch:20 -- named 'Podium' on its source LCL 20" in text


# --------------------------------------------------------------------------
# 2. The delta plan
# --------------------------------------------------------------------------


def test_horns_skip_the_occupied_strip():
    """The whole scenario in one assertion: the rebuild asked for 20, 21,
    22; 20 is somebody else's; the horns land on 21, 22, 23."""
    amendment = scenario()
    assert amendment.strips == ["ch:21", "ch:22", "ch:23"]
    placed = {c.where: c.slot for c in amendment.additions}
    assert placed == {"'Trumpet'": "ch:21", "'Trombone'": "ch:22", "'T.Sax'": "ch:23"}
    assert [c["channel"] for c in amendment.effective_plan["channels"][-3:]] == [21, 22, 23]


def test_nothing_already_applied_is_renumbered():
    amendment = scenario()
    applied = {c["channel"]: c["name"] for c in applied_plan()["channels"]}
    effective = {c["channel"]: c["name"] for c in amendment.effective_plan["channels"]}
    for number, name in applied.items():
        assert effective[number] == name


def test_the_skip_announces_itself():
    """An inferred value that does not announce itself is the
    defect, not the inference."""
    amendment = scenario()
    assert any("proposed ch:20" in i and "ch:21" in i for i in amendment.infos)


def test_unchanged_channels_are_reported_and_not_written():
    amendment = scenario()
    unchanged = [c for c in amendment.changes if c.kind is ChangeKind.UNCHANGED]
    assert len(unchanged) == 19
    assert amendment.scope.why("/ch/1/name") is None


def test_a_moved_source_is_refused_not_renumbered():
    """FR-2.3: "rather than renumbering existing channels"."""
    plan = amended_plan()
    for channel in plan["channels"]:
        if channel["name"] == "Kick":
            channel["channel"] = 30
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    blocked = amendment.blocked
    assert [c.kind for c in blocked] == [ChangeKind.RENUMBERED]
    assert "'Kick'" in blocked[0].where
    assert "ch:1" in blocked[0].reason and "ch:30" in blocked[0].reason
    with pytest.raises(AmendRefused, match="RENUMBERED"):
        apply_amendment(amendment, FakeConsole(), dry_run=True)


def test_a_channel_with_nowhere_to_go_fails_by_name():
    """FR-2.3 again: name the channels that could not be placed."""
    state = occupancy_state(unread=tuple(range(20, 41)))
    amendment = plan_amendment(applied_plan(), amended_plan(),
                               strip_occupancy(state, applied_plan()))
    unplaceable = [c for c in amendment.changes if c.kind is ChangeKind.UNPLACEABLE]
    assert {c.where for c in unplaceable} == {"'Trumpet'", "'Trombone'", "'T.Sax'"}
    assert amendment.strips == []
    with pytest.raises(AmendRefused, match="UNPLACEABLE"):
        apply_amendment(amendment, FakeConsole(), dry_run=True)


def test_a_modified_running_strip_is_reported_and_left_alone():
    plan = amended_plan()
    for channel in plan["channels"]:
        if channel["name"] == "Kick":
            channel["processing"]["hpf_hz"] = 200
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    modified = [c for c in amendment.changes if c.kind is ChangeKind.MODIFIED]
    assert [c.where for c in modified] == ["'Kick'"]
    assert amendment.blocked == []
    assert amendment.scope.why("/ch/1/flt/lcf") is None




def test_an_override_can_open_one_occupied_strip_and_only_that_one():
    amendment = plan_amendment(applied_plan(), amended_plan(), occupancy(),
                               allow_strips={"ch:20"})
    assert amendment.strips == ["ch:20", "ch:21", "ch:22"]
    assert any("--allow-strip override" in w and "ch:20" in w for w in amendment.warnings)
    assert amendment.scope.why("/ch/33/name") is None


def test_an_override_cannot_open_a_strip_the_applied_plan_owns():
    amendment = plan_amendment(applied_plan(), amended_plan(), occupancy(),
                               allow_strips={"ch:5"})
    assert "ch:5" not in amendment.strips
    assert amendment.scope.why("/ch/5/name") is None
    # Refused out loud. Two independent guards stop this -- the plan's own
    # claim on the slot, and the strip being OURS in the occupancy read --
    # and the warning is what proves the first one ran rather than the
    # second one happening to cover for it.
    assert any("ch:5 is claimed by the applied plan" in w for w in amendment.warnings)


def test_a_new_bus_is_in_scope_but_existing_sends_into_it_are_not():
    plan = amended_plan()
    plan["busses"]["Horn Wedge"] = {
        "destination": {"type": "dedicated_output", "label": "Horn Wedge",
                        "socket": {"group": "LCL", "sockets": [5], "stated": True}},
        "fader": {"fader_db": -144, "muted": None},
        "dca": [], "mute_group": [], "description": "", "provenance": "",
        "index": 13, "mono": True,
    }
    for channel in plan["channels"][-3:]:
        channel["bus_sends"].append({"bus": "Horn Wedge", "mode": "pre", "level_db": -144})
    plan["channels"][0]["bus_sends"].append(
        {"bus": "Horn Wedge", "mode": "pre", "level_db": -144})
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    assert amendment.scope.why("/bus/13/name") is not None
    assert amendment.scope.why("/io/out/LCL/5/grp") is not None
    # The new horn strips feed it; the running Kick does not get a new send.
    assert amendment.scope.why("/ch/21/send/13/on") is not None
    assert amendment.scope.why("/ch/1/send/13/on") is None
    assert any("no already-applied channel's send into it is written" in w
               for w in amendment.warnings)


def test_a_new_bus_cannot_take_an_index_the_applied_plan_uses():
    plan = amended_plan()
    plan["busses"]["Horn Wedge"] = dict(plan["busses"]["Horns"], index=5)
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    blocked = [c for c in amendment.blocked if c.kind_of_object == "bus"]
    assert blocked and "'Drums'" in blocked[0].reason
    assert amendment.scope.why("/bus/5/name") is None


def test_delay_speakers_get_their_socket_without_the_run_of_main_1():
    """The other half of "amend", and the reason the word is not "add
    channels": a new output off an internal object that is already live."""
    plan = amended_plan()
    plan["outputs"]["Delay Speakers"] = {
        "kind": "matrix", "index": 3,
        "sockets": [{"group": "LCL", "sockets": [5, 6], "stated": True}],
        "description": "", "provenance": "",
        "fed_by": {"type": "main", "index": 1},
    }
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    assert amendment.scope.why("/io/out/LCL/5/grp") is not None
    assert amendment.scope.why("/mtx/3/fdr") is not None
    # One node on the running Main, and nothing else about it.
    assert amendment.scope.why("/main/1/send/MX3/on") is not None
    assert amendment.scope.why("/main/1/fdr") is None
    assert amendment.scope.why("/main/1/mute") is None
    assert any("Exactly one node on it is written" in w for w in amendment.warnings)


def test_a_new_output_on_an_internal_object_already_in_use_gets_only_the_socket():
    plan = amended_plan()
    plan["outputs"]["FOH Spare"] = {
        "kind": "main", "index": 1,
        "sockets": [{"group": "LCL", "sockets": [6], "stated": True}],
        "description": "", "provenance": "",
    }
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    assert amendment.scope.why("/io/out/LCL/6/grp") is not None
    assert amendment.scope.why("/main/1/fdr") is None
    assert any("only the new socket" in w for w in amendment.warnings)


def test_a_new_output_cannot_take_a_socket_the_applied_plan_already_routes():
    """LCL 3 is the MON3 wedge in the applied show. A rebuild that puts a
    new output on it is asking to unplug a monitor mid-set."""
    plan = amended_plan()
    plan["outputs"]["FOH Spare"] = {
        "kind": "main", "index": 2,
        "sockets": [{"group": "LCL", "sockets": [3], "stated": True}],
        "description": "", "provenance": "",
    }
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    assert amendment.scope.why("/io/out/LCL/3/grp") is None
    assert any("already routes -- not written" in w for w in amendment.warnings)


def test_a_socket_shared_with_a_running_strip_is_not_relabelled():
    """One socket cannot carry two names, and the running strip's is the
    one that must not change under it."""
    plan = amended_plan()
    plan["channels"][-1]["patch"] = {"group": "A", "sockets": [1], "stated": True}
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    assert amendment.scope.why("/io/in/A/1/name") is None
    assert amendment.scope.why("/io/in/A/21/name") is not None
    assert any("also uses" in w and "A 1" in w for w in amendment.warnings)


# --------------------------------------------------------------------------
# 2b. A channel the rebuild dropped: returned to free, or refused
#
# --------------------------------------------------------------------------
#
# *"Whether this is for a rebuild of the plan, or an
# amend, the answer is C. Channels are not an unlimited resource and we
# want to do what the engineer is asking for."*
#
# The safety property these tests exist for: **a tracked removal may be
# cleared, untracked state may never be.** `test_a_podium_shaped_strip_is
# _never_cleared` is the one that matters, and it is mutation-checked --
# see its docstring.

#: The strip the applied touring-band plan puts 'MLD VOX' on, and the
#: socket it patches it from. Read off the plan rather than written down,
#: so a change to the fixture cannot quietly make these tests vacuous.
def _mld_vox() -> dict:
    return next(c for c in applied_plan()["channels"] if c["name"] == "MLD VOX")


MLD_VOX_BASE = f"/ch/{_mld_vox()['channel']}"
MLD_VOX_LABEL = f"ch:{_mld_vox()['channel']}"
MLD_VOX_SOCKET = (_mld_vox()["patch"]["group"], _mld_vox()["patch"]["sockets"][0])


def plan_without(*names: str) -> dict:
    """The rebuild with these channels dropped -- three horns added and a
    vocalist who has left, which is the case the maintainer named."""
    plan = amended_plan()
    plan["channels"] = [c for c in plan["channels"] if c["name"] not in names]
    return plan


def removal_scenario(state: ConsoleState | None = None, *, dropped: str = "MLD VOX"):
    state = state if state is not None else occupancy_state()
    return plan_amendment(applied_plan(), plan_without(dropped),
                          strip_occupancy(state, applied_plan()))


def taken_over_state(**overrides) -> ConsoleState:
    """The occupancy read of a desk where somebody has taken 'MLD VOX's
    strip over since the plan was applied."""
    state = occupancy_state()
    values = dict(state.values)
    values.update(overrides)
    return ConsoleState(values, console_model="wing-compact")


def kinds(amendment, kind) -> list:
    return [c for c in amendment.changes if c.kind is kind]


def test_a_dropped_channel_is_returned_to_free():
    amendment = removal_scenario()
    released = kinds(amendment, ChangeKind.RELEASED)
    assert [c.where for c in released] == ["'MLD VOX'"]
    assert released[0].slot == MLD_VOX_LABEL
    assert amendment.released == [MLD_VOX_LABEL]
    assert kinds(amendment, ChangeKind.REMOVED) == []
    # The strip and its socket are granted, and by the RELEASE scope --
    # not the additions' scope, which must stay a claim about free strips
    # only.
    assert amendment.release_scope.why(f"{MLD_VOX_BASE}/mute") is not None
    assert amendment.scope.why(f"{MLD_VOX_BASE}/mute") is None
    assert amendment.release_scope.why(
        f"/io/in/{MLD_VOX_SOCKET[0]}/{MLD_VOX_SOCKET[1]}/name") is not None
    assert amendment.allows(f"{MLD_VOX_BASE}/name")
    # And still default-deny about everything else: a strip that is
    # running is no more writable because a different strip is being
    # cleared.
    assert amendment.allows("/ch/1/name") is False


def test_returned_to_free_means_muted_unpatched_and_blank():
    """"the end state should be indistinguishable from a strip
    the show never touched".

    The patch half is the maintainer's of 2026-10-20: a freed strip is left
    unpatched (OFF), as a full apply's reset leaves an unused one. 'MLD VOX'
    was on A 10; its strip goes OFF.

    Asserted as the WHOLE write set, not a sample: this list is the
    definition of "free", and something quietly dropping out of it is the
    failure mode -- a strip that is nearly free reads as somebody's work
    to the next person and to this project's own `is_in_use`.
    """
    channel = _mld_vox()
    targets = amendment_targets(removal_scenario())
    # A LIST of pairs, not a dict: `mute` is written twice on purpose
    # (on first, off last) and a dict keyed by address
    # would hide exactly the half this test now exists to pin.
    wrote = [(t.address, t.compute_value(None)) for t in targets.releases]
    group, socket = MLD_VOX_SOCKET
    applied = applied_plan()
    sends = sorted(applied["busses"][s["bus"]]["index"] for s in channel["bus_sends"])
    assert sends  # or the send arm below is vacuous
    assert channel["processing"]["hpf_hz"] is not None  # or the flt arm is
    number = channel["channel"]
    # A Compact's measured factory patch covers ch 1-24, and the kept plan
    # must not already use this strip's LCL socket, or the restore arm is
    # vacuous.
    assert number <= 24 and group != "LCL"
    assert ("LCL", number) not in {
        (c["patch"]["group"], s) for c in plan_without("MLD VOX")["channels"]
        for s in c["patch"]["sockets"]}
    assert sorted(wrote) == sorted([
        (f"{MLD_VOX_BASE}/mute", 1),
        (f"/io/in/{group}/{socket}/vph", 0),
        (f"/io/in/{group}/{socket}/name", ""),
        (f"/io/in/{group}/{socket}/col", _facts.FACTORY_SOURCE_COLOUR_INDEX),
        (f"{MLD_VOX_BASE}/in/conn/grp", "OFF"),
        (f"{MLD_VOX_BASE}/name", ""),
        (f"{MLD_VOX_BASE}/col", _facts.FACTORY_STRIP_COLOUR_INDEX),
        (f"{MLD_VOX_BASE}/clink", 1),
        (f"{MLD_VOX_BASE}/tags", ""),
        *[(f"{MLD_VOX_BASE}/send/{i}/on", 0) for i in sends],
        # Back to the factory's direct Main routing (2026-09-27): Main 1
        # ON, 2-4 OFF, whatever the plan routed -- the build writes every
        # Main, so the release puts every Main back.
        *[(f"{MLD_VOX_BASE}/main/{m}/on", 1 if m == 1 else 0) for m in range(1, 5)],
        # The plan stated a high-pass, so the plan's build wrote these
        # two and the release puts them back.
        (f"{MLD_VOX_BASE}/flt/lc", _facts.FACTORY_STRIP_PROCESSING["flt/lc"]),
        (f"{MLD_VOX_BASE}/flt/lcf", _facts.FACTORY_STRIP_PROCESSING["flt/lcf"]),
        # The factory fader, -inf: the strip goes back
        # on a live factory socket, so it must not keep the plan's level.
        (f"{MLD_VOX_BASE}/fdr", _facts.FACTORY_STRIP_FADER_DB),
        (f"{MLD_VOX_BASE}/mute", 0),
    ])

    # Muted first, unpatched only after the socket has been dealt with,
    # and unmuted last of all.
    order = [t.address for t in targets.releases]
    assert order[0] == f"{MLD_VOX_BASE}/mute"
    assert order[-1] == f"{MLD_VOX_BASE}/mute"
    assert order.index(f"/io/in/{group}/{socket}/name") < order.index(
        f"{MLD_VOX_BASE}/in/conn/grp")


def test_the_tags_write_removes_only_this_channel_s_own_tokens():
    """`{base}/tags` is a shared field. A strip may carry a token this
    plan never put there, and removing that would be wiping a field
    rather than returning a strip to free -- the subtractive mirror of
    `_merge_tags` being additive."""
    from atoo.apply import _released_tags

    channel = _mld_vox()
    applied = applied_plan()
    dcas = [applied["dcas"][d]["index"] for d in channel["dca"]]
    mutes = [applied["mute_groups"][m]["index"] for m in channel["mute_group"]]
    target = next(t for t in amendment_targets(removal_scenario()).releases
                  if t.address.endswith("/tags"))
    ours = ",".join([f"#D{i}" for i in dcas] + [f"#M{i}" for i in mutes])
    assert target.compute_value(ours) == ""
    assert target.compute_value(f"{ours},#D9") == "#D9"
    assert _released_tags("#D9,#M9", dcas, mutes) == "#D9,#M9"


def test_a_release_pulls_the_fader_to_the_factory_reading_and_nothing_else():
    """The maintainer, 2026-09-24. Release now restores the factory patch, so a
    strip left unmuted at the plan's level would carry a stray source on
    its factory jack to Main 1. The fader goes to -inf -- the reading all
    40 strips of both initialized snapshots give -- and to no other value:
    a level chosen for a strip no plan is building is still the mixing
    `apply.py` must never do.

    And it lands BEFORE the closing unmute: the strip is silent by level
    before it stops being silent by mute. Reversed, there is a window in
    which a stray source is live at the plan's level."""
    targets = amendment_targets(removal_scenario())
    releases = targets.releases
    faders = [t for t in releases if t.address.endswith("/fdr")]
    assert len(faders) == len({t.address.rsplit("/", 1)[0] for t in faders}) >= 1
    for fader in faders:
        assert fader.compute_value(None) == _facts.FACTORY_STRIP_FADER_DB == -144.0
        base = fader.address.rsplit("/", 1)[0]
        mutes = [i for i, t in enumerate(releases) if t.address == f"{base}/mute"]
        assert mutes, "the release is bracketed by mute writes"
        assert mutes[0] < releases.index(fader) < mutes[-1], (
            "fader must come after the opening mute and before the closing unmute")


def test_the_colour_written_back_is_a_value_the_console_has():
    """`ch.{n}.col` is `int [1 .. 18]` in the parameter map -- there is no
    colour 0, so "no colour" is 1, measured off an untouched strip of the
    A13 capture. A release that wrote 0 would be out of the console's
    range, which is an error and not a preference."""
    assert _facts.FACTORY_STRIP_COLOUR_INDEX == 1
    targets = amendment_targets(removal_scenario())
    for target in targets.releases:
        if target.address.endswith("/col"):
            assert 1 <= target.compute_value(None) <= 18


def test_an_icon_the_plan_never_set_is_never_cleared():
    """A release undoes what this plan's own build wrote and nothing
    more. The touring-band plan states no icon, so it wrote no icon, so
    there is no icon of somebody's to blank."""
    assert _mld_vox().get("icon") is None
    targets = amendment_targets(removal_scenario())
    assert not [t for t in targets.releases if t.address.endswith("/icon")]


def test_a_stated_icon_is_cleared_to_the_factory_reading_for_its_group():
    """And when the plan DID write one, it comes back off -- to the value
    an untouched socket of that group carries, which on LCL is 1 and not
    0. Measured across the A13 capture."""
    applied = applied_plan()
    target_channel = next(c for c in applied["channels"] if c["name"] == "MLD VOX")
    target_channel["icon"] = 42
    target_channel["patch"] = {"group": "LCL", "sockets": [7], "stated": True}
    rebuilt = plan_without("MLD VOX")
    values = dict(occupancy_state(plan=applied).values)
    amendment = plan_amendment(applied, rebuilt, strip_occupancy(
        ConsoleState(values, console_model="wing-compact"), applied))
    assert kinds(amendment, ChangeKind.RELEASED)
    wrote = {t.address: t.compute_value(None)
             for t in amendment_targets(amendment).releases}
    assert wrote[f"{MLD_VOX_BASE}/icon"] == 0
    assert wrote["/io/in/LCL/7/icon"] == 1


# --- The refusals. Untracked state is never cleared. ----------------------


def test_a_podium_shaped_strip_is_never_cleared():
    """**The test this feature exists to pass.**

    The strip is in the applied plan -- so it is a removal, and every
    signal a strip normally gives off says it is ours to clear. It is not.
    Somebody has taken it over the way a person actually takes a strip
    over on a WING, which is the shape the maintainer's channel 20 had on
    2026-09-22: **blank at `/ch/{n}/name`, sitting on the
    Compact's factory patch, and named only on its SOURCE socket**, where
    a name typed on the desk really lands while `clink` is on.

    A check that read the strip alone would clear it, and clearing a
    strip somebody else is using is the thing this must never do.

    Mutation-checked, 2026-09-23: making `amend.release_refusal` return
    None unconditionally fails this test. So does neutralising either arm
    on its own -- see `test_a_strip_named_only_on_its_source_is_never
    _cleared` for the socket arm by itself.
    """
    state = taken_over_state(**{
        f"{MLD_VOX_BASE}/name": "",
        f"{MLD_VOX_BASE}/in/conn/grp": "LCL",
        f"{MLD_VOX_BASE}/in/conn/in": _mld_vox()["channel"],
        f"/io/in/LCL/{_mld_vox()['channel']}/name": "Podium",
    })
    amendment = removal_scenario(state)

    assert amendment.released == []
    assert amendment.releases == []
    removed = kinds(amendment, ChangeKind.REMOVED)
    assert [c.where for c in removed] == ["'MLD VOX'"]
    assert "NOT returned to free" in removed[0].reason
    assert kinds(amendment, ChangeKind.RELEASED) == []

    # And nothing is generated for it -- not a write, not a grant, not a
    # baseline read. "We only read it" is not a distinction worth having.
    targets = amendment_targets(amendment)
    assert targets.releases == []
    assert not [t for t in targets.to_write if t.address.startswith(MLD_VOX_BASE + "/")]
    assert not [t for t in targets.to_write if t.address.startswith("/io/in/LCL/")]
    assert amendment.release_scope.grants == {}
    assert amendment.allows(f"{MLD_VOX_BASE}/name") is False


def test_a_strip_named_only_on_its_source_is_never_cleared():
    """The socket arm on its own, with every other signal saying ours:
    the patch is exactly the one this plan made, the strip's own name is
    blank -- and the socket carries a name this plan did not write there.

    This is the arm `audit.is_in_use` does not have, and it
    is the only thing between a release and somebody's live channel.
    """
    group, socket = MLD_VOX_SOCKET
    state = taken_over_state(**{
        f"{MLD_VOX_BASE}/name": "",
        f"/io/in/{group}/{socket}/name": "Podium",
    })
    amendment = removal_scenario(state)
    assert amendment.released == []
    reason = kinds(amendment, ChangeKind.REMOVED)[0].reason
    assert f"source {group} {socket} is named 'Podium'" in reason


def test_a_strip_that_never_answered_is_never_cleared():
    """An unread address is not evidence of an empty strip. OPTIONS-H's
    rule for placement -- "an unread strip is not a safe strip" -- binds
    at least as hard when the write is a clear."""
    values = dict(occupancy_state().values)
    del values[f"{MLD_VOX_BASE}/name"]
    amendment = removal_scenario(ConsoleState(values, console_model="wing-compact"))
    assert amendment.released == []
    assert "never answered" in kinds(amendment, ChangeKind.REMOVED)[0].reason


def test_a_repatched_strip_is_never_cleared():
    state = taken_over_state(**{
        f"{MLD_VOX_BASE}/in/conn/grp": "B",
        f"{MLD_VOX_BASE}/in/conn/in": 4,
        "/io/in/B/4/name": "",  # blank, so ONLY the patch arm can fire
    })
    amendment = removal_scenario(state)
    assert amendment.released == []
    assert "somebody has repatched the strip" in kinds(
        amendment, ChangeKind.REMOVED)[0].reason


def test_a_renamed_strip_is_never_cleared():
    state = taken_over_state(**{f"{MLD_VOX_BASE}/name": "Guest Vox"})
    amendment = removal_scenario(state)
    assert amendment.released == []
    assert "somebody has renamed the strip" in kinds(
        amendment, ChangeKind.REMOVED)[0].reason


def test_a_strip_somebody_already_freed_by_hand_is_still_cleared():
    """Unpatched and blank is a reading a strip this plan built can give
    once somebody has started tidying it. Refusing there would leave a
    half-freed strip that nothing ever finishes."""
    group, socket = MLD_VOX_SOCKET
    state = taken_over_state(**{
        f"{MLD_VOX_BASE}/name": "",
        f"{MLD_VOX_BASE}/in/conn/grp": "OFF",
        f"{MLD_VOX_BASE}/in/conn/in": 0,
        f"/io/in/{group}/{socket}/name": "",
    })
    amendment = removal_scenario(state)
    assert amendment.released == [MLD_VOX_LABEL]


def test_a_factory_label_on_the_strip_still_reads_as_ours():
    """`CH14` is the desk's own label, not somebody's name."""
    state = taken_over_state(**{f"{MLD_VOX_BASE}/name": "CH14"})
    assert removal_scenario(state).released == [MLD_VOX_LABEL]


def test_a_release_never_clears_a_socket_a_kept_strip_still_uses():
    """One jack feeding a strip that is going and a strip that is staying
    is an ordinary request. Clearing its label would take the name off a
    channel nobody asked to remove."""
    applied = applied_plan()
    going = next(c for c in applied["channels"] if c["name"] == "MLD VOX")
    staying = next(c for c in applied["channels"] if c["name"] == "Kick")
    going["patch"] = dict(staying["patch"])
    rebuilt = plan_without("MLD VOX")
    for channel in rebuilt["channels"]:
        if channel["name"] == "Kick":
            channel["patch"] = dict(staying["patch"])
    values = dict(occupancy_state(plan=applied).values)
    group, socket = staying["patch"]["group"], staying["patch"]["sockets"][0]
    # What `apply` really wrote on a socket feeding two strips: the
    # composite label, not either strip's own name.
    values[f"/io/in/{group}/{socket}/name"] = "Kick/MLD VOX"
    state = ConsoleState(values, console_model="wing-compact")
    amendment = plan_amendment(applied, rebuilt, strip_occupancy(state, applied))
    assert amendment.released == [MLD_VOX_LABEL]
    assert amendment.release_scope.why(f"/io/in/{group}/{socket}/name") is None
    addresses = [t.address for t in amendment_targets(amendment).releases]
    assert not [a for a in addresses if a.startswith(f"/io/in/{group}/{socket}/")]
    assert f"{MLD_VOX_BASE}/mute" in addresses
    assert any("still feeds a strip the rebuild keeps" in w for w in amendment.warnings)


def test_the_collision_guard_still_refuses_everything_but_the_release():
    """The deliberate overlap is named, not folded in. A release writes
    addresses the applied plan wrote -- that is what it means -- and every
    OTHER overlap is still the refusal it was."""
    amendment = removal_scenario()
    assert amendment_targets(amendment).collisions == []
    # Grant a running strip through the ADDITIONS scope and the guard
    # fires again, unchanged.
    amendment.scope.grant("/ch/1", "a bug in the prefix matcher")
    assert amendment_targets(amendment).collisions


# --------------------------------------------------------------------------
# 3 & 4. The filter, the withheld set, and the proof
# --------------------------------------------------------------------------


def test_scope_is_default_deny():
    scope = AmendScope()
    scope.grant("/ch/21", "new channel")
    assert scope.allows("/ch/21")
    assert scope.allows("/ch/21/send/8/on")
    assert not scope.allows("/ch/22/name")
    # A prefix must not leak into a longer strip number.
    assert not scope.allows("/ch/210/name")
    assert scope.why("/ch/21/fdr") == "new channel"
    assert scope.why("/ch/1/fdr") is None


def test_withheld_is_everything_a_full_build_would_have_written():
    amendment = scenario()
    targets = amendment_targets(amendment)
    assert targets.collisions == []
    written = {t.address for t in targets.to_write}
    withheld = {t.address for t in targets.withheld}
    assert not written & withheld
    # Every running strip's every parameter is in the withheld set.
    assert "/ch/1/fdr" in withheld and "/ch/1/name" in withheld
    assert "/ch/1/send/5/lvl" in withheld and "/ch/1/tags" in withheld
    assert "/bus/5/fdr" in withheld and "/dca/1/name" in withheld
    # And nothing belonging to a running strip is on the write side.
    assert not [a for a in written if a.startswith(tuple(f"/ch/{n}/" for n in range(1, 21)))]


def test_the_collision_check_catches_a_scope_that_grants_a_running_strip():
    """The second guard, derived from the other side: an address both
    plans write belongs to a running object, whatever the matcher says."""
    amendment = scenario()
    amendment.scope.grant("/ch/1", "deliberately wrong")
    targets = amendment_targets(amendment)
    assert "/ch/1/name" in targets.collisions
    with pytest.raises(AmendRefused, match="the scope is wrong"):
        apply_amendment(amendment, FakeConsole(), dry_run=True, targets=targets)


# --------------------------------------------------------------------------
# THE untouched-strip proof.
# --------------------------------------------------------------------------


class DeskConsole(FakeConsole):
    """`FakeConsole` plus the one hardware quirk a full, real plan runs
    into: WING answers a connector or colour index ONE LOWER than the SET
    that put it there (`console_facts.readback_index_offset`),
    and `apply.py` corrects for that on readback. A naive round-trip fake
    reports a mismatch on every colour and every patch, which would make
    the proof below fail for a reason that has nothing to do with scope.
    Stored values are what the SET carried; reads answer what the desk
    would answer."""

    def _reply_to(self, address: str):
        reply = super()._reply_to(address)
        offset = _facts.readback_index_offset(address)
        if (offset and reply is not None and reply.args
                and isinstance(reply.args[0], int) and not isinstance(reply.args[0], bool)):
            return OscReply(address=reply.address, typetag=reply.typetag,
                            args=[reply.args[0] - offset])
        return reply


_FACTORY = {"s": "", "i": 0, "f": 0.0}

#: The only objects this amend owns: the three horn strips and the
#: three input sockets they are patched to. Everything else on the desk
#: is the running show or somebody else's.
OURS = ("/ch/21", "/ch/22", "/ch/23", "/io/in/A/21", "/io/in/A/22", "/io/in/A/23")


def is_ours(address: str) -> bool:
    """Written out longhand rather than reusing `AmendScope.allows`: this
    is the independent check, and a proof that calls the code it is
    proving is not a proof. `set_node` addresses the NODE (`/ch/21` with
    `name=Trumpet,...`), so an equality arm is needed alongside the
    prefix one -- and the prefix arm carries its own separator, or
    `/ch/210` would pass as `/ch/21`."""
    return any(address == base or address.startswith(base + "/") for base in OURS)



def full_console_state() -> dict:
    """A FakeConsole seeding for a desk that has the show on it: every address the
    applied plan wrote holds the value it wrote, and every other address
    a build of the amended plan would touch answers with a factory value.

    Both halves matter. Without the first, "unchanged" would be
    indistinguishable from "never written". Without the second, the new
    horn strips' addresses would read as unreadable and `apply_plan`
    would skip them -- a test that proved nothing by writing nothing,
    which is exactly what `test_untouched_strips`'s first assertion
    guards against.
    """
    from atoo.apply import _build_write_targets

    state: dict = {}
    for plan, factory in ((amended_plan(), True), (applied_plan(), False)):
        targets, _ = _build_write_targets(plan, set_fader_levels=True)
        for t in targets:
            state[t.address] = ((_FACTORY[t.value_type], t.value_type) if factory
                                else (t.compute_value(None), t.value_type))
    return state


def test_untouched_strips(tmp_path):
    """**The most important test in this PR.**

    Strips 1-19 are the running show, 20 is somebody else's, 21-40 free.
    An amend writing 21-23 must leave every other address alone -- proved
    three ways, since one way is a claim about the code and the other two
    are claims about what reached the wire:

    1. every address the console was asked to write is one of ours;
    2. FR-2.2's own proof -- read every unrelated address before the
       delta and again after, and assert equality;
    3. the console never even received a GET for an unrelated address.
    """
    amendment = scenario()
    targets = amendment_targets(amendment)
    console = DeskConsole(full_console_state())
    witness = witness_addresses(targets)
    before = read_witness(console, witness)
    gets_during_witness = len(console._get_call_counts)

    journal = tmp_path / "amend-journal.json"
    result = apply_amendment(amendment, console, dry_run=False,
                             journal_path=str(journal), targets=targets)

    # 1. Address by address, everything the console was told to change.
    touched = ([address for address, _v, _t in console.set_param_calls]
               + [address for address, _payload in console.set_node_calls])
    assert touched, "the amend wrote nothing at all, so this proves nothing"
    strayed = sorted({a for a in touched if not is_ours(a)})
    assert strayed == [], f"the amend wrote outside its scope: {strayed}"

    # 2. FR-2.2: "verified by reading back every parameter of every
    #    unrelated channel before and after the delta and asserting
    #    equality -- not merely by not writing to it."
    after = read_witness(console, witness)
    assert witness_changes(before, after, witness) == []
    assert len(witness) > 500, "the witness must cover the whole running show"

    # 3. Not read, either -- the filter drops a foreign target before the
    #    baseline GET, so an unrelated address is never addressed at all.
    asked = set(console._get_call_counts) - {a for a, _ in witness}
    assert not [a for a in asked if not is_ours(a)]
    assert gets_during_witness  # the witness read really happened

    # And the run did something: the horns landed.
    assert result.mismatches == []
    assert {w.address for w in result.writes} >= {
        "/ch/21/name", "/ch/22/name", "/ch/23/name", "/ch/21/fdr"}
    assert json.loads(journal.read_text())["scope"]["strips"] == ["ch:21", "ch:22", "ch:23"]


def release_console() -> "DeskConsole":
    """The same desk `test_untouched_strips` uses, seeded for a rebuild
    that drops 'MLD VOX' -- so the strip being released holds exactly what
    the applied plan wrote to it."""
    from atoo.apply import _build_write_targets

    state: dict = {}
    for plan, factory in ((plan_without("MLD VOX"), True), (applied_plan(), False)):
        built, _ = _build_write_targets(plan, set_fader_levels=True)
        for t in built:
            state[t.address] = ((_FACTORY[t.value_type], t.value_type) if factory
                                else (t.compute_value(None), t.value_type))
    # The strip's fader as a real WING answers it -- a FLOAT (the seeding
    # above carries the plan's JSON integer -144, which `OscReply.value('f')`
    # rightly does not read as a float) -- and RAISED, because a raised
    # fader is the case release's -inf write exists for: -144 here would
    # pass as `skipped_no_change` and prove nothing.
    state[f"{MLD_VOX_BASE}/fdr"] = (-5.0, "f")
    return DeskConsole(state)


def test_a_release_is_previewed_and_nothing_is_written_without_confirm():
    """"a removal is the one change a reviewer most needs to
    see in the preview, and `apply` without `--confirm` must show it and
    write nothing"."""
    amendment = removal_scenario()
    targets = amendment_targets(amendment)
    console = release_console()
    result = apply_amendment(amendment, console, dry_run=True, targets=targets)

    assert console.set_param_calls == [] and console.set_node_calls == []
    previewed = {w.address for w in result.writes if w.status == "dry_run"}
    assert previewed >= {t.address for t in targets.releases}
    # A preview that shows the before AND the after for the clear, which
    # is the whole point of showing it.
    name = next(w for w in result.writes if w.address == f"{MLD_VOX_BASE}/name")
    assert (name.prior_value, name.intended_value) == ("MLD VOX", "")
    assert name.would_change
    # And it says so in words, ahead of the write.
    assert "RETURN A STRIP TO FREE" in targets.summary()
    assert f"{MLD_VOX_BASE}/mute" in targets.summary()
    assert "1 returned to free" in amendment.summary()
    assert f"returns to free: {MLD_VOX_LABEL}" in amendment.summary()


def test_a_release_lands_is_readback_proved_and_is_journalled(tmp_path):
    """Same proof path as every other write: a baseline read before, the
    value read back after, and a journal row carrying both."""
    amendment = removal_scenario()
    targets = amendment_targets(amendment)
    console = release_console()
    journal = tmp_path / "amend-journal.json"
    result = apply_amendment(amendment, console, dry_run=False,
                             journal_path=str(journal), targets=targets)

    assert result.mismatches == []
    # Zipped rather than looked up by address: `mute` appears twice
    #  and a dict would silently compare the second write
    # against the first target.
    tail = result.writes[-len(targets.releases):]
    assert [w.address for w in tail] == [t.address for t in targets.releases]
    records = {w.address: w for w in result.writes}
    for record, target in zip(tail, targets.releases):
        assert record.status in ("match", "skipped_no_change"), record
        assert record.intended_value == target.compute_value(None)
    assert records[f"{MLD_VOX_BASE}/name"].prior_value == "MLD VOX"
    assert records[f"{MLD_VOX_BASE}/name"].status == "match"

    recorded = json.loads(journal.read_text())
    # `released` is its own key: "we wrote this strip" and "we cleared
    # this strip" are different answers to the question a journal is
    # asked, and FR-2.5 replays prior values either way.
    assert recorded["scope"]["released"] == [MLD_VOX_LABEL]
    assert MLD_VOX_LABEL not in recorded["scope"]["strips"]
    assert recorded["scope"]["grants"][MLD_VOX_BASE].startswith("returning channel 'MLD VOX'")
    rows = {w["address"]: w for w in recorded["writes"]}
    assert rows[f"{MLD_VOX_BASE}/name"]["prior_value"] == "MLD VOX"
    assert rows[f"{MLD_VOX_BASE}/name"]["intended_value"] == ""


def test_a_released_strip_reads_unmuted_afterwards():
    """An earlier change, the first of the two properties the first hardware run
    found missing: A15 cleared ch:18 and the strip came back **muted**.

    The own success test is "indistinguishable from a strip the show
    never touched", and an untouched WING strip is unmuted. The mute is a
    bracket around the clear -- on first so nothing pops while the strip
    is taken apart, off last -- and this asserts the END of that, on the
    desk, after the whole run, rather than the presence of a target in a
    list.

    The bracket itself is asserted too: the run must genuinely have muted
    the strip on the way in, or this is just "we never muted it".
    """
    amendment = removal_scenario()
    targets = amendment_targets(amendment)
    console = release_console()
    result = apply_amendment(amendment, console, dry_run=False, targets=targets)

    assert result.mismatches == []
    reply = console.get(f"{MLD_VOX_BASE}/mute")
    assert reply is not None
    assert reply.value("i") == (0, None)

    mutes = [w for w in result.writes if w.address == f"{MLD_VOX_BASE}/mute"]
    assert [w.intended_value for w in mutes] == [1, 0]
    # ...and the unmute is the very last thing the run does to that strip,
    # so nothing after it can put audio through an unmuted one.
    strip_rows = [w.address for w in result.writes
                  if w.address.startswith(MLD_VOX_BASE + "/")]
    assert strip_rows[-1] == f"{MLD_VOX_BASE}/mute"
    # The fader: pulled from the raised level `release_console` seeds to
    # the factory -inf, proved on the desk, and BEFORE the unmute
    #  -- silent by level before it stops being
    # silent by mute.
    faders = [w for w in result.writes if w.address == f"{MLD_VOX_BASE}/fdr"]
    assert [(w.prior_value, w.intended_value, w.status) for w in faders] == [
        (-5.0, -144.0, "match")]
    assert console.get(f"{MLD_VOX_BASE}/fdr").value("f") == (-144.0, None)
    assert strip_rows.index(f"{MLD_VOX_BASE}/fdr") < len(strip_rows) - 1


def test_a_released_strip_carries_no_filter_the_plan_set():
    """The other half: A15's ch:18 came back still carrying the
    plan's 120Hz high-pass.

    A stale filter on a strip this tool has just advertised as free is
    invisible until somebody patches a mic into it, and then it is a
    filter nobody set and nobody can account for. Asserted against the
    desk after the run, and against the reading an untouched strip gives
    (`console_facts.FACTORY_STRIP_PROCESSING`, measured across all 48
    strips of A8-initialized.snap) rather than against "not 120".
    """
    channel = _mld_vox()
    assert channel["processing"]["hpf_hz"] == 120  # or there is nothing to clear

    amendment = removal_scenario()
    targets = amendment_targets(amendment)
    console = release_console()
    # The strip starts out holding what the applied plan wrote -- the
    # filter in circuit at 120Hz -- or this test proves nothing.
    assert console.get(f"{MLD_VOX_BASE}/flt/lc").value("i") == (1, None)
    assert console.get(f"{MLD_VOX_BASE}/flt/lcf").value("f") == (120.0, None)

    result = apply_amendment(amendment, console, dry_run=False, targets=targets)
    assert result.mismatches == []

    assert console.get(f"{MLD_VOX_BASE}/flt/lc").value("i") == (
        _facts.FACTORY_STRIP_PROCESSING["flt/lc"], None)
    assert console.get(f"{MLD_VOX_BASE}/flt/lcf").value("f") == (
        _facts.FACTORY_STRIP_PROCESSING["flt/lcf"], None)


def test_a_release_clears_only_the_processing_this_plan_wrote():
    """The bound, from the other side: undo what this plan wrote, never
    more. The touring-band plan states a high-pass and nothing else, so a
    release writes `flt/lc` and `flt/lcf` and touches no other processing
    leaf -- an EQ, a trim or a hi-cut on that strip is somebody else's and
    stays.

    And head-amp gain is out of scope by construction: it is built at
    `STAGE_PHANTOM`, on the socket, not at `STAGE_PROCESSING` on the
    strip.
    """
    from atoo.apply import STAGE_PROCESSING

    channel = _mld_vox()
    assert {k for k, v in channel["processing"].items() if v is not None} == {"hpf_hz"}
    targets = amendment_targets(removal_scenario())
    processing = [t for t in targets.releases if t.stage == STAGE_PROCESSING]
    # The value before its switch: a strip's processing is written in
    # `preset_expand.write_order`, selectors, values, switches.
    assert [t.address for t in processing] == [
        f"{MLD_VOX_BASE}/flt/lcf", f"{MLD_VOX_BASE}/flt/lc"]
    # Nothing at all under eq/peq/in-set, and no head-amp gain anywhere.
    for t in targets.releases:
        assert "/eq/" not in t.address and "/peq/" not in t.address
        assert "/in/set/" not in t.address
        assert not t.address.endswith("/g")


def test_a_plan_that_stated_no_processing_clears_none():
    """The same bound at zero: a channel whose plan entry sets no
    processing has no processing of ours on the desk, so a release
    generates nothing for it. This is what stops a clear from wiping a
    filter somebody set by hand on a strip we merely patched."""
    from atoo.apply import STAGE_PROCESSING

    applied = applied_plan()
    target_channel = next(c for c in applied["channels"] if c["name"] == "MLD VOX")
    target_channel["processing"] = {k: None for k in target_channel["processing"]}
    rebuilt = plan_without("MLD VOX")
    amendment = plan_amendment(applied, rebuilt, strip_occupancy(
        occupancy_state(plan=applied), applied))
    assert kinds(amendment, ChangeKind.RELEASED)
    targets = amendment_targets(amendment)
    assert not [t for t in targets.releases if t.stage == STAGE_PROCESSING]


def test_a_processing_leaf_with_no_measured_factory_reading_is_warned_about():
    """A leaf this plan wrote whose untouched reading nobody has measured
    is left alone and SAID so, never guessed at. Writing an invented
    value onto a strip this tool has just called free is the same defect
    as leaving the filter on, one layer down."""
    from atoo import apply as apply_module

    channel = dict(_mld_vox())
    warnings: list[str] = []
    saved = dict(_facts.FACTORY_STRIP_PROCESSING)
    try:
        _facts.FACTORY_STRIP_PROCESSING.pop("flt/lcf")
        targets = apply_module.release_write_targets(
            [channel], bus_index={}, dca_index={}, mute_group_index={},
            warnings=warnings)
    finally:
        _facts.FACTORY_STRIP_PROCESSING.clear()
        _facts.FACTORY_STRIP_PROCESSING.update(saved)
    assert not [t for t in targets if t.address.endswith("/flt/lcf")]
    assert any("flt/lcf" in w and "nothing has measured" in w for w in warnings)


def test_a_cleared_strip_that_did_not_clear_is_reported_as_a_mismatch():
    """"A cleared strip that did not clear is a value that did not land,
    and gets reported as one." The console accepts the write on the wire
    and stores nothing, which is the failure readback verification exists
    for -- and the one a clear must not be exempt from."""
    amendment = removal_scenario()
    targets = amendment_targets(amendment)
    console = release_console()
    console.reject_writes_to = {f"{MLD_VOX_BASE}/name"}
    result = apply_amendment(amendment, console, dry_run=False, targets=targets)
    assert [m.address for m in result.mismatches] == [f"{MLD_VOX_BASE}/name"]
    assert f"MISMATCH {MLD_VOX_BASE}/name" in result.summary()


def test_a_released_strip_reads_as_free_on_the_next_occupancy_read():
    """The end-to-end claim an earlier change actually makes: "the end state
    should be indistinguishable from a strip the show never touched, so
    the next person allocating one finds it genuinely free rather than
    nearly free."

    Written by taking the desk the release left behind and asking the
    occupancy read about it again, with the rebuild as the applied plan --
    which is what the next amend will do.
    """
    amendment = removal_scenario()
    console = release_console()
    # The socket the strip goes back to, as an untouched desk answers for
    # it: blank (`console_facts.FACTORY_SOURCE_NAME`). `release_console`
    # seeds only what a build writes, and a build of this plan never
    # names LCL n -- so without this the next read would find the socket
    # unanswered and say UNKNOWN, which a real desk would not.
    factory_socket = ("LCL", _mld_vox()["channel"])
    console.state[f"/io/in/LCL/{factory_socket[1]}/name"] = (_facts.FACTORY_SOURCE_NAME, "s")
    before = strip_occupancy(
        ConsoleState({a: v for a, (v, _t) in console.state.items()},
                     console_model="wing-compact"), plan_without("MLD VOX"))
    assert {s.label: s.state for s in before}[MLD_VOX_LABEL] is StripState.THEIRS

    apply_amendment(amendment, console, dry_run=False)
    after = strip_occupancy(
        ConsoleState({a: v for a, (v, _t) in console.state.items()},
                     console_model="wing-compact"), plan_without("MLD VOX"))
    status = {s.label: s for s in after}[MLD_VOX_LABEL]
    assert status.state is StripState.FREE
    assert status.available is True
    assert status.name == ""
    # Unpatched (2026-10-20), as a full apply leaves an unused strip.
    assert status.patch is None


def test_a_release_writes_nothing_outside_the_strip_and_its_socket():
    """The same claim `test_untouched_strips` makes about additions, made
    about a clear: no address of any other strip is so much as read."""
    amendment = removal_scenario()
    console = release_console()
    apply_amendment(amendment, console, dry_run=False)
    group, socket = MLD_VOX_SOCKET
    ours = OURS + (MLD_VOX_BASE, f"/io/in/{group}/{socket}")
    touched = ([a for a, _v, _t in console.set_param_calls]
               + [a for a, _p in console.set_node_calls])
    assert touched
    assert not [a for a in touched
                if not any(a == b or a.startswith(b + "/") for b in ours)]


def test_a_refused_removal_reaches_the_wire_as_nothing_at_all():
    """The Podium strip again, this time all the way to the console: not
    written, and not read either. "We only read it" is not a distinction
    worth having to explain."""
    state = taken_over_state(**{
        f"{MLD_VOX_BASE}/name": "",
        f"{MLD_VOX_BASE}/in/conn/grp": "LCL",
        f"{MLD_VOX_BASE}/in/conn/in": _mld_vox()["channel"],
        f"/io/in/LCL/{_mld_vox()['channel']}/name": "Podium",
    })
    amendment = removal_scenario(state)
    console = release_console()
    apply_amendment(amendment, console, dry_run=False)
    touched = ([a for a, _v, _t in console.set_param_calls]
               + [a for a, _p in console.set_node_calls]
               + list(console._get_call_counts))
    assert not [a for a in touched if a.startswith(MLD_VOX_BASE)]
    assert not [a for a in touched if a.startswith("/io/in/LCL/")]


def test_the_untouched_proof_catches_a_broken_target_filter():
    """The mutation `test_untouched_strips` exists to catch, run as a test
    in its own right: widen the scope by one running strip and watch each
    arm of the proof fire.

    The rebuild is given one extra change -- the Kick's high-pass moved
    from 40Hz to 200Hz -- so that a scope bug has something to actually
    do. A correct amend classifies that as MODIFIED and refuses to write
    it (the strip is in use); a broken filter writes it to the running
    show mid-set, which is precisely FR-2.2's failure.
    """
    plan = amended_plan()
    for channel in plan["channels"]:
        if channel["name"] == "Kick":
            channel["processing"]["hpf_hz"] = 200

    # The witness comes from the CORRECT amendment: these are the
    # addresses the amend promises not to move.
    good = plan_amendment(applied_plan(), plan, occupancy())
    witness = witness_addresses(amendment_targets(good))
    assert ("/ch/1/flt/lcf", "f") in witness

    broken = plan_amendment(applied_plan(), plan, occupancy())
    broken.scope.grant("/ch/1", "the mutation: a running strip")
    targets = amendment_targets(broken)

    # Guard 2 catches it on its own, before anything is sent.
    assert "/ch/1/flt/lcf" in targets.collisions
    with pytest.raises(AmendRefused):
        apply_amendment(broken, DeskConsole(full_console_state()), dry_run=False,
                        targets=targets)

    # Go around that guard, to prove the desk-side proof would have
    # caught it too rather than the two overlapping.
    targets.collisions = []
    console = DeskConsole(full_console_state())
    before = read_witness(console, witness)
    apply_amendment(broken, console, dry_run=False, targets=targets)
    after = read_witness(console, witness)

    touched = ([a for a, _v, _t in console.set_param_calls]
               + [a for a, _p in console.set_node_calls])
    assert [a for a in touched if not is_ours(a)], \
        "a widened scope must show up as a write outside it"
    assert "/ch/1/flt/lcf" in witness_changes(before, after, witness)


def test_witness_changes_reports_an_address_that_moved():
    witness = [("/ch/1/name", "s"), ("/ch/1/fdr", "f")]
    before = {"/ch/1/name": "Kick", "/ch/1/fdr": 0.0}
    after = {"/ch/1/name": "Trumpet", "/ch/1/fdr": 0.0}
    assert witness_changes(before, after, witness) == ["/ch/1/name"]


def test_witness_changes_tolerates_a_stepped_float():
    """Compared with `apply._values_equal`, the same comparison the write
    path uses -- a desk that rounds 100Hz to 100.237Hz has not moved."""
    witness = [("/ch/1/flt/lcf", "f")]
    assert witness_changes({"/ch/1/flt/lcf": 100.0},
                           {"/ch/1/flt/lcf": 100.237}, witness) == []


def test_witness_reports_an_address_that_stopped_answering():
    witness = [("/ch/1/name", "s")]
    assert witness_changes({"/ch/1/name": "Kick"},
                           {"/ch/1/name": amend.UNREAD}, witness) == ["/ch/1/name"]
    # Unread before and unread after is a clean pass, not a change.
    assert witness_changes({"/ch/1/name": amend.UNREAD},
                           {"/ch/1/name": amend.UNREAD}, witness) == []


class SilentConsole:
    """A desk that answers nothing at all -- `WingConsole.get` returns
    None on a timeout, which `FakeConsole` never does (it answers an
    unseeded address with a NODE NOT FOUND error instead). Both are
    "we do not know", and the witness has to record both."""

    def get(self, address):
        return None


def test_read_witness_records_an_unanswered_address_rather_than_dropping_it():
    # The error path: the console answered, with an error.
    console = FakeConsole({"/ch/1/name": ("Kick", "s")})
    values = read_witness(console, [("/ch/1/name", "s"), ("/ch/2/name", "s")])
    assert values == {"/ch/1/name": "Kick", "/ch/2/name": amend.UNREAD}
    # The timeout path: the console did not answer at all. Dropping it
    # would let a strip that stopped answering halfway through the delta
    # look untouched, which is the one reading the witness must not make.
    assert read_witness(SilentConsole(), [("/ch/1/name", "s")]) == {
        "/ch/1/name": amend.UNREAD}


# --------------------------------------------------------------------------
# The apply.py seam
# --------------------------------------------------------------------------


def test_target_filter_drops_targets_before_the_baseline_read():
    from atoo.apply import apply_plan

    console = DeskConsole(full_console_state())
    apply_plan(applied_plan(), console, dry_run=True,
               target_filter=lambda t: t.address == "/ch/1/name")
    assert set(console._get_call_counts) == {"/ch/1/name"}


def test_a_full_build_journal_still_has_no_scope_field(tmp_path):
    from atoo.apply import apply_plan

    journal = tmp_path / "j.json"
    apply_plan({"channels": []}, FakeConsole(), dry_run=True, journal_path=str(journal))
    assert "scope" not in json.loads(journal.read_text())


def test_declared_output_patches_skips_a_bare_list_entry():
    """Its docstring promises malformed entries are skipped; `bus or {}`
    let a truthy non-dict through to `.get` and raised AttributeError.
    `archive/examples/archive/smallband.gemma3:4b.plan.json` has exactly that
    shape for a dca entry, so an amend reading an old plan off disk would
    have hit it."""
    from atoo.apply import _declared_output_patches

    assert _declared_output_patches({"busses": {"Drums": ["not", "a", "dict"]},
                                     "outputs": {"Main": ["nor", "this"]}}) == {}


def test_targets_only_carry_the_warnings_the_new_objects_caused():
    """A build of the effective plan warns about every strip in it, most
    of which were applied hours ago. Printing those in a review buries the one
    that is about tonight.

    Uses the smallband demo rather than the touring band, because
    smallband's patches are unstated and so it actually produces the
    nine "patch socket was not stated" warnings the amend must not
    repeat. Against a plan with no warnings at all this test would pass
    whatever the code did.
    """
    from atoo.apply import _build_write_targets

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())
    state = _load_demo_state()
    amendment = plan_amendment(applied, rebuilt,
                               strip_occupancy(state, applied))
    _all, all_warnings = _build_write_targets(amendment.effective_plan,
                                              set_fader_levels=True)
    assert [w for w in all_warnings if "'Kick'" in w], "fixture must produce a stale warning"
    assert not [w for w in amendment_targets(amendment).warnings if "'Kick'" in w]


# --------------------------------------------------------------------------
# The CLI, offline -- `atoo amend --state FILE` contacts nothing.
# --------------------------------------------------------------------------

# Frozen copies of the amend walkthrough's files (`amend-demo/` and
# `smallband.plan.json`; the worked example in `docs/user/applying.md`).
# The tests below assert on what is in them -- "11 ours, 1 theirs",
# "'Trumpet' -> ch:12" -- so they read these copies, which do not move
# when a show is rebuilt.
FIXTURES = Path(__file__).parent / "fixtures"
DEMO = FIXTURES / "amend-demo"
SMALLBAND = FIXTURES / "smallband.plan.json"


def _load_demo_state() -> ConsoleState:
    return ConsoleState(json.loads((DEMO / "occupancy.json").read_text()))


def amend_cli(*extra: str, amended: str = "rebuilt.plan.json",
              state: str = "occupancy.json") -> tuple[int, str, str]:
    from atoo.cli import main
    import io
    import contextlib

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["amend", "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / amended),
                     "--state", str(DEMO / state), *extra])
    return code, out.getvalue(), err.getvalue()


def test_cli_reviews_the_demo_offline():
    """The worked example in `examples/README.md` and
    `docs/user/applying.md`, pinned against a frozen copy of its files so
    it cannot go stale silently -- and so rebuilding smallband cannot turn
    it red."""
    code, out, _err = amend_cli()
    assert code == 0
    assert "11 ours, 1 theirs, 20 free, 16 unknown" in out
    assert "never answered, therefore treated as OCCUPIED" in out
    assert "ADDED            channel 'Trumpet' -> ch:12 (the rebuild asked for ch:11)" in out
    assert "ADDED            channel 'T.Sax' -> ch:13" in out
    assert "will be written" in out and "will NOT be" in out
    assert "no console was contacted" in out


def test_cli_returns_a_dropped_channel_to_free_offline():
    """The removal walkthrough in `examples/README.md` stage 6 and
    `docs/user/applying.md`, pinned so it cannot go stale silently."""
    code, out, _err = amend_cli(amended="rebuilt-minus-bgvox.plan.json")
    assert code == 0
    assert "3 added, 1 returned to free, 10 unchanged" in out
    assert "RETURNED TO FREE channel 'BG Vox 1' -> ch:10" in out
    assert "returns to free: ch:10" in out
    assert "24 of them RETURN A STRIP TO FREE" in out
    for address in ("/ch/10/mute", "/ch/10/in/conn/grp", "/ch/10/name",
                    "/ch/10/tags", "/io/in/LCL/10/name", "/io/in/LCL/10/vph",
                    # The filter this plan set, and the unmute.
                    "/ch/10/flt/lc", "/ch/10/flt/lcf",
                    # 2026-09-27: back to the factory Main routing.
                    "/ch/10/main/1/on", "/ch/10/main/2/on"):
        assert address in out
    assert "unmuted -- an untouched strip is not a muted one" in out
    # The fader goes to the factory reading, -inf.
    assert "/ch/10/fdr: returned to free: ch:10 (was 'BG Vox 1') fader to -inf" in out


def test_cli_refuses_to_clear_a_strip_somebody_else_has_taken_over():
    """The other half of the same walkthrough, and the one that matters:
    the same rebuild against a desk where ch:10 has gone Podium-shaped.
    Reported, not cleared, and not one of its addresses written."""
    code, out, _err = amend_cli(amended="rebuilt-minus-bgvox.plan.json",
                                state="occupancy-bgvox-taken-over.json")
    assert code == 0
    assert "3 added, 10 unchanged, 1 removed" in out
    assert "REMOVED          channel 'BG Vox 1' -> ch:10" in out
    assert "NOT returned to free" in out
    assert "source LCL 10 is named 'Spare SM58'" in out
    assert "returns to free:" not in out
    assert "RETURN A STRIP TO FREE" not in out
    assert "/ch/10/" not in out
    # Same address count as the amendment with nothing dropped: the
    # refusal costs the run nothing and changes nothing.
    # 57: the amended plan adds a DCA (Horns), whose starting fader and
    # mute are written since 2026-10-01.
    assert "57 address(es) will be written" in out


def _amend_cli_console(monkeypatch, *, applied, rebuilt):
    """A DeskConsole on the line, seeded the way
    `test_cli_confirm_writes_journals_its_scope_and_proves_nothing_else_moved`
    seeds one, plus the occupancy capture the offline tests use."""
    from atoo import cli
    from atoo.apply import _build_write_targets

    state: dict = {}
    for plan, factory in ((rebuilt, True), (applied, False)):
        built, _ = _build_write_targets(plan, set_fader_levels=True)
        for t in built:
            state[t.address] = ((_FACTORY[t.value_type], t.value_type) if factory
                                else (t.compute_value(None), t.value_type))
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    for address, value in json.loads((DEMO / "occupancy.json").read_text()).items():
        console.state[address] = (value, "i" if isinstance(value, int) else "s")
    return console


def test_a_preview_does_not_read_the_witness_set_at_all(monkeypatch, capsys):
    """A15 spent ~9 of its ~15 seconds reading 672 unrelated
    addresses twice, to establish that a run which sent no packets moved
    no values.

    A preview writes nothing, so FR-2.2 has nothing to prove. It must
    still SAY what the proof set would be -- that is what the engineer is
    deciding about when they decide to arm -- and read none of it.
    """
    from atoo import cli

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())
    console = _amend_cli_console(monkeypatch, applied=applied, rebuilt=rebuilt)

    code = cli.main(["amend", "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / "rebuilt.plan.json"),
                     "--console", "192.0.2.16", "--no-progress"])
    out = capsys.readouterr().out
    assert code == 0, out

    # It says what the proof would cover, with the real number.
    amendment = plan_amendment(applied, rebuilt, strip_occupancy(
        ConsoleState(json.loads((DEMO / "occupancy.json").read_text()),
                     console_model="wing-compact"), applied))
    witness = witness_addresses(amendment_targets(amendment))
    assert len(witness) > 300, "the witness set must be big enough for this to matter"
    assert f"The proof set is {len(witness)} unrelated address(es)" in out
    assert "not run -- this is a preview" in out

    # And it read none of them. A preview still has to do the occupancy
    # read and the dry run's own baseline GET per target, and those two
    # sets overlap the witness -- so the claim is made two ways.
    #
    # First: every witness address that is NOT part of the occupancy read
    # went completely unasked.
    # The drawing's name and colour reads (`desk_view`) are
    # part of the preview's own read, once each, like the occupancy read.
    from atoo.desk_view import face_read_plan

    occupancy = {a for a, _ in occupancy_read_plan()} | {
        a for a in console._get_call_counts if a.startswith("/io/in/")
        and a.endswith("/name")} | {a for a, _ in face_read_plan()}
    only_witness = {a for a, _ in witness} - occupancy
    assert len(only_witness) > 300, "this assertion would be vacuous otherwise"
    asked = set(console._get_call_counts)
    assert not (asked & only_witness), sorted(asked & only_witness)[:5]

    # Second: no witness address was asked TWICE. A witness address is by
    # definition one this amend does not write, so the only things that
    # can ask for it are the occupancy read (once) and the witness read
    # (twice) -- a second GET on one of them is the tell.
    twice = sorted(a for a, _ in witness if console._get_call_counts.get(a, 0) > 1)
    assert twice == [], twice

    assert console.set_param_calls == [] and console.set_node_calls == []


def test_a_confirmed_amend_still_reads_the_witness_set_before_and_after(
        tmp_path, monkeypatch, capsys):
    """The other half, and the one that must not be traded away: a run
    that WRITES still proves it. Both passes, over the whole set."""
    from atoo import cli

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())
    console = _amend_cli_console(monkeypatch, applied=applied, rebuilt=rebuilt)

    journal = tmp_path / "amend-journal.json"
    code = cli.main(["amend", "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / "rebuilt.plan.json"),
                     "--console", "192.0.2.16", "--confirm",
                     "--journal", str(journal), "--no-progress"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "unrelated address(es) read before and after, 0 changed" in out

    amendment = plan_amendment(applied, rebuilt, strip_occupancy(
        ConsoleState(json.loads((DEMO / "occupancy.json").read_text()),
                     console_model="wing-compact"), applied))
    witness = witness_addresses(amendment_targets(amendment))
    # Every witness address really was asked, TWICE -- not sampled, not
    # narrowed. `_get_call_counts` is per address, so this is the claim.
    for address, _ in witness:
        assert console._get_call_counts.get(address, 0) >= 2, address


@pytest.mark.parametrize("flags, expected_bulk", [
    ((), True),                 # the absent case: node dump
    (("--per-leaf",), False),   # The way back, as on audit and watch
])
def test_a_confirmed_amend_reads_its_proof_by_the_path_asked_for(
        tmp_path, monkeypatch, capsys, flags, expected_bulk):
    """Both witness passes take the same path, and `--per-leaf` is the
    only thing that changes it. The occupancy read is not this flag's to
    change (it is per-leaf regardless)."""
    from atoo import cli

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())
    _amend_cli_console(monkeypatch, applied=applied, rebuilt=rebuilt)

    real_read_witness = amend.read_witness
    paths: list[bool] = []

    def recording(console, witness, **kwargs):
        paths.append(kwargs.get("bulk", "unspecified"))
        return real_read_witness(console, witness, **kwargs)

    monkeypatch.setattr(amend, "read_witness", recording)
    code = cli.main(["amend", "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / "rebuilt.plan.json"),
                     "--console", "192.0.2.16", "--confirm",
                     "--journal", str(tmp_path / "amend-journal.json"),
                     "--no-progress", *flags])
    assert code == 0, capsys.readouterr().out
    assert paths == [expected_bulk, expected_bulk]


def test_only_skip_untouched_proof_can_turn_the_proof_off_for_a_real_write():
    """The structural requirement: making a PREVIEW cheap and
    weakening a CONFIRMED run's proof must not be the same switch.

    `witness_plan` takes the two facts separately and decides. There is
    no value of the preview-facing argument that turns the proof off for
    a confirmed run, and this enumerates the whole truth table to say so.
    """
    targets = amendment_targets(removal_scenario())
    table = {(confirm, skip): witness_plan(targets, confirm=confirm, skip=skip).read
             for confirm in (True, False) for skip in (True, False)}
    assert table == {
        (True, False): True,    # a real write proves itself
        (True, True): False,    # ...unless the user says not to, explicitly
        (False, False): False,  # a preview writes nothing, so proves nothing
        (False, True): False,
    }
    # The set itself is computed and reported whichever way it went -- a
    # preview says what arming would cost to prove.
    for (confirm, skip), read in table.items():
        plan = witness_plan(targets, confirm=confirm, skip=skip)
        assert len(plan.addresses) == len(witness_addresses(targets))
        assert str(len(plan.addresses)) in plan.line()
        if not read:
            assert plan.reason and "not run" in plan.line()


def test_the_proof_set_is_never_narrowed_to_make_a_run_fast():
    """The thing an earlier change explicitly refuses. `bulk` changes HOW the
    witness addresses are fetched, never WHICH ones -- a smaller witness
    set is a weaker proof, and FR-2.2 exists to make the stronger claim.
    """
    targets = amendment_targets(scenario())
    full = witness_addresses(targets)
    assert len(full) > 500
    assert set(witness_plan(targets, confirm=True).addresses) == set(full)
    # Both read paths cover the identical set of addresses.
    console = DeskConsole(full_console_state())
    per_leaf = read_witness(console, full, bulk=False)
    assert set(per_leaf) == {a for a, _ in full}
    # And the withheld set is still literally "everything a full build
    # would write, minus what this amend owns" -- see
    # test_withheld_is_everything_a_full_build_would_have_written.
    assert {t.address for t in targets.withheld} == {a for a, _ in full}


class DumpingConsole(DeskConsole):
    """A DeskConsole that also answers `node_dump`, the way a WING
    answers a `,s *` query -- so the node-dump witness path can be
    exercised without hardware.

    Deliberately does NOT apply the readback offset to the dump,
    because real hardware does not: a dump carries the text form, which
    is already the number the desk shows
    (`console.value_from_dump_text`), and the per-leaf GET is the one
    that is low by one. A11 measured exactly that across 5,712 values.
    """

    def __init__(self, state: dict):
        super().__init__(state)
        self.node_dump_calls: list[str] = []

    def node_dump(self, node: str):
        self.node_dump_calls.append(node)
        leaves = {a: v for a, (v, _t) in self.state.items()
                  if a.startswith(node + "/") and "/" not in a[len(node) + 1:]}
        if not leaves:
            return None
        body = ",".join(f"{a.rsplit('/', 1)[-1]}={v}" for a, v in leaves.items())
        return f"{node} {{{body}}}"


def test_the_witness_read_goes_through_the_node_dump_path_and_agrees_with_per_leaf():
    """The other half: keep both passes and make them cheap.

    The values a dump yields must be the values a per-leaf read yields,
    or a cheap proof is a broken one -- a phantom MOVED on a real amend
    is the worst possible false alarm.
    """
    targets = amendment_targets(scenario())
    witness = witness_addresses(targets)
    state = full_console_state()
    dumping, plain = DumpingConsole(state), DeskConsole(state)

    by_dump = read_witness(dumping, witness, bulk=True)
    by_leaf = read_witness(plain, witness, bulk=False)
    assert dumping.node_dump_calls, "the dump path never ran"
    assert set(by_dump) == set(by_leaf)
    assert witness_changes(by_dump, by_leaf, witness) == []
    # Far fewer round trips than there are addresses -- the whole point.
    assert len(dumping.node_dump_calls) < len(witness) / 2


def test_the_measured_cost_of_the_proof_is_inside_the_budget():
    """An earlier change, measured the way an earlier change was: request counts against the
    two rates A11 derived (`watch_scope`, net of the 320 unanswered
    addresses). Not an estimate, and not a wall clock -- a wall clock in
    this container measures this container.

    The numbers this pins are A15's own: a 672-address witness set that
    cost 2 x 4.54s per-leaf and costs 2 x 1.43s through node dumps.
    """
    from atoo import watch_scope as rates

    rebuilt = json.loads(
        (Path(__file__).parent.parent / "tests" / "fixtures" / "console-runs"
         / "session-2026-09-23-0928" / "A15-rebuilt-minus-ch18.plan.json").read_text())
    from atoo.apply import _build_write_targets
    built, _ = _build_write_targets(rebuilt, set_fader_levels=True)
    # A15 ran before an unstated bus width was decided rather than skipped
    # (`inferred.py`, 2026-09-25): the recorded plan leaves some widths
    # null, and apply now writes a `busmono` for each. Those are not part
    # of the set A15 measured, so they are left out of the witness it pins.
    decided_since = {f"/bus/{b['index']}/busmono" for b in rebuilt["busses"].values()
                     if b.get("mono") is None}
    # Likewise the direct-Main OFF writes (2026-09-27): every Main a
    # strip does not list is now switched off, and A15 ran before that.
    decided_since |= {f"/{c.get('bank', 'ch')}/{c['channel']}/main/{m}/on"
                      for c in rebuilt["channels"] for m in range(1, 5)
                      if m not in {r["index"] for r in c.get("main_routes") or []}}
    # And a bus's: every Main its destinations do not list.
    decided_since |= {f"/bus/{b['index']}/main/{m}/on"
                      for b in rebuilt["busses"].values() for m in range(1, 5)
                      if m not in {d.get("index", 1) for d in
                                   (b.get("destinations") or [b.get("destination") or {}])
                                   if d.get("type") == "main"}}
    # And each strip's `in/set/altsrc` (2026-09-28):
    # apply puts every strip it builds back on its main input.
    decided_since |= {f"/{c.get('bank', 'ch')}/{c['channel']}/in/set/altsrc"
                      for c in rebuilt["channels"]}
    # And the colours A24 named (2026-09-28): "Pink" is the desk's 11 now,
    # so EG 1's strip and socket `col` are written; at A15 it was a word
    # the desk lacked and wrote nothing.
    decided_since |= {t.address for c in rebuilt["channels"] if c.get("color") == "Pink"
                      for t in built if t.address.endswith("/col")
                      and f"({c['name']})" in t.description}
    # And each DCA's starting fader and mute (2026-10-01): apply wrote
    # only a DCA's name when A15 ran.
    decided_since |= {f"/dca/{d['index']}/{leaf}" for d in rebuilt["dcas"].values()
                      for leaf in ("fdr", "mute")}
    # And each Main's and Matrix's name (2026-10-09): apply wrote none
    # when A15 ran.
    decided_since |= {t.address for t in built
                      if t.address.startswith(("/main/", "/mtx/")) and t.address.endswith("/name")}
    # And phantom on a stereo pair's second socket: apply
    # wrote the first socket's only when A15 ran.
    decided_since |= {f"/io/in/{c['patch']['group']}/{c['patch']['sockets'][1]}/vph"
                      for c in rebuilt["channels"]
                      if c.get("patch") and len(c["patch"].get("sockets") or []) == 2}
    witness = sorted({t.address: t.value_type for t in built
                      if t.address not in decided_since}.items())
    assert len(witness) == 672, "A15's own witness set, from the run's own output"

    per_leaf = witness_requests(witness, bulk=False)
    bulk = witness_requests(witness, bulk=True)
    assert per_leaf == 672
    assert bulk < 200, bulk
    per_leaf_pass = per_leaf * rates.PER_LEAF_SECONDS_PER_ADDRESS
    bulk_pass = bulk * rates.NODE_DUMP_SECONDS_PER_REQUEST
    assert 4.4 < per_leaf_pass < 4.7, per_leaf_pass
    assert bulk_pass < 1.6, bulk_pass

    # A preview: the occupancy read plus the dry run's own baseline GETs,
    # and NOT one witness address. A15's occupancy read was 218.
    preview = (218 + 19) * rates.PER_LEAF_SECONDS_PER_ADDRESS
    assert preview < rates.RESPONSIVENESS_BUDGET_SECONDS[0], preview

    # A confirmed run: the same, plus both witness passes and the writes.
    confirmed = ((218 + 19 + 2 * 17) * rates.PER_LEAF_SECONDS_PER_ADDRESS
                 + 2 * bulk_pass)
    assert confirmed < 5.0, confirmed
    # ...against what it was before this change, which is the point.
    was = ((218 + 16 + 2 * 14) * rates.PER_LEAF_SECONDS_PER_ADDRESS
           + 2 * per_leaf_pass)
    assert was > 10.0 and confirmed < was / 2, (was, confirmed)


def test_cli_rejects_a_malformed_allow_strip():
    code, _out, err = amend_cli("--allow-strip", "channel 20")
    assert code == 1
    assert "expected a strip label like 'ch:20'" in err


def test_cli_allow_strip_opens_the_occupied_strip():
    code, out, _err = amend_cli("--allow-strip", "ch:11")
    assert code == 0
    assert "ADDED            channel 'Trumpet' -> ch:11" in out


def test_cli_confirm_writes_journals_its_scope_and_proves_nothing_else_moved(
        tmp_path, monkeypatch, capsys):
    """The one path no other test reaches: the CLI's own stage 4, with a
    console on the line. Stubs the connection rather than the engine, so
    the witness read, the journal and the exit code are all the real
    ones."""
    from atoo import cli

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())

    from atoo.apply import _build_write_targets
    state: dict = {}
    for plan, factory in ((rebuilt, True), (applied, False)):
        built, _ = _build_write_targets(plan, set_fader_levels=True)
        for t in built:
            state[t.address] = ((_FACTORY[t.value_type], t.value_type) if factory
                                else (t.compute_value(None), t.value_type))
    console = DeskConsole(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    # The occupancy read goes over the same console, so seed its three
    # leaves per strip from the capture the offline tests use.
    for address, value in json.loads((DEMO / "occupancy.json").read_text()).items():
        console.state[address] = (value, "i" if isinstance(value, int) else "s")

    journal = tmp_path / "amend-journal.json"
    code = cli.main(["amend", "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / "rebuilt.plan.json"),
                     "--console", "192.0.2.16", "--confirm",
                     "--journal", str(journal), "--no-progress"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "unrelated address(es) read before and after, 0 changed" in out
    recorded = json.loads(journal.read_text())
    assert recorded["scope"]["strips"] == ["ch:12", "ch:13"]
    assert recorded["scope"]["grants"]["/ch/12"].startswith("new channel 'Trumpet'")
    # And nothing outside the two new strips, their sockets or the new DCA.
    ours = ("/ch/12", "/ch/13", "/io/in/LCL/11", "/io/in/LCL/12", "/dca/7")
    touched = ([a for a, _v, _t in console.set_param_calls]
               + [a for a, _p in console.set_node_calls])
    assert touched
    assert not [a for a in touched
                if not any(a == b or a.startswith(b + "/") for b in ours)]


def test_a_confirmed_amend_lands_on_the_bundles_journal_stack(
        tmp_path, monkeypatch, capsys):
    """One time-ordered stack per bundle, and an amend is a
    write on it like any other -- on top of the apply it amends, not in
    a file of its own that the next amend overwrites.

    The amend journal itself still goes exactly where it always did;
    what is new is the timestamped copy in `journals/`, which is what
    `atoo undo --show DIR` walks back.

    Mutation-checked: drop the `_record_on_stack` call from
    `cli.amend_cmd` and this fails.
    """
    from atoo import cli
    from atoo import journal_stack

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())
    _amend_cli_console(monkeypatch, applied=applied, rebuilt=rebuilt)

    show = tmp_path / "show"
    show.mkdir()
    journal = show / "amend-journal.json"
    code = cli.main(["amend", "--show", str(show), "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / "rebuilt.plan.json"),
                     "--console", "192.0.2.16", "--confirm",
                     "--journal", str(journal), "--no-progress"])
    assert code == 0, capsys.readouterr().out

    assert journal.is_file()
    entries = journal_stack.entries(show)
    assert [e.kind for e in entries] == ["amend"]
    assert journal_stack.top(show).id == entries[0].id
    # The entry is the run, not a summary of it.
    assert json.loads(entries[0].path.read_text())["writes"] == \
        json.loads(journal.read_text())["writes"]


def test_a_previewed_amend_puts_nothing_on_the_stack(tmp_path, monkeypatch, capsys):
    """The stack is a record of writes to a console. A preview wrote
    nothing, `atoo undo` refuses a dry-run journal outright, and an
    entry for one would be a row on the Apply screen that looks
    reversible and is not."""
    from atoo import cli
    from atoo import journal_stack

    applied = json.loads(SMALLBAND.read_text())
    rebuilt = json.loads((DEMO / "rebuilt.plan.json").read_text())
    _amend_cli_console(monkeypatch, applied=applied, rebuilt=rebuilt)

    show = tmp_path / "show"
    show.mkdir()
    code = cli.main(["amend", "--show", str(show), "--plan", str(SMALLBAND),
                     "--amended-plan", str(DEMO / "rebuilt.plan.json"),
                     "--console", "192.0.2.16", "--no-progress"])
    assert code == 0, capsys.readouterr().out
    assert journal_stack.entries(show) == []
    assert not journal_stack.stack_dir(show).exists()
