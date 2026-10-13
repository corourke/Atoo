"""A Main or Matrix with no physical socket is a WARNING, not a refusal.

The maintainer, 2026-10-09: *"I'm getting output.nopatch on a Matrix that I will
use as the headphone monitoring source"* -- and it was an ERROR, so apply
refused the whole plan. An unpatched Matrix is a working desk state:
apply still writes its fader, mute, processing and what feeds it, and
skips only the `/io/out/...` routing to a socket. So `output.no-patch` is
a WARNING (CLAUDE.md, "An error of judgement is not an error of
patching"), and the socket is still never guessed.

Every plan here is built in the test; nothing is read from `examples/`.
"""

from __future__ import annotations

import pytest

from atoo.apply import _build_write_targets
from atoo.input_list import InputRow
from atoo.verify_plan import verify_plan

#: The input list the plan was built from, so reconciliation runs too.
ROWS = [InputRow(name="Vox", category="vocals", type="Mic", phantom=False, patch="LCL 1")]


def _plan(fed_by: dict) -> dict:
    """One channel into one bus and Main 1; Main 1 on LCL 1-2; a Matrix
    "Phones" fed from `fed_by`, with a fader, and no patch at all."""
    return {
        "channels": [{
            "channel": 1, "bank": "ch", "name": "Vox",
            "source": {"input": "Vox", "type": "Mic", "stereo": False, "phantom": False},
            "patch": {"group": "LCL", "sockets": [1], "stated": True},
            "processing": {"hpf_hz": None, "preset": None}, "fader": {"fader_db": None, "muted": None},
            "dca": [], "mute_group": [],
            "bus_sends": [{"bus": "Vocals", "mode": "post", "level_db": 0.0}],
            "main_routes": [{"index": 1}],
        }],
        "dcas": {}, "mute_groups": {},
        "busses": {"Vocals": {
            "index": 1, "mono": False,
            "destination": {"type": "main", "index": 1},
            "fader": {"fader_db": None, "muted": None},
        }},
        "outputs": {
            "Main": {"kind": "main", "index": 1,
                     "patch": {"group": "LCL", "sockets": [1, 2]},
                     "fader": {"fader_db": 0.0, "muted": False}},
            "Phones": {"kind": "matrix", "index": 3, "fed_by": fed_by,
                       "fader": {"fader_db": -6.0, "muted": False}},
        },
        "meta": {"console_model": "wing-compact"},
    }


FEEDS = {
    "fed by Main 1": ({"type": "main", "index": 1}, "/main/1/send/MX3"),
    "fed by a bus": ({"type": "bus", "name": "Vocals"}, "/bus/1/send/MX3"),
}


@pytest.mark.parametrize("name", FEEDS)
def test_an_unpatched_matrix_verifies_as_applicable_with_one_warning(name):
    fed_by, _ = FEEDS[name]
    result = verify_plan(_plan(fed_by), ROWS)

    assert result.ok, [f"{f.code}: {f.message}" for f in result.errors]
    assert [(f.code, f.where) for f in result.warnings] == [("output.no-patch", "outputs[Phones]")]
    [warning] = result.warnings
    assert warning.severity == "warning"
    assert "nothing is patched from this output to a physical socket" in warning.message
    assert "apply sets it up (its feed, level and processing)" in warning.message
    assert "phones or monitor source" in warning.message
    assert '"patch"' in warning.fix


@pytest.mark.parametrize("name", FEEDS)
def test_apply_sets_up_an_unpatched_matrix_and_routes_it_nowhere(name):
    fed_by, send = FEEDS[name]
    targets, warnings = _build_write_targets(_plan(fed_by), True)
    addresses = {t.address: t for t in targets}

    # Its level...
    assert addresses["/mtx/3/fdr"].compute_value(None) == -6.0
    assert "/mtx/3/mute" in addresses
    # ...and what feeds it, a send on the source object.
    assert addresses[f"{send}/on"].compute_value(None) == 1
    assert f"{send}/lvl" in addresses
    # No physical socket is written for it: only the Main's LCL 1-2.
    routed = sorted(a for a in addresses if a.startswith("/io/out/"))
    assert routed == ["/io/out/LCL/1/grp", "/io/out/LCL/1/in",
                      "/io/out/LCL/2/grp", "/io/out/LCL/2/in"]
    assert addresses["/io/out/LCL/1/grp"].compute_value(None) == "MAIN"
    assert not any("Phones" in w for w in warnings), warnings


def test_an_unpatched_main_is_a_warning_too():
    """A Main with no socket and no Matrix carrying it out may be a
    mistake -- but the desk still works, so it is said, not refused."""
    # Fed from the bus, not Main 1: a patched Matrix fed from this Main
    # would carry it to a socket, and that is not this case.
    plan = _plan({"type": "bus", "name": "Vocals"})
    plan["outputs"]["Phones"]["patch"] = {"group": "LCL", "sockets": [3]}
    del plan["outputs"]["Main"]["patch"]
    result = verify_plan(plan, ROWS)

    assert result.ok
    [warning] = [f for f in result.warnings if f.code == "output.no-patch"]
    assert warning.where == "outputs[Main]"
    assert "nothing is patched from this output to a physical socket" in warning.message
    # The Matrix sentence is for a Matrix only.
    assert "phones or monitor source" not in warning.message
