"""A simulated WING on a real UDP socket, with a slow network -- an earlier change.

`tests/snap_desk.SnapDesk` answers method calls; this puts one behind a
real localhost UDP socket in the OSC wire format, so the real
`atoo.console.WingConsole` -- its matching, its timeouts, its window
of requests in flight -- is what is under test. On top of the desk it
adds the network the maintainer's desk sat behind on 2026-10-13:

* `latency` seconds before each reply goes out (about 0.015 there);
* `jitter` seconds of extra, random delay per reply, which reorders
  replies to requests sent close together (`seed` makes it repeatable);
* `silent`: addresses the desk never answers at all, the way a WING does
  not answer a leaf it does not have;
* `drop_first`: `{address: n}`, the first n replies to that address lost
  on the way back -- a dropped datagram the client must retry.

It records what a test needs to see about the client's behaviour:
`requests` (every request, in arrival order), `replies_sent` (the
requests answered, in the order the answers left), `max_outstanding` (the most
requests it had received and not yet answered at once -- the client's
window, from the desk's side) and `same_address_overlaps` (how often a
request arrived for an address the desk had not yet answered: the one
thing the client must never do, since the protocol cannot tell the two
replies apart).

The desk answers requests one at a time in arrival order (as a real
desk's single OSC task would) and only the network delays them.
"""

from __future__ import annotations

import heapq
import random
import socket
import threading
import time

from atoo.console import NODE_DUMP_MODE, decode_message, encode_message


class UdpDesk:
    def __init__(self, desk, *, latency: float = 0.0, jitter: float = 0.0,
                 seed: int = 0, silent: set[str] | None = None,
                 drop_first: dict[str, int] | None = None):
        self.desk = desk
        self.latency = latency
        self.jitter = jitter
        self.rng = random.Random(seed)
        self.silent = set(silent or ())
        self.drop_first = dict(drop_first or {})
        self.requests: list[tuple[str, str]] = []
        # The address of every reply that went out, in the order it did:
        # with `jitter`, not the order the requests came in.
        self.replies_sent: list[str] = []
        self.outstanding: dict[str, int] = {}
        self.max_outstanding = 0
        self.same_address_overlaps = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.05)
        self._queue: list[tuple[float, int, bytes, tuple, str | None]] = []
        self._seq = 0
        self._lock = threading.Condition()
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._receive, daemon=True),
                         threading.Thread(target=self._send, daemon=True)]
        for thread in self._threads:
            thread.start()

    # -- the desk ----------------------------------------------------------

    def _answer(self, address: str, typetag: str, args: list):
        """`(address, typetag, args)` of the desk's reply, or None."""
        if address == "/?" and not typetag:
            return "/*", "s", [self.desk.identity().args[0]]
        if not typetag:
            reply = self.desk.get(address)
            return reply.address, reply.typetag, list(reply.args)
        if typetag == "s" and args == [NODE_DUMP_MODE]:
            dump = self.desk.node_dump(address)
            return address, "s", [dump if dump is not None else "NODE NOT FOUND"]
        if typetag == "s":
            reply = self.desk.set_node(address, args[0])
            return "/*", "s", list(reply.args)
        self.desk.set_param(address, args[0], typetag)
        return None

    # -- the network -------------------------------------------------------

    def _receive(self) -> None:
        while not self._stop.is_set():
            try:
                data, peer = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            request = decode_message(data)
            self.requests.append((request.address, request.typetag))
            answer = self._answer(request.address, request.typetag, request.args)
            if answer is None or request.address in self.silent:
                continue
            reply_address = answer[0]
            with self._lock:
                key = request.address
                if self.outstanding.get(key):
                    self.same_address_overlaps += 1
                self.outstanding[key] = self.outstanding.get(key, 0) + 1
                self.max_outstanding = max(self.max_outstanding,
                                           sum(self.outstanding.values()))
                lost = self.drop_first.get(reply_address, 0) > 0
                if lost:
                    self.drop_first[reply_address] -= 1
                delay = self.latency + (self.rng.random() * self.jitter if self.jitter else 0.0)
                self._seq += 1
                heapq.heappush(self._queue, (
                    time.monotonic() + delay, self._seq,
                    None if lost else encode_message(*answer[:2], *answer[2]), peer, key))
                self._lock.notify()

    def _send(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                while not self._queue and not self._stop.is_set():
                    self._lock.wait(0.05)
                if self._stop.is_set():
                    return
                due, _seq, data, peer, key = self._queue[0]
                wait = due - time.monotonic()
                if wait > 0:
                    self._lock.wait(wait)
                    continue
                heapq.heappop(self._queue)
                self.outstanding[key] -= 1
            if data is not None:
                self.replies_sent.append(key)
                try:
                    self.sock.sendto(data, peer)
                except OSError:
                    return

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._lock.notify_all()
        for thread in self._threads:
            thread.join(timeout=1)
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
