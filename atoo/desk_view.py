"""The desk drawn as scribble strips, for Apply's Preview.

Apply's second step draws the desk the way the WING draws it: one
scribble strip per channel, aux, bus, main, matrix, DCA and mute group,
each in its colour, with its name and its number. This module works out
what to draw, so the page only paints it (`apply.js`) and a test can read
it without a browser.

**How many of each** is `console_facts.CAPACITY` -- never a number written
here, so a desk whose counts differ draws its own size.

**Full build** (`full_build_desk`): the desk as the plan will leave it.
Names and colours are the plan's own `/{kind}/{n}/name` and `/col`
writes, taken from `apply._build_write_targets` -- the same targets a
write sends, so the drawing cannot name a strip differently from the
write. A strip the plan writes no name or colour to is drawn dimmed, as
"not in the plan" (a full build resets it to initialized). The preview's
journal says which strips the write would change.

A full build's drawing also carries every row of the
preview in the tile it belongs to (`preview_detail`), with four more banks
after Mute groups (Inputs, Outputs, FX, Console), for Apply's Detail.

**Patch** (`patch_desk`): the desk as it is, read -- the occupancy read's
names and verdicts (`amend.strip_occupancy`) plus one colour per strip and
a name and colour per bus, main, matrix and DCA (`face_read_plan`, read by
`read_faces`) -- with what the change adds, edits and returns to free
marked on it, from the amendment's own scopes. An unread strip stays
UNKNOWN and is never drawn as free: the rule `amend.js` has always kept.

Icons are not drawn: a plan stores only the WING's icon number, and the
artwork is Behringer's (out of scope).
"""

from __future__ import annotations

import re

from atoo import console_facts as facts

#: The desk's sections, in the order the WING lists them, with the title
#: the page gives each.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("ch", "Channels"), ("aux", "Aux"), ("bus", "Buses"), ("main", "Mains"),
    ("mtx", "Matrices"), ("dca", "DCAs"), ("mgrp", "Mute groups"),
)

#: What `face_read_plan` asks of each kind. Channels and auxes need only a
#: colour: the occupancy read already reads their names (and their source
#: sockets' names). A mute group has a name and no colour on a WING.
FACE_FIELDS: dict[str, tuple[str, ...]] = {
    "ch": ("col",), "aux": ("col",), "bus": ("name", "col"), "main": ("name", "col"),
    "mtx": ("name", "col"), "dca": ("name", "col"), "mgrp": ("name",),
}

_STRIP_RE = re.compile(r"^/(ch|aux|bus|main|mtx|dca|mgrp)/(\d+)(?:/|$)")
_FACE_RE = re.compile(r"^/(ch|aux|bus|main|mtx|dca|mgrp)/(\d+)/(name|col)$")
# The desk's own label for an object nobody has named.
_FACTORY_NAME_RE = re.compile(r"^(CH|AUX|BUS|MAIN|MTX|MX|DCA|MGRP|MG)[\s.]*0*\d+$", re.IGNORECASE)


def strip_of(address: str) -> "tuple[str, int] | None":
    """`/ch/12/eq/1g` -> `("ch", 12)`; None for anything that is not on a
    strip the drawing has (a socket, an FX slot, a number past the desk)."""
    m = _STRIP_RE.match(address or "")
    if not m:
        return None
    kind, n = m.group(1), int(m.group(2))
    return (kind, n) if 1 <= n <= facts.CAPACITY[kind] else None


def face_read_plan() -> list[tuple[str, str]]:
    """The addresses Patch's preview reads for the drawing beyond the
    occupancy read, with the OSC type each is read as: 144 on a WING."""
    plan: list[tuple[str, str]] = []
    for kind, _title in SECTIONS:
        for n in range(1, facts.CAPACITY[kind] + 1):
            for field in FACE_FIELDS[kind]:
                plan.append((f"/{kind}/{n}/{field}", "s" if field == "name" else "i"))
    return plan


def read_addresses(console, pairs, *, progress=None) -> dict[str, object]:
    """Read `(address, OSC type)` pairs over a connected console, windowed as
    the occupancy read is (`console.read_in_windows`). An address that does
    not answer is absent -- never a default."""
    from atoo import console as osc

    pairs = list(pairs)
    values: dict[str, object] = {}

    def on_start(address: str) -> None:
        if progress is not None:
            progress.start_address(address)

    replies = osc.read_in_windows(console, [a for a, _ in pairs], on_start=on_start)
    for (address, value_type), (_address, reply) in zip(pairs, replies):
        if progress is not None:
            progress.finish_address(answered=reply is not None)
        if reply is None:
            continue
        value, error = reply.value(value_type)
        if error is None:
            values[address] = facts.correct_readback_index(address, value)
    return values


def read_faces(console, *, progress=None) -> dict[str, object]:
    """Read `face_read_plan` over a connected console. An address that does
    not answer is absent -- never a default."""
    return read_addresses(console, face_read_plan(), progress=progress)


def colour_name(index: object) -> "str | None":
    """The desk's own name for a colour index, or None."""
    if isinstance(index, bool) or not isinstance(index, (int, float)):
        return None
    return facts.COLOUR_NAMES.get(int(index))


def plan_faces(plan: "dict | None") -> dict[tuple[str, int], dict]:
    """`{(kind, n): {"name": ..., "colour": ...}}` for every strip the plan
    writes a name or a colour to, from the write targets themselves."""
    from atoo import apply as apply_module

    if not isinstance(plan, dict):
        return {}
    try:
        targets, _warnings = apply_module._build_write_targets(plan, True)
    except Exception:  # a plan apply cannot target draws as nothing in it
        return {}
    faces: dict[tuple[str, int], dict] = {}
    for target in targets:
        m = _FACE_RE.match(target.address)
        if not m:
            continue
        key = (m.group(1), int(m.group(2)))
        if key[1] > facts.CAPACITY[key[0]]:
            continue
        try:
            value = target.compute_value(None)
        except Exception:
            continue
        face = faces.setdefault(key, {"name": None, "colour": None})
        if m.group(3) == "name":
            face["name"] = value if isinstance(value, str) else None
        else:
            face["colour"] = colour_name(value)
    return faces


def _section(kind: str, title: str, strip) -> dict:
    count = facts.CAPACITY[kind]
    return {"kind": kind, "title": title, "count": count,
            "strips": [dict(strip(kind, n), n=n) for n in range(1, count + 1)]}


def full_build_desk(plan: "dict | None", records: "list[dict] | None" = None) -> dict:
    """The desk as a full build of `plan` leaves it. `records` are the
    preview journal's rows; a tile with any row that would change is
    marked `changes`.

    The drawing also carries every row of the preview in
    the tile it belongs to (`tiles`, from `preview_detail`), and four more
    banks after Mute groups: Inputs and Outputs, one tile per socket group,
    FX and Console. Every strip carries the `key` of its tile (`ch/1`,
    `in/A`) and the `label` its corner shows."""
    from atoo import preview_detail

    faces = plan_faces(plan)
    tiles = preview_detail.detail(records, faces)

    def strip(kind: str, n: int) -> dict:
        key = f"{kind}/{n}"
        face = faces.get((kind, n))
        out = {"key": key, "label": str(n),
               "changes": bool((tiles.get(key) or {}).get("changes"))}
        if face is None:
            return dict(out, state="unused", name=None, colour=None)
        return dict(out, state="plan", name=face["name"], colour=face["colour"])

    sections = [_section(kind, title, strip) for kind, title in SECTIONS]
    sections += preview_detail.banks(tiles, faces)
    return {"mode": "full", "sections": sections, "tiles": tiles,
            "counts": {"in_plan": len(faces),
                       "changing": sum(1 for t in tiles.values() if t["changes"])}}


def _desk_name(value: object) -> "str | None":
    if not isinstance(value, str) or not value.strip():
        return None
    return None if _FACTORY_NAME_RE.match(value.strip()) else value


def patch_desk(occupancy: list, faces: dict[str, object], amendment=None) -> dict:
    """The desk as the occupancy read and `faces` found it, with what
    `amendment` (an `amend.Amendment`, or None) adds, edits and frees."""
    by_strip = {(s.bank, s.number): s for s in occupancy or []}
    new: set[tuple[str, int]] = set()
    edited: set[tuple[str, int]] = set()
    released: set[tuple[str, int]] = set()
    moved: set[tuple[str, int]] = set()
    after: dict[tuple[str, int], dict] = {}
    if amendment is not None:
        for base in amendment.scope.grants:
            m = _STRIP_RE.match(base)
            if m and base == f"/{m.group(1)}/{m.group(2)}":
                where = strip_of(base)
                if where is not None:
                    new.add(where)
        # An insert: the channel put in is new, and every strip a running
        # channel moved onto is rewritten whole -- drawn as moved.
        for label in amendment.strips:
            bank, _, number = str(label).partition(":")
            if number.isdigit():
                new.add((bank, int(number)))
        for base in amendment.shift_scope.grants:
            where = strip_of(base)
            if where is not None and where not in new:
                moved.add(where)
        for address in list(amendment.edit_scope.grants):
            where = strip_of(address)
            if where is not None and where not in new:
                edited.add(where)
        for label in amendment.released or []:
            bank, _, number = str(label).partition(":")
            if number.isdigit():
                released.add((bank, int(number)))
        after = plan_faces(amendment.effective_plan)

    def strip(kind: str, n: int) -> dict:
        base = f"/{kind}/{n}"
        status = by_strip.get((kind, n))
        colour = colour_name(faces.get(f"{base}/col"))
        if status is not None:
            state = {"ours": "used", "theirs": "used", "free": "free",
                     "unknown": "unknown"}.get(str(status.state.value), "unknown")
            name = _desk_name(status.name)
            source = None if name else _desk_name(status.source_name)
            out = {"state": state, "name": name or source, "source_name": bool(source),
                   "colour": colour, "owner": str(status.state.value)}
        else:
            name_field = f"{base}/name"
            # A channel or aux the occupancy read has no verdict for (it read
            # fewer strips than the desk has) is unread, never free; so is a
            # group whose name never answered.
            occupancy_kind = kind in ("ch", "aux")
            asked = "name" in FACE_FIELDS[kind]
            if occupancy_kind or (asked and name_field not in faces):
                out = {"state": "unknown", "name": None, "colour": colour}
            else:
                name = _desk_name(faces.get(name_field))
                out = {"state": "used" if name else "free", "name": name, "colour": colour}
        if (kind, n) in released:
            out["mark"] = "released"
        elif (kind, n) in new:
            out["mark"] = "new"
        elif (kind, n) in moved:
            out["mark"] = "moved"
        elif (kind, n) in edited:
            out["mark"] = "edit"
        if out.get("mark") in ("new", "edit", "moved") and (kind, n) in after:
            face = after[(kind, n)]
            if face.get("name"):
                out["name"] = face["name"]
                out["source_name"] = False
            if face.get("colour"):
                out["colour"] = face["colour"]
        return out

    sections = [_section(kind, title, strip) for kind, title in SECTIONS]
    flat = [s for section in sections for s in section["strips"]]
    return {"mode": "patch", "sections": sections,
            "counts": {"strips": len(flat),
                       "in_use": sum(1 for s in flat if s["state"] == "used"),
                       "free": sum(1 for s in flat if s["state"] == "free"),
                       "unknown": sum(1 for s in flat if s["state"] == "unknown"),
                       "new": len(new), "edit": len(edited), "moved": len(moved),
                       "released": len(released)}}
