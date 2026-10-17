"""Eight unanswered addresses cost 24s of a 47s read on a
full-size WING -- the shape on a model we had only just met.

Two halves, as an earlier change taught:

- **The read plan is corrected.** The eight were `/io/in/AUX/1..8/vph`:
  a full-size's AUX inputs are line-level jacks with no head amp, so
  there is no phantom leaf to answer. An address a model does not have
  is not asked for.
- **A family that does not answer is cheap anyway**, because the next
  model will have its own. Once `UNANSWERED_FAMILY_CUTOFF` siblings have
  gone unanswered, none has answered, and the desk is still answering,
  the rest of the family is not asked -- and is reported as not asked,
  never as a value.

Every desk here is a fake; nothing reads `examples/`.
"""

import io
import json
from pathlib import Path

from atoo import console_facts
from atoo.audit import (UNANSWERED_FAMILY_CUTOFF, UnansweredFamilies,
                             address_family, console_read_plan,
                             read_console_state, socket_groups_to_read)
from atoo.console import OscReply
from atoo.progress import ReadProgress

A18 = json.loads((Path(__file__).parent / "fixtures"
                  / "a18-full-size-unanswered.json").read_text())


class Desk:
    """Answers every address in `values`, and nothing else. `down_after`
    makes it stop answering anything at all after that many requests --
    a pulled cable, not a missing family."""

    console_model = "wing-full"

    def __init__(self, values, *, down_after=None):
        self.values = values
        self.asked = []
        self.down_after = down_after

    def get(self, address):
        self.asked.append(address)
        if self.down_after is not None and len(self.asked) > self.down_after:
            return None
        if address not in self.values:
            return None
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address, "s", [value])
        if isinstance(value, int):
            return OscReply(address, "sfi", [str(value), 0.0, value])
        return OscReply(address, "sff", [str(value), 0.0, float(value)])


# A small read: one channel, one bus, and sockets on the full-size panel.
SMALL = dict(channels=1, aux=0, buses=1, mains=1, matrices=0, dcas=1,
             mute_groups=0, fx_slots=1)
DEFAULTS = {"s": "OFF", "i": 0, "f": 0.0}


def desk_answering(plan, *, missing=()):
    missing = set(missing)
    return {a: DEFAULTS[t] for a, t in plan if a not in missing}


# -- the read-plan fix -----------------------------------------------------


def test_a_full_size_read_no_longer_asks_for_the_eight_that_went_unanswered():
    inputs, outputs = socket_groups_to_read(A18["console_model"])
    asked = {a for a, _ in console_read_plan(input_sockets=inputs,
                                             output_sockets=outputs)}
    assert not asked & set(A18["unanswered"])
    # ...and still asks for the phantom that exists, on the jacks that have it.
    assert set(A18["answered_vph"]) <= asked


def test_phantom_is_asked_only_of_groups_with_a_head_amp():
    """Stated for any group a caller names, not only AUX: USB, PLAY and a
    bay's sockets carry a signal levelled somewhere else and have no
    `vph` either (`console_facts.PHANTOM_CAPABLE_GROUPS`)."""
    plan = console_read_plan(input_sockets={"LCL": 2, "A": 2, "AUX": 2, "USB": 2})
    vph = {a for a, _ in plan if a.endswith("/vph")}
    assert vph == {"/io/in/LCL/1/vph", "/io/in/LCL/2/vph",
                   "/io/in/A/1/vph", "/io/in/A/2/vph"}
    assert {"LCL", "A"} <= console_facts.PHANTOM_CAPABLE_GROUPS
    assert not {"AUX", "USB"} & console_facts.PHANTOM_CAPABLE_GROUPS


# -- the family cut-off ----------------------------------------------------


def test_a_family_is_its_address_with_the_numbers_taken_out():
    assert address_family("/io/in/AUX/3/vph") == "/io/in/AUX/{n}/vph"
    assert address_family("/bus/2/send/MX4/mode") == "/bus/{n}/send/MX{n}/mode"
    # The group is kept: a model differs from another by exactly that.
    assert address_family("/io/in/LCL/3/vph") != address_family("/io/in/AUX/3/vph")


def _family_read(**desk_kwargs):
    """A read of a small plan plus eight sibling addresses the desk does
    not have -- `/io/in/USB/1..8/vph`, a made-up family standing in for
    whatever the next model is missing."""
    plan = console_read_plan(**SMALL, input_sockets={"LCL": 8})
    missing = [f"/io/in/USB/{n}/vph" for n in range(1, 9)]
    desk = Desk(desk_answering(plan), **desk_kwargs)
    return plan, missing, desk


def _read_with(missing_family, desk, progress=None, **extra):
    # Splice the missing family into the plan the read makes, the way a
    # model's panel would put it there.
    import atoo.audit as audit
    real = audit.console_read_plan

    def plan_with_family(**kwargs):
        return real(**kwargs) + [(a, "i") for a in missing_family]

    audit.console_read_plan = plan_with_family
    try:
        return read_console_state(desk, **SMALL, input_sockets={"LCL": 8},
                                  progress=progress, **extra)
    finally:
        audit.console_read_plan = real


def test_an_unanswered_family_costs_the_cutoff_not_the_family():
    plan, missing, desk = _family_read()
    progress = ReadProgress(len(plan) + len(missing), stream=io.StringIO(),
                            timeout=1.0)
    state = _read_with(missing, desk, progress)

    silent = [a for a in desk.asked if a in missing]
    assert silent == missing[:UNANSWERED_FAMILY_CUTOFF]
    assert progress.unanswered == UNANSWERED_FAMILY_CUTOFF
    # The rest are named as not asked, never recorded as a value.
    assert state.unasked_families == {"/io/in/USB/{n}/vph": missing[UNANSWERED_FAMILY_CUTOFF:]}
    assert not set(missing) & set(state.values)
    # The desk was asked once more to prove it was still there, and that
    # re-read is of an address that had already answered.
    probes = len(desk.asked) - len(set(desk.asked))
    assert probes == 1


def test_the_summary_says_which_family_it_stopped_asking_for_at_info():
    plan, missing, desk = _family_read()
    progress = ReadProgress(len(plan) + len(missing), stream=io.StringIO(),
                            timeout=1.0)
    _read_with(missing, desk, progress)
    summary = progress.summary()
    assert f"{len(plan) + len(missing)} of {len(plan) + len(missing)} addresses" in summary
    assert ("INFO: stopped asking for /io/in/USB/{n}/vph once 3 of them had "
            "gone unanswered while the desk kept answering; the other 5 were "
            "not asked. Those values are unknown -- not defaults.") in summary


def test_a_family_that_has_answered_once_is_never_cut():
    """The guarantee for addresses that answer: a family with even one
    answering member is asked in full, however many of the rest are
    silent."""
    plan, missing, desk = _family_read()
    desk.values["/io/in/USB/1/vph"] = 0
    state = _read_with(missing, desk)
    assert [a for a in desk.asked if a in missing] == missing
    assert state.unasked_families == {}
    assert state.values["/io/in/USB/1/vph"] == 0


def test_a_desk_that_stops_answering_altogether_cuts_no_family():
    """A failed liveness check is the link, not the family: the read goes
    on exactly as it did before the cut-off existed."""
    plan = console_read_plan(**SMALL, input_sockets={"LCL": 8})
    plan, missing, desk = _family_read(down_after=len(plan) - 20)
    state = _read_with(missing, desk)
    assert state.unasked_families == {}
    assert set(missing) <= set(desk.asked)
    assert set(a for a, _ in plan) <= set(desk.asked)


def test_a_desk_that_answers_everything_is_read_exactly_as_before():
    plan = console_read_plan(**SMALL, input_sockets={"LCL": 8})
    desk = Desk(desk_answering(plan))
    state = read_console_state(desk, **SMALL, input_sockets={"LCL": 8})
    assert desk.asked[:len(plan)] == [a for a, _ in plan]
    assert state.unasked_families == {}


def test_195s_320_would_have_cost_twelve_timeouts():
    """The shape the cut-off exists for, replayed: every bus and Main send
    to a matrix answering `on`/`lvl` and silent on `mode`/`pon`, the way
    A11's Compact was. Four families, three timeouts each."""
    families = UnansweredFamilies(alive=lambda address: True)
    timeouts = 0
    for bank, count in (("bus", 16), ("main", 4)):
        for n in range(1, count + 1):
            for m in range(1, 9):
                for leaf in ("on", "lvl", "mode", "pon"):
                    address = f"/{bank}/{n}/send/MX{m}/{leaf}"
                    if not families.should_ask(address):
                        continue
                    answered = leaf in ("on", "lvl")
                    timeouts += not answered
                    families.record(address, answered)
    assert timeouts == 4 * UNANSWERED_FAMILY_CUTOFF
    assert sum(len(v) for v in families.unasked.values()) == 320 - timeouts
