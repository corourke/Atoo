"""Capture a desk you didn't build: a reading becomes a show bundle.

*"there is no way I'm going to build a plan for this
existing patch ... I would like to document it, however, and also watch
it."* `atoo capture` reads a live console or a `.snap` and writes what a
show bundle holds, with **no model and nothing written to the desk**:

    <show>/
      input.csv            one row per input in use, names written in
      busses.csv           one row per bus, Main and Matrix in use
      plan.json            the desk as it is: patch, routing, membership,
                           widths -- structure, not the mix
      watch.json           empty, ready for watch conditions
      captures/<date>.snap the snapshot it was made from (a live capture
                           saves its reading as <date>.state.json)

Pieces 1 and 2 of the desk sheets. Every send goes in the
plan on its source, as the desk keeps it: a channel's `bus_sends` and
`matrix_sends`, a bus's `bus_sends` and `matrix_sends`, a Main's
`matrix_sends`, each with its tap. Every effect a strip inserts goes in the
plan on that strip as `inserts`: the model, the engine it is
in and the engine's parameters, so Apply loads it back. What the plan still
cannot hold (a GRP-mode tap) is said at INFO and kept in the sheets and the
snapshot, never dropped silently.

**What a capture decides, and says.** An inferred value is not
a defect; one that does not announce itself is. Every value the desk does
not state is decided and listed in `Capture.notes`, which `atoo capture`
prints and the plan carries as `notes`:

* a strip with no name of its own takes its source's name;
* `category` is the channel's first DCA's name, or `other`;
* `type` is `Line` for a digital or playback source, `Mic` otherwise;
* a bus whose every inserted effect is a reverb, delay, modulation or
  pitch effect (`console_facts.EFFECT_SEND_MODELS`) set fully
  wet takes the role `fx`; every other role is the engineer's to fill;
* a name the input list cannot repeat (two "Acoustic" channels) carries
  its channel in the input row's name; the desk's name stays in the plan.

**What it leaves out, on purpose:** faders, mutes, send levels, EQ and
dynamics. They are the mix, and Atoo never mixes. Writing them would make
Watch report every fader move during a service as a contradiction.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from atoo import console_facts, fx_engines, outputs_sheet, user_sheet
from atoo.audit import (
    ConsoleState,
    bus_indices,
    dca_indices,
    effective_name,
    input_pair_sockets,
    is_in_use,
    main_indices,
    matrix_indices,
    mute_group_indices,
    output_source_object,
    output_sockets,
    position_label,
    strip_bases,
)
from atoo.input_list import format_socket

#: The input list's columns as a capture writes them: the existing format
#: (`input_list.CANONICAL_COLUMNS`, less `order` and `preset`, which a
#: desk does not state) plus the sheet's three new optional columns.
INPUT_COLUMNS = ("channel", "patch", "name", "category", "type", "model", "phantom",
                 "dca", "mute_group", "notes")
#: `busses.csv`, in the spec's order (section 1).
BUS_COLUMNS = ("bus", "name", "role", "width", "sources", "tap", "outputs", "fx", "preset",
               "dca", "mute_group", "label", "notes")

#: Sources a capture types `Line`: a Dante or SoundGrid module, USB, a card,
#: the USB-stick player and AES/EBU carry line or digital signals, never a
#: microphone on a head amp. Everything else (local, AES50, StageConnect,
#: the aux jacks) is `Mic`, the type that keeps the head amp's gain. A
#: judgement, said at INFO.
LINE_GROUPS = frozenset({"MOD", "USB", "CRD", "PLAY", "AES"})
#: Input groups that are not a socket a person cables: the internal
#: oscillator. A strip on it is left out of the sheets, at INFO.
NOT_A_SOCKET = frozenset({"OSC"})

_DCA_TAG = re.compile(r"^#D(\d+)$")
_MUTE_GROUP_TAG = re.compile(r"^#M(\d+)$")
_SEND_MODE = {"PRE": "pre", "POST": "post"}
#: An insert's wet/dry leaf on an FX slot; read when it is in the reading.
FX_MIX = "/fx/{n}/fxmix"


@dataclass
class Capture:
    """One desk, as the two sheets and a plan. `notes` is every INFO line
    the capture made, in the order it made them."""

    input_rows: list[dict[str, str]]
    bus_rows: list[dict[str, str]]
    plan: dict
    notes: list[str] = field(default_factory=list)
    #: A live capture's follow-up read of the inserted engines' parameters: `(engines, requests)`; None for a `.snap`, which holds them.
    effect_reads: "tuple[int, int] | None" = None

    def input_csv(self) -> str:
        return _csv(INPUT_COLUMNS, self.input_rows)

    def busses_csv(self) -> str:
        return _csv(BUS_COLUMNS, self.bus_rows)

    def outputs_csv(self) -> str:
        return outputs_sheet.csv_text(outputs_sheet.rows_from_plan(self.plan))

    def user_csv(self) -> str:
        return user_sheet.csv_text(user_sheet.rows_from_plan(self.plan))


def _csv(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return out.getvalue()


def _user_sources(state: ConsoleState) -> list[dict]:
    """Every USR slot the desk has assigned (`user/grp` not OFF), as the plan's
    `user_sources`: what it takes, and on a user signal its tap
    and leg; its name when it has one."""
    found = []
    for slot in range(1, console_facts.INPUT_SOCKETS["USR"] + 1):
        base = f"/io/in/USR/{slot}"
        group = state.text(f"{base}/user/grp")
        index = state.number(f"{base}/user/in")
        if not group or group == console_facts.USER_SLOT_UNASSIGNED or index is None:
            continue
        entry: dict = {"slot": slot, "source": {"group": group, "index": int(index)}}
        if console_facts.user_slot_kind(slot) == console_facts.USER_SIGNAL:
            tap, leg = state.text(f"{base}/user/tap"), state.text(f"{base}/user/lr")
            if tap in console_facts.USER_SIGNAL_TAPS:
                entry["tap"] = tap
            if leg in console_facts.USER_SIGNAL_LEGS:
                entry["leg"] = leg
        name = (state.text(f"{base}/name") or "").strip()
        if name:
            entry["name"] = name
        found.append(entry)
    return found


def _names(items: list[str]) -> str:
    """`a, b and c`."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _inserts(state: ConsoleState, base: str) -> list[tuple[str, int, str]]:
    """`(point, slot, model)` for each insert switched on that names a
    loaded slot."""
    found = []
    for point, slot, on in state.inserts(base):
        model = state.fx_model(slot) if slot is not None else None
        if on and model and model != console_facts.FX_EMPTY:
            found.append((point, slot, model))
    return found


def _tag_members(state: ConsoleState, base: str, rx: re.Pattern) -> list[int]:
    return [int(m.group(1)) for token in state.tags(base).split(",")
            if (m := rx.match(token.strip()))]


def _socket_runs(sockets: list[tuple[str, int]]) -> str:
    """`[("LCL", 7), ("LCL", 8), ("MOD", 44)]` -> `LCL 7-8; MOD 44`."""
    runs: list[list] = []
    for group, n in sorted(sockets, key=lambda s: (s[0], s[1])):
        if runs and runs[-1][0] == group and runs[-1][2] == n - 1:
            runs[-1][2] = n
        else:
            runs.append([group, n, n])
    return "; ".join(f"{format_socket(g, a)}" if a == b else f"{format_socket(g, a)}-{b}"
                     for g, a, b in runs)


class _Desk:
    """The reading, with the lookups every part of a capture shares."""

    def __init__(self, state: ConsoleState):
        self.state = state
        self.dca_names = {i: (state.name(f"/dca/{i}") or "").strip() or f"DCA {i}"
                          for i in dca_indices(state)}
        self.mute_group_names = {i: (state.name(f"/mgrp/{i}") or "").strip() or f"MGRP {i}"
                                 for i in mute_group_indices(state)}
        # (kind, index) -> [(group, socket, side)], side L for an odd slot.
        self.outputs: dict[tuple[str, int], list[tuple[str, int, str]]] = {}
        self.direct_outputs: list[tuple[str, int]] = []
        for group, socket in output_sockets(state):
            raw = state.output_source(group, socket)
            if raw is None:
                continue
            kind, slot = raw
            if kind in ("BUS", "MAIN", "MTX"):
                obj = output_source_object(state, group, socket)
                self.outputs.setdefault(obj, []).append(
                    (group, socket, "L" if slot % 2 else "R"))
            else:
                self.direct_outputs.append((group, socket))
        # An object's R on a socket that does not follow its L: a patch can
        # only say L, or L then R (`apply._output_slot`), so the plan records
        # it as the socket's own source, with the object's slot.
        self.lone_sides: list[tuple[str, int, tuple[str, int]]] = []
        for obj, sockets in self.outputs.items():
            for group, socket, side in list(sockets):
                if side == "R" and (group, socket - 1, "L") not in sockets:
                    sockets.remove((group, socket, side))
                    self.direct_outputs.append((group, socket))
                    self.lone_sides.append((group, socket, obj))

    def flag(self, address: str) -> bool:
        return bool(self.state.flag(address))

    def dcas(self, base: str) -> list[str]:
        return [self.dca_names.get(i, f"DCA {i}") for i in _tag_members(self.state, base, _DCA_TAG)]

    def mute_groups(self, base: str) -> list[str]:
        return [self.mute_group_names.get(i, f"MGRP {i}")
                for i in _tag_members(self.state, base, _MUTE_GROUP_TAG)]

    def inserts(self, base: str) -> list[tuple[str, int, str]]:
        return _inserts(self.state, base)

    def insert_entries(self, base: str, unread: "set[int]") -> list[dict]:
        """The plan's `inserts` for a strip: each insert
        `inserts` finds, with its engine's parameters as the reading holds
        them -- every one from a `.snap`, those `read_effect_parameters`
        added from a live desk, and none for an engine in `unread`."""
        out = []
        for point, slot, model in self.inserts(base):
            prefix = f"/fx/{slot}/"
            parameters = {} if slot in unread else {
                address[len(prefix):]: value for address, value in self.state.values.items()
                if address.startswith(prefix) and "/" not in address[len(prefix):]
                and fx_engines.is_engine_parameter(address[len(prefix):])}
            out.append({"point": point, "model": model, "engine": slot,
                        "parameters": dict(sorted(parameters.items()))})
        return out

    def output_sockets_of(self, kind: str, index: int) -> list[tuple[str, int, str]]:
        return sorted(self.outputs.get((kind, index), []))


def _plan_patches(sockets: list[tuple[str, int, str]]) -> list[dict]:
    """An object's output sockets as a plan's `patches`: an L socket and the
    R socket after it in the same group are one stereo patch, anything else
    a patch of its own."""
    patches: list[dict] = []
    pending = sorted(sockets)
    used: set[tuple[str, int]] = set()
    for group, n, side in pending:
        if (group, n) in used:
            continue
        used.add((group, n))
        if side == "L" and (group, n + 1, "R") in pending:
            used.add((group, n + 1))
            patches.append({"group": group, "sockets": [n, n + 1], "stated": True})
        else:
            patches.append({"group": group, "sockets": [n], "stated": True})
    return patches


def capture_desk(state: ConsoleState, *, console_model: str | None, made_from: str,
                 captured: str, snapshot: str | None = None,
                 unread_effects: "set[int] | None" = None) -> Capture:
    """The sheets and the plan for the desk `state` reads.

    `made_from` is `desk` or `snap`, `captured` the date (ISO), and
    `snapshot` the bundle-relative path of the evidence it was made from;
    all three go into the plan's `meta`. `unread_effects` is the FX engines
    whose parameters a live read could not get: their inserts keep the
    model only, and a note says so."""
    desk = _Desk(state)
    unread = set(unread_effects or ())

    def with_inserts(entry: dict, base: str) -> dict:
        found = desk.insert_entries(base, unread)
        if found:
            entry["inserts"] = found
        return entry

    def colour(address: str) -> "int | None":
        """The desk's colour index (1-18) at `address`, None when unread."""
        value = state.number(address)
        if value is None or not 1 <= value <= 18:
            return None
        return int(value)

    # The colour of each input socket the plan names: a strip linked to its
    # source shows the socket's colour, and an Outputs row its source's. The
    # page reads it; Apply writes a channel's own colour, never this.
    socket_colours: dict[str, int] = {}

    def note_socket_colour(group: str, n: int) -> None:
        if group in console_facts.INPUT_SOCKETS:
            found = colour(f"/io/in/{group}/{n}/col")
            if found is not None:
                socket_colours[format_socket(group, n)] = found
    notes: list[str] = []
    no_name: list[str] = []
    categorised: dict[str, list[str]] = {}
    typed_line: list[str] = []
    skipped: list[str] = []

    # -- inputs ---------------------------------------------------------------
    input_rows: list[dict[str, str]] = []
    channels: list[dict] = []
    channel_ref: dict[str, str] = {}      # strip base -> the name sources quote
    first_row: dict[str, str] = {}
    row_names: set[str] = set()
    renamed: list[str] = []

    def unique(name: str, base: str) -> str:
        if name not in row_names:
            row_names.add(name)
            return name
        label = position_label(base)
        renamed.append(f"{label} ('{name}')")
        name = f"{name} ({label})"
        row_names.add(name)
        return name

    for base in strip_bases(state):
        if not is_in_use(state, base):
            continue
        bank, number = base.split("/")[1], int(base.split("/")[2])
        label = position_label(base)
        patch = state.patch(base)
        if patch is None:
            skipped.append(f"{label} has no source (OFF)")
            continue
        group, socket = patch
        if group in NOT_A_SOCKET or group not in console_facts.INPUT_SOCKETS:
            skipped.append(f"{label} takes {format_socket(group, socket)}, which is not a "
                           f"socket a sheet describes")
            continue
        # A WING pairs an odd socket with the next one; a strip on an even
        # socket hears that socket alone, whatever its mode says.
        sockets = input_pair_sockets(state, group, socket)
        stereo = len(sockets) == 2
        socket_names = [(state.text(f"/io/in/{group}/{n}/name") or "").strip() for n in sockets]

        name = (effective_name(state, base) or "").strip()
        own = (state.name(base) or "").strip()
        # Where the desk holds the name it shows (`name_on`): apply writes it
        # there and nowhere else, so the capture applied back changes nothing.
        name_on = "strip" if own and name == own else "socket"
        if not name:
            name = socket_names[0]
        if name and not own:
            no_name.append(f"{label} takes '{name}' from {format_socket(group, socket)}")
        if not name:
            name, name_on = label, "none"
            no_name.append(f"{label} and its source {format_socket(group, socket)} have no "
                           f"name, so it is called '{label}'")
        name = name[:console_facts.NAME_MAX_CHARS]

        dcas, mute_groups = desk.dcas(base), desk.mute_groups(base)
        category = dcas[0] if dcas else "other"
        categorised.setdefault(category, []).append(label)
        type_ = "Line" if group in LINE_GROUPS else "Mic"
        if type_ == "Line":
            typed_line.append(label)
        phantom = any(state.input_phantom(group, n) for n in sockets)

        if stereo:
            left, right = socket_names
            if left and right and left != right:
                row_pair = [left, right]
            else:
                row_pair = [f"{name} L", f"{name} R"]
        else:
            row_pair = [name]
        row_pair = [unique(n, base) for n in row_pair]
        channel_ref[base], first_row[base] = name, row_pair[0]

        fx = desk.inserts(base)
        fx_note = ""
        if fx:
            fx_note = "Inserts: " + "; ".join(f"{model} (FX{slot}, {point})"
                                              for point, slot, model in fx)
        channel_cell = str(number) if bank == "ch" else f"Aux {number}"
        for row_name, n in zip(row_pair, sockets):
            input_rows.append({
                "channel": channel_cell, "patch": format_socket(group, n), "name": row_name,
                "category": category, "type": type_, "model": "",
                "phantom": "TRUE" if phantom else "FALSE",
                "dca": ";".join(dcas), "mute_group": ";".join(mute_groups), "notes": fx_note,
            })

        source = {"input": row_pair[0], "type": type_, "model": None, "stereo": stereo,
                  "phantom": phantom}
        if stereo:
            source["pair_input"] = row_pair[1]
        for n in sockets:
            note_socket_colour(group, n)
        # A strip linked to its source shows the socket's colour (above), not
        # its own, which the desk keeps at the default; it gets no `col`, so
        # Apply writes nothing over either. Any other strip's is its own.
        linked = name_on == "socket" or bool(state.flag(f"{base}/clink"))
        channels.append(with_inserts({
            "channel": number, "bank": bank, "name": name, "source": source,
            "col": None if linked else colour(f"{base}/col"),
            "patch": {"group": group, "sockets": sockets, "stated": True},
            "processing": {"hpf_hz": None, "preset": None},
            "fader": {"fader_db": None, "muted": None},
            "dca": dcas, "mute_group": mute_groups,
            "bus_sends": [], "main_routes": [],
            "name_on": name_on,
            "provenance": {"channel": f"captured from the desk ({label})"},
        }, base))

    # A busses.csv source names a channel by its name, which must say which
    # channel: where the desk repeats a name, it is the channel's first
    # input row's (unique) name instead.
    repeats = {n for n in channel_ref.values() if list(channel_ref.values()).count(n) > 1}
    for base, name in channel_ref.items():
        if name in repeats:
            channel_ref[base] = first_row[base]

    # -- buses, Mains and Matrices: their plan keys ---------------------------
    def key_for(kind: str, index: int, word: str) -> str:
        own = (state.name(f"/{kind}/{index}") or "").strip()
        return own or f"{word} {index}"

    bus_key = {i: key_for("bus", i, "Bus") for i in bus_indices(state)}
    main_key = {i: key_for("main", i, "Main") for i in main_indices(state)}
    mtx_key = {i: key_for("mtx", i, "Matrix") for i in matrix_indices(state)}
    seen: dict[str, int] = {}
    for table, word in ((bus_key, "Bus"), (main_key, "Main"), (mtx_key, "Matrix")):
        for i, key in table.items():
            seen[key] = seen.get(key, 0) + 1
    for table, word in ((bus_key, "Bus"), (main_key, "Main"), (mtx_key, "Matrix")):
        for i, key in list(table.items()):
            if seen[key] > 1:
                table[i] = f"{key} ({word} {i})"

    strip_in_plan = {f"/{c['bank']}/{c['channel']}": c for c in channels}

    def tap(mode_value, pre_flag) -> str | None:
        if mode_value is not None:
            return _SEND_MODE.get(str(mode_value).upper())
        return "pre" if pre_flag else "post"

    grp_sends: list[str] = []
    # The buses the sheets hold, decided before any sources cell is written,
    # so a cell names only a bus that has a row: a factory WING
    # routes its unused buses to Main 1.
    kept_buses: "set[int] | None" = None

    def sources_into(target: str) -> list[tuple[str, str | None, str]]:
        """`(source name, tap, source kind)` for everything switched on
        into `target` (`bus:3`, `main:1`, `mtx:6`)."""
        kind, idx = target.split(":")
        idx = int(idx)
        found: list[tuple[str, str | None, str]] = []
        for base, ref in channel_ref.items():
            if kind == "bus":
                on, mode, pre = (f"{base}/send/{idx}/on", f"{base}/send/{idx}/mode", None)
            elif kind == "mtx":
                on, mode, pre = (f"{base}/send/MX{idx}/on", f"{base}/send/MX{idx}/mode", None)
            else:
                on, mode, pre = (f"{base}/main/{idx}/on", None, f"{base}/main/{idx}/pre")
            if desk.flag(on):
                value = state.text(mode) if mode else None
                if value is not None and value.upper() == "GRP":
                    grp_sends.append(f"{position_label(base)} to {target.replace(':', ' ')}")
                found.append((ref, tap(value, desk.flag(pre) if pre else False), "channel"))
        for i, key in bus_key.items():
            if kind == "bus" and i == idx:
                continue
            if kept_buses is not None and i not in kept_buses:
                continue
            leaf = {"bus": f"/bus/{i}/send/{idx}", "mtx": f"/bus/{i}/send/MX{idx}",
                    "main": f"/bus/{i}/main/{idx}"}[kind]
            if desk.flag(f"{leaf}/on"):
                found.append((key, tap(None, desk.flag(f"{leaf}/pre")), "bus"))
        if kind == "mtx":
            for i, key in main_key.items():
                leaf = f"/main/{i}/send/MX{idx}"
                if desk.flag(f"{leaf}/on"):
                    found.append((key, tap(None, desk.flag(f"{leaf}/pre")), "main"))
        return found

    def sources_cells(found) -> tuple[str, str]:
        taps = [t for _n, t, _k in found if t]
        common = max(set(taps), key=taps.count) if taps else ""
        cells = [name if (t is None or t == common) else f"{name} ({t})"
                 for name, t, _k in found]
        return ";".join(cells), common

    def width(kind: str, idx: int) -> str:
        mono = state.flag(f"/{kind}/{idx}/busmono")
        return "" if mono is None else ("mono" if mono else "stereo")

    bus_rows: list[dict[str, str]] = []
    busses: dict[str, dict] = {}
    outputs: dict[str, dict] = {}
    roles_fx: list[str] = []

    # -- buses ------------------------------------------------------------------
    # A bus is kept when it is in use, patched, or fed by a channel, a Main or
    # a kept bus; one fed only by buses that are not kept is not.
    def fed_by_kept(i: int) -> bool:
        return any(kind != "bus" or name in {bus_key[j] for j in kept_buses}
                   for name, _t, kind in sources_into(f"bus:{i}"))

    kept_buses = {i for i in bus_key
                  if is_in_use(state, f"/bus/{i}") or desk.output_sockets_of("BUS", i)}
    grown = True
    while grown:
        grown = False
        for i in bus_key:
            if i not in kept_buses and fed_by_kept(i):
                kept_buses.add(i)
                grown = True
    grp_sends.clear()
    unused_routed = [f"Bus {i}" for i in bus_key if i not in kept_buses
                     and any(desk.flag(f"/bus/{i}/main/{m}/on") for m in main_key)]

    for i, key in bus_key.items():
        base = f"/bus/{i}"
        if i not in kept_buses:
            continue
        found = sources_into(f"bus:{i}")
        mains_on = [m for m in main_key if desk.flag(f"{base}/main/{m}/on")]
        out = desk.output_sockets_of("BUS", i)
        sources, common = sources_cells(found)
        fx = desk.inserts(base)
        role = ""
        if fx and all(model in console_facts.EFFECT_SEND_MODELS for _p, _s, model in fx):
            mixes = [state.number(FX_MIX.replace("{n}", str(slot))) for _p, slot, _m in fx]
            if all(mix is None or mix >= 100 for mix in mixes):
                role = "fx"
                wet = ("100% wet" if all(mix is not None for mix in mixes)
                       else "how wet was not read")
                roles_fx.append(f"{position_label(base)} '{key}': "
                                f"{_names([m for _p, _s, m in fx])} inserted, {wet}")
        desk_name = (state.name(base) or "").strip()
        bus_rows.append({
            "bus": f"Bus {i}", "name": desk_name, "role": role, "width": width("bus", i),
            "sources": sources, "tap": common if found else "",
            "outputs": _socket_runs([(g, n) for g, n, _s in out]),
            "fx": "; ".join(m for _p, _s, m in fx),
            "dca": ";".join(desk.dcas(base)), "mute_group": ";".join(desk.mute_groups(base)),
        })
        destinations = [{"type": "main", "index": m} for m in mains_on]
        if out:
            patches = _plan_patches(out)
            destinations.append({"type": "dedicated_output", "label": key,
                                 "patch": patches[0], "patches": patches})
        busses[key] = with_inserts({
            "index": i, "destination": destinations[0] if destinations else None,
            "destinations": destinations,
            "mono": state.flag(f"{base}/busmono"),
            "col": colour(f"{base}/col"),
            "fader": {"fader_db": None, "muted": None},
            "dca": desk.dcas(base), "mute_group": desk.mute_groups(base),
            "preset": None, "description": None, "role": role or None,
            "name_on": "strip" if desk_name else "none",
            "provenance": f"captured from the desk (Bus {i})",
        }, base)
        for base_ch, ch in strip_in_plan.items():
            if desk.flag(f"{base_ch}/send/{i}/on"):
                value = state.text(f"{base_ch}/send/{i}/mode")
                ch["bus_sends"].append({"bus": key, "mode": tap(value, False),
                                        "level_db": None})

    # -- Mains ------------------------------------------------------------------
    for m, key in main_key.items():
        base = f"/main/{m}"
        found = sources_into(f"main:{m}")
        out = desk.output_sockets_of("MAIN", m)
        feeds = [x for x in mtx_key if desk.flag(f"{base}/send/MX{x}/on")]
        if not (found or out or feeds):
            continue
        sources, common = sources_cells(found)
        bus_rows.append({
            "bus": f"Main {m}", "name": (state.name(base) or "").strip(), "width": width("main", m),
            "sources": sources, "tap": common if found else "",
            "outputs": _socket_runs([(g, n) for g, n, _s in out]),
            "fx": "; ".join(model for _p, _s, model in desk.inserts(base)),
            "dca": ";".join(desk.dcas(base)), "mute_group": ";".join(desk.mute_groups(base)),
        })
        patches = _plan_patches(out)
        outputs[key] = with_inserts({"kind": "main", "index": m,
                                     "patch": patches[0] if patches else None,
                        "name_on": "strip" if (state.name(base) or "").strip() else "none",
                        "patches": patches, "fader": {"fader_db": None, "muted": None},
                        "mono": state.flag(f"{base}/busmono"), "col": colour(f"{base}/col"),
                        "dca": desk.dcas(base), "mute_group": desk.mute_groups(base),
                        "description": None, "provenance": f"captured from the desk (Main {m})"},
                                    base)
        for base_ch, ch in strip_in_plan.items():
            if desk.flag(f"{base_ch}/main/{m}/on"):
                ch["main_routes"].append({"index": m})

    # -- Matrices ---------------------------------------------------------------
    for x, key in mtx_key.items():
        base = f"/mtx/{x}"
        found = sources_into(f"mtx:{x}")
        out = desk.output_sockets_of("MTX", x)
        named = bool((state.name(base) or "").strip())
        if not (found or out):
            if named:
                skipped.append(f"MTX {x} '{key}' is named but nothing feeds it and it is "
                               f"patched nowhere")
            continue
        sources, common = sources_cells(found)
        bus_rows.append({
            "bus": f"Matrix {x}", "name": (state.name(base) or "").strip(),
            "width": width("mtx", x), "sources": sources, "tap": common if found else "",
            "outputs": _socket_runs([(g, n) for g, n, _s in out]),
            "fx": "; ".join(model for _p, _s, model in desk.inserts(base)),
            "dca": ";".join(desk.dcas(base)), "mute_group": ";".join(desk.mute_groups(base)),
        })
        patches = _plan_patches(out)
        # What feeds it is on each source, as `matrix_sends`, with its tap
        # (below); `fed_by`, which holds one Main or bus and no tap, is left
        # to a built plan.
        outputs[key] = with_inserts({"kind": "matrix", "index": x, "fed_by": None,
                        "name_on": "strip" if named else "none",
                        "patch": patches[0] if patches else None, "patches": patches,
                        "fader": {"fader_db": None, "muted": None}, "description": None,
                        "mono": state.flag(f"{base}/busmono"), "col": colour(f"{base}/col"),
                        "dca": desk.dcas(base), "mute_group": desk.mute_groups(base),
                        "provenance": f"captured from the desk (Matrix {x})"}, base)

    # -- the sends, on their source ----------------------
    # A bus's sends to the other buses, and every send to a Matrix -- from a
    # channel, a bus or a Main -- go on the source, as the desk keeps them,
    # with the tap; the level is the mix, and the desk's.
    matrix_keys = {x: key for x, key in mtx_key.items() if key in outputs}
    bus_in_plan = {i: key for i, key in bus_key.items() if key in busses}
    main_in_plan = {m: key for m, key in main_key.items() if key in outputs}
    for i, key in bus_in_plan.items():
        for j, other in bus_in_plan.items():
            leaf = f"/bus/{i}/send/{j}"
            if j != i and desk.flag(f"{leaf}/on"):
                busses[key].setdefault("bus_sends", []).append(
                    {"bus": other, "mode": tap(None, desk.flag(f"{leaf}/pre")), "level_db": None})
    for x, matrix in matrix_keys.items():
        for base_ch, ch in strip_in_plan.items():
            if desk.flag(f"{base_ch}/send/MX{x}/on"):
                ch.setdefault("matrix_sends", []).append(
                    {"matrix": matrix, "mode": tap(state.text(f"{base_ch}/send/MX{x}/mode"), False),
                     "level_db": None})
        for i, key in bus_in_plan.items():
            leaf = f"/bus/{i}/send/MX{x}"
            if desk.flag(f"{leaf}/on"):
                busses[key].setdefault("matrix_sends", []).append(
                    {"matrix": matrix, "mode": tap(None, desk.flag(f"{leaf}/pre")), "level_db": None})
        for m, key in main_in_plan.items():
            leaf = f"/main/{m}/send/MX{x}"
            if desk.flag(f"{leaf}/on"):
                outputs[key].setdefault("matrix_sends", []).append(
                    {"matrix": matrix, "mode": tap(None, desk.flag(f"{leaf}/pre")), "level_db": None})

    # -- the DCAs and mute groups the sheets name -------------------------------
    used_dcas = {d for c in channels for d in c["dca"]} | {d for b in busses.values() for d in b["dca"]}
    used_mgrps = ({g for c in channels for g in c["mute_group"]}
                  | {g for b in busses.values() for g in b["mute_group"]})
    dcas = {name: {"index": i} for i, name in desk.dca_names.items() if name in used_dcas}
    mute_groups = {name: {"index": i} for i, name in desk.mute_group_names.items()
                   if name in used_mgrps}

    # -- what was decided, and what the plan cannot hold yet ---------------------
    if no_name:
        notes.append(f"{len(no_name)} channel(s) have no name of their own, so the name of "
                     f"their source is written in: {'; '.join(no_name)}.")
    if renamed:
        notes.append(f"An input list's names are unique, so a name the desk repeats carries "
                     f"its channel in the row's name: {_names(renamed)}. The plan keeps the "
                     f"desk's name on each channel.")
    if categorised:
        notes.append("category from each channel's first DCA, or 'other' with none: "
                     + "; ".join(f"'{category}' for {_names(labels)}"
                                 for category, labels in categorised.items()) + ".")
    if typed_line:
        notes.append(f"type 'Line' for a source on a module, USB, a card, the player or "
                     f"AES/EBU, 'Mic' for every other: Line on {_names(typed_line)}.")
    for line in roles_fx:
        notes.append(f"role 'fx' for {line}, so it is read as an effect return.")
    if unread:
        engines = sorted(unread)
        notes.append(f"The parameters of {_names([f'FX{e}' for e in engines])} could not be "
                     f"read, so the plan keeps {'its' if len(engines) == 1 else 'their'} model "
                     f"only: Apply loads the model and leaves the engine's parameters as the "
                     f"desk has them. The other effects are kept whole.")
    if grp_sends:
        notes.append(f"Sends in the desk's GRP mode have no pre/post in the plan yet, so "
                     f"their tap is left undecided: {_names(grp_sends)}.")
    # The USR slots a channel or an output reads, so Apply puts
    # them back; one assigned that nothing reads is left as the desk has it.
    read = {n for ch in channels for n in ((ch.get("patch") or {}).get("sockets") or [])
            if (ch.get("patch") or {}).get("group") == "USR"}
    read |= {int(state.number(f"/io/out/{group}/{socket}/in"))
             for group, socket in desk.direct_outputs
             if state.text(f"/io/out/{group}/{socket}/grp") == "USR"}
    assigned = _user_sources(state)
    user_sources = [u for u in assigned if u["slot"] in read]
    unread = [u for u in assigned if u["slot"] not in read]
    if user_sources:
        notes.append(f"{len(user_sources)} USR slot(s) a channel or an output reads, each "
                     f"recorded as the desk has it, so Apply puts it back: "
                     + _names([f"USR {u['slot']} from {u['source']['group']} "
                               f"{u['source']['index']}" for u in user_sources]) + ".")
    if unread:
        notes.append(_names([f"USR {u['slot']} (from {u['source']['group']} "
                             f"{u['source']['index']})" for u in unread])
                     + (" is" if len(unread) == 1 else " are")
                     + " assigned on the desk, but no channel or output reads it, so the "
                       "plan leaves it as the desk has it.")
    lone = {(group, socket) for group, socket, _obj in desk.lone_sides}
    straight = [s for s in desk.direct_outputs if s not in lone]
    if straight:
        notes.append(f"{len(straight)} output socket(s) carry an input or a "
                     f"monitor feed directly, not a bus, Main or Matrix (recording and "
                     f"Dante splits): {_socket_runs(straight)}. They are in "
                     f"outputs.csv, one row each, with every other patched socket; Apply "
                     f"writes them and Watch says only if one changes.")
    if desk.lone_sides:
        words = {"BUS": "Bus", "MAIN": "Main", "MTX": "Matrix"}
        notes.append("A socket carries an object's R without its L on the socket before, "
                     "so outputs.csv and the plan record it as that socket's own source, "
                     "and busses.csv's outputs cell leaves it out: "
                     + _names([f"{format_socket(g, n)} from {words[kind]} {index} R"
                               for g, n, (kind, index) in sorted(desk.lone_sides)]) + ".")
    if unused_routed:
        notes.append(f"Left out of the sheets: {_names(unused_routed)}, which nothing "
                     f"feeds and which reach only a Main, so no row has them and no "
                     f"sources cell names them.")
    for line in skipped:
        notes.append(f"Left out of the sheets: {line}.")

    plan = {
        "channels": channels, "dcas": dcas, "mute_groups": mute_groups,
        "busses": busses, "outputs": outputs, "input_list": "input.csv",
        "direct_outputs": [
            {"group": group, "socket": socket,
             "source": {"group": state.text(f"/io/out/{group}/{socket}/grp"),
                        "index": int(state.number(f"/io/out/{group}/{socket}/in"))}}
            for group, socket in sorted(desk.direct_outputs,
                                        key=lambda s: outputs_sheet.socket_order(*s))],
        **({"user_sources": user_sources} if user_sources else {}),
        "notes": [{"text": text, "source": "capture"} for text in notes],
        "meta": {"made_from": made_from, "captured": captured,
                 "console_model": console_model, "snapshot": snapshot},
    }
    for entry in plan["direct_outputs"]:
        note_socket_colour(entry["source"]["group"], entry["source"]["index"])
    for entry in user_sources:
        note_socket_colour(entry["source"]["group"], entry["source"]["index"])
    if socket_colours:
        plan["meta"]["socket_colours"] = socket_colours
    return Capture(input_rows, bus_rows, plan, notes)


# --------------------------------------------------------------------------
# Reading: a `.snap`, or a live desk
# --------------------------------------------------------------------------


def state_from_snap(ae_data: dict, console_model: str | None) -> ConsoleState:
    """A `.snap`'s `ae_data` as a reading: every leaf, at its OSC address,
    typed the way the desk types it (`initialize.leaves_from_snapshot`). A
    `.snap` is the desk's own JSON node tree, so this is the whole console,
    more than a live read asks for."""
    from atoo.initialize import leaves_from_snapshot

    values = {leaf.address: (int(leaf.value) if isinstance(leaf.value, bool) else leaf.value)
              for leaf in leaves_from_snapshot(ae_data)}
    return ConsoleState(values, console_model=console_model)


#: How much of the desk a live capture reads: every strip and every output
#: socket the address space has, since nothing says in advance where a show
#: put things. One read, once, so the cost (about 750 node-dump requests on
#: a full-size WING) is paid by `capture` and never by a Watch pass.
LIVE_READ = dict(channels=40, aux=8, buses=16, mains=4, matrices=8, dcas=16, mute_groups=8)


def live_read_kwargs(console_model: str | None) -> dict:
    """`read_console_state` arguments for a capture: the panel's inputs and
    the three AES50 ports for 48V, every output group whole, and the leaves
    a capture needs that no rule reads (`capture_extra_addresses`)."""
    inputs: dict[str, int] = {g: console_facts.INPUT_SOCKETS[g] for g in ("A", "B", "C")}
    if console_model in console_facts.CONSOLE_MODELS:
        for group, count in console_facts.CONSOLE_MODELS[console_model]["inputs"].items():
            if count:
                inputs[group] = count
    outputs = dict(console_facts.OUTPUT_SOCKETS)
    # Each input socket's colour, which a strip linked to it shows and an
    # Outputs row's source is drawn in: one leaf of a node already read.
    colours = [(f"/io/in/{group}/{n}/col", "i")
               for group, count in inputs.items() for n in range(1, count + 1)]
    return dict(LIVE_READ, input_sockets=inputs, output_sockets=outputs,
                extra=tuple(capture_extra_addresses()) + tuple(colours))


def _plan_strip_entries(plan: dict) -> list[dict]:
    return ([c for c in plan.get("channels") or []] + list((plan.get("busses") or {}).values())
            + list((plan.get("outputs") or {}).values()))


def capture_extra_addresses() -> list[tuple[str, str]]:
    """What a capture reads beyond the audit's plan: each send's pre/post,
    the bus-to-bus sends, the DCA and mute-group names, and each FX slot's
    wet/dry (`fxmix`), which decides an `fx` role. `read_console_state`
    drops any the plan already asks for."""
    wanted: list[tuple[str, str]] = []
    for bank, count in (("ch", 40), ("aux", 8)):
        for n in range(1, count + 1):
            base = f"/{bank}/{n}"
            # The desk's colours: the strip's own, and whether it shows its
            # source's instead.
            wanted.append((f"{base}/col", "i"))
            wanted.append((f"{base}/clink", "i"))
            for b in range(1, 17):
                wanted.append((f"{base}/send/{b}/mode", "s"))
            for x in range(1, 9):
                wanted.append((f"{base}/send/MX{x}/mode", "s"))
            for m in range(1, 5):
                wanted.append((f"{base}/main/{m}/pre", "i"))
    for n in range(1, 17):
        for b in range(1, 17):
            if b != n:
                wanted.append((f"/bus/{n}/send/{b}/on", "i"))
                wanted.append((f"/bus/{n}/send/{b}/pre", "i"))
        for x in range(1, 9):
            wanted.append((f"/bus/{n}/send/MX{x}/pre", "i"))
    for n in range(1, 5):
        for x in range(1, 9):
            wanted.append((f"/main/{n}/send/MX{x}/pre", "i"))
    for kind, count in (("bus", 16), ("main", 4), ("mtx", 8)):
        for n in range(1, count + 1):
            wanted.append((f"/{kind}/{n}/name", "s"))
            wanted.append((f"/{kind}/{n}/tags", "s"))
            wanted.append((f"/{kind}/{n}/col", "i"))
    for slot in range(1, console_facts.FX_SLOTS + 1):
        wanted.append((FX_MIX.replace("{n}", str(slot)), "f"))
    return wanted


def source_mode_addresses(state: ConsoleState) -> list[tuple[str, str]]:
    """The width (`mode`) of every odd socket a strip in use is patched to,
    where the reading does not hold it: a live read asks it only of the
    sockets that carry 48V, and a stereo source on a module, a card or USB
    is two input rows. Read before `pair_name_addresses`, which needs it."""
    wanted = []
    for base in strip_bases(state):
        patch = state.patch(base)
        if patch is None or not is_in_use(state, base):
            continue
        group, socket = patch
        address = f"/io/in/{group}/{socket}/mode"
        if socket % 2 == 1 and address not in state.values and group not in NOT_A_SOCKET:
            wanted.append((address, "s"))
    return list(dict.fromkeys(wanted))


def pair_name_addresses(state: ConsoleState) -> list[tuple[str, str]]:
    """The name of the second socket of every stereo source a strip in use
    takes, where the reading does not hold it: a live read's second pass
    names only the socket a strip is patched to."""
    wanted = []
    for base in strip_bases(state):
        patch = state.patch(base)
        if patch is None or not is_in_use(state, base):
            continue
        group, socket = patch
        legs = input_pair_sockets(state, group, socket)
        for n in legs[1:]:
            address = f"/io/in/{group}/{n}/name"
            if address not in state.values:
                wanted.append((address, "s"))
    return wanted


# --------------------------------------------------------------------------
# Writing the bundle
# --------------------------------------------------------------------------

EMPTY_WATCH = '{\n  "version": 2,\n  "watch_conditions": []\n}\n'


def bundle_name(*, snap: str | None = None, console_model: str | None = None,
                captured: str) -> str:
    """The folder a capture writes: the `.snap`'s file name without its
    extension, or the desk's model and the date (spec section 3)."""
    from pathlib import Path

    if snap:
        return Path(snap).stem
    return f"{console_model or 'wing'}-{captured}"


def free_directory(parent, name: str):
    """`parent/name`, or `name-2`, `name-3` ... when that is taken."""
    from pathlib import Path

    parent = Path(parent)
    candidate, n = parent / name, 1
    while candidate.exists():
        n += 1
        candidate = parent / f"{name}-{n}"
    return candidate


def write_bundle(capture: Capture, directory, *, evidence_name: str, evidence: bytes) -> list:
    """Write the bundle into `directory`, which must not exist yet, and
    return the paths written. `evidence` is the snapshot's bytes (or a live
    reading's JSON), saved as `captures/<evidence_name>`."""
    import json
    from pathlib import Path

    from atoo import bundle

    directory = Path(directory)
    directory.mkdir(parents=True)
    written = []

    def put(path: Path, text: str | bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        written.append(path)

    put(directory / bundle.INPUT_LIST, capture.input_csv())
    put(directory / bundle.BUSSES, capture.busses_csv())
    if outputs_sheet.output_sources(capture.plan):
        put(directory / bundle.OUTPUTS, capture.outputs_csv())
    if capture.plan.get("user_sources"):
        put(directory / bundle.USER, capture.user_csv())
    # The two sheets' fingerprints, so the plan reads Stale once either is
    # edited outside step 04 (`plan_freshness`), as a built plan's input list.
    from atoo import plan_freshness
    meta = capture.plan.setdefault("meta", {})
    meta["input_list"] = plan_freshness.input_list_record(directory / bundle.INPUT_LIST, directory)
    meta["bus_sheet"] = plan_freshness.input_list_record(directory / bundle.BUSSES, directory)
    if (directory / bundle.OUTPUTS).is_file():
        meta["outputs_sheet"] = plan_freshness.input_list_record(directory / bundle.OUTPUTS,
                                                                 directory)
    if (directory / bundle.USER).is_file():
        meta["user_sheet"] = plan_freshness.input_list_record(directory / bundle.USER, directory)
    put(directory / bundle.PLAN, json.dumps(capture.plan, indent=2, ensure_ascii=False) + "\n")
    put(directory / bundle.WATCH_CONDITIONS, EMPTY_WATCH)
    put(directory / bundle.CAPTURES / evidence_name, evidence)
    return written


@dataclass
class Source:
    """One desk read for a capture: the capture itself, what it was made from
    (`snap` or `desk`), the evidence to keep under `captures/` (its file name
    and bytes) and the bundle's name. `atoo capture` and the Setup page's
    New show > From a desk both make one, and write it with `write_bundle`."""

    capture: Capture
    made_from: str
    evidence_name: str
    evidence: bytes
    name: str


def from_snap(path, console_model: str, *, captured: str) -> Source:
    """A `.snap` file, as the console model its sockets are counted on. Raises
    `snapshot.SnapshotError` for a file that is not a WING snapshot."""
    from pathlib import Path

    from atoo import bundle
    from atoo.snapshot import load_snapshot

    data = load_snapshot(str(path))
    state = state_from_snap(data, console_model)
    evidence_name = Path(path).name
    result = capture_desk(state, console_model=console_model, made_from="snap",
                          captured=captured, snapshot=f"{bundle.CAPTURES}/{evidence_name}")
    return Source(result, "snap", evidence_name, Path(path).read_bytes(),
                  bundle_name(snap=str(path), captured=captured))


def from_console(console, console_model: str, *, captured: str, progress=None) -> Source:
    """A live desk, read in bulk and then the two short follow-ups a capture
    needs: the width of each source a strip takes, and the name of the
    second socket of each stereo one. The reading is kept as `--dump-state`
    keeps one: Atoo reads a `.snap` but cannot write the WING's own format."""
    import json

    from atoo import bundle
    from atoo.audit import read_console_state
    from atoo.initialize import ABSENT, read_desk

    kwargs = live_read_kwargs(console_model)
    state = read_console_state(console, bulk=True, console_model=console_model,
                               progress=progress, **kwargs)
    for follow_up in (source_mode_addresses, pair_name_addresses):
        wanted = follow_up(state)
        if wanted:
            got = read_desk(console, wanted)
            state.values.update({a: v for a, v in got.values.items() if v is not ABSENT})
    unread, requests = read_effect_parameters(console, state, progress)
    evidence_name = f"{captured}.state.json"
    result = capture_desk(state, console_model=console_model, made_from="desk",
                          captured=captured, snapshot=f"{bundle.CAPTURES}/{evidence_name}",
                          unread_effects=unread)
    engines = len({i["engine"] for entry in _plan_strip_entries(result.plan)
                   for i in entry.get("inserts") or []})
    result.effect_reads = (engines, requests)
    evidence = (json.dumps(state.values, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return Source(result, "desk", evidence_name, evidence,
                  bundle_name(console_model=console_model, captured=captured))


def read_effect_parameters(console, state: ConsoleState, progress=None) -> tuple[set[int], int]:
    """The parameters of every FX engine a strip inserts, read
    into `state` by one node dump each (`/fx/{n}`), after the desk's read:
    that read holds each engine's model and wet/dry only. Returns the
    engines whose dump did not come back or did not parse, which a capture
    keeps by model alone, and how many requests it took. Never raises for
    the desk: a failure is an engine left unread, said at INFO."""
    from atoo import console as osc
    from atoo.audit import insert_bases

    engines = sorted({slot for base in insert_bases(state)
                      for _point, slot, _model in _inserts(state, base)})
    if not engines:
        return set(), 0
    if not callable(getattr(console, "node_dump", None)):
        return set(engines), 0
    nodes = [fx_engines.engine_address(e).rsplit("/", 1)[0] for e in engines]
    if progress is not None:
        progress.add_total(len(nodes))
    unread: set[int] = set()
    requests = 0
    dumps = osc.node_dumps(console, nodes, on_start=(
        (lambda node: progress.start_address(node + " (node)")) if progress is not None else None))
    for engine, node in zip(engines, nodes):
        try:
            _node, dump = next(dumps)
        except (OSError, StopIteration):
            unread.update(e for e in engines if e >= engine)
            break
        requests += 1
        if progress is not None:
            progress.finish_address(answered=bool(dump))
        parsed = None
        if dump:
            try:
                parsed = osc.parse_node_dump(node, dump)
            except osc.NodeDumpError:
                parsed = None
        if not parsed:
            unread.add(engine)
            continue
        for address, text in parsed.items():
            leaf = address[len(node) + 1:]
            if "/" in leaf or not fx_engines.is_engine_parameter(leaf):
                continue
            value = fx_engines.value_from_text(leaf, text)
            if value is not None:
                state.values[address] = value
    return unread, requests


def _outputs_summary(plan: dict) -> str:
    """`outputs.csv  147 output sockets: 123 fed straight from a source, 24 by
    a bus, a Main or a Matrix`."""
    from atoo import bundle

    sources = outputs_sheet.output_sources(plan)
    objects = sum(1 for group, _n in sources.values() if group in ("BUS", "MAIN", "MTX"))
    return (f"{bundle.OUTPUTS:<12} {len(sources)} output sockets: "
            f"{len(sources) - objects} fed straight from a source, "
            f"{objects} by a bus, a Main or a Matrix")


def _user_summary(plan: dict) -> str:
    """`user.csv     2 USR slots: 1 user signal, 1 user patch`."""
    from atoo import bundle

    def count(n: int, word: str, plural: str) -> str:
        return f"{n} {word if n == 1 else plural}"

    slots = [u["slot"] for u in plan.get("user_sources") or []]
    signals = sum(1 for s in slots if console_facts.user_slot_kind(s) == console_facts.USER_SIGNAL)
    kinds = [k for k in (count(signals, "user signal", "user signals") if signals else "",
                         count(len(slots) - signals, "user patch", "user patches")
                         if len(slots) - signals else "") if k]
    return f"{bundle.USER:<12} {count(len(slots), 'USR slot', 'USR slots')}: {', '.join(kinds)}"


def summary_lines(result: Capture) -> list[str]:
    """What a capture wrote, one line per file, as `atoo capture` prints it."""
    from atoo import bundle

    rows = {"Bus": 0, "Main": 0, "Matrix": 0}
    for row in result.bus_rows:
        rows[row["bus"].split()[0]] += 1
    effects = ""
    if result.effect_reads is not None and result.effect_reads[0]:
        engines, requests = result.effect_reads
        effects = (f"; {engines} effect(s), their parameters read in {requests} more "
                   f"request(s) after the desk's read")
    return [
        f"{bundle.INPUT_LIST:<12} {len(result.input_rows)} inputs on "
        f"{len(result.plan['channels'])} channels",
        f"{bundle.BUSSES:<12} {rows['Bus']} buses, {rows['Main']} Mains, {rows['Matrix']} Matrices",
        *([_outputs_summary(result.plan)] if outputs_sheet.output_sources(result.plan) else []),
        *([_user_summary(result.plan)] if result.plan.get("user_sources") else []),
        f"{bundle.PLAN:<12} the desk as it is: patch, routing, membership, widths, "
        f"effects{effects}",
        f"{bundle.WATCH_CONDITIONS:<12} empty, ready for watch conditions",
    ]
