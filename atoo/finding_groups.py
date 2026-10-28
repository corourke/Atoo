"""Group repeated findings in what a person READS (FR-X.15c).

A real build of a 24-channel show printed
about sixty notes and warnings -- far too much noise.
Most of them said one thing once per channel -- the plan's high-pass
beat the preset's, twenty-two times; "patch socket was not stated",
twenty-three times; one "declared but unused" note per empty DCA.

So the terminal (`build`, `verify`, `apply`) and the Setup UI's findings
list show **one entry per distinct message**, naming the items it covers
compactly:

    NOTE     ch 1-22 (22 channels): the plan's own processing wins at 2
             address(es) the preset … also sets -- flt/lcf preset
             20.0..200.0 -> plan 40.0..120.0; flt/lc 1 (both agree)

and **every finding stays in the data, unchanged**. `plan.json`'s
`meta.build_findings`/`verify_findings` and an apply journal's
`warnings` hold one entry per item exactly as before; this module only
ever builds a *display* list from them. The UI, `lessons` and anything
else that reads the data sees what it always saw.

How findings are grouped
------------------------

Two findings share an entry when they have the same severity, code,
source, fix, issue, title and category, and the same message once the
item it is about is taken out of it:

* **The item** is read from the message's own prefix
  (``ch 10 ('Sample Pad'): ...``, the form `apply` and the preset layer
  write) or, failing that, from a structured `where`
  (``busses[Drums]``, ``plan.dcas[Tracks]``, ``channels[Kick].patch``).
  A finding with neither -- a critic's free-text `where`, a model note --
  is about no nameable item and is never grouped.
* **An ERROR or a WARNING** groups only when the rest of the message is
  *identical*: something a person must act on never has a value hidden
  behind a summary.
* **An INFO** groups on the message's *template*: quoted strings and
  numbers are slots. Where every member has the same value, the value is
  shown; where they differ, a numeric slot shows its range (``20.0..200.0``)
  and a text slot shows ``…``. The per-item values are in the data.

Severity is never changed, and an ERROR is never grouped with anything
but ERRORs -- severity is part of the key.

A few codes read better with a summary of their own (`_HOOKS`):
``conventions.unused`` and ``group.empty`` become one list of the
declared-but-empty groups; ``inferred.*`` keeps the decided value exact
and lists the distinct reasons given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from atoo.diagnostics import Diagnostic, Severity


# ---- the item a finding is about ---------------------------------------

# "ch 10 ('Sample Pad'): the plan's own processing wins ..." -- the prefix
# `apply` and `preset_expand` put on a per-strip message.
_ITEM_PREFIX = re.compile(
    r"^(?P<bank>ch|aux|bus|mtx|main|dca|channel)\s+(?P<num>\d+)"
    r"(?:\s*\((?P<name>[^)]*)\))?:\s+(?P<rest>.+)$",
    re.S,
)
# "busses[Drums]", "plan.dcas[Tracks]", "channels[Kick].patch".
_WHERE = re.compile(r"^(?P<kind>[A-Za-z_][\w.]*)\[(?P<key>[^\[\]]+)\](?P<tail>.*)$")

# A slot in a message template: a quoted string, or a number standing on
# its own (not the 50 in "AES50-A", not the 0 in "0dB").
# A quote opens only after a non-word character and closes only before
# one, so the apostrophe in "the plan's own" is not a quote.
_SLOT = re.compile(r"(?<!\w)'[^']*'(?!\w)|(?<!\w)\"[^\"]*\"(?!\w)"
                   r"|(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_PLACEHOLDER = "\x00"

# How many names a grouped entry spells out before it says "and N more".
MAX_NAMES = 16

_NOUNS = {"ch": "channels", "aux": "channels", "channels": "channels",
          "busses": "busses", "bus": "busses", "outputs": "outputs"}


@dataclass(frozen=True)
class Item:
    """What one finding is about: ("ch", "10", "") or ("busses", "Drums", "")."""

    kind: str
    key: str
    tail: str = ""
    bracketed: bool = False   # rendered kind[keys]tail, as the `where` was written


def item_of(d: Diagnostic) -> tuple[Item | None, str]:
    """(the item, the message with the item's own prefix taken off)."""
    m = _ITEM_PREFIX.match(d.message)
    if m:
        bank = "ch" if m["bank"] == "channel" else m["bank"]
        return Item(bank, m["num"]), m["rest"]
    w = _WHERE.match(d.where or "")
    if w:
        return Item(w["kind"], w["key"].strip(), w["tail"], bracketed=True), d.message
    return None, d.message


def template(text: str) -> tuple[str, tuple[str, ...]]:
    """("ch \\0: preset \\0 -> plan \\0", ("10", "'Synth'", "40.0"))."""
    values = tuple(m.group(0) for m in _SLOT.finditer(text))
    return _SLOT.sub(_PLACEHOLDER, text), values


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _fill(tmpl: str, columns: list[list[str]]) -> str:
    """The template with each slot summarised across the group."""
    parts = tmpl.split(_PLACEHOLDER)
    out = [parts[0]]
    for column, after in zip(columns, parts[1:]):
        distinct = list(dict.fromkeys(column))
        if len(distinct) == 1:
            shown = distinct[0]
        else:
            numbers = [_number(v) for v in column]
            if all(n is not None for n in numbers):
                lo = column[numbers.index(min(numbers))]
                hi = column[numbers.index(max(numbers))]
                shown = f"{lo}..{hi}"
            else:
                shown = "…"
        out += [shown, after]
    return "".join(out)


def _ranges(numbers: list[int]) -> str:
    """[1, 2, 3, 5, 7, 8] -> "1-3, 5, 7-8"."""
    numbers = sorted(set(numbers))
    runs, start, prev = [], None, None
    for n in numbers:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            runs.append((start, prev))
            start = prev = n
    if start is not None:
        runs.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def _names(keys: list[str]) -> str:
    keys = list(dict.fromkeys(keys))
    if all(k.isdigit() for k in keys):
        return _ranges([int(k) for k in keys])
    if len(keys) > MAX_NAMES:
        return ", ".join(keys[:MAX_NAMES]) + f" and {len(keys) - MAX_NAMES} more"
    return ", ".join(keys)


def items_label(items: list[Item]) -> str:
    """"ch 1-22 (22 channels)", "busses[Drums, Keys] (2 busses)"."""
    by_kind: dict[tuple, list[str]] = {}
    for it in items:
        by_kind.setdefault((it.kind, it.tail, it.bracketed), []).append(it.key)
    parts = []
    for (kind, tail, bracketed), keys in by_kind.items():
        names = _names(keys)
        parts.append(f"{kind}[{names}]{tail}" if bracketed else f"{kind} {names}")
    count = len(set(items))
    nouns = {_NOUNS.get(it.kind, "items") for it in items}
    noun = nouns.pop() if len(nouns) == 1 else "items"
    return f"{'; '.join(parts)} ({count} {noun})"


# ---- per-code summaries -------------------------------------------------

class _Hook:
    """A code that reads better with a summary of its own.

    `key` returns None when this finding does not fit the shape the hook
    knows (it is then grouped, or not, by the default rule), else
    (a grouping key, the item it names). `summarise` returns the one
    entry a person reads for the whole group."""

    def key(self, d: Diagnostic):
        raise NotImplementedError

    def summarise(self, members: list[Diagnostic], items: list) -> Diagnostic:
        raise NotImplementedError


def _name_from_line(line: str) -> str:
    """The group a conventions line declares: 'Horns' from
    "Horns: all horns-category channels", 'Keys' from
    'If there are multiple keyboards, create a "Keys" bus.'"""
    quoted = re.search(r'"([^"]+)"', line)
    if quoted:
        return quoted.group(1).strip()
    colon = re.match(r"^\s*([^:]{1,40}):", line)
    if colon:
        return colon.group(1).strip()
    return line.strip()


class _UnusedConventions(_Hook):
    """Several `conventions.unused` notes become one list:

        declared but unused in this show: DCAs Horns, Speech, Strings,
        Tracks; Mute Groups Speech

    Only a note that quotes ONE line is grouped: one that quotes several
    already covers several groups in one entry, and its first quote's
    section is all the finding records -- listing its other names under
    that section could put a mute group among the DCAs."""

    def key(self, d):
        if not d.line or '"; "' in d.message.partition(" -- quoting ")[2]:
            return None
        section = d.category or d.where.partition(" § ")[2] or d.where
        return ("unused",), (section, _name_from_line(d.line), d.where.partition(" § ")[0])

    def summarise(self, members, items):
        sections: dict[str, list[str]] = {}
        for section, name, _role in items:
            sections.setdefault(section, [])
            if name not in sections[section]:
                sections[section].append(name)
        roles = list(dict.fromkeys(role for _s, _n, role in items if role))
        listed = "; ".join(f"{section} {', '.join(sorted(names, key=str.casefold))}"
                           for section, names in sections.items())
        return replace(members[0], where=", ".join(roles),
                       message=f"declared but unused in this show ({len(members)}): {listed}",
                       line="", category="")


class _EmptyGroups(_Hook):
    """Verify's `group.empty`, one per DCA or mute group, as one list."""

    _KIND = {"dcas": ("DCA", "DCAs"), "mute_groups": ("mute group", "mute groups")}
    _TEXT = "is declared but no channel or bus joins it -- it does nothing"

    def key(self, d):
        w = _WHERE.match(d.where or "")
        if not w or not d.message.endswith(self._TEXT) or w["tail"]:
            return None
        kind = w["kind"].rpartition(".")[2]
        if kind not in self._KIND:
            return None
        return ("empty",), (kind, w["key"].strip())

    def summarise(self, members, items):
        by_kind: dict[str, list[str]] = {}
        for kind, name in items:
            by_kind.setdefault(kind, []).append(name)
        parts = []
        for kind, names in by_kind.items():
            one, many = self._KIND[kind]
            parts.append(f"{one if len(names) == 1 else many} "
                         f"{', '.join(sorted(names, key=str.casefold))}")
        return replace(members[0], where="; ".join(parts),
                       message="declared, but no channel or bus joins them -- they do nothing")


class _Inferred(_Hook):
    """`inferred.*`: the decided value stays exact -- only findings that
    decided the SAME thing share an entry -- and the reasons given are
    listed once each rather than once per bus."""

    _SPLIT = re.compile(r"^(?P<head>.*?); (?P<by>decided by [^:]+): (?P<basis>.*)$", re.S)

    # "Main index set to 1" / "Matrix index set to 1": the strip's kind
    # is already in the item (`outputs[Main]`), so it is not what was
    # decided -- the index is.
    _KIND_WORD = re.compile(r"^(?:Main|Matrix) (?=index set to )")

    def _head(self, head: str) -> str:
        return self._KIND_WORD.sub("", head)

    def key(self, d):
        m = self._SPLIT.match(d.message)
        item, _rest = item_of(d)
        if not m or item is None:
            return None
        return (self._head(m["head"]), m["by"]), (item, m["basis"].strip())

    def summarise(self, members, items):
        m = self._SPLIT.match(members[0].message)
        bases = list(dict.fromkeys(basis for _item, basis in items if basis))
        shown = " / ".join(bases[:3])
        if len(bases) > 3:
            shown += f" / and {len(bases) - 3} other reason(s)"
        return replace(members[0], where=items_label([it for it, _b in items]),
                       message=f"{self._head(m['head'])}; {m['by']}: {shown}")


class _Sends(_Inferred):
    """`inferred.send-level` / `inferred.send-mode`, already one per bus
    (`inferred.py` names the channels in each), and still one per bus:
    eight busses whose sends all start at unity for the same reason are
    one entry. The level or mode stays exact; which channels send to
    which bus is the plan's own `sends`, and each finding in the data
    still lists them."""

    _SENDS = re.compile(r"^sends into (?P<bus>.+?) set (?P<what>.+?) on (?P<n>\d+) "
                        r"channel\(s\) \((?P<channels>.*?)\) -- (?P<rest>.*)$", re.S)

    def key(self, d):
        m = self._SENDS.match(d.message)
        item, _rest = item_of(d)
        if not m or item is None:
            return None
        rest = m["rest"].replace(m["bus"], "the bus")
        return (m["what"], rest), (item, int(m["n"]), rest)

    def summarise(self, members, items):
        m = self._SENDS.match(members[0].message)
        total = sum(n for _item, n, _rest in items)
        return replace(members[0], where=items_label([it for it, _n, _r in items]),
                       message=f"sends set {m['what']} on {total} channel send(s) in all "
                               f"-- {items[0][2]}")


_INFERRED = _Inferred()
_HOOKS: dict[str, _Hook] = {
    "conventions.unused": _UnusedConventions(),
    "group.empty": _EmptyGroups(),
    "inferred.send-level": _Sends(),
    "inferred.send-mode": _Sends(),
}


def _hook_for(code: str) -> _Hook | None:
    if code in _HOOKS:
        return _HOOKS[code]
    if code.startswith("inferred."):
        return _INFERRED
    return None


# ---- grouping -----------------------------------------------------------

@dataclass
class Group:
    """One entry a person reads, and the findings it stands for."""

    entry: Diagnostic
    members: list[Diagnostic]

    @property
    def grouped(self) -> bool:
        return len(self.members) > 1


def _base_key(d: Diagnostic) -> tuple:
    # Severity first: a WARNING never shares an entry with a NOTE, and an
    # ERROR with nothing but ERRORs.
    return (d.severity, d.code, d.source, d.title, d.fix, d.issue)


def _default_key(d: Diagnostic):
    item, rest = item_of(d)
    if item is None:
        return None
    if d.severity == Severity.INFO:
        tmpl, values = template(rest)
    else:
        tmpl, values = rest, ()
    return (item.kind, item.tail, item.bracketed, tmpl, d.line, d.category), (item, values)


def _default_summary(members: list[Diagnostic], payloads: list) -> Diagnostic:
    items = [item for item, _values in payloads]
    tmpl = _default_key(members[0])[0][3]
    columns = [list(col) for col in zip(*(values for _item, values in payloads))]
    message = _fill(tmpl, columns) if columns else tmpl
    return replace(members[0], where=items_label(items), message=message)


def groups(diagnostics) -> list[Group]:
    """The display entries for `diagnostics`, in the order of each
    entry's first member. A finding that nothing repeats is its own
    entry, unchanged."""
    order: list[tuple] = []
    buckets: dict[tuple, tuple[list, list, object]] = {}
    for i, d in enumerate(diagnostics):
        hook = _hook_for(d.code)
        keyed = hook.key(d) if hook else None
        tag, summarise = (type(hook).__name__, hook.summarise) if keyed is not None \
            else ("default", _default_summary)
        if keyed is None:
            keyed = _default_key(d)
        if keyed is None:
            key: tuple = ("single", i)
            payload = None
        else:
            key = (_base_key(d), tag, keyed[0])
            payload = keyed[1]
        if key not in buckets:
            buckets[key] = ([], [], summarise)
            order.append(key)
        members, payloads, _ = buckets[key]
        members.append(d)
        payloads.append(payload)

    out = []
    for key in order:
        members, payloads, summarise = buckets[key]
        if len(members) == 1:
            out.append(Group(members[0], members))
        else:
            out.append(Group(summarise(members, payloads), members))
    return out


def group(diagnostics) -> list[Diagnostic]:
    """Just the entries: what `diagnostics.render()` and
    `VerifyResult.report()` print."""
    return [g.entry for g in groups(diagnostics)]


def group_dicts(findings: list[dict]) -> list[dict]:
    """The same grouping over `Diagnostic.to_dict()` dicts, for the Setup
    UI. A grouped entry carries `members` -- the findings it stands for,
    as they were -- so the page can still jump to each item's row; a
    single finding is passed through untouched (every key it had, UI-only
    ones included)."""
    parsed = []
    for f in findings:
        try:
            parsed.append(Diagnostic.from_dict(f))
        except (KeyError, TypeError, ValueError, AttributeError):
            # Not a finding this build would write (a very old plan's);
            # shown as it is, grouped with nothing.
            parsed.append(Diagnostic(Severity.INFO, "", "", source=f"unparsed-{len(parsed)}"))
    by_id = {id(d): f for d, f in zip(parsed, findings)}
    out = []
    for g in groups(parsed):
        if not g.grouped:
            out.append(by_id[id(g.members[0])])
            continue
        entry = g.entry.to_dict()
        entry["members"] = [by_id[id(m)] for m in g.members]
        out.append(entry)
    return out


def group_lines(lines) -> list[str]:
    """`apply`'s plain-string warnings, grouped the same way.

    A line that starts ``INFO `` is an INFO; every other line is a
    WARNING, so it groups only with lines saying exactly the same thing
    about a different strip:

        ch 1-23 (23 channels): patch socket was not stated in the input
        list and was assigned during generation -- verify before trusting
        this write
    """
    diags = []
    for line in lines:
        text = str(line)
        if text.startswith("INFO "):
            diags.append(Diagnostic(Severity.INFO, "", text[5:], source="INFO"))
        else:
            diags.append(Diagnostic(Severity.WARNING, "", text))
    out = []
    for g in groups(diags):
        d = g.entry
        text = f"{d.where}: {d.message}" if g.grouped else d.message
        out.append(f"INFO {text}" if d.source == "INFO" else text)
    return out


# ---- the dock's INFO rows, by code ------------------------
#
# The notes under a rebuilt plan were simply
# too many of them. The Setup UI's findings dock therefore collapses
# every INFO under one "N info" toggle and, opened, shows ONE ROW PER CODE:
# a count and a plain-English summary, each opening onto its items (which
# are this module's `group_dicts` entries, unchanged). Errors and warnings
# are never folded this way.
#
# The page buckets by `code` and nothing else -- the message-level grouping
# above stays the only grouping there is. What it needs from here is the
# words: (singular noun, plural noun, what the code says), for
#
#     22 channels: the plan's own processing replaced a value its preset sets
#
# The noun counts the items a row stands for (a grouped entry's `members`,
# else one). A code missing from this table still gets a row, reading
# "N notes: <code>"; `code_summary` gives the same text to Python callers.

CODE_SUMMARIES: dict[str, tuple[str, str, str]] = {
    "preset.overridden": ("channel", "channels",
                          "the plan's own processing replaced a value its preset sets"),
    "preset.expanded": ("note", "notes", "preset values carried into the plan"),
    "preset.bus-expanded": ("note", "notes", "bus preset values carried into the plan"),
    "preset.leaf-not-on-strip": ("channel", "channels",
                                 "preset values for a node the strip does not have, left out"),
    "preset.value-not-on-strip": ("channel", "channels",
                                  "a preset choice the strip does not offer, carried as its "
                                  "equivalent or left out"),
    "preset.library-changed": ("channel", "channels",
                               "the library's preset changed since the build; the plan's values stand"),
    "reply.category-rule": ("category", "categories",
                            "code filled fields the reply left out, from the Category table"),
    "fx.inserts": ("note", "notes", "FX inserts loaded and switched on, each read back"),
    "fx.parameter-typed-from-value": ("bus", "busses",
                                      "effect parameters written with their saved value's type"),
    "reply.category-group-declared": ("group", "groups",
                                      "a DCA or mute group declared from the Category table"),
    "reply.instructed-strip": ("strip", "strips",
                               "built by code because the conventions ask for it"),
    "reply.instructed-strip-row": ("strip", "strips",
                                   "an instructed strip matched to an input-list row"),
    "reply.instructed-strip-sends": ("strip", "strips", "an instructed strip's sends, written by code"),
    "reply.channels-numbered": ("note", "notes", "channels numbered in the reply's order"),
    "reply.sockets-chosen": ("note", "notes", "sockets chosen by code"),
    "reply.sends-expanded": ("note", "notes", "bus sends written from the busses' sender lists"),
    "reply.colours-applied": ("note", "notes", "colors written from the conventions"),
    "reply.name-cut": ("name", "names", "a name cut to fit the desk"),
    "reply.pair-phantom": ("channel", "channels",
                           "a stereo pair's two input-list rows disagreed about 48V; the pair "
                           "takes it if either wants it"),
    "reply.line-gain": ("channel", "channels",
                        "a Line source's head-amp gain chosen from its type, not copied from "
                        "the mic channels"),
    "inferred.pair-phantom": ("channel", "channels",
                              "one 48V value for a stereo pair, read as both sockets'"),
    "reply.from-instructions": ("strip", "strips",
                                "built from the instructions, not the input list"),
    # A WARNING or (asked for verbatim) an INFO; the dock
    # gathers several strips' copies of it into one row, and
    # that row reads these words.
    "reconcile.from-instructions": ("strip", "strips",
                                    "built from instructions.md, not on the input list"),
    "apply.init": ("note", "notes", "what a full apply's reset to the initialized desk does"),
    "inferred.output-index": ("output", "outputs", "an output index the plan left out, decided"),
    "inferred.channel-stereo": ("channel", "channels", "stereo decided where no convention states it"),
    "inferred.bus-width": ("bus", "busses", "mono or stereo decided where no convention states it"),
    "inferred.bus-destination": ("bus", "busses", "a destination decided where none was stated"),
    "inferred.bus-main-index": ("bus", "busses", "which Main a bus feeds, decided"),
    "inferred.send-level": ("bus", "busses", "send levels decided where none was stated"),
    "inferred.send-mode": ("bus", "busses", "send pre/post decided where none was stated"),
    "strip.colour-alias": ("note", "notes", "a color name read as the desk's own"),
    "conventions.unused": ("note", "notes", "declared in the conventions, unused in this show"),
    "group.empty": ("note", "notes", "a DCA or mute group with no members"),
    "bus.empty": ("bus", "busses", "a bus nothing sends to"),
    "critic.conventions": ("note", "notes", "the critic on the conventions text"),
    "build.resolved-conventions": ("note", "notes", "the resolved conventions a build reads"),
    "build.watchlist-drafted": ("note", "notes", "watch conditions drafted by the build"),
    "build.fixup": ("note", "notes", "a fix-up round the build ran"),
    "bundle.copied-in": ("file", "files", "copied into the show bundle"),
    "apply.journalled": ("run", "runs", "written and journalled -- undo reverses it"),
    "apply.journal-note": ("note", "notes", "the apply journal's notes"),
}


def code_summary(code: str, count: int) -> str:
    """ "22 channels: the plan's own processing replaced a value its preset
    sets" -- the dock's row for `count` INFO items with this code."""
    one, many, words = CODE_SUMMARIES.get(code, ("note", "notes", code or "uncoded"))
    return f"{count} {one if count == 1 else many}: {words}"


# ---- build details: how the reply was read, not what was chosen ---------
#
# The dock and step 04's Plan
# notes listed "channels numbered in the order the reply listed them",
# "each channel's bus_sends written from the busses' sender lists" and
# "[repair] reply: 'unassigned_inputs' left out once; read as an empty
# list" beside the choices an engineer might disagree with. Those say how
# Atoo read the model's reply -- its plumbing -- and a newcomer reads
# them as something to act on and can't.
#
# So these are BUILD DETAILS: kept, every one, but shown apart from the
# choices (the page's "Build details" fold; the CLI still prints them).
# What makes a code one: its note describes a mechanism, and what it
# produced is shown elsewhere in its own right --
#
# * `reply.channels-numbered`, `reply.colours-applied`,
#   `reply.sends-expanded`: the numbers, colours and sends are on step
#   04's tables;
# * `reply.from-instructions`: verify's `reconcile.from-instructions`
#   note says the same thing about the same strip;
# * `reply.category-rule`: code writing what the
#   conventions' Category table says -- the conventions obeyed, not a
#   choice where they were silent; the values are on step 04's tables;
# * `preset.expanded`, `preset.bus-expanded`, `fx.inserts`,
#   `fx.parameter-typed-from-value`: which presets' values a
#   plan carries, and how an effect's parameters are typed -- the presets
#   are named on step 04's rows, and each value is read back by apply.
#   The two FX notes that ARE choices stay notes: `fx.engine-allocated`
#   (which FX engine an effect goes into) and `fx.insert-switched-on` (a
#   preset saved bypassed, switched on);
# * `build.fixup` (a fix-up round that PASSED -- `build.fixup-unresolved`
#   is a WARNING), `build.resolved-conventions` (which file a build
#   reads), `apply.init` (what a full apply's reset does, every time).
#
# Only an INFO is ever a build detail. An ERROR or a WARNING is something
# to act on whatever its code says, and is never folded away.

BUILD_DETAIL_CODES: frozenset[str] = frozenset({
    "reply.channels-numbered",
    "reply.colours-applied",
    "reply.sends-expanded",
    "reply.from-instructions",
    "reply.category-rule",
    "preset.expanded",
    "preset.bus-expanded",
    "fx.inserts",
    "fx.parameter-typed-from-value",
    "build.fixup",
    "build.resolved-conventions",
    "apply.init",
})

#: A plan note (`plan["notes"]`) from one of these sources is a build
#: detail too: a `repair` note says how `reply_expand.repair_reply` read a
#: slip in the reply (`plan_schema.NOTE_SOURCES`).
DETAIL_NOTE_SOURCES: frozenset[str] = frozenset({"repair"})


def is_build_detail(finding: "Diagnostic | dict") -> bool:
    """True for an INFO whose code is in `BUILD_DETAIL_CODES`; never for
    an ERROR or a WARNING."""
    if isinstance(finding, Diagnostic):
        severity, code = finding.severity.value, finding.code
    else:
        severity, code = finding.get("severity"), finding.get("code")
    return severity == Severity.INFO.value and code in BUILD_DETAIL_CODES


def is_detail_note(note: object) -> bool:
    """True for a plan note whose `source` is in `DETAIL_NOTE_SOURCES`.
    A bare-string note has no source and is not one."""
    return isinstance(note, dict) and note.get("source") in DETAIL_NOTE_SOURCES


# ---- the strip a finding is about, as the desk names it ----
#
# The dock's one line per finding starts with WHERE it is, and a WING
# engineer reads a strip the way the desk labels it: "CH 23 Crowd",
# "AUX 2 HOST", "BUS 3 Drums" -- not `channels[HOST]`, which is the
# plan's own path. The plan has the bank and number; a finding usually
# has only the name (`where`) or the "ch 23 'Crowd'" prefix of its
# message. `label_strips` puts the desk's label on each finding as a
# UI-only `strip` key, beside every key it already had; a finding about
# no strip (a file, the plan as a whole) gets none, and the page says
# where it is in its own words.

_BANK_WORDS = {"ch": "CH", "channel": "CH", "aux": "AUX", "bus": "BUS",
               "mtx": "MTX", "matrix": "MTX", "main": "MAIN", "dca": "DCA"}
_OUTPUT_WORDS = {"main": ("MAIN", "main"), "matrix": ("MTX", "matrix")}
# "ch 23 'Crowd' reaches no Main", "ch 10 ('Sample Pad'): ...".
_STRIP_PREFIX = re.compile(
    r"^(?P<bank>ch|aux|bus|mtx|main|dca|channel)\s+(?P<num>\d+)(?![\w-])"
    r"(?:\s*\(\s*'?(?P<pname>[^)']*)'?\s*\)|\s+'(?P<qname>[^']*)')?", re.I)
# A critic's free-text `where`: "HOST (aux 2)", "Keys (ch 15)".
_NAME_THEN_BANK = re.compile(r"^(?P<name>.+?)\s*\((?P<bank>ch|aux|channel)\s*(?P<num>\d+)\)$", re.I)


def _int(value) -> "int | None":
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def desk_names(plan: "dict | None") -> dict:
    """What `strip_label` looks a finding up in: each strip of `plan`
    under ("ch", 23) / ("aux", 2) / ("bus", 3) and under its plan name
    ("channels", "crowd"), mapped to the desk's label for it. A name two
    strips share is left out: the label would be a guess."""
    names: dict = {}
    taken: dict = {}

    def add(by_number, by_name, label):
        if by_number is not None:
            names[by_number] = label
        if by_name is not None:
            taken[by_name] = taken.get(by_name, 0) + 1
            names[by_name] = label

    plan = plan if isinstance(plan, dict) else {}
    for c in plan.get("channels") or []:
        if not isinstance(c, dict):
            continue
        bank = c.get("bank") if c.get("bank") in ("ch", "aux") else "ch"
        number, name = _int(c.get("channel")), str(c.get("name") or "").strip()
        if number is None:
            continue
        label = f"{_BANK_WORDS[bank]} {number}" + (f" {name}" if name else "")
        add((bank, number), ("channels", name.casefold()) if name else None, label)
    for key, word, short in (("busses", "BUS", "bus"), ("dcas", "DCA", "dca"),
                             ("mute_groups", "MGRP", "mgrp")):
        block = plan.get(key)
        if not isinstance(block, dict):
            continue
        for name, entry in block.items():
            number = _int(entry.get("index")) if isinstance(entry, dict) else None
            if number is None:
                continue
            add((short, number), (key, str(name).casefold()), f"{word} {number} {name}")
    outputs = plan.get("outputs")
    for name, entry in (outputs.items() if isinstance(outputs, dict) else ()):
        if not isinstance(entry, dict) or entry.get("kind") not in _OUTPUT_WORDS:
            continue
        number = _int(entry.get("index"))
        if number is None:
            continue
        word, spoken = _OUTPUT_WORDS[entry["kind"]]
        # "Matrix 1" on MTX 1 says nothing the label does not.
        plain = str(name).casefold().replace(" ", "")
        same = plain in (spoken, f"{spoken}{number}", f"{word.casefold()}{number}")
        add(("mtx" if word == "MTX" else "main", number), ("outputs", str(name).casefold()),
            f"{word} {number}" + ("" if same else f" {name}"))
    for key, count in taken.items():
        if count > 1:
            names.pop(key, None)
    return names


def strip_label(finding: dict, names: dict) -> "str | None":
    """ "CH 23 Crowd" for a finding about channel 23, from its message's
    own "ch 23 'Crowd'" prefix, its `where` (`channels[Crowd]`), or a
    critic's "Crowd" / "HOST (aux 2)"; None when it is about no strip
    the plan has."""
    m = _STRIP_PREFIX.match(str(finding.get("message") or ""))
    if m:
        bank = m["bank"].lower()
        bank = "ch" if bank == "channel" else bank
        found = names.get((bank, int(m["num"])))
        if found:
            return found
        name = m["pname"] or m["qname"]
        return f"{_BANK_WORDS[bank]} {m['num']}" + (f" {name}" if name else "")
    where = str(finding.get("where") or "").strip()
    w = _WHERE.match(where)
    if w:
        kind = w["kind"].rpartition(".")[2]
        return names.get((kind, w["key"].strip().casefold()))
    if finding.get("source") == "critic" and where:
        for kind in ("channels", "busses", "outputs", "dcas", "mute_groups"):
            hit = names.get((kind, where.casefold()))
            if hit:
                return hit
        m = _NAME_THEN_BANK.match(where)
        if m:
            bank = "ch" if m["bank"].lower() == "channel" else m["bank"].lower()
            return names.get((bank, int(m["num"])))
    return None


def label_strips(findings: list[dict], plan: "dict | None") -> list[dict]:
    """Put `strip` on each finding (and each grouped entry's `members`)
    that is about a strip of `plan`. In place, and returned."""
    names = desk_names(plan)
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        for member in finding.get("members") or ():
            if isinstance(member, dict):
                label = strip_label(member, names)
                if label:
                    member["strip"] = label
        if finding.get("members"):
            continue
        label = strip_label(finding, names)
        if label:
            finding["strip"] = label
    return findings
