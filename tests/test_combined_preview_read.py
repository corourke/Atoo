"""A preview reads the desk once: the reset's addresses and the plan's own,
in one pass, under one progress phase.

The reset's read and the preview's baseline read used to run one after the
other, as two phases ("reading the desk for the reset", then "for the
preview"). With a window of requests in flight, the plan's baselines ride in
the reset's read: each address is asked once, the progress line is one
phase, and the preview says what the two reads said before. A real run, a
run with the reset off and a console with no capture read as they did.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from atoo import apply as apply_module
from atoo import audit
from atoo import console as osc
from atoo import initialize as init
from atoo.apply import apply_plan
from atoo.progress import Phases
from tests.snap_desk import SnapDesk
from tests.test_full_apply import tiny
from tests.test_pipelined_reads import _wired

CHANGES = {"/ch/30/fdr": -6.0, "/ch/30/name": "Old show", "/bus/3/mute": 1}

# The same assertions run against every WING model. The Rack has no initialized
# capture, so its fake desk is the Compact's initialized values: the request
# pattern is what is under test there, not the Rack's own settings.
MODELS = ["wing-compact", "wing-full", "wing-rack"]
CAPTURED = [m for m in MODELS if init.load_capture(m) is not None]


def _desk_for(model, changes=None) -> SnapDesk:
    capture = init.load_capture(model) or init.load_capture("wing-compact")
    values = {leaf.address: leaf.value for leaf in capture.leaves}
    values.update(CHANGES if changes is None else changes)
    return SnapDesk(values)


def _plan():
    return tiny(("ch", 1, "Kick"), ("ch", 2, "Snare"))


def _preview(window, *, model="wing-compact", initialize=True, desk=None, **network):
    stream = io.StringIO()
    phases = Phases(stream=stream, isatty=False, timeout=0.5, window=window)
    with _wired(desk or _desk_for(model), window=window, **network) as (console, udp):
        result = apply_plan(_plan(), console, dry_run=True, full_apply=True,
                            initialize=initialize, init_model=model, phases=phases)
    return result, udp, stream.getvalue()


def _phase_lines(text: str, label: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"  {label}: ")]


@pytest.mark.parametrize("model", CAPTURED)
def test_the_preview_is_one_read_under_one_phase(model):
    _result, _udp, text = _preview(8, model=model)
    assert len(_phase_lines(text, init.COMBINED_READ_PHASE)) == 1
    assert _phase_lines(text, init.READ_PHASE) == []
    assert _phase_lines(text, apply_module.PREVIEW_PHASE) == []


def test_the_models_without_a_capture_are_still_one_read_under_one_phase_with_the_warning():
    """Today that is the Rack: no reset, so the one read is the preview's own."""
    assert "wing-rack" not in CAPTURED
    result, _udp, text = _preview(8, model="wing-rack")
    assert len(_phase_lines(text, apply_module.PREVIEW_PHASE)) == 1
    assert _phase_lines(text, init.COMBINED_READ_PHASE) == []
    assert _phase_lines(text, init.READ_PHASE) == []
    assert init.no_capture_warning("wing-rack") in result.warnings


@pytest.mark.parametrize("model", MODELS)
def test_no_address_is_asked_twice(model):
    _result, udp, _text = _preview(8, model=model, latency=0.001, jitter=0.002)
    asked = udp.requests
    assert len(asked) == len(set(asked))


@pytest.mark.parametrize("model", CAPTURED)
def test_every_plan_address_the_desk_answers_is_read_in_the_one_pass(model):
    """No plan address is left for the loop to ask: nothing runs under a second phase."""
    result, _udp, text = _preview(8, model=model)
    assert _phase_lines(text, apply_module.PREVIEW_PHASE) == []
    assert all(r.status != "unreadable" for r in result.writes)


@pytest.mark.parametrize("model", MODELS)
def test_it_says_the_same_as_the_two_reads_did(model):
    serial, _udp, _ = _preview(1, model=model)
    combined, _udp, _ = _preview(8, model=model, latency=0.001, jitter=0.003)

    def rows(result):
        return [(r.address, r.status, r.intended_value, r.forced_by) for r in result.writes]

    assert rows(combined) == rows(serial)
    # A float the desk prints as text in a dump is the same number to its
    # printed digits (`_values_equal`'s own tolerance), not the same bits.
    for a, b in zip(combined.writes, serial.writes):
        if isinstance(a.prior_value, float):
            assert apply_module._values_equal("f", a.prior_value, b.prior_value, a.address)
        else:
            assert a.prior_value == b.prior_value
    assert sum(r.would_change for r in combined.writes) == sum(r.would_change for r in serial.writes)


@pytest.mark.parametrize("model", CAPTURED)
def test_the_result_line_says_what_was_read_in_total(model):
    result, _udp, _ = _preview(8, model=model)
    [line] = [w for w in result.warnings if w.startswith("INFO reset to initialized")]
    assert "the plan's own settings: " in line and "from the node dumps" in line


@pytest.mark.parametrize("model", CAPTURED)
def test_a_plan_address_the_desk_does_not_answer_is_still_unreadable(model):
    silent = {"/ch/1/name"}
    result, _udp, _ = _preview(8, model=model, silent=silent, timeout=0.2)
    [record] = [r for r in result.writes if r.address == "/ch/1/name"]
    assert record.status == "unreadable"


@pytest.mark.parametrize("model", MODELS)
def test_with_the_reset_off_it_is_one_read_under_the_preview_phase(model):
    _result, _udp, text = _preview(8, model=model, initialize=False)
    assert len(_phase_lines(text, apply_module.PREVIEW_PHASE)) == 1
    assert _phase_lines(text, init.COMBINED_READ_PHASE) == []


@pytest.mark.parametrize("model", CAPTURED)
def test_a_real_run_keeps_its_reset_read_and_asks_no_combined_phase(model):
    stream = io.StringIO()
    phases = Phases(stream=stream, isatty=False, timeout=0.5, window=8)
    with _wired(_desk_for(model), window=8) as (console, udp):
        result = apply_plan(_plan(), console, dry_run=False, full_apply=True,
                            initialize=True, init_model=model, phases=phases)
    assert not result.aborted
    text = stream.getvalue()
    assert len(_phase_lines(text, init.READ_PHASE)) == 1
    assert _phase_lines(text, init.COMBINED_READ_PHASE) == []


# -- the dump's value is the single read's value, for every address it covers --

PLAN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sixpiece_2026-10-02.plan.json"


@pytest.mark.parametrize("model", MODELS)
def test_for_every_plan_address_a_dump_covers_its_value_is_the_single_reads(model):
    """A preview's before-value must be what a single read says. The plan's
    addresses a node dump covers are compared both ways over the desk's whole
    protocol: the type the target reads it as, the connector indices a single
    read is one low on, a level at -oo, the stepped values and the selectors."""
    plan = json.loads(PLAN_FIXTURE.read_text())
    targets, _ = apply_module._build_write_targets(plan, True)
    targets = targets + apply_module.full_apply_targets(plan, model)
    pairs = list({t.address: (t.address, t.value_type) for t in targets}.values())
    desk = _desk_for(model)
    read = init.read_desk(desk, [], extra=pairs)
    covered = {a for a, _ in pairs if audit.bulk_node_for(a) is not None}
    assert len(read.plan_values) > 150
    by_type = dict(pairs)
    for address, (value, error) in read.plan_values.items():
        assert address in covered
        single, single_error = apply_module._extract_reply_value(
            desk.get(address), by_type[address], address)
        assert error is None
        assert single_error is None, address
        if by_type[address] == "f":
            assert apply_module._values_equal("f", value, single, address), address
        else:
            assert value == single, (address, value, single)
    # What no dump gives is read singly, once: a name or a tag, anything off
    # the dumped depths, a leaf the dump did not carry. An address is never in
    # both.
    assert not set(read.plan_values) & set(read.replies)
    assert all(a in read.replies for a, _ in pairs
               if audit.bulk_node_for(a) is None and a.rsplit("/", 1)[-1] in ("name", "tags"))


# -- a dump prints the desk's rounded text: the verdict must not move -----------


class RoundingDesk(SnapDesk):
    """A desk whose node dump prints a float as the desk's display text, three
    significant digits and at least one decimal (`100.4755` as `100.0`,
    `999.2505` as `999.0`), while a single read gives the exact value: what a
    WING Compact does. Coarser than the real desk's text, on purpose."""

    def node_dump(self, node):
        exact = self.values
        self.values = {a: (float(f"{v:.3g}") if isinstance(v, float) and not isinstance(v, bool)
                           and v > -140 else v) for a, v in exact.items()}
        try:
            return super().node_dump(node)
        finally:
            self.values = exact


def _float_targets(model):
    plan = json.loads(PLAN_FIXTURE.read_text())
    targets, _ = apply_module._build_write_targets(plan, True)
    return plan, [t for t in targets
                  if t.value_type == "f" and audit.bulk_node_for(t.address) is not None]


def _edge_desk(model, targets):
    """A desk whose floats sit around each plan value's tolerance edge: from 1.5% to
    2.5% off it, on both sides."""
    desk = _desk_for(model)
    for n, target in enumerate(targets):
        intended = target.compute_value(None)
        if not isinstance(intended, (int, float)) or abs(intended) < 1 or intended <= -100:
            continue
        off = 0.015 + 0.001 * (n % 11)
        desk.values[target.address] = float(intended) * (1 + off * (1 if n % 2 else -1))
    return RoundingDesk(desk.values)


def _verdicts(result):
    return {r.address: r.would_change for r in result.writes if r.status == "dry_run"}


@pytest.mark.parametrize("model", CAPTURED)
def test_a_dump_read_value_near_the_tolerance_edge_gives_the_single_reads_verdict(model):
    plan, targets = _float_targets(model)

    def preview(window):
        desk = _edge_desk(model, targets)
        with _wired(desk, window=window) as (console, udp):
            return apply_plan(plan, console, dry_run=True, full_apply=True, initialize=True,
                              init_model=model)

    exact = _verdicts(preview(1))
    dumped = preview(8)
    assert _verdicts(dumped) == exact
    assert any(exact.values()) and not all(exact.values())
    assert any("were read again one by one" in w for w in dumped.warnings)


def test_without_the_guard_the_rounding_would_move_some_verdicts(monkeypatch):
    """The test above can fail: with every dump value trusted, the same desk
    gives a different verdict for at least one value."""
    model = "wing-compact"
    plan, targets = _float_targets(model)
    monkeypatch.setattr(apply_module, "_dump_verdict_is_certain", lambda *a, **k: True)
    with _wired(_edge_desk(model, targets), window=1) as (console, _udp):
        exact = _verdicts(apply_plan(plan, console, dry_run=True, full_apply=True,
                                     initialize=True, init_model=model))
    with _wired(_edge_desk(model, targets), window=8) as (console, _udp):
        trusted = _verdicts(apply_plan(plan, console, dry_run=True, full_apply=True,
                                       initialize=True, init_model=model))
    assert trusted != exact


@pytest.mark.parametrize("text,band", [
    ("144.7", 0.05), ("999.0", 0.5), ("100.0", 50.0), ("70.0", 5.0), ("0.71", 0.005),
    ("0.0", 0.05), ("-oo", 0.0), ("-3.5", 0.05)])
def test_the_rounding_band_comes_from_the_digits_the_dump_prints(text, band):
    assert osc.dump_text_rounding_band(text) == pytest.approx(band)


@pytest.mark.parametrize("exact,printed", [
    (144.6788, "144.7"), (999.2505, "999.0"), (100.4755, "100.0"),
    (0.70568, "0.71"), (69.88, "70.0")])
def test_the_band_covers_the_rounding_the_desk_was_seen_to_do(exact, printed):
    assert abs(float(printed) - exact) <= osc.dump_text_rounding_band(printed)


@pytest.mark.parametrize("model", CAPTURED)
def test_a_real_run_and_its_journal_never_use_a_dump_baseline(model, tmp_path):
    """Each baseline is read singly just before its write: the journal's prior
    values are the desk's exact ones, so Undo puts back what was there."""
    plan, targets = _float_targets(model)
    desk = _edge_desk(model, targets)
    exact = dict(desk.values)
    journal = tmp_path / "apply.json"
    with _wired(desk, window=8) as (console, _udp):
        apply_plan(plan, console, dry_run=False, journal_path=str(journal), full_apply=True,
                   initialize=True, init_model=model)
    rows = {w["address"]: w for w in json.loads(journal.read_text())["writes"]}
    floats = [a for a, row in rows.items()
              if isinstance(row.get("prior_value"), float) and a in exact and isinstance(exact[a], float)
              and not row["description"].startswith(init.DESCRIPTION)]
    assert floats
    for address in floats:
        assert rows[address]["prior_value"] == pytest.approx(exact[address], rel=1e-6), address


@pytest.mark.parametrize("model", CAPTURED)
def test_the_values_a_dump_rounded_are_read_again_together_not_one_round_trip_at_a_time(model):
    """On a real desk every serial read is a round trip: 534 of them were 4 s
    outside the read phase. They go out in one windowed pass, before the loop."""
    plan, targets = _float_targets(model)
    stream = io.StringIO()
    phases = Phases(stream=stream, isatty=False, timeout=0.5, window=8)
    with _wired(_edge_desk(model, targets), window=8) as (console, _udp):
        singles = []
        real_get = console.get
        console.get = lambda address: (singles.append(address), real_get(address))[1]
        result = apply_plan(plan, console, dry_run=True, full_apply=True, initialize=True,
                            init_model=model, phases=phases)
    [note] = [w for w in result.warnings if "were read again one by one" in w]
    again = int(note.split()[1].replace(",", ""))
    lines = [l for l in stream.getvalue().splitlines()
             if l.startswith(f"  {apply_module.REREAD_PHASE}: ")]
    assert len(lines) == 1 and again > 100
    # What the loop still asks one at a time is the few addresses no dump or
    # pass covered, not the re-reads.
    assert len(singles) * 10 < again
