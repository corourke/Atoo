"""A preview taken straight after a full build proposes nothing.

On a WING Compact, after a full build of the Demo, adding a Hi Hat to its
input list, rebuilding and applying again, a preview wanted four changes
it should not make: `/io/in/LCL/2/g`, `/io/in/LCL/4/g`, `/io/in/A/6/g` and
`/io/in/A/12/g`, "reset to initialized", 20 to 0. Those are the second
sockets of the Demo's four stereo sources.

The cause was in the plan's writes. A stereo pair is two sources and the
desk holds a head-amp gain on each; once the pair is in stereo mode the
desk carries the first socket's gain onto the second. The plan wrote the
gain on the first socket only, so the second ended at 20 without the plan
having named it, and the reset to initialized -- which puts back to 0 every
setting the plan does not set itself -- counted it as its own. The plan now
writes the gain on every socket of the patch, as it already does for
phantom power and width.

The desks are `tests/snap_desk`'s, built from the packaged initialized
capture: `PairedSnapDesk` links a stereo pair's gains as a WING does, and
the plain `SnapDesk` does not, so the fix has to hold for a desk that links
them and for one that does not. The show is the packaged Demo. Nothing here
reads `examples/`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atoo import firstrun
from atoo import initialize as init
from atoo.apply import _build_write_targets, apply_plan
from tests.snap_desk import PairedSnapDesk, SnapDesk

DEMO_PLAN = Path(firstrun.STARTER_DIR) / firstrun.DEMO_SHOW_NAME / "plan.json"
MODEL = "wing-compact"


def demo_plan() -> dict:
    return json.loads(DEMO_PLAN.read_text(encoding="utf-8"))


def with_hi_hat(plan: dict) -> dict:
    """The Demo's plan as a rebuild from an input list with one more row
    would leave it: a Hi Hat on a free channel and a free socket, built the
    way the Demo's own Kick is."""
    plan = copy.deepcopy(plan)
    taken = {c["channel"] for c in plan["channels"] if c.get("bank", "ch") == "ch"}
    sockets = {s for c in plan["channels"] if (c.get("patch") or {}).get("group") == "A"
               for s in c["patch"]["sockets"]}
    hat = copy.deepcopy(plan["channels"][0])
    hat.update(channel=max(taken) + 1, name="Hi Hat")
    hat["source"]["input"] = "Hi Hat"
    hat["patch"] = {"group": "A", "sockets": [max(sockets) + 1], "stated": True}
    plan["channels"].append(hat)
    return plan


def fresh_desk(desk_class):
    return desk_class({leaf.address: leaf.value for leaf in init.load_capture(MODEL).leaves})


def full_apply(plan: dict, desk, *, dry_run: bool, **kwargs):
    return apply_plan(plan, desk, dry_run=dry_run, full_apply=True, initialize=True,
                      init_model=MODEL, **kwargs)


def would_change(result) -> set[str]:
    return {w.address for w in result.writes if w.status == "dry_run" and w.would_change}


def written(result) -> set[str]:
    return {w.address for w in result.writes if w.status in ("match", "mismatch")}


def second_sockets(plan: dict) -> set[str]:
    """The gain address of every stereo source's second socket."""
    return {f"/io/in/{c['patch']['group']}/{socket}/g"
            for c in plan["channels"] if c["source"]["stereo"] and c.get("patch")
            for socket in c["patch"]["sockets"][1:]}


# ---- the plan states the gain on every socket --------------------------------


def test_the_plan_states_a_stereo_sources_gain_on_both_its_sockets():
    plan = demo_plan()
    targets = {t.address: t for t in _build_write_targets(plan, True)[0]}
    pairs = [c for c in plan["channels"] if c["source"]["stereo"] and c.get("patch")
             and c["processing"].get("gain_db") is not None]
    assert pairs, "the Demo has stereo sources with a stated gain"
    for channel in pairs:
        group = channel["patch"]["group"]
        for socket in channel["patch"]["sockets"]:
            target = targets[f"/io/in/{group}/{socket}/g"]
            assert target.compute_value(None) == float(channel["processing"]["gain_db"])
    [second] = [t for a, t in targets.items() if a == sorted(second_sockets(plan))[0]]
    assert "second socket" in second.description


def test_a_mono_source_states_its_gain_once():
    plan = demo_plan()
    gains = [t.address for t in _build_write_targets(plan, True)[0]
             if t.address.startswith("/io/in/") and t.address.endswith("/g")]
    sockets = [(c["patch"]["group"], s) for c in plan["channels"]
               if c.get("patch") and c["processing"].get("gain_db") is not None
               for s in c["patch"]["sockets"]]
    assert sorted(gains) == sorted(f"/io/in/{g}/{s}/g" for g, s in sockets)
    assert len(gains) == len(set(gains))


# ---- a preview after an apply proposes nothing -------------------------------


@pytest.mark.parametrize("desk_class", [SnapDesk, PairedSnapDesk])
def test_a_preview_straight_after_a_full_build_proposes_nothing(desk_class):
    plan, desk = demo_plan(), fresh_desk(desk_class)
    first = full_apply(plan, desk, dry_run=False)
    assert not first.mismatches
    assert would_change(full_apply(plan, desk, dry_run=True)) == set()


@pytest.mark.parametrize("desk_class", [SnapDesk, PairedSnapDesk])
def test_apply_edit_apply_then_a_preview_proposes_nothing(desk_class):
    """The sequence on the Compact: apply the Demo, add a Hi Hat, rebuild,
    apply again, preview a third time."""
    desk = fresh_desk(desk_class)
    full_apply(demo_plan(), desk, dry_run=False)
    rebuilt = with_hi_hat(demo_plan())

    preview = full_apply(rebuilt, desk, dry_run=True)
    expected = would_change(preview)
    assert expected, "the new row has something to write"
    assert not expected & second_sockets(rebuilt), "an applied pair's second socket is as planned"

    applied = full_apply(rebuilt, desk, dry_run=False)
    assert not applied.mismatches
    assert written(applied) == expected

    assert would_change(full_apply(rebuilt, desk, dry_run=True)) == set()


def test_the_second_sockets_end_at_the_planned_gain_on_a_desk_that_links_them():
    plan, desk = demo_plan(), fresh_desk(PairedSnapDesk)
    full_apply(plan, desk, dry_run=False)
    full_apply(with_hi_hat(plan), desk, dry_run=False)
    assert second_sockets(plan)
    for address in second_sockets(plan):
        assert desk.values[address] == 20.0, address


def test_an_address_the_reset_and_the_plan_both_touch_is_the_plans_alone():
    """The preview shows the second socket once, as the plan's own write --
    never as a reset to initialized -- and the reset leaves it be."""
    plan, desk = demo_plan(), fresh_desk(PairedSnapDesk)
    preview = full_apply(plan, desk, dry_run=True)
    for address in second_sockets(plan):
        rows = [w for w in preview.writes if w.address == address]
        assert len(rows) == 1
        assert not rows[0].description.startswith(init.DESCRIPTION)
        assert "second socket" in rows[0].description
