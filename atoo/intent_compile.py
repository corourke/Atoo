"""Compile an intent into the change set `atoo patch` merges (`atoo patch --intent`).

`compile_intent(intent, base_plan, console_model, ...)` is the deterministic
half of the intent front end (`atoo/intent_schema.py` says what an intent is;
`atoo/intent.py` asks a model for one). It returns the change set and the INFO
lines it produced, or raises `IntentRefused` with every reason at once.
`patch.merge_change` then does what it does for any change set.

Physics is code and comes from `atoo.console_facts` for every console model
alike: strip counts, socket groups and their sizes, the odd-even stereo rule,
value ranges, the stage box's size. What cannot work is refused with the
reason; every other choice is made and announced at INFO. What the request ASKS
FOR (an insert, a position, a named socket, a fader, a gain) is not guessed
from a sentence: the change set carries it as `patch.Asked` facts.
"""

from __future__ import annotations

import copy
import re
from types import SimpleNamespace

from atoo import apply as apply_module
from atoo import console_facts as facts
from atoo import category_table as category_table_module
from atoo import input_list as input_list_module
from atoo import intent_names, patch, user_patch
from atoo import intent_sanity as sanity_mod
from atoo.intent_schema import (CAPACITY_KEY, explain, without_bounds, KEY as _KEY, PATCH_WORD, SOURCE_TYPES, intent_schema,
                                settings)
from atoo.reply_expand import CategoryRules
from atoo.schema_check import validate as validate_schema


class IntentRefused(ValueError):
    """The intent asks for something the console cannot be left in. Carries
    every reason found, one sentence each, naming the op."""

    def __init__(self, reasons: list[str], final: list[str] | None = None, ops=None):
        self.reasons = list(reasons)
        #: the numbers (1-based, in the compiled intent's `ops`) of the ops refused; empty when
        #: the refusal is of the intent as a whole (not well formed, nothing in it)
        self.ops = set(ops or ())
        #: the reasons that are the ENGINEER's own instruction meeting a limit (a socket
        #: the request named that the stage box does not have). The model is never
        #: asked to fix these: carrying the instruction out elsewhere would not be
        #: carrying it out.
        self.final = list(final or [])
        super().__init__("; ".join(self.reasons))

    @property
    def repairable(self) -> bool:
        """Whether asking the model again could help: nothing here is final."""
        return not self.final


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _prune(value, schema):
    """`value` without the keys `schema` does not have: what a plan holds that a
    change set's `add` may not (a preset's expanded values, derived by code)."""
    if isinstance(value, dict) and isinstance(schema, dict) and schema.get("properties"):
        return {k: _prune(v, schema["properties"][k]) for k, v in value.items()
                if k in schema["properties"]}
    return value


def _as_added(channel: dict) -> dict:
    """A channel taken from the desk, written the way a change set adds one."""
    return _prune(channel, patch.CHANGE_SET_SCHEMA["properties"]["add"]["properties"]["channels"]["items"])


#: The method of `_Compile` that compiles each intent op: one entry for every op in
#: `intent_schema`, which a test holds it to.
OP_HANDLERS = {"add_channel": "add_channel", "drop": "drop", "move_channel": "move_channel",
               "rename": "rename", "set": "set_field", "assign": "assign", "add_bus": "add_bus",
               "add_group": "add_group", "add_output": "add_output", "order": "set_order"}


class _Compile:
    """One compile: the working state the ops share (which sockets and
    strips are taken, what the intent has dropped and added so far)."""

    def __init__(self, base, model, text, table, devices, sanity):
        self.base, self.model, self.table, self.sanity = base, model, table, sanity
        self.boxes = apply_module.box_limits(devices)
        self.cs = patch.empty_change_set("")
        self.infos: list[str] = []
        self.refused: list[str] = []
        self.refused_ops: set[int] = set()
        self.final: list[str] = []
        self.range_problems: list[tuple] = []
        #: the input list's rows by name (a build), the category of each channel, the groups and
        #: buses that take members (resolved once every channel exists), and the strip order asked
        self.rows: dict[str, object] = {}
        #: the socket each input-list row states: (group, number) -> row name
        self.row_sockets: dict[tuple, str] = {}
        self.build = False
        self.conventions_text = ""
        self.cat: dict[str, str] = {}
        self.pending_members: list[tuple] = []
        #: channels this intent adds and then renames: the old name -> the new one
        self.renamed: dict[str, str] = {}
        self.order: list[str] | None = None
        self.order_within: list[str] = []
        self.sentences: list[str] = []
        self.text = text
        #: what the request ASKS FOR, as facts (`patch.Asked`): the merge is told,
        #: and reads no sentence for it
        self.positions: dict[str, int] = {}
        self.stated_sockets: set[str] = set()
        self.gain_named: set[str] = set()
        self.insert = False
        self.fader = self.mute = False
        #: channels as the plan will have them after the ops so far
        self.channels = [copy.deepcopy(c) for c in base.get("channels") or []]
        self.dropped: dict[str, set] = {k: set() for k in _KEY.values()}
        self.new: dict[str, set] = {k: set() for k in _KEY.values()}
        self.used: dict[tuple, str] = {}
        self._rescan_sockets()
        self.group_default = self._default_group()
        #: a stereo pair patched through two USER PATCH slots adds their `user_sources` entries
        #: (`through_user_patch`); the show's `user.csv` slots are never taken
        self.user_sources: list[dict] = []
        self.reserved_user_slots: tuple = ()
        #: stage boxes a channel no socket was named for may overflow to once the local inputs are
        #: full (`input_boxes`): one the input list already uses, or one the conventions name for inputs
        self.input_boxes: tuple = ()

    # -- lookups ----------------------------------------------------------

    def _rescan_sockets(self):
        self.used = {}
        for c in self.channels:
            if c.get("name") in getattr(self, "leaving", ()):
                continue
            p = c.get("patch") or {}
            for s in p.get("sockets") or []:
                self.used.setdefault((p.get("group"), s), c.get("name"))
        self.used.update(getattr(self, "reserved", {}))

    def reserve(self, ops):
        """Make the socket picture order-independent: the sockets of every
        channel the intent drops or moves are free, and the ones it names are
        taken, before any op chooses a socket for a channel that named none."""
        self.reserved, self.leaving = {}, set()
        for op in ops:
            leaving = op.get("name") if (op["op"] == "move_channel" and (op.get("place") or op.get("patch"))) \
                or (op["op"] == "drop" and op.get("object") == "channel") else None
            gone = self.find_channel(leaving) if leaving else None
            if gone is not None:
                self.leaving.add(gone["name"])
        for op in ops:
            spec = op.get("patch") if op["op"] in ("add_channel", "move_channel") else None
            if spec:
                count = spec.get("count") or (2 if op.get("stereo") else 1)
                for s in range(spec["first"], spec["first"] + count):
                    self.reserved[(spec["group"], s)] = op["name"]
        self._rescan_sockets()

    def _default_group(self) -> str:
        """The group most of the show's channel strips are patched to: the
        rig the show is on (A for a stage box, LCL for a desk with none)."""
        groups = [(c.get("patch") or {}).get("group") for c in self.channels
                  if c.get("bank", "ch") == "ch"]
        groups = [g for g in groups if g and g != "OFF"]
        return max(dict.fromkeys(groups), key=groups.count) if groups else "LCL"

    def find_channel(self, name):
        wanted = _norm(name)
        return next((c for c in self.channels if _norm(c.get("name")) == wanted), None)

    def named(self, key, name):
        wanted = _norm(name)
        return next((n for n in self.base.get(key) or {} if _norm(n) == wanted), None)

    def check_name(self, op_no, what, name, structural=False):
        """Refuse a new name that is garbage (`sanity.Sanity.name_problem`).
        `structural`: a bus, group or output, whose words may also come from the
        conventions."""
        problem = self.sanity.name_problem(name, structural=structural)
        if problem:
            self.refuse(op_no, what, problem)
        return problem is None

    def check_free_text(self, op_no, what, field, value):
        """Refuse a category, microphone model, colour or preset the schema let
        through as a string but nothing can account for."""
        check = {"category": self.sanity.category_problem, "model": self.sanity.model_problem,
                 "color": self.sanity.colour_problem, "preset": self.sanity.preset_problem}[field]
        problem = check(value) if isinstance(value, str) and value else None
        if problem:
            self.refuse(op_no, what, problem)
        return problem is None

    def without_missing_preset(self, what, op):
        """In a build, a preset the conventions name that the library does not have is not a
        reason to refuse the show: the strip is built without it, and the INFO says which (a
        change that names a missing preset is refused instead -- that is the engineer's order)."""
        preset = op.get("preset")
        if self.build and preset and self.sanity.preset_problem(preset):
            self.infos.append(f"{what}: the preset {preset!r} is not in the library, so the strip is "
                              "built without it")
            return {**op, "preset": None}
        return op

    def refuse(self, op_no, op, why, final=False):
        self.refused.append(f"op {op_no} ({op}): {why}")
        if isinstance(op_no, int):
            self.refused_ops.add(op_no)
        if final:
            self.final.append(self.refused[-1])

    # -- sockets ----------------------------------------------------------

    def limit(self, group, direction="in"):
        try:
            n = (facts.input_socket_limit if direction == "in" else facts.output_socket_limit)(
                group, self.model)
        except facts.UnknownConsoleModel:
            return 0
        box = self.boxes.get(group)
        return min(n, box[1 if direction == "in" else 2]) if box else n

    def check_sockets(self, op_no, what, group, sockets, direction="in") -> bool:
        """The physical checks on a stated patch; False (and a refusal) when
        it cannot exist."""
        limit = self.limit(group, direction)
        panel = (facts.input_socket_limit if direction == "in" else facts.output_socket_limit)(
            group, self.model)
        box = self.boxes.get(group)
        word = "input" if direction == "in" else "output"
        ok = True
        said = patch._numbers_after(self.text or "", group) if self.text else set()
        final = bool(sockets) and all(s in said for s in sockets)
        for s in sockets:
            if s > limit:
                if panel == 0:
                    why = f"this console has no {group} {word}s at all"
                elif box and s > box[1 if direction == "in" else 2]:
                    why = (f"{group} {s} does not exist on the {box[0]} on AES50-{group} "
                           f"(it has {limit} {word}s)")
                else:
                    why = f"this console has {group} {word}s 1 to {panel}, so {group} {s} does not exist"
                self.refuse(op_no, what, why, final=final)
                ok = False
                break
        if ok and len(sockets) == 2:
            problem = facts.stereo_pair_problem(list(sockets))
            if problem:
                self.refuse(op_no, what, f"{group} {sockets[0]}+{sockets[1]}: {problem}", final=final)
                ok = False
        return ok

    def choose(self, group, count, direction="in"):
        """The lowest free socket (an odd-started pair for two), or None."""
        limit = self.limit(group, direction)
        step = 2 if count == 2 else 1
        for start in range(1, limit - count + 2, step):
            run = list(range(start, start + count))
            if all((group, s) not in self.used for s in run):
                return run
        return None

    def without_unstated_impossible(self, name, spec, rows, stereo):
        """In a build, `spec` (an input-list row's socket, as the model wrote it) unless it cannot exist and nobody but the
        model named it: then None, and code chooses the socket as for any channel whose socket
        nobody named, said at INFO. The input list's socket is the engineer's and the
        conventions' words are too, so a socket either states is checked and refused as ever;
        one the model worked out for itself ("in order from LCL 1") and got wrong is not a
        reason to build nothing."""
        if not (self.build and spec and rows) or any(getattr(r, "patch", None) for r in rows):
            return spec   # a strip that is not a row takes its socket from the conventions' words
        group, first = spec["group"], spec["first"]
        sockets = list(range(first, first + (spec.get("count") or (2 if stereo else 1))))
        limit = self.limit(group)
        problem = (f"{group} {max(sockets)} does not exist on this console" if max(sockets) > limit
                   else facts.stereo_pair_problem(sockets) if len(sockets) == 2 else None)
        if not problem or self.conventions_name(group, sockets):
            return spec
        where = f"{group} {first}" + (f"+{first + 1}" if len(sockets) == 2 else "")
        self.infos.append(f"channel {name!r}: the reply put it on {where} ({problem}); neither the "
                          "input list nor the conventions name that socket, so Atoo chose one")
        return None

    def conventions_name(self, group, sockets) -> bool:
        """Whether the conventions name exactly these sockets: "LCL 6", "LCL 6-7", "LCL 6+7",
        "LCL 6 and 7". A range that merely covers them ("LCL 1-24") is not naming them."""
        nums = r"\s*(?:\+|-|/|&|and|to)\s*".join(str(n) for n in sockets)
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(group)}\s*{nums}(?!\s*(?:\d|-\s*\d))",
                         self.conventions_text, re.IGNORECASE) is not None

    def stated_patch(self, op_no, what, spec, count_default, direction="in"):
        group, first = spec["group"], spec["first"]
        count = spec.get("count") or count_default
        sockets = list(range(first, first + count))
        return (group, sockets) if self.check_sockets(op_no, what, group, sockets, direction) \
            else (group, None)

    # -- strips -----------------------------------------------------------

    def strip_for(self, op_no, what, bank, place, name):
        """The strip number: the one asked for, or the next past the last."""
        cap = facts.CAPACITY[bank]
        taken = [c["channel"] for c in self.channels
                 if c.get("bank", "ch") == bank and isinstance(c.get("channel"), int)]
        place = place or {}
        if place.get("at") is not None:
            n = place["at"]
            how = f"the strip the request named, {bank} {n}"
        elif place.get("after") or place.get("before"):
            ref = place.get("after") or place.get("before")
            beside = self.find_channel(ref)
            if beside is None:
                self.refuse(op_no, what, f"it goes {'after' if place.get('after') else 'before'} "
                            f"{ref!r}, and no channel of that name is on the desk")
                return None
            n = beside["channel"] + (1 if place.get("after") else 0)
            how = f"{'after' if place.get('after') else 'before'} {beside['name']!r}"
        else:
            n = max(taken, default=0) + 1
            how = f"the next strip past the last one in use ({bank} {max(taken, default=0)})"
        if not 1 <= n <= cap:
            self.refuse(op_no, what, f"{bank} {n} is past the desk's range: this console has "
                        f"{bank} strips 1 to {cap}")
            return None
        if how.startswith("the next"):
            self.infos.append(f"channel {name!r}: no strip was named, so it goes on {bank} {n}, {how}")
        if place.get("at") is not None or place.get("after") or place.get("before"):
            self.positions[_norm(name)] = n
        if place.get("renumber"):
            self.insert = True
        return n

    # -- the input list (a build) ---------------------------------------------

    def rows_of(self, i, what, op):
        """The input-list rows an `add_channel` is built from: the ones it names in `rows`, or
        (in a build) the row of its own name, else none. None, and a refusal, for a name the list
        does not have."""
        named = op.get("rows") or []
        if not named:
            row = self.rows.get(_norm(op["name"])) if self.build else None
            return [row] if row is not None else []
        found = []
        for raw in named[:2]:
            row = self.rows.get(_norm(raw))
            if row is None:
                self.refuse(i, what, f"{raw!r} is not a row of the input list")
                return None
            found.append(row)
        return found

    def asked_for(self, i, what, name):
        """The line of the conventions that asks for `name`, a build's strip that is not a row of
        the input list: a line naming it as a word and stating its socket ("Setup TALKBACK on Aux 8,
        source LCL 22"). It goes on the channel's `source.quote`, so verify sees the strip was asked
        for (`instructed_channels`), not invented. None, and a refusal, when no line does."""
        from atoo import instructed_channels as ic

        word = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])", re.IGNORECASE)
        for line in self.conventions_text.splitlines():
            line = ic.clean_quote(line.strip().lstrip("#-*> \t"))
            if word.search(line) and ic.stated_sockets(line):
                self.infos.append(f"channel {name!r} is not a row of the input list; it is built "
                                  f"because the conventions ask for it: {line!r}")
                return line
        self.refuse(i, what, "it is not a row of the input list, and no line of the conventions "
                    "names it with its socket; a strip that is not on the list is built only when "
                    "the conventions ask for it by that name and say where it is plugged in")
        return None

    def fill_from_rows(self, op, rows):
        """`op` with what the rows say of the channel filled in where the op says nothing: the
        source type, model, phantom power, category, preset, and the socket the list states."""
        if not rows:
            return op
        row = rows[0]
        filled = dict(op)
        from_row = {"kind": row.type.strip().lower() if row.type.strip().lower() in SOURCE_TYPES else None,
                    "model": row.model or None,
                    "phantom": True if any(r.phantom for r in rows) else None,
                    "category": row.category.strip().lower() or None,
                    "preset": row.preset or None}
        spec = input_list_module.parse_socket_spec(row.patch) if row.patch else None
        if spec:
            from_row["patch"] = {"group": spec[0], "first": spec[1], "count": 2 if len(rows) == 2 else None}
        if len(rows) == 2:
            from_row["stereo"] = True
        for key, value in from_row.items():
            if value is None:
                continue
            if filled.get(key) in (None, ""):
                filled[key] = value
            elif self.build and key in ("patch", "model", "preset", "kind") and not self._same(key, filled[key], value):
                # In a build the input list is the engineer's word about each row: a socket, a
                # microphone, a preset or a source type it states wins over the model's, and is said.
                self.infos.append(f"channel {op['name']!r}: the input list states {key} "
                                  f"{self._words(key, value)} for {row.name!r}; the model wrote "
                                  f"{self._words(key, filled[key])}, and the list's stands")
                filled[key] = value
        return filled

    @staticmethod
    def _same(key, a, b) -> bool:
        if key == "patch":
            return (a or {}).get("group") == (b or {}).get("group") and (a or {}).get("first") == (b or {}).get("first")
        return _norm(a) == _norm(b)

    @staticmethod
    def _words(key, value) -> str:
        if key == "patch" and isinstance(value, dict):
            return f"{value.get('group')} {value.get('first')}"
        return repr(value)

    # -- ops ----------------------------------------------------------------

    def through_user_patch(self, name, rows):
        """In a build, a pair whose two rows' sockets the desk cannot join (LCL 4 and 5, B 2 and
        3, two groups): `(patch, None)` through the first free pair of USER PATCH slots, with
        their `user_sources` entries recorded and an INFO; `(None, why)` when no pair of slots
        is free or a user patch cannot take a socket, so the rows are built as two mono
        channels; `(None, None)` for a pair the desk forms as cabled, or one the list states
        no sockets for. `user_patch` chooses, as on the compact path."""
        if not (self.build and len(rows) == 2 and rows[0].patch and rows[1].patch):
            return None, None
        a = input_list_module.parse_socket_spec(rows[0].patch)
        b = input_list_module.parse_socket_spec(rows[1].patch)
        if not (a and b) or not user_patch.pair_problem(a, b):
            return None, None
        taken = user_patch.taken_slots(
            {"user_sources": self.user_sources}, self.reserved_user_slots,
            [s for (g, s) in self.used if g == "USR"])
        slot = None if user_patch.cannot_take(a, b) else user_patch.free_pair(taken)
        if slot is None:
            return None, user_patch.split_info(rows[0].name, a, rows[1].name, b)
        self.user_sources.extend(user_patch.entries(slot, name, a, b))
        for socket in (a, b):
            self.used[socket] = name            # the jacks themselves are this channel's
        self.infos.append(user_patch.routed_info(rows[0].name, a, rows[1].name, b, name, slot))
        return {"group": "USR", "sockets": [slot, slot + 1]}, None

    def add_channel(self, i, op):
        name = op["name"]
        what = f"add_channel {name!r}"
        rows = self.rows_of(i, what, op)
        if rows is None:
            return
        routed, split = self.through_user_patch(name, rows)
        if split:
            # No pair of user patch slots can take them: two mono channels, each on its row's own
            # socket, the first keeping what the op said of the channel.
            self.infos.append(split)
            first = {k: v for k, v in op.items() if k not in ("rows", "stereo", "patch")}
            self.add_channel(i, {**first, "rows": [rows[0].name], "stereo": False})
            return self.add_channel(i, {"op": "add_channel", "name": rows[1].name})
        op = self.fill_from_rows(op, rows)
        bank = op.get("bank") or "ch"
        stereo = bool(op.get("stereo"))
        self.cat[_norm(name)] = op.get("category") or ""
        if self.find_channel(name) is not None and name not in self.dropped["channels"]:
            self.refuse(i, what, "a channel of that name is already on the desk")
            return
        self.check_name(i, what, name, structural=self.build)   # a build's strips may be named by the conventions
        op = self.without_missing_preset(what, op)
        for field in ("category", "model", "color", "preset"):
            self.check_free_text(i, what, field, op.get(field))
        for key in ("dca", "mute_group"):
            for gname in op.get(key) or []:
                if self.named("dcas" if key == "dca" else "mute_groups", gname) is None \
                        and gname not in self.cs["add"]["dcas" if key == "dca" else "mute_groups"]:
                    self.check_name(i, what, gname, structural=True)
        n = self.strip_for(i, what, bank, op.get("place"), name)
        spec = None if routed else self.without_unstated_impossible(name, op.get("patch"), rows, stereo)
        if routed:
            group, sockets, stated, stereo = routed["group"], routed["sockets"], True, True
            self.stated_sockets.add(_norm(name))
        elif spec:
            group, sockets = self.stated_patch(i, what, spec, 2 if stereo else 1, "in")
            stated = True
            self.stated_sockets.add(_norm(name))
            if sockets is not None and len(sockets) == 2 and not stereo and spec.get("count") == 2:
                stereo = True
                self.infos.append(f"channel {name!r}: two sockets were named, so it is a stereo channel")
        else:
            stated = False
            group, sockets = self.group_default, None
            for group in dict.fromkeys([self.group_default, "LCL", *self.input_boxes, "AUX"]):
                sockets = self.choose(group, 2 if stereo else 1)
                if sockets is not None:
                    break
            if sockets is None:
                self.refuse(i, what, f"no free {self.group_default} socket (nor a free local "
                            "one) is left to give it")
            # The choice is announced once, by the merge, as Atoo's (`patch.Asked.picked_by`).
        asked = self.asked_for(i, what, name) if self.build and not rows else None
        if n is None or sockets is None or (self.build and not rows and asked is None):
            return
        own = {r.name.casefold() for r in rows}
        for s in sockets[1:]:
            owner = self.row_sockets.get((group, s))
            if owner is not None and owner.casefold() not in own:
                self.refuse(i, what, f"{group} {s}, the other half of the pair, is the input list's socket "
                            f"for {owner!r}; a stereo pair on {group} {sockets[0]} would take it")
                return
        for s in sockets:
            self.used[(group, s)] = name
        channel = {
            "channel": n, "bank": bank, "name": name, "color": op.get("color"),
            "source": {"input": rows[0].name if rows else name,
                       "type": SOURCE_TYPES.get(op.get("kind") or "mic", "Mic"),
                       "model": op.get("model") or "", "stereo": stereo,
                       "phantom": bool(op.get("phantom")),
                       **({"pair_input": rows[1].name, "pair_phantom": bool(rows[1].phantom)}
                          if len(rows) == 2 else {}),
                       **({"from": "conventions", "quote": asked} if asked else {})},
            "patch": {"group": group, "sockets": sockets, "stated": stated},
            "processing": {"gain_db": op.get("gain_db"), "trim_db": None,
                           "preset": op.get("preset"), "hpf_hz": op.get("hpf_hz"),
                           "hi_cut_hz": None, "tilt_db": None, "balance_db": None, "invert": None},
            "fader": {"fader_db": op.get("fader_db"), "muted": None},
            "dca": list(op.get("dca") or []), "mute_group": list(op.get("mute_group") or []),
            "bus_sends": [{"bus": s["bus"], "mode": s.get("mode"), "level_db": s.get("level_db")}
                          for s in op.get("sends") or []],
            "main_routes": [], "provenance": {"channel": "the intent: add_channel"},
        }
        self.range_check(i, what, "fader_db", op.get("fader_db"), facts.FADER_DB_RANGE)
        self.range_check(i, what, "gain_db", op.get("gain_db"), facts.HEAD_AMP_GAIN_DB_RANGE)
        self.range_check(i, what, "hpf_hz", op.get("hpf_hz"), facts.HPF_HZ_RANGE)
        for s in op.get("sends") or []:
            self.range_check(i, what, f"send to {s['bus']!r} level_db", s.get("level_db"),
                             facts.SEND_LEVEL_DB_RANGE)
        if op.get("gain_db") is not None:
            self.gain_named.add(_norm(name))
        if op.get("fader_db") is not None:
            self.fader = True
        self.apply_category(channel, op)
        for key, section in (("dca", "dcas"), ("mute_group", "mute_groups")):
            for gname in channel[key]:
                if self.named(section, gname) is None and gname not in self.cs["add"][section]:
                    self.cs["add"][section][gname] = {}
        self.cs["add"]["channels"].append(channel)
        self.channels.append(channel)
        self.new["channels"].add(_norm(name))
        self.sentences.append(f"Add {name}.")

    def apply_category(self, channel, op):
        if self.table is None or not op.get("category"):
            if op.get("category") and self.table is None:
                self.infos.append(f"channel {channel['name']!r}: the category {op['category']!r} was "
                                  "named, and these conventions have no Category table, so only what "
                                  "the request stated is set")
            return
        written = {k for k in ("color", "hpf_hz", "gain_db", "fader_db", "dca", "mute_group")
                   if op.get(k) not in (None, [])}
        scratch = {"dcas": {}, "mute_groups": {}}
        rules = CategoryRules(self.table, scratch)
        rules.apply(channel, SimpleNamespace(category=op["category"]), written)
        self.infos.extend(f.message for f in rules.findings())
        for section, field in (("dcas", "dca"), ("mute_groups", "mute_group")):
            for gname in scratch[section]:
                if self.named(section, gname) is not None:
                    continue
                same = next((n for n in self.cs["add"][section] if _norm(n) == _norm(gname)), gname)
                self.cs["add"][section].setdefault(same, {})
                if same != gname:      # one group, however the table and the ops spell it
                    channel[field] = [same if g == gname else g for g in channel.get(field) or []]

    def range_check(self, i, what, field, value, bounds):
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and not bounds[0] <= value <= bounds[1]:
            self.refuse(i, what, f"{field} {value} is outside the console's range "
                        f"{bounds[0]:g} to {bounds[1]:g}")

    def drop(self, i, op):
        kind = op["object"]
        key = _KEY[kind]
        if op.get("name") is None and op.get("index") is None:
            return self.refuse(i, f"drop {kind}", "it names neither a name nor an index")
        if kind == "channel":
            c = self.find_channel(op["name"]) if op.get("name") else None
            if c is None:
                return self.refuse(i, f"drop channel {op.get('name')!r}",
                                   "no channel of that name is on the desk")
            pending = next((e for e in self.cs["add"]["channels"] if e is c), None)
            if pending is not None and self.build and not self.quoted(op, c):
                return None
            if pending is not None:       # added earlier in this same intent: take that add back
                self.cs["add"]["channels"].remove(pending)
                self.channels.remove(c)
                self._rescan_sockets()
                self.infos.append(f"channel {c['name']!r} was added by this intent and then dropped: "
                                  "it is not built")
                return self.sentences.append(f"Leave out {c['name']}.")
            self.channels.remove(c)
            self.cs["drop"]["channels"].append(c["name"])
            self.dropped["channels"].add(c["name"])
            self._rescan_sockets()
            return self.sentences.append(f"Remove {c['name']}.")
        target = None
        if op.get("name") is not None:
            target = self.named(key, op["name"])
        else:
            cap = facts.CAPACITY[CAPACITY_KEY.get(kind, "main")]
            if not 1 <= op["index"] <= cap:
                return self.refuse(i, f"drop {kind} {op['index']}",
                                   f"there is no {kind.replace('_', ' ')} {op['index']}: this console has "
                                   f"{kind.replace('_', ' ')}s 1 to {cap}")
            target = next((n for n, o in (self.base.get(key) or {}).items()
                           if isinstance(o, dict) and o.get("index") == op["index"]
                           and (kind != "output" or o.get("kind") == "main")), None)
            if target is None:
                self.infos.append(f"{kind.replace('_', ' ')} {op['index']} is already free on the plan; "
                                  "nothing to clear")
                return None
        if target is None:
            return self.refuse(i, f"drop {kind} {op.get('name')!r}",
                               f"no {kind.replace('_', ' ')} of that name is on the desk")
        self.cs["drop"][key].append(target)
        self.dropped[key].add(target)
        self.sentences.append(f"Drop the {target} {kind.replace('_', ' ')}.")
        if op.get("index") is not None:
            self.infos.append(f"{kind.replace('_', ' ')} {op['index']} is {target!r}: dropped and "
                              "returned to free")
        return None

    def check_ranges(self, ops, schema):
        """A number past the console's range (a bus 40, a strip 60) is refused naming the
        range. It is the engineer's own instruction meeting a limit, and so final, when
        the number is in the request; otherwise the model made it up and is asked again."""
        branches = {b["properties"]["op"]["enum"][0]: b for b in schema["properties"]["ops"]["items"]["oneOf"]}
        typed = set(re.findall(r"\d+", self.text or ""))
        for i, op in enumerate(ops, start=1):
            for problem in validate_schema(op, branches[op["op"]], path="op"):
                if "maximum" in problem or "minimum" in problem:
                    number = re.match(r"op[^:]*: (-?[\d.]+) ", problem)
                    self.range_problems.append((i, op["op"], problem.split(": ", 1)[1].replace(
                        "the maximum", "the console's maximum").replace("the minimum", "the console's minimum"),
                        bool(number) and number.group(1) in typed))

    def fold_edits_of_added_channels(self):
        """An edit (`set`, `assign`, a rename, a re-patch, a stereo change) of a channel THIS intent
        adds is part of its add: the change set's `modify` is for what is already on the desk, and
        `patch.merge_change` refuses an edit of a channel that is not there yet. So the edit is
        written into the add, and said at INFO."""
        added = {_norm(e["name"]): e for e in self.cs["add"]["channels"]}
        kept = []
        for m in self.cs["modify"]:
            entry = None
            if m.get("object") == "channel":
                named = self.renamed.get(_norm(m.get("name")), m.get("name"))
                entry = added.get(_norm(named))
            if entry is None:
                kept.append(m)
                continue
            for path, value in m["fields"].items():
                node = entry
                *parents, leaf = path.split(".")
                for key in parents:
                    node = node.setdefault(key, {})
                node[leaf] = value
            if "source.stereo" in m["fields"]:
                self.settle_added_stereo(entry)
            self.infos.append(f"channel {entry['name']!r} is added by this intent, so the edit "
                              f"({m['change']}) is part of the add")
        self.cs["modify"] = kept

    def settle_added_stereo(self, entry):
        """A channel this intent adds that was made stereo or mono after its add: the socket pair
        the stereo rule needs, or the one socket kept, with the other half's holder named."""
        sockets = list(entry["patch"].get("sockets") or [])
        group = entry["patch"].get("group")
        if not entry["source"].get("stereo"):
            entry["patch"]["sockets"] = sockets[:1]
            entry["source"].pop("pair_input", None)
            return
        if len(sockets) == 2 or not sockets:
            return
        first = sockets[0]
        problem = None
        if first % 2 == 0:
            problem = (f"{group} {first} is an even socket, and a stereo pair starts on an odd one "
                       f"(a pair is {group} {first - 1}+{first}); name the odd pair")
        else:
            holder = next((c["name"] for c in self.channels if c is not entry
                           and (c.get("patch") or {}).get("group") == group
                           and first + 1 in ((c.get("patch") or {}).get("sockets") or [])), None)
            if holder:
                problem = (f"{group} {first + 1}, the other half of the pair, is used by channel {holder!r} "
                           "-- a stereo pair cannot be formed without it; name a free odd pair")
        if problem:
            self.refuse(0, f"channel {entry['name']!r} made stereo", problem)
            return
        entry["patch"]["sockets"] = [first, first + 1]
        self.infos.append(f"channel {entry['name']!r}: made stereo on {group} {first}+{first + 1}, the socket "
                          "after the one it is on, which nothing uses")

    def edit_in_place(self, i, op, what, base_c):
        name = base_c["name"]
        now = bool(base_c["source"].get("stereo"))
        stereo = now if op.get("stereo") is None else bool(op["stereo"])
        spec = op.get("patch")
        if spec and op.get("stereo") is None and not now and spec.get("count") == 2:
            # Two sockets named for a mono channel make it a stereo one, as they do for a new
            # channel: one physical fact gets the same answer however the request states it.
            stereo = True
            self.infos.append(f"channel {name!r}: two sockets were named, so it is made a stereo channel")
        fields = {}
        if op.get("patch"):
            self._rescan_sockets()
            group, sockets = self.stated_patch(i, what, op["patch"], 2 if stereo else 1, "in")
            if sockets is None:
                return None
            fields["patch"] = {"group": group, "sockets": sockets, "stated": True}
        if stereo != now:
            fields["source.stereo"] = stereo
        if not fields:
            self.infos.append(f"channel {name!r} is already {'stereo' if stereo else 'mono'} and "
                              "no socket was named: nothing to change")
            return None
        self.cs["modify"].append({"object": "channel", "name": name, "change": what, "fields": fields})
        if "patch" in fields:
            self.stated_sockets.add(_norm(name))   # a moved source keeps the engineer's patch
            for s in fields["patch"]["sockets"]:
                self.used[(group, s)] = name
        self.sentences.append(f"Move {name}.")
        return None

    def move_channel(self, i, op):
        name = op["name"]
        what = f"move_channel {name!r}"
        base_c = self.find_channel(name)
        if base_c is None:
            return self.refuse(i, what, "no channel of that name is on the desk")
        if not op.get("place"):
            # Not to another strip: the channel is EDITED in place (its `patch` and/or
            # `source.stereo`), not taken off the desk and added again. Whether a pair can
            # be formed, and what is chosen when no pair is named, is `patch.merge_change`'s
            # (the other half taken by another channel is refused naming that channel).
            return self.edit_in_place(i, op, what, base_c)
        channel = _as_added(copy.deepcopy(base_c))
        self.channels.remove(base_c)
        self._rescan_sockets()
        bank = channel.get("bank", "ch")
        if op.get("place"):
            n = self.strip_for(i, what, bank, op["place"], name)
            if n is None:
                return None
            channel["channel"] = n
        stereo = channel["source"].get("stereo") if op.get("stereo") is None else op["stereo"]
        if op.get("patch"):
            group, sockets = self.stated_patch(i, what, op["patch"], 2 if stereo else 1, "in")
            if sockets is None:
                return None
            channel["patch"] = {"group": group, "sockets": sockets, "stated": True}
        elif stereo is False and len(channel["patch"].get("sockets") or []) == 2:
            channel["patch"]["sockets"] = channel["patch"]["sockets"][:1]
            self.infos.append(f"channel {name!r}: made mono and no socket named, so it keeps the "
                              "first of its two sockets")
        if channel["source"].get("stereo") and not stereo:
            channel["source"]["stereo"] = False
            channel["source"].pop("pair_input", None)
        elif stereo and not channel["source"].get("stereo"):
            channel["source"]["stereo"] = True
            if len(channel["patch"].get("sockets") or []) == 1 and not op.get("patch"):
                group = channel["patch"].get("group")
                run = self.choose(group, 2) if group else None
                if run is None:
                    self.refuse(i, what, f"no free pair of {group} sockets for a stereo channel "
                                "(a pair starts on an odd socket)")
                    return None
                channel["patch"] = {"group": group, "sockets": run, "stated": False}
                self.infos.append(f"channel {name!r}: made stereo and moved, no pair named, so it "
                                  f"takes the first free {group} pair, {group} {run[0]}+{run[1]}")
        for s in channel["patch"].get("sockets") or []:
            self.used[(channel["patch"].get("group"), s)] = name
        self.stated_sockets.add(_norm(name))   # a moved source keeps the engineer's patch
        self.cs["drop"]["channels"].append(base_c["name"])
        self.cs["add"]["channels"].append(channel)
        self.channels.append(channel)
        self.sentences.append(f"Move {name}.")
        return None

    def assign(self, i, op):
        """Which DCAs, mute groups and sends an existing channel has: its lists with some added
        and some taken away, written as one edit of the channel. A group the desk lacks is made
        (as `add_channel` makes one); a send to a bus the desk lacks is refused naming it; taking
        away what was not there is said at INFO."""
        name = op["name"]
        what = f"assign {name!r}"
        found = self.find_channel(name)
        if found is None:
            return self.refuse(i, what, "no channel of that name is on the desk")
        fields = {}
        for key, section, word in (("dca", "dcas", "DCA"), ("mute_group", "mute_groups", "mute group")):
            add, drop = op.get(f"{key}_add") or [], op.get(f"{key}_remove") or []
            if not add and not drop:
                continue
            have = list(found.get(key) or [])
            for g in drop:
                match = next((h for h in have if _norm(h) == _norm(g)), None)
                if match is None:
                    self.infos.append(f"channel {found['name']!r} is not in the {g!r} {word}: nothing to take it out of")
                else:
                    have.remove(match)
            for g in add:
                if not any(_norm(h) == _norm(g) for h in have):
                    if self.named(section, g) is None and g not in self.cs["add"][section]:
                        self.check_name(i, what, g, structural=True)
                        self.cs["add"][section][g] = {}
                    have.append(self.named(section, g) or g)
            fields[key] = have
        if op.get("send_add") or op.get("send_remove"):
            sends = [dict(s) for s in found.get("bus_sends") or []]
            for b in op.get("send_remove") or []:
                keep = [s for s in sends if _norm(s["bus"]) != _norm(b)]
                if len(keep) == len(sends):
                    self.infos.append(f"channel {found['name']!r} has no send to {b!r}: nothing to remove")
                sends = keep
            for s in op.get("send_add") or []:
                bus = self.named("busses", s["bus"])
                if bus is None and s["bus"] not in self.cs["add"]["busses"]:
                    self.refuse(i, what, f"it is to send to {s['bus']!r}, and no bus of that name is on the "
                                "desk or added by this change")
                    continue
                self.range_check(i, what, f"send to {s['bus']!r} level_db", s.get("level_db"),
                                 facts.SEND_LEVEL_DB_RANGE)
                entry = {"bus": bus or s["bus"], "mode": s.get("mode"), "level_db": s.get("level_db")}
                sends = [x for x in sends if _norm(x["bus"]) != _norm(entry["bus"])] + [entry]
            fields["bus_sends"] = sends
        if not fields:
            return self.infos.append(f"assign {name!r} named nothing to change") or None
        self.cs["modify"].append({"object": "channel", "name": found["name"], "change": what,
                                  "fields": fields})
        self.sentences.append(f"Change the groups and sends of {name}.")
        return None

    def rename(self, i, op):
        kind, key = op["object"], _KEY[op["object"]]
        found = self.find_channel(op["name"]) if kind == "channel" else self.named(key, op["name"])
        if found is None:
            return self.refuse(i, f"rename {kind} {op['name']!r}", f"no {kind} of that name is on the desk")
        if not self.check_name(i, f"rename {kind} {op['name']!r}", op["new_name"],
                               structural=kind != "channel"):
            return None
        if kind == "channel" and any(e is found for e in self.cs["add"]["channels"]):
            # A channel this intent adds is renamed in its add, now, so the ops after this one
            # find it by its new name; the bookkeeping that is keyed by name moves with it.
            old, new = found["name"], op["new_name"]
            found["name"] = new
            self.renamed[_norm(old)] = new
            for earlier, current in list(self.renamed.items()):
                if _norm(current) == _norm(old):
                    self.renamed[earlier] = new
            self.cat[_norm(new)] = self.cat.pop(_norm(old), "")
            for names in (self.stated_sockets, self.gain_named):
                if _norm(old) in names:
                    names.discard(_norm(old))
                    names.add(_norm(new))
            if _norm(old) in self.positions:
                self.positions[_norm(new)] = self.positions.pop(_norm(old))
            for socket, holder in list(self.used.items()):
                if holder == old:
                    self.used[socket] = new
            self.infos.append(f"channel {old!r} is added by this intent, so it is added as {new!r}")
            self.sentences.append(f"Rename {op['name']} to {new}.")
            return None
        self.cs["modify"].append({"object": PATCH_WORD[kind],
                                  "name": found["name"] if kind == "channel" else found,
                                  "change": f"rename to {op['new_name']}", "fields": {"name": op["new_name"]}})
        self.sentences.append(f"Rename {op['name']} to {op['new_name']}.")
        return None

    def set_field(self, i, op):
        kind = op["object"]
        path = op["field"]
        what = f"set {kind} {op['name']!r} {path}"
        menu = settings(kind)
        if path not in menu:
            return self.refuse(i, what, f"a {kind.replace('_', ' ')} has no setting {path!r} a change "
                               f"can set (its menu: {', '.join(menu) or 'none'})")
        found = self.find_channel(op["name"]) if kind == "channel" else self.named(_KEY[kind], op["name"])
        if found is None and kind == "channel":
            members = self.group_members(op["name"])
            if members:
                return self.set_on_members(i, op, what, members)
        if found is None:
            return self.refuse(i, what, f"no {kind.replace('_', ' ')} of that name is on the desk")
        value = op["value"]
        if path in ("color", "source.model") and not self.check_free_text(
                i, what, "color" if path == "color" else "model", value):
            return None
        if path == "name" and not self.check_name(i, what, str(value), structural=kind != "channel"):
            return None
        problems = validate_schema(value, menu[path], path=path)
        if problems:
            return self.refuse(i, what, f"{value!r} is not allowed for {path}: " + "; ".join(problems[:2]))
        if path == "fader.fader_db":
            self.fader = True
        elif path == "fader.muted":
            self.mute = True
        elif path == "processing.gain_db":
            self.gain_named.add(_norm(found["name"] if kind == "channel" else found))
        self.cs["modify"].append({
            "object": PATCH_WORD[kind], "name": found["name"] if kind == "channel" else found,
            "change": f"set {path} to {value}", "fields": {path: value}})
        self.sentences.append(f"Set {path} of {op['name']} to {value}.")
        return None

    def group_members(self, name):
        """`(word, group name, [channel names])` when `name` is not a channel but is
        a DCA or a mute group on the desk ("HPF 100 on the vocals" names the Vocals
        DCA): the engineer means its members. A DCA wins over a mute group of the
        same name. Chosen here and said at INFO, not asked of the model."""
        for key, word in (("dcas", "DCA"), ("mute_groups", "mute group")):
            group = self.named(key, name)
            if group is not None:
                field = "dca" if key == "dcas" else "mute_group"
                members = [c["name"] for c in self.channels if group in (c.get(field) or [])]
                if members:
                    return word, group, members
        return None

    def set_on_members(self, i, op, what, members):
        word, group, names = members
        self.infos.append(f"{op['name']!r} is not a channel but is the {group!r} {word}: "
                          f"{op['field']} was set on its {len(names)} channels ({', '.join(names)})")
        for name in names:
            self.set_field(i, {**op, "name": name})

    def new_name(self, i, what, kind, name):
        """The name of a new bus, DCA, mute group or output (`atoo/intent_names.py`).

        The engineer's own name (every word in the request) is kept, and refused if
        it clashes with an object already there. A name the request
        did not give -- none, or one the model made up, or one that is garbage -- is
        derived from the request's words at INFO, the first free variant if taken."""
        key = _KEY[kind]
        taken = [n for n in self.base.get(key) or {} if n not in self.dropped[key]] + [
            n for n in self.cs["add"][key]]
        text = self.text
        word = PATCH_WORD[kind]
        if name and text is not None and intent_names.engineers_name(name, text):
            if name.casefold() in {t.casefold() for t in taken}:
                self.refuse(i, what, f"the name {name!r} is already a {word} on the desk")
                return None
            self.check_name(i, what, name, structural=True)
            return name
        if name and text is None:
            if name.casefold() in {t.casefold() for t in taken}:
                self.refuse(i, what, f"the name {name!r} is already a {word} on the desk")
                return None
            return name if self.check_name(i, what, name, structural=True) else None
        if name and name.casefold() not in {t.casefold() for t in taken} \
                and self.sanity.name_problem(name, structural=True) is None:
            return name        # the conventions' own name for it, and nothing else uses it
        derived, how = intent_names.derive(kind, text, taken)
        said = f"the model wrote {name!r}, which the request does not contain; " if name else ""
        self.infos.append(f"named the new {word} {derived!r} from {how}: {said}no name was given")
        return derived

    def made_already(self, i, kind, op) -> bool:
        """In a build, a bus, group or output named as one this show already makes (the Category
        table's DCA, the same group written twice) is that one: made once, its members joined,
        said at INFO. Allocating it twice runs the desk out of groups for nothing."""
        key = _KEY[kind]
        if not self.build or not op.get("name"):
            return False
        same = next((n for n in self.cs["add"][key] if _norm(n) == _norm(op["name"])), None)
        if same is None:
            return False
        self.infos.append(f"{PATCH_WORD[kind]} {op['name']!r} is already made by this show"
                          + (f" (as {same!r})" if same != op["name"] else "")
                          + ": made once" + (", its members joined" if op.get("members") else ""))
        if op.get("members") and kind != "output":
            self.pending_members.append((i, kind, same, op))
        return True

    def add_bus(self, i, op):
        if self.made_already(i, "bus", op):
            return None
        name = self.new_name(i, "add_bus", "bus", op.get("name"))
        if name is None:
            return None
        what = f"add_bus {name!r}"
        op = self.without_missing_preset(what, op)
        for field in ("color", "preset"):
            self.check_free_text(i, what, field, op.get(field))
        entry: dict = {}
        stereo = op.get("stereo")
        to = op.get("to") or {}
        if to.get("output"):
            spec = to["output"]
            group, sockets = self.stated_patch(i, what, spec, 2 if stereo else 1, "out")
            if sockets is None:
                return None
            if stereo is None and len(sockets) == 2:
                stereo = True
                self.infos.append(f"bus {name!r}: patched to two outputs and its width was not stated, "
                                  "so it is stereo")
            entry["destination"] = {"type": "dedicated_output", "label": name,
                                    "patch": {"group": group, "sockets": sockets, "stated": True}}
        else:
            entry["destination"] = {"type": "main"}
            if not to.get("main"):
                self.infos.append(f"bus {name!r}: no destination was named, so it goes to Main")
        entry["mono"] = None if stereo is None else not stereo
        if op.get("index") is not None:
            entry["index"] = op["index"]
        if op.get("color"):
            entry["color"] = op["color"]
        if op.get("preset"):
            entry["preset"] = op["preset"]
        self.cs["add"]["busses"][name] = entry
        self.new["busses"].add(name)
        if op.get("members"):
            self.pending_members.append((i, "bus", name, op))
        self.sentences.append(f"Add a bus {name}.")
        return None

    def add_group(self, i, op):
        kind = op["object"]
        if self.made_already(i, kind, op):
            return None
        name = self.new_name(i, f"add_group {kind}", kind, op.get("name"))
        if name is None:
            return None
        entry = {} if op.get("index") is None else {"index": op["index"]}
        self.cs["add"][_KEY[kind]][name] = entry
        if op.get("members"):
            self.pending_members.append((i, kind, name, op))
        self.sentences.append(f"Add a {PATCH_WORD[kind]} {name}.")
        return None

    def set_order(self, i, op):
        self.order = list(op["categories"])
        self.order_within = [_norm(n) for n in op.get("channels") or []]
        return None

    # -- once every channel exists -------------------------------------------

    def quoted(self, op, channel) -> bool:
        """Whether a build may leave out the input-list row of `channel`: the model must quote
        words of the conventions, the instructions or the row's own notes that say so (every row is
        built unless the engineer's words say otherwise). Otherwise the row is built, and said so."""
        row = self.rows.get(_norm((channel.get("source") or {}).get("input") or channel.get("name")))
        if row is None:
            return True                  # a strip that is not a row: the model's to leave out
        flat = lambda text: re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()  # noqa: E731
        quote = flat(op.get("quote"))
        if quote and quote in flat(f"{self.conventions_text} {row.notes}"):
            self.infos.append(f"input-list row {row.name!r} is left out, as the words it quotes say: "
                              f"{op['quote']!r}")
            return True
        self.infos.append(f"input-list row {row.name!r} is built: the model left it out "
                          + ("without quoting words that say so" if not quote else
                             "with a quote that is not in the conventions, the instructions or the row's notes"))
        return False

    def category_of(self, channel):
        """A channel's category: the one it was added with, else its input-list row's."""
        said = self.cat.get(_norm(channel.get("name")))
        if said:
            return said
        row = self.rows.get(_norm((channel.get("source") or {}).get("input") or channel.get("name")))
        return (row.category if row is not None else "") or ""

    def apply_order(self):
        """The strips added by this intent, in the order of the categories it listed (rows of a
        category keep their order; a category not listed goes after the listed ones). The numbers
        the strips held are handed out again in that order."""
        if not self.order:
            return
        rank = {_norm(c): n for n, c in enumerate(self.order)}
        if self.table is not None:      # a category word the table knows by another alias
            for n, c in enumerate(self.order):
                entry = self.table.entry_for(c)
                for alias in (entry or {}).get("aliases", []):
                    rank.setdefault(_norm(alias), n)
        for bank in ("ch", "aux"):
            added = [c for c in self.cs["add"]["channels"] if c.get("bank", "ch") == bank]
            numbers = sorted(c["channel"] for c in added)
            within = {name: n for n, name in enumerate(self.order_within)}
            ranked = sorted(added, key=lambda c: (rank.get(_norm(self.category_of(c)), len(rank)),
                                                  within.get(_norm(c.get("name")), len(within))))
            for channel, n in zip(ranked, numbers):
                channel["channel"] = n
        self.infos.append("the strips are in the order of the categories " + ", ".join(self.order)
                          + (", the channels " + ", ".join(self.order_within) + " first in theirs"
                             if self.order_within else "")
                          + ", and otherwise in the input list's order")

    def resolve_members(self):
        """Groups and buses that took `members`: every channel they name, by category, by name or
        all, gets the group (or a send to the bus). Said at INFO with the count."""
        edits: dict[str, dict] = {}
        for i, kind, name, op in self.pending_members:
            members = op["members"]
            cats = {_norm(c) for c in members.get("categories") or []}
            if self.table is not None:
                for c in list(cats):
                    entry = self.table.entry_for(c)
                    cats |= {_norm(a) for a in (entry or {}).get("aliases", [])}
            wanted = {_norm(n) for n in members.get("channels") or []}
            for n in wanted:
                if self.find_channel(n) is None:
                    self.refuse(i, f"{kind} {name!r}", f"its member {n!r} is not a channel of the desk")
            matched = [c for c in self.channels
                       if members.get("all") or _norm(c.get("name")) in wanted
                       or _norm(self.category_of(c)) in cats]
            if not matched:
                self.infos.append(f"{kind.replace('_', ' ')} {name!r} named members, and no channel "
                                  "matched them: it has none")
                continue
            field = {"dca": "dca", "mute_group": "mute_group"}.get(kind)
            for c in matched:
                held = next((e for e in self.cs["add"]["channels"] if e is c), None)
                target = held if held is not None else edits.setdefault(
                    c["name"], {"channel": c, "fields": {}})["fields"]
                if field:
                    have = list(target.get(field) or (c.get(field) or [] if held is None else []))
                    if name not in have:
                        have.append(name)
                    target[field] = have
                else:
                    sends = [dict(x) for x in target.get("bus_sends") or c.get("bus_sends") or []]
                    sends = [x for x in sends if _norm(x.get("bus")) != _norm(name)]
                    sends.append({"bus": name, "mode": op.get("mode"), "level_db": op.get("level_db")})
                    target["bus_sends"] = sends
            self.infos.append(f"{kind.replace('_', ' ')} {name!r}: {len(matched)} member channel(s) "
                              f"from {self.member_words(members)}")
        for entry in edits.values():
            self.cs["modify"].append({"object": "channel", "name": entry["channel"]["name"],
                                      "change": "groups and sends from members", "fields": entry["fields"]})

    @staticmethod
    def member_words(members):
        if members.get("all"):
            return "all channels"
        parts = []
        if members.get("categories"):
            parts.append("the categories " + ", ".join(members["categories"]))
        if members.get("channels"):
            parts.append("the channels " + ", ".join(members["channels"]))
        return " and ".join(parts) or "nothing"

    def add_output(self, i, op):
        if self.made_already(i, "output", op):
            return None
        name = self.new_name(i, "add_output", "output", op.get("name"))
        if name is None:
            return None
        what = f"add_output {name!r}"
        entry = {"kind": op["object"]}
        if op.get("patch"):
            group, sockets = self.stated_patch(i, what, op["patch"], 1, "out")
            if sockets is None:
                return None
            entry["patch"] = {"group": group, "sockets": sockets, "stated": True}
        self.cs["add"]["outputs"][name] = entry
        self.sentences.append(f"Add an output {name}.")
        return None


_BOX_RE = re.compile(r"\bAES50[\s-]?([ABC])\b", re.IGNORECASE)


def input_boxes(conventions_text: str | None, input_list_text: str | None) -> tuple:
    """The stage boxes (AES50 groups `A`, `B`, `C`) a channel no socket was named for may overflow
    to once the local inputs are full: one the input list already takes inputs from, then one a
    sentence of the conventions names for inputs ("patch to local inputs 1-24, then overflow to
    AES50-A from 1"). A box neither names is never chosen: nobody said it is there."""
    found: list[str] = []
    for r in input_list_module.parse_input_list(input_list_text) if input_list_text else []:
        spec = input_list_module.parse_socket_spec(r.patch) if r.patch else None
        if spec and spec[0] in ("A", "B", "C") and spec[0] not in found:
            found.append(spec[0])
    for sentence in re.split(r"(?<=[.!?])\s+|\n", conventions_text or ""):
        if re.search(r"\binputs?\b", sentence, re.IGNORECASE) and not re.search(r"\boutputs?\b", sentence, re.IGNORECASE):
            for box in _BOX_RE.findall(sentence):
                if box.upper() not in found:
                    found.append(box.upper())
    return tuple(found)


def compile_intent(intent: dict, base_plan: dict, console_model: str, *, text: str | None = None,
                   category_table=None, aes50_devices: dict | None = None,
                   input_list_text: str | None = None, known_presets=None,
                   conventions_text: str | None = None, build: bool = False,
                   reserved_user_slots=()):
    """`(change_set, infos)` for `intent` on `base_plan`, or `IntentRefused`. `build`: the intent
    is for a whole show, so a channel named like an input-list row is built from that row.
    `reserved_user_slots`: the USR slots the show's `user.csv` defines, which a stereo pair
    routed through a user patch never takes (`user_patch`).

    `text` is the engineer's request as typed: `patch.merge_change` reads it
    for the decisions that are about words (insert, a fader or mute named); an
    intent compiled without it gets a short sentence made from its ops.
    `aes50_devices` is the rig (`{"A": "S16"}`) that bounds the stage box's
    sockets. `category_table` is a checked `category_table.Table`.
    `input_list_text` (the show's input list as text) and `known_presets` (the
    library's preset names) and `conventions_text` (the conventions and the show's
    instructions, whose words a new bus, group or output may use) are what
    `sanity.Sanity` accounts for names,
    categories, models and presets with, besides `text` and the desk."""
    schema = intent_schema(console_model, build=build)
    violations = explain(intent, without_bounds(schema), validate_schema)
    if violations:
        raise IntentRefused([f"the intent is not well formed: {v}" for v in violations[:6]])
    if not intent["ops"]:
        # Nothing to compile is not "nothing to do": a request was made. A model that declines
        # in its notes (an object the desk lacks, a request it will not guess at) has refused
        # in prose; the engineer is told so, with its words, and nothing is written.
        said = " ".join(n.strip() for n in intent.get("notes") or [] if str(n).strip())
        raise IntentRefused(["the intent has no operation, so nothing would be changed"
                             + (f"; the model said: {said}" if said else "")])
    sanity = sanity_mod.Sanity(base_plan, text=text, input_list_text=input_list_text,
                               category_table=category_table, known_presets=known_presets,
                               conventions_text=conventions_text)
    if intent.get("categories"):
        parsed = category_table_module.from_entries(intent["categories"], resolved_name="the intent")
        if parsed.table is None:
            raise IntentRefused([f"the intent's categories are not usable: {parsed.reason}"])
        category_table = parsed.table
    c = _Compile(base_plan, console_model, text, category_table, aes50_devices, sanity)
    c.build = build
    c.reserved_user_slots = tuple(reserved_user_slots or ())
    c.input_boxes = input_boxes(conventions_text, input_list_text)
    c.conventions_text = conventions_text or ""
    if input_list_text:
        c.rows = {_norm(r.name): r for r in input_list_module.parse_input_list(input_list_text)}
        for r in c.rows.values():
            spec = input_list_module.parse_socket_spec(r.patch) if r.patch else None
            if spec:
                c.row_sockets[spec] = r.name
    handlers = {op: getattr(c, method) for op, method in OP_HANDLERS.items()}
    c.reserve(intent["ops"])
    c.check_ranges(intent["ops"], schema)
    for i, op in enumerate(intent["ops"], start=1):
        try:
            handlers[op["op"]](i, op)
        except (KeyError, TypeError, ValueError) as exc:  # a well-formed op the schema let through
            c.refuse(i, op["op"], f"the op is incomplete or malformed ({type(exc).__name__}: {exc})")
    c.apply_order()
    c.resolve_members()
    c.fold_edits_of_added_channels()
    for i, what, why, final in c.range_problems:      # only where the op's own check said nothing
        if not any(r.startswith(f"op {i} ") for r in c.refused):
            c.refuse(i, what, why, final=final)
    if c.refused:
        raise IntentRefused(c.refused, c.final, c.refused_ops)
    cs = c.cs
    label = intent["name"]
    if not sanity.label_ok(label):
        label = patch.default_name(text or " ".join(c.sentences))
        c.infos.append(f"the change's name had characters that appear nowhere in the request, the "
                       f"input list or the desk, so the first words of the request were used: {label!r}")
    cs["name"] = label[:patch.CHANGE_NAME_MAX]
    cs["notes"] = []
    for note in intent.get("notes") or []:
        if sanity.label_ok(note):
            cs["notes"].append(note)
        else:
            c.infos.append("a note of the model's was left out: it had characters that appear "
                           "nowhere in the request, the input list or the desk")
    if c.user_sources:
        cs[patch.USER_SOURCES_KEY] = c.user_sources
    cs[patch.TEXT_KEY] = ((text or "").strip() or " ".join(c.sentences)).strip()
    cs[patch.ASKED_KEY] = patch.Asked(
        insert=c.insert, positions=dict(c.positions), sockets=set(c.stated_sockets),
        fader=c.fader, mute=c.mute, gain=set(c.gain_named), picked_by="Atoo").to_dict()
    return cs, c.infos


def apply_intent(intent: dict, base_plan: dict, console_model: str, **kwargs):
    """`(MergeResult, infos)`: `compile_intent`, the change-set validator
    (cuts long names, reads nulls as unstated) and `patch.merge_change`, all as
    `atoo patch` runs them. The facts the compile stated travel in the change set."""
    aes50 = kwargs.get("aes50_devices")
    change_set, infos = compile_intent(intent, base_plan, console_model, **kwargs)
    infos = list(infos)
    text = change_set.get(patch.TEXT_KEY)  # the validator keeps only the model's keys
    change_set = patch.validate_change_set(change_set, infos=infos)
    merge = patch.merge_change(base_plan, change_set, console_model=console_model,
                               text=text, aes50_devices=aes50)
    return merge, infos + merge.infos
