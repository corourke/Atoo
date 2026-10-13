#!/usr/bin/env python3
"""Freeze a model's initialized capture into package data -- an earlier change.

A full apply puts the desk into its initialized state before it writes the
plan (`atoo/initialize.py`). The values come from a capture of an
initialized desk of the same model, and the OSC type each value is written
with comes from the parameter map. Both are frozen under
`atoo/initialized/`, because a wheel install has no `docs/` and no
`tests/`, and the code never reads either at runtime.

Two jobs:

    # Add (or replace) a model's initialized capture. Copies the .snap
    # byte for byte to atoo/initialized/<model>.snap and says how
    # much of it has a known type.
    python3 tools/freeze_initialized_capture.py add wing-rack path/to/A8-initialized.snap

    # Rebuild the type table from docs/reference/wing-compact-parameter-map.json.
    python3 tools/freeze_initialized_capture.py types

    # Rebuild the FX engine table (which models each engine offers, and
    # every FX parameter name the walk saw) -- an earlier change.
    python3 tools/freeze_initialized_capture.py fx

After `add` for a new model, add one line to `initialize.CAPTURES` naming
the file and where it came from. `tests/test_initialize.py` checks that the
table and the directory agree.

**Getting a capture.** Initialize the desk (Setup -> the initialize
button), then save its show file (`.snap`) from the desk or WING Edit.
That file is the capture.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from atoo import console_facts  # noqa: E402
from atoo import initialize  # noqa: E402

PARAMETER_MAP = REPO / "docs" / "reference" / "wing-compact-parameter-map.json"
RAW_WALK = REPO / "docs" / "reference" / "wing-compact-raw-walk-20260908.json"

# The parameter map's types, as the OSC type tag a write uses.
# `preset_expand.LEAF_TYPES` makes the same mapping for the leaves a preset
# carries: int -> i, lin/log/fader -> f, list/string -> s.
_OSC = {"int": "i", "lin": "f", "log": "f", "fader": "f", "float": "f",
        "list": "s", "string": "s"}


def build_types() -> dict:
    """The type table: `{template: {"osc": "i"|"f"|"s", "tokens": [...]}}`.

    A template is the map's own key with the last `.` as a `/`
    (`/ch/{n}/dyn.thr` -> `/ch/{n}/dyn/thr`). A template whose variants
    disagree on the OSC type (an FX parameter that is a knob under one
    model and a list under another) gets no entry, so a capture leaf on it
    counts as not settable rather than being written with a guessed type."""
    schema = json.loads(PARAMETER_MAP.read_text())
    out: dict[str, dict] = {}
    for key, spec in sorted(schema["schema"].items()):
        head, _, leaf = key.rpartition(".")
        template = f"{head}/{leaf}"
        variants = spec.get("variants") or [spec]
        types = {_OSC.get(v.get("type")) for v in variants}
        if len(types) != 1 or None in types:
            continue
        entry = {"osc": types.pop()}
        tokens = [t for v in variants for t in (v.get("values") or [])]
        if entry["osc"] == "s" and tokens:
            entry["tokens"] = list(dict.fromkeys(str(t) for t in tokens))
        out[template] = entry
    meta = json.loads(PARAMETER_MAP.read_text())["source"]
    return {
        "generated_from": "docs/reference/wing-compact-parameter-map.json",
        "console_identity": meta.get("console_identity"),
        "templates": out,
    }


def cmd_types(_args) -> int:
    path = initialize.CAPTURE_DIR / initialize.LEAF_TYPES_FILE
    table = build_types()
    # One template per line, so a diff of the table reads as a list of
    # changed templates.
    rows = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}"
                      for k, v in sorted(table["templates"].items()))
    head = {k: v for k, v in table.items() if k != "templates"}
    path.write_text(json.dumps(head, indent=1)[:-2] + ',\n "templates": {\n'
                    + rows + "\n }\n}\n")
    print(f"wrote {path.relative_to(REPO)}: {len(table['templates'])} templates")
    return 0


def build_fx_models() -> dict:
    """The FX engine table: which effect models each of the
    sixteen engines offers, and every FX parameter name the map has.

    The models come from the RAW walk, one `/fx/{n}` node per engine,
    because the parameter map collapses the sixteen engines into one
    `/fx/{n}.mdl` template with two variants and does not say which
    engine had which. The walk does: engines 1-8 list 65 models, 9-16
    list 39 -- every reverb and delay is missing from 9-16. Engines with
    the same list are grouped, so a diff of the file reads.

    `parameters` is every `/fx/{n}.<leaf>` the map has, across whatever
    models were loaded when it was walked. It is NOT every parameter of
    every model (V-REV's `mod`, `out` and `trans` are absent: no engine
    held V-REV), so a name missing from it is reported, never refused."""
    walk = json.loads(RAW_WALK.read_text())["parameters"]
    groups: list[dict] = []
    for engine in range(1, console_facts.FX_SLOTS + 1):
        data = walk[f"/fx/{engine}"]["data"]
        line = next(ln for ln in data.splitlines() if ln.split()[:1] == ["mdl"])
        inner = line.split("[", 1)[1].rsplit("]", 1)[0]
        models = [m.strip() for m in inner.split(",") if m.strip()]
        for group in groups:
            if group["models"] == models:
                group["engines"].append(engine)
                break
        else:
            groups.append({"engines": [engine], "models": models})
    schema = json.loads(PARAMETER_MAP.read_text())["schema"]
    parameters = sorted({key.rpartition(".")[2] for key in schema
                         if key.startswith("/fx/{n}.") and not key.rpartition(".")[2].startswith("$")})
    return {
        "generated_from": ["docs/reference/wing-compact-raw-walk-20260908.json",
                           "docs/reference/wing-compact-parameter-map.json"],
        "console_identity": json.loads(PARAMETER_MAP.read_text())["source"].get("console_identity"),
        "engines": groups,
        "parameters": parameters,
    }


def cmd_fx(_args) -> int:
    from atoo import fx_engines

    path = initialize.CAPTURE_DIR / fx_engines.FX_MODELS_FILE
    path.write_text(json.dumps(build_fx_models(), indent=1) + "\n")
    print(f"wrote {path.relative_to(REPO)}")
    return 0


def cmd_add(args) -> int:
    if args.model not in console_facts.CONSOLE_MODELS:
        print(f"{args.model!r} is not a model Atoo knows: "
              f"{', '.join(sorted(console_facts.CONSOLE_MODELS))}", file=sys.stderr)
        return 1
    source = Path(args.snap)
    try:
        data = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"couldn't read {source}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict) or not isinstance(data.get("ae_data"), dict):
        print(f"{source} has no 'ae_data': is it a .snap saved from the desk?", file=sys.stderr)
        return 1
    target = initialize.CAPTURE_DIR / f"{args.model}.snap"
    shutil.copyfile(source, target)
    leaves = initialize.leaves_from_snapshot(data["ae_data"])
    typed = sum(1 for leaf in leaves if leaf.value_type is not None)
    print(f"copied {source} -> {target.relative_to(REPO)}")
    print(f"  {len(leaves)} leaves, {typed} with a known type, {len(leaves) - typed} not settable")
    if args.model not in initialize.CAPTURES:
        print(f"\nNow add to initialize.CAPTURES:\n"
              f'    "{args.model}": ("{args.model}.snap", "<where the capture came from>"),')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="copy a model's initialized .snap into package data")
    add.add_argument("model", help="a console_facts.CONSOLE_MODELS key, e.g. wing-rack")
    add.add_argument("snap", help="the .snap saved from the initialized desk")
    add.set_defaults(func=cmd_add)
    types = sub.add_parser("types", help="rebuild the leaf type table from the parameter map")
    types.set_defaults(func=cmd_types)
    fx = sub.add_parser("fx", help="rebuild the FX engine table from the raw walk and the map")
    fx.set_defaults(func=cmd_fx)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

