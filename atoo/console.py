"""O2/O3 network client: a minimal WING OSC client, promoted from
an early experiment into product code (stdlib only, no dependencies).

Grounded in Behringer's WING_Remote-Protocols-3.1-03.pdf ("OSC Remote
Protocol" chapter, pages 18-26) -- every encode/decode rule here is taken
directly from that document's own worked examples, not guessed -- and
confirmed against a real WING Compact by early write-and-verify and
DCA/mute-group spikes (2026-09-09). The wire-level behavior
this module
relies on:

- OSC strings are ASCII, null-terminated, then padded with 0-3 more nulls
  so the total length is a multiple of 4. Blobs are int32-BE length-
  prefixed, then padded (no null terminator) to a 4-byte boundary.
- A bare address with no type tag is a GET: a leaf parameter replies with
  its value(s), a container node replies with one string argument per
  child name.
- A node address with typetag 's' and the single argument '*' is a NODE
  DATA DUMP: the whole node's settable values, recursively, as one flat
  `key=value,` string (spec pp24-25). `node_dump`/`parse_node_dump`
  below. This is the difference between ~6,100 round trips for a live
  audit read and 325 on a Compact -- measured at 118.8s against
  4.8s on real hardware (A11, 2026-09-24), with the two paths agreeing on
  every value, which is why it is the CLI's default read.
- OSC port 2223, UDP, no bundles, 32kB max packet from WING; this client's
  receive buffer is generous (65535B) rather than trying to predict a
  worst-case reply size.

Writing (spec pp21-23) has two paths with *different failure visibility*
-- this distinction is why apply.py's design leans on set_node wherever
the protocol allows it, and never trusts either path without a readback:

- Single Parameter set (`set_param`): a leaf address + one type-tagged
  value. WING does NOT acknowledge this at all -- "WING does not echo
  data sent over UDP by the client application" (spec p21). A malformed
  or out-of-range write is genuinely silent here; readback is the only
  way to know it landed. Confirmed against real hardware: a non-numeric
  string sent to a float parameter was silently ignored, not rejected
  with any signal on the wire (spike_write_verify.py, test 4). Worse,
  that readback can lose a race with the write it is checking: on the
  2026-09-21 A1 run the desk answered both the readback of `/ch/7/tags`
  and an immediate re-read of it with the pre-write value, then
  volunteered the new one two datagrams later, while the client had
  moved on to `/ch/8/tags`. Those late datagrams are addressed, so this client keeps
  them (`late_reply`) instead of merely counting them.
- Node Data set (`set_node`): a node address + typetag 's' + a
  "key=value,..." command string. WING replies with address '/*' and a
  single string arg, either "OK" or one of ERROR_TOKENS. This path IS
  acknowledged -- confirmed against real hardware for both the success
  case (test 6) and three distinct failure modes (tests 7-9: bogus node
  path, malformed value, unknown parameter name), each returning a real
  error token rather than silence.

FR-X.1 requires a readback path for every
write regardless of which of these two a given write used -- an ack is
useful defense-in-depth for `set_node`, but it is not a substitute for
reading the parameter back, since an ack only proves the command parsed,
not that the value the console now holds is the one the caller intended
(e.g. clamped rather than rejected). apply.py does both.
"""

from __future__ import annotations

import os
import re
import socket
import struct
import time
from dataclasses import dataclass, field

# Only for `model_from_identity` -- turning the `/?` reply's model field
# into a model this project has confirmed facts about. `console_facts`
# imports nothing from `atoo`, so this stays a leaf dependency.
from atoo import console_facts

WING_OSC_PORT = 2223
MAX_UDP_PACKET = 65535  # generous receive buffer; WING itself caps sends at 32kB

# The address WING answers an *acknowledged* write on (set_node) and the
# identity query on. It is not the address that was sent, so those two
# request kinds match on this instead. See ACK_ADDRESS's use in _request.
ACK_ADDRESS = "/*"

# How many unrelated datagrams to drain while looking for the reply to the
# request actually in flight. A bound rather than "until timeout" so a
# console emitting a steady stream of unsolicited traffic cannot wedge a
# run -- 32 is far more than the 1-2 seen on hardware, and cheap.
MAX_STALE_REPLIES = 32

# How many addresses' drained datagrams to keep at once. A
# drained datagram is not noise -- it names the address it is about, and
# a later verification of THAT address can consult it (see `late_reply`).
# The 2026-09-21 A1 run drained 125 of them over 670 addresses, so this
# is not a big map in practice; it is bounded anyway, because a console
# that volunteers traffic all night must not grow this client's memory
# without limit. The oldest entry goes first.
LATE_REPLY_MEMORY = 256

# How many reads may be in flight at once. See "Several
# requests in flight" below, before `WingConsole`.
DEFAULT_WINDOW = 8
# The most `ATOO_CONSOLE_WINDOW` may ask for. Past this the window
# buys nothing a desk read could use (a 2,000-request read is already a
# few dozen round trips) and is only more replies queued at once.
MAX_WINDOW = 64
WINDOW_ENV = "ATOO_CONSOLE_WINDOW"

ERROR_TOKENS = {
    "NODE NOT FOUND",
    "BUFFER OVERFLOW",
    "VALUE ERROR",
    "NODE IS NOT PAR",
    "INCOMPLETE DATA",
    "STACK EMPTY",
}


def _pad(b: bytes) -> bytes:
    b += b"\x00"
    while len(b) % 4 != 0:
        b += b"\x00"
    return b


def encode_string(s: str) -> bytes:
    return _pad(s.encode("ascii", errors="replace"))


def _pad_blob(b: bytes) -> bytes:
    """Blobs are int32-BE length-prefixed, then padded (no null terminator,
    unlike strings) to a 4-byte boundary -- confirmed against the spec's own
    worked example (p26): 1-byte payload 0xdd encodes as length 00000001
    followed by dd and 3 padding bytes."""
    out = struct.pack(">i", len(b)) + b
    while len(out) % 4 != 0:
        out += b"\x00"
    return out


def encode_message(address: str, typetag: str = "", *args) -> bytes:
    """Build a raw OSC packet. typetag is type chars only, no leading comma."""
    packet = encode_string(address)
    packet += encode_string("," + typetag)
    for t, a in zip(typetag, args):
        if t == "s":
            packet += encode_string(a)
        elif t == "f":
            packet += struct.pack(">f", a)
        elif t == "i":
            packet += struct.pack(">i", a)
        elif t == "b":
            packet += _pad_blob(a)
        else:
            raise ValueError(f"unsupported OSC type tag {t!r}")
    return packet


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(b"\x00", offset)
    s = data[offset:end].decode("ascii", errors="replace")
    new_offset = end + 1
    while new_offset % 4 != 0:
        new_offset += 1
    return s, new_offset


@dataclass
class OscReply:
    address: str
    typetag: str
    args: list = field(default_factory=list)
    raw: bytes = b""

    @property
    def error(self) -> str | None:
        """The error token if this reply is one of WING's known error replies."""
        if self.args and isinstance(self.args[0], str) and self.args[0] in ERROR_TOKENS:
            return self.args[0]
        return None

    @property
    def is_transport_error(self) -> bool:
        """True if this isn't a real WING reply at all -- a synthetic marker
        from _request() for a socket-level failure or a reply this client
        couldn't parse. Distinct from .error (which is WING's own, well-formed
        "no such node" reply): this means something went wrong before WING's
        answer, or its content, could be trusted."""
        return self.typetag in ("SOCKET_ERROR", "DECODE_ERROR")

    @property
    def is_socket_error(self) -> bool:
        """True only for the OS-level failure half of is_transport_error
        (host/network unreachable, connection refused, ...) -- never for a
        DECODE_ERROR, which means bytes arrived but didn't parse and says
        nothing about whether the connection itself is still alive.
        apply.py's write loop uses this specifically: a single
        socket error almost always means every subsequent address will fail
        identically (_request() doesn't even retry an OSError, unlike a
        timeout -- there's nothing to wait out), so it's the signal to stop
        the whole run rather than record hundreds of individually "failed"
        addresses that were never actually reachable in the first place."""
        return self.typetag == "SOCKET_ERROR"

    @property
    def is_container_listing(self) -> bool:
        """True if every argument is a string -- WING's shape for 'here are my children'.

        A single-string error reply (NODE NOT FOUND, etc.) is structurally
        identical to a container with exactly one child, so error replies
        must be excluded explicitly rather than inferred from shape alone.
        """
        if self.error is not None or self.is_transport_error:
            return False
        return bool(self.args) and self.typetag == "s" * len(self.typetag) and len(self.typetag) > 0

    def value(self, value_type: str) -> tuple[object, str | None]:
        """Pull the value a caller actually wants out of a multi-arg GET
        reply. Confirmed against real hardware (spike_write_verify.py) for
        `/ch/{n}/fdr` (a "fader"-type param): its `,sff` reply is
        [raw-text, 0..1 raw fraction, real dB value] -- for a float, take
        the LAST float argument, not the first. The schema
        (the Compact parameter map) documents this
        same "fader" type for every `.lvl`/`.fdr` leaf this project reads,
        including its own literal "-oo" notation for -infinity dB as the
        raw-text argument -- exactly the string that broke a naive
        `args[0]` read (`atoo ui`/`atoo audit`
        crashed with "could not convert string to float: '-oo'" reading
        that raw-text argument directly instead of the real value behind
        it). Also applied to `/ch/{n}/flt/lcf`, a "log"-type param, NOT
        the same micro-type as fader -- whether its reply has the same
        double-float shape is NOT independently hardware-confirmed. Taking
        the last float is the safe generalization either way (a
        single-float reply is unaffected), but that one corner should be
        checked against real hardware before being trusted blind.
        """
        if self.is_transport_error:
            return None, f"transport_error: {self.args}"
        if self.error:
            return None, f"console_error: {self.error}"
        if value_type == "s":
            strings = [a for a in self.args if isinstance(a, str)]
            return (strings[-1] if strings else None), (None if strings else "no_string_in_reply")
        if value_type == "f":
            floats = [a for a in self.args if isinstance(a, float)]
            return (floats[-1] if floats else None), (None if floats else "no_float_in_reply")
        if value_type == "i":
            ints = [a for a in self.args if isinstance(a, int)]
            return (ints[-1] if ints else None), (None if ints else "no_int_in_reply")
        return None, f"unknown_value_type: {value_type!r}"


def decode_message(data: bytes) -> OscReply:
    address, offset = _read_string(data, 0)
    typetag_full, offset = _read_string(data, offset)
    typetag = typetag_full[1:] if typetag_full.startswith(",") else typetag_full
    args = []
    for t in typetag:
        if t == "s":
            s, offset = _read_string(data, offset)
            args.append(s)
        elif t == "f":
            (v,) = struct.unpack_from(">f", data, offset)
            args.append(v)
            offset += 4
        elif t == "i":
            (v,) = struct.unpack_from(">i", data, offset)
            args.append(v)
            offset += 4
        elif t == "b":
            (blen,) = struct.unpack_from(">i", data, offset)
            offset += 4
            args.append(data[offset : offset + blen])
            offset += blen
            while offset % 4 != 0:
                offset += 1
        else:
            # Unknown type char -- stop parsing further args rather than guess.
            break
    return OscReply(address=address, typetag=typetag, args=args, raw=data)


def join_addr(parent: str, child: str) -> str:
    if parent == "/":
        return "/" + child
    return parent.rstrip("/") + "/" + child


# --------------------------------------------------------------------------
# Node data dumps -- a whole node's values in one round trip
# --------------------------------------------------------------------------
#
# The protocol PDF, p24-25 ("Special Node Type/Arguments"), with its own
# worked example:
#
#     Node data dump: When using this format, the data returned will
#     strictly correspond to what would be saved in a snap file;
#     Read-only and temporary data are not returned.
#
#     /fx/1 ,s *
#       ->W,   16 B: /fx/1~~~,s~~*~~~
#       W->,   32 B: /fx/1~~~,s~~mdl=NONE,fxmix=100,~
#
# and, on the same page, `/ch/1 ,s *` answered with 2,156 bytes carrying
# the ENTIRE channel -- `in.conn.grp`, `name`, `mute`, `fdr`, all sixteen
# bus sends, all eight matrix sends, all four Main routes, `tags`. One
# datagram for the 106 addresses `audit.read_console_state` asks for per
# channel, one at a time.
#
# The grammar is the write side's, read back (p23): items separated by
# ',', '.' navigating down, leading '.'s navigating up, '/' the root.
# `parse_node_dump` below is that walk, and `tests/test_node_dump.py`
# parses the PDF's own `/ch/1` example verbatim.
#
# Two cautions, both from the same pages:
#
# - "Nodes can return large amounts of data; as a result, some nodes
#   cannot be returned using OSC/UDP as they would overflow the 32kB UDP
#   buffer limitation; In such situation, WING will return an error OSC
#   message event." A channel is ~2kB, so a per-object dump is safe and
#   `/ch` (40 x that) is not. Nothing here dumps above object level.
# - "Read-only and temporary data are not returned" -- every leaf this
#   project reads is settable, so none of them is excluded on that
#   ground. A leaf can still be ABSENT from a dump, and an absent leaf is
#   an unknown value, never a default: the caller reads that one leaf the
#   old way.

NODE_DUMP_MODE = "*"

# What WING writes for a fader or send level at -infinity dB, in the text
# form a dump carries. The per-leaf `,sff` reply for the same parameter
# carries '-oo' as its text argument and -144.0 as its float (protocol
# PDF p21, and hardware: the A1 raw log of 2026-09-21), so
# this is the number a dump has to produce for the two paths to agree.
MINUS_INFINITY_DB = -144.0


class NodeDumpError(ValueError):
    """A node dump that this parser will not guess at.

    Raised rather than returned partially, because half a dump is worse
    than none: the missing half would read as "the console did not say",
    and the caller would record unknown values as unread instead of
    reading them properly. Every caller answers this by falling back to
    per-leaf GETs for the whole node.
    """


def _split_dump_items(dump: str) -> list[str]:
    """Split on ',' except inside a single-quoted value.

    WING quotes a value that would otherwise be ambiguous -- the PDF's
    own channel dump carries `ratio='1:3'`. What it does with a *comma*
    inside a free-text value (a channel named "Vox, Lead") is NOT
    documented and has not been seen on hardware, which is why
    `audit.DUMP_UNSAFE_LEAVES` never takes a name or a tag from a dump at
    all. This splitter handles the quoted case and lets the parser reject
    anything it cannot read.
    """
    items, current, quoted = [], [], False
    for ch in dump:
        if ch == "'":
            quoted = not quoted
            current.append(ch)
        elif ch == "," and not quoted:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    items.append("".join(current))
    if quoted:
        raise NodeDumpError("unterminated quote in node dump")
    return items


def _unquote(value: str) -> str:
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


# A WING node or parameter name, as the console's own '?' listings spell
# them: `$stat`, `MX1`, `1`, `in`, `dlymode`, `$a_chn`. Anything else in
# a dump means the split landed somewhere it should not have.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_$][A-Za-z0-9_$-]*$")


def parse_node_dump(node: str, dump: str) -> dict[str, str]:
    """`{address: text value}` for every leaf in one `,s *` node dump.

    `node` is the address that was dumped (`/ch/1`); the returned keys are
    full OSC addresses under it (`/ch/1/send/3/lvl`). Values are the
    console's own text, unconverted -- turning `-oo` into a number, or
    `0` into an int, is a decision about the leaf's type and belongs to
    whoever knows the type.

    The walk, from the PDF's grammar (p23) and confirmed against its
    `/ch/1` example (p25), which `tests/test_node_dump.py` parses in full:

        in.set.srcauto=0   ->  /ch/1/in/set/srcauto, and we are now IN
                               /ch/1/in/set
        altsrc=0           ->  /ch/1/in/set/altsrc   (a sibling)
        .conn.grp=LCL      ->  one leading dot: up one, then down 'conn'
        ..flt.lc=0         ->  two leading dots: up two, then down 'flt'
        .                  ->  as the LAST item, the climb back out of the
                               last child. Ignored; see below.

    Raises `NodeDumpError` for anything that does not fit, including an
    item with no '=', a name that is not an identifier, and a climb past
    the node that was dumped. A refused dump costs one fallback to
    per-leaf reads; a guessed one costs a wrong value in a report whose
    whole claim is that its values are real.
    """
    values: dict[str, str] = {}
    path: list[str] = []
    items = [raw.strip("\n\r") for raw in _split_dump_items(dump)]
    for position, item in enumerate(items):
        if not item:
            continue  # the trailing comma WING ends a dump with
        up = len(item) - len(item.lstrip("."))
        rest = item[up:]
        if up:
            if up > len(path):
                raise NodeDumpError(
                    f"{node}: item {item!r} climbs {up} level(s) above {path}")
            path = path[:len(path) - up]
        if up and not rest and not any(items[position + 1:]):
            # A dump of an INTERMEDIATE node ends by climbing back out of
            # the last child it descended into, and that climb is an item
            # of its own with nothing after it. Measured 2026-09-23,
            # the A12 protocol probes:
            #
            #   /bus/1/send -> 1.on=0,lvl=-oo,pre=0,. ... .MX8.on=0,lvl=-oo,pre=0,.
            #
            # A11 refused the whole dump over exactly this (`item '.' has
            # no '='`), which is why `/ch/1/send` read as unparseable.
            #
            # Accepted ONLY as the last item, where ignoring it cannot
            # mis-address anything that follows -- there is nothing
            # following. A dots-only item in the MIDDLE would change where
            # every later leaf lands, and no dump has ever shown one, so
            # that still refuses the dump and falls back. Same posture as
            # the rest of this parser: a fallback costs requests, a guess
            # costs a wrong value.
            #
            # The climb bound above is still enforced first: a trailing
            # token that climbs further than the parser ever descended is
            # evidence the walk went wrong EARLIER, which would mean
            # addresses already recorded are wrong. That is a refusal.
            break
        name_part, sep, value = rest.partition("=")
        if not sep:
            raise NodeDumpError(f"{node}: item {item!r} has no '='")
        names = name_part.split(".")
        if not all(names) or not all(_IDENTIFIER.match(n) for n in names):
            raise NodeDumpError(f"{node}: item {item!r} has an unreadable name")
        leaf = names[-1]
        descend = names[:-1]
        address = node.rstrip("/") + "/" + "/".join(path + descend + [leaf])
        values[address] = _unquote(value)
        path = path + descend
    return values



def dump_text_rounding_band(text: str) -> float:
    """How far from the exact value a float printed as `text` in a node dump
    can be: half a unit of the text's last non-zero digit, or 0.0 for a
    level at -oo (exact).

    A dump prints the desk's DISPLAY text, not the value a single read gives:
    on a Compact, `144.6788` came back as `144.7`, `999.2505` as `999.0` and
    `100.4755` as `100.0`. Where the desk rounds is not stated, but a number
    printed with trailing zeros was rounded at that digit or a finer one, so
    the error is at most half a unit of the last digit that is not zero --
    `100.0` is within 50 of the truth, `144.7` within 0.05. That bound is
    derived from the text alone, so it holds for every parameter and every
    model, and is deliberately wide for a round number: a caller that cannot
    tell its verdict from it reads the address singly. A zero has no
    non-zero digit, so its own printed precision is the unit (`0.0`: 0.05).
    """
    from decimal import Decimal, InvalidOperation

    stripped = text.strip()
    if stripped in ("-oo", "-\u221e"):
        return 0.0
    try:
        number = Decimal(stripped)
    except InvalidOperation:
        return float("inf")
    if not number.is_finite():
        return float("inf")
    exponent = (number.normalize() if number else number).as_tuple().exponent
    return float(Decimal(5).scaleb(exponent - 1))


def value_from_dump_text(text: str, value_type: str) -> tuple[object, str | None]:
    """`(value, error)` for one dump value, in the same shape and with the
    same meanings `OscReply.value()` returns for a per-leaf reply -- so a
    caller can take either path and store the result the same way.

    The two paths must agree, and there are two places they could not:

    - **-oo.** A dump writes a level at -infinity dB as `-oo`; the
      per-leaf reply carries the same text plus the float -144.0, and
      `OscReply.value('f')` takes the float. So `-oo` becomes
      `MINUS_INFINITY_DB` here.
    - **Patch indices.** `OscReply.value('i')` takes the reply's INT
      argument, which for a connector is one less than the number the
      desk shows and the SET takes -- hence `console_facts.
      correct_readback_index` at every per-leaf call site. A
      dump carries the TEXT form instead, which is the un-offset number:
      hardware, the A1 raw log of 2026-09-21, `/ch/7/in/conn/in` ->
      `['6', 0.0794, 5]`, where 0.0794 = 5/63 and the corrected value is
      6 -- the text. So a dump value must NOT be run through
      `correct_readback_index`, and `audit.read_console_state` does not.
    """
    if value_type == "s":
        return text, None
    if value_type == "f":
        if text.strip() in ("-oo", "-∞"):
            return MINUS_INFINITY_DB, None
        try:
            return float(text), None
        except ValueError:
            return None, f"dump_value_not_a_float: {text!r}"
    if value_type == "i":
        try:
            return int(text), None
        except ValueError:
            return None, f"dump_value_not_an_int: {text!r}"
    return None, f"unknown_value_type: {value_type!r}"


# --------------------------------------------------------------------------
# Several requests in flight
# --------------------------------------------------------------------------
#
# Every read was strictly serial: send, wait for the
# reply, send the next. That makes a read's time the number of requests
# times the round trip, and the round trip is the network's, not the
# desk's. On 2026-10-02 the Demo show's reset read ran at about 0.26ms a
# request; on 2026-10-13, over another network, the same
# 2,448 requests took about 38s, ~16ms each, and an `apply` preview of
# the Demo almost two minutes. Nothing in the code had changed.
#
# So the long reads keep a bounded WINDOW of requests in flight
# (`WingConsole.get_many`, `node_dump_many`, and `read_in_windows` below
# for the callers), and the read takes about `requests x round trip /
# window`. What does not change, and is the reason this is safe:
#
# - **Replies are matched by the address they carry**, exactly as
#   `_request` matches them, and **never two requests for one address
#   are in flight at once.** The protocol has no request id, so two
#   in-flight requests for the same address could not be told apart; a
#   repeat waits until the first is answered. Reordering on the wire is
#   therefore harmless: each reply finds its own request.
# - **Every request has its own timeout and retries**, counted from its
#   own send -- `(retries + 1)` sends, each waiting the timeout -- so an
#   unanswered address is still detected, still named and still costs
#   no more than it did. What changes is that unanswered requests now
#   wait side by side instead of one after another.
# - **Anything else that arrives is drained** and kept as a late reply
#   (`late_reply`), as before.
# - **Only reads.** Writes, and the readback that follows each write,
#   stay one at a time: a write's readback races the write itself on
#   this desk, and the selector order of `apply` is an order.
#
# The window is `DEFAULT_WINDOW` (8), or `ATOO_CONSOLE_WINDOW`. **1 is
# the serial client every read used, exactly**: `get_many` then just calls `_request`
# once per address, in order, and nothing else. So is
# `ATOO_OSC_REPLY_MATCH=off`, which takes the next datagram as the
# answer and so cannot have two requests outstanding at all.
#
# Why 8. Nothing measured says how a WING behaves with many requests
# queued at it: every hardware run so far was serial. 8 is small -- under
# 1kB of requests, and at most 8 replies, the largest a ~2kB channel
# dump, against the desk's own 32kB UDP limit -- and at a 15ms round
# trip it is about an 8x shorter read. If the desk drops replies under
# that load, every one is retried and reported as before, the read gets
# slower rather than wrong, and `ATOO_CONSOLE_WINDOW=1` puts it back.


def window_setting(environ=None) -> tuple[int, str | None, str | None]:
    """`(window, source, problem)` from `ATOO_CONSOLE_WINDOW`.

    `source` is the variable's name when it set the window, None for the
    default. `problem` is a one-line message when the variable is set to
    something that is not a whole number of at least 1 (the default is
    used then) or is above `MAX_WINDOW` (which is used then). Both
    follow the quiet-but-visible posture `cli._env_number` takes for the
    other `ATOO_CONSOLE_*` variables."""
    environ = os.environ if environ is None else environ
    raw = (environ.get(WINDOW_ENV) or "").strip()
    if not raw:
        return DEFAULT_WINDOW, None, None
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        return DEFAULT_WINDOW, None, (
            f"{WINDOW_ENV}={raw!r} is not a whole number of at least 1 -- "
            f"ignoring it (window {DEFAULT_WINDOW})")
    if value > MAX_WINDOW:
        return MAX_WINDOW, WINDOW_ENV, (
            f"{WINDOW_ENV}={raw!r} is more than {MAX_WINDOW} -- using {MAX_WINDOW}")
    return value, WINDOW_ENV, None


def window_notice(environ=None) -> str | None:
    """The one line a run says about `ATOO_CONSOLE_WINDOW`, or None when there is nothing to say: the variable's problem
    when it was rejected or capped, else `Using console window N from
    ATOO_CONSOLE_WINDOW` when it set a window other than the
    default. The CLI prints it before a command contacts a desk
    (`cli._resolve_console_settings`), so a run started from the UI --
    which is that command -- carries it in its log; the Watch page,
    which is not a command, shows it as a session note."""
    window, source, problem = window_setting(environ)
    if problem:
        return problem
    if source and window != DEFAULT_WINDOW:
        return f"Using console window {window} from {source}"
    return None


#: What `read_in_windows` yields for an address its `should_ask` declined.
SKIPPED = object()


def read_in_windows(console, addresses, *, should_ask=None, on_start=None):
    """`(address, reply)` for every address, in order -- `reply` being what
    `console.get(address)` returns, or `SKIPPED` for one `should_ask`
    declined -- with up to the console's window of GETs in flight.

    The one loop every long per-leaf read shares. The caller
    keeps its own loop body; this only changes how far ahead the requests
    go. Three properties the callers depend on:

    - **Nothing is in flight while the caller's body runs.** The
      addresses go out a batch at a time (one window with `should_ask`,
      four without), and a batch is
      complete before its first result is yielded, so a body that reads
      the desk itself -- `audit.UnansweredFamilies`' liveness probe -- is
      an ordinary serial request on an empty queue.
    - **`should_ask` is asked as each batch is formed**, after the body
      has seen every earlier result. So a family the desk does not have
      (`audit.UnansweredFamilies`) is still cut off; at most one window
      of it is asked, and those wait side by side rather than in a row.
    - **`on_start(address)` is called before each address's result is
      yielded**, and while the batch waits, with the address it is
      waiting on -- so a progress line names the request in flight, and
      `ReadProgress.finish_address` names the right address when one goes
      unanswered.

    A console object with no `get_many` (every test double), or a window
    of 1, takes the serial path: `on_start`, `console.get`, yield -- the
    loop every caller had before, call for call.
    """
    get_many = getattr(console, "get_many", None)
    window = getattr(console, "window", 1)
    if get_many is None or not isinstance(window, int) or window <= 1:
        for address in addresses:
            if should_ask is not None and not should_ask(address):
                yield address, SKIPPED
                continue
            if on_start is not None:
                on_start(address)
            yield address, console.get(address)
        return

    pending = iter(addresses)
    # A read that decides as it goes (`should_ask`) is never more than one
    # window ahead of its decisions: a family the desk does not answer
    # then costs one window of side-by-side timeouts before it is cut
    # off, which is less than the three in a row it cost serially. A read
    # with nothing to decide goes four windows at a time.
    batch_size = window if should_ask is not None else 4 * window
    while True:
        batch: list[tuple[str, bool]] = []
        asked = 0
        for address in pending:
            ask = should_ask is None or should_ask(address)
            batch.append((address, ask))
            asked += ask
            if asked >= batch_size:
                break
        if not batch:
            return
        to_ask = [address for address, ask in batch if ask]
        replies = iter(get_many(to_ask, on_wait=on_start) if to_ask else ())
        for address, ask in batch:
            if not ask:
                yield address, SKIPPED
                continue
            if on_start is not None:
                on_start(address)
            yield address, next(replies)


def node_dumps(console, nodes, *, on_start=None):
    """`(node, dump text or None)` for every node, in order: `node_dump`,
    with up to the console's window of dumps in flight. Same
    contract as `read_in_windows`, and the same serial path for a console
    with no `node_dump_many` or a window of 1."""
    dump_many = getattr(console, "node_dump_many", None)
    window = getattr(console, "window", 1)
    if dump_many is None or not isinstance(window, int) or window <= 1:
        for node in nodes:
            if on_start is not None:
                on_start(node)
            yield node, console.node_dump(node)
        return
    nodes = list(nodes)
    batch_size = 4 * window
    for begin in range(0, len(nodes), batch_size):
        batch = nodes[begin:begin + batch_size]
        for node, dump in zip(batch, dump_many(batch, on_wait=on_start)):
            if on_start is not None:
                on_start(node)
            yield node, dump


@dataclass
class _Flight:
    """One request `_request_many` has on the wire."""
    index: int
    address: str
    packet: bytes
    attempt: int = 0
    deadline: float = 0.0
    sent_order: int = 0
    stale: int = 0


class WingConsole:
    """A tiny synchronous OSC client for one WING console.

    Includes both read (get/query) and write (set_param/set_node) helpers.
    Writes mutate live console state -- callers are responsible for reading
    back and restoring whatever they change; this class doesn't do that for
    you, since what "restore" means depends on the parameter. apply.py is
    the layer that does readback verification and journalling on top of
    this; this class is deliberately just the wire protocol.

    If raw_log is given (an open, writable file object), every request and
    reply is appended to it -- sent bytes, received bytes, the parsed result,
    and exactly what kind of failure occurred if any. This is the thing that
    makes a run diagnosable by someone who wasn't there when it ran: a wrong
    byte-level assumption shows up as an entry here even when the higher-level
    script handled the failure gracefully and moved on.

    request_count/bytes_sent/bytes_received are running totals across every
    call that goes through _request() -- reset them (they're plain ints) to
    measure a specific span. So are replies_discarded (datagrams drained
    because they answered a different address) and replies_used (how many
    of those a caller later consulted through `late_reply`).
    """

    def __init__(self, ip: str, port: int = WING_OSC_PORT, timeout: float = 1.0, raw_log=None,
                 window: int | None = None):
        self.addr = (ip, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.timeout = timeout
        self.raw_log = raw_log
        # How many reads `get_many`/`node_dump_many` keep in flight: the argument, else `ATOO_CONSOLE_WINDOW`, else
        # `DEFAULT_WINDOW`. 1 is the serial client. See "Several requests
        # in flight" above.
        self.window = (min(MAX_WINDOW, max(1, int(window))) if window is not None
                       else window_setting()[0])
        self.request_count = 0
        #: Sends beyond the first of a request: it was not answered in time and went out
        #: again. Real traffic the desk receives, counted apart from `request_count`.
        self.resends = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        # Datagrams drained by _request because they answered some other
        # request. Nonzero means the console duplicated or volunteered
        # something -- which, before reply matching existed, was enough to
        # make every subsequent read report the previous read's value.
        self.replies_discarded = 0
        # How many of those were later consulted and used as evidence
        # about the address they name -- a subset of
        # replies_discarded, the rest of which were genuinely dropped. A
        # run can therefore say "125 drained, 1 of them mattered".
        self.replies_used = 0
        # address -> (mark, reply) for the most recent drained datagram
        # naming that address. See late_reply().
        self._late_replies: dict[str, tuple[int, OscReply]] = {}
        # Monotonic count of datagrams received on this socket. Not a
        # statistic: it is the clock `late_reply(..., after=)` compares
        # against, so a caller can ask "did this arrive AFTER my write?"
        # and never be answered with a copy of the pre-write value.
        self.datagrams_received = 0
        # The model this desk named on `/?`, once it has been asked -- None
        # until then, and for a model `console_facts` has no confirmed
        # facts about. See identity().
        self.console_model: str | None = None

    def _log(self, line: str) -> None:
        if self.raw_log is not None:
            self.raw_log.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
            self.raw_log.flush()

    def _request(self, address: str, typetag: str = "", *args, retries: int = 2,
                 expect: str | tuple[str, ...] | None = None) -> OscReply | None:
        """Send one request and return the reply **to that request**.

        `expect` is the address the reply will carry -- or several, where
        more than one is legitimate. A read expects the address it asked
        for; set_node's ack and the identity query are answered on
        `ACK_ADDRESS`. Anything else that arrives is somebody else's
        datagram and is drained, not returned.

        That drain is the whole point of this method, and it is not
        defensive programming -- it is the fix for a confirmed hardware
        failure. UDP has no request/response pairing; this socket receives
        acks, replies and the console's own unsolicited traffic on one
        queue. Taking "the next datagram" as the answer is only correct
        while the queue is exactly one deep, and **one duplicate desynchs
        every read for the rest of the session, silently**, because each
        request then collects the previous request's reply.

        A 2026-09-21 apply is what this is written from. The desk
        sent `/dca/8/name` twice; the copy was taken as the reply to
        `/mgrp/1/name`, and from there **880 of 1142 reads were answered by
        the wrong leaf**. The journal recorded 188 mismatches -- every one
        of them false -- and, far worse, 44 "match"es that proved nothing.
        A tool whose entire claim is "we read it back and it landed" cannot
        be one duplicated packet away from confidently reading the wrong
        address. Matching makes a stale datagram cost one discarded packet
        instead of the rest of the run: the queue resynchronises on the
        first request after the extra.

        Drained is not destroyed. A datagram this method
        declines to return is still an *addressed* statement by the
        console about the address it names, so it is kept -- see
        `late_reply` -- and a caller verifying THAT address can consult
        it. This is what makes the console's habit of answering a write
        two datagrams late cost nothing: the value arrives, is drained
        here while some later address is being read, and is still on hand
        when the write that was waiting for it is scored.

        `ATOO_OSC_REPLY_MATCH=off` restores the old take-the-next
        behaviour. It exists because this is a wire-protocol change that
        cannot be proven against hardware from here -- if some reply shape
        carries an address neither rule predicts, that is a way to finish a
        console session rather than a blocked evening. `replies_discarded`
        counts what the drain dropped, so a run can say whether it fired.
        """
        expected = (address,) if expect is None else (
            (expect,) if isinstance(expect, str) else tuple(expect))
        match_replies = os.environ.get("ATOO_OSC_REPLY_MATCH", "").lower() != "off"
        packet = encode_message(address, typetag, *args)
        self._log(f"SEND addr={address!r} typetag={typetag!r} args={args!r} "
                  f"expect={'|'.join(expected)} hex={packet.hex()}")
        self.request_count += 1
        for attempt in range(retries + 1):
            if attempt:
                self.resends += 1
            try:
                self.sock.sendto(packet, self.addr)
                self.bytes_sent += len(packet)
            except OSError as exc:
                self._log(f"  SOCKET_ERROR {type(exc).__name__}: {exc}")
                return OscReply(address=address, typetag="SOCKET_ERROR", args=[f"{type(exc).__name__}: {exc}"])

            timed_out = False
            for _ in range(MAX_STALE_REPLIES + 1):
                try:
                    data, _peer = self.sock.recvfrom(MAX_UDP_PACKET)
                    self.bytes_received += len(data)
                    self.datagrams_received += 1
                except socket.timeout:
                    self._log(f"  TIMEOUT attempt={attempt + 1}/{retries + 1}")
                    timed_out = True
                    break
                except OSError as exc:
                    # Network-level failure (host unreachable, etc). Not worth
                    # retrying, and worth surfacing rather than swallowing --
                    # this is a SOCKET_ERROR reply, not a None, precisely so the
                    # caller doesn't have to guess which kind of nothing happened.
                    self._log(f"  SOCKET_ERROR {type(exc).__name__}: {exc}")
                    return OscReply(address=address, typetag="SOCKET_ERROR", args=[f"{type(exc).__name__}: {exc}"])

                self._log(f"  RECV hex={data.hex()}")
                try:
                    reply = decode_message(data)
                except Exception as exc:
                    # The bytes arrived but didn't match this client's parsing
                    # assumptions. Preserve the raw bytes rather than crash or
                    # drop them, so the mismatch is diagnosable without another
                    # hardware round-trip. Undecodable means unmatchable, so
                    # this is returned rather than drained -- the alternative
                    # is spinning until timeout on a console that has started
                    # speaking a shape we do not know.
                    self._log(f"  DECODE_ERROR {type(exc).__name__}: {exc}")
                    return OscReply(
                        address=address,
                        typetag="DECODE_ERROR",
                        args=[f"{type(exc).__name__}: {exc}"],
                        raw=data,
                    )

                self._log(f"  PARSED addr={reply.address!r} typetag={reply.typetag!r} args={reply.args!r}")
                if not match_replies or reply.address in expected:
                    return reply
                self.replies_discarded += 1
                self._remember_late_reply(reply)
                self._log(f"  STALE discarded (wanted {'|'.join(expected)}, got "
                          f"{reply.address!r}); discarded so far: {self.replies_discarded}")
            else:
                # Drained MAX_STALE_REPLIES without a match. Something is
                # producing traffic faster than we can filter it; retrying
                # the send would only add to it.
                self._log(f"  GAVE UP after {MAX_STALE_REPLIES} stale replies "
                          f"waiting for {'|'.join(expected)}")
                return None

            if timed_out and attempt == retries:
                return None
        return None

    def _remember_late_reply(self, reply: OscReply) -> None:
        """File a drained datagram under the address it names, with the
        receive count at which it arrived. Only the most recent one per
        address is kept: two datagrams for the same leaf are the console
        correcting itself (on the 2026-09-21 A1 run `/bus/10/name` was
        pushed twice, the first still carrying the pre-write empty
        string and the second the value that had landed), so the newest
        is the one that describes the console's state now."""
        self._late_replies.pop(reply.address, None)  # refresh its eviction order
        self._late_replies[reply.address] = (self.datagrams_received, reply)
        while len(self._late_replies) > LATE_REPLY_MEMORY:
            self._late_replies.pop(next(iter(self._late_replies)))

    def late_reply(self, address: str, *, after: int = -1) -> OscReply | None:
        """The most recent drained datagram that named `address`, if it
        arrived after the `after` mark -- otherwise None. Read-only;
        `use_late_reply` is what consumes one.

        Two rules, and both exist so this can never manufacture a match:

        - **Only for the address it names.** There is no nearest-match,
          no prefix rule and no "the console was probably talking about
          this". An unaddressed value is not evidence; the whole reason a drained datagram
          is usable at all is
          that it carries its own identity.
        - **Only if it arrived after `after`.** Pass
          `datagrams_received` from before a write and a duplicate of
          the *pre*-write reply -- which is exactly what the console
          also sends -- cannot answer for the write. Callers should
          treat the reply as one more reading to compare, not as proof
          in itself.
        """
        entry = self._late_replies.get(address)
        if entry is None:
            return None
        mark, reply = entry
        return reply if mark > after else None

    def use_late_reply(self, address: str) -> OscReply | None:
        """Consume the stored late reply for `address`: drop it (so the
        same datagram cannot be counted twice) and count it in
        `replies_used`, which is what lets a run's summary tell a
        datagram that was merely dropped from one that answered a
        question."""
        entry = self._late_replies.pop(address, None)
        if entry is None:
            return None
        self.replies_used += 1
        self._log(f"  USED a discarded reply for {address!r}: args={entry[1].args!r} "
                  f"(used so far: {self.replies_used} of {self.replies_discarded} discarded)")
        return entry[1]

    def get(self, address: str) -> OscReply | None:
        """Bare GET. Leaf -> its value(s). Container -> list of child names."""
        return self._request(address, "")

    def query(self, address: str, mode: str) -> OscReply | None:
        """mode is '?' (descriptions), '#' (descriptions+values), or '*' (values only)."""
        if mode not in ("?", "#", "*"):
            raise ValueError("mode must be one of '?', '#', '*'")
        return self._request(address, "s", mode)

    def node_dump(self, address: str) -> str | None:
        """Every settable value under `address`, in ONE round trip, as the
        console's own `key=value,` text -- or None if the desk did not
        answer, errored, or answered with a shape this cannot read.

        This is `query(address, '*')` with the reply unwrapped. Nothing in
        this project called it, and the audit paid 5,712
        serial round trips for what the protocol will hand over in about
        364. `parse_node_dump` turns the text into addresses.

        Returning None rather than raising is deliberate: every caller's
        correct response to "the dump did not work" is the same one --
        read the leaves individually, the way the tool always has.
        """
        # Through the class, so a test double borrowing this method needs
        # only `query` and `_log`.
        return WingConsole._dump_text(self, address, self.query(address, NODE_DUMP_MODE))

    def _dump_text(self, address: str, reply: OscReply | None) -> str | None:
        """A `,s *` reply unwrapped to its dump text, or None. See `node_dump`."""
        if reply is None or reply.is_transport_error or reply.error:
            return None
        if reply.typetag != "s" or not reply.args or not isinstance(reply.args[0], str):
            self._log(f"  NODE DUMP of {address!r} came back as typetag "
                      f"{reply.typetag!r}, which is not a dump; falling back to leaves")
            return None
        return reply.args[0]

    # -- several requests in flight ----------------------------

    def get_many(self, addresses, *, on_wait=None) -> list[OscReply | None]:
        """`[self.get(a) for a in addresses]`, with up to `self.window` of
        them in flight. See "Several requests in flight" above, and
        `_request_many` for the rules. `on_wait(address)` is told which
        request the client is waiting on whenever it blocks."""
        return self._request_many([(address, "", ()) for address in addresses],
                                  on_wait=on_wait)

    def node_dump_many(self, nodes, *, on_wait=None) -> list[str | None]:
        """`[self.node_dump(n) for n in nodes]`, with up to `self.window`
        of them in flight."""
        nodes = list(nodes)
        replies = self._request_many([(node, "s", (NODE_DUMP_MODE,)) for node in nodes],
                                     on_wait=on_wait)
        return [self._dump_text(node, reply) for node, reply in zip(nodes, replies)]

    def _request_many(self, items, *, retries: int = 2, on_wait=None) -> list[OscReply | None]:
        """One reply per `(address, typetag, args)` item, in item order, each
        what `_request(address, typetag, *args, retries=retries)` would
        have returned, with up to `self.window` requests on the wire.

        The rules, each one `_request`'s own carried over:

        - A reply belongs to the in-flight request **for the address it
          carries**, and only one request per address is ever in flight
          (a repeated address waits its turn), so a reply can never be
          taken for another request's -- however the network orders them.
        - Each request is sent at most `retries + 1` times and waits
          `self.timeout` after each send, measured from that send; one that
          is never answered comes back None, as `_request`'s does.
        - A datagram no in-flight request expects is drained and kept as a
          late reply. Every request in flight counts it, and one that has
          seen more than `MAX_STALE_REPLIES` since its last send gives up
          (None), as `_request` does.
        - A datagram that does not decode is the answer, as a
          DECODE_ERROR, to the request longest on the wire -- with one in
          flight that is the request `_request` would have given it to.
        - An OS-level socket error ends the batch: every request not yet
          answered gets the SOCKET_ERROR reply, and every caller already
          stops the run at the first one.

        A window of 1, one item, or `ATOO_OSC_REPLY_MATCH=off` (no
        matching means no way to have two outstanding) is `_request` once
        per item, in order: the serial client, exactly.
        """
        items = list(items)
        match_replies = os.environ.get("ATOO_OSC_REPLY_MATCH", "").lower() != "off"
        if self.window <= 1 or len(items) <= 1 or not match_replies:
            return [self._request(address, typetag, *args, retries=retries)
                    for address, typetag, args in items]

        results: list[OscReply | None] = [None] * len(items)
        waiting = list(range(len(items)))   # not yet sent, in order
        flights: dict[str, _Flight] = {}     # address -> its request on the wire
        sent = 0
        self._log(f"PIPELINE {len(items)} request(s), window {self.window}")

        def socket_error(exc: OSError) -> list[OscReply | None]:
            self._log(f"  SOCKET_ERROR {type(exc).__name__}: {exc}")
            failed = OscReply(address="", typetag="SOCKET_ERROR",
                              args=[f"{type(exc).__name__}: {exc}"])
            for flight in flights.values():
                results[flight.index] = OscReply(flight.address, failed.typetag, list(failed.args))
            for index in waiting:
                results[index] = OscReply(items[index][0], failed.typetag, list(failed.args))
            return results

        def send(flight: _Flight) -> None:
            nonlocal sent
            self.sock.sendto(flight.packet, self.addr)
            self.bytes_sent += len(flight.packet)
            flight.deadline = time.monotonic() + self.timeout
            flight.stale = 0
            sent += 1
            flight.sent_order = sent

        def land(flight: _Flight, reply: OscReply | None) -> None:
            flights.pop(flight.address, None)
            results[flight.index] = reply

        try:
            while waiting or flights:
                # Fill the window, in order, skipping (for now) an address
                # that already has a request on the wire.
                if len(flights) < self.window and waiting:
                    held = []
                    while waiting and len(flights) < self.window:
                        index = waiting.pop(0)
                        address, typetag, args = items[index]
                        if address in flights:
                            held.append(index)
                            if len(held) >= self.window:
                                break
                            continue
                        packet = encode_message(address, typetag, *args)
                        self._log(f"SEND addr={address!r} typetag={typetag!r} args={args!r} "
                                  f"expect={address} hex={packet.hex()}")
                        self.request_count += 1
                        flight = _Flight(index=index, address=address, packet=packet)
                        flights[address] = flight
                        try:
                            send(flight)
                        except OSError as exc:
                            return socket_error(exc)
                    waiting[:0] = held
                if not flights:
                    continue

                # Expire anything past its deadline: resend, or give up.
                now = time.monotonic()
                for flight in sorted(flights.values(), key=lambda f: f.sent_order):
                    if flight.deadline > now:
                        continue
                    self._log(f"  TIMEOUT addr={flight.address!r} "
                              f"attempt={flight.attempt + 1}/{retries + 1}")
                    if flight.attempt >= retries:
                        land(flight, None)
                        continue
                    flight.attempt += 1
                    self.resends += 1
                    self._log(f"RESEND addr={flight.address!r} hex={flight.packet.hex()}")
                    try:
                        send(flight)
                    except OSError as exc:
                        return socket_error(exc)
                if not flights:
                    continue

                oldest = min(flights.values(), key=lambda f: f.sent_order)
                soonest = min(f.deadline for f in flights.values())
                if on_wait is not None:
                    on_wait(oldest.address)
                self.sock.settimeout(max(0.0005, soonest - time.monotonic()))
                try:
                    data, _peer = self.sock.recvfrom(MAX_UDP_PACKET)
                except socket.timeout:
                    continue
                except OSError as exc:
                    return socket_error(exc)
                self.bytes_received += len(data)
                self.datagrams_received += 1
                self._log(f"  RECV hex={data.hex()}")
                try:
                    reply = decode_message(data)
                except Exception as exc:
                    self._log(f"  DECODE_ERROR {type(exc).__name__}: {exc} "
                              f"(given to {oldest.address!r}, longest in flight)")
                    land(oldest, OscReply(address=oldest.address, typetag="DECODE_ERROR",
                                          args=[f"{type(exc).__name__}: {exc}"], raw=data))
                    continue
                self._log(f"  PARSED addr={reply.address!r} typetag={reply.typetag!r} "
                          f"args={reply.args!r}")
                flight = flights.get(reply.address)
                if flight is not None:
                    land(flight, reply)
                    continue
                self.replies_discarded += 1
                self._remember_late_reply(reply)
                self._log(f"  STALE discarded (in flight: {'|'.join(flights)}, got "
                          f"{reply.address!r}); discarded so far: {self.replies_discarded}")
                for flight in list(flights.values()):
                    flight.stale += 1
                    if flight.stale > MAX_STALE_REPLIES:
                        self._log(f"  GAVE UP after {MAX_STALE_REPLIES} stale replies "
                                  f"waiting for {flight.address}")
                        land(flight, None)
        finally:
            self.sock.settimeout(self.timeout)
        return results

    def identity(self) -> OscReply | None:
        """/? -- WING,<ip>,<name>,<model>,<serial>,<firmware>:<build>

        Answered on `/*`, not on `/?`. Confirmed on hardware 2026-09-21:
        `SEND addr='/?'` -> `PARSED addr='/*' args=['WING,192.0.2.16,...']`.
        Both are accepted, because this is the *first* request of a session
        -- the queue is empty, there is nothing to confuse it with, and a
        console or emulator that echoed `/?` would otherwise be unreachable
        at the one call every other command's error message tells you to try.

        The model named in that reply is kept on `self.console_model`, so
        anything downstream can have it without a second round trip and
        without being handed it by every caller in between. `audit.
        read_console_state` is the one that needs it: what counts as a
        factory-default input patch is measured per model
        (`console_facts.FACTORY_INPUT_PATCHES`), and every online command
        already makes this call before reading anything. It stays None
        until the desk is asked, and for a model this project has no
        confirmed facts about.
        """
        reply = self._request("/?", "", expect=(ACK_ADDRESS, "/?"))
        if reply is not None and not reply.is_transport_error:
            self.console_model = console_facts.model_from_identity(reply.args) or self.console_model
        return reply

    def set_param(self, address: str, value, value_type: str = "f") -> None:
        """Single Parameter set (spec p21-22): a leaf address plus one
        type-tagged value ('f' float, 'i' int, 's' string -- WING converts
        as needed). Returns nothing because WING sends nothing back over
        UDP for this form -- there is no reply to wait for, let alone
        check. Pass value=-1 with value_type='i' to use WING's toggle
        special case on a 0/1 int parameter. Caller must read back to
        find out whether this landed -- see this module's docstring.
        """
        if value_type not in ("f", "i", "s"):
            raise ValueError("value_type must be one of 'f', 'i', 's'")
        packet = encode_message(address, value_type, value)
        self._log(f"SET (no-ack) addr={address!r} type={value_type!r} value={value!r} hex={packet.hex()}")
        self.sock.sendto(packet, self.addr)

    def blob(self, address: str, payload: bytes) -> OscReply | None:
        """Send a raw binary payload with OSC's 'b' (blob) typetag. This is
        the documented sugar for issuing native/binary-protocol commands
        over OSC's UDP transport (spec p26-28). Not used by apply.py today
        -- kept for parity with the spike this module was promoted from,
        and because a future native-protocol path would build on it.

        Matched on `ACK_ADDRESS`: a blob is a command, and the only replies
        ever observed for one are the `/*` acks. If a future native-protocol
        path finds otherwise, that is a reason to give this its own `expect`.
        """
        return self._request(address, "b", payload, expect=ACK_ADDRESS)

    def set_node(self, address: str, command: str) -> OscReply | None:
        """Node Data set (spec p22-23): address ('/' for root, or any node)
        plus typetag 's' plus a command string, e.g. "fdr=3,mute=1" against
        node address /ch/1, or a '/'-rooted path list like
        "/ch.1.fdr=-1,mute=0,.2.fdr=0,mute=1" against address '/'.
        Unlike set_param, this DOES get acknowledged: WING replies with
        address '/*' and a single string arg, either "OK" or one of the
        error tokens in ERROR_TOKENS. Returns that reply so the caller can
        check .error directly. apply.py prefers this path over set_param
        wherever the target is a single key=value pair on a known node,
        specifically for that ack -- see apply.py's WRITE_PLAN comments.
        """
        return self._request(address, "s", command, expect=ACK_ADDRESS)

    def close(self):
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --- the identity handshake, as a value rather than a printed line -------
#
# `atoo ping` is exactly this: open a socket, send `/?`,
# say what answered, close. `cli._open_console`/`cli.ping_cmd` do it in CLI
# shape -- an argparse Namespace in, `print()` to stdout/stderr out, and an
# *open* console handed back for the command to keep reading through. None
# of that is reusable from a web request handler, which needs a value it
# can serialise and no side effects at all.
#
# So the three steps live here, once, as a function: `identity()`, the
# SOCKET_ERROR check, and `console_facts.model_from_identity`
# -- the same three `_open_console` performs, in the same order, with the
# same meanings. This is what `webui.py`'s `POST /api/ping` calls (the UI's
# Ping button, mockup version H's bundle bar). When `cli.py` is next free
# of in-flight work, `_open_console` should be rewritten on top of this; it
# cannot be today, because it must hand the console back still open, and
# this closes it -- which is the whole reason a ping is safe mid-show.


@dataclass(frozen=True)
class PingResult:
    """What one `/?` round trip found out.

    `ok` is the only question a caller has to answer: the desk replied,
    and the reply was a real one. Everything else is detail for the human
    -- `error` is set when and only when `ok` is False, and carries a
    message already phrased for a user, the same wording `ping` prints.
    """

    ok: bool
    address: str
    port: int
    identity: tuple = ()              # the `/?` reply's args, as strings
    model: str | None = None          # a key of console_facts.CONSOLE_MODELS
    model_label: str | None = None    # that model's human label
    elapsed_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """The wire shape `POST /api/ping` answers with. Every key is
        always present, including the null ones: a browser that has to
        ask `if ("model" in r)` before reading it is a browser one
        rename away from rendering a silently blank pill."""
        return {
            "ok": self.ok,
            "address": self.address,
            "port": self.port,
            "identity": list(self.identity),
            "model": self.model,
            "model_label": self.model_label,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


def ping(ip: str, *, port: int = WING_OSC_PORT, timeout: float = 1.0) -> PingResult:
    """One OSC round trip to `/?`, nothing else read, socket closed.

    **Reads nothing beyond the identity reply** (FR-X.16), which is what
    makes it safe to run in the middle of a show -- no strip sweep, no
    writes, one datagram out and one in. `tests/test_ping.py` asserts that
    property for the CLI by counting a fake console's requests;
    `tests/test_webui.py` asserts it again for this function, because the
    browser button is the one someone will press mid-set.

    Never raises for an unreachable desk: an OS-level failure, a timeout
    and a garbled reply all come back as `ok=False` with a message. A ping
    is a question, and "no" is an answer rather than an exception.
    """
    from atoo import console_facts

    console = WingConsole(ip, port=port, timeout=timeout)
    started = time.monotonic()
    try:
        reply = console.identity()
    finally:
        console.close()
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)

    if reply is None:
        return PingResult(
            ok=False, address=ip, port=port, elapsed_ms=elapsed_ms,
            error=f"no reply from {ip}:{port} -- is the console reachable, and is "
                  f"its OSC remote enabled?",
        )
    if reply.is_socket_error:
        # A SOCKET_ERROR reply is truthy, which is what let
        # "Console: OSError: [Errno 65] No route to host" print as a
        # successful connection for a while. Checked explicitly, here as
        # in `_open_console`.
        return PingResult(
            ok=False, address=ip, port=port, elapsed_ms=elapsed_ms,
            error=f"couldn't reach {ip}:{port} -- {reply.args[0]}",
        )

    model = console_facts.model_from_identity(reply.args)
    return PingResult(
        ok=True, address=ip, port=port,
        identity=tuple(str(a) for a in reply.args),
        model=model,
        model_label=console_facts.CONSOLE_MODELS[model]["label"] if model else None,
        elapsed_ms=elapsed_ms,
    )
