"""A value whose meaning depends on a selector.

Found at desk run A22 (2026-09-28, ch 1, preset "Kick B91A"). The strip
started at `in/set/dlymode` M, `in/set/dly` 0.5. The preset wanted FT and
0.5. Apply wrote the mode, then read the delay -- 0.5 -- and skipped it as
`skipped_no_change`, though 0.5 m is not 0.5 ft. Undo put the mode back
and had no record of the delay, which then read 0.1.

`SelectorDesk` is a fake WING that does what the real one does to a
governed value when its selector changes: it re-reads it. Two selectors
are modelled, simply:

* `in/set/dlymode` -- the delay is a physical distance, shown in the
  mode's unit. M -> FT turns a reading of 0.5 into 1.64.
* `dyn/mdl` -- the compressor threshold is rescaled from one model's
  scale to the other's (COMP in dB, "LA" on a made-up scale of -2x).

And, as on the desk at A22, the first read of a governed value after its
selector changes answers with the old number (`stale_reads`), which is
what let the pre-fix apply read 0.5 straight after writing FT.

The tests that name the old behaviour were run against the pre-fix
`apply.py`/`undo.py` (the branch's parent) before being committed, and
failed there: see the PR body.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atoo import preset_expand
from atoo.apply import _strip_processing_targets, apply_plan
from atoo.console import OscReply
from atoo.undo import REVERSED, WOULD_REVERSE, _restore_order, journal_records, undo_from_journal
from tests.test_apply import compiled
from tests.test_undo import DeskConsole, raw

FIXTURES = Path(__file__).parent / "fixtures"
#: the maintainer's A22 apply journal, frozen byte-for-byte from
#: examples/console-runs/2026-09-28-1904/ (tests/fixtures/README.md). A
#: journal written BEFORE the fix: `/ch/1/in/set/dly` is skipped_no_change
#: under a `dlymode` the run changed.
A22_JOURNAL = FIXTURES / "console-runs" / "2026-09-28-1904" / "A22-apply-journal.json"

#: selector leaf -> (the leaves it rescales, unit per selector value)
CONVERSIONS = {
    "in/set/dlymode": (("in/set/dly",), {"M": 1.0, "FT": 0.3048}),
    "dyn/mdl": (("dyn/thr",), {"COMP": 1.0, "LA": -0.5}),
}


class SelectorDesk(DeskConsole):
    """A fake desk that re-reads a governed value when its selector
    changes -- see the module docstring."""

    def __init__(self, state=None, stale_reads=1):
        super().__init__(state)
        self.stale_reads = stale_reads
        self.stale: dict[str, list] = {}

    def get(self, address):
        held = self.stale.get(address)
        if held is not None:
            value, remaining = held
            if remaining <= 1:
                del self.stale[address]
            else:
                held[1] -= 1
            self._get_call_counts[address] = self._get_call_counts.get(address, 0) + 1
            return OscReply(address=address, typetag="f", args=[value])
        return super().get(address)

    def set_node(self, address, command):
        key, _, _ = command.partition("=")
        full = f"{address}/{key}"
        before = self.state.get(full, (None, None))[0]
        reply = super().set_node(address, command)
        self._after_write(full, before)
        return reply

    def set_param(self, address, value, value_type="f"):
        before = self.state.get(address, (None, None))[0]
        super().set_param(address, value, value_type)
        self._after_write(address, before)

    def _after_write(self, address, before):
        self.stale.pop(address, None)
        strip = "/" + "/".join(address.split("/")[1:3])
        leaf = address[len(strip) + 1:]
        if leaf not in CONVERSIONS:
            return
        after = self.state.get(address, (None, None))[0]
        governed, units = CONVERSIONS[leaf]
        if before == after or before not in units or after not in units:
            return
        for g in governed:
            full = f"{strip}/{g}"
            if full not in self.state:
                continue
            reading = self.state[full][0]
            self.state[full] = (reading * units[before] / units[after], "f")
            if self.stale_reads:
                self.stale[full] = [reading, self.stale_reads]

    def value(self, address):
        return self.state[address][0]


BEFORE = {
    "/ch/1/in/set/dlymode": ("M", "s"),
    "/ch/1/in/set/dly": (0.5, "f"),
    "/ch/1/in/set/dlyon": (0, "i"),
    "/ch/1/dyn/mdl": ("COMP", "s"),
    "/ch/1/dyn/thr": (-24.0, "f"),
    "/ch/1/dyn/on": (0, "i"),
}

PRESET = {
    # Selectors change; each governed value is what the strip already
    # read under the OLD selector -- A22's trap exactly.
    "in/set/dlymode": "FT", "in/set/dly": 0.5, "in/set/dlyon": True,
    "dyn/mdl": "LA", "dyn/thr": -24.0, "dyn/on": True,
}


def kick_plan(leaves=PRESET):
    plan = compiled("smallband")
    channel = plan["channels"][0]
    assert channel["channel"] == 1 and channel.get("bank", "ch") == "ch"
    channel["processing"] = {"preset": "Kick", "preset_values": {
        "preset": "Kick", "file": "kick.chn", "library": "/tmp", "sha256": "0",
        "leaves": dict(leaves), "overridden": {}}}
    return plan


def only_selector_leaves(target):
    return target.address in BEFORE


def apply_kick(desk, *, dry_run=False, tmp_path=None, leaves=PRESET):
    journal = str(tmp_path / "apply.json") if tmp_path is not None else None
    return apply_plan(kick_plan(leaves), desk, dry_run=dry_run, journal_path=journal,
                      target_filter=only_selector_leaves)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("selector, address, expected", [
    ("/ch/1/in/set/dlymode", "/ch/1/in/set/dly", True),
    ("/ch/1/in/set/dlymode", "/ch/1/in/set/trim", False),   # same node, not the mode's
    ("/ch/1/in/set/dlymode", "/ch/1/in/set/dlyon", False),  # a switch
    ("/ch/1/dyn/mdl", "/ch/1/dyn/thr", True),
    ("/ch/1/dyn/mdl", "/ch/1/dyn/ratio", True),
    ("/ch/1/dyn/mdl", "/ch/1/dyn/on", False),
    ("/ch/1/dyn/mdl", "/ch/1/dynxo/f", False),               # a different node
    ("/ch/1/dyn/mdl", "/ch/2/dyn/thr", False),               # a different strip
    ("/ch/1/gate/mdl", "/ch/1/gate/thr", True),
    ("/ch/1/eq/mdl", "/ch/1/eq/1g", True),
    ("/ch/1/eq/leq", "/ch/1/eq/lg", True),
    ("/ch/1/eq/mdl", "/ch/1/eq/leq", False),                 # a selector is not governed
    ("/ch/1/flt/mdl", "/ch/1/flt/tilt", True),
    ("/ch/1/flt/mdl", "/ch/1/flt/lc", False),                # a switch
    ("/ch/1/gatesc/type", "/ch/1/gatesc/f", True),
    ("/bus/3/eq/mdl", "/bus/3/eq/2f", True),
    ("/ch/1/in/set/dly", "/ch/1/in/set/dly", False),         # not a selector
])
def test_which_values_a_selector_governs(selector, address, expected):
    assert preset_expand.governs(selector, address) is expected


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def test_a_governed_value_is_not_left_at_the_old_selectors_reading():
    """(a) The A22 trap: the baseline read after the selector equals the
    preset's number, so the pre-fix apply skipped the delay and left the
    desk's re-read 1.64 ft where the preset asked for 0.5 ft.

    **Against the pre-fix code** this fails: `/ch/1/in/set/dly` ends at
    1.64 with status `skipped_no_change`."""
    desk = SelectorDesk(BEFORE)
    result = apply_kick(desk)
    assert desk.value("/ch/1/in/set/dlymode") == "FT"
    assert desk.value("/ch/1/in/set/dly") == pytest.approx(0.5)
    assert desk.value("/ch/1/dyn/mdl") == "LA"
    assert desk.value("/ch/1/dyn/thr") == pytest.approx(-24.0)
    statuses = {w.address: w.status for w in result.writes}
    assert statuses["/ch/1/in/set/dly"] == "match"
    assert statuses["/ch/1/dyn/thr"] == "match"


def test_apply_writes_and_reads_back_the_value_after_its_selector(tmp_path):
    """(b) The value is written AFTER its selector, read back, and its
    prior is the reading taken before the selector changed -- the value an
    undo has to put back -- with the selector named in the journal."""
    desk = SelectorDesk(BEFORE)
    result = apply_kick(desk, tmp_path=tmp_path)
    order = [f"{a}/{c.partition('=')[0]}" for a, c in desk.set_node_calls]
    assert order.index("/ch/1/in/set/dlymode") < order.index("/ch/1/in/set/dly") \
        < order.index("/ch/1/in/set/dlyon")
    assert order.index("/ch/1/dyn/mdl") < order.index("/ch/1/dyn/thr") < order.index("/ch/1/dyn/on")

    dly = next(w for w in result.writes if w.address == "/ch/1/in/set/dly")
    assert dly.forced_by == "/ch/1/in/set/dlymode"
    assert dly.prior_value == pytest.approx(0.5)      # under M, before the mode changed
    assert dly.readback_value == pytest.approx(0.5)
    assert any(w.startswith("INFO 2 value(s) written and read back after their selector")
               for w in result.warnings)

    rows = {r["address"]: r for r in json.loads((tmp_path / "apply.json").read_text())["writes"]}
    assert rows["/ch/1/in/set/dly"]["forced_by"] == "/ch/1/in/set/dlymode"
    # A row no selector forced keeps the journal's old shape exactly.
    assert "forced_by" not in rows["/ch/1/in/set/dlymode"]


def test_an_unchanged_selector_forces_nothing():
    """The rule is about a selector the run CHANGES. One already at the
    plan's value leaves its values to the ordinary skip-if-unchanged."""
    state = dict(BEFORE, **{"/ch/1/in/set/dlymode": ("FT", "s")})
    desk = SelectorDesk(state)
    result = apply_kick(desk)
    dly = next(w for w in result.writes if w.address == "/ch/1/in/set/dly")
    assert dly.status == "skipped_no_change" and dly.forced_by is None


def test_the_preview_counts_a_forced_value_as_a_change():
    desk = SelectorDesk(BEFORE)
    result = apply_kick(desk, dry_run=True)
    dly = next(w for w in result.writes if w.address == "/ch/1/in/set/dly")
    assert dly.forced_by == "/ch/1/in/set/dlymode" and dly.would_change
    assert desk.set_node_calls == [] and desk.set_param_calls == []


def test_the_plans_own_processing_is_ordered_selectors_first():
    """The plan's typed EQ fields build the bands before `eq/mdl`; the
    strip's processing is now ordered selectors, values, switches."""
    targets, _ = _strip_processing_targets("/bus/1", "bus", "bus 1", {"eq": {
        "model": "SOUL", "bands": [{"band": "1", "gain_db": 3.0}]}})
    assert [t.address for t in targets] == ["/bus/1/eq/mdl", "/bus/1/eq/1g", "/bus/1/eq/on"]


def test_the_pre_read_never_leaves_the_runs_own_targets():
    """FR-2.2: the extra baseline read before a selector is taken only for
    targets this run already owns -- `target_filter` has dropped every
    other strip's before the loop, so nothing else is so much as read."""
    desk = SelectorDesk(dict(BEFORE, **{"/ch/2/in/set/dly": (0.5, "f")}))
    apply_kick(desk)
    assert set(desk._get_call_counts) <= set(BEFORE)


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def test_undo_restores_the_selector_then_the_value(tmp_path):
    """(c) Undo puts the selector back first, then the value it governs,
    then the switch -- and the strip reads exactly what it read before
    the apply.

    **Against the pre-fix code** this fails: reverse order restores the
    delay, then the mode's change re-reads it, leaving 0.1524."""
    desk = SelectorDesk(BEFORE)
    apply_kick(desk, tmp_path=tmp_path)
    journal = json.loads((tmp_path / "apply.json").read_text())
    desk.set_node_calls.clear()
    result = undo_from_journal(journal, desk, dry_run=False)
    for address, (value, _t) in BEFORE.items():
        assert desk.value(address) == pytest.approx(value), address
    order = [f"{a}/{c.partition('=')[0]}" for a, c in desk.set_node_calls]
    assert order.index("/ch/1/in/set/dlymode") < order.index("/ch/1/in/set/dly") \
        < order.index("/ch/1/in/set/dlyon")
    assert order.index("/ch/1/dyn/mdl") < order.index("/ch/1/dyn/thr") < order.index("/ch/1/dyn/on")
    assert {s.address for s in result.of(REVERSED)} == set(BEFORE)


def old_style_journal():
    """A journal shaped as the pre-fix apply wrote it (A22): the selector
    written, the value it governs skipped with its prior recorded."""
    def row(address, prior, intended, value_type, status):
        return {"address": address, "description": f"ch 1 (Kick): preset Kick {address}",
                "value_type": value_type, "method": "node" if status == "match" else None,
                "ack": "OK" if status == "match" else None, "prior_value": prior,
                "intended_value": intended, "readback_value": intended, "status": status,
                "timestamp": "2026-09-29T02:05:26+00:00", "readback_source": None}
    return {"generated_at": "2026-09-29T02:05:27+00:00", "dry_run": False, "warnings": [],
            "replies_discarded": 0, "replies_used": 0, "writes": [
                row("/ch/1/in/set/dlymode", "M", "FT", "s", "match"),
                row("/ch/1/in/set/dly", 0.5, 0.5, "f", "skipped_no_change"),
                row("/ch/1/in/set/dlyon", 0, 1, "i", "match"),
            ]}


def test_undo_of_an_old_journal_restores_the_skipped_value():
    """(d) The journal from before the fix records the delay as skipped.
    Undo still puts it back after the mode, from the prior the journal
    recorded, and says so at INFO.

    **Against the pre-fix code** this fails: the delay is never a
    candidate and reads 0.1524 after the mode goes back -- A22's 0.1."""
    # The desk as A22 left it: FT, and a delay reading 0.5 (ft).
    desk = SelectorDesk({"/ch/1/in/set/dlymode": ("FT", "s"), "/ch/1/in/set/dly": (0.5, "f"),
                         "/ch/1/in/set/dlyon": (1, "i")})
    result = undo_from_journal(old_style_journal(), desk, dry_run=False)
    assert desk.value("/ch/1/in/set/dlymode") == "M"
    assert desk.value("/ch/1/in/set/dly") == pytest.approx(0.5)
    assert desk.value("/ch/1/in/set/dlyon") == 0
    assert any(w.startswith("INFO 1 value(s) were put back after the selector")
               and "/ch/1/in/set/dly" in w for w in result.warnings)
    assert result.never_written == 0


def test_the_preview_of_an_old_journal_says_it_will_restore_the_value():
    desk = SelectorDesk({"/ch/1/in/set/dlymode": ("FT", "s"), "/ch/1/in/set/dly": (0.5, "f"),
                         "/ch/1/in/set/dlyon": (1, "i")})
    result = undo_from_journal(old_style_journal(), desk, dry_run=True)
    dly = next(s for s in result.steps if s.address == "/ch/1/in/set/dly")
    assert dly.verdict == WOULD_REVERSE
    assert "after its selector /ch/1/in/set/dlymode" in dly.detail
    assert desk.set_node_calls == []


def test_a_skipped_value_whose_selector_is_not_restored_is_left_alone():
    """Only a selector this undo actually puts back re-reads its values.
    If somebody has since moved the mode, the mode is refused -- and the
    delay, which the apply never wrote, is not touched either."""
    desk = SelectorDesk({"/ch/1/in/set/dlymode": ("MS", "s"), "/ch/1/in/set/dly": (0.5, "f"),
                         "/ch/1/in/set/dlyon": (1, "i")})
    result = undo_from_journal(old_style_journal(), desk, dry_run=False)
    assert desk.value("/ch/1/in/set/dlymode") == "MS"
    assert all(s.address != "/ch/1/in/set/dly" for s in result.steps)
    assert result.never_written == 1


def test_undo_of_a22s_real_journal_restores_ch1s_delay():
    """(d), on the real thing: A22's own journal (frozen), ch 1's
    processing, against a desk seeded as that apply left it. The delay is
    put back to 0.5 after the mode, and every processing address the run
    touched on the strip reads its journalled prior."""
    journal = json.loads(A22_JOURNAL.read_text())
    rows = [r for r in journal["writes"]
            if preset_expand.is_processing_address(r["address"])
            and r["address"].startswith("/ch/1/")]
    assert {"/ch/1/in/set/dlymode", "/ch/1/in/set/dly"} <= {r["address"] for r in rows}
    state = {r["address"]: (raw(r["address"], r["readback_value"]), r["value_type"])
             for r in rows}
    desk = SelectorDesk(state)
    result = undo_from_journal(journal, desk, dry_run=False, only=["/ch/1"])
    assert desk.value("/ch/1/in/set/dlymode") == "M"
    assert desk.value("/ch/1/in/set/dly") == pytest.approx(0.5)
    for r in rows:
        if r["status"] in ("match", "mismatch") or r["address"] == "/ch/1/in/set/dly":
            assert desk.value(r["address"]) == pytest.approx(raw(r["address"], r["prior_value"])), \
                r["address"]
    assert not result.failed and not result.refused


def test_old_journals_still_load():
    """Every A22 row loads, and none of them carries `forced_by`."""
    records = journal_records(json.loads(A22_JOURNAL.read_text()))
    assert len(records) == 1100
    assert all(r.forced_by is None for r in records)


def test_undo_order_moves_only_processing_rows():
    """Selectors, values, switches among the processing rows; every
    other row keeps its reverse-journal position."""
    records = journal_records({"writes": [
        {"address": a, "status": "match"} for a in (
            "/ch/1/main/1/on", "/ch/1/in/set/dlymode", "/ch/1/in/set/dly",
            "/ch/1/in/set/dlyon", "/ch/1/fdr")]})
    assert [r.address for r in _restore_order(records)] == [
        "/ch/1/fdr", "/ch/1/in/set/dlymode", "/ch/1/in/set/dly", "/ch/1/in/set/dlyon",
        "/ch/1/main/1/on"]


# ---------------------------------------------------------------------------
# A value that exists only under the NEW selector
# ---------------------------------------------------------------------------
#
# sixpiece's apply, 2026-09-29 (examples/sixpiece/journals/): the vocal
# presets switched ch 16-22's gate/mdl GATE -> PSE and carried gate/depth,
# gate/fast and gate/peak -- leaves the GATE model does not have. Their
# baselines were read under GATE, failed, and all 21 were journalled
# `unreadable_skipped`: preset values that never reached the desk.

PSE_BEFORE = {
    "/ch/1/gate/mdl": ("GATE", "s"),
    "/ch/1/gate/thr": (-40.0, "f"),
    "/ch/1/gate/on": (0, "i"),
}
PSE_PRESET = {"gate/mdl": "PSE", "gate/thr": -36.0, "gate/depth": 20.0, "gate/on": True}


def _pse_only(target):
    return target.address.startswith("/ch/1/gate/")


class PseDesk(SelectorDesk):
    """As the desk does: `gate/depth` exists only while the gate model is
    PSE, and appears (at the model's default) when it is switched to."""

    def get(self, address):
        if address == "/ch/1/gate/depth" and self.state["/ch/1/gate/mdl"][0] != "PSE":
            self._get_call_counts[address] = self._get_call_counts.get(address, 0) + 1
            return OscReply(address=address, typetag="s", args=["NODE NOT FOUND"])
        return super().get(address)

    dumps = 0

    def node_dump(self, node):
        """The desk's own `,s *` dump of a node: its leaves as held now."""
        self.dumps += 1
        prefix = node + "/"
        items = [f"{a[len(prefix):]}={v}" for a, (v, _t) in self.state.items()
                 if a.startswith(prefix) and "/" not in a[len(prefix):]
                 and (a != "/ch/1/gate/depth" or self.state["/ch/1/gate/mdl"][0] == "PSE")]
        return ",".join(items) or None

    def _after_write(self, address, before):
        super()._after_write(address, before)
        if address == "/ch/1/gate/mdl" and self.state[address][0] == "PSE":
            self.state.setdefault("/ch/1/gate/depth", (10.0, "f"))


def test_a_value_the_old_selector_does_not_have_is_written_after_it():
    desk = PseDesk(PSE_BEFORE)
    preview = apply_plan(kick_plan(PSE_PRESET), desk, dry_run=True, target_filter=_pse_only)
    planned = next(w for w in preview.writes if w.address == "/ch/1/gate/depth")
    assert planned.forced_by == "/ch/1/gate/mdl" and planned.would_change

    result = apply_plan(kick_plan(PSE_PRESET), desk, dry_run=False, target_filter=_pse_only)
    depth = next(w for w in result.writes if w.address == "/ch/1/gate/depth")
    assert depth.forced_by == "/ch/1/gate/mdl"
    assert depth.prior_value is None            # nothing was there under GATE
    assert depth.status == "match"
    assert desk.value("/ch/1/gate/depth") == pytest.approx(20.0)


def test_a_value_unreadable_with_no_selector_change_is_still_skipped():
    """Only a changed selector explains an unreadable baseline. With the
    model already PSE, an unreadable leaf is skipped as before."""
    # Already PSE, but this desk cannot read the leaf at all.
    desk = SelectorDesk(dict(PSE_BEFORE, **{"/ch/1/gate/mdl": ("PSE", "s")}))
    result = apply_plan(kick_plan(PSE_PRESET), desk, dry_run=False, target_filter=_pse_only)
    depth = next(w for w in result.writes if w.address == "/ch/1/gate/depth")
    assert depth.status == "unreadable_skipped" and depth.forced_by is None


def test_a_value_the_old_selector_does_not_have_costs_no_read():
    """The same run's other cost: each of those 21 baselines was a GET the
    desk never answered -- 3 s of timeout and retries apiece, 63 of the
    run's 65 seconds. One node dump before the selector changes says the
    leaf is not there, and it is not asked for."""
    desk = PseDesk(PSE_BEFORE)
    apply_plan(kick_plan(PSE_PRESET), desk, dry_run=False, target_filter=_pse_only)
    assert desk.dumps == 1
    # Read once only: its readback, under PSE.
    assert desk._get_call_counts["/ch/1/gate/depth"] == 1


def test_without_a_dump_every_governed_value_is_still_read():
    desk = PseDesk(PSE_BEFORE)
    desk.node_dump = lambda node: None          # the desk did not answer the dump
    result = apply_plan(kick_plan(PSE_PRESET), desk, dry_run=False, target_filter=_pse_only)
    assert desk._get_call_counts["/ch/1/gate/depth"] == 2    # baseline, then readback
    depth = next(w for w in result.writes if w.address == "/ch/1/gate/depth")
    assert depth.status == "match"
