"""An earlier change (apply puts 48V on only the first socket of a stereo pair,
so the second condenser is silent).

Phantom lives on each physical SOCKET. A stereo channel is patched to two,
and each answers to its own input-list row: the plan records the second
row's value as `source.pair_phantom`. Where a plan states one value for a
pair, it is read as both sockets' and announced at INFO
(`inferred.pair-phantom`). Build, apply, verify and amend/patch all read
it through `inferred.socket_phantom`, so they cannot disagree.

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
    (True, False, [(5, True), (6, False)]),    # a condenser and a dynamic
    (False, True, [(5, False), (6, True)]),
    (True, None, [(5, True), (6, True)]),      # one value for the pair
    (False, None, [(5, False), (6, False)]),
])
def test_each_socket_takes_its_own_rows_phantom(phantom, pair, expected):
    assert inferred.socket_phantom(_channel(phantom=phantom, pair_phantom=pair)) == expected


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


def test_apply_writes_each_socket_what_its_own_row_says():
    assert _vph_values(_plan(_channel(phantom=True, pair_phantom=False))) == {
        "/io/in/A/5/vph": 1, "/io/in/A/6/vph": 0}
    assert _vph_values(_plan(_channel(phantom=False, pair_phantom=True))) == {
        "/io/in/A/5/vph": 0, "/io/in/A/6/vph": 1}


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


@pytest.mark.parametrize("phantom,pair", [(True, True), (True, False), (False, None)])
def test_nothing_is_announced_when_nothing_was_chosen(phantom, pair):
    """Two stated values, or one that leaves the pair off -- which is what
    the reset before a full apply leaves on the second socket anyway."""
    diags = inferred.inferred_diagnostics(_plan(_channel(phantom=phantom, pair_phantom=pair)))
    assert inferred.CODE_PAIR_PHANTOM not in [d.code for d in diags]


def test_48v_on_a_passive_ribbon_on_the_second_socket_is_refused():
    rows = [InputRow(name="OH L", category="drums", type="Mic", phantom=True, model="KSM137"),
            InputRow(name="OH R", category="drums", type="Mic", phantom=True,
                     model="Royer R-121")]
    assert "safety.phantom-on-passive-ribbon" in _codes(
        _plan(_channel(pair_phantom=True)), rows)
    assert "safety.phantom-on-passive-ribbon" not in _codes(
        _plan(_channel(pair_phantom=False)), rows)


# --------------------------------------------------------------------------
# build: the second row's phantom reaches the plan
# --------------------------------------------------------------------------


ROWS_CSV = ("patch,name,category,type,model,phantom,notes\n"
            "AES50-A 5,OH L,drums,Mic,KSM137,TRUE,\n"
            "AES50-A 6,OH R,drums,Mic,SM57,FALSE,\n")


def test_build_records_the_pair_rows_own_phantom():
    reply = {"channels": [{"input": "OH L", "pair": "OH R", "name": "OH"}],
             "dcas": [], "mute_groups": [], "busses": [],
             "outputs": [{"name": "Main", "kind": "main",
                          "patch": {"group": "LCL", "sockets": [7, 8]}}],
             "unassigned_inputs": [], "notes": []}
    plan = generate.generate_plan("conventions", ROWS_CSV,
                                  provider=FakeProvider(response=json.dumps(reply)),
                                  console_model="wing-compact")
    [oh] = [c for c in plan["channels"] if c["name"] == "OH"]
    assert oh["source"]["phantom"] is True and oh["source"]["pair_phantom"] is False
    assert _vph_values(plan)["/io/in/A/6/vph"] == 0
    assert _vph_values(plan)["/io/in/A/5/vph"] == 1


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
