"""Tests for atoo/apply.py -- plan -> console writes -> readback
verification. No real console is available (or wanted) here: FakeConsole
below records every set_param/set_node call and serves canned get()
replies, so the address mapping, tag-merging, dry-run, journal, and
mismatch-reporting logic can all be tested without hardware, per the
brief ("design for [no console]... put all socket I/O behind the client
class so tests can substitute a fake console").
"""

from __future__ import annotations

import collections
import copy
import json
import re
from pathlib import Path

import pytest

from atoo.apply import (
    STAGE_PHANTOM,
    STAGE_PROCESSING,
    ApplyResult,
    WriteRecord,
    WriteTarget,
    _PendingCheck,
    _build_write_targets,
    _channel_write_targets,
    _format_for_node_command,
    _merge_tags,
    _output_slot,
    _recheck_disagreements,
    _write_target,
    apply_plan,
    release_write_targets,
)
from atoo.console import OscReply

FIXTURES = Path(__file__).parent / "fixtures"

# Plans these tests used to build by running the deterministic compiler over
# a few lines of conventions. That path was retired, so the exact
# plans it produced are checked in instead -- generated from the compiler at
# `origin/main` immediately before deletion, so every assertion below is
# still made against the same bytes it was written against. These are
# `apply` tests: what matters is the plan's shape, never how it was built.
_COMPILED = json.loads((FIXTURES / "compiled_plans.json").read_text())


def compiled(name: str) -> dict:
    """One of the checked-in plans, deep-copied so a test that mutates it
    cannot leak into the next one."""
    return copy.deepcopy(_COMPILED[name]["plan"])



class FakeConsole:
    """Records every set_param/set_node call it receives. `state` is a
    dict of address -> (value, value_type) used to answer get(); starts
    empty (every address "unreadable") unless seeded by the test. A write
    updates `state` for that address, mirroring what a real console would
    do, so a second get() sees the new value -- this is what lets the
    apply loop's own readback verification actually mean something in a
    test."""

    def __init__(self, state: dict | None = None):
        self.state = dict(state or {})
        self.set_param_calls: list[tuple[str, object, str]] = []
        self.set_node_calls: list[tuple[str, str]] = []
        # address -> OscReply to return instead of the default, for
        # simulating a console error ack or a dropped reply on set_node.
        self.node_ack_overrides: dict[str, OscReply] = {}
        # Address -> (1-indexed call number, reply to return on
        # THAT call only, normal state-lookup on every other call). A
        # plain address->reply dict can't simulate "the readback fails but
        # the baseline read didn't" -- apply_plan() calls get() twice per
        # written address, and those two calls need to be distinguishable.
        self.get_overrides: dict[str, tuple[int, OscReply]] = {}
        self._get_call_counts: dict[str, int] = {}
        # When set, set_param() raises this instead of
        # recording normally -- simulates console.py's own set_param
        # propagating a real socket-level OSError from sendto().
        self.set_param_raises: OSError | None = None
        # Addresses this console silently refuses to store. A write to one
        # is accepted on the wire and changes nothing -- which is the
        # failure mode readback verification exists for, and the one a
        # re-read must NOT be able to hide.
        self.reject_writes_to: set[str] = set()
        # An earlier change, the read-after-write race on the unacked path.
        # Addresses in `answer_late` take the write on the desk but keep
        # answering READS with the pre-write value; the new value turns up
        # later as a datagram the client drains while asking about some
        # other address. That is `/ch/7/tags` on the 2026-09-21 A1 run
        # (raw log lines 1469-1485): three reads in a row answered '',
        # two unsolicited datagrams carrying '#D7,#M1' afterwards, and
        # the maintainer confirming at the desk that the tags were there. Before
        # this existed nothing in 1149 tests could express a peer that
        # answers late.
        self.answer_late: set[str] = set()
        # address -> the value its late datagram carries, when that is
        # NOT the value that was written. A console volunteering an
        # address's state says what the desk holds, which need not be
        # what was asked for -- and a late datagram that disagrees must
        # settle nothing.
        self.answer_late_with: dict[str, object] = {}
        # How many get() calls go by after such a write before the
        # console's own datagram shows up. The hardware took two.
        self.late_after_gets = 2
        self._due_late: list[list] = []
        # What WingConsole keeps for a drained datagram: address ->
        # (datagram count when it arrived, reply). Same three-method
        # surface apply.py consults through getattr.
        self._late_replies: dict[str, tuple[int, OscReply]] = {}
        self.datagrams_received = 0
        self.replies_discarded = 0
        self.replies_used = 0
        self.late_replies_used: list[str] = []

    def get(self, address: str) -> OscReply | None:
        self._get_call_counts[address] = self._get_call_counts.get(address, 0) + 1
        self.datagrams_received += 1
        reply = self._reply_to(address)
        self._deliver_late_datagrams()
        return reply

    def _reply_to(self, address: str) -> OscReply | None:
        if address in self.get_overrides:
            at_call, reply = self.get_overrides[address]
            if self._get_call_counts[address] == at_call:
                return reply
        if address not in self.state:
            return OscReply(address=address, typetag="s", args=["NODE NOT FOUND"])
        value, value_type = self.state[address]
        return OscReply(address=address, typetag=value_type, args=[value])

    def _deliver_late_datagrams(self) -> None:
        """Let one get() go by on every write still owed a late datagram,
        and file the ones that are now due exactly as WingConsole._request
        would when it drained them."""
        for due in list(self._due_late):
            due[3] -= 1
            if due[3] > 0:
                continue
            self._due_late.remove(due)
            address, value, value_type, _ = due
            self.replies_discarded += 1
            self.push_late_reply(address, value, value_type)

    def push_late_reply(self, address: str, value, value_type: str = "s",
                        mark: int | None = None) -> None:
        """Plant a drained datagram for `address`. `mark` overrides when
        it arrived, which is how a test can place one BEFORE a write."""
        self.datagrams_received += 1
        self._late_replies[address] = (
            self.datagrams_received if mark is None else mark,
            OscReply(address=address, typetag=value_type, args=[value]),
        )

    def late_reply(self, address: str, *, after: int = -1) -> OscReply | None:
        entry = self._late_replies.get(address)
        if entry is None:
            return None
        mark, reply = entry
        return reply if mark > after else None

    def use_late_reply(self, address: str) -> OscReply | None:
        entry = self._late_replies.pop(address, None)
        if entry is None:
            return None
        self.replies_used += 1
        self.late_replies_used.append(address)
        return entry[1]

    def set_param(self, address: str, value, value_type: str = "f") -> None:
        if self.set_param_raises is not None:
            raise self.set_param_raises
        self.set_param_calls.append((address, value, value_type))
        if address in self.answer_late or address in self.answer_late_with:
            # The desk took it; its reads just have not caught up. The
            # truth arrives as its own datagram, `late_after_gets` reads
            # from now, and never through `state` -- so a test that
            # passes here passed on the late datagram alone, not on a
            # re-read that happened to find the value.
            self._due_late.append([address, self.answer_late_with.get(address, value),
                                   value_type, self.late_after_gets])
            return
        if address not in self.reject_writes_to:
            self.state[address] = (value, value_type)

    def set_node(self, address: str, command: str) -> OscReply | None:
        self.set_node_calls.append((address, command))
        if address in self.node_ack_overrides:
            return self.node_ack_overrides[address]
        key, _, text = command.partition("=")
        full_address = f"{address}/{key}"
        # Infer a plausible type from the existing state, defaulting to
        # string -- good enough for a fake that just needs to round-trip
        # what apply.py itself sent.
        prior_type = self.state.get(full_address, (None, "s"))[1]
        if prior_type == "f":
            value = float(text)
        elif prior_type == "i":
            try:
                value = int(text)
            except ValueError:
                value = text
        else:
            value = text
        if full_address not in self.reject_writes_to:
            self.state[full_address] = (value, prior_type)
        return OscReply(address="/*", typetag="s", args=["OK"])


_PAIR_MODE = re.compile(r"^(/io/in/[^/]+/)(\d+)(/mode)$")


class PairModeMirror:
    """Mixin for a fake desk that, like the real one, sets BOTH sockets of a
    stereo pair when either one's `mode` is written (by set_param or by node
    command). A preview counts the pair once (`WriteRecord.mirrored_by`), so a
    test that compares its count with a confirmed run needs a desk that does
    what the real one does."""

    def _mirror(self, address: str, value, value_type: str) -> None:
        match = _PAIR_MODE.match(address)
        if match and address not in self.reject_writes_to:
            n = int(match.group(2))
            other = f"{match.group(1)}{n + 1 if n % 2 else n - 1}{match.group(3)}"
            if other in self.state:
                self.state[other] = (value, value_type)

    def set_param(self, address, value, value_type="f"):
        super().set_param(address, value, value_type)
        self._mirror(address, value, value_type)

    def set_node(self, address, command):
        reply = super().set_node(address, command)
        key, _, text = command.partition("=")
        if key == "mode":
            self._mirror(f"{address}/{key}", text, "s")
        return reply


class MirroringConsole(PairModeMirror, FakeConsole):
    pass


@pytest.fixture
def plan():
    return compiled("smallband")


# --- tag merging ---


def test_merge_tags_preserves_unrelated_tokens_and_replaces_dca_mute():
    # Starts with an unrelated tag and a stale DCA/mute token -- the new
    # plan-derived membership should replace D/M tokens wholesale while
    # keeping the unrelated one, per spike_dca_mgrp.py's confirmed shape
    # ("#D1,#M1,#M8" -- multiple conventions share one field).
    result = _merge_tags("SOMETAG,#D9,#M3", dca_indices=[2], mute_group_indices=[1, 8])
    assert result == "SOMETAG,#D2,#M1,#M8"


def test_merge_tags_from_empty_current():
    assert _merge_tags(None, dca_indices=[1], mute_group_indices=[]) == "#D1"
    assert _merge_tags("", dca_indices=[], mute_group_indices=[3]) == "#M3"


def test_merge_tags_dedupes_and_sorts():
    assert _merge_tags("", dca_indices=[3, 1, 3], mute_group_indices=[]) == "#D1,#D3"


# --- /io/out/{grp}/{n}/in slot arithmetic ---


def test_output_slot_reserves_a_pair_per_object():
    # Object 1's L slot equals its own index -- the coincidence that hid
    # this bug until a real apply used a bus other than the first.
    assert _output_slot(1, 0) == 1
    assert _output_slot(1, 1) == 2
    assert _output_slot(2, 0) == 3
    assert _output_slot(2, 1) == 4
    assert _output_slot(9, 0) == 17
    assert _output_slot(9, 1) == 18


# --- dry run ---


def test_dry_run_never_calls_set_param_or_set_node(plan):
    console = FakeConsole()
    result = apply_plan(plan, console, dry_run=True)
    assert console.set_param_calls == []
    assert console.set_node_calls == []
    assert result.dry_run is True
    assert all(w.status in ("dry_run", "unreadable") for w in result.writes)


def test_dry_run_reports_intended_values_from_the_plan(plan):
    console = FakeConsole()
    result = apply_plan(plan, console, dry_run=True)
    kick_name = next(w for w in result.writes if w.address == "/ch/1/name")
    # Computed even though the baseline was unreadable -- a literal
    # target's intended value doesn't depend on the current value.
    assert kick_name.intended_value == "Kick"
    assert kick_name.prior_value is None  # FakeConsole starts empty -> NODE NOT FOUND -> unreadable
    assert kick_name.status == "unreadable"


def test_dry_run_reads_current_value_for_an_accurate_preview(plan):
    # A channel whose name already matches the plan -- dry run must show
    # that via a real read, not just echo the plan's own intended value
    # back as if it were unknown.
    console = FakeConsole(state={"/ch/1/name": ("Kick", "s")})
    result = apply_plan(plan, console, dry_run=True)
    kick_name = next(w for w in result.writes if w.address == "/ch/1/name")
    assert kick_name.prior_value == "Kick"
    assert kick_name.intended_value == "Kick"
    assert kick_name.status == "dry_run"


# --- The preview counts with the write path's own comparison ---
#
# `100.23745727539062` below is not a made-up near-miss. It is what
# the maintainer's Compact actually reports for `/ch/{10,11,12}/flt/lcf` against
# a plan asking for 100Hz, in all three real journals -- the low-cut is
# stepped (641 steps over 20-2000Hz), so 100Hz lands there and stays
# there. Those three addresses are the entire 340-vs-337 gap the issue
# measured on the 631-address A1 run.
_A_STEPPED_LCF_READING = 100.23745727539062


def test_dry_run_would_change_count_equals_what_a_confirmed_run_writes(plan):
    """The actual claim, tested as the property rather than as
    either number on its own: one plan, one console state, preview and
    apply must agree about how many addresses change.

    Before the fix the preview said 161 and the apply wrote 160 -- the
    preview counting `/ch/7/flt/lcf` because 100.237 != 100.0, the apply
    skipping it because `_values_equal` knows the desk cannot represent
    the difference."""
    state = _seed_all(plan)
    state["/ch/7/flt/lcf"] = (_A_STEPPED_LCF_READING, "f")

    preview = apply_plan(plan, MirroringConsole(state=dict(state)), dry_run=True)
    confirmed = apply_plan(plan, MirroringConsole(state=dict(state)), dry_run=False)

    would_change = [w for w in preview.writes if w.status == "dry_run" and w.would_change]
    assert len(would_change) == len(confirmed.changed)
    # And the summary line a user reads carries that same number.
    assert f"{len(confirmed.changed)} would change" in preview.summary()
    # Not vacuous: this plan really does change most of what it touches.
    assert len(would_change) > 100


def test_a_float_already_within_tolerance_is_not_previewed_as_a_change(plan):
    """The leaf-level version of the above: the same reading the write
    path calls `skipped_no_change` must not be `would change` in the
    preview, and the ones genuinely off target still must be."""
    state = _seed_all(plan)
    state["/ch/7/flt/lcf"] = (_A_STEPPED_LCF_READING, "f")  # plan wants 100.0
    preview = apply_plan(plan, FakeConsole(state=dict(state)), dry_run=True)

    settled = next(w for w in preview.writes if w.address == "/ch/7/flt/lcf")
    assert settled.prior_value == _A_STEPPED_LCF_READING
    assert settled.intended_value == 100.0
    assert settled.would_change is False

    # /ch/8 wants the same 100Hz and was seeded far away -- the tolerance
    # must not have swallowed the whole comparison.
    genuinely_off = next(w for w in preview.writes if w.address == "/ch/8/flt/lcf")
    assert genuinely_off.would_change is True

    confirmed = apply_plan(plan, FakeConsole(state=dict(state)), dry_run=False)
    assert next(w for w in confirmed.writes
                if w.address == "/ch/7/flt/lcf").status == "skipped_no_change"
    assert next(w for w in confirmed.writes
                if w.address == "/ch/8/flt/lcf").status in ("match", "mismatch")


def test_would_change_is_exact_for_a_non_float_leaf(plan):
    """The tolerance is a float-only affair -- a string or int leaf must
    still compare exactly, or `would_change` would start excusing real
    differences."""
    state = _seed_all(plan)
    state["/ch/1/name"] = ("Kick", "s")   # the plan's own value
    state["/ch/2/name"] = ("Kick.", "s")  # one character out
    preview = apply_plan(plan, FakeConsole(state=dict(state)), dry_run=True)
    assert next(w for w in preview.writes if w.address == "/ch/1/name").would_change is False
    assert next(w for w in preview.writes if w.address == "/ch/2/name").would_change is True


def test_cleaned_sockets_preview_asks_the_same_question_as_the_summary():
    """`ApplyResult.cleaned` carried its own copy of `prior != intended`
    -- The bug in a second place. Every `--clean-output-sockets`
    target is a `.grp` string enum today, so nothing was observably
    wrong; this pins the shared comparison so the two cannot drift apart
    again, whatever leaf a future clean-write touches."""
    def clean_record(address, prior, intended, value_type):
        return WriteRecord(
            address=address,
            description=f"--clean-output-sockets: {address} disconnected (no bus or output in the plan routes here)",
            value_type=value_type, method=None, ack=None,
            prior_value=prior, intended_value=intended, readback_value=None,
            status="dry_run", timestamp="t",
        )

    result = ApplyResult(dry_run=True, writes=[
        clean_record("/io/out/LCL/5/grp", "BUS", "OFF", "s"),   # a real change
        clean_record("/io/out/LCL/6/grp", "OFF", "OFF", "s"),   # already clean
        clean_record("/io/out/LCL/7/lvl", 0.001, 0.0, "f"),     # within tolerance
    ])
    assert [w.address for w in result.cleaned] == ["/io/out/LCL/5/grp"]
    assert "1 undeclared output socket(s) would be disconnected" in result.summary()


def test_the_journal_records_the_osc_type_tag(plan, tmp_path):
    """Without the type tag a journal can only be re-scored by
    guessing the leaf's type from the shape of its JSON value, which is
    how the preview came to disagree with the apply in the first place."""
    journal_path = tmp_path / "journal.json"
    apply_plan(plan, FakeConsole(state=_seed_all(plan)), dry_run=True,
               journal_path=str(journal_path))
    entries = {w["address"]: w for w in json.loads(journal_path.read_text())["writes"]}
    assert entries["/ch/1/name"]["value_type"] == "s"
    assert entries["/ch/1/flt/lcf"]["value_type"] == "f"
    assert all("value_type" in e for e in entries.values())


def test_would_change_reproduces_a_real_run_write_for_write():
    """The same claim scored against hardware rather than a fake: replay
    every baseline reading from the maintainer's 2026-09-18 apply and ask
    `would_change` what a preview of that run would have said.

    340 by plain inequality, 337 written. `would_change` has to say 337,
    and say it about the same 337 addresses -- not merely reach the right
    total by excusing one write and inventing another.

    The fixture predates `value_type` (added by this fix), so the tag is
    inferred from the JSON value's own shape here. That it reproduces the
    run's verdicts exactly, on every one of 627 addresses, is the check
    that the inference is faithful."""
    journal = json.loads(
        (FIXTURES / "touringband-2026-09-18.apply-journal.json").read_text())
    writes = journal["writes"]

    def as_record(w: dict) -> WriteRecord:
        value_type = "f" if any(
            isinstance(v, float) for v in (w["prior_value"], w["intended_value"])) else "s"
        return WriteRecord(
            address=w["address"], description=w["description"], value_type=value_type,
            method=w["method"], ack=w["ack"], prior_value=w["prior_value"],
            intended_value=w["intended_value"], readback_value=w["readback_value"],
            status=w["status"], timestamp=w["timestamp"],
        )

    records = [as_record(w) for w in writes]
    assert len(records) == 627, "the fixture is the 2026-09-18 run; it should not have moved"

    strictly_different = {w["address"] for w in writes
                          if w["prior_value"] != w["intended_value"]}
    actually_written = {w["address"] for w in writes
                        if w["status"] in ("match", "mismatch")}
    would_change = {r.address for r in records if r.would_change}

    assert len(strictly_different) == 340, "the old preview's answer, for the record"
    assert would_change == actually_written
    assert len(would_change) == 337
    # The three the old comparison over-counted: stepped low-cuts reading
    # 100.237Hz against a plan asking for 100Hz.
    assert sorted(strictly_different - would_change) == [
        "/ch/10/flt/lcf", "/ch/11/flt/lcf", "/ch/12/flt/lcf",
    ]


# --- real apply: address mapping ---


def _seed_all(plan: dict) -> dict:
    """A FakeConsole state dict with every address this plan will touch
    pre-populated with an obviously-different placeholder, so every write
    in a real (non-dry-run) apply is exercised rather than skipped as
    'no change needed'.

    Connector leaves (`in/conn/in`, `io/out/*/in`) are seeded to **-1**,
    not 0. The correction adds 1 to what the console reports for
    those two families, so a 0 placeholder now READS as 1 -- a perfectly
    valid socket index, and one the plan really does intend for Main 1,
    which made three tests here skip the write as 'already correct'. -1
    corrects to 0, which is out of band for a 1-based index either way.
    The same reasoning the `col`/`icon`/`vph` seeds below already used."""
    state = {}
    for name, entry in plan["dcas"].items():
        state[f"/dca/{entry['index']}/name"] = ("placeholder", "s")
    for name, entry in plan["mute_groups"].items():
        state[f"/mgrp/{entry['index']}/name"] = ("placeholder", "s")
    for name, entry in plan["busses"].items():
        state[f"/bus/{entry['index']}/name"] = ("placeholder", "s")
        if entry.get("mono") is not None:
            # Out-of-band sentinel value so both mono=True (wants 1) and
            # mono=False (wants 0) are exercised as real writes, never a
            # coincidental "already correct" skip.
            state[f"/bus/{entry['index']}/busmono"] = (-1, "i")
        if entry.get("col") is not None:
            state[f"/bus/{entry['index']}/col"] = (-1, "i")
        if entry.get("icon") is not None:
            state[f"/bus/{entry['index']}/icon"] = (-1, "i")
        # Destinations (plural) is authoritative when non-empty
        # -- seed every one of them, not just the singular mirror.
        destinations = entry.get("destinations")
        if not destinations:
            destinations = [entry["destination"]] if entry.get("destination") else []
        for dest in destinations:
            if dest["type"] == "main":
                state[f"/bus/{entry['index']}/main/{dest.get('index', 1)}/on"] = (0, "i")
            if dest["type"] == "dedicated_output":
                sockets = dest.get("sockets") or ([dest["socket"]] if dest.get("socket") else [])
                for socket in sockets:
                    for sock in socket["sockets"]:
                        grp = socket["group"]
                        state[f"/io/out/{grp}/{sock}/grp"] = ("OFF", "s")
                        state[f"/io/out/{grp}/{sock}/in"] = (-1, "i")
    for name, entry in plan.get("outputs", {}).items():
        sockets = entry.get("sockets") or ([entry["socket"]] if entry.get("socket") else [])
        for socket in sockets:
            for sock in socket["sockets"]:
                state[f"/io/out/{socket['group']}/{sock}/grp"] = ("OFF", "s")
                state[f"/io/out/{socket['group']}/{sock}/in"] = (-1, "i")
    for ch in plan["channels"]:
        n = ch["channel"]
        bank = ch.get("bank", "ch")
        base = f"/{bank}/{n}"
        state[f"{base}/name"] = ("placeholder", "s")
        # 1 is both the console default and the broken state ("Link
        # Customization to Source" ON), so seeding it here means every
        # apply in these tests exercises the unlink as a real write
        # rather than skipping it as already correct.
        state[f"{base}/clink"] = (1, "i")
        state[f"{base}/in/conn/grp"] = ("OFF", "s")
        state[f"{base}/in/conn/in"] = (-1, "i")
        if ch.get("col") is not None:
            state[f"{base}/col"] = (-1, "i")
        if ch.get("icon") is not None:
            state[f"{base}/icon"] = (-1, "i")
        if ch["patch"]["group"] in ("LCL", "A", "B", "C"):
            # Seeded to an out-of-band sentinel (never 0 or 1, the only
            # values the plan ever intends) so every channel's phantom
            # write -- on AND off -- is exercised rather than silently
            # skipped as "already correct" for whichever value happens to
            # match this channel's own target.
            state[f"/io/in/{ch['patch']['group']}/{ch['patch']['sockets'][0]}/vph"] = (-1, "i")
        for socket in ch["patch"]["sockets"]:
            state[f"/io/in/{ch['patch']['group']}/{socket}/mode"] = ("M/S", "s")  # sentinel, never M or ST
            # The source-side identity: the strip inherits its
            # displayed name/colour/icon from the socket, so these are the
            # addresses that actually matter to an engineer looking at the
            # desk. Placeholders so every one is exercised as a real write.
            state[f"/io/in/{ch['patch']['group']}/{socket}/name"] = ("placeholder", "s")
            if ch.get("col") is not None:
                state[f"/io/in/{ch['patch']['group']}/{socket}/col"] = (-1, "i")
            if ch.get("icon") is not None:
                state[f"/io/in/{ch['patch']['group']}/{socket}/icon"] = (-1, "i")
        if bank != "aux" and ch["processing"]["hpf_hz"] is not None:
            state[f"{base}/flt/lc"] = (0, "i")
            state[f"{base}/flt/lcf"] = (20.0, "f")
        if ch["dca"] or ch["mute_group"]:
            state[f"{base}/tags"] = ("", "s")
        for send in ch["bus_sends"]:
            bidx = plan["busses"][send["bus"]]["index"]
            state[f"{base}/send/{bidx}/on"] = (0, "i")
            state[f"{base}/send/{bidx}/lvl"] = (-144.0, "f")
            state[f"{base}/send/{bidx}/mode"] = ("PRE", "s")
        for route in ch.get("main_routes", []):
            # A channel's own direct-to-Main route -- sentinels,
            # never this module's documented defaults (on/unity/post),
            # same reasoning as fdr/mute below.
            main_base = f"{base}/main/{route['index']}"
            state[f"{main_base}/on"] = (0, "i")
            state[f"{main_base}/lvl"] = (-144.0, "f")
            state[f"{main_base}/pre"] = (1, "i")
        # Sentinels, never the plan's own starting-state values (unity /
        # off) -- so a real apply's fdr/mute writes are exercised rather
        # than silently skipped as "already correct".
        state[f"{base}/fdr"] = (-6.0, "f")
        state[f"{base}/mute"] = (1, "i")
    for name, entry in plan["busses"].items():
        # Same sentinel reasoning as a channel's fdr/mute above -- a
        # bus's own starting fader/mute (2026-09-10 correction) is a
        # real address on real hardware, exercised the same way.
        state[f"/bus/{entry['index']}/fdr"] = (-6.0, "f")
        state[f"/bus/{entry['index']}/mute"] = (1, "i")
    for name, entry in plan.get("outputs", {}).items():
        kind, index = entry.get("kind"), entry.get("index")
        if kind in ("main", "matrix") and index is not None:
            out_base = f"/main/{index}" if kind == "main" else f"/mtx/{index}"
            state[f"{out_base}/fdr"] = (-6.0, "f")
            state[f"{out_base}/mute"] = (1, "i")
    return state


def test_channel_name_and_patch_written(plan):
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert ("/ch/1", "name=Kick") in console.set_node_calls
    assert ("/ch/1/in/conn", "grp=LCL") in console.set_node_calls
    assert ("/ch/1/in/conn", "in=1") in console.set_node_calls
    name_record = next(w for w in result.writes if w.address == "/ch/1/name")
    assert name_record.status == "match"
    assert name_record.method == "node"
    assert name_record.ack == "OK"


def test_an_unstated_patch_socket_warns_in_words_that_are_still_true(plan):
    """This string is read by an operator standing at a desk,
    and it named the compiler an earlier change deleted. `stated: False` now means the
    MODEL chose the socket during generate -- a stronger reason to check
    it before the write lands, so the warning has to say that and not
    point at a component that no longer exists."""
    assert plan["channels"][0]["patch"]["stated"] is False
    _, warnings = _build_write_targets(plan, True)
    unstated = [w for w in warnings if "patch socket was not stated" in w]
    kick = [w for w in unstated if w.startswith("ch 1 ('Kick')")]
    assert len(kick) == 1
    assert "assigned during generation" in kick[0]
    assert "verify before trusting this write" in kick[0]
    assert not any("compiler" in w for w in warnings)


def test_no_warning_when_the_input_list_stated_the_socket(plan):
    """The other half: a socket the engineer wrote down is not flagged --
    otherwise the warning is noise on every channel and gets ignored."""
    tampered = copy.deepcopy(plan)
    for channel in tampered["channels"]:
        channel["patch"]["stated"] = True
    _, warnings = _build_write_targets(tampered, True)
    assert not [w for w in warnings if "patch socket was not stated" in w]


def test_phantom_power_written_to_source_not_channel(plan):
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    # Overheads (channel 3) is phantom=True -- phantom must land on the
    # physical socket (/io/in/LCL/3/vph), never on the channel object.
    overheads = next(c for c in plan["channels"] if c["name"] == "Overheads")
    assert overheads["source"]["phantom"] is True
    assert overheads["patch"]["group"] == "LCL"
    socket = overheads["patch"]["sockets"][0]
    assert (f"/io/in/LCL/{socket}", "vph=1") in console.set_node_calls
    # Kick is not phantom -- must be written as an explicit 0, not skipped
    # (phantom is a stated fact either way in the plan, never left implicit).
    assert ("/io/in/LCL/1", "vph=0") in console.set_node_calls


def test_stereo_width_written_to_both_sockets_of_the_pair(plan):
    """Hand-built, and it has to be.

    A stereo channel is still a real thing a plan can describe -- two mono
    sockets linked into one strip -- and apply must write "ST" to BOTH of
    them (Festival_STANDALONE.snap: io.in.LCL.15/16.mode both == "ST").
    What no longer exists is a stereo INPUT: the input list dropped the
    column, so the deterministic compiler patches every row
    mono and cannot produce this shape. Compiling a fixture would test the
    absence of the behaviour instead of the behaviour."""
    stereo_plan = json.loads(json.dumps(plan))
    overheads = next(c for c in stereo_plan["channels"] if c["name"] == "Overheads")
    overheads["source"]["stereo"] = True
    overheads["patch"]["sockets"] = [3, 4]

    console = FakeConsole(state=_seed_all(stereo_plan))
    apply_plan(stereo_plan, console, dry_run=False)

    assert ("/io/in/LCL/3", "mode=ST") in console.set_node_calls
    assert ("/io/in/LCL/4", "mode=ST") in console.set_node_calls
    # Kick (channel 1) is mono -- "M", single socket.
    assert ("/io/in/LCL/1", "mode=M") in console.set_node_calls


def test_bus_dca_and_mute_group_membership_written_to_bus_tags(plan):
    """A bus can be a DCA/mute-group member in its own right (confirmed against Festival_STANDALONE.snap: its MONITORS mute group
    holds busses, not channels), not just a destination channels send to.
    Same tags mechanism, same merge helper, as a channel's own membership
    -- there was no code path writing it at all until now, since the plan
    format itself had no dca/mute_group field on a bus entry."""
    tagged = json.loads(json.dumps(plan))
    tagged["busses"]["FX"]["dca"] = ["FX"]
    tagged["busses"]["FX"]["mute_group"] = ["Vocals"]  # any declared group

    console = FakeConsole(state=_seed_all(tagged))
    fx_idx = tagged["busses"]["FX"]["index"]
    # Not seeded by _seed_all: the compiled FIXTURE has no bus-level
    # dca/mute_group, so it doesn't know to seed this address -- same
    # reason test_dca_and_mute_group_tags_merged_on_apply seeds /ch/7/tags
    # by hand rather than relying on _seed_all for its injected case.
    console.state[f"/bus/{fx_idx}/tags"] = ("", "s")
    apply_plan(tagged, console, dry_run=False)

    fx_dca_idx = tagged["dcas"]["FX"]["index"]
    vocals_mgrp_idx = tagged["mute_groups"]["Vocals"]["index"]
    # Two tokens -> comma-joined -> set_param, not set_node (same reason
    # as a channel's tags: comma is the node-command's own separator).
    expected = f"#D{fx_dca_idx},#M{vocals_mgrp_idx}"
    assert (f"/bus/{fx_idx}/tags", expected, "s") in console.set_param_calls


def test_bus_membership_in_an_undeclared_group_is_warned_not_written(plan):
    tagged = json.loads(json.dumps(plan))
    tagged["busses"]["FX"]["dca"] = ["No Such DCA"]

    console = FakeConsole(state=_seed_all(tagged))
    result = apply_plan(tagged, console, dry_run=False)

    fx_idx = tagged["busses"]["FX"]["index"]
    assert not any(a == f"/bus/{fx_idx}/tags" for a, *_ in console.set_param_calls)
    assert not any(a == f"/bus/{fx_idx}/tags" for a, _ in console.set_node_calls)
    assert any("No Such DCA" in w and "has no console index" in w for w in result.warnings)


def test_a_bus_destination_type_apply_cannot_write_is_warned_not_dropped(plan):
    """"matrix" is a legal destination type in the schema (a bus feeding a
    Matrix is a real signal path) but there is no confirmed console
    address for it -- an earlier change.
    Before this, a bus with that destination type silently produced no
    write at all and no warning: it fell through every branch of an
    if/elif chain that only handled "main" and "dedicated_output"."""
    matrixed = json.loads(json.dumps(plan))
    matrixed["busses"]["FX"]["destination"] = {"type": "matrix", "index": 1}

    console = FakeConsole(state=_seed_all(matrixed))
    result = apply_plan(matrixed, console, dry_run=False)

    fx_idx = matrixed["busses"]["FX"]["index"]
    assert not any(a.startswith(f"/bus/{fx_idx}/main") for a, _ in console.set_node_calls)
    assert any("matrix" in w and "no confirmed way to write it" in w for w in result.warnings)


def test_phantom_power_not_written_for_ungrounded_group(rows_and_cf_with_usb_phantom):
    plan = rows_and_cf_with_usb_phantom
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert not any("vph" in c for _, c in console.set_node_calls)
    assert any("no confirmed phantom-power address" in w for w in result.warnings)


@pytest.fixture
def rows_and_cf_with_usb_phantom():
    return compiled("usb_phantom")


def test_high_pass_written_only_when_stated(plan):
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    # Kick has hpf_hz=80 (smallband.md's drums rule).
    assert ("/ch/1/flt", "lc=1") in console.set_node_calls
    assert ("/ch/1/flt", "lcf=80.0") in console.set_node_calls
    # Playback (channel 9, misc category) has no processing rule -- no
    # flt writes should exist for it at all.
    assert not any(a.startswith("/ch/9/flt") for a, _ in console.set_node_calls)


def test_dca_and_mute_group_tags_merged_on_apply(plan):
    console = FakeConsole(state=_seed_all(plan))
    # Seed Lead Vox's tags with an unrelated tag to prove it survives.
    console.state["/ch/7/tags"] = ("CUSTOM", "s")
    result = apply_plan(plan, console, dry_run=False)
    lead_vox = next(c for c in plan["channels"] if c["name"] == "Lead Vox")
    assert lead_vox["dca"] == ["Vocals"]
    assert lead_vox["mute_group"] == ["Vocals"]
    vocals_dca_index = plan["dcas"]["Vocals"]["index"]
    vocals_mgrp_index = plan["mute_groups"]["Vocals"]["index"]
    # tags values are comma-joined ("CUSTOM,#D3,#M1"), and a comma is the
    # node-command's own pair separator -- this falls back to set_param
    # (unacked), which is exactly why readback verification below is what
    # actually proves it landed, not an ack.
    expected = f"CUSTOM,#D{vocals_dca_index},#M{vocals_mgrp_index}"
    assert ("/ch/7/tags", expected, "s") in console.set_param_calls
    tags_record = next(w for w in result.writes if w.address == "/ch/7/tags")
    assert tags_record.method == "param"
    assert tags_record.status == "match"


def test_bus_sends_written_with_console_bus_index(plan):
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/ch/1/send/{drums_idx}", "on=1") in console.set_node_calls
    assert (f"/ch/1/send/{drums_idx}", "mode=POST") in console.set_node_calls


def test_bus_routes_to_main(plan):
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/bus/{drums_idx}/main/1", "on=1") in console.set_node_calls


def test_bus_routes_to_a_stated_main_index(plan):
    # Built by hand per the contract (a missing index means default to 1,
    # tested above).
    #
    # Both keys are set deliberately. `apply` reads `destinations` (the
    # list) and only falls back to the singular `destination`
    # when that is absent, so setting the singular alone changes nothing.
    # Until an earlier change this test set only `destination` and still passed --
    # because the compiler happened to put the *same dict object* in both
    # places and `copy.deepcopy` preserved that aliasing. Reading the plan
    # from a file (as every real caller does, and as this test now does)
    # splits them, which is what exposed it. The plan format has both
    # keys; a test about routing should say what it means in the one
    # `apply` actually reads.
    plan = copy.deepcopy(plan)
    plan["busses"]["Drums"]["destination"]["index"] = 2
    plan["busses"]["Drums"]["destinations"][0]["index"] = 2
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/bus/{drums_idx}/main/2", "on=1") in console.set_node_calls
    assert not any(a == f"/bus/{drums_idx}/main/1" for a, _ in console.set_node_calls)


def _with_factory_bus_mains(plan: dict) -> dict:
    """`_seed_all(plan)` plus every planned bus's direct Main routes as a
    factory WING ships them: bus 1-8 on no Main, bus 9-16 on
    Main 1 only -- the reading counted on all three initialized captures."""
    from atoo import console_facts
    state = dict(_seed_all(plan))
    for entry in plan["busses"].values():
        for m in range(1, 5):
            state[f"/bus/{entry['index']}/main/{m}/on"] = (
                console_facts.factory_bus_main_on(entry["index"], m), "i")
    return state


def test_a_monitor_bus_on_9_16_is_taken_off_main_1(plan):
    """A factory WING ships bus 9-16 on Main 1, and apply used
    to write only the Mains a bus lists -- so a monitor bus the plan puts
    on bus 9 reached the PA as well. The plan's silence is now WRITTEN."""
    plan = copy.deepcopy(plan)
    plan["busses"]["Monitor 1"]["index"] = 9
    assert not any(d["type"] == "main" for d in plan["busses"]["Monitor 1"]["destinations"])
    console = FakeConsole(state=_with_factory_bus_mains(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert [console.state[f"/bus/9/main/{m}/on"][0] for m in range(1, 5)] == [0, 0, 0, 0]
    main_1 = next(w for w in result.writes if w.address == "/bus/9/main/1/on")
    assert (main_1.prior_value, main_1.intended_value, main_1.status) == (1, 0, "match")
    assert "the desk ships bus 9-16 on it" in main_1.description


def test_a_bus_routed_to_main_2_on_9_16_is_off_main_1(plan):
    """The listed Main goes ON; the factory's Main 1 goes OFF rather than
    doubling it; 3 and 4 are written OFF too."""
    plan = copy.deepcopy(plan)
    plan["busses"]["Drums"]["index"] = 10
    plan["busses"]["Drums"]["destination"]["index"] = 2
    plan["busses"]["Drums"]["destinations"][0]["index"] = 2
    console = FakeConsole(state=_with_factory_bus_mains(plan))
    apply_plan(plan, console, dry_run=False)
    assert [console.state[f"/bus/10/main/{m}/on"][0] for m in range(1, 5)] == [0, 1, 0, 0]


def test_a_bus_writes_each_main_once_on_or_off(plan):
    """Before `_dedupe_by_address`, which keeps the first write for an
    address and would hide an OFF also built for the listed Main."""
    from atoo.apply import _bus_write_targets
    targets = _bus_write_targets(plan, {}, {}, [], True)
    drums_idx = plan["busses"]["Drums"]["index"]
    values = {}
    for t in targets:
        if t.address.startswith(f"/bus/{drums_idx}/main/"):
            assert t.address not in values, t.address
            values[t.address] = t.compute_value(None)
    assert values == {f"/bus/{drums_idx}/main/{m}/on": (1 if m == 1 else 0) for m in range(1, 5)}


def test_factory_bus_main_routing_matches_the_initialized_capture():
    """The fact apply relies on, checked against the capture it was counted
    on (a console-runs capture, not a living example bundle)."""
    from atoo import console_facts
    snap = json.loads((FIXTURES / "console-runs" / "Initialized-Compact.snap").read_text())

    def find_bus(node):
        if isinstance(node, dict):
            if isinstance(node.get("bus"), dict) and "16" in node["bus"]:
                return node["bus"]
            for value in node.values():
                found = find_bus(value)
                if found:
                    return found
        return None

    busses = find_bus(snap)
    for n in range(1, console_facts.CAPACITY["bus"] + 1):
        for m in range(1, console_facts.CAPACITY["main"] + 1):
            assert int(busses[str(n)]["main"][str(m)]["on"]) == console_facts.factory_bus_main_on(n, m), (n, m)


def test_bus_mono_width_written_when_stated(plan):
    plan = copy.deepcopy(plan)
    plan["busses"]["Drums"]["mono"] = True
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/bus/{drums_idx}", "busmono=1") in console.set_node_calls


def test_bus_mono_width_false_writes_zero_not_skipped(plan):
    # False is a real stated value ("make this stereo"), not "unstated" --
    # only None means leave the console alone.
    plan = copy.deepcopy(plan)
    plan["busses"]["Drums"]["mono"] = False
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/bus/{drums_idx}", "busmono=0") in console.set_node_calls


def test_bus_mono_width_unstated_is_decided_and_written(plan):
    """The mono/stereo decision may not be left to whatever the
    desk had. An unstated width used to write nothing; now the fallback
    (`inferred.bus_width_fallback`) decides it -- Drums reaches only a
    Main, so no jack depends on it and it takes the factory stereo -- and
    apply writes that, exactly as verify's INFO says it will."""
    plan = copy.deepcopy(plan)
    plan["busses"]["Drums"]["mono"] = None
    state = _seed_all(plan)
    drums_idx = plan["busses"]["Drums"]["index"]
    state[f"/bus/{drums_idx}/busmono"] = (-1, "i")
    console = FakeConsole(state=state)
    apply_plan(plan, console, dry_run=False)
    assert (f"/bus/{drums_idx}", "busmono=0") in console.set_node_calls
    # ...on a copy: the caller's plan is not rewritten underneath it.
    assert plan["busses"]["Drums"]["mono"] is None


def test_bus_color_and_icon_written_when_stated(plan):
    plan = copy.deepcopy(plan)
    plan["busses"]["Drums"]["col"] = 9
    plan["busses"]["Drums"]["icon"] = 200
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/bus/{drums_idx}", "col=9") in console.set_node_calls
    assert (f"/bus/{drums_idx}", "icon=200") in console.set_node_calls


def test_bus_color_and_icon_not_written_when_unstated(plan):
    assert plan["busses"]["Drums"].get("col") is None
    assert plan["busses"]["Drums"].get("icon") is None
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert not any("col=" in c or "icon=" in c for _, c in console.set_node_calls)


def test_channel_color_and_icon_written_when_stated(plan):
    plan = copy.deepcopy(plan)
    plan["channels"][0]["col"] = 9
    plan["channels"][0]["icon"] = 200
    n = plan["channels"][0]["channel"]
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert (f"/ch/{n}", "col=9") in console.set_node_calls
    assert (f"/ch/{n}", "icon=200") in console.set_node_calls


def test_channel_color_and_icon_not_written_when_unstated(plan):
    assert plan["channels"][0].get("col") is None
    assert plan["channels"][0].get("icon") is None
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert not any("col=" in c or "icon=" in c for _, c in console.set_node_calls)


def test_bus_routes_to_main_and_a_dedicated_output_at_once(plan):
    # An earlier change, Festival_STANDALONE.snap's real finding: VOCALS bus routes
    # to Main 1 AND has a dedicated output tap at the same time.
    tampered = copy.deepcopy(plan)
    drums_idx = tampered["busses"]["Drums"]["index"]
    tampered["busses"]["Drums"]["destinations"] = [
        {"type": "main", "index": 1},
        {"type": "dedicated_output", "label": "IEM tap",
         "socket": {"group": "LCL", "sockets": [21]},
         "sockets": [{"group": "LCL", "sockets": [21]}]},
    ]
    console = FakeConsole(state=_seed_all(tampered))
    apply_plan(tampered, console, dry_run=False)
    assert (f"/bus/{drums_idx}/main/1", "on=1") in console.set_node_calls
    assert ("/io/out/LCL/21", "grp=BUS") in console.set_node_calls
    # A bus's single physical socket carries its "L"/mono slot,
    # 2*index - 1, not the bus's own declared index.
    assert ("/io/out/LCL/21", f"in={2 * drums_idx - 1}") in console.set_node_calls


def test_bus_dedicated_output_fans_out_to_several_sockets_at_once(plan):
    # An earlier change, TOURING_260821_MIX.snap's real finding: a single
    # dedicated output tap fanning out to more than one physical jack.
    tampered = copy.deepcopy(plan)
    drums_idx = tampered["busses"]["Drums"]["index"]
    tampered["busses"]["Drums"]["destinations"] = [{
        "type": "dedicated_output", "label": "Multi tap",
        "socket": {"group": "LCL", "sockets": [21]},
        "sockets": [{"group": "LCL", "sockets": [21]}, {"group": "A", "sockets": [3]}],
    }]
    console = FakeConsole(state=_seed_all(tampered))
    apply_plan(tampered, console, dry_run=False)
    # Each is its OWN one-socket clause, so each independently
    # gets the bus's "L"/mono slot (2*index - 1) -- a genuine duplicate
    # fan-out to two unrelated jacks, not one stereo pair split across
    # them (see test_bus_routes_to_dedicated_output for that case).
    assert ("/io/out/LCL/21", "grp=BUS") in console.set_node_calls
    assert ("/io/out/LCL/21", f"in={2 * drums_idx - 1}") in console.set_node_calls
    assert ("/io/out/A/3", "grp=BUS") in console.set_node_calls
    assert ("/io/out/A/3", f"in={2 * drums_idx - 1}") in console.set_node_calls


def test_bus_routes_to_dedicated_output(plan):
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    monitor_idx = plan["busses"]["Monitor 1"]["index"]
    # Monitor 1 is routed to LCL 3-4 in smallband.md -- ONE clause with two
    # sockets, so LCL 3 is this bus's "L" slot (2*index - 1) and LCL 4 is
    # "R" (2*index), an earlier change.
    assert ("/io/out/LCL/3", "grp=BUS") in console.set_node_calls
    assert ("/io/out/LCL/3", f"in={2 * monitor_idx - 1}") in console.set_node_calls
    assert ("/io/out/LCL/4", "grp=BUS") in console.set_node_calls
    assert ("/io/out/LCL/4", f"in={2 * monitor_idx}") in console.set_node_calls


def test_main_output_resolved_and_applied(plan):
    # smallband.md's "Main" output entry -> Local outputs 1-2. The plan's
    # kind/index (not yet emitted by compiler.py at the time this was
    # written -- added by hand per the contract) says which internal
    # source feeds it: MAIN index 1 (Festival_STANDALONE.snap-confirmed
    # convention), unlike a bus's dedicated_output which already knows
    # its own source identity.
    plan = copy.deepcopy(plan)
    plan["outputs"]["Main"]["kind"] = "main"
    plan["outputs"]["Main"]["index"] = 1
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    # Main index 1's "L" slot (2*1 - 1) happens to equal its own index --
    # the coincidence that hid an earlier change until a bus/Main/Matrix other
    # than the first was used in a real apply.
    assert ("/io/out/LCL/1", "grp=MAIN") in console.set_node_calls
    assert ("/io/out/LCL/1", "in=1") in console.set_node_calls
    assert ("/io/out/LCL/2", "grp=MAIN") in console.set_node_calls
    assert ("/io/out/LCL/2", "in=2") in console.set_node_calls


def test_matrix_output_resolved_and_applied(matrix_with_socket_plan):
    # Confirmed real value (Festival_STANDALONE.snap): MTX/9 -- kind
    # "matrix" + index 9 written the same shape as Main, just grp=MTX.
    plan = matrix_with_socket_plan
    plan["outputs"]["Matrix"]["kind"] = "matrix"
    plan["outputs"]["Matrix"]["index"] = 9
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert ("/io/out/A/9", "grp=MTX") in console.set_node_calls
    # Single socket -> position 0 -> this Matrix's "L" slot,
    # 2*9 - 1 = 17, not the matrix's own declared index (9).
    assert ("/io/out/A/9", "in=17") in console.set_node_calls


def test_output_name_is_never_pattern_matched_only_kind_index(matrix_with_socket_plan):
    # An engineer's own Output naming (not literally "Main"/"Matrix") must
    # apply identically as long as kind+index are stated -- the plan's
    # kind/index is authoritative, not the name.
    plan = matrix_with_socket_plan
    plan["outputs"]["Matrix"]["kind"] = "main"
    plan["outputs"]["Matrix"]["index"] = 2
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert ("/io/out/A/9", "grp=MAIN") in console.set_node_calls
    # Main 2's "L" slot is 2*2 - 1 = 3, not 2.
    assert ("/io/out/A/9", "in=3") in console.set_node_calls


def test_matrix_output_not_applied_but_warned(plan):
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    # smallband.md's "Matrix" output entry has no stated socket, so
    # nothing to apply either way here -- confirm no /io/out write claims
    # to be Matrix's.
    assert not any(a.startswith("/io/out") and c == "grp=MTX" for a, c in console.set_node_calls)


def test_matrix_fed_by_main_writes_the_send_on_the_main(plan):
    # A matrix has no routing table of its own -- the feed is a
    # SEND on the SOURCE object. smallband.md's Matrix is fed from Main
    # (index 1), and the Matrix output itself is index 1 too (MX1).
    tampered = copy.deepcopy(plan)
    tampered["outputs"]["Matrix"]["kind"] = "matrix"
    tampered["outputs"]["Matrix"]["index"] = 1
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/main/1/send/MX1/on"].compute_value(None) == 1
    assert addresses["/main/1/send/MX1/lvl"].compute_value(None) == 0.0
    assert addresses["/main/1/send/MX1/pre"].compute_value(None) == 0
    assert not any("fed" in w for w in warnings)


def test_matrix_fed_by_a_bus_writes_the_send_on_that_bus(plan):
    tampered = copy.deepcopy(plan)
    tampered["outputs"]["Matrix"]["kind"] = "matrix"
    tampered["outputs"]["Matrix"]["index"] = 5
    drums_idx = tampered["busses"]["Drums"]["index"]
    tampered["outputs"]["Matrix"]["fed_by"] = {"type": "bus", "name": "Drums"}
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address for t in targets}
    assert f"/bus/{drums_idx}/send/MX5/on" in addresses
    assert f"/bus/{drums_idx}/send/MX5/lvl" in addresses
    assert f"/bus/{drums_idx}/send/MX5/pre" in addresses
    assert not any(a.startswith("/main/") and "/send/MX5/" in a for a in addresses)


def test_matrix_fed_by_an_undeclared_bus_warns_not_written(plan):
    tampered = copy.deepcopy(plan)
    tampered["outputs"]["Matrix"]["kind"] = "matrix"
    tampered["outputs"]["Matrix"]["index"] = 1
    tampered["outputs"]["Matrix"]["fed_by"] = {"type": "bus", "name": "No Such Bus"}
    targets, warnings = _build_write_targets(tampered, True)
    assert not any("/send/MX1/" in t.address for t in targets)
    assert any("No Such Bus" in w and "no console index" in w for w in warnings)


def test_a_main_output_never_writes_a_matrix_feed(plan):
    # Only a "matrix" kind has a feed to write -- a Main's own outputs
    # entry has no fed_by concept even if one were somehow present.
    tampered = copy.deepcopy(plan)
    del tampered["outputs"]["Matrix"]  # isolate: only smallband's Main entry left
    tampered["outputs"]["Main"]["kind"] = "main"
    tampered["outputs"]["Main"]["index"] = 1
    tampered["outputs"]["Main"]["fed_by"] = {"type": "bus", "name": "Drums"}
    targets, _ = _build_write_targets(tampered, True)
    assert not any("/send/MX" in t.address for t in targets)


def test_output_with_a_socket_but_no_kind_index_warns_not_guessed(matrix_with_socket_plan):
    # Has a resolved physical socket (AES50-A 9) but the plan states no
    # kind/index for it -- must warn, never guess an internal source from
    # the entry's name.
    plan = matrix_with_socket_plan
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert not any(a.startswith("/io/out/A/9") for a, _ in console.set_node_calls)
    assert any(
        "output 'Matrix'" in w and "not applied" in w and "kind+index" in w
        for w in result.warnings
    )


# --- --clean-output-sockets (opt-in, off by default) ---


def test_clean_output_sockets_none_by_default_touches_nothing_extra(plan):
    # smallband.md declares nothing at LCL 5 -- with clean_output_sockets
    # left at its default (None), a stray patch there must be left alone,
    # confirming this feature really is off unless explicitly turned on.
    state = _seed_all(plan)
    state["/io/out/LCL/5/grp"] = ("BUS", "s")
    state["/io/out/LCL/5/in"] = (9, "i")
    console = FakeConsole(state=state)
    apply_plan(plan, console, dry_run=False)
    assert not any(a == "/io/out/LCL/5" for a, _ in console.set_node_calls)


def test_clean_output_sockets_disconnects_an_undeclared_patch(plan):
    state = _seed_all(plan)
    state["/io/out/LCL/5/grp"] = ("BUS", "s")  # stray -- nothing in smallband.md routes here
    state["/io/out/LCL/5/in"] = (9, "i")
    console = FakeConsole(state=state)
    result = apply_plan(plan, console, dry_run=False, clean_output_sockets={"LCL": 6})
    assert ("/io/out/LCL/5", "grp=OFF") in console.set_node_calls
    assert [w.address for w in result.cleaned] == ["/io/out/LCL/5/grp"]
    assert result.cleaned[0].prior_value == "BUS"


def test_clean_output_sockets_leaves_a_declared_patch_alone(plan):
    # Monitor 1 (smallband.md) is declared at LCL 3-4 -- must never be
    # touched by cleaning, matching exactly what the plan itself would
    # already write there.
    monitor_idx = plan["busses"]["Monitor 1"]["index"]
    state = _seed_all(plan)
    state["/io/out/LCL/3/grp"] = ("BUS", "s")
    state["/io/out/LCL/3/in"] = (2 * monitor_idx - 1, "i")
    state["/io/out/LCL/4/grp"] = ("BUS", "s")
    state["/io/out/LCL/4/in"] = (2 * monitor_idx, "i")
    console = FakeConsole(state=state)
    apply_plan(plan, console, dry_run=False, clean_output_sockets={"LCL": 4})
    assert not any(a in ("/io/out/LCL/3", "/io/out/LCL/4") and c == "grp=OFF" for a, c in console.set_node_calls)


def test_clean_output_sockets_skips_a_socket_already_off(plan):
    state = _seed_all(plan)
    state["/io/out/LCL/5/grp"] = ("OFF", "s")
    console = FakeConsole(state=state)
    result = apply_plan(plan, console, dry_run=False, clean_output_sockets={"LCL": 6})
    assert not any(a == "/io/out/LCL/5" for a, _ in console.set_node_calls)
    assert result.cleaned == []


def test_clean_output_sockets_dry_run_previews_without_writing(plan):
    state = _seed_all(plan)
    state["/io/out/LCL/5/grp"] = ("BUS", "s")
    state["/io/out/LCL/5/in"] = (9, "i")
    console = FakeConsole(state=state)
    result = apply_plan(plan, console, dry_run=True, clean_output_sockets={"LCL": 6})
    assert console.set_node_calls == []
    assert [w.address for w in result.cleaned] == ["/io/out/LCL/5/grp"]


def test_apply_result_summary_reports_cleaned_sockets_separately():
    result = ApplyResult(dry_run=False, writes=[
        WriteRecord(
            address="/io/out/LCL/5/grp",
            description="--clean-output-sockets: LCL 5 disconnected (no bus or output in the plan routes here)",
            value_type="s", method="set_node", ack="OK", prior_value="BUS", intended_value="OFF",
            readback_value="OFF", status="match", timestamp="t",
        ),
    ])
    summary = result.summary()
    assert "1 undeclared output socket(s) disconnected" in summary
    assert "/io/out/LCL/5/grp: was 'BUS'" in summary


@pytest.fixture
def matrix_with_socket_plan():
    # Hand-built, deliberately: this fixture has to represent an output
    # whose physical socket is known but whose *internal source* is not,
    # and the compiler no longer produces that shape for a Matrix -- it
    # allocates a kind+index now (2026-09-10), which is why the matrix
    # output is applied rather than skipped. Compiling this fixture would
    # therefore test the opposite of what it is here to test. The shape
    # still occurs in the wild: any output entry the compiler could not
    # classify, and every plan written before allocation existed.
    return {
        "conventions_file": "x.md",
        "input_list": "x.csv",
        "channels": [],
        "dcas": {},
        "mute_groups": {},
        "busses": {},
        "outputs": {
            "Matrix": {
                "socket": {"group": "A", "sockets": [9]},
                "description": "fed from Main, routed to AES50-A output 9",
                "provenance": "Output: Matrix",
            }
        },
    }


def test_full_build_sets_fader_to_unity_and_mute_off_when_unstated(plan):
    # Job 3's reversal: a strip this plan builds gets a known starting
    # state so soundcheck can verify signal actually flows -- this is the
    # full-build case, not a mixing decision. smallband.md states no
    # starting level anywhere, so this exercises apply.py's own
    # documented DEFAULT (unity, unmuted), not a value the plan stated --
    # see test_bus_at_minus_6db_end_to_end below for the "stated" half.
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert ("/ch/1", "fdr=0.0") in console.set_node_calls
    assert ("/ch/1", "mute=0") in console.set_node_calls
    fdr_record = next(w for w in result.writes if w.address == "/ch/1/fdr")
    mute_record = next(w for w in result.writes if w.address == "/ch/1/mute")
    assert fdr_record.status == "match"
    assert fdr_record.intended_value == 0.0
    assert mute_record.status == "match"
    assert mute_record.intended_value == 0
    # And busses get the same default (2026-09-10 correction) -- a bus is
    # a strip this plan builds too, no less than a channel.
    drums_idx = plan["busses"]["Drums"]["index"]
    assert (f"/bus/{drums_idx}", "fdr=0.0") in console.set_node_calls
    assert (f"/bus/{drums_idx}", "mute=0") in console.set_node_calls


def test_set_fader_levels_false_never_touches_fader_or_mute(plan):
    # The append case (a console already in use mid-show): an existing
    # strip's fader/mute must never be touched by this tool -- channels,
    # busses, AND Main/Matrix outputs alike (all three write fdr/mute as
    # of the 2026-09-10 correction).
    plan = copy.deepcopy(plan)
    plan["outputs"]["Main"]["kind"] = "main"
    plan["outputs"]["Main"]["index"] = 1
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False, set_fader_levels=False)
    assert not any(c.startswith("fdr=") or c.startswith("mute=") for _, c in console.set_node_calls)
    assert not any(a.endswith("/fdr") or a.endswith("/mute") for a, _, _ in console.set_param_calls)
    assert not any(w.address.endswith("/fdr") or w.address.endswith("/mute") for w in result.writes)


def test_write_target_sends_a_stated_non_unity_fader_value():
    # The old "unity only" rule is gone (2026-09-10 correction, overruled
    # by the project owner): a WriteTarget carrying a STATED, non-unity
    # value is written like any other parameter, not rejected. What keeps
    # this module from mixing is no longer a value check here at all --
    # see _build_write_targets_only_writes_a_fader_the_plan_
    # states_or_the_default below for the structural guarantee that
    # replaced it.
    console = FakeConsole(state={"/ch/1/fdr": (-6.0, "f")})
    method, _ = _write_target(console, WriteTarget("/ch/1/fdr", "f", "bus starts at -10dB", lambda _: -10.0, 7), -10.0)
    assert method == "node"
    assert ("/ch/1", "fdr=-10.0") in console.set_node_calls


def test_write_target_can_send_mute_on_not_only_off():
    # Previously impossible under the unity-only rule (its guard rejected
    # ANY mute value other than 0) -- "start everything muted" needs
    # exactly this.
    console = FakeConsole(state={"/ch/1/mute": (0, "i")})
    _write_target(console, WriteTarget("/ch/1/mute", "i", "starts muted", lambda _: 1, 7), 1)
    assert ("/ch/1", "mute=1") in console.set_node_calls


def test_build_write_targets_only_writes_a_fader_the_plan_states_or_the_default(plan):
    # The structural guarantee that replaced the old value-whitelist
    # assertion (see the module docstring's fader/mute section): every
    # fdr/mute WriteTarget this function builds carries EITHER a value
    # copied straight from the corresponding plan entry's own
    # `fader`, or the documented default -- never anything else.
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["fader"] = {"fader_db": -17.0, "muted": True}
    targets, _ = _build_write_targets(tampered, True)
    fdr_target = next(t for t in targets if t.address == "/ch/1/fdr")
    mute_target = next(t for t in targets if t.address == "/ch/1/mute")
    assert fdr_target.compute_value(None) == -17.0
    assert mute_target.compute_value(None) == 1


# --- starting levels end to end: grammar -> plan -> the addresses apply writes ---


def test_bus_at_minus_6db_end_to_end():
    # The owner's own example ("setting busses at -6dB to give some
    # headroom during the show") -- a real WING address gets a real,
    # non-unity write, proving the unity-only rule would have made this
    # literally impossible to apply.
    plan = compiled("bus_minus6")
    assert plan["busses"]["Drums"]["fader"] == {"fader_db": -6.0, "muted": None}
    state = _seed_all(plan)
    drums_idx = plan["busses"]["Drums"]["index"]
    # _seed_all's own sentinel for a bus's fdr happens to BE -6.0 (a
    # coincidence with this test's own target value, not the point under
    # test) -- reseed with a value that's actually different so the write
    # is exercised rather than skipped as "already correct".
    state[f"/bus/{drums_idx}/fdr"] = (0.0, "f")
    console = FakeConsole(state=state)
    result = apply_plan(plan, console, dry_run=False)
    assert (f"/bus/{drums_idx}", "fdr=-6.0") in console.set_node_calls
    fdr_record = next(w for w in result.writes if w.address == f"/bus/{drums_idx}/fdr")
    assert fdr_record.status == "match"
    assert fdr_record.intended_value == -6.0


def test_starting_muted_channel_and_bus_end_to_end():
    plan = compiled("starting_muted")
    assert plan["channels"][0]["fader"] == {"fader_db": None, "muted": True}
    drums_idx = plan["busses"]["Drums"]["index"]
    state = _seed_all(plan)
    # Same sentinel-collision fix as test_bus_at_minus_6db_end_to_end --
    # _seed_all's mute sentinel (1) happens to equal this test's own
    # target (muted=True writes mute=1), so reseed with the OTHER value.
    state["/ch/1/mute"] = (0, "i")
    state[f"/bus/{drums_idx}/mute"] = (0, "i")
    console = FakeConsole(state=state)
    apply_plan(plan, console, dry_run=False)
    assert ("/ch/1", "mute=1") in console.set_node_calls
    assert (f"/bus/{drums_idx}", "mute=1") in console.set_node_calls
    # muted=True says nothing about the fader -- a separate statement, so
    # the unstated fader still falls back to this module's own default.
    assert ("/ch/1", "fdr=0.0") in console.set_node_calls


def test_neg_inf_fader_writes_the_wire_floor_end_to_end():
    plan = compiled("neg_inf")
    assert plan["channels"][0]["fader"]["fader_db"] == -144.0
    console = FakeConsole(state=_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert ("/ch/1", "fdr=-144.0") in console.set_node_calls


# --- direct-to-Main channel routing ---


@pytest.fixture
def host_plan():
    return compiled("host_main2")


def test_channel_route_writes_on_lvl_pre_for_the_stated_main(host_plan):
    console = FakeConsole(state=_seed_all(host_plan))
    result = apply_plan(host_plan, console, dry_run=False)
    host = next(c for c in host_plan["channels"] if c["name"] == "HOST")
    base = f"/{host['bank']}/{host['channel']}"
    written = {w.address: w for w in result.writes}
    assert written[f"{base}/main/2/on"].status == "match"
    assert written[f"{base}/main/2/on"].intended_value == 1
    assert written[f"{base}/main/2/lvl"].intended_value == 0.0
    assert written[f"{base}/main/2/pre"].intended_value == 0


def _with_factory_mains(plan: dict, state: dict | None = None) -> dict:
    """`state` plus every planned strip's direct Main routes as a factory
    WING ships them: Main 1 ON, 2-4 OFF, lvl 0, pre off -- the reading
    counted on every ch and aux strip of `Initialized-Compact.snap`."""
    state = dict(state if state is not None else _seed_all(plan))
    for ch in plan["channels"]:
        base = f"/{ch.get('bank', 'ch')}/{ch['channel']}"
        for m in range(1, 5):
            state[f"{base}/main/{m}/on"] = (1 if m == 1 else 0, "i")
            state[f"{base}/main/{m}/lvl"] = (0.0, "f")
            state[f"{base}/main/{m}/pre"] = (0, "i")
    return state


def test_channel_with_no_route_is_switched_off_every_main(plan):
    """2026-09-27, the festival click on the PA. `main_routes: []` means
    "reaches Main only through a mix bus, or not at all", and a factory
    WING has every strip on Main 1 -- so the plan's silence has to be
    WRITTEN as OFF, or the channel reaches Main directly as well. Before
    this, no `/ch/{n}/main/*` address was built at all, so a dry run
    reported nothing to change."""
    assert all(ch["main_routes"] == [] for ch in plan["channels"])  # or this is vacuous
    console = FakeConsole(state=_with_factory_mains(plan))
    result = apply_plan(plan, console, dry_run=False)
    written = {w.address: w for w in result.writes}
    for ch in plan["channels"]:
        base = f"/{ch.get('bank', 'ch')}/{ch['channel']}"
        for m in range(1, 5):
            assert written[f"{base}/main/{m}/on"].intended_value == 0, (base, m)
            assert console.state[f"{base}/main/{m}/on"][0] == 0, (base, m)
        # Main 1 really moved: it is the one the factory had ON.
        assert written[f"{base}/main/1/on"].prior_value == 1
        assert written[f"{base}/main/1/on"].status == "match"
        # An unlisted Main is switched off, not given a level or a tap.
        assert f"{base}/main/1/lvl" not in written
        assert f"{base}/main/1/pre" not in written


def test_channel_routed_to_main_1_stays_on_and_the_rest_go_off(host_plan):
    """The listed route is ON (with its level and tap, as before), every
    other Main is OFF, and Main 1 is written once, not once each way."""
    host = next(c for c in host_plan["channels"] if c["name"] == "HOST")
    host["main_routes"] = [{"index": 1}]
    base = f"/{host['bank']}/{host['channel']}"
    # The strip's own builder, BEFORE `_dedupe_by_address`: a dedupe
    # keeps the first write for an address, so it would hide an OFF that
    # was also built for the listed Main.
    targets = _channel_write_targets(host, {}, {}, {}, [], True)
    by_address = collections.Counter(t.address for t in targets)
    assert by_address[f"{base}/main/1/on"] == 1
    values = {t.address: t.compute_value(None) for t in targets
              if t.address.startswith(f"{base}/main/")}
    assert values == {
        f"{base}/main/1/on": 1, f"{base}/main/1/lvl": 0.0, f"{base}/main/1/pre": 0,
        f"{base}/main/2/on": 0, f"{base}/main/3/on": 0, f"{base}/main/4/on": 0,
    }


def test_channel_routed_to_main_2_is_taken_off_main_1(host_plan):
    """The an earlier change HOST shape: straight to Main 2. The factory's Main 1
    route is switched off rather than left doubling it."""
    console = FakeConsole(state=_with_factory_mains(host_plan))
    result = apply_plan(host_plan, console, dry_run=False)
    host = next(c for c in host_plan["channels"] if c["name"] == "HOST")
    base = f"/{host['bank']}/{host['channel']}"
    assert [console.state[f"{base}/main/{m}/on"][0] for m in range(1, 5)] == [0, 1, 0, 0]
    written = {w.address for w in result.writes}
    assert {f"{base}/main/{m}/on" for m in range(1, 5)} <= written


def test_an_aux_strip_is_switched_off_the_mains_it_does_not_list(aux_plan):
    """Aux strips ship on Main 1 too (all 8, on both initialized
    captures), so they get the same explicit OFF writes."""
    targets, _ = _build_write_targets(aux_plan, True)
    values = {t.address: t.compute_value(None) for t in targets
              if t.address.startswith("/aux/1/main/")}
    assert values == {f"/aux/1/main/{m}/on": 0 for m in range(1, 5)}


def test_the_main_count_comes_from_console_facts(plan, monkeypatch):
    """Four Mains is a fact of the desk (`CAPACITY["main"]`), read from
    there rather than hard-coded in the builder."""
    from atoo import console_facts
    monkeypatch.setitem(console_facts.CAPACITY, "main", 2)
    targets, _ = _build_write_targets(plan, True)
    base = f"/ch/{plan['channels'][0]['channel']}"
    assert {t.address for t in targets if t.address.startswith(f"{base}/main/")} == {
        f"{base}/main/1/on", f"{base}/main/2/on"}


def test_after_an_apply_a_dry_run_finds_the_mains_already_right(host_plan):
    console = FakeConsole(state=_with_factory_mains(host_plan))
    apply_plan(host_plan, console, dry_run=False)
    again = apply_plan(host_plan, console, dry_run=True)
    assert not [w for w in again.writes if "/main/" in w.address and w.would_change]


def test_undo_puts_main_1_back_on(plan, tmp_path):
    """The OFF writes are journalled like every other write, and undo
    reverses them: the factory Main 1 route comes back."""
    from atoo.undo import load_journal, undo_from_journal
    console = FakeConsole(state=_with_factory_mains(plan))
    path = tmp_path / "apply-journal.json"
    apply_plan(plan, console, dry_run=False, journal_path=str(path))
    base = f"/ch/{plan['channels'][0]['channel']}"
    assert console.state[f"{base}/main/1/on"][0] == 0
    # Only the Main routes: this FakeConsole does not model the
    # connectors' GET offset (`in/conn/in`), which undo's guard reads.
    mains = [f"/{ch.get('bank', 'ch')}/{ch['channel']}/main" for ch in plan["channels"]]
    result = undo_from_journal(load_journal(str(path)), console, dry_run=False,
                               only=mains)
    assert len(result.steps) == len(plan["channels"])  # Main 1 on each strip moved
    assert not result.refused and not result.failed
    for ch in plan["channels"]:
        b = f"/{ch.get('bank', 'ch')}/{ch['channel']}"
        assert [console.state[f"{b}/main/{m}/on"][0] for m in range(1, 5)] == [1, 0, 0, 0]


def test_release_puts_every_main_back_to_the_factory_routing(host_plan):
    """A released strip goes back to how the desk ships it -- Main 1 ON,
    2-4 OFF -- whatever the plan routed. HOST was on Main 2 only, so both
    halves move: Main 2 off, Main 1 back on."""
    host = next(c for c in host_plan["channels"] if c["name"] == "HOST")
    base = f"/{host['bank']}/{host['channel']}"
    targets = release_write_targets([host])
    values = {t.address: t.compute_value(None) for t in targets
              if t.address.startswith(f"{base}/main/")}
    assert values == {f"{base}/main/1/on": 1, f"{base}/main/2/on": 0,
                      f"{base}/main/3/on": 0, f"{base}/main/4/on": 0}


def test_no_address_is_written_twice_with_main_routes_listed(host_plan):
    """The an earlier change guarantee, over a plan that LISTS a direct route: the
    listed Main's `on` and the unlisted Mains' OFF never collide."""
    for index in (1, 2, 4):
        candidate = copy.deepcopy(host_plan)
        for ch in candidate["channels"]:
            ch["main_routes"] = [{"index": index}]
        targets, warnings = _build_write_targets(candidate, True)
        seen = collections.Counter(t.address for t in targets)
        assert not [a for a, n in seen.items() if n > 1], index
        # ...and not merely deduplicated after the fact.
        assert not [w for w in warnings if "/main/" in w and "disagree" in w], index


# --- aux strips ---


@pytest.fixture
def aux_plan():
    plan = compiled("aux")
    # "bank" isn't emitted by compiler.py yet -- built by hand per the
    # contract (aux.*'s "channel" field is the index WITHIN the aux bank,
    # same semantics as ch's, just a different bank).
    plan["channels"][0]["bank"] = "aux"
    return plan


def test_aux_strip_addressed_under_aux_not_ch(aux_plan):
    console = FakeConsole(state=_seed_all(aux_plan))
    apply_plan(aux_plan, console, dry_run=False)
    # "Stage Wedge" has a space -- routed through set_param, not set_node,
    # since a space in a Node Data command's value silently vanishes on
    # real hardware (confirmed 2026-09-16) rather than landing.
    assert ("/aux/1/name", "Stage Wedge", "s") in console.set_param_calls
    assert ("/aux/1/in/conn", "grp=LCL") in console.set_node_calls
    assert ("/aux/1/in/conn", "in=1") in console.set_node_calls
    assert not any(a.startswith("/ch/1") for a, _ in console.set_node_calls)


def test_name_with_space_verifies_correctly_end_to_end(aux_plan):
    # Not just "routed to set_param" (the test above) -- the whole
    # write-then-readback loop still has to report "match", the same
    # confidence any other write gets, with FakeConsole's state dict
    # simulating a console that actually stores what set_param sent.
    console = FakeConsole(state=_seed_all(aux_plan))
    result = apply_plan(aux_plan, console, dry_run=False)
    name_write = next(w for w in result.writes if w.address == "/aux/1/name")
    assert name_write.status == "match"
    assert name_write.readback_value == "Stage Wedge"


@pytest.mark.parametrize("value,expected", [
    ("Kick", "Kick"),                # no unsafe chars -- set_node is fine
    ("Drums Comp", None),            # space -- silently dropped by set_node (2026-09-16)
    ("A,B", None),                   # comma -- the command's own field delimiter
    ("A=B", None),                   # equals -- the command's own pair delimiter
])
def test_format_for_node_command_rejects_unsafe_string_values(value, expected):
    assert _format_for_node_command("s", value) == expected
    # Non-string types are never routed through this space/comma/equals
    # check -- a float or int WriteTarget's value never goes through
    # _format_for_node_command's string branch at all.
    assert _format_for_node_command("f", 1.5) == "1.5"


def test_aux_strip_has_no_flt_node_warns_and_is_not_written(aux_plan):
    console = FakeConsole(state=_seed_all(aux_plan))
    result = apply_plan(aux_plan, console, dry_run=False)
    assert aux_plan["channels"][0]["processing"]["hpf_hz"] == 100
    assert not any(a.startswith("/aux/1/flt") for a, _ in console.set_node_calls)
    assert any("aux 1" in w and "no flt node" in w for w in result.warnings)


def test_aux_strip_still_gets_starting_fader_and_mute(aux_plan):
    # fdr/mute are in the aux key list (unlike flt) -- Job 3's starting
    # state applies to an aux strip exactly as it does to a channel.
    console = FakeConsole(state=_seed_all(aux_plan))
    apply_plan(aux_plan, console, dry_run=False)
    assert ("/aux/1", "fdr=0.0") in console.set_node_calls
    assert ("/aux/1", "mute=0") in console.set_node_calls


def test_aux_strip_phantom_still_targets_the_physical_source(aux_plan):
    # Phantom/stereo mode live on /io/in/..., unaffected by bank.
    console = FakeConsole(state=_seed_all(aux_plan))
    apply_plan(aux_plan, console, dry_run=False)
    assert ("/io/in/LCL/1", "vph=0") in console.set_node_calls


def test_unrecognized_bank_warns_and_falls_back_to_ch(plan):
    # Seeded from the UNtampered plan on purpose: apply.py's fallback
    # means this must land at the exact same /ch/1/... addresses as a
    # plan with no bank field at all.
    console = FakeConsole(state=_seed_all(plan))
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["bank"] = "weird"
    result = apply_plan(tampered, console, dry_run=False)
    assert ("/ch/1", "name=Kick") in console.set_node_calls
    assert not any(a.startswith("/weird/1") for a, _ in console.set_node_calls)
    assert any("unrecognized bank" in w and "'weird'" in w for w in result.warnings)


# --- skip-no-change ---


def test_skips_write_when_value_already_matches(plan):
    state = _seed_all(plan)
    state["/ch/1/name"] = ("Kick", "s")  # already correct
    console = FakeConsole(state=state)
    result = apply_plan(plan, console, dry_run=False)
    record = next(w for w in result.writes if w.address == "/ch/1/name")
    assert record.status == "skipped_no_change"
    assert not any(a == "/ch/1" and c == "name=Kick" for a, c in console.set_node_calls)


# --- mismatch reporting ---


def test_mismatch_reported_with_expected_and_actual(plan):
    console = FakeConsole(state=_seed_all(plan))

    real_set_node = console.set_node

    def lying_set_node(address, command):
        reply = real_set_node(address, command)
        if address == "/ch/1" and command.startswith("name="):
            # Pretend the console silently stored something else.
            console.state["/ch/1/name"] = ("NotKick", "s")
        return reply

    console.set_node = lying_set_node
    result = apply_plan(plan, console, dry_run=False)
    mismatch = next(w for w in result.writes if w.address == "/ch/1/name")
    assert mismatch.status == "mismatch"
    assert mismatch.intended_value == "Kick"
    assert mismatch.readback_value == "NotKick"
    assert mismatch in result.mismatches
    assert "MISMATCH /ch/1/name" in result.summary()
    assert "Kick" in result.summary()
    assert "NotKick" in result.summary()


def test_console_error_ack_still_gets_readback_verified(plan):
    console = FakeConsole(state=_seed_all(plan))
    console.node_ack_overrides["/ch/1"] = OscReply(address="/*", typetag="s", args=["VALUE ERROR"])
    result = apply_plan(plan, console, dry_run=False)
    name_record = next(w for w in result.writes if w.address == "/ch/1/name")
    assert name_record.ack == "VALUE ERROR"
    # The write didn't actually land (state untouched by the overridden
    # set_node), so readback verification -- not the ack -- is what
    # correctly reports this as a mismatch/unreadable, never silently "ok"
    # because the ack alone was checked.
    assert name_record.status in ("mismatch", "unreadable")


def test_unreadable_baseline_is_not_written(plan):
    # No state seeded at all -- every get() returns NODE NOT FOUND.
    console = FakeConsole()
    result = apply_plan(plan, console, dry_run=False)
    assert console.set_node_calls == []
    assert console.set_param_calls == []
    assert all(w.status == "unreadable_skipped" for w in result.writes)


# --- journal ---


def test_journal_written_with_reversal_information(plan, tmp_path):
    state = _seed_all(plan)
    state["/ch/1/name"] = ("OldKickName", "s")
    console = FakeConsole(state=state)
    journal_path = tmp_path / "journal.json"
    apply_plan(plan, console, dry_run=False, journal_path=str(journal_path))
    payload = json.loads(journal_path.read_text())
    assert payload["dry_run"] is False
    entry = next(w for w in payload["writes"] if w["address"] == "/ch/1/name")
    assert entry["prior_value"] == "OldKickName"
    assert entry["intended_value"] == "Kick"
    assert entry["readback_value"] == "Kick"
    assert entry["status"] == "match"
    assert "timestamp" in entry


def test_journal_written_even_in_dry_run(plan, tmp_path):
    journal_path = tmp_path / "journal.json"
    apply_plan(plan, FakeConsole(), dry_run=True, journal_path=str(journal_path))
    payload = json.loads(journal_path.read_text())
    assert payload["dry_run"] is True
    assert len(payload["writes"]) > 0


def test_no_journal_file_written_when_path_omitted(plan, tmp_path):
    apply_plan(plan, FakeConsole(state=_seed_all(plan)), dry_run=False)
    assert list(tmp_path.iterdir()) == []


# --- ordering ---


def test_patch_ordered_before_phantom(plan):
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    addresses = [w.address for w in result.writes]
    patch_idx = addresses.index("/ch/3/in/conn/grp")
    phantom_addr = next(a for a in addresses if a.startswith("/io/in/") and a.endswith("/vph") and "/3/" in a)
    assert addresses.index(phantom_addr) > patch_idx


# ---------------------------------------------------------------------------
# hi-cut, tilt, trim, balance, invert, head-amp gain.
# Built with `_build_write_targets` directly (like the Matrix tests above)
# rather than through a full FakeConsole apply -- none of `plan`'s smallband
# fixture channels state these fields (compiler.py doesn't emit them yet,
# deliberately out of scope here), so `_seed_all` has nothing to pre-seed
# for them; a target's own `compute_value` is a pure function of the
# (irrelevant, for a literal target) prior value, so checking it directly is
# both simpler and exactly what "expected WriteTarget addresses/values"
# means.
# ---------------------------------------------------------------------------


def test_hi_cut_written_only_when_stated(plan):
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["hi_cut_hz"] = 8000.0
    targets, _ = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/ch/1/flt/hc"].compute_value(None) == 1
    assert addresses["/ch/1/flt/hcf"].compute_value(None) == 8000.0
    assert addresses["/ch/1/flt/hc"].stage == STAGE_PROCESSING
    # Playback (channel 9) states no hi-cut -- no flt/hc* writes for it.
    assert not any(a.startswith("/ch/9/flt/hc") for a in addresses)


def test_tilt_written_only_when_stated(plan):
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["tilt_db"] = -2.5
    targets, _ = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/ch/1/flt/tf"].compute_value(None) == 1
    assert addresses["/ch/1/flt/tilt"].compute_value(None) == -2.5
    assert not any(a.startswith("/ch/9/flt/tf") for a in addresses)


def test_trim_balance_invert_written_when_stated(plan):
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"].update(trim_db=6.0, balance_db=-3.0, invert=True)
    targets, _ = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/ch/1/in/set/trim"].compute_value(None) == 6.0
    assert addresses["/ch/1/in/set/bal"].compute_value(None) == -3.0
    assert addresses["/ch/1/in/set/inv"].compute_value(None) == 1
    assert addresses["/ch/1/in/set/trim"].stage == STAGE_PROCESSING


def test_invert_false_still_written_explicitly(plan):
    """Same "stated fact either way" rule as phantom power -- `invert:
    false` is a real, explicit statement, not the same as leaving it out."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["invert"] = False
    targets, _ = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/ch/1/in/set/inv"].compute_value(None) == 0


def test_new_processing_fields_produce_no_write_target_when_absent(plan):
    """The smallband fixture's own channels never state any of these six
    fields (compiler.py doesn't emit them) -- confirms the "only write
    what's stated" rule holds for all of them, the same way it already
    does for hpf_hz."""
    targets, _ = _build_write_targets(plan, True)
    addresses = {t.address for t in targets}
    for suffix in ("flt/hc", "flt/hcf", "flt/tf", "flt/tilt",
                   "in/set/trim", "in/set/bal", "in/set/inv"):
        assert not any(a.endswith(suffix) for a in addresses), suffix
    assert not any(a.endswith("/g") and a.startswith("/io/in/") for a in addresses)


def test_aux_strip_hi_cut_and_tilt_warn_combined_not_separately(aux_plan):
    """hpf_hz/hi_cut_hz/tilt_db all hit the same aux guard -- one combined
    warning naming every blocked filter, not a near-duplicate line per
    field (aux_plan's Stage Wedge already has hpf_hz=100 from
    conventions; hi-cut and tilt are added here by hand, same as bank)."""
    tampered = copy.deepcopy(aux_plan)
    tampered["channels"][0]["processing"]["hi_cut_hz"] = 8000.0
    tampered["channels"][0]["processing"]["tilt_db"] = 2.0
    targets, warnings = _build_write_targets(tampered, True)
    assert not any(a.startswith("/aux/1/flt") for a in (t.address for t in targets))
    aux_flt_warnings = [w for w in warnings if "aux 1" in w and "no flt node" in w]
    assert len(aux_flt_warnings) == 1
    assert "high-pass" in aux_flt_warnings[0]
    assert "hi-cut" in aux_flt_warnings[0]
    assert "tilt" in aux_flt_warnings[0]


def test_aux_strip_trim_balance_invert_still_write(aux_plan):
    """Unlike flt, `in/set/*` is confirmed present on both banks -- no
    guard, no warning."""
    tampered = copy.deepcopy(aux_plan)
    tampered["channels"][0]["processing"].update(trim_db=4.0, balance_db=1.5, invert=True)
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/aux/1/in/set/trim"].compute_value(None) == 4.0
    assert addresses["/aux/1/in/set/bal"].compute_value(None) == 1.5
    assert addresses["/aux/1/in/set/inv"].compute_value(None) == 1
    assert not any("in/set" in w for w in warnings)


def test_gain_resolves_to_the_physical_socket_from_the_channels_patch(plan):
    """Kick (channel 1) is patched to LCL 1 -- gain must land on
    `/io/in/LCL/1/g`, the physical socket, never `/ch/1/...`. Same stage
    (STAGE_PHANTOM) and same "depends on the patch write already having
    landed" reasoning as phantom power."""
    tampered = copy.deepcopy(plan)
    assert tampered["channels"][0]["patch"] == {"group": "LCL", "sockets": [1], "stated": False}
    tampered["channels"][0]["processing"]["gain_db"] = 30.0
    targets, _ = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    gain_target = addresses["/io/in/LCL/1/g"]
    assert gain_target.compute_value(None) == 30.0
    assert gain_target.stage == STAGE_PHANTOM
    assert not any(a.startswith("/ch/1/") and a.endswith("/g") for a in addresses)


def test_gain_warns_without_writing_for_a_group_outside_capable_groups(rows_and_cf_with_usb_phantom):
    """Mirrors `test_phantom_power_not_written_for_ungrounded_group` --
    same fixture (a channel patched to USB, which has no confirmed .vph
    OR .g address), same shape of assertion."""
    plan = rows_and_cf_with_usb_phantom
    plan["channels"][0]["processing"]["gain_db"] = 20.0
    console = FakeConsole(state=_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert not any(a.startswith("/io/in/USB") and a.endswith("/g") for a, _ in console.set_node_calls)
    assert any("no confirmed head-amp-gain address" in w for w in result.warnings)


# --- A dead connection aborts the whole run instead of
# recording hundreds of individually "unreadable" addresses ---


def test_write_target_raises_oserror_when_set_node_gets_a_socket_error_reply():
    """`_write_target` is the one place apply_plan()'s loop can catch a
    fatal connection loss -- a SOCKET_ERROR ack from set_node must come
    out as a plain OSError, not the soft "transport_error: ..." ack string
    an ordinary decode hiccup gets."""
    console = FakeConsole()
    console.node_ack_overrides["/ch/1"] = OscReply(
        address="/ch/1", typetag="SOCKET_ERROR", args=["OSError: [Errno 65] No route to host"],
    )
    target = WriteTarget(
        address="/ch/1/name", description="name", value_type="s",
        compute_value=lambda prior: "Kick", stage=STAGE_PROCESSING,
    )
    with pytest.raises(OSError, match="No route to host"):
        _write_target(console, target, "Kick")


def test_apply_plan_aborts_immediately_when_the_baseline_read_hits_a_socket_error(plan):
    """The very first address's baseline get() fails with a socket error
    -- the run must stop right there, not record it as "unreadable" and
    move on to the next of ~150 remaining targets. `/dca/1/name` is the
    real first target `_build_write_targets` produces for this plan
    (lowest stage) -- picked deliberately, not assumed, so `result.writes
    == []` is a fact about this test's setup, not a guess at iteration
    order."""
    console = FakeConsole(state=_seed_all(plan))
    console.get_overrides["/dca/1/name"] = (
        1, OscReply(address="/dca/1/name", typetag="SOCKET_ERROR", args=["OSError: [Errno 65] No route to host"]),
    )
    result = apply_plan(plan, console, dry_run=False)
    assert result.aborted is True
    assert "No route to host" in result.abort_reason
    assert result.writes == []
    assert console.set_node_calls == []
    assert console.set_param_calls == []


def test_apply_plan_aborts_on_a_socket_error_during_dry_run_too(plan):
    """A dead connection is just as fatal for a preview -- dry_run still
    reads a baseline for every address, so the same flood would happen
    there if this weren't checked before the dry_run branch."""
    console = FakeConsole(state=_seed_all(plan))
    console.get_overrides["/dca/1/name"] = (
        1, OscReply(address="/dca/1/name", typetag="SOCKET_ERROR", args=["OSError: [Errno 61] Connection refused"]),
    )
    result = apply_plan(plan, console, dry_run=True)
    assert result.aborted is True
    assert result.writes == []


def test_apply_plan_aborts_when_a_write_itself_raises_oserror(aux_plan):
    """"Stage Wedge" routes through set_param (a name with a space) --
    simulating set_param's own sendto() failing must abort the run the
    same way a socket-error reply from set_node does, not crash out of
    apply_plan() uncaught."""
    console = FakeConsole(state=_seed_all(aux_plan))
    console.set_param_raises = OSError("[Errno 65] No route to host")
    result = apply_plan(aux_plan, console, dry_run=False)
    assert result.aborted is True
    assert "No route to host" in result.abort_reason


def test_apply_plan_aborts_when_the_readback_after_a_write_hits_a_socket_error(plan):
    """The write itself (set_node) succeeds -- the connection dies on the
    very next call, the readback. Distinct from the baseline-read case:
    this needs the override to fire on the SECOND get() call for the
    address, not the first, which is exactly what get_overrides' call
    counter is for."""
    console = FakeConsole(state=_seed_all(plan))
    console.get_overrides["/ch/1/name"] = (
        2, OscReply(address="/ch/1/name", typetag="SOCKET_ERROR", args=["OSError: [Errno 65] No route to host"]),
    )
    result = apply_plan(plan, console, dry_run=False)
    assert result.aborted is True
    assert "No route to host" in result.abort_reason
    # The write was actually sent before the connection died on readback --
    # but with no confirmed outcome, so it must not appear in the journal
    # as if it were verified one way or the other.
    assert ("/ch/1", "name=Kick") in console.set_node_calls
    assert not any(w.address == "/ch/1/name" for w in result.writes)


def test_apply_result_summary_leads_with_the_abort_reason_not_buried_in_noise():
    result = ApplyResult(
        dry_run=False, writes=[], aborted=True,
        abort_reason="OSError: [Errno 65] No route to host",
    )
    summary = result.summary()
    assert summary.startswith("ABORTED:")
    assert "No route to host" in summary


# ---------------------------------------------------------------------------
# the parametric EQ, on every strip class that has one.
# Same `_build_write_targets` approach as phase 1 above, and for the same
# reason -- no fixture plan states an EQ, so the fields are added by hand.
#
# What these are really guarding is the band-count asymmetry. A channel's
# EQ node stops at band 4 and a bus's runs to 6; write `/ch/1/eq/5f` and
# the console does not complain, it simply does not have that leaf, and
# the band the engineer asked for is missing at soundcheck with nothing
# anywhere saying so.
# ---------------------------------------------------------------------------


def _eq(bands, **kw):
    return {"bands": bands, **kw}


def test_channel_eq_bands_write_to_the_expected_leaves(plan):
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([
        {"band": "low", "freq_hz": 120.0, "gain_db": -3.0, "q": 0.7, "shape": "SHV"},
        {"band": "2", "freq_hz": 2500.0, "gain_db": 2.5, "q": 1.4},
        {"band": "high", "freq_hz": 9000.0, "gain_db": 1.5},
    ], model="SOUL")
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/ch/1/eq/lf"].compute_value(None) == 120.0
    assert addresses["/ch/1/eq/lg"].compute_value(None) == -3.0
    assert addresses["/ch/1/eq/lq"].compute_value(None) == 0.7
    assert addresses["/ch/1/eq/leq"].compute_value(None) == "SHV"
    assert addresses["/ch/1/eq/2f"].compute_value(None) == 2500.0
    assert addresses["/ch/1/eq/2g"].compute_value(None) == 2.5
    assert addresses["/ch/1/eq/2q"].compute_value(None) == 1.4
    assert addresses["/ch/1/eq/hf"].compute_value(None) == 9000.0
    assert addresses["/ch/1/eq/hg"].compute_value(None) == 1.5
    assert addresses["/ch/1/eq/mdl"].compute_value(None) == "SOUL"
    # Nothing was stated for band 2's shape or the high band's Q -- and
    # nothing is written for them, the same "only what's stated" rule the
    # rest of processing follows.
    assert "/ch/1/eq/2eq" not in addresses
    assert "/ch/1/eq/hq" not in addresses
    assert addresses["/ch/1/eq/lf"].stage == STAGE_PROCESSING
    assert warnings == [] or not any("EQ" in w for w in warnings)


def test_stating_any_eq_band_turns_the_eq_on(plan):
    """Same precedent hpf_hz set with flt.lc: asking for a value is asking
    for it to be in circuit."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([{"band": "1", "gain_db": -2.0}])
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    assert addresses["/ch/1/eq/on"].compute_value(None) == 1


def test_eq_on_false_is_honoured_over_the_implied_on(plan):
    """"These are the settings, but start it bypassed" is a real request."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([{"band": "1", "gain_db": -2.0}], on=False)
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    assert addresses["/ch/1/eq/on"].compute_value(None) == 0
    assert addresses["/ch/1/eq/1g"].compute_value(None) == -2.0


def test_no_eq_stated_writes_nothing_to_the_eq_node(plan):
    addresses = {t.address for t in _build_write_targets(plan, True)[0]}
    assert not any("/eq/" in a for a in addresses)


def test_channel_eq_band_five_is_refused_because_a_channel_has_four(plan):
    """The whole point of the band-count fact. A bus has band 5; a channel
    does not, and `/ch/1/eq/5f` is a leaf the firmware never answers."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([
        {"band": "5", "freq_hz": 5000.0, "gain_db": 3.0},
        {"band": "4", "freq_hz": 4000.0, "gain_db": 1.0},
    ])
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address for t in targets}
    assert "/ch/1/eq/5f" not in addresses
    assert "/ch/1/eq/4f" in addresses          # the valid band still lands
    assert any("band '5'" in w and "not written" in w for w in warnings)


def test_channel_shelf_shape_cut_is_refused_but_an_aux_takes_it(plan, aux_plan):
    """Four tiers, not one: `ch.eq.leq` is list [PEQ, SHV], `aux.eq.leq`
    is list [PEQ, SHV, CUT]. The plan schema holds their union because one
    CHANNEL_SCHEMA serves both banks -- this is where the bank decides."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([{"band": "low", "shape": "CUT"}])
    targets, warnings = _build_write_targets(tampered, True)
    assert "/ch/1/eq/leq" not in {t.address for t in targets}
    assert any("CUT" in w and "ch strip" in w for w in warnings)

    aux = copy.deepcopy(aux_plan)
    aux["channels"][0]["processing"]["eq"] = _eq([{"band": "low", "shape": "CUT"}])
    aux_targets, aux_warnings = _build_write_targets(aux, True)
    n = aux["channels"][0]["channel"]
    assert {t.address: t for t in aux_targets}[f"/aux/{n}/eq/leq"].compute_value(None) == "CUT"
    assert not any("CUT" in w for w in aux_warnings)


def test_shape_on_a_parametric_band_is_refused(plan):
    """Only the low and high bands have a filter-type leaf at all -- a
    numbered band is always a bell."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([{"band": "3", "shape": "SHV", "gain_db": 1.0}])
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address for t in targets}
    assert "/ch/1/eq/3g" in addresses
    assert not any(a.startswith("/ch/1/eq/3") and a.endswith("eq") for a in addresses)
    assert any("filter-type leaf" in w for w in warnings)


def test_channel_eq_model_mach4_is_a_channel_only_model(plan, aux_plan):
    """`ch.eq.mdl` has MACH4 and no PIA; an aux has neither."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([], model="MACH4")
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    assert addresses["/ch/1/eq/mdl"].compute_value(None) == "MACH4"

    aux = copy.deepcopy(aux_plan)
    aux["channels"][0]["processing"]["eq"] = _eq([], model="MACH4")
    aux_targets, aux_warnings = _build_write_targets(aux, True)
    assert not any(a.address.endswith("/eq/mdl") for a in aux_targets)
    assert any("MACH4" in w and "aux strip" in w for w in aux_warnings)


def test_a_band_stated_twice_writes_the_first_and_warns(plan):
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([
        {"band": "1", "gain_db": 2.0},
        {"band": "1", "gain_db": -6.0},
    ])
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses["/ch/1/eq/1g"].compute_value(None) == 2.0
    assert len([t for t in targets if t.address == "/ch/1/eq/1g"]) == 1
    assert any("more than once" in w for w in warnings)


def test_eq_mix_is_written_and_counts_as_stating_the_eq(plan):
    """`eq.mix` is the wet/dry blend, distinct from `eq.on`: 0% keeps the
    curve and takes it out of circuit, `on: false` bypasses the node."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([], mix_pct=60.0)
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    assert addresses["/ch/1/eq/mix"].compute_value(None) == 60.0
    assert addresses["/ch/1/eq/on"].compute_value(None) == 1


def test_bus_eq_reaches_band_six_and_its_own_tilt(plan):
    """A bus has the six numbered bands a channel does not, and its tilt
    lives on the EQ node (`bus.{n}.eq.tilt`), not on a `flt` one -- no
    strip except `ch` has a `flt` node at all."""
    tampered = copy.deepcopy(plan)
    idx = tampered["busses"]["Drums"]["index"]
    tampered["busses"]["Drums"]["processing"] = {
        "eq": _eq([
            {"band": "6", "freq_hz": 12000.0, "gain_db": -2.0},
            {"band": "low", "shape": "LR24", "freq_hz": 80.0},
        ], model="PIA"),
        "tilt_db": -1.5,
    }
    targets, warnings = _build_write_targets(tampered, True)
    addresses = {t.address: t for t in targets}
    assert addresses[f"/bus/{idx}/eq/6f"].compute_value(None) == 12000.0
    assert addresses[f"/bus/{idx}/eq/6g"].compute_value(None) == -2.0
    assert addresses[f"/bus/{idx}/eq/leq"].compute_value(None) == "LR24"
    assert addresses[f"/bus/{idx}/eq/mdl"].compute_value(None) == "PIA"
    assert addresses[f"/bus/{idx}/eq/tilt"].compute_value(None) == -1.5
    assert addresses[f"/bus/{idx}/eq/on"].compute_value(None) == 1
    assert not any("EQ" in w for w in warnings)


def test_bus_eq_is_written_even_with_faders_suppressed(plan):
    """`--no-faders` is about not moving levels on a live desk. An EQ
    curve is a starting state like a name or a route, not a level."""
    tampered = copy.deepcopy(plan)
    idx = tampered["busses"]["Drums"]["index"]
    tampered["busses"]["Drums"]["processing"] = {"eq": _eq([{"band": "1", "gain_db": 1.0}])}
    addresses = {t.address for t in _build_write_targets(tampered, False)[0]}
    assert f"/bus/{idx}/eq/1g" in addresses


def test_main_and_matrix_eq_land_on_the_internal_strip(plan):
    """smallband carries both a Main and a Matrix with kind+index, so one
    fixture covers the two strip classes that share the six-band node."""
    tampered = copy.deepcopy(plan)
    written = {}
    for name, entry in tampered["outputs"].items():
        if entry.get("kind") and entry.get("index"):
            entry["processing"] = {"eq": _eq([{"band": "5", "freq_hz": 6000.0, "gain_db": -1.0}])}
            written[name] = (entry["kind"], entry["index"])
    assert written, "fixture has no kind+index output to put an EQ on"
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    for kind, index in written.values():
        node = "/main" if kind == "main" else "/mtx"
        assert addresses[f"{node}/{index}/eq/5f"].compute_value(None) == 6000.0
        assert addresses[f"{node}/{index}/eq/on"].compute_value(None) == 1


# ---------------------------------------------------------------------------
# the PreSend EQ (`ch.{n}.peq`) -- a channel's SECOND EQ, three
# bells at a different tap point. Channel-only, like `flt`.
#
# It is in this PR because `presets.py` already allow-lists `peq.` under
# the EQ scope, so a `.chn` export carries one: without a field, a plan
# could name a preset whose PreSend EQ it has no way to state or show.
# ---------------------------------------------------------------------------


def test_presend_eq_writes_to_the_peq_node(plan):
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["presend_eq"] = {
        "bands": [{"band": "2", "freq_hz": 900.0, "gain_db": -3.0, "q": 1.2}],
    }
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    assert addresses["/ch/1/peq/2f"].compute_value(None) == 900.0
    assert addresses["/ch/1/peq/2g"].compute_value(None) == -3.0
    assert addresses["/ch/1/peq/2q"].compute_value(None) == 1.2
    assert addresses["/ch/1/peq/on"].compute_value(None) == 1
    assert addresses["/ch/1/peq/2f"].stage == STAGE_PROCESSING


def test_presend_eq_and_the_main_eq_are_separate_nodes(plan):
    """Both stated on one channel must land on `eq/*` and `peq/*`
    respectively -- the bug this guards against is one overwriting the
    other because they share a band vocabulary."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["eq"] = _eq([{"band": "2", "gain_db": 5.0}])
    tampered["channels"][0]["processing"]["presend_eq"] = {"bands": [{"band": "2", "gain_db": -5.0}]}
    addresses = {t.address: t for t in _build_write_targets(tampered, True)[0]}
    assert addresses["/ch/1/eq/2g"].compute_value(None) == 5.0
    assert addresses["/ch/1/peq/2g"].compute_value(None) == -5.0


def test_presend_eq_has_no_fourth_band(plan):
    """Three bells, and the peq node has no shelf bands at all -- so
    neither "4" nor "low" is a thing to ask for."""
    tampered = copy.deepcopy(plan)
    tampered["channels"][0]["processing"]["presend_eq"] = {
        "bands": [{"band": "4", "gain_db": 1.0}, {"band": "low", "gain_db": 1.0}],
    }
    targets, warnings = _build_write_targets(tampered, True)
    assert not any("/peq/" in t.address for t in targets)
    assert len([w for w in warnings if "PreSend EQ band" in w]) == 2


def test_an_aux_strip_has_no_presend_eq_node(aux_plan):
    """Same confirmed absence as `flt`: an aux strip has no `peq` node."""
    aux = copy.deepcopy(aux_plan)
    aux["channels"][0]["processing"]["presend_eq"] = {"bands": [{"band": "1", "gain_db": 2.0}]}
    targets, warnings = _build_write_targets(aux, True)
    assert not any("/peq/" in t.address for t in targets)
    assert any("no peq node" in w for w in warnings)


# ---------------------------------------------------------------------------
# The readback tolerance. Written from a value that silently never reached
# a console.
#
# 2026-09-22, the maintainer's A3 run: the plan asked for Q=1.4 on /ch/1/eq/1q
# against a prior of 0.998. The float comparison's absolute floor was 0.5,
# |1.4 - 0.998| = 0.402, so `apply` decided the desk was already correct,
# SKIPPED THE WRITE, and journalled it `skipped_no_change`. Band 4's Q=1.2
# went the same way. Two stated values never left the laptop and the
# journal said everything was fine.
#
# The failure direction that matters is the skip, not the false mismatch:
# a false mismatch is noise someone investigates, and a false "already
# correct" is a show with the wrong EQ on it.
# ---------------------------------------------------------------------------

from atoo.apply import _values_equal


def test_a_q_that_differs_by_four_tenths_is_not_already_correct():
    """The exact numbers from the run. Q is `0.44..10 in 181 steps`
    (protocol PDF p.49) -- roughly 0.05 per step -- so 0.402 is eight
    steps of a parameter whose entire range is under ten."""
    assert not _values_equal("f", 1.4, 0.9979702234268188)
    assert not _values_equal("f", 1.2, 0.9979702234268188)


def test_a_stepped_readback_still_counts_as_equal():
    """The whole reason a tolerance exists. These are real readbacks from
    the same run: WING returns the nearest step, not the value sent, and
    exact equality would report every write as a mismatch.

    The worst genuine deviation across the 2026-09-18, A1 and A3 journals
    is 19.6Hz on a 5000Hz band -- 0.4%, which relative tolerance covers
    without needing an absolute floor at all."""
    assert _values_equal("f", 5000.0, 4987.75341796875)     # bus 5 band 5 freq
    assert _values_equal("f", 9000.0, 8998.185546875)       # bus 5 band 6 freq
    assert _values_equal("f", 60.0, 60.13883590698242)      # ch 1 low freq
    assert _values_equal("f", 2.0, 1.9958817958831787)      # ch 1 band 2 Q
    assert _values_equal("f", 1.0, 0.9979702234268188)      # a Q genuinely at 1.0


def test_the_absolute_floor_still_covers_values_at_zero():
    """A relative tolerance degenerates at zero, which is the only job
    the absolute floor has left. A gain of 0.0 read back as 0.0 must not
    depend on `rel_tol`."""
    assert _values_equal("f", 0.0, 0.0)
    assert _values_equal("f", 0.0, 0.005)
    assert not _values_equal("f", 0.0, 0.5)


def test_the_tolerance_is_tight_enough_to_see_one_dB():
    """Gain is `-15..15 in 301 steps` -- 0.1dB each. The old floor
    swallowed five of them. Nobody would call a 1dB error 'already
    correct', and until this run nothing stopped us doing exactly that."""
    assert not _values_equal("f", -3.0, -2.0)
    assert not _values_equal("f", 0.0, 1.0)


# ---------------------------------------------------------------------------
# The read-after-write race on the unacked path, and the discarded
# datagram that settles it. Confirmed on hardware 2026-09-21 (the A1 run)
# and replayed here from the raw log -- an earlier change.
# ---------------------------------------------------------------------------


def test_a_value_the_console_reports_late_is_confirmed_without_reading_again(plan):
    """`/ch/7/tags` on the 21:00 A1 run, line for line (raw log
    1469-1485): the write landed, three consecutive reads all answered
    with the pre-write empty string, and the console then pushed
    '#D7,#M1' twice -- as datagrams the client drained while it was
    asking about `/ch/8/tags`. The journal called it a MISMATCH; the maintainer
    confirmed at the desk that the tags were there.

    A drained datagram names its own address, so it is evidence about
    that address and nothing else. Consulting it costs no
    round trip and no sleep, which is what this asserts: the address is
    read exactly twice, the baseline and the racing readback, and the
    verdict still comes out right."""
    console = FakeConsole(_seed_all(plan))
    address = "/ch/7/tags"
    console.answer_late = {address}
    result = apply_plan(plan, console, dry_run=False)

    record = next(w for w in result.writes if w.address == address)
    assert record.status == "match", (
        f"a value the console reported late was journalled {record.status!r} -- "
        "this is the false mismatch #144 is about")
    assert record.readback_value == "#D3,#M1"
    assert record.readback_source == "late_reply"
    assert console._get_call_counts[address] == 2, \
        "the late datagram was already in hand; re-reading would be a wasted round trip"
    assert result.replies_used == 1
    assert console.late_replies_used == [address]


def test_the_summary_says_a_discarded_reply_answered_for_a_write(plan):
    """`replies_discarded` was already reported; a reply that was USED
    has to be distinguishable from one merely dropped, or a run cannot
    say how it reached its verdict."""
    console = FakeConsole(_seed_all(plan))
    console.answer_late = {"/ch/7/tags"}
    result = apply_plan(plan, console, dry_run=False)
    summary = result.summary()

    assert "/ch/7/tags" not in summary, "the address it confirmed is not a mismatch"
    assert "stale reply/replies from the console were discarded" in summary
    assert "1 of them named an address whose readback had raced the write" in summary


def test_a_readback_that_stays_stale_is_settled_by_a_deferred_re_read(plan):
    """The other half of the mechanism, and what replaced the
    immediate re-read plus a 0.1s sleep.

    Written 2026-09-21 as `test_a_value_that_lands_late_is_not_reported_
    as_a_mismatch`, asserting that the third read happened *immediately*
    after the write. It no longer does: a re-read issued microseconds
    into the race mostly loses it too (`/ch/7/tags` lost it three times),
    so the re-read is deferred to `_recheck_disagreements` after the last
    write of the run, where the race is long over. Same single re-read,
    same verdict, no sleep -- only the timing changed, which is why the
    call count is still 3."""
    console = FakeConsole(_seed_all(plan))
    address = "/ch/1/name"
    console.get_overrides[address] = (2, OscReply(address=address, typetag="s", args=[""]))
    result = apply_plan(plan, console, dry_run=False)

    record = next(w for w in result.writes if w.address == address)
    assert record.status == "match"
    assert record.readback_source == "recheck"
    assert console._get_call_counts[address] == 3, \
        "one deferred re-read per disagreement, never more"


def test_an_agreeing_readback_is_not_read_twice(plan):
    """The re-read costs a round trip per address, so it must only happen
    when the first read disagreed. 631 needless extra reads would be a
    real cost at the desk."""
    console = FakeConsole(_seed_all(plan))
    apply_plan(plan, console, dry_run=False)
    assert console._get_call_counts["/ch/1/name"] == 2


def test_a_write_the_console_never_accepted_is_still_a_mismatch(plan):
    """The proof that none of this can manufacture a match. The console
    refuses the write and keeps reporting the wrong value however often
    it is asked -- and, to make it as hard as possible, the run is also
    handed two drained datagrams: one for this very address carrying
    something else, and one carrying the exact intended value under a
    DIFFERENT address. Neither may be borrowed.

    Renamed from `test_a_value_that_really_did_not_land_is_still_a_
    mismatch` when an earlier change added the late-reply path; the old name described
    a re-read that is no longer the only thing being guarded."""
    console = FakeConsole(_seed_all(plan))
    # 'Lead Vox' has a space, so it goes the unacked set_param way -- the
    # same reason the two false mismatches on the A1 run did.
    address = "/ch/7/name"
    console.reject_writes_to = {address}
    console.state[address] = ("WRONG", "s")
    console.push_late_reply(address, "ALSO WRONG")
    console.push_late_reply("/ch/8/name", "Lead Vox")
    result = apply_plan(plan, console, dry_run=False)

    record = next(w for w in result.writes if w.address == address)
    assert record.intended_value == "Lead Vox"
    assert record.status == "mismatch"
    assert record.readback_value == "WRONG"
    assert record.readback_source is None
    assert console.late_replies_used == [], \
        "a datagram naming another address is not evidence about this one"


def test_a_late_datagram_that_disagrees_confirms_nothing(plan):
    """The console pushing an address's state after a write is not the
    same as the console agreeing with it. Here the desk volunteers
    `/ch/7/name` a moment after the write, carrying something else --
    which is what a genuinely clamped, truncated or ignored write would
    look like from the wire. It has to stay a mismatch."""
    console = FakeConsole(_seed_all(plan))
    address = "/ch/7/name"
    console.answer_late_with = {address: "Lead Vo"}  # as if the desk truncated it
    console.state[address] = ("placeholder", "s")
    result = apply_plan(plan, console, dry_run=False)

    record = next(w for w in result.writes if w.address == address)
    assert record.intended_value == "Lead Vox"
    assert record.status == "mismatch"
    assert console.late_replies_used == []
    assert result.replies_used == 0


def test_a_datagram_that_arrived_before_the_write_cannot_confirm_it(plan):
    """The console duplicates its *pre*-write replies too -- that is the
    same habit seen from the other side. A drained datagram is only
    evidence about a write if it arrived after it, so the mark taken
    before the write is checked, not just the address and the value."""
    console = FakeConsole(_seed_all(plan))
    address = "/ch/7/name"
    console.reject_writes_to = {address}
    console.state[address] = ("WRONG", "s")
    # Planted with mark 0: filed before this run sent anything at all,
    # yet carrying exactly the value the write intends.
    console.push_late_reply(address, "Lead Vox", mark=0)
    result = apply_plan(plan, console, dry_run=False)

    record = next(w for w in result.writes if w.address == address)
    assert record.intended_value == "Lead Vox"
    assert record.status == "mismatch", \
        "a datagram older than the write was read as proof of the write"
    assert console.late_replies_used == []


def test_a_datagram_drained_by_the_re_read_itself_is_still_consulted():
    """A GET returns the FIRST matching datagram in the queue, so the
    deferred re-read can be answered by a stale copy with the real value
    queued behind it -- which is then drained, filed, and would be thrown
    away if the re-check stopped at its own read. It does not: it looks
    at the drained datagrams once more afterwards."""
    address = "/ch/7/tags"
    target = WriteTarget(address=address, value_type="s", description="tags",
                         compute_value=lambda _current: "#D3,#M1", stage=STAGE_PROCESSING)

    class SlowDesk:
        """Answers the re-read with the pre-write value, and only then
        hands over the datagram carrying the real one."""

        def __init__(self):
            self.gets = 0
            self.late: dict[str, OscReply] = {}
            self.replies_used = 0
            self.datagrams_received = 5

        def get(self, _address):
            self.gets += 1
            self.datagrams_received += 1
            self.late[address] = OscReply(address=address, typetag="s", args=["#D3,#M1"])
            return OscReply(address=address, typetag="s", args=[""])

        def late_reply(self, addr, *, after=-1):
            return self.late.get(addr) if self.datagrams_received > after else None

        def use_late_reply(self, addr):
            self.replies_used += 1
            return self.late.pop(addr, None)

    console = SlowDesk()
    record = WriteRecord(address=address, description="tags", value_type="s", method="param",
                         ack="no_ack_path", prior_value="", intended_value="#D3,#M1",
                         readback_value="", status="mismatch", timestamp="now")
    warning = _recheck_disagreements(console, [_PendingCheck(
        record=record, target=target, intended_value="#D3,#M1", mark=5)])

    assert warning is None
    assert console.gets == 1, "one re-read, not a retry loop"
    assert record.status == "match"
    assert record.readback_source == "late_reply"
    assert console.replies_used == 1


def test_losing_the_connection_during_the_re_check_leaves_the_verdict_standing(plan):
    """The writes are done and journalled by then, so there is nothing
    left to abort -- but a re-check that could not run must not pass for
    one that ran and agreed. The mismatch stands and the run says why."""
    address = "/ch/7/tags"
    target = WriteTarget(address=address, value_type="s", description="tags",
                         compute_value=lambda _current: "#D3,#M1", stage=STAGE_PROCESSING)

    class DeadSocket:
        datagrams_received = 0

        def get(self, _address):
            return OscReply(address=_address, typetag="SOCKET_ERROR",
                            args=["OSError: [Errno 65] No route to host"])

    record = WriteRecord(address=address, description="tags", value_type="s", method="param",
                         ack="no_ack_path", prior_value="", intended_value="#D3,#M1",
                         readback_value="", status="mismatch", timestamp="now")
    warning = _recheck_disagreements(DeadSocket(), [_PendingCheck(
        record=record, target=target, intended_value="#D3,#M1", mark=0)])

    assert record.status == "mismatch"
    assert warning is not None and "lost the connection" in warning


def test_the_journal_records_which_reading_settled_a_verdict(plan, tmp_path):
    """Someone diagnosing a desk that answers slowly needs to see that an
    address only verified on the second look, and how."""
    console = FakeConsole(_seed_all(plan))
    console.answer_late = {"/ch/7/tags"}
    journal = tmp_path / "apply-journal.json"
    apply_plan(plan, console, dry_run=False, journal_path=str(journal))

    payload = json.loads(journal.read_text())
    tags = next(w for w in payload["writes"] if w["address"] == "/ch/7/tags")
    assert tags["status"] == "match"
    assert tags["readback_source"] == "late_reply"
    assert payload["replies_used"] == 1
    name = next(w for w in payload["writes"] if w["address"] == "/ch/1/name")
    assert name["readback_source"] is None, "an ordinary readback records no second source"


# ---------------------------------------------------------------------------
# `clink` -- the switch that decides whether a name is visible at all.
# An earlier change, found 2026-09-22.
# ---------------------------------------------------------------------------


def test_the_name_goes_on_the_source_socket(plan):
    """*"set the name, icon and color on the source,
    and let the 'Link Customization to Source' flag flow the
    customization to the channel since that is the default."*

    `input.csv` is one row per PHYSICAL INPUT, so the name originates at
    the socket. This asserts the write actually lands there."""
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)

    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    group, socket = kick["patch"]["group"], kick["patch"]["sockets"][0]
    record = next(w for w in result.writes
                  if w.address == f"/io/in/{group}/{socket}/name")
    assert record.intended_value == "Kick"
    assert record.status == "match"


def test_every_patched_strip_is_linked_to_its_source(plan):
    """The opposite of what this test asserted an hour ago. `clink`
    defaults to ON and the desk shows the SOCKET's name; now that the
    socket carries the right name, the link is the mechanism rather than
    the bug -- and it is forced to 1 in case someone unlinked by hand."""
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)

    for channel in plan["channels"]:
        base = f"/{channel.get('bank', 'ch')}/{channel['channel']}"
        record = next(w for w in result.writes if w.address == f"{base}/clink")
        assert record.intended_value == 1, (
            f"{base} was left unlinked, so the desk shows whatever its "
            "socket happens to be called")


def test_the_source_is_named_only_after_it_is_patched(plan):
    """The hazard phantom is already staged around, and worse. A name
    written to a socket this plan has not patched yet lands on the wrong
    physical input -- and unlike a stray 48V, it looks entirely
    correct."""
    console = FakeConsole(_seed_all(plan))
    apply_plan(plan, console, dry_run=False)

    ordered = [a for a, *_ in console.set_param_calls] + [
        f"{node}/{cmd.split('=')[0]}" for node, cmd in console.set_node_calls]
    kick = next(c for c in plan["channels"] if c["name"] == "Kick")
    group, socket = kick["patch"]["group"], kick["patch"]["sockets"][0]
    assert ordered.index("/ch/1/in/conn/in") < ordered.index(f"/io/in/{group}/{socket}/name")


def test_both_sockets_of_a_stereo_pair_are_named(plan):
    """touringband's Keys is one channel on A 15+16. Naming only the
    first leaves the second showing whatever it was called before -- which
    is what an engineer sees the moment the pair is split."""
    stereo = [c for c in plan["channels"] if len(c["patch"]["sockets"]) > 1]
    if not stereo:
        pytest.skip("this plan has no stereo channel -- nothing to check")
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)

    written = {w.address for w in result.writes}
    for channel in stereo:
        group = channel["patch"]["group"]
        for socket in channel["patch"]["sockets"]:
            assert f"/io/in/{group}/{socket}/name" in written, \
                f"{group} {socket} of stereo channel {channel['name']!r} was left unnamed"


def test_a_strip_with_no_nameable_source_carries_its_own_name(plan):
    """BUS, MAIN, MTX and OFF have no name/col/icon leaf (PDF pp.40-43),
    so there is no source identity to inherit and the link has to be
    broken instead -- otherwise the strip would display nothing."""
    plan = copy.deepcopy(plan)
    plan["channels"][0]["patch"] = {"group": "BUS", "sockets": [1], "stated": True}
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)

    clink = next(w for w in result.writes if w.address == "/ch/1/clink")
    assert clink.intended_value == 0
    assert not [w for w in result.writes if w.address.startswith("/io/in/BUS/")], \
        "wrote a name to a group that has no name leaf"


# ---------------------------------------------------------------------------
# One input, two strips. The maintainer, 2026-09-22 -- a normal request, not a
# mistake, and `atoo/domain/knowledge.md` now says why: a separate
# strip for monitors, or one jack reused between acts at a festival.
# ---------------------------------------------------------------------------


def _share_a_socket(plan: dict) -> dict:
    """Patch channel 2 to channel 1's socket, as an input list calling for
    a monitor strip off the same mic would."""
    plan = copy.deepcopy(plan)
    plan["channels"][1]["patch"] = dict(plan["channels"][0]["patch"])
    return plan


def test_strips_sharing_a_socket_carry_their_own_names(plan):
    """*"we need to unlink the channel and source customization, and
    customize the channels separately."* One socket cannot hold two
    names, so the link has to go -- for BOTH strips, not just the second
    one to be built."""
    shared = _share_a_socket(plan)
    console = FakeConsole(_seed_all(shared))
    result = apply_plan(shared, console, dry_run=False)

    for base in ("/ch/1", "/ch/2"):
        clink = next(w for w in result.writes if w.address == f"{base}/clink")
        assert clink.intended_value == 0, f"{base} was left inheriting a name it cannot have"
    names = {w.address: w.intended_value for w in result.writes if w.address.endswith("/name")}
    assert names["/ch/1/name"] == plan["channels"][0]["name"]
    assert names["/ch/2/name"] == plan["channels"][1]["name"]


def test_the_shared_socket_gets_one_composite_label(plan):
    """*"The source can be given some kind of composite name or something
    else that makes sense."* One write, not two strips fighting over it."""
    shared = _share_a_socket(plan)
    group = shared["channels"][0]["patch"]["group"]
    socket = shared["channels"][0]["patch"]["sockets"][0]
    console = FakeConsole(_seed_all(shared))
    result = apply_plan(shared, console, dry_run=False)

    labels = [w for w in result.writes if w.address == f"/io/in/{group}/{socket}/name"]
    assert len(labels) == 1, "the socket label must be written once, not once per strip"
    assert labels[0].intended_value == "Kick/Snare"


def test_a_composite_label_is_cut_to_what_the_console_accepts():
    """16 characters (`facts.NAME_MAX_CHARS`). A label that is
    approximately right beats one the desk refuses -- the strips carry the
    precise names anyway."""
    from atoo.apply import _composite_source_name
    assert _composite_source_name(["Kick", "Kick IEM"]) == "Kick/Kick IEM"
    assert len(_composite_source_name(["Trumpet SM57", "Tenor Sax SM57"])) == 16
    assert _composite_source_name(["Kick", "Kick", "Kick"]) == "Kick", "repeats collapse"


def test_sharing_a_socket_is_reported_but_not_refused(plan):
    """It is a legitimate request. The user should be told what it costs
    -- one head amp between them -- not stopped."""
    shared = _share_a_socket(plan)
    console = FakeConsole(_seed_all(shared))
    result = apply_plan(shared, console, dry_run=False)

    assert any("feeds 2 strips" in w for w in result.warnings)
    assert not result.aborted


def test_two_strips_asking_for_different_phantom_is_surfaced(plan):
    """From the knowledge file: *"An input list asking for 48V on one of
    them and not the other is asking for something the hardware cannot
    do."* One preamp, one setting -- and before this, the second write
    silently overwrote the first."""
    shared = _share_a_socket(plan)
    shared["channels"][0]["source"]["phantom"] = True
    shared["channels"][1]["source"]["phantom"] = False
    console = FakeConsole(_seed_all(shared))
    result = apply_plan(shared, console, dry_run=False)

    assert any("two writes disagree" in w and "/vph" in w for w in result.warnings), \
        f"a phantom conflict on a shared socket went unreported: {result.warnings}"


def test_no_address_is_ever_written_twice(plan):
    """An earlier change slice B's standing requirement, and the shared-socket case is
    what made it real: two strips on one socket each emitted that
    socket's phantom and stereo-mode write."""
    for candidate in (plan, _share_a_socket(plan)):
        targets, _ = _build_write_targets(candidate, True)
        seen = collections.Counter(t.address for t in targets)
        assert not [a for a, n in seen.items() if n > 1], \
            f"duplicate addresses: {[a for a, n in seen.items() if n > 1]}"


# ---------------------------------------------------------------------------
# The colour palette, measured on hardware 2026-09-22 (A2b). 
# ---------------------------------------------------------------------------


def test_a_colour_stated_in_words_is_written(plan):
    """The half of an earlier change that needed a desk. The plan carries free-text
    `color` ("Red"); the console takes an integer 1..18. With no mapping
    the word was silently dropped at write time -- reaching the plan,
    reading as though it would apply, and changing nothing."""
    plan = copy.deepcopy(plan)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = "Red"
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)

    record = next(w for w in result.writes if w.address == "/ch/1/col")
    assert record.intended_value == 9, "Red is 9: the desk's own name for it (A24)"


def test_the_colour_rides_on_the_socket_like_the_name_does(plan):
    """A patched strip inherits colour from its source the same way it
    inherits the name, so writing only the strip's own `col` would be
    invisible -- exactly the trap that hid nineteen names."""
    plan = copy.deepcopy(plan)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = "Cyan"
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)

    group = plan["channels"][0]["patch"]["group"]
    socket = plan["channels"][0]["patch"]["sockets"][0]
    record = next(w for w in result.writes
                  if w.address == f"/io/in/{group}/{socket}/col")
    assert record.intended_value == 14


def test_an_explicit_col_beats_the_word(plan):
    """`col` is the console's own index. A plan that states it has said
    something more specific than a colour name and should win."""
    plan = copy.deepcopy(plan)
    plan["channels"][0]["color"] = "Red"      # would be 9
    plan["channels"][0]["col"] = 3            # Violet
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert next(w for w in result.writes if w.address == "/ch/1/col").intended_value == 3


def test_a_colour_the_desk_does_not_have_is_left_alone(plan):
    """"Gold" is not one of the eighteen. Guessing at the nearest --
    Amber? Yellow? -- would put a colour on a desk that nobody chose."""
    plan = copy.deepcopy(plan)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = "Gold"
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert not [w for w in result.writes if w.address == "/ch/1/col"]


@pytest.mark.parametrize("word, index", [("Red", 9), ("Pink", 11), ("Amber", 13), ("Orange", 15),
                                         ("Crimson", 9), ("Magenta", 11)])
def test_a_colour_is_written_as_the_desk_names_it(plan, word, index):
    """A24 (2026-09-28): the desk's own names for 9, 11, 13 and 15 are
    Red, Pink, Amber and Orange -- so "Drums-Red" now lands on the desk's
    red, not on 15, which the desk calls Orange. The retired "Crimson" and
    "Magenta" still land on the index they always meant."""
    plan = copy.deepcopy(plan)
    for ch in plan["channels"]:
        ch.pop("col", None)
    plan["channels"][0]["color"] = word
    console = FakeConsole(_seed_all(plan))
    result = apply_plan(plan, console, dry_run=False)
    assert next(w for w in result.writes if w.address == "/ch/1/col").intended_value == index


def test_the_measured_palette_has_all_eighteen():
    """From `2026-09-21-2110/A2b-palette-names.txt`, with the names the
    desk itself gives 9, 11, 13 and 15 (A24, 2026-09-28). Index 13 is the
    cross-check A2b rested on -- predicted from a snapshot of a channel set
    by hand, by a completely different route, and held; A24 only corrected
    its name, from Orange to the desk's Amber."""
    from atoo.console_facts import COLOUR_NAMES, colour_alias, colour_index
    assert sorted(COLOUR_NAMES) == list(range(1, 19))
    assert [COLOUR_NAMES[i] for i in range(1, 19)] == [
        "Navy", "Blue", "Violet", "Turquoise", "Green", "Lime", "Yellow", "Rust", "Red",
        "Salmon", "Pink", "Purple", "Amber", "Cyan", "Orange", "Mint", "Grey", "White"]
    assert colour_index("amber") == 13
    assert colour_index("orange") == 15 and colour_index("red") == 9 and colour_index("pink") == 11
    assert colour_index("crimson") == 9 and colour_index("MAGENTA") == 11, "retired names still resolve"
    assert colour_alias("Magenta") == 11 and colour_alias("Crimson") == 9
    assert colour_alias("Pink") is None and colour_alias("Gold") is None, "only a retired name is an alias"
    assert colour_index("Gold") is None
    assert colour_index("TURQUOISE") == 4, "matching is forgiving about case"


# sixpiece's apply of 2026-09-29 journalled 31 MISMATCHes that were not:
# 21 `in/set/dly` writes of 0.0 the desk holds as its floor, 0.1, and 10
# release times read back at the nearest step, 2.4-2.8% away.
@pytest.mark.parametrize("address, a, b, equal", [
    ("/ch/2/in/set/dly", 0.0, 0.10000000149011612, True),    # below the floor is the floor
    ("/ch/2/in/set/dly", 0.5, 0.10000000149011612, False),
    ("/ch/2/gate/rel", 551.5627441, 565.01513671875, True),
    ("/ch/11/dyn/rel", 274.9598999, 267.3375244140625, True),
    ("/ch/2/gate/rel", 551.5627441, 600.0, False),            # a real difference still shows
    ("/ch/2/gate/thr", 100.0, 102.5, False),                  # other leaves keep 2%
    (None, 100.0, 102.5, False),
])
def test_values_equal_knows_the_desks_floors_and_steps(address, a, b, equal):
    from atoo.apply import _values_equal
    assert _values_equal("f", a, b, address) is equal


def test_a_dca_gets_its_starting_fader_and_mute():
    """"All created DCAs should start with fader at
    unity" reached the plan and never the desk -- apply wrote only the
    DCA's name."""
    plan = {"channels": [], "busses": {}, "mute_groups": {}, "outputs": {},
            "dcas": {"Drums": {"index": 1, "fader": {"fader_db": -10}},
                     "Band": {"index": 2}}}
    targets, _ = _build_write_targets(plan, True)
    by_addr = {t.address: t for t in targets}
    assert by_addr["/dca/1/fdr"].description == "DCA 1 (Drums): starting fader -> -10dB"
    assert by_addr["/dca/2/fdr"].description == "DCA 2 (Band): starting fader -> unity (0dB)"
    assert by_addr["/dca/1/mute"].description == "DCA 1 (Drums): starting mute -> off"
    # --no-faders leaves every level alone, a DCA's included.
    quiet, _ = _build_write_targets(plan, False)
    assert not [t for t in quiet if t.address.endswith(("/fdr", "/mute"))]


# Measured with a Compact (fw 3.1) and an S16 on AES50 A: a preamp gain lands
# on the hardware's own 2.5 dB steps. S16: -2.0 .. 45.5 (0 asked holds 0.5,
# 20 asked holds 20.5, 33.3 holds 33.0, 55 holds 45.5); Compact local:
# -2.5 .. 45 (1.2 holds 0.0, 1.3 holds 2.5, 20.5 holds 20.0, 50 holds 45).
# A held value within half a step of the request is the nearest step: the
# same answer to "is a write needed" and "did it land".
@pytest.mark.parametrize("address, asked, held, equal", [
    ("/io/in/A/1/g", 20.0, 20.5, True),
    ("/io/in/A/8/g", 0.0, 0.5, True),
    ("/io/in/A/8/g", 1.25, 0.5, True),
    ("/io/in/A/8/g", 1.8, 0.5, False),             # 3.0 is the nearer step
    ("/io/in/A/8/g", 45.0, 45.5, True),             # at the top of the range
    ("/io/in/A/8/g", -3.0, -2.0, True),            # the bottom of the plan's range
    ("/io/in/C/3/g", 20.0, 19.5, True),
    ("/io/in/A/1/g", 20.0, 21.5, False),           # a real miss still shows
    ("/io/in/LCL/20/g", 1.2, 0.0, True),
    ("/io/in/LCL/20/g", 1.3, 0.0, False),          # 2.5 is the nearer step
    ("/io/in/LCL/20/g", 20.5, 20.0, True),
    ("/io/in/LCL/20/g", 33.3, 32.5, True),
    ("/io/in/LCL/20/g", 45.5, 45.0, True),
    ("/io/in/USB/1/g", 20.0, 20.5, False),         # a group with no measured step is exact
])
def test_a_preamp_gain_is_compared_on_the_hardwares_own_steps(address, asked, held, equal):
    from atoo.apply import _values_equal
    assert _values_equal("f", held, asked, address) is equal


class _SteppedPreampConsole(FakeConsole):
    """Holds every `/io/in/*/g` on the nearest step of a 2.5 dB grid (an S16
    on AES50 A: -2.0 + 2.5k), as measured."""

    GRID = [-2.0 + 2.5 * k for k in range(20)]

    def _snap(self, address):
        if address.startswith("/io/in/A/") and address.endswith("/g") and address in self.state:
            value, value_type = self.state[address]
            self.state[address] = (min(self.GRID, key=lambda g: abs(g - float(value))), value_type)

    def set_param(self, address, value, value_type="f"):
        super().set_param(address, value, value_type)
        self._snap(address)

    def set_node(self, address, command):
        reply = super().set_node(address, command)
        self._snap(f"{address}/{command.partition('=')[0]}")
        return reply


def _gain_targets(*asked):
    return [WriteTarget(f"/io/in/A/{n}/g", "f", f"A {n}: gain", lambda _, v=v: v, 1)
            for n, v in enumerate(asked, 1)]


def test_a_stepped_preamp_gain_is_a_match_and_says_it_was_snapped():
    plan = {"channels": [], "busses": {}, "mute_groups": {}, "outputs": {}, "dcas": {}}
    console = _SteppedPreampConsole({"/io/in/A/1/g": (-2.0, "f"), "/io/in/A/2/g": (-2.0, "f")})
    result = apply_plan(plan, console, dry_run=False, extra_targets=_gain_targets(20.0, 0.0))
    rows = {w.address: w for w in result.writes if w.address.startswith("/io/in/A/")}
    assert {w.status for w in rows.values()} == {"match"}
    assert rows["/io/in/A/1/g"].readback_value == 20.5
    [note] = [w for w in result.warnings if "preamp gain(s) snapped" in w]
    assert note.startswith("INFO 2 preamp gain(s) snapped to the nearest step")
    assert "A 1: 20 dB asked, 20.5 dB held" in note


def test_a_preview_after_a_stepped_gain_apply_proposes_nothing():
    """The loop the stage box made: 0 asked, 0.5 held, and every preview
    after it proposed the same write again."""
    plan = {"channels": [], "busses": {}, "mute_groups": {}, "outputs": {}, "dcas": {}}
    console = _SteppedPreampConsole({"/io/in/A/1/g": (-2.0, "f"), "/io/in/A/2/g": (-2.0, "f")})
    apply_plan(plan, console, dry_run=False, extra_targets=_gain_targets(20.0, 0.0))
    preview = apply_plan(plan, console, dry_run=True, extra_targets=_gain_targets(20.0, 0.0))
    gains = [w for w in preview.writes if w.address.endswith("/g")]
    assert gains and not [w for w in gains if w.would_change]
    assert not [w for w in preview.writes if w.address.endswith("/g")
                and w.status == "dry_run" and w.would_change]
    assert any("preamp gain(s) snapped" in w for w in preview.warnings)


def test_a_main_and_a_matrix_get_their_names():
    """"Its not setting my main or matrix bus names
    even though they are in the plan." The plan's key is the name, and it
    is written whether or not a socket is patched."""
    plan = {"channels": [], "busses": {}, "mute_groups": {}, "dcas": {},
            "outputs": {"FOH": {"kind": "main", "index": 1, "patch": None},
                        "Phones": {"kind": "matrix", "index": 4, "patch": None,
                                   "fed_by": {"type": "main", "index": 1}}}}
    targets, _ = _build_write_targets(plan, True)
    by_addr = {t.address: t for t in targets}
    assert by_addr["/main/1/name"].compute_value(None) == "FOH"
    assert by_addr["/mtx/4/name"].compute_value(None) == "Phones"
    assert by_addr["/mtx/4/name"].description == "output Phones (matrix 4): name"


def test_the_audit_reads_a_stepped_gain_as_the_planned_one():
    """CV008 compares the plan's gain with the live one on the same grid, so
    an audit straight after an apply does not report 20.5 held for 20."""
    from atoo.audit import ConsoleState, _differs
    state = ConsoleState({"/io/in/A/1/g": 20.5, "/io/in/A/2/g": 23.0})
    assert _differs(state, "/io/in/A/1/g", "f", 20.0) is None
    assert _differs(state, "/io/in/A/2/g", "f", 20.0) == 23.0
