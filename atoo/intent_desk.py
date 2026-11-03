"""The desk as a graph, and the slice of it a request needs (`atoo patch --intent`).

The change-set path puts the whole plan on the desk into every `atoo patch`
prompt. With the intent compiler the model no longer writes sockets, indices or sends, so
what it must SEE shrinks to: every object's name and slot (so it can say
which one the engineer means), what is free, and the details of what the
request touches. Code never relies on the slice: `compile_intent` still
checks every name, socket and index against the whole base, so a slice that
is too small makes the model's intent refused or widened, never wrong.

    index_desk(plan, aes50_devices=None, console_model=None) -> graph
    hints_from_request(text, graph) / hints_from_intent(intent) -> hints
    slice_for(hints, graph) -> slice   (a dict; `compact(slice)` is its JSON)

One code path for all three consoles: the only console-specific numbers are
the socket counts, which come from `console_facts`.

Node ids: `ch:N` `aux:N` (strips), `bus:N`, `dca:N`, `mgrp:N`, `main:N`
`mtx:N` (outputs), `in:G:N` (an occupied input socket), `out:G:N` (an
occupied output socket). Link kinds: `send` (strip -> bus, with mode and
level), `main` (strip -> main), `member` (strip or bus -> dca or mgrp),
`patch_in` (strip -> in socket), `routes_to` (bus -> main or out socket),
`patch_out` (output -> out socket).
"""

from __future__ import annotations

import json
import re

from atoo import apply as apply_module
from atoo import console_facts as facts

from atoo.patch import _INSERT_WORDS  # the words merge_change itself reads

_PLAN_KEY = {"bus": "busses", "dca": "dcas", "mgrp": "mute_groups"}
_WORDS = {"bus": "bus", "dca": "dca", "mgrp": "mute group", "ch": "channel", "aux": "aux",
          "main": "main", "mtx": "matrix"}


def compact(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _ranges(numbers) -> str:
    """[10, 16, 17, 18] -> "10,16-18"."""
    out, run = [], []
    for n in sorted(numbers):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(run)
        run = [n]
    if run:
        out.append(run)
    return ",".join(str(r[0]) if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in out)


def _strip_id(channel: dict) -> str:
    return f"{channel.get('bank', 'ch')}:{channel['channel']}"


def _out_id(output: dict) -> str:
    return f"{'mtx' if output.get('kind') == 'matrix' else 'main'}:{output.get('index')}"


# --------------------------------------------------------------------------
# The index
# --------------------------------------------------------------------------


def index_desk(plan: dict, *, aes50_devices: dict | None = None, console_model: str | None = None,
               extra_occupied=()) -> dict:
    """`{"nodes", "links", "console_model", "boxes", "extra"}` for `plan`.

    `extra_occupied` is `[(group, socket, who)]` the plan does not know about
    (a strip somebody named by hand, read from the desk by `amend`)."""
    model = console_model or ((plan.get("meta") or {}).get("console_model"))
    nodes: dict[str, dict] = {}
    links: list[dict] = []
    by_name = {key: {} for key in ("ch", "aux", "bus", "dca", "mgrp", "out")}

    def add(node_id, kind, name, **fields):
        nodes[node_id] = {"id": node_id, "type": kind, "name": name, **fields}
        return node_id

    for kind, key in _PLAN_KEY.items():
        for name, obj in (plan.get(key) or {}).items():
            if isinstance(obj, dict) and isinstance(obj.get("index"), int):
                node_id = add(f"{kind}:{obj['index']}", kind, name)
                by_name[kind][name] = node_id
                if kind == "bus":
                    nodes[node_id]["width"] = None if obj.get("mono") is None else (
                        "mono" if obj["mono"] else "stereo")
                for g in obj.get("dca") or []:
                    links.append({"from": node_id, "kind": "member", "to": ("dca", g)})
                for g in obj.get("mute_group") or []:
                    links.append({"from": node_id, "kind": "member", "to": ("mgrp", g)})
    for name, obj in (plan.get("outputs") or {}).items():
        if isinstance(obj, dict) and isinstance(obj.get("index"), int):
            node_id = add(_out_id(obj), "output", name, out_kind=obj.get("kind"))
            by_name["out"][name] = node_id
            _patch_link(links, nodes, node_id, "patch_out", obj.get("patch"), "out")
    for bus_name, obj in (plan.get("busses") or {}).items():
        if not isinstance(obj, dict) or bus_name not in by_name["bus"]:
            continue
        src = by_name["bus"][bus_name]
        for dest in obj.get("destinations") or [obj.get("destination")]:
            if not isinstance(dest, dict):
                continue
            if dest.get("type") in ("main", "matrix") and isinstance(dest.get("index"), int):
                links.append({"from": src, "kind": "routes_to",
                              "to": f"{'mtx' if dest['type'] == 'matrix' else 'main'}:{dest['index']}"})
            elif dest.get("type") == "dedicated_output":
                _patch_link(links, nodes, src, "routes_to", dest.get("patch"), "out")
    for c in plan.get("channels") or []:
        if not isinstance(c, dict) or not isinstance(c.get("channel"), int):
            continue
        bank = c.get("bank", "ch")
        node_id = add(_strip_id(c), bank, c.get("name"),
                      stereo=bool((c.get("source") or {}).get("stereo")))
        by_name[bank][c.get("name")] = node_id
        _patch_link(links, nodes, node_id, "patch_in", c.get("patch"), "in")
        for s in c.get("bus_sends") or []:
            links.append({"from": node_id, "kind": "send", "to": ("bus", s.get("bus")),
                          "mode": s.get("mode"), "level_db": s.get("level_db")})
        for r in c.get("main_routes") or []:
            links.append({"from": node_id, "kind": "main", "to": f"main:{r.get('index', 1)}"})
        for g in c.get("dca") or []:
            links.append({"from": node_id, "kind": "member", "to": ("dca", g)})
        for g in c.get("mute_group") or []:
            links.append({"from": node_id, "kind": "member", "to": ("mgrp", g)})
    for group, socket, who in extra_occupied:
        nodes.setdefault(f"in:{group}:{socket}", {"id": f"in:{group}:{socket}", "type": "in",
                                                  "name": f"{group} {socket}", "occupant": who})
    # Resolve name references to ids; a reference to nothing stays a name.
    for link in links:
        if isinstance(link["to"], tuple):
            kind, name = link["to"]
            link["to"] = by_name[kind].get(name, f"?{kind}:{name}")
    return {"nodes": nodes, "links": links, "by_name": by_name, "console_model": model,
            "boxes": apply_module.box_limits(aes50_devices)}


def _patch_link(links, nodes, src, kind, patch, direction):
    if not isinstance(patch, dict) or patch.get("group") in (None, "OFF"):
        return
    for socket in patch.get("sockets") or []:
        sock = f"{direction}:{patch['group']}:{socket}"
        nodes.setdefault(sock, {"id": sock, "type": direction, "name": f"{patch['group']} {socket}"})
        links.append({"from": src, "kind": kind, "to": sock})


def neighbours(graph: dict, node_id: str, *, kinds=None, direction="both") -> list[tuple[dict, dict]]:
    """`[(link, other node)]` around `node_id`."""
    out = []
    for link in graph["links"]:
        if kinds and link["kind"] not in kinds:
            continue
        other = link["to"] if link["from"] == node_id and direction in ("both", "out") else (
            link["from"] if link["to"] == node_id and direction in ("both", "in") else None)
        if other is not None and other in graph["nodes"]:
            out.append((link, graph["nodes"][other]))
    return out


def occupant_of_socket(graph: dict, group: str, socket: int, direction="in") -> list[dict]:
    node_id = f"{direction}:{group}:{socket}"
    node = graph["nodes"].get(node_id)
    if node is None:
        return []
    owners = [n for _l, n in neighbours(graph, node_id) if n["type"] not in ("in", "out")]
    return owners or ([{"name": node["occupant"], "id": node_id}] if node.get("occupant") else [])


# --------------------------------------------------------------------------
# What is free: always in the slice
# --------------------------------------------------------------------------


def free_map(graph: dict, plan_groups: set[str] | None = None) -> dict:
    """What a request could collide with, as compact ranges: free input and
    output sockets of the groups in play (bounded by the console's panel and
    by the stage box on an AES50 port), free strips, and the lowest free
    index of each kind."""
    model = graph["console_model"]
    taken_in = {tuple(n["id"].split(":")[1:]) for n in graph["nodes"].values() if n["type"] == "in"}
    taken_out = {tuple(n["id"].split(":")[1:]) for n in graph["nodes"].values() if n["type"] == "out"}
    groups_in = sorted({g for g, _ in taken_in} | set(plan_groups or ()) | {"LCL"})
    groups_out = sorted({g for g, _ in taken_out} | {"LCL"})
    out = {"in": {}, "out": {}, "strip": {}, "index": {}}
    for direction, groups, taken in (("in", groups_in, taken_in), ("out", groups_out, taken_out)):
        for group in groups:
            try:
                limit = (facts.input_socket_limit if direction == "in" else facts.output_socket_limit)(
                    group, model)
            except facts.UnknownConsoleModel:
                limit = 0
            box = graph["boxes"].get(group)
            if box:
                limit = min(limit, box[1 if direction == "in" else 2])
            if limit:
                out[direction][group] = _ranges(
                    n for n in range(1, limit + 1) if (group, str(n)) not in taken) or "none"
    for bank in ("ch", "aux"):
        used = {int(n["id"].split(":")[1]) for n in graph["nodes"].values() if n["type"] == bank}
        out["strip"][bank] = _ranges(set(range(1, facts.CAPACITY[bank] + 1)) - used) or "none"
    for kind, cap in (("bus", "bus"), ("dca", "dca"), ("mgrp", "mgrp")):
        used = {int(n["id"].split(":")[1]) for n in graph["nodes"].values() if n["type"] == kind}
        out["index"][kind] = _ranges(set(range(1, facts.CAPACITY[cap] + 1)) - used) or "none"
    return out


# --------------------------------------------------------------------------
# Hints: what a request names
# --------------------------------------------------------------------------

_SOCKET = re.compile(
    r"(?<![A-Za-z0-9])(?P<g>LCL|AUX|SC|USB|CRD|MOD|AES50-?[ABC]|AES|PLAY|[ABC])\s?(?P<a>\d+)"
    r"(?:\s?[-–]\s?(?P<b>\d+))?(?![A-Za-z])", re.I)
_UPPER_ONLY = {"A", "B", "C"}
_NUMBERED = re.compile(
    r"\b(?P<w>bus(?:ses)?|mute\s*groups?|mutegroups?|dcas?|channels?|ch|strips?|aux|mains?|matrix|mtx)"
    r"\s*(?P<n>\d+(?:\s*(?:,|and|&|to|-)\s*\d+)*)", re.I)
_KIND_OF = {"bus": "bus", "mute": "mgrp", "dca": "dca", "chan": "ch", "ch": "ch", "stri": "ch",
            "aux": "aux", "main": "main", "matr": "mtx", "mtx": "mtx"}
#: The kind of request each intent op stands for, when an intent widens the slice
#: (`hints_from_intent`). One entry for every op in `intent_schema`: a test holds it to that, so
#: an op added to the vocabulary cannot be missed here again.
OP_HINT = {"add_channel": "add", "add_bus": "bus", "add_group": "add", "add_output": "output",
           "move_channel": "move", "drop": "drop", "rename": "rename", "set": "set", "assign": "set",
           "order": "add"}

_OPWORDS = {
    "insert": _INSERT_WORDS,
    "drop": re.compile(r"\b(?:remove|drop|delete|clear|get rid of|take out|scrap)\b", re.I),
    "add": re.compile(r"\b(?:add|new|another|need|put)\b|\bon\s+(?:LCL|A|B|C)\b", re.I),
    "move": re.compile(r"\bmove\b", re.I),
    "rename": re.compile(r"\brename\b|\bcall(?:ed)?\b", re.I),
    "set": re.compile(r"\b(?:set|hpf|gain|trim|fader|mute|unmute|level|-?\d+\s?db)\b", re.I),
    "stereo": re.compile(r"\bstereo\b|\bpair\b|\bL/?R\b|\b[A-Z]{1,3}\s?\d+\s?[-–]\s?\d+\b", re.I),
    "bus": re.compile(r"\b(?:bus|send|iem|wedge|monitor|mix|fx|reverb|verb|aux)\b", re.I),
    "output": re.compile(r"\b(?:output|matrix|main|pa|patch(?:ed)? to)\b", re.I),
}


def hints_from_request(text: str, graph: dict) -> dict:
    """What the request names, without a model: object names, numbered
    objects ("bus 5 and 6"), sockets ("A 16", "LCL 3-4"), and the op words."""
    text = text or ""
    names = []
    for kind in ("ch", "aux", "bus", "dca", "mgrp", "out"):
        for name, node_id in graph["by_name"][kind].items():
            if name and re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, re.I):
                names.append(node_id)
    numbered = []
    for m in _NUMBERED.finditer(text):
        word = m.group("w").lower().replace(" ", "")
        kind = next(v for k, v in _KIND_OF.items() if word.startswith(k))
        nums = [int(x) for x in re.findall(r"\d+", m.group("n"))]
        if re.search(r"to|-", m.group("n")) and len(nums) == 2 and nums[0] < nums[1]:
            nums = list(range(nums[0], nums[1] + 1))
        numbered += [f"{kind}:{n}" for n in nums]
    sockets = []
    for m in _SOCKET.finditer(text):
        g = m.group("g").upper().replace("AES50-", "").replace("AES50", "")
        if m.group("g") in ("a", "b", "c") or (g in _UPPER_ONLY and m.group("g") != g):
            continue  # an article, not AES50-A
        a = int(m.group("a"))
        b = int(m.group("b")) if m.group("b") else a
        sockets += [(g, n) for n in range(a, max(a, b) + 1)]
    # "after Snare" lands on the strip below Snare's: whoever stands there is
    # what the new channel meets ("before Kick" lands on Kick's own).
    for m in re.finditer(r"\b(after|behind|below|following)\s+(?:the\s+)?([^,.;]+)", text, re.I):
        words = m.group(2).split()
        for count in range(min(len(words), 4), 0, -1):
            beside = graph["by_name"]["ch"].get(" ".join(words[:count]).strip(" '\""))
            if beside is not None:
                numbered.append(f"ch:{int(beside.split(':')[1]) + 1}")
                break
    ops = {k for k, rx in _OPWORDS.items() if rx.search(text)}
    return {"names": names, "numbered": list(dict.fromkeys(numbered)), "sockets": sockets,
            "ops": ops, "text": text}


def hints_from_intent(intent: dict, graph: dict) -> dict:
    """The same hints from an intent: for a second, wider look once a first
    intent exists."""
    names, numbered, sockets, ops = [], [], [], set()
    for op in intent.get("ops") or []:
        ops.add(OP_HINT[op["op"]])
        for key in ("name", "after", "before"):
            value = op.get(key) or (op.get("place") or {}).get(key)
            for kind in ("ch", "aux", "bus", "dca", "mgrp", "out"):
                if value in graph["by_name"][kind]:
                    names.append(graph["by_name"][kind][value])
        if op.get("index") is not None and op.get("op") == "drop":
            numbered.append(f"{ {'channel': 'ch', 'bus': 'bus', 'dca': 'dca', 'mute_group': 'mgrp', 'output': 'main'}[op['object']] }:{op['index']}")
        for spec in (op.get("patch"), (op.get("to") or {}).get("output")):
            if spec:
                count = spec.get("count") or 1
                sockets += [(spec["group"], n) for n in range(spec["first"], spec["first"] + count)]
        if (op.get("place") or {}).get("at"):
            numbered.append(f"ch:{op['place']['at']}")
        if (op.get("place") or {}).get("renumber"):
            ops.add("insert")
    return {"names": names, "numbered": numbered, "sockets": sockets, "ops": ops, "text": ""}


# --------------------------------------------------------------------------
# The slice
# --------------------------------------------------------------------------


def _card(graph: dict, node: dict) -> dict:
    """What the model is shown of a touched node."""
    nid = node["id"]
    card: dict = {"id": nid, "name": node.get("name")}
    kind = node["type"]
    if kind in ("ch", "aux"):
        card["stereo"] = node.get("stereo")
        card["in"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"patch_in"}, direction="out")]
        card["sends"] = [f"{graph['nodes'][l['to']]['name']} {l['mode']} {l['level_db']}"
                         for l, _n in neighbours(graph, nid, kinds={"send"}, direction="out")
                         if l["to"] in graph["nodes"]]
        card["groups"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"member"}, direction="out")]
        card["main"] = bool(neighbours(graph, nid, kinds={"main"}, direction="out"))
    elif kind == "bus":
        card["width"] = node.get("width")
        card["to"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"routes_to"}, direction="out")]
        card["senders"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"send"}, direction="in")]
        card["groups"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"member"}, direction="out")]
    elif kind in ("dca", "mgrp"):
        card["members"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"member"}, direction="in")]
    elif kind == "output":
        card["out"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"patch_out"}, direction="out")]
        card["fed_by"] = [n["name"] for _l, n in neighbours(graph, nid, kinds={"routes_to"}, direction="in")]
    return card


def slice_for(hints: dict, graph: dict, *, members: bool = False) -> dict:
    """The slice: always the index of names and slots and the free map; the
    cards of what the request touches; and the neighbours the op can move.

    **Always** (so the model is never blind to something it can collide
    with): every name with its slot; free sockets per group in play, free
    strips, lowest free bus/DCA/mute-group indices. **Per request**: a card
    for each named object, each numbered object, and the occupant of each
    named socket and of its stereo-pair neighbour; a bus card lists who sends
    into it and a DCA / mute group card lists its members (so a drop is not
    blind to whoever it moves); an insert or renumber adds the cards of the
    run of strips it pushes down."""
    wanted: dict[str, str] = {}   # card id -> why

    def want(node_id, why):
        if node_id in graph["nodes"] and node_id not in wanted:
            wanted[node_id] = why

    for node_id in hints["names"]:
        want(node_id, "named")
    for node_id in hints["numbered"]:
        want(node_id, "numbered")
    text = hints.get("text", "").lower()
    # an input or an output, when the request says which; else both
    directions = ("out",) if "output" in text and "input" not in text else (
        ("in",) if "input" in text and "output" not in text else (
            ("in", "out") if hints["ops"] & {"bus", "output"} else ("in",)))
    for group, socket in hints["sockets"]:
        # the socket and its stereo-pair neighbour: a pair is odd-even
        for partner in (socket, socket + 1 if socket % 2 else socket - 1):
            for direction in directions:
                for owner in occupant_of_socket(graph, group, partner, direction):
                    want(owner.get("id"), f"on {group} {partner}")
    if "insert" in hints["ops"]:
        starts = [int(i.split(":")[1]) for i in wanted if i.startswith("ch:")] + [
            int(i.split(":")[1]) for i in hints["numbered"] if i.startswith("ch:")]
        if starts:
            n = min(starts)
            while f"ch:{n}" in graph["nodes"]:
                want(f"ch:{n}", "pushed down by the insert")
                n += 1
    index = {key: {n: node_id.split(":")[1] for n, node_id in names.items()}
             for key, names in graph["by_name"].items() if names}
    groups_in_play = {g for g, _ in hints["sockets"]}
    if members:
        # engineers address sets by group ("the kit", "the vocals"): who is in each
        index["members"] = {
            f"{n['type']}:{n['name']}": [m["name"] for _l, m in neighbours(
                graph, n["id"], kinds={"member"}, direction="in")]
            for n in graph["nodes"].values() if n["type"] in ("dca", "mgrp")}
    return {
        "index": index,
        "free": free_map(graph, groups_in_play),
        "cards": [_card(graph, graph["nodes"][i]) for i in wanted],
        "why": wanted,
    }


def slice_json(sl: dict) -> str:
    """What is sent: the slice without the bookkeeping."""
    return compact({k: v for k, v in sl.items() if k != "why"})


def covered(sl: dict, graph: dict, node_id: str) -> str | None:
    """How the slice covers `node_id`: "card", "listed" (named inside the card
    of a neighbour, as a bus's senders or a DCA's members), "index" (named in
    the index only), or None."""
    if node_id in {c["id"] for c in sl["cards"]}:
        return "card"
    name = graph["nodes"][node_id].get("name")
    for c in sl["cards"]:
        if any(name in (v if isinstance(v, list) else []) for k, v in c.items() if k in ("senders", "members")):
            return "listed"
    key = {"main": "out", "mtx": "out"}.get(node_id.split(":")[0], node_id.split(":")[0])
    if name in sl["index"].get(key, {}):
        return "index"
    return None
