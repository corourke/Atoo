"""Is this text garbage? (`atoo patch --intent`)

A reply that is valid against the intent schema can still be nonsense: a
7B model wrote, for "add a tambourine mic on A 17", a change named
"Add a few words naming the<CJK>", a category "vocals<CJK>" and a microphone
"SM500". A schema takes any string for those, so the compiler holds them to
what the engineer's own words and the desk can account for. This is not a
judgement call to infer (an error of judgement is not an error of
patching): a made-up microphone or a name with a script nobody typed is not
a preference the engineer can correct at soundcheck, it is garbage, so it is
refused with which one.

The rules, each with the reason it is that strict and no stricter:

* **A character** outside printable ASCII must appear in the request, the
  input list or a name on the desk. A show in another language keeps its
  own letters; a stray CJK character in an English request is not one of them.
  Control characters are never a name.
* **A new name** (a strip, bus, DCA, mute group, output, or a rename): every
  word must be traceable to the request, the input list or the desk. A word
  is traceable if it is (case-insensitively) a word of one of them; or an
  abbreviation of one, at least three letters ("Tamb" for "tambourine"); or a
  plural of one; or a number or a single letter ("Choir 2", "Choir L"). A
  CamelCase name is judged by its parts ("DrumsComp" is "Drums" and "Comp"),
  and a name that appears verbatim in the request is traceable whole. A
  length over the console's 16 is not refused here: the cut-with-INFO rule
  already covers a label that is merely long.
* **A category** is one the show knows: a Category table alias, a category of
  the input list, or one of the domain knowledge's category words.
* **A microphone model** is one the request, the input list or the desk
  names: nothing in the repository lists every microphone, and the compiler
  cannot tell a real one from a plausible one, so it accepts only one it was
  told.
* **A colour** is one of the console's eighteen (`console_facts.COLOUR_NAMES`).
* **A preset** is one the library holds, when the caller gives the library.
* **The change's own name** is a label for the journal. A label with a stray
  character is not refused: it is replaced by the first words of the request,
  at INFO. Notes with a stray character are dropped, at INFO.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from atoo import console_facts as facts

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[^\W\d_]+", re.UNICODE)
_DOMAIN = Path(__file__).resolve().parent / "domain" / "knowledge.md"


def domain_categories() -> set[str]:
    """The category words the domain knowledge names ("Band", "VOX", "Horns" ...)."""
    text = _DOMAIN.read_text(encoding="utf-8")
    start = text.index("## Category words engineers use")
    end = text.index("\n## ", start + 1)
    return {w.casefold() for quoted in re.findall(r'"([^"]+)"', text[start:end])
            for w in re.split(r"\s+or\s+|,", quoted) if w.strip()}


def input_list_categories(input_list_text: str | None) -> set[str]:
    if not input_list_text:
        return set()
    try:
        rows = csv.DictReader(io.StringIO(input_list_text))
        return {(r.get("category") or "").strip().casefold() for r in rows} - {""}
    except csv.Error:
        return set()


class Sanity:
    def __init__(self, base: dict, *, text: str | None, input_list_text: str | None = None,
                 category_table=None, known_presets=None, conventions_text: str | None = None):
        self.text, self.input_list = text, input_list_text or ""
        desk = [str(c.get("name") or "") for c in base.get("channels") or []]
        desk += [str(n) for k in ("busses", "dcas", "mute_groups", "outputs")
                 for n in (base.get(k) or {})]
        self.desk_models = [str((c.get("source") or {}).get("model") or "")
                            for c in base.get("channels") or []]
        self.corpus = " \n".join([text or "", self.input_list, *desk])
        self.words = {w.casefold() for w in _WORD.findall(self.corpus)}
        self.chars = set(self.corpus)
        #: the conventions and instructions name a show's buses, groups and
        #: outputs ("Monitor 1", "Reverb Send"), so a NEW one of those may use
        #: their words; a strip's name may not (it comes from the request)
        self.structural_words = self.words | {w.casefold() for w in _WORD.findall(conventions_text or "")}
        self.chars |= set(conventions_text or "")
        self.categories = set(domain_categories()) | input_list_categories(input_list_text)
        if category_table is not None:
            self.categories |= {a for a in category_table.by_alias}
        self.known_presets = None if known_presets is None else {p.casefold() for p in known_presets}
        #: with no request text the words of a name cannot be traced
        self.check_words = text is not None

    # -- characters ---------------------------------------------------------

    def stray_characters(self, value: str) -> list[str]:
        return sorted({ch for ch in value if ch not in self.chars and not (" " <= ch <= "~")} |
                      {ch for ch in value if ord(ch) < 32})

    # -- names --------------------------------------------------------------

    def _traceable(self, word: str, words: set | None = None) -> bool:
        words = self.words if words is None else words
        w = word.casefold()
        if w.isdigit() or len(w) == 1 or w in words:
            return True
        if w.endswith("s") and w[:-1] in words:
            return True
        return len(w) >= 3 and any(t.startswith(w) or (len(t) >= 3 and w.startswith(t))
                                   for t in words)

    def name_problem(self, name: str, *, structural: bool = False) -> str | None:
        """Why `name` cannot be a new object's name, or None."""
        stray = self.stray_characters(name)
        if stray:
            return (f"the name contains {''.join(stray)!r}, which appears nowhere in the request, "
                    "the input list or the desk")
        if not self.check_words or (self.text and name.casefold().strip() in self.text.casefold()):
            return None
        missing = []
        for chunk in _WORD.findall(name):
            parts = _CAMEL.findall(chunk) or [chunk]
            words = self.structural_words if structural else self.words
            if not (self._traceable(chunk, words) or all(self._traceable(p, words) for p in parts)):
                missing.append(chunk)
        if missing:
            return (f"the name has the word {', '.join(repr(m) for m in missing)}, which appears "
                    "nowhere in the request, the input list, the desk"
                    + (" or the conventions" if structural else "")
                    + ", so it cannot be a name the engineer meant")
        return None

    # -- fields that are free text in the schema ------------------------------

    def category_problem(self, category: str) -> str | None:
        if category.casefold().strip() in self.categories:
            return None
        return (f"the category {category!r} is not one this show knows (no Category table alias, "
                "input-list category or domain category word matches it)")

    def model_problem(self, model: str) -> str | None:
        wanted = model.casefold().strip()
        if not wanted or wanted in self.corpus.casefold() or any(
                wanted == m.casefold().strip() for m in self.desk_models):
            return None
        return (f"the microphone model {model!r} is not named in the request, the input list or "
                "on the desk; a model is only accepted when someone said it")

    def colour_problem(self, colour: str) -> str | None:
        if facts.colour_index(colour) is not None:
            return None
        return (f"{colour!r} is not a colour this console has "
                f"({', '.join(facts.COLOUR_NAMES.values())})")

    def preset_problem(self, preset: str) -> str | None:
        if self.known_presets is None or preset.casefold() in self.known_presets:
            return None
        return f"{preset!r} is not a preset in the library"

    # -- labels --------------------------------------------------------------

    def label_ok(self, label: str) -> bool:
        return not self.stray_characters(label)
