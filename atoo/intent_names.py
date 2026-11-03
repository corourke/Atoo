"""A new object's name, when the request did not give one (`atoo patch --intent`).

A new object is named from the request's words, at INFO. The
request "Add a stereo IEM bus (reuse bus 5)" gives no name; a model that writes
"Drum IEM" has invented one, and that was an existing bus. So the name of a new
bus, DCA, mute group or output is **the engineer's** only when every word of it
is in the request. Otherwise the code derives it from the request's own words,
takes the first free variant if it is taken ("IEM 2"), and says so at INFO. A
name the engineer DID give that clashes with an object on the desk is refused,
naming the clash: it is theirs, and the code does not change it.

The rule is general over the request text, not tied to a request:

1. a name after "called" or "named" ("a bus called FOH Verb") or in quotes next
   to the object word;
2. else the word or two immediately before the object word ("a stereo IEM bus"
   is IEM; "the vocal reverb bus" is vocal reverb), skipping the small words
   an engineer puts there (a, new, stereo, another ...);
3. else the word or two after "for" ("a DCA for the horns" is Horns);
4. else the object word itself ("Bus", "DCA", "Mute group", "Output").
"""

from __future__ import annotations

import re

#: The words that name each kind of object in a request.
KIND_WORDS = {
    "bus": ("bus", "busses", "buses"),
    "dca": ("dca", "dcas"),
    "mute_group": ("mute group", "mute-group", "mutegroup"),
    "output": ("output", "matrix", "main"),
}
DEFAULT = {"bus": "Bus", "dca": "DCA", "mute_group": "Mute group", "output": "Output"}

#: Small words that sit before an object word and are not its name.
_SMALL = frozenset("""a an the new another extra additional more stereo mono dedicated separate
    and or for to of my our your their its this that these those add create make put give build
    please also then now one two first second third mix mixes send sends reuse use using on in
    with without into it we i you""".split())

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'+\-]*")
_CALLED = re.compile(r"\b(?:called|named|name it|call it)\s+[\"“']?([^\"”',.;()\n]+)", re.I)


def words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text or "")]


def engineers_name(name: str, request: str | None) -> bool:
    """Whether `name` is in the request: every one of its words."""
    mine = words(name)
    return bool(mine) and request is not None and set(mine) <= set(words(request))


def _free(name: str, taken) -> tuple[str, bool]:
    """`name` or its first free variant ("IEM 2"), and whether it had to change."""
    used = {t.casefold() for t in taken}
    if name.casefold() not in used:
        return name, False
    n = 2
    while f"{name} {n}".casefold() in used:
        n += 1
    return f"{name} {n}", True


def derive(kind: str, request: str | None, taken) -> tuple[str, str]:
    """`(name, how)` for a new `kind` object the request gave no name: the name,
    and a clause saying where it came from (for the INFO)."""
    text = request or ""
    found, how = None, None
    called = _CALLED.search(text)
    if called and called.group(1).strip():
        found, how = called.group(1).strip().rstrip(" ."), "the name the request gave"
    if found is None:
        for word in KIND_WORDS[kind]:
            for match in re.finditer(rf"\b{re.escape(word)}\b(?!\s*\d)", text, re.I):
                before = _WORD.findall(text[:match.start()])[::-1]
                picked: list[str] = []
                for w in before[:3]:
                    if w.casefold() in _SMALL:
                        if picked:
                            break
                        continue
                    picked.append(w)
                if picked:
                    found, how = " ".join(reversed(picked)), "the request's own words"
                    break
            if found:
                break
    if found is None:
        for word in KIND_WORDS[kind]:
            preposition = "for|with|to hold|to carry" + ("|on|over" if kind in ("dca", "mute_group") else "")
            m = re.search(rf"\b{re.escape(word)}\b\s+(?:{preposition})\s+(?:the\s+|my\s+|our\s+)?"
                          r"([A-Za-z0-9][\w'+\-]*(?:\s+[A-Za-z0-9][\w'+\-]*)?)", text, re.I)
            if m:
                tail = [w for w in m.group(1).split() if w.casefold() not in _SMALL]
                if tail:
                    found, how = " ".join(tail[:2]), "the request's own words"
                    break
    if found is None:
        found, how = DEFAULT[kind], "the kind of object, the request having no word for it"
    if found == found.lower():
        found = found.title()   # "vocal reverb" is written the way a desk names things
    name, changed = _free(found, taken)
    if changed:
        how += f"; {found!r} was taken, so the first free variant"
    return name, how
