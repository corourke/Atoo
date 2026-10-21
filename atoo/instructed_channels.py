"""Channels the conventions or instructions ask for that are not rows of
the input list.

The case: the sixpiece show's `instructions.md` (frozen in
`tests/fixtures/sixpiece_instructions_2026-09-29.md`) says *"Setup Talkback on
Channel 40, source A 40"*. Talkback is not on the input list -- nobody
writes the engineer's own talk mic on a band's list -- and until this
module the build refused the channel as an invention (rule 2). The decision:
**allow it when its source socket is stated.** The engineer
asked for it in words, and said where the cable is; building it is doing
what they asked, not inventing.

So a channel with no input-list row is built only when all three hold:

  (a) the conventions or instructions state its source socket, as a group
      and a number ("A 40", "AES50-A 40", "LCL 3");
  (b) the reply marks it as coming from them -- a `quote` naming the
      sentence verbatim, or (what an unconstrained model writes) that
      sentence quoted in the channel's `provenance`;
  (c) its source is not an input-list row.

And the quote is CHECKED against the texts the build was given, exactly
as the critic's quotes are (`conventions_audit.locate`): a sentence the
engineer never wrote is invention, and is refused at build and an ERROR
at verify (`reconcile.invented-source`). A found one is built, and verify
reports it every time (`reconcile.from-instructions`), so the engineer
sees the one channel on the desk that is not on his list: an INFO when
it is asked for verbatim with its socket, else a WARNING (`verify_plan._explicitly_requested`).

The plan records it on the channel's `source`:

    "source": {"input": "Talkback", "type": "Mic", "model": null,
               "stereo": false, "phantom": false,
               "from": "instructions",
               "quote": "Setup Talkback on Channel 40, source A 40"}

and its `patch` is the stated socket, `stated: true`. What the text does
not say -- the source type, phantom, the colour category -- is decided
here and announced at INFO (an error of judgement is not an
error of patching): a talk mic is a mic, phantom is off unless the text
asks for it, and the colour is the category the text or the name points
at, if the conventions colour one.

## Strips code builds (the resolved conventions, 2026-10-01)

A sixpiece build of 2026-10-01 (commit c04dd25) showed rule 2's
exception is not reliable as prompt wording: the conventions ask for Aux 1
MUSIC (LCL 23-24), Aux 2 HOST (preset "Host CO2", LCL 20) and Aux 8
TALKBACK (LCL 22 if available), the resolved file stated all three, and
the generator built none ("not in the input list ... nothing invented").
So, as the Category table did for per-category settings, the
resolve step now writes them as data and CODE builds them:

  * `conventions_resolve` asks for a `## Instructed strips` section: one
    ```json fence, one object per strip the conventions ask for that is not
    an input-list row -- name, `kind` (aux or channel) and stated `number`,
    `source` socket(s), `stereo`, `preset`, `category`, `main_direct`,
    `sends`, a `condition` ("if available") and the verbatim `quote`.
  * `parse_strips` checks it (an invalid block builds none; an entry code
    cannot build -- no stated socket, a strip the console lacks -- is a
    WARNING and the rest build). Each quote is checked against the
    conventions like any citation (`conventions_resolve.check`), and a strip
    whose quote is not there is not built (`drop_unquoted`).
  * `reply_expand.prepare_instructed_strips` holds each strip's socket and
    number before any row is counted, merges a reply channel that is the
    same strip into it (code's strip, socket, stereo pair and preset win;
    the reply's other decisions stand), and finds the conflicts;
    `build_instructed_strips` builds them -- category defaults from the
    Category table, `source.from: "conventions"` and the quote, so verify's
    `reconcile.from-instructions` names each one.
  * A stated socket an input-list row (or a reply channel) already holds is
    a physical conflict. With "if available" in the text the strip is built
    UNPATCHED (`patch: null`, `source.condition`), at INFO; without it the
    strip is built on the stated socket anyway -- never silently dropped --
    and verify refuses the plan (`reconcile.instructed-conflict`, ERROR).
    A stated strip number a reply channel names outright is
    `strip.double-booked`.
  * An input-list row with the strip's name IS the strip (festival's HOST
    row): code moves that row's channel to the stated strip and socket.

The generator is told which strips code builds (`strips_prompt_note`) and
builds none of them. Strips the show's INSTRUCTIONS ask for are not in the
resolved file (resolve reads only the house conventions), so they -- and
every strip on a build with `--no-resolve` or no resolved file -- still
go through the reply path above (`reply_expand._resolve_instructed`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from atoo import conventions_audit
from atoo.conventions_audit import Layer

ROLES = ("conventions", "instructions")

# "A 40", "AES50-A 40", "LCL 3", "LCL3", "CRD 12". A bare A/B/C is read as
# its AES50 network only in UPPER case, and only here: an input list's
# patch column refuses it (`input_list._SELF_SPELLABLE`) because a column
# can start with a letter, but in a sentence like "source A 40" it is how
# an engineer writes the socket -- and the patch it produces is shown in
# full ("AES50-A 40") in provenance and at verify, so a misreading is seen.
_SOCKET_IN_TEXT_RE = re.compile(
    r"(?<![\w-])(?P<group>AES50[\s-]?[A-Ca-c]|[A-Za-z]+)[\s-]?(?P<n>\d{1,3})(?!\d)")

# Text a model wraps a quotation in, inside a provenance sentence.
_QUOTED_RE = re.compile(r"'([^']{8,})'|\"([^\"]{8,})\"|“([^”]{8,})”|‘([^’]{8,})’")

# "Channel 40", "ch 40", "Ch. 40": the strip a line asks a channel to go on.
_CHANNEL_IN_TEXT_RE = re.compile(r"\b(?:channel|ch)\.?\s*(\d{1,3})(?!\d)", re.IGNORECASE)

_TALKBACK_RE = re.compile(r"\btalk|\bt/?b\b|\bcomms?\b", re.IGNORECASE)
_PHANTOM_ON_RE = re.compile(r"\bphantom\b|\+?48\s*v\b", re.IGNORECASE)
_PHANTOM_OFF_RE = re.compile(r"\bno phantom\b|\bphantom\s*(?:off|none|no)\b|\bwithout phantom\b",
                             re.IGNORECASE)


def stated_sockets(text: str) -> list[tuple[str, int]]:
    """Every input socket `text` names, in order, de-duplicated."""
    from atoo.input_list import parse_socket_spec

    out: list[tuple[str, int]] = []
    for m in _SOCKET_IN_TEXT_RE.finditer(str(text or "")):
        group, n = m.group("group"), int(m.group("n"))
        parsed = (group, n) if group in ("A", "B", "C") else parse_socket_spec(f"{group} {n}")
        if parsed and parsed not in out:
            out.append(parsed)
    return out


def stated_channel(quote: str, layer: Layer | None) -> int | None:
    """The channel number the quote states -- or, failing that, the line
    it was quoted from -- when it states exactly one. "Setup Talkback on
    Channel 40, source A 40." states 40; a line naming two channels states
    none, and the strip is counted as any other."""
    for text in (clean_quote(quote), matched_line(quote, layer)):
        found = {int(n) for n in _CHANNEL_IN_TEXT_RE.findall(str(text or ""))}
        if len(found) == 1:
            return found.pop()
        if found:
            return None
    return None


def candidate_quotes(channel: dict) -> list[str]:
    """What the reply offers as the sentence it built the channel from:
    its `quote`, then any quoted span in its provenance, then each
    provenance sentence whole."""
    out: list[str] = []
    if isinstance(channel.get("quote"), str) and channel["quote"].strip():
        out.append(channel["quote"].strip())
    provenance = channel.get("provenance")
    texts = ([v for v in provenance.values() if isinstance(v, str)] if isinstance(provenance, dict)
             else [provenance] if isinstance(provenance, str) else [])
    for text in texts:
        for m in _QUOTED_RE.finditer(text):
            span = next(g for g in m.groups() if g)
            if span.strip() not in out:
                out.append(span.strip())
    for text in texts:
        if text.strip() and text.strip() not in out:
            out.append(text.strip())
    return out


# What a model writes in front of a quotation to say where it came from:
# "Instructions:", "Conventions:", "Input list:", "the input list's notes:",
# "instructions.md:", "Instructions § Inputs:". Stripped before matching
# -- the label is the model's, not the engineer's, so it is never in the
# text (Haiku's sixpiece reply, 2026-09-29: "Instructions: Talkback on
# Channel 40, source A 40").
_LABEL_RE = re.compile(
    r"""^\s*(?:
        (?:the\s+)?(?:instructions?|conventions?|input[\s-]?list(?:'s)?(?:\s+notes?)?|notes?)
      | [\w.-]+\.(?:md|markdown|txt|csv)
    )(?:\s*(?:§|section)\s*[^:]{0,40})?\s*:\s*""",
    re.IGNORECASE | re.VERBOSE)
_QUOTE_MARKS = " \t\"'“”‘’`"
_TRAILING = " \t.,;:!?"

# The fewest words a quote may have and still vouch for anything. "source
# A 40" is in the text, and so is "on Channel": a fragment that short
# says nothing about which sentence it came from, so it is not taken as
# the engineer asking for anything.
MIN_QUOTE_WORDS = 4


def clean_quote(quote: str) -> str:
    """`quote` as the engineer's words alone: a leading source label, the
    quote marks around it and its closing punctuation stripped."""
    text = str(quote or "").strip()
    while True:
        bare = _LABEL_RE.sub("", text, count=1).strip().strip(_QUOTE_MARKS).rstrip(_TRAILING)
        bare = bare.strip(_QUOTE_MARKS)
        if bare == text:
            return text
        text = bare


def find(quote: str, layers: list[Layer] | None) -> Layer | None:
    """The layer `quote` appears in (instructions first), or None.

    The quote is cleaned first (`clean_quote`), and what remains must
    appear contiguously in one of the texts -- after the whitespace, case
    and emphasis folding `conventions_audit.normalise` does -- but need
    not be a whole line: a model that drops "Setup" from the front of a
    sentence still quoted it. It must be at least `MIN_QUOTE_WORDS`
    words, so a fragment cannot vouch for a channel -- unless it is a whole
    line (`_whole_line`). An invented sentence is not in the text, and is
    refused."""
    if not layers or not quote:
        return None
    core = clean_quote(quote)
    if len(core.split()) < MIN_QUOTE_WORDS:
        return _whole_line(core, layers)
    spot = conventions_audit.locate(core, layers)
    if spot is None:
        return None
    if spot.via:
        # Found in the resolved conventions (`conventions_resolve.py`).
        # What the callers read off the layer -- the line the quote sits
        # in, the sockets and channel that line states -- is the resolved
        # rule's line, followed by the raw line it cites, so a rule that
        # restated "source A 40" still states it. Named for both files.
        raw = next((layer for layer in layers
                    if layer.role == spot.role and not layer.resolved), None)
        name = f"{raw.name} (via {spot.via})" if raw is not None and spot.raw_quote \
            else spot.via
        text = "\n".join(t for t in (spot.via_line, spot.raw_quote) if t)
        return Layer(spot.role, name, text, resolved=True)
    return next((layer for layer in layers
                 if layer.role == spot.role and not layer.resolved), None)


def _whole_line(core: str, layers: list[Layer]) -> Layer | None:
    """A quote shorter than `MIN_QUOTE_WORDS` still counts when it is a
    whole line of a text -- a row's notes that say only "spare" -- since
    a whole line is no fragment. Instructions first, as `locate` orders."""
    want = conventions_audit.normalise(core)
    if not want:
        return None
    for layer in sorted(layers, key=lambda layer: layer.role != "instructions"):
        for line in layer.text.splitlines():
            if conventions_audit.normalise(clean_quote(line.lstrip("#-*> \t"))) == want:
                return layer
    return None


def not_found_reason(quote: str, layers: list[Layer] | None) -> str:
    """Why `find` refused `quote`, for the message: too short, or not in
    the texts."""
    core = clean_quote(quote)
    words = len(core.split())
    if layers and words < MIN_QUOTE_WORDS and conventions_audit.locate(core, layers):
        return (f"is only {words} word{'s' if words != 1 else ''} of the conventions or "
                f"instructions -- too short to say which sentence it is from (at least "
                f"{MIN_QUOTE_WORDS} words, or a whole line)")
    return "is not in the conventions or instructions"


def matched_line(quote: str, layer: Layer | None) -> str:
    """The line of `layer` the (cleaned) quote sits in, "" when it spans
    lines or is not there."""
    if layer is None:
        return ""
    core = conventions_audit.normalise(clean_quote(quote))
    return next((line.strip() for line in layer.text.splitlines()
                 if core and core in conventions_audit.normalise(line)), "")


def sockets_for(quote: str, layer: Layer | None) -> list[tuple[str, int]]:
    """The sockets the quote states -- or, failing that, the line it was
    quoted from. "Talkback on Channel 40" is quoted from "Setup Talkback
    on Channel 40, source A 40.", and that line states A 40."""
    return stated_sockets(clean_quote(quote)) or stated_sockets(matched_line(quote, layer))


def first_found(quotes: list[str], layers: list[Layer] | None) -> tuple[str, Layer] | None:
    """The first of `quotes` that is in the texts AND states a socket (in
    itself or its line); failing that, the first that is in the texts at
    all. The quote is returned cleaned (`clean_quote`)."""
    found = [(clean_quote(q), layer) for q in quotes for layer in [find(q, layers)]
             if layer is not None]
    for q, layer in found:
        if sockets_for(q, layer):
            return q, layer
    return found[0] if found else None


def decide_type(quote: str, name: str) -> tuple[str, str]:
    """(source type, why). Stated when the sentence says DI or wireless;
    otherwise a mic -- what a talk mic, a spare vocal or an ambient pair
    is -- and said so."""
    text = f"{quote} {name}"
    if re.search(r"\bDI\b", text):
        return "DI", "the text says DI"
    if re.search(r"\bwireless\b|\bradio\b|\bRF\b", text, re.IGNORECASE):
        return "Wireless", "the text says wireless"
    if re.search(r"\bmic\b|\bmicrophone\b", text, re.IGNORECASE):
        return "Mic", "the text says mic"
    if re.search(r"\bplayback\b|\bmusic\b|\bplayer\b|\bline\b", text, re.IGNORECASE):
        return "Line", "the text names a playback or line source"
    if _TALKBACK_RE.search(text):
        return "Mic", "a talkback source is a microphone"
    return "Mic", "the text names no type; a channel asked for in words is taken as a mic"


def decide_phantom(quote: str) -> tuple[bool, str]:
    if _PHANTOM_OFF_RE.search(quote):
        return False, "the text says no phantom"
    if _PHANTOM_ON_RE.search(quote):
        return True, "the text asks for phantom power"
    return False, "the text does not ask for phantom power, so it is off"


def decide_category(quote: str, name: str, categories) -> tuple[str | None, str]:
    """The colour category this channel takes, from the categories the
    conventions colour: one the text or the name names outright, else a
    talkback/comms one for a talk mic, else `misc`; None when none fits."""
    known = {str(c).strip().casefold(): str(c) for c in categories or ()}
    text = f"{quote} {name}".casefold()
    for key, label in known.items():
        if key and re.search(rf"\b{re.escape(key)}\b", text):
            return label, f"the text names {label!r}"
    if _TALKBACK_RE.search(f"{quote} {name}"):
        for key in ("talkback", "comms", "communications"):
            if key in known:
                return known[key], f"a talk mic takes the {known[key]!r} category"
    if "misc" in known:
        return known["misc"], "no category fits better, so 'misc'"
    return None, "the conventions colour no category that fits, so no category colour"


# Words that make a strip a playback source: walk-in music, a playlist, a
# backing-track player. The conventions colour "Playback", and say the aux
# the show adds for music belongs to it (in the DCA line, not the colour
# line), so the colour must not hang on the model remembering that.
_PLAYBACK_RE = re.compile(r"\b(?:music|walk-?in|playlist|playback|backing tracks?)\b",
                          re.IGNORECASE)
PLAYBACK_CATEGORIES = ("playback", "tracks", "backing tracks", "backing")


def playback_category(quote: str, name: str, categories) -> tuple[str | None, str | None]:
    """(category, why) when the text is about music or playback and the
    conventions name a playback category among `categories`; else
    (None, None). A judgement the build announces at INFO."""
    if not _PLAYBACK_RE.search(f"{quote} {name}"):
        return None, None
    known = {str(c).strip().casefold(): str(c) for c in categories or ()}
    for key in PLAYBACK_CATEGORIES:
        if key in known:
            return known[key], f"{name!r} is music or playback, which the conventions' {known[key]!r} category covers"
    return None, None


def is_instructed(channel: dict) -> bool:
    """A plan channel built from the conventions or instructions."""
    source = channel.get("source") if isinstance(channel, dict) else None
    return isinstance(source, dict) and source.get("from") in ROLES


def layers_from_texts(conventions: str | None, conventions_name: str | None,
                      instructions: str | None, instructions_name: str | None,
                      resolved: str | None = None,
                      resolved_name: str | None = None) -> list[Layer]:
    return conventions_audit.layers_for(conventions or "", conventions_name or "conventions",
                                        instructions, instructions_name,
                                        resolved=resolved, resolved_name=resolved_name)


def layers_from_plan(plan: dict, bundle_dir=None, instructions_path=None) -> list[Layer] | None:
    """The conventions and instructions a built plan names in
    `meta.conventions_stack`, read from where they are now
    (`conventions_ref.resolve_recorded`), and the bundle's
    `instructions.md` when the stack names none. None when no text can be
    found -- then verify says the quote was not checked rather than
    passing or failing it."""
    from pathlib import Path

    from atoo import conventions_ref, conventions_text

    layers: list[Layer] = []
    meta = plan.get("meta") if isinstance(plan, dict) else None
    stack = meta.get("conventions_stack") if isinstance(meta, dict) else None
    for layer in stack if isinstance(stack, list) else []:
        if not isinstance(layer, dict) or layer.get("role") not in ROLES:
            continue
        path, _how = conventions_ref.resolve_recorded(layer, bundle_dir)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        layers.append(Layer(layer["role"], path.name, conventions_text.strip_comments(text)))
    # The resolved conventions the generator read in place of the raw file
    # (`conventions_resolve.py`, `meta.resolved_conventions`), when the
    # build used one and it is still there: a quote of it is accepted, as
    # it was at build time.
    record = meta.get("resolved_conventions") if isinstance(meta, dict) else None
    if isinstance(record, dict) and record.get("used"):
        path, _how = conventions_ref.resolve_recorded(record, bundle_dir)
        if path is not None:
            try:
                layers.append(Layer("conventions", path.name,
                                    conventions_text.strip_comments(path.read_text(encoding="utf-8")),
                                    resolved=True))
            except OSError:
                pass
    if instructions_path and not any(layer.role == "instructions" for layer in layers):
        path = Path(instructions_path)
        if path.is_file():
            try:
                layers.append(Layer("instructions", path.name,
                                    conventions_text.strip_comments(path.read_text(encoding="utf-8"))))
            except OSError:
                pass
    return layers or None


# ---------------------------------------------------------------------------
# The resolved conventions' Instructed strips block (2026-10-01)
# ---------------------------------------------------------------------------

STRIPS_HEADING = "Instructed strips"
CODE_STRIPS_INVALID = "instructed-strips.invalid"
CODE_STRIPS_MISSING = "instructed-strips.missing"
CODE_STRIP_INVALID = "instructed-strips.entry-invalid"

# "if available" and its spellings: the strip is wanted whether or not its
# socket is free, and patched only if it is.
_IF_AVAILABLE_RE = re.compile(r"\bif\s+(?:it\s+is\s+|it's\s+)?(?:available|free)\b", re.I)

_SEND_SCHEMA = {
    "type": "object",
    "properties": {
        "bus": {"type": "string", "minLength": 1},
        "mode": {"type": ["string", "null"]},
        "level_db": {"type": ["number", "null"]},
    },
    "required": ["bus"],
    "additionalProperties": False,
}

STRIP_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "kind": {"type": "string", "enum": ["channel", "aux"]},
        "number": {"type": ["integer", "null"], "minimum": 1},
        "source": {"type": ["string", "null"]},
        "stereo": {"type": ["boolean", "null"]},
        "preset": {"type": ["string", "null"]},
        "category": {"type": ["string", "null"]},
        "main_direct": {"type": ["boolean", "null"]},
        "sends": {"type": ["array", "null"], "items": _SEND_SCHEMA},
        "condition": {"type": ["string", "null"]},
        "quote": {"type": "string", "minLength": 1},
    },
    "required": ["name", "kind", "quote"],
    "additionalProperties": False,
}

STRIPS_SCHEMA = {"type": "array", "items": STRIP_SCHEMA}

_STRIPS_SECTION_RE = re.compile(
    r"^##[ \t]+" + re.escape(STRIPS_HEADING) + r"[ \t]*\n(.*?)(?=^##[ \t]|\Z)", re.M | re.S | re.I)
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)[\w-]*[ \t]*\n(.*?)^[ \t]*\1[ \t]*$", re.M | re.S)

# "LCL 23-24", "LCL 23+24", "LCL 23/24", "LCL 23-LCL 24", "AES50-A 39-40".
_SOURCE_RANGE_RE = re.compile(
    r"^\s*(?P<first>.*?\d+)\s*(?:[-+/&]|\band\b)\s*(?:[A-Za-z][\w-]*?\s*)?(?P<second>\d+)\s*$")


@dataclass
class Strip:
    """One instructed strip, checked: what code builds."""
    name: str
    bank: str                       # "ch" or "aux"
    number: int | None              # the stated strip number, or None (counted)
    group: str | None               # the stated source group, or None (none stated)
    sockets: list[int]              # [] when no socket is stated
    stereo: bool
    stereo_why: str                 # "stated", or why it was decided
    preset: str | None
    category: str | None
    main_direct: bool | None
    sends: list[dict]
    if_available: bool
    condition: str | None
    quote: str

    @property
    def spelled_source(self) -> str:
        from atoo.input_list import format_socket

        if not self.group or not self.sockets:
            return "no socket"
        first = format_socket(self.group, self.sockets[0])
        return first + (f"-{self.sockets[-1]}" if len(self.sockets) > 1 else "")


@dataclass
class ParsedStrips:
    strips: list[Strip]
    findings: list
    state: str            # "valid", "invalid" or "missing"
    reason: str = ""

    def meta(self, *, applied: bool) -> dict:
        """`meta.resolved_conventions.instructed_strips`."""
        out: dict = {"state": self.state, "applied": applied,
                     "strips": [s.name for s in self.strips]}
        if self.reason:
            out["reason"] = self.reason
        return out


def strips_section(text: str) -> str | None:
    """The `## Instructed strips` section's body, or None."""
    match = _STRIPS_SECTION_RE.search(text or "")
    return match.group(1) if match else None


def strip_strips_section(text: str) -> str:
    """`text` without its `## Instructed strips` section: the generator
    reads what code builds from `strips_prompt_note`, not as JSON."""
    return _STRIPS_SECTION_RE.sub("", text or "").rstrip()


def parse_source(raw: str | None) -> tuple[str | None, list[int]] | None:
    """`"LCL 23-24"` -> `("LCL", [23, 24])`; `"LCL 20"` -> `("LCL", [20])`;
    None or "" -> `(None, [])`. None when it cannot be read."""
    from atoo.input_list import parse_socket_spec

    def one(spec: str) -> tuple[str, int] | None:
        # A bare A/B/C is its AES50 network here, as in `stated_sockets`:
        # it is how an engineer writes the socket in a sentence.
        bare = re.fullmatch(r"([ABC])[\s-]?(\d{1,3})", spec.strip())
        return (bare.group(1), int(bare.group(2))) if bare else parse_socket_spec(spec.strip())

    text = str(raw or "").strip()
    if not text or text.casefold() in ("none", "null", "not set", "unpatched"):
        return None, []
    single = one(text)
    if single:
        return single[0], [single[1]]
    match = _SOURCE_RANGE_RE.match(text)
    if match:
        first = one(match.group("first"))
        if first:
            return first[0], [first[1], int(match.group("second"))]
    return None


def _strip_from_entry(entry: dict) -> tuple[Strip | None, str | None]:
    """A checked `Strip`, or (None, why code cannot build it)."""
    from atoo import console_facts as facts

    bank = "aux" if entry["kind"] == "aux" else "ch"
    number = entry.get("number")
    if number is not None and not 1 <= number <= facts.CAPACITY[bank]:
        return None, (f"{bank} {number} does not exist (a WING has {bank} "
                      f"1-{facts.CAPACITY[bank]})")
    parsed = parse_source(entry.get("source"))
    if parsed is None:
        return None, (f"its source {entry.get('source')!r} is not a socket Atoo can read "
                      "(write it as a group and number, like 'LCL 20' or 'LCL 23-24')")
    group, sockets = parsed
    if group is None:
        # The rule for every strip not on the input list (module doc): it
        # is built only when its socket is stated.
        return None, ("it states no source socket, and a strip that is not on the input list "
                      "is built only when its socket is stated")
    if len(sockets) == 2 and sockets[1] != sockets[0] + 1:
        return None, (f"its source {entry.get('source')!r} names two sockets that are not "
                      "consecutive, and a stereo strip takes a consecutive pair")
    stated = entry.get("stereo")
    if len(sockets) == 2:
        stereo = True
        why = ("stated" if stated is True else
               f"two sockets ({entry.get('source')}) make one stereo strip"
               + ("; the block said mono, but a mono strip takes one socket"
                  if stated is False else ""))
    elif stated is True:
        stereo = True
        if sockets:
            sockets = [sockets[0], sockets[0] + 1]
            why = f"stated stereo with one socket named, so the pair is {sockets[0]}+{sockets[1]}"
        else:
            why = "stated"
    else:
        stereo = False
        why = "stated" if stated is False else "one socket, so mono"
    condition = entry.get("condition") or None
    if_available = bool(_IF_AVAILABLE_RE.search(str(condition or ""))
                        or _IF_AVAILABLE_RE.search(entry["quote"]))
    sends = [{"bus": s["bus"].strip(), "mode": s.get("mode"), "level_db": s.get("level_db")}
             for s in entry.get("sends") or []]
    return Strip(name=entry["name"].strip(), bank=bank, number=number, group=group,
                 sockets=sockets, stereo=stereo, stereo_why=why,
                 preset=(entry.get("preset") or None), category=(entry.get("category") or None),
                 main_direct=entry.get("main_direct"), sends=sends,
                 if_available=if_available, condition=condition,
                 quote=clean_quote(entry["quote"])), None


def parse_strips(text: str, *, resolved_name: str = "resolved conventions") -> ParsedStrips:
    """The resolved file's Instructed strips block, checked. Never raises.

    No section is one INFO (a file made before 2026-10-01: the generator
    builds them, as before). Not JSON, or not the shape, is one WARNING,
    and code builds none. An entry code cannot build (a socket it cannot
    read, a strip number the console does not have, a name used twice) is
    a WARNING naming it, and the others are built."""
    from atoo.diagnostics import Diagnostic, Severity
    from atoo.schema_check import validate as validate_schema

    body = strips_section(text)
    if body is None:
        return ParsedStrips([], [Diagnostic(
            severity=Severity.INFO, code=CODE_STRIPS_MISSING, where=resolved_name,
            source="build",
            message=(f"{resolved_name} has no '## {STRIPS_HEADING}' section (it was made before "
                     "code built the strips the conventions ask for), so code builds none: a "
                     "strip the conventions ask for is the generator's to build, as before"),
            fix="resolve again (`atoo resolve`) to add the block")], "missing", "no block")

    def invalid(reason: str) -> ParsedStrips:
        return ParsedStrips([], [Diagnostic(
            severity=Severity.WARNING, code=CODE_STRIPS_INVALID,
            where=f"{resolved_name} § {STRIPS_HEADING}", source="build",
            message=(f"the Instructed strips block in {resolved_name} is not used: {reason}. "
                     "Code builds none of them; a strip the conventions ask for is the "
                     "generator's to build, as before"),
            fix="resolve again (`atoo resolve`)")], "invalid", reason)

    fence = _FENCE_RE.search(body)
    raw = fence.group(2) if fence else body
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return invalid(f"it is not JSON ({exc})")
    if isinstance(data, dict) and isinstance(data.get("strips"), list):
        data = data["strips"]
    violations = validate_schema(data, STRIPS_SCHEMA, path="strips")
    if violations:
        more = f" (and {len(violations) - 3} more)" if len(violations) > 3 else ""
        return invalid("; ".join(violations[:3]) + more)
    strips: list[Strip] = []
    findings: list = []
    seen: set[str] = set()
    for entry in data:
        strip, why = _strip_from_entry(entry)
        key = conventions_audit.normalise(entry["name"])
        if strip is not None and key in seen:
            strip, why = None, "another entry has the same name"
        if strip is None:
            findings.append(Diagnostic(
                severity=Severity.WARNING, code=CODE_STRIP_INVALID,
                where=f"{resolved_name} § {STRIPS_HEADING}", line=entry.get("quote"),
                source="build",
                message=(f"the instructed strip {entry['name']!r} is not built by code: {why}. "
                         "It is the generator's to build, from the resolved rules"),
                fix="resolve again (`atoo resolve`), or reword the conventions line"))
            continue
        seen.add(key)
        strips.append(strip)
    return ParsedStrips(strips, findings, "valid")


def drop_unquoted(parsed: ParsedStrips, conventions: str, *, conventions_name: str,
                  resolved_name: str) -> ParsedStrips:
    """`parsed` without each strip whose quote is not in the conventions --
    a strip the engineer never asked for is invention, and code does not
    build it (one WARNING each). The others are returned as they were."""
    from atoo.diagnostics import Diagnostic, Severity

    layers = [Layer("conventions", conventions_name, conventions)]
    kept, findings = [], list(parsed.findings)
    for strip in parsed.strips:
        if find(strip.quote, layers) is not None:
            kept.append(strip)
            continue
        findings.append(Diagnostic(
            severity=Severity.WARNING, code=CODE_STRIP_INVALID,
            where=f"{resolved_name} § {STRIPS_HEADING}", line=strip.quote, source="build",
            message=(f"the instructed strip {strip.name!r} is not built by code: its quote "
                     f"{strip.quote!r} {not_found_reason(strip.quote, layers)}"),
            fix="resolve again (`atoo resolve`)"))
    return ParsedStrips(kept, findings, parsed.state, parsed.reason)


def strips_prompt_note(strips: list[Strip]) -> str:
    """The generator's instruction: the strips code builds, so it builds
    none of them, and may name them in a bus's sends."""
    lines = []
    for s in strips:
        bits = [f"{s.bank} {s.number}" if s.number is not None else f"a {s.bank} strip"]
        bits.append(f"from {s.spelled_source}" + (" if available" if s.if_available else ""))
        if s.stereo:
            bits.append("stereo")
        if s.preset:
            bits.append(f"preset {s.preset!r}")
        if s.category:
            bits.append(f"category {s.category}")
        lines.append(f"- {s.name}: " + ", ".join(bits))
    return ("## Strips code builds for you\n\n"
            "The conventions ask for these strips, which are not input-list rows. Code builds "
            "each one: its strip, socket, stereo pair, preset, category settings, Main routing "
            "and the sends the conventions state for it. Write no channel for any of them, and "
            "put no input-list row on its strip or socket. You may name one in a bus's "
            "`sends.from`; that send is yours.\n\n" + "\n".join(lines))
