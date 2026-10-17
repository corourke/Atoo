"""What a rebuild changed against the plan it replaced (FR-1.4).

A model drafts the plan, so two builds of the same files are not promised
to match. That is exactly why a rebuild has to say what it changed: an
engineer edits one line of the conventions or adds one row to the input
list, rebuilds, and needs to see what moved -- and, above all, anything
that moved although nothing he edited is about it. That is the model
rewriting something it should have left alone.

This module is model-free and has no I/O. `compare(previous, current)`
takes two plans and returns a `PlanChanges`: one `StripChange` per strip
that differs, keyed by strip (bank and number), `meta` ignored.

## Matching

Strips are matched by identity first -- a channel by the input-list row it
is made from (`source.input`), a bus, DCA, mute group or output by its
name -- so a strip that moved number shows as **moved**, not as removed
and added. What is left is matched by slot (bank and number), which shows
a rename as a changed name. What is left after that was added or removed.

Compared field by field: every value `apply` could write. Not compared:
`provenance`, `description`, `inferred` and a source's `quote` (prose and
bookkeeping -- a reworded explanation is not a change to the desk), and a
preset's expanded values, which are compared as the preset file they come
from (its name and sha256), not leaf by leaf.

## Grading (an error of judgement is not an error of patching)

A change is **INFO** when something the strip is made from changed:

* a row of the input list it is made from (each built row's fingerprint is
  recorded at build time in `meta.change_basis.rows`), or, for a bus, DCA,
  mute group or output, a row of any channel that uses it;
* a line of the conventions or the instructions that names it -- its
  name, its source, its desk label ("CH 14", "BUS 3", "DCA 5"), its
  input-list category, or a bus, DCA or mute group it belongs to (the
  texts as built are recorded in `meta.change_basis.conventions`);
* the preset file its values come from;
* for a strip that only moved: any row added, removed or reordered, or a
  strip added or removed in the same bank.

A change to a strip none of that is true of is a **WARNING**, never an
error: the plan may still be right, and the engineer judges it.

**This is an approximation, and says so.** Which conventions lines "are
about" a strip is decided by the words in the line, not by understanding
it. When a changed line names no strip at all (a general rule, "monitor
sends are pre-fader"), every change is taken as asked for -- unless it
is a Markdown heading, or its words all still run on, in order, on the
other side (a re-wrapped line), which ask for nothing. When the
replaced plan has no `change_basis` (it was built before there was one),
the files' recorded sha256s are compared instead: unchanged files mean
every change was unasked; a changed file means every change is taken as
asked for. Each such fallback is an INFO note in `PlanChanges.notes`.
"""

from __future__ import annotations

import hashlib
import json
import re
import textwrap
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass

from atoo import conventions_text

#: Where `build` records what each strip was made from, and where it
#: keeps the comparison it made, in `plan["meta"]`.
BASIS_KEY = "change_basis"
CHANGES_KEY = "changes_since_previous"

INFO = "INFO"
WARNING = "WARNING"

ADDED, REMOVED, CHANGED, MOVED = "added", "removed", "changed", "moved"

#: Prose and bookkeeping, at any depth: not a value `apply` writes.
_IGNORED_KEYS = frozenset({"provenance", "description", "inferred", "quote"})

_COLLECTIONS = ("channels", "busses", "dcas", "mute_groups", "outputs")
_MISSING = object()


def _norm(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


# --------------------------------------------------------------------------
# The basis: what a build records about its inputs, for the next rebuild
# --------------------------------------------------------------------------

def row_fingerprint(row) -> str:
    """A short fingerprint of one input-list row, every column included
    (the model reads the row whole, notes too)."""
    data = asdict(row) if is_dataclass(row) else dict(row)
    text = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def conventions_lines(text: str | None) -> list[str]:
    """The lines of a conventions text that can change a build: comments
    stripped (no reader of the conventions sees them), blank lines
    dropped, whitespace collapsed."""
    if not text:
        return []
    out = []
    for line in conventions_text.strip_comments(text).splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out.append(line)
    return out


def _slot_key(bank, number) -> str:
    return f"{bank}:{number}"


def basis(plan: dict, rows, layers) -> dict:
    """What `plan` was made from, recorded in `meta.change_basis` so the
    next rebuild can tell an asked-for change from one nobody asked for.

    `rows` are the built input-list rows (`InputRow`s, skipped rows left
    out), in file order; `layers` is `[(role, text), ...]` for the
    conventions and the instructions, as built."""
    from atoo.input_list import rows_feeding

    rows = list(rows or ())
    feeding = {}
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict) or not isinstance(ch.get("channel"), int):
            continue
        feeding[_slot_key(ch.get("bank") or "ch", ch["channel"])] = [
            _norm(r.name) for r in rows_feeding(ch, rows)]
    return {
        "rows": {_norm(r.name): {"sha": row_fingerprint(r), "category": r.category}
                 for r in rows},
        "channels": feeding,
        "conventions": {role: conventions_lines(text) for role, text in layers},
    }


# --------------------------------------------------------------------------
# Strips, flattened
# --------------------------------------------------------------------------

def _is_patch(value) -> bool:
    return isinstance(value, dict) and "group" in value and "sockets" in value


def _patch_text(value) -> str:
    sockets = "+".join(str(s) for s in value.get("sockets") or [])
    return f"{value.get('group')} {sockets}".strip()


def _preset_summary(value: dict) -> str:
    """A preset's expanded values, as the file they came from."""
    name = value.get("file") or value.get("preset") or "preset values"
    sha = value.get("sha256")
    if not sha:
        bare = {k: v for k, v in value.items() if k != "library"}
        sha = hashlib.sha256(json.dumps(bare, sort_keys=True, default=str)
                             .encode("utf-8")).hexdigest()
    return f"{name} ({sha[:8]})"


def _flatten(value, path: str, out: dict) -> None:
    if isinstance(value, dict):
        if path and _is_patch(value):
            out[path] = _patch_text(value)
            return
        for key, sub in value.items():
            if key in _IGNORED_KEYS:
                continue
            sub_path = f"{path}.{key}" if path else key
            if key == "preset_values" and isinstance(sub, dict):
                out[sub_path] = _preset_summary(sub)
            else:
                _flatten(sub, sub_path, out)
        return
    if isinstance(value, list):
        if value and all(isinstance(x, dict) for x in value):
            for key in ("bus", "index", "name"):
                if all(key in x for x in value):
                    for x in value:
                        _flatten({k: v for k, v in x.items() if k != key},
                                 f"{path}[{x[key]}]", out)
                        out.setdefault(f"{path}[{x[key]}]", "on")
                    return
        if not value:
            return       # an empty list sets nothing: the same as no list
        if all(isinstance(x, str) for x in value):
            out[path] = tuple(sorted(value))
            return
        out[path] = json.dumps(value, sort_keys=True, default=str)
        return
    out[path] = value


@dataclass
class _Strip:
    collection: str
    identity: str
    slot: tuple          # (bank word, number)
    name: str
    label: str
    values: dict
    record: dict
    refs: set            # (collection, name) this strip belongs to / sends to


_WORDS = {"ch": "CH", "aux": "AUX", "bus": "BUS", "dca": "DCA", "mgrp": "MGRP",
          "main": "MAIN", "matrix": "MTX"}


def _strips(plan: dict) -> dict[str, list[_Strip]]:
    plan = plan if isinstance(plan, dict) else {}
    out: dict[str, list[_Strip]] = {c: [] for c in _COLLECTIONS}
    seen: Counter = Counter()
    for ch in plan.get("channels") or []:
        if not isinstance(ch, dict):
            continue
        bank = ch.get("bank") if ch.get("bank") in ("ch", "aux") else "ch"
        number = ch.get("channel")
        source = ch.get("source") if isinstance(ch.get("source"), dict) else {}
        identity = _norm(source.get("input") or ch.get("name"))
        seen[identity] += 1
        if seen[identity] > 1:
            identity = f"{identity}#{seen[identity]}"
        name = str(ch.get("name") or "")
        values: dict = {}
        _flatten({k: v for k, v in ch.items() if k not in ("channel", "bank")}, "", values)
        refs = {("busses", s.get("bus")) for s in ch.get("bus_sends") or []
                if isinstance(s, dict)}
        refs |= {("dcas", d) for d in ch.get("dca") or []}
        refs |= {("mute_groups", m) for m in ch.get("mute_group") or []}
        refs |= {("main", r.get("index")) for r in ch.get("main_routes") or []
                 if isinstance(r, dict)}
        out["channels"].append(_Strip(
            "channels", identity, (bank, number), name,
            f"{_WORDS[bank]} {number}" + (f" {name}" if name else ""), values, ch, refs))
    for collection, word in (("busses", "bus"), ("dcas", "dca"), ("mute_groups", "mgrp"),
                             ("outputs", None)):
        block = plan.get(collection)
        if not isinstance(block, dict):
            continue
        for name, entry in block.items():
            if not isinstance(entry, dict):
                entry = {"value": entry}
            kind = word or str(entry.get("kind") or "output")
            number = entry.get("index")
            values = {"name": str(name)}
            _flatten({k: v for k, v in entry.items() if k != "index"}, "", values)
            refs = {("dcas", d) for d in entry.get("dca") or [] if isinstance(d, str)}
            refs |= {("mute_groups", m) for m in entry.get("mute_group") or []
                     if isinstance(m, str)}
            label = f"{_WORDS.get(kind, kind.upper())} {number}" if number is not None \
                else _WORDS.get(kind, kind.upper())
            out[collection].append(_Strip(
                collection, _norm(name), (kind, number), str(name), f"{label} {name}",
                values, entry, refs))
    return out


def _slot_label(strip: _Strip) -> str:
    kind, number = strip.slot
    return f"{_WORDS.get(kind, str(kind).upper())} {number}"


# --------------------------------------------------------------------------
# One changed value, in the desk's terms
# --------------------------------------------------------------------------

_FIELD_WORDS = {
    "name": "name", "color": "colour", "col": "colour", "icon": "icon",
    "patch": "patch", "alt_patch": "alternate patch", "fader.fader_db": "fader",
    "fader.muted": "mute", "processing.hpf_hz": "HPF", "processing.gain_db": "gain",
    "processing.trim_db": "trim", "processing.preset": "preset",
    "processing.preset_values": "preset values", "preset_values": "preset values",
    "processing.hi_cut_hz": "hi-cut", "processing.tilt_db": "tilt",
    "processing.balance_db": "balance", "processing.invert": "polarity invert",
    "dca": "DCA", "mute_group": "mute group", "mono": "mono",
    "source.stereo": "stereo", "source.phantom": "phantom",
}


def _unit(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    return " dB" if leaf.endswith("_db") else " Hz" if leaf.endswith("_hz") else ""


def _field_label(path: str) -> str:
    m = re.match(r"^bus_sends\[(?P<bus>[^\]]+)\](?:\.(?P<leaf>.+))?$", path)
    if m:
        leaf = {"level_db": "level", "mode": "mode", None: ""}.get(m["leaf"], m["leaf"])
        return f"send to {m['bus']}" + (f" {leaf}" if leaf else "")
    m = re.match(r"^main_routes\[(?P<i>[^\]]+)\](?:\.(?P<leaf>.+))?$", path)
    if m:
        leaf = (m["leaf"] or "").replace("_db", "")
        return f"route to Main {m['i']}" + (f" {leaf}" if leaf else "")
    if path in _FIELD_WORDS:
        return _FIELD_WORDS[path]
    return path.replace("_db", "").replace("_hz", "").replace("_", " ")


def _fmt(value) -> str:
    if value is _MISSING:
        return "(none)"
    if value is None:
        return "(unset)"
    if isinstance(value, tuple):
        return ", ".join(value) or "(none)"
    if isinstance(value, bool):
        return "on" if value else "off"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


@dataclass(frozen=True)
class ValueChange:
    path: str
    old: object
    new: object

    def text(self) -> str:
        label = _field_label(self.path)
        if isinstance(self.old, tuple) or isinstance(self.new, tuple):
            was = set(self.old) if isinstance(self.old, tuple) else set()
            now = set(self.new) if isinstance(self.new, tuple) else set()
            parts = [f"+{x}" for x in sorted(now - was)] + [f"-{x}" for x in sorted(was - now)]
            return f"{label} {' '.join(parts)}"
        if self.path.endswith("]") and (self.old is _MISSING or self.new is _MISSING):
            # A send or route added or removed, with what it was set to.
            gone = self.new is _MISSING
            detail = self.old if gone else self.new
            return f"{label} {'removed' if gone else 'added'}" + (
                f" ({detail})" if detail not in ("on", None) else "")
        unit = _unit(self.path)
        return f"{label} {_fmt(self.old)} -> {_fmt(self.new)}{unit if self.new not in (None, _MISSING) else ''}"

    def to_dict(self) -> dict:
        def plain(v):
            if v is _MISSING:
                return None
            return list(v) if isinstance(v, tuple) else v
        return {"path": self.path, "old": plain(self.old), "new": plain(self.new),
                "text": self.text()}


def _item_summary(values: dict, marker: str) -> str:
    leaves = [f"{_fmt(v)}{_unit(p)}" for p, v in values.items() if p.startswith(marker + ".")]
    return ", ".join(leaves) or "on"


def _value_changes(old: dict, new: dict) -> list[ValueChange]:
    """Every path whose value differs. A send (or route) added or removed
    is one change, carrying its settings, not one per leaf."""
    whole = {p for p in set(old) | set(new)
             if p.endswith("]") and (p in old) != (p in new)}
    out = []
    for path in list(old) + [p for p in new if p not in old]:
        if any(path.startswith(w + ".") for w in whole):
            continue
        a, b = old.get(path, _MISSING), new.get(path, _MISSING)
        if path in whole:
            a = _item_summary(old, path) if a is not _MISSING else a
            b = _item_summary(new, path) if b is not _MISSING else b
        if a != b:
            out.append(ValueChange(path, a, b))
    return out


# --------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------

@dataclass
class StripChange:
    collection: str
    kind: str                 # ADDED / REMOVED / CHANGED / MOVED
    label: str                # as the strip is now (as it was, when removed)
    severity: str
    reason: str
    moved_from: str | None = None
    values: list[ValueChange] = field(default_factory=list)
    # The slot it is in now, ("ch", 14), for a page that marks table rows.
    slot: tuple | None = None

    def summary(self, limit: int = 2) -> str:
        if self.kind in (ADDED, REMOVED):
            return self.kind
        parts = []
        if self.moved_from:
            parts.append(f"moved from {self.moved_from}")
        shown = self.values if limit is None else self.values[:limit]
        parts += [v.text() for v in shown]
        more = len(self.values) - len(shown)
        if more:
            parts.append(f"and {more} more value{'s' if more > 1 else ''}")
        return "; ".join(parts)

    def headline(self) -> str:
        """What happened to the strip, without its values."""
        if self.kind in (ADDED, REMOVED):
            return self.kind
        parts = [f"moved from {self.moved_from}"] if self.moved_from else []
        if self.values:
            n = len(self.values)
            parts.append(f"{n} value{'s' if n != 1 else ''} changed")
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return {"collection": self.collection, "kind": self.kind, "label": self.label,
                "severity": self.severity, "reason": self.reason,
                "moved_from": self.moved_from,
                "slot": list(self.slot) if self.slot else None,
                "summary": self.summary(), "values": [v.to_dict() for v in self.values]}


#: Said at INFO under every list of changes: the grading is a judgement
#: made by reading words, and the engineer should know what it rests on.
GRADING_NOTE = ("graded by what each strip is made from: a change is asked for when an "
                "input-list row it is made from changed, or a conventions line naming it, its "
                "category, or a bus, DCA or mute group it is on -- read from the words, so a "
                "line that calls a strip something else is not seen")

_ORDER = {WARNING: 0, INFO: 1}


def _wrapped(severity: str, text: str, *, indent: int = 11, width: int = 100) -> list[str]:
    first = f"  {severity:<8} " if severity else " " * indent
    return textwrap.wrap(text, width=width, initial_indent=first,
                         subsequent_indent=" " * indent, break_long_words=False,
                         break_on_hyphens=False) or [first.rstrip()]


def _display_order(s: "StripChange") -> tuple:
    slot = s.slot or (None, None)
    return (_ORDER[s.severity], _COLLECTIONS.index(s.collection), str(slot[0]),
            slot[1] if isinstance(slot[1], int) else 0, s.label)


@dataclass
class PlanChanges:
    strips: list[StripChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # INFO: how this was graded

    def counts(self) -> dict:
        c = Counter(s.kind for s in self.strips)
        return {ADDED: c[ADDED], REMOVED: c[REMOVED], CHANGED: c[CHANGED], MOVED: c[MOVED],
                "unasked": sum(1 for s in self.strips if s.severity == WARNING)}

    def to_dict(self, against: str = "") -> dict:
        return {"against": against, "counts": self.counts(),
                "notes": list(self.notes) + ([GRADING_NOTE] if self.strips else []),
                "strips": [s.to_dict() for s in self.strips]}

    def render(self, *, all_values: bool = False, against: str = "plan.previous.json") -> list[str]:
        """The CLI's "Changed since the last build" section, one line each."""
        if not self.strips:
            # The notes still print: how this was graded (a fallback, a
            # changed console model) matters even when nothing changed.
            return ([f"Changed since the last build: nothing -- every strip matches {against}."]
                    + [line for note in self.notes for line in _wrapped(INFO, note)])
        c = self.counts()
        parts = [f"{c[k]} {k}" for k in (ADDED, REMOVED, CHANGED, MOVED) if c[k]]
        n = len(self.strips)
        head = (f"Changed since the last build -- {n} strip{'s' if n != 1 else ''} "
                f"against {against}: {', '.join(parts)}")
        if c["unasked"]:
            head += f"; {c['unasked']} not asked for"
        out = [head]
        for s in sorted(self.strips, key=_display_order):
            what = s.headline() if all_values else s.summary(2)
            line = f"{s.label}: {what}"
            if s.severity == WARNING or all_values:
                line += f" -- {s.reason}"
            out += _wrapped(s.severity, line)
            if all_values:
                for v in s.values:
                    out += _wrapped("", v.text(), indent=13)
        for note in self.notes + [GRADING_NOTE]:
            out += _wrapped(INFO, note)
        if not all_values and any(len(s.values) > 2 for s in self.strips):
            out.append(f"  {'':8} (`--all-changes` lists every changed value)")
        return out


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------

def _stem(token: str) -> str:
    return token[:-1] if token.isalpha() and len(token) > 3 and token.endswith("s") else token


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", str(text).casefold())]


def _contains(line: list[str], term: list[str]) -> bool:
    n = len(term)
    return bool(n) and any(line[i:i + n] == term for i in range(len(line) - n + 1))


_LABEL_WORDS = {"ch": ("ch", "channel"), "aux": ("aux",), "bus": ("bus", "b"),
                "dca": ("dca",), "mgrp": ("mgrp", "mute group"),
                "main": ("main", "m"), "matrix": ("mtx", "matrix", "mx")}


def _terms(strip: _Strip, rows: dict, feeding: list[str]) -> list[list[str]]:
    terms = [strip.name, strip.identity.split("#")[0]] + list(feeding)
    terms += [(rows.get(k) or {}).get("category") or "" for k in feeding]
    kind, number = strip.slot
    if number is not None:
        for word in _LABEL_WORDS.get(kind, (str(kind),)):
            terms.append(f"{word} {number}")
            terms.append(f"{word}{number}")
    return [t for t in (_tokens(x) for x in terms if x) if t]


@dataclass
class _Pair:
    old: _Strip | None
    new: _Strip | None

    @property
    def any(self) -> _Strip:
        return self.new or self.old


def _match(old: list[_Strip], new: list[_Strip]) -> list[_Pair]:
    pairs: list[_Pair] = []
    left_new = list(new)
    by_identity = {s.identity: s for s in left_new}
    left_old = []
    for s in old:
        hit = by_identity.pop(s.identity, None)
        if hit is not None:
            pairs.append(_Pair(s, hit))
            left_new.remove(hit)
        else:
            left_old.append(s)
    by_slot = {s.slot: s for s in left_new}
    gone = []
    for s in left_old:
        hit = by_slot.pop(s.slot, None)
        if hit is not None:
            pairs.append(_Pair(s, hit))
            left_new.remove(hit)
        else:
            gone.append(s)
    pairs += [_Pair(s, None) for s in gone]
    pairs += [_Pair(None, s) for s in left_new]
    return pairs


def _feeding(strip: _Strip | None, channel_map: dict) -> list[str]:
    if strip is None or strip.collection != "channels":
        return []
    found = channel_map.get(_slot_key(*strip.slot))
    if found is not None:
        return list(found)
    return [strip.identity.split("#")[0]]


def _preset_files_changed(values: list[ValueChange]) -> bool:
    return any(v.path.endswith("preset_values") for v in values)


def compare(previous: dict, current: dict) -> PlanChanges:
    """Every strip that differs between `previous` (the plan a rebuild
    replaced) and `current`, graded (module docstring)."""
    previous = previous if isinstance(previous, dict) else {}
    current = current if isinstance(current, dict) else {}
    old_meta = previous.get("meta") if isinstance(previous.get("meta"), dict) else {}
    new_meta = current.get("meta") if isinstance(current.get("meta"), dict) else {}
    old_basis = old_meta.get(BASIS_KEY) if isinstance(old_meta.get(BASIS_KEY), dict) else None
    new_basis = new_meta.get(BASIS_KEY) if isinstance(new_meta.get(BASIS_KEY), dict) else None
    result = PlanChanges()

    old_strips, new_strips = _strips(previous), _strips(current)
    pairs = {c: _match(old_strips[c], new_strips[c]) for c in _COLLECTIONS}

    # ---- what changed among the inputs -------------------------------------
    rows_global = conv_global = False
    old_rows = (old_basis or {}).get("rows") or {}
    new_rows = (new_basis or {}).get("rows") or {}
    old_map = (old_basis or {}).get("channels") or {}
    new_map = (new_basis or {}).get("channels") or {}
    # (line, the tokens of the same layer on the OTHER side): a line
    # whose words run on unchanged over there was only re-wrapped.
    changed_lines: list[tuple[str, list[str]]] = []
    if old_basis is None or new_basis is None:
        rows_global, conv_global = _hash_fallback(old_meta, new_meta, result.notes)
    else:
        old_conv = old_basis.get("conventions") or {}
        new_conv = new_basis.get("conventions") or {}
        for role in list(old_conv) + [r for r in new_conv if r not in old_conv]:
            olds, news = old_conv.get(role) or [], new_conv.get(role) or []
            a, b = Counter(olds), Counter(news)
            old_tokens = _tokens(" ".join(olds))
            new_tokens = _tokens(" ".join(news))
            changed_lines += [(line, new_tokens) for line in (a - b).elements()]
            changed_lines += [(line, old_tokens) for line in (b - a).elements()]
    if old_meta.get("console_model") != new_meta.get("console_model") \
            and old_meta.get("console_model") and new_meta.get("console_model"):
        result.notes.append(
            f"the console model changed ({old_meta['console_model']} -> "
            f"{new_meta['console_model']}), so every change is taken as asked for")
        rows_global = conv_global = True
    if old_meta.get("model") and new_meta.get("model") \
            and old_meta.get("model") != new_meta.get("model"):
        result.notes.append(f"built on a different model ({old_meta['model']} -> "
                            f"{new_meta['model']}); that does not make a change asked for")
    have_rows = old_basis is not None and new_basis is not None
    rows_structure = rows_global or (have_rows and list(old_rows) != list(new_rows))

    # ---- which strips each changed conventions line is about ---------------
    all_pairs = [p for c in _COLLECTIONS for p in pairs[c]]
    terms = {}
    for p in all_pairs:
        t = []
        if p.old is not None:
            t += _terms(p.old, old_rows, _feeding(p.old, old_map))
        if p.new is not None:
            t += _terms(p.new, new_rows, _feeding(p.new, new_map))
        terms[id(p)] = t
    touched: set[int] = set()
    general: list[str] = []
    layout_only = 0
    for line, other_side in changed_lines:
        tokens = _tokens(line)
        hit = {id(p) for p in all_pairs if any(_contains(tokens, t) for t in terms[id(p)])}
        if hit:
            touched |= hit
        elif line.lstrip().startswith("#") or _contains(other_side, tokens) or not tokens:
            # A Markdown heading, or a line whose words are all still
            # there in the same order (re-wrapped, re-indented): it asks
            # for nothing, so it does not make every change asked for.
            layout_only += 1
        else:
            general.append(line)
    if layout_only:
        result.notes.append(
            f"{layout_only} changed conventions line(s) only re-wrap text or are headings "
            "naming no strip; they are not counted as asking for anything")
    if general and not conv_global:
        conv_global = True
        quoted = general[0] if len(general[0]) <= 70 else general[0][:67] + "..."
        more = f" (and {len(general) - 1} more)" if len(general) > 1 else ""
        result.notes.append(
            f"a changed conventions line names no particular strip -- \"{quoted}\"{more} -- "
            "so every change is taken as asked for")
    # A bus, DCA, mute group or Main a changed line names reaches every
    # strip that belongs to it or sends to it: a send lives on the channel.
    named = {(p.any.collection if p.any.collection != "outputs" else p.any.slot[0],
              s.name if p.any.collection != "outputs" else s.slot[1])
             for p in all_pairs if id(p) in touched for s in (p.old, p.new) if s}
    for p in all_pairs:
        if any(s is not None and s.refs & named for s in (p.old, p.new)):
            touched.add(id(p))

    # ---- rows each strip is made from ---------------------------------------
    def rows_changed(keys) -> bool:
        return any((old_rows.get(k) or {}).get("sha") != (new_rows.get(k) or {}).get("sha")
                   for k in keys)

    channel_keys = {}
    for p in pairs["channels"]:
        channel_keys[id(p)] = set(_feeding(p.old, old_map)) | set(_feeding(p.new, new_map))
    member_keys: dict = {}
    for p in pairs["channels"]:
        for s in (p.old, p.new):
            if s is None:
                continue
            for ref in s.refs:
                member_keys.setdefault(ref, set()).update(channel_keys[id(p)])

    def strip_rows_changed(p: _Pair) -> bool:
        if rows_global or not have_rows:
            return rows_global
        if p.any.collection == "channels":
            return rows_changed(channel_keys[id(p)])
        keys = set()
        for s in (p.old, p.new):
            if s is None:
                continue
            ref = ((s.collection, s.name) if s.collection != "outputs"
                   else (s.slot[0], s.slot[1]))
            keys |= member_keys.get(ref, set())
        return rows_changed(keys)

    # ---- grade --------------------------------------------------------------
    for collection in _COLLECTIONS:
        bank_churn = {p.any.slot[0] for p in pairs[collection]
                      if p.old is None or p.new is None}
        for p in pairs[collection]:
            if p.old is None or p.new is None:
                kind, values, moved_from = (ADDED if p.old is None else REMOVED), [], None
            else:
                values = _value_changes(p.old.values, p.new.values)
                moved_from = _slot_label(p.old) if p.old.slot != p.new.slot else None
                if not values and moved_from is None:
                    continue
                kind = CHANGED if values else MOVED
            reasons = []
            if strip_rows_changed(p):
                reasons.append("a row it is made from changed" if not rows_global
                               else "the input list changed")
            if conv_global or id(p) in touched:
                reasons.append("a conventions line about it changed" if not conv_global
                               else "the conventions changed")
            if _preset_files_changed(values):
                reasons.append("its preset file changed")
            if not reasons and kind == MOVED:
                if rows_structure:
                    reasons.append("input-list rows were added, removed or reordered")
                elif p.any.slot[0] in bank_churn:
                    reasons.append("a strip was added or removed beside it")
            severity = INFO if reasons else WARNING
            reason = "; ".join(reasons) if reasons else (
                "nothing in the input list or the conventions about it changed")
            shown = p.new or p.old
            result.strips.append(StripChange(
                collection, kind, shown.label, severity, reason, moved_from, values,
                tuple(shown.slot) if p.new is not None else None))
    return result


def _hash_fallback(old_meta: dict, new_meta: dict, notes: list[str]) -> tuple[bool, bool]:
    """No per-row record on one side: compare the files' recorded sha256s.
    Returns `(rows changed, conventions changed)`, each True when it
    cannot be told -- every change is then taken as asked for."""
    def sha(meta, *keys):
        v = meta
        for k in keys:
            v = v.get(k) if isinstance(v, dict) else None
        return v

    old_list, new_list = sha(old_meta, "input_list", "sha256"), sha(new_meta, "input_list", "sha256")
    rows_changed = not old_list or old_list != new_list

    def layers(meta):
        stack = meta.get("conventions_stack")
        if not isinstance(stack, list):
            return None
        return [(x.get("role"), x.get("sha256")) for x in stack if isinstance(x, dict)]

    old_layers, new_layers = layers(old_meta), layers(new_meta)
    conv_changed = (not old_layers or old_layers != new_layers
                    or any(not s for _r, s in old_layers))
    if rows_changed or conv_changed:
        which = " and ".join(w for w, c in (("the input list", rows_changed),
                                            ("the conventions", conv_changed)) if c)
        notes.append(f"the replaced plan has no record of what each strip was made from, and "
                     f"{which} changed (or cannot be told), so every change is taken as asked "
                     "for; from the next rebuild on, changes are graded strip by strip")
    else:
        notes.append("the replaced plan has no record of what each strip was made from; its "
                     "input list and conventions are unchanged, so every change is one "
                     "nobody asked for")
    return rows_changed, conv_changed
