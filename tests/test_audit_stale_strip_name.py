"""`effective_name` must not prefer a stale strip name over
the socket name the desk is actually showing.

The maintainer, watching a live full-size WING on 2026-09-24:

    N001  2 channel/aux strips share the name 'Acoustic': /ch/4, /ch/7.

Not true. One channel is 'Acoustic' and the other is 'Acoustic 2', and
`archive/examples/console-runs/2026-09-23-1921/A17-wing-full.snap` -- the capture
off that same desk, in the same session -- proves both halves:

    /ch/4  name='Acoustic'  clink=true  ->  A 11, socket name 'Acoustic'
    /ch/7  name='Acoustic'  clink=true  ->  A  9, socket name 'Acoustic 2'

Both strip leaves hold a stale 'Acoustic'; the sockets hold the truth, and
with `clink` ON the surface displays the socket's name. `effective_name`
already had the right rule for this (an earlier change: unread -> prefer the strip,
read-and-ON -> prefer the socket, read-and-OFF -> prefer the strip). What
it never had was a reading: `clink` was in no read plan, so the audit was
permanently in the first branch. An earlier change puts it in the second pass,
per patched strip.

**The fixture is the capture**, read straight off disk, so this test
cannot drift from the evidence. `tests/conftest.py`'s living-example guard
exempts `examples/console-runs/` -- those are hardware captures, never
regenerated and never edited.
"""

import json
from pathlib import Path

import pytest

from atoo.audit import (
    ConsoleState,
    console_read_plan,
    custom_link_addresses,
    effective_name,
    read_console_state,
    run_audit,
    source_name_addresses,
)

ROOT = Path(__file__).resolve().parents[1]
A17_WING_FULL = (ROOT / "tests" / "fixtures" / "console-runs" / "2026-09-23-1921"
                 / "A17-wing-full.snap")

#: The two strips the false finding was about.
THE_ACOUSTICS = ("/ch/4", "/ch/7")


def _ae_data() -> dict:
    return json.loads(A17_WING_FULL.read_text())["ae_data"]


def _two_strips_from_the_capture(*, read_clink: bool) -> ConsoleState:
    """`/ch/4` and `/ch/7` off the A17 capture, in the addresses a read
    walks: name, patch, the patched socket's name, and -- when
    `read_clink` -- the link flag.

    `read_clink=False` is what an audit produced, and it is
    how the mutation check below gets the false finding back.

    A `.snap` stores the patch connector as the number the desk shows
    (`conn.in == 11` for A 11), which is already what `ConsoleState.patch`
    expects; the OSC readback is the one that comes back a digit low and
    is corrected on the way in.
    """
    ae = _ae_data()
    values: dict[str, object] = {}
    for base in THE_ACOUSTICS:
        strip = ae["ch"][base.rsplit("/", 1)[1]]
        conn = strip["in"]["conn"]
        values[f"{base}/name"] = strip["name"]
        values[f"{base}/in/conn/grp"] = conn["grp"]
        values[f"{base}/in/conn/in"] = conn["in"]
        if read_clink:
            values[f"{base}/clink"] = int(strip["clink"])
        socket = ae["io"]["in"][conn["grp"]][str(conn["in"])]
        values[f"/io/in/{conn['grp']}/{conn['in']}/name"] = socket["name"]
    return ConsoleState(values, console_model="wing-fullsize")


def _rule_ids(findings):
    return {f.rule_id for f in findings}


def test_the_capture_really_does_hold_the_case_this_file_is_about():
    """Not vacuous. If the capture were ever swapped for one where the two
    strips genuinely share a name, every test below would pass while
    proving nothing."""
    ae = _ae_data()
    ch4, ch7 = ae["ch"]["4"], ae["ch"]["7"]

    # Both strip leaves hold the same stale string ...
    assert ch4["name"] == ch7["name"] == "Acoustic"
    # ... both are linked to their socket ...
    assert ch4["clink"] is True and ch7["clink"] is True
    # ... they are on different sockets ...
    assert ch4["in"]["conn"] == {"grp": "A", "in": 11,
                                 "altgrp": "USB", "altin": 27}
    assert ch7["in"]["conn"]["grp"] == "A" and ch7["in"]["conn"]["in"] == 9
    # ... and those sockets are named differently, which is what the desk
    # was showing the maintainer.
    assert ae["io"]["in"]["A"]["11"]["name"] == "Acoustic"
    assert ae["io"]["in"]["A"]["9"]["name"] == "Acoustic 2"


def test_no_collision_when_clink_was_read():
    """The finding the maintainer saw, against a read that took the flag."""
    state = _two_strips_from_the_capture(read_clink=True)
    assert effective_name(state, "/ch/4") == "Acoustic"
    assert effective_name(state, "/ch/7") == "Acoustic 2"
    assert "N001" not in _rule_ids(run_audit(state))


def test_the_finding_cites_the_socket_the_name_came_off():
    """FR-4.3: a finding points at what it read. With the name coming off
    the socket, `/ch/7`'s label has to follow it -- otherwise a report
    says 'Acoustic' about a strip the engineer can see says 'Acoustic 2'.
    """
    state = _two_strips_from_the_capture(read_clink=True)
    state.values["/ch/7/send/1/on"] = 1
    state.values["/ch/7/send/1/lvl"] = -110.0
    detail = next(f.detail for f in run_audit(state) if f.rule_id == "L001")
    assert '"Acoustic 2"' in detail


def test_the_false_collision_is_exactly_what_an_unread_clink_produces():
    """The other half of the evidence, and the shape of the mutation: the
    same two strips, read without the flag, collide. This is not a test of
    a bug left in place -- it pins WHY the read had to change, since the
    tie-break itself was already correct."""
    state = _two_strips_from_the_capture(read_clink=False)
    assert effective_name(state, "/ch/4") == effective_name(state, "/ch/7") == "Acoustic"
    assert "N001" in _rule_ids(run_audit(state))


# --------------------------------------------------------------------------
# The read is what changed
# --------------------------------------------------------------------------


class _Desk:
    """Answers nothing, remembers every address asked for."""

    def __init__(self, patches: dict[str, tuple[str, int]]):
        self._patches = patches
        self.asked: list[str] = []

    def get(self, address):
        self.asked.append(address)
        for base, (group, socket) in self._patches.items():
            if address == f"{base}/in/conn/grp":
                return _Reply(group)
            if address == f"{base}/in/conn/in":
                # The OSC readback is one low; the read
                # corrects it, so hand back what the desk really sends.
                return _Reply(socket - 1)
        return None


class _Reply:
    def __init__(self, value):
        self._value = value

    def value(self, value_type):
        return self._value, None


def test_a_read_asks_for_clink_on_a_patched_strip_and_not_on_a_bare_one():
    """The cost decision, as a test. `clink` is one address per PATCHED
    strip -- 26 on a factory Compact, not 48 -- because `source_is_named`
    answers False for an unpatched strip without ever consulting the flag,
    so an unpatched strip's reading could not be used by any rule."""
    desk = _Desk({"/ch/1": ("LCL", 6)})
    read_console_state(desk, channels=2, aux=0, buses=1, mains=1,
                       matrices=1, dcas=0, mute_groups=0)
    assert "/ch/1/clink" in desk.asked
    assert "/ch/2/clink" not in desk.asked


def test_clink_is_not_in_the_first_pass():
    """It cannot be: the first pass is pure and knows no patches, and
    which strips are patched is not knowable until it has run. Same reason
    the socket names are a second pass."""
    plan = [address for address, _ in console_read_plan(channels=4, aux=0, buses=1,
                                                        mains=1, matrices=1,
                                                        dcas=0, mute_groups=0)]
    assert not [a for a in plan if a.endswith("/clink")]


def test_the_second_pass_pairs_a_clink_with_every_source_name():
    """One socket feeding two strips is one name request and two flag
    requests -- the name is deduplicated because it is a fact about the
    socket, the flag is not because it is a fact about the strip."""
    shared = ConsoleState({
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 5,
        "/ch/2/in/conn/grp": "LCL", "/ch/2/in/conn/in": 5,
        "/ch/3/name": "unpatched",
    })
    assert source_name_addresses(shared) == [("/io/in/LCL/5/name", "s")]
    assert custom_link_addresses(shared) == [("/ch/1/clink", "i"),
                                             ("/ch/2/clink", "i")]


# --------------------------------------------------------------------------
# What must not weaken
# --------------------------------------------------------------------------


def test_two_strips_that_really_do_share_a_name_still_collide():
    """N001's actual job, on the same shape as the A17 case: `clink`
    read and ON, two different sockets -- and this time both sockets carry
    the same name."""
    state = ConsoleState({
        "/ch/4/name": "", "/ch/4/clink": 1,
        "/ch/4/in/conn/grp": "A", "/ch/4/in/conn/in": 11,
        "/ch/7/name": "", "/ch/7/clink": 1,
        "/ch/7/in/conn/grp": "A", "/ch/7/in/conn/in": 9,
        "/io/in/A/11/name": "Acoustic",
        "/io/in/A/9/name": "Acoustic",
    })
    assert "N001" in _rule_ids(run_audit(state))


def test_a_shared_socket_deliberately_unlinked_still_cannot_collide():
    """The case the tie-break was written for, which must survive.
    `apply.py` switches `clink` OFF for a socket shared between two strips
    and names each strip separately; with the flag now actually read, the
    strip's own name wins outright rather than by the unread-flag
    fallback."""
    state = ConsoleState({
        "/ch/1/name": "Kick", "/ch/1/clink": 0,
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 5,
        "/ch/2/name": "Kick Sub", "/ch/2/clink": 0,
        "/ch/2/in/conn/grp": "LCL", "/ch/2/in/conn/in": 5,
        "/io/in/LCL/5/name": "Kick",
    })
    assert effective_name(state, "/ch/1") == "Kick"
    assert effective_name(state, "/ch/2") == "Kick Sub"
    assert "N001" not in _rule_ids(run_audit(state))


def test_an_unread_clink_still_prefers_the_strip():
    """The third branch is unchanged, and it has to be: an assumption must
    not overrule a real reading. A capture taken, or a state
    assembled by hand, still reaches here."""
    state = ConsoleState({
        "/ch/1/name": "Kick",
        "/ch/1/in/conn/grp": "LCL", "/ch/1/in/conn/in": 5,
        "/io/in/LCL/5/name": "Something Else",
    })
    assert state.flag("/ch/1/clink") is None
    assert effective_name(state, "/ch/1") == "Kick"


@pytest.mark.parametrize("clink", [None, 1])
def test_the_podium_shape_reads_as_named_either_way(clink):
    """An earlier change inverted is what an earlier change fixes, so an earlier change itself must not
    move: a blank strip whose socket carries the name shows the socket's
    name, whether the flag was read or assumed."""
    values = {
        "/ch/20/name": "",
        "/ch/20/in/conn/grp": "LCL", "/ch/20/in/conn/in": 20,
        "/io/in/LCL/20/name": "Podium",
    }
    if clink is not None:
        values["/ch/20/clink"] = clink
    assert effective_name(ConsoleState(values), "/ch/20") == "Podium"
