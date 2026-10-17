"""A writable fake WING built from a `.snap` -- the test desk.

It holds `address -> value` in the type the desk takes (from
`initialize.leaves_from_snapshot`, so a bool is 0/1 and a list choice its
token) and answers the way the protocol PDF and the hardware runs say a
WING does:

* a per-leaf GET -- `,s` for a string, `,sfi` for an int, `,sff` for a
  float, with a connector's INT one LOWER than the number it shows (`console_facts.readback_index_offset`);
* a node dump (`,s *`), in the climbing-dots grammar of PDF p25, with `-oo`
  for a level at -infinity -- the same shape `tests/test_bulk_read.py`'s
  `TwoWayConsole` answers in;
* `set_node` and `set_param`, which store the value.

`selectors` gives a selector leaf the leaves that exist under each of its
values (`{"/ch/1/gate/mdl": {"PSE": {"/ch/1/gate/ratio": None}}}`): a
leaf named for another value of its selector is not on the desk, so a GET
answers NODE NOT FOUND and a dump leaves it out -- the case of a gate value
that exists only under one gate model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from atoo import console_facts
from atoo.console import MINUS_INFINITY_DB, OscReply
from atoo.initialize import leaf_types, leaves_from_snapshot, template

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def snap_values(path: Path) -> dict[str, object]:
    ae = json.loads(Path(path).read_text())["ae_data"]
    return {leaf.address: leaf.value for leaf in leaves_from_snapshot(ae)}


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "-oo" if value <= MINUS_INFINITY_DB else repr(value)
    if isinstance(value, str) and ("," in value or "=" in value):
        return f"'{value}'"
    return str(value)


class SnapDesk:
    def __init__(self, values: dict[str, object], *, hidden: set[str] | None = None,
                 identity: str = "WING,198.51.100.9,TEST,wing-compact,S1,3.1.0"):
        self.values = dict(values)
        self._index: dict[str, list[str]] | None = None
        # Leaves the desk does not have right now (another selector value's).
        self.hidden = set(hidden or ())
        self.identity_text = identity
        self.gets: list[str] = []
        self.dumps: list[str] = []
        self.writes: list[tuple[str, object]] = []

    # -- reading -------------------------------------------------------
    def get(self, address: str):
        self.gets.append(address)
        if address not in self.values or address in self.hidden:
            return OscReply(address, "s", ["NODE NOT FOUND"])
        value = self.values[address]
        if isinstance(value, str):
            return OscReply(address, "s", [value])
        if isinstance(value, bool) or isinstance(value, int):
            offset = console_facts.readback_index_offset(address) or 0
            return OscReply(address, "sfi", [str(int(value)), 0.0, int(value) - offset])
        return OscReply(address, "sff", [_text(value), 0.0, float(value)])

    def node_dump(self, node: str) -> str | None:
        self.dumps.append(node)
        items, path = [], []
        for address in self._under(node):
            value = self.values[address]
            if address in self.hidden:
                continue
            segments = address[len(node) + 1:].split("/")
            items.append("." * len(path) + ".".join(segments) + f"={_text(value)}")
            path = segments[:-1]
        return ",".join(items) + ("," if items else "") if items else None

    def _under(self, node: str) -> list[str]:
        """The addresses under `node`, in the desk's order -- indexed once
        by every ancestor, so a dump does not scan the whole desk."""
        if self._index is None:
            self._index = {}
            for address in self.values:
                self._add_to_index(address)
        return self._index.get(node, [])

    def _add_to_index(self, address: str) -> None:
        parts = address.split("/")
        for depth in range(2, len(parts)):
            self._index.setdefault("/".join(parts[:depth]), []).append(address)

    # -- writing -------------------------------------------------------
    def _store(self, address: str, value: object) -> None:
        if address not in self.values and self._index is not None:
            self._add_to_index(address)
        self.values[address] = value
        self.hidden.discard(address)
        self.writes.append((address, value))

    def set_node(self, node: str, command: str):
        key, _, text = command.partition("=")
        address = f"{node}/{key}"
        # The parameter map's type for the leaf, as the desk takes it --
        # also for a leaf that only appears under a new selector value.
        # Only a leaf the map does not know keeps its prior's type.
        spec = leaf_types().get(template(address))
        prior = self.values.get(address)
        if spec is not None:
            osc = spec["osc"]
        else:
            osc = "s" if isinstance(prior, str) or prior is None else (
                "i" if isinstance(prior, int) and not isinstance(prior, bool) else "f")
        value: object = (text if osc == "s" else int(float(text)) if osc == "i"
                         else float(text))
        self._store(address, value)
        return OscReply(node, "s", ["OK"])

    def set_param(self, address: str, value, value_type: str = "f") -> None:
        self._store(address, value)

    def identity(self):
        return OscReply("/?", "s", [self.identity_text])

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_SOCKET_LEAF = re.compile(r"^/io/in/(\w+)/(\d+)/(g|mode)$")


class PairedSnapDesk(SnapDesk):
    """A `SnapDesk` whose stereo pairs behave as a WING's do: once both
    sockets of an odd/even pair read mode ST, a gain written to either lands
    on both, and the pair taking ST mode puts the first socket's gain on the
    second. Every stereo pair in the captures on file reads the same gain on
    both sockets, which is what this reproduces."""

    def _store(self, address: str, value: object) -> None:
        super()._store(address, value)
        match = _SOCKET_LEAF.match(address)
        if match is None:
            return
        group, number, leaf = match.group(1), int(match.group(2)), match.group(3)
        first = number if number % 2 else number - 1
        a, b = f"/io/in/{group}/{first}/", f"/io/in/{group}/{first + 1}/"
        if not (self.values.get(a + "mode") == "ST" and self.values.get(b + "mode") == "ST"
                and a + "g" in self.values and b + "g" in self.values):
            return
        if leaf == "g":
            self.values[a + "g"] = self.values[b + "g"] = value
        else:
            self.values[b + "g"] = self.values[a + "g"]
