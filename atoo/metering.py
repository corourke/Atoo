"""Clip detection for Watch: an ERROR, `L003 Clipped`, for
about a minute after a channel, aux, bus, main or matrix clips.

Product decision, 2026-10-13: *"We don't need live meters or anything like that.
What we should do is throw up an ERROR that lasts for about a minute if
any channel or bus clips. ... Reset the one minute timer if the channel
or bus clips again."* So there is **no level display** here, and nothing
of this module reaches the page but the finding.

**Where the signal comes from.** Meters are not in WING's OSC node tree
at all; they are the one thing that needs the native protocol's metering
channel on TCP 2222 (`WING_Remote-Protocols-3.1-03.pdf` pp96-98). A Watch
opens one native connection (one of the desk's 24 client slots), declares
a UDP port, asks for **one** meter collection and renews it under the
desk's 5-second timeout. It **never writes a parameter** (FR-6.7): the
only bytes sent are the port declaration, the meter request and its
renewals.

**One collection, one report id.** The desk keeps only the last
collection request on a connection (measured on a WING Compact, fw 3.1:
with two requests only the second was ever served, and renewing the id of
the first stopped the stream). So channels 1-40, aux 1-8, bus 1-16,
main 1-4 and matrix 1-8 are one collection under `REPORT_ID`, and a packet
is split by position: its words must be exactly `WORDS_PER_STRIP` for
each strip of each type, in the order the types were asked. Each strip is
8 words (input L/R, output L/R, gate key/gain, dyn key/gain), confirmed
for channels and for bus, main and matrix on a Compact. A packet of any
other size cannot be split, so none of it is read and the status says so.

**Renewal repeats the whole request.** That is the form measured to keep
the stream going with one report and with several; it also re-asks for
the data should the desk have forgotten it.

**Liveness.** A stream that stops after it began is not "on": after
`STALL_AFTER` seconds with no packet the status says the meter data
stopped, and the monitor asks again (declaration and request) every
`RENEW_SECONDS` until packets come back.

**Which word means "clipped", and at what level -- a judgement call,
announced here and at INFO in the product.** A strip clips
when any of its four level words -- input left/right, output left/right
-- reads at or above `CLIP_THRESHOLD_DB`, -0.5 dBFS. Input words are
where a converter or a bus sum overloads; output words are where a boost
after the input does. Both channels of a stereo strip count as one strip,
and so do both words: one finding per strip. -0.5 dB is "within a hair
of full scale": a peak there is a clipped peak to anyone listening, and a
level meter reads a clipped converter at 0 dBFS to within a quantum.
The WING's own clip indicator is what the desk test
compares this against; if the two disagree, this constant is what moves.

**What a clip is: what lights the desk's clip LED.** A clip
is the time a strip is at or above `CLIP_THRESHOLD_DB`, with dips below it
shorter than `CLIP_BRIDGE_SECONDS` (200 ms) bridged, so a converter
hovering at full scale is one clip and not "clipped 222 times". A new clip
begins when the level reaches the threshold again after more than 200 ms
below it -- seen in packets that say so, not assumed from packets that did
not come. A gap in the data up to `GAP_BRIDGE` (the stream paused for its
renewal) neither ends a clip nor counts as below; a longer one does end
it. "Clipped N times" counts clips.

It used to end only once the level stayed below -3 dBFS for 200 ms. On a
desk, a snare mic's level between hits, and a hot drum mix's between
peaks, stays above -3 dBFS, so a whole groove read as one clip "for about
53 s", and the count never rose while the clip light flashed hit after
hit.

**How long the clip lasted.** A clip's span, from its first clipped packet
to its last, plus one packet interval, the dips it bridged included, as the
clip LED shows them -- reported only when packets come
fast enough to mean something (`MAX_DURATION_INTERVAL`) and the clip is
long enough to measure (`MIN_DURATION`). A duplicated or late packet adds
nothing to it. The finding gives the longest clip, the count, and when the
first and the last were.

**The timer.** `ClipTracker` keeps, per strip, when it last clipped. A
strip's ERROR stands for `HOLD_SECONDS` after that and a new clip starts
the minute again. It is a pure object driven by times its caller hands
it, so the tests need no clock. `ClipMonitor` is the thread that feeds it
from the desk; Watch reads it once per pass, so an ERROR appears (and
clears) within a pass of the clip and of the minute running out.
"""

from __future__ import annotations

import errno
import select
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

# --- the protocol (WING_Remote-Protocols-3.1-03.pdf pp93-98) ---------------
# Moved here from an early experiment, whose spikes proved it;
# nothing in the package imports from the experiments.

NATIVE_PORT = 2222

_ESCAPE = 0xDF
_CHANNEL_ID_BASE = 0xD0
_NUM_CHANNELS = 14

#: Table 1's ChID for "Meter Data Requests" (select byte 0xd3).
METERING_CHANNEL_ID = 3

_TOKEN_UDP_PORT = 0xD3
_TOKEN_REPORT_ID = 0xD4
_TOKEN_COLLECTION_START = 0xDC
_TOKEN_COLLECTION_END = 0xDE

#: Table 4's meter type bytes for the strips Watch listens to.
_METER_TYPES = {"channel": 0xA0, "aux": 0xA1, "bus": 0xA2, "main": 0xA3, "matrix": 0xA4}

#: Table 4's index ranges.
STRIP_COUNTS = {"channel": 40, "aux": 8, "bus": 16, "main": 4, "matrix": 8}

#: The OSC base each meter type's strips have (`/ch/3`, `/mtx/2`), which is
#: how a clip is named everywhere else in Watch.
STRIP_BANKS = {"channel": "ch", "aux": "aux", "bus": "bus", "main": "main", "matrix": "mtx"}

#: Words per strip: input L/R, output L/R, gate key/gain, dyn key/gain
#: (Table 5; confirmed for `channel` on a Compact, 2026-09-09).
WORDS_PER_STRIP = 8

#: The words of a strip that are levels a clip shows in: input L/R and
#: output L/R. The gate's and the dynamics' words are gain reduction.
LEVEL_WORDS = (0, 1, 2, 3)

#: Levels are 1/256 dB (the spec).
UNITS_PER_DB = 256

# --- the choices (see the module docstring) --------------------------------

#: At or above this, a strip has clipped.
CLIP_THRESHOLD_DB = -0.5
CLIP_THRESHOLD = round(CLIP_THRESHOLD_DB * UNITS_PER_DB)

#: A dip below the threshold shorter than this is part of the clip; once
#: the level has been below it this long, the clip is over, and the next
#: one is a new clip.
CLIP_BRIDGE_SECONDS = 0.2

#: How long a strip's ERROR stands after its last clip.
HOLD_SECONDS = 60.0

#: A run of clipped packets is timed only when packets come at least this
#: often (seconds apart) and only reported when it lasted at least
#: `MIN_DURATION`.
MAX_DURATION_INTERVAL = 0.25
MIN_DURATION = 0.1

#: A gap in the meter data up to this long (the stream paused for its
#: renewal) neither ends a clip nor counts as quiet; a longer one ends it.
GAP_BRIDGE = 1.0

#: Two packets closer than this are one packet heard twice: they move no
#: timing.
DUPLICATE_WITHIN = 0.01

#: A strip is carrying signal when a level word reads at or above this
#: (-60 dBFS: an open mic's noise floor on a WING is well above it, a
#: dead input reads far below) within the last `LIVE_WINDOW` seconds. What lets Watch tell a stage box that passes audio from one that
#: does not, whatever word the desk's link status shows.
LIVE_THRESHOLD_DB = -60.0
LIVE_THRESHOLD = round(LIVE_THRESHOLD_DB * UNITS_PER_DB)
LIVE_WINDOW = 5.0

#: The desk drops a meter request not renewed within 5 s; renew well inside.
RENEW_SECONDS = 2.0

#: No packet this long after the request went out: say so at INFO.
NO_PACKETS_AFTER = 10.0

#: No packet this long after the stream began: the data has stopped.
STALL_AFTER = 3.0

#: The one report id, and the meter types of its collection in the order
#: they are requested (and so the order the desk answers them).
REPORT_ID = 1
REPORT_TYPES: tuple[str, ...] = ("channel", "aux", "bus", "main", "matrix")


def report_strips(meter_types: Iterable[str]) -> list[str]:
    """The OSC base of every strip of `meter_types`, in the order the desk
    answers them: `["/ch/1", ..., "/ch/40", "/aux/1", ...]`."""
    return [f"/{STRIP_BANKS[t]}/{n}" for t in meter_types for n in range(1, STRIP_COUNTS[t] + 1)]


def _stuff(ch_id: int, payload: bytes, state: dict) -> bytes:
    """The spec's sample transmit routine (p94): a channel-select prefix
    only when the channel changes, and a literal 0xdf escaped when the
    byte after it would read as a channel select."""
    out = bytearray()
    if state.get("tx") != ch_id:
        out += bytes([_ESCAPE, _CHANNEL_ID_BASE + ch_id])
        state["tx"] = ch_id
    esc = False
    i, n = 0, len(payload)
    while i < n:
        db = payload[i]
        i += 1
        if db == _ESCAPE:
            esc = True
        else:
            if esc and _CHANNEL_ID_BASE <= db <= _CHANNEL_ID_BASE + _NUM_CHANNELS:
                db = _ESCAPE - 1
                i -= 1
            esc = False
        out.append(db)
    if esc:
        out.append(_ESCAPE - 1)
    return bytes(out)


def meter_collection(meter_types: Iterable[str]) -> bytes:
    """One meter collection: every strip of each type, `0xdc`
    `<type> <index-1>... 0xde` (Table 4). Indices are one byte each."""
    out = bytearray([_TOKEN_COLLECTION_START])
    for meter_type in meter_types:
        out.append(_METER_TYPES[meter_type])
        out.extend(range(STRIP_COUNTS[meter_type]))   # token value = index - 1
    out.append(_TOKEN_COLLECTION_END)
    return bytes(out)


def requests(udp_port: int) -> tuple[bytes, bytes, bytes]:
    """The bytes a Watch sends, as (declaration, request, renewal), framed
    for the native channel. The renewal is the whole request again: the
    form measured to keep a stream going. Nothing else is ever sent: this
    is the whole of what Watch says to the desk's native port."""
    framing: dict = {}
    declaration = _stuff(METERING_CHANNEL_ID, bytes([_TOKEN_UDP_PORT]) + struct.pack(">H", udp_port),
                         framing)
    ident = bytes([_TOKEN_REPORT_ID]) + struct.pack(">I", REPORT_ID)
    ask = _stuff(METERING_CHANNEL_ID, ident + meter_collection(REPORT_TYPES), framing)
    return declaration, ask, ask


def parse_packet(data: bytes) -> tuple[int, list[int]]:
    """A meter packet: a 4-byte report id, then signed 16-bit big-endian
    words. ValueError on anything too short or ragged."""
    if len(data) < 4 or (len(data) - 4) % 2:
        raise ValueError(f"meter packet of {len(data)} bytes")
    words = (len(data) - 4) // 2
    return struct.unpack_from(">I", data)[0], list(struct.unpack_from(f">{words}h", data, 4))


def clipped_strips(strips: Sequence[str], words: Sequence[int],
                   threshold: int = CLIP_THRESHOLD) -> set[str]:
    """The strips of one packet that clipped: any of a strip's level words
    at or above `threshold`. `words` must be exactly `WORDS_PER_STRIP`
    per strip -- the caller has checked that the packet is the size the
    layout says."""
    hit = set()
    for i, base in enumerate(strips):
        block = words[i * WORDS_PER_STRIP:(i + 1) * WORDS_PER_STRIP]
        if any(block[w] >= threshold for w in LEVEL_WORDS):
            hit.add(base)
    return hit


def live_strips(strips: Sequence[str], words: Sequence[int],
                threshold: int = LIVE_THRESHOLD) -> set[str]:
    """The strips of one packet carrying signal: any level word at or above
    `threshold` (see `clipped_strips` for the layout)."""
    hit = set()
    for i, base in enumerate(strips):
        block = words[i * WORDS_PER_STRIP:(i + 1) * WORDS_PER_STRIP]
        if any(block[w] >= threshold for w in LEVEL_WORDS):
            hit.add(base)
    return hit


# --- the timer -------------------------------------------------------------


@dataclass(frozen=True)
class StripClip:
    """One strip with an ERROR standing: what `L003` says about it."""

    base: str                    # "/ch/3"
    count: int                   # separate clips since the ERROR went up
    ago: float                   # seconds since the last clipped packet
    remaining: float             # seconds until it clears unless it clips again
    longest: float | None = None  # longest clip, seconds -- None when not measurable
    first_ago: float | None = None  # seconds since the first clip of this ERROR


@dataclass
class _Episode:
    first_at: float                # the first clipped packet
    last_at: float                 # the last clipped packet
    count: int = 1
    clip_start: float = 0.0        # the current clip's first clipped packet
    clip_last: float = 0.0         # ... and its last
    longest_span: float = 0.0      # longest clip, first to last clipped packet
    below_since: float | None = None  # first packet below the threshold since the last clipped one
    released: bool = False         # the current clip has ended


class ClipTracker:
    """Per-strip clip timers, driven by the times its caller passes.

    `observe(now, clipped)` is one meter packet: the set of strips that
    clipped in it. `snapshot(now)` is every strip whose ERROR stands.

    A strip's episode starts at its first clip; each later clip adds to its
    count and moves its end `hold` seconds past it; and the episode is
    over once `hold` seconds pass with no clip. A strip that clips after
    that starts a new episode, which is a new finding. A clip goes on while
    the strip clips, bridging dips shorter than `CLIP_BRIDGE_SECONDS`, and
    ends once packets have shown it below the threshold that long, or the
    data stopped for more than `GAP_BRIDGE`.
    """

    def __init__(self, hold: float = HOLD_SECONDS) -> None:
        self.hold = hold
        self._episodes: dict[str, _Episode] = {}
        self._live_at: dict[str, float] = {}
        self._last_packet_at: float | None = None
        self._interval: float | None = None
        self.packets = 0
        self._lock = threading.Lock()

    @property
    def interval(self) -> float | None:
        """Seconds between packets, smoothed. None until two have come."""
        with self._lock:
            return self._interval

    def observe(self, now: float, clipped: Iterable[str]) -> None:
        clipped = set(clipped)
        with self._lock:
            before = self._last_packet_at
            dt = None if before is None else now - before
            if dt is not None and DUPLICATE_WITHIN <= dt < 2.0:
                self._interval = dt if self._interval is None else 0.8 * self._interval + 0.2 * dt
            self._last_packet_at = now
            self.packets += 1
            self._expire(now)
            step = self._interval or 0.0
            for base, ep in self._episodes.items():
                if dt is not None and dt > GAP_BRIDGE:
                    ep.released = True           # the data stopped: whatever was, is over
                if base in clipped:
                    ep.below_since = None
                    continue
                if ep.below_since is None:
                    ep.below_since = now
                # Below for the bridge time, as the packets show it: N packets
                # cover N intervals.
                if now - ep.below_since + step >= CLIP_BRIDGE_SECONDS - 1e-9:
                    ep.released = True
            for base in clipped:
                ep = self._episodes.get(base)
                if ep is None:
                    self._episodes[base] = _Episode(now, now, clip_start=now, clip_last=now)
                    continue
                if ep.released:
                    ep.count += 1                    # a new clip, the minute restarts
                    ep.clip_start = now
                    ep.released = False
                ep.clip_last = now
                ep.last_at = now
                ep.longest_span = max(ep.longest_span, ep.clip_last - ep.clip_start)

    def observe_live(self, now: float, live: Iterable[str]) -> None:
        """The strips of one meter packet carrying signal."""
        with self._lock:
            for base in live:
                self._live_at[base] = now

    def live(self, now: float, window: float = LIVE_WINDOW) -> frozenset[str]:
        """Every strip that carried signal within the last `window` seconds."""
        with self._lock:
            return frozenset(b for b, t in self._live_at.items() if now - t <= window)

    def _expire(self, now: float) -> None:
        for base in [b for b, ep in self._episodes.items() if now - ep.last_at >= self.hold]:
            del self._episodes[base]

    def snapshot(self, now: float) -> tuple[StripClip, ...]:
        with self._lock:
            self._expire(now)
            interval = self._interval
            out = []
            for base, ep in self._episodes.items():
                longest = None
                if interval is not None and interval <= MAX_DURATION_INTERVAL:
                    seconds = ep.longest_span + interval      # N packets cover N intervals
                    if seconds >= MIN_DURATION:
                        longest = seconds
                out.append(StripClip(base, ep.count, now - ep.last_at,
                                     self.hold - (now - ep.last_at), longest,
                                     first_ago=now - ep.first_at))
            return tuple(sorted(out, key=lambda c: _strip_order(c.base)))


def _strip_order(base: str) -> tuple[int, int]:
    _, bank, number = base.split("/")
    order = [STRIP_BANKS[t] for t in STRIP_BANKS]
    return (order.index(bank), int(number))


# --- what a watch is told about the monitor --------------------------------


@dataclass(frozen=True)
class ClipStatus:
    """What `ClipMonitor` says about itself, for the one INFO note Watch
    carries (`watch.clip_status_note`). `on` is whether clips are being
    listened for; `summary` is the short form on the Watch page's "This
    watch" line, `detail` the sentence."""

    on: bool
    summary: str
    detail: str


# --- the monitor -----------------------------------------------------------


class ClipMonitor:
    """Listens to one desk's meters on a thread of its own and feeds a
    `ClipTracker`. `start()` returns at once -- the connection is made on
    the thread, so a desk that does not answer cannot hold a Watch back --
    and **never raises**: whatever goes wrong becomes the INFO in
    `status()`, and Watch carries on without clip detection.

    The socket calls are the module's own; `connect` and `udp_socket` are
    injectable for tests."""

    def __init__(self, host: str, *, port: int = NATIVE_PORT, connect_timeout: float = 2.0,
                 clock: Callable[[], float] = time.monotonic,
                 connect: "Callable[[], socket.socket] | None" = None,
                 udp_socket: "Callable[[], socket.socket] | None" = None,
                 record: "str | None" = None) -> None:
        self.host = host
        self.port = port
        self.clock = clock
        self.tracker = ClipTracker()
        self._connect_timeout = connect_timeout
        self._connect = connect or self._default_connect
        self._udp_socket = udp_socket or self._default_udp
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._problem: str | None = None       # why it is off, once it is
        self._started_at: float | None = None
        self._first_packet_at: float | None = None
        self._last_packet_at: float | None = None
        #: The word count of the last packet that was not the size the
        #: layout says, if any came.
        self._bad_words: int | None = None
        self._strips = report_strips(REPORT_TYPES)
        #: Where every datagram from the desk is written as it comes, for a
        #: replay (`replay_recording`); None when not recording.
        self._record_path = record
        self._record = None

    # -- the public face --

    def start(self) -> None:
        self._started_at = self.clock()
        if self._record_path:
            self._record = open_recording(self._record_path, self.host)
        self._thread = threading.Thread(target=self._run, name="atoo-clip-monitor", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self._record is not None:
            self._record.close()
            self._record = None

    def snapshot(self) -> tuple[StripClip, ...]:
        return self.tracker.snapshot(self.clock())

    def live(self) -> frozenset[str] | None:
        """The strips carrying signal just now, or None while no meter
        packet has come (nothing is known, which is not the same as silent)."""
        if self._first_packet_at is None:
            return None
        return self.tracker.live(self.clock())

    def status(self) -> ClipStatus:
        with self._lock:
            problem = self._problem
            bad = self._bad_words
            last = self._last_packet_at
        threshold = f"{CLIP_THRESHOLD_DB:g} dBFS"
        off = "Clip detection is off, and Watch carries on without it: "
        if problem:
            return ClipStatus(False, "off", off + problem)
        now = self.clock()
        if self._first_packet_at is None and bad is not None:
            return ClipStatus(False, "off: unexpected meter layout", off + _bad_layout(bad))
        if self._first_packet_at is None:
            waited = now - (self._started_at if self._started_at is not None else now)
            if waited >= NO_PACKETS_AFTER:
                return ClipStatus(
                    False, "off: no meter packets",
                    off + f"the console has sent no meter data in {waited:.0f} s. Meter packets "
                    "come back by UDP to this machine; a firewall that blocks them stops "
                    "clip detection.")
            return ClipStatus(True, "starting", "Clip detection is starting: waiting for the "
                              "console's first meter packets.")
        silent = now - (last if last is not None else now)
        if silent > STALL_AFTER:
            return ClipStatus(
                False, "off: meter data stopped",
                off + f"meter data stopped (no packet for {silent:.0f} s). Atoo is asking the "
                "console for it again; clip detection comes back by itself when packets do.")
        rate = self._rate()
        parts = [f"Listening to the console's meters for clips (a strip clips at {threshold}; "
                 f"a clip ends once the strip has been below that for "
                 f"{CLIP_BRIDGE_SECONDS * 1000:.0f} ms, and \"clipped N times\" counts those clips); "
                 f"an ERROR stands for {HOLD_SECONDS:.0f} s after its last clip."]
        summary = "on"
        if rate:
            summary = f"on, {rate:.0f} packets/s" if rate >= 2 else f"on, {rate:.1f} packets/s"
            parts.append(f"Meter packets are arriving about {rate:.1f} times a second"
                         + ("" if self.tracker.interval is not None
                            and self.tracker.interval <= MAX_DURATION_INTERVAL
                            else ", too slowly to say how long a clip lasted") + ".")
        if bad is not None:
            summary += "; some packets not read"
            parts.append(_bad_layout(bad))
        return ClipStatus(True, summary, " ".join(parts))

    # -- internals --

    def _rate(self) -> float | None:
        interval = self.tracker.interval
        return 1.0 / interval if interval else None

    def _fail(self, problem: str) -> None:
        with self._lock:
            if self._problem is None:
                self._problem = problem

    def _default_connect(self) -> socket.socket:
        return socket.create_connection((self.host, self.port), timeout=self._connect_timeout)

    @staticmethod
    def _default_udp() -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("", 0))
        return s

    def _run(self) -> None:
        udp = tcp = None
        try:
            try:
                udp = self._udp_socket()
            except OSError as exc:
                self._fail(f"this machine could not open a UDP port for meter data ({exc}).")
                return
            try:
                tcp = self._connect()
            except OSError as exc:
                self._fail(f"the console's metering connection ({self.host} port {self.port}) "
                           f"could not be opened ({_why(exc)}). It uses one of the console's "
                           "native client slots; a console with all 24 in use refuses it.")
                return
            tcp.setblocking(False)
            declaration, ask, renewal = requests(udp.getsockname()[1])
            tcp.sendall(declaration + ask)
            self._loop(udp, tcp, declaration, renewal)
        except OSError as exc:
            self._fail(f"the meter connection was lost ({_why(exc)}). Stop and Start watching "
                       "to try again.")
        except Exception as exc:  # a bug here must not take a Watch down with it
            self._fail(f"it stopped on an unexpected error ({type(exc).__name__}: {exc}).")
        finally:
            for s in (udp, tcp):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

    def _loop(self, udp: socket.socket, tcp: socket.socket, declaration: bytes,
              renewal: bytes) -> None:
        last_renew = self.clock()
        while not self._stop.is_set():
            now = self.clock()
            if now - last_renew >= RENEW_SECONDS:
                # The renewal is the whole request. Once packets have stopped
                # the port is declared again too, in case the desk forgot it.
                stalled = (self._last_packet_at is not None
                           and now - self._last_packet_at > STALL_AFTER)
                tcp.sendall((declaration if stalled else b"") + renewal)
                last_renew = now
            ready, _, _ = select.select([udp, tcp], [], [], 0.25)
            if tcp in ready:
                try:
                    data = tcp.recv(4096)       # the desk says nothing back; EOF is a drop
                except BlockingIOError:
                    data = None
                if data == b"":
                    raise ConnectionResetError(errno.ECONNRESET, "the console closed it")
            if udp in ready:
                data, addr = udp.recvfrom(65535)
                if addr[0] == self.host:
                    if self._record is not None:
                        write_recorded(self._record, self.clock() - (self._started_at or 0.0), data)
                    self.feed(data)

    def feed(self, data: bytes) -> None:
        """One UDP datagram. A packet that is not our report, or is not the
        size the layout says, is not read (and the second kind is
        remembered, for the status)."""
        try:
            report_id, words = parse_packet(data)
        except ValueError:
            return
        if report_id != REPORT_ID:
            return
        if len(words) != WORDS_PER_STRIP * len(self._strips):
            with self._lock:
                self._bad_words = len(words)
            return
        now = self.clock()
        with self._lock:
            if self._first_packet_at is None:
                self._first_packet_at = now
            self._last_packet_at = now
        self.tracker.observe(now, clipped_strips(self._strips, words))
        self.tracker.observe_live(now, live_strips(self._strips, words))


# --- recording and replaying the meter stream ----------------
#
# A desk test cannot be rerun here, but what the desk sent can: `atoo watch
# --record-meters FILE` writes every datagram from the desk, as it came,
# with its time, and `replay_recording` feeds a recording through the same
# reading and tracker a live watch uses. A recording is JSON lines: a header
# `{"atoo_meter_recording": 1, "host": ..., "report_types": [...],
# "words_per_strip": 8}`, then one `{"t": seconds since the start, "packet":
# hex}` per datagram.

RECORDING_VERSION = 1


def open_recording(path: str, host: str):
    handle = open(path, "w", encoding="utf-8")
    import json

    handle.write(json.dumps({"atoo_meter_recording": RECORDING_VERSION, "host": host,
                             "report_types": list(REPORT_TYPES),
                             "words_per_strip": WORDS_PER_STRIP}) + "\n")
    handle.flush()
    return handle


def write_recorded(handle, t: float, data: bytes) -> None:
    import json

    handle.write(json.dumps({"t": round(t, 4), "packet": data.hex()}) + "\n")
    handle.flush()


def iter_recording(lines: Iterable[str], *, hold: float = HOLD_SECONDS):
    """A recording fed through the monitor's own reading (`ClipMonitor.feed`)
    on its recorded times, one datagram at a time: yields `(time, tracker)`
    after each. ValueError for a file that is not a recording."""
    import json

    clock = [0.0]
    monitor = ClipMonitor("replay", clock=lambda: clock[0])
    monitor.tracker.hold = hold
    header = None
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if header is None:
            if record.get("atoo_meter_recording") != RECORDING_VERSION:
                raise ValueError("not an Atoo meter recording (no header on line 1)")
            header = record
            continue
        clock[0] = float(record["t"])
        monitor.feed(bytes.fromhex(record["packet"]))
        yield clock[0], monitor.tracker
    if header is None:
        raise ValueError("an empty file is not a meter recording")


def replay_recording(lines: Iterable[str], *, hold: float = HOLD_SECONDS
                     ) -> "tuple[ClipTracker, float]":
    """The tracker a whole recording leaves, and the time of its last packet."""
    now, tracker = 0.0, None
    for now, tracker in iter_recording(lines, hold=hold):
        pass
    if tracker is None:
        tracker = ClipTracker(hold)
    return tracker, now


def with_clip_detection(provider: Callable[[], object], host: str,
                        **monitor_options) -> "tuple[Callable[[], object], Callable[[], None]]":
    """`provider` (a state provider) with the console's clips on every
    state it returns, and the function that ends the listening.

    The monitor starts before the first read so it hears the whole of a
    slow one. Everything it can get wrong is in the state's `clip_status`
    (one INFO, `watch.clip_status_note`); this never raises."""
    from dataclasses import replace

    monitor = ClipMonitor(host, **monitor_options)
    monitor.start()

    def detecting():
        return replace(provider(), clips=monitor.snapshot(), clip_status=monitor.status(),
                       live_strips=monitor.live())

    return detecting, monitor.close


def _bad_layout(words: int) -> str:
    expected = WORDS_PER_STRIP * len(report_strips(REPORT_TYPES))
    counts = ", ".join(f"{STRIP_COUNTS[t]} {t}" for t in REPORT_TYPES)
    return (f"The console's meter packets have {words} words, not the {expected} the layout says "
            f"({counts}, {WORDS_PER_STRIP} words each), so they cannot be split by strip and "
            "none are read.")


def _why(exc: OSError) -> str:
    return exc.strerror or str(exc)
