"""Watch raises an ERROR for about a minute when a strip clips (`atoo/metering.py`, rule L003).

Everything here is synthetic: meter packets are built in the test, time is
handed to the tracker rather than read, and the "console" the monitor talks
to is a loopback server in a thread. Nothing reaches a network, and no
example bundle is read.

What is pinned, in the issue's words: a single clip raises the ERROR; a
second clip at 40 s keeps it up until 100 s; it clears 60 s after the last
clip; two strips are timed separately; a stereo strip gives one finding;
a lost connection gives an INFO, not a crash. Beside those: the bytes a
Watch sends the desk (nothing but a port declaration, two meter requests
and their renewals), the level words that count as a clip, and that the
Watch page keeps showing the finding's sentence as it changes.
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
from atoo.metering import (CLIP_THRESHOLD, ClipMonitor, ClipTracker, StripClip, WORDS_PER_STRIP,
                           clipped_strips, parse_packet, report_strips, requests)
from atoo.watch import CLIP_STATUS_RULE_ID, WatchNote, finding_key, present_findings, watch

CH = report_strips(("channel", "aux"))
BUSES = report_strips(("bus", "main", "matrix"))

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


def test_the_only_things_sent_are_a_port_a_pair_of_meter_requests_and_their_renewals():
    declaration, asks, renewals = requests(40000)
    # The channel is selected once, in the declaration; after that each
    # request is the report id (0xd4) and one collection (0xdc ... 0xde).
    assert declaration == bytes([0xDF, 0xD3, 0xD3]) + struct.pack(">H", 40000)
    assert asks[0] == bytes([0xD4, 0, 0, 0, 1]) + metering.meter_collection(("channel", "aux"))
    assert asks[1] == (bytes([0xD4, 0, 0, 0, 2])
                       + metering.meter_collection(("bus", "main", "matrix")))
    # Renewals are the report id alone.
    assert [r.hex() for r in renewals] == ["d400000001", "d400000002"]
    # Nothing in any of it is a token that sets a parameter: only the
    # port, report-id and collection tokens and type/index bytes.
    for ask in asks:
        assert ask[5] == 0xDC and ask[-1] == 0xDE
        assert set(ask[6:-1]) <= set(range(0x00, 0x28)) | {0xA0, 0xA1, 0xA2, 0xA3, 0xA4}


def test_meter_collections_name_every_strip_of_their_types():
    one = metering.meter_collection(("channel", "aux"))
    assert one[0] == 0xDC and one[-1] == 0xDE
    assert one[1] == 0xA0 and list(one[2:42]) == list(range(40))
    assert one[42] == 0xA1 and list(one[43:51]) == list(range(8))
    two = metering.meter_collection(("bus", "main", "matrix"))
    assert two[1] == 0xA2 and list(two[2:18]) == list(range(16))
    assert two[18] == 0xA3 and list(two[19:23]) == list(range(4))
    assert two[23] == 0xA4 and list(two[24:32]) == list(range(8))
    # One collection, at most 128 indices (Table 4).
    assert 40 + 8 <= 128 and 16 + 4 + 8 <= 128


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


def test_a_run_of_clipped_packets_is_one_clip_and_a_gap_makes_the_next_a_second():
    t = ClipTracker()
    for i in range(5):
        t.observe(i * 0.05, {"/ch/3"})            # one clip, five packets
    assert seconds(t, 1.0)["/ch/3"].count == 1
    t.observe(0.25, set())
    t.observe(0.30, {"/ch/3"})                    # a second
    assert seconds(t, 1.0)["/ch/3"].count == 2


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


def test_the_two_reports_keep_their_own_runs():
    """Report 2's packet, between two of report 1's, must not end report 1's
    clip."""
    t = ClipTracker()
    t.observe(0.00, {"/ch/3"}, 1)
    t.observe(0.01, set(), 2)
    t.observe(0.05, {"/ch/3"}, 1)
    t.observe(0.06, set(), 2)
    assert seconds(t, 1.0)["/ch/3"].count == 1


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
    assert finding.detail == ('BUS 5 "Drums" clipped 3 times, the longest for about 1.2 s; '
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
    assert "clipped 2 times; the last was 5.0 s ago" in l003s(events[3])[0].detail
    assert "This clears in 1.0 s" in l003s(events[4])[0].detail


def test_a_stereo_strip_is_one_finding_through_the_whole_path():
    """A packet with left and right, input and output all hot is one
    finding on one strip."""
    strips = ["/bus/5", "/bus/6"]
    t = ClipTracker()
    t.observe(0.0, clipped_strips(strips, [HOT, HOT, HOT, HOT] + [QUIET] * 4 + [QUIET] * 8), 2)
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
    """The desk's native port: accepts one connection, keeps what it is
    sent, and can send UDP meter packets to whoever declared a port."""

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.received = bytearray()
        self.conn: socket.socket | None = None
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
            self.received.extend(data)

    def declared_udp_port(self) -> int:
        deadline = time.time() + 3
        while time.time() < deadline:
            raw = bytes(self.received)
            if raw.startswith(bytes([0xDF, 0xD3, 0xD3])) and len(raw) >= 5:
                return struct.unpack(">H", raw[3:5])[0]
            time.sleep(0.02)
        raise AssertionError("the monitor never declared a UDP port")

    def send_meters(self, udp_port: int, data: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(data, ("127.0.0.1", udp_port))

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


def monitor_for(console: FakeConsole) -> ClipMonitor:
    return ClipMonitor(
        "127.0.0.1", port=console.port,
        connect=lambda: socket.create_connection(("127.0.0.1", console.port), timeout=2))


def test_the_monitor_declares_a_port_asks_for_both_reports_and_hears_a_clip(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        udp = console.declared_udp_port()
        declaration, asks, _ = requests(udp)
        assert wait_for(lambda: bytes(console.received) == declaration + b"".join(asks)
                        or bytes(console.received).startswith(declaration + b"".join(asks)))
        # Quiet packets first, then a clip on channel 3 and on bus 2.
        console.send_meters(udp, packet(1, CH))
        assert wait_for(lambda: monitor.status().summary.startswith("on"))
        assert monitor.snapshot() == ()
        console.send_meters(udp, packet(1, CH, {"/ch/3": (HOT, QUIET, QUIET, QUIET)}))
        console.send_meters(udp, packet(2, BUSES, {"/bus/2": (QUIET, QUIET, HOT, HOT)}))
        assert wait_for(lambda: {c.base for c in monitor.snapshot()} == {"/ch/3", "/bus/2"})
        status = monitor.status()
        assert status.on and "ERROR stands for 60 s" in status.detail
    finally:
        monitor.close()


def test_a_packet_from_a_stranger_or_for_a_report_we_did_not_ask_for_is_ignored(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        udp = console.declared_udp_port()
        console.send_meters(udp, packet(9, CH, {"/ch/3": (HOT,)}))        # not our report
        console.send_meters(udp, b"\x00\x01")                              # not a packet
        console.send_meters(udp, packet(1, CH))
        assert wait_for(lambda: monitor.status().on and monitor.status().summary.startswith("on"))
        assert monitor.snapshot() == ()
    finally:
        monitor.close()


def test_report_two_with_packets_of_another_size_is_switched_off_and_report_one_still_works(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        udp = console.declared_udp_port()
        short = struct.pack(">I", 2) + struct.pack(">28h", *([HOT] * 28))     # 4 words a strip
        console.send_meters(udp, short)
        console.send_meters(udp, packet(1, CH, {"/ch/7": (HOT,)}))
        assert wait_for(lambda: {c.base for c in monitor.snapshot()} == {"/ch/7"})
        status = monitor.status()
        assert status.on and "busses, mains, matrices not read" in status.summary
        assert "not the size the layout says" in status.detail
    finally:
        monitor.close()


def test_a_lost_connection_is_an_info_and_not_a_crash(console):
    monitor = monitor_for(console)
    monitor.start()
    try:
        udp = console.declared_udp_port()
        console.send_meters(udp, packet(1, CH, {"/ch/3": (HOT,)}))
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
    monitor = ClipMonitor(
        "127.0.0.1", port=console.port, clock=lambda: clock[0],
        connect=lambda: socket.create_connection(("127.0.0.1", console.port), timeout=2))
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
        udp = console.declared_udp_port()
        for _ in range(8):
            console.send_meters(udp, packet(1, CH))
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
