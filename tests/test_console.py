"""Tests for atoo/console.py -- the OSC wire client promoted from
experiments/wing/wing_osc.py. No real console is available in this environment, so
these tests run a tiny local UDP responder (127.0.0.1, ephemeral port)
that plays the role of a WING console for exactly the message shapes the
spec documents, and check the client's encode/decode/get/set_param/
set_node behavior against it end to end -- real sockets, real wire bytes,
just not real hardware.
"""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from atoo.console import (
    ERROR_TOKENS,
    LATE_REPLY_MEMORY,
    OscReply,
    WingConsole,
    decode_message,
    encode_message,
    encode_string,
    join_addr,
)


class FakeWingServer:
    """A local UDP responder. `handler(address, typetag, args) -> (reply_address, reply_typetag, reply_args) | None`
    decides how to answer each decoded request; returning None sends
    nothing (simulates a real timeout).

    A handler may also return a **list** of such triples, and every one is
    sent. That is not a convenience: sending two datagrams for one request
    is the exact hardware behaviour that desynchronised the maintainer's
    2026-09-21 apply, and there is no way to test the client's resistance
    to it with a responder that can only ever answer once.
    """

    def __init__(self, handler):
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.sock.settimeout(0.2)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            req = decode_message(data)
            result = self.handler(req.address, req.typetag, req.args)
            if result is None:
                continue
            replies = result if isinstance(result, list) else [result]
            for reply_address, reply_typetag, reply_args in replies:
                self.sock.sendto(encode_message(reply_address, reply_typetag, *reply_args), addr)

    def close(self):
        self._stop.set()
        self.thread.join(timeout=1)
        self.sock.close()


@pytest.fixture
def server_factory():
    servers = []

    def make(handler):
        s = FakeWingServer(handler)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


# --- pure encode/decode, no network ---


def test_string_encoding_is_null_terminated_and_4byte_padded():
    assert encode_string("") == b"\x00\x00\x00\x00"
    assert encode_string("ab") == b"ab\x00\x00"  # 2 chars + null = 3, pad to 4
    assert encode_string("abc") == b"abc\x00"  # 3 chars + null = 4, already a multiple of 4
    assert encode_string("abcd") == b"abcd\x00\x00\x00\x00"  # 4 + null = 5, pad to 8


def test_encode_decode_roundtrip_float():
    packet = encode_message("/ch/1/fdr", "f", -6.0)
    reply = decode_message(packet)
    assert reply.address == "/ch/1/fdr"
    assert reply.typetag == "f"
    assert reply.args == [-6.0]


def test_encode_decode_roundtrip_string_and_int():
    packet = encode_message("/ch/1/name", "si", "Kick", 3)
    reply = decode_message(packet)
    assert reply.args == ["Kick", 3]


def test_encode_message_unsupported_typetag_raises():
    with pytest.raises(ValueError):
        encode_message("/x", "z", 1)


def test_join_addr():
    assert join_addr("/", "ch") == "/ch"
    assert join_addr("/ch", "1") == "/ch/1"
    assert join_addr("/ch/", "1") == "/ch/1"


def test_oscreply_error_detection():
    r = OscReply(address="/ch/999", typetag="s", args=["NODE NOT FOUND"])
    assert r.error == "NODE NOT FOUND"
    assert not r.is_container_listing

    ok = OscReply(address="/*", typetag="s", args=["OK"])
    assert ok.error is None


def test_oscreply_container_listing_shape():
    r = OscReply(address="/ch/1", typetag="ss", args=["name", "fdr"])
    assert r.is_container_listing
    # A single-string reply is structurally identical to a one-child
    # container -- error tokens must be excluded explicitly, not inferred
    # from shape, exactly the distinction is_container_listing documents.
    err = OscReply(address="/ch/1", typetag="s", args=["VALUE ERROR"])
    assert not err.is_container_listing


def test_oscreply_transport_error_markers():
    r = OscReply(address="/x", typetag="SOCKET_ERROR", args=["boom"])
    assert r.is_transport_error
    assert not r.error  # transport error, not a well-formed WING error reply


def test_oscreply_is_socket_error_is_narrower_than_is_transport_error():
    """Apply.py's write loop needs to abort on a genuine
    socket-level failure but NOT on a single DECODE_ERROR (bytes arrived
    but didn't parse -- says nothing about whether the connection itself
    is alive), so the two must be distinguishable, not just both true
    under is_transport_error."""
    socket_error = OscReply(address="/x", typetag="SOCKET_ERROR", args=["boom"])
    decode_error = OscReply(address="/x", typetag="DECODE_ERROR", args=["boom"])
    assert socket_error.is_socket_error
    assert not decode_error.is_socket_error
    assert decode_error.is_transport_error  # unchanged: still true for both


# --- WingConsole against a fake UDP responder ---


def test_get_leaf_value(server_factory):
    def handler(address, typetag, args):
        if address == "/ch/1/fdr" and typetag == "":
            return "/ch/1/fdr", "f", [-3.0]
        return None

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        reply = client.get("/ch/1/fdr")
    assert reply is not None
    assert reply.args == [-3.0]


def test_get_container_listing(server_factory):
    def handler(address, typetag, args):
        if address == "/ch/1" and typetag == "":
            return "/ch/1", "ss", ["name", "fdr"]
        return None

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        reply = client.get("/ch/1")
    assert reply.is_container_listing
    assert reply.args == ["name", "fdr"]


def test_set_param_sends_and_gets_no_reply(server_factory):
    # set_param is fire-and-forget per the protocol -- there is nothing to
    # wait for. This test just confirms it doesn't block or raise, and
    # that the bytes it sent decode back to what was asked.
    received = []
    ready = threading.Event()

    def handler(address, typetag, args):
        received.append((address, typetag, args))
        ready.set()
        return None  # no ack for single-parameter set, per spec

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.3) as client:
        client.set_param("/ch/1/fdr", -6.0, "f")
    ready.wait(timeout=1.0)
    assert received == [("/ch/1/fdr", "f", [-6.0])]


def test_set_node_ok_ack(server_factory):
    def handler(address, typetag, args):
        if address == "/ch/1" and typetag == "s" and args == ["fdr=-6.0,mute=0"]:
            return "/*", "s", ["OK"]
        return "/*", "s", ["VALUE ERROR"]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        reply = client.set_node("/ch/1", "fdr=-6.0,mute=0")
    assert reply.error is None
    assert reply.args == ["OK"]


def test_set_node_error_ack(server_factory):
    def handler(address, typetag, args):
        return "/*", "s", ["NODE NOT FOUND"]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        reply = client.set_node("/", "/ch.999.fdr=3")
    assert reply.error == "NODE NOT FOUND"
    assert reply.error in ERROR_TOKENS


def test_timeout_returns_none(server_factory):
    def handler(address, typetag, args):
        return None  # never answer -- simulates an unreachable console

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.1) as client:
        reply = client._request("/ch/1/fdr", "", retries=0)
    assert reply is None


def test_identity(server_factory):
    def handler(address, typetag, args):
        if address == "/?":
            return "/?", "s", ["WING,192.0.2.16,MyConsole,wing-compact,SERIAL,3.1-0"]
        return None

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        reply = client.identity()
    assert reply.args[0].startswith("WING,")


def test_identity_remembers_the_model_the_desk_named(server_factory):
    """The `/?` reply is where the console says which WING it is, and it
    is the only place anything asks. `audit.read_console_state` reads it
    off the client afterwards, because what counts as a factory-default
    input patch is measured per model -- so this has to survive the call
    rather than being thrown away with the reply."""
    def handler(address, typetag, args):
        return "/?", "s", ["WING,192.0.2.16,MyConsole,wing-compact,SERIAL,3.1-0"]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        assert client.console_model is None      # nothing asked yet
        client.identity()
        assert client.console_model == "wing-compact"


def test_a_model_this_project_cannot_confirm_leaves_it_unknown(server_factory):
    """Same hard line `console_facts.model_from_identity` draws: an
    unfamiliar model string is None, never a guess, and the audit then
    falls back to the one factory patch it is confident of."""
    def handler(address, typetag, args):
        return "/?", "s", ["WING,192.0.2.16,MyConsole,wing-ultra,SERIAL,9.9-9"]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=1.0) as client:
        client.identity()
        assert client.console_model is None


def test_an_unreachable_desk_names_no_model(server_factory):
    def handler(address, typetag, args):
        return None          # never answers

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.1) as client:
        assert client.identity() is None
        assert client.console_model is None


def test_raw_log_records_traffic(server_factory, tmp_path):
    def handler(address, typetag, args):
        return "/ch/1/fdr", "f", [-3.0]

    server = server_factory(handler)
    log_path = tmp_path / "raw.log"
    with open(log_path, "w") as log_file:
        with WingConsole("127.0.0.1", server.port, timeout=1.0, raw_log=log_file) as client:
            client.get("/ch/1/fdr")
    contents = log_path.read_text()
    assert "SEND" in contents
    assert "RECV" in contents


# ---------------------------------------------------------------------------
# Reply matching. Written from a real failure, not from a code reading.
#
# On 2026-09-21 the maintainer applied touringband to a WING. The desk sent
# `/dca/8/name` twice; the duplicate was taken as the reply to the next
# request, and from there every read collected the *previous* request's
# answer. 880 of 1142 reads were answered by the wrong leaf, the journal
# recorded 188 false mismatches, and the 44 "match"es proved nothing. The
# raw log is committed at
# archive/examples/console-runs/2026-09-21/A1-tb-raw-log.log.
#
# The property these tests hold the client to is not "never sees a stale
# datagram" -- it cannot control what a console sends -- but **a stale
# datagram costs one discarded packet, not the rest of the session.**
# ---------------------------------------------------------------------------


def test_a_duplicate_datagram_does_not_desync_every_later_read(server_factory):
    """Replays the hardware failure: one request answered twice, then
    ordinary reads. Every later read must return its own value.

    Under the old take-the-next-datagram client this fails from the second
    read onwards and never recovers -- `/ch/2/name` returns Kick, `/ch/3`
    returns Snare, forever."""
    def handler(address, typetag, args):
        value = {"/ch/1/name": "Kick", "/ch/2/name": "Snare",
                 "/ch/3/name": "HH", "/ch/4/name": "Tom1"}[address]
        reply = (address, "s", [value])
        # The desk duplicates this one, exactly as it duplicated
        # /dca/8/name at line 79 of the 2026-09-21 raw log.
        return [reply, reply] if address == "/ch/1/name" else reply

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        got = {a: client.get(a).args[0]
               for a in ("/ch/1/name", "/ch/2/name", "/ch/3/name", "/ch/4/name")}

    assert got == {"/ch/1/name": "Kick", "/ch/2/name": "Snare",
                   "/ch/3/name": "HH", "/ch/4/name": "Tom1"}
    assert client.replies_discarded == 1, "the duplicate should be drained exactly once"


def test_an_ack_is_never_returned_as_a_value(server_factory):
    """The 2026-09-21 journal recorded `/mgrp/1/name` readback as the
    string `OK` -- a set_node ack consumed as a parameter value. A write's
    ack and a read's reply share one queue, so nothing but address
    matching keeps them apart, and `OK` is a perfectly plausible channel
    name."""
    def handler(address, typetag, args):
        if typetag == "s" and not address.endswith("/name"):
            # A set_node, answered on /* -- and answered twice, so one ack
            # is left in the queue for the following read to trip over.
            return [("/*", "s", ["OK"]), ("/*", "s", ["OK"])]
        return (address, "s", ["Band"])

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        assert client.set_node("/mgrp/1", "name=Band").args == ["OK"]
        reply = client.get("/mgrp/1/name")

    assert reply.args == ["Band"], "a read must not be answered by a leftover ack"
    assert client.replies_discarded == 1


def test_unsolicited_traffic_is_drained_not_returned(server_factory):
    """A console volunteering state (metering, a surface move) must not be
    able to answer a question nobody asked it."""
    def handler(address, typetag, args):
        return [("/ch/9/fdr", "f", [-12.0]),      # nobody asked for this
                ("/ch/1/fdr", "f", [-6.0])]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        reply = client.get("/ch/1/fdr")

    assert reply.address == "/ch/1/fdr"
    assert reply.args == [-6.0]
    assert client.replies_discarded == 1


def test_a_reply_that_never_matches_times_out_rather_than_lying(server_factory):
    """If the console only ever answers on an address we did not ask for,
    the honest result is "no reply" -- the one thing it must not be is a
    confident value for the wrong leaf."""
    def handler(address, typetag, args):
        return ("/some/other/leaf", "f", [1.0])

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.1) as client:
        reply = client._request("/ch/1/fdr", "", retries=0)

    assert reply is None
    assert client.replies_discarded >= 1


def test_the_escape_hatch_restores_take_the_next_datagram(server_factory, monkeypatch):
    """`ATOO_OSC_REPLY_MATCH=off` exists because this is a
    wire-protocol change that cannot be proven against hardware from this
    environment. If some reply shape carries an address neither rule
    predicts, it is the difference between finishing a console session and
    losing the evening -- so it is tested, not just documented."""
    def handler(address, typetag, args):
        return ("/some/other/leaf", "f", [1.0])

    server = server_factory(handler)
    monkeypatch.setenv("ATOO_OSC_REPLY_MATCH", "off")
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        reply = client.get("/ch/1/fdr")

    assert reply.address == "/some/other/leaf"
    assert client.replies_discarded == 0


def test_identity_accepts_the_star_address_hardware_answers_on(server_factory):
    """Confirmed 2026-09-21: `SEND addr='/?'` -> `PARSED addr='/*'`. The
    fake server in this file answered on `/?` and had done since it was
    written, which is why nothing here ever noticed."""
    def handler(address, typetag, args):
        return ("/*", "s", ["WING,192.0.2.16,MyConsole,wing-compact,SERIAL,3.1-0"])

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        reply = client.identity()

    assert reply.args[0].startswith("WING,")


# --- A drained datagram is kept for the address it names ---


def test_a_drained_datagram_is_kept_under_the_address_it_names(server_factory):
    """Replays `/ch/7/tags` from the 2026-09-21 A1 run (raw log lines
    1469-1485). The desk answers the read of `/ch/8/tags` with two
    datagrams for `/ch/7/tags` first -- the write that the client had
    already given up on, landing two datagrams late.

    Before an earlier change those were counted and dropped, and `apply` reported a
    MISMATCH for a write that had landed. They are addressed, so they are
    kept."""
    def handler(address, typetag, args):
        if address == "/ch/8/tags":
            late = ("/ch/7/tags", "s", ["#D7,#M1"])
            return [late, late, ("/ch/8/tags", "s", [""])]
        return (address, "s", [""])

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        assert client.get("/ch/8/tags").args == [""]
        late = client.late_reply("/ch/7/tags")

    assert late is not None and late.args == ["#D7,#M1"]
    assert client.replies_discarded == 2
    assert client.replies_used == 0, "keeping one is not using one"


def test_a_late_reply_is_offered_only_for_the_address_it_names(server_factory):
    """No nearest-match and no "it was probably about this". An
    unaddressed value is not evidence; the only
    reason a drained datagram can be used at all is that it carries its
    own identity."""
    def handler(address, typetag, args):
        return [("/ch/7/tags", "s", ["#D7,#M1"]), (address, "s", [""])]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        client.get("/ch/8/tags")

        assert client.late_reply("/ch/7/tags") is not None
        assert client.late_reply("/ch/8/tags") is None
        assert client.late_reply("/ch/7") is None
        assert client.late_reply("/ch/7/tags/") is None


def test_the_newest_datagram_for_an_address_is_the_one_kept(server_factory):
    """`/bus/10/name` on the 19:14 A1 run was pushed twice: the first
    copy still carried the pre-write empty string, the second carried
    'VOX Delay'. Keeping the first would describe the console as it was
    before the write."""
    def handler(address, typetag, args):
        if address == "/bus/11/name":
            return [("/bus/10/name", "s", [""]),
                    ("/bus/10/name", "s", ["VOX Delay"]),
                    ("/bus/11/name", "s", [""])]
        return (address, "s", [""])

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        client.get("/bus/11/name")

    assert client.late_reply("/bus/10/name").args == ["VOX Delay"]


def test_a_late_reply_older_than_the_mark_is_not_offered(server_factory):
    """The `after` mark is what stops a duplicate of the PRE-write reply
    answering for the write. A caller takes `datagrams_received` before
    it writes and passes it back here; anything filed at or before that
    is about the console as it was."""
    def handler(address, typetag, args):
        return [("/ch/7/tags", "s", [""]), (address, "s", [""])]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        client.get("/ch/8/tags")
        mark = client.datagrams_received

        assert client.late_reply("/ch/7/tags") is not None
        assert client.late_reply("/ch/7/tags", after=mark) is None
        assert client.late_reply("/ch/7/tags", after=mark - 2) is not None


def test_using_a_late_reply_consumes_it_and_is_counted(server_factory):
    """`replies_discarded` says how many datagrams were drained;
    `replies_used` says how many of them answered a question. The same
    datagram cannot answer twice."""
    def handler(address, typetag, args):
        return [("/ch/7/tags", "s", ["#D7,#M1"]), (address, "s", [""])]

    server = server_factory(handler)
    with WingConsole("127.0.0.1", server.port, timeout=0.5) as client:
        client.get("/ch/8/tags")

        used = client.use_late_reply("/ch/7/tags")
        assert used.args == ["#D7,#M1"]
        assert client.replies_used == 1
        assert client.replies_discarded == 1
        assert client.late_reply("/ch/7/tags") is None
        assert client.use_late_reply("/ch/7/tags") is None
        assert client.replies_used == 1


def test_the_late_reply_store_is_bounded(server_factory):
    """A console that volunteers traffic all evening must not grow this
    client's memory without limit -- 125 datagrams were drained in one
    670-address run. Oldest out first."""
    with WingConsole("127.0.0.1", 2223, timeout=0.1) as client:
        for n in range(LATE_REPLY_MEMORY + 10):
            client.datagrams_received += 1
            client._remember_late_reply(OscReply(address=f"/ch/{n}/name", typetag="s", args=["x"]))

    assert len(client._late_replies) == LATE_REPLY_MEMORY
    assert client.late_reply("/ch/0/name") is None, "the oldest should have been evicted"
    assert client.late_reply(f"/ch/{LATE_REPLY_MEMORY + 9}/name") is not None
