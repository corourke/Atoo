"""Human-readable rendering of a compiled plan.

FR-6.3 requires the setup UI show a plan "human-readable, not a raw
parameter dump" -- a UI is a future adapter over the same plan dict; this
serves that same requirement as plain text today, for `atoo
--pretty`, since there's no UI yet to render anything. Text in, text out,
no new plan fields -- purely a view over what compile_plan() already
produces.
"""

from __future__ import annotations

from atoo import plan_compat
from atoo.plan_schema import note_line


def _source_desc(source: dict) -> str:
    bits = [source["type"]] if source.get("type") else []
    if source.get("model"):
        bits.append(source["model"])
    desc = "/".join(bits)
    tags = [t for t, present in (("stereo", source.get("stereo")), ("phantom", source.get("phantom"))) if present]
    if tags:
        desc += f" ({', '.join(tags)})"
    return desc


def _processing_desc(processing: dict) -> str:
    bits = []
    if processing.get("hpf_hz") is not None:
        bits.append(f"HPF {processing['hpf_hz']}Hz")
    # Shown only when present, same rule as the rest of
    # this function and as `_source_desc`'s stereo/phantom tags -- a plan
    # that never uses these fields renders byte-identical to before.
    if processing.get("hi_cut_hz") is not None:
        bits.append(f"Hi-cut {processing['hi_cut_hz']}Hz")
    if processing.get("tilt_db") is not None:
        bits.append(f"Tilt {processing['tilt_db']}dB")
    if processing.get("trim_db") is not None:
        bits.append(f"Trim {processing['trim_db']}dB")
    if processing.get("balance_db") is not None:
        bits.append(f"Balance {processing['balance_db']}dB")
    if processing.get("invert"):
        bits.append("Inverted")
    if processing.get("gain_db") is not None:
        bits.append(f"Gain {processing['gain_db']}dB")
    if processing.get("preset"):
        # Say whether the plan carries the preset's
        # values (they will be written) or only its name (nothing will be).
        values = processing.get("preset_values")
        if isinstance(values, dict) and isinstance(values.get("leaves"), dict):
            bits.append(f'preset "{processing["preset"]}" ({len(values["leaves"])} values)')
        else:
            bits.append(f'preset "{processing["preset"]}" (not expanded -- nothing written)')
    # One short clause per stated band rather than a
    # curve -- a plan review is checking that what the conventions asked
    # for arrived, not reading a response plot.
    eq_desc = _eq_desc(processing.get("eq"))
    if eq_desc:
        bits.append(eq_desc)
    # The channel's second EQ, labelled so a reader can tell the two
    # apart at a glance -- they are different tap points, not a typo.
    peq = processing.get("presend_eq")
    if peq:
        peq_desc = _eq_desc(peq)
        if peq_desc:
            bits.append(peq_desc.replace("EQ", "PreSend EQ", 1))
    return ", ".join(bits) if bits else "-"


def _eq_desc(eq: dict | None) -> str:
    if not eq:
        return ""
    bands = []
    for entry in eq.get("bands") or []:
        parts = []
        if entry.get("freq_hz") is not None:
            parts.append(f"{entry['freq_hz']:g}Hz")
        if entry.get("gain_db") is not None:
            parts.append(f"{entry['gain_db']:+g}dB")
        if entry.get("q") is not None:
            parts.append(f"Q{entry['q']:g}")
        if entry.get("shape"):
            parts.append(entry["shape"])
        bands.append(f"{entry.get('band')} {' '.join(parts)}".strip() if parts else f"{entry.get('band')} (empty)")
    if eq.get("model"):
        bands.append(eq["model"])
    if eq.get("mix_pct") is not None:
        bands.append(f"mix {eq['mix_pct']:g}%")
    if not bands:
        # An `eq` block holding nothing but `on` still says something --
        # "start this strip's EQ bypassed" is a real instruction.
        if eq.get("on") is not None:
            return f"EQ {'on' if eq['on'] else 'off'}"
        return ""
    prefix = "EQ" if eq.get("on") is not False else "EQ (off)"
    return f"{prefix} [{'; '.join(bands)}]"


def _strip_processing_desc(processing: dict | None) -> str:
    """A bus's or an output's own `processing`.

    Not `_processing_desc`: these strips carry only the EQ half of it --
    none of a channel's filter/head-amp fields exist on a bus at all --
    and their tilt lives on the EQ node rather than a `flt` one.
    """
    if not processing:
        return ""
    bits = []
    if processing.get("tilt_db") is not None:
        bits.append(f"Tilt {processing['tilt_db']}dB")
    eq_desc = _eq_desc(processing.get("eq"))
    if eq_desc:
        bits.append(eq_desc)
    return ", ".join(bits)


def _bus_send_desc(send: dict) -> str:
    mode = send["mode"] or "mode?"
    level = f"{send['level_db']}dB" if send["level_db"] is not None else "level?"
    return f"{send['bus']} ({mode}, {level})"


def _socket_desc(socket: dict | None) -> str:
    if socket is None:
        return "patch?"
    return f"{socket['group']} {'-'.join(map(str, socket['sockets']))}"


def _sockets_desc(sockets: list[dict]) -> str:
    # A Main/dedicated output can fan out to several physical
    # sockets at once (TOURING_260821_MIX.snap's Main feeds USB 47/48,
    # CRD 31/32 AND REC 1/2 simultaneously).
    if not sockets:
        return "patch?"
    return " + ".join(_socket_desc(s) for s in sockets)


def _patch_desc(patch: dict | None) -> str:
    if patch is None:
        # An instructed strip asked for "if available" whose socket was not.
        return "unpatched"
    desc = _socket_desc({"group": patch["group"], "sockets": patch["sockets"]})
    return desc if patch["stated"] else f"{desc} (auto)"


def _destination_desc(destination: dict | None) -> str:
    if destination is None:
        return "(unresolved)"
    if destination["type"] == "main":
        return "-> Main"
    if destination["type"] == "matrix":
        # Legal in the schema but not how a Matrix feed is actually
        # expressed or applied (see outputs.fed_by) -- flagged
        # here too so a human reading --pretty sees the same gap
        # `atoo verify` would report.
        return "-> Matrix (wrong field -- state this on the matrix's own outputs[].fed_by instead)"
    label = destination.get("label")
    label_desc = f'"{label}"' if label else "(unlabeled)"
    sockets = plan_compat.output_patches(destination)
    return f"-> Dedicated output {label_desc}, {_sockets_desc(sockets)}"


def _fed_by_desc(fed_by: dict | None) -> str:
    if fed_by is None:
        return "?"
    if fed_by["type"] == "main":
        return f"Main {fed_by['index']}"
    return f"bus {fed_by['name']}"


def render_plan(plan: dict, warnings: list) -> str:
    # Where the texts came from is in `meta` (the conventions are a
    # stack, not one file; the input list has its own record). A plan
    # once carried top-level `conventions_file` / `input_list` strings and
    # `--pretty` still read them -- a KeyError on every plan built since.
    meta = plan.get("meta") or {}
    conventions = ", ".join(layer.get("path", "?") for layer in meta.get("conventions_stack") or []) or "?"
    input_list = (meta.get("input_list") or {}).get("path", "?")
    lines = [
        "Atoo plan",
        f"  conventions: {conventions}",
        f"  input list:  {input_list}",
        f"  channels:    {len(plan['channels'])}",
        "",
        "CHANNELS",
    ]

    # An aux strip is labelled as the desk labels it, "Aux 1", not as a
    # second channel 1; the column widens to fit only when
    # the plan has one.
    labels = [f"Aux {ch['channel']}" if ch.get("bank") == "aux" else str(ch["channel"])
              for ch in plan["channels"]]
    width = max([3] + [len(label) for label in labels])
    for ch, label in zip(plan["channels"], labels):
        name_field = ch["name"]
        if ch.get("color"):
            name_field += f" [{ch['color']}]"
        lines.append(
            f"  {label:>{width}}  {name_field:<16} {_source_desc(ch['source']):<28} {_processing_desc(ch['processing'])}"
        )
        lines.append(f"       Patch: {_patch_desc(ch['patch'])}")
        if ch["dca"]:
            lines.append(f"       DCA: {', '.join(ch['dca'])}")
        if ch["mute_group"]:
            lines.append(f"       Mute group: {', '.join(ch['mute_group'])}")
        if ch["bus_sends"]:
            lines.append(f"       Bus: {' | '.join(_bus_send_desc(s) for s in ch['bus_sends'])}")
        if ch.get("main_routes"):
            # A channel routed straight to Main with no bus and
            # no DCA -- distinct from "Bus:" above (a channel feeding a
            # bus that itself feeds Main), so it gets its own line.
            mains = ", ".join(f"Main {r['index']}" for r in ch["main_routes"])
            lines.append(f"       Direct route: -> {mains}")

    if plan.get("busses"):
        lines += ["", "BUSSES"]
        for name, b in plan["busses"].items():
            # A bus can state BOTH a main route AND a dedicated
            # output at once (Festival_STANDALONE.snap's VOCALS bus).
            destinations = b.get("destinations") or ([b["destination"]] if b.get("destination") else [])
            desc = " + ".join(_destination_desc(d) for d in destinations) if destinations else _destination_desc(None)
            lines.append(f"  {name:<20} {desc}")
            if b.get("dca"):
                lines.append(f"                       DCA: {', '.join(b['dca'])}")
            if b.get("mute_group"):
                lines.append(f"                       Mute group: {', '.join(b['mute_group'])}")
            # A bus's own processing, which had no
            # field at all before it and so had nothing to render.
            bus_proc = _strip_processing_desc(b.get("processing"))
            if bus_proc:
                lines.append(f"                       Processing: {bus_proc}")

    if plan.get("outputs"):
        lines += ["", "OUTPUTS"]
        for name, o in plan["outputs"].items():
            sockets = plan_compat.output_patches(o)
            lines.append(f"  {name:<20} {_sockets_desc(sockets)}")
            if o.get("kind") == "matrix":
                lines.append(f"                       Fed by: {_fed_by_desc(o.get('fed_by'))}")
            out_proc = _strip_processing_desc(o.get("processing"))
            if out_proc:
                lines.append(f"                       Processing: {out_proc}")

    # `warnings` is compile_plan()'s own bare-string list, or (on the
    # generate path) plan["notes"]'s tagged {text, source} objects -- note_line() renders either, prefixing the source tag when
    # there is one, so "the model flagged this" reads differently from
    # "Atoo's own repair step did." They are NOTES, not warnings
    # (a model's remark and a repair are neither), and a
    # `repair` note is a build detail, listed apart as the Setup UI's
    # step 04 lists it (`finding_groups.DETAIL_NOTE_SOURCES`).
    from atoo.finding_groups import is_detail_note

    notes = [w for w in warnings if not is_detail_note(w)]
    details = [w for w in warnings if is_detail_note(w)]
    lines += ["", f"NOTES ({len(notes)})" if notes else "No notes."]
    lines += [f"  - {note_line(w)}" for w in notes]
    if details:
        lines += ["", f"BUILD DETAILS ({len(details)}) -- how the model's reply was read"]
        lines += [f"  - {note_line(w)}" for w in details]

    return "\n".join(lines)
