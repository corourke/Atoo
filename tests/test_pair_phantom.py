"""A stereo channel has one 48V value for its pair.

Phantom lives on each physical SOCKET, and a stereo channel is patched to
two -- but the desk switches the two together (writing the first reads the
second back already on). So Build states one value for the pair, in
`source.phantom` and `source.pair_phantom` alike: on if EITHER input-list
row wants it, said at INFO naming the row that asked. A passive ribbon on
either side is refused. Where a plan states one value for a pair it is
read as both sockets' and announced at INFO (`inferred.pair-phantom`); one
that states two different values (an older build) is read as on if either
is, and verify reports it. Build, apply, verify and the audit all read it
through `inferred.socket_phantom`, so they cannot disagree.

Every plan and input list here is built in the test (nothing
reads `examples/`).
"""

from __future__ import annotations

import json

import pytest

from atoo import generate, inferred
from atoo.ai_provider import FakeProvider
from atoo.apply import _build_write_targets
from atoo.input_list import InputRow
from atoo.verify_plan import verify_plan


def _channel(*, phantom=True, pair_phantom=None, stereo=True, sockets=(5, 6),
             model=None, pair_input="OH R") -> dict:
    source = {"input": "OH L", "type": "Mic", "model": model, "stereo": stereo,
              "phantom": phantom}
    if stereo and pair_input:
        source["pair_input"] = pair_input
    if pair_phantom is not None:
        source["pair_phantom"] = pair_phantom
    return {
        "channel": 5, "bank": "ch", "name": "OH", "color": None, "source": source,
        "patch": {"group": "A", "sockets": list(sockets), "stated": True},
        "processing": {}, "fader": {}, "dca": [], "mute_group": [], "bus_sends": [],
        "main_routes": [],
    }


def _plan(*channels) -> dict:
    return {"channels": list(channels), "dcas": {}, "mute_groups": {}, "busses": {},
            "outputs": {}, "meta": {"console_model": "wing-compact"}}


def _vph_values(plan: dict) -> dict[str, int]:
    targets, _warnings = _build_write_targets(plan, set_fader_levels=False)
    return {t.address: _value(t) for t in targets if t.address.endswith("/vph")}


def _value(target):
    """A `WriteTarget`'s intended value (its `compute_value` ignores the
    current value for a constant)."""
    return target.compute_value(None)


# --------------------------------------------------------------------------
# The reading itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("phantom,pair,expected", [
    (True, True, [(5, True), (6, True)]),
    (True, False, [(5, True), (6, True)]),     # a condenser and a dynamic: on for both
    (False, True, [(5, True), (6, True)]),
    (True, None, [(5, True), (6, True)]),      # one value for the pair
    (False, None, [(5, False), (6, False)]),
    (False, False, [(5, False), (6, False)]),
])
def test_a_pair_has_one_value_on_if_either_socket_wants_it(phantom, pair, expected):
    assert inferred.socket_phantom(_channel(phantom=phantom, pair_phantom=pair)) == expected


def test_the_stated_values_are_kept_so_a_disagreement_can_be_reported():
    channel = _channel(phantom=True, pair_phantom=False)
    assert inferred.stated_socket_phantom(channel) == [(5, True), (6, False)]
    assert inferred.pair_phantom_differs(channel)
    assert not inferred.pair_phantom_differs(_channel(phantom=True, pair_phantom=True))
    assert not inferred.pair_phantom_differs(_channel(phantom=True, pair_phantom=None))
    assert not inferred.pair_phantom_differs(_channel(stereo=False, sockets=(3,), pair_input=None))


def test_a_mono_channel_has_one_socket_and_an_unpatched_one_none():
    mono = _channel(stereo=False, sockets=(3,), pair_input=None)
    assert inferred.socket_phantom(mono) == [(3, True)]
    unpatched = dict(_channel(), patch=None)
    assert inferred.socket_phantom(unpatched) == []


# --------------------------------------------------------------------------
# apply (and so readback, which reads back exactly what apply wrote)
# --------------------------------------------------------------------------


def test_apply_writes_phantom_on_both_sockets_of_a_condenser_pair():
    assert _vph_values(_plan(_channel(pair_phantom=True))) == {
        "/io/in/A/5/vph": 1, "/io/in/A/6/vph": 1}


@pytest.mark.parametrize("phantom,pair", [(True, False), (False, True)])
def test_apply_writes_the_same_value_to_both_sockets_of_a_pair(phantom, pair):
    """A plan on disk that states two values (an older build): the desk
    holds one for the pair, so both sockets are written on."""
    assert _vph_values(_plan(_channel(phantom=phantom, pair_phantom=pair))) == {
        "/io/in/A/5/vph": 1, "/io/in/A/6/vph": 1}


def test_one_value_for_a_pair_is_written_on_both_and_says_so():
    plan = _plan(_channel(pair_phantom=None))
    targets, _warnings = _build_write_targets(plan, set_fader_levels=False)
    vph = {t.address: t for t in targets if t.address.endswith("/vph")}
    assert {a: _value(t) for a, t in vph.items()} == {"/io/in/A/5/vph": 1, "/io/in/A/6/vph": 1}
    assert "read as both sockets" in vph["/io/in/A/6/vph"].description
    assert "read as both" not in vph["/io/in/A/5/vph"].description


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------


def _codes(plan, rows=()):
    return [f.code for f in verify_plan(plan, rows=list(rows)).findings]


def test_one_value_putting_48v_on_a_pair_is_announced_at_info():
    found = [d for d in inferred.inferred_diagnostics(_plan(_channel(pair_phantom=None)))
             if d.code == inferred.CODE_PAIR_PHANTOM]
    assert len(found) == 1 and found[0].severity.value == "info"
    assert "OH" in found[0].message
    assert inferred.CODE_PAIR_PHANTOM in _codes(_plan(_channel(pair_phantom=None)))


@pytest.mark.parametrize("phantom,pair", [(True, True), (False, False), (False, None)])
def test_nothing_is_announced_when_nothing_was_chosen(phantom, pair):
    """Two stated values alike, or one that leaves the pair off -- which is
    what the reset before a full apply leaves on the second socket anyway."""
    diags = inferred.inferred_diagnostics(_plan(_channel(phantom=phantom, pair_phantom=pair)))
    assert inferred.CODE_PAIR_PHANTOM not in [d.code for d in diags]


def _ribbon_findings(plan, rows):
    return [f for f in verify_plan(plan, rows=list(rows)).findings
            if f.code == "safety.phantom-on-passive-ribbon"]


@pytest.mark.parametrize("ribbon_first", [False, True])
def test_48v_on_a_passive_ribbon_on_either_side_of_a_pair_is_refused(ribbon_first):
    """The pair has one 48V value, so the ribbon meets it whichever socket
    it is on, and whichever row asked for it. The finding names the ribbon's
    row and says how to mend it."""
    condenser = InputRow(name="OH L", category="drums", type="Mic", phantom=True, model="KSM137")
    ribbon = InputRow(name="OH R", category="drums", type="Mic", phantom=False,
                      model="Royer R-121")
    rows = [ribbon, condenser] if ribbon_first else [condenser, ribbon]
    channel = _channel(phantom=True, pair_phantom=True)
    channel["source"].update(input=rows[0].name, pair_input=rows[1].name)
    [finding] = _ribbon_findings(_plan(channel), rows)
    assert finding.severity.value == "error"
    assert "Royer R-121" in finding.message and "OH R" in finding.message
    assert "together" in finding.message
    assert "Split the pair into two mono channels" in finding.message


def test_a_ribbon_in_a_pair_nobody_powers_is_not_refused():
    rows = [InputRow(name="OH L", category="drums", type="Mic", phantom=False, model="KSM137"),
            InputRow(name="OH R", category="drums", type="Mic", phantom=False,
                     model="Royer R-121")]
    assert _ribbon_findings(_plan(_channel(phantom=False, pair_phantom=False)), rows) == []


def test_a_plan_with_the_pair_on_the_ribbon_off_and_the_other_row_on_is_refused_too():
    """An older build stating 48V off on the ribbon's socket and on for the
    other: the desk would put it on both, so the ribbon is refused."""
    rows = [InputRow(name="OH L", category="drums", type="Mic", phantom=False,
                     model="Royer R-121"),
            InputRow(name="OH R", category="drums", type="Mic", phantom=True, model="KSM137")]
    assert len(_ribbon_findings(_plan(_channel(phantom=False, pair_phantom=True)), rows)) == 1


def test_a_mono_ribbon_is_refused_as_before():
    row = InputRow(name="OH L", category="drums", type="Mic", phantom=True, model="Royer R-121")
    channel = _channel(stereo=False, sockets=(3,), pair_input=None)
    [finding] = _ribbon_findings(_plan(channel), [row])
    assert "together" not in finding.message


def test_a_pair_stating_two_values_is_reported_with_the_fix():
    found = [f for f in verify_plan(_plan(_channel(phantom=True, pair_phantom=False))).findings
             if f.code == "phantom.pair-differs"]
    assert len(found) == 1 and found[0].severity.value == "warning"
    assert "48V on for socket 5 and off for socket 6" in found[0].message
    assert "split the pair into two mono channels" in found[0].message
    for state in (dict(phantom=True, pair_phantom=True), dict(phantom=True, pair_phantom=None),
                  dict(phantom=False, pair_phantom=False)):
        assert "phantom.pair-differs" not in _codes(_plan(_channel(**state)))


# --------------------------------------------------------------------------
# build: the second row's phantom reaches the plan
# --------------------------------------------------------------------------


ROWS_CSV = ("patch,name,category,type,model,phantom,notes\n"
            "AES50-A 5,OH L,drums,Mic,KSM137,TRUE,\n"
            "AES50-A 6,OH R,drums,Mic,SM57,FALSE,\n")


def _build(rows_csv):
    reply = {"channels": [{"input": "OH L", "pair": "OH R", "name": "OH"}],
             "dcas": [], "mute_groups": [], "busses": [],
             "outputs": [{"name": "Main", "kind": "main",
                          "patch": {"group": "LCL", "sockets": [7, 8]}}],
             "unassigned_inputs": [], "notes": []}
    findings: list = []
    plan = generate.generate_plan("conventions", rows_csv,
                                  provider=FakeProvider(response=json.dumps(reply)),
                                  console_model="wing-compact", findings=findings)
    [oh] = [c for c in plan["channels"] if c["name"] == "OH"]
    return plan, oh, [f for f in findings if f.code == "reply.pair-phantom"]


@pytest.mark.parametrize("first,second,asked,other", [
    ("TRUE", "FALSE", "OH L", "OH R"),     # a condenser and a dynamic
    ("FALSE", "TRUE", "OH R", "OH L"),
])
def test_build_gives_the_pair_one_value_on_if_either_row_wants_it(first, second, asked, other):
    csv = ROWS_CSV.replace("KSM137,TRUE", f"KSM137,{first}").replace("SM57,FALSE", f"SM57,{second}")
    plan, oh, [info] = _build(csv)
    assert oh["source"]["phantom"] is True and oh["source"]["pair_phantom"] is True
    assert _vph_values(plan) == {"/io/in/A/5/vph": 1, "/io/in/A/6/vph": 1}
    assert info.severity.value == "info"
    assert f"{asked!r} asks for it and {other!r} does not" in info.message
    assert f"split the pair into two mono channels if you want {other!r} without 48V" in info.message
    assert "phantom.pair-differs" not in [f.code for f in verify_plan(plan).findings]


@pytest.mark.parametrize("value", ["TRUE", "FALSE"])
def test_build_says_nothing_when_the_pairs_rows_agree(value):
    csv = ROWS_CSV.replace("KSM137,TRUE", f"KSM137,{value}").replace("SM57,FALSE", f"SM57,{value}")
    plan, oh, infos = _build(csv)
    assert infos == []
    assert oh["source"]["phantom"] is oh["source"]["pair_phantom"] is (value == "TRUE")


def test_build_refuses_a_ribbon_on_either_side_of_a_powered_pair():
    csv = ROWS_CSV.replace("SM57,FALSE", "Royer R-121,FALSE")
    plan, _oh, _infos = _build(csv)
    errors = [f for f in verify_plan(plan, rows=[
        InputRow(name="OH L", category="drums", type="Mic", phantom=True, model="KSM137"),
        InputRow(name="OH R", category="drums", type="Mic", phantom=False,
                 model="Royer R-121")]).findings
        if f.code == "safety.phantom-on-passive-ribbon"]
    assert len(errors) == 1 and "OH R" in errors[0].message


# --------------------------------------------------------------------------
# amend and patch: the same targets, scoped to the new strip
# --------------------------------------------------------------------------


def test_an_amend_adding_a_condenser_pair_writes_phantom_on_both_sockets():
    """`amend` and `patch` build their writes with apply's own
    `_build_write_targets` over the effective plan and keep the ones the
    new strip owns -- so a stereo pair added mid-show gets 48V on both of
    its sockets, and the scope lets the second one through."""
    from test_amend import amended_plan, applied_plan, horn, occupancy
    from atoo.amend import amendment_targets, plan_amendment

    plan = amended_plan()
    pair = horn(24, "Room", 25)
    pair["source"].update(stereo=True, phantom=True, pair_input="Room R", pair_phantom=True)
    pair["patch"]["sockets"] = [25, 26]
    plan["channels"].append(pair)
    amendment = plan_amendment(applied_plan(), plan, occupancy())
    assert not amendment.blocked
    written = {t.address: _value(t) for t in amendment_targets(amendment).to_write
               if t.address.endswith("/vph")}
    assert written["/io/in/A/25/vph"] == 1 and written["/io/in/A/26/vph"] == 1
