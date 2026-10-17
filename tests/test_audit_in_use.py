"""What "in use" means, and what follows from it.

`docs/developer/audit-rules.md`'s **Vocabulary Rules** section is the
specification here:

    An "in-use" or "active" channel, aux or bus is one that is named,
    input patched, or has sends (whatever the console patches and routes
    by itself out of the box -- channels to their own LCL inputs, the
    media auxes to the USB and media players, busses to Main 1 -- doesn't
    count, unless also named, patched somewhere else, or is receiving
    sends.)

The two parenthetical exclusions are what this file is mostly about. They
are not fussiness: a WING out of its box patches channel n from LCL n,
patches its two media auxes from the USB and media players, and switches
`main/1/on` on for every strip and half its busses, so a definition
without them calls an untouched desk fully in use, and every rule built on
it fires dozens of times on a board nobody has plugged anything into.

**Which patches the factory made is a fact about the console model**, so
it lives in `console_facts.FACTORY_INPUT_PATCHES` and the state has to say
which desk it was read off. We have measured two models, the Compact and
the full-size WING; a
state that names an unmeasured model, or names none at all, falls back to
the channel-n-from-LCL-n identity alone, which is the direction that hides
nothing (see that table's comment).

The last tests in this file score an actual factory-initialized WING
Compact (`examples/console-runs/Initialized-Compact.snap`, one of
the maintainer's own hardware captures) and a factory-initialized full-size WING
(`examples/Initialized-Full.snap`) rather than a fixture that says what we
expect a factory board to look like.
"""

import json
import re
from pathlib import Path

import pytest

from atoo import console_facts
from atoo.audit import (
    DEFAULT_RULES,
    ConsoleState,
    console_read_plan,
    custom_link_addresses,
    effective_name,
    is_factory_source_label,
    is_in_use,
    source_is_named,
    output_source_object,
    read_console_state,
    run_audit,
    source_name_addresses,
)
from atoo.console import OscReply
from atoo.diagnostics import Severity

ROOT = Path(__file__).resolve().parents[1]
INITIALIZED_COMPACT = ROOT / "tests" / "fixtures" / "console-runs" / "Initialized-Compact.snap"
#: A factory-initialized full-size WING (committed 2026-09-23, c402c2f).
#: Under `examples/` rather than `examples/console-runs/`, but a capture
#: all the same: evidence the desk wrote, not a show file anybody edits.
INITIALIZED_FULL = ROOT / "tests" / "fixtures" / "Initialized-Full.snap"
BOARD_WITH_PODIUM = (ROOT / "tests" / "fixtures" / "console-runs" / "2026-09-22-2139"
                     / "A13-board-with-podium.snap")


def _rule_ids(findings):
    return {f.rule_id for f in findings}


# --------------------------------------------------------------------------
# The definition itself
# --------------------------------------------------------------------------


def test_a_bare_strip_is_not_in_use():
    assert not is_in_use(ConsoleState({"/ch/3/name": ""}), "/ch/3")


def test_a_named_strip_is_in_use():
    assert is_in_use(ConsoleState({"/ch/3/name": "Kick"}), "/ch/3")


def test_a_factory_default_name_is_not_a_name():
    """`CH03` is what the desk calls channel 3 before anyone does."""
    assert not is_in_use(ConsoleState({"/ch/3/name": "CH03"}), "/ch/3")


def test_the_factory_patch_of_channel_n_to_lcl_n_is_not_a_patch():
    state = ConsoleState({"/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 3})
    assert not is_in_use(state, "/ch/3")


def test_any_other_patch_is_a_patch():
    """Read narrowly on purpose: only the n -> n identity is the default.
    A desk that genuinely wants channel 3 on LCL 7 said something."""
    state = ConsoleState({"/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 7})
    assert is_in_use(state, "/ch/3")


def test_the_same_socket_number_in_another_group_is_a_patch():
    state = ConsoleState({"/ch/3/in/conn/grp": "A", "/ch/3/in/conn/in": 3})
    assert is_in_use(state, "/ch/3")


def test_the_default_patch_on_a_named_channel_is_still_in_use():
    """*"...unless also named or input patched"*. The exclusion is about
    evidence, and a name is evidence."""
    state = ConsoleState({
        "/ch/3/name": "Kick", "/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 3,
    })
    assert is_in_use(state, "/ch/3")


def test_an_aux_has_no_lcl_default_so_its_patch_always_counts():
    state = ConsoleState({"/aux/3/in/conn/grp": "LCL", "/aux/3/in/conn/in": 3})
    assert is_in_use(state, "/aux/3")


def test_a_route_to_main_1_alone_is_not_activity():
    """A factory WING ships `main/1/on = 1` on all forty channels, so a
    deliberate route to Main 1 and an untouched desk are the same reading
    at this address. The rule set gives up the one to be rid of the other."""
    assert not is_in_use(ConsoleState({"/ch/3/main/1/on": 1}), "/ch/3")


def test_a_route_to_any_other_main_is_activity():
    """Main 2-4 are off from the factory, so switching one on says
    something."""
    assert is_in_use(ConsoleState({"/ch/3/main/2/on": 1}), "/ch/3")


def test_a_bus_send_is_activity():
    assert is_in_use(ConsoleState({"/ch/3/send/1/on": 1}), "/ch/3")


def test_a_matrix_send_is_activity():
    assert is_in_use(ConsoleState({"/ch/3/send/MX1/on": 1}), "/ch/3")


def test_a_send_that_exists_but_is_off_is_not_activity():
    assert not is_in_use(ConsoleState({"/ch/3/send/1/on": 0}), "/ch/3")


def test_a_bus_routed_only_to_main_1_is_not_in_use():
    """*"...or busses to Main 1 don't count"*. Busses 9-16 ship routed to
    Main 1 with their faders at unity."""
    assert not is_in_use(ConsoleState({"/bus/9/main/1/on": 1, "/bus/9/fdr": 0.0}), "/bus/9")


def test_a_bus_receiving_a_send_is_in_use():
    """The one arm of the definition that only makes sense for a bus:
    *"or is receiving sends"*."""
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/send/4/on": 1, "/bus/4/fdr": 0.0})
    assert is_in_use(state, "/bus/4")


def test_a_bus_receiving_a_send_that_is_off_is_not_in_use():
    state = ConsoleState({"/ch/1/name": "Kick", "/ch/1/send/4/on": 0, "/bus/4/fdr": 0.0})
    assert not is_in_use(state, "/bus/4")


def test_a_bus_that_sends_to_a_matrix_is_in_use():
    assert is_in_use(ConsoleState({"/bus/4/send/MX1/on": 1}), "/bus/4")


# --------------------------------------------------------------------------
# ...and "named" means named where the desk puts a name
# --------------------------------------------------------------------------
#
# `clink` ("Link Customization to Source", ON from the factory) makes a
# strip display its source socket's name, and a name a human types on the
# channel screen goes to the SOCKET. The maintainer named channel 20 "Podium" by
# hand; `/ch/20/name` read blank, `/io/in/LCL/20/name` read 'Podium', and
# the strip was on LCL 20 -- the factory patch -- so `is_in_use` called
# somebody's live channel free.


def _podium(**overrides) -> ConsoleState:
    """Channel 20 of the A13 capture, in literals: blank strip name, named
    socket, factory patch. Every arm but the socket one says "free"."""
    values = {
        "/ch/20/name": "",
        "/ch/20/clink": 1,
        "/ch/20/in/conn/grp": "LCL", "/ch/20/in/conn/in": 20,
        "/io/in/LCL/20/name": "Podium",
    }
    values.update(overrides)
    return _compact({k: v for k, v in values.items() if v is not None})


def test_a_strip_named_on_its_socket_is_in_use():
    assert is_in_use(_podium(), "/ch/20")


def test_every_other_arm_of_the_test_says_that_strip_is_free():
    """Not a vacuous test: it is what makes the one above the only thing
    standing between an amendment and somebody's live channel."""
    blind = _podium(**{"/io/in/LCL/20/name": None})
    assert blind.name("/ch/20") == ""
    assert blind.patch("/ch/20") == ("LCL", 20)
    assert not is_in_use(blind, "/ch/20")


def test_an_unread_socket_name_is_not_an_answer():
    """`is_in_use` has only a bool, so an unread socket name is simply not
    evidence of use -- but `source_is_named` says None, which is what
    `amend.strip_occupancy` turns into UNKNOWN, and unknown is never
    free."""
    assert source_is_named(_podium(**{"/io/in/LCL/20/name": None}), "/ch/20") is None
    assert source_is_named(_podium(), "/ch/20") is True


def test_clink_unread_is_treated_as_on_because_on_is_the_factory_setting():
    """The audit's read plan does not ask for `clink` -- one address per
    strip, patched or not, against an assumption whose only cost is going
    to look at one more socket."""
    assert is_in_use(_podium(**{"/ch/20/clink": None}), "/ch/20")


def test_a_strip_unlinked_from_its_socket_is_read_by_its_own_name():
    """`clink` is per strip and `apply.py` switches it off for a socket
    shared between two strips. On those the strip's own name is the one
    that shows, and the socket's says nothing about this strip."""
    assert not is_in_use(_podium(**{"/ch/20/clink": 0}), "/ch/20")
    assert is_in_use(_podium(**{"/ch/20/clink": 0, "/ch/20/name": "Podium"}), "/ch/20")


def test_an_unpatched_strip_has_no_socket_to_be_named_by():
    assert source_is_named(_compact({"/ch/20/name": ""}), "/ch/20") is False


def test_the_desks_own_label_on_a_media_aux_is_not_somebody_naming_it():
    """The false positive in the other direction, and the one that would
    cost `a8-audit-initialized-board.sh` its zero: every WING ships
    `/aux/1` patched from USB 1, whose socket reads `'USB 1/2'`, and
    `/aux/2` from PLAY 1, whose socket reads `'2TR'`. Both measured off
    `Initialized-Compact.snap`."""
    usb = _compact({"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1,
                    "/io/in/USB/1/name": "USB 1/2"})
    play = _compact({"/aux/2/in/conn/grp": "PLAY", "/aux/2/in/conn/in": 1,
                     "/io/in/PLAY/1/name": "2TR"})
    assert not is_in_use(usb, "/aux/1")
    assert not is_in_use(play, "/aux/2")


def test_a_person_naming_that_same_media_aux_is_seen():
    """The discount is of the desk's own label, not of the socket."""
    state = _compact({"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1,
                      "/io/in/USB/1/name": "Walk-in Music"})
    assert is_in_use(state, "/aux/1")


@pytest.mark.parametrize("group,label", [
    ("LCL", ""), ("LCL", "LCL 20"), ("USB", "USB 1/2"), ("PLAY", "2TR"),
    ("A", "A 1"), ("AES", "AES 3"),
])
def test_labels_the_desk_writes_about_itself(group, label):
    assert is_factory_source_label(group, label)


@pytest.mark.parametrize("group,name", [
    ("LCL", "Podium"), ("A", "Kick"), ("USB", "Walk-in"), ("PLAY", "Interval"),
])
def test_names_a_person_writes(group, name):
    assert not is_factory_source_label(group, name)


# -- the name a finding quotes, and the name a collision compares ----------


def test_the_name_a_finding_quotes_is_the_one_on_the_desk():
    """A finding that says `/ch/20` about a strip the engineer can see is
    called Podium reads as a finding about some other desk."""
    state = _podium(**{"/ch/20/fdr": -144.0, "/ch/20/mute": 0})
    detail = " ".join(f.detail for f in run_audit(state))
    assert 'CH 20 "Podium"' in detail


def test_two_strips_named_on_their_sockets_still_collide():
    """N001 compared `{base}/name` alone, so two strips a
    person named identically on the desk -- blank strip names, the names
    on their sockets -- did not collide at all."""
    state = _compact({
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 2,
        "/io/in/A/1/name": "Vox", "/io/in/A/2/name": "Vox",
    })
    finding = next(f for f in run_audit(state) if f.rule_id == "N001")
    assert "CH 1" in finding.detail and "CH 2" in finding.detail
    # ...and it cites the addresses the names were actually read from.
    assert set(finding.addresses) == {"/io/in/A/1/name", "/io/in/A/2/name"}


def test_one_socket_feeding_two_strips_is_not_a_name_collision():
    """It is one name, in one place, on a festival split -- which C002
    reports as what it is. A collision needs two sources."""
    state = _compact({
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 1,
        "/io/in/A/1/name": "Vox",
    })
    rules = _rule_ids(run_audit(state))
    assert "C002" in rules
    assert "N001" not in rules


def test_a_name_read_on_the_strip_beats_an_assumed_clink():
    """`apply.py` switches `clink` off for a shared socket and names each
    strip separately. A state with no reading of `clink` in it -- one
    assembled by hand, or a capture taken -- assumes ON,
    and an assumption must not overrule a name that was actually read, or
    every shared input would report a collision that is not there. (A full
    read takes the reading now, and then this strip lands in the
    clink-OFF branch and gets the same answer for a better reason.)"""
    state = _compact({
        "/ch/1/name": "Vox L", "/ch/2/name": "Vox R",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 1,
        "/io/in/A/1/name": "Vox",
    })
    assert effective_name(state, "/ch/1") == "Vox L"
    assert "N001" not in _rule_ids(run_audit(state))


def test_where_clink_was_actually_read_and_is_on_the_socket_name_is_what_shows():
    """The other side of the same judgement: both a scoped occupancy read
    and a full audit read ask for `clink`, and where it
    comes back ON the desk is displaying the socket's name whatever the
    strip's own says. This is the branch the A17 'Acoustic'/'Acoustic 2'
    pair needed -- see `tests/test_audit_stale_strip_name.py`."""
    state = _compact({"/ch/1/name": "Old Name", "/ch/1/clink": 1,
                      "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
                      "/io/in/A/1/name": "Podium"})
    assert effective_name(state, "/ch/1") == "Podium"


def test_a_shared_input_finding_says_which_strips_by_name():
    state = _compact({
        "/ch/1/name": "Kick", "/ch/2/name": "Kick Sub",
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 1,
        "/ch/1/clink": 0, "/ch/2/clink": 0,
    })
    finding = next(f for f in run_audit(state) if f.rule_id == "C002")
    assert 'CH 1 "Kick"' in finding.detail and 'CH 2 "Kick Sub"' in finding.detail


# -- what the second pass costs --------------------------------------------


def test_the_second_pass_asks_only_about_sockets_a_strip_is_patched_to():
    state = _compact({
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "OFF", "/ch/2/in/conn/in": 1,
        "/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1,
    })
    assert source_name_addresses(state) == [("/io/in/A/1/name", "s"),
                                            ("/io/in/USB/1/name", "s")]


def test_one_socket_feeding_two_strips_is_asked_about_once():
    state = _compact({
        "/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 1,
        "/ch/2/in/conn/grp": "A", "/ch/2/in/conn/in": 1,
    })
    assert source_name_addresses(state) == [("/io/in/A/1/name", "s")]


# --------------------------------------------------------------------------
# Which patches are the factory's own is a fact about the model
# --------------------------------------------------------------------------
#
# Choosing between naming the Compact's two media
# auxes in the vocabulary rule and broadening it once: *"Go with your
# recommended B"* -- any factory-default patch, whatever the source. The
# table that answers "which" is `console_facts.FACTORY_INPUT_PATCHES`,
# measured off `Initialized-Compact.snap` and keyed by model.


def _compact(values: dict) -> ConsoleState:
    return ConsoleState(values, console_model="wing-compact")


def test_a_compacts_media_aux_is_not_in_use_on_the_model_we_measured():
    """`/aux/1` ships patched from USB 1 -- the USB stick player. Nobody
    plugged that in; it is how the desk arrives."""
    assert not is_in_use(_compact({"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1}),
                         "/aux/1")


def test_the_other_media_aux_is_the_media_player():
    assert not is_in_use(_compact({"/aux/2/in/conn/grp": "PLAY", "/aux/2/in/conn/in": 1}),
                         "/aux/2")


def test_the_same_source_on_the_other_aux_is_a_patch():
    """Narrow, the same way the channel identity is narrow: the factory
    put USB 1 on aux 1, so USB 1 on aux 2 is somebody's decision."""
    assert is_in_use(_compact({"/aux/2/in/conn/grp": "USB", "/aux/2/in/conn/in": 1}),
                     "/aux/2")


def test_a_different_socket_from_the_same_player_is_a_patch():
    assert is_in_use(_compact({"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 2}),
                     "/aux/1")


def test_an_aux_the_factory_leaves_unpatched_is_in_use_the_moment_it_is_patched():
    """Auxes 3-8 arrive OFF, so any patch on one of them is a decision."""
    assert is_in_use(_compact({"/aux/5/in/conn/grp": "USB", "/aux/5/in/conn/in": 1}),
                     "/aux/5")


def test_a_channel_beyond_the_factorys_own_lcl_run_is_in_use_on_lcl():
    """The measured table beats the identity where the two disagree: a
    Compact patches channels 1-24 and leaves 25-40 OFF, so `/ch/30` on
    LCL 30 is a patch somebody made, not a default."""
    assert is_in_use(_compact({"/ch/30/in/conn/grp": "LCL", "/ch/30/in/conn/in": 30}),
                     "/ch/30")
    assert not is_in_use(_compact({"/ch/24/in/conn/grp": "LCL", "/ch/24/in/conn/in": 24}),
                         "/ch/24")


def test_a_bus_has_no_factory_input_patch_at_all():
    """A bus has no `in.conn` node on the capture, so anything read there
    is somebody's doing -- and `is_in_use` must not quietly exclude it."""
    assert is_in_use(_compact({"/bus/3/in/conn/grp": "LCL", "/bus/3/in/conn/in": 3}),
                     "/bus/3")


# -- the unmeasured case: the fallback hides nothing ------------------------


@pytest.mark.parametrize("model", [None, "wing-rack", "wing-ultra"])
def test_an_unmeasured_model_still_discounts_the_channel_lcl_identity(model):
    """Every WING puts channel n on local input n before it is told
    otherwise; that much we are confident of across the family, and it is
    all the fallback claims."""
    state = ConsoleState({"/ch/3/in/conn/grp": "LCL", "/ch/3/in/conn/in": 3},
                         console_model=model)
    assert not is_in_use(state, "/ch/3")


@pytest.mark.parametrize("model", [None, "wing-rack", "wing-ultra"])
def test_an_unmeasured_model_reports_a_media_aux_rather_than_hiding_it(model):
    """The direction the fallback errs in, asserted rather than assumed.
    We have never measured a Rack, so `/aux/1` on USB 1 might be
    that desk's factory patch or might be tonight's playback rig -- and an
    INFO the engineer can dismiss beats a finding that never prints."""
    state = ConsoleState({"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1},
                         console_model=model)
    assert is_in_use(state, "/aux/1")


# -- where the model comes from ---------------------------------------------


def test_a_state_says_nothing_about_a_console_until_it_is_told():
    assert ConsoleState({}).console_model is None


def test_a_plan_can_supply_the_model_the_state_does_not_know():
    """`atoo audit --state <file> --plan <file>`: the file names no
    console, but the plan does, in `meta.console_model` -- the same field
    `verify_plan.resolve_console_model` reads."""
    values = {"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1,
              "/aux/1/fdr": -144.0, "/aux/1/mute": 0, "/aux/1/main/1/on": 1}
    without = run_audit(ConsoleState(values))
    with_plan = run_audit(ConsoleState(values),
                          plan={"meta": {"console_model": "wing-compact"},
                                "channels": []})
    assert "L002" in _rule_ids(without)
    assert "L002" not in _rule_ids(with_plan)


def test_the_state_beats_the_plan_about_which_desk_this_reading_came_off():
    """A plan is a claim about the console it was written for; a state
    read off a desk is the desk. Where they disagree, the desk wins.

    `/ch/20` on LCL 20 is the factory patch on a Compact and not on a
    Full (whose factory LCL run stops at 8), so the two models give
    different answers. It used to be `/aux/1` on USB 1, which stopped
    discriminating once the Full was measured and turned out to ship that
    patch too."""
    values = {"/ch/20/in/conn/grp": "LCL", "/ch/20/in/conn/in": 20,
              "/ch/20/fdr": -144.0, "/ch/20/mute": 0, "/ch/20/main/1/on": 1}
    plan = {"meta": {"console_model": "wing-compact"}, "channels": []}
    assert "L002" not in _rule_ids(run_audit(ConsoleState(values), plan=plan))
    findings = run_audit(ConsoleState(values, console_model="wing-full"), plan=plan)
    assert "L002" in _rule_ids(findings)


def test_a_live_read_takes_the_model_the_desk_stated_on_its_identity():
    """`read_console_state` asks the console object, which remembered the
    `/?` reply -- so no caller has to carry the model down, and no second
    round trip is spent on it."""
    class Desk:
        console_model = "wing-compact"

        def get(self, address):
            return None

    state = read_console_state(Desk(), channels=0, aux=0, buses=0, mains=0,
                               matrices=0, dcas=0, mute_groups=0)
    assert state.console_model == "wing-compact"


def test_a_live_read_from_a_desk_that_was_never_asked_knows_no_model():
    class Desk:
        def get(self, address):
            return None

    state = read_console_state(Desk(), channels=0, aux=0, buses=0, mains=0,
                               matrices=0, dcas=0, mute_groups=0)
    assert state.console_model is None


# --------------------------------------------------------------------------
# An output socket's number is a slot, not an object index
# --------------------------------------------------------------------------


def test_an_output_socket_number_decodes_to_the_object_it_feeds():
    """`apply._output_slot` gives object N the pair `(2N-1, 2N)`. This is
    its inverse, and without it every object after the first is misread."""
    state = ConsoleState({
        "/io/out/LCL/1/grp": "BUS", "/io/out/LCL/1/in": 1,   # bus 1, L
        "/io/out/LCL/2/grp": "BUS", "/io/out/LCL/2/in": 2,   # bus 1, R
        "/io/out/LCL/3/grp": "BUS", "/io/out/LCL/3/in": 3,   # bus 2, L
        "/io/out/LCL/4/grp": "MAIN", "/io/out/LCL/4/in": 6,  # Main 3, R
    })
    assert output_source_object(state, "LCL", 1) == ("BUS", 1)
    assert output_source_object(state, "LCL", 2) == ("BUS", 1)
    assert output_source_object(state, "LCL", 3) == ("BUS", 2)
    assert output_source_object(state, "LCL", 4) == ("MAIN", 3)


def test_an_unpatched_output_socket_decodes_to_nothing():
    assert output_source_object(ConsoleState({"/io/out/LCL/1/grp": "OFF"}), "LCL", 1) is None


def test_a_mains_right_hand_socket_is_not_a_second_main():
    """The factory Compact patches local out 8 from `MAIN 2`, which is
    Main 1's R slot. Read as an index it is a Main patched to a jack with
    nothing feeding it, and R004 says so on an untouched desk."""
    state = ConsoleState({
        "/main/1/fdr": 0.0, "/main/2/fdr": 0.0,
        "/ch/1/name": "Kick", "/ch/1/main/1/on": 1,
        "/io/out/LCL/7/grp": "MAIN", "/io/out/LCL/7/in": 1,
        "/io/out/LCL/8/grp": "MAIN", "/io/out/LCL/8/in": 2,
    })
    assert "R004" not in _rule_ids(run_audit(state))


# --------------------------------------------------------------------------
# The whole rule set against a real factory board
# --------------------------------------------------------------------------


def _console_state_from_snap(path: Path, console_model: str = "wing-compact") -> ConsoleState:
    """One of the maintainer's hardware captures, flattened into the addresses
    `read_console_state` walks. A `.snap` is the console's own JSON node
    tree (`atoo/snapshot.py`), so `ae_data["ch"]["1"]["fdr"]` is
    `/ch/1/fdr` -- and it is evidence the desk wrote itself, not a
    recollection of what a board looks like.

    The model is stated because the capture cannot state it: a `.snap`
    carries `creator_model: "wing"`, which every WING writes. Both
    captures this file scores are the maintainer's Compact -- the same desk the
    panel counts below assume, and the desk
    `console_facts.FACTORY_INPUT_PATCHES`' one measured row was read off.
    A live audit gets the model from the `/?` identity instead.
    """
    ae = json.loads(path.read_text())["ae_data"]
    values: dict[str, object] = {}

    def put(address, value):
        if value is not None:
            values[address] = int(value) if isinstance(value, bool) else value

    def scalar(node, key):
        return node.get(key, (node.get("config") or {}).get(key))

    for bank in ("ch", "aux", "bus"):
        for n, strip in (ae.get(bank) or {}).items():
            base = f"/{bank}/{n}"
            for key in ("name", "mute", "fdr", "tags"):
                put(f"{base}/{key}", scalar(strip, key))
            conn = ((strip.get("in") or {}).get("conn") or {})
            put(f"{base}/in/conn/grp", conn.get("grp"))
            put(f"{base}/in/conn/in", conn.get("in"))
            if bank != "bus":
                put(f"{base}/in/conn/altgrp", conn.get("altgrp"))
                put(f"{base}/in/set/altsrc",
                    ((strip.get("in") or {}).get("set") or {}).get("altsrc"))
            for idx, send in (strip.get("send") or {}).items():
                if bank == "bus" and not str(idx).startswith("MX"):
                    continue   # read_console_state reads only MX sends on a bus
                for key in ("on", "lvl", "mode", "pon"):
                    put(f"{base}/send/{idx}/{key}", send.get(key))
            for idx, route in (strip.get("main") or {}).items():
                put(f"{base}/main/{idx}/on", route.get("on"))

    for bank, keys in (("main", ("mute", "fdr")), ("mtx", ("mute", "fdr")),
                       ("dca", ("name", "mute", "fdr")), ("mgrp", ("name", "mute"))):
        for n, obj in (ae.get(bank) or {}).items():
            for key in keys:
                put(f"/{bank}/{n}/{key}", scalar(obj, key))
    for n, main in (ae.get("main") or {}).items():
        for idx, send in (main.get("send") or {}).items():
            for key in ("on", "lvl", "mode", "pon"):
                put(f"/main/{n}/send/{idx}/{key}", send.get(key))

    # The panel a WING Compact actually has (console_facts.panel_for),
    # which is what `socket_groups_to_read()` gives a live run with no
    # plan: LCL 1-24 in, LCL 1-8 out.
    io = ae.get("io") or {}
    for n, socket in list((io.get("in") or {}).get("LCL", {}).items()):
        put(f"/io/in/LCL/{n}/vph", socket.get("vph"))
    for n, socket in list((io.get("out") or {}).get("LCL", {}).items()):
        put(f"/io/out/LCL/{n}/grp", socket.get("grp"))
        put(f"/io/out/LCL/{n}/in", socket.get("in"))
    for n, socket in list((io.get("in") or {}).get("USR", {}).items()):
        user = socket.get("user") or {}
        put(f"/io/in/USR/{n}/user/grp", user.get("grp"))
        put(f"/io/in/USR/{n}/user/in", user.get("in"))

    # The SECOND PASS: the name on every socket a strip turned
    # out to be patched to, which on a WING is where a name a human typed
    # actually lives. Built the way `audit.source_name_addresses` builds
    # it -- off the patches the first pass read -- so this state holds
    # exactly the addresses a live read would have, no more.
    for address, _ in source_name_addresses(ConsoleState(dict(values))):
        _, _, _, group, number, _ = address.split("/")
        put(address, (((io.get("in") or {}).get(group) or {}).get(number) or {}).get("name"))

    # And the rest of it: `clink`, per patched strip, which
    # is what tells `effective_name` whether the strip is showing its own
    # name or its socket's. Same discipline -- taken off the capture, and
    # only for the strips a live read would have asked about.
    for address, _ in custom_link_addresses(ConsoleState(dict(values))):
        bank, number = address.split("/")[1:3]
        put(address, ((ae.get(bank) or {}).get(number) or {}).get("clink"))

    return ConsoleState(values, console_model=console_model)


def _initialized_console_state() -> ConsoleState:
    """The factory board: `Initialized-Compact.snap`."""
    return _console_state_from_snap(INITIALIZED_COMPACT)


def _podium_console_state() -> ConsoleState:
    """The board the maintainer set up by hand, with channel 20 named "Podium"
    **on its socket** -- `A13-board-with-podium.snap`, the capture an earlier change was written off."""
    return _console_state_from_snap(BOARD_WITH_PODIUM)


def _captured_patch(strip) -> tuple[str, int] | None:
    """What this strip's `in.conn` node says, as `is_in_use` reads it --
    `grp: "OFF"` is no patch, whatever socket number sits beside it."""
    conn = ((strip.get("in") or {}).get("conn") or {})
    group, socket = conn.get("grp"), conn.get("in")
    if not group or group == "OFF" or socket is None:
        return None
    return group, int(socket)


def test_the_snapshot_this_file_scores_really_is_an_untouched_desk():
    """Not vacuous: if someone swaps in a capture of a desk mid-show, the
    zero-findings test below stops meaning anything. These are the facts
    the rest of this file rests on, measured rather than assumed."""
    ae = json.loads(INITIALIZED_COMPACT.read_text())["ae_data"]
    assert [n for n, s in ae["ch"].items() if (s.get("name") or "").strip()] == []
    assert [n for n, s in ae["bus"].items() if (s.get("name") or "").strip()] == []
    # every channel patched from LCL is patched from its own number
    assert all(((s.get("in") or {}).get("conn") or {}).get("in") == int(n)
               for n, s in ae["ch"].items()
               if ((s.get("in") or {}).get("conn") or {}).get("grp") == "LCL")
    # and `main/1/on` really is on for all forty, which is the reading
    # that used to make every one of them "active"
    assert all(((s.get("main") or {}).get("1") or {}).get("on") for s in ae["ch"].values())


def test_the_factory_patch_table_says_what_the_capture_says():
    """`console_facts.FACTORY_INPUT_PATCHES["wing-compact"]` is a
    transcription of this file, and this is the test that keeps it one.

    Spelled out in literals rather than rebuilt from the constant it is
    checking -- a table compared against itself passes whatever it says.
    The capture is the independent side.
    """
    ae = json.loads(INITIALIZED_COMPACT.read_text())["ae_data"]

    captured_ch = {int(n): _captured_patch(s) for n, s in ae["ch"].items()}
    assert [n for n, patch in sorted(captured_ch.items()) if patch is not None] == list(range(1, 25))
    assert all(captured_ch[n] == ("LCL", n) for n in range(1, 25))
    assert captured_ch[25] is None and captured_ch[40] is None

    captured_aux = {int(n): _captured_patch(s) for n, s in ae["aux"].items()}
    assert captured_aux[1] == ("USB", 1)
    assert captured_aux[2] == ("PLAY", 1)
    assert [n for n in range(3, 9) if captured_aux[n] is not None] == []

    assert [n for n, s in ae["bus"].items() if _captured_patch(s) is not None] == []

    # ...and that is exactly what the table is asked for, one call at a
    # time, through the function the audit actually uses.
    patch_for = console_facts.factory_input_patch
    assert patch_for("wing-compact", "ch", 1) == ("LCL", 1)
    assert patch_for("wing-compact", "ch", 24) == ("LCL", 24)
    assert patch_for("wing-compact", "ch", 25) is None
    assert patch_for("wing-compact", "aux", 1) == ("USB", 1)
    assert patch_for("wing-compact", "aux", 2) == ("PLAY", 1)
    assert patch_for("wing-compact", "aux", 3) is None
    assert patch_for("wing-compact", "bus", 1) is None


def test_an_unpatched_strip_is_not_carrying_the_factory_patch():
    """`None` is "nothing is patched here", and the factory leaves aux 3
    alone -- but "both are nothing" must not read as "these match", or an
    unpatched strip would count as factory-patched and the two answers
    `is_in_use` gives would collapse into one."""
    assert console_facts.is_factory_input_patch("wing-compact", "aux", 3, None) is False
    assert console_facts.is_factory_input_patch("wing-compact", "aux", 1, None) is False


def test_the_full_size_factory_patch_table_says_what_its_capture_says():
    """`console_facts.FACTORY_INPUT_PATCHES["wing-full"]` is a
    transcription of `Initialized-Full.snap`, kept one the same way the
    Compact row is: literals against the capture, then the table asked one
    call at a time."""
    ae = json.loads(INITIALIZED_FULL.read_text())["ae_data"]

    captured_ch = {int(n): _captured_patch(s) for n, s in ae["ch"].items()}
    assert [n for n, patch in sorted(captured_ch.items()) if patch is not None] == list(range(1, 9))
    assert all(captured_ch[n] == ("LCL", n) for n in range(1, 9))
    assert captured_ch[9] is None and captured_ch[40] is None

    captured_aux = {int(n): _captured_patch(s) for n, s in ae["aux"].items()}
    assert captured_aux[1] == ("USB", 1)
    assert captured_aux[2] == ("PLAY", 1)
    assert [n for n in range(3, 9) if captured_aux[n] is not None] == []

    assert [n for n, s in ae["bus"].items() if _captured_patch(s) is not None] == []

    patch_for = console_facts.factory_input_patch
    assert "wing-full" in console_facts.MEASURED_FACTORY_PATCH_MODELS
    assert patch_for("wing-full", "ch", 1) == ("LCL", 1)
    assert patch_for("wing-full", "ch", 8) == ("LCL", 8)
    # Where the identity fallback used to say LCL 9: the panel has 8.
    assert patch_for("wing-full", "ch", 9) is None
    assert patch_for("wing-full", "ch", 40) is None
    assert patch_for("wing-full", "aux", 1) == ("USB", 1)
    assert patch_for("wing-full", "aux", 2) == ("PLAY", 1)
    assert patch_for("wing-full", "aux", 3) is None
    assert patch_for("wing-full", "bus", 1) is None


def test_on_a_full_size_a_channel_past_its_eight_local_inputs_is_not_factory():
    """What measuring the Full changed for occupancy. The identity
    fallback said an untouched `/ch/9..40` should sit on LCL 9..40 --
    sockets a Full does not have -- so the genuinely untouched reading
    (OFF) was fine but a strip on LCL 12 would have been discounted as
    factory. Measured, LCL 12 on `/ch/12` is a patch somebody made, and
    `/aux/1` on USB 1 is the factory's."""
    def full(values):
        return ConsoleState(values, console_model="wing-full")
    assert is_in_use(full({"/ch/12/in/conn/grp": "LCL", "/ch/12/in/conn/in": 12}), "/ch/12")
    assert not is_in_use(full({"/ch/8/in/conn/grp": "LCL", "/ch/8/in/conn/in": 8}), "/ch/8")
    assert not is_in_use(full({"/aux/1/in/conn/grp": "USB", "/aux/1/in/conn/in": 1}), "/aux/1")
    assert not is_in_use(full({"/aux/2/in/conn/grp": "PLAY", "/aux/2/in/conn/in": 1}), "/aux/2")


def test_an_unmeasured_model_gets_the_identity_and_nothing_else():
    """The fallback, at the table rather than through `is_in_use`. A model
    we have never had in front of us is not given a Compact's aux patches
    on the strength of the family resemblance."""
    patch_for = console_facts.factory_input_patch
    assert "wing-rack" not in console_facts.MEASURED_FACTORY_PATCH_MODELS
    assert patch_for("wing-rack", "ch", 9) == ("LCL", 9)
    assert patch_for("wing-rack", "ch", 40) == ("LCL", 40)
    assert patch_for("wing-rack", "aux", 1) is None
    assert patch_for("wing-rack", "bus", 1) is None
    assert patch_for(None, "ch", 3) == ("LCL", 3)
    assert patch_for(None, "aux", 1) is None


def test_an_initialized_console_produces_exactly_0_findings():
    """The headline, and the number is the whole of it.

    This capture scored **97** findings before the maintainer's vocabulary rule
    was implemented, 49 of them warnings; **4** after it, all
    INFO, all about `/aux/1` and `/aux/2` -- the two auxes a Compact ships
    patched from the USB player and the media player, which the rule named
    no exclusion for. On whether to name a third one
    or broaden the rule once: *"Go with your recommended B"*. So: **0**.

    Nothing about this number is allowed to be arranged. If it moves, read
    what came back before touching anything -- a real finding on an
    untouched desk is a finding about the rules, not about the desk.
    """
    findings = run_audit(_initialized_console_state())
    assert len(findings) == 0, "\n".join(
        f"{f.severity.value} {f.rule_id} {f.detail}" for f in findings)


def test_an_initialized_full_size_console_produces_exactly_0_findings():
    """The same headline for the second model we have measured. Before
    `FACTORY_INPUT_PATCHES["wing-full"]` existed this capture scored 4
    INFO findings (CH001 and L002 on `/aux/1` and `/aux/2`), the
    identity fallback not knowing the Full ships the same two media auxes
    the Compact does."""
    findings = run_audit(_console_state_from_snap(INITIALIZED_FULL, "wing-full"))
    assert len(findings) == 0, "\n".join(
        f"{f.severity.value} {f.rule_id} {f.detail}" for f in findings)


def test_an_initialized_console_raises_no_error_and_no_warning():
    """Weaker than the test above and kept deliberately: it is the one
    that still says something if a later change decides an untouched board
    is worth an INFO or two. Silence about errors and warnings is the
    floor; zero is the current reading."""
    findings = run_audit(_initialized_console_state())
    loud = [f for f in findings if f.severity is not Severity.INFO]
    assert loud == [], "\n".join(f"{f.severity.value} {f.rule_id} {f.detail}" for f in loud)


def test_the_two_media_auxes_are_what_the_zero_is_made_of():
    """The four findings that went, and why they went.

    `/aux/1` ships patched from USB 1 and `/aux/2` from PLAY 1. Told this
    is a Compact, the audit knows those are the desk's own doing and says
    nothing; told nothing, it reports them -- the reading every other
    model gets, because we have measured no other model. Both halves are
    asserted here so that "zero" cannot be reached by excluding patches
    wholesale.
    """
    from dataclasses import replace

    known = _initialized_console_state()
    unknown = replace(known, console_model=None)

    assert [f.rule_id for f in run_audit(known)] == []

    blind = run_audit(unknown)
    assert sorted(f.rule_id for f in blind) == [
        "CH001", "CH001", "L002", "L002"]
    assert {a.split("/fdr")[0] for f in blind for a in f.addresses} == {"/aux/1", "/aux/2"}


def test_the_factory_boards_media_auxes_are_named_by_the_desk_itself():
    """What the zero now also depends on. Reading socket
    names means reading `/io/in/USB/1/name` and `/io/in/PLAY/1/name`,
    which on a board nobody has touched are `'USB 1/2'` and `'2TR'` --
    the desk's own labels. Discount them wrongly and an untouched Compact
    reports two auxes as somebody's work; the values are asserted here off
    the capture, not assumed."""
    state = _initialized_console_state()
    assert state.text("/io/in/USB/1/name") == "USB 1/2"
    assert state.text("/io/in/PLAY/1/name") == "2TR"
    assert {state.text(f"/io/in/LCL/{n}/name") for n in range(1, 25)} == {""}
    assert not is_in_use(state, "/aux/1")
    assert not is_in_use(state, "/aux/2")


# --------------------------------------------------------------------------
# ...and the board the maintainer set up BY HAND
# --------------------------------------------------------------------------
#
# Every other capture in this repository is a desk this project built
# itself, which is exactly why the blind spot survived: `apply.py` writes
# the name to the strip as well as the socket, so `/ch/1/name` is 'Kick'
# on all of them. `A13-board-with-podium.snap` is the one board a human
# named by hand, and channel 20 is the strip he named.


def test_the_podium_capture_really_does_carry_the_name_only_on_the_socket():
    """Not vacuous, and it is the fact the rest of this section rests on:
    if a future capture were swapped in with the name on the strip, the
    test below would pass while proving nothing."""
    state = _podium_console_state()
    assert state.name("/ch/20") == ""
    assert state.text("/io/in/LCL/20/name") == "Podium"
    assert state.patch("/ch/20") == ("LCL", 20)   # the Compact's factory patch
    # The desk has `clink` on, and since an earlier change the audit's read goes
    # and takes that reading rather than assuming it -- per patched strip,
    # in the same second pass that fetches the socket's name. The Podium
    # answer does not move either way: with the flag unread it was ON by
    # assumption, and with it read it is ON in fact.
    assert json.loads(BOARD_WITH_PODIUM.read_text())["ae_data"]["ch"]["20"]["clink"] is True
    assert state.flag("/ch/20/clink") is True


def test_the_channel_a_human_named_by_hand_is_in_use():
    """The headline, scored off the capture. `False` here
, on a strip with somebody's live feed on it."""
    assert is_in_use(_podium_console_state(), "/ch/20")


def test_the_audit_now_has_something_to_say_about_that_channel():
    """30 findings on this board before an earlier change and 32 after, and the two new
    ones are both about `/ch/20`: it is in use and in no DCA (CH001),
    and it is unmuted and in use with its fader at the floor (L002).
    Neither is a regression to paper over -- they are the rules finally
    seeing a strip that was invisible to them. Both name it 'Podium',
    which is only readable because the name came off the socket."""
    findings = [f for f in run_audit(_podium_console_state()) if "CH 20" in f.detail]
    assert sorted(f.rule_id for f in findings) == ["CH001", "L002"]
    assert all('"Podium"' in f.detail for f in findings)


# --------------------------------------------------------------------------
# ...and the same board down the LIVE path
# --------------------------------------------------------------------------
#
# Everything above scores a `ConsoleState` built straight out of the
# `.snap`. A snapshot carries TRUE values -- the console wrote it itself --
# and a live read does not: WING's GET reply for a patch connector is one
# less than the number the desk shows, and `read_console_state` has to
# put that back (`console_facts.correct_readback_index`).
#
# So the zero above was real and said nothing about the path a user
# actually runs. `/aux/{n}/in/conn/in` was missing from the offset table
# until 2026-09-23, which meant a live audit read the Compact's two media
# auxes as patched from socket 0, matched neither against
# `FACTORY_INPUT_PATCHES`, and reported both as in use -- **4 findings on
# an untouched desk that the snapshot path scored at 0**. Nothing in the
# suite compared the two paths, so nothing caught it; A11 did, on
# hardware. This is that comparison.


# What the DESK does to a reply, spelled out here rather than taken from
# `console_facts.readback_index_offset`. The table is the thing under
# test; a fake that asked the table what to do would agree with it no
# matter what it said. Evidence for this list: A11 (aux, 8 of 8), the
# 2026-09-18 apply run (/ch, 20 of 20), A1's own `.snap` (/io/out/*/in)
# and A16 (/io/in/USR/*/user/in: screen and node dump 5, per-leaf 4). See
# `tests/test_readback_index_base.py`.
_DESK_REPORTS_ONE_LOW = (
    re.compile(r"^/ch/\d+/in/conn/in$"),
    re.compile(r"^/aux/\d+/in/conn/in$"),
    re.compile(r"^/io/out/[A-Z]+/\d+/in$"),
    re.compile(r"^/io/in/USR/\d+/user/in$"),
)


class SnapshotBackedDesk:
    """A WING that answers a GET the way the hardware does, from values a
    real factory-initialized Compact wrote into its own `.snap`.

    Reply shapes are the protocol PDF's (p21) and the ones
    `OscReply.value()` was confirmed against: `,s` for a string, `,sfi`
    for an int (raw text, 0..1 fraction, the int -- which for a connector
    is one lower than the text), `,sff` for a level. An address the
    snapshot does not carry gets no reply at all, exactly as an address
    the desk will not answer gets none.
    """

    console_model = "wing-compact"

    def __init__(self, values):
        self.values = values
        self.asked = []

    def get(self, address):
        self.asked.append(address)
        if address not in self.values:
            return None
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address=address, typetag="s", args=[value])
        if isinstance(value, float):
            text = "-oo" if value <= -144.0 else f"{value:g}"
            return OscReply(address=address, typetag="sff", args=[text, 0.0, value])
        shown = int(value)
        wire = shown - (1 if any(rx.match(address) for rx in _DESK_REPORTS_ONE_LOW) else 0)
        return OscReply(address=address, typetag="sfi", args=[str(shown), 0.0, wire])


_COMPACT_READ = dict(channels=40, aux=8, buses=16, mains=4, matrices=8,
                     dcas=16, mute_groups=8,
                     input_sockets={"LCL": 24}, output_sockets={"LCL": 8})


def _desk_from(state: ConsoleState) -> SnapshotBackedDesk:
    """A capture's values, typed the way the leaf is typed rather than
    the way JSON happened to spell it -- a fader of `-144` is a LEVEL, and
    a desk answers a level with `,sff` and the text `-oo`.

    A socket name is not in `console_read_plan` (it is the second pass) and so gets no type from it; it is a string in the capture
    and a string on the wire, and this desk answers it as one."""
    types = dict(console_read_plan(**_COMPACT_READ))
    values = {}
    for address, value in state.values.items():
        value_type = types.get(address)
        if value_type == "f":
            value = float(value)
        elif value_type == "i":
            value = int(value)
        elif value_type == "s":
            value = str(value)
        values[address] = value
    return SnapshotBackedDesk(values)


def _initialized_desk() -> SnapshotBackedDesk:
    return _desk_from(_initialized_console_state())


def _initialized_console_read() -> ConsoleState:
    """The factory board as `atoo audit --console` would read it:
    through `read_console_state`, off a desk answering in wire shapes,
    with the panel a Compact has."""
    return read_console_state(_initialized_desk(), **_COMPACT_READ)


def test_a_live_read_of_an_initialized_console_also_produces_exactly_0_findings():
    """The headline, down the path a user runs.

    **4 before the fix**, all INFO, all `/aux/1` and `/aux/2` -- the two
    media auxes, read as patched from socket 0 because the aux connector
    leaf was not in the readback-offset table. The snapshot-based sibling
    above scored 0 throughout and could not see it.
    """
    findings = run_audit(_initialized_console_read())
    assert len(findings) == 0, "\n".join(
        f"{f.severity.value} {f.rule_id} {f.detail}" for f in findings)


def test_the_live_read_puts_the_media_aux_patches_back_where_the_desk_shows_them():
    """The mechanism under the zero, in literals. The desk answers 0 for
    a socket it displays as 1; if that stays 0, nothing matches
    `FACTORY_INPUT_PATCHES` and the auxes come back as in use."""
    state = _initialized_console_read()
    assert state.text("/aux/1/in/conn/grp") == "USB"
    assert state.number("/aux/1/in/conn/in") == 1
    assert state.text("/aux/2/in/conn/grp") == "PLAY"
    assert state.number("/aux/2/in/conn/in") == 1
    # The channel leaf beside it, which was already right.
    assert state.text("/ch/7/in/conn/grp") == "LCL"
    assert state.number("/ch/7/in/conn/in") == 7


def test_the_live_read_and_the_snapshot_agree_on_every_address_both_hold():
    """The general form of the bug: the two paths are meant to describe
    the same desk, and until an earlier change they differed on eight addresses.

    Compared over the addresses the live read asks for, so the snapshot's
    extra leaves (a bus send `mode`, which the console has no such thing
    as -- an earlier change again) are not counted against it."""
    snapshot = _initialized_desk().values          # what the desk holds
    live = _initialized_console_read().values      # what the read made of it
    disagree = {a: (snapshot[a], live[a])
                for a in set(snapshot) & set(live)
                if snapshot[a] != live[a]}
    assert disagree == {}
    assert set(live) - set(snapshot) == set()


def test_a_user_patch_excuses_its_own_jack_from_sp_c001_on_a_live_read():
    """The consequence A16 found, down the path a user runs. USR 25 is fed
    from LOCAL IN 5 and that jack has 48V on, which is a perfectly good
    patch -- a condenser into a user patch needs phantom like any other.

    The desk answers the source index one low (A16: screen 5, per-leaf 4).
    Uncorrected, the read made this LCL 4, so C001 reported LCL 5 as
    "patched to nothing" and excused the jack beside it. Channels 4 and 5
    are unpatched here, because on a factory Compact they would patch those
    jacks themselves and hide the question."""
    values = dict(_initialized_console_state().values)
    values["/ch/4/in/conn/grp"] = "OFF"
    values["/ch/5/in/conn/grp"] = "OFF"
    values["/io/in/USR/25/user/grp"] = "LCL"
    values["/io/in/USR/25/user/in"] = 5
    values["/io/in/LCL/5/vph"] = 1
    state = read_console_state(SnapshotBackedDesk(values), **_COMPACT_READ)

    assert state.number("/io/in/USR/25/user/in") == 5
    wrongly_blamed = [f for f in run_audit(state)
                      if f.rule_id == "C001" and "LCL 5 " in f.detail]
    assert wrongly_blamed == [], wrongly_blamed[0].detail if wrongly_blamed else ""


def test_the_live_path_never_asks_for_a_bus_send_mode():
    """The other half, asserted where the read really happens: a
    full Compact read is 5,712 planned requests, not 6,032, and not one of
    them is an address the desk went silent on.

    **5,738 since an earlier change**: the 26 extra are the second pass, one per
    distinct socket a strip is patched to -- this desk's 24 LCL-patched
    channels and its two media auxes, and nothing at all for the 22 strips
    the factory leaves unpatched. See
    `test_the_second_pass_asks_only_about_sockets_a_strip_is_patched_to`.

    **5,808 + 26 since an earlier change**: each strip's alternate-patch group and
    switch, two leaves on each of the 48.

    **5,808 + 26 + 26 since an earlier change**: the second pass now also takes
    `clink` for each of those same 26 patched strips, so the audit stops
    guessing at the flag that decides whether a strip shows its own name
    or its socket's. Per PATCHED strip, not per strip -- an unpatched
    strip's flag answers no rule's question, which is what keeps this 26
    rather than 48.

    **6,112 + 26 + 26 since an earlier change**: every insert point and FX slot.
    **6,113 + 26 + 26** since its comms half: `/cfg/talk/assign`. A
    factory desk's talkback is unassigned, so its routing is not asked.
    **6,114 + 26 + 26** since the global alternate switch.
    **6,138 + 26 + 26**: each phantom-capable socket's
    width, beside its `vph`.
    **6,143 + 26 + 26**: the three AES50 ports'
    link status and the two monitor sources. A factory desk has nothing
    on AES50, so no AES50 output is asked.
    **6,167 + 26 + 26** since each local socket's own mute (C007).
    **6,195 + 26 + 26** since the width of each bus, Main and Matrix.

    **Counted as asked-or-deliberately-not.** The capture
    this desk is built from predates the insert points and FX slots, so
    here -- unlike on a real desk -- those families never answer, and the
    read stops asking for each after `UNANSWERED_FAMILY_CUTOFF`. Every
    planned address is still either asked (once; the liveness re-reads
    repeat an address already asked) or named as not asked."""
    desk = _initialized_desk()
    state = read_console_state(desk, **_COMPACT_READ)
    not_asked = sum(len(v) for v in state.unasked_families.values())
    assert len(set(desk.asked)) + not_asked == 6195 + 26 + 26
    assert "/bus/1/send/MX1/mode" not in desk.asked
    assert "/main/4/send/MX8/pon" not in desk.asked
    assert "/bus/1/send/MX1/on" in desk.asked
    assert "/ch/1/send/MX1/mode" in desk.asked


def test_the_second_pass_is_one_address_per_patched_socket_on_a_real_board():
    """The cost, counted on hardware values rather than argued.
    26 of 5,738: the 24 channels a Compact ships patched from its own LCL
    sockets, plus USB 1 and PLAY 1. The 16 unpatched channels and 6
    unpatched auxes cost nothing, which is the shape the budget has to
    have -- an earlier change had just spent a night removing addresses this
    project should never have asked for."""
    desk = _initialized_desk()
    read_console_state(desk, **_COMPACT_READ)
    sockets = [a for a in desk.asked if a.startswith("/io/in/") and a.endswith("/name")]
    assert len(sockets) == 26
    assert sockets == [f"/io/in/LCL/{n}/name" for n in range(1, 25)] + [
        "/io/in/USB/1/name", "/io/in/PLAY/1/name"]


def test_a_live_read_of_the_board_somebody_named_by_hand_sees_the_name():
    """The whole point, down the path a user runs. `atoo audit
    --console` against the A13 board reads `/ch/20/name` as blank and then
    goes and asks `/io/in/LCL/20/name`, which is where the name is."""
    state = read_console_state(_desk_from(_podium_console_state()), **_COMPACT_READ)
    assert state.name("/ch/20") == ""
    assert state.text("/io/in/LCL/20/name") == "Podium"
    assert is_in_use(state, "/ch/20")
    assert [f.rule_id for f in run_audit(state) if '"Podium"' in f.detail] == [
        "CH001", "L002"]
