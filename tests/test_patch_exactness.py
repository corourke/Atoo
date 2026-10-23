"""Preview and Undo are exact (Forge's desk check).

1. **The count.** "Make Gtr 2 stereo" previewed 5 and wrote 4: a stereo pair's
   `/io/in/{group}/{n}/mode` is MIRRORED by the desk -- writing the first
   socket sets both -- so the second was already held when the real run read
   it, and skipped. The preview counts the pair once.
2. **Undo across a selector.** A strip move that puts a different gate model
   on a strip (PSE -> GATE) loses the old model's own values (PSE's depth and
   fast) when the model changes; Undo put the model back and the values came
   back as the model's defaults. The values under the OLD model are read and
   journalled before the selector is written, so Undo restores the model and
   then them.

The fake desk models both, as the real one does.
"""

from __future__ import annotations

import copy
import re

import pytest

from atoo import cli, patch
from atoo.ai_provider import FakeProvider
from test_amend import DeskConsole, applied_plan, horn, occupancy_state
from test_apply import PairModeMirror
from test_amend_plan_json import _seed
from test_patch import _bundle, _patch, _reply

MODELS = ["wing-compact", "wing-full", "wing-rack"]


class MirroringDesk(PairModeMirror, DeskConsole):
    """A desk that, like the real one, sets both sockets of a stereo pair
    when either one's `mode` is written."""


def _plan(model: str) -> dict:
    plan = applied_plan()
    plan["meta"]["console_model"] = model
    plan["channels"].append(horn(30, "Extra", 21))      # mono on A 21; A 22 is free
    return plan


def _counts(capsys) -> tuple[int, int]:
    previewed = int(re.search(r"(\d+) would change", capsys.readouterr().out).group(1))
    return previewed, 0


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("stereo", [True, False])
def test_the_preview_counts_a_stereo_pairs_mode_once(model, stereo, tmp_path, monkeypatch, capsys):
    plan = _plan(model)
    if not stereo:                 # start from a stereo channel: Extra on A 21+22
        extra = next(c for c in plan["channels"] if c["name"] == "Extra")
        extra["source"]["stereo"] = True
        extra["patch"]["sockets"] = [21, 22]
    state = _seed(plan)
    for socket in (21, 22):        # the pair's mode as the plan built it
        state[f"/io/in/A/{socket}/mode"] = ("ST" if not stereo else "M", "s")
    console = MirroringDesk(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    change_set = patch.empty_change_set("stereo")
    change_set["modify"] = [{"object": "channel", "name": "Extra", "change": "x",
                             "fields": {"source.stereo": stereo}}]
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(patch.validate_change_set(change_set))))
    show = _bundle(tmp_path, plan=plan)
    text = f"Make Extra {'stereo' if stereo else 'mono'}."
    assert _patch(show, text=text) == 0
    previewed = int(re.search(r"(\d+) would change", capsys.readouterr().out).group(1))
    assert _patch(show, text=text, confirm=True) == 0
    written = int(re.search(r"(\d+) written", capsys.readouterr().out).group(1))
    assert previewed == written > 0
    wanted = "ST" if stereo else "M"
    assert console.state["/io/in/A/21/mode"][0] == console.state["/io/in/A/22/mode"][0] == wanted


# ----------------------------------------------------------------------
# Undo across a model selector
# ----------------------------------------------------------------------

from atoo.apply import ORPHANED_STATUS, apply_plan  # noqa: E402
from atoo.console import OscReply  # noqa: E402
from atoo.undo import undo_from_journal  # noqa: E402
from test_apply import FakeConsole, compiled  # noqa: E402

#: What each gate model holds of its own, and the default each takes when the
#: desk switches to it. The real desk drops the leaves of the model it leaves
#: and shows the new model's at defaults.
_MODEL_LEAVES = {"PSE": {"depth": (12.0, "f"), "fast": (0, "i")}, "GATE": {}}


class GateDesk(FakeConsole):
    """A desk that, like the real one, resets a model selector's leaves when
    the selector changes: the old model's own values are gone (they read
    NODE NOT FOUND), the new model's start at their defaults."""

    def _leaf_ok(self, address: str) -> bool:
        match = re.match(r"^(/ch/\d+/gate)/(depth|fast)$", address)
        return not match or match.group(2) in _MODEL_LEAVES[self.state[match.group(1) + "/mdl"][0]]

    def _reply_to(self, address):
        if not self._leaf_ok(address):
            return OscReply(address=address, typetag="s", args=["NODE NOT FOUND"])
        return super()._reply_to(address)

    def node_dump(self, node):
        prefix = node + "/"
        items = [f"{a[len(prefix):]}={v}" for a, (v, _t) in self.state.items()
                 if a.startswith(prefix) and "/" not in a[len(prefix):] and self._leaf_ok(a)]
        return ",".join(items) or None

    def _switch(self, address, before, after):
        if before == after or not address.endswith("/gate/mdl"):
            return
        strip = address.rpartition("/")[0]
        for leaf in ("depth", "fast"):
            self.state.pop(f"{strip}/{leaf}", None)
        for leaf, value in _MODEL_LEAVES[after].items():
            self.state[f"{strip}/{leaf}"] = value

    def set_param(self, address, value, value_type="f"):
        before = self.state.get(address, (None, None))[0]
        super().set_param(address, value, value_type)
        self._switch(address, before, value)

    def set_node(self, address, command):
        key, _, text = command.partition("=")
        before = self.state.get(f"{address}/{key}", (None, None))[0]
        reply = super().set_node(address, command)
        self._switch(f"{address}/{key}", before, text)
        return reply


def _gate_plan(model: str) -> dict:
    plan = compiled("smallband")
    plan.setdefault("meta", {})["console_model"] = model
    channel = plan["channels"][0]
    channel["processing"] = {"preset": "Gate", "preset_values": {
        "preset": "Gate", "file": "gate.chn", "library": "/tmp", "sha256": "0",
        "leaves": {"gate/mdl": "GATE", "gate/thr": -36.0, "gate/on": True}, "overridden": {}}}
    return plan


@pytest.mark.parametrize("model", MODELS)
def test_undo_puts_back_the_old_models_own_values_after_a_model_change(model, tmp_path):
    """The strip held a PSE gate with depth 16 and fast 1 (the plan's own, not
    the model's defaults 12 / 0). The move puts a GATE-model strip there; the
    desk drops PSE's leaves. Undo restores the model and then them."""
    state = {
        "/ch/1/gate/mdl": ("PSE", "s"), "/ch/1/gate/thr": (-40.0, "f"),
        "/ch/1/gate/on": (0, "i"), "/ch/1/gate/depth": (16.0, "f"), "/ch/1/gate/fast": (1, "i"),
    }
    desk = GateDesk(state)
    before = copy.deepcopy(desk.state)
    journal_path = str(tmp_path / "apply.json")
    result = apply_plan(_gate_plan(model), desk, dry_run=False, journal_path=journal_path,
                        target_filter=lambda t: t.address.startswith("/ch/1/gate/"))
    assert not result.aborted and not result.mismatches
    # The old model's values were journalled before the selector was written ...
    orphaned = {w.address: w.prior_value for w in result.writes if w.status == ORPHANED_STATUS}
    assert orphaned == {"/ch/1/gate/depth": 16.0, "/ch/1/gate/fast": 1}
    # ... and the desk really lost them.
    assert "/ch/1/gate/depth" not in desk.state

    import json
    undone = undo_from_journal(json.loads(open(journal_path).read()), desk, dry_run=False)
    assert not undone.aborted
    assert desk.state == before


def test_without_the_journalled_values_the_desk_comes_back_at_the_models_defaults():
    """The failure Forge saw, pinned: restore the model alone and the desk
    reads PSE's defaults (12 / 0), not the plan's 16 / 1."""
    desk = GateDesk({"/ch/1/gate/mdl": ("GATE", "s")})
    desk.set_param("/ch/1/gate/mdl", "PSE", "s")
    assert desk.state["/ch/1/gate/depth"] == (12.0, "f")
    assert desk.state["/ch/1/gate/fast"] == (0, "i")


# ----------------------------------------------------------------------
# Whole-plan Undo: every address back, not only the ones the change named
# ----------------------------------------------------------------------
#
# Apply a change on a fake desk seeded with the whole show's address set,
# Undo it, and compare EVERY address with its value before the change (the
# coordinator's rule): an insert across a gate-model change, the
# preset switch on a running channel, and the stereo toggle.

from test_patch_insert import INSERT, _change, _hihat  # noqa: E402
from test_patch_preset_values import preset_plan  # noqa: E402

#: The leaves each gate model has to itself (the fixture presets: Kick In is a
#: GATE gate, Vocal a PSE one). Switching the model drops the old model's and
#: shows the new model's at defaults, as the real desk does.
_GATE_ONLY = {
    "GATE": {"acc": (3.0, "f"), "att": (2.0, "f"), "hld": (50.0, "f"), "range": (40.0, "f"),
             "ratio": ("3.0", "s"), "rel": (200.0, "f")},
    "PSE": {"depth": (12.0, "f"), "fast": (0, "i"), "peak": (0, "i")},
}


class ModelDesk(PairModeMirror, DeskConsole):
    """A fake desk with the two behaviours a whole-plan Undo has to survive: it
    mirrors a stereo pair's mode, and it resets a gate model's own leaves when
    the model changes (the old model's are gone, the new model's start at
    their defaults)."""

    def _gone(self, address: str) -> bool:
        match = re.match(r"^(/ch/\d+/gate)/(\w+)$", address)
        if not match:
            return False
        model = self.state.get(match.group(1) + "/mdl", ("GATE",))[0]
        other = "PSE" if model == "GATE" else "GATE"
        return match.group(2) in _GATE_ONLY[other] and match.group(2) not in _GATE_ONLY[model]

    def _reply_to(self, address):
        if self._gone(address):
            return OscReply(address=address, typetag="s", args=["NODE NOT FOUND"])
        return super()._reply_to(address)

    def node_dump(self, node):
        prefix = node + "/"
        items = [f"{a[len(prefix):]}={v}" for a, (v, _t) in self.state.items()
                 if a.startswith(prefix) and "/" not in a[len(prefix):] and not self._gone(a)]
        return ",".join(items) or None

    def _switch(self, address, before, after):
        if before == after or not address.endswith("/gate/mdl") or after not in _GATE_ONLY:
            return
        strip = address.rpartition("/")[0]
        for model, leaves in _GATE_ONLY.items():
            if model != after:
                for leaf in leaves:
                    self.state.pop(f"{strip}/{leaf}", None)
        for leaf, value in _GATE_ONLY[after].items():
            self.state.setdefault(f"{strip}/{leaf}", value)

    def set_param(self, address, value, value_type="f"):
        before = self.state.get(address, (None, None))[0]
        super().set_param(address, value, value_type)
        self._switch(address, before, value)

    def set_node(self, address, command):
        key, _, text = command.partition("=")
        before = self.state.get(f"{address}/{key}", (None, None))[0]
        reply = super().set_node(address, command)
        self._switch(f"{address}/{key}", before, text)
        return reply


def _seed_free(plan: dict) -> dict:
    """`_seed`, with nobody else's strip on the desk: an insert that moves the
    last strips down needs ch 20 to be free."""
    state = _seed(plan)
    state.pop("/io/in/LCL/20/name", None)
    for address, value in occupancy_state(theirs=(), plan=plan).values.items():
        state[address] = (value, "i" if isinstance(value, int) else "s")
    return state


def _put_gate_model(state: dict, strip: str, model: str, **values) -> None:
    """The desk's `strip` holds gate model `model`, with that model's own leaves
    at `values` (else at the defaults)."""
    state[f"/ch/{strip}/gate/mdl"] = (model, "s")
    for leaf, common in {"mix": (100.0, "f"), "thr": (-40.0, "f"), "gain": (0.0, "f"),
                         "on": (0, "i")}.items():       # every model has these
        state.setdefault(f"/ch/{strip}/gate/{leaf}", common)
    other = "PSE" if model == "GATE" else "GATE"
    for leaf in _GATE_ONLY[other]:
        state.pop(f"/ch/{strip}/gate/{leaf}", None)
    for leaf, default in _GATE_ONLY[model].items():
        state[f"/ch/{strip}/gate/{leaf}"] = (values.get(leaf, default[0]), default[1])


def _whole_plan_undo(tmp_path, monkeypatch, capsys, plan, state, change_set, text):
    console = ModelDesk(state)
    console.close = lambda: None
    monkeypatch.setattr(cli, "_open_console", lambda args: console)
    monkeypatch.setattr(cli, "provider_from_env",
                        lambda: FakeProvider(response=_reply(patch.validate_change_set(change_set))))
    show = _bundle(tmp_path, plan=plan)
    before = copy.deepcopy(console.state)
    assert _patch(show, text=text, confirm=True) == 0, capsys.readouterr()
    capsys.readouterr()
    assert console.state != before
    code = cli.main(["undo", "--show", str(show), "--console", "198.51.100.9", "--confirm"])
    undo_out = capsys.readouterr()
    assert code == 0, undo_out
    console.undo_output = undo_out.out + undo_out.err
    differing = {a: (before.get(a), console.state.get(a))
                 for a in set(before) | set(console.state) if console.state.get(a) != before.get(a)}
    assert differing == {}, differing
    return console


@pytest.mark.parametrize("model", MODELS)
def test_whole_plan_undo_of_an_insert_across_a_gate_model_change(
        model, tmp_path, monkeypatch, capsys):
    plan = preset_plan()
    plan["meta"]["console_model"] = model
    state = _seed_free(plan)
    # ch 3 (where HiHat is inserted) holds a PSE gate with the show's own depth and fast
    _put_gate_model(state, "3", "PSE", depth=16.0, fast=1)
    hihat = _hihat()
    hihat["processing"] = {"hpf_hz": None, "preset": "HiHat", "hi_cut_hz": None, "tilt_db": None,
                           "trim_db": None, "balance_db": None, "invert": None, "gain_db": None}
    console = _whole_plan_undo(tmp_path, monkeypatch, capsys, plan, state,
                               _change(hihat), INSERT)
    assert console.state["/ch/3/gate/depth"] == (16.0, "f")
    assert console.state["/ch/3/gate/fast"] == (1, "i")


@pytest.mark.parametrize("model", MODELS)
def test_whole_plan_undo_of_a_preset_switch_on_a_running_channel(
        model, tmp_path, monkeypatch, capsys):
    plan = preset_plan()
    plan["meta"]["console_model"] = model
    state = _seed_free(plan)
    _put_gate_model(state, "1", "GATE", acc=7.0, hld=33.0)     # the Kick's own gate values
    change_set = patch.empty_change_set("Vocal preset")
    change_set["modify"] = [{"object": "channel", "name": "Kick", "change": "Vocal preset",
                             "fields": {"processing.preset": "Vocal"}}]
    console = _whole_plan_undo(tmp_path, monkeypatch, capsys, plan, state, change_set,
                               "Use the Vocal preset on the Kick.")
    assert console.state["/ch/1/gate/acc"] == (7.0, "f")
    assert console.state["/ch/1/gate/hld"] == (33.0, "f")
    # The PSE model's own leaves (depth, fast, peak) the run set are gone with
    # it, and Undo says so rather than that they "stay as the run left them".
    assert "existed only under the model the run set and are gone with it" in console.undo_output
    assert "/ch/1/gate/depth" in console.undo_output
    assert "stay as the run left them" not in console.undo_output


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("stereo", [True, False])
def test_whole_plan_undo_of_the_stereo_toggle(model, stereo, tmp_path, monkeypatch, capsys):
    plan = _plan(model)
    if not stereo:
        extra = next(c for c in plan["channels"] if c["name"] == "Extra")
        extra["source"]["stereo"] = True
        extra["patch"]["sockets"] = [21, 22]
    state = _seed(plan)
    for socket in (21, 22):
        state[f"/io/in/A/{socket}/mode"] = ("ST" if not stereo else "M", "s")
    change_set = patch.empty_change_set("stereo")
    change_set["modify"] = [{"object": "channel", "name": "Extra", "change": "x",
                             "fields": {"source.stereo": stereo}}]
    _whole_plan_undo(tmp_path, monkeypatch, capsys, plan, state, change_set,
                     f"Make Extra {'stereo' if stereo else 'mono'}.")
