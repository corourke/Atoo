"""`user.csv`: the desk's USR slots a show uses, one row each, in the desk's own
words (built).

The desk has 56 USR slots. USR 1-24 are **user signals**: each takes a
channel, an aux, a bus, a Main or a Matrix at its tap (PRE or POST its fader),
as L+R, L or R. USR 25-56 are **user patches**: each takes an input socket as
it is. A processed feed leaves the desk through one, since an output cannot
take a channel; a channel can take one as its source too.

The file has five columns, in the order the desk's USR routing page shows
them:

    slot,source,tap,leg,name
    USR 1,CH 19,POST,L+R,Lead post
    USR 25,LCL 5,,,Mic 3 split

The plan holds the same as `user_sources` (`{slot, source: {group, index},
tap, leg, name}`), which Apply writes ahead of anything that reads a slot.

* **Capture** writes it from the slots a channel or an output reads
  (`rows_from_plan`).
* **Build** lays it on the plan the model made: a filled row wins over the
  conventions for its slot, `OFF` in `source` takes the slot out, and a slot
  the sheet does not name is left to them (`overlay(..., complete=False)`).
* **A Save** in Build 04 lays it on whole: the sheet is the complete list
  (`overlay(..., complete=True)`).

What cannot physically work is refused, naming the row, and nothing is
changed: a cell that is no slot or no source, a slot listed twice, a tap or a
leg on a user patch (which has neither), and every new ERROR `verify_plan`
finds about a slot (one that does not exist, a source its kind cannot take, a
number past the desk's).
"""

from __future__ import annotations

import copy
import csv
import io
import re

from atoo import console_facts as facts
from atoo.input_list import format_socket, parse_socket_spec
from atoo.sheets import Refusal, Result

USER_SHEET = "user.csv"
COLUMNS = ("slot", "source", "tap", "leg", "name")
OFF = "OFF"

_SLOT = re.compile(r"^\s*(?:USR\s*)?(?P<n>\d+)\s*$", re.IGNORECASE)
#: A user signal's strip, as the desk's routing page names it (and the
#: spellings an engineer types for the same thing).
_STRIP = re.compile(r"^\s*(?P<kind>ch|channel|aux|bus|main|mtx|matrix|mx)\s*(?P<n>\d+)\s*$",
                    re.IGNORECASE)
_STRIP_GROUP = {"ch": "CH", "channel": "CH", "aux": "AUX", "bus": "BUS", "main": "MAIN",
                "mtx": "MTX", "matrix": "MTX", "mx": "MTX"}


def parse_slot(text) -> "int | None":
    m = _SLOT.match(str(text or ""))
    return int(m.group("n")) if m else None


def slot_words(slot: int) -> str:
    return f"USR {slot}"


def kind_words(slot: int) -> str:
    """"user signal" or "user patch": the desk tells them apart by number."""
    return "user signal" if facts.user_slot_kind(slot) == facts.USER_SIGNAL else "user patch"


def source_words(group: str, index: int) -> str:
    """The desk's pair as the sheet writes it: `("CH", 19)` -> `CH 19`,
    `("LCL", 5)` -> `LCL 5`, `("A", 3)` -> `AES50-A 3`."""
    if group in facts.USER_SIGNAL_SOURCE_GROUPS:
        return f"{group} {index}"
    return format_socket(group, index)


def parse_source(slot: int, text) -> "tuple[tuple[str, int] | str | None, str | None]":
    """A `source` cell for `slot`: `(("CH", 19), None)`, `(OFF, None)`, `(None,
    None)` for a blank cell, or `(None, reason)` for one the slot's kind
    cannot take -- a user signal takes a strip, a user patch an input socket."""
    raw = str(text or "").strip()
    if not raw:
        return None, None
    if raw.upper() == OFF:
        return OFF, None
    signal = facts.user_slot_kind(slot) == facts.USER_SIGNAL
    m = _STRIP.match(raw)
    if m:
        if not signal:
            return None, (f"{raw!r}: USR {slot} is a user patch, which takes an input socket "
                          "(LCL 5, AES50-A 3) -- only a user signal (USR 1-24) takes a strip")
        return (_STRIP_GROUP[m.group("kind").lower()], int(m.group("n"))), None
    parsed = parse_socket_spec(raw)
    if parsed is not None and parsed[0] in facts.USER_PATCH_SOURCE_GROUPS:
        if signal:
            return None, (f"{raw!r}: USR {slot} is a user signal, which takes a strip (CH 19, "
                          "BUS 8, MAIN 1) -- only a user patch (USR 25-56) takes an input socket")
        return parsed, None
    return None, (f"{raw!r} is not a source a USR slot takes: write a strip for a user signal "
                  "(CH 19, AUX 3, BUS 8, MAIN 1, MTX 2), an input socket for a user patch "
                  "(LCL 5, AES50-A 3), or OFF")


def rows_from_plan(plan: dict) -> list[dict[str, str]]:
    """The sheet as the plan has it: one row per `user_sources` entry, by slot."""
    rows = []
    for entry in sorted((e for e in plan.get("user_sources") or [] if isinstance(e, dict)
                         and isinstance(e.get("slot"), int)), key=lambda e: e["slot"]):
        source = entry.get("source") or {}
        rows.append({
            "slot": slot_words(entry["slot"]),
            "source": (source_words(source["group"], source["index"])
                       if isinstance(source.get("group"), str)
                       and isinstance(source.get("index"), int) else ""),
            "tap": entry.get("tap") or "",
            "leg": entry.get("leg") or "",
            "name": entry.get("name") or "",
        })
    return rows


def readers(plan: dict) -> dict[int, list[str]]:
    """What reads each slot: `{3: ["USB 29", "CH 27"]}` -- the output sockets
    fed from it and the channels patched from it, in the desk's words. Set in
    Outputs and Channels, shown beside the slot."""
    from atoo import outputs_sheet

    found: dict[int, list[str]] = {}
    for socket, (group, index) in sorted(outputs_sheet.output_sources(plan).items(),
                                         key=lambda item: outputs_sheet.socket_order(*item[0])):
        if group == "USR":
            found.setdefault(index, []).append(outputs_sheet.format_output(*socket))
    for ch in plan.get("channels") or []:
        patch = (ch or {}).get("patch") or {}
        if patch.get("group") == "USR" and isinstance(ch.get("channel"), int):
            label = f"{'AUX' if ch.get('bank') == 'aux' else 'CH'} {ch['channel']}"
            for slot in patch.get("sockets") or []:
                found.setdefault(slot, []).append(label)
    return found


def csv_text(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in COLUMNS})
    return out.getvalue()


def read_rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            for row in reader]


def _said(entry: dict) -> str:
    source = entry["source"]
    words = source_words(source["group"], source["index"])
    if facts.user_slot_kind(entry["slot"]) == facts.USER_SIGNAL:
        bits = [b for b in (entry.get("tap"), entry.get("leg")) if b]
        words += f" {' '.join(bits)}" if bits else ""
    if entry.get("name"):
        words += f" ({entry['name']})"
    return words


def overlay(plan: dict, rows: list[dict], *, complete: bool,
            console_model: "str | None" = None) -> Result:
    """`rows` laid onto a copy of `plan`'s `user_sources`.

    `complete` (a Save): the sheet is the whole list, so a slot it does not
    have comes out of the plan. Otherwise (a build): each row with a filled
    `source` sets its slot, `OFF` takes the slot out, and a slot the sheet
    does not name is left to the plan. A blank tap, leg or name keeps the
    plan's for that slot. Every change is said in `changes`; what cannot
    work is a refusal, and nothing is changed then."""
    result = Result(plan=copy.deepcopy(plan))
    before = {e["slot"]: e for e in plan.get("user_sources") or []
              if isinstance(e, dict) and isinstance(e.get("slot"), int)}
    after: dict[int, dict] = {} if complete else copy.deepcopy(before)
    seen: dict[int, int] = {}
    for n, row in enumerate(rows, start=2):
        slot_cell = (row.get("slot") or "").strip()
        src_cell = (row.get("source") or "").strip()
        if not slot_cell and not src_cell:
            continue
        slot = parse_slot(slot_cell)
        label = slot_cell or f"line {n}"
        if slot is None or facts.user_slot_kind(slot) is None:
            result.refusals.append(Refusal(
                USER_SHEET, label, "slot", slot_cell,
                "is not a USR slot: the desk has USR 1-24 (user signals) and USR 25-56 "
                "(user patches)"))
            continue
        label = slot_words(slot)
        if slot in seen:
            result.refusals.append(Refusal(
                USER_SHEET, label, "slot", slot_cell,
                f"is listed twice (lines {seen[slot]} and {n}): one slot holds one source"))
            continue
        seen[slot] = n
        source, problem = parse_source(slot, src_cell)
        if problem:
            result.refusals.append(Refusal(USER_SHEET, label, "source", src_cell, problem))
            continue
        tap = (row.get("tap") or "").strip().upper()
        leg = (row.get("leg") or "").strip().upper()
        if facts.user_slot_kind(slot) == facts.USER_PATCH:
            for column, cell in (("tap", tap), ("leg", leg)):
                if cell:
                    result.refusals.append(Refusal(
                        USER_SHEET, label, column, row.get(column, ""),
                        f"USR {slot} is a user patch, which takes an input socket as it is -- "
                        f"only a user signal (USR 1-24) has a {column}. Clear it, or move the "
                        "feed to a user signal"))
            if any(r.row == label for r in result.refusals):
                continue
        else:
            if tap and tap not in facts.USER_SIGNAL_TAPS:
                result.refusals.append(Refusal(USER_SHEET, label, "tap", row.get("tap", ""),
                                               "a user signal's tap is PRE or POST"))
                continue
            if leg and leg not in facts.USER_SIGNAL_LEGS:
                result.refusals.append(Refusal(USER_SHEET, label, "leg", row.get("leg", ""),
                                               "a user signal's leg is L+R, L or R"))
                continue
        if source is None:
            if complete and slot in before:
                after[slot] = copy.deepcopy(before[slot])
            continue
        if source == OFF:
            after.pop(slot, None)
            continue
        was = before.get(slot) or {}
        entry = {"slot": slot, "source": {"group": source[0], "index": source[1]}}
        if facts.user_slot_kind(slot) == facts.USER_SIGNAL:
            entry["tap"] = tap or was.get("tap") or "POST"
            entry["leg"] = leg or was.get("leg") or "L+R"
        name = (row.get("name") or "").strip() or was.get("name")
        if name:
            entry["name"] = name
        after[slot] = entry
    if result.refusals:
        return result
    for slot in sorted(set(before) | set(after)):
        was, now = before.get(slot), after.get(slot)
        if was == now:
            continue
        if now is None:
            result.changes.append(f"{slot_words(slot)} taken out (was {_said(was)})")
        elif was is None:
            result.changes.append(f"{slot_words(slot)} takes {_said(now)}")
        else:
            result.changes.append(f"{slot_words(slot)} takes {_said(now)} (was {_said(was)})")
    if not result.changes:
        return result
    if after:
        result.plan["user_sources"] = [after[slot] for slot in sorted(after)]
    else:
        result.plan.pop("user_sources", None)
    _refuse_new_errors(plan, result, console_model)
    return result


_WHERE = re.compile(r"^user_sources\[(?P<i>\d+)\]")


def _refuse_new_errors(before: dict, result: Result, console_model: "str | None") -> None:
    """Every ERROR `verify_plan` finds in the edited plan about a USR slot that
    the plan did not already have, as a refusal on that slot's row."""
    from atoo import verify_plan

    def errors(plan):
        return verify_plan.verify_plan(plan, console_model=console_model).errors

    old = {(f.code, f.message) for f in errors(before)}
    entries = result.plan.get("user_sources") or []
    for finding in errors(result.plan):
        if (finding.code, finding.message) in old:
            continue
        m = _WHERE.match(finding.where or "")
        if not m or int(m.group("i")) >= len(entries):
            continue
        slot = entries[int(m.group("i"))].get("slot")
        result.refusals.append(Refusal(USER_SHEET, slot_words(slot), "source", "",
                                       f"{finding.message} ({finding.code})"))
