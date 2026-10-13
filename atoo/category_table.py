"""The Category table: the resolved conventions' per-category channel
settings, as data code applies (2026-09-30; FR-1.18a).

Why: on three real Sonnet builds with the resolved conventions
(`conventions_resolve.py`), the interpretation work was gone, and most of
the generator's remaining thinking -- 10-12K tokens on festival and
sixpiece -- went to applying the same category rules channel by
channel: "drums: HPF 40, DCA Drums, mute group Band, gain 20, trim 0,
fader down", thirty times. And it still left stated defaults null (the
critic's "all faders down" left null on every channel). Prompt wording
did not fix either. The maintainer approved moving the application
into code.

So the resolve step writes, as the LAST section of the resolved file,

    ## Category table

    ```json
    [{"name": "Keyboards", "aliases": ["keys", "keyboards"], "color": "Cyan",
      "hpf_hz": 80, "dca": ["Keys"], "mute_group": ["Band"], "gain_db": 20,
      "trim_db": 0, "fader_db": -144, "main_direct": true}, ...]
    ```

one object per category, restating the prose `## Categories` section for
the fields that are plain per-channel values of the compact reply. It
cites nothing -- the check (`conventions_resolve.check`) runs on the
prose -- and it is never shown to the generator as JSON: `strip` takes
it out of the text the generator reads, and `prompt_note` renders the
entries the show's input list uses in the reply's own field names.

`reply_expand.apply_category_table` fills, on each channel built from an
input-list row whose category is one of an entry's `aliases`, every
field the reply LEFT OUT or wrote null. A value the reply wrote wins: it
is the model's exception.

**The fields** (every one optional; a field left out, or null, is not
applied -- the reply's own default stands, and the model owns it):

  aliases      the input-list category words the entry matches, case-
               insensitive. Required. A word in two entries is ambiguous,
               and the table is refused.
  color        the channel colour.
  hpf_hz       the high-pass frequency. Not on an aux strip, which has
               no filter node.
  dca          DCA names.
  mute_group   mute-group names.
  gain_db      head-amp gain. Only on a socket with a head amp
               (`console_facts.PHANTOM_CAPABLE_GROUPS`): a digital
               source has none.
  trim_db      trim.
  fader_db     the channel fader (-144 is fully down).
  main_direct  true: routed straight to Main 1; false: reaches Main only
               through its busses. Left out when it depends on the show
               (a bus made only for several keyboards).

Monitor sends, mix-bus membership and FX sends are NOT here: they are
written on the busses (`reply_expand.expand_sends`) and stay the
model's.

**An invalid table** (not JSON, not the shape above, an alias in two
entries) is not applied at all: one WARNING (`category-table.invalid`),
and the build proceeds exactly as it did before the table existed. **No
table** -- a resolved file made before 2026-09-30's prompt -- is one INFO
(`category-table.missing`). `--no-category-rules` /
`ATOO_CATEGORY_RULES=0` ignores the table and leaves the generator's
prompt as it was, for the A/B.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from atoo import console_facts as facts
from atoo.diagnostics import Diagnostic, Severity
from atoo.schema_check import validate as validate_schema

ENV = "ATOO_CATEGORY_RULES"
HEADING = "Category table"

CODE_INVALID = "category-table.invalid"
CODE_MISSING = "category-table.missing"
CODE_APPLIED = "reply.category-rule"

# The fields an entry may carry, in the order a person reads them.
FIELDS = ("color", "hpf_hz", "dca", "mute_group", "gain_db", "trim_db", "fader_db",
          "main_direct")

_NAMES = {"type": "array", "items": {"type": "string", "minLength": 1}}

ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "aliases": {"type": "array", "items": {"type": "string", "minLength": 1},
                    "minItems": 1},
        "color": {"type": ["string", "null"], "minLength": 1},
        "hpf_hz": {"type": ["number", "null"],
                   "minimum": facts.HPF_HZ_RANGE[0], "maximum": facts.HPF_HZ_RANGE[1]},
        "dca": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "mute_group": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "gain_db": {"type": ["number", "null"],
                    "minimum": facts.HEAD_AMP_GAIN_DB_RANGE[0],
                    "maximum": facts.HEAD_AMP_GAIN_DB_RANGE[1]},
        "trim_db": {"type": ["number", "null"],
                    "minimum": facts.TRIM_DB_RANGE[0], "maximum": facts.TRIM_DB_RANGE[1]},
        "fader_db": {"type": ["number", "null"],
                     "minimum": facts.FADER_DB_RANGE[0], "maximum": facts.FADER_DB_RANGE[1]},
        "main_direct": {"type": ["boolean", "null"]},
    },
    "required": ["name", "aliases"],
    "additionalProperties": False,
}

SCHEMA = {"type": "array", "items": ENTRY_SCHEMA, "minItems": 1}

# `## Category table` up to the next `## ` heading (or the end).
_SECTION_RE = re.compile(r"^##[ \t]+" + re.escape(HEADING) + r"[ \t]*\n(.*?)(?=^##[ \t]|\Z)",
                         re.M | re.S | re.I)
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)[\w-]*[ \t]*\n(.*?)^[ \t]*\1[ \t]*$", re.M | re.S)


def enabled(env=None) -> bool:
    """`ATOO_CATEGORY_RULES`: unset or anything but 0/off/false/no is on."""
    env = os.environ if env is None else env
    raw = str(env.get(ENV, "") or "").strip().casefold()
    return raw not in ("0", "off", "false", "no")


def norm(word) -> str:
    return re.sub(r"\s+", " ", str(word)).strip().casefold()


@dataclass
class Table:
    """A checked Category table."""
    entries: list[dict]
    by_alias: dict[str, dict] = field(default_factory=dict)

    def entry_for(self, category) -> dict | None:
        return self.by_alias.get(norm(category or ""))


@dataclass
class Parsed:
    table: Table | None
    findings: list[Diagnostic]
    state: str            # "valid", "invalid" or "missing"
    reason: str = ""

    def meta(self, *, applied: bool, off_reason: str | None = None) -> dict:
        """`meta.resolved_conventions.category_table`, for the A/B."""
        out: dict = {"state": self.state, "applied": applied}
        if self.table is not None:
            out["categories"] = len(self.table.entries)
        if self.reason:
            out["reason"] = self.reason
        if off_reason:
            out["off"] = off_reason
        return out


def section(text: str) -> str | None:
    """The `## Category table` section's body, or None."""
    match = _SECTION_RE.search(text or "")
    return match.group(1) if match else None


def strip(text: str) -> str:
    """`text` without its `## Category table` section: the generator reads
    the prose; what code applies is told it by `prompt_note`."""
    return _SECTION_RE.sub("", text or "").rstrip()


def parse(text: str, *, resolved_name: str = "resolved conventions") -> Parsed:
    """The resolved file's Category table, checked. Never raises."""
    body = section(text)
    if body is None:
        return Parsed(None, [Diagnostic(
            severity=Severity.INFO, code=CODE_MISSING, where=resolved_name, source="build",
            message=(f"{resolved_name} has no '## {HEADING}' section (it was made before code "
                     "applied the per-category settings), so code applies none: the generator "
                     "writes every channel's settings, as before"),
            fix="resolve again (`atoo resolve`) to add the table")],
            "missing", "no table")

    def invalid(reason: str) -> Parsed:
        return Parsed(None, [Diagnostic(
            severity=Severity.WARNING, code=CODE_INVALID, where=f"{resolved_name} § {HEADING}",
            source="build",
            message=(f"the Category table in {resolved_name} is not used: {reason}. Code "
                     "applies no per-category setting; the generator writes every channel's "
                     "settings, as before"),
            fix="resolve again (`atoo resolve`)")], "invalid", reason)

    fence = _FENCE_RE.search(body)
    raw = fence.group(2) if fence else body
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return invalid(f"it is not JSON ({exc})")
    if isinstance(data, dict) and isinstance(data.get("categories"), list):
        data = data["categories"]
    violations = validate_schema(data, SCHEMA, path="table")
    if violations:
        more = f" (and {len(violations) - 3} more)" if len(violations) > 3 else ""
        return invalid("; ".join(violations[:3]) + more)
    by_alias: dict[str, dict] = {}
    for entry in data:
        for alias in entry["aliases"]:
            key = norm(alias)
            other = by_alias.get(key)
            if other is not None and other is not entry:
                return invalid(f"the category word {alias!r} is an alias of both "
                               f"{other['name']!r} and {entry['name']!r}")
            by_alias[key] = entry
    return Parsed(Table(list(data), by_alias), [], "valid")


_PLAIN = {"color": "colour", "hpf_hz": "HPF", "dca": "DCA", "mute_group": "mute group",
          "gain_db": "gain", "trim_db": "trim", "fader_db": "fader",
          "main_direct": "Main routing"}


def fields_named(table: Table) -> str:
    """The fields some entry of `table` sets, in words: "colour, HPF and
    gain"."""
    names = [_PLAIN[key] for key in FIELDS
             if any(e.get(key) is not None and e.get(key) != [] for e in table.entries)]
    if not names:
        return "nothing"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------------------
# what the generator is told
# ---------------------------------------------------------------------------

def reply_fields(entry: dict) -> list[str]:
    """The entry's values in the reply's own field names, as the generator
    would write them: `hpf_hz 80`, `dca ["Keys"]`, `main_routes [{"index":1}]`."""
    out: list[str] = []
    for key in FIELDS:
        value = entry.get(key)
        if value is None or (isinstance(value, list) and not value):
            continue
        if key == "main_direct":
            out.append('main_routes [{"index":1}]' if value else "main_routes []")
        elif isinstance(value, list):
            out.append(f"{key} {json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, float) and value.is_integer():
            out.append(f"{key} {int(value)}")
        else:
            out.append(f"{key} {value}")
    return out


def prompt_note(table: Table, categories: list[str]) -> str:
    """The generator's instruction: what code writes for each input-list
    category this show uses, and which categories it does not cover.
    `categories` are the input list's category words, in row order."""
    seen: list[str] = []
    for word in categories:
        if norm(word) and norm(word) not in (norm(s) for s in seen):
            seen.append(word)
    covered = [(w, table.entry_for(w)) for w in seen if table.entry_for(w) is not None]
    lines = [f"- {word}: {', '.join(reply_fields(entry)) or 'nothing'} ({entry['name']})"
             for word, entry in covered]
    uncovered = [w for w in seen if table.entry_for(w) is None]
    text = ("## What code writes for you\n\n"
            "Code applies the Category table to every channel by its category: leave those "
            "fields out unless a channel is an exception. For each input-list category "
            "below, code writes these values on every channel of it whose reply leaves the "
            "field out or null (`color` by category, so no `category_colors` entry is "
            "needed for it). A value you write wins. An aux strip gets no `hpf_hz`, a socket "
            "with no head amp no `gain_db`, and a click, guide or talkback strip no "
            "`main_routes` from it. A field not listed for a category is yours to write.\n\n"
            + ("\n".join(lines) if lines else "- none"))
    if uncovered:
        text += ("\n\nNot covered, so write every field yourself: "
                 + ", ".join(uncovered) + ". So too for a channel not on the input list.")
    else:
        text += "\n\nA channel not on the input list is not covered: write its fields yourself."
    return text
