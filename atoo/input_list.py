"""Input list (CSV) loading and validation -- FR-1.1.

One row per physical input. Every input socket on a WING is mono, so a row is one mono source and nothing else -- there is no
such thing as a stereo input to list.

No channel-number column and no stereo column. Both state a decision as
though it were a fact: which strip a source lands on, and whether two
sources are linked into one stereo channel, are computed from the
conventions and the source names ("Keys L"/"Keys R"). An input list that
tries to specify either is a modeling error in whatever produced it, not
something this loader silently accepts.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass

REQUIRED_COLUMNS = ("name", "category", "type", "phantom")

# The order an Atoo-written input list uses, and what the docs show.
# Column order is NOT significant to this loader -- every read goes through
# csv.DictReader, by header name -- so a file in any order loads the same.
# It matters to the person holding the sheet: `patch` leads because it is
# what you check against the stage box, `notes` trails because nothing
# reads it. `preset` is optional and sits just before
# `notes`; a Save adds it to a file's header only when a row sets one
# (`source_edit.splice_input_list`), at the end, so a file's own column
# order is never rewritten.
CANONICAL_COLUMNS = (
    "order", "patch", "name", "category", "type", "model", "phantom", "preset", "notes",
)

# The `order` column (FR-1.1). Optional. A cell holds
# the band's OWN input number -- usually the split from their IEM rack, or
# the way they patch a stage box -- or `-`, which means "skip": the row
# stays in the file and is left out of the next build entirely. Blank is
# an ordinary included row with no number.
#
# The number does NOT set the desk channel, and nothing in code reads it
# as one: channel order is the conventions' to compute (FR-1.1), and this
# column is not the `channel` column FORBIDDEN_COLUMNS refuses. It reaches
# the model as data, with the row, so an instruction such as "Patch the
# inputs according to the band's channel order numbers" can use it.
ORDER_COLUMN = "order"
SKIP_MARK = "-"

# The patch column's name before an earlier change (2026-09-28). A **socket** is
# the physical input on the desk; a **patch** is the connection from a
# channel to it -- and the column says where each source is patched, so
# it is `patch` now. A list headed `socket` still loads exactly the same,
# and a Save keeps whichever header the file has (`source_edit`).
PATCH_COLUMN = "patch"
OLD_PATCH_COLUMN = "socket"


def patch_column(header) -> str:
    """Which of a header's columns holds the patch: `socket` only when the
    file says `socket` and not `patch` (a list written before the rename),
    otherwise `patch` -- the name a new file, or a new column, gets."""
    names = set(header or ())
    if OLD_PATCH_COLUMN in names and PATCH_COLUMN not in names:
        return OLD_PATCH_COLUMN
    return PATCH_COLUMN

# Columns an input list must NOT have -- the clearest possible signal that
# whatever produced this file assumed the old, rejected design (FR-1.1).
# Ignoring them silently would be worse than refusing: the file would load,
# the column would have no effect, and the plan would quietly contradict
# what the sheet appears to say.
FORBIDDEN_COLUMNS = {"channel", "channel_number", "ch", "stereo"}

_FORBIDDEN_REASONS = {
    "channel": "conventions compute channel assignment; the input list must not "
               "specify one",
    "channel_number": "conventions compute channel assignment; the input list must "
                      "not specify one",
    "ch": "conventions compute channel assignment; the input list must not specify "
          "one",
    "stereo": "every input socket on a WING is mono, so no row is "
              "stereo. Linking two sources into one stereo channel is a decision "
              "made from the conventions and the source names ('Keys L'/'Keys R'), "
              "not a property of an input -- state it in the conventions file, "
              "where the exceptions live too ('overheads stay mono')",
}

_TRUE_VALUES = {"true", "TRUE", "True", "1", "yes", "YES"}
_FALSE_VALUES = {"false", "FALSE", "False", "0", "no", "NO"}


class InputListError(ValueError):
    """Raised for any problem with an input list file -- always names the
    row (1-based, header excluded) and column responsible, never a bare
    parse failure. Matches the project's standing rule: never silently
    coerce or swallow a malformed input."""


@dataclass(frozen=True)
class InputRow:
    name: str
    category: str
    type: str
    phantom: bool
    model: str = ""
    notes: str = ""
    # Optional, free text like "LCL 3" or "AES50-A 12" -- where this
    # source is patched: which physical socket it is plugged into (FR-1.5's
    # io.in.{group}.{socket}). The `patch` column, or `socket` in a list
    # written.
    # Blank is legitimate: the compiler auto-assigns sequentially within a
    # default group when unstated (compiler.py), not a modeling error the
    # way a channel-number column is -- unlike channel order (a matching/
    # ordering *policy* the conventions file computes), which physical
    # jack a source is cabled into is a fact about this specific show, so
    # it belongs here, on the input list, same as model/phantom.
    patch: str = ""
    # Optional: the name of a preset in Atoo's preset library (the
    # `preset` column). Like a stated patch it is the
    # engineer's word about this row and WINS over whatever the conventions
    # and instructions led the model to choose -- `reply_expand.
    # apply_stated_presets` puts it on the channel after the reply is
    # expanded, and `verify_plan` warns when a plan disagrees. Matched the
    # forgiving way every preset name is (`presets.normalize_preset_name`),
    # and left as written here: whether the library has it is `verify`'s
    # `preset.unknown`, not a reason to refuse the list.
    preset: str = ""
    # The `order` cell as written, stripped: the band's own input number
    # ("7"), SKIP_MARK, or "" (ORDER_COLUMN above). Validated on read.
    order: str = ""

    @property
    def skipped(self) -> bool:
        """`-` in the order column: left out of the next build."""
        return self.order == SKIP_MARK

    @property
    def band_number(self) -> "int | None":
        """The band's own input number, when the order cell gives one."""
        return int(self.order) if self.order.isdigit() else None


class InputRows(list):
    """The rows a build reads -- a plain list of `InputRow` -- carrying
    the rows `-` left out as ``.skipped``, so a reader that meets a plan
    channel for one (a plan built before the row was skipped) can say
    that, rather than call it invented (`verify_plan`)."""
    skipped: list = []


def _parse_order(raw: str, *, row_num: int) -> str:
    text = raw.strip()
    if text in ("", SKIP_MARK):
        return text
    if text.isdigit() and int(text) >= 1:
        return text
    raise InputListError(
        f"row {row_num}: column 'order' must be the band's input number (1, 2, ...), "
        f"'-' to skip the row, or blank -- got {raw!r}"
    )


def _parse_bool(raw: str, *, row_num: int, column: str) -> bool:
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise InputListError(
        f"row {row_num}: column {column!r} must be TRUE or FALSE, got {raw!r}"
    )


def parse_input_list(text: str, *, include_skipped: bool = False) -> list[InputRow]:
    """Parse already-read CSV text. Raises InputListError on any problem,
    with the specific row/column at fault -- never returns a partially
    valid result.

    A row skipped with `-` in the `order` column is left out of what this
    returns, so every reader that builds, verifies or reconciles from the
    list sees the same rows the build did. It is still read and checked
    like any other row -- it stays in the file, and turning it back on
    must not surface an error nobody saw -- except that its name may
    repeat an included row's (a festival list can keep two bands' "Kick",
    one of them off). `include_skipped=True` returns every row, in file
    order: the editor's view."""
    # Excel's "CSV UTF-8" starts the file with a byte-order mark; left
    # in, it glues itself to the first column's name and that column
    # silently reads empty. The file keeps it -- Excel needs
    # it to reopen the list without garbling accents.
    reader = csv.DictReader(text.removeprefix("﻿").splitlines())
    if reader.fieldnames is None:
        raise InputListError("input list is empty -- no header row found")

    fieldnames = set(reader.fieldnames)
    patch_key = patch_column(fieldnames)
    missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        raise InputListError(
            f"input list is missing required column(s): {', '.join(missing)}"
        )
    forbidden = sorted(fieldnames & FORBIDDEN_COLUMNS)
    if forbidden:
        raise InputListError(
            "input list has column(s) it must not have: "
            + "; ".join(f"{c!r} -- {_FORBIDDEN_REASONS[c]}" for c in forbidden)
        )

    rows: list[InputRow] = []
    seen_names: set[str] = set()
    for row_num, raw_row in enumerate(reader, start=2):  # header is line 1
        name = (raw_row.get("name") or "").strip()
        category = (raw_row.get("category") or "").strip()
        type_ = (raw_row.get("type") or "").strip()
        model = (raw_row.get("model") or "").strip()
        notes = (raw_row.get("notes") or "").strip()
        patch = (raw_row.get(patch_key) or "").strip()
        preset = (raw_row.get("preset") or "").strip()
        order = _parse_order(raw_row.get(ORDER_COLUMN) or "", row_num=row_num)
        skipped = order == SKIP_MARK

        # Every blank required column at once: naming them one
        # per Save cost a round trip for each.
        blank = [repr(column) for column, value
                 in (("name", name), ("category", category), ("type", type_)) if not value]
        if blank:
            listed = (blank[0] if len(blank) == 1
                      else ", ".join(blank[:-1]) + " and " + blank[-1])
            verb = "is" if len(blank) == 1 else "are"
            raise InputListError(f"row {row_num}: {listed} {verb} required and cannot be blank")

        if not skipped:
            if name in seen_names:
                raise InputListError(f"row {row_num}: duplicate input name {name!r}")
            seen_names.add(name)

        phantom = _parse_bool((raw_row.get("phantom") or "").strip(), row_num=row_num, column="phantom")

        rows.append(
            InputRow(
                name=name,
                category=category,
                type=type_,
                phantom=phantom,
                model=model,
                notes=notes,
                patch=patch,
                preset=preset,
                order=order,
            )
        )

    if not rows:
        raise InputListError("input list has a header but no data rows")
    if include_skipped:
        return rows
    included = InputRows(row for row in rows if not row.skipped)
    included.skipped = [row for row in rows if row.skipped]
    if not included:
        raise InputListError(
            f"every row of the input list is skipped ('{SKIP_MARK}' in the 'order' column), "
            "so there is nothing to build -- clear the '-' on the rows this show uses")
    return included


def load_input_list(path: str, *, include_skipped: bool = False) -> list[InputRow]:
    with open(path, newline="", encoding="utf-8") as f:
        return parse_input_list(f.read(), include_skipped=include_skipped)


def skipped_rows(text: str) -> list[InputRow]:
    """The rows `-` in the `order` column leaves out of the next build,
    in file order. Raises InputListError as `parse_input_list` does."""
    return [row for row in parse_input_list(text, include_skipped=True) if row.skipped]


def build_text(text: str) -> str:
    """The input list as the build hands it to the model: ``text`` with
    every skipped row taken out and everything else -- the header, the
    `order` column and its numbers, quoting, line endings -- exactly as
    the file has it. A list with no skipped row comes back unchanged, to
    the byte. Raises InputListError as `parse_input_list` does."""
    from atoo.source_edit import read_records

    rows = parse_input_list(text, include_skipped=True)
    if not any(row.skipped for row in rows):
        return text
    header, records, header_end = read_records(text)
    if len(records) != len(rows):  # a parse the two readers disagree on: keep it whole
        raise InputListError("could not line the input list's rows up to leave the skipped "
                             "ones out -- check the file for a stray quote")
    head = text[:len(text) - len("".join(r.raw + r.end for r in records))]
    kept = "".join(r.raw + r.end for r, row in zip(records, rows) if not row.skipped)
    return head + kept


def skip_finding(rows: list[InputRow], where: str = "input list"):
    """The one INFO a build gives for the rows it left out (`-` in the
    `order` column), naming each; None when there are none."""
    from atoo.diagnostics import Diagnostic, Severity

    skipped = [row for row in rows if row.skipped]
    if not skipped:
        return None
    names = ", ".join(row.name for row in skipped)
    return Diagnostic(
        severity=Severity.INFO, code="input-list.skipped", where=where, source="build",
        message=(f"{len(skipped)} input-list row(s) skipped ('{SKIP_MARK}' in the 'order' "
                 f"column) and left out of this build: {names}"),
        fix="clear the '-' in a row's order cell (or untick Skip on Build step 02) "
            "to build it again",
    )


# --------------------------------------------------------------------------
# The `patch` column's own little grammar (FR-1.5): "AES50-A 12" -> ("A", 12).
#
# Moved here from compiler.py when the deterministic compile path was retired. It is input-list parsing, not plan derivation -- it reads a
# column of this file's own format -- so this is where it belonged all along;
# living in the compiler was an accident of which module needed it first.
# `verify_plan.py` is the other caller.
# --------------------------------------------------------------------------

# Physical input/output group vocabulary, confirmed against real hardware
# and Behringer's WING Remote Protocols document --
# io.in/io.out.{group}.{n}. Used for both a row's own `patch` column
# (FR-1.5's patch) and a conventions file's physical-output-socket clause
# (FR-1.9). Includes PLAY (the console's own USB-stick player, 4 sources)
# since 2026-09-10 -- a real aux.* strip's source can be PLAY.{n}, not
# just a physical jack group (confirmed against Festival_STANDALONE.snap
# alongside the rest of the aux-bank work; see wing-console-model.md).
# Still deliberately excludes OSC/REC (internal oscillator, recorder tap)
# -- neither is something a live input list or an output destination
# would ever name.
_GROUP_ALIASES = {
    "local": "LCL", "lcl": "LCL",
    "aes50a": "A", "aes50-a": "A",
    "aes50b": "B", "aes50-b": "B",
    "aes50c": "C", "aes50-c": "C",
    "stageconnect": "SC", "sc": "SC",
    "usb": "USB",
    "card": "CRD", "crd": "CRD",
    "module": "MOD", "mod": "MOD",
    "aux": "AUX",
    "user": "USR", "usr": "USR",
    "aesebu": "AES", "aes": "AES",
    "play": "PLAY",
}

# An earlier change, 2026-09-20: `"sdcard": "CRD"` was removed from the table
# above, and it is worth saying why out loud because the entry looked
# harmless for as long as it existed. **CRD is the expansion
# card, not the SD card; the SD card is used by WING LIVE** -- so an
# input list whose patch column said "SD card 3" was silently patched to
# socket 3 of the *expansion card*, a different piece of hardware, and
# nothing anywhere reported it. That is the precise failure an earlier change was filed
# about: a confident wrong friendly name producing a plausible patch
# nobody catches.
#
# With the alias gone, "SD card 3" no longer parses, and an unparsable
# socket is already reported -- `verify_plan`'s
# `patch.unparsable-stated-socket` warning says the plan's patch for that
# row could not be checked. Refusing loudly is the correct answer here
# rather than re-pointing the alias at something else, because the SD
# card is **not an input group at all**: it is the storage behind WING
# LIVE, whose patching this project cannot yet represent.
#
# `"module": "MOD"` stayed while `console_facts` dropped MOD's friendly
# label -- a deliberate asymmetry, flagged on an earlier change for the engineer to overrule
# if they disagreed. The question is moot now rather than answered: an earlier change
# settled MOD on 2026-09-21 as the AoIP module bay (Dante or WSG, 64 in
# and 64 out, `/$syscfg/opt_mod`) from the protocol PDF and our own walk,
# so both tables point the same way and "Module 3" means what the console
# means by it.
#
# **`"dante"` is deliberately NOT in the table above, and must not be
# added.** Dante is available as *either* bay -- the W-DANTE extension
# card, which is `CRD`, or the internal Dante module, which is `MOD`
# (PDF p.256). The word does not say which hardware it means, so an
# alias for it would resolve a coin-flip to one of two different pieces
# of hardware silently: the "SD card 3" mistake one slot over. `"wsg"`
# and `"aoip"` are left out for the same reason -- WSG is also both a
# card (`WDWSG`) and a module. An engineer who knows which bay theirs is
# in can write `CRD 3` or `MOD 3`, both of which parse; one who writes
# "Dante 3" gets `patch.unparsable-stated-socket` and a question, which
# is the correct outcome and is covered by a test so it stays that way.

# An earlier change, found the hard way: every entry above was a FRIENDLY name,
# so four groups the console itself names -- CRD, MOD, AUX, USR -- were
# refused by their own token. "CRD 64" is exactly how the hardware, this
# project's own `console_facts.INPUT_SOCKETS`, and the engineer all write
# that socket, and it did not parse. Guarded rather than re-fixed by
# hand: any group in the socket vocabulary must be spellable the way it
# is spelled everywhere else.
#
# A/B/C are the deliberate exception, and stay one. A bare "A 1" is
# ambiguous with a column that happens to start with a letter, and the
# whole point of `_GROUP_DISPLAY` below is that an AES50 socket is
# written with its network spelled out -- "AES50-A 1", never "A 1".
# OSC/REC stay out too, per this section's own header comment.
_SELF_SPELLABLE = {"LCL", "SC", "USB", "CRD", "MOD", "AES", "PLAY", "AUX", "USR"}
assert all(g.lower() in _GROUP_ALIASES for g in _SELF_SPELLABLE), (
    "a socket group the console names is not spellable by its own token"
)

_SOCKET_SPEC_RE = re.compile(r"^\s*(?P<group>[A-Za-z][A-Za-z0-9/\- ]*?)\s+(?P<n>\d+)\s*$")

def _normalize_group(raw: str) -> str | None:
    key = re.sub(r"[\s\-]+", "", raw.strip().lower())
    return _GROUP_ALIASES.get(key)

def parse_socket_spec(raw: str) -> tuple[str, int] | None:
    """"LCL 3" -> ("LCL", 3). None if the group isn't in the known
    vocabulary or the text doesn't match "<group> <number>" at all --
    caller's job to warn, this just refuses to guess at a malformed or
    unrecognized spec rather than silently produce something wrong."""
    m = _SOCKET_SPEC_RE.match(raw)
    if not m:
        return None
    group = _normalize_group(m.group("group"))
    if group is None:
        return None
    return group, int(m.group("n"))


# How each group is SPELLED back to a human -- the inverse of the aliases
# above, and the reason this lives next to them: a socket parsed from an
# input list and a socket printed in a finding must be the same words, or
# an operator cannot copy one into the other. Only the AES50 networks
# need a mapping; every other group's token is already how it is written.
# "AES50-A 12", never "A12" -- "AES 1" (AES/EBU, 2 sockets)
# and "AES50-A 1" are different sockets, and the one confusion this
# project has already watched a model make 19 times in a row.
_GROUP_DISPLAY = {"A": "AES50-A", "B": "AES50-B", "C": "AES50-C"}


def format_socket(group: str, n: int) -> str:
    """`("A", 12)` -> `"AES50-A 12"`; `("LCL", 3)` -> `"LCL 3"`. The exact
    spelling `parse_socket_spec` accepts, so anything this prints can be
    pasted straight back into an input list's patch column or a watch
    condition's `patch` value."""
    return f"{_GROUP_DISPLAY.get(group, group)} {n}"


# The older private spelling, kept as an alias because `verify_plan.py`
# and the tests were written against it.
_parse_socket_spec = parse_socket_spec


# --------------------------------------------------------------------------
# One patch cell, checked the way the build will read it (found in UI
# testing, 2026-09-28: step 02's Patch is edited in place, and a value that
# cannot be a socket is refused inline). This is NOT a second grammar: the
# parse is `parse_socket_spec` above, the spelling is `format_socket`, and
# the bound is `console_facts.input_socket_limit` -- the calls `verify_plan`
# and `apply` make. It only puts their verdict into words a cell can show.
# Read-only: nothing is written anywhere. `GET /api/build/validate-patch`
# (webui.py) is its only caller.
# --------------------------------------------------------------------------

# "AES50-A 15-16", "LCL 1/2", "LCL 1+2": a stereo pair in one cell. The
# grammar above takes one socket per row -- a stereo source is two rows
# (docs/user/input-lists.md) -- so this is recognised only to say that,
# rather than the bare "not <group> <number>".
_STEREO_RANGE_RE = re.compile(
    r"^\s*(?P<group>[A-Za-z][A-Za-z0-9/\- ]*?)\s+(?P<a>\d+)\s*[-/+&]\s*(?P<b>\d+)\s*$")

# The groups a person writes, in the order a refusal lists them.
_GROUP_EXAMPLES = "LCL, AES50-A, AES50-B, AES50-C, SC, USB, CRD, MOD, AUX, USR, AES, PLAY"


def check_patch(raw: str | None, console_model: str | None = None) -> dict:
    """The verdict on one input-list patch cell.

    Returns `ok`, `patch` (the canonical spelling: what `format_socket`
    prints and `parse_socket_spec` reads back), `group`, `number`, `limit`
    (the highest socket of that group on `console_model`), `model`,
    `error` (a short reason, when not ok) and `note`. A blank cell is ok:
    the build chooses a socket, and says so.

    `console_model` None checks against the console's address space
    (`console_facts.INPUT_SOCKETS`) and says so in `note`, because the
    local and aux jacks differ panel to panel. An unknown model raises
    `console_facts.UnknownConsoleModel`, as `panel_for` does.
    """
    from atoo import console_facts

    if console_model is not None:
        console_facts.panel_for(console_model)  # raises on an unknown model
    text = (raw or "").strip()
    out: dict = {"ok": False, "value": raw or "", "patch": None, "group": None,
                 "number": None, "limit": None, "model": console_model,
                 "error": None, "note": None}
    if not text:
        out.update(ok=True, patch="", note="blank: the build chooses a socket, and says so")
        return out
    parsed = parse_socket_spec(text)
    if parsed is None:
        stereo = _STEREO_RANGE_RE.match(text)
        group = _normalize_group(stereo.group("group")) if stereo else None
        if group:
            a, b = int(stereo.group("a")), int(stereo.group("b"))
            out["error"] = (f"one socket per row: a stereo source is two rows, "
                            f"{format_socket(group, a)} and {format_socket(group, b)}")
        elif _SOCKET_SPEC_RE.match(text) or stereo:
            name = (_SOCKET_SPEC_RE.match(text) or stereo).group("group").strip()
            out["error"] = f"{name!r} is not a socket group ({_GROUP_EXAMPLES})"
        else:
            out["error"] = "not '<group> <number>', e.g. LCL 3 or AES50-A 12"
        return out
    group, number = parsed
    spelled = _GROUP_DISPLAY.get(group, group)
    out.update(group=group, number=number, patch=format_socket(group, number))
    if console_model is None:
        limit = console_facts.INPUT_SOCKETS.get(group, 0)
        label = "the console"
        out["note"] = ("no console model chosen: checked against the console's address "
                       "space; LCL and AUX depend on the model")
    else:
        limit = console_facts.input_socket_limit(group, console_model)
        label = console_facts.CONSOLE_MODELS[console_model]["label"]
    out["limit"] = limit
    if limit <= 0:
        out["error"] = f"{label} has no {spelled} inputs"
    elif not 1 <= number <= limit:
        out["error"] = f"{spelled} {number} is out of range: {label} has {spelled} 1-{limit}"
    else:
        out["ok"] = True
    return out


# --------------------------------------------------------------------------
# The `preset` column: which rows feed a plan channel,
# and the preset they state for it. Shared by `reply_expand` (which puts it
# on the channel) and `verify_plan` (which checks a plan agrees), so the two
# can never read the column differently.
# --------------------------------------------------------------------------

def _row_key(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


def rows_feeding(channel: dict, rows, pair_row: "InputRow | None" = None) -> list[InputRow]:
    """The input-list rows a plan channel is made from, first row first:
    the row its `source.input` names (else its `name`, as reconciliation
    reads it), and for a stereo channel the second row too.

    The plan names only a pair's FIRST row. The second is `pair_row` when
    the caller knows it (the reply's `pair`, while it is being expanded);
    otherwise it is the row whose stated patch is the channel's other
    socket -- the same match `verify_plan`'s reconciliation makes."""
    if not isinstance(channel, dict):
        return []
    by_key = {_row_key(row.name): row for row in rows or ()}
    source = channel.get("source") if isinstance(channel.get("source"), dict) else {}
    first = by_key.get(_row_key(source.get("input") or channel.get("name")))
    out = [first] if first is not None else []
    if pair_row is not None:
        if pair_row not in out:
            out.append(pair_row)
        return out
    patch = channel.get("patch") if isinstance(channel.get("patch"), dict) else {}
    sockets = [n for n in patch.get("sockets") or [] if isinstance(n, int)]
    if source.get("stereo") and len(sockets) == 2 and patch.get("group"):
        for row in rows or ():
            if row in out or not row.patch:
                continue
            if parse_socket_spec(row.patch) == (patch["group"], sockets[1]):
                out.append(row)
                break
    return out


def stated_preset(feeding: list[InputRow]) -> "tuple[str, InputRow, list[InputRow]] | None":
    """The preset the input list states for a channel fed by `feeding`
    (from `rows_feeding`): `(name, the row it is taken from, the rows that
    state a DIFFERENT one)`, or None when no row states one.

    A stereo pair's two rows should name the same preset (compared the
    forgiving way, `presets.normalize_preset_name`). One row naming it is
    enough -- it is the channel's preset. When the two disagree, the
    FIRST row's wins: it is the row the channel is named from, and the
    one whose socket the pair is patched from. A judgement, not a physical
    error -- the strip works either way -- so it is never a refusal; the
    rows that lost are returned so the caller can say so."""
    from atoo.presets import normalize_preset_name

    stating = [row for row in feeding if row.preset]
    if not stating:
        return None
    chosen = stating[0]
    target = normalize_preset_name(chosen.preset)
    others = [row for row in stating[1:] if normalize_preset_name(row.preset) != target]
    return chosen.preset, chosen, others
