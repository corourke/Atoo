"""Every address of an Apply preview, in the tile it belongs to.

Apply's Preview draws the desk as tiles (`desk_view`): one per channel,
aux, bus, main, matrix, DCA and mute group, one per input and output
socket group, and one per FX slot and a Console bank for
what belongs to no strip. Clicking a tile shows its
**Detail** in the side bar: what this write changes on it, with the value
now and after, then what it leaves as it is. This module works out that
Detail, so the page only paints it (`apply.js`) and a test can read it
without a browser.

**Every address lands in exactly one tile** (`tile_of`). A strip's own
addresses are its tile; `/io/in/{group}/...` and `/io/out/{group}/...`
are the socket group's; `/fx/{n}/...` the slot's; `/cfg/talk/...` the
Console's Talkback tile; and anything else the Console's catch-all Other
tile, so no row of the journal can go unshown. The tiles' change counts
therefore add up to the preview's "N will change".

**"Will change" is the engine's answer**, the journal row's own
`would_change` (`apply.WriteRecord.would_change`, `_values_equal` with the
stepped tolerance), never a comparison of the two strings
drawn here. A value the desk holds within that tolerance is listed under
Not changing, with the plan's figure beside it.

**Names and units are a reading aid**, not a parameter map: a table of
the leaves a full build writes, with a fallback to the leaf's own path
for anything not in it, so an address the table does not know is still
shown, under "Other", rather than dropped.
"""

from __future__ import annotations

import re

from atoo import console_facts as facts

#: The socket groups that always have a tile, in the order the desk lists
#: them (one tile per group, not per socket). A group outside
#: this list that a preview touches (`AUX`, `PLAY`, `REC` ...) gets a tile
#: of its own after these, so no address goes without one.
SOCKET_GROUPS: tuple[tuple[str, str], ...] = (
    ("LCL", "Local"), ("A", "AES50-A"), ("B", "AES50-B"), ("C", "AES50-C"),
    ("SC", "StageConnect"), ("USB", "USB"), ("CRD", "Card"), ("MOD", "Module"),
    ("AES", "AES/EBU"),
)
_EXTRA_GROUP_NAMES = {"AUX": "Aux In", "PLAY": "Player", "REC": "Recorder",
                      "OSC": "Oscillator", "USR": "User"}

#: What a tile is, in Detail's heading ("Channel 1", "Input sockets, Local").
KIND_WORDS = {"ch": "Channel", "aux": "Aux", "bus": "Bus", "main": "Main", "mtx": "Matrix",
              "dca": "DCA", "mgrp": "Mute group", "in": "Input sockets",
              "out": "Output sockets", "fx": "FX slot", "cfg": "Console"}

#: Detail's headings, in the order the desk's own screen runs: the strip,
#: its input, its processing, then where it goes. A send or a main route
#: is its own heading ("Send to Drums (bus 5)", "Main 1") and sorts after
#: these, in that order; "Other" is last.
SECTION_ORDER = ("Strip", "Patch", "Input", "Filter", "Gate", "Gate sidechain", "Pre-EQ",
                 "EQ", "Dynamics", "Dynamics crossover", "Dynamics sidechain", "Insert",
                 "Delay", "Effect", "Console", "DCAs and mute groups")

_STRIP_RE = re.compile(r"^/(ch|aux|bus|main|mtx|dca|mgrp)/(\d+)(?:/(.*))?$")
_IO_RE = re.compile(r"^/io/(in|out)/([A-Za-z]+)/(\d+)(?:/(.*))?$")
_FX_RE = re.compile(r"^/fx/(\d+)(?:/(.*))?$")

# Units: how a number reads. "bool" is 0/1 shown as off/on, "colour" a WING
# colour index shown with its name, "fader" dB where the bottom is -inf.
_HZ, _DB, _MS, _BOOL, _COLOUR, _FADER = "Hz", "dB", "ms", "bool", "colour", "fader"

#: A strip's leaves: path below `/{kind}/{n}/` -> (heading, name, unit).
_STRIP_LEAVES: dict[str, tuple[str, str, "str | None"]] = {
    "name": ("Strip", "name", None), "col": ("Strip", "color", _COLOUR),
    "clink": ("Strip", "name follows source", _BOOL), "busmono": ("Strip", "mono", _BOOL),
    "fdr": ("Strip", "starting fader", _FADER), "mute": ("Strip", "starting mute", _BOOL),
    "tags": ("DCAs and mute groups", "tags", None),
    "in/conn/grp": ("Patch", "group", None), "in/conn/in": ("Patch", "socket", None),
    "in/set/altsrc": ("Input", "alternate source", _BOOL), "in/set/trim": ("Input", "trim", _DB),
    "in/set/dlymode": ("Input", "delay mode", None), "in/set/dly": ("Input", "delay", None),
    "in/set/dlyon": ("Input", "delay on", _BOOL),
    "flt/mdl": ("Filter", "model", None), "flt/lc": ("Filter", "low cut", _BOOL),
    "flt/lcf": ("Filter", "low cut frequency", _HZ), "flt/lcs": ("Filter", "low cut slope", None),
    "flt/hc": ("Filter", "high cut", _BOOL), "flt/hcf": ("Filter", "high cut frequency", _HZ),
    "flt/hcs": ("Filter", "high cut slope", None), "flt/tf": ("Filter", "tilt filter", _BOOL),
    "flt/tilt": ("Filter", "tilt", _DB),
    "gate/on": ("Gate", "on", _BOOL), "gate/mdl": ("Gate", "model", None),
    "gate/mix": ("Gate", "mix", None), "gate/gain": ("Gate", "make-up gain", _DB),
    "gate/thr": ("Gate", "threshold", _DB), "gate/range": ("Gate", "range", _DB),
    "gate/att": ("Gate", "attack", _MS), "gate/hld": ("Gate", "hold", _MS),
    "gate/rel": ("Gate", "release", _MS), "gate/acc": ("Gate", "accent", _DB),
    "gate/ratio": ("Gate", "ratio", None), "gate/depth": ("Gate", "depth", _DB),
    "gate/fast": ("Gate", "fast", _BOOL), "gate/peak": ("Gate", "peak", _BOOL),
    "peq/on": ("Pre-EQ", "on", _BOOL),
    "eq/on": ("EQ", "on", _BOOL), "eq/mdl": ("EQ", "model", None), "eq/mix": ("EQ", "mix", None),
    "eq/tilt": ("EQ", "tilt", _DB),
    "eq/leq": ("EQ", "low band shape", None), "eq/heq": ("EQ", "high band shape", None),
    "dyn/on": ("Dynamics", "on", _BOOL), "dyn/mdl": ("Dynamics", "model", None),
    "dyn/mix": ("Dynamics", "mix", None), "dyn/gain": ("Dynamics", "make-up gain", _DB),
    "dyn/thr": ("Dynamics", "threshold", _DB), "dyn/ratio": ("Dynamics", "ratio", None),
    "dyn/knee": ("Dynamics", "knee", None), "dyn/det": ("Dynamics", "detector", None),
    "dyn/att": ("Dynamics", "attack", _MS), "dyn/hld": ("Dynamics", "hold", _MS),
    "dyn/rel": ("Dynamics", "release", _MS), "dyn/env": ("Dynamics", "envelope", None),
    "dyn/auto": ("Dynamics", "auto", _BOOL),
    "preins/on": ("Insert", "pre-insert on", _BOOL), "preins/ins": ("Insert", "pre-insert", None),
    "postins/on": ("Insert", "post-insert on", _BOOL),
    "postins/ins": ("Insert", "post-insert", None),
    "dly/on": ("Delay", "on", _BOOL), "dly/mode": ("Delay", "mode", None),
    "dly/dly": ("Delay", "delay", None),
}
for _part, _heading in (("gatesc", "Gate sidechain"), ("dynsc", "Dynamics sidechain"),
                        ("dynxo", "Dynamics crossover")):
    _STRIP_LEAVES.update({
        f"{_part}/type": (_heading, "type", None), f"{_part}/f": (_heading, "frequency", _HZ),
        f"{_part}/q": (_heading, "Q", None), f"{_part}/src": (_heading, "source", None),
        f"{_part}/tap": (_heading, "tap", None), f"{_part}/depth": (_heading, "depth", _DB),
    })
_BAND_RE = re.compile(r"^(eq|peq)/([1-6lh])([gfq])$")
_BAND_WORDS = {"l": "low band", "h": "high band"}
_BAND_PART = {"g": ("gain", _DB), "f": ("frequency", _HZ), "q": ("Q", None)}
_SEND_RE = re.compile(r"^send/(\d+)/(on|lvl|mode|pan|pon|ind)$")
_SEND_LEAVES = {"on": ("on", _BOOL), "lvl": ("level", _FADER), "mode": ("mode", None),
                "pan": ("pan", None), "pon": ("pan follows", _BOOL), "ind": ("independent", _BOOL)}
_MAIN_RE = re.compile(r"^main/(\d+)/(on|lvl|pre)$")

#: A socket's leaves.
_SOCKET_LEAVES: dict[str, tuple[str, "str | None"]] = {
    "name": ("name", None), "col": ("color", _COLOUR), "g": ("head-amp gain", _DB),
    "vph": ("phantom power", _BOOL), "mode": ("mode", None), "mute": ("mute", _BOOL),
    "inv": ("polarity invert", _BOOL), "grp": ("source group", None),
    "in": ("source number", None), "lvl": ("level", _DB), "icon": ("icon", None),
}

#: An FX slot's leaves the build commonly writes; any other is its own path.
_FX_LEAVES: dict[str, tuple[str, "str | None"]] = {
    "mdl": ("model", None), "fxmix": ("mix", None), "on": ("on", _BOOL),
    "pdel": ("pre-delay", None), "dcy": ("decay", None), "lmult": ("low multiplier", None),
    "hmult": ("high multiplier", None), "mod": ("modulation", None), "lc": ("low cut", None),
    "hc": ("high cut", None), "out": ("output", None), "trans": ("transition", None),
}

_CONSOLE_LEAVES = {"cfg/talk/assign": "talkback assign"}

_OWNER_STRIP_RE = re.compile(r"^(ch|aux|bus|mtx|main) (\d+)\b")
_OWNER_OUTPUT_RE = re.compile(r"^output (.+?) \(")
_PRESET_RE = re.compile(r": preset (.+) \S+$")


# ---- where an address belongs ----------------------------------------------


def tile_of(address: str) -> str:
    """The key of the one tile an address is shown under: `ch/1`,
    `in/A`, `out/LCL`, `fx/5`, `cfg/talk` or, for anything else,
    `cfg/other`."""
    m = _STRIP_RE.match(address or "")
    if m and 1 <= int(m.group(2)) <= facts.CAPACITY[m.group(1)]:
        return f"{m.group(1)}/{int(m.group(2))}"
    m = _IO_RE.match(address or "")
    if m:
        return f"{m.group(1)}/{m.group(2).upper()}"
    m = _FX_RE.match(address or "")
    if m and 1 <= int(m.group(1)) <= facts.FX_SLOTS:
        return f"fx/{int(m.group(1))}"
    if (address or "").startswith("/cfg/talk/"):
        return "cfg/talk"
    return "cfg/other"


def socket_word(group: str, n: "int | str") -> str:
    """How a socket is named in a sentence: `AES50-A 1`, `LCL 3`."""
    return f"AES50-{group} {n}" if group in facts.AES50_PORTS else f"{group} {n}"


# ---- values -----------------------------------------------------------------


def _number(value: float, sig: int = 3) -> str:
    """At most `sig` significant figures and two decimals, no trailing
    zeros: 40.19 -> `40.2`, 200.47 -> `200`, 0.99797 -> `1`, 12030.25 ->
    `12030`."""
    if value == 0:
        return "0"
    magnitude = len(str(int(abs(value)))) if abs(value) >= 1 else 0
    places = min(2, max(0, sig - magnitude))
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def format_value(value: object, unit: "str | None") -> "str | None":
    """A value as Detail shows it. None (the desk holds no such address
    yet) stays None, and the page draws it as a dash."""
    if value is None:
        return None
    if unit == _COLOUR:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            name = facts.COLOUR_NAMES.get(int(value))
            return f"{name} ({int(value)})" if name else f"color {int(value)}"
        return str(value)
    if unit == _BOOL and value in (0, 1, "0", "1"):
        return "on" if int(value) else "off"
    if isinstance(value, str):
        return value if value != "" else "(blank)"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if unit == _FADER:
        return "-∞ dB" if value <= -144 else f"{_number(value)} dB"
    if unit == _HZ:
        if abs(value) >= 1000:
            return f"{_number(round(value / 1000, 2), 4)} kHz"
        return f"{_number(value)} Hz"
    if unit in (_DB, _MS):
        return f"{_number(value)} {unit}"
    return _number(value)


# ---- one row ------------------------------------------------------------------


def _strip_leaf(kind: str, leaf: str, faces: dict) -> tuple[str, str, "str | None"]:
    if leaf in _STRIP_LEAVES:
        return _STRIP_LEAVES[leaf]
    m = _BAND_RE.match(leaf)
    if m:
        band = _BAND_WORDS.get(m.group(2), f"band {m.group(2)}")
        part, unit = _BAND_PART[m.group(3)]
        return ("Pre-EQ" if m.group(1) == "peq" else "EQ", f"{band} {part}", unit)
    m = _SEND_RE.match(leaf)
    if m:
        target = "bus" if kind in ("ch", "aux") else "mtx"
        n = int(m.group(1))
        name = (faces.get((target, n)) or {}).get("name")
        word = "bus" if target == "bus" else "matrix"
        heading = f"Send to {name} ({word} {n})" if name else f"Send to {word} {n}"
        label, unit = _SEND_LEAVES[m.group(2)]
        return (heading, label, unit)
    m = _MAIN_RE.match(leaf)
    if m:
        label = {"on": "routed directly" if kind in ("ch", "aux") else "routed",
                 "lvl": "level", "pre": "pre-fader"}[m.group(2)]
        unit = {"on": _BOOL, "lvl": _FADER, "pre": _BOOL}[m.group(2)]
        return (f"Main {int(m.group(1))}", label, unit)
    return ("Other", leaf.replace("/", " "), None)


def _section_rank(section: str) -> int:
    if section in SECTION_ORDER:
        return SECTION_ORDER.index(section)
    if section.startswith("Send to "):
        return 100
    if section.startswith("Main "):
        return 200
    return 300


def _note(record: dict, label_of) -> str:
    """Why a row is written, when that is not obvious."""
    description = str(record.get("description") or "")
    forced = record.get("forced_by")
    if record.get("status") in ("unreadable", "unreadable_skipped"):
        return "didn't answer"
    if forced and record.get("prior_value") is None:
        return f"not on the desk until {label_of(forced)} changes"
    if forced:
        return f"sent again: {label_of(forced)} changes"
    if record.get("mirrored_by"):
        return "set with the first socket of its stereo pair"
    if description.startswith("reset to initialized"):
        return "reset to the initialized desk"
    if "no bus or output in this plan is patched here" in description:
        return "disconnected: nothing in the plan is patched here"
    if "second socket" in description or "read as both sockets" in description:
        return "second socket of a stereo pair"
    return ""


def _owner(record: dict, faces: dict) -> "tuple[str, int] | None":
    """The strip a socket row is written for, from its description
    (`ch 1 (Kick): name on source A 1`; a main's is `output PA (LCL 1):
    source`, by the main's name), or None."""
    description = str(record.get("description") or "")
    m = _OWNER_STRIP_RE.match(description.split(":", 1)[0])
    if m:
        return (m.group(1), int(m.group(2)))
    m = _OWNER_OUTPUT_RE.match(description)
    if m:
        return next((k for k, f in sorted(faces.items())
                     if k[0] == "main" and f.get("name") == m.group(1)), None)
    return None


def _changes(record: dict) -> bool:
    return record.get("status") == "dry_run" and bool(record.get("would_change"))


# ---- the tiles ----------------------------------------------------------------


def detail(records: "list[dict] | None", faces: "dict | None" = None) -> dict:
    """`{tile key: tile}` for every tile a row of `records` lands in.

    `records` are the preview journal's rows as dicts (`address`,
    `description`, `status`, `prior_value`, `intended_value`,
    `would_change`, and `forced_by` / `mirrored_by` where set). `faces` is
    `desk_view.plan_faces(plan)`, for the names in headings.

    A tile is `{"rows": [...], "changes": n, "same": n, "presets": [...],
    "links": [...]}`; a row is `{"section", "label", "address", "now",
    "after", "changes", "note"}`, plus `"plan"` on a row that does not
    change but whose plan figure reads differently from the desk's, and
    `"owner"` on a socket row (the strip it is written for)."""
    faces = faces or {}
    records = list(records or [])

    def label_of(address: str) -> str:
        m = _STRIP_RE.match(address or "")
        if m and m.group(3):
            return _strip_leaf(m.group(1), m.group(3), faces)[1]
        return address.rsplit("/", 1)[-1]

    tiles: dict[str, dict] = {}
    for index, record in enumerate(records):
        address = str(record.get("address") or "")
        key = tile_of(address)
        section, label, unit, owner = _describe(address, record, faces)
        now = format_value(record.get("prior_value"), unit)
        after = format_value(record.get("intended_value"), unit)
        changes = _changes(record)
        row = {"section": section, "label": label, "address": address, "now": now,
               "after": after, "changes": changes, "note": _note(record, label_of),
               "_order": (_sort_key(key, section, address), index)}
        if not changes and after is not None and now is not None and after != now:
            row["plan"] = after
        if owner:
            row["owner"] = owner
        tile = tiles.setdefault(key, {"rows": [], "changes": 0, "same": 0, "presets": [],
                                      "links": []})
        tile["rows"].append(row)
        tile["changes" if changes else "same"] += 1
        m = _PRESET_RE.search(str(record.get("description") or ""))
        if m and m.group(1) not in tile["presets"]:
            tile["presets"].append(m.group(1))
    for tile in tiles.values():
        tile["rows"].sort(key=lambda r: r["_order"])
        for row in tile["rows"]:
            del row["_order"]
    _link(tiles, records, faces)
    return tiles


def _sort_key(key: str, section: str, address: str):
    if key.startswith(("in/", "out/")):
        m = _IO_RE.match(address)
        return (int(m.group(3)) if m else 0, 0)
    return (_section_rank(section), 0)


def _strip_owner_words(where: "tuple[str, int] | None", faces: dict) -> str:
    if where is None:
        return ""
    name = (faces.get(where) or {}).get("name")
    return f"{where[0]} {where[1]}" + (f" ({name})" if name else "")


def _describe(address: str, record: dict, faces: dict):
    """(section, label, unit, owner words) for one row."""
    m = _STRIP_RE.match(address)
    if m and m.group(3) is not None:
        section, label, unit = _strip_leaf(m.group(1), m.group(3), faces)
        return section, label, unit, ""
    m = _IO_RE.match(address)
    if m:
        group, n, leaf = m.group(2).upper(), int(m.group(3)), m.group(4) or ""
        label, unit = _SOCKET_LEAVES.get(leaf, (leaf.replace("/", " "), None))
        owner = _strip_owner_words(_owner(record, faces), faces)
        return socket_word(group, n), label, unit, owner
    m = _FX_RE.match(address)
    if m:
        leaf = m.group(2) or ""
        label, unit = _FX_LEAVES.get(leaf, (leaf.replace("/", " "), None))
        return "Effect", label, unit, ""
    leaf = address.lstrip("/")
    return "Console", _CONSOLE_LEAVES.get(leaf, leaf), None, ""


def _link(tiles: dict, records: list, faces: dict) -> None:
    """A strip's source and output sockets are their own tiles: give the
    strip a line for each socket group it is written to, with a jump.
    `Source AES50-A 1 has 3 changes`: the line names the socket group and
    counts what is written there, so the tile says where to look next."""
    found: dict[tuple, dict] = {}
    for record in records:
        address = str(record.get("address") or "")
        m = _IO_RE.match(address)
        if not m:
            continue
        where = _owner(record, faces)
        if where is None:
            continue
        direction, group, n = m.group(1), m.group(2).upper(), int(m.group(3))
        entry = found.setdefault((f"{where[0]}/{where[1]}", direction, group),
                                 {"sockets": [], "changes": 0})
        if n not in entry["sockets"]:
            entry["sockets"].append(n)
        entry["changes"] += 1 if _changes(record) else 0
    for (strip_key, direction, group), entry in sorted(
            found.items(), key=lambda kv: (kv[0][1] != "in", kv[0][2])):
        tile = tiles.get(strip_key)
        if tile is None:
            continue
        sockets = sorted(entry["sockets"])
        word = "Source" if direction == "in" else "Output"
        plural = len(sockets) > 1
        what = socket_word(group, ", ".join(str(n) for n in sockets))
        n = entry["changes"]
        verb = "have" if plural else "has"
        tail = (f"{verb} {n} change{'s' if n != 1 else ''}" if n
                else f"{verb} no changes")
        tile["links"].append({"key": f"{direction}/{group}",
                              "text": f"{word}{'s' if plural else ''} {what} {tail}"})


def banks(tiles: dict, faces: "dict | None" = None) -> list[dict]:
    """The four banks after Mute groups: Inputs and Outputs (one tile per
    socket group), FX (one per slot) and Console. A tile no row lands in
    is drawn as not in the plan."""
    faces = faces or {}

    def state(key: str) -> str:
        return "plan" if key in tiles else "unused"

    out: list[dict] = []
    for direction, title in (("in", "Inputs"), ("out", "Outputs")):
        groups = list(SOCKET_GROUPS)
        known = {code for code, _ in groups}
        extra = sorted({k.split("/", 1)[1] for k in tiles if k.startswith(direction + "/")}
                       - known)
        groups += [(code, _EXTRA_GROUP_NAMES.get(code, code)) for code in extra]
        strips = [{"n": code, "key": f"{direction}/{code}", "label": code, "name": name,
                   "colour": None, "state": state(f"{direction}/{code}")}
                  for code, name in groups]
        out.append({"kind": direction, "title": title, "count": len(strips),
                    "note": "one tile per socket group", "strips": strips})
    fx = []
    for n in range(1, facts.FX_SLOTS + 1):
        key = f"fx/{n}"
        model = next((r["after"] for r in (tiles.get(key) or {}).get("rows", [])
                      if r["address"].endswith("/mdl")), None)
        fx.append({"n": n, "key": key, "label": str(n), "name": model or f"FX {n}",
                   "colour": None, "state": state(key)})
    out.append({"kind": "fx", "title": "FX", "count": len(fx), "strips": fx})
    console = [{"n": "TB", "key": "cfg/talk", "label": "TB", "name": "Talkback",
                "colour": None, "state": state("cfg/talk")}]
    if "cfg/other" in tiles:
        console.append({"n": "…", "key": "cfg/other", "label": "…", "name": "Other",
                        "colour": None, "state": "plan"})
    out.append({"kind": "cfg", "title": "Console", "count": len(console),
                "note": "settings that belong to no strip", "strips": console})
    for bank in out:
        for strip in bank["strips"]:
            strip["changes"] = bool((tiles.get(strip["key"]) or {}).get("changes"))
    return out
