"""Compare a plan against a show file the console saved (`.snap`).

The closing half of the loop. `apply` proves a write landed by reading the
same address straight back; this proves the *desk as a whole* matches the
plan, using a file the console wrote itself, after whatever else happened
to it -- a recall, a hand edit at soundcheck, a page the operator nudged.

A `.snap` is JSON whose `ae_data` mirrors the OSC tree
(`ae_data.{ch,aux,bus,main,mtx,dca,mgrp,io,...}`), so `/ch/1/flt/lcf` is
`ae_data["ch"]["1"]["flt"]["lcf"]`. Confirmed against three real show
files (`docs/reference/wing-console-model.md`).

UNVERIFIED IN ONE RESPECT, deliberately flagged: WING firmware has moved
some per-strip scalars (`name`, `icon`, `col`) under a `config` node in
some versions and left them at the top in others. Every lookup here tries
both and reports `snapshot.field-not-found` when neither exists, rather
than reporting a match it did not actually check. If you see that finding
on a real file, send me the file -- the fix is one line in `_LOOKUPS`.

What this does NOT do is reverse-engineer a show into conventions. That
is the decompiler, still deferred.
"""

from __future__ import annotations

import json
from pathlib import Path

from atoo.verify_plan import SEVERITY_ERROR, SEVERITY_WARNING, VerifyResult

# dB values within this of each other count as equal. WING's fader is
# 1024 steps over ~154dB, so ~0.15dB per step; anything tighter than this
# would report quantisation as a mismatch.
DB_TOLERANCE = 0.25


class SnapshotError(ValueError):
    """The file is not a WING show file this can read."""


def load_snapshot(path: str | Path) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"couldn't read {p}: {exc}") from exc
    if not isinstance(data, dict) or "ae_data" not in data:
        raise SnapshotError(
            f"{p} has no 'ae_data' -- a WING .snap is JSON with the console's node tree "
            "under that key. Is this a .snap saved from the desk?"
        )
    return data["ae_data"]


def _dig(node, *keys):
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


class _Missing:
    def __repr__(self) -> str:
        return "<not in snapshot>"


_MISSING = _Missing()


def _scalar(strip: dict, name: str):
    """A per-strip scalar, wherever this firmware keeps it."""
    for path in ((name,), ("config", name)):
        value = _dig(strip, *path)
        if value is not _MISSING:
            return value
    return _MISSING


def _close(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= DB_TOLERANCE
    except (TypeError, ValueError):
        return False


def _tag_indices(tags: str, letter: str) -> set[int]:
    """DCA and mute-group membership live as #D<n>/#M<n> tokens in the
    strip's shared `tags` string (FR-1.6, confirmed on hardware)."""
    out = set()
    for token in str(tags or "").replace(",", " ").split():
        token = token.strip()
        if token.upper().startswith(f"#{letter}"):
            digits = token[2:]
            if digits.isdigit():
                out.add(int(digits))
    return out


def compare_snapshot(plan: dict, ae_data: dict) -> VerifyResult:
    """Every difference between what the plan says and what the desk saved.

    Only fields the plan actually states are compared. A plan that leaves
    `fader_db` null is not asserting a fader position, so a desk sitting
    at -7.3 is not a mismatch -- it is soundcheck.
    """
    r = VerifyResult()
    dca_index = {n: e.get("index") for n, e in (plan.get("dcas") or {}).items()}
    mgrp_index = {n: e.get("index") for n, e in (plan.get("mute_groups") or {}).items()}
    bus_index = {n: e.get("index") for n, e in (plan.get("busses") or {}).items()}

    for ch in plan.get("channels") or []:
        bank, idx, name = ch.get("bank", "ch"), ch.get("channel"), ch.get("name")
        where = f"{bank} {idx} ({name})"
        strip = _dig(ae_data, bank, str(idx))
        if strip is _MISSING:
            r.add(SEVERITY_ERROR, "snapshot.strip-missing", where,
                  f"the plan uses {bank} {idx} but the show file has no such strip")
            continue

        actual_name = _scalar(strip, "name")
        if actual_name is _MISSING:
            r.add(SEVERITY_WARNING, "snapshot.field-not-found", where,
                  "couldn't find this strip's name in the show file (tried 'name' and "
                  "'config.name') -- name not compared")
        elif str(actual_name).strip() != str(name).strip():
            r.add(SEVERITY_ERROR, "snapshot.name", where,
                  f"plan names this {name!r}; the desk has {actual_name!r}")

        _compare_patch(ch, strip, where, r)
        _compare_processing(ch, strip, where, r)
        _compare_fader(ch, strip, where, r)
        _compare_membership(ch, strip, where, dca_index, mgrp_index, r)
        _compare_sends(ch, strip, where, bus_index, r)

    return r


def _compare_patch(ch: dict, strip: dict, where: str, r: VerifyResult) -> None:
    patch = ch.get("patch") or {}
    if not patch.get("sockets"):
        return
    conn = _dig(strip, "in", "conn")
    if conn is _MISSING:
        r.add(SEVERITY_WARNING, "snapshot.field-not-found", where,
              "no in.conn in the show file -- patch not compared")
        return
    want_group, want_socket = patch.get("group"), patch["sockets"][0]
    got_group, got_socket = conn.get("grp"), conn.get("in")
    if str(got_group) != str(want_group) or got_socket != want_socket:
        r.add(SEVERITY_ERROR, "snapshot.patch", where,
              f"plan patches to {want_group} {want_socket}; the desk is on "
              f"{got_group} {got_socket}")


def _compare_processing(ch: dict, strip: dict, where: str, r: VerifyResult) -> None:
    hpf = (ch.get("processing") or {}).get("hpf_hz")
    if hpf is None:
        return
    lcf, lc = _dig(strip, "flt", "lcf"), _dig(strip, "flt", "lc")
    if lcf is _MISSING:
        r.add(SEVERITY_WARNING, "snapshot.field-not-found", where,
              "no flt.lcf in the show file -- high-pass not compared")
        return
    if lc is not _MISSING and not lc:
        r.add(SEVERITY_ERROR, "snapshot.hpf-off", where,
              f"plan sets a {hpf}Hz high-pass; the desk has the filter switched off")
    elif not _close(lcf, hpf):
        r.add(SEVERITY_ERROR, "snapshot.hpf", where,
              f"plan sets the high-pass to {hpf}Hz; the desk is at {lcf}Hz")


def _compare_fader(ch: dict, strip: dict, where: str, r: VerifyResult) -> None:
    fader = ch.get("fader") or {}
    if fader.get("fader_db") is not None:
        fdr = _scalar(strip, "fdr")
        if fdr is _MISSING:
            r.add(SEVERITY_WARNING, "snapshot.field-not-found", where,
                  "no fdr in the show file -- fader not compared")
        elif not _close(fdr, fader["fader_db"]):
            r.add(SEVERITY_ERROR, "snapshot.fader", where,
                  f"plan starts this fader at {fader['fader_db']}dB; the desk saved {fdr}dB")
    if fader.get("muted") is not None:
        mute = _scalar(strip, "mute")
        if mute is not _MISSING and bool(mute) != bool(fader["muted"]):
            r.add(SEVERITY_ERROR, "snapshot.mute", where,
                  f"plan has this {'muted' if fader['muted'] else 'unmuted'}; "
                  f"the desk saved the opposite")


def _compare_membership(ch: dict, strip: dict, where: str,
                        dca_index: dict, mgrp_index: dict, r: VerifyResult) -> None:
    tags = _scalar(strip, "tags")
    if tags is _MISSING:
        if ch.get("dca") or ch.get("mute_group"):
            r.add(SEVERITY_WARNING, "snapshot.field-not-found", where,
                  "no tags in the show file -- DCA and mute-group membership not compared")
        return
    for label, names, index_map, letter in (
        ("DCA", ch.get("dca") or [], dca_index, "D"),
        ("mute group", ch.get("mute_group") or [], mgrp_index, "M"),
    ):
        unindexed = [n for n in names if index_map.get(n) is None]
        if unindexed:
            # Silence here would be a lie: membership is stored by INDEX in
            # the strip's tags, so a plan that never allocated one cannot be
            # compared at all. Reporting a clean result would claim a check
            # that never ran.
            r.add(SEVERITY_WARNING, "snapshot.no-console-index", where,
                  f"{label} {sorted(unindexed)} has no console index in this plan, so "
                  "membership could not be compared -- plans from `atoo build` carry "
                  "one; a hand-written plan may not")
        want = {index_map[n] for n in names if index_map.get(n) is not None}
        got = _tag_indices(tags, letter)
        missing = want - got
        if missing:
            by_index = {v: k for k, v in index_map.items()}
            r.add(SEVERITY_ERROR, f"snapshot.{letter.lower()}-membership", where,
                  f"plan puts this in {label} "
                  f"{sorted(by_index.get(i, i) for i in missing)}; the desk did not")


def _compare_sends(ch: dict, strip: dict, where: str,
                   bus_index: dict, r: VerifyResult) -> None:
    for send in ch.get("bus_sends") or []:
        bus = send.get("bus")
        index = bus_index.get(bus)
        if index is None:
            continue
        node = _dig(strip, "send", str(index))
        if node is _MISSING:
            r.add(SEVERITY_WARNING, "snapshot.field-not-found", where,
                  f"no send/{index} in the show file -- send to {bus!r} not compared")
            continue
        if not node.get("on"):
            r.add(SEVERITY_ERROR, "snapshot.send-off", where,
                  f"plan sends this to {bus!r} (bus {index}); the desk has that send off")
            continue
        level = send.get("level_db")
        if level is not None and not _close(node.get("lvl"), level):
            r.add(SEVERITY_ERROR, "snapshot.send-level", where,
                  f"plan sends to {bus!r} at {level}dB; the desk saved {node.get('lvl')}dB")
        mode = send.get("mode")
        got_mode = str(node.get("mode") or "").upper()
        if mode and got_mode and got_mode != str(mode).upper():
            r.add(SEVERITY_ERROR, "snapshot.send-mode", where,
                  f"plan sends to {bus!r} {mode}-fader; the desk saved {got_mode}")
