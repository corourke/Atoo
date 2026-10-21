"""The reset's own read takes the capture's values from node dumps, which
print the desk's display-rounded text. A float the reset will write is read
exactly for the journal that Undo restores from. (The reset's "already
initialized" verdict stays on the dump's text, by decision: a value edited by
less than the readout's rounding may be left as it is.)

Every assertion runs on the Compact and Full fakes (the models with a capture;
the Rack has none, so it has no reset), over a desk whose dump prints three
significant digits while a single read gives the exact value.
"""

from __future__ import annotations

import io
import json

import pytest

from atoo import initialize as init
from atoo.apply import apply_plan
from atoo.progress import Phases
from atoo.undo import load_journal, undo_from_journal
from tests.test_combined_preview_read import CAPTURED, RoundingDesk, _wired
from tests.test_full_apply import tiny


def _edge_values(model):
    """The capture's own values, with every float 1.5 to 2.5 percent off its
    value (either side of the edge of `_values_equal`'s 2% tolerance)."""
    capture = init.load_capture(model)
    values = {leaf.address: leaf.value for leaf in capture.leaves}
    for n, leaf in enumerate(capture.leaves):
        v = leaf.value
        if (leaf.value_type == "f" and isinstance(v, float) and abs(v) >= 1 and v > -100
                and init.skip_rule(leaf.address) is None):
            # Either side of the edge (2.04%), none exactly on it: a single read is a
            # 32-bit float, so a value exactly on the edge is not a fair test.
            off = (0.0150, 0.0185, 0.0199, 0.0203, 0.0206, 0.0212, 0.0225, 0.0245)[n % 8]
            values[leaf.address] = v * (1 + off * (1 if n % 2 else -1))
    return values


def _preview(model, window=8, **kw):
    with _wired(RoundingDesk(_edge_values(model)), window=window, **kw) as (console, udp):
        return apply_plan(tiny(("ch", 1, "Kick")), console, dry_run=True, full_apply=True,
                          initialize=True, init_model=model), udp


@pytest.mark.parametrize("model", CAPTURED)
def test_the_reset_line_says_what_was_read_exactly(model):
    result, _ = _preview(model)
    [line] = [w for w in result.warnings if w.startswith("INFO reset to initialized")]
    assert "read exactly for the journal" in line


@pytest.mark.parametrize("model", CAPTURED)
def test_the_reset_is_one_phase_for_the_read_and_one_for_the_exact_priors(model):
    stream = io.StringIO()
    phases = Phases(stream=stream, isatty=False, timeout=0.5, window=8)
    with _wired(RoundingDesk(_edge_values(model)), window=8) as (console, _udp):
        apply_plan(tiny(("ch", 1, "Kick")), console, dry_run=True, full_apply=True,
                   initialize=True, init_model=model, phases=phases)
    lines = [l for l in stream.getvalue().splitlines() if l.startswith("  reading the")]
    assert sum(l.startswith(f"  {init.COMBINED_READ_PHASE}: ") for l in lines) == 1
    assert sum(l.startswith(f"  {init.EXACT_PHASE}: ") for l in lines) == 1


@pytest.mark.parametrize("model", CAPTURED)
def test_a_reset_write_is_journalled_with_the_exact_value_and_undo_restores_it(model, tmp_path):
    values = _edge_values(model)
    desk = RoundingDesk(values)
    journal = tmp_path / "apply.json"
    with _wired(desk, window=8) as (console, _udp):
        apply_plan(tiny(("ch", 1, "Kick")), console, dry_run=False, journal_path=str(journal),
                   full_apply=True, initialize=True, init_model=model)
        rows = {w["address"]: w for w in json.loads(journal.read_text())["writes"]
                if w["description"].startswith(init.DESCRIPTION)}
        floats = [a for a, row in rows.items()
                  if isinstance(row.get("prior_value"), float) and isinstance(values[a], float)]
        assert floats
        for address in floats:
            assert rows[address]["prior_value"] == pytest.approx(values[address], rel=1e-6), address
        undo_from_journal(load_journal(str(journal)), console, dry_run=False)
    for address in floats:
        assert desk.values[address] == pytest.approx(values[address], rel=1e-6), address
