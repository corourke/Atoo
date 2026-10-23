"""The Demo show's simulated WING, on a localhost UDP socket.

The Demo show has no desk behind it, and before this module that meant Apply
could not preview anything in it: a preview is a read of a desk. Watch
already ran on a simulated rig (`webui.demo_provider_factory`, over
`web/demo_states/before.json`), so the Demo could be watched but not
previewed. This module lets it be previewed **through the real command**:
`atoo apply` (or `patch`) is pointed at `127.0.0.1` and a port this
module answers on, so the preview read -- `initialize.read_desk`, the
reset read, the occupancy read, the windowed `console.read_in_windows`,
the readback index correction -- is the same code a real desk gets. A
preview path that read a Python dict instead would be a second opinion
about what a preview is.

**What the desk holds.** The shipped initialized capture for the WING
Compact (`initialize.load_capture`), with `before.json` -- the clean rig
the Demo show describes, as if its plan had been applied -- laid over it.
So it answers every address a real Compact does, and its strips carry the
Demo show, as Watch's rig does. None of Watch's random faults are armed:
a preview of the same plan reads the same desk every time.

**It is read-only.** A set (`,s` with a value, or a typed parameter) is
dropped and never answered, so a write that somehow reached it would read
back as a mismatch rather than appear to land. Nothing should: the server
refuses every Demo write before a command starts (`_demo_write_refusal`
in `webui.create_app`), and a preview passes no `--confirm`. This is the
second lock, not the first.

It answers the way `tests/snap_desk.SnapDesk` does, which is the way the
protocol PDF and the hardware runs say a WING does: a per-leaf GET as
`,s` / `,sfi` / `,sff` (a connector's INT one LOWER than the number it
shows), a node dump in the climbing-dots grammar, `/?` with the
identity, and NODE NOT FOUND for a leaf it does not have.
"""

from __future__ import annotations

import json
import socket
import threading
from functools import lru_cache
from pathlib import Path

from atoo import console_facts
from atoo.console import (MINUS_INFINITY_DB, NODE_DUMP_MODE, decode_message,
                               encode_message)

DEMO_STATE_FILE = Path(__file__).parent / "web" / "demo_states" / "before.json"
#: The model the Demo show is built for and the rig `before.json` describes.
DEMO_MODEL = "wing-compact"
#: What the simulated desk answers to `/?`: a WING Compact called "Demo".
#: The serial is not a real one, so no journal row of a real desk can ever
#: be matched to it.
DEMO_IDENTITY = "WING,127.0.0.1,Demo,wing-compact,DEMO-SIMULATED,3.1-0:demo"
#: How the page and the run log name this desk.
DEMO_DESK_WORDS = "the Demo's simulated WING"


@lru_cache(maxsize=1)
def _rig() -> tuple[tuple[str, object], ...]:
    from atoo.initialize import coerce, leaf_types, load_capture, template

    capture = load_capture(DEMO_MODEL)
    values: dict[str, object] = {}
    if capture is not None:
        values.update((leaf.address, leaf.value) for leaf in capture.leaves)
    types = leaf_types()
    state = json.loads(DEMO_STATE_FILE.read_text(encoding="utf-8"))
    for address, value in state.items():
        if not address.startswith("/"):
            continue  # `_comment`
        if value is None:
            values.pop(address, None)
            continue
        # In the type the desk takes, as the capture's leaves are: an FX
        # mix of 100 is a float on the desk, and answers as one.
        spec = types.get(template(address))
        values[address] = coerce(value, spec) if spec else value
    return tuple(values.items())


def demo_rig_values() -> dict[str, object]:
    """`address -> value` of the simulated desk, a fresh copy each call."""
    return dict(_rig())


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "-oo" if value <= MINUS_INFINITY_DB else repr(value)
    if isinstance(value, str) and ("," in value or "=" in value):
        return f"'{value}'"
    return str(value)


class DemoDesk:
    """The simulated desk, answering on `127.0.0.1:port` until `close()`.

    One thread, one request at a time in arrival order, as a real desk's
    single OSC task does; there is no network delay to simulate.
    """

    def __init__(self, values: "dict[str, object] | None" = None,
                 identity: str = DEMO_IDENTITY):
        self.values = demo_rig_values() if values is None else dict(values)
        self.identity = identity
        self._index: dict[str, list[str]] = {}
        for address in self.values:
            parts = address.split("/")
            for depth in range(2, len(parts)):
                self._index.setdefault("/".join(parts[:depth]), []).append(address)
        #: How many requests it answered -- what a preview read, for a test.
        self.answered = 0
        #: Sets it was sent and dropped. Should stay 0.
        self.refused_writes = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.05)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="demo-desk", daemon=True)
        self._thread.start()

    # -- the desk ----------------------------------------------------------

    def _get(self, address: str) -> tuple[str, str, list]:
        if address not in self.values:
            return address, "s", ["NODE NOT FOUND"]
        value = self.values[address]
        if isinstance(value, str):
            return address, "s", [value]
        if isinstance(value, (bool, int)):
            offset = console_facts.readback_index_offset(address) or 0
            return address, "sfi", [str(int(value)), 0.0, int(value) - offset]
        return address, "sff", [_text(value), 0.0, float(value)]

    def _dump(self, node: str) -> str:
        items, path = [], []
        for address in self._index.get(node, []):
            segments = address[len(node) + 1:].split("/")
            items.append("." * len(path) + ".".join(segments) + f"={_text(self.values[address])}")
            path = segments[:-1]
        return ",".join(items) + "," if items else "NODE NOT FOUND"

    def _answer(self, address: str, typetag: str, args: list):
        if address == "/?" and not typetag:
            return "/*", "s", [self.identity]
        if not typetag:
            return self._get(address)
        if typetag == "s" and args == [NODE_DUMP_MODE]:
            return address, "s", [self._dump(address)]
        self.refused_writes += 1
        return None

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, peer = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                request = decode_message(data)
                answer = self._answer(request.address, request.typetag, list(request.args))
            except Exception:  # a garbled datagram is not an answer
                continue
            if answer is None:
                continue
            self.answered += 1
            try:
                self.sock.sendto(encode_message(answer[0], answer[1], *answer[2]), peer)
            except OSError:
                return

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
