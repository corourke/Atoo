"""Making a running channel stereo, or mono again.

"Make ch 5 stereo" is an instruction, not a rule to refuse with "drop it and
add it again". A mono channel on an odd socket takes the next socket if nothing
uses it; what physically cannot be done (an even socket, a second socket
another channel uses) is refused with the reason. Nothing reads a bundle under
`examples/`: the frozen applied show, plus an extra mono channel on A 21 with A 22 free,
Snare is on A 2 and Kick on A 1 next to it.
"""

from __future__ import annotations

import pytest

from atoo import amend, patch
from atoo.amend import ChangeKind
from atoo.amend import strip_occupancy
from test_amend import applied_plan, horn, occupancy_state

MODELS = ["wing-compact", "wing-full", "wing-rack"]


def _stereo(name: str, model: str = "wing-compact", *, stereo: bool = True, extra=None):
    fields = {"source.stereo": stereo, **(extra or {})}
    change_set = patch.empty_change_set("stereo")
    change_set["modify"] = [{"object": "channel", "name": name, "change": "x", "fields": fields}]
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    plan["channels"].append(horn(30, "Extra", 21))      # mono on A 21; A 22 is free
    desk = strip_occupancy(occupancy_state(plan=plan), plan)
    amendment, merge = patch.plan_patch(plan, patch.validate_change_set(change_set), desk,
                                        console_model=model)
    return amendment, merge


@pytest.mark.parametrize("model", MODELS)
def test_a_mono_channel_on_an_odd_socket_takes_the_next_one(model):
    amendment, merge = _stereo("Extra", model)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    eg = next(c for c in merge.plan["channels"] if c["name"] == "Extra")
    assert eg["source"]["stereo"] is True and eg["patch"]["sockets"] == [21, 22]
    assert any("made stereo on A 21+22" in i for i in merge.infos)
    written = {t.address: t.compute_value("") for t in amend.amendment_targets(amendment).to_write}
    assert written["/io/in/A/21/mode"] == written["/io/in/A/22/mode"] == "ST"
    assert [e.path for e in merge.edits] == ["source.stereo", "patch"]


def test_a_second_socket_another_channel_uses_is_refused_with_the_reason():
    _a, merge = _stereo("Kick")
    [refused] = merge.refused
    assert "A 2, the other half of the pair, is used by channel 'Snare'" in refused.reason


def test_a_channel_on_an_even_socket_cannot_be_half_of_a_pair_and_says_why():
    _a, merge = _stereo("Snare")
    [refused] = merge.refused
    assert "starts on an odd socket" in refused.reason


def test_the_change_may_name_the_pair_itself():
    # A 23+24: free. (A 21 is the extra channel's: moving the Kick onto it
    # would turn that strip's link off too, which the change would have to name.)
    amendment, merge = _stereo("Kick", extra={"patch": {"group": "A", "sockets": [23, 24],
                                                        "stated": True}})
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    kick = next(c for c in merge.plan["channels"] if c["name"] == "Kick")
    assert kick["patch"]["sockets"] == [23, 24] and kick["source"]["stereo"] is True


def test_a_pair_that_cannot_be_formed_is_refused():
    _a, merge = _stereo("Kick", extra={"patch": {"group": "A", "sockets": [21, 23],
                                                 "stated": True}})
    assert merge.refused


@pytest.mark.parametrize("model", MODELS)
def test_a_stereo_channel_made_mono_keeps_its_first_socket(model):
    amendment, merge = _stereo("Keys", model, stereo=False)
    assert not amendment.blocked, [c.line() for c in amendment.blocked]
    keys = next(c for c in merge.plan["channels"] if c["name"] == "Keys")
    assert keys["source"]["stereo"] is False and keys["patch"]["sockets"] == [15]
    assert any("A 16, its other half, is left exactly as the desk has it" in i
               for i in merge.infos)
    written = {t.address: t.compute_value("") for t in amend.amendment_targets(amendment).to_write}
    assert written["/io/in/A/15/mode"] == "M"
