"""An explicit drop of a channel wins over "the desk no longer reads this
strip as the one the plan built".

Decision recorded on the issue (coordinator, from the "An explicit
instruction is carried out" rule): the engineer's typed "lose the Kick" is done even
where somebody has renamed or repatched the strip since; the review says what
the strip holds now and that it is not what the plan built, at WARNING; Undo
puts it back. A rebuild (`amend`) that merely leaves a channel out is still
held back by the guard -- it never named one.
"""

from __future__ import annotations

import dataclasses

import pytest

from atoo import amend, patch
from atoo.amend import ChangeKind, strip_occupancy
from test_amend import amended_plan, applied_plan, occupancy_state


def _occupancy(**changes):
    state = occupancy_state()
    values = dict(state.values) if hasattr(state, "values") else None
    values.update(changes)
    return strip_occupancy(dataclasses.replace(state, values=values), applied_plan())


def _drop_kick() -> dict:
    change_set = patch.empty_change_set("No kick")
    change_set["drop"]["channels"] = ["Kick"]
    return patch.validate_change_set(change_set)


@pytest.mark.parametrize("model", ["wing-compact", "wing-full", "wing-rack"])
@pytest.mark.parametrize("found", [
    {"/ch/1/name": "Dave's vox"},
    {"/ch/1/in/conn/grp": "A", "/ch/1/in/conn/in": 33},
])
def test_an_explicit_drop_is_carried_out_on_a_strip_somebody_changed(model, found):
    occupancy = _occupancy(**found)
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    amendment, merge = patch.plan_patch(plan, _drop_kick(), occupancy, console_model=model)
    assert not amendment.blocked
    [freed] = [c for c in amendment.changes
               if c.kind is ChangeKind.RELEASED and c.where == "'Kick'"]
    assert "does NOT read it as the strip this plan built" in freed.reason
    assert "still reads as the strip this plan built" not in freed.reason
    assert not [c for c in amendment.changes if c.kind is ChangeKind.REMOVED]
    [warning] = [w for w in amendment.warnings if "'Kick'" in w and "no longer reads" in w]
    assert warning.startswith("WARNING: ")
    assert "Undo puts it back" in warning
    targets = amend.amendment_targets(amendment)
    assert "/ch/1/name" in {t.address for t in targets.to_write}


def test_a_strip_that_is_still_ours_says_nothing_extra():
    amendment, _merge = patch.plan_patch(applied_plan(), _drop_kick(), _occupancy())
    assert [c for c in amendment.changes if c.kind is ChangeKind.RELEASED and c.where == "'Kick'"]
    assert not [w for w in amendment.warnings if "no longer reads" in w]


def test_a_rebuild_that_leaves_the_channel_out_is_still_held_back():
    """The guard stays for an amend: it never named the channel."""
    rebuilt = amended_plan()
    rebuilt["channels"] = [c for c in rebuilt["channels"] if c["name"] != "Kick"]
    amendment = amend.plan_amendment(applied_plan(), rebuilt,
                                     _occupancy(**{"/ch/1/name": "Dave's vox"}))
    assert [c for c in amendment.changes if c.kind is ChangeKind.REMOVED
            and c.where == "'Kick'"]


def test_a_dropped_channel_is_unmuted_once_so_the_preview_counts_what_the_write_makes():
    """Forge's check: the preview said 47 would change and 48 were
    written, because a freed strip's mute was ON then OFF, two writes to one
    address. The fader goes to -inf first and the mute is written once."""
    amendment, _merge = patch.plan_patch(applied_plan(), _drop_kick(), _occupancy())
    targets = amend.amendment_targets(amendment)
    addresses = [t.address for t in targets.to_write]
    assert len(addresses) == len(set(addresses)), "an address is written twice"
    assert addresses.count("/ch/1/mute") == 1 and addresses[0] == "/ch/1/fdr"
    mute = next(t for t in targets.to_write if t.address == "/ch/1/mute")
    assert mute.compute_value("") == 0 and targets.to_write[-1] is mute


def test_the_preview_counts_the_writes_the_confirm_makes_for_a_channel_drop(
        tmp_path, monkeypatch, capsys):
    import re

    from atoo import cli
    from atoo.ai_provider import FakeProvider
    from test_amend import DeskConsole
    from test_amend_plan_json import _seed
    from test_patch import _bundle, _patch, _reply

    console = DeskConsole(_seed(applied_plan()))
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env", lambda: FakeProvider(response=_reply(_drop_kick())))
    show = _bundle(tmp_path)
    assert _patch(show, text="Lose the Kick.") == 0
    previewed = int(re.search(r"(\d+) would change", capsys.readouterr().out).group(1))
    assert previewed > 0
    assert _patch(show, text="Lose the Kick.", confirm=True) == 0
    written = int(re.search(r"(\d+) written", capsys.readouterr().out).group(1))
    assert written == previewed
