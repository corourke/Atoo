"""What the model writes today, frozen by hand, for comparison.

`atoo patch` asks the model for a change set in the plan's own shapes. No
live call is made here, so the "today" side of every comparison is written
down by hand as a compact spec and expanded into the shape a model emits
(`patch.CHANGE_SET_SCHEMA`): the full channel object with its dozen nested
fields and a `provenance` sentence for each decision, as the saved replies
`tests/fixtures/demo-horns.change-set.json` and
`tests/fixtures/patch-aux8.change-reply.json` have them. Calibration against
the first is in `docs/exploration/structured-intent-compiler.md`.
"""

from __future__ import annotations

from atoo import patch


def channel(spec: dict) -> dict:
    """A channel as a model writes it, from `{channel, name, group, sockets,
    ...}`."""
    name, group, sockets = spec["name"], spec["group"], spec["sockets"]
    ask = spec.get("said", "the change")
    return {
        "channel": spec["channel"], "bank": spec.get("bank", "ch"), "name": name,
        "color": spec.get("color"),
        "source": {"input": name, "type": spec.get("type", "Mic"), "model": spec.get("model", ""),
                   "stereo": len(sockets) == 2, "phantom": spec.get("phantom", False)},
        "patch": {"group": group, "sockets": sockets, "stated": spec.get("stated", True)},
        "processing": {"gain_db": spec.get("gain_db", 20), "trim_db": 0, "preset": None,
                       "hpf_hz": spec.get("hpf_hz"), "hi_cut_hz": None, "tilt_db": None,
                       "balance_db": None, "invert": None},
        "fader": {"fader_db": spec.get("fader_db", 0), "muted": False},
        "dca": spec.get("dca", []), "mute_group": spec.get("mute_group", []),
        "bus_sends": [{"bus": b, "mode": "post", "level_db": 0} for b in spec.get("sends", [])],
        "main_routes": [] if spec.get("sends") else [{"index": 1}],
        "provenance": {
            "patch": f"{ask}: {group} {'+'.join(str(s) for s in sockets)}",
            "color": "conventions: the category's colour",
            "processing": "conventions: gain 20 dB, trim 0 dB",
            "fader": "conventions: channel faders start at unity, unmuted",
            "dca": f"{ask}: the DCA named",
            "main_routes": "conventions: straight to Main 1 unless in a mix bus",
            "channel": f"{ask}: ch {spec['channel']}",
        },
    }


def change_set(spec: dict) -> dict:
    cs = patch.empty_change_set(spec.get("name", "change"))
    cs["add"]["channels"] = [channel(c) for c in spec.get("add_channels", [])]
    cs["add"]["busses"] = spec.get("add_busses", {})
    cs["add"]["dcas"] = spec.get("add_dcas", {})
    cs["add"]["mute_groups"] = spec.get("add_mute_groups", {})
    cs["add"]["outputs"] = spec.get("add_outputs", {})
    for key, names in spec.get("drop", {}).items():
        cs["drop"][key] = names
    cs["modify"] = spec.get("modify", [])
    return cs
