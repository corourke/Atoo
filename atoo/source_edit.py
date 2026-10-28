"""Editing the three files a build reads, from the Setup page, without
rewriting them.

These files are also edited in other editors (Obsidian, say) as well as on
the page, so the page is a second editor of a file that is the user's, and
it behaves like one:

* **Saving a file nobody changed leaves it byte-identical** -- nothing
  is written at all.
* **Conventions and instructions are saved whole**, as the step's one
  editor holds them, in the file's own line ending (`replace_text`).
* **The input list is spliced by row.** An untouched row
  keeps its exact text -- quoting, spacing, a ``yes`` where Atoo
  would write ``TRUE`` -- and a changed row is rewritten in the file's
  own column order and newline style. Columns the page does not show
  are carried through from the original row.

Everything here is text in, text out. Whether the file changed on disk
since the page read it, which file a slot means, and whether the page
asking is stale are the web server's to check (`webui`), before it gets
here.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from atoo.input_list import (CANONICAL_COLUMNS, OLD_PATCH_COLUMN, ORDER_COLUMN,
                                  PATCH_COLUMN, SHEET_COLUMNS, patch_column)


class EditError(ValueError):
    """An edit that cannot be applied to the text as it is -- a row that
    is not there any more. Carries a message for a person."""


def newline_of(text: str) -> str:
    """The file's own line ending: ``\\r\\n`` when most of its line breaks
    are, else ``\\n``. A file with no line break at all is ``\\n``."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _content(line: str) -> str:
    """A line without its terminator, whatever the terminator is."""
    parts = line.splitlines()
    return parts[0] if parts else ""


def _terminator(line: str) -> str:
    return line[len(_content(line)):]


def replace_text(text: str, new_text: str) -> tuple[str, bool]:
    """The whole file replaced by ``new_text`` -- a Save on step 01 or 03,
    whose one editor is the file (no sections view).

    The editor is the file, so there is nothing to splice: what it says is
    what is written. Two things are still kept from the file on disk:
    its line ending (a browser textarea hands back ``\\n`` whatever the
    file used, and a CRLF file stays CRLF), and the file itself when the
    editor says the same thing -- an unchanged save writes nothing.

    Returns the new text and whether it differs from ``text``.
    """
    nl = newline_of(text)
    out = new_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", nl)
    return (text, False) if out == text else (out, True)


# ---------------------------------------------------------------------------
# The input list
# ---------------------------------------------------------------------------

_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


@dataclass(frozen=True)
class Record:
    """One CSV record as written: ``raw`` is its text without the line
    break that ends it (a quoted field may hold line breaks of its own),
    ``end`` that line break plus any blank lines after it, ``values`` its
    fields by column name."""
    raw: str
    end: str
    values: dict


def _split_records(text: str) -> list[tuple[str, str]]:
    """``text`` cut into ``(record, terminator)`` pairs. A record runs
    until its double quotes balance -- a ``""`` inside a quoted field is
    two, so it never unbalances one -- and blank lines ride on the
    terminator of the record before them, so every byte is somewhere."""
    out: list[tuple[str, str]] = []
    pending = ""
    for line in text.splitlines(keepends=True):
        content, term = _content(line), _terminator(line)
        if pending:
            pending += content
            if pending.count('"') % 2 == 0:
                out.append((pending, term))
                pending = ""
            else:
                pending += term
            continue
        if content == "" and out:
            raw, end = out[-1]
            out[-1] = (raw, end + line)
            continue
        if content.count('"') % 2:
            pending = content + term
            continue
        out.append((content, term))
    if pending:
        out.append((pending, ""))
    return out


def _fields(raw: str) -> list[str]:
    rows = list(csv.reader(io.StringIO(raw, newline="")))
    return rows[0] if rows else []


def read_records(text: str) -> tuple[list[str], list[Record], str]:
    """The header, the data records and the header's own line break --
    leniently: a file that `input_list.parse_input_list` refuses still
    reads here, so the page can show it and the operator can fix the row
    the finding names."""
    pairs = _split_records(text)
    if not pairs:
        return [], [], "\n"
    header_raw, header_end = pairs[0]
    header = [name.lstrip("﻿").strip() for name in _fields(header_raw)]
    records = []
    for raw, end in pairs[1:]:
        fields = _fields(raw)
        values = {column: (fields[i] if i < len(fields) else "") for i, column in enumerate(header)}
        records.append(Record(raw, end, values))
    return header, records, header_end


def phantom_value(raw: str) -> "bool | None":
    """What an input list's phantom cell says: True, False, or None for a
    spelling `input_list` would refuse."""
    text = (raw or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def _format_row(values: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(values)
    return buffer.getvalue()


def _as_file_columns(values, own_patch: str) -> dict:
    """The page's ``values`` with the patch, sent as `patch` (or `socket`,
    from a page older than the rename), under ``own_patch`` -- the name
    the file's own header gives that column."""
    out = {}
    for key, value in (values or {}).items():
        if key in (PATCH_COLUMN, OLD_PATCH_COLUMN):
            if key != own_patch and own_patch in (values or {}):
                continue        # the file's own name, sent too, wins
            key = own_patch
        out[key] = value
    return out


def splice_input_list(text: str, rows: list[dict]) -> tuple[str, dict]:
    """``text`` with its data rows replaced by ``rows``, touching only the
    rows that changed.

    ``rows`` is the page's table, in order: ``{"line": i, "values":
    {...}}`` for a row that was record ``i`` of the file (0-based, header
    excluded), ``{"line": None, "values": {...}}`` for a new one.
    ``values`` holds the canonical columns as strings; a column the page
    did not send keeps what the file had. A row whose values are what
    the file already says keeps its exact text. A record no row names is
    removed.

    The patch column is `patch` in ``values`` whatever the file calls it: a file headed `socket` -- every list written before
    2026-09-28 -- has the value written into its `socket` column, and its
    header is left exactly as it was. `socket` in ``values`` is read the
    same way.

    A value for a canonical column the header does not have adds that
    column at the end of the header (every row then gains a field) --
    except `order`, which is added first, where a new file has it. The
    returned summary says what happened: ``{"changed": [...], "added":
    n, "removed": n, "columns_added": [...]}``.
    """
    header, _records, _end = read_records(text)
    if not header:
        raise EditError("the input list has no header row -- it is empty")
    own_patch = patch_column(header)
    rows = [dict(row, values=_as_file_columns(row.get("values"), own_patch))
            for row in rows or []]
    known = set(CANONICAL_COLUMNS) | set(SHEET_COLUMNS) | {own_patch}
    return splice_rows(text, rows, known, lead=ORDER_COLUMN)


def splice_bus_sheet(text: "str | None", rows: list[dict]) -> tuple[str, dict]:
    """`busses.csv` with its rows replaced by ``rows``, as `splice_input_list`
    does for the input list: an untouched row keeps its exact text, a changed
    one is rewritten in the file's own column order, a column the page sends
    that the header lacks is added at the end. With no file yet (``text``
    None or empty: a built show's first Save in step 04), a new one is made
    with the sheet's own header (`sheets.BUS_COLUMNS`), holding the rows sent."""
    from atoo.sheets import BUS_COLUMNS

    if not (text or "").strip():
        text = ",".join(BUS_COLUMNS) + "\n"
    header, _records, _end = read_records(text)
    if not header:
        raise EditError("busses.csv has no header row -- it is empty")
    return splice_rows(text, rows, set(BUS_COLUMNS) | set(header))


def splice_rows(text: str, rows: list[dict], known: set, *, lead: "str | None" = None
                ) -> tuple[str, dict]:
    """The splice both sheets share: ``rows`` are the page's table in order,
    ``{"line": i | None, "values": {...}}``; ``known`` the columns a row may
    write; ``lead`` a column that, added, goes first rather than last."""
    nl = newline_of(text)
    header, records, header_end = read_records(text)
    columns_added = []
    for row in rows:
        for column, value in (row.get("values") or {}).items():
            if column in known and column not in header \
                    and column not in columns_added and (value or "").strip():
                columns_added.append(column)
    # `order` leads, as it does in a new file (FR-1.1: the band's own
    # numbering is the first thing read down the sheet). Adding a column
    # rewrites every row anyway, so putting it first costs nothing more;
    # any other new column goes at the end, as before.
    first = [c for c in columns_added if c == lead]
    new_header = first + header + [c for c in columns_added if c != lead]

    out_rows: list[tuple[str, str]] = []  # (record text, its own terminator or "")
    changed, added, used, order = [], 0, set(), []
    for position, row in enumerate(rows or []):
        line = row.get("line")
        sent = {k: ("" if v is None else str(v)) for k, v in (row.get("values") or {}).items()
                if k in known}
        if line is not None:
            try:
                line = int(line)
            except (TypeError, ValueError):
                raise EditError(f"row {position + 1} names no usable line: {row.get('line')!r}")
            if line < 0 or line >= len(records):
                raise EditError(f"row {position + 1} names record {line}, which the file does "
                                "not have any more -- reload it")
            if line in used:
                raise EditError(f"record {line} appears twice in the table")
            used.add(line)
            order.append(line)
            record = records[line]
            merged = dict(record.values)
            merged.update({k: v for k, v in sent.items() if k in header or v.strip()})
            same = all(merged.get(c, "") == record.values.get(c, "") for c in new_header)
            if same and not columns_added:
                out_rows.append((record.raw, record.end))
                continue
            out_rows.append((_format_row([merged.get(c, "") for c in new_header]),
                             record.end))
            if not same:
                changed.append(merged.get("name") or merged.get("bus") or f"row {position + 1}")
        else:
            out_rows.append((_format_row([sent.get(c, "") for c in new_header]), ""))
            added += 1
    removed = len(records) - len(used)
    moved = order != sorted(order)

    head = _format_row(new_header) if columns_added else _split_records(text)[0][0]
    entries = [(head, header_end)] + out_rows
    pieces = []
    for raw, end in entries:
        pieces.append(raw)
        pieces.append(end if end else nl)
    result = "".join(pieces)
    # The file ends the way it ended: with a line break, or without one.
    ended = text[-1:] in ("\n", "\r")
    if not ended:
        for term in ("\r\n", "\n", "\r"):
            if result.endswith(term):
                result = result[:-len(term)]
                break
    if not (changed or added or removed or columns_added or moved):
        # Nothing the page sent differs from the file: the file as it is,
        # to the byte, whatever the reassembly above made of it.
        result = text
    return result, {"changed": changed, "added": added, "removed": removed,
                    "columns_added": columns_added}
