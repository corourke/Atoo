#!/usr/bin/env python3
"""Rebuild the demo show's plan.json -- with no model.

The demo show (`starter/demo-show/`, the sample show) is a packaged, read-only bundle
that matches the Demo console's rig (`atoo/web/demo_states/
before.json`). Its plan is a REAL plan -- `atoo build`'s own output,
recorded inputs and all, so Build's freshness check, Apply's pre-flight
and `atoo verify` treat it like any other -- but no model writes it.
The generator's reply is recorded in `tools/demo_show.reply.json`,
and this script plays it back through `atoo build` exactly as a
model's reply would arrive, so code expands it (`reply_expand`), numbers
it and verifies it.

Run it from the repository root after changing any of:

  * starter/conventions.md          (the starter house conventions, which
                                      the demo is built from)
  * starter/presets/*.chn, *.bus    (the starter preset library, the demo's)
  * starter/demo-show/input.csv
  * starter/demo-show/instructions.md
  * tools/demo_show.reply.json      (what the "model" answers)

    python3 tools/build_demo_show.py

It builds in a scratch copy of `starter/` and copies back ONLY
plan.json; the hand-written watch.json is never touched (the watchlist
call is answered with an empty draft). It refuses -- and copies nothing --
when the build fails or verify finds an error, so a broken demo plan
never reaches the package. Then it writes the Demo console's rig,
`atoo/web/demo_states/before.json`, from the plan: the desk as that
plan would leave it, so the two cannot drift. Then re-run the suite:
`tests/test_demo_show.py` checks the plan verifies and is fresh.

**After a model rebuild.** When the maintainer rebuilds the Demo with a
real model (as on 2026-10-13, commits 335bcd7 and d89acf7), the plan he
gets is the content to keep, but it records his machine's paths, may
lack preset values, and carries a build log and resolved conventions the
starter set does not ship. Recover the reply from it and rebuild here:

    python3 tools/demo_reply_from_plan.py starter/demo-show/plan.json tools/demo_show.reply.json
    rm -rf starter/conventions.resolved.md starter/demo-show/builds
    python3 tools/build_demo_show.py

The rebuilt plan's channels, busses, DCAs, mute groups, outputs and
notes are his, field for field; what changes is the meta (no model
critic, no resolve step, relative paths) and the preset values, now
expanded from `starter/presets`.

The demo show is changed only by editing these files in the repository:
the UI refuses every write to it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atoo import cli  # noqa: E402
from atoo.ai_provider import FakeProvider  # noqa: E402

STARTER = ROOT / "starter"
SHOW = "demo-show"
REPLY = ROOT / "tools" / "demo_show.reply.json"


RIG = ROOT / "atoo" / "web" / "demo_states" / "before.json"

RIG_COMMENT = (
    "The Demo console's rig: the clean WING Compact the Demo show (starter/demo-show/plan.json) "
    "describes, as if that plan had been applied -- its channel and aux names, colours and sockets, each "
    "socket's width (ST on both sockets of a stereo pair, M otherwise), phantom on the sockets the "
    "input list marks (both sockets of a stereo pair, so OH R's 48V is on A 6), "
    "every send, the busses (named and coloured) and their outputs, each FX bus's effect (the engine's model, its "
    "parameters as the bus preset sets them, and the bus's insert, switched on), Main 1 and its sockets, the DCAs and mute groups -- and "
    "every strip the show does not use as a full apply leaves it, unnamed and unpatched, so patch and "
    "amend find free strips here. Channel and bus processing (presets, high-pass) is not simulated, so "
    "Apply's Preview on the Demo lists it as changes the write would make. webui._DEMO_ISSUES arms and "
    "clears faults on top of it. Written by "
    "tools/build_demo_show.py from the plan; tests/test_demo_show.py checks the two "
    "line up.")


def rig_from_plan(plan: dict, rows: dict) -> list[dict]:
    """The Demo rig, one block per strip, as `plan` would leave a desk.
    `rows` is the input list by name, for phantom power; each row is
    matched to its socket by its own patch column, so the right-hand mic
    of a stereo pair answers for its own 48V."""
    from atoo.apply import bus_col
    from atoo.console_facts import colour_index
    from atoo.input_list import parse_socket_spec
    rows_by_socket = {parse_socket_spec(r["patch"]): r for r in rows.values()
                      if parse_socket_spec(r["patch"] or "")}
    dca_idx = {n: d["index"] for n, d in plan["dcas"].items()}
    mg_idx = {n: d["index"] for n, d in plan["mute_groups"].items()}
    bus_idx = {n: b["index"] for n, b in plan["busses"].items()}

    def tags(obj: dict) -> str:
        return ",".join([f"#D{dca_idx[d]}" for d in obj.get("dca") or []]
                        + [f"#M{mg_idx[m]}" for m in obj.get("mute_group") or []])

    blocks, phantom, widths, outs = [], [], {}, {}
    used = set()
    for c in plan["channels"]:
        bank, n = c.get("bank", "ch"), c["channel"]
        used.add((bank, n))
        s = f"/{bank}/{n}"
        b = {f"{s}/name": c["name"], f"{s}/in/conn/grp": c["patch"]["group"],
             f"{s}/in/conn/in": c["patch"]["sockets"][0], f"{s}/mute": 0,
             f"{s}/fdr": float(c["fader"]["fader_db"]), f"{s}/tags": tags(c)}
        # Its colour, as apply writes it (Apply's Preview draws
        # the Demo desk's scribble strips from this rig).
        col = c.get("col") if isinstance(c.get("col"), int) else colour_index(c.get("color"))
        if col is not None:
            b[f"{s}/col"] = col
        for r in c.get("main_routes") or []:
            b[f"{s}/main/{r['index']}/on"] = 1
        for send in c.get("bus_sends") or []:
            i = bus_idx[send["bus"]]
            b[f"{s}/send/{i}/on"] = 1
            b[f"{s}/send/{i}/lvl"] = float(send["level_db"])
        blocks.append(b)
        group, sockets = c["patch"]["group"], c["patch"]["sockets"]
        # The source's width, on every socket, as `apply` writes it: a
        # stereo strip names only its odd socket, and this is what says
        # the even one is taken too (C001).
        for socket in sockets:
            widths[(group, socket)] = "ST" if c["source"]["stereo"] else "M"
        # 48V on every socket whose input-list row asks for it -- both
        # mics of a stereo condenser pair, each by its own row (OH L, OH R).
        for socket in sockets:
            row = rows_by_socket.get((group, socket))
            if row and row["phantom"].strip().upper() == "TRUE":
                phantom.append((group, socket))
    for name, bus in plan["busses"].items():
        i = bus["index"]
        b = {f"/bus/{i}/name": name, f"/bus/{i}/mute": 0,
             f"/bus/{i}/fdr": float(bus["fader"]["fader_db"]),
             f"/bus/{i}/busmono": 1 if bus["mono"] else 0}
        if bus_col(bus) is not None:
            b[f"/bus/{i}/col"] = bus_col(bus)
        if bus.get("dca") or bus.get("mute_group"):
            b[f"/bus/{i}/tags"] = tags(bus)
        # Its bus preset's effect: the engine holds the model,
        # and the insert names it, switched on -- as apply leaves them.
        for ins in (bus.get("preset_values") or {}).get("inserts") or []:
            if isinstance(ins.get("engine"), int):
                b[f"/fx/{ins['engine']}/mdl"] = ins["model"]
                # And its parameters, as the preset sets them (Apply's Preview reads them on the simulated WING).
                for leaf, value in (ins.get("parameters") or {}).items():
                    b[f"/fx/{ins['engine']}/{leaf}"] = int(value) if isinstance(value, bool) else value
                b[f"/bus/{i}/{ins['point']}/ins"] = f"FX{ins['engine']}"
                b[f"/bus/{i}/{ins['point']}/on"] = 1
        d = bus["destination"]
        if d["type"] == "main":
            b[f"/bus/{i}/main/{d['index']}/on"] = 1
        else:
            for k, socket in enumerate(d["patch"]["sockets"]):
                outs[(d["patch"]["group"], socket)] = ("BUS", 2 * i - 1 + k)
        blocks.append(b)
    for name, o in plan["outputs"].items():
        i = o["index"]
        blocks.append({f"/main/{i}/name": name, f"/main/{i}/mute": 0,
                       f"/main/{i}/fdr": float(o["fader"]["fader_db"])})
        for k, socket in enumerate(o["patch"]["sockets"]):
            outs[(o["patch"]["group"], socket)] = ("MAIN", 2 * i - 1 + k)
    blocks.append({k: v for name, d in plan["dcas"].items() for k, v in (
        (f"/dca/{d['index']}/name", name), (f"/dca/{d['index']}/mute", 0),
        (f"/dca/{d['index']}/fdr", float(d["fader"]["fader_db"])))})
    blocks.append({k: v for name, g in plan["mute_groups"].items() for k, v in (
        (f"/mgrp/{g['index']}/name", name), (f"/mgrp/{g['index']}/mute", 0))})
    # LCL 9 is unused, with phantom off: `phantom_unpatched` turns it on.
    blocks.append({**{f"/io/in/{g}/{n}/vph": 1 for g, n in sorted(phantom)},
                   "/io/in/LCL/9/vph": 0})
    blocks.append({f"/io/in/{g}/{n}/mode": m for (g, n), m in sorted(widths.items())})
    blocks.append({k: v for (g, n), (src, i) in sorted(outs.items()) for k, v in (
        (f"/io/out/{g}/{n}/grp", src), (f"/io/out/{g}/{n}/in", i))})
    free = {}
    for bank, count in (("ch", 40), ("aux", 8)):
        for n in range(1, count + 1):
            if (bank, n) not in used:
                free.update({f"/{bank}/{n}/name": "", f"/{bank}/{n}/clink": 1,
                             f"/{bank}/{n}/in/conn/grp": "OFF", f"/{bank}/{n}/in/conn/in": 1})
    blocks.append(free)
    return blocks


def write_rig(plan: dict) -> None:
    """`RIG`, laid out one block per strip so a diff reads."""
    import csv
    rows = {r["name"]: r for r in csv.DictReader(
        (STARTER / SHOW / "input.csv").read_text().splitlines())}
    out = ["{", f'  "_comment": {json.dumps(RIG_COMMENT)},']
    for block in rig_from_plan(plan, rows):
        out.append("")
        line = "  "
        for item in (f"{json.dumps(k)}: {json.dumps(v)}" for k, v in block.items()):
            if len(line) + len(item) + 2 > 100 and line.strip():
                out.append(line.rstrip())
                line = "  "
            line += item + ", "
        out.append(line.rstrip())
    text = "\n".join(out).rstrip(",") + "\n}\n"
    json.loads(text)
    RIG.write_text(text)


class _DemoProvider(FakeProvider):
    """The generator answers with the hand-written reply; the watchlist
    drafter with an empty draft, so the build leaves watch.json alone."""

    def complete(self, *, system: str, user: str, response_schema=None, label: str = "") -> str:
        if label == "generator":
            self.response = REPLY.read_text()
        else:
            self.response = '{"watch_conditions": []}'
        return super().complete(system=system, user=user,
                                response_schema=response_schema, label=label)


def main() -> int:
    provider = _DemoProvider()
    cli.provider_from_env = lambda *a, **k: provider
    with tempfile.TemporaryDirectory(prefix="atoo-demo-") as scratch:
        work = Path(scratch) / "starter"
        shutil.copytree(STARTER, work, ignore=shutil.ignore_patterns("__pycache__"))
        (work / SHOW / "plan.json").unlink(missing_ok=True)
        # The demo's own preset library, expanded into the
        # plan. With no .chn there yet the build names the presets and
        # carries none of their values: verify warns once,
        # `preset.no-library`, and the plan still applies.
        presets = work / "presets"
        library = (["--presets", str(presets)] if any(presets.glob("*.chn"))
                   else [])
        if not library:
            print(f"no .chn files in {STARTER / 'presets'} -- building without a preset "
                  "library", file=sys.stderr)
        code = cli.main(["build", "--show", str(work / SHOW),
                         "--conventions", str(work / "conventions.md"),
                         "--console-model", "wing-compact",
                         "--no-resolve", "--no-category-rules", *library])
        if code != 0:
            print(f"build exited {code} -- nothing copied", file=sys.stderr)
            return code
        verify = cli.main(["verify", "--show", str(work / SHOW), *library])
        if verify != 0:
            print(f"verify exited {verify} -- nothing copied", file=sys.stderr)
            return verify
        # The plan records where its inputs were -- the scratch copy.
        # Spelled repository-relative instead, so the packaged plan names
        # no temporary folder; Build finds each one by its
        # `bundle_relative_path` first, which is unchanged. The build log
        # the pointer names stays behind in the scratch copy: the demo
        # had no model call worth keeping.
        text = (work / SHOW / "plan.json").read_text().replace(str(work), "starter")
        plan = json.loads(text)
        plan["meta"].pop("build_log_file", None)
        (STARTER / SHOW / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    write_rig(plan)
    print(f"wrote {STARTER / SHOW / 'plan.json'} and {RIG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
