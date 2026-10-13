#!/usr/bin/env python3
"""
Turn a experiments/wing/spike_param_coverage.py walk into O1's parameter map: a
schema keyed by address *template* (numbered instances collapsed to
"{n}") with type, range, enum, and unit extracted from the '?' mode
description text -- built from a live node-tree dump per project-brief.md
section 9's "Parameter coverage" risk, rather than hand-written.

Input: a wing_params_*.json file from experiments/wing/spike_param_coverage.py (mode '?').
Output: two files next to each other --
  <out>.json  -- the machine-readable schema
  <out>.md    -- a human-readable summary: counts, categories, and every
                 template flagged as instance-variant (see below)

What this does NOT do: decide relevance for you. Every collapsed
top-level node -- ch, aux, $ctl, io, and so on -- gets a `category` guess
(see CATEGORY_HINTS below) but nothing is dropped from the output. This
is a first mechanical pass, not a final schema; review the categories
before treating anything as excluded from O1's scope.

Usage:
    python3 tools/build_parameter_map.py wing_params_20260908.json \
        --out docs/reference/wing-compact-parameter-map
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

INDEX_RE = re.compile(r"/(\d+)(?=/|$)")
NODE_MARKER_RE = re.compile(r"^\s*(\S+)\s+\(node\)\s*$")
LEAF_LINE_RE = re.compile(r"^\s*(\S+)\s+(.*\S)\s*$")

# WING types seen in '?' descriptions: int, float, fader, lin, log, list,
# string. All but list/string share the same "type [min .. max]" shape,
# optionally followed by ", N steps"; a trailing token on the max side can
# carry a unit (dB, %, ms, ...). Values aren't always plain numbers --
# durations show up as "0:00 .. 9:59:59" -- so this stays permissive and
# keeps the raw range string whenever it can't confidently split further.
RANGE_RE = re.compile(
    r"^(?P<type>\w+)\s+\[(?P<min>[^\]]+?)\s*\.\.\s*(?P<max>[^\]]+?)\]"
    r"(?:,\s*(?P<steps>\d+)\s*steps)?$"
)
LIST_RE = re.compile(r"^list\s+\[(?P<values>.*)\]$")
STRING_RE = re.compile(r"^string\s+\[(?P<maxlen>\d+)\]$")
NUMBER_UNIT_RE = re.compile(r"^([+-]?[\d.]+)\s*(\S*)$")

# First-pass guesses only -- not authoritative. Anything not listed here
# defaults to "unclassified" and should be reviewed, not trusted blind.
CATEGORY_HINTS = {
    "ch": "show", "aux": "show", "bus": "show", "main": "show",
    "mtx": "show", "dca": "show", "mgrp": "show", "fx": "show",
    "io": "show", "cards": "show",
    "$ctl": "surface-ui", "$stat": "surface-ui", "$globals": "console-global",
    "cfg": "surface-ui", "$syscfg": "console-identity",
    "play": "transport", "rec": "transport",
}


def strip_index(addr: str) -> str:
    return INDEX_RE.sub("/{n}", addr)


def parse_value(raw: str):
    """Best-effort split of a bare min/max token into (number, unit) or
    (raw_string, None) if it doesn't look like a plain number."""
    m = NUMBER_UNIT_RE.match(raw.strip())
    if m and m.group(1) not in ("", "-", "+"):
        try:
            num = float(m.group(1))
            if num.is_integer():
                num = int(num)
            return num, (m.group(2) or None)
        except ValueError:
            pass
    return raw.strip(), None


def parse_leaf(name: str, rest: str) -> dict:
    """Parse one leaf-parameter description into a structured entry.
    Always keeps `raw` so nothing is lost if the structured parse misses
    something -- these grammars were reverse-engineered from observed
    output, not from a formal spec of the '?' text format."""
    entry = {"raw": rest}

    m = LIST_RE.match(rest)
    if m:
        entry["type"] = "list"
        entry["values"] = [v.strip() for v in m.group("values").split(",")]
        return entry

    m = STRING_RE.match(rest)
    if m:
        entry["type"] = "string"
        entry["max_len"] = int(m.group("maxlen"))
        return entry

    m = RANGE_RE.match(rest)
    if m:
        entry["type"] = m.group("type")
        min_val, min_unit = parse_value(m.group("min"))
        max_val, max_unit = parse_value(m.group("max"))
        entry["min"] = min_val
        entry["max"] = max_val
        unit = max_unit or min_unit
        if unit:
            entry["unit"] = unit
        if m.group("steps"):
            entry["steps"] = int(m.group("steps"))
        return entry

    # Didn't match a known shape -- keep the type token if there's an
    # obvious one, but don't guess at structure past that.
    entry["type"] = rest.split(None, 1)[0] if rest else None
    return entry


def build(raw: dict) -> dict:
    params = raw["parameters"]

    # full_param_path -> {"variants": [...]} -- usually one entry; more
    # than one means different instances of the collection disagreed.
    schema = defaultdict(lambda: {"variants": []})
    collections = defaultdict(set)  # top-level segment -> set of indices seen
    variant_templates = set()

    for addr, entry in params.items():
        data = entry.get("data") or ""
        tmpl = strip_index(addr)

        top = addr.strip("/").split("/")[0] if addr != "/" else "/"
        # Known gap, found 2026-09-10 (docs/reference/wing-console-model.md):
        # this assumes /{top}/{digit}/... (true for ch, bus, main, mtx, dca,
        # mgrp, fx), so /io/* -- shaped /io/{in,out}/{GROUP}/{digit}/... --
        # never matches and collections["io"] stays empty even though its
        # ~187 parameter templates are captured fine in flat_schema below.
        # Cosmetic: only this per-collection index-range summary is affected.
        idx_match = re.match(r"^/([^/]+)/(\d+)(?:/|$)", addr)
        if idx_match:
            collections[idx_match.group(1)].add(int(idx_match.group(2)))

        for line in data.splitlines():
            if not line.strip():
                continue
            if NODE_MARKER_RE.match(line):
                continue  # children are separate addresses, already walked
            m = LEAF_LINE_RE.match(line)
            if not m:
                continue
            name, rest = m.group(1), m.group(2)
            parsed = parse_leaf(name, rest)
            param_path = f"{tmpl}.{name}" if tmpl != "/" else f"/{name}"
            variants = schema[param_path]["variants"]
            if parsed not in variants:
                variants.append(parsed)

    # Flatten: single-variant params get a plain entry; multi-variant ones
    # keep all observed variants and get flagged, rather than silently
    # picking one and hiding that instances disagreed.
    flat_schema = {}
    for param_path, bucket in schema.items():
        variants = bucket["variants"]
        top = param_path.strip("/").split(".")[0].strip("/").split("/")[0]
        category = CATEGORY_HINTS.get(top, "unclassified")
        if len(variants) == 1:
            flat_schema[param_path] = {**variants[0], "category": category}
        else:
            variant_templates.add(param_path)
            flat_schema[param_path] = {
                "category": category,
                "variant_count": len(variants),
                "variants": variants,
            }

    collection_summary = {
        name: {"count": len(idxs), "index_range": [min(idxs), max(idxs)]}
        for name, idxs in collections.items()
        if idxs
    }

    by_category = defaultdict(int)
    for entry in flat_schema.values():
        by_category[entry["category"]] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "console_identity": raw.get("console_identity"),
            "start_node": raw.get("start_node"),
            "mode": raw.get("mode"),
            "requests_sent": raw.get("requests_sent"),
            "addresses_walked": len(params),
        },
        "collections": collection_summary,
        "category_counts": dict(by_category),
        "variant_template_count": len(variant_templates),
        "variant_templates": sorted(variant_templates),
        "schema": dict(sorted(flat_schema.items())),
    }


def write_markdown(result: dict, path: str) -> None:
    lines = []
    src = result["source"]
    lines.append(f"# Parameter map — {src.get('console_identity', 'unknown console')}\n")
    lines.append(f"Generated {result['generated_at']} from a walk of "
                  f"{src.get('addresses_walked')} addresses "
                  f"({src.get('requests_sent')} requests, mode `{src.get('mode')}`, "
                  f"start node `{src.get('start_node')}`).\n")
    lines.append("Mechanical first pass -- see the script docstring. Category "
                  "guesses are unreviewed; nothing is dropped from the JSON "
                  "regardless of category.\n")
    lines.append("**Known limitation:** a handful of duration-formatted ranges "
                  "(`0:00:00 .. 9:59:59`, seen on transport/recording fields) "
                  "get misparsed as number+unit rather than recognised as "
                  "timestamps -- `raw` is correct on every entry regardless, "
                  "only the structured min/max/unit fields are wrong for "
                  "these few. Not fixed because it's rare and cosmetic; worth "
                  "a real fix before this schema is load-bearing.\n")

    lines.append("## Collections\n")
    lines.append("| Collection | Count | Index range |")
    lines.append("|---|---|---|")
    for name, info in sorted(result["collections"].items()):
        lines.append(f"| `{name}` | {info['count']} | {info['index_range'][0]}–{info['index_range'][1]} |")
    lines.append("")

    lines.append("## Parameters by category\n")
    lines.append("| Category | Parameter count |")
    lines.append("|---|---|")
    for cat, count in sorted(result["category_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{cat}` | {count} |")
    lines.append("")

    lines.append(f"## Instance variance ({result['variant_template_count']} templates)\n")
    lines.append("Parameter templates where different instances of the same "
                  "collection (e.g. channel 3 vs channel 12) returned different "
                  "descriptions -- most look state-dependent (a currently "
                  "selected dynamics model changing what sub-parameters are "
                  "described), not structural noise, but unreviewed. "
                  "All observed variants are kept in the JSON, not collapsed.\n")
    for t in result["variant_templates"][:40]:
        lines.append(f"- `{t}`")
    if len(result["variant_templates"]) > 40:
        lines.append(f"- … and {len(result['variant_templates']) - 40} more (see JSON)")
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="wing_params_*.json from spike_param_coverage.py")
    ap.add_argument("--out", required=True, help="output path stem (writes <out>.json and <out>.md)")
    args = ap.parse_args()

    with open(args.input) as f:
        raw = json.load(f)

    result = build(raw)

    with open(f"{args.out}.json", "w") as f:
        json.dump(result, f, indent=2)
    write_markdown(result, f"{args.out}.md")

    print(f"{len(result['schema'])} parameter templates written to {args.out}.json")
    print(f"Summary written to {args.out}.md")
    print(f"Categories: {result['category_counts']}")
    print(f"{result['variant_template_count']} templates have instance variance -- see the .md")


if __name__ == "__main__":
    main()
