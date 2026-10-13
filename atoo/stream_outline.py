"""Read a JSON document as it streams in, tolerantly, for the live view.

The maintainer, 2026-09-26: *"Is there any way to show progress updates from the
build step or get progressive output? It would be nice to be able to stop
it if things are going haywire."* A count of characters says a build is
alive; it does not say whether it is doing the right thing. The goal is
that he can read "Channels · 14 · Horns -- dca: Vocals" on step 04 and
decide to press Stop.

So `StreamOutline` is fed the model's text one chunk at a time, as the
provider receives it, and keeps:

- **which part of the document it is on** -- the top-level key being
  written (`channels`, `busses`, `dcas` ...);
- **the names written so far** in each part: a list's items by their
  `name` (or `id`, or -- the reply's channels, which write a `name` only
  when it differs from the input-list row -- their `input`), a name-keyed
  map's items by their keys. The plan format on disk has both (`channels`
  is a list; `busses`, `dcas`, `mute_groups` and `outputs` are maps), and
  the reply the generator writes has lists throughout (`reply_expand`);
- **the item being written now**: its name, its number when it has one
  (`channel`), the field in progress, and the short string lists written
  under its fields so far (`dca: ["Vocals"]`, `bus_sends: ["Monitor 1"]`).

**Tolerant, by construction.** It is an incremental scanner, not a parser
that runs on the whole text: it never needs the document to be finished,
never raises on anything a model writes, and never looks back. Text before
the first `{` (a code fence, a sentence of preamble) is skipped, and
anything after the root object closes is ignored. A malformed document
degrades the outline; it cannot break the build, which validates the
finished plan on its own terms (`generate.py`) regardless.

**Bounded.** A snapshot keeps at most `MAX_NAMES` recent names per part
(with the full count), `MAX_NAME_CHARS` of each, and a handful of values
per field, because the snapshot rides on `GET /api/build/status`, which
the page polls every second.

Nothing here knows what a plan means. It knows JSON, and that items have
names. The page decides how to word it.
"""

from __future__ import annotations

MAX_NAMES = 48
MAX_NAME_CHARS = 60
# The longest string kept while scanning. Names and keys are short; a
# long `provenance` or `description` string is scanned but not kept.
_MAX_STRING = 200
_MAX_FIELDS = 6
_MAX_VALUES = 8
# Under an item's field, the keys whose string values name something:
# `bus_sends: [{"bus": "Monitor 1", ...}]`.
_NAMING_KEYS = ("bus", "name", "id", "group")

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}


class _Frame:
    __slots__ = ("kind", "key", "expect_key", "index")

    def __init__(self, kind: str) -> None:
        self.kind = kind          # "obj" or "arr"
        self.key: str | None = None
        self.expect_key = kind == "obj"
        self.index = -1


class StreamOutline:
    """Feed it text with `feed()`; read it with `snapshot()`."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self._stack: list[_Frame] = []
        self._in_string = False
        self._string_is_key = False
        self._escape = False
        self._unicode: list[str] | None = None
        self._buf: list[str] = []
        self._scalar: list[str] | None = None
        # name -> {"kind", "count", "names"}; dicts keep insertion order.
        self._sections: dict[str, dict] = {}
        self.section: str | None = None
        self.item: dict | None = None

    # -- scanning ------------------------------------------------------------

    def feed(self, text: str) -> None:
        for ch in text:
            try:
                self._char(ch)
            except Exception:  # noqa: BLE001 -- an outline must never break a call
                pass

    def _char(self, ch: str) -> None:
        if self.closed:
            return
        if not self.started:
            if ch == "{":
                self.started = True
                self._stack.append(_Frame("obj"))
            return
        if self._in_string:
            self._string_char(ch)
            return
        if self._scalar is not None:
            if ch in ",}]:" or ch.isspace():
                value = "".join(self._scalar)
                self._scalar = None
                self._on_scalar(value)
            else:
                if len(self._scalar) < 40:
                    self._scalar.append(ch)
                return
        if ch.isspace():
            return
        top = self._stack[-1] if self._stack else None
        if top is None:
            return
        if ch == '"':
            self._in_string = True
            self._string_is_key = top.kind == "obj" and top.expect_key
            if not self._string_is_key:
                self._value_start("str")
            self._buf = []
        elif ch in "{[":
            self._value_start("obj" if ch == "{" else "arr")
            self._stack.append(_Frame("obj" if ch == "{" else "arr"))
        elif ch in "}]":
            self._stack.pop()
            if not self._stack:
                self.closed = True
        elif ch == ":":
            top.expect_key = False
        elif ch == ",":
            if top.kind == "obj":
                top.expect_key = True
        else:
            self._value_start("scalar")
            self._scalar = [ch]

    def _string_char(self, ch: str) -> None:
        if self._unicode is not None:
            self._unicode.append(ch)
            if len(self._unicode) == 4:
                try:
                    self._append(chr(int("".join(self._unicode), 16)))
                except ValueError:
                    pass
                self._unicode = None
            return
        if self._escape:
            self._escape = False
            if ch == "u":
                self._unicode = []
            else:
                self._append(_ESCAPES.get(ch, ch))
            return
        if ch == "\\":
            self._escape = True
        elif ch == '"':
            self._in_string = False
            value = "".join(self._buf)
            self._buf = []
            if self._string_is_key:
                self._on_key(value)
            else:
                self._on_string(value)
        else:
            self._append(ch)

    def _append(self, ch: str) -> None:
        if len(self._buf) < _MAX_STRING:
            self._buf.append(ch)

    # -- what the scan means -------------------------------------------------

    def _depth(self) -> int:
        return len(self._stack)

    def _value_start(self, kind: str) -> None:
        """A value begins in the container on top of the stack."""
        top = self._stack[-1]
        if top.kind == "arr":
            top.index += 1
        depth = self._depth()
        if depth == 1 and top.key is not None:
            # A top-level part: a list or a map of items, or a plain value.
            self.section = top.key
            self.item = None
            if kind in ("arr", "obj"):
                self._sections.setdefault(top.key, {
                    "kind": "list" if kind == "arr" else "map", "count": 0, "names": []})
        elif depth == 2 and top.kind == "arr" and self.section in self._sections:
            # A new item in a list part.
            part = self._sections[self.section]
            part["count"] += 1
            self.item = {"section": self.section, "index": top.index,
                         "name": None, "number": None, "field": None, "values": {}}

    def _on_key(self, key: str) -> None:
        top = self._stack[-1]
        top.key = key
        top.expect_key = False
        depth = self._depth()
        if depth == 1:
            self.section = key
            self.item = None
        elif depth == 2 and self.section in self._sections \
                and self._sections[self.section]["kind"] == "map":
            # A name-keyed map: the key IS the item's name.
            self._add_name(self._sections[self.section], key)
            self._sections[self.section]["count"] += 1
            self.item = {"section": self.section, "index": None,
                         "name": _clip(key), "number": None, "field": None, "values": {}}
        elif depth == 3 and self.item is not None:
            self.item["field"] = key

    def _on_string(self, value: str) -> None:
        self._on_value(value, is_string=True)

    def _on_scalar(self, value: str) -> None:
        self._on_value(value, is_string=False)

    def _on_value(self, value: str, *, is_string: bool) -> None:
        item = self.item
        if item is None:
            return
        depth = self._depth()
        top = self._stack[-1]
        if depth == 3 and top.kind == "obj":
            if is_string and top.key in ("name", "id", "input") and \
                    (item["name"] is None or (top.key != "input" and item.get("named_by") == "input")):
                # `input` names the item until a `name` arrives: a reply
                # channel writes a name only when it differs from the row.
                replacing = item["name"] is not None
                item["name"] = _clip(value)
                item["named_by"] = top.key
                part = self._sections.get(item["section"])
                if part is not None and part["kind"] == "list":
                    if replacing and part["names"]:
                        part["names"][-1] = _clip(value)
                    else:
                        self._add_name(part, value)
            elif not is_string and top.key in ("channel", "index", "number"):
                try:
                    item["number"] = int(float(value))
                except ValueError:
                    pass
            return
        if not is_string:
            return
        # Under one of the item's fields: a list of names (`dca`), or a
        # list of objects that name something (`bus_sends[].bus`).
        field = self._stack[2].key if len(self._stack) > 2 else None
        if field is None:
            return
        if (depth == 4 and top.kind == "arr") or \
                (depth == 5 and top.kind == "obj" and top.key in _NAMING_KEYS):
            values = item["values"]
            if field not in values and len(values) >= _MAX_FIELDS:
                return
            bucket = values.setdefault(field, [])
            if len(bucket) < _MAX_VALUES:
                bucket.append(_clip(value))

    @staticmethod
    def _add_name(part: dict, name: str) -> None:
        part["names"].append(_clip(name))
        del part["names"][:-MAX_NAMES]

    # -- reading -------------------------------------------------------------

    def snapshot(self) -> dict | None:
        """None until the document has begun; then where it is and what it
        has named. A copy -- safe to hand to another thread."""
        if not self.started:
            return None
        item = None
        if self.item is not None:
            item = {k: v for k, v in self.item.items() if k not in ("values", "named_by")}
            item["values"] = {k: list(v) for k, v in self.item["values"].items()}
        return {
            "section": self.section,
            "sections": [
                {"name": name, "kind": part["kind"], "count": part["count"],
                 "names": list(part["names"])}
                for name, part in self._sections.items()
            ],
            "item": item,
            "complete": self.closed,
        }


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_NAME_CHARS else text[:MAX_NAME_CHARS - 1] + "…"


def outline_of(text: str) -> dict | None:
    """The outline of `text` read in one go -- what a stream of it would
    have shown at its end. For tests and for a partial reply on disk."""
    outline = StreamOutline()
    outline.feed(text)
    return outline.snapshot()
