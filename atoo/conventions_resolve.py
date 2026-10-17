"""Resolved conventions: one clear text in place of the conventions and the
domain knowledge (2026-09-30, an experiment to A/B against today's builds).

Why: across three real Sonnet builds (smallband, festival, sixpiece),
40-55% of the generator's thinking in EVERY show went to re-deriving the
same reading of the house conventions -- per-category HPF, DCA, mute
group, monitor sends, "in a mix bus, so no direct Main route", head-amp
scope, whether an empty group is declared, where Talkback goes. That work
does not depend on the show. The proposal: generate a
replacement, exceedingly clear prompt that replaces both the domain and
conventions text, re-made only when either changes.

So one model call, its own role `resolve`, reads the house conventions and
the domain knowledge (`generate._domain_knowledge`) and writes
`<conventions stem>.resolved.md` beside the conventions file. It is PROSE,
not a schema -- the original fixed-vocabulary conventions IR was abandoned,
and nothing
here parses a rule's meaning. In the prose, code relies on two pieces of syntax:

  * a citation, `[conventions: "..."]` or `[domain: "..."]`, the verbatim
    text a rule rests on (`citations_in`);
  * the heading `## Lines with no effect`, whose citations are the
    conventions lines that yield no rule.

and two JSON blocks code applies, each its own module's: the `## Category
table` (`category_table.py`) and the `## Instructed strips`
(`instructed_channels.py`, 2026-10-01) -- the strips the conventions ask
for that are not input-list rows, which code builds. Each strip's quote
is checked here like any citation. Both blocks are taken out of the text
the generator reads (`prompt_text`).

And on a machine-readable header, an HTML comment the model never sees:

    <!-- atoo resolved conventions
    conventions: conventions.md
    conventions_sha256: ...   the conventions as the model reads them
    domain_sha256: ...        the domain knowledge file
    prompt_sha256: ...        prompts/conventions_resolve.md, as sent
    model: claude-sonnet-5
    effort: medium
    made: 2026-09-30T12:00:00Z
    -->

**Fresh** means the three sha256s match what the build would send now.
The model and effort are recorded, not compared: a file resolved on one
model stays fresh for a build on another (INFO, decided here: the A/B
must compare the generator with and without the SAME resolved text, and
a re-resolve per model would change both arms at once). A hand edit to
the resolved file is kept until one of the three inputs changes.

## What code checks (`check`)

Every citation is looked for in its text (`conventions_audit.locate`, the
same folding every other quote check uses). Every substantive conventions
line -- not blank, not a heading, not a comment -- must be cited by some
rule or listed under "Lines with no effect". A citation shorter than
`instructed_channels.MIN_QUOTE_WORDS` words covers a line only when it is
the whole line: a fragment like "Blue" is in several lines and says which
one of them nothing about.

A citation not found is a WARNING (`resolve.quote-not-found`): the rule
citing it may be the resolver's own, not the engineer's, and the
generator would follow it. A line not covered is an INFO
(`resolve.line-not-covered`, decided): the generator is given
that line verbatim, so nothing is lost and the board is not at risk --
it says only that the resolved file is not the whole story. A list item
is compared without its bullet, on the line and in the quote alike, and a
lead-in line ending in a colon is covered when any item indented under it
is. A preset-map item -- a line indented under a lead-in that names
presets, quoting a preset name ("- Kick: \"Kick In\"") or saying "no
preset" -- is covered when every name it quotes is in the preset library,
cited or not: the preset choice consumes it, not a resolved rule, and the
resolver cites such lines in one run and not the next. One
naming a preset the library has not got is still a note, and says that.
Both are printed and kept in `meta.build_findings`. **The file is
still used** (decided, INFO): it
is a readable artifact the engineer reviews, the critic still reads the
RAW conventions and so checks the interpretation independently, and an
uncovered line is not lost -- it is appended to the generator's text
verbatim under its own heading (`prompt_text`), so the generator reads
every line either way. The file is refused, and the build falls back to
the raw conventions and domain knowledge (`resolve.refused`), only when
it cannot be a resolution at all: it is empty, or not one of its
citations is found in either text.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import unicodedata
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from atoo import conventions_audit
from atoo import conventions_text
from atoo.diagnostics import Diagnostic, Severity

RESOLVE_ENV = "ATOO_RESOLVE"
PROMPT = "conventions_resolve.md"
ROLE = "resolve"
SUFFIX = ".resolved.md"
HEADER_TAG = "atoo resolved conventions"
NO_EFFECT_HEADING = "Lines with no effect"

CODE_QUOTE = "resolve.quote-not-found"
CODE_UNCOVERED = "resolve.line-not-covered"
CODE_REFUSED = "resolve.refused"
CODE_LIBRARY_UNREADABLE = "resolve.preset-library-unreadable"
CODE_FAILED = "resolve.failed"
CODE_NOT_WRITTEN = "resolve.not-written"

FINGERPRINT_KEYS = ("conventions_sha256", "domain_sha256", "prompt_sha256")

# `[conventions: "..."]`, `[domain: "..."]` ("domain knowledge" too), with
# straight or curly quotes. The quote ends at the first `"]`, so a quoted
# name inside it ("Drums Comp") does not end it early.
_CITATION_RE = re.compile(
    r"\[\s*(conventions|domain(?:[ -]knowledge)?)\s*:\s*[\"“](.+?)[\"”]\s*\]",
    re.IGNORECASE)
_HEADER_RE = re.compile(r"<!--\s*" + re.escape(HEADER_TAG) + r"\s*\n(.*?)-->", re.S)
_FENCED_RE = re.compile(r"\A\s*(```|~~~)[\w-]*[ \t]*\n(.*)\n\1[ \t]*\s*\Z", re.S)


# ---------------------------------------------------------------------------
# settings and paths
# ---------------------------------------------------------------------------

def enabled(env=None) -> bool:
    """`ATOO_RESOLVE`: unset or anything but 0/off/false/no is on."""
    env = os.environ if env is None else env
    raw = str(env.get(RESOLVE_ENV, "") or "").strip().casefold()
    return raw not in ("0", "off", "false", "no")


def resolved_path(conventions_path: "str | Path") -> Path:
    """`my-show/conventions.md` -> `my-show/conventions.resolved.md`."""
    path = Path(conventions_path)
    return path.with_name(path.stem + SUFFIX)


def _sha(text: str) -> str:
    """sha256 of `text` with line endings and Unicode form made one
    spelling, so the same words hash the same on any machine: a Windows
    checkout's CRLF, or an editor that saves accents decomposed, must not
    cost a re-resolve. Both are no-ops on an LF, NFC file, which is every
    file here -- no existing fingerprint changes."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def made_by() -> str:
    """Which Atoo wrote a resolved file: the package version, and the
    git commit when it runs from a checkout. Recorded in the header so a
    file that reads stale on another machine says what made it (2026-10-02: one resolve on
    one machine hashed what no committed code
    or text produces -- most likely a checkout not yet pulled)."""
    from atoo import __version__
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent,
            capture_output=True, text=True, timeout=2, encoding="utf-8").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return f"{__version__} ({commit})" if commit else __version__


def conventions_for_model(conventions_raw: str) -> str:
    """The conventions as the resolve call reads them: comments stripped
    (`conventions_text.strip_comments`), as every model-facing reader does.
    Its sha256 is the fingerprint's, so editing a note to yourself does
    not cost a re-resolve."""
    return conventions_text.strip_comments(conventions_raw or "")


def fingerprint(conventions_raw: str) -> dict:
    """The three sha256s a resolved file is fresh against."""
    from atoo import generate

    return {
        "conventions_sha256": _sha(conventions_for_model(conventions_raw)),
        "domain_sha256": _sha(generate._domain_knowledge()),
        "prompt_sha256": _sha(resolve_system()),
    }


# ---------------------------------------------------------------------------
# the header
# ---------------------------------------------------------------------------

def render_header(values: dict) -> str:
    lines = [f"<!-- {HEADER_TAG}"]
    lines += [f"{key}: {value}" for key, value in values.items() if value is not None]
    lines.append("Made by Atoo from the conventions and the domain knowledge; made "
                 "again when either changes. Edit the conventions, not this file.")
    lines.append("-->")
    return "\n".join(lines)


def parse_header(text: str) -> dict | None:
    """The header's `key: value` lines, or None when the file has none."""
    match = _HEADER_RE.search(text or "")
    if not match:
        return None
    out: dict = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and re.fullmatch(r"[a-z_0-9]+", key.strip()):
            out[key.strip()] = value.strip()
    return out


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

@dataclass
class Freshness:
    """Where a build stands with the resolved file, before any call."""
    path: Path
    state: str               # "fresh", "stale", "missing" or "unreadable"
    reason: str              # for the message: what changed, or why unreadable
    fingerprint: dict
    text: str | None = None
    header: dict | None = None

    @property
    def fresh(self) -> bool:
        return self.state == "fresh"


def freshness(conventions_path: "str | Path", conventions_raw: str) -> Freshness:
    path = resolved_path(conventions_path)
    fp = fingerprint(conventions_raw)
    if not path.is_file():
        return Freshness(path, "missing", "there is no resolved file yet", fp)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Freshness(path, "unreadable", f"it could not be read ({exc})", fp)
    header = parse_header(text)
    if header is None:
        return Freshness(path, "stale", "it has no Atoo header to check", fp, text, None)
    changed = [key for key in FINGERPRINT_KEYS if header.get(key) != fp[key]]
    if changed:
        names = {"conventions_sha256": "the conventions", "domain_sha256": "the domain knowledge",
                 "prompt_sha256": "the resolve prompt"}
        reason = " and ".join(names[k] for k in changed) + " changed"
        now = made_by()
        if header.get("atoo") and header["atoo"] != now:
            reason += f"; it was made by Atoo {header['atoo']}, and this is {now}"
        return Freshness(path, "stale", reason, fp, text, header)
    return Freshness(path, "fresh", "the conventions, the domain knowledge and the resolve "
                     "prompt are unchanged", fp, text, header)


# ---------------------------------------------------------------------------
# the model call
# ---------------------------------------------------------------------------

def resolve_system() -> str:
    from atoo import generate

    return generate.load_prompt(PROMPT)


def resolve_user(conventions_raw: str, conventions_name: str) -> str:
    from atoo import generate

    return f"""\
# The engineer's conventions ({conventions_name})

{conventions_for_model(conventions_raw).strip()}

---

# Audio domain knowledge

{generate._domain_knowledge().strip()}

---

Write the resolved conventions now."""


def _clean_reply(raw: str) -> str:
    """The reply as a document: an outer code fence around the whole of
    it removed, and any header of ours it echoed dropped."""
    text = (raw or "").strip()
    match = _FENCED_RE.match(text)
    if match:
        text = match.group(2).strip()
    return _HEADER_RE.sub("", text).strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(conventions_raw: str, conventions_name: str, *, provider,
        now: str | None = None) -> str:
    """One `resolve` call; returns the whole file (header + document).
    Raises what the provider raises."""
    fp = fingerprint(conventions_raw)
    raw = provider.complete(system=resolve_system(),
                            user=resolve_user(conventions_raw, conventions_name),
                            response_schema=None, label=ROLE)
    model_for = getattr(provider, "model_for", None)
    effort_for = getattr(provider, "effort_for", None)
    header = render_header({
        "conventions": conventions_name,
        **fp,
        "model": (model_for(ROLE) if callable(model_for) else getattr(provider, "model", None)),
        "effort": effort_for(ROLE) if callable(effort_for) else None,
        "made": now or _now(),
        "atoo": made_by(),
    })
    body = _clean_reply(raw)
    return (f"{header}\n\n# Resolved conventions ({conventions_name})\n\n{body}\n")


# ---------------------------------------------------------------------------
# the check
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Citation:
    kind: str        # "conventions" or "domain"
    quote: str
    line: int        # 1-based line of the resolved file
    section: str     # the resolved file's heading it sits under
    found: bool


@dataclass
class Check:
    citations: list[Citation] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)   # conventions lines, as written
    substantive: int = 0
    findings: list[Diagnostic] = field(default_factory=list)
    refused: str | None = None
    # Preset-map lines no rule cites whose presets are all in the library
    # (or that say "no preset"): covered by the preset choice, so not in
    # `uncovered` and not a note, but still given to the generator
    # verbatim (`verbatim`), as an uncovered line is.
    preset_lines: list[str] = field(default_factory=list)
    # Every line no rule cites, in conventions order: what `prompt_text`
    # appends for the generator. `uncovered` plus `preset_lines`.
    verbatim: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[Citation]:
        return [c for c in self.citations if not c.found]

    @property
    def usable(self) -> bool:
        return self.refused is None

    def summary(self) -> str:
        found = sum(1 for c in self.citations if c.found)
        covered = self.substantive - len(self.uncovered)
        by_presets = (f" ({len(self.preset_lines)} of them preset-map line(s) whose presets "
                      "are in the library)" if self.preset_lines else "")
        return (f"{found} of {len(self.citations)} citation(s) found; {covered} of "
                f"{self.substantive} conventions line(s) covered{by_presets}")


# One citation naming several lines: `[conventions: "a" / "b"]`.
_JOINED_RE = re.compile(r"[\"”]\s*/\s*[\"“]")


def citations_in(text: str) -> list[tuple[str, str]]:
    """Every `(kind, quote)` cited in `text`, kind "conventions" or
    "domain". A citation joining several quotes with " / " is one quote
    per part."""
    return [("conventions" if m.group(1).lower().startswith("conv") else "domain",
             part.strip())
            for m in _CITATION_RE.finditer(text or "")
            for part in _JOINED_RE.split(m.group(2)) if part.strip()]


def _substantive(line: str) -> bool:
    return bool(line.strip()) and conventions_text.heading_name(line) is None \
        and any(ch.isalnum() for ch in line)


def _covered_lines(conventions: str, quotes: list[str]) -> set[int]:
    """Indexes of the conventions lines the quotes cover. A quote covers
    each line any occurrence of it overlaps (so a quote across two lines
    covers both); one under `MIN_QUOTE_WORDS` words only a line it is the
    whole of -- or, on a list line, one whole item of it, when at least
    half the line's items (and two) are quoted that way."""
    from atoo.instructed_channels import MIN_QUOTE_WORDS, clean_quote

    lines = conventions.splitlines()
    spans: list[tuple[int, int, int]] = []
    joined = ""
    for i, line in enumerate(lines):
        n = conventions_audit.normalise(line)
        if not n:
            continue
        if joined:
            joined += " "
        spans.append((len(joined), len(joined) + len(n), i))
        joined += n
    bare = {i: conventions_audit.normalise(clean_quote(_unlisted(line)))
            for i, line in enumerate(lines)}
    covered: set[int] = set()
    short: set[str] = set()
    for quote in quotes:
        core = conventions_audit._quote_core(quote)
        parts = conventions_audit.segments(core)
        if len(parts) > 1:
            # An elided quote ("Color coding: Drums-Red...Speech-Purple")
            # covers the stretch from its first part to its last, found in
            # order, when its parts together are long enough to be a quote.
            if sum(len(p.split()) for p in parts) < MIN_QUOTE_WORDS:
                continue
            at, first = 0, None
            for part in parts:
                at = joined.find(part, at)
                if at == -1:
                    break
                first = at if first is None else first
                at += len(part)
            else:
                covered.update(i for s, e, i in spans if s < at and e > first)
            continue
        # A quoted list item carries its bullet ("- Snare: \"Snare\"", the
        # resolver quoting the line as written). The bullet is
        # not a word and not the engineer's text: it is taken off the
        # quote as it is off the line, before either is counted or
        # compared.
        core = _unlisted(core)
        if not core:
            continue
        if len(core.split()) < MIN_QUOTE_WORDS:
            want = conventions_audit.normalise(clean_quote(core))
            covered.update(i for i, b in bare.items() if b and b == want)
            short.add(want)
            continue
        start = joined.find(core)
        while start != -1:
            end = start + len(core)
            covered.update(i for s, e, i in spans if s < end and e > start)
            start = joined.find(core, start + 1)
    # A list line ("Color coding: Drums-Red, Bass-Blue, ...") is cited an
    # item at a time, each too short to cover a line alone (the
    # 2026-10-01 resolve). It is covered when at least half its items,
    # and at least two, are each quoted whole.
    for i, line in enumerate(lines):
        if i in covered:
            continue
        items = [conventions_audit.normalise(part) for part in
                 _LIST_ITEM_RE.split(_unlisted(line))]
        items = [item for item in items if item]
        if len(items) < 2:
            continue
        quoted = sum(1 for item in items if item in short)
        if quoted >= max(2, (len(items) + 1) // 2):
            covered.add(i)
    # A lead-in ("- Default channel presets by source, from my preset
    # library:") only introduces the indented items under it, and says
    # nothing they do not: it is covered when any of its items is. Its items' own coverage is checked line by line.
    for i, line in enumerate(lines):
        if i in covered or not line.rstrip().endswith(":"):
            continue
        if any(j in covered for j in _items_under(lines, i)):
            covered.add(i)
    return covered


# A Markdown list marker or block-quote mark at the start of a line or a
# quote: "- ", "* ", "+ ", "> ", "1. ", "2) ". Only followed by a space,
# so the minus of "-18dB" is kept.
_LIST_MARKER_RE = re.compile(r"^\s*(?:(?:[-*+>]|\d+[.)])\s+)+")


def _unlisted(text: str) -> str:
    """`text` stripped, without the list marker or heading marks it
    starts with: "- Snare: \"Snare\"" -> "Snare: \"Snare\""."""
    text = _LIST_MARKER_RE.sub("", text.strip())
    return text.lstrip("#").strip() if text.startswith("#") else text


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _items_under(lines: list[str], i: int) -> list[int]:
    """The indexes of the lines indented under line `i`, up to the first
    non-blank line that is not."""
    own = _indent(lines[i])
    out = []
    for j in range(i + 1, len(lines)):
        if not lines[j].strip():
            continue
        if _indent(lines[j]) <= own:
            break
        out.append(j)
    return out


# What separates the items of a list line: commas, semicolons, and the
# colon after a label ("Color coding: Drums-Red, ...").
_LIST_ITEM_RE = re.compile(r"[,;:]")


# A quoted name in a preset-map item: double quotes, straight or curly,
# or single ones. A single quote only opens after a
# non-word character and only closes before one, so the apostrophe of
# "Kick's" or "Drummer's" is never read as a quote.
_QUOTED_NAME_RE = re.compile(
    r"[\"“]([^\"“”]+)[\"”]|(?<!\w)['‘]([^'‘’]+)['’](?!\w)")
_NO_PRESET_RE = re.compile(r"\bno\s+preset\b", re.IGNORECASE)

# What a preset-map item may say besides its names: the names
# themselves, with a few connecting words ("for the high (or only) rack
# tom"). A number, a processing word, or a long stretch of prose is a rule,
# and a rule the resolver did not cite is not carried out by the preset
# choice, so the item is not covered by the library.
_RULE_WORD_RE = re.compile(
    r"\d|\b(?:db|hz|khz|ms|boost\w*|cut|cuts|raise\w*|lower\w*|reduc\w*|increas\w*|more|less|"
    r"louder|quieter|gain|trim|fader|mute\w*|pan|filter\w*|hpf|lpf|eq|compress\w*|gate\w*|"
    r"reverb|delay|threshold|ratio|start|always|never|must|should)\b", re.IGNORECASE)
_MAX_CONNECTIVE_WORDS = 10

_BUS_WORD_RE = re.compile(r"\bbus(?:es|ses|s)?\b", re.IGNORECASE)
_CHANNEL_WORD_RE = re.compile(r"\bchannels?\b", re.IGNORECASE)


@dataclass(frozen=True)
class MapItem:
    """One preset-map item: the names it quotes (`()` for "no preset"),
    the lead-in line it sits under, which preset kinds it can name
    (`"channel"` and/or `"bus"`: a bus-preset lead-in is looked up among
    the `.bus` files, a channel one among the `.chn`, one that says both,
    or neither, among both), and `rule_text`, whatever else it says that is
    more than connecting prose ("" when nothing)."""

    names: tuple[str, ...]
    lead_in: int
    kinds: frozenset
    rule_text: str = ""


def _kinds_of(lead_in: str) -> frozenset:
    bus, channel = bool(_BUS_WORD_RE.search(lead_in)), bool(_CHANNEL_WORD_RE.search(lead_in))
    if bus and not channel:
        return frozenset({"bus"})
    if channel and not bus:
        return frozenset({"channel"})
    return frozenset({"channel", "bus"})


def _rule_text(rest: str) -> str:
    """What `rest` (an item without its label) says besides the names it
    quotes and light connecting prose: "" for none, else the offending
    stretch ("and get 3 dB more at 3k")."""
    rest = _NO_PRESET_RE.sub(" ", _QUOTED_NAME_RE.sub(" | ", rest))
    for piece in rest.split("|"):
        piece = re.sub(r"\s+", " ", piece).strip(" \t.,;:-()")
        if piece and (_RULE_WORD_RE.search(piece) or len(piece.split()) > _MAX_CONNECTIVE_WORDS):
            return piece
    return ""


def preset_map_items(conventions: str) -> dict[int, MapItem]:
    """The preset map's items: line index -> the `MapItem`.

    The map is the items indented under a lead-in line that ends in a
    colon and mentions a preset ("- Default channel presets by source,
    from my preset library:"). An item's names are the quoted ones after
    its label's colon ("Kick: \"Kick In\"" -> ["Kick In"]), or anywhere in
    it when it has no colon ("Generic sax \"B Sax\""), so a quoted label
    is not read as a preset. An item that quotes nothing and does not say
    "no preset" is not a map entry, and is checked like any other line."""
    lines = conventions.splitlines()
    out: dict[int, MapItem] = {}
    for i, line in enumerate(lines):
        if not line.rstrip().endswith(":") or "preset" not in line.casefold():
            continue
        kinds = _kinds_of(line)
        for j in _items_under(lines, i):
            item = _unlisted(lines[j])
            _label, colon, rest = item.partition(":")
            rest = rest if colon else item
            names = [(m[0] or m[1]).strip() for m in _QUOTED_NAME_RE.findall(rest)
                     if (m[0] or m[1]).strip()]
            if names or _NO_PRESET_RE.search(item):
                out[j] = MapItem(tuple(names), i, kinds, _rule_text(rest))
    return out


def _library_names(preset_library) -> "tuple[dict[str, set[str] | None], str]":
    """The names in `preset_library`, normalised as a lookup normalises
    them (`presets.normalize_preset_name`), by kind: `{"channel": {...},
    "bus": {...}}`, a kind None when its files cannot be read (a file
    that is damaged, a directory that is gone), with the reason ("" when
    all could be read). With no library, every kind is None and the reason
    empty -- the build says `preset.no-library` on its own."""
    if preset_library is None:
        return {"channel": None, "bus": None}, ""
    from atoo.presets import PresetError, normalize_preset_name

    names: "dict[str, set[str] | None]" = {}
    reasons: list[str] = []
    for kind, read in (("channel", lambda: preset_library.names()),
                       ("bus", lambda: [p.name for p in preset_library.bus_presets()])):
        try:
            names[kind] = {normalize_preset_name(n) for n in read()}
        except (PresetError, OSError, ValueError) as exc:
            names[kind] = None
            reason = str(exc) or type(exc).__name__
            if reason not in reasons:
                reasons.append(reason)
    return names, "; ".join(reasons)


def check(resolved_text: str, conventions_raw: str, *, conventions_name: str = "conventions",
          resolved_name: str = "resolved conventions", preset_library=None) -> Check:
    """Every citation found? Every conventions line covered? (module doc).

    `preset_library` (a `presets.PresetLibrary`, or None) is the library
    the build takes presets from. A preset-map item no rule cites is
    covered when every name it quotes is in it, or when it says "no
    preset"; one naming a preset the library has not got is still a note,
    saying so. A name is looked up among the channel presets
    or the bus presets as its lead-in says (`MapItem.kinds`); an item
    that also states a rule is not covered; a lead-in line
    is covered when any item under it is. With no library, nothing can be
    called missing (the build says `preset.no-library` on its own), so
    every map item is covered; a library that cannot be read is said at
    INFO (`resolve.preset-library-unreadable`) and counts the same."""
    from atoo import generate

    conventions = conventions_for_model(conventions_raw)
    domain = generate._domain_knowledge()
    body = conventions_text.strip_comments(resolved_text or "")
    texts = {
        "conventions": [conventions_audit.Layer("conventions", conventions_name, conventions)],
        "domain": [conventions_audit.Layer("domain", "domain knowledge", domain)],
    }
    result = Check()
    section = ""
    for number, line in enumerate(body.splitlines(), 1):
        heading = conventions_text.heading_name(line)
        if heading:
            section = heading[1]
            continue
        for kind, quote in citations_in(line):
            found = conventions_audit.locate(quote, texts[kind]) is not None
            result.citations.append(Citation(kind, quote, number, section, found))

    # The Instructed strips block's quotes are citations too
    # (`instructed_channels.parse_strips`): each is the conventions
    # sentence that asks for the strip, checked like any other.
    from atoo import instructed_channels

    heading_line = next((n for n, line in enumerate(body.splitlines(), 1)
                         if (conventions_text.heading_name(line) or (0, ""))[1].strip().casefold()
                         == instructed_channels.STRIPS_HEADING.casefold()), 0)
    for strip in instructed_channels.parse_strips(body).strips:
        found = conventions_audit.locate(strip.quote, texts["conventions"]) is not None
        result.citations.append(Citation("conventions", strip.quote, heading_line,
                                         instructed_channels.STRIPS_HEADING, found))

    lines = conventions.splitlines()
    substantive = [i for i, line in enumerate(lines) if _substantive(line)]
    covered = _covered_lines(conventions, [c.quote for c in result.citations
                                           if c.kind == "conventions" and c.found])
    result.substantive = len(substantive)
    # A preset-map item is consumed by the preset choice, not by a
    # resolved rule, so whether the resolver happened to cite it says
    # nothing about whether it takes effect (the same map came
    # back cited line by line in one run and half uncited in the next).
    # It is covered when the library has every preset it names.
    preset_map = preset_map_items(conventions)
    library, unreadable = _library_names(preset_library)
    not_in_library: dict[str, tuple[list[str], frozenset]] = {}
    with_rule_text: dict[str, str] = {}
    unchecked: list[str] = []   # items passed because the library could not be read

    def lookup(item: MapItem) -> "list[str] | None":
        """The names of `item` the library has not got; None when it cannot
        say (a kind it might be in could not be read)."""
        from atoo.presets import normalize_preset_name

        sets = [library[kind] for kind in item.kinds]
        missing = [name for name in item.names
                   if not any(known is not None and normalize_preset_name(name) in known
                              for known in sets)]
        if missing and any(known is None for known in sets):
            return None
        return missing

    # An item is covered by the library when it names nothing the library
    # lacks and states no rule of its own; a lead-in is covered when any
    # item under it is, cited or not -- the lead-in is only a heading for
    # them, so the result must not depend on which of them the resolver
    # happened to cite.
    preset_covered: set[int] = set()
    substantive_set = set(substantive)
    for i, item in preset_map.items():
        if i not in covered and i in substantive_set and not item.rule_text:
            found = lookup(item)
            if found is None and preset_library is not None:
                unchecked.append(lines[i].strip())
            if found is None or not found:
                preset_covered.add(i)
    led_in = {item.lead_in for j, item in preset_map.items() if j in covered or j in preset_covered}
    for i in substantive:
        if i in covered:
            continue
        line = lines[i].strip()
        result.verbatim.append(line)
        if i in preset_covered or i in led_in:
            result.preset_lines.append(line)
            continue
        if i in preset_map:
            item = preset_map[i]
            if item.rule_text:
                with_rule_text[line] = item.rule_text
            else:
                not_in_library[line] = (lookup(item) or [], item.kinds)
        result.uncovered.append(line)

    if unchecked:
        where_lib = getattr(preset_library, "directory", None)
        result.findings.append(Diagnostic(
            severity=Severity.INFO, code=CODE_LIBRARY_UNREADABLE, where=conventions_name,
            line=unchecked[0], source="build",
            message=(f"the preset library{f' {where_lib}' if where_lib else ''} could not be "
                     f"read ({unreadable}) -- the preset map's names were not checked against "
                     f"it, so {len(unchecked)} map line(s) count as covered, whether the "
                     "library has their presets or not"),
            fix=("fix or replace the library (`atoo presets` lists what it holds), then check "
                 "again (`atoo resolve --check`)")))

    for c in result.missing:
        where = f"{resolved_name} § {c.section}" if c.section else resolved_name
        result.findings.append(Diagnostic(
            severity=Severity.WARNING, code=CODE_QUOTE, where=where, category=c.section,
            line=c.quote, source="build",
            message=(f"a rule cites the {c.kind if c.kind == 'conventions' else 'domain knowledge'}"
                     f' as "{c.quote}", which is not in '
                     f"{conventions_name if c.kind == 'conventions' else 'the domain knowledge'}"
                     " -- the rule may be the resolver's own, not the engineer's"),
            fix=(f"read that rule in {resolved_name}; resolve again (`atoo resolve`) or "
                 "reword the conventions line it was meant to cite")))
    for line in result.uncovered:
        if line in not_in_library:
            missing, kinds = not_in_library[line]
            quoted = ", ".join(f'"{name}"' for name in missing)
            where_lib = getattr(preset_library, "directory", None)
            target = "bus" if kinds == {"bus"} else "channel"
            result.findings.append(Diagnostic(
                severity=Severity.INFO, code=CODE_UNCOVERED, where=conventions_name,
                line=line, source="build",
                message=(f'the preset map line "{line}" names {quoted}, which '
                         f'{"is" if len(missing) == 1 else "are"} not in the preset library'
                         + (f" ({where_lib})" if where_lib else "")
                         + f" -- a {target} given "
                         + ("it" if len(missing) == 1 else "one of them")
                         + " is built without its processing"),
                fix=("export a preset saved under that name into the library, or change the "
                     "line to a name `atoo presets` lists")))
            continue
        if line in with_rule_text:
            result.findings.append(Diagnostic(
                severity=Severity.INFO, code=CODE_UNCOVERED, where=conventions_name,
                line=line, source="build",
                message=(f'the preset map line "{line}" says more than a preset name '
                         f'("{with_rule_text[line]}"), and no rule in {resolved_name} cites it '
                         "-- the preset choice reads only the name, so the rest reaches the "
                         "generator verbatim instead"),
                fix=("put that rule on a line of its own, outside the preset map, or resolve "
                     "again (`atoo resolve`)")))
            continue
        result.findings.append(Diagnostic(
            severity=Severity.INFO, code=CODE_UNCOVERED, where=conventions_name,
            line=line, source="build",
            message=(f'the conventions line "{line}" is cited by no rule in {resolved_name} '
                     "and not listed under \"Lines with no effect\" -- the generator is given "
                     "it verbatim instead"),
            fix=("resolve again (`atoo resolve`), or make the line clearer; a quote of "
                 "fewer than four words covers a line only when it is the whole line")))

    if not body.strip() or not any(True for line in body.splitlines() if _substantive(line)):
        result.refused = "it is empty"
    elif not any(c.found for c in result.citations):
        result.refused = ("none of its rules cites text that is in the conventions or the domain "
                          "knowledge" if result.citations else "it cites nothing")
    if result.refused:
        result.findings.append(Diagnostic(
            severity=Severity.WARNING, code=CODE_REFUSED, where=resolved_name, source="build",
            message=(f"{resolved_name} is not used: {result.refused}. This build reads the raw "
                     "conventions and the domain knowledge instead"),
            fix="resolve again (`atoo resolve`), or build with --no-resolve"))
    return result


# ---------------------------------------------------------------------------
# what the generator reads
# ---------------------------------------------------------------------------

def strip_citations(text: str) -> str:
    """`text` with every `[conventions: "..."]` / `[domain: "..."]` taken
    out. The citations are for the check and for the engineer reading the
    file; they are ~60% of it (the first high-effort resolve,
    2026-09-30: 26K of 43K characters), and the generator needs the rule,
    not where it came from."""
    return "\n".join(_ANY_CITATION_RE.sub("", line).rstrip()
                     for line in (text or "").splitlines())


# Looser than `_CITATION_RE`, for stripping only: a citation the model
# added its own words to after the quote (`[domain: "..." - same
# reasoning extends to FX]`), or one with no quote at all
# (`[conventions: DCA list]`), is still a citation, and still not for the
# generator.
_ANY_CITATION_RE = re.compile(
    r"\s*\[\s*(?:conventions|domain(?:[ -]knowledge)?)\s*:[^\]]*\]", re.IGNORECASE)


def prompt_text(resolved_text: str, uncovered: list[str], conventions_name: str) -> str:
    """The resolved file as the generator and the fix-up read it: the
    header, any comment and every citation stripped (`strip_citations`),
    and every conventions line no rule covers appended verbatim, so a
    line the resolver dropped still reaches the generator."""
    from atoo import category_table

    # The Category table is for code (`category_table.py`); the generator
    # reads the prose, and is told what code writes by its own note.
    # So is the Instructed strips block (`instructed_channels.py`): code
    # builds those strips, and the generator is told which by its note.
    from atoo import instructed_channels

    body = strip_citations(instructed_channels.strip_strips_section(category_table.strip(
        conventions_text.strip_comments(resolved_text or "")))).strip()
    if not uncovered:
        return body
    listed = "\n".join(f"- {line}" for line in uncovered)
    return (f"{body}\n\n## Conventions lines the rules above do not cover\n\n"
            f"These lines of {conventions_name} are cited by no rule above. They are the "
            "engineer's own words: apply them as written, and where one disagrees with a "
            f"rule above, the line wins.\n\n{listed}")


@dataclass
class Resolved:
    """A resolved file a build is using."""
    path: Path
    text: str                 # the file as written
    body: str                 # what the generator reads (`prompt_text`)
    fingerprint: dict
    header: dict
    made_now: bool
    check: Check
    # The Category table (`category_table.parse`): valid, invalid or
    # missing, with its one finding when it is not valid.
    table: "object | None" = None
    # The Instructed strips block (`instructed_channels.parse_strips`),
    # each strip's quote checked against the conventions
    # (`instructed_channels.drop_unquoted`).
    strips: "object | None" = None

    @property
    def name(self) -> str:
        return self.path.name

    def meta(self, bundle_dir=None) -> dict:
        from atoo import conventions_ref

        return {
            "used": True,
            "path": str(self.path),
            **conventions_ref.layer_record(self.path, bundle_dir),
            "fingerprint": {k: self.header.get(k) for k in FINGERPRINT_KEYS},
            "model": self.header.get("model"),
            "effort": self.header.get("effort"),
            "made": self.header.get("made"),
            "made_in_this_build": self.made_now,
            "citations": len(self.check.citations),
            "quotes_not_found": len(self.check.missing),
            "lines_not_covered": len(self.check.uncovered),
        }


def not_used_meta(reason: str) -> dict:
    return {"used": False, "reason": reason}


def obtain(state: Freshness, conventions_raw: str, conventions_name: str, *, provider,
           force: bool = False, out=None,
           findings: list | None = None, preset_library=None) -> "Resolved | None":
    """The resolved file for this build: the fresh one on disk, or a new
    one made now (one `resolve` call, written beside the conventions).
    None when there is none to use -- the call failed, or the file is
    refused -- and then the build reads the raw texts; every such case is
    said on `out` and added to `findings` as a WARNING.

    `force` resolves again even when the file on disk is fresh
    (`atoo resolve`). `preset_library` is the library the build takes
    presets from, for the preset map's coverage (`check`)."""
    from atoo.ai_provider import AIProviderError
    from atoo import generate

    out = sys.stderr if out is None else out
    findings = [] if findings is None else findings
    text = state.text
    made_now = False
    if force or not state.fresh:
        try:
            text = run(conventions_raw, conventions_name, provider=provider)
        except (AIProviderError, generate.PromptError) as exc:
            findings.append(Diagnostic(
                severity=Severity.WARNING, code=CODE_FAILED, where=str(state.path),
                source="build",
                message=(f"resolving the conventions failed ({exc}); this build reads the raw "
                         "conventions and the domain knowledge instead"),
                fix="build again, or build with --no-resolve"))
            print(f"resolve: failed ({exc}) -- building from the raw conventions and domain "
                  "knowledge", file=out, flush=True)
            return None
        made_now = True
        try:
            state.path.write_text(text, encoding="utf-8")
            print(f"resolve: wrote {state.path}", file=out, flush=True)
        except OSError as exc:
            findings.append(Diagnostic(
                severity=Severity.WARNING, code=CODE_NOT_WRITTEN, where=str(state.path),
                source="build",
                message=(f"the resolved conventions could not be written to {state.path} "
                         f"({exc.strerror or exc}); this build uses them, but the next one "
                         "resolves again"),
                fix="make the conventions file's directory writable"))
            print(f"resolve: could not write {state.path} ({exc.strerror or exc}); using it "
                  "for this build only", file=out, flush=True)

    result = check(text or "", conventions_raw, conventions_name=conventions_name,
                   resolved_name=state.path.name, preset_library=preset_library)
    findings.extend(result.findings)
    print(f"resolve: checked {state.path.name}: {result.summary()}", file=out, flush=True)
    if not result.usable:
        print(f"resolve: {state.path.name} is not used ({result.refused}) -- building from "
              "the raw conventions and domain knowledge", file=out, flush=True)
        return None
    from atoo import category_table, instructed_channels

    strips = instructed_channels.drop_unquoted(
        instructed_channels.parse_strips(text or "", resolved_name=state.path.name),
        conventions_for_model(conventions_raw), conventions_name=conventions_name,
        resolved_name=state.path.name)
    return Resolved(path=state.path, text=text or "",
                    body=prompt_text(text or "", result.verbatim, conventions_name),
                    fingerprint=state.fingerprint, header=parse_header(text or "") or {},
                    made_now=made_now, check=result,
                    table=category_table.parse(text or "", resolved_name=state.path.name),
                    strips=strips)
