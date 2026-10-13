#!/usr/bin/env python3
"""Recover the Demo's generator reply from a plan a model built.

    python3 tools/demo_reply_from_plan.py starter/demo-show/plan.json tools/demo_show.reply.json

The Demo show is rebuilt with no model (`tools/build_demo_show.py`): it
plays `tools/demo_show.reply.json` back through `atoo build`. When
the maintainer rebuilds the Demo with a real model instead, his plan is
the content to keep, but a build does not save the model's reply. This
writes a reply that, played back, gives that plan again: the same
channels, busses, DCAs, mute groups, outputs and notes, field for field.

It writes the reply in the compact form a model writes (the input-list
row by name, a stereo pair by its second row, each bus's senders as
lists) and leaves out what code writes: channel numbers, sockets copied
off the input list, the patch and numbering provenance, preset values.
Two of the build's own `repair` notes are reproduced by repeating the
slip that caused them (an omitted `unassigned_inputs`, a `stated` on an
instruction-built strip's patch), so the notes come back too.

Then run `tools/build_demo_show.py`; its docstring has the whole recipe.
"""

from __future__ import annotations

import json
import re
import sys

#: Channel provenance code writes for an input-list row; left out of the
#: reply so the rebuild writes it afresh.
CODE_PROVENANCE = {"patch", "channel", "input"}
#: ... and for a strip built from the instructions (its `channel` line is
#: the model's).
CODE_PROVENANCE_INSTRUCTED = {"input", "patch"}


def _bus_cites(channel: dict, busses: list[str]) -> dict[str, str]:
    """A channel's `bus_sends` provenance, `"<bus>: <cite>; <bus>: ..."`,
    split back into each bus's cite. A cite may itself hold "; ", so the
    split is at a known bus name only."""
    text = (channel.get("provenance") or {}).get("bus_sends") or ""
    names = "|".join(re.escape(b) for b in busses)
    parts = re.split(rf"(?:^|; )({names}): ", text)
    return dict(zip(parts[1::2], parts[2::2]))


def reply_from_plan(plan: dict) -> dict:
    notes = plan.get("notes") or []
    repaired = " ".join(n.get("text", "") for n in notes if n.get("source") == "repair")

    channels = []
    for c in plan["channels"]:
        source = c["source"]
        if source.get("from") == "instructions":
            keep_stated = "dropped 'stated'" in repaired
            r = {"input": source["input"], "quote": source["quote"], "bank": c["bank"],
                 "channel": c["channel"], "name": c["name"], "stereo": source["stereo"],
                 "patch": {k: v for k, v in c["patch"].items()
                           if k != "stated" or keep_stated}}
            code = CODE_PROVENANCE_INSTRUCTED
        else:
            r = {"input": source["input"]}
            if source.get("pair_input"):
                r["pair"] = source["pair_input"]
                r["stereo"] = True
            r["name"] = c["name"]
            code = CODE_PROVENANCE
        if c.get("color") is not None:
            r["color"] = c["color"]
        r["processing"] = {k: v for k, v in c["processing"].items()
                           if v is not None and k not in ("preset_values", "preset_library")}
        r["fader"] = {k: v for k, v in c["fader"].items() if v is not None}
        for k in ("dca", "mute_group", "main_routes"):
            r[k] = c[k]
        r["provenance"] = {k: v for k, v in c["provenance"].items()
                           if k not in code and k != "bus_sends"}
        channels.append(r)

    names = list(plan["busses"])
    busses = []
    for name, b in plan["busses"].items():
        groups: dict[tuple, list[str]] = {}
        for c in plan["channels"]:
            for send in c["bus_sends"]:
                if send["bus"] == name:
                    key = (send["mode"], send["level_db"], _bus_cites(c, names).get(name))
                    groups.setdefault(key, []).append(c["name"])
        out = {"name": name, "mono": b["mono"], "color": b.get("color"),
               "destination": b["destination"], "fader": b["fader"]}
        for k in ("preset", "dca", "mute_group"):
            if k in b:
                out[k] = b[k]
        out["sends"] = [{"from": senders, "mode": mode, "level_db": level,
                         **({"provenance": cite} if cite else {})}
                        for (mode, level, cite), senders in groups.items()]
        out["provenance"] = b["provenance"]
        busses.append(out)

    reply = {
        "channels": channels,
        "busses": busses,
        "dcas": [{"name": n, "fader": d["fader"]} for n, d in plan["dcas"].items()],
        "mute_groups": [{"name": n} for n in plan["mute_groups"]],
        "outputs": [{"name": n, **o} for n, o in plan["outputs"].items()],
    }
    if "'unassigned_inputs' left out" not in repaired:
        reply["unassigned_inputs"] = plan["unassigned_inputs"]
    reply["notes"] = [{"text": n["text"], "source": "model"}
                      for n in notes if n.get("source") == "model"]
    return reply


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    with open(argv[0]) as f:
        plan = json.load(f)
    with open(argv[1], "w") as f:
        f.write(json.dumps(reply_from_plan(plan), indent=2) + "\n")
    print(f"wrote {argv[1]} -- now run tools/build_demo_show.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
