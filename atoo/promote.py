"""`atoo patch --promote`: keep a change in the show for good, slice 3.

The maintainer, 2026-09-25: *"If I decide that my show file should have
additional inputs or additional outputs all the time I'm going to just
change the input list or change my conventions file or instructions file
and this will be the new show moving forward and I'll just do a rebuild.
Amend is a special case."* A change typed at the desk is that special case.
Promoting one turns it into the ordinary case after the fact: its text goes
into the bundle's `instructions.md`, the inputs it added go onto
`input.csv`, and from then on a normal rebuild owns them.

## What it writes, and what it never does

* **`instructions.md`** -- the change's own text, appended under a
  "Promoted changes" heading, one dated sub-heading per change, carrying a
  comment with the journal entry's id. The comment is how a second promote
  of the same change is recognised (and it is stripped before the
  instructions reach the model, like every comment in that file).
* **`input.csv`** -- a row for each input the change ADDED that is not on
  the list already: the channels the change placed on strips (its
  journal's `scope.strips`), read from the plan it left on the desk. The
  file's own header and column order are kept (a list still headed
  `socket` keeps `socket`); a stereo channel is two rows, "Name
  L" and "Name R", because every WING input socket is mono.
  Each row's patch is the socket the channel is on NOW -- where the cable
  is -- so the rebuild patches it where it already is.
* **Never `plan.json`** (decision 1: only a build writes it).
  A change that dropped or edited something is promoted as text only: its
  words are the instruction, and no input-list row is removed -- a source
  that has gone for good is the engineer's to delete from the list, and a
  promote that deleted rows would be a promote that could lose data.

Preview by default; `--confirm` writes, the project's convention. A change
that was undone is refused (it is not on the desk, so there is nothing to
keep), and so is an amend from a rebuilt plan (it has no typed text, and
its plan was already a build).

## The judgement calls, announced

`input.csv` needs a category and a type for each row, and a change's
channel does not carry a category. Both are inferred and said at INFO
(`CLAUDE.md`: an inferred value that announces itself is not a defect):

* **category** -- that of an input already on the list that shares the new
  channel's first DCA (the horns join the category the other Horns-DCA
  channels have); else a category on the list spelled like that DCA; else
  `other`.
* **type** -- the channel's `source.type`, else `Mic`.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from atoo import bundle
from atoo import input_list
from atoo import journal_stack

HEADING = "## Promoted changes"

#: The comment each promoted change carries in `instructions.md`.
MARKER = "<!-- atoo: promoted {id} -->"
_MARKER_RE = re.compile(r"<!--\s*atoo:\s*promoted\s+(\S+)\s*-->")

DEFAULT_CATEGORY = "other"
DEFAULT_TYPE = "Mic"


def promoted_ids(bundle_dir: str | Path) -> set[str]:
    """The journal-entry ids of every change already promoted into this
    bundle's `instructions.md` -- read from the markers `write` leaves."""
    try:
        text = (Path(bundle_dir) / bundle.INSTRUCTIONS).read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(_MARKER_RE.findall(text))


class PromoteError(Exception):
    """A change that cannot be promoted, phrased for a user."""


@dataclass
class Promotion:
    """What a promote would write -- the preview, and what `--confirm` does."""

    entry: journal_stack.Entry
    label: str
    #: The block appended to instructions.md (empty when already promoted).
    instructions_block: str = ""
    #: `{column: value}` rows appended to input.csv, keyed by the file's own
    #: column names.
    rows: list[dict] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    #: This change's marker is already in instructions.md: nothing to do.
    already: bool = False

    def summary(self) -> str:
        if self.already:
            return (f"{self.label} is already in the show: instructions.md carries it "
                    f"(entry {self.entry.id}). Nothing to write.")
        lines = [f"Promote {self.label} into the show:", "",
                 f"  {bundle.INSTRUCTIONS} gains:"]
        lines += [f"    | {line}" if line else "    |" for line in
                  self.instructions_block.strip("\n").splitlines()]
        if self.rows:
            lines += ["", f"  {bundle.INPUT_LIST} gains {len(self.rows)} row(s):",
                      "    " + ",".join(self.header)]
            lines += ["    " + _csv_line(self.header, row).rstrip("\r\n") for row in self.rows]
        else:
            lines += ["", f"  {bundle.INPUT_LIST}: no rows to add."]
        lines += ["", f"  {bundle.PLAN} is not touched -- rebuild the show to put the change in "
                      "it (only a build writes plan.json)."]
        return "\n".join(lines)


def _csv_line(header: list[str], row: dict) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow([row.get(c, "") for c in header])
    return out.getvalue()


def patch_entries(bundle_dir: str | Path) -> list[journal_stack.Entry]:
    """Every change recorded on this bundle's stack, oldest first."""
    return [e for e in journal_stack.entries(bundle_dir) if e.kind == "patch" and e.change]


def _listing(bundle_dir: str | Path) -> str:
    changes = patch_entries(bundle_dir)
    if not changes:
        return "This bundle's journal records no typed changes."
    rows = []
    for entry in changes:
        undone = " (undone)" if journal_stack.reversed_by(bundle_dir, entry) else ""
        rows.append(f"  {journal_stack.change_label(entry.change)}{undone}  [{entry.id}]")
    return "The changes this bundle's journal records:\n" + "\n".join(rows)


def find_change(bundle_dir: str | Path, ref: str) -> journal_stack.Entry:
    """The change `ref` names: its number ("3", "change 3"), its journal
    entry's id, or its short name (exactly, else a unique part of it,
    either ignoring case)."""
    text = (ref or "").strip()
    wanted = text.casefold()
    changes = patch_entries(bundle_dir)
    match = re.fullmatch(r"(?:change\s*)?#?(\d+)", text, re.IGNORECASE)
    if match:
        found = [e for e in changes if e.change.get("number") == int(match.group(1))]
    else:
        found = [e for e in changes if e.id == text or Path(text).name == e.id]
        if not found:
            found = [e for e in changes if str(e.change.get("name", "")).casefold() == wanted]
        if not found:
            found = [e for e in changes if wanted and wanted in str(
                e.change.get("name", "")).casefold()]
    if not found:
        amends = [e for e in journal_stack.entries(bundle_dir)
                  if e.kind == "amend" and (e.id == text or Path(text).name == e.id)]
        if amends:
            raise PromoteError(
                f"{text} is an amend from a rebuilt plan, not a typed change: it has no text to "
                "promote, and the plan it came from was already a build -- put what it added "
                "in the input list or instructions.md and rebuild")
        gone = [r for r in journal_stack.pruned_rows(bundle_dir)
                if isinstance(r.get("change"), dict) and (
                    (match and r["change"].get("number") == int(match.group(1)))
                    or r.get("id") == text
                    or (wanted and wanted in str(r["change"].get("name", "")).casefold()))]
        if gone:
            raise PromoteError(
                f"{journal_stack.change_label(gone[-1]['change'])} is still on the desk, but its "
                f"journal was pruned ({bundle.JOURNALS}/ keeps only the newest "
                f"{journal_stack.keep_limit()} entries), and promoting needs the plan it "
                "saved. Write it into instructions.md (and input.csv) by hand -- its text was: "
                f"{gone[-1]['change'].get('text')!r}")
        raise PromoteError(f"no change {text!r} in this bundle's journal.\n{_listing(bundle_dir)}")
    if len(found) > 1:
        names = "; ".join(f"{journal_stack.change_label(e.change)} [{e.id}]" for e in found)
        raise PromoteError(f"{text!r} names more than one change: {names}. Give its number.")
    return found[0]


def _read_payload(entry: journal_stack.Entry) -> dict:
    try:
        payload = json.loads(entry.path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PromoteError(f"the journal {entry.path} could not be read: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _added_channels(payload: dict) -> list[dict]:
    """The channels this change placed on strips, from the plan it left."""
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    strips = [s for s in scope.get("strips") or [] if isinstance(s, str)]
    block = payload.get(journal_stack.DESK_PLAN_BLOCK)
    plan = block.get("plan") if isinstance(block, dict) else None
    channels = (plan or {}).get("channels") or []
    by_slot = {f"{c.get('bank', 'ch')}:{c.get('channel')}": c
               for c in channels if isinstance(c, dict)}
    return [by_slot[s] for s in strips if s in by_slot]


def _desk_channels(payload: dict) -> list[dict]:
    block = payload.get(journal_stack.DESK_PLAN_BLOCK)
    plan = block.get("plan") if isinstance(block, dict) else None
    return [c for c in (plan or {}).get("channels") or [] if isinstance(c, dict)]


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _category(channel: dict, desk: list[dict], rows: list[dict]) -> tuple[str, str]:
    """`(category, why)` for a new input-list row -- see the module
    docstring's judgement calls."""
    by_name = {_norm(r.get("name")): r.get("category") for r in rows if r.get("category")}
    for dca in channel.get("dca") or []:
        for other in desk:
            if other is channel or dca not in (other.get("dca") or []):
                continue
            source = (other.get("source") or {}).get("input") or other.get("name")
            category = by_name.get(_norm(source))
            if category:
                return category, (f"the category of {source!r}, which shares its DCA "
                                  f"{dca!r}")
        categories = {_norm(c): c for c in by_name.values()}
        for spelled in (_norm(dca), _norm(dca).rstrip("s")):
            if spelled in categories:
                return categories[spelled], f"the input-list category spelled like its DCA {dca!r}"
    return DEFAULT_CATEGORY, ("no input on the list shares its DCA, and no category is spelled "
                              f"like one, so {DEFAULT_CATEGORY!r}")


def _read_input_list(path: Path) -> tuple[list[str], list[dict], str]:
    text = path.read_text(encoding="utf-8")
    # A byte-order mark (Excel's "CSV UTF-8") is not part of the first
    # column's name; see input_list.parse_input_list.
    reader = csv.DictReader(io.StringIO(text.removeprefix("﻿")))
    header = list(reader.fieldnames or [])
    return header, [dict(r) for r in reader], text


def promotion(bundle_dir: str | Path, ref: str, *, today: str | None = None) -> Promotion:
    """Work out what promoting the change `ref` names would write. Pure:
    nothing is written here (`write` does that)."""
    from datetime import date

    directory = Path(bundle_dir)
    entry = find_change(directory, ref)
    label = journal_stack.change_label(entry.change)
    undone = journal_stack.reversed_by(directory, entry)
    if undone:
        raise PromoteError(
            f"{label} was undone ({undone}), so it is not on the desk -- there is nothing of it "
            "to keep. Patch it again first if it is wanted.")
    if entry.aborted:
        raise PromoteError(
            f"{label} aborted partway, so only part of it is on the desk. Patch it again (or "
            "undo what landed) before keeping it in the show.")
    text = str(entry.change.get("text") or "").strip()
    if not text:
        raise PromoteError(f"{label} carries no text -- it was written from a change set with "
                           "none recorded, so there is nothing to put in instructions.md")

    result = Promotion(entry=entry, label=label)
    instructions = directory / bundle.INSTRUCTIONS
    existing = instructions.read_text(encoding="utf-8") if instructions.exists() else ""
    if entry.id in _MARKER_RE.findall(existing):
        result.already = True
        return result

    day = (entry.timestamp or "")[:10] or today or date.today().isoformat()
    block = []
    if HEADING not in existing:
        block += [HEADING, "",
                  "Changes typed at the desk with `atoo patch` and kept in the show with "
                  "`--promote`. Each is an instruction for every rebuild from now on.", ""]
    block += [f"### {day}: {label}", "", MARKER.format(id=entry.id), "", text, ""]
    result.instructions_block = "\n".join(block) + "\n"
    if not instructions.exists():
        result.infos.append(f"the bundle has no {bundle.INSTRUCTIONS}; promoting creates it")

    payload = _read_payload(entry)
    added = _added_channels(payload)
    listing = directory / bundle.INPUT_LIST
    if not listing.exists():
        if added:
            result.infos.append(
                f"the bundle has no {bundle.INPUT_LIST}, so the {len(added)} input(s) this "
                "change added are kept as the instruction's text only")
        return result
    header, rows, _text = _read_input_list(listing)
    result.header = header
    patch_key = input_list.patch_column(header)
    known = {_norm(r.get("name")) for r in rows}
    skipped = {_norm(r.get("name")) for r in rows
               if (r.get(input_list.ORDER_COLUMN) or "").strip() == input_list.SKIP_MARK}
    desk = _desk_channels(payload)
    for channel in added:
        source = channel.get("source") or {}
        name = str(source.get("input") or channel.get("name") or "").strip()
        if not name:
            continue
        patch = channel.get("patch") or {}
        group = patch.get("group")
        sockets = [s for s in patch.get("sockets") or [] if isinstance(s, int)]
        stereo = bool(source.get("stereo")) or len(sockets) == 2
        names = [f"{name} L", f"{name} R"] if stereo else [name]
        if any(_norm(n) in known for n in names) or _norm(name) in known:
            off = [n for n in [name, *names] if _norm(n) in skipped]
            if off:
                # On the list but switched off (`-` in `order`, FR-1.1):
                # the desk has it and the next build would not. Promote
                # adds rows and never edits one, so it says so.
                result.infos.append(
                    f"{name!r} is already on the input list but skipped ('-' in its order "
                    "cell) -- no row added, and the next build leaves it out until that "
                    "'-' is cleared")
            else:
                result.infos.append(f"{name!r} is already on the input list -- no row added")
            continue
        category, why = _category(channel, desk, rows)
        kind = source.get("type") or DEFAULT_TYPE
        result.infos.append(
            f"{name!r}: category {category!r} -- {why}"
            + ("" if source.get("type") else f"; type {DEFAULT_TYPE!r}, since the channel "
               "states none"))
        if stereo:
            result.infos.append(f"{name!r} is stereo, so it is two rows, {names[0]!r} and "
                                f"{names[1]!r} -- every WING input socket is mono")
        for i, row_name in enumerate(names):
            socket = ""
            if isinstance(group, str) and group != "OFF" and i < len(sockets):
                socket = input_list.format_socket(group, sockets[i])
            row = {"name": row_name, "category": category, "type": kind,
                   "model": source.get("model") or "",
                   "phantom": "TRUE" if source.get("phantom") else "FALSE",
                   patch_key: socket, "notes": f"promoted from {label}"}
            result.rows.append({c: row.get(c, "") for c in header})
            known.add(_norm(row_name))
    return result


def write(bundle_dir: str | Path, result: Promotion) -> list[str]:
    """Append what `result` holds. Returns the files written."""
    if result.already:
        return []
    directory = Path(bundle_dir)
    written = []
    instructions = directory / bundle.INSTRUCTIONS
    existing = instructions.read_text(encoding="utf-8") if instructions.exists() else ""
    lead = "" if not existing or existing.endswith("\n\n") else (
        "\n" if existing.endswith("\n") else "\n\n")
    instructions.write_text(existing + lead + result.instructions_block, encoding="utf-8")
    written.append(bundle.INSTRUCTIONS)
    if result.rows:
        listing = directory / bundle.INPUT_LIST
        raw = listing.read_bytes().decode()
        newline = "\r\n" if "\r\n" in raw else "\n"
        out = io.StringIO()
        writer = csv.writer(out, lineterminator=newline)
        for row in result.rows:
            writer.writerow([row.get(c, "") for c in result.header])
        if raw and not raw.endswith(("\n", "\r")):
            raw += newline
        # Newlines kept exactly as the file has them.
        listing.write_bytes((raw + out.getvalue()).encode())
        written.append(bundle.INPUT_LIST)
    return written


__all__ = ["HEADING", "MARKER", "PromoteError", "Promotion", "find_change", "patch_entries",
           "promotion", "write"]
