"""Put the desk into its initialized state before a full apply.

The console has to be initialized before
a full apply so that it is in a known state, and Atoo does that itself,
rather than asking the engineer to press Initialize
by hand. So before a full apply (`atoo apply`, and the Apply page that
runs it) writes the plan, it:

1. reads the desk, by node dump (A11's fast path: `audit.bulk_node_for`);
2. writes the initialized value to every setting where the desk differs,
   taking the values from an initialized capture of that console model;
3. then writes the plan.

`amend`, `patch` and `undo` never do this. It is the same boundary as a
full apply's unpatching of strips outside the plan: only a run
that writes the whole show may change what the show does not mention.

## Where the values come from

`CAPTURES` names one capture per model, frozen in `atoo/initialized/`
as the `.snap` the desk itself exported (only its `ae_data` is read; the
file's `ce_data` is the console environment -- panel lights, display
preferences -- and is never touched). The OSC type each leaf is written
with comes from `initialized/leaf_types.json`, a table built from the
parameter map (the desk
describing its own parameters) by a script in the development repository.
A capture leaf with no entry in that table has no address we know how to
set, and is skipped and counted (`unsettable`).

The WING Rack has no capture. A full apply on a Rack, or on a desk whose
model cannot be told, says so at WARNING and goes on to write the plan
without resetting (`no_capture_warning`).

## What is reset, and what is not

Every leaf the capture holds, except:

* **The skip-list** (`SKIP_LIST`, below), each entry with its reason: the
  desk's own system nodes (network/IP, clock, console name -- anything
  that could cut Atoo's own connection), the expansion cards' setup,
  the meter/RTA display, and the engineer's own listening.
* **Anything the run writes itself** (`plan`): the plan's own leaves, and
  the full apply's own unpatching and talkback assign. A value the plan
  sets is written once, as the plan's value -- see "Order", below.
* **A value whose selector the plan sets to another model** (`other-model`):
  the capture's compressor threshold is a threshold for the capture's
  compressor model. If the plan chooses another model, those values mean
  something else, and the plan's own processing sets the ones it wants.
* **A bus's width under a bus the plan makes mono** (`mono`): the desk
  holds `/bus/{n}/wid` at 0 while `/bus/{n}/busmono` is 1, and a write of
  anything else reads back 0 (the first full apply on the
  Compact wrote the capture's 100 to the six mono monitor buses, and all
  six read back 0). Every `.snap` in the repository agrees: of 72 bus
  strips captured with `busmono` 1, all 72 hold `wid` 0, while a stereo
  bus holds whatever width it was given. So `busmono` is treated as the
  selector that governs `wid` (`HELD_BY`): a width under a bus the run
  ends mono is not written, and a width under a bus the run takes back to
  stereo is written after the `busmono` that frees it. Only the bus
  bank: the captures hold no mono main or matrix, so whether theirs
  behaves the same is unmeasured.
* **A value the desk does not have** (`absent`): not in a node dump that
  otherwise parsed, and not about to appear under a selector this run
  writes.
* **A value the desk did not answer** (`unanswered`), said at WARNING.

## Order, and the overlap with the plan

**Reset first, then the plan, and a leaf the plan writes is not reset.**
Reset-everything-then-overwrite would write a few hundred leaves twice and
leave a moment where the desk holds neither the old show nor the new one
on the strips the plan is building; resetting only what the plan leaves
alone writes each leaf once, and the plan's own write of a leaf is already
its reset. The one leaf whose plan value depends on what the desk holds --
a strip's `tags`, into which apply merges its DCA and mute-group tokens --
has that value computed over the INITIALIZED value rather than the desk's
(`baseline`), so a previous show's tokens do not survive the merge.

Within the reset: selectors first (a dynamics model, an EQ model, a delay
mode), then values, then switches, then mutes, so a value is always set
under the selector it belongs to, and nothing is unmuted before its level
is down (`preset_expand.write_order`). A selector the reset changes forces
every value it governs to be written even when the desk read the
initialized value under the old selector -- the desk re-reads
it when the selector lands. A selector the PLAN writes that governs a
value the reset touches is written in the reset's selector pass, with the
plan's value, so the reset's values land under it.

## Diff only

The desk is read first and only leaves whose value differs from the
capture are written, compared with `apply._values_equal` -- the same
type-aware, stepped-parameter tolerance apply uses to skip a write. Every
write goes through apply's ordinary loop: written, read back, journalled
with the value the desk held, so `undo` reverses the reset with the rest of
the run.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from atoo import console_facts as facts

CAPTURE_DIR = Path(__file__).parent / "initialized"
LEAF_TYPES_FILE = "leaf_types.json"

#: Model -> (file under `initialized/`, where the capture came from).
#: A model is added in the development repository, from the `.snap` an
#: initialized desk of that model exported.
CAPTURES: dict[str, tuple[str, str]] = {
    "wing-compact": (
        "wing-compact.snap",
        "a WING Compact, initialized and exported 2026-09-23 "
        "(frozen copy: tests/fixtures/console-runs/Initialized-Compact.snap; "
        "desk run A8's capture is identical, leaf for leaf)"),
    "wing-full": (
        "wing-full.snap",
        "a full-size WING, initialized and exported 2026-09-23 "
        "(frozen copy: tests/fixtures/Initialized-Full.snap)"),
}

#: How a desk with no capture gets one -- said in the WARNING. A capture is
#: frozen into the package by the project, so the user's part is to send one.
HOW_TO_CAPTURE = (
    "initialize the desk, save its show file (.snap) from the desk or WING Edit, and attach "
    "it to a desk test report "
    "(https://github.com/corourke/Atoo/issues/new?template=desk-test-report.yml)")


@dataclass(frozen=True)
class SkipRule:
    key: str
    pattern: re.Pattern
    label: str
    reason: str


#: The leaves a reset never writes, whatever the capture says. One place,
#: each with its reason. Matched against the full OSC address.
SKIP_LIST: tuple[SkipRule, ...] = (
    SkipRule(
        "system", re.compile(r"(^|/)\$"), "desk system and status",
        "the desk's own system and status nodes, every name starting `$`: read-only status, "
        "`$syscfg` (IP address, network mode, console name -- writing them could cut "
        "Atoo's own connection), `$globals` (clock source and rate) and `$ctl` (the "
        "surface's layers). None of it is a show."),
    SkipRule(
        "cards", re.compile(r"^/cards(/|$)"), "expansion cards",
        "the expansion card's own setup (a MADI card's port and receive clock, a WING-LIVE "
        "card's track count and play mode): which card is fitted and how it is clocked is "
        "the desk's environment, and a clock change can drop the desk's audio."),
    SkipRule(
        "display", re.compile(r"^/cfg/(rta|mtr)(/|$)"), "meter/RTA display",
        "meter and RTA display preferences: what the screen shows, not what the desk does."),
    SkipRule(
        "listening", re.compile(r"^/cfg/(mon|solo)(/|$)"), "monitor/solo listening",
        "the engineer's own listening -- the headphone and monitor-speaker source, level, "
        "EQ and delay, and how solo behaves: set for his phones and the room he is in, not "
        "for the show."),
)

#: The other reasons a capture leaf is not written, and how a note says
#: each. `SKIP_LIST`'s keys say theirs with the rule's own label.
SKIP_WORDS = {
    "plan": "the plan sets itself",
    "unsettable": "not settable (no address the desk takes)",
    "other-model": "under a selector the plan sets to another model",
    "mono": "a mono bus's width (the desk holds it at 0)",
    "absent": "not on this desk",
    "unanswered": "did not answer a read",
}

#: The first address component -> the area a note counts it under.
AREAS = {
    "ch": "channel", "aux": "aux", "bus": "bus", "main": "main", "mtx": "matrix",
    "dca": "DCA", "mgrp": "mute group", "fx": "FX", "io": "I/O", "cfg": "setup",
    "play": "media", "rec": "media", "cards": "cards",
}

DESCRIPTION = "reset to initialized"


def skip_rule(address: str) -> SkipRule | None:
    return next((rule for rule in SKIP_LIST if rule.pattern.search(address)), None)


def area(address: str) -> str:
    first = address.split("/")[1] if address.count("/") >= 1 else address
    return AREAS.get(first, first)


# --------------------------------------------------------------------------
# The capture
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureLeaf:
    address: str
    #: "i" | "f" | "s" -- or None: no address the desk takes is known.
    value_type: str | None
    #: In the type the desk takes (a bool as 0/1, a list choice as its token).
    value: object


@dataclass(frozen=True)
class Capture:
    model: str
    file: str
    source: str
    leaves: tuple[CaptureLeaf, ...]

    @property
    def label(self) -> str:
        return facts.CONSOLE_MODELS.get(self.model, {}).get("label", self.model)


_INDEX = re.compile(r"/(\d+)(?=/|$)")


def template(address: str) -> str:
    """`/ch/12/send/3/lvl` -> `/ch/{n}/send/{n}/lvl`, the type table's key."""
    return _INDEX.sub("/{n}", address)


@lru_cache(maxsize=1)
def leaf_types() -> dict[str, dict]:
    return json.loads((CAPTURE_DIR / LEAF_TYPES_FILE).read_text(encoding="utf-8"))["templates"]


def coerce(value: object, spec: dict) -> object:
    """A capture's JSON value in the type the desk takes."""
    osc = spec["osc"]
    if osc == "i":
        return int(value) if isinstance(value, (bool, int, float)) else value
    if osc == "f":
        return float(value) if isinstance(value, (bool, int, float)) else value
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        # A list choice whose token is a number: dyn.ratio 3 is "3.0".
        for token in spec.get("tokens") or ():
            try:
                if float(token) == float(value):
                    return token
            except ValueError:
                continue
        return str(int(value)) if float(value).is_integer() else str(value)
    return value


def leaves_from_snapshot(ae_data: dict) -> list[CaptureLeaf]:
    """Every leaf of a `.snap`'s `ae_data`, as (address, type, value), in
    the order the desk exported them."""
    types = leaf_types()
    out: list[CaptureLeaf] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}/{key}")
            return
        spec = types.get(template(path))
        if spec is None:
            out.append(CaptureLeaf(path, None, node))
        else:
            out.append(CaptureLeaf(path, spec["osc"], coerce(node, spec)))

    walk(ae_data, "")
    return out


@lru_cache(maxsize=None)
def load_capture(model: str | None) -> Capture | None:
    """The initialized capture for `model`, or None when there is none."""
    if model not in CAPTURES:
        return None
    file, source = CAPTURES[model]
    data = json.loads((CAPTURE_DIR / file).read_text(encoding="utf-8"))
    return Capture(model, file, source, tuple(leaves_from_snapshot(data["ae_data"])))


def no_capture_warning(model: str | None, desk_token: str | None = None) -> str:
    """The WARNING a full apply gives when it cannot reset the desk first."""
    if model is None:
        who = (f"the desk calls itself {desk_token!r}, a model Atoo has not measured"
               if desk_token else "the desk did not say which model it is")
        return (f"WARNING not reset to initialized first: {who}, so there is no initialized "
                "capture to reset it from. The plan is applied as it stands; anything the plan "
                "does not write keeps what the desk holds. Initialize the desk by hand first "
                "if it carries an old show.")
    label = facts.CONSOLE_MODELS.get(model, {}).get("label", model)
    return (f"WARNING not reset to initialized first: there is no initialized capture for the "
            f"{label}. The plan is applied as it stands; anything the plan does not write keeps "
            f"what the desk holds. Initialize the desk by hand first if it carries an old show. "
            f"To give Atoo a capture: " + HOW_TO_CAPTURE + ".")


NO_INIT_NOTE = ("INFO not reset to initialized first (--no-init): anything the plan does not "
                "write keeps what the desk holds")


# --------------------------------------------------------------------------
# Reading the desk
# --------------------------------------------------------------------------


#: What the reset's read is called on the progress line.
READ_PHASE = "reading the desk for the reset"


class _Absent:
    def __repr__(self) -> str:
        return "<not on the desk>"


ABSENT = _Absent()


@dataclass
class DeskRead:
    #: address -> value (in the leaf's type) or ABSENT.
    values: dict[str, object] = field(default_factory=dict)
    unanswered: set[str] = field(default_factory=set)
    dumps: int = 0
    gets: int = 0
    seconds: float = 0.0
    abort_reason: str | None = None

    @property
    def requests(self) -> int:
        return self.dumps + self.gets


def read_desk(console, wanted: list[tuple[str, str]], *, progress=None) -> DeskRead:
    """The desk's value at every `(address, type)` in `wanted`, by node dump
    where a node covers it (`audit.bulk_node_for`, A11's measured fast path)
    and by GET otherwise -- names and tags, which a dump is never
    trusted for, and nodes the dump depths do not cover. Both with up to
    the console's window of requests in flight (`console.node_dumps`/`read_in_windows`); one at a time for a window
    of 1.

    A leaf a parsed dump does not mention is ABSENT: the desk does not have
    it now (a gate value that exists only under another gate model). It is
    not asked for again, because an address the desk does not have costs
    the full timeout and its retries. A dump that did not come back, or did
    not parse, falls back to GETs for its node, with `audit`'s cut-off for a
    family the desk does not answer.

    `progress` is a `progress.ReadProgress`, told of every
    request in flight -- each dump, each GET, each probe -- so a slow read
    says which request it is waiting on, and its summary counts the
    requests that went unanswered (each one the full timeout and its
    retries), which is where a slow read's time usually goes."""
    from atoo import apply as apply_module
    from atoo import audit
    from atoo import console as osc
    from atoo.progress import _NoProgress

    progress = _NoProgress() if progress is None else progress
    started = time.monotonic()
    out = DeskRead()
    by_node, alone = audit.group_plan_by_node(wanted)
    dump_node = getattr(console, "node_dump", None)
    if not callable(dump_node):
        alone = [pair for pairs in by_node.values() for pair in pairs] + alone
        by_node = {}
    progress.set_total(len(by_node) + len(alone))
    # Up to the console's window of dumps, and below of GETs,
    # in flight at once; `osc.node_dumps`/`osc.read_in_windows` are the
    # serial loop this was for a window of 1.
    dumps = osc.node_dumps(console, list(by_node),
                           on_start=lambda node: progress.start_address(node + " (node)"))
    for node, pairs in by_node.items():
        try:
            _node, dump = next(dumps)
        except OSError as exc:
            out.abort_reason = str(exc)
            out.seconds = time.monotonic() - started
            return out
        out.dumps += 1
        progress.finish_address(answered=bool(dump))
        parsed = None
        if dump:
            try:
                parsed = osc.parse_node_dump(node, dump)
            except osc.NodeDumpError:
                parsed = None
        if parsed is None:
            alone.extend(pairs)
            progress.add_total(len(pairs))
            continue
        for address, value_type in pairs:
            text = parsed.get(address)
            if text is None:
                out.values[address] = ABSENT
                continue
            value, error = osc.value_from_dump_text(text, value_type)
            if error is None:
                out.values[address] = value
            else:
                alone.append((address, value_type))
                progress.add_total()

    def alive(address: str) -> bool:
        progress.add_total()
        progress.start_address(address)
        reply = console.get(address)
        out.gets += 1
        progress.finish_address(answered=reply is not None and not reply.is_transport_error)
        return reply is not None and not reply.is_transport_error and reply.error is None

    families = audit.UnansweredFamilies(alive)
    replies = osc.read_in_windows(console, [address for address, _ in alone],
                                  should_ask=families.should_ask,
                                  on_start=progress.start_address)
    for (address, value_type), (_address, reply) in zip(alone, replies):
        if reply is osc.SKIPPED:
            out.unanswered.add(address)
            progress.skip_address(address, audit.address_family(address))
            continue
        out.gets += 1
        progress.finish_address(answered=reply is not None and not reply.is_transport_error)
        if reply is not None and reply.is_socket_error:
            out.abort_reason = reply.args[0] if reply.args else "socket error"
            break
        if reply is not None and reply.error is not None:
            # NODE NOT FOUND and its kin: the desk answered, and has no such leaf.
            out.values[address] = ABSENT
            families.record(address, True)
            continue
        value, error = apply_module._extract_reply_value(reply, value_type, address)
        families.record(address, error is None)
        if error is None:
            out.values[address] = value
        else:
            out.unanswered.add(address)
    out.seconds = time.monotonic() - started
    return out


# --------------------------------------------------------------------------
# What the reset writes
# --------------------------------------------------------------------------


#: A value the desk holds fixed while a selector is 1, which is not one of
#: `preset_expand`'s processing selectors: (the selector's address
#: pattern, the key a value it holds counts under when skipped). Each
#: holds the `wid` beside it. Evidence in the module docstring, "What is
#: reset, and what is not".
HELD_BY: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^/bus/\d+/busmono$"), "mono"),
)


def _held_key(selector: str) -> str | None:
    """The skip key of a `HELD_BY` selector, or None for any other."""
    for pattern, key in HELD_BY:
        if pattern.match(selector):
            return key
    return None


def _is_on(value: object) -> bool:
    """A `HELD_BY` selector's value holds its width when it is 1."""
    try:
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return False


def _is_selector(address: str) -> bool:
    from atoo import preset_expand

    return (preset_expand.write_order(address) == preset_expand.SELECTOR
            or _held_key(address) is not None)


def _governs(selector: str, address: str) -> bool:
    """`preset_expand.governs`, plus a bus's `busmono` over its `wid`."""
    from atoo import preset_expand

    if _held_key(selector) is not None:
        return address == selector.rpartition("/")[0] + "/wid"
    return preset_expand.governs(selector, address)


def _order(address: str) -> int:
    """Selectors, values, switches, then mutes -- see the module docstring."""
    from atoo import preset_expand

    if address.endswith("/mute"):
        return 3
    if _held_key(address) is not None:
        return preset_expand.SELECTOR
    return preset_expand.write_order(address)


@dataclass
class InitReset:
    """What a full apply's reset will do on the desk it read."""

    capture: Capture
    #: The reset's own writes, in order.
    targets: list = field(default_factory=list)
    #: address -> (value, error) for each reset target, from the read --
    #: its baseline, so the apply loop does not ask again.
    known: dict[str, tuple[object, str | None]] = field(default_factory=dict)
    #: Plan addresses whose value is computed over the initialized value
    #: rather than the desk's (address -> the capture's value).
    baseline: dict[str, object] = field(default_factory=dict)
    #: Plan selectors written in the reset's selector pass.
    early_selectors: set[str] = field(default_factory=set)
    #: Capture leaves considered (after the skip-list and `unsettable`).
    considered: int = 0
    #: Considered leaves that already read their initialized value.
    matched: int = 0
    #: Written only because a selector this run changes governs them.
    forced: int = 0
    skipped: Counter = field(default_factory=Counter)
    read: DeskRead = field(default_factory=DeskRead)

    @property
    def abort_reason(self) -> str | None:
        return self.read.abort_reason

    @property
    def addresses(self) -> set[str]:
        return {t.address for t in self.targets}


def _governors(addresses: list[str]) -> dict[str, list[str]]:
    """value address -> the selector addresses (among `addresses`) that
    govern it. `_governs` only ever relates two leaves of one node, so the
    search is per node."""
    by_node: dict[str, list[str]] = {}
    for address in addresses:
        by_node.setdefault(address.rpartition("/")[0], []).append(address)
    out: dict[str, list[str]] = {}
    for leaves in by_node.values():
        selectors = [a for a in leaves if _is_selector(a)]
        if not selectors:
            continue
        for address in leaves:
            governing = [s for s in selectors if _governs(s, address)]
            if governing:
                out[address] = governing
    return out


def plan_reset(console, capture: Capture, run_targets: list, *, phases=None) -> InitReset:
    """Read the desk and decide the reset's writes. `run_targets` is every
    other write this run makes (the plan's, and the full apply's own), so
    no leaf is written twice. `phases` (a `progress.Phases`)
    reports the read as it goes, as "reading the desk for the reset"."""
    from atoo import apply as apply_module
    from atoo.apply import WriteTarget, _const

    equal = apply_module._values_equal
    reset = InitReset(capture=capture)
    run = {t.address: t for t in run_targets}

    in_scope: list[CaptureLeaf] = []
    for leaf in capture.leaves:
        rule = skip_rule(leaf.address)
        if rule is not None:
            reset.skipped[rule.key] += 1
        elif leaf.value_type is None:
            reset.skipped["unsettable"] += 1
        else:
            in_scope.append(leaf)
    reset.considered = len(in_scope)
    leaves = {leaf.address: leaf for leaf in in_scope}
    governors = _governors(list(leaves))

    # The plan's own value of a leaf it shares with the capture is
    # computed over the initialized value (the module docstring, "Order").
    for address in run:
        if address in leaves:
            reset.baseline[address] = leaves[address].value

    def final(selector: str) -> object:
        """The value a selector ends this run at: the plan's when it writes
        it, the capture's otherwise."""
        if selector in run:
            return run[selector].compute_value(leaves[selector].value)
        return leaves[selector].value

    run_selectors = {s for gov in governors.values() for s in gov if s in run}
    wanted = [(leaf.address, leaf.value_type) for leaf in in_scope
              if leaf.address not in run or leaf.address in run_selectors]
    phase = None if phases is None else phases.start(READ_PHASE, len(wanted))
    reset.read = read_desk(console, wanted, progress=phase)
    if phase is not None:
        phase.finish()
    if reset.read.abort_reason is not None:
        return reset
    desk = reset.read.values

    def changes(selector: str) -> bool:
        """Whether this run writes `selector` to a value the desk does not hold."""
        value = desk.get(selector)
        if value is None or value is ABSENT:
            return False
        return not equal(leaves[selector].value_type, value, final(selector), selector)

    chosen: list[CaptureLeaf] = []
    for leaf in in_scope:
        address = leaf.address
        if address in run:
            reset.skipped["plan"] += 1
            continue
        governing = governors.get(address, [])
        held = [s for s in governing if _held_key(s) is not None and _is_on(final(s))]
        if held:
            reset.skipped[_held_key(held[0])] += 1
            continue
        if any(_held_key(s) is None and not equal("s", final(s), leaves[s].value, s)
               for s in governing):
            reset.skipped["other-model"] += 1
            continue
        value = desk.get(address)
        # A `HELD_BY` selector does not make its value appear or vanish
        # (a mono bus still has a width, held at 0), so it forces only a
        # value the desk has.
        forcing = [s for s in governing if changes(s)
                   and (_held_key(s) is None or (value is not None and value is not ABSENT))]
        if forcing:
            # Written whatever the read said -- even a value it could not
            # make sense of, which under another model is often a different
            # kind of control (a bus compressor's `rel` reads AUTO under
            # one model and a time under another).
            reset.forced += 1
            reset.early_selectors.update(s for s in forcing if s in run)
        elif address in reset.read.unanswered:
            reset.skipped["unanswered"] += 1
            continue
        elif value is None or value is ABSENT:
            reset.skipped["absent"] += 1
            continue
        elif equal(leaf.value_type, value, leaf.value, address):
            reset.matched += 1
            continue
        chosen.append(leaf)
        reset.known[address] = ((None, "not on the desk under its old selector")
                                if value is None or value is ABSENT else (value, None))

    description = f"{DESCRIPTION} ({capture.label} capture)"
    chosen.sort(key=lambda leaf: _order(leaf.address))
    reset.targets = [
        WriteTarget(leaf.address, leaf.value_type, description, _const(leaf.value), stage=0)
        for leaf in chosen]
    return reset


def combine(reset: InitReset, run_targets: list) -> tuple[list, int]:
    """The run's whole write order, and how many of its first targets are
    the reset phase: the reset's selectors and the plan selectors it moved
    forward, then the reset's other writes, then everything else in its
    own order. Each plan target the reset shares a leaf with computes its
    value over the initialized value."""
    from dataclasses import replace

    def over_baseline(target):
        if target.address not in reset.baseline:
            return target
        initial = reset.baseline[target.address]
        compute = target.compute_value
        return replace(target, compute_value=lambda _prior, c=compute, v=initial: c(v))

    run = [over_baseline(t) for t in run_targets]
    early = [t for t in run if t.address in reset.early_selectors]
    rest = [t for t in run if t.address not in reset.early_selectors]
    selectors = [t for t in reset.targets if _is_selector(t.address)]
    others = [t for t in reset.targets if not _is_selector(t.address)]
    phase = selectors + early + others
    return phase + rest, len(phase)


# --------------------------------------------------------------------------
# What it says
# --------------------------------------------------------------------------


def _seconds(value: float) -> str:
    if value < 90:
        return f"{value:.1f}s"
    return f"{value / 60:.1f} min"


def _rates() -> tuple[float, float]:
    from atoo.cli import NODE_DUMP_SECONDS_PER_REQUEST, PER_LEAF_SECONDS_PER_REQUEST

    return PER_LEAF_SECONDS_PER_REQUEST, NODE_DUMP_SECONDS_PER_REQUEST


def estimate_write_seconds(writes: int) -> float:
    """A write is two requests (the write and its readback), each at A11's
    measured per-leaf rate."""
    per_leaf, _ = _rates()
    return writes * 2 * per_leaf


def by_area(addresses) -> str:
    counts = Counter(area(a) for a in addresses)
    return ", ".join(f"{n:,} {name}" for name, n in counts.most_common())


def skipped_words(skipped: Counter) -> str:
    labels = {rule.key: f"on the skip-list ({rule.label})" for rule in SKIP_LIST}
    labels.update(SKIP_WORDS)
    return ", ".join(f"{n:,} {labels.get(key, key)}" for key, n in skipped.most_common())


def run_notes(reset: InitReset, records: list, *, dry_run: bool,
              write_seconds: float | None) -> list[str]:
    """The INFO (and, for unanswered reads, WARNING) lines a run's reset
    leaves in its journal and on screen."""
    ours = [r for r in records if r.description.startswith(DESCRIPTION)]
    if dry_run:
        moving = [r for r in ours if r.would_change]
        verb = "would change"
    else:
        moving = [r for r in ours if r.status in ("match", "mismatch")]
        verb = "written"
    capture = reset.capture
    what = (f"{len(moving):,} setting(s) {verb} -- {by_area(r.address for r in moving)}"
            if moving else f"nothing {'would change' if dry_run else 'written'}")
    parts = [what, f"{reset.matched:,} already initialized"]
    if reset.forced:
        parts.append(f"{reset.forced:,} of the writes forced by a selector it changes")
    if reset.skipped:
        parts.append(f"left alone: {skipped_words(reset.skipped)}")
    read = reset.read
    timing = f"reading the desk took {_seconds(read.seconds)} ({read.requests:,} requests)"
    if dry_run:
        timing += (f"; writing would take about {_seconds(estimate_write_seconds(len(moving)))} "
                   "at the rate measured on a WING Compact")
    elif write_seconds is not None:
        timing += (f", writing {_seconds(write_seconds)}: "
                   f"{_seconds(read.seconds + write_seconds)} in all")
    notes = [f"INFO reset to initialized ({capture.label} capture) before the plan's writes: "
             + "; ".join(parts) + f"; {timing}"]
    if reset.skipped.get("unanswered"):
        notes.append(
            f"WARNING {reset.skipped['unanswered']:,} setting(s) did not answer a read, so they "
            "were not reset to initialized and keep whatever the desk holds")
    return notes


def preflight_note(plan: dict, model: str | None) -> tuple[str, str]:
    """`(code, "INFO ..." | "WARNING ...")` for Apply's pre-flight, from the
    plan alone: what the reset will consider, and a worst-case time. The
    desk is not read here, so the count is an upper bound."""
    from atoo import apply as apply_module

    capture = load_capture(model)
    if capture is None:
        return ("apply.init-no-capture", no_capture_warning(model))
    targets, _warnings = apply_module._build_write_targets(plan, True)
    run = {t.address for t in targets + apply_module.full_apply_targets(plan, model)}
    skipped: Counter = Counter()
    candidates = []
    for leaf in capture.leaves:
        rule = skip_rule(leaf.address)
        if rule is not None:
            skipped[rule.key] += 1
        elif leaf.value_type is None:
            skipped["unsettable"] += 1
        elif leaf.address in run:
            skipped["plan"] += 1
        else:
            candidates.append(leaf)
    from atoo import audit

    by_node, alone = audit.group_plan_by_node([(leaf.address, leaf.value_type)
                                               for leaf in candidates])
    per_leaf, per_dump = _rates()
    read_seconds = len(by_node) * per_dump + len(alone) * per_leaf
    return ("apply.init", (
        f"INFO before writing the plan, a full apply resets the desk to the {capture.label}'s "
        f"initialized state: it reads the desk (about {_seconds(read_seconds)}) and writes back "
        f"only what differs from the initialized capture, among up to {len(candidates):,} "
        f"settings the plan does not set itself ({skipped_words(skipped)} are left alone). "
        f"A desk already initialized costs only the read; at the very most, every one of "
        f"them differing, writing takes about {_seconds(estimate_write_seconds(len(candidates)))}"
        f". `atoo apply --no-init` skips it"))
