"""Structural diff between two plans -- generated vs. the deterministic
compiler's output for the same inputs.

Not a correctness oracle. The compiler's plan is what today's pipeline
produces, warts included (it drops 25 lines of the touringband conventions
and leaves the Matrix unrouted). Where the two disagree, either could be
the one that is wrong, and that is the interesting part: the disagreements
are where the architecture question actually gets decided.
"""

from __future__ import annotations

import re

from atoo import plan_compat


def _norm(name) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().casefold()


def _by_source(plan: dict) -> dict[str, dict]:
    return {_norm((ch.get("source") or {}).get("input") or ch.get("name")): ch
            for ch in plan.get("channels", [])}


def _sends(ch: dict) -> set[tuple]:
    return {(s.get("bus"), s.get("mode"), s.get("level_db")) for s in ch.get("bus_sends") or []}


def compare_plans(generated: dict, oracle: dict, *, gen_label="generated", ora_label="oracle") -> list[str]:
    lines: list[str] = []
    g, o = _by_source(generated), _by_source(oracle)

    only_gen, only_ora = sorted(set(g) - set(o)), sorted(set(o) - set(g))
    if only_gen:
        lines.append(f"Channels only in {gen_label}: {', '.join(g[k]['name'] for k in only_gen)}")
    if only_ora:
        lines.append(f"Channels only in {ora_label}: {', '.join(o[k]['name'] for k in only_ora)}")

    for key in sorted(set(g) & set(o)):
        gc, oc = g[key], o[key]
        name = oc.get("name")
        diffs: list[str] = []

        if (gc.get("bank"), gc.get("channel")) != (oc.get("bank"), oc.get("channel")):
            diffs.append(f"strip {gc.get('bank')} {gc.get('channel')} vs {oc.get('bank')} {oc.get('channel')}")
        if gc.get("name") != oc.get("name"):
            diffs.append(f"name {gc.get('name')!r} vs {oc.get('name')!r}")

        gp, op = gc.get("patch") or {}, oc.get("patch") or {}
        if (gp.get("group"), gp.get("sockets")) != (op.get("group"), op.get("sockets")):
            diffs.append(f"patch {gp.get('group')} {gp.get('sockets')} vs {op.get('group')} {op.get('sockets')}")

        ghpf = (gc.get("processing") or {}).get("hpf_hz")
        ohpf = (oc.get("processing") or {}).get("hpf_hz")
        if ghpf != ohpf:
            diffs.append(f"HPF {ghpf} vs {ohpf}")

        for field in ("dca", "mute_group"):
            gv, ov = set(gc.get(field) or []), set(oc.get(field) or [])
            if gv != ov:
                added = ", ".join(sorted(gv - ov)) or "-"
                removed = ", ".join(sorted(ov - gv)) or "-"
                diffs.append(f"{field}: +[{added}] -[{removed}]")

        gs, os_ = _sends(gc), _sends(oc)
        if gs != os_:
            added = ", ".join(f"{b}/{m}/{l}" for b, m, l in sorted(gs - os_, key=str)) or "-"
            removed = ", ".join(f"{b}/{m}/{l}" for b, m, l in sorted(os_ - gs, key=str)) or "-"
            diffs.append(f"sends: +[{added}] -[{removed}]")

        if diffs:
            lines.append(f"{name}: " + "; ".join(diffs))

    for label, key in (("DCAs", "dcas"), ("mute groups", "mute_groups"),
                       ("busses", "busses"), ("outputs", "outputs")):
        gv, ov = set(generated.get(key) or {}), set(oracle.get(key) or {})
        if gv != ov:
            lines.append(f"{label}: only in {gen_label} [{', '.join(sorted(gv - ov)) or '-'}]; "
                         f"only in {ora_label} [{', '.join(sorted(ov - gv)) or '-'}]")

    for bus in sorted(set(generated.get("busses") or {}) & set(oracle.get("busses") or {})):
        # Read through plan_compat: an oracle written
        # says `socket` where a new plan says `patch`, and that alone is
        # not a difference.
        gd = plan_compat.normalise_entry((generated["busses"][bus] or {}).get("destination"))
        od = plan_compat.normalise_entry((oracle["busses"][bus] or {}).get("destination"))
        if gd != od:
            lines.append(f"bus {bus} destination: {gd} vs {od}")

    return lines or ["(identical on every compared field)"]
