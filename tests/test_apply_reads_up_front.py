"""A confirmed run reads the plan's baselines up front, as the preview does
(Apply --confirm reads each setting one at a time before writing it).

A real run used to ask the desk for each setting just before writing it, one
round trip at a time: on the church desk, 2,423 requests in 50 s where the
preview, reading the same settings with node dumps and a window of requests in
flight, took 5. Now both read the same way. What the one-at-a-time read was
for still holds, and these tests pin it, over the wire with a window of 8:

* a value its selector governs is written after the selector and journalled
  with the prior it had under the OLD selector;
* every float a dump printed rounded is read again exactly, so the journal's
  priors are the desk's values and Undo puts back what was there;
* every write is still read back;
* a setting the run skipped as already set, which one of its own writes then
  moved on the desk, is found after the writes and written too.
"""

from __future__ import annotations

import io
import json

import pytest

from atoo import apply as apply_module
from atoo.progress import Phases
from atoo.apply import apply_plan
from atoo.console import OscReply
from atoo.undo import undo_from_journal
from tests.snap_desk import SnapDesk, _text
from tests.test_combined_preview_read import _desk_for, _edge_desk, _float_targets, _plan
from tests.test_pipelined_reads import _wired
from tests.test_selector_dependent import BEFORE, SelectorDesk, kick_plan, only_selector_leaves

IDENTITY = "WING,198.51.100.9,TEST,wing-compact,S1,3.1.0"


class WiredSelectorDesk(SelectorDesk):
    """`SelectorDesk` with what the wire asks of a desk: who it is, and a node
    dump of what it holds."""

    def identity(self):
        return OscReply("/?", "s", [IDENTITY])

    def node_dump(self, node):
        items = [f"{address[len(node) + 1:]}={_text(value)}"
                 for address, (value, _t) in self.state.items()
                 if address.startswith(node + "/") and "/" not in address[len(node) + 1:]]
        return ",".join(items) + "," if items else None


class KnockOnDesk(SnapDesk):
    """A desk on which writing channel 1's name moves channel 2's, as a
    stereo pair's mode carries its partner on a WING."""

    def _store(self, address, value):
        super()._store(address, value)
        if address == "/ch/1/name":
            super()._store("/ch/2/name", "Knocked")


def _knock_on_run(monkeypatch=None):
    desk = KnockOnDesk(dict(_desk_for("wing-compact").values,
                            **{"/ch/1/name": "Old show", "/ch/2/name": "Snare"}))
    if monkeypatch is not None:
        import atoo.apply as apply_module

        monkeypatch.setattr(apply_module, "_recheck_skipped", lambda *a, **k: (None, []))
    with _wired(desk, window=8) as (console, _udp):
        result = apply_plan(_plan(), console, dry_run=False, full_apply=True, initialize=True,
                            init_model="wing-compact")
    return desk, result


def test_a_setting_a_write_moved_after_it_was_skipped_is_written_too():
    desk, result = _knock_on_run()
    assert (desk.values["/ch/1/name"], desk.values["/ch/2/name"]) == ("Kick", "Snare")
    [record] = [w for w in result.writes if w.address == "/ch/2/name"]
    # Journalled with what it held before the run, so Undo leaves it as it was.
    assert (record.status, record.prior_value, record.readback_value) == (
        "match", "Snare", "Snare")
    assert result.writes[-1] is record
    [said] = [w for w in result.warnings if "changed on the desk while it wrote" in w]
    assert said.startswith("INFO 1 setting(s) the run had found already set changed")
    assert "it read 'Knocked'" in said


def test_without_the_check_the_knock_on_would_be_left(monkeypatch):
    desk, result = _knock_on_run(monkeypatch)
    assert desk.values["/ch/2/name"] == "Knocked"
    assert [w.status for w in result.writes if w.address == "/ch/2/name"] == [
        "skipped_no_change"]


def test_nothing_written_means_nothing_read_again():
    """A run that writes nothing cannot have moved anything: no second pass."""
    desk = _desk_for("wing-compact")
    texts = []
    for _run in range(2):
        stream = io.StringIO()
        phases = Phases(stream=stream, isatty=False, timeout=0.5, window=8)
        with _wired(desk, window=8) as (console, _udp):
            result = apply_plan(_plan(), console, dry_run=False, full_apply=True,
                                initialize=True, init_model="wing-compact", phases=phases)
        texts.append(stream.getvalue())
    assert all(w.status == "skipped_no_change" for w in result.writes)
    assert apply_module.SKIPPED_RECHECK_PHASE in texts[0]
    assert apply_module.SKIPPED_RECHECK_PHASE not in texts[1]


def _count_gets(console):
    asked: list[str] = []
    real_get = console.get
    console.get = lambda address: (asked.append(address), real_get(address))[1]
    return asked


def test_a_real_run_asks_no_setting_one_at_a_time_that_the_read_up_front_answered():
    """Nothing on the desk differs from the plan but three settings: the run
    reads the rest in its one pass and asks singly only to read its writes
    back."""
    with _wired(_desk_for("wing-compact"), window=8) as (console, _udp):
        asked = _count_gets(console)
        result = apply_plan(_plan(), console, dry_run=False, full_apply=True, initialize=True,
                            init_model="wing-compact")
    assert not result.aborted and not result.mismatches
    written = {w.address for w in result.writes if w.status == "match"}
    assert written
    # Each written setting is read back once; nothing is asked before its write.
    assert sorted(asked) == sorted(written)
    assert any(w.startswith("INFO the run, before its writes, read the desk with")
               for w in result.warnings)


def test_a_governed_value_keeps_its_old_selectors_prior_and_undo_puts_it_back(tmp_path):
    """An earlier change over the wire: the delay is read up front under M, written
    after the mode turns FT, read back, and Undo restores the strip."""
    desk = WiredSelectorDesk(BEFORE)
    journal = tmp_path / "apply.json"
    with _wired(desk, window=8) as (console, _udp):
        result = apply_plan(kick_plan(), console, dry_run=False, journal_path=str(journal),
                            target_filter=only_selector_leaves)
    assert desk.value("/ch/1/in/set/dlymode") == "FT"
    assert desk.value("/ch/1/in/set/dly") == pytest.approx(0.5)
    assert desk.value("/ch/1/dyn/thr") == pytest.approx(-24.0)
    by_address = {w.address: w for w in result.writes}
    for address, selector in (("/ch/1/in/set/dly", "/ch/1/in/set/dlymode"),
                              ("/ch/1/dyn/thr", "/ch/1/dyn/mdl")):
        record = by_address[address]
        assert (record.status, record.forced_by) == ("match", selector)
        assert record.prior_value == pytest.approx(BEFORE[address][0])

    undo_from_journal(json.loads(journal.read_text()), desk, dry_run=False)
    for address, (value, _t) in BEFORE.items():
        assert desk.value(address) == pytest.approx(value), address


def test_undo_of_a_run_whose_baselines_a_dump_rounded_is_exact(tmp_path):
    """The desk's floats sit 1.5-2.5% off the plan's and its dump prints three
    significant digits: Undo still puts back each exact value."""
    model = "wing-compact"
    plan, targets = _float_targets(model)
    desk = _edge_desk(model, targets)
    before = dict(desk.values)
    journal = tmp_path / "apply.json"
    with _wired(desk, window=8) as (console, _udp):
        result = apply_plan(plan, console, dry_run=False, journal_path=str(journal),
                            full_apply=True, initialize=False)
    written = [w.address for w in result.writes
               if w.status == "match" and isinstance(before.get(w.address), float)]
    assert len(written) > 20
    undo_from_journal(json.loads(journal.read_text()), desk, dry_run=False)
    for address in written:
        assert desk.values[address] == pytest.approx(before[address], rel=1e-6), address
