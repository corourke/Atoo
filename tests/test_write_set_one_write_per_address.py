"""One write per address across the whole write set, outputs included.

`_dedupe_by_address` used to run before the `outputs` loop appended every
Main/Matrix target, so a socket claimed by both a bus's dedicated output
and an `outputs` entry (reachable with `--skip-verify`) was written twice
with no warning. Plans come from `tests/fixtures/`.
"""

from __future__ import annotations

from collections import Counter

from atoo.apply import _build_write_targets
from tests.test_apply import compiled


def test_a_socket_claimed_by_a_bus_and_an_output_is_written_once_and_warned():
    plan = compiled("smallband")
    plan["meta"] = {"console_model": "wing-compact"}
    # The Matrix is patched onto the drum wedge's LCL 3-4 as well.
    plan["outputs"]["Matrix"]["socket"] = {"group": "LCL", "sockets": [3, 4]}
    plan["outputs"]["Matrix"]["sockets"] = [{"group": "LCL", "sockets": [3, 4]}]

    targets, warnings = _build_write_targets(plan, set_fader_levels=True)

    counts = Counter(t.address for t in targets)
    assert counts["/io/out/LCL/3/grp"] == 1
    assert counts["/io/out/LCL/3/in"] == 1
    assert not [a for a, n in counts.items() if n > 1]
    assert any(w.startswith("/io/out/LCL/3/grp: two writes disagree") for w in warnings)
