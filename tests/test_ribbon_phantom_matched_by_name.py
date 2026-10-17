"""The 48V-on-a-ribbon check finds its input-list row the way
reconciliation does.

`_check_reconciliation` matches a channel to its row by `source.input`,
falling back to the channel's `name`; `_check_safety` matched by
`source.input` only. A channel with `source.input: null` then reconciled
cleanly against the `Ribbon` row while the safety check found no row, no
model, and let phantom through to a Royer.
"""

from __future__ import annotations

from atoo.input_list import InputRow
from atoo.verify_plan import verify_plan


def _plan(source_input) -> dict:
    return {
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Ribbon",
            "source": {"input": source_input, "type": "Mic", "model": None,
                       "stereo": False, "phantom": True},
            "patch": {"group": "A", "sockets": [1], "stated": False},
            "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
        }],
        "dcas": {}, "mute_groups": {}, "busses": {}, "outputs": {},
        "meta": {"console_model": "wing-compact"},
    }


ROWS = [InputRow(name="Ribbon", category="guitars", type="Mic", phantom=False,
                 model="Royer R-121")]


def _ribbon_errors(plan):
    result = verify_plan(plan, rows=ROWS)
    return [f for f in result.findings if f.code == "safety.phantom-on-passive-ribbon"]


def test_phantom_on_a_ribbon_is_refused_when_source_input_is_null():
    found = _ribbon_errors(_plan(None))
    assert len(found) == 1
    assert "Royer R-121" in found[0].message


def test_phantom_on_a_ribbon_is_still_refused_by_source_input():
    assert len(_ribbon_errors(_plan("Ribbon"))) == 1
