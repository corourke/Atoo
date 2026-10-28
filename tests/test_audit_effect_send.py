"""R014 (Signal Split Through An Effect Send), an earlier change.

A WING has no send/return path to an effect: a reverb is a bus that
inserts it, fully wet, routed to Main. A strip on Main 1 directly and
through that bus is the dry signal beside the effect's return, not two dry
copies, so R012 stands down for it with no plan and R014 says so at INFO.

The hand-built desks reuse `test_audit_signal_split`'s builders; the church
desk is `tests/fixtures/church-full-fx.state.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo import console_facts, fx_engines
from atoo.audit import DEFAULT_RULES, ConsoleState, effect_send_inserts, run_audit
from atoo.diagnostics import Severity
from tests.test_audit_signal_split import _bus, _main, _split, _state, _strip


def _fx_bus(index, name, model, *, slot=4, on=1, point="preins", mains=(1,)):
    v = _bus(index, name, mains=mains)
    v[f"/bus/{index}/{point}/on"] = on
    v[f"/bus/{index}/{point}/ins"] = f"FX{slot}"
    v[f"/fx/{slot}/mdl"] = model
    return v


def _verb_desk(model="VSS3", **fx):
    """Kick on Main 1 directly and through bus 11, which inserts `model`."""
    return _state(_main(1), _fx_bus(11, "Reverb", model, **fx),
                  _strip("/ch/1", "Kick", main1=1, bus11=1))


# -- the classification -------------------------------------------------------


def test_every_effect_send_model_is_one_the_desk_offers():
    offered = set(fx_engines.all_models())
    assert set(console_facts.EFFECT_SEND_MODELS) <= offered
    assert not {"DOUBLE", "ROTARY", "TAPE", "EXT", "NONE"} & set(console_facts.EFFECT_SEND_MODELS)


def test_the_rule_row_is_an_info():
    rule = next(r for r in DEFAULT_RULES if r.id == "R014")
    assert (rule.severity, rule.title) == (Severity.INFO, "Signal Split Through An Effect Send")


# -- a reverb bus beside the dry signal -----------------------------------------


def test_a_reverb_bus_is_read_as_an_effect_send_with_no_plan():
    state = _verb_desk()
    assert _split(state) == []
    [note] = _split(state, "R014")
    assert note.severity is Severity.INFO
    assert note.message.startswith(
        'CH 1 "Kick" reaches MAIN 1 through BUS 11 "Reverb" as well as by another route. '
        'Read as an effect send: BUS 11 "Reverb" runs VSS3 in FX4 (a reverb)')
    assert "/fx/4/mdl" in note.addresses and "/bus/11/preins/ins" in note.addresses


def test_delay_modulation_and_pitch_count_too():
    for model in ("TAP-DL", "DIMCRS", "PITCH"):
        assert _split(_verb_desk(model)) == [], model
        assert len(_split(_verb_desk(model), "R014")) == 1, model


def test_a_post_insert_counts_as_a_pre_insert_does():
    assert _split(_verb_desk(point="postins")) == []


# -- what is not an effect send ------------------------------------------------


def test_a_doubler_is_not_an_effect_send():
    """DOUBLE blends a doubled copy with the dry voice: the bus still
    carries a dry copy, so the split is R012's."""
    state = _verb_desk("DOUBLE")
    assert len(_split(state)) == 1
    assert _split(state, "R014") == []


def test_a_compressor_bus_is_parallel_compression_not_an_effect_send():
    assert len(_split(_verb_desk("C5-CMB"))) == 1


def test_an_effect_inserted_but_switched_off_is_no_effect_send():
    assert len(_split(_verb_desk(on=0))) == 1


def test_an_insert_naming_an_empty_slot_is_no_effect_send():
    assert len(_split(_verb_desk("NONE"))) == 1


def test_a_bus_whose_slot_was_not_read_is_not_guessed():
    values = dict(_verb_desk().values)
    del values["/fx/4/mdl"]
    state = ConsoleState(values, console_model="wing-compact")
    assert effect_send_inserts(state, "bus:11") == []
    assert len(_split(state)) == 1


# -- two dry copies and a reverb -------------------------------------------------


def test_two_dry_routes_still_warn_and_say_which_route_was_left_out():
    state = _state(_main(1), _bus(1, "Drums", mains=(1,)), _bus(2, "Drums Comp", mains=(1,)),
                   _fx_bus(11, "Reverb", "BPLATE"),
                   _strip("/ch/1", "Kick", bus1=1, bus2=1, bus11=1))
    [warning] = _split(state)
    assert warning.message.startswith(
        'CH 1 "Kick" reaches MAIN 1 twice: through BUS 1 "Drums", and through BUS 2 "Drums Comp".')
    assert ('Its route through BUS 11 "Reverb" is read as an effect send and left out: '
            "it runs BPLATE in FX4 (a reverb).") in warning.message
    assert _split(state, "R014") == []


# -- a plan still decides first ---------------------------------------------------


def _verb_plan(*, main_route=True):
    return {"channels": [{"channel": 1, "bank": "ch", "name": "Kick",
                          "bus_sends": [{"bus": "Reverb", "level_db": 0.0}],
                          "main_routes": [{"index": 1}] if main_route else []}],
            "busses": {"Reverb": {"index": 11, "destinations": [{"type": "main", "index": 1}]}},
            "outputs": {}}


def test_a_plan_that_states_every_leg_is_r013_and_not_r014():
    state = _verb_desk()
    assert _split(state, "R013", plan=_verb_plan())
    assert _split(state, "R014", plan=_verb_plan()) == []
    assert _split(state, plan=_verb_plan()) == []


def test_a_plan_that_leaves_a_leg_out_still_reads_the_effect_send():
    state = _verb_desk()
    assert _split(state, plan=_verb_plan(main_route=False)) == []
    assert len(_split(state, "R014", plan=_verb_plan(main_route=False))) == 1


# -- the church desk ----------------------------------------------------------------

_CHURCH = Path(__file__).parent / "fixtures" / "church-full-fx.state.json"


def _church_findings():
    state = ConsoleState(json.loads(_CHURCH.read_text(encoding="utf-8")),
                         console_model="wing-full")
    return [f for f in run_audit(state, DEFAULT_RULES) if f.rule_id in ("R012", "R014")]


def test_the_church_desks_effect_buses_are_read_as_effect_sends():
    """Buses 11-14 and 16 carry a reverb, chorus or delay inserted on them;
    every split through them alone is R014, one per bus."""
    notes = [f for f in _church_findings() if f.rule_id == "R014"]
    heads = [f.message.split(" as well as")[0].rsplit(" through ", 1)[1] for f in notes]
    assert heads == ['BUS 11 "Reverb"', 'BUS 12 "CHORUS"', 'BUS 13 "Delay Long"',
                     'BUS 14 "Delay Short"', 'BUS 16 "InstReverb"']
    assert 'BUS 11 "Reverb" runs BPLATE in FX4 (a reverb) and VSS3 in FX1 (a reverb)' in (
        notes[0].message)


def test_the_church_desks_parallel_drum_bus_still_warns():
    """Drums and Drums Comp are two dry copies (parallel compression, no
    effect on either): R012 still says so, for every drum channel."""
    warnings = [f for f in _church_findings() if f.rule_id == "R012"]
    assert len(warnings) == 9
    assert all('through BUS 1 "Drums", and through BUS 2 "Drums Comp"' in f.message
               for f in warnings)
    assert not any("twice: through BUS 11" in f.message for f in warnings)
