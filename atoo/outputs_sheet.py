"""`outputs.csv`: one row per output socket and the source that feeds it, in
the desk's own words.

The desk patches an output socket to one of 18 source groups and a number
(`/io/out/{group}/{n}/grp` and `/in`): an input socket (`LCL 3`,
`AES50-A 1`, `MOD 12`), a user signal or patch (`USR 3`), the oscillator,
a bus, a Main or a Matrix, a send or the monitor. Nothing here invents a
word the desk does not have: a split or a recording feed is a socket fed
straight from an input socket, and a processed feed is a `USR` slot.

The file has three columns, `output`, `source` and `notes`, and **one row
per socket**: no ranges, since sockets fed in order are a coincidence, not a
rule. The table in Build's step 04 shows a run of them compactly.

It holds **every output socket the plan patches** (answer A):
those fed straight from a source (`direct_outputs`) and those a bus, a Main
or a Matrix feeds (`LCL 1 / Bus 9 L`), so one place says what each jack
carries. The plan keeps an object's sockets on the object, as its `patches`
(position 0 its L, position 1 its R); a socket the object's patches cannot
hold -- its R alone, or an object the plan does not have -- is a
`direct_outputs` entry with the object's slot, which Apply writes as it is
(`place`). `busses.csv`'s `outputs` column says the same sockets, worked out
from the plan: this file is where a socket's source is kept, and a build does
not lay that column on when the show has this file.

* **Capture** writes it from the desk (`rows_from_plan`).
* **Build** lays it on the plan the model made: a filled row wins over the
  conventions, `OFF` disconnects, a blank source is left to the conventions
  (`overlay(..., complete=False)`).
* **A Save** in step 04 lays it on whole: the sheet is then the complete
  list, so a socket it no longer has comes out of the plan
  (`overlay(..., complete=True)`).

What cannot physically work is refused, naming the row, and nothing is
written: a cell that is no socket or no source, a socket listed twice, and
every new ERROR `verify_plan` finds in the edited plan about a socket (one
the desk does not have, one something else the plan routes also claims, a
source past its group's end).
"""

from __future__ import annotations

import copy
import csv
import io
import re

from atoo import console_facts as facts
from atoo.input_list import format_socket, parse_socket_spec
from atoo.sheets import Refusal, Result

OUTPUT_SHEET = "outputs.csv"
COLUMNS = ("output", "source", "notes")

#: The order the desk lists its output groups in, so a sheet reads as the
#: desk's routing page does.
OUTPUT_GROUP_ORDER = ("LCL", "AUX", "A", "B", "C", "SC", "USB", "CRD", "MOD", "AES", "REC")

#: A bus, Main or Matrix as an output's source: the desk lists each by its
#: object and side, and the wire carries a slot (`2N - 1` for L, `2N` for R).
_OBJECT_GROUPS = {"BUS": "Bus", "MAIN": "Main", "MTX": "Matrix"}
_OBJECT_WORDS = {"bus": "BUS", "main": "MAIN", "matrix": "MTX", "mtx": "MTX", "mx": "MTX"}
_OBJECT_CAPACITY = {"BUS": facts.CAPACITY["bus"], "MAIN": facts.CAPACITY["main"],
                    "MTX": facts.CAPACITY["mtx"]}
_OBJECT_RE = re.compile(r"^\s*(?P<kind>bus|main|matrix|mtx|mx)\s*(?P<n>\d+)\s*(?P<side>[LR])\s*$",
                        re.IGNORECASE)
#: Source groups an input list never names, written by their own token.
_OWN_TOKEN = re.compile(r"^\s*(?P<group>MON|SEND|OSC|REC)\s*(?P<n>\d+)\s*$", re.IGNORECASE)
#: The desk's word for no source.
OFF = "OFF"


def parse_output(text) -> "tuple[str, int] | None":
    """`USB 5` -> `("USB", 5)`, `AES50-B 3` -> `("B", 3)`, `REC 2`; None
    for anything that is no output group and number. Whether the socket
    exists on this desk is verify's to say."""
    text = str(text or "")
    m = _OWN_TOKEN.match(text)
    if m:
        group = m.group("group").upper()
        return (group, int(m.group("n"))) if group in facts.OUTPUT_SOCKETS else None
    parsed = parse_socket_spec(text)
    if parsed is None or parsed[0] not in facts.OUTPUT_SOCKETS:
        return None
    return parsed


def format_output(group: str, n: int) -> str:
    return format_socket(group, n)


def parse_source(text) -> "tuple[tuple[str, int] | str | None, str | None]":
    """A `source` cell as the desk's pair: `(("A", 1), None)` for
    `AES50-A 1`, `(("BUS", 17), None)` for `Bus 9 L`, `(OFF, None)` for
    `OFF`, `(None, None)` for a blank cell, and `(None, reason)` for one
    that is no source the desk's output routing offers."""
    raw = str(text or "").strip()
    if not raw:
        return None, None
    if raw.upper() == OFF:
        return OFF, None
    m = _OBJECT_RE.match(raw)
    if m:
        group = _OBJECT_WORDS[m.group("kind").lower()]
        n = int(m.group("n"))
        if not 1 <= n <= _OBJECT_CAPACITY[group]:
            return None, (f"{raw!r}: the desk has {_OBJECT_GROUPS[group]} 1-"
                          f"{_OBJECT_CAPACITY[group]}")
        return (group, 2 * n - (1 if m.group("side").upper() == "L" else 0)), None
    m = _OWN_TOKEN.match(raw)
    if m and m.group("group").upper() != "REC":
        return (m.group("group").upper(), int(m.group("n"))), None
    parsed = parse_socket_spec(raw)
    if parsed is not None and parsed[0] in facts.OUTPUT_SOURCE_GROUPS:
        return parsed, None
    return None, (f"{raw!r} is not a source the desk's output routing offers: write an input "
                  "socket (AES50-A 1, LCL 3, MOD 12), USR n, OSC n, MON n, SEND n, Bus n L, "
                  "Main n R, Matrix n L, or OFF")


def source_words(group: str, index: int) -> str:
    """The desk's pair as the sheet writes it: `("A", 1)` -> `AES50-A 1`,
    `("BUS", 17)` -> `Bus 9 L`, `("MON", 2)` -> `MON 2`."""
    if group in _OBJECT_GROUPS:
        return f"{_OBJECT_GROUPS[group]} {(index + 1) // 2} {'L' if index % 2 else 'R'}"
    return format_socket(group, index)


def socket_order(group: str, n: int) -> tuple:
    return (OUTPUT_GROUP_ORDER.index(group) if group in OUTPUT_GROUP_ORDER else len(
        OUTPUT_GROUP_ORDER), group, n)


def _objects(plan: dict) -> dict[tuple[str, int], tuple[str, str, dict]]:
    """`{("BUS", 9): ("busses", key, entry), ("MAIN", 1): ("outputs", ...)}`:
    every bus, Main and Matrix the plan has, by the desk's group and number."""
    found: dict[tuple[str, int], tuple[str, str, dict]] = {}
    for key, entry in (plan.get("busses") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("index"), int):
            found[("BUS", entry["index"])] = ("busses", key, entry)
    for key, entry in (plan.get("outputs") or {}).items():
        group = {"main": "MAIN", "matrix": "MTX"}.get(
            entry.get("kind") if isinstance(entry, dict) else None)
        if group and isinstance(entry.get("index"), int):
            found[(group, entry["index"])] = ("outputs", key, entry)
    return found


def _patches_of(section: str, entry: dict) -> list[dict]:
    from atoo import plan_compat

    if section == "outputs":
        return plan_compat.output_patches(entry)
    destinations = entry.get("destinations") or (
        [entry["destination"]] if isinstance(entry.get("destination"), dict) else [])
    return [p for d in destinations if isinstance(d, dict) and d.get("type") == "dedicated_output"
            for p in plan_compat.output_patches(d)]


def _patch_sources(group: str, index: int, patches: list[dict]) -> dict:
    """An object's patches as `{socket: (group, slot)}`: position 0 of a patch
    is the object's L (`2N - 1`), position 1 its R, as Apply writes them
    (`apply._output_slot`)."""
    found = {}
    for patch in patches:
        if not isinstance(patch.get("group"), str):
            continue
        for position, n in enumerate(patch.get("sockets") or []):
            if isinstance(n, int) and not isinstance(n, bool):
                found[(patch["group"], n)] = (group, 2 * index - 1 + position)
    return found


def output_sources(plan: dict) -> dict[tuple[str, int], tuple[str, int]]:
    """Every output socket the plan patches and the desk's source for it:
    each bus's, Main's and Matrix's patches, then `direct_outputs`."""
    from atoo.apply import direct_output_sources

    found: dict[tuple[str, int], tuple[str, int]] = {}
    for (group, index), (section, _key, entry) in _objects(plan).items():
        found.update(_patch_sources(group, index, _patches_of(section, entry)))
    found.update(direct_output_sources(plan))
    return found


def rows_from_plan(plan: dict) -> list[dict[str, str]]:
    """The sheet as the plan has it: one row per output socket it patches,
    in the desk's output order."""
    found = output_sources(plan)
    return [{"output": format_output(group, n), "source": source_words(*found[(group, n)]),
             "notes": ""}
            for group, n in sorted(found, key=lambda key: socket_order(*key))]


def display(plan: dict) -> dict:
    """What Build 04's Outputs table draws beside a source, read from the plan:

    - `sockets`: each input socket's colour on the desk, by its words
      (`{"AES50-A 1": "navy"}`): the capture's reading (`meta.socket_colours`),
      else the colour of a channel patched from it, which Apply writes there;
    - `objects`: each bus's, Main's and Matrix's colour and name
      (`{"Bus 9": {"colour": "pink", "name": "Presentr"}}`).

    Colours are the desk's names, lower case; none where the plan states
    none."""
    from atoo.apply import bus_col

    def name(index) -> "str | None":
        found = facts.COLOUR_NAMES.get(index) if isinstance(index, int) else None
        return found.lower() if found else None

    sockets: dict[str, str] = {}
    for channel in plan.get("channels") or []:
        if not isinstance(channel, dict):
            continue
        col = channel.get("col")
        colour = name(col if isinstance(col, int) else facts.colour_index(channel.get("color")))
        patch = channel.get("patch") or {}
        if colour and isinstance(patch.get("group"), str):
            for n in patch.get("sockets") or []:
                if isinstance(n, int):
                    sockets.setdefault(format_socket(patch["group"], n), colour)
    captured = ((plan.get("meta") or {}).get("socket_colours") or {})
    for words, index in captured.items():
        if name(index):
            sockets[words] = name(index)
    objects = {}
    for (group, index), (_section, key, entry) in _objects(plan).items():
        objects[f"{_OBJECT_GROUPS[group]} {index}"] = {"colour": name(bus_col(entry)), "name": key}
    return {"sockets": sockets, "objects": objects}


def runs(plan: dict) -> list[tuple[str, str, int]]:
    """The plan's `direct_outputs` as runs, in the desk's output order:
    `[("AES50-B 1-12", "AES50-A 1-12", 12), ("AUX 3", "SEND 19", 1)]`. A run
    is consecutive sockets of one output group fed by consecutive numbers of
    one source group; a bus's, Main's or Matrix's run stays on one object
    (`Bus 9 L-R`). For a summary only: the sheet itself has one row per
    socket."""
    from atoo.apply import direct_output_sources

    found = direct_output_sources(plan)
    groups: list[list[tuple[tuple[str, int], tuple[str, int]]]] = []
    for socket in sorted(found, key=lambda key: socket_order(*key)):
        source = found[socket]
        if groups:
            (last_out, last_src) = groups[-1][-1]
            if (socket[0] == last_out[0] and socket[1] == last_out[1] + 1
                    and source[0] == last_src[0] and source[1] == last_src[1] + 1
                    and (source[0] not in _OBJECT_GROUPS
                         or (source[1] + 1) // 2 == (last_src[1] + 1) // 2)):
                groups[-1].append((socket, source))
                continue
        groups.append([(socket, source)])
    out = []
    for run in groups:
        (first_out, first_src), (last_out, last_src) = run[0], run[-1]
        if len(run) == 1:
            out.append((format_output(*first_out), source_words(*first_src), 1))
            continue
        if first_src[0] in _OBJECT_GROUPS:
            src = f"{_OBJECT_GROUPS[first_src[0]]} {(first_src[1] + 1) // 2} L-R"
        else:
            src = f"{source_words(*first_src)}-{last_src[1]}"
        out.append((f"{format_output(*first_out)}-{last_out[1]}", src, len(run)))
    return out


def summary_line(plan: dict) -> "str | None":
    """One line for a build's or a capture's output: `Direct outputs: 24
    socket(s) fed straight from a source (AES50-B 1-12, USB 1-12)`, the
    sockets as runs whatever feeds them. None when the plan has none."""
    from atoo.apply import direct_output_sources

    sockets = sorted(direct_output_sources(plan), key=lambda key: socket_order(*key))
    if not sockets:
        return None
    spans: list[list] = []
    for group, n in sockets:
        if spans and spans[-1][0] == group and spans[-1][2] == n - 1:
            spans[-1][2] = n
        else:
            spans.append([group, n, n])
    words = ", ".join(format_output(g, a) if a == b else f"{format_output(g, a)}-{b}"
                      for g, a, b in spans)
    return f"Direct outputs: {len(sockets)} socket(s) fed straight from a source ({words})"


def csv_text(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in COLUMNS})
    return out.getvalue()


def read_rows(text: str) -> list[dict[str, str]]:
    """The file's rows as `{column: cell}`; an unknown column is kept, and
    ignored."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            for row in reader]


def _entries(direct: dict) -> list[dict]:
    return [{"group": group, "socket": n, "source": {"group": src[0], "index": src[1]}}
            for (group, n), src in sorted(direct.items(),
                                          key=lambda item: socket_order(*item[0]))]


def overlay(plan: dict, rows: list[dict], *, complete: bool,
            console_model: "str | None" = None) -> Result:
    """`rows` laid onto a copy of `plan`'s `direct_outputs`.

    `complete` (a Save): the sheet is the whole list, so a socket it does
    not have comes out of the plan. Otherwise (a build): each row with a
    filled `source` wins, `OFF` disconnects, and a socket the sheet does
    not name is left to the plan -- except one a bus, Main or Matrix the
    sheet names fed: that object feeds the sockets its rows give it and no
    others. Every change is said in `changes`; what
    cannot work is a refusal, and nothing is changed then."""
    result = Result(plan=copy.deepcopy(plan))
    before = output_sources(plan)
    after = {} if complete else dict(before)
    seen: dict[tuple[str, int], int] = {}
    for n, row in enumerate(rows, start=2):
        out_cell = (row.get("output") or "").strip()
        src_cell = (row.get("source") or "").strip()
        if not out_cell and not src_cell:
            continue
        label = out_cell or f"line {n}"
        socket = parse_output(out_cell)
        if socket is None:
            result.refusals.append(Refusal(
                OUTPUT_SHEET, label, "output", out_cell,
                "is not an output socket: write a group and a number, such as USB 5 or "
                "AES50-B 3"))
            continue
        label = format_output(*socket)
        if socket in seen:
            result.refusals.append(Refusal(
                OUTPUT_SHEET, label, "output", out_cell,
                f"is listed twice (lines {seen[socket]} and {n}): one socket carries one source"))
            continue
        seen[socket] = n
        source, problem = parse_source(src_cell)
        if problem:
            result.refusals.append(Refusal(OUTPUT_SHEET, label, "source", src_cell, problem))
            continue
        if source is None:
            if complete and socket in before:
                after[socket] = before[socket]
            continue
        if source == OFF:
            after.pop(socket, None)
        else:
            after[socket] = source
    if result.refusals:
        return result
    # A bus, Main or Matrix the sheet names feeds the sockets its rows give it
    # and no others: a row is where that object goes, so one it
    # fed before -- from the conventions, or the bus sheet -- that the sheet
    # does not list comes off. A move, never a copy.
    named = {(src[0], (src[1] + 1) // 2) for socket, src in after.items()
             if socket in seen and isinstance(src, tuple) and src[0] in _OBJECT_GROUPS}
    for socket, src in list(after.items()):
        if (socket not in seen and src[0] in _OBJECT_GROUPS
                and (src[0], (src[1] + 1) // 2) in named):
            del after[socket]
    for socket in sorted(set(before) | set(after), key=lambda key: socket_order(*key)):
        was, now = before.get(socket), after.get(socket)
        if was == now:
            continue
        words = format_output(*socket)
        if now is None:
            result.changes.append(f"{words} disconnected (was {source_words(*was)})")
        elif was is None:
            result.changes.append(f"{words} from {source_words(*now)}")
        else:
            result.changes.append(f"{words} from {source_words(*now)} (was {source_words(*was)})")
    if result.changes:
        place(result.plan, after, touched={
            (src[0], (src[1] + 1) // 2) for socket in set(before) | set(after)
            if before.get(socket) != after.get(socket)
            for src in (before.get(socket), after.get(socket))
            if src is not None and src[0] in _OBJECT_GROUPS})
        _refuse_new_errors(plan, result, console_model)
    return result


def changed_sockets(before: dict, after: dict) -> set:
    """The sockets whose source differs between two plans."""
    was, now = output_sources(before), output_sources(after)
    return {s for s in set(was) | set(now) if was.get(s) != now.get(s)}


def follow_plan(text: "str | None", before: dict, after: dict, *,
                complete: bool) -> "tuple[str | None, list[str]]":
    """`outputs.csv` brought up to date with an edit made elsewhere -- a Save
    of the bus sheet that moved a bus's outputs: each row for a
    socket whose source changed says its new source, or goes when nothing
    feeds the socket now. `complete` (a captured show's sheet, the whole
    list): a socket newly patched gains a row too. Every other row, and its
    notes, is kept. Returns the new text (None for no file and nothing to
    add) and what changed, in the sheet's words."""
    moved = changed_sockets(before, after)
    if not moved:
        return text, []
    now = output_sources(after)
    rows, said, named = [], [], set()
    for row in read_rows(text or ""):
        socket = parse_output(row.get("output"))
        if socket in moved:
            named.add(socket)
            if socket not in now:
                said.append(f"{format_output(*socket)} removed")
                continue
            row = {**row, "output": format_output(*socket), "source": source_words(*now[socket])}
            said.append(f"{format_output(*socket)} from {source_words(*now[socket])}")
        rows.append(row)
    if complete:
        for socket in sorted(moved - named, key=lambda key: socket_order(*key)):
            if socket in now:
                rows.append({"output": format_output(*socket),
                             "source": source_words(*now[socket]), "notes": ""})
                said.append(f"{format_output(*socket)} from {source_words(*now[socket])}")
        rows.sort(key=lambda row: socket_order(*(parse_output(row.get("output"))
                                                  or ("~", 0))))
    if text is None and not rows:
        return None, []
    return csv_text(rows), said


def _pair(group: str, index: int, sockets: dict) -> tuple[list[dict], list]:
    """An object's sockets (`{socket: (group, slot)}`) as its `patches`: its
    L and its R on the next socket of one group are one stereo patch, its L
    alone a patch of its own. What a patch cannot say -- its R alone, or on
    a socket that does not follow its L -- is returned for `direct_outputs`."""
    left = 2 * index - 1
    sides = {socket: ("L" if slot == left else "R") for socket, (_g, slot) in sockets.items()}
    patches, rest, used = [], [], set()
    for (out, n), side in sorted(sides.items(), key=lambda item: socket_order(*item[0])):
        if (out, n) in used:
            continue
        if side == "L":
            if sides.get((out, n + 1)) == "R":
                used.add((out, n + 1))
                patches.append({"group": out, "sockets": [n, n + 1], "stated": True})
            else:
                patches.append({"group": out, "sockets": [n], "stated": True})
        else:
            rest.append((out, n))
    return patches, rest


def _set_patches(section: str, key: str, entry: dict, patches: list[dict]) -> None:
    if section == "outputs":
        entry.pop("sockets", None)
        entry.pop("socket", None)
        entry["patches"] = patches
        entry["patch"] = patches[0] if patches else None
        return
    destinations = [d for d in (entry.get("destinations") or (
        [entry["destination"]] if isinstance(entry.get("destination"), dict) else []))
        if isinstance(d, dict)]
    own = next((d for d in destinations if d.get("type") == "dedicated_output"), None)
    destinations = [d for d in destinations if d.get("type") != "dedicated_output"]
    if patches:
        own = dict(own or {"type": "dedicated_output", "label": key})
        for old in ("socket", "sockets"):
            own.pop(old, None)
        own.update(patch=patches[0], patches=patches)
        destinations.append(own)
    entry["destinations"] = destinations
    entry["destination"] = destinations[0] if destinations else None


def place(plan: dict, sources: dict, *, touched: "set[tuple[str, int]] | None" = None) -> None:
    """`sources` (`{socket: (group, n)}`, every socket the plan patches) put
    back into `plan`, in place: each socket a bus, Main or Matrix the plan has
    feeds goes on that object's `patches` where a patch can say it
    (`_pair`), and every other socket is a `direct_outputs` entry, an object's
    slot included. Only the objects in `touched` (`(group, n)`) are rebuilt;
    the rest keep their patches as they are."""
    objects = _objects(plan)
    placed: dict[tuple[str, int], tuple[str, int]] = {}
    for obj, (section, key, entry) in objects.items():
        group, index = obj
        if touched is not None and obj not in touched:
            placed.update(_patch_sources(group, index, _patches_of(section, entry)))
            continue
        mine = {socket: src for socket, src in sources.items()
                if src[0] == group and (src[1] + 1) // 2 == index}
        patches, _rest = _pair(group, index, mine)
        if _patch_sources(group, index, patches) != _patch_sources(
                group, index, _patches_of(section, entry)):
            _set_patches(section, key, entry, patches)
        placed.update(_patch_sources(group, index, patches))
    direct = {socket: src for socket, src in sources.items() if placed.get(socket) != src}
    if direct:
        plan["direct_outputs"] = _entries(direct)
    else:
        plan.pop("direct_outputs", None)


_WHERE = re.compile(r"^direct_outputs\[(?P<group>\S+) (?P<n>\S+)\]")
#: `output.socket-collision`'s message: `LCL output 3 is claimed by ...`.
_CLAIMED = re.compile(r"^(?P<group>\S+) outputs? (?P<n>\d+)")


def _refuse_new_errors(before: dict, result: Result, console_model: "str | None") -> None:
    """Every ERROR `verify_plan` finds in the edited plan that the plan did not
    already have and that is about a socket the sheet names, as a refusal on
    that row: a socket the desk does not have, one something else also
    patches, a source past its group's end."""
    from atoo import verify_plan

    def errors(plan):
        return verify_plan.verify_plan(plan, console_model=console_model).errors

    old = {(f.code, f.message) for f in errors(before)}
    for finding in errors(result.plan):
        if (finding.code, finding.message) in old:
            continue
        sockets = [m for m in (_WHERE.match(finding.where or ""),
                               re.search(r"direct_outputs\[(?P<group>\S+) (?P<n>\S+)\]",
                                         finding.message or ""),
                               _CLAIMED.match(finding.message or "")) if m]
        if not sockets:
            continue
        m = sockets[0]
        label = format_output(m.group("group"), int(m.group("n")))
        column = "output" if finding.code.startswith("output.") else "source"
        result.refusals.append(Refusal(OUTPUT_SHEET, label, column, "",
                                       f"{finding.message} ({finding.code})"))
