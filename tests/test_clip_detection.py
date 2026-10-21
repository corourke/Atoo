"""Watch raises an ERROR for about a minute when a strip clips (`atoo/metering.py`, rule L003).

Everything here is synthetic: meter packets are built in the test, time is
handed to the tracker rather than read, and the "console" the monitor talks
to is a loopback server in a thread. Nothing reaches a network, and no
example bundle is read.

What is pinned, in the issue's words: a single clip raises the ERROR; a
second clip at 40 s keeps it up until 100 s; it clears 60 s after the last
clip; two strips are timed separately; a stereo strip gives one finding;
a lost connection gives an INFO, not a crash. Beside those: the bytes a
Watch sends the desk (nothing but a port declaration, one meter request
and its renewals), the level words that count as a clip, that a clip is a
run which ends only after the strip stays quiet, that a stream which
stops is said to have stopped, and that the Watch page keeps showing the
finding's sentence as it changes.

The "console" is a fake that behaves as the WING Compact was measured to:
it keeps only the LAST meter request on a connection, answers with just
what that request asked for, and stops the stream when sent a renewal for
a report id it is not serving.
"""

from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from atoo import metering
from atoo.audit import ConsoleState, DEFAULT_RULES, run_audit
from atoo.diagnostics import Severity
from atoo.metering import (CLIP_THRESHOLD, REPORT_ID, REPORT_TYPES, RELEASE_THRESHOLD, ClipMonitor,
                           ClipTracker, StripClip, WORDS_PER_STRIP, clipped_strips, parse_packet,
                           report_strips, requests)
from atoo.watch import CLIP_STATUS_RULE_ID, WatchNote, finding_key, present_findings, watch

ALL = report_strips(REPORT_TYPES)
CH = ALL[:48]                       # channels 1-40, aux 1-8
BUSES = ALL[48:]                    # bus 1-16, main 1-4, matrix 1-8

QUIET = -128 * 256        # a strip with nothing on it: -128 dB
HOT = 0                   # 0 dBFS


def packet(report_id: int, strips: list[str], levels: dict[str, tuple[int, ...]] | None = None) -> bytes:
    """A meter packet for a report: every strip quiet but those in
    `levels`, which map to their words (padded with quiet)."""
    words: list[int] = []
    for base in strips:
        block = list((levels or {}).get(base, ())) + [QUIET] * WORDS_PER_STRIP
        words.extend(block[:WORDS_PER_STRIP])
    return struct.pack(">I", report_id) + struct.pack(f">{len(words)}h", *words)


# ---- what is sent to the desk -----------------------------------------------


def test_the_declaration_is_the_specs_own_worked_example():
    """`dfd3d33737` (pp97-98): select the metering channel, declare UDP
    port 0x3737."""
    declaration, _asks, _renewals = requests(0x3737)
    assert declaration.hex() == "dfd3d33737"


def test_the_only_things_sent_are_a_port_one_meter_request_and_its_renewals():
    declaration, ask, renewal = requests(40000)
    # The channel is selected once, in the declaration; after that the
    # request is the report id (0xd4) and one collection (0xdc ... 0xde).
    assert declaration == bytes([0xDF, 0xD3, 0xD3]) + struct.pack(">H", 40000)
    assert ask == bytes([0xD4, 0, 0, 0, REPORT_ID]) + metering.meter_collection(REPORT_TYPES)
    # A renewal is the whole request again, the form measured to keep a
    # stream going.
    assert renewal == ask
    # Nothing in any of it is a token that sets a parameter: only the
    # report-id and collection tokens and type/index bytes.
    assert ask[5] == 0xDC and ask[-1] == 0xDE
    assert set(ask[6:-1]) <= set(range(0x00, 0x28)) | {0xA0, 0xA1, 0xA2, 0xA3, 0xA4}


def test_one_collection_names_every_strip_of_every_type_in_the_order_they_are_split():
    one = metering.meter_collection(REPORT_TYPES)
    assert one[0] == 0xDC and one[-1] == 0xDE
    types = [b for b in one[1:-1] if b >= 0xA0]
    assert types == [0xA0, 0xA1, 0xA2, 0xA3, 0xA4]
    assert len(one) == 2 + 5 + 76
    # Table 4's limit is 128 indices to a collection.
    assert 76 <= 128
    assert len(ALL) == 76 and ALL[0] == "/ch/1" and ALL[40] == "/aux/1" and ALL[48] == "/bus/1"
    assert ALL[64] == "/main/1" and ALL[68] == "/mtx/1" and ALL[-1] == "/mtx/8"


def test_the_strips_are_named_as_the_rest_of_watch_names_them():
    assert CH[0] == "/ch/1" and CH[39] == "/ch/40" and CH[40] == "/aux/1" and CH[-1] == "/aux/8"
    assert BUSES[0] == "/bus/1" and "/main/4" in BUSES and BUSES[-1] == "/mtx/8"


# ---- which words are a clip -------------------------------------------------


def test_a_strip_clips_when_a_level_word_is_within_half_a_dB_of_full_scale():
    one = CH[:3]
    assert CLIP_THRESHOLD == -128          # -0.5 dBFS in 1/256 dB
    quiet = [QUIET] * (3 * WORDS_PER_STRIP)
    assert clipped_strips(one, quiet) == set()

    def with_word(strip: int, word: int, value: int) -> list[int]:
        words = list(quiet)
        words[strip * WORDS_PER_STRIP + word] = value
        return words

    assert clipped_strips(one, with_word(1, 0, HOT)) == {"/ch/2"}
    assert clipped_strips(one, with_word(1, 0, CLIP_THRESHOLD)) == {"/ch/2"}
    assert clipped_strips(one, with_word(1, 0, CLIP_THRESHOLD - 1)) == set()
    assert clipped_strips(one, with_word(1, 0, 6 * 256)) == {"/ch/2"}      # over


def test_input_and_output_words_count_and_the_gate_and_dynamics_words_do_not():
    one = ["/ch/1"]
    for word, clips in ((0, True), (1, True), (2, True), (3, True),
                        (4, False), (5, False), (6, False), (7, False)):
        words = [QUIET] * WORDS_PER_STRIP
        words[word] = HOT
        assert (clipped_strips(one, words) == {"/ch/1"}) is clips, word


def test_both_sides_of_a_stereo_strip_are_one_strip():
    words = [HOT, HOT, HOT, HOT] + [QUIET] * 4          # L and R, in and out
    assert clipped_strips(["/bus/5"], words) == {"/bus/5"}


# ---- the timer --------------------------------------------------------------


def seconds(tracker: ClipTracker, now: float) -> dict[str, StripClip]:
    return {c.base: c for c in tracker.snapshot(now)}


def test_a_single_clip_stands_for_sixty_seconds_and_then_clears():
    t = ClipTracker()
    t.observe(100.0, {"/ch/3"})
    assert list(seconds(t, 100.0)) == ["/ch/3"]
    assert list(seconds(t, 159.9)) == ["/ch/3"]
    assert seconds(t, 160.0) == {}


def test_a_second_clip_at_40_seconds_keeps_it_up_until_100():
    t = ClipTracker()
    t.observe(0.0, {"/ch/3"})
    t.observe(10.0, set())
    t.observe(40.0, {"/ch/3"})
    held = seconds(t, 99.9)
    assert list(held) == ["/ch/3"]
    assert held["/ch/3"].count == 2
    assert held["/ch/3"].ago == pytest.approx(59.9)
    assert held["/ch/3"].remaining == pytest.approx(0.1)
    assert seconds(t, 100.0) == {}


def test_two_strips_are_timed_separately():
    t = ClipTracker()
    t.observe(0.0, {"/ch/3"})
    t.observe(30.0, {"/bus/5"})
    assert set(seconds(t, 45.0)) == {"/ch/3", "/bus/5"}
    assert set(seconds(t, 61.0)) == {"/bus/5"}
    assert set(seconds(t, 89.0)) == {"/bus/5"}
    assert seconds(t, 90.0) == {}


def test_a_clip_after_the_minute_is_a_new_episode_not_a_second_count():
    t = ClipTracker()
    t.observe(0.0, {"/ch/3"})
    assert seconds(t, 61.0) == {}
    t.observe(70.0, {"/ch/3"})
    assert seconds(t, 71.0)["/ch/3"].count == 1


def test_a_run_of_clipped_packets_is_one_clip_and_a_long_enough_quiet_makes_the_next_a_second():
    t = ClipTracker()
    for i in range(5):
        t.observe(i * 0.05, {"/ch/3"})            # one clip, five packets
    assert seconds(t, 1.0)["/ch/3"].count == 1
    t.observe(0.25, set())
    t.observe(0.50, set())                        # more than 200 ms quiet
    t.observe(0.55, {"/ch/3"})                    # a second
    assert seconds(t, 1.0)["/ch/3"].count == 2


def test_a_level_hovering_at_the_threshold_is_one_clip_not_hundreds():
    """Packets at 20/s whose strip flickers between clipped and just under
    it (above the release level) are one run."""
    t = ClipTracker()
    for i in range(200):                          # 10 s
        now = i * 0.05
        t.observe(now, {"/ch/3"} if i % 3 else set(), {"/ch/3"})
    clip = seconds(t, 10.0)["/ch/3"]
    assert clip.count == 1
    assert clip.longest == pytest.approx(9.9, abs=0.2)


def test_dips_shorter_than_the_release_time_do_not_end_a_clip_and_longer_ones_do():
    t = ClipTracker()
    t.observe(0.00, {"/ch/3"})
    t.observe(0.05, set())                        # quiet from here ...
    t.observe(0.15, set())
    t.observe(0.20, {"/ch/3"})                    # ... 150 ms: the same clip
    assert seconds(t, 0.3)["/ch/3"].count == 1
    t.observe(0.25, set())
    t.observe(0.50, set())
    t.observe(0.55, {"/ch/3"})                    # 350 ms quiet: a second clip
    assert seconds(t, 0.6)["/ch/3"].count == 2


def test_the_release_level_is_minus_three_dBFS_and_a_level_between_it_and_a_clip_holds_a_run():
    assert RELEASE_THRESHOLD == -3 * 256
    strips = ["/ch/1"]
    just_under = [RELEASE_THRESHOLD + 1] + [QUIET] * 7
    quiet = [RELEASE_THRESHOLD - 1] + [QUIET] * 7
    assert clipped_strips(strips, just_under, RELEASE_THRESHOLD) == {"/ch/1"}
    assert clipped_strips(strips, just_under) == set()
    assert clipped_strips(strips, quiet, RELEASE_THRESHOLD) == set()
    t = ClipTracker()
    t.observe(0.0, {"/ch/1"}, {"/ch/1"})
    for i in range(1, 20):                        # a full second at -2 dBFS
        t.observe(i * 0.05, set(), {"/ch/1"})
    t.observe(1.0, {"/ch/1"}, {"/ch/1"})
    assert seconds(t, 1.0)["/ch/1"].count == 1


def test_clipped_packets_far_apart_are_two_clips_even_with_nothing_heard_between():
    t = ClipTracker()
    t.observe(0.0, {"/ch/3"})
    t.observe(40.0, {"/ch/3"})
    assert seconds(t, 41.0)["/ch/3"].count == 2


def test_how_long_it_lasted_is_the_run_of_packets_at_the_packet_rate():
    t = ClipTracker()
    t.observe(0.0, set())
    for i in range(1, 25):                        # 20 packets/s, a 1.2 s run
        t.observe(i * 0.05, {"/ch/3"})
    clip = seconds(t, 1.3)["/ch/3"]
    assert clip.longest == pytest.approx(24 * 0.05, abs=0.01)
    # A clip of a single packet is shorter than anything worth saying.
    t2 = ClipTracker()
    for i in range(4):
        t2.observe(i * 0.05, {"/ch/9"} if i == 2 else set())
    assert seconds(t2, 1.0)["/ch/9"].longest is None


def test_a_packet_rate_too_slow_to_time_a_clip_says_that_it_clipped_and_nothing_more():
    t = ClipTracker()
    for i in range(6):                            # 2 packets/s
        t.observe(i * 0.5, {"/ch/3"})
    assert t.interval == pytest.approx(0.5)
    assert seconds(t, 3.0)["/ch/3"].longest is None


# ---- the rule ---------------------------------------------------------------


def state_with(*clips: StripClip, names: dict[str, str] | None = None) -> ConsoleState:
    values = {f"{base}/name": name for base, name in (names or {}).items()}
    return ConsoleState(values, clips=tuple(clips))


def l003(state: ConsoleState):
    return [f for f in run_audit(state, list(DEFAULT_RULES)) if f.rule_id == "L003"]


def test_a_clip_is_an_error_named_the_way_the_desk_labels_the_strip():
    (finding,) = l003(state_with(StripClip("/ch/3", 1, 12.0, 48.0),
                                 names={"/ch/3": "Kick"}))
    assert finding.severity is Severity.ERROR and finding.title == "Clipped"
    assert finding.category == "levels"
    assert finding.detail == ('CH 3 "Kick" clipped; the last was 12 s ago. '
                              "This clears in 48 s unless it clips again.")
    assert finding.addresses == ("/ch/3/clip",)


def test_the_sentence_says_how_often_and_how_long_when_it_can():
    (finding,) = l003(state_with(StripClip("/bus/5", 3, 4.0, 56.0, longest=1.2),
                                 names={"/bus/5": "Drums"}))
    assert finding.detail == ('BUS 5 "Drums" clipped 3 times (a clip ends once the level stays '
                              'below -3 dBFS for 200 ms), the longest for about 1.2 s; '
                              "the last was 4.0 s ago. This clears in 56 s unless it clips again.")
    (one,) = l003(state_with(StripClip("/main/1", 1, 30.0, 30.0, longest=0.4)))
    assert one.detail.startswith("MAIN 1 clipped for about 0.4 s; the last was 30 s ago.")


def test_a_strip_with_no_clip_and_a_state_with_none_say_nothing():
    assert l003(ConsoleState({})) == []
    assert l003(state_with()) == []


def test_every_kind_of_strip_has_a_clip_finding():
    bases = ["/ch/1", "/aux/2", "/bus/3", "/main/1", "/mtx/4"]
    found = l003(state_with(*(StripClip(b, 1, 1.0, 59.0) for b in bases)))
    assert [f.addresses[0] for f in found] == [f"{b}/clip" for b in bases]
    assert [f.detail.split(" clipped")[0] for f in found] == [
        "CH 1", "AUX 2", "BUS 3", "MAIN 1", "MTX 4"]


# ---- through watch() --------------------------------------------------------


def run_watch(passes: list[tuple[float, ClipTracker | None]], names=None):
    """Each pass reads a state whose clips are the tracker's at that time."""
    tracker = ClipTracker()
    events = []
    times = iter(passes)
    schedule = []

    def provider():
        now, action = next(times)
        if action is not None:
            action(tracker)
        schedule.append(now)
        return ConsoleState({f"{b}/name": n for b, n in (names or {}).items()},
                            clips=tracker.snapshot(now),
                            clip_status=metering.ClipStatus(True, "on", "listening"))

    for event in watch(provider, interval=0, max_iterations=len(passes), sleep=lambda s: None):
        events.append(event)
    return events


def test_the_error_is_new_once_stays_through_a_restart_and_clears_sixty_seconds_after_the_last_clip():
    names = {"/ch/3": "Kick"}
    events = run_watch([
        (0.0, None),
        (5.0, lambda t: t.observe(2.0, {"/ch/3"})),     # a clip: new
        (30.0, None),
        (45.0, lambda t: t.observe(40.0, {"/ch/3"})),   # clips again: same finding
        (99.0, None),                                    # 59 s after the last clip
        (101.0, None),                                   # 61 s after
    ], names)

    def l003s(event):
        return [f for f in event.all_findings if f.rule_id == "L003"]

    assert [len(l003s(e)) for e in events] == [0, 1, 1, 1, 1, 0]
    clip_news = [[f.rule_id for f in e.new_findings if f.rule_id == "L003"] for e in events]
    assert clip_news == [[], ["L003"], [], [], [], []]          # the restart does not re-alert
    assert [[f.rule_id for f in e.cleared_findings if f.rule_id == "L003"] for e in events] == [
        [], [], [], [], [], ["L003"]]
    # The restart is seen in the sentence.
    assert "clipped; the last was 28 s ago" in l003s(events[2])[0].detail
    assert "clipped 2 times (a clip ends once the level stays below -3 dBFS for 200 ms); the last was 5.0 s ago" in l003s(events[3])[0].detail
    assert "This clears in 1.0 s" in l003s(events[4])[0].detail


def test_a_stereo_strip_is_one_finding_through_the_whole_path():
    """A packet with left and right, input and output all hot is one
    finding on one strip."""
    strips = ["/bus/5", "/bus/6"]
    t = ClipTracker()
    t.observe(0.0, clipped_strips(strips, [HOT, HOT, HOT, HOT] + [QUIET] * 4 + [QUIET] * 8))
    state = ConsoleState({}, clips=t.snapshot(0.5))
    assert [f.addresses for f in l003(state)] == [("/bus/5/clip",)]


def test_the_clip_note_is_an_info_beside_the_findings_not_a_row_in_the_table():
    (event,) = run_watch([(0.0, None)])
    notes = [f for f in event.all_findings if f.rule_id == CLIP_STATUS_RULE_ID]
    assert len(notes) == 1 and notes[0].severity is Severity.INFO
    assert isinstance(notes[0], WatchNote) and notes[0].group == "Clip detection"
    shown = present_findings(event.all_findings)
    assert [n.rule_id for n in shown.notes if n.rule_id == CLIP_STATUS_RULE_ID]
    assert not [a for a in shown.alerts if a.rule_id == CLIP_STATUS_RULE_ID]


def test_a_state_with_no_clip_status_carries_no_note_and_audit_is_untouched():
    findings = run_audit(ConsoleState({}), list(DEFAULT_RULES))
    assert not [f for f in findings if f.rule_id in ("L003", CLIP_STATUS_RULE_ID)]
    events = list(watch(lambda: ConsoleState({}), interval=0, max_iterations=1,
                        sleep=lambda s: None))
    assert not [f for f in events[0].all_findings if f.rule_id == CLIP_STATUS_RULE_ID]


def test_the_note_is_keyed_on_off_so_the_command_line_says_when_it_changes():
    on = metering.ClipStatus(True, "on", "x")
    off = metering.ClipStatus(False, "off", "y")
    from atoo.watch import clip_status_note
    assert finding_key(clip_status_note(on)) != finding_key(clip_status_note(off))


# ---- the monitor, against a loopback "console" -------------------------------


class FakeConsole:
    """The desk's native port, behaving as the WING Compact was measured to.

    It accepts one connection and reads what it is sent as the desk does:
    a UDP port declaration (0xd3), a report id (0xd4) alone, or a report id
    followed by a collection (0xdc ... 0xde).

    - **It keeps only the last collection request** on the connection: a
      second request replaces the first, so a monitor that asks for two
      collections is only ever served the second.
    - **It serves exactly what that collection asked for**, in order, eight
      words a strip -- `meters()` builds the packet from it.
    - **A report id alone for an id it is not serving stops the stream**
      (`stopped`), and a meter request not renewed within `timeout` desk
      seconds (the `clock`) does too. A renewal that is the full request
      keeps it going.
    """

    def __init__(self, clock=None, timeout: float = 5.0) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.received = bytearray()
        self.conn: socket.socket | None = None
        self.clock = clock or time.monotonic
        self.timeout = timeout
        self.lock = threading.Lock()
        self.udp_port: int | None = None
        self.declarations = 0
        self.requests_seen = 0
        self.serving: tuple[int, list[tuple[int, int]]] | None = None    # (report id, [(type, count)])
        self.stopped = False
        self.renewed_at = 0.0
        self._pos = 0
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        self.server.settimeout(0.2)
        while not self._stop.is_set():
            try:
                self.conn, _ = self.server.accept()
                break
            except socket.timeout:
                continue
        if self.conn is None:
            return
        self.conn.settimeout(0.1)
        while not self._stop.is_set():
            try:
                data = self.conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.received.extend(data)
                self._parse()

    def _parse(self) -> None:
        buf = bytes(self.received)
        i = self._pos
        while i < len(buf):
            tok = buf[i]
            if tok == 0xDF:                       # channel select
                i += 2
            elif tok == 0xD3:
                if i + 3 > len(buf):
                    break
                self.udp_port = struct.unpack(">H", buf[i + 1:i + 3])[0]
                self.declarations += 1
                i += 3
            elif tok == 0xD4:
                if i + 5 > len(buf):
                    break
                report_id = struct.unpack(">I", buf[i + 1:i + 5])[0]
                j = i + 5
                if j < len(buf) and buf[j] == 0xDC:          # a collection follows
                    end = buf.find(bytes([0xDE]), j)
                    if end < 0:
                        break
                    self._collection(report_id, buf[j + 1:end])
                    i = end + 1
                else:
                    if j >= len(buf):
                        # An id alone, or the start of a request not yet in?
                        # The desk reads the next byte, so wait for it.
                        break
                    self._renewal(report_id)
                    i = j
            else:
                i += 1
        self._pos = i

    def _collection(self, report_id: int, body: bytes) -> None:
        groups: list[tuple[int, int]] = []
        for byte in body:
            if byte >= 0xA0:
                groups.append((byte, 0))
            else:
                kind, count = groups[-1]
                groups[-1] = (kind, count + 1)
        self.requests_seen += 1
        self.serving = (report_id, groups)        # the last request is the only one kept
        self.stopped = False
        self.renewed_at = self.clock()

    def _renewal(self, report_id: int) -> None:
        if self.serving is None or self.serving[0] != report_id:
            self.stopped = True
        else:
            self.renewed_at = self.clock()

    def declared_udp_port(self) -> int:
        deadline = time.time() + 3
        while time.time() < deadline:
            with self.lock:
                if self.udp_port is not None and self.serving is not None:
                    return self.udp_port
            time.sleep(0.02)
        raise AssertionError("the monitor never declared a UDP port and asked for meters")

    def meters(self, levels: dict[str, tuple[int, ...]] | None = None) -> bytes | None:
        """The packet the desk would send now: None when it is not serving."""
        with self.lock:
            if self.serving is None or self.stopped or self.clock() - self.renewed_at > self.timeout:
                return None
            report_id, groups = self.serving
        bases = {0xA0: "ch", 0xA1: "aux", 0xA2: "bus", 0xA3: "main", 0xA4: "mtx"}
        strips = [f"/{bases[kind]}/{n}" for kind, count in groups for n in range(1, count + 1)]
        return packet(report_id, strips, levels)

    def send_meters(self, levels: dict[str, tuple[int, ...]] | None = None) -> bool:
        """One UDP packet to the declared port, if the desk is serving."""
        data = self.meters(levels)
        if data is None or self.udp_port is None:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(data, ("127.0.0.1", self.udp_port))
        return True

    def send_raw(self, data: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(data, ("127.0.0.1", self.udp_port))

    def drop(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def close(self) -> None:
        self._stop.set()
        for s in (self.conn, self.server):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


@pytest.fixture
def console():
    fake = FakeConsole()
    yield fake
    fake.close()


def wait_for(condition, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def monitor_for(console: FakeConsole, **options) -> ClipMonitor:
    return ClipMonitor(
        "127.0.0.1", port=console.port,
        connect=lambda: socket.create_connection(("127.0.0.1", console.port), timeout=2), **options)


def test_the_fake_console_keeps_only_the_last_request_and_stops_on_an_unknown_renewal():
    """The fake is what lets CI see the failure the real desk showed."""
    fake = FakeConsole()
    try:
        client = socket.create_connection(("127.0.0.1", fake.port))
        declaration, _, _ = requests(40001)
        first = bytes([0xD4, 0, 0, 0, 1]) + metering.meter_collection(("channel", "aux"))
        second = bytes([0xD4, 0, 0, 0, 2]) + metering.meter_collection(("bus", "main", "matrix"))
        client.sendall(declaration + first + second)
        fake.declared_udp_port()
        assert wait_for(lambda: fake.requests_seen == 2)
        packet_ = fake.meters()
        assert parse_packet(packet_)[0] == 2 and len(parse_packet(packet_)[1]) == 8 * 28
        client.sendall(bytes([0xD4, 0, 0, 0, 1]) + b"\xd4")          # renew report 1: not served
        assert wait_for(lambda: fake.stopped)
        assert fake.meters() is None
        client.close()
    finally:
        fake.close()


def test_the_monitor_declares_a_port_asks_once_and_hears_a_clip_on_a_channel_and_a_bus(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        udp = console.declared_udp_port()
        declaration, ask, _ = requests(udp)
        assert wait_for(lambda: bytes(console.received) == declaration + ask)
        assert console.requests_seen == 1
        assert console.send_meters()
        assert wait_for(lambda: monitor.status().summary.startswith("on"))
        assert monitor.snapshot() == ()
        # Channel 3 and bus 2, in the same packet, as the desk sends them.
        assert console.send_meters({"/ch/3": (HOT, QUIET, QUIET, QUIET),
                                    "/bus/2": (QUIET, QUIET, HOT, HOT),
                                    "/mtx/8": (HOT,)})
        assert wait_for(lambda: {c.base for c in monitor.snapshot()} == {"/ch/3", "/bus/2", "/mtx/8"})
        status = monitor.status()
        assert status.on and "ERROR stands for 60 s" in status.detail
    finally:
        monitor.close()


def test_renewals_keep_the_desk_serving_and_a_clip_after_them_is_still_heard(console):
    clock = [0.0]
    console.clock = lambda: clock[0]
    monitor = monitor_for(console, clock=lambda: clock[0])
    monitor.start()
    try:
        console.declared_udp_port()
        for step in range(1, 5):                  # 8 desk-seconds, renewed every 2
            clock[0] = step * 2.0
            seen = console.requests_seen
            assert wait_for(lambda: console.requests_seen > seen), "no renewal sent"
            assert not console.stopped
        assert console.requests_seen == 5 and console.serving[0] == REPORT_ID
        assert console.send_meters({"/ch/1": (HOT,)})
        assert wait_for(lambda: {c.base for c in monitor.snapshot()} == {"/ch/1"})
    finally:
        monitor.close()


def test_a_packet_from_a_stranger_or_for_a_report_we_did_not_ask_for_is_ignored(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        console.declared_udp_port()
        console.send_raw(packet(9, ALL, {"/ch/3": (HOT,)}))               # not our report
        console.send_raw(b"\x00\x01")                                     # not a packet
        console.send_meters()
        assert wait_for(lambda: monitor.status().on and monitor.status().summary.startswith("on"))
        assert monitor.snapshot() == ()
    finally:
        monitor.close()


def test_a_packet_of_another_size_cannot_be_split_so_none_is_read_and_the_status_says_so(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        console.declared_udp_port()
        short = struct.pack(">I", REPORT_ID) + struct.pack(">28h", *([HOT] * 28))
        console.send_raw(short)
        assert wait_for(lambda: monitor.status().summary == "off: unexpected meter layout")
        assert monitor.snapshot() == ()
        detail = monitor.status().detail
        assert "28 words, not the 608 the layout says" in detail and "none are read" in detail
        assert "40 channel, 8 aux, 16 bus, 4 main, 8 matrix" in detail
        console.send_meters({"/ch/7": (HOT,)})                             # a good packet works
        assert wait_for(lambda: {c.base for c in monitor.snapshot()} == {"/ch/7"})
        assert "not read" in monitor.status().summary
    finally:
        monitor.close()


def test_meter_data_that_stops_is_said_to_have_stopped_and_asked_for_again(console):
    clock = [0.0]
    console.clock = lambda: clock[0]
    monitor = monitor_for(console, clock=lambda: clock[0])
    monitor.start()
    try:
        console.declared_udp_port()
        console.send_meters()
        assert wait_for(lambda: monitor.status().summary.startswith("on"))
        clock[0] = 2.0
        assert monitor.status().on                               # a quiet moment is not a stall
        clock[0] = 4.5
        status = monitor.status()
        assert not status.on and status.summary == "off: meter data stopped"
        assert "meter data stopped" in status.detail and "asking the console for it again" in status.detail
        # It asks again, declaration included.
        before = console.declarations
        assert wait_for(lambda: console.declarations > before)
        # And when packets come back, so does the detection.
        clock[0] = 5.0
        console.renewed_at = clock[0]
        console.send_meters({"/ch/2": (HOT,)})
        assert wait_for(lambda: monitor.status().on)
        assert {c.base for c in monitor.snapshot()} == {"/ch/2"}
    finally:
        monitor.close()


def test_a_desk_that_stopped_serving_is_noticed_through_the_page_note(console):
    clock = [0.0]
    console.clock = lambda: clock[0]
    provider, close = metering.with_clip_detection(
        lambda: ConsoleState({}), "127.0.0.1", port=console.port, clock=lambda: clock[0],
        connect=lambda: socket.create_connection(("127.0.0.1", console.port), timeout=2))
    try:
        console.declared_udp_port()
        console.send_meters()
        assert wait_for(lambda: provider().clip_status.on and provider().clip_status.summary != "starting")
        clock[0] = 10.0
        (event,) = list(watch(provider, interval=0, max_iterations=1, sleep=lambda s: None))
        (note,) = [f for f in event.all_findings if f.rule_id == CLIP_STATUS_RULE_ID]
        assert note.title == "Clip detection is off" and "meter data stopped" in note.detail
    finally:
        close()


def test_a_lost_connection_is_an_info_and_not_a_crash(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        console.declared_udp_port()
        console.send_meters({"/ch/3": (HOT,)})
        assert wait_for(lambda: monitor.snapshot())
        console.drop()
        assert wait_for(lambda: not monitor.status().on)
        status = monitor.status()
        assert status.summary == "off" and "connection was lost" in status.detail
        assert "Watch carries on without it" in status.detail
        # And it does: the state a watch reads says so, as one INFO.
        provider, close = metering.with_clip_detection(lambda: ConsoleState({}), "127.0.0.1",
                                                       port=1, connect=_refuse)
        try:
            assert wait_for(lambda: not provider().clip_status.on)
        finally:
            close()
    finally:
        monitor.close()


def _refuse():
    raise ConnectionRefusedError(111, "Connection refused")


def test_a_console_that_refuses_the_connection_says_so_once_and_the_watch_goes_on():
    provider, close = metering.with_clip_detection(
        lambda: ConsoleState({"/ch/1/name": "Kick"}), "192.0.2.1", connect=_refuse)
    try:
        assert wait_for(lambda: not provider().clip_status.on)
        state = provider()
        assert state.clips == () and state.values == {"/ch/1/name": "Kick"}
        assert "could not be opened" in state.clip_status.detail
        assert "24 native client slots" in state.clip_status.detail or "slots" in state.clip_status.detail
        (event,) = list(watch(lambda: provider(), interval=0, max_iterations=1, sleep=lambda s: None))
        notes = [f for f in event.all_findings if f.rule_id == CLIP_STATUS_RULE_ID]
        assert len(notes) == 1 and notes[0].severity is Severity.INFO
        assert notes[0].title == "Clip detection is off"
    finally:
        close()


def test_no_free_udp_port_is_an_info_too():
    def no_udp():
        raise OSError(98, "Address already in use")

    monitor = ClipMonitor("192.0.2.1", udp_socket=no_udp, connect=_refuse)
    monitor.start()
    try:
        assert wait_for(lambda: not monitor.status().on)
        assert "UDP port" in monitor.status().detail
    finally:
        monitor.close()


def test_no_meter_packets_at_all_is_said_after_ten_seconds(console):
    clock = [0.0]
    monitor = monitor_for(console, clock=lambda: clock[0])
    monitor.start()
    try:
        console.declared_udp_port()
        assert monitor.status().summary == "starting"
        clock[0] = 11.0
        status = monitor.status()
        assert not status.on and "no meter data in 11 s" in status.detail
        assert "firewall" in status.detail
    finally:
        monitor.close()


def test_the_packet_rate_is_reported_for_the_desk_test(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        console.declared_udp_port()
        for _ in range(8):
            console.send_meters()
            time.sleep(0.05)
        assert wait_for(lambda: "packets/s" in monitor.status().summary)
        assert "times a second" in monitor.status().detail
    finally:
        monitor.close()


# ---- wiring: the Watch page's provider and the Demo --------------------------


def test_the_watch_pages_console_provider_carries_the_clip_status(monkeypatch):
    from atoo import webui
    import atoo.console as console_module

    class Desk:
        def identity(self):
            return console_module.OscReply(
                address="/?", typetag="s",
                args=["WING,198.51.100.1,DESK,wing-compact,SER,3.1"])

        def close(self):
            pass

    monkeypatch.setattr(console_module, "WingConsole", lambda *a, **k: Desk())
    monkeypatch.setattr(webui, "read_console_state", lambda *a, **k: ConsoleState({}))
    provider, close = webui.console_provider_factory("198.51.100.1", name_refresh=1)
    try:
        assert wait_for(lambda: provider().clip_status is not None
                        and not provider().clip_status.on)       # conftest refuses the connection
    finally:
        close()
    provider, close = webui.console_provider_factory("198.51.100.1", name_refresh=1,
                                                     clip_detection=False)
    close()
    assert provider().clip_status is None


def test_the_demo_simulates_an_occasional_clip_and_a_restart(monkeypatch):
    from atoo import webui

    monkeypatch.setenv("ATOO_DEMO_SEED", "703")
    monkeypatch.setattr(webui, "DEMO_CLIP_CHANCE", 1.0)
    provider, _ = webui.demo_provider_factory()
    first = provider()
    assert first.clips == ()                       # the baseline is clean
    assert first.clip_status.summary == "simulated"
    later = [provider() for _ in range(6)]
    assert all(s.clips for s in later)
    assert any(s.clips[0].count > 1 or len(s.clips) > 1 for s in later[-3:])
    findings = [f for f in run_audit(later[-1], list(DEFAULT_RULES)) if f.rule_id == "L003"]
    assert findings and all(f.severity is Severity.ERROR for f in findings)
    assert all(f.addresses[0].split("/")[1] in ("ch", "bus", "main") for f in findings)


def test_the_demo_without_clips_is_the_demo_as_it_was(monkeypatch):
    """A seed makes the Demo's faults the same run after run
    (the screenshot script); the clips have a stream of their own, so
    asking for none leaves that order alone."""
    from atoo import webui

    monkeypatch.setenv("ATOO_DEMO_SEED", "703")
    monkeypatch.setattr(webui, "DEMO_CLIP_CHANCE", 0.0)
    provider, _ = webui.demo_provider_factory()
    plain = [provider().values for _ in range(10)]
    monkeypatch.setattr(webui, "DEMO_CLIP_CHANCE", 1.0)
    provider, _ = webui.demo_provider_factory()
    clipping = [provider().values for _ in range(10)]
    assert plain == clipping
