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
a UDP port, asks for two meter collections and renews them under the
desk's 5-second timeout. It **never writes a parameter** (FR-6.7): the
only bytes sent are the port declaration, two meter requests and their
renewals.

- **Report 1**: channels 1-40 and aux 1-8 -- 8 words each (input L/R,
  output L/R, gate key/gain, dyn key/gain), confirmed for `channel` on a
  WING Compact, 2026-09-09 (a metering spike).
- **Report 2**: bus 1-16, main 1-4 and matrix 1-8. Table 5 lists them
  under the same 8-word layout as the channel, but that is the spec's
  grouping, **not yet seen on a desk**. They are a separate report (the
  spec asks for a different report id per collection) so that if a desk's
  packets are not the size the layout says, only this half is switched
  off, with an INFO saying so, and channel clips are still caught.

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

**How long the clip lasted.** The length of a run of consecutive clipped
packets, at the packet rate's resolution -- reported only when that
resolution is fine enough to mean something (`MAX_DURATION_INTERVAL`) and
the run is long enough to measure (`MIN_DURATION`). Otherwise the finding
says it clipped and nothing about for how long.

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

#: How long a strip's ERROR stands after its last clip.
HOLD_SECONDS = 60.0

#: A run of clipped packets is timed only when packets come at least this
#: often (seconds apart) and only reported when it lasted at least
#: `MIN_DURATION`.
MAX_DURATION_INTERVAL = 0.25
MIN_DURATION = 0.1

#: Clipped packets this far apart (seconds) are not one run, whatever came
#: between them: a run is consecutive packets, and packets are tens of ms
#: apart.
RUN_GAP = 1.0

#: The desk drops a meter request not renewed within 5 s; renew well inside.
RENEW_SECONDS = 2.0

#: No packet this long after the request went out: say so at INFO.
NO_PACKETS_AFTER = 10.0

#: The two collections, in the order they are requested: (report id, which
#: meter types).
REPORTS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, ("channel", "aux")),
    (2, ("bus", "main", "matrix")),
)


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


def requests(udp_port: int) -> tuple[bytes, list[bytes], list[bytes]]:
    """The bytes a Watch sends, as (declaration, one request per report,
    one renewal per report), framed for the native channel. Nothing else
    is ever sent: this is the whole of what Watch says to the desk's
    native port."""
    framing: dict = {}
    declaration = _stuff(METERING_CHANNEL_ID, bytes([_TOKEN_UDP_PORT]) + struct.pack(">H", udp_port),
                         framing)
    asks, renewals = [], []
    for report_id, types in REPORTS:
        ident = bytes([_TOKEN_REPORT_ID]) + struct.pack(">I", report_id)
        asks.append(_stuff(METERING_CHANNEL_ID, ident + meter_collection(types), framing))
        renewals.append(_stuff(METERING_CHANNEL_ID, ident, framing))
    return declaration, asks, renewals


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


# --- the timer -------------------------------------------------------------


@dataclass(frozen=True)
class StripClip:
    """One strip with an ERROR standing: what `L003` says about it."""

    base: str                    # "/ch/3"
    count: int                   # separate clips since the ERROR went up
    ago: float                   # seconds since the last clipped packet
    remaining: float             # seconds until it clears unless it clips again
    longest: float | None = None  # longest clip, seconds -- None when not measurable


@dataclass
class _Episode:
    first_at: float
    last_at: float
    source: object = 0
    count: int = 1
    run_start: float = 0.0
    longest_packets: int = 1
    run_packets: int = 1


class ClipTracker:
    """Per-strip clip timers, driven by the times its caller passes.

    `observe(now, clipped, source)` is one meter packet: the set of strips
    that clipped in it, from the report `source` (each report has its own
    packet stream, so runs and rates are kept per source). `snapshot(now)`
    is every strip whose ERROR stands.

    A strip's episode starts at its first clip; each later clip -- a run
    of clipped packets is one clip, however long -- adds to its count and
    moves its end `hold` seconds past it; and the episode is over once
    `hold` seconds pass with no clip. A strip that clips after that starts
    a new episode, which is a new finding.
    """

    def __init__(self, hold: float = HOLD_SECONDS) -> None:
        self.hold = hold
        self._episodes: dict[str, _Episode] = {}
        self._last_clipped: dict[object, set[str]] = {}
        self._last_packet_at: dict[object, float] = {}
        self._intervals: dict[object, float] = {}
        self.packets = 0
        self._lock = threading.Lock()

    @property
    def interval(self) -> float | None:
        """Seconds between packets, smoothed -- the slowest report's, which
        is the resolution the least certain duration has. None until a
        report has sent two."""
        with self._lock:
            return max(self._intervals.values()) if self._intervals else None

    def observe(self, now: float, clipped: Iterable[str], source: object = 0) -> None:
        clipped = set(clipped)
        with self._lock:
            before = self._last_packet_at.get(source)
            if before is not None and 0 < now - before < 2.0:
                old = self._intervals.get(source)
                dt = now - before
                self._intervals[source] = dt if old is None else 0.8 * old + 0.2 * dt
            self._last_packet_at[source] = now
            self.packets += 1
            self._expire(now)
            previous = self._last_clipped.get(source, set())
            for base in clipped:
                ep = self._episodes.get(base)
                if ep is None:
                    self._episodes[base] = _Episode(now, now, source, run_start=now)
                elif base in previous and now - ep.last_at < RUN_GAP:
                    ep.run_packets += 1          # the same clip, still going
                    ep.last_at = now
                    ep.longest_packets = max(ep.longest_packets, ep.run_packets)
                else:
                    ep.count += 1                # a new clip, the minute restarts
                    ep.last_at = now
                    ep.run_start = now
                    ep.run_packets = 1
            self._last_clipped[source] = clipped

    def _expire(self, now: float) -> None:
        for base in [b for b, ep in self._episodes.items() if now - ep.last_at >= self.hold]:
            del self._episodes[base]

    def snapshot(self, now: float) -> tuple[StripClip, ...]:
        with self._lock:
            self._expire(now)
            out = []
            for base, ep in self._episodes.items():
                interval = self._intervals.get(ep.source)
                longest = None
                if interval is not None and interval <= MAX_DURATION_INTERVAL:
                    # N consecutive packets cover N intervals.
                    seconds = ep.longest_packets * interval
                    if seconds >= MIN_DURATION:
                        longest = seconds
                out.append(StripClip(base, ep.count, now - ep.last_at,
                                     self.hold - (now - ep.last_at), longest))
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
                 udp_socket: "Callable[[], socket.socket] | None" = None) -> None:
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
        #: Reports (by id) whose packets were not the size the layout says.
        self._bad_reports: dict[int, int] = {}
        self._strips = {rid: report_strips(types) for rid, types in REPORTS}

    # -- the public face --

    def start(self) -> None:
        self._started_at = self.clock()
        self._thread = threading.Thread(target=self._run, name="atoo-clip-monitor", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def snapshot(self) -> tuple[StripClip, ...]:
        return self.tracker.snapshot(self.clock())

    def status(self) -> ClipStatus:
        with self._lock:
            problem = self._problem
            bad = dict(self._bad_reports)
        threshold = f"{CLIP_THRESHOLD_DB:g} dBFS"
        off = "Clip detection is off, and Watch carries on without it: "
        if problem:
            return ClipStatus(False, "off", off + problem)
        now = self.clock()
        if self._first_packet_at is None and bad:
            said = ", ".join(_report_name(r) for r in sorted(bad))
            return ClipStatus(False, "off: unexpected meter layout",
                              off + f"the console's meter packets for {said} are not the size "
                              "the layout says, so none are read.")
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
        rate = self._rate()
        said = ", ".join(_report_name(r) for r in sorted(bad))
        parts = [f"Listening to the console's meters for clips (a strip clips at {threshold}); "
                 f"an ERROR stands for {HOLD_SECONDS:.0f} s after its last clip."]
        summary = "on"
        if rate:
            summary = f"on, {rate:.0f} packets/s" if rate >= 2 else f"on, {rate:.1f} packets/s"
            parts.append(f"Meter packets are arriving about {rate:.1f} times a second"
                         + ("" if self.tracker.interval is not None
                            and self.tracker.interval <= MAX_DURATION_INTERVAL
                            else ", too slowly to say how long a clip lasted") + ".")
        if bad:
            summary += f"; {said} not read"
            parts.append(f"The console's meter packets for {said} are not the size the layout "
                         "says, so those are not read.")
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
            declaration, asks, renewals = requests(udp.getsockname()[1])
            tcp.sendall(declaration + b"".join(asks))
            self._loop(udp, tcp, renewals)
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

    def _loop(self, udp: socket.socket, tcp: socket.socket, renewals: list[bytes]) -> None:
        last_renew = self.clock()
        while not self._stop.is_set():
            now = self.clock()
            if now - last_renew >= RENEW_SECONDS:
                tcp.sendall(b"".join(renewals))
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
                    self.feed(data)

    def feed(self, data: bytes) -> None:
        """One UDP datagram. A packet that is not one of ours, or is not the
        size its report's layout says, is not read (and the second kind is
        remembered, for the status)."""
        try:
            report_id, words = parse_packet(data)
        except ValueError:
            return
        strips = self._strips.get(report_id)
        if strips is None:
            return
        if len(words) != WORDS_PER_STRIP * len(strips):
            with self._lock:
                self._bad_reports[report_id] = len(words)
            return
        with self._lock:
            if self._first_packet_at is None:
                self._first_packet_at = self.clock()
        self.tracker.observe(self.clock(), clipped_strips(strips, words), report_id)


_PLURAL = {"channel": "channels", "aux": "aux", "bus": "busses", "main": "mains",
           "matrix": "matrices"}


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
        return replace(provider(), clips=monitor.snapshot(), clip_status=monitor.status())

    return detecting, monitor.close


def _report_name(report_id: int) -> str:
    return ", ".join(_PLURAL[t] for t in dict(REPORTS)[report_id])


def _why(exc: OSError) -> str:
    return exc.strerror or str(exc)
