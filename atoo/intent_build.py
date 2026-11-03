"""`atoo build --intent`: the model writes an INTENT for the whole show, code compiles it.

The build's other contract (`generate.generate_plan`) asks for the show in the plan's
compact reply format. This is the one `atoo patch --intent` uses (`atoo/intent.py`),
over an empty desk: the input list is sent whole, the model writes one `add_channel` per
row and the groups, buses and outputs the conventions ask for, and the same compile
(`atoo/intent_compile.py`) and merge (`patch.merge_change`) that `patch` runs make the plan:
the strips, the sockets for rows that name none, the DCA / mute-group / bus numbers, the
stereo pairs, every range. Both contracts stay until this one is at parity.

Code writes the channels (`with_rows`): one per input-list row, in the list's order. The model
writes what the list cannot say: a stereo pair, a strip with another name or a preset, the
groups, buses and outputs (with their members by category or by name), the strip order by
category, and the Category table as a small JSON list in the reply itself, so the long rewrite of
the conventions (`atoo resolve`) is not needed. A row is left out only when the model quotes the
conventions, the instructions or the row's own notes saying so.

What it does NOT do: the fix-up round (the intent has its own repair round). The critic and
watch-condition steps are unchanged because they run on the plan this returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from atoo import generate, input_list, intent, patch
from atoo.intent_compile import IntentRefused

#: The request a build puts to the intent compile.
REQUEST = "Build the show from the input list, following the conventions."


def with_rows(intent: dict, rows) -> dict:
    """The model's intent with the channels of the input list written by code.

    One `add_channel` per row, in the list's order, naming only the row: the compile fills in
    what the list says (the source type, model, phantom power, category, preset and the socket
    it states). The model writes a channel only for what the list does not say: a stereo pair
    (`rows` names both), a strip with another name, a bank, a preset. Its op takes the place of
    the row's own, so the list's order stands; a second row it names is not added twice. Ops for
    strips that are not rows, and every other op, follow."""
    by_row = {}                                  # row name -> the model's op that is built from it
    consumed = set()
    for op in intent["ops"]:
        if op["op"] != "add_channel":
            continue
        named = [n for n in (op.get("rows") or [])[:2]]
        if not named:
            named = [op["name"]]
        for n in named:
            by_row.setdefault(n.casefold(), op)
        consumed.update(n.casefold() for n in named[1:])
    row_names = {r.name.casefold() for r in rows}
    ops, used = [], set()
    for row in rows:
        key = row.name.casefold()
        if key in consumed:
            continue
        model_op = by_row.get(key)
        if model_op is not None and key in row_names:
            if id(model_op) not in used:
                used.add(id(model_op))
                ops.append(model_op)
            continue
        ops.append({"op": "add_channel", "name": row.name})
    rest = [op for op in intent["ops"] if id(op) not in used and not (
        op["op"] == "add_channel" and (
            (op.get("rows") or [op["name"]])[0].casefold() in row_names))]
    return {**intent, "ops": ops + rest}


# -- a row the model names nearly as the list does ---------------------------------------------

#: Words engineers shorten, folded to one spelling each side of the comparison.
_SAME_WORD = {"oh": "overhead", "ovhd": "overhead", "vox": "vocal", "voc": "vocal", "gtr": "guitar",
              "gtrs": "guitar", "gt": "guitar", "kbd": "key", "kbds": "key"}
_SIDES = {"l": "L", "left": "L", "r": "R", "right": "R"}


def row_key(name: str) -> tuple:
    """`name` folded for a near match: case, punctuation and spacing gone, digits apart from
    letters ("Tom1" is "tom 1"), a plural's s dropped, the shortenings in `_SAME_WORD` spelled out,
    and the stereo side (L/R, Left/Right) kept apart, so "Overheads L" is ('overhead',), 'L'."""
    words = re.findall(r"[a-z]+|\d+", str(name or "").casefold())
    side = None
    # "stage left" is where the player stands, not a side of a signal pair: two guitars, not one
    if words and words[-1] in _SIDES and not (len(words) > 1 and words[-2] == "stage"):
        side = _SIDES[words.pop()]
    out = []
    for w in words:
        w = _SAME_WORD.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = _SAME_WORD.get(w[:-1], w[:-1])
        out.append(w)
    return tuple(out), side


def resolve_row_names(intent_: dict, rows) -> tuple[dict, list[str]]:
    """The intent with every channel name that is not a row of the list, but matches exactly one
    row by `row_key`, written as that row's name; and an INFO for each. An L/R side matches only
    a row of the same side, never a mono row. An `add_channel` named by what an L/R pair of rows
    shares ("Keys 1" for "Keys 1 L" and "Keys 1 R"), with no rows of its own, is that pair: one
    stereo channel (a judgement the name makes plain, said at INFO). A name that matches none, or several, is left for
    the compile, which refuses it naming it."""
    exact = {r.name.casefold(): r.name for r in rows}
    by_key: dict = {}
    for r in rows:
        by_key.setdefault(row_key(r.name), []).append(r.name)
    infos: list[str] = []

    def pair_of(name):
        """(left, right): the one L/R pair of rows whose shared name `name` is ("Keys 1" for
        "Keys 1 L" and "Keys 1 R"), when no row is called just that; else None."""
        if not isinstance(name, str) or name.casefold() in exact:
            return None
        words, side = row_key(name)
        if side is not None or by_key.get((words, None)):
            return None
        left, right = by_key.get((words, "L")) or [], by_key.get((words, "R")) or []
        return (left[0], right[0]) if len(left) == 1 and len(right) == 1 else None

    def fix(name):
        if not isinstance(name, str) or name.casefold() in exact:
            return name
        found = by_key.get(row_key(name)) or []
        if len(found) != 1:
            return name
        infos.append(f"the reply wrote {name!r}, which is the input list's {found[0]!r}: read as that row")
        return found[0]

    ops = []
    for op in intent_.get("ops") or []:
        op = dict(op)
        if op.get("op") == "add_channel":
            if op.get("rows"):
                op["rows"] = [fix(n) for n in op["rows"]]
            elif op.get("name") and pair_of(op["name"]):
                left, right = pair_of(op["name"])
                op["rows"] = [left, right]
                if op.get("stereo") is None:
                    op["stereo"] = True
                infos.append(f"the reply wrote {op['name']!r}, the name the input list's {left!r} and "
                             f"{right!r} share: built as that pair, one stereo channel")
            elif op.get("name"):
                op["name"] = fix(op["name"])
        elif op.get("op") in ("drop", "set", "rename") and op.get("object") == "channel" or op.get("op") == "move_channel":
            op["name"] = fix(op.get("name"))
        if op.get("op") == "order" and op.get("channels"):
            op["channels"] = [fix(n) for n in op["channels"]]
        if isinstance(op.get("members"), dict) and op["members"].get("channels"):
            op["members"] = {**op["members"], "channels": [fix(n) for n in op["members"]["channels"]]}
        ops.append(op)
    return {**intent_, "ops": ops}, infos


# -- L/R pairs, when the conventions say plainly what they are ---------------------------------

#: A sentence that makes an L/R (Left/Right) pair of inputs one stereo channel, in so many words:
#: "Any other L/R pair of inputs becomes one stereo channel", "Two inputs that are an L/R pair
#: become one stereo channel", "... marked as stereo pair (L/R, Left/Right), patch as one stereo
#: channel". "Stereo-paired inputs become one stereo channel" does not say WHICH inputs, so it is
#: not one: the reply's choice stands there.
_PAIR_RULE_RE = re.compile(r"\b(?:L/R|left/right)\b[^.\n]*?\b(?:becomes?|is|are|patch(?:ed)?\s+as)\s+"
                           r"(?:one|a)\s+stereo\s+channel", re.IGNORECASE)
#: A sentence that keeps some pair apart: "Overhead L and overhead R stay two mono channels",
#: "except OH L and OH R, which stay two mono channels", "do NOT patch as a stereo pair".
_PAIR_EXCEPT_RE = re.compile(r"\bmono\s+channels?\b|\bnot\b[^.\n]*\bstereo\s+pair", re.IGNORECASE)
_SIDE_RE = re.compile(r"[\s_-]*[(\[]?\b(?:l|r|left|right)\b[)\]]?\s*$", re.IGNORECASE)
_NEGATED_RE = re.compile(r"\b(?:not|never|don'?t|no)\b", re.IGNORECASE)


def _words(text: str) -> set[str]:
    """`text`'s words folded as `row_key` folds a name's."""
    out = set()
    for w in re.findall(r"[a-z]+|\d+", str(text or "").casefold()):
        w = _SAME_WORD.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = _SAME_WORD.get(w[:-1], w[:-1])
        out.add(w)
    return out


def stated_pairs(conventions: str, rows) -> tuple[list[tuple[str, str, str]], str | None, list[str]]:
    """`(pairs, rule, kept_apart)`: the L/R pairs of `rows` the conventions make one stereo channel
    in so many words (`_PAIR_RULE_RE`), as (left row, right row, the channel's name: the rows'
    shared name), the sentence that says so, and the pairs a sentence keeps apart
    (`_PAIR_EXCEPT_RE`: every word of the pair's shared name is in it), the same triples. No rule:
    no pairs."""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n", conventions or "") if x.strip()]
    rule = next((x for x in sentences if _PAIR_RULE_RE.search(x) and not _NEGATED_RE.search(
        _PAIR_RULE_RE.search(x).group(0))), None)
    by_key: dict = {}
    for r in rows:
        by_key.setdefault(row_key(r.name), []).append(r.name)
    pairs, kept = [], []
    if rule is None:
        return pairs, None, kept
    apart = [_words(x) for x in sentences if _PAIR_EXCEPT_RE.search(x)]
    for (words, side), names in by_key.items():
        if side != "L" or len(names) != 1:
            continue
        right = by_key.get((words, "R")) or []
        if len(right) != 1:
            continue
        stem = _SIDE_RE.sub("", names[0]).strip() or names[0]
        if any(set(words) <= w for w in apart):
            kept.append((names[0], right[0], stem))
            continue
        pairs.append((names[0], right[0], stem))
    return pairs, rule, kept


def _split_joined(ops: list, left: str, right: str) -> tuple[list, list[str]]:
    """`ops` with every `add_channel` that joins rows `left` and `right` split into two mono
    channels, one per row, each keeping what the op said of the channel; and the names of the ops
    split (a reference to one of them names both rows: `_expand_refs`)."""
    both = {left.casefold(), right.casefold()}
    out, names = [], []
    for op in ops:
        if op.get("op") == "add_channel" and {str(n).casefold() for n in (op.get("rows") or [])} == both:
            rest = {f: v for f, v in op.items() if f not in ("name", "rows", "stereo", "patch")}
            out += [{**rest, "name": left}, {**rest, "name": right}]
            names.append(str(op.get("name")))
        else:
            out.append(op)
    return out, names


def _expand_refs(ops: list, split: dict[str, list[str]], renamed: dict[str, str] | None = None) -> list:
    """`ops` with each member or order entry naming a split channel naming both its rows, and one
    naming a renamed row naming its new name."""
    renamed = renamed or {}

    def names(lst):
        out = []
        for n in lst or []:
            for m in split.get(str(n).casefold(), [renamed.get(str(n).casefold(), n)]):
                if m not in out:
                    out.append(m)
        return out

    for op in ops:
        if isinstance(op.get("members"), dict) and op["members"].get("channels"):
            op["members"] = {**op["members"], "channels": names(op["members"]["channels"])}
        if op.get("op") == "order" and op.get("channels"):
            op["channels"] = names(op["channels"])
    return ops


def with_stated_pairs(intent_: dict, rows, conventions: str) -> tuple[dict, list[str]]:
    """The intent with every L/R pair the conventions make one stereo channel (`stated_pairs`)
    written as ONE `add_channel` with both `rows` and `stereo` true, whatever the reply wrote: the
    engineer said so, and an explicit instruction is carried out. What the reply wrote for either
    row (a preset, a name) is kept on the pair; a reference to either row (a member, the order)
    names the pair. Each said at INFO. Where the conventions say nothing so plain, the reply's
    choice stands, and that is said once when the list has L/R pairs. A pair whose list sockets
    the desk cannot join (LCL 4 and 5) is one stereo channel too: the compile patches it through
    two USER PATCH slots (`user_patch`). A pair a sentence keeps apart ("OH L and OH
    R stay two mono channels") is two mono channels whatever the reply wrote: a reply that joins
    them is split, at INFO, and a reference to the joined name names both."""
    pairs, rule, kept = stated_pairs(conventions, rows)
    infos: list[str] = []
    if rule is None:
        lr = {row_key(r.name)[0] for r in rows if row_key(r.name)[1] == "L"} & \
             {row_key(r.name)[0] for r in rows if row_key(r.name)[1] == "R"}
        if lr and re.search(r"stereo", conventions or "", re.IGNORECASE):
            infos.append("the conventions do not say in so many words that an L/R pair of inputs is one "
                         "stereo channel, so how the list's L/R rows are paired is the reply's choice")
        return intent_, infos
    ops = [dict(op) for op in intent_.get("ops") or []]
    renamed: dict[str, str] = {}
    for left, right, stem in pairs:
        both = {left.casefold(), right.casefold()}
        own = [k for k, op in enumerate(ops) if op.get("op") == "add_channel"
               and {str(n).casefold() for n in (op.get("rows") or [])} == both]
        if own:
            if ops[own[0]].get("stereo") is not True:
                ops[own[0]]["stereo"] = True
                infos.append(f"{ops[own[0]].get('name')!r} ({left} and {right}) is one stereo channel, as "
                             f"the conventions say: {rule[:120]!r}")
            continue
        single = [k for k, op in enumerate(ops) if op.get("op") == "add_channel" and (
            {str(n).casefold() for n in (op.get("rows") or [op.get("name")])} & both)]
        pair = {"op": "add_channel", "name": stem, "rows": [left, right], "stereo": True}
        for k in single:            # what the reply said of either row stays, on the pair
            pair.update({f: v for f, v in ops[k].items()
                         if f not in ("op", "name", "rows", "stereo", "patch") and v is not None and f not in pair})
        ops = [op for k, op in enumerate(ops) if k not in single]
        ops.append(pair)
        renamed.update({left.casefold(): stem, right.casefold(): stem})
        infos.append(f"{left!r} and {right!r} are one stereo channel, {stem!r}, as the conventions say: "
                     f"{rule[:120]!r}" + (" (the reply wrote them apart)" if single else ""))
    split: dict[str, list[str]] = {}
    for left, right, stem in kept:
        ops, joined = _split_joined(ops, left, right)
        for joined_name in joined:
            split[joined_name.casefold()] = [left, right]
            infos.append(f"{joined_name!r} ({left} and {right}) is two mono channels, as the conventions "
                         "say; the reply joined them")
    if kept:
        infos.append(f"kept apart as the conventions say: {', '.join(repr(stem) for _, _, stem in kept)}")
    return {**intent_, "ops": _expand_refs(ops, split, renamed)}, infos


# -- what the conventions ask for, read from their sections ---------------------------------

#: A conventions heading's words -> the kind of object its `- Name: ...` items ask for.
_SECTION_KINDS = (("mute", "mute group"), ("dca", "DCA"), ("bus", "bus"), ("output", "output"))
_ITEM_RE = re.compile(r"^\s*[-*]\s*\**([^:*\n]{1,40}?)\**\s*:\s*(.*)$")
_NAMED_RE = re.compile(r"\bnamed\s+[\"“']([^\"”']{1,30})[\"”']", re.IGNORECASE)


@dataclass(frozen=True)
class AskedFor:
    """One object a conventions section asks for: its kind, the item's name, any other name the
    item gives it ('named "Drum wedge"'), and the item's text."""
    kind: str
    name: str
    aliases: tuple
    text: str


#: "Setup TALKBACK on Aux 8, source LCL 22", "Set up a MUSIC playback on Aux 1, source LCL 23-24":
#: a strip the conventions ask for BY NAME on an Aux strip, with where it is plugged in.
_ASKED_STRIP_RE = re.compile(r"(?i:\b(?:set\s*up|add|create)\s+(?:an?\s+|the\s+)?)"
                             r"(?P<name>[A-Z][\w/&-]*(?:\s+[A-Z][\w/&-]*)*)"
                             r"(?i:[^.\n]*?\bon\s+aux(?:iliary)?\s*(?:channel\s*)?\d+)")


def asked_strips(conventions: str) -> list[AskedFor]:
    """The strips the conventions ask for by name on an Aux strip, with a stated socket (a line
    with no socket is not one: nobody could plug it in). Kind "aux strip", for `left_out`."""
    from atoo import instructed_channels as ic

    out = []
    for line in (conventions or "").splitlines():
        m = _ASKED_STRIP_RE.search(line)
        if m and ic.stated_sockets(line):
            text = line.strip().lstrip("-*# ").strip()
            out.append(AskedFor("aux strip", m.group("name").strip(), (), text))
    return out


_AUX_NUMBER_RE = re.compile(r"\bon\s+aux(?:iliary)?\s*(?:channel\s*)?(\d+)", re.IGNORECASE)
_SOURCE_RE = re.compile(r"\bsource\s+(?:is\s+)?(?P<group>[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z])?)\s*(?P<first>\d+)"
                        r"(?:\s*(?:-|–|\+|and|to)\s*(?P<second>\d+))?", re.IGNORECASE)
_PRESET_RE = re.compile(r"\bpreset\s+[\"“']([^\"”']{1,40})[\"”']", re.IGNORECASE)


def with_asked_strips(intent_: dict, conventions: str, rows) -> tuple[dict, list[str]]:
    """The intent with every strip the conventions ask for by name on an Aux strip, with its
    source ("Setup TALKBACK on Aux 8, source LCL 22"; `asked_strips`), that the reply did not make:
    an `add_channel` on that Aux strip and socket (a range, "LCL 23-24", is a stereo pair), with the
    preset the line quotes, filled by code at INFO, as Main's stated sockets are (`with_main`).
    The engineer said where it goes and what it is, so building it is carrying that out, not
    inventing it; a line whose Aux number or source cannot be read is left to the reply and to the
    completeness check. A strip the reply made, under that name, stands as the reply wrote it."""
    made = {str(op.get("name") or "").casefold() for op in intent_.get("ops") or [] if op.get("op") == "add_channel"}
    made |= {r.name.casefold() for r in rows}
    ops, infos = list(intent_.get("ops") or []), []
    for strip in asked_strips(conventions):
        if strip.name.casefold() in made:
            continue
        aux, source = _AUX_NUMBER_RE.search(strip.text), _SOURCE_RE.search(strip.text)
        spec = input_list.parse_socket_spec(f"{source.group('group')} {source.group('first')}") if source else None
        if aux is None or spec is None:
            continue
        first, second = int(source.group("first")), source.group("second")
        pair = second is not None and int(second) == first + 1
        op = {"op": "add_channel", "name": strip.name, "bank": "aux", "place": {"at": int(aux.group(1))},
              "patch": {"group": spec[0], "first": first, "count": 2 if pair else None}}
        if pair:
            op["stereo"] = True
        preset = _PRESET_RE.search(strip.text)
        if preset:
            op["preset"] = preset.group(1)
        ops.append(op)
        made.add(strip.name.casefold())
        where = f"{spec[0]} {first}" + (f"-{first + 1}" if pair else "")
        infos.append(f"{strip.name!r} on Aux {aux.group(1)}, source {where}, filled by code: the conventions "
                     f"say {strip.text[:100]!r} and the reply did not make it")
    if not infos:
        return intent_, []
    return {**intent_, "ops": ops}, infos


#: "Every tracks-category input goes on an Aux channel": the rows of a category, on Aux strips.
_AUX_CATEGORY_RE = re.compile(r"\bevery\s+(?P<cat>[\w-]+?)[-\s]category\s+(?:input|row|strip|channel)s?\s+"
                              r"(?:goes|go|is|are|belongs?)\s+on\s+(?:an?\s+)?aux", re.IGNORECASE)


def with_stated_aux(intent_: dict, rows, conventions: str) -> tuple[dict, list[str]]:
    """The intent with every input-list row of a category the conventions put on Aux strips in so
    many words ("Every tracks-category input goes on an Aux channel") written with `bank` `aux`,
    whatever the reply wrote, and an INFO for each category: the engineer said so."""
    cats = {m.group("cat").casefold() for m in _AUX_CATEGORY_RE.finditer(conventions or "")}
    if not cats:
        return intent_, []
    names = [r.name for r in rows if str(r.category or "").strip().casefold() in cats]
    if not names:
        return intent_, []
    want = {n.casefold() for n in names}
    ops, moved, covered = [], [], set()
    for op in intent_.get("ops") or []:
        if op.get("op") == "add_channel":
            mine = {str(n).casefold() for n in (op.get("rows") or [op.get("name")])} & want
            if mine:
                covered |= mine
                if op.get("bank") != "aux":
                    op = {**op, "bank": "aux"}
                    moved.append(op.get("name"))
        ops.append(op)
    for n in names:
        if n.casefold() not in covered:
            ops.append({"op": "add_channel", "name": n, "bank": "aux"})
            moved.append(n)
    if not moved:
        return intent_, []
    return {**intent_, "ops": ops}, [
        f"on Aux strips, as the conventions put every {', '.join(sorted(cats))}-category input there: "
        + ", ".join(repr(n) for n in moved)]


_HPF_WORD_RE = re.compile(r"high[- ]?pass|\bhpf\b|low[- ]?cut", re.IGNORECASE)
#: A high-pass frequency: a number with its unit ("120 Hz", "1.2 kHz"), or right after a high-pass
#: word ("HPF 80", "high-pass at 100") or after "at" ("the kick at 40") on a high-pass line.
_HPF_HZ_RE = re.compile(
    r"(?P<n>\d+(?:\.\d+)?)\s*(?P<k>k)?hz\b"
    r"|(?:high[- ]?pass|\bhpf|low[- ]?cut)(?:\s+filter)?\s*(?:at|of|to|=|:)?\s*(?P<m>\d+(?:\.\d+)?)(?!\d|\.\d)(?!\s*k?hz)"
    r"|\bat\s+(?P<a>\d+(?:\.\d+)?)(?!\d|\.\d)(?!\s*k?hz)", re.IGNORECASE)
_HPF_SIDE_RE = re.compile(r"[\s_-]*\b(?:l|r|left|right)$", re.IGNORECASE)
_HPF_EXCEPT_RE = re.compile(r"\b(?:except|but|not|unless)\b", re.IGNORECASE)


def _hpf_frequencies(text: str) -> list[tuple[int, float]]:
    """(position, Hz) of each high-pass frequency in a line that names a high-pass."""
    found = []
    for m in _HPF_HZ_RE.finditer(text):
        if m.group("n"):
            found.append((m.start(), float(m.group("n")) * (1000 if m.group("k") else 1)))
        else:
            found.append((m.start(), float(m.group("m") or m.group("a"))))
    return found


def _hpf_named(text: str, names: dict[str, list[str]]) -> dict[str, float]:
    """The high-pass each row named in `text` is given: a name takes the first frequency after it,
    or the last before it when none follows ("Kick, snare and toms: HPF 100"; "HPF the kick at 40
    and the snare at 100"; "High-pass at 40 for the kick"). A name after the last frequency with
    "except", "but", "not" or "unless" between them takes nothing ("HPF 80, except the kick")."""
    if not _HPF_WORD_RE.search(text):
        return {}
    freqs = _hpf_frequencies(text)
    if not freqs:
        return {}
    spans: list[tuple[int, int, str]] = []
    for name in sorted(names, key=len, reverse=True):
        for m in re.finditer(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text, re.IGNORECASE):
            if not any(a <= m.start() < b for a, b, _ in spans):      # the longer name already holds it
                spans.append((m.start(), m.end(), name))
    out: dict[str, float] = {}
    for start, end, name in sorted(spans):
        after = [hz for at, hz in freqs if at >= end]
        if after:
            hz = after[0]
        else:
            at, hz = [f for f in freqs if f[0] < start][-1]
            if _HPF_EXCEPT_RE.search(text[at:start]):
                continue
        for row in names[name]:
            out[row] = hz
    return out


def with_stated_hpf(intent_: dict, rows, conventions: str) -> tuple[dict, list[str]]:
    """The intent with the high-pass the conventions, the instructions or a row's own notes state
    for that one channel ("Kick: HPF 40", "the snare at 100 Hz", a row's notes "HPF 150") written
    on its `add_channel`, where the reply left the channel's `hpf_hz` out, each said at INFO. A row
    is named by its name, or an L/R row by its pair's name ("Keys" for Keys L and Keys R). A line
    that names only a category is the Category table's, not this. What the reply wrote stands, and
    a row its Category table already gives the same value is left alone, with nothing said; the
    row's notes win over a line of the conventions, and a later line over an earlier one (the
    instructions follow the conventions). An aux strip has no high-pass, and a value past the
    desk's range is not written: each said at INFO. "HPF off" is not read: the intent has no way
    to say a channel has none over its category's."""
    from atoo import console_facts as facts
    names: dict[str, list[str]] = {}
    for r in rows:
        names.setdefault(r.name, []).append(r.name)
        stem = _HPF_SIDE_RE.sub("", r.name).strip()
        if stem and stem != r.name:
            names.setdefault(stem, []).append(r.name)
    stated: dict[str, tuple[float, str]] = {}
    for line in (conventions or "").splitlines():
        for row, hz in _hpf_named(line, names).items():
            stated[row.casefold()] = (hz, f"as the conventions state it: {line.strip()[:100]!r}")
    for r in rows:
        own = _hpf_named(str(r.notes or ""), {r.name: [r.name]}) or (
            {r.name: _hpf_frequencies(r.notes)[0][1]}
            if _HPF_WORD_RE.search(str(r.notes or "")) and len(_hpf_frequencies(str(r.notes or ""))) == 1 else {})
        if r.name in own:
            stated[r.name.casefold()] = (own[r.name], f"as its input-list notes state it: {r.notes.strip()[:100]!r}")
    if not stated:
        return intent_, []
    table_hpf: dict[str, float] = {}
    for entry in intent_.get("categories") or []:
        if isinstance(entry, dict) and entry.get("hpf_hz") is not None:
            for word in (entry.get("name"), *(entry.get("aliases") or [])):
                table_hpf.setdefault(str(word or "").strip().casefold(), entry["hpf_hz"])
    ops = [dict(op) for op in intent_.get("ops") or []]
    infos: list[str] = []
    # A high-pass stated for one side of a joined pair, or a different one for each side, is a
    # setting one stereo channel cannot carry: the pair is two mono channels, said so.
    by_name = {r.name.casefold(): r for r in rows}

    def side_hz(row_name):
        row = by_name.get(str(row_name).casefold())
        said = stated.get(str(row_name).casefold())
        return said[0] if said else table_hpf.get(str(getattr(row, "category", "") or "").strip().casefold())

    split: dict[str, list[str]] = {}
    for op in list(ops):
        pair = op.get("rows") or []
        if op.get("op") != "add_channel" or len(pair) != 2:
            continue
        left, right = pair
        if not ({str(left).casefold(), str(right).casefold()} & set(stated)) or side_hz(left) == side_hz(right):
            continue
        ops, joined = _split_joined(ops, left, right)
        for joined_name in joined:
            split[joined_name.casefold()] = [left, right]
            said = [n for n in (left, right) if str(n).casefold() in stated]
            whose = f"for {said[0]!r} only" if len(said) == 1 else "differently for each side"
            infos.append(f"{joined_name!r} ({left} and {right}) is two mono channels: a high-pass is stated "
                         f"{whose}, which one stereo channel cannot carry")
    ops = _expand_refs(ops, split)
    done: set[int] = set()
    lo, hi = facts.HPF_HZ_RANGE
    for r in rows:
        if r.name.casefold() not in stated:
            continue
        hz, why = stated[r.name.casefold()]
        if table_hpf.get(str(r.category or "").strip().casefold()) == hz:
            continue                     # the reply's Category table already gives it that value
        k = next((k for k, op in enumerate(ops) if op.get("op") == "add_channel" and r.name.casefold() in
                  {str(n).casefold() for n in (op.get("rows") or [op.get("name")])}), None)
        if k is not None and (k in done or ops[k].get("hpf_hz") is not None):
            continue                     # the reply wrote one, or this pair's other row already did
        label = ops[k].get("name") if k is not None else r.name
        if k is not None and ops[k].get("bank") == "aux":
            infos.append(f"{label!r} gets no high-pass of {hz:g} Hz, {why}: an aux strip has no high-pass")
            continue
        if not lo <= hz <= hi:
            infos.append(f"{label!r} gets no high-pass of {hz:g} Hz, {why}: the desk's high-pass runs "
                         f"{lo:g} to {hi:g} Hz")
            continue
        if k is None:
            ops.append({"op": "add_channel", "name": r.name, "hpf_hz": hz})
            k = len(ops) - 1
        else:
            ops[k]["hpf_hz"] = hz
        done.add(k)
        infos.append(f"{label!r} high-pass {hz:g} Hz, {why}")
    if not infos:
        return intent_, []
    return {**intent_, "ops": ops}, infos


# -- a strip order stated by category -----------------------------------------------------------

#: A line or sentence that states the strip order: "Patch order: ...", "Strip order: ...", "Order
#: on the desk: ...", "The channel order is ...", "Lay the strips out: ...". The list after it is
#: read by `stated_order`.
_ORDER_LINE_RE = re.compile(
    r"^[\W_]*(?:the\s+)?(?:(?:patch|strip|channel|input|desk|console|fader|layout)s?\s+order"
    r"|order\s+(?:on|of|across)\s+(?:the\s+)?(?:desk|console|strips|channels|faders|inputs)"
    r"|lay\s+(?:the\s+)?(?:strips|channels)\s+out(?:\s+in\s+(?:this|the)\s+order)?)"
    r"[*_]*(?:\s*[:\-–—]|\s+(?:is|runs|goes|reads|should\s+be)\s*:?)\s*(?P<list>.+)$", re.IGNORECASE)
_ORDER_SPLIT_RE = re.compile(r"\s*(?:,\s*(?:and\s+)?(?:then\s+)?|\bthen\b|\bfollowed\s+by\b|->|→|>|;)\s*",
                             re.IGNORECASE)
#: The shorthand an engineer writes for a kind of source, one family each: "voice", "vox" and
#: "vocals" are one family, as "kit" and "drums", "kbd" and "keys", "brass" and "horns" are.
#: Domain knowledge, used only where a stated word names none of the show's categories itself.
_CATEGORY_FAMILY = {
    **dict.fromkeys(("vocal", "vox", "voc", "voice", "singer", "bv", "bgv", "choir"), "vocal"),
    **dict.fromkeys(("drum", "kit", "drumkit"), "drum"),
    **dict.fromkeys(("bass", "bs"), "bass"),
    **dict.fromkeys(("guitar", "gtr", "gt", "git"), "guitar"),
    **dict.fromkeys(("key", "keyboard", "kbd", "kb"), "key"),
    **dict.fromkeys(("perc", "percussion"), "perc"),
    **dict.fromkeys(("horn", "brass", "wind", "woodwind", "reed"), "horn"),
    **dict.fromkeys(("string", "str"), "string"),
    **dict.fromkeys(("playback", "track"), "playback"),
}
#: The words for "every category the line does not name": "band, then vocals".
_REST_WORDS = {"band", "the band", "instruments", "the instruments", "everything else", "the rest", "rest",
               "everything", "others", "the others", "all else", "all the rest"}


def _order_word(text: str) -> str:
    """A stated category word, without its decoration: "the drums", "all vocal channels" and
    "Drums." are "drums" and "vocal"."""
    t = re.sub(r"[^a-z0-9 ]+", " ", text.casefold())
    t = re.sub(r"^\s*(?:and\s+)?(?:last(?:ly)?\s+|finally\s+)?(?:all\s+)?(?:(?:the|of the)\s+)?", "", t)
    t = re.sub(r"\s+(?:channels?|inputs?|strips?|sources?|section|category|categories|last|first)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _family(word: str) -> str | None:
    """The family of a stated or category word, by its last word, a plural's s dropped."""
    words = word.split()
    if not words:
        return None
    w = words[-1]
    for cand in (w, w[:-1] if len(w) > 2 and w.endswith("s") and not w.endswith("ss") else w,
                 w[:-2] if w.endswith("es") else w):
        if cand in _CATEGORY_FAMILY:
            return _CATEGORY_FAMILY[cand]
    return None


def _same_word(a: str, b: str) -> bool:
    """Two category words that are one word but for case, spacing or a plural's s."""
    fold = lambda w: re.sub(r"s$", "", re.sub(r"[^a-z0-9]+", "", w.casefold()))  # noqa: E731
    return bool(fold(a)) and fold(a) == fold(b)


def show_categories(intent_: dict, rows) -> list[str]:
    """The categories the show's channels carry, in the order they first appear: an
    `add_channel`'s own, then the input list's."""
    out: list[str] = []
    for c in [*(op.get("category") for op in intent_.get("ops") or [] if op.get("op") == "add_channel"),
              *(r.category for r in rows)]:
        c = str(c or "").strip()
        if c and not any(_same_word(c, o) for o in out):
            out.append(c)
    return out


def stated_order(conventions: str, categories: list[str], table_entries=()) -> tuple[list[str], str] | None:
    """The strip order the conventions state by category, as the show's own categories:
    `(categories in order, the line)`, or None when no line states one.

    A stated word names the categories it is (case and a plural's s aside), or that a Category
    table entry lists it under; failing that, the categories of its family ("voice" is the "Vox"
    category, "kbd" is "Keys", "brass" is "Horns": `_CATEGORY_FAMILY`). "band" (or "the rest") is
    every category the line does not name. A word that names nothing the show has is passed over,
    and a line with a word that is no category at all ("Order on the desk: kick, snare, ...") is
    not a category order: None, and the reply's order stands."""
    sentences = [s for line in (conventions or "").splitlines() for s in re.split(r"(?<=[a-z][.!?])\s+", line)]
    for line in sentences:
        m = _ORDER_LINE_RE.match(line.strip())
        if not m:
            continue
        listed = m.group("list").strip()
        listed = re.split(r"(?<=[a-z])\.(?:\s|$)", listed, maxsplit=1, flags=re.IGNORECASE)[0]
        words = [_order_word(w) for w in _ORDER_SPLIT_RE.split(listed)]
        words = [w for w in words if w]
        if len(words) < 2:
            continue
        claimed: dict[str, list[str]] = {}
        known = True
        for w in words:
            if w in _REST_WORDS:
                continue
            direct = [c for c in categories if _same_word(w, c)]
            for entry in table_entries:
                names = [entry.get("name") or "", *(entry.get("aliases") or [])]
                if any(_same_word(w, n) for n in names):
                    direct += [c for c in categories if any(_same_word(c, n) for n in names) and c not in direct]
            if direct:
                claimed[w] = direct
            elif _family(w) is None:
                known = False
                break
        if not known:
            continue
        taken = {c for cs in claimed.values() for c in cs}
        for w in words:
            if w in _REST_WORDS or w in claimed:
                continue
            claimed[w] = [c for c in categories if c not in taken and _family(_order_word(c)) == _family(w)]
            taken |= set(claimed[w])
        order: list[str] = []
        for w in words:
            group = [c for c in categories if c not in taken] if w in _REST_WORDS else claimed.get(w, [])
            order += [c for c in group if c not in order]
        if order:
            return order, line.strip().lstrip("-*# ").strip()
    return None


def with_stated_order(intent_: dict, conventions: str, rows) -> tuple[dict, list[str]]:
    """The intent with the strip order the conventions state by category (`stated_order`), in the
    show's own category names, as its `order` op: the reply's `order` is kept when it already lays
    the strips out that way, and replaced (its `channels`, the order within a category, kept) when
    it does not or when the reply wrote none, at INFO. The engineer stated the order; a reply that
    wrote it in other words ("voice" for a "Vox" category), or left a category out, would put
    those strips last."""
    ops = list(intent_.get("ops") or [])
    entries = [e for e in intent_.get("categories") or [] if isinstance(e, dict)]
    found = stated_order(conventions, show_categories(intent_, rows), entries)
    if found is None:
        return intent_, []
    order, line = found
    at = next((k for k, op in enumerate(ops) if op.get("op") == "order"), None)
    said = [str(c) for c in (ops[at].get("categories") or [])] if at is not None else []
    if at is not None and len(said) == len(order) and all(_same_word(a, b) for a, b in zip(said, order)):
        return intent_, []
    op = {"op": "order", "categories": order}
    if at is not None and ops[at].get("channels"):
        op["channels"] = ops[at]["channels"]
    if at is None:
        ops.append(op)
        why = "the reply wrote no order"
    else:
        ops[at] = op
        why = "the reply's order was " + (", ".join(said) if said else "empty")
    return {**intent_, "ops": ops}, [
        f"the strips are laid out by category as the conventions state ({line[:100]!r}): "
        f"{', '.join(order)}, filled by code; {why}"]


def asked_for(conventions: str) -> list[AskedFor]:
    """The buses, DCAs, mute groups and outputs the conventions ask for, one per `- Name: ...`
    item under a heading that names the kind ("## Busses", "## DCAs", "## Mute Groups",
    "## Output"). Only what is written as an item counts: prose is not parsed for names."""
    out: list[AskedFor] = []
    kind = None
    for line in (conventions or "").splitlines():
        if line.lstrip().startswith("#"):
            words = line.casefold()
            kind = next((k for key, k in _SECTION_KINDS if key in words), None)
            continue
        m = _ITEM_RE.match(line) if kind else None
        if m and 1 <= len(m.group(1).split()) <= 4:
            out.append(AskedFor(kind, m.group(1).strip().strip("\"“”'"), tuple(_NAMED_RE.findall(m.group(2))),
                                m.group(2).strip()))
    return out


def made_names(intent_: dict) -> set[str]:
    """Every bus, group, output and strip name an intent makes, folded."""
    names = {str(op.get("name") or "").casefold() for op in intent_.get("ops") or []
             if op.get("op") in ("add_bus", "add_group", "add_output", "add_channel")}
    for entry in intent_.get("categories") or []:
        for key in ("dca", "mute_group"):
            value = entry.get(key)
            names.update(str(v).casefold() for v in (value if isinstance(value, list) else [value]) if v)
    return names - {""}


def applies(item: AskedFor, categories: set[str]) -> bool:
    """Whether the item asks for anything on this show: one that speaks of categories ("all
    strings-category channels") asks for nothing when none of the input list's categories is
    among its words, as a Strings DCA on a show with no strings."""
    if "categor" not in item.text.casefold():
        return True
    words = set(re.findall(r"[a-z0-9]+", item.text.casefold()))
    return bool(words & categories)


def left_out(intent_: dict, asked: list[AskedFor], categories: set[str] | None = None) -> str:
    """What the conventions ask for that the intent neither makes nor mentions in its notes, as
    one sentence for the repair round; "" when nothing is. `categories` are the input list's
    category words (folded), for `applies`."""
    if categories is not None:
        asked = [a for a in asked if applies(a, categories)]
    made = made_names(intent_)
    notes = " ".join(str(n) for n in intent_.get("notes") or []).casefold()

    def has(a: AskedFor) -> bool:
        names = [a.name, *a.aliases]
        return any(n.casefold() in made or any(m.startswith(n.casefold() + " ") for m in made)
                   or n.casefold() in notes for n in names)

    missing = [a for a in asked if not has(a)]
    if not missing:
        return ""
    listed = "; ".join(f"the {a.kind} {a.name!r} ({a.text[:80]})" for a in missing)
    return (f"the conventions ask for objects the intent does not make: {listed}. Make each one "
            "they ask for with its op, or say in `notes` why it is not made")


def _setting_words():
    """Words that say a line of the conventions gives a category one of the Category table's
    settings: the settings' own words and the desk's colour names (`console_facts`)."""
    from atoo import console_facts as facts
    colours = "|".join(sorted({n.casefold() for n in (*facts.COLOUR_NAMES.values(), *facts.COLOUR_ALIASES)}))
    return re.compile(r"high[- ]?pass|\bhpf\b|\bhz\b|colou?r|\bgain\b|\btrim\b|(?<!-)\bfader\b|\b(?:" + colours + r")\b",
                      re.IGNORECASE)


_CATEGORY_SETTING_RE = _setting_words()


def categories_given_settings(conventions: str, rows) -> list[str]:
    """The input list's category words that some line of the conventions gives a setting the
    Category table carries (a colour, by that word or a desk colour's name, a high-pass, a gain, a
    trim or a fader): "Drums: yellow, high-pass 80 Hz". A word matches as written or with its plural's s dropped. Only those lines
    count: a category named for a bus or a DCA is not a setting of the category."""
    words: dict[str, str] = {}
    for row in rows:
        for w in re.findall(r"[a-z0-9]+", (row.category or "").casefold()):
            words.setdefault(w, w)
            if len(w) > 3 and w.endswith("s"):
                words.setdefault(w[:-1], w)
    found: list[str] = []
    for line in (conventions or "").splitlines():
        if not _CATEGORY_SETTING_RE.search(line):
            continue
        for token in re.findall(r"[a-z0-9]+", line.casefold()):
            word = words.get(token)
            if word and word not in found:
                found.append(word)
    return found


def categories_left_out(intent_: dict, conventions: str, rows) -> str:
    """When the conventions give categories settings and the reply's Category table is empty, one
    sentence for the repair round, naming them; "" otherwise. A table the reply did write is its
    own judgement, and is not second-guessed here."""
    if intent_.get("categories"):
        return ""
    named = categories_given_settings(conventions, rows)
    if not named:
        return ""
    return ("the conventions give settings to categories (" + ", ".join(named) + ") and the reply's "
            "`categories` is empty: write one entry for each category the conventions give settings "
            "to, with only the settings they state")


#: Spellings of a desk colour the desk's own name does not match ("Gray" for its "Grey"): the same
#: colour, not a nearest guess (`console_facts.colour_index` makes none).
_COLOUR_SPELLINGS = {"gray": "Grey"}


def desk_colour(colour) -> str | None:
    """The desk's name for a colour the reply wrote otherwise, or None when it is already the
    desk's or names none: "Gray" is "Grey", and a colour whose LAST word is one of the desk's
    ("Drum-Red", "Keyboards-Amber", "kit lime": a category's name run into its colour) is that
    colour. A colour with no word of the desk's palette in that place is left as written."""
    from atoo import console_facts as facts

    if not isinstance(colour, str) or facts.colour_index(colour) is not None:
        return None
    for word in (colour.strip(), re.split(r"[-\s_/]+", colour.strip())[-1]):
        desk = _COLOUR_SPELLINGS.get(word.casefold())
        if desk:
            return desk
        index = facts.colour_index(word) if word != colour.strip() else None
        if index is not None:
            return word[:1].upper() + word[1:].lower()
    return None


def with_reasonable_values(intent_: dict) -> tuple[dict, list[str]]:
    """The intent with two judgement slips read as what they mean, and an INFO for each, where
    the compile would otherwise refuse the reply (a judgement call is made and said, not
    refused):

    - a high-pass of 0 Hz, on a Category-table entry or a channel, is no high-pass: the field is
      left out, so none is set (the range starts at 20 Hz, and 0 was refused as below it);
    - a colour spelled otherwise than the desk spells it ("Gray") is the desk's colour ("Grey"),
      and one whose last word is the desk's ("Drum-Red") is that colour (`desk_colour`), on a
      channel, a bus or a Category-table entry. A colour with no word of the palette there is
      left as written: a channel's or bus's is refused by the compile, as before."""
    from atoo import console_facts as facts

    infos: list[str] = []
    categories = []
    for entry in intent_.get("categories") or []:
        if isinstance(entry, dict) and entry.get("hpf_hz") == 0:
            entry = {k: v for k, v in entry.items() if k != "hpf_hz"}
            infos.append(f"category {entry.get('name')!r}: a high-pass of 0 Hz is read as no "
                         "high-pass, so none is set")
        desk = desk_colour(entry.get("color")) if isinstance(entry, dict) else None
        if desk:
            infos.append(f"category {entry.get('name')!r}: the colour {entry['color']!r} is the desk's {desk!r}")
            entry = {**entry, "color": desk}
        categories.append(entry)
    ops = []
    for op in intent_.get("ops") or []:
        if op.get("op") == "add_channel" and op.get("hpf_hz") == 0:
            op = {**op, "hpf_hz": None}
            infos.append(f"channel {op.get('name')!r}: a high-pass of 0 Hz is read as no high-pass, so "
                         "none is set")
        colour = op.get("color") if op.get("op") in ("add_channel", "add_bus") else None
        if isinstance(colour, str) and facts.colour_index(colour) is None:
            desk = desk_colour(colour)
            if desk:
                op = {**op, "color": desk}
                infos.append(f"{op['op'].removeprefix('add_')} {op.get('name')!r}: the colour "
                             f"{colour!r} is the desk's {desk!r}")
        ops.append(op)
    out = {**intent_, "ops": ops}
    if "categories" in intent_:
        out["categories"] = categories
    return out, infos


# -- Main's sockets, when the conventions state them -------------------------------------------

_GROUP_WORDS = {"local": "LCL", "lcl": "LCL", "usb": "USB", "aux": "AUX"}
_OUT_SOCKETS_RE = re.compile(
    r"\b(local|lcl|usb|aux|aes50[\s-]?([abc]))\b\s*(?:xlrs?\s*)?(?:outputs?|outs?|xlrs?)?\s*#?\s*(\d{1,3})"
    r"(?:\s*(?:-|–|to|through|thru|\+|and|&)\s*(\d{1,3}))?", re.IGNORECASE)
_OUTPUT_WORD_RE = re.compile(r"\bout(?:put)?s?\b|\bxlrs?\b", re.IGNORECASE)


def _line_naming(name: str, conventions: str, items=()) -> AskedFor | None:
    """The conventions' words about where `name` goes out, when no item of a bus or output section
    states it: the first sentence that names it (a whole word, any heading) and, from the name on,
    states an output socket with an output word ("Main goes to Local outputs 5-6", "the Vocal Wdg
    goes out on AES50-A outputs 1"). Read from the name on, so a sentence naming two objects gives
    each the socket after it. A line that is an item of a section (`items`, read as that item)
    is not read again, and a name used as a category ("drums channels") is not the object. None
    when no sentence does."""
    if not name:
        return None
    own = {" ".join(str(t).split()) for t in items}
    for line in (conventions or "").splitlines():
        if " ".join(line.strip().lstrip("-*# ").split()) in own or _ITEM_RE.match(line) and any(
                " ".join(_ITEM_RE.match(line).group(2).split()) in t for t in own):
            continue
        label = _ITEM_RE.match(line)
        if label and label.group(1).strip().strip("\"“”'").casefold().startswith(name.casefold()):
            # "- Vocal Wdg: a wedge for the singer. It goes out on AES50-A outputs 1": an item under a
            # heading that names no kind is about its label, every sentence of it
            text = label.group(2).strip()
            if _OUTPUT_WORD_RE.search(text) and _OUT_SOCKETS_RE.search(text):
                return AskedFor("line", name, (), text)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            m = re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])(?!\s+(?:channels?|inputs?|category|rows?)\b)",
                          sentence, re.IGNORECASE)
            if not m:
                continue
            rest = sentence[m.start():]
            if _OUTPUT_WORD_RE.search(rest) and _OUT_SOCKETS_RE.search(rest):
                return AskedFor("line", name, (), rest.strip())
    return None


def _stated_item(name: str, by_name: dict, conventions: str) -> AskedFor | None:
    """The item a bus's or output's stated socket is read from: its own item of the conventions
    when that states one, else the sentence that names it (`_line_naming`), else its item (which
    states none) or None."""
    item = by_name.get(str(name or "").casefold())
    if item is not None and stated_sockets(item) is not None:
        return item
    return _line_naming(str(name or ""), conventions, [a.text for a in by_name.values()]) or item


def stated_sockets(item: AskedFor) -> dict | None:
    """The output sockets an item of the conventions states ("routed to AES50-A outputs 41",
    "Local outputs 1-2"), as an intent `patch`; None when it states none Atoo can read."""
    m = _OUT_SOCKETS_RE.search(item.text)
    if m is None:
        return None
    group = m.group(2).upper() if m.group(2) else _GROUP_WORDS[m.group(1).casefold()]
    first, last = int(m.group(3)), int(m.group(4)) if m.group(4) else None
    return {"group": group, "first": first, "count": 2 if last == first + 1 else None}


def _output_spec(op: dict) -> tuple[str | None, dict | None]:
    """Where an op names an output socket: ("to", spec) on a bus, ("patch", spec) on an output."""
    if op.get("op") == "add_bus":
        return "to", (op.get("to") or {}).get("output")
    if op.get("op") == "add_output":
        return "patch", op.get("patch")
    return None, None


def _nearest_free(group: str, first: int, count: int, limit: int, taken: set) -> int | None:
    """The first socket of `count` free outputs of `group` nearest to `first` (a pair starts on an
    odd socket), or None when the group has no room."""
    starts = [n for n in range(1, limit - count + 2)
              if (count == 1 or n % 2 == 1) and not any((group, n + k) in taken for k in range(count))]
    return min(starts, key=lambda n: (abs(n - first), n)) if starts else None


def _fits(spec: dict, console_model: str) -> bool:
    """The sockets exist, and a pair starts on an odd one (`facts.stereo_pair_problem`)."""
    from atoo import console_facts as facts

    count = spec.get("count") or 1
    first = spec.get("first") or 0
    return 1 <= first and first + count - 1 <= facts.output_socket_limit(spec.get("group"), console_model) \
        and (count != 2 or facts.stereo_pair_problem([first, first + 1]) is None)


def stage_boxes(rows) -> tuple[str, ...]:
    """The AES50 groups (`A`, `B`, `C`) the input list takes inputs from: a stage box that is there,
    with outputs of its own."""
    found = set()
    for row in rows:
        spec = input_list.parse_socket_spec(row.patch) if row.patch else None
        if spec is not None and spec[0] in ("A", "B", "C"):
            found.add(spec[0])
    return tuple(sorted(found))


def _relocate(spec: dict, taken: set, console_model: str, boxes=()) -> tuple[dict | None, str | None]:
    """Free outputs for `spec`'s count, and why they were chosen: the free socket of the same group
    nearest the one written; else the nearest free local (LCL) output; else the LOWEST free one on a
    stage box the show already uses (`stage_boxes`). (None, None) when none has room.

    A box's limit here is the AES50 link's 48 channels (`output_socket_limit`), not the jacks the
    box has (an S16 has 8 outputs), so on a box the lowest free socket is taken, never the one
    nearest a number written for another group: a far pick could name a jack the box lacks."""
    from atoo import console_facts as facts

    count = spec.get("count") or 1
    group = spec.get("group")
    tiers = [(group, "Atoo chose the nearest free one of that group")]
    if group != "LCL":
        tiers.append(("LCL", f"this console has no free {group} output for it, so Atoo chose the nearest free local one"))
    tiers += [(box, f"this console has no free {group} or local output for it, so Atoo chose the lowest free "
                    f"one on the {box} stage box the input list already uses")
              for box in boxes if box not in (group, "LCL")]
    for g, why in tiers:
        near = spec.get("first") or 1 if g in (group, "LCL") else 1
        start = _nearest_free(g, near, count, facts.output_socket_limit(g, console_model), taken)
        if start is not None:
            return {"group": g, "first": start, "count": spec.get("count")}, why
    return None, None


def with_free_outputs(intent_: dict, asked: list[AskedFor], console_model: str, boxes=(),
                      conventions: str = "") -> tuple[dict, list[str]]:
    """The intent with no output socket claimed twice: where two buses or outputs write the same
    socket (a bus's LCL 1 and Main's LCL 1-2, two IEM buses on AES 1-2), the one whose socket the
    engineer states (the conventions or instructions) keeps it, else the one written first. A
    socket only the reply chose earns no precedence, not even Main's. The other, if a bus, takes
    free sockets (`_relocate`); if an output, its patch goes: an output may be unpatched, and an
    invented patch is not given another invented one. Each said at INFO. One socket carries one
    signal, so a socket claimed twice leaves one of them dead at the jack. Two the conventions both
    state are left as stated, for verify to name; a bus with nowhere free is left as written, for
    verify to name. An `add_output` with a bus's name (or an
    alias the conventions give it) on that bus's own sockets is the same object said twice, the
    bus with its output in one step and the output in another: it is dropped, said at INFO,
    before any socket is claimed."""
    by_name: dict[str, AskedFor] = {}
    for a in asked:
        if a.kind in ("bus", "output"):
            for n in (a.name, *a.aliases):
                by_name.setdefault(n.casefold(), a)
    ops = list(intent_.get("ops") or [])
    infos: list[str] = []
    # The same object said twice is not two claimants: a monitor bus written with its output in
    # the buses step, and an `add_output` of that name on the same sockets in the outputs step.
    # The bus is the object; the output is dropped, said so, and nothing is moved for it.
    def names_of(op):
        item = by_name.get(str(op.get("name") or "").casefold())
        return {str(op.get("name") or "").casefold()} | ({n.casefold() for n in (item.name, *item.aliases)}
                                                          if item is not None else set())

    def at(spec):
        return (spec.get("group"), spec.get("first"))      # a bus may leave its count to `stereo`

    buses = [(names_of(op), at(spec)) for op in ops if op.get("op") == "add_bus"
             for _, spec in [_output_spec(op)] if spec]
    kept = []
    for op in ops:
        _, spec = _output_spec(op)
        if op.get("op") == "add_output" and spec and any(
                names_of(op) & names and at(spec) == place for names, place in buses):
            infos.append(f"{op.get('name')!r}: the reply made it as a bus with its output on "
                         f"{spec['group']} {spec['first']} and again as an output on the same sockets; "
                         "it is one object, so the output is left out and the bus stands")
            continue
        kept.append(op)
    ops = kept
    claims = []
    for k, op in enumerate(ops):
        where, spec = _output_spec(op)
        if not spec or not _fits(spec, console_model):
            continue
        item = _stated_item(op.get("name"), by_name, conventions)
        stated = stated_sockets(item) if item is not None else None
        own = stated is not None and (stated["group"], stated["first"]) == (spec.get("group"), spec.get("first"))
        claims.append((0 if own else 1, k, where, spec, own))
    taken: set = set()
    holder: dict = {}
    for _, k, where, spec, own in sorted(claims, key=lambda c: (c[0], c[1])):
        sockets = [(spec["group"], spec["first"] + n) for n in range(spec.get("count") or 1)]
        clash = [x for x in sockets if x in taken]
        if not clash or own:
            taken.update(sockets)
            holder.update({x: ops[k].get("name") for x in sockets if x not in holder})
            continue
        op = ops[k]
        wrote = f"{spec['group']} {spec['first']}" + (f"-{spec['first'] + 1}" if (spec.get("count") or 1) == 2 else "")
        also = f"{op.get('name')!r}: the reply wrote {wrote}, which {holder[clash[0]]!r} also uses"
        if where == "patch":
            ops[k] = {key: v for key, v in op.items() if key != "patch"}
            infos.append(f"{also}; nothing the engineer wrote puts it there, so it is left unpatched")
            continue
        new, why = _relocate(spec, taken, console_model, boxes)
        if new is None:
            continue
        ops[k] = {**op, "to": {**op["to"], "output": new}} if where == "to" else {**op, "patch": new}
        taken.update((new["group"], new["first"] + n) for n in range(new.get("count") or 1))
        holder.update({(new["group"], new["first"] + n): op.get("name") for n in range(new.get("count") or 1)})
        infos.append(f"{also}; {why}, so {new['group']} {new['first']} stands")
    if not infos:
        return intent_, []
    return {**intent_, "ops": ops}, infos


def with_stated_outputs(intent_: dict, asked: list[AskedFor], console_model: str, boxes=(),
                        conventions: str = "") -> tuple[dict, list[str]]:
    """The intent with every output socket the reply wrote that cannot exist on this console (a
    group it does not have, a socket past its last, a pair starting on an even socket) made into
    one that can, and an INFO for each,
    so one bad socket costs at most that patch, never the show:

    1. the socket the conventions state for that bus or output ("AES50-A outputs 41" written as
       AES 41 is the model's slip, and the engineer's words say where it goes);
    2. else the free socket of the same group nearest the one written (USB 49 on a desk with 48
       is USB 47-48 or the nearest free);
    3. else the nearest free local (LCL) output, when that group has none free on this console;
    4. else the nearest free output on a stage box the input list already uses (`stage_boxes`);
    5. else an output is built unpatched, said so; a bus with no free output anywhere is left for
       the compile to refuse, naming why (nothing valid can be chosen).

    A socket that exists stays the reply's own choice, and one the conventions state that cannot
    exist is the engineer's and is left for the compile to refuse, naming it."""
    from atoo import console_facts as facts

    by_name: dict[str, AskedFor] = {}
    for a in asked:
        if a.kind in ("bus", "output"):
            for n in (a.name, *a.aliases):
                by_name.setdefault(n.casefold(), a)

    def fits(spec):
        return _fits(spec, console_model)

    taken: set = set()
    for op in intent_.get("ops") or []:
        _, spec = _output_spec(op)
        if spec and fits(spec):
            taken.update((spec["group"], spec["first"] + k) for k in range(spec.get("count") or 1))
    infos: list[str] = []
    ops = []
    for op in intent_.get("ops") or []:
        where, spec = _output_spec(op)
        if not spec:
            # Written with no socket at all, where the conventions state one: carried out, as
            # Main's stated sockets are (`with_main`). A bus routed to Main is left to the reply.
            item = _stated_item(op.get("name"), by_name, conventions) if op.get("op") in ("add_bus", "add_output") else None
            stated = stated_sockets(item) if item is not None else None
            routed = op.get("op") == "add_bus" and (op.get("to") or {}).get("main")
            if stated is not None and fits(stated) and not routed and not (
                    op.get("op") == "add_output" and op.get("object") == "main"):
                new = {**stated, "count": stated.get("count") or (2 if op.get("stereo") else None)}
                op = ({**op, "to": {**(op.get("to") or {}), "output": new}} if op.get("op") == "add_bus"
                      else {**op, "patch": new})
                taken.update((new["group"], new["first"] + k) for k in range(new.get("count") or 1))
                infos.append(f"{op.get('name')!r} patched to {new['group']} {new['first']}, filled by code: the "
                             f"conventions say {item.text[:80]!r} and the reply gave it no socket")
            ops.append(op)
            continue
        wrote = f"{spec.get('group')} {spec.get('first')}"
        item = _stated_item(op.get("name"), by_name, conventions)
        stated = stated_sockets(item) if item is not None else None
        if fits(spec):
            if stated is not None and fits(stated) and (spec.get("group"), spec.get("first")) != (
                    stated["group"], stated["first"]):
                # The engineer said where it goes ("AES50-A outputs 1-2" is A 1-2, not AES 1-2): an
                # explicit instruction is carried out, whatever socket the reply chose.
                new = {**stated, "count": stated.get("count") or spec.get("count")}
                op = ({**op, "to": {**op["to"], "output": new}} if where == "to" else {**op, "patch": new})
                infos.append(f"{op.get('name')!r}: the reply wrote {wrote}; the conventions say "
                             f"{item.text[:80]!r}, so {new['group']} {new['first']} stands")
            ops.append(op)
            continue
        if stated is not None and not fits(stated):
            ops.append(op)       # the engineer's own socket cannot exist: refused, naming it
            continue
        if stated is not None:
            new, why = {**stated, "count": stated.get("count") or 1}, f"the conventions say {item.text[:80]!r}"
            if where == "to" and new["count"] == 1 and op.get("stereo"):
                op = {**op, "stereo": False}
                why += ", one output, so the bus is mono"
        else:
            new, why = _relocate(spec, taken, console_model, boxes)
            if new is None and where == "to":
                ops.append(op)        # no output at all is free: the compile refuses it, naming why
                continue
            if new is None:
                why = "no output of this console is free for it, so it is left unpatched"
        if new is not None:
            taken.update((new["group"], new["first"] + k) for k in range((new.get("count") or 1)))
        if where == "to":
            op = {**op, "to": {**op["to"], "output": new}}
        else:
            op = {k: v for k, v in op.items() if k != "patch"} if new is None else {**op, "patch": new}
        infos.append(f"{op.get('name')!r}: the reply wrote {wrote}, which does not exist on this console; "
                     + why + (f", so {new['group']} {new['first']} stands" if new is not None else ""))
        ops.append(op)
    return {**intent_, "ops": ops}, infos


def stated_main(asked: list[AskedFor], conventions: str = "") -> tuple[AskedFor, dict | None] | None:
    """The conventions' Main item and the sockets it states, as an intent `patch` (None when it
    states none Atoo can read); a sentence that names Main and states its socket when no item does
    (`_line_naming`). None when the conventions say nothing of Main's socket."""
    item = next((a for a in asked if a.kind == "output" and a.name.casefold().startswith("main")), None)
    if item is None or stated_sockets(item) is None:
        item = _line_naming("Main", conventions, [a.text for a in asked]) or item
    if item is None:
        return None
    return item, stated_sockets(item)


def with_main(intent_: dict, asked: list[AskedFor], conventions: str = "") -> tuple[dict, str | None]:
    """The intent with Main patched where the conventions state its sockets and the intent
    leaves Main unpatched or does not make it, and the INFO saying so (None when nothing was
    done). What the conventions state is the engineer's; filling it in is not invention."""
    stated = stated_main(asked, conventions)
    if stated is None:
        return intent_, None
    item, spec = stated
    ops = list(intent_.get("ops") or [])
    mains = [k for k, op in enumerate(ops) if op.get("op") == "add_output" and op.get("object") == "main"]
    if any(ops[k].get("patch") for k in mains):
        return intent_, None
    if spec is None:
        return intent_, (f"Main: the conventions say {item.text[:80]!r}, which names no socket Atoo can "
                         "read, and the reply gave none; Main is left unpatched")
    where = f"{spec['group']} {spec['first']}" + ("-" + str(spec["first"] + 1) if spec["count"] == 2 else "")
    if mains:
        ops[mains[0]] = {**ops[mains[0]], "patch": spec}
        said = "the reply made Main without its sockets"
    else:
        ops.append({"op": "add_output", "object": "main", "name": "Main" if item.kind == "line" else item.name,
                    "patch": spec})
        said = "the reply did not make Main"
    return ({**intent_, "ops": ops},
            f"Main patched to {where}, filled by code: the conventions say {item.text[:80]!r} and {said}")


_LEFT_OUT_RE = re.compile(r"input-list row (?P<name>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\") is left out, "
                          r"as the words it quotes say: (?P<quote>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")")


def declare_left_out(plan: dict, rows, lines: list[str]) -> None:
    """Write `plan["unassigned_inputs"]` for the input-list rows a build left out ON PURPOSE, so
    verify reads them as declared (a WARNING to confirm), not as dropped (an ERROR that blocks the
    plan): a row the engineer's quoted words leave out (`drop` with `quote`), with that quote; and
    a row whose channel could not be built and that a "not built: ..." line names (the refused
    op's rows, by their repr). A row no channel uses for any other reason -- one the reply dropped
    silently in the same build, or one behind "not built as the reply wrote it" (that row WAS
    built, from the list) -- is left for verify to report."""
    import ast

    used = set()
    for ch in plan.get("channels") or []:
        source = ch.get("source") or {}
        for key in ("input", "pair_input"):
            if source.get(key):
                used.add(str(source[key]).casefold())
    quoted = {}
    for line in lines:
        m = _LEFT_OUT_RE.search(line)
        if m:
            quoted[str(ast.literal_eval(m.group("name"))).casefold()] = ast.literal_eval(m.group("quote"))
    unbuilt = [line.casefold() for line in lines if line.startswith("not built:")]
    declared = plan.setdefault("unassigned_inputs", [])
    have = {str(e.get("input") if isinstance(e, dict) else e).casefold() for e in declared}
    for row in rows:
        key = row.name.casefold()
        if key in used or key in have:
            continue
        if key in quoted:
            said_in = "input list" if quoted[key].casefold() in str(row.notes or "").casefold() else "conventions"
            declared.append({"input": row.name, "quote": quoted[key], "from": said_in})
        elif any(repr(row.name).casefold() in line for line in unbuilt):
            declared.append({"input": row.name})


_SECTION_OF = {"bus": "busses", "dca": "dcas", "mute group": "mute_groups", "output": "outputs"}


def merge_built(base: dict, change_set: dict, *, console_model: str, text, infos: list[str], reply=""):
    """`patch.merge_change` for a BUILD: an object the desk has no room for ("every mute group on
    this console is already in use") costs that object, never the show. It is left out with every
    reference to it (a channel's DCA or mute group, a send to the bus), named at INFO ("not
    built"), and the rest merged. Any other refusal is the answer, as before."""
    import ast

    for _ in range(4):
        merge = patch.merge_change(base, change_set, console_model=console_model, text=text)
        if not merge.refused:
            return merge
        full = [c for c in merge.refused if "already in use" in c.reason and c.kind_of_object in _SECTION_OF]
        if not full:
            break          # what is left is not a matter of room: the answer, as before
        add = change_set.get("add") or {}
        for c in full:
            section = _SECTION_OF[c.kind_of_object]
            try:
                name = ast.literal_eval(c.where)
            except (ValueError, SyntaxError):
                name = c.where
            (add.get(section) or {}).pop(name, None)
            for ch in add.get("channels") or []:
                for field in ("dca", "mute_group"):
                    if isinstance(ch.get(field), list):
                        ch[field] = [g for g in ch[field] if g != name]
                if section == "busses" and isinstance(ch.get("bus_sends"), list):
                    ch["bus_sends"] = [b for b in ch["bus_sends"] if b.get("bus") != name]
            infos.append(f"not built: the {c.kind_of_object} {name!r}, because {c.reason}")
    raise generate.GenerationError(
        "the show cannot be built as the intent describes it:\n  "
        + "\n  ".join(c.reason for c in merge.refused), reply=reply)


def generate_plan(conventions: str, input_csv: str, *, provider, console_model: str,
                  conventions_name: str = "<conventions>", input_name: str = "<input list>",
                  instructions: str | None = None, instructions_name: str | None = None,
                  category_table=None, known_presets=None, infos: list[str] | None = None,
                  replies: list | None = None, trace: dict | None = None,
                  reserved_user_slots=()) -> dict:
    """Conventions + input list -> a plan, by an intent. Anything code decided on the way is
    appended to `infos`; the model's replies to `replies`. Raises `generate.GenerationError`
    when the model could not give a usable intent or the plan cannot be made (each reason
    named), the way `generate_plan` does."""
    infos = infos if infos is not None else []
    trace = trace if trace is not None else {}
    base = patch.empty_base(console_model)
    rows = input_list.parse_input_list(input_csv)
    conventions_text = "\n".join(t for t in (conventions, instructions) if t)
    asked = asked_for(conventions_text) + asked_strips(conventions_text)
    categories = {w for row in rows for w in re.findall(r"[a-z0-9]+", (row.category or "").casefold())}
    boxes = stage_boxes(rows)
    filled: dict = {}

    def prepare(intent_):
        intent_, filled["values"] = with_reasonable_values(intent_)
        intent_, filled["rows"] = resolve_row_names(intent_, rows)
        intent_, pair_infos = with_stated_pairs(intent_, rows, conventions_text)
        intent_, aux_infos = with_stated_aux(intent_, rows, conventions_text)
        intent_, hpf_infos = with_stated_hpf(intent_, rows, conventions_text)
        intent_, strip_infos = with_asked_strips(intent_, conventions_text, rows)
        intent_, order_infos = with_stated_order(intent_, conventions_text, rows)
        filled["rows"] = [*filled["rows"], *pair_infos, *aux_infos, *hpf_infos, *strip_infos, *order_infos]
        intent_, filled["outputs"] = with_stated_outputs(intent_, asked, console_model, boxes, conventions_text)
        intent_, filled["main"] = with_main(with_rows(intent_, rows), asked, conventions_text)
        intent_, free_infos = with_free_outputs(intent_, asked, console_model, boxes, conventions_text)
        filled["outputs"] = [*filled["outputs"], *free_infos]
        return intent_

    try:
        change_set = intent.compile_change(
            REQUEST, base, provider=provider, console_model=console_model,
            conventions=conventions, conventions_name=conventions_name,
            instructions=instructions, instructions_name=instructions_name,
            input_list_text=input_csv, input_csv=input_csv, input_name=input_name,
            category_table=category_table, known_presets=known_presets, infos=infos, trace=trace,
            prepare=prepare, reserved_user_slots=reserved_user_slots,
            complete=lambda intent_: "; ".join(m for m in (
                left_out(prepare(intent_), asked, categories),
                categories_left_out(intent_, conventions_text, rows)) if m))
        infos.extend(filled.get("values") or [])
        infos.extend(filled.get("rows") or [])
        infos.extend(filled.get("outputs") or [])
        if filled.get("main"):
            infos.append(filled["main"])
    except IntentRefused as refused:
        raise generate.GenerationError(
            "the intent cannot be built on this console:\n  " + "\n  ".join(refused.reasons),
            reply=(trace.get("replies") or [""])[-1]) from refused
    except patch.ChangeError as exc:
        raise generate.GenerationError(str(exc), partial_text=exc.partial_text or "",
                                       reply=(trace.get("replies") or [""])[-1]) from exc
    finally:
        if replies is not None:
            replies.extend(trace.get("replies") or [])
    text = change_set.get(patch.TEXT_KEY)
    change_set = patch.validate_change_set(change_set, infos=infos)
    merge = merge_built(base, change_set, console_model=console_model, text=text, infos=infos,
                        reply=(trace.get("replies") or [""])[-1])
    plan = merge.plan
    declare_left_out(plan, rows, [*infos, *merge.infos])
    plan.setdefault("meta", {})["console_model"] = console_model
    plan.setdefault("notes", []).extend(
        {"text": line, "source": "allocation"} for line in [*infos, *merge.infos])
    return plan
