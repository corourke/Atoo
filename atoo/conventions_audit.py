"""FR-6.2, folded into the build: problems in the conventions TEXT itself.

No separate pre-compile stage. The audit runs during
`atoo build`, over the COMBINATION of the house conventions and the
show's `instructions.md`, because that combination is what the show is
built from. Three producers, one rule for what they may claim:

  * the generator's top-level `conventions_audit` entries
    (`plan_schema.CONVENTIONS_AUDIT_SCHEMA`) -- a conflict it had to pick
    a side in, or something declared that ended up with no members;
  * the critic's `conventions` kind (`generate.CRITIC_KINDS`);
  * `verify_plan`'s deterministic `group.empty` / `bus.empty`, which need
    no quote because they read the built plan, not the prose.

**Instructions overriding the house conventions is the design, not a
finding.** A conflict is two statements that disagree with nothing to
settle it: both in the house file, both in the instructions, or a house
conflict the instructions do not resolve. Both prompts say so.

## A model's quote is checked, not believed

FR-6.2 says a finding cites the specific convention, "never a guess". A
model can paraphrase, merge two lines, or invent one outright, and a
finding that quotes text the engineer never wrote sends them hunting
through their own file for a sentence that is not there. So every quote
is looked for in the conventions and instructions text, whitespace,
emphasis markers and curly quotes normalised. A finding whose quotes are
all found keeps its severity and gains the file and heading it came from
(`where`), and its first quote as `line` -- what the Setup UI's finding
dock jumps to: the step's editor, with that line selected. One with a quote that is NOT found is
downgraded to INFO under its own code, `conventions.unverified-quote`,
and says so -- kept rather than dropped, so a real problem described with
a sloppy quote is not silently lost, but never at a severity that asks
for action.

Grading follows the principle that an error of judgement is not an error of
patching: a conflict the plan resolved by picking one reading is INFO --
a choice was made, and the engineer settles it in his text next time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from atoo import conventions_text
from atoo.diagnostics import Diagnostic, Severity

CODE_UNVERIFIED = "conventions.unverified-quote"

# Curly quotes and dashes a model "helpfully" normalises one way or the
# other; folded to one spelling on both sides before comparing. Double
# and single quotes fold together too, and a backslash escape goes: a
# model quoting `- "INST Reverb" -- All instrument channels` inside its
# own `[conventions: "..."]` writes `'INST Reverb'` or `\"INST Reverb\"`
# (the 2026-09-30 resolve: 40 of its 46 unfound quotes were this, or the
# joins and elisions `_segments` handles).
_FOLD = str.maketrans({
    "‘": "'", "’": "'", "“": "'", "”": "'", '"': "'",
    "–": "-", "—": "-", "…": "...", "\\": None,
})
_EMPHASIS_RE = re.compile(r"[*_`]")
_SPACE_RE = re.compile(r"\s+")
# A line break the model wrote AS TEXT inside a quote -- the two
# characters `\` `n` -- where the source wraps (the 2026-10-01 resolve:
# 8 of its 9 notes were `"there\nmay be a channel called click..."`).
# It is whitespace, like the real line break it stands for; without this
# the backslash is dropped below and `there\nmay` reads `therenmay`.
_ESCAPED_SPACE_RE = re.compile(r"\\[ntr]")


def normalise(text: str) -> str:
    """Whitespace collapsed, Markdown emphasis and curly quotes folded,
    case folded -- what two copies of the same sentence have in common
    after a model has retyped one of them."""
    text = _ESCAPED_SPACE_RE.sub(" ", str(text))
    text = _EMPHASIS_RE.sub("", text.translate(_FOLD))
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _quote_core(quote: str) -> str:
    """A quote stripped of what a model wraps around one: surrounding
    quote marks and a leading/trailing ellipsis marking an excerpt."""
    core = normalise(quote)
    core = core.strip(" \"'")
    while core.startswith("..."):
        core = core[3:].lstrip()
    while core.endswith("..."):
        core = core[:-3].rstrip()
    # A model closes a quoted fragment with its own full stop ("...or a
    # combination of the two." of "...of the two -- these tracks").
    return core.strip(" \"'").rstrip(".,;:").rstrip()


@dataclass(frozen=True)
class Layer:
    """One conventions text the show was built from."""
    role: str        # "conventions" or "instructions"
    name: str        # the file name, for messages
    text: str
    # The RESOLVED conventions (`conventions_resolve.py`): the house
    # conventions restated as cited rules, which the generator read in
    # place of the raw file. Its role stays "conventions" -- it is that
    # layer, rewritten -- and a quote found in it is mapped back to the
    # raw line its rule cites where there is one (`locate`). Searched
    # after every raw text, so a quote of the engineer's own words is
    # always credited to his file first.
    resolved: bool = False


@dataclass(frozen=True)
class Located:
    role: str
    section: str     # the `## ` heading it sits under, "" for the preamble
    # Set when the quote was found in the resolved conventions: `via` is
    # that file's name, `via_line` the resolved rule's line, and
    # `raw_quote` the raw conventions text that rule cites, when it cites
    # one (then `role`/`section` are where THAT text sits in the raw file).
    via: str = ""
    via_line: str = ""
    raw_quote: str = ""


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading name, body) split on headings (`conventions_text.
    split_sections`). The heading only LABELS where a quote was found
    ("instructions § Busses", in the finding's text); a file with no
    headings is one part named "" and is checked exactly the same. The
    Setup page finds the quote itself, in the step's editor, by `line`."""
    return [(name, "\n".join(([heading] if heading else []) + body))
            for name, heading, body in conventions_text.split_sections(text)]


def segments(core: str) -> list[str]:
    """A quote's parts either side of an elision ("Color coding:
    Drums-Red...Speech-Purple"): each must be in the text, in order."""
    return [part.strip(" '") for part in core.split("...") if part.strip(" '")]


def contains(text: str, core: str) -> bool:
    """Whether normalised `text` holds the quote `core`, reading an
    elision as "these parts, in this order"."""
    at = 0
    for part in segments(core) or [core]:
        at = text.find(part, at)
        if at == -1:
            return False
        at += len(part)
    return True


def locate(quote: str, layers: list[Layer]) -> Located | None:
    """Where `quote` appears -- instructions first, since where both
    carry a line the instructions are the layer that won -- or None."""
    core = _quote_core(quote)
    if len(core) < 3:
        return None
    ordered = sorted(layers, key=lambda layer: (layer.role != "instructions", layer.resolved))
    for layer in ordered:
        for name, body in _sections(layer.text):
            if contains(normalise(body), core):
                return _map_back(core, layer, name, layers) if layer.resolved \
                    else Located(layer.role, name)
    for layer in ordered:
        # A quote spanning a heading boundary: found, but in no one section.
        if contains(normalise(layer.text), core):
            return _map_back(core, layer, "", layers) if layer.resolved \
                else Located(layer.role, "")
    return None


def _map_back(core: str, resolved: Layer, section: str, layers: list[Layer]) -> Located:
    """A quote found in the resolved conventions, credited to the raw
    conventions line its rule cites (`[conventions: "..."]` on the same
    line) when that line is in the raw text -- so a finding points at
    the engineer's own sentence, which is what he edits. A rule citing
    only the domain knowledge, or a "Decided:" with nothing in the raw
    file behind it, stays credited to the resolved file."""
    from atoo import conventions_resolve

    raw = [layer for layer in layers if not layer.resolved]
    line = next((ln.strip() for ln in resolved.text.splitlines()
                 if core in normalise(ln)), "")
    for kind, cited in conventions_resolve.citations_in(line):
        if kind != "conventions":
            continue
        spot = locate(cited, raw)
        if spot is not None:
            return replace(spot, via=resolved.name, via_line=line, raw_quote=cited)
    return Located(resolved.role, section, via=resolved.name, via_line=line)


def layers_for(conventions: str, conventions_name: str,
               instructions: str | None, instructions_name: str | None,
               resolved: str | None = None, resolved_name: str | None = None) -> list[Layer]:
    """The texts a quote is checked against, comments stripped
    (`conventions_text.strip_comments`) -- the same text the model was
    shown. A sentence that exists only inside `<!-- ... -->` is a note,
    not a rule, so a finding quoting it must not verify.

    `resolved`, when the generator read the resolved conventions in place
    of the raw file (`conventions_resolve.py`), is one more layer: a quote
    of it is accepted too, and credited to the raw line its rule cites."""
    layers = [Layer("conventions", conventions_name,
                    conventions_text.strip_comments(conventions or ""))]
    if instructions:
        layers.append(Layer("instructions", instructions_name or "instructions",
                            conventions_text.strip_comments(instructions)))
    if resolved:
        layers.append(Layer("conventions", resolved_name or "resolved conventions",
                            conventions_text.strip_comments(resolved), resolved=True))
    return layers


def _where(located: Located) -> str:
    if located.via and not located.raw_quote:
        return f"{located.via} § {located.section}" if located.section else located.via
    return f"{located.role} § {located.section}" if located.section else located.role


def _line(located: Located, quote: str) -> str:
    """The text the Setup UI's finding dock selects: the raw line a
    resolved rule cites, when the quote came through one; else the quote."""
    return (located.raw_quote or quote).strip()


def _quoted(quotes: list[str]) -> str:
    return "; ".join(f'"{q.strip()}"' for q in quotes)


def check_quotes(quotes: list[str], layers: list[Layer]) -> tuple[list[Located], list[str]]:
    """(where each found quote sits, the quotes that were not found)."""
    found, missing = [], []
    for quote in quotes:
        spot = locate(quote, layers)
        if spot is None:
            missing.append(quote)
        else:
            found.append(spot)
    return found, missing


def findings_from_plan(plan: dict, layers: list[Layer]) -> list[Diagnostic]:
    """The generator's `conventions_audit` entries, quote-checked, as
    Diagnostics (source "build"). Every entry becomes exactly one finding:
    INFO `conventions.<kind>` when its quotes are all in the text, INFO
    `conventions.unverified-quote` when one is not."""
    out: list[Diagnostic] = []
    for entry in (plan or {}).get("conventions_audit") or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "conflict")
        quotes = [str(q) for q in entry.get("quotes") or [] if str(q).strip()]
        message = str(entry.get("message") or "").strip()
        found, missing = check_quotes(quotes, layers)
        if quotes and not missing:
            out.append(Diagnostic(
                severity=Severity.INFO, code=f"conventions.{kind}",
                where=_where(found[0]), category=found[0].section,
                line=_line(found[0], quotes[0]),
                message=f"{message} -- quoting {_quoted(quotes)}",
                fix=("settle it in your conventions or this show's instructions" if kind == "conflict"
                     else "drop it for shows like this one, or give it members"),
                source="build"))
        else:
            out.append(Diagnostic(
                severity=Severity.INFO, code=CODE_UNVERIFIED, where="conventions",
                message=(f"the generator reported a conventions {kind}, but "
                         + (f"quoted text that is not in your conventions or instructions "
                            f"({_quoted(missing)})" if quotes else "quoted nothing")
                         + f" -- not trusted, shown so it is not lost: {message}"),
                source="build"))
    return out


def check_critic_omission(finding: Diagnostic, quotes: list[str],
                          layers: list[Layer]) -> Diagnostic:
    """One critic `omission` finding, its quote checked.

    An omission that quotes a line of the conventions or instructions, every
    quote found, gets `line` set to that line: the build sends it to the
    fix-up round (`cli._build`). Anything else -- an input-list row the plan
    left out, a quote not in the text, no quote -- is returned as it came,
    reported and never fed back, so only a line the engineer wrote can steer
    the build."""
    quotes = [str(q) for q in quotes or [] if str(q).strip()]
    found, missing = check_quotes(quotes, layers)
    if not quotes or missing:
        return finding
    return replace(finding, line=_line(found[0], quotes[0]),
                   message=f"{finding.message} -- quoting {_quoted(quotes)}")


def check_critic_finding(finding: Diagnostic, quotes: list[str],
                         layers: list[Layer]) -> Diagnostic:
    """One critic `conventions` finding, quote-checked.

    Found: severity kept, `where`/`category` set to the section the first
    quote sits in (what the finding dock jumps to), `line` to the quote.
    Not found, or no quote at all: downgraded to INFO and re-coded
    `conventions.unverified-quote`, with the original severity named.
    """
    quotes = [str(q) for q in quotes or [] if str(q).strip()]
    found, missing = check_quotes(quotes, layers)
    if quotes and not missing:
        return replace(finding, where=_where(found[0]), category=found[0].section,
                       line=_line(found[0], quotes[0]),
                       message=f"{finding.message} -- quoting {_quoted(quotes)}")
    reason = (f"quoted text that is not in your conventions or instructions ({_quoted(missing)})"
              if quotes else "quoted nothing")
    return replace(
        finding, severity=Severity.INFO, code=CODE_UNVERIFIED, category="conventions",
        message=(f"the critic reported a problem in the conventions at {finding.severity.value}, "
                 f"but {reason} -- downgraded to a note and not trusted: {finding.message}"))
