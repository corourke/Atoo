"""Comments in a conventions file or instructions.md: notes the build ignores.

The maintainer, 2026-09-25: the conventions file needs a place for notes to
himself that the build must not act on -- *"(We will EQ this so it sounds
good for a recording.)"* is a reminder, not a rule. Parentheses were
rejected for that job because the same file uses them for real rules
("(L/R, Left/Right)", a compressor's settings, "(but not drums)"). The
syntax chosen is Markdown's own: an HTML comment, ``<!-- ... -->``,
inline or across lines. Markdown previewers already hide it, so the file
reads the same in a viewer as it does to the build.

This module is the ONE place that decides what a comment is. Everything
that hands the text to a model or checks against it goes through
`strip_comments`:

  * `generate._conventions_section` -- the generator, critic and
    watchlist prompts all embed the conventions through it;
  * `conventions_audit.layers_for` -- a quote the model says it found
    only counts if it is in the text the model was given, so a quote
    that exists only inside a comment is not a rule and does not verify;
  * `webui` -- the Setup page's "View house file" on step 03, which
    shows the file as written but marks each comment as not read
    (`segments`).

**What is recorded stays whole.** `meta.conventions_stack`'s sha256 and
every byte-identity check of a file (`conventions_ref`) are over the
file's real bytes, comments included: they answer "is this the file the
plan was built from", and editing a comment is editing the file.

## What counts as a comment

``<!--`` up to the first ``-->`` after it (CommonMark's rule, so
``<!-->`` and ``<!--->`` are empty comments). Two exceptions, both
literal text rather than comments, because that is what they are in the
Markdown the file is written in:

  * inside a fenced code block (a line opening with three or more
    backticks or tildes, up to its closing fence);
  * inside an inline code span (```...```, closed by a run of the same
    number of backticks before the paragraph ends).

Indented (four-space) code blocks are NOT recognised: in a conventions
file a four-space indent is a nested bullet far more often than code,
and telling the two apart takes a full list parser.

A ``## `` line inside a comment is not a heading -- a commented-out
``## DCAs`` is not a heading (`heading_name`, `lines_inside_comments`).

## Whitespace, when a comment is removed

  * A line that held only a comment (or only a list marker and a
    comment, e.g. ``- <!-- Keys: all keys channels -->``) is removed
    whole, newline included -- no blank line, no empty bullet left
    behind. If that leaves two blank lines where there was one on each
    side, one of them goes too.
  * A comment that spans lines never joins the text before it to the
    text after it: ``rule A <!-- ...\\n... --> rule B`` keeps ``rule A``
    and ``rule B`` on separate lines.
  * An inline comment's surrounding spaces collapse to one, and a line
    it ended is right-trimmed.

## What does not strip

An ``<!--`` with no ``-->`` after it is NOT a comment that runs to the
end of the file -- one typo would silently drop every rule after it.
The text from that opener on is kept exactly as written, and
`comment_findings` raises a WARNING naming the file and line. A stray
``-->`` with no opener is kept as written too (it may be an arrow) and
noted at INFO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from atoo.diagnostics import Diagnostic, Severity

OPEN = "<!--"
CLOSE = "-->"

CODE_UNCLOSED = "conventions.unclosed-comment"
CODE_STRAY_CLOSE = "conventions.stray-comment-close"

# What the Setup page says on a comment (a tooltip and the legend).
NOT_READ_LABEL = "comment -- not read by the build"

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_BARE_MARKER = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])?\s*$")


@dataclass(frozen=True)
class Segment:
    """A run of a file's text: either read by the build, or a comment."""
    text: str
    comment: bool

    def to_dict(self) -> dict:
        return {"text": self.text, "comment": self.comment}


@dataclass(frozen=True)
class Scan:
    """One pass over a text. ``segments`` concatenate back to the text
    exactly; ``unclosed_at`` is the offset of an ``<!--`` that never
    closes (None when every one does); ``stray_closes`` are the offsets
    of ``-->`` outside any comment or code."""
    segments: tuple[Segment, ...]
    unclosed_at: int | None
    stray_closes: tuple[int, ...]


def _closes_fence(line: str, fence: str) -> bool:
    stripped = line.strip()
    return (len(line) - len(line.lstrip(" ")) <= 3
            and len(stripped) >= len(fence)
            and set(stripped) == {fence[0]})


def _closing_backticks(text: str, start: int, run: int) -> int | None:
    """Offset of the backtick run of exactly ``run`` that closes a code
    span opened just before ``start`` -- or None when the paragraph (a
    blank line) or the text ends first, in which case the opening
    backticks are literal."""
    n = len(text)
    k = start
    while k < n:
        c = text[k]
        if c == "\n":
            nxt = text.find("\n", k + 1)
            if not text[k + 1: n if nxt == -1 else nxt].strip():
                return None
        elif c == "`":
            j = k
            while j < n and text[j] == "`":
                j += 1
            if j - k == run:
                return k
            k = j
            continue
        k += 1
    return None


def scan(text: str) -> Scan:
    """Split ``text`` into read and comment segments (see the module
    docstring for the rules)."""
    text = text or ""
    n = len(text)
    segments: list[Segment] = []
    stray: list[int] = []
    unclosed: int | None = None
    fence: str | None = None
    lit_start = 0
    i = 0
    while i < n:
        if i == 0 or text[i - 1] == "\n":
            end = text.find("\n", i)
            end = n if end == -1 else end
            line = text[i:end]
            if fence is not None:
                if _closes_fence(line, fence):
                    fence = None
                i = end + 1
                continue
            m = _FENCE_OPEN.match(line)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = m.group(1)
                i = end + 1
                continue
        c = text[i]
        if c == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            close = _closing_backticks(text, j, j - i)
            i = j if close is None else close + (j - i)
            continue
        if text.startswith(OPEN, i):
            close = text.find(CLOSE, i + 2)
            if close == -1:
                unclosed = i
                break
            if i > lit_start:
                segments.append(Segment(text[lit_start:i], False))
            segments.append(Segment(text[i:close + len(CLOSE)], True))
            i = lit_start = close + len(CLOSE)
            continue
        if text.startswith(CLOSE, i):
            stray.append(i)
            i += len(CLOSE)
            continue
        i += 1
    if lit_start < n:
        segments.append(Segment(text[lit_start:], False))
    return Scan(tuple(segments), unclosed, tuple(stray))


def segments(text: str) -> list[Segment]:
    return list(scan(text).segments)


def strip_comments(text: str) -> str:
    """``text`` with every comment removed -- what a model is shown and
    what a quote is checked against. Deterministic, and a no-op on text
    with no comments. Whitespace rules are in the module docstring."""
    parts = scan(text).segments
    if not any(p.comment for p in parts):
        return text or ""
    mark = "\x00" if "\x00" not in text else "\ufffe"
    out: list[str] = []
    for part in parts:
        if not part.comment:
            out.append(part.text)
        elif "\n" in part.text:
            out.append(mark + "\n" + mark)
        else:
            out.append(mark)
    lines = "".join(out).split("\n")

    kept: list[str] = []
    dropped_after_blank = False
    for line in lines:
        if mark not in line:
            if dropped_after_blank and not line.strip():
                # A dropped line had a blank line on each side: keep one.
                dropped_after_blank = False
                continue
            dropped_after_blank = False
            kept.append(line)
            continue
        residue = line.replace(mark, "")
        if _BARE_MARKER.match(residue):
            if kept and not kept[-1].strip():
                dropped_after_blank = True
            continue
        dropped_after_blank = False
        # The tail of a comment that spanned lines starts its own line:
        # the space that separated it from the comment goes with it.
        line = re.sub(rf"^{re.escape(mark)}[ \t]+", "", line)
        line = re.sub(rf"(?<=\S)[ \t]*{re.escape(mark)}[ \t]*(?=\S)", " ", line)
        kept.append(line.replace(mark, "").rstrip())
    return "\n".join(kept)


def lines_inside_comments(text: str) -> set[int]:
    """Indexes (0-based) of the lines that START inside a comment -- a
    ``## `` there is commented out, not a heading."""
    text = text or ""
    ranges, offset = [], 0
    for part in scan(text).segments:
        if part.comment:
            ranges.append((offset, offset + len(part.text)))
        offset += len(part.text)
    if not ranges:
        return set()
    inside: set[int] = set()
    start = 0
    # keepends, so the line numbering is exactly `str.splitlines`'s --
    # the split `split_sections` makes.
    for index, line in enumerate(text.splitlines(keepends=True)):
        if any(lo < start < hi for lo, hi in ranges):
            inside.add(index)
        start += len(line)
    return inside


# A Markdown ATX heading of ANY level: up to three spaces, one to six `#`,
# whitespace, then the name (an optional closing run of `#` is dropped).
# The maintainer, 2026-09-25: "it should not matter how many hash marks there
# are" -- `# Busses`, `## Busses` and `### Busses` all start the section
# named "Busses".
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")


def heading_name(line: str) -> "tuple[int, str] | None":
    """``(level, name)`` when ``line`` is a heading, else None. The name
    has any inline comment stripped; a heading with no name is not one."""
    match = _HEADING_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    name = strip_comments(match.group(2)).strip()
    return (len(match.group(1)), name) if name else None


def _heading_lines(lines: list[str], commented: set[int]) -> dict[int, str]:
    """``{line index: section name}`` for every line that starts a
    section -- a heading of any level, outside a comment -- with ONE
    exception: the document's title. When the first non-blank line is a
    level-1 heading and it is the only level-1 heading in the file, it is
    the file's name for itself (`# atoo-rules-house.md`, which is
    how the examples from `webui.conventions_example` begin), not a
    section; it stays in the leading text before the first section."""
    found: dict[int, tuple[int, str]] = {}
    for index, line in enumerate(lines):
        if index in commented:
            continue
        parsed = heading_name(line)
        if parsed:
            found[index] = parsed
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first in found and found[first][0] == 1 \
            and sum(1 for level, _ in found.values() if level == 1) == 1:
        del found[first]
    return {index: name for index, (_, name) in found.items()}


def split_sections(text: str) -> list[tuple[str, str, list[str]]]:
    """``(name, heading line, body lines)`` split on heading lines of any
    level (`heading_name`; the document's own title excepted, see
    `_heading_lines`) that are not inside a comment, with anything before
    the first heading as
    a leading section named "". What the conventions audit names the
    part of the file a quote was found in (`conventions_audit._sections`)
    -- a label in the finding's text, never a requirement: a file with no
    headings is one leading section, and reads and audits the same."""
    commented = lines_inside_comments(text)
    lines = (text or "").splitlines()
    headings = _heading_lines(lines, commented)
    out: list[tuple[str, str, list[str]]] = [("", "", [])]
    for index, line in enumerate(lines):
        if index in headings:
            out.append((headings[index], line.rstrip(), []))
        else:
            out[-1][2].append(line)
    return out


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def comment_findings(text: str, filename: str) -> list[Diagnostic]:
    """What reading ``filename``'s comments has to say: a WARNING for an
    ``<!--`` that never closes (the text from it on is read as written,
    comment and all), an INFO for each stray ``-->``. Empty for a file
    whose comments are all well formed -- the ordinary case."""
    result = scan(text)
    out: list[Diagnostic] = []
    if result.unclosed_at is not None:
        line_no = _line_of(text, result.unclosed_at)
        line = text.splitlines()[line_no - 1] if text.splitlines() else ""
        out.append(Diagnostic(
            severity=Severity.WARNING, code=CODE_UNCLOSED,
            where=f"{filename} line {line_no}", line=line.strip(),
            message=(f"A comment opened here with {OPEN} never closes with {CLOSE}. "
                     "Rather than drop everything after it, the build "
                     "reads the rest of the file as written, the unfinished comment "
                     "included -- so a note there will be read as if it were a rule."),
            fix=f"close the comment with {CLOSE}, or delete the {OPEN}",
            source="build"))
    for offset in result.stray_closes:
        line_no = _line_of(text, offset)
        out.append(Diagnostic(
            severity=Severity.INFO, code=CODE_STRAY_CLOSE,
            where=f"{filename} line {line_no}",
            line=text.splitlines()[line_no - 1].strip(),
            message=(f"A {CLOSE} here has no {OPEN} before it. "
                     "It is read as written (it may be an arrow); if it was meant to end a "
                     "comment, the comment is not one."),
            fix=f"add the missing {OPEN}, or ignore this if the {CLOSE} is an arrow",
            source="build"))
    return out
