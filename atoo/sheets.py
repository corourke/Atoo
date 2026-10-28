"""The desk sheets, edited in Build's step 04, laid onto the plan with no model
(desk sheets piece 3).

A show has two sheets: the input list (`input.csv`) and the bus sheet
(`busses.csv`, one row per bus, Main and Matrix). Both are the engineer's
words, and **a filled cell wins**. A Save in step 04 writes the sheet and then
updates the plan from it here, in code: what the cells now say is put into
`plan.json` the way a structured edit would be, and the result is verified.
Nothing calls a model.

* **The bus sheet is read by state.** Each row names its object by the `bus`
  cell (`Bus 3`, `Main 1`, `Matrix 6`), and every FILLED cell is compared
  with what the plan has for that object (`bus_rows_from_plan`). A cell that
  says something else is carried out; a blank cell is left to the plan.
  `sources` is the complete list of what feeds the row: a send it no longer
  names comes out of the plan, and one it adds goes in.
* **The input list is read by row.** A Save knows which row of the file each
  row of the table was (`line`), so it knows what a row said before and what
  it says now: a renamed input renames its channel, a changed patch moves the
  channel's socket, a removed row takes its channel out, and an added row
  with a `channel` cell is put on that channel. An added row with no `channel`
  cell is left for the next build to place, and said.
* **What cannot physically work is refused, naming the cell**: a `bus` cell
  that is no bus, Main or Matrix the desk has; a source no row or channel is
  named; a Main or Matrix feeding a bus; a channel already taken; and every
  new ERROR `verify_plan` finds in the edited plan (a socket the desk does not
  have, a stereo pair that cannot be formed). Nothing is written then.
* **Everything else is carried out, and a choice made on the way is said at
  INFO**: the tap of a new send no row states, a DCA or mute group a cell
  names that the plan did not have, a column the plan does not hold yet.

The plan's sends live on their source (`plan_schema`),
so a bus row's `sources` is spread over the channels' `bus_sends` and
`main_routes`, the buses' `bus_sends` and `destinations`, and every source's
`matrix_sends`. A Matrix whose `sources` cell is edited has its `fed_by`
written as a send on its source, so all its feeds are in one place.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from atoo import console_facts as facts
from atoo import plan_compat
from atoo.input_list import (InputListError, InputRow, format_socket, parse_input_list,
                             parse_socket_spec, rows_feeding)
from atoo.plan_schema import BUS_ROLES, OUTPUT_ROLES

INPUT_SHEET = "input.csv"
BUS_SHEET = "busses.csv"

#: `busses.csv`'s columns, in the spec's order (section 1).
BUS_COLUMNS = ("bus", "name", "role", "width", "sources", "tap", "outputs", "fx", "preset",
               "dca", "mute_group", "label", "notes")
#: The columns a row of the Busses or Outputs table shows; the rest fold open
#: under it (the desk sheets' mockup, revision 3).
BUS_ROW_COLUMNS = ("name", "role", "width", "sources", "tap", "outputs")
BUS_DETAIL_COLUMNS = ("fx", "preset", "dca", "mute_group", "label", "notes")

_LABEL = re.compile(r"^\s*(?P<kind>bus|main|matrix|mtx|mx)\s*(?P<n>\d+)?\s*$", re.IGNORECASE)
_KIND = {"bus": "bus", "main": "main", "matrix": "matrix", "mtx": "matrix", "mx": "matrix"}
_TAP_SUFFIX = re.compile(r"^(?P<name>.*?)\s*\((?P<tap>pre|post)\)\s*$", re.IGNORECASE)
_RUN = re.compile(r"^(?P<head>.*?)\s*(?P<a>\d+)\s*(?:-\s*(?P<b>\d+))?\s*$")
_CAPACITY = {"bus": "bus", "main": "main", "matrix": "mtx"}
#: DCAs and mute groups a desk has: an index past these is no DCA at all.
_GROUP_CAPACITY = {"dcas": facts.CAPACITY["dca"], "mute_groups": facts.CAPACITY["mgrp"]}


@dataclass
class Refusal:
    """A cell that cannot physically work: the sheet, the row as the sheet
    names it, the column, the value as written, and why."""

    sheet: str
    row: str
    column: str
    value: str
    reason: str

    def text(self) -> str:
        cell = f"{self.column} {self.value!r}" if self.value else self.column
        return f"{self.sheet}, {self.row}, {cell}: {self.reason}"

    def as_dict(self) -> dict:
        return {"sheet": self.sheet, "row": self.row, "column": self.column,
                "value": self.value, "reason": self.reason, "text": self.text()}


@dataclass
class Result:
    """The plan with the sheets laid on, or the reasons it cannot be.

    `notes` are the INFO lines (a choice made, a column the plan does not
    hold); `changes` say in a few words what changed in the plan, for the
    Save's message; `unplaced` names the input rows the plan has no channel
    for (the next build places them); `renamed` maps an old channel, bus,
    Main or Matrix name to its new one, so the bus sheet's `sources` can say
    the new name."""

    plan: dict
    notes: list[str] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)
    #: Input-list cells a Save changed that the plan has no field for
    #: (category, notes, preset, order): only a rebuild reads them, so the
    #: plan stays Stale for them.
    uncarried: list[str] = field(default_factory=list)
    #: How a renamed object is written in the sheet's `sources` cells, when
    #: its new name alone would read as a channel (`Bus 4`).
    spelled: dict[str, str] = field(default_factory=dict)

    def sources_spelling(self) -> dict[str, str]:
        """Old name -> what the bus sheet's `sources` cells should now say."""
        return {**self.renamed, **self.spelled}

    @property
    def ok(self) -> bool:
        return not self.refusals


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------

def split_list(text) -> list[str]:
    """A `;`-separated cell, each part stripped, blanks dropped."""
    return [part.strip() for part in str(text or "").split(";") if part.strip()]


def parse_label(text) -> "tuple[str, int | None] | None":
    """`Bus 3` -> `("bus", 3)`, `Bus` -> `("bus", None)` (Atoo picks the
    number), `Main 1`, `Matrix 6` (or `Mtx 6`, `MX6`). None for anything
    else."""
    m = _LABEL.match(str(text or ""))
    if not m:
        return None
    kind = _KIND[m.group("kind").lower()]
    return kind, (int(m.group("n")) if m.group("n") else None)


def label_of(kind: str, index: int) -> str:
    return {"bus": "Bus", "main": "Main", "matrix": "Matrix"}[kind] + f" {index}"


def parse_sources(text) -> list[tuple[str, "str | None"]]:
    """`Kick; Snare (pre)` -> `[("Kick", None), ("Snare", "pre")]`."""
    out = []
    for part in split_list(text):
        m = _TAP_SUFFIX.match(part)
        out.append((m.group("name").strip(), m.group("tap").lower()) if m else (part, None))
    return out


def parse_outputs(text) -> "tuple[list[tuple[str, list[int]]], str | None]":
    """`LCL 7-8; MOD 44-45` -> `[("LCL", [7, 8]), ("MOD", [44, 45])]`, or the
    first part that is not a socket or a range of them, as the reason."""
    runs: list[tuple[str, list[int]]] = []
    for part in split_list(text):
        m = _RUN.match(part)
        parsed = parse_socket_spec(f"{m.group('head')} {m.group('a')}") if m else None
        if parsed is None:
            return [], (f"{part!r} is not an output socket: write a group and a number or a "
                        "range, such as LCL 7-8 or AES50-A 3")
        group, first = parsed
        last = int(m.group("b")) if m.group("b") else first
        if last < first:
            return [], f"{part!r} runs backwards: write the lower socket first"
        runs.append((group, list(range(first, last + 1))))
    return runs, None


def _socket_runs(patches) -> str:
    """A plan's patches as a sheet's `outputs` cell: `LCL 7-8; MOD 44`."""
    sockets = sorted({(p["group"], n) for p in patches for n in p.get("sockets") or []
                      if isinstance(p, dict) and p.get("group")})
    runs: list[list] = []
    for group, n in sockets:
        if runs and runs[-1][0] == group and runs[-1][2] == n - 1:
            runs[-1][2] = n
        else:
            runs.append([group, n, n])
    return "; ".join(format_socket(g, a) if a == b else f"{format_socket(g, a)}-{b}"
                     for g, a, b in runs)


def _socket_set(text) -> "set[tuple[str, int]] | None":
    runs, problem = parse_outputs(text)
    if problem:
        return None
    return {(group, n) for group, ns in runs for n in ns}


def _patches(runs, mono) -> list[dict]:
    """The sheet's sockets as a plan's `patches`: a stereo row's sockets in
    pairs, in order, a mono row's one by one (as `capture` writes them)."""
    out = []
    for group, sockets in runs:
        if mono:
            out.extend({"group": group, "sockets": [n], "stated": True} for n in sockets)
            continue
        for i in range(0, len(sockets), 2):
            out.append({"group": group, "sockets": sockets[i:i + 2], "stated": True})
    return out


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _same_list(a, b) -> bool:
    return sorted(_norm(x) for x in split_list(a)) == sorted(_norm(x) for x in split_list(b))


# ---------------------------------------------------------------------------
# The plan, as the bus sheet sees it
# ---------------------------------------------------------------------------

def _objects(plan: dict) -> list[tuple[str, int, str, dict]]:
    """`(kind, index, key, entry)` for every bus, Main and Matrix, in sheet
    order: buses, then Mains, then Matrices, each by index."""
    out = []
    for key, entry in (plan.get("busses") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("index"), int):
            out.append(("bus", entry["index"], key, entry))
    for key, entry in (plan.get("outputs") or {}).items():
        if isinstance(entry, dict) and entry.get("kind") in ("main", "matrix") \
                and isinstance(entry.get("index"), int):
            out.append((entry["kind"], entry["index"], key, entry))
    order = {"bus": 0, "main": 1, "matrix": 2}
    return sorted(out, key=lambda o: (order[o[0]], o[1]))


def _bus_destinations(entry: dict) -> list[dict]:
    dests = entry.get("destinations")
    if dests:
        return [d for d in dests if isinstance(d, dict)]
    single = entry.get("destination")
    return [single] if isinstance(single, dict) else []


def _feeds(plan: dict, kind: str, key: str, index: int) -> list[tuple[str, str, "str | None"]]:
    """What feeds one bus, Main or Matrix: `[(source kind, source key,
    tap)]`, channels first, then buses, then Mains."""
    found: list[tuple[str, str, "str | None"]] = []
    channels = [ch for ch in plan.get("channels") or [] if isinstance(ch, dict)]
    busses = plan.get("busses") or {}
    if kind == "bus":
        for ch in channels:
            for send in ch.get("bus_sends") or []:
                if isinstance(send, dict) and send.get("bus") == key:
                    found.append(("channel", ch.get("name"), send.get("mode")))
        for other, entry in busses.items():
            for send in (entry.get("bus_sends") or []) if isinstance(entry, dict) else []:
                if isinstance(send, dict) and send.get("bus") == key:
                    found.append(("bus", other, send.get("mode")))
    elif kind == "main":
        for ch in channels:
            if any(isinstance(r, dict) and r.get("index") == index for r in ch.get("main_routes") or []):
                found.append(("channel", ch.get("name"), None))
        for other, entry in busses.items():
            if isinstance(entry, dict) and any(d.get("type") == "main" and d.get("index", 1) == index
                                               for d in _bus_destinations(entry)):
                found.append(("bus", other, None))
    else:
        order = {"channel": 0, "bus": 1, "main": 2}
        found = sorted(plan_compat.matrix_feeds(plan).get(key, []), key=lambda f: order[f[0]])
    return found


def _sources_cells(found) -> tuple[str, str]:
    taps = [t for _k, _n, t in found if t]
    common = max(sorted(set(taps)), key=taps.count) if taps else ""
    cells = [name if (t is None or t == common) else f"{name} ({t})" for _k, name, t in found]
    return ";".join(str(c) for c in cells), common


def _outputs_of(kind: str, entry: dict) -> list[dict]:
    if kind == "bus":
        out = []
        for d in _bus_destinations(entry):
            if d.get("type") == "dedicated_output":
                out.extend(plan_compat.output_patches(d))
        return out
    return plan_compat.output_patches(entry)


def bus_rows_from_plan(plan: dict) -> list[dict]:
    """The plan as the bus sheet would say it: one row per bus, Main and
    Matrix, every column but `notes` filled from the plan. Step 04 shows a
    blank cell's plan value beside it from these, and the overlay compares
    a filled cell with them. `fx` is what the plan inserts on it
    (`bus_presets.strip_inserts`: its own inserts, and a bus preset's)."""
    from atoo import bus_presets

    rows = []
    for kind, index, key, entry in _objects(plan):
        sources, tap = _sources_cells(_feeds(plan, kind, key, index))
        mono = entry.get("mono")
        inserts = [i for i in bus_presets.strip_inserts(entry) if i.get("model")]
        rows.append({
            "bus": label_of(kind, index),
            "name": "" if entry.get("name_on") == "none" else key,
            "key": key,
            "kind": kind,
            "role": entry.get("role") or "",
            "width": "" if mono is None else ("mono" if mono else "stereo"),
            "sources": sources,
            "tap": tap,
            "outputs": _socket_runs(_outputs_of(kind, entry)),
            "fx": "; ".join(i["model"] for i in inserts),
            "preset": entry.get("preset") or "",
            "dca": ";".join(entry.get("dca") or []),
            "mute_group": ";".join(entry.get("mute_group") or []),
            "label": entry.get("description") or "",
            "notes": "",
        })
    return rows


# ---------------------------------------------------------------------------
# Renaming, everywhere a name is a reference
# ---------------------------------------------------------------------------

def _rekey(mapping: dict, old: str, new: str) -> dict:
    return {(new if k == old else k): v for k, v in mapping.items()}


def _rename_bus(plan: dict, old: str, new: str) -> None:
    plan["busses"] = _rekey(plan.get("busses") or {}, old, new)
    for ch in plan.get("channels") or []:
        for send in ch.get("bus_sends") or []:
            if send.get("bus") == old:
                send["bus"] = new
    for entry in (plan.get("busses") or {}).values():
        for send in entry.get("bus_sends") or []:
            if send.get("bus") == old:
                send["bus"] = new
        for d in _bus_destinations(entry):
            if d.get("type") == "dedicated_output" and d.get("label") == old:
                d["label"] = new
    for entry in (plan.get("outputs") or {}).values():
        fed = entry.get("fed_by")
        if isinstance(fed, dict) and fed.get("type") == "bus" and fed.get("name") == old:
            fed["name"] = new


def _rename_output(plan: dict, old: str, new: str) -> None:
    plan["outputs"] = _rekey(plan.get("outputs") or {}, old, new)
    holders = [*(plan.get("channels") or []), *(plan.get("busses") or {}).values(),
               *(plan.get("outputs") or {}).values()]
    for holder in holders:
        for send in holder.get("matrix_sends") or []:
            if send.get("matrix") == old:
                send["matrix"] = new


def rename_in_sources(text: str, renamed: dict[str, str]) -> str:
    """A `sources` cell with each renamed name replaced, its `(pre)` kept."""
    if not renamed or not text:
        return text
    folded = {_norm(old): new for old, new in renamed.items()}
    parts = []
    changed = False
    for name, tap in parse_sources(text):
        new = folded.get(_norm(name))
        if new is not None:
            changed = True
            name = new
        parts.append(f"{name} ({tap})" if tap else name)
    return ";".join(parts) if changed else text


# ---------------------------------------------------------------------------
# The bus sheet onto the plan
# ---------------------------------------------------------------------------

class _Names:
    """What a `sources` cell may name, resolved to `(kind, key)`."""

    def __init__(self, plan: dict, categories: dict[str, str], renamed: dict[str, str]):
        self.plan = plan
        self.renamed = {_norm(k): v for k, v in renamed.items()}
        self.channels = [ch for ch in plan.get("channels") or [] if isinstance(ch, dict)]
        self.categories = categories

    def resolve(self, name: str, notes: "list[str] | None" = None) -> "list[tuple[str, str]] | None":
        if name.strip() == "*":
            return [("channel", ch.get("name")) for ch in self.channels]
        renamed = self.renamed.get(_norm(name))
        wanted = _norm(renamed or name)
        objects = [(kind, key) for kind, index, key, _entry in _objects(self.plan)
                   if wanted in (_norm(key), _norm(label_of(kind, index)))]
        if renamed is not None and objects:
            # The old name of a bus, Main or Matrix this Save renamed.
            return objects[:1]
        channel = next((ch for ch in self.channels if _norm(ch.get("name")) == wanted), None) \
            or next((ch for ch in self.channels
                     if wanted in (_norm((ch.get("source") or {}).get("input")),
                                   _norm((ch.get("source") or {}).get("pair_input")))), None)
        if channel is not None:
            if objects and notes is not None:
                kind, key = objects[0]
                index = (_find_key(self.plan, key) or (kind, 0))[1]
                line = (f"{name!r} names both a channel and {label_of(kind, index)}; in a "
                        f"sources cell it is read as the channel. Write {label_of(kind, index)} "
                        "for the other.")
                if line not in notes:
                    notes.append(line)
            return [("channel", channel.get("name"))]
        if objects:
            return objects[:1]
        members = [("channel", ch.get("name")) for ch in self.channels
                   if _norm(self.categories.get(ch.get("name"), "")) == wanted]
        return members or None


def _find_key(plan: dict, key: str) -> "tuple[str, int] | None":
    for kind, index, k, _entry in _objects(plan):
        if k == key:
            return kind, index
    return None


def _find(plan: dict, kind: str, index: int) -> "tuple[str, dict] | None":
    for k, i, key, entry in _objects(plan):
        if k == kind and i == index:
            return key, entry
    return None


def _capacity(kind: str) -> int:
    return facts.CAPACITY[_CAPACITY[kind]]


def _new_object(plan: dict, kind: str, index: int, name: str, sheet_label: str) -> str:
    key = name or label_of(kind, index)
    common = {"index": index, "fader": {"fader_db": None, "muted": None}, "description": None,
              "name_on": "strip" if name else "none",
              "provenance": f"added from {BUS_SHEET} ({sheet_label})"}
    if kind == "bus":
        plan.setdefault("busses", {})[key] = {
            **common, "destination": None, "destinations": [], "mono": None, "dca": [],
            "mute_group": [], "preset": None}
    else:
        entry = {**common, "kind": kind, "patch": None, "patches": []}
        if kind == "matrix":
            entry["fed_by"] = None
        plan.setdefault("outputs", {})[key] = entry
    return key


def _ensure_groups(plan: dict, section: str, names: list[str], row: str, column: str,
                   value: str, result: Result) -> bool:
    """Every DCA (or mute group) a cell names is one the plan has: a new name
    takes the lowest free index, at INFO. False, with a refusal, when the desk
    has no free one left."""
    groups = plan.setdefault(section, {})
    word = "DCA" if section == "dcas" else "mute group"
    for name in names:
        if name in groups:
            continue
        match = [k for k in groups if _norm(k) == _norm(name)]
        if match:
            continue
        taken = {e.get("index") for e in groups.values() if isinstance(e, dict)}
        free = [i for i in range(1, _GROUP_CAPACITY[section] + 1) if i not in taken]
        if not free:
            result.refusals.append(Refusal(
                BUS_SHEET if row.split()[0] in ("Bus", "Main", "Matrix") else INPUT_SHEET,
                row, column, value,
                f"the desk has {_GROUP_CAPACITY[section]} {word}s and every one is in use, so "
                f"there is none left for {name!r}"))
            return False
        groups[name] = {"index": free[0]}
        result.notes.append(f"{word} {name!r} is new to this plan ({row}'s {column}), so it "
                            f"takes {word} {free[0]}, the first free one.")
    return True


def _canonical_group_names(plan: dict, section: str, names: list[str]) -> list[str]:
    groups = plan.get(section) or {}
    out = []
    for name in names:
        match = [k for k in groups if _norm(k) == _norm(name)]
        out.append(match[0] if match else name)
    return out


def _list_group_names(plan: dict, section: str, names: list[str], result: Result) -> list[str]:
    """The input list's group names, as `reply_expand.apply_stated_columns`
    takes them in a build: a group the plan spells differently only in case
    or spacing is renamed to the list's spelling, at INFO."""
    from atoo.reply_expand import rename_group

    groups = plan.get(section) or {}
    word = "DCA" if section == "dcas" else "mute group"
    for name in names:
        if name in groups:
            continue
        match = [k for k in groups if _norm(k) == _norm(name)]
        if match:
            rename_group(plan, section, match[0], name)
            result.notes.append(f"{word} {match[0]!r} is named {name!r}, as the input list "
                                "spells it.")
    return list(names)


def _set_feeds(plan: dict, kind: str, key: str, index: int,
               wanted: dict[tuple[str, str], "str | None"]) -> None:
    """Make exactly `wanted` (`{(source kind, source key): tap}`) feed this
    object, on each source, leaving every other send as it is."""
    channels = {ch.get("name"): ch for ch in plan.get("channels") or [] if isinstance(ch, dict)}
    busses = plan.get("busses") or {}
    outputs = plan.get("outputs") or {}
    if kind == "bus":
        for name, ch in channels.items():
            _set_send(ch, "bus_sends", "bus", key, wanted, ("channel", name))
        for name, entry in busses.items():
            if name != key:
                _set_send(entry, "bus_sends", "bus", key, wanted, ("bus", name))
    elif kind == "main":
        for name, ch in channels.items():
            routes = [r for r in ch.get("main_routes") or [] if r.get("index") != index]
            if ("channel", name) in wanted:
                routes.append({"index": index})
                routes.sort(key=lambda r: r["index"])
            ch["main_routes"] = routes
        for name, entry in busses.items():
            dests = [d for d in _bus_destinations(entry)
                     if not (d.get("type") == "main" and d.get("index", 1) == index)]
            if ("bus", name) in wanted:
                dests.insert(0, {"type": "main", "index": index})
            entry["destinations"] = dests
            entry["destination"] = dests[0] if dests else None
    else:
        matrix = outputs[key]
        fed = matrix.get("fed_by")
        if isinstance(fed, dict):
            # Its one `fed_by` becomes a send on that source, so every feed
            # of this Matrix is in one place, with its tap.
            matrix["fed_by"] = None
            source = None
            if fed.get("type") == "bus" and fed.get("name") in busses:
                source = busses[fed["name"]]
            elif fed.get("type") == "main":
                source = next((e for e in outputs.values()
                               if e.get("kind") == "main" and e.get("index") == fed.get("index", 1)), None)
            if source is not None and not any(s.get("matrix") == key for s in source.get("matrix_sends") or []):
                source.setdefault("matrix_sends", []).append({"matrix": key, "mode": None,
                                                              "level_db": None})
        for name, ch in channels.items():
            _set_send(ch, "matrix_sends", "matrix", key, wanted, ("channel", name))
        for name, entry in busses.items():
            _set_send(entry, "matrix_sends", "matrix", key, wanted, ("bus", name))
        for name, entry in outputs.items():
            if entry.get("kind") == "main":
                _set_send(entry, "matrix_sends", "matrix", key, wanted, ("main", name))


def _set_send(holder: dict, field_name: str, target_key: str, target: str, wanted: dict,
              me: tuple[str, str]) -> None:
    sends = [s for s in holder.get(field_name) or [] if isinstance(s, dict)]
    mine = [s for s in sends if s.get(target_key) == target]
    rest = [s for s in sends if s.get(target_key) != target]
    if me in wanted:
        if mine:
            send = mine[0]
            if wanted[me] is not None:
                send["mode"] = wanted[me]
        else:
            send = {target_key: target, "mode": wanted[me], "level_db": None}
        rest.append(send)
    if rest or field_name in holder:
        holder[field_name] = rest


def overlay_busses(plan: dict, rows: list[dict], *, categories: "dict[str, str] | None" = None,
                   before: "list[dict] | None" = None, result: "Result | None" = None) -> Result:
    """`plan` with every filled cell of the bus sheet's `rows` carried out
    (`rows` are the sheet's rows as `{column: text}`). `before` is the sheet
    as it was, when the caller has it: a column the plan does not hold is
    said at INFO only when its cell changed. `categories` is each channel's
    input-list category, by channel name, for a `sources` cell that names
    one. Never raises; a cell that cannot work is a refusal."""
    if result is None:
        result = Result(plan=copy.deepcopy(plan))
    plan = result.plan
    plan.setdefault("busses", {})
    plan.setdefault("outputs", {})
    previous = {}
    for row in before or []:
        parsed = parse_label(row.get("bus"))
        if parsed and parsed[1] is not None:
            previous[parsed] = row

    resolved: list[tuple[dict, str, int, str]] = []   # (row, kind, index, sheet label)
    seen: dict[tuple[str, int], str] = {}
    for n, row in enumerate(rows, start=2):
        cell = (row.get("bus") or "").strip()
        sheet_row = cell or f"row {n}"
        parsed = parse_label(cell)
        if parsed is None:
            result.refusals.append(Refusal(BUS_SHEET, sheet_row, "bus", cell,
                                           "a row is a bus, Main or Matrix: write Bus 1-16, "
                                           "Main 1-4 or Matrix 1-8 (or Bus alone, for Atoo to "
                                           "pick the number)"))
            continue
        kind, index = parsed
        if index is None:
            if kind != "bus":
                result.refusals.append(Refusal(BUS_SHEET, sheet_row, "bus", cell,
                                               "only a bus's number can be left to Atoo; a Main "
                                               "or Matrix needs its number"))
                continue
            taken = {i for k, i, _key, _e in _objects(plan) if k == "bus"} | \
                    {i for (k, i) in seen if k == "bus"}
            free = [i for i in range(1, _capacity("bus") + 1) if i not in taken]
            if not free:
                result.refusals.append(Refusal(BUS_SHEET, sheet_row, "bus", cell,
                                               f"every one of the desk's {_capacity('bus')} buses "
                                               "is in use"))
                continue
            index = free[0]
            result.notes.append(f"{BUS_SHEET} row {n} says Bus with no number; it is Bus {index}, "
                                "the first free one.")
        if not 1 <= index <= _capacity(kind):
            result.refusals.append(Refusal(BUS_SHEET, sheet_row, "bus", cell,
                                           f"the desk has {label_of(kind, 1)}-{_capacity(kind)}, "
                                           f"so there is no {label_of(kind, index)}"))
            continue
        if (kind, index) in seen:
            result.refusals.append(Refusal(BUS_SHEET, sheet_row, "bus", cell,
                                           f"{label_of(kind, index)} has two rows; give each one "
                                           "row"))
            continue
        seen[(kind, index)] = sheet_row
        resolved.append((row, kind, index, label_of(kind, index)))

    # Names first, so a `sources` cell can say a new name.
    for row, kind, index, label in resolved:
        name = (row.get("name") or "").strip()
        found = _find(plan, kind, index)
        if found is None:
            if name and any(_norm(name) == _norm(k) for _k, _i, k, _e in _objects(plan)):
                result.refusals.append(Refusal(BUS_SHEET, label, "name", name,
                                               "another bus, Main or Matrix already has this "
                                               "name, and the plan names each one once"))
                continue
            _new_object(plan, kind, index, name, label)
            result.changes.append(f"{label} added")
            result.notes.append(f"{label} {name or ''} is a row of {BUS_SHEET} the plan did not "
                                "have, so it is added to the plan.".replace("  ", " "))
            continue
        key, entry = found
        if not name or name == key:
            if name and entry.get("name_on") == "none":
                entry["name_on"] = "strip"
            continue
        if len(name) > 16:
            result.refusals.append(Refusal(BUS_SHEET, label, "name", name,
                                           "a desk name is at most 16 characters"))
            continue
        if any(_norm(name) == _norm(k) and k != key for _k, _i, k, _e in _objects(plan)):
            result.refusals.append(Refusal(BUS_SHEET, label, "name", name,
                                           "another bus, Main or Matrix already has this name, "
                                           "and the plan names each one once"))
            continue
        (_rename_bus if kind == "bus" else _rename_output)(plan, key, name)
        found_entry = _find(plan, kind, index)[1]
        found_entry["name_on"] = "strip"
        result.renamed[key] = name
        if any(_norm(ch.get("name")) == _norm(name) for ch in plan.get("channels") or []):
            # A channel has this name too: the sheet's other rows say the
            # row's number, so their sources cells cannot read as the channel.
            result.spelled[key] = label
        result.changes.append(f"{label} renamed {name!r}")

    names = _Names(plan, categories or {}, result.renamed)
    for row, kind, index, label in resolved:
        found = _find(plan, kind, index)
        if found is None:
            continue
        key, entry = found
        now = next((r for r in bus_rows_from_plan(plan) if r["bus"] == label), {})
        was = previous.get((kind, index), {})

        def changed(column):
            return (row.get(column) or "").strip() != (was.get(column) or "").strip()

        role = (row.get("role") or "").strip().lower()
        if role and role != (entry.get("role") or ""):
            allowed = BUS_ROLES if kind == "bus" else OUTPUT_ROLES
            if role not in allowed:
                result.notes.append(f"{BUS_SHEET}, {label}, role {row.get('role')!r} is not one of "
                                    f"{', '.join(allowed)}, so it is read as 'other'.")
                role = "other"
            entry["role"] = role
            result.changes.append(f"{label} role {role}")

        width = (row.get("width") or "").strip().lower()
        if width:
            if width not in ("mono", "stereo"):
                result.refusals.append(Refusal(BUS_SHEET, label, "width", row.get("width", ""),
                                               "width is mono or stereo"))
            elif entry.get("mono") != (width == "mono"):
                entry["mono"] = width == "mono"
                result.changes.append(f"{label} {width}")

        outputs = (row.get("outputs") or "").strip()
        if outputs and _socket_set(outputs) != _socket_set(now.get("outputs")):
            runs, problem = parse_outputs(outputs)
            if problem:
                result.refusals.append(Refusal(BUS_SHEET, label, "outputs", outputs, problem))
            else:
                patches = _patches(runs, entry.get("mono") is True)
                if kind == "bus":
                    dests = [d for d in _bus_destinations(entry) if d.get("type") != "dedicated_output"]
                    dests.append({"type": "dedicated_output", "label": key,
                                  "patch": patches[0], "patches": patches})
                    entry["destinations"] = dests
                    entry["destination"] = dests[0]
                else:
                    entry["patch"] = patches[0]
                    entry["patches"] = patches
                result.changes.append(f"{label} to {_socket_runs(patches)}")

        for column, section in (("dca", "dcas"), ("mute_group", "mute_groups")):
            cell = (row.get(column) or "").strip()
            if not cell or _same_list(cell, now.get(column)):
                continue
            listed = split_list(cell)
            if not _ensure_groups(plan, section, listed, label, column, cell, result):
                continue
            entry[column] = _canonical_group_names(plan, section, listed)
            result.changes.append(f"{label} {column} {'; '.join(entry[column])}")

        label_cell = (row.get("label") or "").strip()
        if label_cell and label_cell != (entry.get("description") or ""):
            entry["description"] = label_cell
            result.changes.append(f"{label} label")

        preset = (row.get("preset") or "").strip()
        if preset and preset != (entry.get("preset") or ""):
            if kind != "bus":
                if changed("preset"):
                    result.notes.append(
                        f"{BUS_SHEET}, {label}, preset {preset!r}: the plan holds a preset for a "
                        "bus only, so the sheet keeps it and Apply leaves the desk's.")
            else:
                entry["preset"] = preset
                entry.pop("preset_values", None)
                result.changes.append(f"{label} preset {preset}")
                result.notes.append(
                    f"{label}'s preset is now {preset!r}: its values come from the preset library "
                    "at the next build (or `atoo presets --expand`); until then Apply writes "
                    "none of them, and gives a warning.")

        fx = (row.get("fx") or "").strip()
        # A blank cell keeps the plan's, as every column's does; one emptied
        # since the sheet was read takes the effects off.
        emptied = not fx and bool((was.get("fx") or "").strip()) and bool(now.get("fx"))
        if (fx or emptied) and not _same_list(fx, now.get("fx")):
            _overlay_fx(plan, kind, label, entry, fx, result)

        sources = (row.get("sources") or "").strip()
        if sources:
            _overlay_sources(plan, kind, index, key, label, row, now, names, result)
    return result


_BANK = {"bus": "bus", "main": "main", "matrix": "mtx"}


def _overlay_fx(plan: dict, kind: str, label: str, entry: dict, cell: str,
                result: Result) -> None:
    """The bus sheet's `fx` cell on a bus, Main or Matrix: the
    effects it inserts, by model, as the strip's own `inserts`. An effect
    the plan already inserts and the cell still names stays as it is, with
    its engine and parameters; one the cell no longer names comes off its
    insert point; one the cell adds goes on a free insert point, in an
    engine `fx_engines.allocate` gives it around every engine the plan
    already uses, with the parameters the desk gives the model. A model no
    engine offers, more effects than the strip has insert points, or no
    engine left is a refusal naming the cell, and nothing changes."""
    from atoo import bus_presets, fx_engines
    from atoo.presets import INSERT_POINT_NAMES

    bank = _BANK[kind]
    points = facts.INSERT_POINTS[bank]
    models = {m.casefold(): m for m in fx_engines.all_models() if fx_engines.is_known_model(m)}
    wanted = []
    for name in split_list(cell):
        model = models.get(name.casefold())
        if model is None:
            result.refusals.append(Refusal(BUS_SHEET, label, "fx", name,
                                           "no FX engine on the desk offers this effect; write "
                                           "the model as the desk names it (V-REV, ST-DL)"))
            return
        wanted.append(model)
    if len(wanted) > len(points):
        result.refusals.append(Refusal(BUS_SHEET, label, "fx", cell,
                                       f"a {label.split()[0]} has {len(points)} insert points "
                                       f"(pre and post), so it inserts {len(points)} effects at "
                                       f"most"))
        return
    current = [i for i in bus_presets.strip_inserts(entry) if i.get("model")]
    remaining = list(wanted)
    kept, removed = [], []
    for ins in current:
        if ins["model"] in remaining:
            remaining.remove(ins["model"])
            kept.append(ins)
        else:
            removed.append(ins)
    free = [p for p in points if p not in {i.get("point") for i in kept}]
    released = {i.get("engine") for i in removed}
    taken = {e: who for e, who in bus_presets.claimed_engines(plan).items() if e not in released}
    requests = [fx_engines.EngineRequest(key=n, owner=f"{label}'s {INSERT_POINT_NAMES[p]}",
                                         model=m, saved_engine=None)
                for n, (p, m) in enumerate(zip(free, remaining))]
    allocations = fx_engines.allocate(requests, taken)
    for request in requests:
        if allocations[request.key].engine is None:
            legal = fx_engines.engines_for(request.model)
            result.refusals.append(Refusal(
                BUS_SHEET, label, "fx", request.model,
                f"every engine that can hold {request.model} "
                f"(FX{fx_engines.engine_range_text(legal)}) is already in use"))
            return
    own = {i.get("point"): i for i in bus_presets.own_inserts(entry)}
    reused = {allocations[r.key].engine for r in requests}
    for ins in removed:
        point = ins.get("point")
        own[point] = {"point": point, "model": None}
        kept = isinstance(ins.get("engine"), int) and ins["engine"] not in reused
        result.notes.append(f"{label}: {ins['model']} comes off its {INSERT_POINT_NAMES[point]}"
                            + (f"; FX{ins['engine']} keeps the model, inserted nowhere."
                               if kept else "."))
    for request, point in zip(requests, free):
        engine = allocations[request.key].engine
        own[point] = {"point": point, "model": request.model, "engine": engine, "parameters": {}}
        result.notes.append(f"{label}: {request.model} goes on its {INSERT_POINT_NAMES[point]}, "
                            f"in FX{engine}, a free engine that can hold it; its "
                            f"parameters are left as the desk has them.")
    entry["inserts"] = [own[p] for p in points if p in own]
    result.changes.append(f"{label} fx {'; '.join(wanted) or 'none'}")


def _overlay_sources(plan, kind, index, key, label, row, now, names: _Names,
                     result: Result) -> None:
    tap_cell = (row.get("tap") or "").strip().lower()
    if tap_cell and tap_cell not in ("pre", "post"):
        result.refusals.append(Refusal(BUS_SHEET, label, "tap", row.get("tap", ""),
                                       "tap is pre or post"))
        return
    current = {(k, n): t for k, n, t in _feeds(plan, kind, key, index)}
    wanted: dict[tuple[str, str], "str | None"] = {}
    problems = 0
    for name, tap in parse_sources(row.get("sources")):
        hits = names.resolve(name, result.notes)
        if hits is None:
            result.refusals.append(Refusal(
                BUS_SHEET, label, "sources", name,
                "no channel, bus, Main or input-list category has this name"))
            problems += 1
            continue
        for hit in hits:
            source_kind, source_key = hit
            if source_kind == "matrix":
                result.refusals.append(Refusal(BUS_SHEET, label, "sources", name,
                                               "a Matrix feeds only its outputs, never another "
                                               "bus, Main or Matrix"))
                problems += 1
                continue
            if source_kind == "main" and kind != "matrix":
                result.refusals.append(Refusal(BUS_SHEET, label, "sources", name,
                                               f"a Main feeds only a Matrix, never a "
                                               f"{'bus' if kind == 'bus' else 'Main'}"))
                problems += 1
                continue
            if source_kind == "bus" and kind == "bus" and source_key == key:
                result.refusals.append(Refusal(BUS_SHEET, label, "sources", name,
                                               "a bus cannot feed itself"))
                problems += 1
                continue
            wanted[hit] = tap or (tap_cell or None)
    if problems:
        return
    if kind == "main":
        stated = sorted({t for t in wanted.values() if t})
        if stated and stated != ["post"]:
            result.notes.append(f"{BUS_SHEET}, {label}: the plan does not hold a tap for a route "
                                "to a Main, so a Main's routes keep the desk's.")
        wanted = {k: None for k in wanted}
    decided = []
    for hit, tap in list(wanted.items()):
        if tap is None and hit in current:
            wanted[hit] = current[hit]
        elif tap is None and kind != "main":
            wanted[hit] = "post"
            decided.append(hit[1])
    if wanted == current or (set(wanted) == set(current) and all(
            wanted[h] == current[h] or wanted[h] is None for h in wanted)):
        return
    _set_feeds(plan, kind, key, index, wanted)
    added = [n for (k, n) in wanted if (k, n) not in current]
    removed = [n for (k, n) in current if (k, n) not in wanted]
    retapped = [n for (k, n) in wanted if (k, n) in current and wanted[(k, n)] != current[(k, n)]]
    bits = []
    if added:
        bits.append("from " + ", ".join(added))
    if removed:
        bits.append("no longer from " + ", ".join(removed))
    if retapped:
        bits.append("tap changed for " + ", ".join(retapped))
    result.changes.append(f"{label} fed " + "; ".join(bits))
    if decided:
        result.notes.append(f"{BUS_SHEET}, {label}: no tap is stated for the new send(s) from "
                            f"{', '.join(decided)}, so they are post-fader.")


# ---------------------------------------------------------------------------
# The input list onto the plan
# ---------------------------------------------------------------------------

def _row_label(row: InputRow, n: int) -> str:
    return f"row {n} ({row.name})" if row.name else f"row {n}"


def _channel_at(plan: dict, bank: str, number: int) -> "dict | None":
    for ch in plan.get("channels") or []:
        if isinstance(ch, dict) and (ch.get("bank") or "ch") == bank and ch.get("channel") == number:
            return ch
    return None


def _chan_label(bank: str, number: int) -> str:
    return f"{'Aux ' if bank == 'aux' else 'CH '}{number}"


def overlay_inputs(plan: dict, before_text: str, after_text: str,
                   lines: list["int | None"], *, result: "Result | None" = None) -> Result:
    """`plan` with an edit of the input list carried out. `before_text` and
    `after_text` are the file before and after the Save; `lines[j]` is which
    row of the old file the new file's row `j` was (None for a new row), as
    the Save sent them. An input list that does not load leaves the plan as
    it is, with a note."""
    if result is None:
        result = Result(plan=copy.deepcopy(plan))
    plan = result.plan
    try:
        old_rows = parse_input_list(before_text, include_skipped=True)
    except InputListError:
        old_rows = []
    try:
        new_rows = parse_input_list(after_text, include_skipped=True)
    except InputListError as exc:
        result.notes.append(f"The plan was not updated from {INPUT_SHEET}: it does not load as it "
                            f"stands ({exc}).")
        return result
    if len(new_rows) != len(lines):
        lines = [None] * len(new_rows)
    channels = [ch for ch in plan.get("channels") or [] if isinstance(ch, dict)]
    included_old = [r for r in old_rows if not r.skipped]
    owner: dict[int, tuple[dict, int]] = {}   # old row index -> (channel, position in pair)
    for ch in channels:
        for position, fed in enumerate(rows_feeding(ch, included_old)):
            idx = next((i for i, r in enumerate(old_rows) if r is fed), None)
            if idx is not None:
                owner[idx] = (ch, position)

    kept_old = {line for line in lines if line is not None}
    removed_channels: list[dict] = []
    for i, row in enumerate(old_rows):
        if i in kept_old or i not in owner:
            continue
        ch, position = owner[i]
        _drop_input(plan, ch, position, row, result, removed_channels)

    for j, new in enumerate(new_rows):
        n = j + 2
        line = lines[j]
        old = old_rows[line] if line is not None and 0 <= line < len(old_rows) else None
        if old is not None and line in owner:
            ch, position = owner[line]
            if ch in removed_channels:
                continue
            if new.skipped and not old.skipped:
                _drop_input(plan, ch, position, old, result, removed_channels)
                continue
            _edit_input(plan, ch, position, old, new, n, result)
        elif not new.skipped:
            _add_input(plan, new, n, result)

    plan["channels"] = [ch for ch in plan.get("channels") or [] if ch not in removed_channels]
    taken: dict[tuple[str, int], str] = {}
    for ch in plan["channels"]:
        spot = ((ch.get("bank") or "ch"), ch.get("channel"))
        if spot in taken:
            result.refusals.append(Refusal(
                INPUT_SHEET, f"{ch.get('name')}", "channel", str(ch.get("channel")),
                f"{_chan_label(*spot)} would hold both {taken[spot]!r} and {ch.get('name')!r}; "
                "a channel holds one input, or two rows of one stereo pair"))
        taken[spot] = ch.get("name")
    return result


def _drop_input(plan, ch, position, row, result, removed_channels) -> None:
    source = ch.setdefault("source", {})
    label = _chan_label(ch.get("bank") or "ch", ch.get("channel"))
    if source.get("stereo"):
        patch = ch.get("patch") or {}
        sockets = list(patch.get("sockets") or [])
        keep = 1 - position
        if keep < len(sockets):
            patch["sockets"] = [sockets[keep]]
        if position == 0:
            source["input"] = source.get("pair_input") or source.get("input")
        source["stereo"] = False
        source.pop("pair_input", None)
        result.changes.append(f"{label} mono (row {row.name!r} removed)")
        result.notes.append(f"{row.name!r} is no longer on the input list, so {label} "
                            f"{ch.get('name')!r} is mono, on its other input.")
        return
    removed_channels.append(ch)
    result.changes.append(f"{label} {ch.get('name')!r} removed")
    result.notes.append(f"{row.name!r} is no longer on the input list, so {label} "
                        f"{ch.get('name')!r} is taken out of the plan; a full Apply leaves the "
                        "strip unpatched.")


def _edit_input(plan, ch, position, old: InputRow, new: InputRow, n: int, result: Result) -> None:
    source = ch.setdefault("source", {})
    bank = ch.get("bank") or "ch"
    label = _chan_label(bank, ch.get("channel"))
    where = _row_label(new, n)
    if new.name != old.name:
        if position == 0:
            if ch.get("name") in (old.name, source.get("input")) or not source.get("stereo"):
                result.renamed[ch.get("name")] = new.name
                ch["name"] = new.name
            source["input"] = new.name
        else:
            source["pair_input"] = new.name
        result.changes.append(f"{label} input {old.name!r} renamed {new.name!r}")
    if new.patch and new.patch != old.patch:
        parsed = parse_socket_spec(new.patch)
        if parsed is None:
            result.refusals.append(Refusal(INPUT_SHEET, where, "patch", new.patch,
                                           "not a socket: write a group and a number, such as "
                                           "LCL 3 or AES50-A 12"))
        else:
            group, number = parsed
            patch = ch.setdefault("patch", {"group": group, "sockets": [], "stated": True})
            sockets = list(patch.get("sockets") or [])
            while len(sockets) <= position:
                sockets.append(number)
            sockets[position] = number
            patch["group"] = group
            patch["sockets"] = sockets
            patch["stated"] = True
            result.changes.append(f"{label} patched from {format_socket(group, number)}")
    if position == 0:
        if new.type != old.type:
            source["type"] = new.type
            result.changes.append(f"{label} type {new.type}")
        if new.model != old.model:
            source["model"] = new.model or None
            result.changes.append(f"{label} model {new.model or 'none'}")
    if new.phantom != old.phantom:
        source["phantom"] = new.phantom
        result.changes.append(f"{label} phantom {'on' if new.phantom else 'off'}")
    if new.channel and new.channel != old.channel and new.channel != (bank, ch.get("channel")):
        to_bank, to_number = new.channel
        if source.get("stereo") and position == 1:
            result.refusals.append(Refusal(
                INPUT_SHEET, where, "channel", _chan_label(to_bank, to_number),
                f"this row is the second input of {label}'s stereo pair; move the pair by its "
                "first row"))
        else:
            ch["bank"], ch["channel"] = to_bank, to_number
            result.changes.append(f"{label} moved to {_chan_label(to_bank, to_number)}")
    for column, section, cells in (("dca", "dcas", new.dca), ("mute_group", "mute_groups",
                                                              new.mute_group)):
        if tuple(cells) == tuple(getattr(old, column)):
            continue
        if not _ensure_groups(plan, section, list(cells), where, column, "; ".join(cells), result):
            continue
        ch[column] = _list_group_names(plan, section, list(cells), result)
        result.changes.append(f"{label} {column} {'; '.join(ch[column]) or 'none'}")
    if new.category != old.category:
        result.uncarried.append(f"{where} category")
        result.notes.append(f"{INPUT_SHEET}, {where}, category {new.category!r}: the plan has no "
                            "category of its own; the next build reads it (color, DCAs by the "
                            "conventions).")
    if new.preset != old.preset:
        result.uncarried.append(f"{where} preset")
        result.notes.append(f"{INPUT_SHEET}, {where}, preset {new.preset!r}: a preset's values come "
                            "from the preset library at the next build, so the plan keeps "
                            "its current one until then.")
    if new.notes != old.notes:
        result.uncarried.append(f"{where} notes")
    if new.order != old.order and not (new.skipped or old.skipped):
        result.uncarried.append(f"{where} order")


def _add_input(plan: dict, new: InputRow, n: int, result: Result) -> None:
    where = _row_label(new, n)
    if new.channel is None:
        result.unplaced.append(new.name)
        return
    bank, number = new.channel
    held = _channel_at(plan, bank, number)
    parsed = parse_socket_spec(new.patch) if new.patch else None
    if new.patch and parsed is None:
        result.refusals.append(Refusal(INPUT_SHEET, where, "patch", new.patch,
                                       "not a socket: write a group and a number, such as "
                                       "LCL 3 or AES50-A 12"))
        return
    if held is not None:
        source = held.get("source") or {}
        patch = held.get("patch") or {}
        sockets = list(patch.get("sockets") or [])
        if source.get("stereo") or parsed is None or len(sockets) != 1 \
                or parsed != (patch.get("group"), sockets[0] + 1):
            result.refusals.append(Refusal(
                INPUT_SHEET, where, "channel", _chan_label(bank, number),
                f"{_chan_label(bank, number)} already holds {held.get('name')!r}; a second row on "
                "a channel makes it a stereo pair, which needs the socket after its first "
                f"({format_socket(patch.get('group') or '?', (sockets or [0])[0] + 1)})"))
            return
        source["stereo"] = True
        source["pair_input"] = new.name
        patch["sockets"] = sockets + [parsed[1]]
        result.changes.append(f"{_chan_label(bank, number)} stereo, with {new.name!r}")
        return
    ch = {
        "channel": number, "bank": bank, "name": new.name,
        "source": {"input": new.name, "type": new.type, "model": new.model or None,
                   "stereo": False, "phantom": new.phantom},
        "patch": ({"group": parsed[0], "sockets": [parsed[1]], "stated": True} if parsed
                  else None),
        "processing": {"hpf_hz": None, "preset": None},
        "fader": {"fader_db": None, "muted": None},
        "dca": [], "mute_group": [], "bus_sends": [], "main_routes": [],
        "provenance": {"channel": f"added from {INPUT_SHEET} ({where})"},
    }
    for column, section, cells in (("dca", "dcas", new.dca), ("mute_group", "mute_groups",
                                                              new.mute_group)):
        if cells and _ensure_groups(plan, section, list(cells), where, column, "; ".join(cells),
                                    result):
            ch[column] = _list_group_names(plan, section, list(cells), result)
    plan.setdefault("channels", []).append(ch)
    plan["channels"].sort(key=lambda c: ((c.get("bank") or "ch") != "ch", c.get("channel") or 0))
    result.changes.append(f"{_chan_label(bank, number)} {new.name!r} added")
    if parsed is None:
        result.notes.append(f"{new.name!r} is on {_chan_label(bank, number)} with no patch: the "
                            "next build patches it, or fill its patch cell.")


def categories_by_channel(plan: dict, input_text: str) -> dict[str, str]:
    """Each plan channel's input-list category, by channel name, for a
    `sources` cell that names a category."""
    try:
        rows = parse_input_list(input_text)
    except InputListError:
        return {}
    out = {}
    for ch in plan.get("channels") or []:
        fed = rows_feeding(ch, rows) if isinstance(ch, dict) else []
        if fed:
            out[ch.get("name")] = fed[0].category
    return out


# ---------------------------------------------------------------------------
# What cannot physically work: verify's own ERRORs, new since the edit
# ---------------------------------------------------------------------------

#: Which column a verify ERROR is about, by its code.
_CODE_COLUMN = (("output.", "outputs"), ("bus.", "outputs"), ("patch.", "patch"),
                ("alt-patch.", "patch"), ("strip.", "channel"))
_WHERE = re.compile(r"^(?P<section>channels|busses|outputs)\[(?P<name>[^\]]*)\]")
# A plan path inside a finding's text (`busses[Speakers].destinations[1]`).
_PLAN_PATH = re.compile(r"\b(?P<section>channels|busses|outputs)\[(?P<name>[^\]]*)\]"
                        r"(?P<rest>(?:\.\w+(?:\[\d+\])?)*)")


def _as_sheet_says(message: str, rows: dict) -> str:
    """`message` with each plan path it names spelled as the sheets name the
    row: `busses[Speakers].destinations[1]` -> `Bus 10 "Speakers", outputs`,
    `channels[Kick]` -> `CH 9 (Kick)`. A path no row has is left as it is."""
    def spell(m):
        found = rows.get((m.group("section"), m.group("name")))
        if found is None:
            return m.group(0)
        label = found[1] if found[0] == INPUT_SHEET else f'{found[1]} "{m.group("name")}"'
        rest = m.group("rest") or ""
        if rest.startswith((".destinations", ".patch", ".sockets")):
            label += ", outputs"
        elif rest.startswith((".sources", ".bus_sends", ".matrix_sends", ".fed_by")):
            label += ", sources"
        return label
    return _PLAN_PATH.sub(spell, message)


def refuse_new_errors(before: dict, result: Result, *, console_model: "str | None" = None) -> Result:
    """Every ERROR `verify_plan` finds in the edited plan that the plan did
    not already have, as a refusal naming the row it is about: a socket the
    desk does not have, a stereo pair it cannot form, two objects on one
    socket. An ERROR the plan had before the edit is not the edit's, and is
    left to the Findings panel."""
    from atoo import verify_plan

    def errors(plan):
        return verify_plan.verify_plan(plan, console_model=console_model).errors

    old = {(f.code, f.where, f.message) for f in errors(before)}
    rows = {}
    for kind, index, key, _entry in _objects(result.plan):
        rows[("busses" if kind == "bus" else "outputs", key)] = (BUS_SHEET, label_of(kind, index))
    for ch in result.plan.get("channels") or []:
        if isinstance(ch, dict):
            rows[("channels", ch.get("name"))] = (
                INPUT_SHEET, f"{_chan_label(ch.get('bank') or 'ch', ch.get('channel'))} "
                             f"({(ch.get('source') or {}).get('input') or ch.get('name')})")
    for finding in errors(result.plan):
        if (finding.code, finding.where, finding.message) in old:
            continue
        m = _WHERE.match(finding.where or "")
        sheet, row = rows.get((m.group("section"), m.group("name")), (BUS_SHEET, finding.where)) \
            if m else ("plan", finding.where or "plan")
        column = next((col for prefix, col in _CODE_COLUMN if finding.code.startswith(prefix)), "")
        if sheet == BUS_SHEET and column in ("patch", "channel"):
            column = "outputs" if column == "patch" else ""
        result.refusals.append(Refusal(sheet, row, column, "",
                                       f"{_as_sheet_says(finding.message, rows)} ({finding.code})"))
    return result


# ---------------------------------------------------------------------------
# What a Save leaves for Apply: the desk writes it changed
# ---------------------------------------------------------------------------
#
# A structural cell (a name, a socket, a source, a width) changes what Apply
# writes; an annotation (role, label, notes) changes nothing on the desk. A
# Save records the writes it changed, with the cells that asked for them, at
# `meta.sheet_pending`, and Watch's CV023 says "Sheet differs from desk" for
# each one the desk does not have yet. Watch never writes: Apply does.

def _cell(sheet: str, row: str, column: str, value: str) -> str:
    return f"{sheet}, {row}, {column}: {value}" if value else f"{sheet}, {row}, {column} emptied"


def bus_cells(before_rows: list[dict], after_rows: list[dict], plan: dict) -> dict[str, list[str]]:
    """The bus sheet's changed cells, by the label Apply's write targets give
    the object (`bus 9 (Presentr)`, `output Main PA (matrix 1)`)."""
    was = {r.get("bus"): r for r in before_rows}
    out: dict[str, list[str]] = {}
    for row in after_rows:
        parsed = parse_label(row.get("bus"))
        if parsed is None or parsed[1] is None:
            continue
        kind, index = parsed
        found = _find(plan, kind, index)
        if found is None:
            continue
        key, _entry = found
        old = was.get(row.get("bus"), {})
        name = (row.get("name") or "").strip()
        sheet_row = f'{label_of(kind, index)} "{name}"' if name else label_of(kind, index)
        cells = [_cell(BUS_SHEET, sheet_row, column, (row.get(column) or "").strip())
                 for column in BUS_COLUMNS[1:]
                 if (row.get(column) or "").strip() != (old.get(column) or "").strip()]
        if cells:
            target = (f"bus {index} ({key})" if kind == "bus"
                      else f"output {key} ({kind} {index})")
            out.setdefault(target, []).extend(cells)
    return out


def input_cells(before_text: str, after_text: str, lines: list, plan: dict) -> dict[str, list[str]]:
    """The input list's changed cells, by the label Apply's write targets
    give the channel each row is on (`ch 9 (Kick In)`)."""
    try:
        old_rows = parse_input_list(before_text, include_skipped=True)
        new_rows = parse_input_list(after_text, include_skipped=True)
    except InputListError:
        return {}
    columns = ("channel", "patch", "name", "category", "type", "model", "phantom", "preset",
               "dca", "mute_group", "notes")
    out: dict[str, list[str]] = {}
    for j, new in enumerate(new_rows):
        line = lines[j] if j < len(lines) else None
        old = old_rows[line] if line is not None and 0 <= line < len(old_rows) else None

        def text(row, column):
            value = getattr(row, column)
            if column == "channel":
                return "" if value is None else _chan_label(*value).replace("CH ", "")
            if isinstance(value, tuple):
                return "; ".join(value)
            if isinstance(value, bool):
                return "TRUE" if value else "FALSE"
            return str(value or "")

        cells = [_cell(INPUT_SHEET, new.name, column, text(new, column)) for column in columns
                 if old is None or text(new, column) != text(old, column)]
        if not cells:
            continue
        for ch in plan.get("channels") or []:
            fed = rows_feeding(ch, [new]) if isinstance(ch, dict) else []
            if fed:
                bank = ch.get("bank") or "ch"
                out.setdefault(f"{bank} {ch.get('channel')} ({ch.get('name')})", []).extend(cells)
                break
    return out


def pending_writes(before: dict, after: dict, cells: dict[str, list[str]],
                   pending: "list[dict] | None" = None) -> list[dict]:
    """`meta.sheet_pending` after a Save: the earlier entries, with every
    write Apply would now make that the plan before the Save did not --
    another value at an address, or a new address -- grouped by the object
    it is on and carrying the cells that asked for it. An object no changed
    cell names (a channel's send, changed by a bus's `sources`) carries each
    `sources` or `tap` cell of the Save (every cell, when none changed)."""
    from atoo.apply import _build_write_targets

    def targets(plan):
        out = {}
        for target in _build_write_targets(plan, True)[0]:
            try:
                value = target.compute_value("")
            except Exception:  # noqa: BLE001 -- a value that needs the desk's
                continue
            out[target.address] = (target, value)
        return out

    old, new = targets(before), targets(after)
    every = [c for group in cells.values() for c in group]
    # A write on an object no changed cell names is a send or a route that a
    # row's `sources` (or `tap`) moved: those are the cells that asked for it.
    routing = [c for c in every if ", sources:" in c or ", tap:" in c] or every
    groups: dict[str, dict] = {}
    for entry in pending or []:
        groups[entry["object"]] = {**entry, "writes": list(entry.get("writes") or [])}
    for address, (target, value) in new.items():
        if address in old and old[address][1] == value:
            continue
        label = target.description.split(":", 1)[0].strip()
        group = groups.setdefault(label, {"object": label, "cells": [], "writes": []})
        for cell in cells.get(label) or routing:
            if cell not in group["cells"]:
                group["cells"].append(cell)
        group["writes"] = [w for w in group["writes"] if w["address"] != address]
        group["writes"].append({"address": address, "type": target.value_type,
                                "value": value, "what": target.description})
    # An earlier write the plan no longer makes (an edit undone) waits for
    # nothing: Apply would not write it.
    for group in groups.values():
        group["writes"] = [w for w in group["writes"]
                           if w["address"] in new and new[w["address"]][1] == w["value"]]
    return [g for g in groups.values() if g["writes"]]
