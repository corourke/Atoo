"""WING's GET reply for a patch connector is one less than the
value its SET takes.

**Anchored to hardware, not to a reading of the spec.** The decisive tests
below replay the 20 real mismatches from the maintainer's 2026-09-18 apply
against a real desk, and assert the correction turns every one of them
into a match.

The journal lives in `tests/fixtures/` rather than in the show bundle it
came from (the maintainer, 2026-09-21: *"examples is really for experimentation
and user testing"*). It was `examples/touringband/apply-journal.json`,
which is a **fixed bundle slot every apply overwrites** -- so a test
asserting on historical evidence was one console session away from
losing it. It is evidence, not an example. If the correction is ever changed, those 20 readings are
what disagrees, not somebody's interpretation.

Three independent lines of evidence, for the record:

  * 25 readings across two runs, `readback == intended - 1`, no exceptions;
  * the console's own post-apply `.snap` -- written by WING, never through
    our read path -- agrees with what was INTENDED on all of them;
  * Behringer documents the convention. `WING_Remote-Protocols-3.1-03.pdf`
    p.72, footnote [54]: *"The get command reports values between 0 and 75,
    but index 1 to 76 should be used when setting values."*

The other half of this module is the part that matters more in a year: the
tests asserting what is NOT corrected. An unverified correction turns a
real "did not land" into a false "landed", which is worse than the bug.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo.apply import _extract_reply_value
from atoo.console import OscReply
from atoo.console_facts import correct_readback_index, readback_index_offset

JOURNAL = Path(__file__).parent / "fixtures" / "touringband-2026-09-18.apply-journal.json"


def real_mismatches() -> list[dict]:
    writes = json.loads(JOURNAL.read_text())["writes"]
    return [w for w in writes if w["status"] == "mismatch"]


# ---------------------------------------------------------------------------
# the hardware evidence
# ---------------------------------------------------------------------------


def test_the_journal_still_holds_the_evidence_this_fix_rests_on():
    """A guard on the fixture itself. If this file is ever regenerated from
    a run made AFTER the fix, the 20 mismatches vanish and every test below
    would pass trivially against an empty list."""
    mismatches = real_mismatches()
    assert len(mismatches) == 20, (
        f"{JOURNAL.name} should still be the 2026-09-18 pre-fix run, with "
        f"its 20 connector mismatches"
    )
    assert all(w["readback_value"] == w["intended_value"] - 1 for w in mismatches)


def test_every_real_mismatch_becomes_a_match_once_corrected():
    """The whole fix, measured against the desk rather than the spec."""
    for write in real_mismatches():
        corrected = correct_readback_index(write["address"], write["readback_value"])
        assert corrected == write["intended_value"], write["address"]


def test_the_real_mismatches_covered_both_affected_families():
    """20 readings would prove little if they were all one address. They
    span the channel connector and the output connector."""
    families = {w["address"].split("/")[1] for w in real_mismatches()}
    assert families == {"ch", "io"}


def test_no_write_that_already_matched_is_broken_by_the_correction():
    """The other direction, and the one that would be a disaster: 317
    writes verified correctly on that run. The correction must not turn a
    single one of them into a mismatch."""
    writes = json.loads(JOURNAL.read_text())["writes"]
    for write in writes:
        if write["status"] != "match":
            continue
        corrected = correct_readback_index(write["address"], write["readback_value"])
        assert corrected == write["readback_value"], (
            f"{write['address']} verified fine on real hardware and must not "
            f"be adjusted"
        )


# ---------------------------------------------------------------------------
# what is corrected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("address", [
    "/ch/1/in/conn/in",
    "/ch/40/in/conn/in",
    "/aux/1/in/conn/in",
    "/aux/8/in/conn/in",
    "/io/out/LCL/1/in",
    "/io/out/AES/2/in",
    "/io/out/CRD/64/in",
])
def test_the_confirmed_families_are_corrected(address):
    assert readback_index_offset(address) == 1
    assert correct_readback_index(address, 7) == 8


def test_the_aux_patch_leaf_is_corrected_because_a11_measured_it():
    """A11 read the whole desk twice -- per-leaf and by node
    dump -- and of 5,712 values exactly eight disagreed, all
    `/aux/{n}/in/conn/in`, per-leaf 0 against dump 1. The dump carries
    the text form the desk itself shows, so the per-leaf read was the low
    one, and the aux leaf behaves exactly like the channel leaf beside
    it.

    The channel leaf is asserted here too, as the control: it was already
    corrected and it did NOT appear among the eight, which is what says
    the correction is right rather than merely applied."""
    assert correct_readback_index("/aux/1/in/conn/in", 0) == 1
    assert correct_readback_index("/aux/8/in/conn/in", 0) == 1
    assert correct_readback_index("/ch/1/in/conn/in", 0) == 1
    # A Compact ships aux 1 from USB 1 and aux 2 from PLAY 1. Socket 1 is
    # the number the desk shows; 0 is what the wire said.
    assert correct_readback_index("/aux/2/in/conn/in", 0) == 1


def test_the_user_patch_source_leaf_is_corrected_because_a16_measured_it():
    """A16 (2026-09-23): USR 25 set to LOCAL IN 5 by hand, the
    screen read "USR 25, LCL 5", the `/io/in/USR/25` node dump said 5 and
    the per-leaf read said 4. The dump carries the text the desk shows, so
    the per-leaf read is the low one -- the aux leaf's signature exactly.

    Both ends of the USER PATCH range, and a USER SIGNAL slot, because the
    leaf is the same address shape across all 64 and the regex must not
    have quietly narrowed to the slot that was measured."""
    assert correct_readback_index("/io/in/USR/25/user/in", 4) == 5
    assert correct_readback_index("/io/in/USR/56/user/in", 0) == 1
    assert correct_readback_index("/io/in/USR/1/user/in", 0) == 1
    # The group half of the same patch is text and verified clean in the
    # same run ('OFF' -> 'LCL' on both paths). It must stay uncorrected.
    assert readback_index_offset("/io/in/USR/25/user/grp") == 0


def test_the_alternate_patch_socket_is_corrected_as_inferred():
    """`in/conn/altin` joined the table when `apply`
    started writing it -- on A7's read-only evidence, not a write. The
    reply `sfi ['1', 0.0, 0]` against the desk's snapshot `altin: 1` is
    exactly `/ch/1/in/conn/in`'s reply for socket 1 in the A1 raw log.
    Both banks, and the group half stays uncorrected."""
    assert correct_readback_index("/ch/1/in/conn/altin", 0) == 1
    assert correct_readback_index("/aux/8/in/conn/altin", 26) == 27
    assert readback_index_offset("/ch/1/in/conn/altgrp") == 0
    assert readback_index_offset("/ch/1/in/set/altsrc") == 0


def test_the_alternate_offset_evidence_is_on_disk():
    """The comparison the correction rests on, from the captures
    themselves (read-only evidence), so it cannot be misremembered."""
    root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "console-runs" / "2026-09-21"
    aes = (root / "A7-with-AES-alt.txt").read_text()
    assert "/ch/1/in/conn/altin -> OscReply(address='/ch/1/in/conn/altin', typetag='sfi', args=['1', 0.0, 0]" in aes
    snap = json.loads((root / "A7-ch1-with-WLIVE-alt.snap").read_text())
    assert snap["ae_data"]["ch"]["1"]["in"]["conn"]["altin"] == 1
    assert "PARSED addr='/ch/1/in/conn/in' typetag='sfi' args=['1', 0.0, 0]" in \
        (root / "A1-raw.log").read_text()


# ---------------------------------------------------------------------------
# what is deliberately NOT corrected -- the half that ages best
#
# The three `col` entries left this list on 2026-09-22, when A2b measured
# it, `/aux/{n}/in/conn/in` on 2026-09-23, when A11 did, and
# `/io/in/USR/{n}/user/in` on 2026-09-24, from A16's capture. That is the
# list working as intended: an address sits here on the grounds that its
# SHAPE is suspicious and nothing has tested it, and leaves only when
# something has. Both turned out to share the offset, which is a
# vindication of the suspicion and not a reason to have acted on it early
# -- `in/conn/grp` has the same look and verifies 21/21.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("address, why", [
    ("/ch/1/in/conn/grp", "the other half of the same patch -- verified 21/21 on real hardware"),
    ("/bus/1/busmono", "an int, and 100% clean on that run"),
    ("/ch/1/mute", "an int, clean"),
])
def test_nothing_else_is_corrected(address, why):
    """Every entry here is a line item for the next console session. The
    default is no adjustment precisely so this list can be wrong without
    being dangerous: an uncorrected address reports a false mismatch, which
    is noisy. A wrongly-corrected one reports a false match, which is a
    show going out broken."""
    assert readback_index_offset(address) == 0, why
    assert correct_readback_index(address, 7) == 7, why


def test_the_correction_only_touches_plain_ints():
    """A None (unreadable), a bool, or a float must come back untouched
    rather than being arithmetic'd into something that looks like data."""
    address = "/ch/1/in/conn/in"
    assert correct_readback_index(address, None) is None
    assert correct_readback_index(address, True) is True
    assert correct_readback_index(address, 3.0) == 3.0
    assert correct_readback_index(address, "A") == "A"


# ---------------------------------------------------------------------------
# the correction is applied where it has to be
# ---------------------------------------------------------------------------


def test_extract_reply_value_applies_it():
    reply = OscReply(address="/ch/3/in/conn/in", typetag="i", args=[3])
    value, error = _extract_reply_value(reply, "i", "/ch/3/in/conn/in")
    assert error is None
    assert value == 4


def test_extract_reply_value_without_an_address_corrects_nothing():
    """The default is "" -- so a caller that has no address cannot get a
    correction applied by accident."""
    reply = OscReply(address="/ch/3/in/conn/in", typetag="i", args=[3])
    assert _extract_reply_value(reply, "i")[0] == 3


def test_a_read_error_is_not_turned_into_a_number():
    reply = OscReply(address="/ch/3/in/conn/in", typetag="SOCKET_ERROR", args=["boom"])
    value, error = _extract_reply_value(reply, "i", "/ch/3/in/conn/in")
    assert value is None and error is not None


def test_read_console_state_applies_it_too():
    """The read that hurt most. `apply` reads an address before deciding
    whether to write it, and `audit`/`watch` read the same leaf for
    CV005 and #93's `patch` condition -- all of them saw a socket
    number one lower than the desk really had."""
    from atoo.audit import read_console_state

    class OneChannel:
        def get(self, address):
            if address == "/ch/1/in/conn/in":
                return OscReply(address=address, typetag="i", args=[11])
            return OscReply(address=address, typetag="SOCKET_ERROR", args=["n/a"])

    state = read_console_state(OneChannel(), channels=1, aux=0, buses=0, mains=0,
                               matrices=0, dcas=0, mute_groups=0)
    assert state.number("/ch/1/in/conn/in") == 12


# ---------------------------------------------------------------------------
# `col` joined the table on 2026-09-22, measured rather than inferred.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("address", [
    "/ch/5/col", "/aux/2/col", "/bus/3/col", "/main/1/col", "/mtx/4/col",
    "/dca/8/col", "/io/in/LCL/9/col", "/io/in/A/17/col",
])
def test_col_is_corrected_on_every_strip_class(address):
    """A2b, 2026-09-22 -- the first run that ever wrote a colour. Wrote
    3, 5, 11 and 18 to `/ch/{3,5,11,18}/col`; read back 2, 4, 10 and 17.

    It sat in this module's "deliberately NOT corrected" list for exactly
    the right reason: it has the same 1-based shape, and resemblance is
    not evidence. Now it has evidence."""
    assert readback_index_offset(address) == 1
    assert correct_readback_index(address, 8) == 9


def test_the_measured_col_readbacks_all_correct_to_what_was_written():
    """The four measurements themselves, so a future change to the table
    has to explain these rather than merely pass a shape test."""
    measured = {3: 2, 5: 4, 11: 10, 18: 17}   # written -> read back
    for written, read in measured.items():
        assert correct_readback_index(f"/ch/{written}/col", read) == written


def test_icon_is_still_not_corrected():
    """`icon` is `0..999` -- zero-based, so it has no reason to share the
    offset, and nothing has measured it. The point of the table is that
    entries arrive by measurement."""
    assert readback_index_offset("/ch/5/icon") == 0
