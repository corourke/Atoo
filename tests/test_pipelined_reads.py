"""Desk reads with several requests in flight -- an earlier change.

At the desk on 2026-10-13 every request took ~16ms, the network's round
trip, and an `apply` preview of the Demo took almost two minutes, because
every read was strictly serial. `WingConsole.get_many`/`node_dump_many`
keep a bounded window of reads in flight instead, and
`console.read_in_windows`/`node_dumps` are how the long reads use them.

Everything here runs the real `WingConsole` over a real localhost UDP
socket against `tests/udp_desk.UdpDesk`: a `SnapDesk` behind a network
with latency, jitter (so replies come back out of order), addresses the
desk never answers, and replies lost on the way back. What is asserted is
what the serial client guaranteed and the window must not lose:

* every reply is matched to its request by address, however reordered;
* never two requests for one address in flight at once;
* an unanswered address is retried, times out on its own clock and is
  reported, and a lost reply is retried and answered;
* a window of 1 is the serial client, request for request;
* and the reads that use it give the same values, the same unanswered
  addresses and the same `apply` preview at any window.
"""

from __future__ import annotations

import contextlib
import io
import time

import pytest

from atoo import audit, cli
from atoo import console as osc
from atoo import initialize as init
from atoo.apply import apply_plan
from atoo.console import SKIPPED, WingConsole, read_in_windows, window_setting
from atoo.progress import ReadProgress
from tests.snap_desk import SnapDesk
from tests.test_full_apply import tiny
from tests.test_initialize import desk_with, initialized_desk
from tests.udp_desk import UdpDesk


def _desk() -> SnapDesk:
    return initialized_desk()


@contextlib.contextmanager
def _wired(desk, *, window, timeout=0.5, **network):
    with UdpDesk(desk, **network) as udp:
        console = WingConsole("127.0.0.1", port=udp.port, timeout=timeout, window=window)
        try:
            yield console, udp
        finally:
            console.close()


ADDRESSES = ([f"/ch/{n}/fdr" for n in range(1, 21)]
             + [f"/ch/{n}/name" for n in range(1, 11)]
             + [f"/bus/{n}/mute" for n in range(1, 9)])


def _values(replies):
    return [None if r is None else (r.address, r.typetag, r.args) for r in replies]


# -- the window, from the desk's side ------------------------------------------


def test_replies_reordered_by_the_network_each_find_their_own_request():
    expected = [_desk().get(address) for address in ADDRESSES]
    with _wired(_desk(), window=6, latency=0.002, jitter=0.01, seed=3) as (console, udp):
        replies = console.get_many(ADDRESSES)
    assert udp.replies_sent != ADDRESSES, "the jitter did not reorder anything"
    assert _values(replies) == _values(expected)
    assert console.replies_discarded == 0


def test_the_window_bounds_what_is_in_flight_and_is_used():
    with _wired(_desk(), window=5, latency=0.01) as (console, udp):
        console.get_many(ADDRESSES)
    assert udp.max_outstanding == 5


def test_never_two_requests_for_one_address_in_flight():
    """The protocol carries no request id: two replies for one address
    cannot be told apart. So a repeated address waits for the first."""
    addresses = ["/ch/1/fdr", "/ch/1/fdr", "/ch/2/fdr", "/ch/1/fdr", "/ch/2/fdr"]
    with _wired(_desk(), window=8, latency=0.01, jitter=0.005) as (console, udp):
        replies = console.get_many(addresses)
    assert udp.same_address_overlaps == 0
    assert [r.address for r in replies] == addresses
    assert len(udp.requests) == len(addresses)


def test_an_unanswered_address_times_out_on_its_own_clock_and_comes_back_none():
    silent = {"/ch/3/fdr", "/ch/7/name"}
    timeout = 0.2
    with _wired(_desk(), window=8, timeout=timeout, latency=0.002, silent=silent) as (console, udp):
        started = time.monotonic()
        replies = console.get_many(ADDRESSES)
        took = time.monotonic() - started
    by_address = dict(zip(ADDRESSES, replies))
    assert {a for a, r in by_address.items() if r is None} == silent
    asked = [address for address, _ in udp.requests]
    # `retries + 1` sends each, as `_request` makes.
    assert all(asked.count(address) == 3 for address in silent)
    # Waited side by side: about one address's three timeouts, not two.
    assert took < 3 * timeout * 1.8


def test_a_lost_reply_is_asked_again_and_answered():
    with _wired(_desk(), window=8, timeout=0.15, latency=0.002,
                drop_first={"/ch/5/fdr": 1, "/bus/2/mute": 2}) as (console, udp):
        replies = console.get_many(ADDRESSES)
    assert None not in replies
    asked = [address for address, _ in udp.requests]
    assert asked.count("/ch/5/fdr") == 2
    assert asked.count("/bus/2/mute") == 3


def test_a_datagram_nobody_asked_for_is_drained_and_kept_as_a_late_reply():
    from tests.test_console import FakeWingServer

    def handler(address, typetag, args):
        # Every reply comes with a volunteered datagram for another address.
        return [("/dca/8/name", "s", ["late"]), (address, "s", [address])]

    server = FakeWingServer(handler)
    try:
        console = WingConsole("127.0.0.1", port=server.port, timeout=0.5, window=4)
        replies = console.get_many(["/a", "/b", "/c", "/d", "/e"])
        console.close()
    finally:
        server.close()
    assert [r.args for r in replies] == [["/a"], ["/b"], ["/c"], ["/d"], ["/e"]]
    assert console.replies_discarded == 5
    assert console.late_reply("/dca/8/name").args == ["late"]


def test_a_socket_error_ends_the_batch_with_every_unanswered_request_marked():
    class Failing:
        """The console's socket, refusing the seventh send."""

        def __init__(self, sock):
            self.sock, self.sent = sock, 0

        def sendto(self, packet, addr):
            if self.sent == 6:
                raise OSError("No route to host")
            self.sent += 1
            return self.sock.sendto(packet, addr)

        def __getattr__(self, name):
            return getattr(self.sock, name)

    with _wired(_desk(), window=4, latency=0.01) as (console, udp):
        console.sock = Failing(console.sock)
        replies = console.get_many(ADDRESSES[:12])
        console.sock = console.sock.sock
    assert all(r is not None for r in replies)
    # Whatever was answered before the error stands; everything else --
    # in flight or never sent -- is the socket error, which every caller
    # stops the run on.
    failed = [r.is_socket_error for r in replies]
    assert failed[6:] == [True] * 6
    for reply, address in zip(replies, ADDRESSES[:12]):
        assert reply.address == address
        assert reply.is_socket_error or not reply.is_transport_error


def test_node_dumps_in_flight_carry_the_same_text():
    desk = _desk()
    nodes = [f"/ch/{n}" for n in range(1, 9)] + ["/bus/1", "/main/1"]
    with _wired(desk, window=4, latency=0.002, jitter=0.01) as (console, udp):
        dumps = console.node_dump_many(nodes)
    assert dumps == [_desk().node_dump(node) for node in nodes]


# -- a window of 1 is the serial client --------------------------------------------


def test_a_window_of_one_is_the_serial_client_request_for_request():
    network = dict(latency=0.001, silent={"/ch/4/fdr"}, drop_first={"/ch/9/name": 1})
    with _wired(_desk(), window=1, timeout=0.1, **network) as (console, udp):
        serial = [console.get(address) for address in ADDRESSES]
        serial_wire = list(udp.requests)
    network["drop_first"] = {"/ch/9/name": 1}
    with _wired(_desk(), window=1, timeout=0.1, **network) as (console, udp):
        many = console.get_many(ADDRESSES)
        many_wire = list(udp.requests)
    assert many_wire == serial_wire
    assert _values(many) == _values(serial)


def test_read_in_windows_with_a_window_of_one_calls_get_in_order():
    class Recording:
        window = 1
        calls: list = []

        def get(self, address):
            self.calls.append(("get", address))
            return address

        def get_many(self, addresses, **_):  # pragma: no cover - must not be used
            raise AssertionError("a window of 1 must take the serial path")

    console = Recording()
    out = list(read_in_windows(console, ["/a", "/b", "/c"],
                               should_ask=lambda a: a != "/b",
                               on_start=lambda a: console.calls.append(("start", a))))
    assert out == [("/a", "/a"), ("/b", SKIPPED), ("/c", "/c")]
    assert console.calls == [("start", "/a"), ("get", "/a"), ("start", "/c"), ("get", "/c")]


def test_reply_matching_off_is_serial_too(monkeypatch):
    monkeypatch.setenv("ATOO_OSC_REPLY_MATCH", "off")
    with _wired(_desk(), window=8, latency=0.005) as (console, udp):
        console.get_many(ADDRESSES[:10])
    assert udp.max_outstanding == 1


def test_the_window_is_8_by_default_and_set_by_the_environment():
    assert window_setting({}) == (8, None, None)
    assert window_setting({"ATOO_CONSOLE_WINDOW": "1"}) == (1, "ATOO_CONSOLE_WINDOW", None)
    assert window_setting({"ATOO_CONSOLE_WINDOW": " 16 "})[0] == 16
    for bad in ("0", "-2", "eight", "2.5"):
        window, source, problem = window_setting({"ATOO_CONSOLE_WINDOW": bad})
        assert (window, source) == (8, None)
        assert "ATOO_CONSOLE_WINDOW" in problem
    window, source, problem = window_setting({"ATOO_CONSOLE_WINDOW": "500"})
    assert (window, source) == (64, "ATOO_CONSOLE_WINDOW")
    assert "more than 64" in problem
    assert window_setting({"ATOO_CONSOLE_WINDOW": "64"}) == (64, "ATOO_CONSOLE_WINDOW", None)
    assert WingConsole("127.0.0.1", port=9, window=1000).window == 64


def test_wingconsole_takes_its_window_from_the_environment(monkeypatch):
    monkeypatch.setenv("ATOO_CONSOLE_WINDOW", "3")
    console = WingConsole("127.0.0.1", port=9)
    assert console.window == 3
    console.close()
    assert WingConsole("127.0.0.1", port=9, window=1).window == 1


def test_the_cli_says_when_the_window_is_not_the_default(monkeypatch):
    monkeypatch.setenv("ATOO_CONSOLE_WINDOW", "2")
    err = io.StringIO()
    args = cli.argparse.Namespace(console="127.0.0.1", port=None, timeout=None)
    with contextlib.redirect_stderr(err):
        cli._resolve_console_settings(args)
    assert "Using console window 2 from ATOO_CONSOLE_WINDOW" in err.getvalue()
    monkeypatch.setenv("ATOO_CONSOLE_WINDOW", "zero")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        cli._resolve_console_settings(args)
    assert "is not a whole number" in err.getvalue()


# -- the reads that use it ----------------------------------------------------------


def _read_desk(window, wanted, **network):
    progress = ReadProgress(0, stream=io.StringIO(), isatty=False, timeout=0.1)
    with _wired(_desk(), window=window, timeout=0.1, **network) as (console, udp):
        started = time.monotonic()
        out = init.read_desk(console, wanted, progress=progress)
        took = time.monotonic() - started
    return out, progress, udp, took


def _typed(address: str, value) -> tuple[str, str]:
    return address, ("s" if isinstance(value, str) else "f" if isinstance(value, float) else "i")


def test_the_reset_read_gives_the_same_values_and_the_same_unanswered_at_any_window():
    desk = _desk()
    covered = [_typed(a, v) for a, v in desk.values.items()
               if a.startswith(("/ch/1/", "/ch/2/", "/bus/1/", "/dca/"))
               and not a.endswith("/name")]
    names = [("/bus/2/name", "s")] + [(f"/ch/{n}/name", "s") for n in range(1, 41)]
    wanted = covered + names
    # The whole `/ch/{n}/name` family is silent: the desk answers its
    # neighbours, so the read stops asking for it.
    silent = {f"/ch/{n}/name" for n in range(1, 41)}
    serial, serial_progress, _, serial_took = _read_desk(1, wanted, silent=silent)
    windowed, progress, udp, took = _read_desk(8, wanted, silent=silent, latency=0.002,
                                               jitter=0.004)
    assert windowed.values == serial.values
    assert windowed.unanswered == serial.unanswered == silent
    assert udp.max_outstanding > 1
    # The family was cut off at the window too, not asked to the end.
    asked = {address for address, _ in udp.requests}
    assert not silent <= asked
    # And named as unanswered, by the address that went silent.
    assert set(progress.unanswered_addresses) <= silent
    assert progress.unanswered == len(set(progress.unanswered_addresses))
    assert took < serial_took


def test_audit_reads_the_same_state_at_any_window():
    def read(window, **network):
        with _wired(_desk(), window=window, **network) as (console, udp):
            state = audit.read_console_state(
                console, channels=6, aux=2, buses=4, mains=1, matrices=2, dcas=4,
                mute_groups=2, fx_slots=2, bulk=True)
        return state.values

    assert read(8, latency=0.002, jitter=0.004) == read(1)


def test_audit_per_leaf_reads_the_same_state_at_any_window():
    def read(window, **network):
        with _wired(_desk(), window=window, **network) as (console, udp):
            state = audit.read_console_state(
                console, channels=2, aux=1, buses=2, mains=1, matrices=1, dcas=2,
                mute_groups=1, fx_slots=1, bulk=False)
        return state.values

    assert read(8, latency=0.001, jitter=0.003) == read(1)


def test_the_apply_preview_is_the_same_at_any_window():
    changes = {"/ch/30/fdr": -6.0, "/ch/30/name": "Old show", "/bus/3/mute": 1}

    def preview(window, **network):
        with _wired(desk_with(changes), window=window, **network) as (console, udp):
            result = apply_plan(tiny(("ch", 1, "Kick"), ("ch", 2, "Snare")), console,
                                dry_run=True, full_apply=True, initialize=True,
                                init_model="wing-compact")
        return ([(r.address, r.status, r.prior_value, r.intended_value, r.forced_by)
                 for r in result.writes], result.warnings, udp.max_outstanding)

    serial, serial_warnings, serial_max = preview(1)
    windowed, warnings, windowed_max = preview(8, latency=0.001, jitter=0.003)
    assert windowed == serial
    assert [w for w in warnings if "s)" not in w] == [w for w in serial_warnings if "s)" not in w]
    assert serial_max == 1 and windowed_max > 1


@pytest.mark.parametrize("window", [1, 8])
def test_a_window_of_the_desks_latency_is_what_the_read_costs(window):
    """The point, measured: at 10ms a reply, 64 reads are
    ~0.64s one at a time and a fraction of that eight at a time."""
    addresses = [f"/ch/{n}/fdr" for n in range(1, 41)] + [f"/ch/{n}/mute" for n in range(1, 25)]
    with _wired(_desk(), window=window, latency=0.01) as (console, udp):
        started = time.monotonic()
        list(read_in_windows(console, addresses))
        took = time.monotonic() - started
    if window == 1:
        assert took >= 0.64
    else:
        assert took < 0.64 / 3


def test_the_progress_line_names_the_address_a_window_is_waiting_on():
    """`on_start` is told the oldest request in flight while the batch
    waits -- so a stalled read still names its stall."""
    seen = []
    with _wired(_desk(), window=4, timeout=0.1, latency=0.002, silent={"/ch/2/fdr"}) as (console, udp):
        list(read_in_windows(console, ["/ch/1/fdr", "/ch/2/fdr", "/ch/3/fdr"],
                             on_start=seen.append))
    assert "/ch/2/fdr" in seen[:seen.index("/ch/1/fdr")] or seen.count("/ch/2/fdr") > 1


def test_the_undo_preview_is_the_same_at_any_window(tmp_path):
    from atoo.undo import load_journal, undo_from_journal

    changes = {"/ch/30/fdr": -6.0, "/ch/30/dyn/mdl": "LA", "/bus/3/name": "Old",
               "/io/in/A/12/vph": 1}
    desk = desk_with(changes)
    journal = tmp_path / "apply.json"
    apply_plan(tiny(("ch", 1, "Kick"), ("ch", 2, "Snare")), desk, dry_run=False,
               journal_path=str(journal), full_apply=True, initialize=True,
               init_model="wing-compact")
    # Somebody moved two of them at the desk since.
    desk.values["/ch/1/fdr"] = -12.0
    desk.values["/bus/3/name"] = "Moved"

    def preview(window, **network):
        snapshot = SnapDesk(dict(desk.values), hidden=set(desk.hidden))
        with _wired(snapshot, window=window, **network) as (console, udp):
            result = undo_from_journal(load_journal(str(journal)), console, dry_run=True)
        return ([(s.address, s.verdict, s.current_value) for s in result.steps],
                udp.max_outstanding, snapshot.writes)

    serial, serial_max, _ = preview(1)
    windowed, windowed_max, writes = preview(8, latency=0.001, jitter=0.003)
    assert windowed == serial
    assert serial_max == 1 and windowed_max > 1
    assert writes == []


def test_the_demo_shows_apply_preview_prints_the_same_at_any_window(monkeypatch, tmp_path):
    """The command the maintainer timed at the desk, end to
    end: the packaged Demo show's preview, against an initialized
    Compact. Whatever the window, stdout -- every line of the preview --
    is the same."""
    from pathlib import Path

    from atoo import firstrun

    demo = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME
    monkeypatch.setenv("HOME", str(tmp_path))

    def preview(window, **network):
        monkeypatch.setenv("ATOO_CONSOLE_WINDOW", str(window))
        with UdpDesk(initialized_desk(), **network) as udp:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["apply", "--plan", str(demo / "plan.json"),
                                 "--input", str(demo / "input.csv"),
                                 "--console", "127.0.0.1", "--port", str(udp.port)])
        return code, out.getvalue(), udp.max_outstanding

    serial = preview(1)
    windowed = preview(8, jitter=0.001)
    assert serial[0] == windowed[0] == 0
    assert windowed[1] == serial[1]
    assert (serial[2], windowed[2]) == (1, 8)


def test_patch_and_amend_reads_are_the_same_at_any_window():
    from atoo import amend

    def reads(window, **network):
        with _wired(desk_with({"/ch/3/in/conn/in": 9, "/ch/3/name": "Kick"}),
                    window=window, **network) as (console, udp):
            occupancy = amend.read_occupancy(console, channels=12, aux=2).values
            witness = [(f"/ch/{n}/fdr", "f") for n in range(1, 9)] + [("/ch/3/name", "s")]
            leaves = amend.read_witness(console, witness, bulk=False)
            dumped = amend.read_witness(console, witness, bulk=True)
        return occupancy, leaves, dumped, udp.max_outstanding

    *serial, serial_max = reads(1)
    *windowed, windowed_max = reads(8, latency=0.001, jitter=0.003)
    assert windowed == serial
    assert serial_max == 1 and windowed_max > 1


class _InOrder(SnapDesk):
    """A SnapDesk that records every read in the order it was asked --
    and has no window, so every caller takes its serial path: the
    request order this project had."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.asked: list[str] = []

    def get(self, address):
        self.asked.append(address)
        return super().get(address)

    def node_dump(self, node):
        self.asked.append(node)
        return super().node_dump(node)


def test_a_window_of_one_asks_the_desk_in_the_order_it_always_did(tmp_path):
    """Window 1 is not merely the same answers: it is the same requests,
    in the same order, for the reset read and the apply preview, and for
    the undo preview -- the serial client, exactly."""
    from atoo.undo import load_journal, undo_from_journal

    changes = {"/ch/30/fdr": -6.0, "/bus/3/name": "Old"}
    plan = tiny(("ch", 1, "Kick"))
    journal = tmp_path / "apply.json"
    apply_plan(plan, desk_with(changes), dry_run=False, journal_path=str(journal),
               full_apply=True, initialize=True, init_model="wing-compact")

    def run(console):
        apply_plan(plan, console, dry_run=True, full_apply=True, initialize=True,
                   init_model="wing-compact")
        undo_from_journal(load_journal(str(journal)), console, dry_run=True)

    today = _InOrder(desk_with(changes).values)
    run(today)
    with _wired(desk_with(changes), window=1) as (console, udp):
        run(console)
    assert [address for address, _ in udp.requests] == today.asked


# -- the end-of-read line, at a window (review) -------------------


def test_the_unanswered_cost_is_not_summed_when_they_waited_side_by_side():
    """At a window of 8, 18 unanswered addresses wait at once: the serial
    arithmetic (18 x 3 x 1.0 = "about 54s of the time above") was printed
    after a read that took 3.4s. Each one's cost is what is known."""
    from atoo.progress import Phases

    serial = ReadProgress(20, stream=io.StringIO(), isatty=False, timeout=1.0)
    windowed = Phases(stream=io.StringIO(), isatty=False, timeout=1.0, window=8).start(
        "read", 20)
    for progress in (serial, windowed):
        for n in range(1, 21):
            progress.start_address(f"/ch/{n}/name")
            progress.finish_address(answered=n > 18)
    assert "18 address(es) went unanswered, about 54s of the time above" in serial.summary()
    summary = windowed.summary()
    assert "18 address(es) went unanswered, each waiting about 3s, up to 8 at a time" in summary
    assert "of the time above" not in summary
    assert "not defaults" in summary


def test_the_cli_read_line_is_told_the_window(monkeypatch):
    args = cli.argparse.Namespace(timeout=1.0, no_progress=False)
    monkeypatch.setenv("ATOO_CONSOLE_WINDOW", "4")
    assert cli._phases(args).start("read", 1).window == 4
    monkeypatch.delenv("ATOO_CONSOLE_WINDOW")
    assert cli._phases(args).start("read", 1).window == 8


def test_a_real_windowed_read_does_not_claim_more_time_than_it_took():
    silent = [f"/ch/{n}/name" for n in range(1, 19)]
    progress = ReadProgress(0, stream=io.StringIO(), isatty=False, timeout=0.2, window=8)
    with _wired(_desk(), window=8, timeout=0.2, silent=set(silent)) as (console, udp):
        started = time.monotonic()
        init.read_desk(console, [("/bus/1/name", "s")] + [(a, "s") for a in silent],
                       progress=progress)
        took = time.monotonic() - started
    summary = progress.summary()
    assert progress.unanswered > 1
    assert "of the time above" not in summary
    assert "each waiting about 1s, up to 8 at a time" in summary
    assert took < progress.unanswered * 3 * 0.2


# -- a datagram that does not decode (review) ----------------------


class _RawDesk:
    """A UDP responder answering each GET with its address as a string,
    and, before the reply to the address in `garble_before`, a datagram
    that does not decode as OSC at all."""

    def __init__(self, garble_before: str, *, hold_first: bool = False):
        import socket
        import threading

        self.garble_before = garble_before
        # Answer the first request only after the second: so garbage sent
        # ahead of the second's reply arrives while the first is still
        # the oldest request in flight.
        self.hold_first = hold_first
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import socket

        from atoo.console import decode_message, encode_message

        held = []
        while not self._stop.is_set():
            try:
                data, peer = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            address = decode_message(data).address
            if self.hold_first and not held:
                held.append(address)
                continue
            if address == self.garble_before:
                self.sock.sendto(b"\xff\xff\xff", peer)   # no NUL: not an OSC string
            self.sock.sendto(encode_message(address, "s", f"value of {address}"), peer)
            for first in held[:1] if len(held) == 1 else []:
                held.append(None)
                self.sock.sendto(encode_message(first, "s", f"value of {first}"), peer)

    def close(self):
        self._stop.set()
        self.thread.join(timeout=1)
        self.sock.close()


@pytest.mark.parametrize("garbled", ["/a", "/b"])
def test_a_garbled_datagram_is_an_error_for_one_request_never_a_wrong_value(garbled):
    """A garbled datagram is an error for one request, never a wrong value.

    `garbled` is the reply the garbage really preceded. For "/b" the
    desk holds /a's reply until after /b's, so the garbage arrives while
    /a is still the oldest in flight and /a is the one blamed -- the
    case where the rule picks the wrong request, and still costs only an
    error, not a value.

    console.py's rule: a datagram that does not decode cannot be
    matched, so it is a DECODE_ERROR for the request longest on the wire.
    That request's real reply, when it comes, is drained and kept as a
    late reply. Whichever request the garbage was really about, no
    address is ever given another address's value."""
    desk = _RawDesk(garble_before=garbled, hold_first=garbled == "/b")
    try:
        console = WingConsole("127.0.0.1", port=desk.port, timeout=0.5, window=4)
        replies = console.get_many(["/a", "/b", "/c"])
        console.close()
    finally:
        desk.close()
    # The oldest request in flight, /a, takes the error -- even when the
    # garbage arrived just before /b's reply.
    assert replies[0].typetag == "DECODE_ERROR"
    assert replies[0].is_transport_error
    assert replies[0].value("s") == (None, replies[0].value("s")[1])
    assert replies[0].value("s")[1].startswith("transport_error")
    # /a's real reply is not lost: it is on hand for /a, and only /a.
    assert console.late_reply("/a").args == ["value of /a"]
    for reply, address in zip(replies[1:], ["/b", "/c"]):
        assert reply.address == address
        assert reply.args == [f"value of {address}"]
    # Every value that came out is the value OF the address it came out for.
    for reply, address in zip(replies, ["/a", "/b", "/c"]):
        assert reply.address == address
        value, error = reply.value("s")
        assert error is not None or value == f"value of {address}"
